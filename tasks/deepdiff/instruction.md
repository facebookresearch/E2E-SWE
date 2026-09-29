# deepdiff — Deep Object Comparison, Diffing, and Patching

Implement **deepdiff**, a Python library for deep comparison of Python objects.

## Dependencies

The environment is **offline** and all dependencies are **already installed** — do not install
anything (there is no network). The project is installed for you by a `setup.sh` that runs offline
(`pip install -e . --no-build-isolation`).

The only runtime dependency is:

- `orderly-set>=5.4.1,<6`

## Package Structure

```python
from deepdiff import DeepDiff, DeepHash, DeepSearch, Delta, extract, grep, parse_path
```

The package also exposes a `CannotCompare` exception used with `iterable_compare_func` (see below).

## 1. DeepDiff — `DeepDiff(t1, t2, **kwargs)`

Compares two objects. Returns a dict-like result containing all differences.

**Parameters:**
- `t1`, `t2` — objects to compare
- `ignore_order` (bool, default `False`) — ignore iterable order
- `ignore_order_func` (callable, default `None`) — function `f(level)` returning `True` to ignore order for that path. When set, `ignore_order` is applied selectively per path instead of globally. `level` is a string representation of the current comparison path.
- `iterable_compare_func` (callable, default `None`) — function `f(x, y)` to guide item pairing in iterables when `ignore_order=True`. Return `True` if items match, `False` if not. Raise `CannotCompare` (from `deepdiff.helper`) if unable to decide (falls back to default matching).
- `report_repetition` (bool, default `False`) — report repetition changes
- `max_passes` (int, default `10000000`) — maximum matching passes for `ignore_order`. A pass is counted per *iterable-vs-iterable* comparison (i.e. each time two iterables are matched by comparing every differing item in one against every differing item in the other), **not** per individual item-to-item comparison inside that match. The comparison of the two top-level operands is always the first pass, so it runs for any `max_passes >= 1`: the outermost pairing is attempted and any resulting top-level change is reported — including a paired-item inner value change surfaced as `values_changed` when the pair falls within `cutoff_intersection_for_pairs`. Reducing `max_passes` removes granularity from the **deepest** (most-nested) reordered iterables first and never suppresses a top-level change into a wholesale add/remove for any cap `>= 1`; once the budget is exhausted, deeper reordered iterables degrade to wholesale `iterable_item_added` / `iterable_item_removed`.
- `max_diffs` (int, default `None`) — caps the total number of individual item-level differences recorded under `ignore_order`. `None` means unlimited. Every reported change counts toward the limit — each `values_changed` entry as well as each wholesale `iterable_item_added` / `iterable_item_removed` of an unmatched item (not only deep comparisons of paired items). Once the cap is reached the diff stops recording further changes, so a small `max_diffs` yields a strictly less granular result (fewer total reported changes) than the unlimited diff — including for fully-disjoint iterables whose diff consists solely of additions and removals.
- `cache_size` (int >= 0, default `0`) — cache size to improve performance for nested objects. `0` disables caching. Larger values trade memory for speed on deeply nested structures.
- `cutoff_intersection_for_pairs` (float in [0, 1], default `0.7`) — under `ignore_order`, a *distance* threshold deciding whether two iterables (or dicts) are paired and diffed item-by-item rather than reported as a wholesale add/remove. The engine measures the distance between the two candidates (0 = identical, 1 = completely different). If that distance is **below** the cutoff they are paired and diffed deeper (their inner changes are reported); if it is **at or above** the cutoff they are reported only as wholesale add/remove. So **higher** values pair more aggressively: at `cutoff=1` any two candidates that are not 100% different are still paired and diffed deeper, even when they share only part of their content (e.g. two dicts that share one of two keys are paired, so a change to the differing key is reported as a deep `values_changed` rather than a wholesale replacement).
- `threshold_to_diff_deeper` (float in [0, 1], default `0.33`) — under `ignore_order`, the minimum relative difference at which two paired iterables are diffed deeper instead of reported as a single change. `0` always diffs deeper.
- `significant_digits` (int) — number of digits used for numeric comparison. Meaning depends on `number_format_notation`.
- `number_format_notation` (str, default `"f"`) — `"f"` (fixed point): `significant_digits` means digits after the decimal point. `"e"` (scientific notation): `significant_digits` means digits in scientific notation. E.g., with `significant_digits=2, number_format_notation="e"`, numbers `1234567` and `1234568` are equal (both `1.23e+06`), but with `"f"` they differ.
- `math_epsilon` (float) — use `math.isclose` with this tolerance
- `ignore_string_type_changes` (bool, default `False`) — treat str/bytes as same type
- `ignore_numeric_type_changes` (bool, default `False`) — treat int/float/Decimal as same type. Does **not** include `bool`: `bool` is always distinct from `int`.
- `ignore_string_case` (bool, default `False`) — case-insensitive string comparison
- `ignore_nan_inequality` (bool, default `False`) — treat NaN == NaN
- `ignore_private_variables` (bool, default `True`) — skip attributes starting and ending with `__`. Set `False` to include them.
- `exclude_paths` (set/list) — paths to exclude
- `include_paths` (set/list) — only compare these paths
- `exclude_types` (list) — types to exclude
- `exclude_regex_paths` (set/list) — regex patterns; paths matching via `re.search` are skipped
- `exclude_obj_callback` (callable) — function `f(obj, path)` returning `True` to exclude that object from comparison. Called for each value encountered during traversal.
- `include_obj_callback` (callable) — function `f(obj, path)` returning `True` to include. Called for each value encountered during traversal; only values for which it returns `True` are compared. It filters which values are reported, not which are descended into: the root object is always traversed, and a non-matching container (dict/list/object) is still recursed into so that matching descendant values are still compared and reported. E.g. with a callback that returns `True` only for `str`, comparing two dicts reports the changed `str` leaf values while non-`str` leaves are excluded.
- `number_to_string_func` (callable) — custom function to convert numbers to strings for comparison. Signature: `f(number, *args, **kwargs)` → `str`. Numbers that produce the same string are treated as equal.
- `truncate_datetime` (str) — `"second"`, `"minute"`, `"hour"`, or `"day"`
- `verbose_level` (int, default `1`) — 2 includes values for added/removed items
- `view` (str, default `"text"`) — `"text"` or `"tree"`
- `group_by` (str, default `None`) — when comparing two lists of dicts, group items by this key for comparison instead of by index. Items with the same key value are paired and compared.
- `ignore_type_in_groups` (list of tuples, default `None`) — treat types within each group as interchangeable. E.g., `[(int, float)]` treats int and float as the same type; `[(list, tuple)]` treats lists and tuples as interchangeable.
- `get_deep_distance` (bool, default `False`) — when True, the result includes a `"deep_distance"` key: a float in [0, 1] measuring how different the two objects are. Identical objects give `0`; the value grows monotonically as the objects diverge (a larger change yields a larger distance) and approaches (but never exceeds) `1` for completely different objects.

