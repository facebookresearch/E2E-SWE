"""End-to-end tests for the ``tuf`` (The Update Framework) implementation.

Each test is a single, realistic end-to-end workflow that exercises one
cohesive part of the library through its public API and asserts every contract
that workflow touches (failing as a unit if any contract is wrong). Tests drive
the client through ``tuf.ngclient.Updater`` against an in-memory
``RepositorySimulator`` (built on the public ``tuf.api.metadata`` API) and the
authoring side through ``tuf.repository.Repository``. Everything is served from
memory, so the tests are deterministic and need no network.
"""

from __future__ import annotations

import copy
import datetime
import os
from collections import defaultdict

import pytest
from repository_simulator import RepositorySimulator
from securesystemslib.signer import CryptoSigner

from tuf.api.exceptions import (
    BadVersionNumberError,
    ExpiredMetadataError,
    LengthOrHashMismatchError,
    UnsignedMetadataError,
)
from tuf.api.metadata import (
    TOP_LEVEL_ROLE_NAMES,
    DelegatedRole,
    Metadata,
    MetaFile,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)
from tuf.ngclient import Updater
from tuf.repository import AbortEdit, Repository

_PAST = datetime.datetime.now(datetime.timezone.utc).replace(
    microsecond=0
) - datetime.timedelta(days=5)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fresh(tmp_path, name):
    """A fresh repository simulator with its own client cache directories."""
    md = os.path.join(tmp_path, name, "metadata")
    tg = os.path.join(tmp_path, name, "targets")
    os.makedirs(md)
    os.makedirs(tg)
    return RepositorySimulator(), md, tg


def _updater(sim, md, tg, bootstrap_idx=0):
    return Updater(
        md,
        "https://example.com/metadata/",
        tg,
        "https://example.com/targets/",
        sim,
        bootstrap=sim.signed_roots[bootstrap_idx],
    )


def _cached_version(md, role):
    return Metadata.from_file(os.path.join(md, f"{role}.json")).signed.version


def _deleg(name, terminating=False, paths=("*",)):
    return DelegatedRole(name, [], 1, terminating, list(paths), None)


# --------------------------------------------------------------------------- #
# 1. Client secure-update lifecycle
# --------------------------------------------------------------------------- #


def test_client_secure_update_lifecycle(tmp_path):
    """A client securely bootstraps, refreshes all top-level metadata in order,
    downloads and verifies a target, recognizes the cached copy, reports an
    unknown target as missing, honors a per-call target_base_url override, and
    works under the non-consistent-snapshot repository layout."""
    # --- consistent-snapshot repository: refresh + cache + download + lookup
    sim, md, tg = _fresh(tmp_path, "lifecycle")
    sim.root.version += 1  # force a root rotation v1 -> v2 during refresh
    sim.publish_root()
    data = b"the quick brown fox"
    sim.add_target("targets", data, "file.txt")
    sim.targets.version += 1
    sim.update_snapshot()

    updater = _updater(sim, md, tg)
    updater.refresh()
    for role in TOP_LEVEL_ROLE_NAMES:
        assert os.path.isfile(os.path.join(md, f"{role}.json"))
    assert _cached_version(md, "root") == 2  # root rotation applied
    assert _cached_version(md, "targets") == 2  # target publish picked up

    info = updater.get_targetinfo("file.txt")
    assert info is not None and info.path == "file.txt" and info.length == len(data)
    path = updater.download_target(info)
    with open(path, "rb") as f:
        assert f.read() == data
    assert updater.find_cached_target(info) == path
    assert updater.get_targetinfo("does/not/exist") is None

    # A tampered cache file must no longer count as a valid cached target.
    with open(path, "wb") as f:
        f.write(b"tampered")
    assert updater.find_cached_target(info) is None

    # --- per-call target_base_url override
    sim2, md2, tg2 = _fresh(tmp_path, "override")
    sim2.add_target("targets", b"ov", "ov.bin")
    sim2.targets.version += 1
    sim2.update_snapshot()
    up2 = _updater(sim2, md2, tg2)
    i2 = up2.get_targetinfo("ov.bin")
    assert i2 is not None
    p2 = up2.download_target(i2, target_base_url="https://example.com/targets/")
    with open(p2, "rb") as f:
        assert f.read() == b"ov"

    # --- non-consistent-snapshot layout (unversioned metadata, plain targets)
    sim3, md3, tg3 = _fresh(tmp_path, "plain")
    sim3.root.consistent_snapshot = False
    sim3.root.version += 1
    sim3.publish_root()
    sim3.add_target("targets", b"plain", "plain.bin")
    sim3.targets.version += 1
    sim3.update_snapshot()
    up3 = _updater(sim3, md3, tg3, bootstrap_idx=-1)
    up3.refresh()
    i3 = up3.get_targetinfo("plain.bin")
    assert i3 is not None
    p3 = up3.download_target(i3)
    with open(p3, "rb") as f:
        assert f.read() == b"plain"


