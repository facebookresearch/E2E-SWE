# regipy

Build `regipy`, a pure-Python library for parsing offline Windows registry hive
files (files whose first four bytes are `regf`). Registry hives store Windows'
configuration and per-user state as a tree of *keys* (named nodes with a last-
modified timestamp) and *values* (typed leaves). This library parses those files
without any Windows-only dependencies and exposes both a Python API and a set of
command-line tools used by digital-forensics workflows.

## Dependencies

The environment is **offline**: all dependencies are already installed and you must **not**
install anything (there is no network). The project itself is installed for you by a `setup.sh`
that runs offline (an editable install against the pre-installed dependencies), so just implement
the package so that an editable install exposes the API and console scripts described below.

The following runtime dependencies are pre-installed and available to import:

- `construct` — declarative binary-struct parser.
- `inflection` — string-case helpers used by plugin naming.
- `pytz` — timezone-aware datetime construction.
- `click` — command-line entry points.
- `tabulate` — human-readable table rendering for CLI output.

Pure Python; no system services or C extensions required.

## Package layout

Tests import from these paths and they must resolve:

- `regipy.registry.RegistryHive`, `regipy.registry.NKRecord`
- `regipy.exceptions.RegistryKeyNotFoundException`
- `regipy.exceptions.NoRegistrySubkeysException`
- `regipy.utils.convert_wintime`
- `regipy.recovery.apply_transaction_logs`
- `regipy.regdiff.compare_hives`
- `regipy.plugins.utils.run_relevant_plugins`

The agent is free to organize internal modules however it likes, but these
specific symbols must be importable from the paths above.

## CLI entry points

Six console scripts must be installable via the package's `[project.scripts]`
table (or equivalent `entry_points`). Each is run as a bare command after
`pip install`.

### `regipy-parse-header HIVE_PATH`

Prints the parsed REGF header fields (primary/secondary sequence numbers,
last-modification time, major/minor version, file_type, file_format, root key
offset, hive bins data size, clustering factor, embedded file_name, checksum)
in a human-readable form. When the header indicates the hive is dirty (its
primary sequence number differs from its secondary sequence number, or the hive
is otherwise detected as not cleanly closed), the command surfaces a warning
that mentions either "dirty" or "transaction logs".

### `regipy-dump HIVE_PATH -o OUT_PATH [-t]`

Without `-t`: writes newline-delimited JSON to `OUT_PATH`. Each line is one JSON
object describing one subkey (including the root). Each object has these keys:
`subkey_name`, `path`, `timestamp`, `values_count`, `values`. (`actual_path` may
also be present.)

With `-t` (timeline mode): writes a CSV to `OUT_PATH` with a header row
followed by one row per subkey. The header fields are `timestamp`,
`subkey_name`, `values_count`, `values` (other columns may be added but these
must be present). In timeline mode the `subkey_name` column carries each
subkey's full backslash-prefixed registry path (e.g.
`\AppEvents\EventLabels\.Default`) — not the leaf name. (This differs from the
NDJSON output above, where `subkey_name` is the leaf name and the full path
lives in the separate `path` field.)

### `regipy-plugins-list`

Prints a human-readable listing of every registered plugin, where each row
shows the plugin's `NAME`, the hive type it is compatible with, and a short
description. The listing must include at least the names `ntuser_persistence`,
`user_assist`, `typed_urls`, `computer_name`, and `services`.

### `regipy-plugins-run HIVE_PATH -o OUT_PATH`

Auto-detects the hive type, runs every plugin whose `COMPATIBLE_HIVE` matches,
and writes a single JSON object to `OUT_PATH` whose top-level keys are plugin
`NAME`s and whose values are the plugin output structures.

### `regipy-diff HIVE1 HIVE2 -o OUT_PATH`

Compares two hives of the same type. Writes a pipe-delimited (`|`) file to
`OUT_PATH` with one header row followed by one row per detected difference.
The header row names the four columns, in order:
`difference|first_hive|second_hive|description`. Each difference row begins
with a difference-type token in the `difference` column; the only emitted
tokens are `new_subkey` and `new_value` (mirroring the underlying
`compare_hives` API — see Python API section). The remaining columns carry the
first-hive value slot, the second-hive value slot, and the affected key path,
matching the 4-tuple the `compare_hives` API returns. Because the populated
value slot of a `new_value` difference identifies the value by name and data
(see `compare_hives` below), a rendered `new_value` row names the added value
as well as its data.