### Result Keys

| Key | Description |
|---|---|
| `"values_changed"` | `{path: {"old_value": ..., "new_value": ...}}`. Multi-line strings also include a `"diff"` key with a unified diff string. |
| `"type_changes"` | `{path: {"old_type": type, "new_type": type, "old_value": ..., "new_value": ...}}` |
| `"dictionary_item_added"` | Paths of added dict keys (`set` at verbose_level≤1, `dict` at verbose_level=2) |
| `"dictionary_item_removed"` | Paths of removed dict keys |
| `"iterable_item_added"` | `{path: value}` |
| `"iterable_item_removed"` | `{path: value}` |
| `"set_item_added"` | `set` of path strings |
| `"set_item_removed"` | `set` of path strings |
| `"attribute_added"` / `"attribute_removed"` | Added/removed object attributes |
| `"repetition_change"` | Repetition count changes (with `report_repetition`) |

**Path format:** `root['key']` for dict keys, `root[0]` for indices, `root.attr` for attributes, `root[repr(item)]` for set items.

### Result Methods

- `to_json(**kwargs)` — JSON string
- `to_dict()` — plain dict
- `pretty()` — human-readable string. Each change is rendered as a sentence that refers to the
  changed location using the standard `root[...]` path notation (e.g. `Value of root['a'] changed
  from 1 to 2.`), so the documented path strings appear in the output.
- `affected_paths` — property: set of all changed paths
- `affected_root_keys` — property: set of root-level keys with changes

### Tree View

With `view='tree'`, values are iterables of `DiffLevel` objects:
- `.t1`, `.t2` — the two values, following the same old→new convention as the text view: for a
  changed / type-changed level `.t1` is the old value and `.t2` the new one; for an *added*
  category (`dictionary_item_added`, `iterable_item_added`, `attribute_added`) `.t1` is absent
  (the item did not exist in `t1`) and `.t2` is the added value; for a *removed* category `.t1`
  is the removed value and `.t2` is absent. These underlying values are always present on the
  level regardless of the text-view `verbose_level` — a tree-view added/removed level exposes the
  value on `.t2`/`.t1` even at the default `verbose_level=1`, where the text view renders the same
  categories as value-less sets of paths (see the Result Keys table).
- `.path()` — path string
- `.report_type` — change type string
- `.up`, `.down` — parent/child levels

