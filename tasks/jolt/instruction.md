# JOLT - JSON Transform Library

Build a pure-Java library that reshapes JSON documents using declarative specs. Input, spec, and output are all represented as already-parsed JSON trees; your code works on the in-memory model, not on raw strings.

## JSON Data Model

The runtime uses plain Java objects like Jackson would produce:

- JSON object -> `java.util.Map<String, Object>` with insertion-order preserved. You must use an order-preserving map implementation.
- JSON array -> `java.util.List<Object>`
- JSON primitives -> `String`, `Integer` / `Long` / `Double` (whatever Jackson yields for numbers), `Boolean`, `null`

Transforms must not mutate the input when they are specified to produce a new tree. Output object key order is observable: it must follow insertion order for all explicitly ordered cases.

A helper `com.bazaarvoice.jolt.JsonUtils` for parsing/serializing is already on the classpath along with Jackson, Guava, commons-lang3, and javax.inject. Do not reimplement or replace `JsonUtils`.

## Package and Public API

All classes must live in exactly this package:

```
package com.bazaarvoice.jolt
```

Exact signatures — the grader calls these via reflection:

```java
class Shiftr {
    public Shiftr(Object spec)
    public Object transform(Object input)
}
class Defaultr {
    public Defaultr(Object spec)
    public Object transform(Object input)
}
class Removr {
    public Removr(Object spec)
    public Object transform(Object input)
}
class Chainr {
    public static Chainr fromSpec(Object chainrSpec)
    public Object transform(Object input)
}
```

- `spec` for `Shiftr`/`Defaultr`/`Removr` is a parsed JSON object (a `Map`).
- `chainrSpec` for `Chainr` is a parsed JSON array (a `List` of step objects).
- `transform` takes a parsed input tree and returns a new parsed output tree.

## Shiftr — Move Data from Input to Output

Shiftr is the core operation. It walks the input tree in parallel with the spec tree. Where a spec leaf is reached, the leaf's value tells where to write the currently matched input data.

Spec structure: internal nodes contain **left-hand-side (LHS) patterns** that are matched against input keys. Leaves contain **right-hand-side (RHS) output paths** (strings, or arrays of strings). If the leaf is an array of strings, the same matched data is written to every path listed. If a leaf resolves to `null` or empty-string `""`, that matched data is discarded.

### LHS match operators

- **Literal key**: matches exactly that input key.
- **Wildcard `*`**: matches input keys. Can stand alone (`*` matches any key) or be embedded (`tag-*`, `*-suffix`, `a-*-b-*-c`). A `*` captures the substring it matched as non-greedily as possible and matches **one or more** characters (it never matches the empty string); with multiple `*` in one pattern each produces its own capture group.
- **Match against scalar leaf values**: when the parallel walk reaches a scalar leaf (a string, number, or boolean — including a scalar element of an input array) and the spec at that position still has child LHS keys, those keys (literal, `*`, `|`) are matched against the **stringified leaf value** rather than a key. A boolean matches the literal `true`/`false`; a number matches its textual form (`1234` matches `1234`). Wildcards capture from the value as usual. This lets a spec route on the *value* of a field, not just its key.
- **Computed key `&`**: the key to match is derived from the walk history. Form `&(levels,captureGroup)`: go `levels` up the already-matched path, look at the wildcard capture from that level, take its `captureGroup`-th piece, and use that string as a literal key to match here. Shorthands: `&` means `&0` which means `&(0)` which means `&(0,0)` — all refer to the full matched key at level 0 (see **Reference levels** below).
- **`$` as data source (LHS only)**: instead of using the input *value* as data to output, use the matched *key itself*. Same addressing as `&`: `$(n,m)` goes `n` levels up and pulls capture `m` of that matched key. Useful for turning keys into values or collecting key names.
- **`@` as data source (LHS)**: use an input *value* as the data. Forms:
  - bare `@` — the value at the current walk node.
  - `@(n,path)` — climb `n` levels then read the value at `path` inside that ancestor. `path` may traverse nested objects and array indices, and may itself embed `&`/`&(n,m)` references (e.g. `@(3,capitals[&1])`), which are resolved against the walk history before the lookup.
  - `@path` shorthand — equivalent to `@(0,path)` (e.g. `@clientName` reads the value at `clientName` at the current level; `@&1` reads the value at the path named by the `&1` reference).
  - As a **spec-node key** mapping to a sub-spec, `@(n,path)` transposes the looked-up subtree into the walk and **continues matching** the child spec against it.
  - Missing vs. null: an `@` lookup whose path is absent produces **no output** (the target key simply does not appear); a lookup that resolves to a value that is `null` in the input is written as `null`.