### `regipy-process-transaction-logs HIVE_PATH -p PRIMARY_LOG [-s SECONDARY_LOG] -o OUT_PATH`

Replays the supplied transaction log(s) onto a dirty hive and writes the
recovered hive to `OUT_PATH`. The recovered file must be parseable as a normal
hive. Stdout/stderr report the number of dirty pages that were recovered.

## Python API

### `RegistryHive(file_path, hive_type=None, partial_hive_path=None)`

Opens and parses a hive file at `file_path`.

- When `hive_type` is omitted, the type is auto-identified from the root
  key's name and its direct subkey names. The identification must return one
  of the strings `"ntuser"`, `"system"`, `"software"`, `"sam"`, `"security"`,
  `"amcache"`, `"bcd"`, `"usrclass"` for the corresponding well-known hives,
  exposed as the instance attribute `hive_type`. Disambiguation rules
  (checked in this order — the first match wins):
  - root subkey `Select` AND `ControlSet001` both present → `"system"`
  - root subkey `SAM` present AND root subkey `Microsoft` absent → `"sam"`
  - root subkey `Policy` present AND root subkey `SAM` absent → `"security"`
  - root key name contains `amcache`, OR root subkey `InventoryApplication`
    present, OR root subkey `Root` whose own subkeys include
    `InventoryApplication` → `"amcache"`
  - root subkey `Objects` AND (root subkey `Description` OR `Descriptions`)
    present → `"bcd"` (real BCD hives may use either spelling)
  - root subkey `Local Settings` present → `"usrclass"` (must be checked
    before the software/ntuser rules below, since usrclass hives also
    contain `Software`-like keys)
  - root subkey `Microsoft` present → `"software"` (a SOFTWARE hive's root
    typically contains `Microsoft`, `Classes`, `Mozilla`, etc.; do NOT
    exclude based on `Classes` — `HKLM\SOFTWARE\Classes` is legitimate)
  - root subkey `Software` present (under the user profile) → `"ntuser"`
  An unmatched root must raise `UnidentifiedHiveException`.
- `hive_type` lets the caller assert the type manually (also accepts the
  strings above).
- `partial_hive_path` (e.g. `"\\Software"`) declares that the supplied file
  is actually a sub-tree of the named hive type, rooted at the given path.
  When set, every absolute path passed to `get_key` is interpreted as
  starting from the partial root, and the path is exposed on yielded
  subkeys via the `actual_path` attribute.

Instance attributes used by tests:

- `header` — an object exposing parsed REGF header fields as attributes
  (e.g. `header.last_modified`, `header.primary_sequence_num`).
- `root` — the root `NKRecord` (named-key record) of the hive.

### Navigation: `RegistryHive.get_key(path)`

Returns the `NKRecord` at the given backslash-separated registry path. The
following invocations must all return equivalent records (same header) for a
given key:

```python
reg.get_key("ODBC")
reg.get_key("\\ODBC")
reg.get_key("SOFTWARE\\ODBC")  # for SOFTWARE hive — see prefix-stripping rule below
reg.root.get_subkey("ODBC")
```

Path-normalisation rules `get_key` MUST apply, in order:
1. Strip any leading backslash (so `"\\ODBC"` and `"ODBC"` are equivalent).
2. If the resulting first path component (case-insensitive) matches the
   instance's `hive_type` string (e.g. `"software"`, `"system"`, `"ntuser"`),
   drop that component before walking. Match against `self.hive_type` (the
   lowercase-string attribute), NOT against `self.root.name` (which on real
   hives is an internal CMI-generated identifier like
   `CMI-CreateHive{3D971F19-...}` and does not look like `"SOFTWARE"`).
3. If `partial_hive_path` is set and the path (after step 2) begins with the
   same first component as `partial_hive_path` (case-insensitive, leading
   backslash stripped from both sides for comparison), drop that component
   too. Example: with `partial_hive_path=r"\Software"`, the path
   `r"\Software\Microsoft\Windows\..."` walks the same node as
   `r"\Microsoft\Windows\..."`.
