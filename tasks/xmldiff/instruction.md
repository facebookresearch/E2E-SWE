# xmldiff: a tree-structured diff and patch tool for XML

Build a Python library that computes the difference between two XML documents as
a **tree edit script** — an ordered list of structural actions that transforms a
*left* XML tree into a *right* XML tree — and that can apply such an edit script
back to a tree (patching). The library is built on `lxml`.

The package must be importable as `xmldiff`. These import paths must resolve
exactly:

```python
from xmldiff import main, actions, formatting, patch, utils
from xmldiff.diff import Differ
```

Organise the internal module layout however you like, as long as those names
resolve. Two console scripts must also be installed: `xmldiff` and `xmlpatch`
(see §7).

## Dependencies

The single runtime dependency is `lxml`. **It is already installed in the
environment, which is fully offline — do not install anything.** All XML parsing
and serialization go through `lxml.etree`. No system services or network access
are available at run time. Your project is installed by a `setup.sh` that runs
offline (an editable install against the pre-installed dependencies); just make
the package importable as described below.

---

## 1. The edit-script vocabulary (`xmldiff.actions`)

An edit script is a Python `list` of **action** objects. Each action type is a
`collections.namedtuple` with exactly these names and fields (field order
matters — they are compared by value):

```
DeleteNode(node)
InsertNode(target, tag, position)
RenameNode(node, tag)
MoveNode(node, target, position)
UpdateTextIn(node, text, oldtext=None)
UpdateTextAfter(node, text, oldtext=None)
UpdateAttrib(node, name, value)
DeleteAttrib(node, name)
InsertAttrib(node, name, value)
RenameAttrib(node, oldname, newname)
InsertComment(target, position, text)
InsertNamespace(prefix, uri)
DeleteNamespace(prefix)
```

`node`, `target` are **xpath strings** locating a node in the *left* tree (see
§4). `position` is an integer child index. `UpdateTextIn`/`UpdateTextAfter` carry
both the new `text` and the previous `oldtext` (defaulting to `None`).

Because these are namedtuples, two edit scripts are equal when their actions are
equal element-by-element, so the exact action **types, field values, and list
order** are all part of the contract.

---

## 2. Computing a diff (`xmldiff.main`, `xmldiff.diff.Differ`)

`main.diff_texts(left, right, diff_options=None, formatter=None)` takes two
Unicode strings of XML and returns the edit script (a list of §1 actions) when
`formatter is None`, or the formatter's rendered output otherwise.
`main.diff_files(left, right, ...)` is the same but each argument is a filename or
open stream parsed with `etree.parse`. `main.diff_trees(left, right, ...)` takes
two parsed `lxml` elements / element-trees.

`diff.Differ(F=None, uniqueattrs=None, ratio_mode="fast", fast_match=False,
best_match=False, ignored_attrs=[])` is the engine. If `F is None`, use the default
threshold `0.5`. If `uniqueattrs is None`, use the default unique attribute list
`["{http://www.w3.org/XML/1998/namespace}id"]`. `diff_options` is a dict of these
same keyword arguments.

The diff is produced by **matching** nodes between the two trees by similarity,
then emitting the actions that turn the matched left tree into the right tree.
The algorithm is deterministic: the same inputs always yield the same edit
script, in the same order.

### Matching and similarity

Two nodes are considered a match when their similarity is at least the threshold
`F` (default `0.5`). Similarity combines how alike the nodes themselves are with
how alike their already-matched children are.

**Node self-similarity** is a `difflib.SequenceMatcher` ratio measuring how alike
two nodes are on their own, based on their tag, their text content, and their
(non-ignored) attribute names and values; `ignored_attrs` do not contribute. Each
node is first reduced to a **single flat character string** by concatenating its
tag, its text content, and its non-ignored attribute name/value pairs (in
sorted-name order), and the ratio is `SequenceMatcher` run **character-wise** over
those two strings — *not* over a list of field tokens and with no field-label
boilerplate (e.g. no `"tag="`/`"text="` prefixes). A component that is absent
contributes nothing at all rather than an empty placeholder, so an element with no
text and no attributes reduces to its tag alone. An element's namespace URI is part
of its identity here, so adding or removing a namespace changes the element enough
that it is generally treated as a different node (delete + insert) rather than a
rename. A comment's self-similarity is based on its text. `ratio_mode` selects
which SequenceMatcher ratio is used: `"accurate"` (exact `ratio`), `"fast"`
(`quick_ratio`, the default), or `"faster"` (`real_quick_ratio`).

