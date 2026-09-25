# tuf — A Python implementation of The Update Framework (TUF)

Build `tuf`, a Python package that implements **The Update Framework**: a
framework for securing software update systems. It provides (1) a low-level
**Metadata API** for creating, signing, serializing and verifying TUF metadata,
(2) a high-level **client (`ngclient`)** that securely downloads target files by
following the TUF detailed client workflow, and (3) a **repository-authoring**
helper for producing and maintaining repository metadata.

The security guarantee is that a client can detect tampering — including
rollback, freeze, arbitrary-software and key-compromise attacks — **even when
the repository or transport is compromised**, as long as enough signing keys
remain uncompromised.

## Dependencies

The environment is **offline** and every dependency is **already installed** — do
**not** install anything (there is no network). The project itself is installed
for you by a `setup.sh` that runs offline (an editable install of the code you
write). You only need to write the package source so that `import tuf` works.

The runtime libraries available in the environment are:

- Python 3.10+.
- `securesystemslib` (`~=1.0`), installed with its cryptography backend
  (`securesystemslib[crypto]`) — provides the cryptographic key, signer and
  signature primitives used by this library (see *Cryptographic primitives*).
  The backend is required for key generation and signature verification.
- `urllib3` (`>=1.21.1,<3`) — HTTP library used by the default fetcher.

The package must be importable as `import tuf`, exposing the modules and import
paths described below.

## Cryptographic primitives (from `securesystemslib`)

This library does **not** implement cryptography itself. Keys, signers and
signatures are `securesystemslib.signer` types:

- `Signer` — an object with `.sign(payload: bytes) -> Signature` and a
  `.public_key` attribute (a `Key`). Tests create signers with
  `securesystemslib.signer.CryptoSigner.generate_ed25519()`.
- `Key` — a public key with a unique `.keyid: str` and a
  `.verify_signature(signature, data: bytes) -> None` method that raises
  `securesystemslib.exceptions.UnverifiedSignatureError` when verification
  fails.
- `Signature` — has a `.keyid: str`, plus `.from_dict`/`.to_dict`.

Your code consumes these types; it must store/lookup signatures by `keyid` and
verify them with the corresponding `Key`.

---

## Part 1 — Metadata API (`tuf.api`)

TUF metadata is JSON. There are four **roles**, each a separately-signed
metadata file:

- **root** — the root of trust. Lists the public keys and signature thresholds
  for all four roles (including itself). Establishes which keys sign what.
- **timestamp** — tiny, frequently re-signed file that records the current
  snapshot's version (and optionally its hash/length). Detects that the client
  is seeing the latest state (freeze-attack defense).
- **snapshot** — records the version number of targets metadata (and every
  delegated targets role). Guarantees the client sees a consistent set of
  metadata.
- **targets** — lists the available target files with their hashes and lengths,
  and may **delegate** trust over subsets of target paths to other targets
  roles.

### `tuf.api.metadata`

This module must export the following names.

**Constants**

- `SPECIFICATION_VERSION` — a 3-tuple of strings `("1", "0", "31")`; the
  string form is `".".join(SPECIFICATION_VERSION)`.
- `TOP_LEVEL_ROLE_NAMES` — the collection `{"root", "timestamp", "snapshot",
  "targets"}`.

**`Metadata`** — a generic container for one signed metadata file.

- Constructor: `Metadata(signed, signatures=None, unrecognized_fields=None)`.
  - `.signed` — the payload object (a `Root`, `Timestamp`, `Snapshot` or
    `Targets`).
  - `.signatures` — an **ordered dict** mapping `keyid -> Signature`. Default
    is an empty dict.
- `.signed_bytes -> bytes` — the **canonical** serialization of `.signed` used
  as the signing payload (see *Canonical serialization*).
- `.sign(signer, append=False) -> Signature` — sign `.signed` with `signer`
  and store the resulting `Signature` under its `keyid`. If `append` is
  `False`, existing signatures are cleared first; if `True`, the new signature
  is added alongside existing ones.