- **`#literal` as data source (LHS)**: inject a fixed string that does not exist in the input. The part after `#` becomes synthetic data; the RHS decides where it lands.
- **OR `|`**: `a|b|c` as a single spec key matches if the input key (or, on a scalar leaf, the value) equals any of the alternatives. It is syntactic sugar for repeating the same subtree under several names.
- **Array indexing**: input arrays are treated as maps from numeric-string keys to elements, so a spec key `"0"`, `"1"` etc. selects that array position.

On the Shiftr LHS `.` is **not** a path separator — it carries no special meaning and is matched literally as an ordinary character inside the key (so a spec key `note.*-*-*` matches the literal input key `note.9-4-4`). Dot-notation for building nested output objects applies only to RHS output paths.

### RHS output path operators

RHS paths use dot notation to create nested objects: `a.b.c`. A path segment can be any of:

- **Literal segment**: a fixed output key.
- **Reference substitution `&(n,m)`**: insert a value from the walk history as an output key, e.g. `Ratings.&1.Score` where `&1` inserts the key that matched one level above.
- **`@` transpose on RHS**: `@`, `@(n,path)`, or the `@path` shorthand may appear as an output path segment, in which case the segment is the value looked up from the input. For example `data.@clientId` writes under the output key equal to the looked-up `clientId`, and `clients.@(3,clientId)` keys the output by a value fetched three levels up. A non-string looked-up value used as an output key is **coerced to its string form** (the integer `77` becomes the key `"77"`). The `@(...)` path may itself contain `&`/`&(n,m)` references and array-index traversal.
- **Array construction with `[]`**:
  - Bare trailing `[]`: append each matched value to an array at that path, in input-walk (match) order, **wrapping even a single value** in a one-element array. It may be followed by a sub-path (`foo[].id`) to build an array of objects.
  - Fixed index `[n]`: `Photos[1].Url` writes into array `Photos` at index 1; earlier holes with no data become `null`.
  - Dynamic index from a reference `[&(0,1)]`: uses a captured value as the array index.
  - Dynamic index from a transpose `[@(n,path)]`: uses a looked-up value as the array index. A numeric string is coerced to an integer; a non-numeric or negative index produces **no output** for that item; earlier gaps become `null`.
  - Cardinality index `[#n]`: the running **0-based** count of children matched so far under the ancestor reached by climbing `n` levels (same level counting as `&(n)` — see **Reference levels**), incrementing once per matched child in match order. The anchor is the *specific matched ancestor* on the current walk, not the shared spec node, so the count is per-ancestor: it restarts at 0 for each distinct such ancestor match. This converts a map iteration into an ordered list, and when the counted level sits below an enclosing wildcard each parent match builds its own list starting at index 0.
- **Collision handling**: if unrelated input pieces are written to the same output path without explicit array brackets, that location becomes an array holding all values, appended in input-walk (insertion) order.
- Arrays created via explicit indexes (`[n]`, `[&(…)]`, `[@(…)]`, `[#n]`), a bare `[]`, by incidental collision, or by walking an input array all follow input-walk (insertion) order, which the output is compared against.

### Reference levels

`&`/`$`/`@`/`#` addressing counts **levels** along the chain of matches from the current position up to the root of the input tree. **Every enclosing match adds exactly one level** — a literal key, a `*` wildcard key, a scalar **value-match**, and an array-index match each count as one — and the original input tree sits at the top, so a high-enough climb reaches the root. `&(n,m)` climbs `n` levels and takes capture group `m` of the match there (`m=0` is the full matched key, `m=1` the first `*` capture, and so on). For `@`/`$`, a climb that lands on a level reads its `path`/key from the input node that match descended into.

What counts as **level 0** depends on where the reference sits:

- **In an RHS output path**, level 0 is the current spec node's own match — the RHS-bearing leaf's matched key — and levels 1, 2, … are the enclosing matches above it.
- **An operator key's own climb** — an `&(n,m)` computing the key to match here, a `$(n,m)` selecting a key, or an `@(n,path)` reading/transposing a value — anchors level 0 on **the match it fires under** (the deepest match already on the walked path, i.e. the node it is written beneath). The operator does **not** add a level for itself, so `&(n,m)` / `$(n)` / `@(n,path)` counts `n` enclosing matches upward from that node. An `&` spec key therefore always resolves to a concrete key string before it can match — it can never refer to its own match, so it never matches unconditionally. Because every value-match and array-index in between still counts as a level, a climb out of a matched array element (and its value-match) consumes those levels before it reaches an ancestor object.
- **Once an operator has resolved**, it contributes its own produced match to the walked path, so any `&`/`$`/`@` reference written on that operator's **RHS** counts level 0 = the operator's produced match, with the enclosing matches shifted up by one. An `&` key's produced match is the input key it matched; a `$` operator's produced match is the key it selected; an `@` operator's produced match mirrors the match it fired under (so `&(0,1)` on an `@` RHS yields that match's first `*` capture); a `#literal` data source likewise contributes one produced match, so a `&`/`$`/`@` reference written on its RHS counts level 0 as the `#`'s produced match.

For example, to read a field from an ancestor object while matched deep inside an array:

```
// input   { "items": [ { "name": "A", "avail": [ "x" ] } ] }
// spec     { "items": { "*": { "avail": { "*": { "x": { "@(3,name)": "Hits[]" } } } } } }
// output   { "Hits": [ "A" ] }
```

`@(3,name)` fires under the value-match `x`; climbing 3 levels — value-match `x` (0), the `avail` array-index (1), the `avail` literal (2), the `items` array-index (3) — lands on the matched item object and reads its `name`.

### Escaping and precedence

Special characters (`*`, `@`, `$`, `#`, `&`, `|`, `[`, `]`) can be taken literally by prefixing with a backslash: `\*`, `\@`, `\$`, `\#`, `\&`, `\|`, `\[`, `\]` match (LHS) or emit (RHS) the actual character rather than invoking the operator. Escaping applies to **both** LHS patterns and RHS output literals (e.g. an RHS `\[x` emits the literal output key `[x`).

When multiple LHS keys at the same spec level could all match a single input key, evaluation follows a fixed priority: **literal keys first, then `&` computed keys, then `*` wildcard keys**. The first matching priority class wins for output placement. Within the `&` group and within the `*` group, ordering is deterministic alphabetical after expanding shorthands. Keys starting with `@` and `$` are unconditional — whenever their parent spec node matches, they fire and do not prevent other keys at the same level from also matching.

## Defaultr — Fill Missing Values Non-Destructively

Defaultr walks the spec tree and ensures defaults exist in the input. For each spec entry, if that key is already present in the input with a non-null value it is left untouched; if absent — **or present with a `null` value** — it is added/filled with the default value from the spec. Nested objects merge recursively rather than overwrite.

LHS supports literal keys, wildcard `*`, and OR `|` keys. Only a **literal** key can create a key that is absent from the input: an absent literal key is added with its default. A wildcard `*` and an OR `|` key are **match patterns** — they apply the default rule only to keys that already exist at that level (present in the input, or created by a literal sibling entry) and never materialize a new key for an alternative that is absent from the input.

- **Array handling (`[]`)**: a spec key suffixed with `[]` (e.g. `photos[]`, `*[]`) declares that the data at that key is an **array**; its child spec keys must be numeric indices, or `*` to apply to every element. Defaults recurse into each array element. If the top-level input is itself an array, the spec's root is applied as if it were the child of such an array key (so a spec like `{"*[]": {"*": {…}}}` defaults into every element of a nested top-level array).
- **Conflict precedence**: when more than one spec key matches the same input key, **every** matching key contributes its defaults through the same recursive non-destructive merge (so the matched key accumulates the union of all their sub-fields). Specificity only fixes the **order** in which the matches are applied — **literal keys first, then OR `|` keys, then `*`** — so on a directly conflicting leaf the most specific key's value is the one kept. Among competing `|` keys, fewer alternatives is more specific and wins; ties are broken alphabetically by the sorted alternatives. This ordering is independent of the order keys are listed in the spec.
- **`*` applies to created keys, not just input keys**: because the matches are applied in that specificity order, `*` (and any OR `|` key) defaults into every key present at that level **after** the literal entries have run — including the keys those literal entries just created — not only keys already present in the input. So with an empty or partial input, a key created by a literal spec entry still receives the OR `|` and wildcard defaults (e.g. under an empty input, a `*` sibling fills its fields into each literal-declared key, and an OR `|` key merges into whichever of those literal-created keys it names).

