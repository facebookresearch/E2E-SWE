# yamlpath

Build `yamlpath`, a Python library and suite of CLI tools for getting, setting, searching, merging, validating, and diffing YAML/JSON data using a powerful path expression language.

## Dependencies

The environment is **offline** — there is no network access, and every dependency is **already installed**. Do **not** install or upgrade anything. The runtime dependencies, already present, are:

- `ruamel.yaml` (version 0.19.1)
- `python-dateutil`

The project is installed from your source tree by a `setup.sh` that runs **offline** against the pre-installed dependencies.

## setup.sh

```bash
pip install -e . --no-build-isolation
```

## Console Scripts

Installing the package must register six console-script commands (executable entry points) with these exact names; each dispatches to the corresponding command documented below. The internal module and function each script is wired to is an implementation choice and is not otherwise constrained.

- `yaml-get`
- `yaml-set`
- `yaml-paths`
- `yaml-merge`
- `yaml-validate`
- `yaml-diff`

## Path Expression Syntax

Both **dot notation** (`hash.child.key`) and **forward-slash notation** (`/hash/child/key`) are supported interchangeably and compare equal.

### Addressing

| Syntax | Description |
|---|---|
| `key` | Hash key |
| `[N]` | Array element by 0-based index (negative indices supported) |
| `[start:stop]` | Array slice (exclusive stop) |
| `&anchor_name` | YAML anchor lookup |
| `'dotted.key'` or `"dotted.key"` | Quoted keys containing special characters |
| `\.` | Escape special characters |
| `*` | Wildcard — match all immediate children |
| `**` | Deep traversal — all descendants |

A path may contain at most one `**` deep-traversal segment. Repeating it (e.g. `root.**.**.leaf`) is an invalid expression and is rejected with a non-zero exit.

### Search Expressions (`[attr OP value]`)

| Operator | Meaning |
|---|---|
| `=` | Exact match |
| `^` | Starts with |
| `$` | Ends with |
| `%` | Contains |
| `>` | Greater than |
| `<` | Less than |
| `>=` | Greater than or equal |
| `<=` | Less than or equal |
| `=~` | Regex match (`=~/pattern/`) |
| `!` | Invert (`[attr!=value]`) |
| `.` | Match element values in arrays or key names in hashes (`[.=value]`) |

The bare comparison value undergoes the same YAML scalar type inference as the `default`-format `-a`/`--value` (see yaml-set): a bare `true`/`false` becomes a boolean, a bare integer/float becomes a number, `null`/`~` becomes null, and anything else stays a string. For `=`, the value matches a node only when both compare equal after inference — so `[flag=true]` matches a boolean node `flag: true` (not the text `"true"`), and `[count=5]` matches an integer node `count: 5`. For `>`/`<`/`>=`/`<=`, the comparison is numeric when the node's value is numeric (and the given value parses as a number); otherwise it is a lexical string comparison.

### Search Keywords (`[KEYWORD(PARAMS)]`)

| Keyword | Behavior |
|---|---|
| `has_child(NAME)` | Nodes having a named child key |
| `max([NAME])` | Node(s) with maximum value |
| `min([NAME])` | Node(s) with minimum value |
| `name()` | Match only the key name |
| `parent([STEPS])` | Step up N levels; STEPS defaults to 1 when omitted |
| `distinct(NAME)` | One of every value, discarding duplicates |
| `unique(NAME)` | Only values with no duplicates |

A leading `!` inverts a keyword search, mirroring how `!` inverts a comparison in `[attr!=value]`: `[!KEYWORD(PARAMS)]` matches the nodes the keyword search would NOT match. For example, `[!has_child(NAME)]` matches nodes that do NOT have the named child key.

### Collectors