4. Walk the remaining components from the root.

Worked example for the SOFTWARE hive (whose `hive_type == "software"`),
all four forms must return the same `NKRecord`:

```python
reg.get_key("ODBC")             # → root["ODBC"]
reg.get_key("\\ODBC")           # step 1 strips "\" → "ODBC"
reg.get_key("SOFTWARE\\ODBC")   # step 2 drops "SOFTWARE" → "ODBC"
reg.get_key("\\Software\\ODBC") # steps 1+2 both fire → "ODBC"
```

If the requested path does not exist, `RegistryKeyNotFoundException` is raised.

### SYSTEM-hive helper: `RegistryHive.get_control_sets(registry_path)`

For a SYSTEM hive, takes a registry path containing a placeholder for the
control set (e.g. `r"\Select"`) and returns a list of fully-qualified paths
— one per actual ControlSet present on the hive. A Windows machine typically
has two control sets (`ControlSet001`, `ControlSet002`), so the call returns
a 2-element list; machines with more or fewer ControlSets return that many.
Each returned path is the input path with the control set name interpolated.

```python
reg = RegistryHive(system_hive)
reg.get_control_sets(r"\Select")
# → ["...ControlSet001...", "...ControlSet002..."]
```

### NKRecord (named-key record)

A single registry key. Attributes:

- `name` — the key name as a Python string (UTF-16 names, including non-BMP
  characters like emoji, must round-trip).
- `header` — exposes `last_modified` as a raw NT FILETIME integer
  (100-nanosecond intervals since 1601-01-01 UTC), plus other parsed
  header fields.
- `subkey_count`, `values_count` — counts as stored in the key header.

Methods:

- `iter_subkeys()` — yields child `NKRecord`s.
- `iter_values(as_json=False)` — yields child values (see Value below).
- `get_subkey(name, raise_on_missing=True)` — returns the named child or, when
  `raise_on_missing=False` and the child does not exist, returns `None`. When
  `raise_on_missing=True` and no child matches, raise `NoRegistrySubkeysException`.
  This applies to **both** missing-child cases:
  - The parent key has no children at all (a true leaf).
  - The parent has children but none match the requested name.
  In other words, `get_subkey` reports any miss — whether the key is childless or
  merely lacks that particular child — as `NoRegistrySubkeysException`; it does NOT
  raise `RegistryKeyNotFoundException` (that exception is reserved for `get_key`,
  see below).
- `get_value(name, as_json=False)` — returns the value's data (only) for the
  named value.
- `get_values(as_json=False)` — returns a list of value objects (see below).
- `get_security_key_info()` — see "Security descriptors" below.

### Values

A registry value carries a name, a typed data payload, and a type tag.

`NKRecord.iter_values()` (and `get_value`, `get_values`) ALWAYS yields
namespace-style objects (e.g. `namedtuple`-like) exposing the attributes
`name`, `value`, `value_type`, and `is_corrupted`. The `as_json` argument on
these methods controls only how the `.value` payload is encoded (see below);
the wrapper object itself remains attribute-accessible.

The `recurse_subkeys` generator is the only place that produces value entries
as **dicts**: when `as_json=True` is passed to `recurse_subkeys`, each entry's
`values` list contains dicts with keys `name`, `value`, `value_type`,
`is_corrupted`; when `as_json=False`, it contains the same namespace-style
objects described above.

The `value_type` field must use these symbolic strings for the standard types:

- `REG_NONE`, `REG_SZ`, `REG_EXPAND_SZ`, `REG_BINARY`, `REG_DWORD`,
  `REG_MULTI_SZ`, `REG_QWORD`.

For Windows device-property value types, the on-disk `data_type` carries
high-order flag bits (`0xFFFF0000`) plus a 16-bit type code in the low bits.
Implementations MUST mask off the high bits before classifying the value
(i.e. consult `data_type & 0xFFFF`). Two masked low-16-bit type codes appear in
these hives and both carry a typed payload rather than one of the standard
`REG_*` shapes:

- Code `16` (`0x10`) — an 8-byte NT FILETIME (the on-disk raw type is
  `0xFFFF0010`). The `value_type` reported on the value MUST be the masked
  integer `16`.