# --------------------------------------------------------------------------- #
# 2. Client rejects rollback and freeze attacks
# --------------------------------------------------------------------------- #


def test_client_rejects_rollback_and_freeze_attacks(tmp_path):
    """The client rejects every malicious repository state in the TUF threat
    model: timestamp rollback, snapshot rollback, a non-consecutive root
    version, an expired timestamp (freeze), and a snapshot whose content does
    not match the hash pinned by timestamp."""
    # timestamp version rollback
    sim, md, tg = _fresh(tmp_path, "ts_roll")
    sim.timestamp.version = 2
    _updater(sim, md, tg).refresh()
    sim.timestamp.version = 1
    with pytest.raises(BadVersionNumberError):
        _updater(sim, md, tg).refresh()
    assert _cached_version(md, "timestamp") == 2

    # snapshot version rollback (detected during timestamp update)
    sim, md, tg = _fresh(tmp_path, "snap_roll")
    sim.snapshot.version = 2
    sim.update_timestamp()
    _updater(sim, md, tg).refresh()
    sim.timestamp.snapshot_meta.version = 1
    sim.timestamp.version += 1
    with pytest.raises(BadVersionNumberError):
        _updater(sim, md, tg).refresh()
    assert _cached_version(md, "timestamp") == 2

    # non-consecutive root version
    sim, md, tg = _fresh(tmp_path, "root_jump")
    sim.root.version += 2
    sim.publish_root()
    with pytest.raises(BadVersionNumberError):
        _updater(sim, md, tg).refresh()
    assert _cached_version(md, "root") == 1

    # expired timestamp (freeze attack)
    sim, md, tg = _fresh(tmp_path, "ts_exp")
    sim.timestamp.expires = _PAST
    sim.update_timestamp()
    with pytest.raises(ExpiredMetadataError):
        _updater(sim, md, tg).refresh()

    # snapshot hash mismatch vs timestamp's pinned hash
    sim, md, tg = _fresh(tmp_path, "snap_hash")
    sim.compute_metafile_hashes_length = True
    sim.update_timestamp()
    _updater(sim, md, tg).refresh()
    sim.snapshot.expires += datetime.timedelta(days=1)
    sim.snapshot.version += 1
    sim.timestamp.snapshot_meta.version = sim.snapshot.version
    sim.timestamp.version += 1
    with pytest.raises(LengthOrHashMismatchError):
        _updater(sim, md, tg).refresh()
    assert _cached_version(md, "snapshot") == 1


# --------------------------------------------------------------------------- #
# 3. Signature thresholds and key rotation
# --------------------------------------------------------------------------- #