Parentheses create virtual list collectors with operators: `+` (addition), `-` (subtraction), `&` (intersection). An operator joins two parenthesized collectors written side by side: it sits **between** the groups, not inside one — the surface form is `(A)+(B)`, not `(A + B)`. Each parenthesized group is itself a path that gathers a list (a whole array such as `(list_a)`, or specific indexed elements such as `(items[0])`). Given `list_a: [1, 2]` and `list_b: [3, 4]`, `(list_a)+(list_b)` yields the single virtual list `[1, 2, 3, 4]`; `(items[0])+(items[2])` gathers just those two elements. `-` removes elements of the right collector from the left by value; `&` keeps only elements present in both. Operators chain left to right, so `(a)+(b)-(c)` first adds `a` and `b`, then subtracts `c`.

A collector expression that evaluates to an empty list (e.g. an intersection with no common elements, or a subtraction that removes every element) is treated as a no-match and exits non-zero — it is not a successful empty-list result.

### Array-of-Hashes Pass-Through

Omitting a selector for array elements passes through all hashes: `users.name` yields every user's `name` from an array of user hashes.

## CLI Commands

All commands support noise control: `-d` (debug), `-v` (verbose), `-q` (quiet). File arguments accept `-` for STDIN.

### yaml-get

Retrieve values from YAML/JSON files at a YAML Path.

```
yaml-get -p YAML_PATH [YAML_FILE] [-t {dot,fslash,auto}] [--frontmatter] [-S]
```

- `-p`/`--query` — the path expression (required)
- `-t`/`--pathsep` — path separator mode
- `--frontmatter` — parse Markdown frontmatter
- `-S`/`--nostdin` — suppress STDIN reading

**Behaviors:**
- Complex results (dicts, lists) are output as JSON.
- When the path matches more than one node (e.g. a wildcard, deep traversal, array-of-hashes pass-through, or search on an array), each matched node is printed on its own line — one node per line. The JSON rendering above applies per matched node: a single matched scalar prints as a bare value, a single matched dict/list prints as one JSON document on its line. A collector expression instead yields a single virtual list, printed as one JSON array.
- An array slice `[start:stop]` selects a single list node (the chosen elements gathered into one list), so it prints as one JSON array on one line — not one element per line. For example, over a 5-element list `items`, `yaml-get -p 'items[1:3]'` prints `["b", "c"]`.
- When a `[name()]` or `[parent()]` search keyword is used as the **terminal** segment of the path, it re-targets the output to a different node than the leaf the path addresses:
  - `[name()]` yields the addressed node's own **key name** as a bare string, not its value.
  - `[parent()]` yields the resolved **ancestor node** reached by stepping up (see `parent([STEPS])` below), rendered per the normal scalar/dict/list rules.
- A YAML set (`!!set`) is emitted as a JSON object whose members become keys with `null` values, e.g. `{"java": null, "python": null}`.
- `None`/null values print as `\x00` (null byte character).
- Boolean values print as `true`/`false`.
- Date values print in ISO format (`YYYY-MM-DD`). Timestamps print in ISO format, preserving timezone offsets.
- Literal block scalars (`|`) have internal newlines replaced with literal `\n` in output. Folded block scalars (`>`) have lines joined with spaces.
- Raises error (non-zero exit) if path does not match any node.
- Exception: when the input document is empty (no data at all), produces no output and exits 0 — the no-match error applies only to non-empty documents.
- Reads from STDIN if no file argument provided (unless `-S`).

### yaml-set

Change, create, or delete values in YAML/JSON files.

```
yaml-set -g YAML_PATH [-a VALUE | -N | -D | -R LEN | -f FILE | -i | -A ANCHOR | -K ANCHOR] [YAML_FILE] [options]
```

