"""End-to-end hidden test suite for the regipy WRG task.

Each test exercises a user-facing capability — CLI invocation, public Python API,
or plugin extraction — against real Windows registry hive fixtures shipped under
/tests/data/. No internal-module imports, no unit tests. Every assertion checks
a semantic property that a correct implementation must produce.
"""

import csv
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.absolute() / "data"


def _extract_xz(name: str, dest_dir: str) -> str:
    """Extract a .xz hive fixture to dest_dir and return the extracted path."""
    out_path = os.path.join(dest_dir, name.replace(".xz", ""))
    with lzma.open(DATA_DIR / name) as src, open(out_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return out_path


@pytest.fixture
def workdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def ntuser_hive(workdir):
    return _extract_xz("NTUSER.DAT.xz", workdir)


@pytest.fixture
def system_hive(workdir):
    return _extract_xz("SYSTEM.xz", workdir)


@pytest.fixture
def software_hive(workdir):
    return _extract_xz("SOFTWARE.xz", workdir)


@pytest.fixture
def sam_hive(workdir):
    return _extract_xz("SAM.xz", workdir)


@pytest.fixture
def bcd_hive(workdir):
    return _extract_xz("BCD.xz", workdir)


@pytest.fixture
def amcache_hive(workdir):
    return _extract_xz("amcache.hve.xz", workdir)


@pytest.fixture
def ntuser_modified_hive(workdir):
    return _extract_xz("NTUSER_modified.DAT.xz", workdir)


@pytest.fixture
def ntuser_software_partial_hive(workdir):
    return _extract_xz("ntuser_software_partial.xz", workdir)


@pytest.fixture
def transaction_ntuser(workdir):
    hive = _extract_xz("transactions_NTUSER.DAT.xz", workdir)
    log1 = _extract_xz("transactions_ntuser.dat.log1.xz", workdir)
    return hive, log1


@pytest.fixture
def transaction_system(workdir):
    hive = _extract_xz("SYSTEM_B.xz", workdir)
    log1 = _extract_xz("SYSTEM_B.LOG1.xz", workdir)
    log2 = _extract_xz("SYSTEM_B.LOG2.xz", workdir)
    return hive, log1, log2


@pytest.fixture
def transaction_usrclass(workdir):
    hive = _extract_xz("UsrClass.dat.xz", workdir)
    log1 = _extract_xz("UsrClass.dat.LOG1.xz", workdir)
    log2 = _extract_xz("UsrClass.dat.LOG2.xz", workdir)
    return hive, log1, log2


@pytest.fixture
def system_devprop_hive(workdir):
    return _extract_xz("SYSTEM_2.xz", workdir)


@pytest.fixture
def system_filetime_hive(workdir):
    return _extract_xz("SYSTEM_WIN_10_1709.xz", workdir)


# ---------------------------------------------------------------------------
# CLI tests — exercise the installed `regipy-*` entry points end-to-end.
# ---------------------------------------------------------------------------


def test_cli_parse_header_reports_known_ntuser_fields(ntuser_hive):
    """The `regipy-parse-header` CLI prints the parsed REGF header for an NTUSER hive."""
    result = subprocess.run(
        ["regipy-parse-header", ntuser_hive],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = result.stdout + result.stderr
    # Header fields rendered into the output (table layout is implementation-defined,
    # but the values themselves are not negotiable).
    assert "749" in combined, "primary sequence number missing"
    assert "?\\C:\\Users\\vibranium\\ntuser.dat" in combined, "embedded hive file_name missing"
    # The NTUSER fixture is clean (primary == secondary == 749), so no dirty-state warning.
    assert "dirty" not in combined.lower() and "transaction logs" not in combined.lower()


def test_cli_parse_header_dirty_hive_surfaces_warning(transaction_ntuser):
    """`regipy-parse-header` flags a dirty hive (primary != secondary sequence)."""
    hive, _log1 = transaction_ntuser
    result = subprocess.run(
        ["regipy-parse-header", hive],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = result.stdout + result.stderr
    # The dirty fixture has primary=567, secondary=566 — header values must render.
    assert "567" in combined, "primary sequence number 567 missing"
    assert "566" in combined, "secondary sequence number 566 missing"
    # And the CLI must surface a dirty-state warning ("dirty" or "transaction logs").
    low = combined.lower()
    assert "dirty" in low or "transaction logs" in low, (
        f"expected dirty/transaction-logs warning in output, got: {combined!r}"
    )


def test_cli_dump_produces_ndjson_with_known_entry_count(ntuser_hive, workdir):
    """`regipy-dump -o <out>` writes one JSON object per subkey, including the root."""
    out_path = os.path.join(workdir, "ntuser.ndjson")
    result = subprocess.run(
        ["regipy-dump", ntuser_hive, "-o", out_path],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    with open(out_path) as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    # 1812 subkeys in NTUSER.DAT counting from root (matches the recursive walk).
    assert len(lines) == 1812, f"expected 1812 NDJSON entries, got {len(lines)}"
    # Every line is valid JSON, and each entry has the documented fields.
    parsed = [json.loads(line) for line in lines]
    for entry in parsed[:50]:
        assert "subkey_name" in entry
        assert "path" in entry
        assert "timestamp" in entry
        assert "values_count" in entry
        assert "values" in entry
    # Field presence is shape; pin one concrete entry's content so a serializer that emits the
    # right keys with wrong/empty values is caught. \AppEvents\EventLabels\.Default is a fixed
    # fixture property: leaf name ".Default", last-modified 2012-04-03T21:19:54.733216+00:00, and
    # two REG_SZ values ("(default)" -> "Default Beep", "DispFileName" -> "@mmres.dll,-5824").
    by_path = {e["path"]: e for e in parsed}
    target = r"\AppEvents\EventLabels\.Default"
    assert target in by_path, f"expected NDJSON entry for {target}"
    ae = by_path[target]
    assert ae["subkey_name"] == ".Default", f"unexpected subkey_name: {ae['subkey_name']!r}"
    assert ae["timestamp"] == "2012-04-03T21:19:54.733216+00:00", (
        f"unexpected timestamp: {ae['timestamp']!r}"
    )
    assert ae["values_count"] == 2, f"unexpected values_count: {ae['values_count']!r}"
    ae_values = {v["name"]: v["value"] for v in ae["values"]}
    assert ae_values.get("(default)") == "Default Beep", f"unexpected (default): {ae['values']}"
    assert ae_values.get("DispFileName") == "@mmres.dll,-5824", f"unexpected values: {ae['values']}"


def test_cli_dump_timeline_csv_has_expected_columns(ntuser_hive, workdir):
    """`regipy-dump -t -o <out>` writes a CSV timeline with the documented columns and values."""
    out_path = os.path.join(workdir, "ntuser_timeline.csv")
    result = subprocess.run(
        ["regipy-dump", ntuser_hive, "-t", "-o", out_path],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Per-row `values` column can serialise large REG_BINARY/REG_MULTI_SZ payloads,
    # exceeding Python's default csv field limit (128KB). Bump it for this read.
    csv.field_size_limit(2**24)
    with open(out_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    expected_cols = {"timestamp", "subkey_name", "values_count", "values"}
    assert expected_cols.issubset(set(reader.fieldnames or [])), (
        f"missing columns; got fieldnames={reader.fieldnames}"
    )
    # One row per subkey — same stable tree total as the NDJSON dump (catches dropped/duplicated
    # rows, not just headers).
    assert len(rows) == 1812, f"expected 1812 timeline rows, got {len(rows)}"
    # The `subkey_name` column carries each subkey's full backslash path. Assert a concrete
    # computed cell for a fixed path so a wrong-but-right-shaped timeline (correct columns/count,
    # garbage values) is caught: the \AppEvents\EventLabels\.Default key has values_count 2 and
    # its last-modified time decodes to 2012-04-03 21:19:54.733216 UTC.
    by_path = {r["subkey_name"]: r for r in rows}
    target = r"\AppEvents\EventLabels\.Default"
    assert target in by_path, f"expected timeline row for {target}; got e.g. {list(by_path)[:5]}"
    ae = by_path[target]
    assert ae["values_count"] == "2", f"unexpected values_count: {ae['values_count']!r}"
    # Date and time-of-day are unambiguous; the date/time separator (ISO 'T' vs space) is left to
    # the writer, so assert the components rather than the exact rendering.
    assert "2012-04-03" in ae["timestamp"] and "21:19:54.733216" in ae["timestamp"], (
        f"unexpected timestamp: {ae['timestamp']!r}"
    )


def test_cli_plugins_list_includes_known_plugin_names():
    """`regipy-plugins-list` enumerates the available plugin catalog."""
    result = subprocess.run(
        ["regipy-plugins-list"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    combined = result.stdout + result.stderr
    # A representative cross-section of plugin NAMEs from different hive types.
    for plugin_name in [
        "ntuser_persistence",
        "user_assist",
        "typed_urls",
        "computer_name",
        "services",
    ]:
        assert plugin_name in combined, f"plugin '{plugin_name}' missing from listing"
    # Each row also renders the plugin's compatible hive type, so a name-only stub catalog (right
    # NAME constants, no COMPATIBLE_HIVE) does not pass: the listed plugins span the ntuser and
    # system hive types, both of which must appear in the output.
    for hive_type in ["ntuser", "system"]:
        assert hive_type in combined, f"compatible hive type '{hive_type}' missing from listing"


def test_cli_plugins_run_writes_json_with_expected_artifacts(ntuser_hive, workdir):
    """`regipy-plugins-run` auto-detects the hive type and writes JSON output."""
    out_path = os.path.join(workdir, "plugins.json")
    result = subprocess.run(
        ["regipy-plugins-run", ntuser_hive, "-o", out_path],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    with open(out_path) as f:
        output = json.load(f)
    # CLI-specific contract: the entry point auto-detects the hive type, runs its plugins, and
    # writes a non-empty JSON dict keyed by plugin name. The full NTUSER key-set is verified by
    # the API-level test_run_relevant_plugins_extracts_ntuser_artifacts (this test does not
    # re-assert the whole key set, to avoid double-crediting it).
    assert isinstance(output, dict) and output, f"plugins-run produced empty output: {output}"
    assert "ntuser_persistence" in output, (
        f"NTUSER hive not auto-detected / no plugins ran; got keys: {set(output.keys())}"
    )
    # But verify the CLI JSON serialization end-to-end with one concrete decoded artifact from the
    # CLI's own output: the Sidebar autorun under the Run key must survive into plugins.json, so a
    # right-shaped-but-empty result ({'ntuser_persistence': []}) is caught here, not only via the API.
    persistence = output["ntuser_persistence"]
    run_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    found_sidebar = False
    entries = persistence.items() if isinstance(persistence, dict) else enumerate(persistence)
    for path_or_idx, entry in entries:
        path = path_or_idx if isinstance(path_or_idx, str) else ""
        if isinstance(entry, dict):
            path = entry.get("key", "") or entry.get("path", "") or path
            if run_key_path in path:
                if any(v.get("name") == "Sidebar" for v in entry.get("values", [])):
                    found_sidebar = True
    assert found_sidebar, f"Sidebar autorun entry missing from CLI plugins-run JSON: {persistence}"


def test_cli_diff_writes_csv_with_expected_difference_content(
    ntuser_hive, ntuser_modified_hive, workdir
):
    """`regipy-diff h1 h2 -o <out>` writes a pipe-delimited file enumerating the real differences.

    Unlike the API-level shape/count test, this pins the actual *content* the diff must compute
    for this fixture pair: the rendered rows must name the added value and the affected key paths.
    """
    out_path = os.path.join(workdir, "diff.csv")
    result = subprocess.run(
        ["regipy-diff", ntuser_hive, ntuser_modified_hive, "-o", out_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Pipe-delimited: difference | first_hive | second_hive | description.
    csv.field_size_limit(2**24)
    with open(out_path) as f:
        reader = csv.reader(f, delimiter="|")
        rows = [r for r in reader if r and any(c.strip() for c in r)]
    header, data_rows = rows[0], rows[1:]
    assert header[0].strip().lower() == "difference", f"unexpected header: {header}"
    assert {r[0] for r in data_rows} <= {"new_subkey", "new_value"}, (
        f"unexpected difference types: {sorted({r[0] for r in data_rows})}"
    )

    # The lone new_value: the planted 'not_a_malware' autorun under the Run key. The value name,
    # its data, and the affected key path must all be rendered into the row.
    new_value_rows = [r for r in data_rows if r[0] == "new_value"]
    assert new_value_rows, f"no new_value row emitted: {data_rows}"
    nv_blob = " | ".join(" ".join(r) for r in new_value_rows)
    assert "not_a_malware" in nv_blob, f"new_value name 'not_a_malware' missing: {new_value_rows}"
    assert "legitimate_binary.exe" in nv_blob, f"new_value data missing: {new_value_rows}"
    assert r"\Software\Microsoft\Windows\CurrentVersion\Run" in nv_blob, (
        f"new_value key path missing: {new_value_rows}"
    )

    # The added subkeys land under the planted WinRAR tree and the 'legitimate_subkey'.
    new_subkey_descs = " ".join(r[3] for r in data_rows if r[0] == "new_subkey")
    assert "WinRAR" in new_subkey_descs, f"expected WinRAR subkey additions: {new_subkey_descs}"
    assert "legitimate_subkey" in new_subkey_descs, (
        f"expected 'legitimate_subkey' addition: {new_subkey_descs}"
    )


def test_cli_process_transaction_logs_recovers_dirty_hive(
    transaction_ntuser, workdir
):
    """`regipy-process-transaction-logs` applies the log and produces a clean hive."""
    hive, log1 = transaction_ntuser
    out_path = os.path.join(workdir, "recovered.dat")
    result = subprocess.run(
        [
            "regipy-process-transaction-logs",
            hive,
            "-p",
            log1,
            "-o",
            out_path,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Output path must exist and be a non-trivial file.
    assert os.path.exists(out_path), "recovered hive not written"
    assert os.path.getsize(out_path) > 1024, "recovered hive too small to be valid"
    # Combined CLI output reports the number of recovered dirty pages. The exact count is a
    # reference-replay internal that depends on how the (spec-undocumented) log block layout is
    # parsed (see the API test above), so assert only that the surfaced count is a substantial
    # positive total, not the exact reference constant. A faithful replay of a genuinely dirty
    # hive recovers a page total "in the low hundreds", so a >= 100 floor comfortably rejects a
    # no-op / near-empty replay while tolerating a faithful-but-differently-parsed count. Real
    # fixture: 132. The count is read off the line that reports it (the CLI must surface the
    # recovered dirty-page count itself) rather than from any digit run anywhere in the output,
    # which a temp-path component or a byte size would satisfy without replaying a single page.
    combined = result.stdout + result.stderr
    reported = [
        int(n)
        for line in combined.splitlines()
        if re.search(r"dirty|page|recover", line, re.IGNORECASE)
        for n in re.findall(r"\d+", line)
    ]
    assert any(n >= 100 for n in reported), (
        f"expected a substantial recovered-dirty-pages count in output, got: {combined!r}"
    )


# ---------------------------------------------------------------------------
# Python API tests — core hive parsing.
# ---------------------------------------------------------------------------


def test_hive_type_autodetection_across_six_hive_kinds(
    ntuser_hive, system_hive, software_hive, sam_hive, amcache_hive, bcd_hive
):
    """Loading any of the six well-known hive kinds auto-identifies the hive type."""
    from regipy.registry import RegistryHive

    assert RegistryHive(ntuser_hive).hive_type == "ntuser"
    assert RegistryHive(system_hive).hive_type == "system"
    assert RegistryHive(software_hive).hive_type == "software"
    assert RegistryHive(sam_hive).hive_type == "sam"
    assert RegistryHive(amcache_hive).hive_type == "amcache"
    assert RegistryHive(bcd_hive).hive_type == "bcd"


def test_full_recursive_walk_over_ntuser_hive(ntuser_hive):
    """Recursing the entire NTUSER hive yields the expected subkey total and value-type mix.

    The subkey total is a stable property of the hive tree (corroborated by the NDJSON dump
    test). The exact per-type histogram, however, hinges on edge-case decisions the spec does
    not pin (counting of corrupted/slack records, big-data cells, etc.), so it is checked
    structurally: every documented REG_* type must appear and the dominant buckets must clear
    sensible lower bounds, rather than matching fixture-specific exact counts.
    """
    from regipy.registry import RegistryHive

    reg = RegistryHive(ntuser_hive)
    value_types = {
        "REG_BINARY": 0,
        "REG_DWORD": 0,
        "REG_EXPAND_SZ": 0,
        "REG_MULTI_SZ": 0,
        "REG_NONE": 0,
        "REG_QWORD": 0,
        "REG_SZ": 0,
    }
    subkey_count = 0
    values_count = 0
    for subkey in reg.recurse_subkeys(as_json=True):
        subkey_count += 1
        for v in subkey.values or []:
            values_count += 1
            vtype = v["value_type"]
            if vtype in value_types:
                value_types[vtype] += 1
    # Tree shape is stable and independently verified by the NDJSON dump test.
    assert subkey_count == 1812
    # A faithful walk fetches the bulk of the values; allow headroom for edge-case counting.
    assert values_count >= 3800, f"expected ~4094 values, got {values_count}"
    # Every documented value type must be present in this hive.
    assert all(v > 0 for v in value_types.values()), f"some REG_* type missing: {value_types}"
    # The dominant buckets must clear sensible lower bounds (real fixture: SZ~1636, DWORD~1336,
    # BINARY~531, MULTI_SZ~303, NONE~141, EXPAND_SZ~93, QWORD~54).
    assert value_types["REG_SZ"] >= 1500
    assert value_types["REG_DWORD"] >= 1200
    assert value_types["REG_BINARY"] >= 450
    assert value_types["REG_MULTI_SZ"] >= 250


def test_full_recursive_walk_over_amcache_hive(amcache_hive):
    """Recursing the AMCACHE hive yields exact subkey, value, and value-type totals.

    Amcache stores Windows application execution metadata. Its value mix is heavily
    skewed toward REG_SZ and REG_QWORD (file timestamps), which sharply differs from
    NTUSER — a correct parser must produce these distinct distributions.
    """
    from regipy.registry import RegistryHive

    reg = RegistryHive(amcache_hive)
    value_types = {
        "REG_BINARY": 0,
        "REG_DWORD": 0,
        "REG_EXPAND_SZ": 0,
        "REG_MULTI_SZ": 0,
        "REG_NONE": 0,
        "REG_QWORD": 0,
        "REG_SZ": 0,
    }
    subkey_count = 0
    values_count = 0
    for subkey in reg.recurse_subkeys(as_json=True):
        subkey_count += 1
        for v in subkey.values or []:
            values_count += 1
            vtype = v["value_type"]
            if vtype in value_types:
                value_types[vtype] += 1
    # Tree shape is stable for this fixture.
    assert subkey_count == 2105
    # Exact value total depends on edge-case counting; assert a faithful lower bound.
    assert values_count >= 16000, f"expected ~17539 values, got {values_count}"
    # Amcache is heavily skewed toward REG_SZ (file paths) and REG_QWORD (timestamps); these
    # dominant buckets distinguish it from NTUSER and must clear sensible lower bounds (real
    # fixture: SZ~14433, DWORD~1656, QWORD~1254, MULTI_SZ~140, BINARY~56).
    assert value_types["REG_SZ"] >= 13000
    assert value_types["REG_QWORD"] >= 1100
    assert value_types["REG_DWORD"] >= 1400
    # The mix is sharply different from NTUSER: far more REG_SZ than REG_DWORD here.
    assert value_types["REG_SZ"] > value_types["REG_DWORD"]


def test_recurse_without_fetching_values(ntuser_hive):
    """`recurse_subkeys(fetch_values=False)` skips value parsing but reports values_count."""
    from regipy.registry import RegistryHive

    reg = RegistryHive(ntuser_hive)
    subkey_count = 0
    saw_nonzero_count = False
    for subkey in reg.recurse_subkeys(as_json=True, fetch_values=False):
        subkey_count += 1
        # Values must be empty when fetching is disabled.
        assert subkey.values == [] or subkey.values is None
        if subkey.values_count and subkey.values_count > 0:
            saw_nonzero_count = True
    # Full walk (including root) yields 1812 entries — same total as a fetch_values=True walk.
    assert subkey_count == 1812
    # Many subkeys have values; the count field must still be populated from headers.
    assert saw_nonzero_count, "values_count never surfaced a non-zero count"


def test_key_navigation_paths_and_missing_key_exceptions(software_hive):
    """`get_key` accepts equivalent paths; missing keys/subkeys raise distinct exceptions."""
    from regipy.exceptions import (
        NoRegistrySubkeysException,
        RegistryKeyNotFoundException,
    )
    from regipy.registry import RegistryHive

    reg = RegistryHive(software_hive)

    # Three equivalent ways to reach the same key must resolve to the same on-disk key. Compare
    # the documented public attributes (name, header.last_modified, subkey_count) rather than
    # relying on NKRecord object identity / value-equality, which the contract does not mandate.
    by_root_subkey = reg.root.get_subkey("ODBC")
    by_simple_path = reg.get_key("ODBC")
    by_prefixed_path = reg.get_key("SOFTWARE\\ODBC")
    names = {by_simple_path.name, by_root_subkey.name, by_prefixed_path.name}
    last_modified = {
        by_simple_path.header.last_modified,
        by_root_subkey.header.last_modified,
        by_prefixed_path.header.last_modified,
    }
    subkey_counts = {
        by_simple_path.subkey_count,
        by_root_subkey.subkey_count,
        by_prefixed_path.subkey_count,
    }
    assert len(names) == 1 and len(last_modified) == 1 and len(subkey_counts) == 1

    # Missing top-level key raises RegistryKeyNotFoundException.
    with pytest.raises(RegistryKeyNotFoundException):
        reg.get_key("\\Definitely\\Not\\A\\Real\\Path")

    # Missing subkey under a leaf key raises NoRegistrySubkeysException
    # (distinct from RegistryKeyNotFoundException — leaf has no children at all).
    odbc = reg.get_key("ODBC")
    with pytest.raises(NoRegistrySubkeysException):
        odbc.get_subkey("totally_made_up_name")

    # `raise_on_missing=False` returns None for the missing-subkey case.
    assert odbc.get_subkey("totally_made_up_name", raise_on_missing=False) is None


# ---------------------------------------------------------------------------
# Edge cases the agent could miss.
# ---------------------------------------------------------------------------


def test_unicode_emoji_subkey_name_preserved(workdir):
    """Subkey names that contain UTF-16 emoji are decoded and exposed verbatim."""
    from regipy.registry import RegistryHive

    hive = _extract_xz("transactions_NTUSER.DAT.xz", workdir)
    reg = RegistryHive(hive)
    intl = reg.get_key(r"\Control Panel\International")
    names = [sk.name for sk in intl.iter_subkeys()]
    assert "\U0001f30e\U0001f30f\U0001f30d" in names, (
        f"emoji subkey not preserved; got names: {names}"
    )


def test_partial_hive_with_explicit_type_and_path(ntuser_software_partial_hive):
    """Loading a partial hive requires both `hive_type` and `partial_hive_path`."""
    from regipy.registry import RegistryHive

    reg = RegistryHive(
        ntuser_software_partial_hive,
        hive_type="ntuser",
        partial_hive_path=r"\Software",
    )
    # The recognized prefix must apply to every yielded subkey.
    subkey_count = 0
    for subkey in reg.recurse_subkeys(as_json=True):
        subkey_count += 1
        assert subkey.actual_path is not None
        assert subkey.actual_path.startswith(r"\Software"), (
            f"subkey path '{subkey.actual_path}' missing partial prefix"
        )
    assert subkey_count == 6396

    # And `get_key` resolves a path that exists below the partial root.
    run_key = reg.get_key(r"\Software\Microsoft\Windows\CurrentVersion\Run")
    values = list(run_key.iter_values(as_json=True))
    names = [v.name for v in values]
    assert "OneDrive" in names


def test_filetime_value_type_serialises_to_iso(system_filetime_hive):
    """Value type 18 (FILETIME) becomes an ISO-8601 string when as_json=True."""
    from regipy.registry import RegistryHive

    reg = RegistryHive(system_filetime_hive)
    subkey = reg.get_key(
        r"\ControlSet001\Enum\USBSTOR\Disk&Ven_SanDisk&Prod_Cruzer&Rev_1.2"
        r"0\200608767007B7C08A6A&0\Properties"
        r"\{83da6326-97a6-4088-9453-a1923f573b29}\0064"
    )
    val = subkey.get_value("(default)", as_json=True)
    # The 8-byte FILETIME decodes to this UTC instant, serialised as an offset-aware ISO-8601
    # string. The microsecond field follows from the documented float-division conversion
    # (FILETIME / 10 microseconds added to the 1601 epoch), which pins the final digit, so the
    # whole rendered string is asserted rather than a prefix.
    assert isinstance(val, str)
    assert val == "2020-03-17T14:02:38.955490+00:00"


def test_devprop_string_value_type_18(system_devprop_hive):
    """Non-standard registry value type 18 (string content) is parsed correctly."""
    from regipy.registry import RegistryHive

    reg = RegistryHive(system_devprop_hive)
    subkey = reg.get_key(
        r"\ControlSet001\Enum\ACPI\ACPI0003\0\Properties"
        r"\{83da6326-97a6-4088-9453-a1923f573b29}\0003"
    )
    assert subkey.values_count == 1
    value = subkey.get_values()[0]
    assert value.name == "(default)"
    assert value.value == "cmbatt.inf:db04a16c09a7808a:AcAdapter_Inst:6.3.9600.16384:ACPI\\ACPI0003"
    # The type is the raw integer 18 (no symbolic REG_* name for this Windows-device-property variant).
    assert value.value_type == 18


def test_convert_wintime_round_trip(ntuser_hive):
    """`convert_wintime` decodes a subkey's last_modified field to a datetime."""
    import datetime

    from regipy.registry import RegistryHive
    from regipy.utils import convert_wintime

    reg = RegistryHive(ntuser_hive)
    run = reg.get_key(r"\Software\Microsoft\Windows\CurrentVersion\Run")
    raw = run.header.last_modified
    # Known FILETIME for this fixture's Run key (~2012-04-03).
    assert raw == 129779615948377168
    dt = convert_wintime(raw)
    assert isinstance(dt, datetime.datetime)
    assert dt.year == 2012 and dt.month == 4 and dt.day == 3


# ---------------------------------------------------------------------------
# Transaction-log recovery — three independent scenarios.
# ---------------------------------------------------------------------------


def test_transaction_log_recovery_ntuser_single_log(transaction_ntuser, workdir):
    """Applying a primary log to a dirty NTUSER hive recovers the documented dirty pages."""
    from regipy.recovery import apply_transaction_logs
    from regipy.regdiff import compare_hives

    hive, log1 = transaction_ntuser
    out = os.path.join(workdir, "recovered_ntuser.dat")
    restored_path, recovered_pages = apply_transaction_logs(
        hive, log1, restored_hive_path=out
    )
    # The exact dirty-page total depends on how the (spec-undocumented) log block layout is parsed
    # (sequence/hash gating, per-table-entry vs per-4096-byte counting) that the spec does not pin
    # down, so assert a recovery floor rather than the reference constant (mirroring the dual-log
    # sibling tests below). The floor is the spec's own documented magnitude: a faithful replay of
    # a genuinely dirty hive recovers a page total "in the low hundreds", so >= 100 rejects a
    # no-op / partial replay while tolerating a faithful-but-differently-parsed count. Real
    # fixture: 132.
    assert recovered_pages >= 100, f"expected substantial single-log recovery, got {recovered_pages}"
    assert restored_path == out
    # The recovery must materially change the hive: the diff yields many new_subkey / new_value
    # records (exact totals over-fit the reference replay + compare_hives semantics; real fixture:
    # ~527 new_subkey + ~60 new_value).
    diffs = compare_hives(hive, restored_path)
    assert sum(1 for d in diffs if d[0] == "new_subkey") >= 400
    assert sum(1 for d in diffs if d[0] == "new_value") >= 40


def test_transaction_log_recovery_system_primary_and_secondary(transaction_system, workdir):
    """Applying primary+secondary logs to a SYSTEM hive recovers the documented page counts."""
    from regipy.recovery import apply_transaction_logs
    from regipy.regdiff import compare_hives

    hive, log1, log2 = transaction_system
    out = os.path.join(workdir, "recovered_system.dat")
    restored_path, recovered_pages = apply_transaction_logs(
        hive, log1, secondary_log_path=log2, restored_hive_path=out
    )
    # The exact combined page total still depends on how the (spec-undocumented) log block layout
    # is parsed, so the count itself is asserted as a floor (real fixture: 315). The recovered
    # IMAGE, however, is spec-determined: the combine applies every dirty page of every block of
    # both logs, secondary first and then primary onto that image, and the result is promised to
    # be parseable and to report the recovered subkeys and values against the original hive. So
    # the post-recovery diff must be substantial, not merely non-empty — a replay that writes
    # pages at the wrong offsets, or applies only one of the two logs, is caught here rather than
    # by the page count. Floors keep headroom over the real fixture (2458 new_subkey / 53 new_value).
    assert recovered_pages >= 250, f"expected substantial dual-log recovery, got {recovered_pages}"
    diffs = compare_hives(hive, restored_path)
    assert sum(1 for d in diffs if d[0] == "new_subkey") >= 2000
    assert sum(1 for d in diffs if d[0] == "new_value") >= 40


def test_transaction_log_recovery_usrclass_primary_and_secondary(transaction_usrclass, workdir):
    """Applying primary+secondary logs to a UsrClass hive recovers the documented page counts."""
    from regipy.recovery import apply_transaction_logs
    from regipy.regdiff import compare_hives

    hive, log1, log2 = transaction_usrclass
    out = os.path.join(workdir, "recovered_usrclass.dat")
    restored_path, recovered_pages = apply_transaction_logs(
        hive, log1, secondary_log_path=log2, restored_hive_path=out
    )
    # The exact combined page total still depends on how the (spec-undocumented) log block layout
    # is parsed, so the count itself is asserted as a floor (real fixture: 158). The recovered
    # IMAGE is spec-determined (every dirty page of every block of both logs, secondary then
    # primary, yielding a hive whose diff against the original reports the recovered subkeys AND
    # values), so the diff must be substantial on both levels — on this fixture the value-level
    # recovery is the dominant signal. Floors keep headroom over the real fixture (93 new_subkey /
    # 132 new_value).
    assert recovered_pages >= 120, f"expected substantial dual-log recovery, got {recovered_pages}"
    diffs = compare_hives(hive, restored_path)
    assert sum(1 for d in diffs if d[0] == "new_subkey") >= 70
    assert sum(1 for d in diffs if d[0] == "new_value") >= 100


# ---------------------------------------------------------------------------
# Diffing + Security descriptors.
# ---------------------------------------------------------------------------


def test_compare_hives_returns_tuple_difference_records(ntuser_hive, ntuser_modified_hive):
    """`compare_hives` returns a list of 4-tuples capturing each subkey/value difference.

    `compare_hives` is a deterministic set difference over subkey paths/timestamps and value
    names, so the result for this fixture pair is well-defined and fixed. This test rewards the
    record *shape* and the exact difference counts; the sibling CLI test
    `test_cli_diff_writes_csv_with_expected_difference_content` rewards the rendered difference
    *content* (the affected value name / data / key paths), so the two cover distinct contracts.
    """
    from regipy.regdiff import compare_hives

    diffs = compare_hives(ntuser_hive, ntuser_modified_hive)
    # Each record is a 4-tuple: (difference_type, first_value, second_value, description).
    for d in diffs:
        assert len(d) == 4
    # Only subkey/value additions are expected for this fixture pair.
    assert {d[0] for d in diffs} <= {"new_subkey", "new_value"}, (
        f"unexpected difference types: {sorted({d[0] for d in diffs})}"
    )
    # The planted modifications add a WinRAR subtree + 'legitimate_subkey' (reported as one
    # new_subkey record per node of the one-side-only subtree) and exactly one new value
    # ('not_a_malware'). Both totals are fully pinned by the spec: new_value only under keys
    # present in both hives with differing last_modified, and new_subkey as a set difference over
    # the full subkey-path set with one record per node (not one per subtree root). Exact totals
    # therefore bound the diff from ABOVE as well: an over-reporting walk that emits a record per
    # scan direction, re-reports keys whose only change is last_modified, or double-walks a
    # subtree is caught here.
    assert sum(1 for d in diffs if d[0] == "new_subkey") == 6
    assert sum(1 for d in diffs if d[0] == "new_value") == 1
    assert len(diffs) == 7


def test_security_key_info_exposes_owner_group_and_dacl(ntuser_hive):
    """`get_security_key_info()` decodes the SK record into owner SID, group SID, and DACL."""
    from regipy.registry import RegistryHive

    reg = RegistryHive(ntuser_hive)
    run = reg.get_key(r"\Software\Microsoft\Windows\CurrentVersion\Run")
    info = run.get_security_key_info()
    assert info["owner"] == "S-1-5-18"
    assert info["group"] == "S-1-5-18"
    # DACL is a list of ACE dicts with documented keys.
    assert len(info["dacl"]) == 4
    sids = [ace["sid"] for ace in info["dacl"]]
    assert sids == [
        "S-1-5-21-2036804247-3058324640-2116585241-1673",
        "S-1-5-18",
        "S-1-5-32-544",
        "S-1-5-12",
    ]
    # Every ACE exposes access_mask, ace_type, flags, sid.
    for ace in info["dacl"]:
        assert set(ace.keys()) >= {"access_mask", "ace_type", "flags", "sid"}
    # And the first ACE's access flags match the known values.
    first = info["dacl"][0]
    assert first["ace_type"] == "ACCESS_ALLOWED"
    assert first["access_mask"]["DELETE"] is True
    assert first["access_mask"]["READ_CONTROL"] is True
    assert first["access_mask"]["WRITE_DAC"] is True
    assert first["access_mask"]["WRITE_OWNER"] is True


# ---------------------------------------------------------------------------
# Plugin invocations — exercise the auto-detected plugin pipeline.
# ---------------------------------------------------------------------------


def test_run_relevant_plugins_extracts_ntuser_artifacts(ntuser_hive):
    """`run_relevant_plugins` on an NTUSER hive yields the documented forensic artifacts."""
    from regipy.plugins.utils import run_relevant_plugins
    from regipy.registry import RegistryHive

    reg = RegistryHive(ntuser_hive)
    results = run_relevant_plugins(reg, as_json=True)

    # The NTUSER hive must produce all of these named plugin outputs.
    must_have = {
        "ntuser_persistence",
        "user_assist",
        "typed_urls",
        "typed_paths",
        "installed_programs_ntuser",
        "network_drives_plugin",
        "word_wheel_query",
    }
    missing = must_have - set(results.keys())
    assert not missing, f"missing required plugin outputs: {missing}"

    # ntuser_persistence reports at least the well-known Run key with the Sidebar autorun entry.
    persistence = results["ntuser_persistence"]
    # Output may be dict keyed by path, or list of dicts; check both shapes.
    run_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    found_sidebar = False
    if isinstance(persistence, dict):
        for path, entry in persistence.items():
            if run_key_path in path:
                values = entry.get("values", []) if isinstance(entry, dict) else []
                if any(v.get("name") == "Sidebar" for v in values):
                    found_sidebar = True
    elif isinstance(persistence, list):
        for entry in persistence:
            path = entry.get("key", "") or entry.get("path", "")
            if run_key_path in path:
                values = entry.get("values", [])
                if any(v.get("name") == "Sidebar" for v in values):
                    found_sidebar = True
    assert found_sidebar, f"Sidebar autorun entry not found in ntuser_persistence: {persistence}"


def test_run_relevant_plugins_extracts_system_artifacts(system_hive):
    """`run_relevant_plugins` on a SYSTEM hive yields the documented system-state artifacts."""
    from regipy.plugins.utils import run_relevant_plugins
    from regipy.registry import RegistryHive

    reg = RegistryHive(system_hive)
    results = run_relevant_plugins(reg, as_json=True)

    # A SYSTEM hive must surface at least these plugins.
    must_have = {"computer_name", "services"}
    missing = must_have - set(results.keys())
    assert not missing, f"missing required SYSTEM plugin outputs: {missing}"

    # computer_name plugin must report the host name from the SYSTEM fixture.
    cname = results["computer_name"]
    assert cname, "computer_name returned no entries"
    # The plugin returns a list of {name, control_set/path, timestamp} dicts (any shape variant).
    names = []
    if isinstance(cname, list):
        for entry in cname:
            if isinstance(entry, dict):
                for key in ("computer_name", "name"):
                    if entry.get(key):
                        names.append(entry[key])
    # The SYSTEM fixture carries computer names from two control sets.
    assert "WKS-WIN732BITA" in names and "WIN-V5T3CSP8U4H" in names, (
        f"expected both ControlSet computer names, got: {names}"
    )


def test_run_relevant_plugins_extracts_software_artifacts(software_hive):
    """`run_relevant_plugins` on a SOFTWARE hive yields the documented software-state artifacts."""
    from regipy.plugins.utils import run_relevant_plugins
    from regipy.registry import RegistryHive

    reg = RegistryHive(software_hive)
    results = run_relevant_plugins(reg, as_json=True)

    # A SOFTWARE hive must surface at least these plugins.
    must_have = {
        "winver_plugin",
        "profilelist_plugin",
        "installed_programs_software",
        "software_plugin",
        "uac_plugin",
    }
    missing = must_have - set(results.keys())
    assert not missing, f"missing required SOFTWARE plugin outputs: {missing}"

    # winver_plugin must decode the OS identity from \Microsoft\Windows NT\CurrentVersion.
    # Keyed by that path; the entry carries the parsed ProductName / build for the fixture OS.
    winver = results["winver_plugin"]
    win_ver_path = r"\Microsoft\Windows NT\CurrentVersion"
    assert isinstance(winver, dict) and win_ver_path in winver, (
        f"winver_plugin missing the CurrentVersion entry: {winver}"
    )
    ver_entry = winver[win_ver_path]
    assert ver_entry.get("ProductName") == "Windows 7 Ultimate", (
        f"unexpected ProductName: {ver_entry.get('ProductName')!r}"
    )
    assert ver_entry.get("CurrentBuild") == "7601", (
        f"unexpected CurrentBuild: {ver_entry.get('CurrentBuild')!r}"
    )

    # profilelist_plugin must enumerate the user profiles, decoding each profile's SID and path.
    profiles = results["profilelist_plugin"]
    assert isinstance(profiles, list) and profiles, f"profilelist_plugin returned no entries: {profiles}"
    sids = {p.get("sid") for p in profiles if isinstance(p, dict)}
    paths = {p.get("path") for p in profiles if isinstance(p, dict)}
    # The system profile SID and a known user-profile path from the fixture.
    assert "S-1-5-18" in sids, f"expected system-profile SID S-1-5-18 in {sids}"
    assert "C:\\Users\\Pepper" in paths, f"expected profile path C:\\Users\\Pepper in {paths}"


def test_get_control_sets_returns_multiple_paths_for_system_hive(system_hive):
    """`RegistryHive.get_control_sets(path)` expands the path into one entry per ControlSet."""
    from regipy.registry import RegistryHive

    reg = RegistryHive(system_hive)
    # The SYSTEM fixture carries two control sets: ControlSet001 and ControlSet002.
    paths = reg.get_control_sets(r"\Select")
    assert len(paths) == 2, f"expected 2 control set expansions, got: {paths}"
    assert any("ControlSet001" in p for p in paths), f"missing ControlSet001 in {paths}"
    assert any("ControlSet002" in p for p in paths), f"missing ControlSet002 in {paths}"