def test_client_signature_threshold_and_key_rotation(tmp_path):
    """The client enforces signature thresholds and supports secure key
    rotation: an unsigned role is rejected; a k-of-n role needs k valid
    signatures; and rotating a role's keys via a new root version enables
    fast-forward recovery (a lower version signed by the new keys is accepted)."""
    # unsigned timestamp
    sim, md, tg = _fresh(tmp_path, "unsigned")
    sim.signers["timestamp"].clear()
    with pytest.raises(UnsignedMetadataError):
        _updater(sim, md, tg).refresh()

    # k-of-n threshold: threshold 2, one signature rejected, two accepted
    sim, md, tg = _fresh(tmp_path, "threshold")
    extra = CryptoSigner.generate_ed25519()
    sim.root.add_key(extra.public_key, "timestamp")
    sim.root.roles["timestamp"].threshold = 2
    sim.root.version += 1
    sim.publish_root()
    with pytest.raises(UnsignedMetadataError):
        _updater(sim, md, tg).refresh()
    sim.add_signer("timestamp", extra)
    _updater(sim, md, tg).refresh()
    assert _cached_version(md, "timestamp") == 1

    # fast-forward recovery via root key rotation
    sim, md, tg = _fresh(tmp_path, "rotate")
    sim.timestamp.version = 99999
    _updater(sim, md, tg).refresh()
    assert _cached_version(md, "timestamp") == 99999
    sim.rotate_keys("timestamp")
    sim.root.version += 1
    sim.publish_root()
    sim.timestamp.version = 1
    _updater(sim, md, tg).refresh()
    assert _cached_version(md, "timestamp") == 1


# --------------------------------------------------------------------------- #
# 4. Delegation graph traversal and delegated-role freeze
# --------------------------------------------------------------------------- #


def test_delegation_graph_resolution_and_freeze(tmp_path):
    """Target lookup walks the delegation graph correctly: it resolves a target
    several hops deep, honors terminating delegations (which block later
    siblings), and rejects an expired delegated role (freeze attack on a
    delegation)."""
    # multi-level resolution: targets -> A -> C
    sim, md, tg = _fresh(tmp_path, "multilevel")
    sim.add_delegation("targets", _deleg("A"), Targets(expires=sim.safe_expiry))
    sim.add_delegation("A", _deleg("C"), Targets(expires=sim.safe_expiry))
    data = b"deeply delegated"
    sim.add_target("C", data, "deep.bin")
    sim.targets.version += 1
    sim.update_snapshot()
    up = _updater(sim, md, tg)
    info = up.get_targetinfo("deep.bin")
    assert info is not None and info.length == len(data)
    assert up.download_target(info)

    # terminating delegation blocks a later sibling that holds the target
    sim, md, tg = _fresh(tmp_path, "terminating")
    sim.add_delegation(
        "targets", _deleg("A", terminating=True), Targets(expires=sim.safe_expiry)
    )
    sim.add_delegation("targets", _deleg("B"), Targets(expires=sim.safe_expiry))
    sim.add_target("B", b"unreachable", "blocked.bin")
    sim.targets.version += 1
    sim.update_snapshot()
    assert _updater(sim, md, tg).get_targetinfo("blocked.bin") is None

    # expired delegated role is rejected during lookup
    sim, md, tg = _fresh(tmp_path, "deleg_exp")
    sim.add_delegation(
        "targets", _deleg("d", terminating=True), Targets(expires=_PAST)
    )
    sim.add_target("d", b"x", "d.bin")
    sim.targets.version += 1
    sim.update_snapshot()
    with pytest.raises(ExpiredMetadataError):
        _updater(sim, md, tg).get_targetinfo("d.bin")


# --------------------------------------------------------------------------- #
# 5. Succinct (hash-bin) delegation
# --------------------------------------------------------------------------- #


def test_succinct_hashbin_delegation(tmp_path):
    """A target routed through succinct (hash-bin) delegation is found in its
    computed bin: the bin namespace has the correct size and naming, the bin is
    selected by the hash of the target path, and its metadata (verified with the
    succinct role's shared keys) yields the target."""
    sim, md, tg = _fresh(tmp_path, "succinct")
    sim.add_succinct_roles("targets", 5, "bin")  # 2**5 = 32 bins
    succinct = sim.targets.delegations.succinct_roles
    assert succinct is not None

    bins = list(succinct.get_roles())
    assert len(bins) == 32
    assert bins[0] == "bin-00" and bins[-1] == "bin-1f"

    data = b"binned payload"
    target_bin = succinct.get_role_for_target("packages/app.bin")
    assert target_bin in bins
    sim.add_target(target_bin, data, "packages/app.bin")
    sim.targets.version += 1
    sim.update_snapshot()

    info = _updater(sim, md, tg).get_targetinfo("packages/app.bin")
    assert info is not None and info.length == len(data)