- `-g`/`--change` — target path (required)
- `-a`/`--value` — literal value
- `-N`/`--null` — set to null
- `-D`/`--delete` — delete node(s); implies `--mustexist`
- `-R`/`--random` — random string of the given length. The generated value is stored and read back as a string scalar: it is exactly `LEN` characters long and is composed solely of characters from the pool.
- `-M`/`--random-from` — character pool for `--random`
- `-f`/`--file` — read value from file
- `-i`/`--stdin` — read value from STDIN
- `-A`/`--aliasof` — make target an alias of source anchor path; the source anchor path must resolve to an existing node — aliasing a source that matches no node fails with a non-zero exit
- `-K`/`--mergekey` — assign YAML Merge Key (`<<:`)
- `-H`/`--anchor` — name/rename anchor (with `-A` or `-K`)
- `-F`/`--format` — value format: `bare`, `boolean`, `default`, `dquote`, `float`, `folded`, `int`, `literal`, `squote`. The `default` format (used when `-F` is omitted) emits a `-a`/`--value` scalar using YAML's native type inference: a bare numeric like `99` round-trips as an integer, `1.5` as a float, `true`/`false` as a boolean, and `null`/`~` as null — only text that is not a recognized YAML scalar type stays a plain string. An explicitly-supplied empty value (`-a ''`) is stored and read back as an empty string, not coerced to null: null is produced only by the literal texts `null`/`~` (or by `-N`/`--null`). Use `-F squote`/`-F dquote` to force a quoted string, or `-F int`/`-F float`/`-F bare`/`-F boolean` to force the named type.
- `-c`/`--check` — verify old value matches before replacing (non-zero exit if mismatch). The supplied check value is taken as a raw string and the comparison is type-sensitive: it matches a stored string of the same text (so `port: "5432"` passes `-c 5432`) but not a stored value of a different YAML type with the same text (so a numeric `port: 5432` fails `-c 5432`).
- `-s`/`--saveto` — save old value to another path before change; implies `--mustexist`; works with exactly one matched node
- `-m`/`--mustexist` — require path already exists (non-zero exit if not)
- `-b`/`--backup` — create `.bak` backup file (only when changes are made)
- `-T`/`--tag` — assign a custom YAML tag (auto-prefixed with `!` if missing)
- `--frontmatter` — parse/modify Markdown frontmatter

**Behaviors:**
- Creates intermediate path nodes when path doesn't exist (unless `--mustexist`).
- `--delete` reverses deletion order for array indices.
- JSON files (`.json` extension) are written as JSON, not YAML.

### yaml-paths

Search for YAML Paths matching expressions.

```
yaml-paths -s EXPRESSION [YAML_FILE...] [-L] [-F] [-X] [-P] [-n] [-k|-K|-i] [options]
```

- `-s`/`--search` — search expression (repeatable)
- `--line LINE` — find paths at a 1-based source line number (repeatable)
- `-L`/`--values` — print each value alongside its path, joined as `<path>: <value>` (the path, a colon, a space, then the value), e.g. `scores[1].val: 50`
- `-F`/`--nofile` — omit filename decorators
- `-X`/`--noexpression` — omit expression decorators
- `-P`/`--noyamlpath` — omit paths
- `-k`/`--keynames` — search keys AND values
- `-K`/`--onlykeynames` — search keys ONLY
- `-i`/`--ignorekeynames` — search values only (default)
- `-c`/`--except` — exclude matching results (repeatable)
- `-m`/`--expand` — expand parent matches to leaves
- `-A`/`--anchorsonly` — like the default, exclude alias matches but keep all non-alias matches (both anchored originals and plain values); it does NOT restrict results to only anchored nodes
- `-l`/`--allowaliases` — include ALL aliases
- `-j`/`--json-multi-doc` — parse as NDJSON/JSONL