Output must preserve the input's key ordering, with newly defaulted keys appended in spec order.

## Removr — Delete Matched Content

Removr walks the spec and deletes every input key it names. A spec leaf value is conventionally `""` (empty string) as a placeholder — the presence of the key in the spec signals removal, not the leaf value.

Supports literal keys, OR `|` keys (`a|b` removes any listed alternative), and wildcard `*` (delete all keys at that level, or all keys matching a template like `tag-*`), and recurses into nested objects and arrays. A numeric-string key removes that array index. Anything not named stays.

Removr wildcard details:

- `*` matches **one or more** characters (never the empty string) and is as non-greedy as possible; it may appear multiple times in a template (`a-*-*$*`). Because `*` cannot match empty, a trailing `*` requires at least one character after the preceding literal (so `a-*-*$*` matches `a-p-q$1` but not `a-p-q$`).
- In Removr patterns, characters that carry meaning elsewhere in Jolt — Shiftr LHS operators (`$`, `#`) and the RHS output-path separator (`.`) — have no special meaning here and are matched **literally**.

## Chainr — Ordered Pipeline

Chainr chains multiple transforms.

- Its spec is a JSON array, each element a step object: `{"operation": "<name>", "spec": <spec>}`
- Steps execute in array order: input of Chainr goes to step 0, output of step N becomes input of step N+1, final step output is Chainr's output.
- Required operations: `shift` -> Shiftr, `default` -> Defaultr, `remove` -> Removr. Each of those step types includes a `"spec"` field containing the inner spec for that operation. You do not need to support custom or unknown operations.

## Worked Examples

These illustrate the walk semantics end to end (input tree + spec -> output tree).

**Shiftr** — wildcard capture, `&1` back-reference, `$` key-as-data, and bare `[]`:

```
// input
{ "rating": { "primary": { "value": 3 }, "quality": { "value": 4 } } }

// spec
{ "rating": { "*": { "value": "Ratings.&1", "$": "RatingNames[]" } } }

// output   (&1 = the key matched one level up; $ emits that key; [] wraps into an array)
{ "Ratings": { "primary": 3, "quality": 4 }, "RatingNames": [ "primary", "quality" ] }
```

**Defaultr** — literal default, `*` over existing children, recursive merge, null default:

```
// input
{ "Rating": 3, "SecondaryRatings": { "quality": { "Value": 3 } } }

// spec
{ "RatingRange": 5, "SecondaryRatings": { "*": { "Range": 5, "Label": null } } }

// output   (existing keys kept in place; newly defaulted keys appended in spec order)
{ "Rating": 3,
  "SecondaryRatings": { "quality": { "Value": 3, "Range": 5, "Label": null } },
  "RatingRange": 5 }
```

**Removr** — remove a named key and a wildcard template:

```
// input   { "keep": 1, "dropMe": 2, "tmp-a": 3, "tmp-b": 4 }
// spec    { "dropMe": "", "tmp-*": "" }
// output  { "keep": 1 }
```

**Chainr** — run a shift then a default in sequence: `[ {"operation":"shift","spec":{…}}, {"operation":"default","spec":{…}} ]` feeds the shift output into the default step.

## Contracts Summary

- Exact package `com.bazaarvoice.jolt` and exact class/method names above.
- Preserve map insertion order for output objects.
- Explain escaping via backslash and priority literal -> `&` -> `*` with sorted intra-group order, `@`/`$` always firing.
- All output arrays — from explicit `[index]` / `[&]` / `[@]` / `[#]` writes, a bare `[]`, incidental collision, or iterating an input array — follow input-walk (insertion) order, and the output is compared against that order.