## 2. Delta — `Delta(diff=None, **kwargs)`

Creates a patch from a diff. Applied via operator overloading.

**Parameters:** `diff` (DeepDiff result, dict, or bytes), `bidirectional`, `mutate`, `raise_errors`, `force`, `log_errors`, `serializer`/`deserializer`.

**Application:**
- `t1 + delta` or `delta + t1` → forward (returns t2)
- `t2 - delta` → reverse (requires `bidirectional=True`, returns t1)

Forward application of a Delta built from any DeepDiff result fully reconstructs `t2`:
`t1 + Delta(DeepDiff(t1, t2)) == t2` (and likewise through `.dumps()`/`Delta(bytes)`).

**Serialization:**
- `delta.dumps()` → bytes (pickle), `Delta(bytes)` → restore
- `delta.to_dict()` → raw diff dictionary
- `delta.to_flat_dicts()` → list of flat dict representations, one per change. Each carries (at
  least) `action`, `path`, and `value` keys: `action` is the name of the DeepDiff result key the
  change came from (e.g. `"values_changed"`, `"dictionary_item_added"`, `"iterable_item_added"`,
  `"type_changes"`); `path` is the element-decomposition list of the change (the same list
  `parse_path` returns, e.g. `["b"]` for `root['b']`); `value` is the new value.
- `delta.to_flat_rows()` → the same changes as flat row objects exposing `.action`, `.path`, and
  `.value` attributes (same meanings as the flat-dict keys above).

Handles immutable types (tuples, frozensets) at any nesting depth by converting to mutable equivalents, applying changes, then converting back.

## 3. DeepHash — `DeepHash(obj, **kwargs)`

Content-based hashing. Returns a dict-like mapping from objects to hash strings.

**Parameters:** `hasher` (default `sha256hex`), `ignore_iterable_order` (default `True`), `ignore_repetition` (default `True`), `apply_hash` (bool, default `True` — set `False` to get the raw unhashed content string instead of the hex digest), `significant_digits`, `ignore_string_type_changes`, `ignore_numeric_type_changes`, `ignore_string_case`, `exclude_paths`, `exclude_types`, `truncate_datetime`.

**Access:** `result[obj]` for top-level hash, `result[sub_obj]` for any sub-object encountered
during hashing. Indexing is **content-based**, not identity-based: `result[obj]` returns the hash
for any object equal in content to one that was hashed, not only the exact instance passed in — e.g.
`DeepHash({"a": 1})[{"a": 1}]` succeeds with a distinct but content-equal dict.

**Class methods:** `DeepHash.sha256hex(data)`, `DeepHash.sha1hex(data)`.

## 4. DeepSearch and grep — `DeepSearch(obj, item, **kwargs)`

Searches for an item within a nested object.

**Parameters:** `verbose_level` (1=paths, 2=paths+values), `case_sensitive` (default `False`), `match_string` (default `False` — `False` means substring match, `True` means exact match), `use_regexp` (default `False`), `exclude_paths`, `exclude_regex_paths`, `exclude_types`.

**Result keys:** `"matched_values"`, `"matched_paths"`. Routing: a hit where the search term
appears in an object's **value** is recorded under `"matched_values"` (mapping path → matched
value at `verbose_level=2`); a hit where the search term matches a **dictionary key name** is
recorded under `"matched_paths"`, where the recorded path is the full path to and including the
matched key (e.g. `root['b']['target_key']` for a hit on key `target_key` under `b`).

**grep:** `obj | grep("term", **kwargs)` — equivalent to `DeepSearch(obj, "term", **kwargs)`.

## 5. Path Utilities

- `extract(obj, path)` — navigate into an object by path string. Supports `['key']`, `[index]`, and `.attr` access.
- `parse_path(path, include_actions=False)` — parse path into elements. With `include_actions=True`, returns `[{"element": ..., "action": "GET"|"GETATTR"}, ...]`.

## 6. Custom Operators

Custom operators allow overriding comparison for specific types or paths. Subclass `deepdiff.operator.BaseOperator`:

```python
from deepdiff.operator import BaseOperator

class MyOperator(BaseOperator):
    def give_up_diffing(self, level, diff_instance):
        # Return True to skip comparison for this item
        return True
```

Pass to DeepDiff via `custom_operators=[MyOperator(types=[SomeType])]` or `MyOperator(regex_paths=[r"pattern"])`. The operator's `give_up_diffing` is called for matching types/paths. Return `True` to skip, `False` to proceed with normal comparison.

## 7. Custom Objects

DeepDiff compares custom objects via `__dict__`. Changes appear as `values_changed`, `attribute_added`, or `attribute_removed` with `.attr` paths.