**Behaviors:**
- Results are deduplicated.
- A **value** search is evaluated only against scalar-leaf values; a composite hash/array node and the top-level document node are never reported as value matches — the search descends through them to their scalar leaves.
- A search that matches no paths produces no output and exits 0 (success); a zero-match result is not an error for yaml-paths (unlike yaml-get, which errors on a no-match against a non-empty document).
- By default, alias matches are excluded from results.
- When more than one search expression is given, each result line is prefixed with its matching expression as `[EXPRESSION]` (e.g. `[=findme]`); `-X`/`--noexpression` omits this prefix. With a single search expression, no expression prefix is emitted.
- Default output line format: each result is rendered as `<file_decorator>: <yaml_path>` (the file decorator, a colon, a space, then the path); `-F`/`--nofile` omits the file decorator. The file decorator is the source filename suffixed with the 0-based index of the matching source document as `<file>/<doc_index>` — so for a single-document file a match prints `<file>/0: <yaml_path>`, and for a multi-document or NDJSON/JSONL (`-j`) source a match in the second document prints `<file>/1: <yaml_path>`. With `-L`/`--values` the value follows the path as `: <value>`; combined with `-P`/`--noyamlpath` (which drops the path), the line becomes `<file>/<doc_index>: <value>`. The `<yaml_path>` itself renders in **dot notation** by default (e.g. `items[0].tags[2]`).

### yaml-merge

Merge two or more YAML/JSON documents.

```
yaml-merge YAML_FILE... [-o OUTPUT | -w FILE] [-b] [-S] [-c CONFIG]
           [-a {stop,left,right,rename}] [-A {all,left,right,unique}]
           [-H {deep,left,right}] [-O {all,deep,left,right,unique}]
           [-E {unique,left,right}] [-m YAML_PATH] [-D {auto,yaml,json}]
           [-M {condense_all,merge_across,matrix_merge}] [-l]
```

- `-o`/`--output` — write to new file (must not already exist)
- `-w`/`--overwrite` — overwrite existing file
- `-b`/`--backup` — backup overwrite target as `.bak`
- `-S`/`--nostdin` — suppress implicit STDIN reading
- `-c`/`--config` — INI config file with `[defaults]`, `[rules]`, `[keys]` sections
- `-a`/`--anchors` — anchor conflict resolution when both sides define an anchor with the same name: `stop` (default, error), `left`, `right`, `rename`
- `-A`/`--arrays` — array merge mode: `all` (default), `left`, `right`, `unique`
- `-H`/`--hashes` — hash merge mode: `deep` (default), `left`, `right`
- `-O`/`--aoh` — array-of-hashes merge mode: `all` (default), `deep`, `left`, `right`, `unique`
- `-E`/`--sets` — set merge mode: `unique` (default), `left`, `right`
- `-m`/`--mergeat` — path at which to merge RHS into LHS (default: `/`, root)
- `-D`/`--document-format` — force the **output** document format: `yaml`, `json`, or `auto`
- `-M`/`--multi-doc-mode` — `condense_all` (default), `merge_across`, `matrix_merge`
- `-l`/`--preserve-lhs-comments` — preserve LHS comments in the merged output. A comment attached to an LHS key (including a standalone/leading top-of-file comment) that is retained through the merge survives verbatim in the output; without this flag such comments are dropped.

**Behaviors:**
- Deep hash merge: LHS keys kept, RHS keys added, shared keys use RHS value recursively.
- Array `all`: concatenate. `unique`: deduplicate. `left`/`right`: keep only that side.
- AoH `deep`: match by identity key and merge matched hashes; unmatched items appended. When no `[keys]` config supplies a key, the identity key defaults to the first key of each record.
- Anchor conflict (`-a`): when both sides define an anchor with the same name, `left`/`right` keep the chosen side's anchored mapping body and re-point the other side's occurrence of that name at it, so both nodes read back the chosen side's value (e.g. with `left`, an RHS node whose anchor name clashes with an LHS anchor reads back the LHS value). `rename` keeps both bodies by renaming the colliding anchor; `stop` (default) errors.
- Config `[defaults]` section: keys map to the long flag names — `anchors`, `arrays`, `hashes`, `aoh`, `sets` — each taking that flag's mode vocabulary, and set the default merge mode (e.g. `hashes = left` makes the default hash mode `left`).
- Config `[rules]` section: each entry maps a YAML Path to a per-path merge mode (`left`, `right`, or `deep`) that overrides the global mode for the node at that path, using the same mode vocabulary as the `--hashes`/`--arrays`/`--aoh` flags. For example, with `items = left` the `items` node keeps the LHS value while `config = right` makes the `config` node take the RHS value.
- Multi-doc modes (`-M`): `condense_all` (default) flattens all subdocuments of each side into one before merging; `merge_across` merges subdocuments pairwise by index; `matrix_merge` merges every RHS subdocument into every LHS subdocument.
- Document format (`-D`): selects the format the merged result is **serialized/written** in only — `json` writes JSON, `yaml` writes YAML, `auto` (default) infers from the output filename extension (per the `.json` rule in yaml-set). It does **not** change how input files are parsed: inputs are always auto-detected (YAML, a superset of JSON) by their own content, so `-D json` given YAML inputs is valid and simply writes the merged result as JSON.