- Code `18` (`0x12`) — a UTF-16-LE string (the on-disk raw type is
  `0xFFFF0012`). The `value_type` reported on the value MUST be the masked
  integer `18`.

In general the `value_type` field reported on a device-property value MUST be
the masked low-16-bit integer (not the raw on-disk value), and these two codes
have no symbolic `REG_*` name — report the raw masked integer (`16` / `18`). The
payload is decoded by its length:

- When the payload is exactly 8 bytes, decode it as a little-endian NT
  FILETIME (this is the code-`16` case). The decoded data is a timezone-aware
  UTC `datetime`; when `as_json=True`, that timestamp is serialised as an
  ISO-8601 string (e.g. `"2020-03-17T14:02:38.955490+00:00"`).
- Otherwise (payload longer than 8 bytes), decode the payload as a
  null-terminated UTF-16-LE string (this is the code-`18` case). The decoded
  data is a Python `str`
  (e.g. `"cmbatt.inf:db04a16c09a7808a:AcAdapter_Inst:6.3.9600.16384:ACPI\\ACPI0003"`).

Value names like the unnamed default value are exposed as the string
`"(default)"`.

### Recursive enumeration: `RegistryHive.recurse_subkeys(name_key_entry=None, as_json=False, fetch_values=True)`

A generator yielding one entry per key reachable from `name_key_entry`
(defaulting to `root`), including the starting key itself.

Each yielded entry must be a **dataclass instance** (or equivalent
namespace-style object that supports attribute access — `entry.path`,
`entry.values`, etc.). Returning a raw `dict` is **not** sufficient: tests
access the fields below via attribute syntax, and `entry.values` must refer
to the registry-value list (not to Python's built-in `dict.values()`
method).

The following attributes are required on every entry:

- `subkey_name` — the leaf key name (str).
- `path` — backslash-prefixed path within the hive (str).
- `actual_path` — for partial hives, the absolute path within the full hive
  (i.e. prefixed with `partial_hive_path`); `None` for non-partial hives.
- `timestamp` — the key's last-modified time. ISO-8601 string when
  `as_json=True`; a `datetime` otherwise.
- `values_count` — int, the count from the key header (populated whether or
  not values were fetched).
- `values` — a list of value entries. Each value entry is itself a dict
  with keys `name`, `value`, `value_type`, `is_corrupted` when
  `as_json=True`; or a namespace-style object with those same attributes
  when `as_json=False`. Empty list when `fetch_values=False`.

When `fetch_values=False`, value parsing is skipped (`values` is the empty
list for every yielded entry) but `values_count` continues to reflect the
count from each key's header.

### `regipy.utils.convert_wintime(filetime, as_json=False)`

Converts an NT FILETIME integer to a timezone-aware UTC `datetime` (or to an
ISO-8601 string when `as_json=True`).

An NT FILETIME counts 100-nanosecond intervals, a finer resolution than a Python
`datetime` (1 microsecond). The conversion divides the FILETIME by 10 to obtain a
**floating-point** microsecond offset and adds it to the 1601-01-01 UTC epoch as a
`timedelta` (i.e. `datetime(1601, 1, 1, tzinfo=utc) + timedelta(microseconds=filetime / 10)`).
Because the division is floating-point, the sub-microsecond remainder is resolved to
the nearest representable microsecond — which is what `timedelta` produces — rather than
truncated toward zero. Use this floating-point division (not exact integer rounding):
at a sub-microsecond boundary the two can differ by one microsecond in the last digit,
and the float result is the contract. For example, FILETIME `132289273589554894`
serialises to `"2020-03-17T14:02:38.955490+00:00"`. This conversion applies once here, and
every timestamp derived from a FILETIME — the NDJSON / CSV-timeline dumps,
`recurse_subkeys` timestamps, and `regdiff` output — inherits it.

### Security descriptors: `NKRecord.get_security_key_info()`

Parses the associated `SK` (security key) record and returns a dict with the
keys `owner`, `group`, and `dacl`.