**Combining with children.** If neither node has element children, the node's
similarity is just its self-similarity. Otherwise the node's similarity blends its
self-similarity with a child-similarity term — the fraction of its children
already matched to children on the other side, relative to the larger of the two
child counts — so that a node sharing more matched children scores as more
similar. Matching proceeds bottom-up (post-order), so children are matched before
their parents.

`fast_match` and `best_match` are alternative, mutually-exclusive matching
strategies that trade accuracy for speed / minimality but must still produce a
valid edit script.

`uniqueattrs` is a list of attributes (or `(tag, attribute)` pairs) that uniquely
identify a node: if either node carries such an attribute, the two nodes match
iff that attribute's value is identical, ignoring all other similarity. It
defaults to `["{http://www.w3.org/XML/1998/namespace}id"]` (i.e. `xml:id`).
`ignored_attrs` lists attributes excluded from both similarity and the emitted
attribute actions.

### Behaviour that is pinned exactly

The following observable rules are part of the contract:

- **Attribute actions are emitted in a canonical, sorted order**: first
  `UpdateAttrib` for changed common attributes (sorted by name), then
  `RenameAttrib` for any removed attribute whose value reappears under a new name
  (a removed/added pair with equal value becomes a single rename, processed in
  sorted order of the old name), then `InsertAttrib` for genuinely new attributes
  (sorted by name), then `DeleteAttrib` for genuinely removed attributes (sorted
  by name). Attribute names are the lxml fully-qualified `{ns}local` form.
- A node whose tag changed but which is otherwise matched yields `RenameNode`,
  not a delete + insert.
- A matched node that ends up under a different parent yields `MoveNode`.
- Re-ordered (but otherwise matched) siblings are realigned with the minimum set
  of `MoveNode` actions; siblings already in the right relative order are left
  alone.
- Text content uses `UpdateTextIn` for an element's `.text` and `UpdateTextAfter`
  for its `.tail`.
- Namespace declarations added on the right yield `InsertNamespace`; those only
  on the left yield `DeleteNamespace`. These are emitted **before** the structural
  actions. Because an element's namespace URI is part of its identity (see
  *Matching and similarity*), adding or removing a namespace lowers similarity: an
  element whose namespace differs is generally **not** matched to the
  differently-qualified element and is emitted as a delete + insert (a new node),
  **not** a `RenameNode`.
- An XML comment present only on the right yields `InsertComment`; comments are
  matched to each other by their text similarity (so a changed comment becomes an
  `UpdateTextIn` on the comment node, not delete + insert).
- Diffing a document against itself yields an empty list.

For two trees with several similar candidate children, which left node is paired
with which right node — and therefore the exact moves, renames, updates, inserts
and deletes that result — is determined entirely by the similarity computation
above. Reproduce it so that the emitted edit script matches exactly.

---

## 3. Patching (`xmldiff.patch`, `xmldiff.main`)

`patch.Patcher().patch(actions, tree)` applies an edit script (a list of §1
actions) to an `lxml` tree and returns the resulting tree. It must not mutate the
input tree. Applying the edit script produced by diffing *left* against *right*
to *left* must reproduce *right* (round-trip).

`main.patch_text(actions, xml)` takes a **string** edit script (in the
DiffFormatter text format, §5) and a string of XML, applies it, and returns the
patched XML as a Unicode string. `main.patch_file(actions, xml,
diff_encoding=None)` is the file/stream analogue.