- Serialization: `.to_bytes(serializer=None) -> bytes`,
  `.from_bytes(data, deserializer=None) -> Metadata` (classmethod),
  `.to_file(filename, serializer=None)`,
  `.from_file(filename, deserializer=None) -> Metadata` (classmethod),
  `.to_dict()`, `.from_dict(d)` (classmethod). The default serializer is the
  JSON serializer (see below); a round trip through bytes/file/dict must
  preserve `.signed` and `.signatures` (and keep signatures valid).

**Signed payload classes.** Each has at least `.version: int` (default 1),
`.spec_version: str`, `.expires: datetime` (timezone-aware UTC), a `.type`
class attribute equal to the role name, and `from_dict`/`to_dict`.

- `Root(version=1, spec_version=..., expires=..., keys=None, roles=None,
  consistent_snapshot=True, unrecognized_fields=None)`
  - `.consistent_snapshot: bool` (default `True`).
  - `.keys` — dict `keyid -> Key`.
  - `.roles` — dict `role_name -> Role`, with one entry for **each** of the four
    top-level roles (`root`, `timestamp`, `snapshot`, `targets`). A newly
    constructed `Root()` (i.e. `roles=None`) **initializes all four entries** as
    `Role([], 1)` — empty `keyids`, threshold `1` — so a caller can build a root
    from scratch by then attaching keys with `add_key`. (Root therefore always
    carries a `"root"` role definition, used to verify root's own signatures.)
  - `.add_key(key, role)` — register `key` for an already-present `role`: add it
    to `.keys` and append its keyid to that role's `keyids`.
  - `.revoke_key(keyid, role)` — remove a key from `role` (and from `.keys` if
    no other role uses it).
- `Timestamp(...)`
  - `.snapshot_meta: MetaFile` — points at the current snapshot
    (version, and optionally length + hashes). Defaults to `MetaFile(1)` for a
    new timestamp.
- `Snapshot(...)`
  - `.meta` — dict `"<rolename>.json" -> MetaFile` for `targets` and every
    delegated targets role. Defaults to `{"targets.json": MetaFile(1)}` for a
    new snapshot.
- `Targets(version=1, spec_version=..., expires=..., targets=None,
  delegations=None, unrecognized_fields=None)`
  - `.targets` — dict `target_path -> TargetFile`.
  - `.delegations: Delegations | None`.
  - `.add_key(key, role=None)` — register a delegated role's key.

**Supporting types**

- `Role(keyids, threshold)` — `.keyids: list[str]`, `.threshold: int`.
- `Key` — re-export the `securesystemslib` public-key type so that
  `from tuf.api.metadata import Key` works.
- `MetaFile(version=1, length=None, hashes=None)` — `.version`, `.length`,
  `.hashes` (dict `algo -> hexdigest`); `.verify_length_and_hashes(data)`
  raises `LengthOrHashMismatchError` on mismatch.
- `TargetFile(length, hashes, path, unrecognized_fields=None)` —
  `.path`, `.length`, `.hashes`.
  - classmethod `TargetFile.from_data(target_path, data, hash_algorithms=None)
    -> TargetFile` — build a `TargetFile` by hashing `data` (bytes) with the
    named algorithms; defaults to `["sha256"]` when `hash_algorithms` is omitted.
  - `.verify_length_and_hashes(data)` — raises `LengthOrHashMismatchError` if
    `data` (bytes or a file object) does not match `.length`/`.hashes`.
- `DelegatedRole(name, keyids, threshold, terminating, paths=None,
  path_hash_prefixes=None)` — a delegation entry. `.name`. A target path is
  matched against `paths` (glob patterns, e.g. `"*"`) or `path_hash_prefixes`.
  `terminating=True` means: if this role is consulted for a target and does not
  provide it, the search stops (no backtracking to later delegations).
- `Delegations(keys, roles=None, succinct_roles=None)` — a targets role's
  delegations. `.roles` is an **ordered** dict `name -> DelegatedRole`.
  - `.get_roles_for_target(target_path) -> Iterator[tuple[str, bool]]` — yield
    `(role_name, terminating)` for each delegated role whose patterns match
    `target_path`, in delegation order.
- `SuccinctRoles(keyids, threshold, bit_length, name_prefix)` — a compact form
  of delegation (TAP-15) that maps every target to one of `2**bit_length` bins
  by hash. `bit_length` must be 1–32.
  - Bin names are `"<name_prefix>-<suffix>"`, where `<suffix>` is the bin index
    in lowercase hex, zero-padded to the width of the largest index
    (`2**bit_length - 1`). E.g. `bit_length=5` → 32 bins named `bin-00` …
    `bin-1f`.
  - `.get_roles() -> Iterator[str]` — yield all bin role names in index order.
  - `.get_role_for_target(target_path) -> str` — return the single bin
    responsible for `target_path` (one of the names yielded by `get_roles()`).
    The mapping from a target path to its bin is deterministic, so the same path
    always resolves to the same bin.
  - All succinct-roles bins are **terminating**. When a targets role uses
    succinct roles, `get_roles_for_target` yields exactly the one computed bin
    (with `terminating=True`).
  - The `keyids` and `threshold` given to `SuccinctRoles` are shared by **every**
    bin: each bin's metadata is verified by the delegating role using those same
    `keyids`/`threshold` (there is no per-bin key entry). The delegating targets
    role registers these shared keys with `add_key`, called with `role` omitted.

**Canonical serialization.** Signatures are computed over a *deterministic*
canonical byte encoding of the `signed` payload (stable key ordering, no
insignificant whitespace). Your implementation only needs to be internally
consistent: the bytes produced when signing must equal the bytes produced when
verifying, so that a signature created by `Metadata.sign` verifies later.

### `tuf.api.serialization` and `tuf.api.serialization.json`

- `tuf.api.serialization.json.JSONSerializer` — the default `Metadata`
  serializer (produces the JSON file format). Instantiable with no arguments
  and passed to `Metadata.to_bytes(...)`.
- `tuf.api.serialization.json.JSONDeserializer` — the default deserializer.
- A canonical-JSON serializer used for the signing payload.

### `tuf.api.exceptions`

Define this exception hierarchy (names are asserted by tests):

- `RepositoryError(Exception)` — base for repository-state errors.
  - `UnsignedMetadataError(RepositoryError)` — metadata lacks a sufficient
    threshold of valid signatures.
  - `BadVersionNumberError(RepositoryError)` — invalid/rolled-back version.
    - `EqualVersionNumberError(BadVersionNumberError)` — version equals the
      currently trusted one.
  - `ExpiredMetadataError(RepositoryError)` — metadata `expires` is in the past.
  - `LengthOrHashMismatchError(RepositoryError)` — length/hash check failed.
- `DownloadError(Exception)` — base for download errors.
  - `DownloadLengthMismatchError(DownloadError)`
  - `SlowRetrievalError(DownloadError)`
  - `DownloadHTTPError(DownloadError)` — constructed as
    `DownloadHTTPError(message, status_code)` with a `.status_code: int`
    attribute; raised by fetchers for HTTP errors (e.g. 404).

---

## Part 2 — Client (`tuf.ngclient`)

`tuf.ngclient` must export `Updater`, `UpdaterConfig`, `FetcherInterface`,
`Urllib3Fetcher` and `TargetFile`.

### `tuf.ngclient.fetcher.FetcherInterface`

An abstract base class for downloading bytes over the network.

- Subclasses implement `_fetch(self, url: str) -> Iterator[bytes]` (yielding
  chunks). On HTTP error a `_fetch` implementation raises `DownloadHTTPError`.
- The base class provides:
  - `download_bytes(url, max_length) -> bytes` — download up to `max_length`
    bytes (raising a `DownloadError` subclass if the content is longer).
  - `download_file(url, max_length)` — a context manager yielding a temporary
    file object containing the downloaded data.

(Tests supply a custom `FetcherInterface` subclass that serves signed metadata
and targets from memory, so your `Updater` must accept any fetcher and route
all network access through it.)

### `tuf.ngclient.config`

- `UpdaterConfig` — a dataclass of tunables with these fields and defaults:
  `max_root_rotations=256`, `max_delegations=32`, `root_max_length=512000`,
  `timestamp_max_length=16384`, `snapshot_max_length=2000000`,
  `targets_max_length=5000000`, `prefix_targets_with_hash=True`,
  `envelope_type=EnvelopeType.METADATA`, `app_user_agent=None`.
- `EnvelopeType` — a `Flag` enum with members `METADATA = 1` and `SIMPLE = 2`.

### `tuf.ngclient.Updater`

```
Updater(metadata_dir, metadata_base_url, target_dir=None,
        target_base_url=None, fetcher=None, config=None, *, bootstrap)
```

- `metadata_dir` — local directory used to cache trusted metadata.
- `metadata_base_url` / `target_base_url` — remote base URLs.
- `fetcher` — a `FetcherInterface`; defaults to `Urllib3Fetcher`.
- `bootstrap` — **keyword-only, required**. The trusted initial root metadata
  as bytes (pass the embedded root). If `None`, the cached `root.json` in
  `metadata_dir` is used as the trust anchor instead (and if absent, an
  `OSError` is raised).

On construction the Updater loads and validates the bootstrap/initial root and
persists it to the local cache under `metadata_dir`, keeping a `root.json` there
that reflects the current trusted root version (the exact on-disk storage scheme
is an implementation choice).

**`refresh()`** — perform the TUF detailed client workflow, loading and
verifying the top-level metadata strictly in the order **root → timestamp →
snapshot → targets**, then caching each as `<role>.json` in `metadata_dir`.
`refresh()` may be called only once per Updater. The following checks are
mandatory (each is exercised by the tests):

1. **Root update.** Repeatedly try to fetch the next root version
   (current + 1, current + 2, …), from local cache then remote, stopping when
   the remote returns 404/403 or after `max_root_rotations`. Each new root:
   - must be a strictly **consecutive** version (current + 1); a repeated or
     non-consecutive version is a `BadVersionNumberError`;
   - must be signed by a threshold of keys from **both** the previous root and
     the new root (`UnsignedMetadataError` otherwise) — this is what makes key
     rotation secure;
   - intermediate roots' expiry does not matter, but the **final** trusted root
     must not be expired (`ExpiredMetadataError`).
   - **Fast-forward attack recovery:** if the updated root rotates the keys of
     the timestamp or snapshot role (i.e. the trusted signing keys for that role
     changed), the client must discard its locally cached timestamp and snapshot
     before loading them. This lets the repository recover from a compromised
     role by rotating its keys and resetting its version — a subsequent
     timestamp/snapshot signed by the *new* keys is accepted even if its version
     number is lower than the previously cached (attacker-inflated) one.
2. **Timestamp.** Must meet the timestamp role's signature threshold
   (`UnsignedMetadataError`), must not be expired (`ExpiredMetadataError`), and
   its version must not be **lower** than the currently trusted timestamp
   (`BadVersionNumberError`); an equal version is silently ignored. **Both
   rollback checks happen while updating the timestamp**, so a timestamp that
   fails either check is rejected and the previously trusted timestamp remains
   the cached one (it is not overwritten):
   - the new timestamp's own version vs. the trusted timestamp's version, and
   - the new timestamp's `snapshot_meta.version` vs. the trusted timestamp's
     `snapshot_meta.version` — a lower snapshot version is a snapshot rollback
     and raises `BadVersionNumberError`.

   Rollback checks compare against the locally cached timestamp even if that
   cached timestamp has itself expired.
3. **Snapshot.** Must meet the snapshot threshold; if the trusted timestamp's
   `snapshot_meta` records a length/hash, the downloaded snapshot must match it
   (`LengthOrHashMismatchError`); the snapshot version must equal the version in
   `timestamp.snapshot_meta` (`BadVersionNumberError`); no role's version listed
   in the new snapshot may be lower than in the trusted snapshot
   (`BadVersionNumberError`); must not be expired.
4. **Targets.** Must meet the targets threshold; its version must equal the
   version recorded for `targets.json` in the trusted snapshot; must not be
   expired.

**`get_targetinfo(target_path) -> TargetFile | None`** — return the
`TargetFile` for `target_path`, or `None` if no role provides it. Calls
`refresh()` first if it has not been called. Resolves the target by a
**preorder depth-first traversal** of the delegation graph starting at
`targets`: load and verify each delegated targets role on demand — each role's
metadata is verified against its delegating role for **both** the required
signature threshold (`UnsignedMetadataError`) and expiry (`ExpiredMetadataError`)
— return the first matching `TargetFile`, and honor `terminating` delegations
(which stop backtracking). Traversal visits at most `config.max_delegations`
roles.

**`download_target(targetinfo, filepath=None, target_base_url=None) -> str`** —
download the target described by `targetinfo`, verify its length and hashes,
write it to `filepath` (or a path derived from `target_dir` and the target
path), and return that path. When the trusted root has `consistent_snapshot`
set and `config.prefix_targets_with_hash` is true, the download URL's filename
is prefixed with the target's hash digest (`<hash>.<filename>`).

**`find_cached_target(targetinfo, filepath=None) -> str | None`** — return the
local path if a file already on disk matches `targetinfo`'s length and hashes,
otherwise `None`.

---

## Part 3 — Repository authoring (`tuf.repository`)

`tuf.repository` must export `Repository` and `AbortEdit`.

- `AbortEdit(Exception)` — raised inside an `edit()` block to cancel the edit so
  that **no** new metadata version is stored.

- `Repository` — an **abstract base class** for metadata-editing applications
  (repository servers, signing tools). Subclasses implement storage; the base
  class provides the editing workflow.

  **Abstract members the subclass must implement:**
  - `open(role) -> Metadata` — load the current metadata for `role` from
    storage; if it does not exist, return a fresh first version.
  - `close(role, md) -> None` — persist `md` for `role` (bump version, refresh
    expiry, re-sign with all available keys, update version caches).
  - property `targets_infos -> dict[str, MetaFile]` — the `MetaFile`s for the
    targets metadata that currently exist (keyed by `"<role>.json"`). Used by
    `do_snapshot()`.
  - property `snapshot_info -> MetaFile` — the `MetaFile` for the current
    snapshot. Used by `do_timestamp()`.

  **Concrete members the base class provides:**
  - `edit(role)` — a context manager yielding the role's `Signed` payload; on
    normal exit it calls `close()` to store a new version. Raising `AbortEdit`
    inside the block cancels the edit (nothing is stored).
  - `edit_root()`, `edit_timestamp()`, `edit_snapshot()`,
    `edit_targets(rolename="targets")` — typed wrappers around `edit()` that
    yield the corresponding payload type.
  - `root()`, `timestamp()`, `snapshot()`, `targets(rolename="targets")` —
    return the current signed payload for the role.
  - `do_snapshot(force=False) -> tuple[bool, dict[str, MetaFile]]` — bring the
    snapshot up to date with the current targets metadata. Creates a new
    snapshot version **iff** a targets role is new in, or has a higher version
    than, the current snapshot meta — or the existing snapshot is not validly
    signed by the current snapshot keys, or `force` is true. A lower targets
    version is a rollback and raises `ValueError`. Returns
    `(created, removed_metafiles)`; when nothing changed, `created` is `False`
    and no new version is written.
  - `do_timestamp(force=False) -> tuple[bool, MetaFile | None]` — bring the
    timestamp up to date with the current snapshot. Creates a new timestamp
    version **iff** `snapshot_info.version` differs from the timestamp's recorded
    `snapshot_meta.version` (a lower snapshot version raises `ValueError`), or
    the existing timestamp is not validly signed, or `force` is true. Returns
    `(created, removed_metafile)`.

## Notes

- All metadata `expires` values are timezone-aware UTC datetimes; expiry is
  checked against the current time.
- **Signature thresholds.** A metadata file is considered correctly signed only
  when at least `threshold` *distinct* keys authorized for that role (by the
  trusted root, or by the delegating targets role) have valid signatures over
  its canonical bytes; fewer than `threshold` valid signatures raises
  `UnsignedMetadataError`, regardless of how many signatures are attached.
- **Consistent snapshot.** When the trusted root has `consistent_snapshot`
  enabled, remote metadata is requested version-prefixed
  (`<version>.<role>.json`) **except** `timestamp`, which is always requested
  unversioned; and target downloads use a hash-prefixed filename
  (`<hash>.<filename>`) when `config.prefix_targets_with_hash` is set. When
  `consistent_snapshot` is disabled, all metadata is requested unversioned and
  targets are downloaded under their plain filenames.