- `owner` and `group` are SID strings (e.g. `"S-1-5-18"`).
- `dacl` is a list of ACE (access-control-entry) dicts. Each ACE has at least
  these keys: `access_mask`, `ace_type`, `flags`, `sid`.
  - `access_mask` is a dict of named permission bits. Standard bit names
    include `DELETE`, `READ_CONTROL`, `WRITE_DAC`, `WRITE_OWNER`,
    `SYNCHRONIZE`, `ACCESS_SYSTEM_SECURITY`, `GENERIC_READ`,
    `GENERIC_WRITE`, `GENERIC_EXECUTE`, `GENERIC_ALL`,
    `MAXIMUM_ALLOWED`. Each maps to a boolean.
  - `ace_type` is a string such as `"ACCESS_ALLOWED"`.
  - `flags` is a dict of inheritance flags.
  - `sid` is the SID string.

### Transaction-log recovery: `regipy.recovery.apply_transaction_logs(hive_path, primary_log_path, secondary_log_path=None, restored_hive_path=None)`

Replays the supplied transaction log(s) onto a dirty hive and writes the
recovered hive to `restored_hive_path` (caller-supplied path). Returns a
two-tuple `(restored_hive_path, recovered_dirty_pages_count)` where the second
element is the integer number of dirty pages written from the log into the
recovered image.

The recovered-page count is a **cumulative total**: replaying a log applies
*every* dirty page carried by *every* log block it contains and adds one to the
count for each such page written. It is therefore an accumulated sum over all of
the log's blocks — not the number of distinct hive offsets touched, and not just
the pages from the last block. A real dirty log carries many pages, so a faithful
replay of a genuinely dirty hive recovers a substantial page total (in the low
hundreds), and the recovered image differs from the original hive at hundreds of
keys.

When both a primary and a secondary log are supplied, the two are combined by
replaying the **secondary log first** onto the original hive and then the
**primary log** onto that already-partially-recovered image; the returned count is
the **sum** of the pages applied from both logs. Combining the two logs this way
yields a recovered image that is again parseable as a normal hive of the original
type (so `RegistryHive(restored_hive_path)` succeeds and `compare_hives` against
the original hive reports the recovered subkeys and values).

### Hive diffing: `regipy.regdiff.compare_hives(first_hive_path, second_hive_path)`

Compares two hives end-to-end and returns a list of 4-tuples. Each tuple is
`(difference_type, first_hive_value, second_hive_value, description)`. The
difference-type tokens are exactly `"new_subkey"` (a subkey present in one
hive but missing in the other) and `"new_value"` (a value present in one but
missing in the other) — no other difference categories are emitted. The
comparison is **symmetric**: a subkey/value present in either hive but absent
from the other is reported (both "only in the first" and "only in the second"
differences appear in the result). The tuple's two value slots encode the
direction of each individual difference: for an item found only in the second
hive, the first-hive slot is `None` and the second-hive slot carries the item;
for an item found only in the first hive, the second-hive slot is `None` and
the first-hive slot carries it. For a `new_value` difference, the populated
value slot identifies the value by **name as well as data** (it renders the
value's name, its data, and the affected subkey's last-modified timestamp,
e.g. `"<value_name>: <value_data> @ <last_modified>"`); for a `new_subkey`
difference the populated slot carries the subkey's timestamp. The
`description` is the path of the affected key. Note that "new values" are only looked for under
subkeys that exist in **both** hives but whose `last_modified` timestamps
differ; a key present in only one hive is reported only as a `new_subkey`
record (its values are not separately enumerated as `new_value` records). A
value whose decoded data is empty — an empty string, an empty list, empty
binary data, or a numeric `0` — is skipped by the value comparison and counts
as not present under that key on that side, so a value that is empty in one
hive but populated in the other is reported as a `new_value`. The
subkey comparison is a set difference over the full subkey-path set, so when a
whole subtree exists on only one side, **every** key within it is reported as
its own `new_subkey` record (one record per node, not one record for the
subtree root). Keys whose contents and `last_modified` timestamps are
identical are NOT reported.

### Plugin system: `regipy.plugins.utils.run_relevant_plugins(registry_hive, as_json=False)`

Runs every registered plugin whose `COMPATIBLE_HIVE` matches the hive's type
and returns a dict mapping each plugin's `NAME` to its result structure. A
matching plugin is included in the returned dict under its `NAME` whenever it
runs successfully — **including when its output is empty** (e.g. the source key
it reads is absent or carries no entries on this particular hive). Do NOT drop a
matching plugin from the result just because its result structure is empty;
auto-dispatch is by `COMPATIBLE_HIVE` membership, not gated on output content.