`patch.DiffParser().parse(text)` parses the DiffFormatter text format (§5) back
into a list of §1 actions — the exact inverse of how `DiffFormatter` renders
them. (When parsing, the `oldtext` of text updates is not reconstructed.)

---

## 4. XPath conventions (`xmldiff.utils`)

Action `node`/`target` xpaths are produced by `utils.getpath(element, tree=None)`.
The rule is exactly: take lxml's own `tree.getpath(element)` and then, **only if
that string does not already end with `]`, append a single `[1]`**. Nothing else
is changed — intermediate path steps keep whatever lxml emits (lxml omits the
`[n]` predicate on a step that is unambiguous among its siblings). So:

- the path of an element pathed as the terminal step gains a trailing `[1]` when
  it had none: a root `<r>` is `/r[1]`;
- but an *intermediate* step that lxml left bare stays bare. For
  `<document><p/><p/></document>` the children are `/document/p[1]` and
  `/document/p[2]` — **not** `/document[1]/p[1]` (lxml does not index the unique
  `document` step, and `getpath` only ever touches the final character);
- for `<r><a/><a/></r>`, `utils.getpath(root)` is `/r[1]` but
  `utils.getpath(first_a)` is `/r/a[1]` and the second is `/r/a[2]`;
- a deeply nested unique chain `<a><b><c/></b></a>` gives `/a/b/c[1]` for the
  `<c>` (only the final step is suffixed);
- a comment is `/r/comment()[1]`, and a namespaced child uses its prefix, e.g.
  `/doc/x:p[1]`.

In short: append `[1]` to lxml's path string when and only when it does not
already end in `]`; do **not** re-index any earlier step.

---

## 5. Formatters (`xmldiff.formatting`)

`main.diff_texts(..., formatter=<formatter instance>)` renders the edit script
instead of returning it. Three formatters exist, keyed in `main.FORMATTERS` as
`"diff"`, `"xml"`, and `"old"`.

### `DiffFormatter` (`"diff"`) — the default CLI output

Renders the edit script as one action per line. Each line is
`[<name>, <param>, <param>, ...]`. The action name is the lower-cased,
hyphen-joined form of the action type, with these exact spellings:

```
DeleteNode      -> delete
InsertNode      -> insert
RenameNode      -> rename
MoveNode        -> move
UpdateTextIn    -> update-text
UpdateTextAfter -> update-text-after
UpdateAttrib    -> update-attribute
DeleteAttrib    -> delete-attribute
InsertAttrib    -> insert-attribute
RenameAttrib    -> rename-attribute
InsertComment   -> insert-comment
InsertNamespace -> insert-namespace
DeleteNamespace -> delete-namespace
```

xpaths, tags, attribute names and namespace prefixes/uris are rendered bare.
**Text values and attribute values are rendered as JSON** (so a string is
double-quoted, and a `None` becomes `null`). `update-text`/`update-text-after`
render both the new text and the old text as JSON. Positions and indices render
as bare integers. Worked examples (each is the full rendered string):

```
[update-text, /document/p[1], "Tokst", "Text"]
[insert, /document[1], p, 1]
[delete, /document/b[1]]
[rename, /document/p[1], h1]
[move, /a/b/c[1], /a/d[1], 0]
[update-attribute, /doc[1], id, "2"]
[insert-attribute, /node[1], c, "3"]
[delete-attribute, /node[1], b]
[rename-attribute, /node[1], a, b]
[update-text-after, /doc/a[1], "tail2", "tail1"]
```

A multi-action script is these lines joined by `\n`. `DiffParser` (§3) parses
exactly this grammar back to actions.

### `XMLFormatter` (`"xml"`)

`XMLFormatter` renders an *annotated copy of the left document* in which every
change is marked up in place using elements and attributes in the diff namespace
`http://namespaces.shoobx.com/diff` (conventional prefix `diff`, declared on the
root). The annotation vocabulary is:

- **Changed text** (`UpdateTextIn`/`UpdateTextAfter`) is rendered as a character
  diff: removed runs are wrapped in a `<diff:delete>` element and added runs in a
  `<diff:insert>` element, with unchanged text left bare. For example, diffing
  `<doc><p>old text here</p></doc>` against `<doc><p>new text here</p></doc>`
  produces a `<p>` containing
  `<diff:delete>old</diff:delete><diff:insert>new</diff:insert> text here`. (When
  `use_replace` is set, a single replaced run is instead wrapped in one
  `<diff:replace old-text="<old>">…</diff:replace>` element carrying the old text in
  an `old-text` attribute, rather than a separate delete + insert pair.)
- **Inserted node** (`InsertNode`): the new element is added in place carrying an
  empty `diff:insert=""` attribute. **Deleted node** (`DeleteNode`): the element is
  kept in place carrying an empty `diff:delete=""` attribute. **Moved node**
  (`MoveNode`): the original keeps a `diff:delete=""` marker and a copy is inserted
  at the destination with a `diff:insert=""` marker. **Renamed node**
  (`RenameNode`): the element is given the new tag plus a `diff:rename="<old-tag>"`
  attribute.
- **Attribute changes** are marked with extra attributes on the same element, whose
  *values accumulate* (multiple changes on one element join with `;`):
  `diff:add-attr="<name>"` for an inserted attribute, `diff:delete-attr="<name>"`
  for a removed one, `diff:update-attr="<name>:<old-value>"` for a changed one (the
  attribute itself holds the new value), and `diff:rename-attr="<old>:<new>"` for a
  rename.
- Comments are **dropped** by this formatter (it strips all comments before
  diffing), so `InsertComment` produces no markup.
- Namespace declarations are reconciled on the result tree but not otherwise
  visibly annotated.

Options: `normalize` controls whitespace handling (`WS_NONE=0` keep all —
the `XMLFormatter` default; `WS_TAGS=1` drop ignorable whitespace between tags;
`WS_TEXT=2` collapse whitespace inside text; `WS_BOTH=3` both); `pretty_print`
(default `True`) selects readable (indented) vs compact single-line output; and
`use_replace` (default `False`) switches text changes to the single
`<diff:replace>` form described above.

### `XmlDiffFormatter` (`"old"`)

`XmlDiffFormatter` renders the older line-based "`[update, <xpath>, ...]`" format;
e.g. the text change above renders as `[update, /doc/p[1]/text()[1], "Tokst"]`.

---

## 6. Diff options recap

`diff_options` (and the corresponding `Differ` kwargs) accepted by the API:
`F` (similarity threshold in `(0, 1]`), `uniqueattrs`, `ratio_mode`
(`"accurate"`/`"fast"`/`"faster"`), `fast_match` (bool), `best_match` (bool),
`ignored_attrs` (list of attribute names).

---

## 7. Command-line tools

Installed as two console scripts.

### `xmldiff file1 file2 [options]`

Prints the diff of two XML files. Options:

- `-f` / `--formatter {diff,xml,old}` — choose the formatter (default `diff`).
- `-w` / `--keep-whitespace` — do not strip ignorable whitespace.
- `-p` / `--pretty-print` — make XML output more readable.
- `-F <float>` — similarity threshold (rejects values `<= 0` or `> 1`).
- `--unique-attributes <csv>` — comma-separated unique attributes (defaults to
  `{http://www.w3.org/XML/1998/namespace}id`).
- `--ratio-mode {accurate,fast,faster}` — default `fast`.
- `--fast-match` / `--best-match` — mutually exclusive match strategies.
- `--ignored-attributes <csv>` — attributes to ignore.
- `--check` — exit with status `1` if the files differ (status `0` if identical),
  in addition to printing the diff.
- `-v` / `--version` — print `xmldiff <version>` and exit, where `<version>` is the
  package's own version string. The exact version is implementation-defined and is not
  graded.

With the default formatter the output is the DiffFormatter text (§5), one action
per line.

### `xmlpatch patchfile xmlfile [--diff-encoding ENC]`

Reads an edit script in DiffFormatter text format from `patchfile`, applies it to
`xmlfile`, and prints the patched XML.