### yaml-validate

Validate YAML/JSON file structure.

```
yaml-validate YAML_FILE... [-S] [--frontmatter] [-j]
```

- Exit 0 on valid, non-zero on invalid.
- Validates each subdocument in multi-document files independently.

### yaml-diff

Calculate functional differences between two YAML/JSON documents.

```
yaml-diff YAML_FILE YAML_FILE [-s] [-o] [-A {position,value}] [-O {position,deep,dpos,key,value}]
          [-c CONFIG] [-L N] [-R N] [-t {dot,fslash,auto}]
```

- `-s`/`--same` — show identical nodes too
- `-o`/`--onlysame` — show ONLY identical nodes (exit 1 if differences exist)
- `-A`/`--arrays` — array diff mode: `position` (default), `value`
- `-O`/`--aoh` — AoH diff mode: `position` (default), `deep`, `dpos`, `key`, `value`
- `-c`/`--config` — INI config file
- `-L`/`-R` — select subdocument index from multi-doc source
- `-t`/`--pathsep` — path separator for output

**Behaviors:**
- Exit 0 if identical, exit 1 if differences found.
- Output is diff-like: each reported node is a line `<marker> <yaml_path>` where the leading marker is `a` (added, present only in RHS), `d` (deleted, present only in LHS), `c` (changed value), or `s` (same/unchanged). A changed scalar emits a single `c <path>` line; `-s`/`--same` additionally emits `s <path>` lines for unchanged nodes and `-o`/`--onlysame` emits only those.
- Array `value` mode: order-insensitive comparison. `position` mode: element-by-element.
- Type changes (e.g. scalar to hash, hash to array) are reported as DELETE of the old node + ADD of the new node, not CHANGE. Both sides are enumerated at leaf/element granularity: a scalar node is reported at its own path, while a **composite** node (hash or array) is descended into and reported one line per leaf — a hash by child key (`<path>.<child>`) and an array by index (`<path>[N]`). This applies symmetrically to the deleted old node and the added new node.
- AoH (`-O`) modes differ in how they pair records and at what granularity they report a changed record. `key` and `dpos` pair records across the two documents by an identity key — defaulting to the **first key** of each record (the same identity-key default as yaml-merge), or a `[keys]`-configured key — so reordered records are matched by identity rather than position; a record that changed is reported as a single whole-record change line at its **LHS index path** (e.g. `c users[1]`), not descended into per field. `deep` instead pairs records by identity key and then descends into the matched records, reporting field-level change lines (e.g. `c users[0].role`). `position` compares records element-by-element at the same index, and `value` is order-insensitive.
- Output paths render in **dot notation** by default (e.g. `config.database.host`, `users[0].role`, and a top-level node as bare `b`); use `-t`/`--pathsep` to select `fslash` or `auto`.
- Config `[rules]` per-path entries use the diff mode vocabulary (arrays: `position`/`value`; AoH: `position`/`deep`/`dpos`/`key`/`value`), mirroring the per-path-rules pattern of yaml-merge.