Each plugin class defines class attributes `NAME` (str), `DESCRIPTION` (str),
and `COMPATIBLE_HIVE` (the hive-type string it applies to). These three are
exposed by `regipy-plugins-list` and drive auto-dispatch in
`run_relevant_plugins` and `regipy-plugins-run`.

Tests exercise the auto-discovery pipeline against NTUSER, SYSTEM, and
SOFTWARE hives, so the following plugin `NAME`s must be present in the catalog,
must be auto-dispatched on a hive of the matching type, and so must appear as
keys in the `run_relevant_plugins` result for that hive (their result structure
may be empty when the hive lacks the corresponding source key — see above):

- For an NTUSER hive: `ntuser_persistence`, `user_assist`, `typed_urls`,
  `typed_paths`, `installed_programs_ntuser`, `network_drives_plugin`,
  `word_wheel_query`.
- For a SYSTEM hive: `computer_name`, `services`.
- For a SOFTWARE hive: `winver_plugin` (Windows version info from
  `Microsoft\Windows NT\CurrentVersion`), `profilelist_plugin` (user
  profile entries from `Microsoft\Windows NT\CurrentVersion\ProfileList`),
  `installed_programs_software` (uninstall-key entries from
  `Microsoft\Windows\CurrentVersion\Uninstall`), `software_plugin`
  (top-level software catalogue summary), `uac_plugin` (UAC settings from
  `Microsoft\Windows\CurrentVersion\Policies\System`).

#### `ntuser_persistence`

Enumerates autorun-style keys under the user hive (the canonical example is
`Software\Microsoft\Windows\CurrentVersion\Run`). The plugin output, for each
detected autorun key, exposes the key path and its values list, where each
value dict carries at least `name`, `value`, and `value_type`. The
implementation may return either a list of `{key/path, timestamp, values}`
dicts or a dict keyed by path with the same shape.

#### `computer_name`

Walks each control set under the SYSTEM hive and returns one entry per
control set with the computer name and the last-modified timestamp of the
`ComputerName` subkey. The computer name appears under either the key
`computer_name` or `name` in the per-entry dict.

#### `winver_plugin`

Reports the Windows version info from `Microsoft\Windows NT\CurrentVersion`.
The output is a dict keyed by the (backslash-prefixed) registry key path
`\Microsoft\Windows NT\CurrentVersion`; that entry exposes the decoded
registry value names directly as keys — including `ProductName` and
`CurrentBuild`, each mapping to that registry value's decoded data as read
from the hive.

#### `profilelist_plugin`

Enumerates the user profile entries under
`Microsoft\Windows NT\CurrentVersion\ProfileList`. The output is a list of
per-profile dicts, each carrying at least the keys `sid` (the profile's SID
string) and `path` (the profile directory decoded from that profile's entry).

## Exceptions

- `RegistryKeyNotFoundException` — raised by `get_key()` when the path does
  not resolve. (`get_subkey()` does not raise this — it uses
  `NoRegistrySubkeysException` for every miss; see below.)
- `NoRegistrySubkeysException` — raised by `get_subkey()` for any unmatched
  child, both when the parent key's stored `subkey_count` is zero (a true leaf)
  and when the parent has children but none match the requested name.
- `UnidentifiedHiveException` — raised by `RegistryHive(...)` when
  auto-detection cannot match the root key against any rule above.

## Implementation notes

- Hive paths are backslash-separated. A leading backslash on absolute paths
  is optional and must be tolerated.
- The on-disk format is little-endian throughout; key/value names are
  Latin-1 (when the key-comp-name flag is set) or UTF-16-LE (otherwise),
  and UTF-16 names that include surrogate-pair characters (e.g. emoji)
  must round-trip through the API as Python strings.
- The dirty-page count returned from transaction-log replay is the integer
  number of dirty pages recovered from the supplied log(s) and written into
  the restored hive — a cumulative total of every page carried by every block of
  the log(s), not a count of distinct hive offsets (see the
  `apply_transaction_logs` contract above for the multi-log combine).