# --------------------------------------------------------------------------- #
# 6. Repository authoring workflow
# --------------------------------------------------------------------------- #

_SIGNED_INIT = {
    "root": Root,
    "snapshot": Snapshot,
    "targets": Targets,
    "timestamp": Timestamp,
}


class _InMemoryRepository(Repository):
    """Minimal in-memory Repository implementation for the authoring workflow."""

    expiry_period = datetime.timedelta(days=1)

    def __init__(self) -> None:
        self.role_cache: dict[str, list[Metadata]] = defaultdict(list)
        self.signer_cache: dict[str, list] = defaultdict(list)
        self._snapshot_info = MetaFile(1)
        self._targets_infos: dict[str, MetaFile] = defaultdict(lambda: MetaFile(1))

        with self.edit_root() as root:
            for role in ["root", "timestamp", "snapshot", "targets"]:
                signer = CryptoSigner.generate_ed25519()
                self.signer_cache[role].append(signer)
                root.add_key(signer.public_key, role)
        for role in ["timestamp", "snapshot", "targets"]:
            with self.edit(role):
                pass

    @property
    def targets_infos(self):
        return self._targets_infos

    @property
    def snapshot_info(self):
        return self._snapshot_info

    def open(self, role):
        if role not in self.role_cache:
            md = Metadata(_SIGNED_INIT.get(role, Targets)())
            md.signed.version = 0
            return md
        return copy.deepcopy(self.role_cache[role][-1])

    def close(self, role, md):
        md.signed.version += 1
        md.signed.expires = (
            datetime.datetime.now(datetime.timezone.utc) + self.expiry_period
        )
        md.signatures.clear()
        for signer in self.signer_cache[role]:
            md.sign(signer, append=True)
        self.role_cache[role].append(md)
        if role == "snapshot":
            self._snapshot_info.version = md.signed.version
        elif role not in ["root", "timestamp"]:
            self._targets_infos[f"{role}.json"].version = md.signed.version


def test_repository_authoring_workflow():
    """Building a repository from scratch behaves correctly: a fresh repo has
    all roles at v1 with typed readers; do_snapshot/do_timestamp are no-ops when
    nothing changed but advance and propagate versions after a targets change;
    rotating the snapshot key forces a re-sign; and AbortEdit cancels an edit."""
    repo = _InMemoryRepository()

    # initial state
    assert set(repo.role_cache) == TOP_LEVEL_ROLE_NAMES
    for role in TOP_LEVEL_ROLE_NAMES:
        assert repo.role_cache[role][-1].signed.version == 1
    assert isinstance(repo.root(), Root)
    assert isinstance(repo.snapshot(), Snapshot)

    # no-op snapshot/timestamp when nothing changed
    assert repo.do_snapshot()[0] is False
    assert repo.do_timestamp()[0] is False

    # targets change propagates through snapshot then timestamp
    with repo.edit_targets() as targets:
        targets.targets["app.bin"] = TargetFile.from_data("app.bin", b"data")
    assert repo.do_snapshot()[0] is True
    assert repo.snapshot().version == 2
    assert repo.snapshot().meta["targets.json"].version == 2
    assert repo.do_timestamp()[0] is True
    assert repo.timestamp().snapshot_meta.version == 2

    # rotating the snapshot key invalidates the signature -> re-sign
    with repo.edit_root() as root:
        root.revoke_key(root.roles["snapshot"].keyids[0], "snapshot")
        repo.signer_cache["snapshot"].clear()
        new_signer = CryptoSigner.generate_ed25519()
        repo.signer_cache["snapshot"].append(new_signer)
        root.add_key(new_signer.public_key, "snapshot")
    assert repo.do_snapshot()[0] is True

    # AbortEdit cancels the edit (no new version stored)
    before = len(repo.role_cache["targets"])
    with repo.edit_targets() as targets:
        targets.targets["x"] = TargetFile.from_data("x", b"d")
        raise AbortEdit
    assert len(repo.role_cache["targets"]) == before
