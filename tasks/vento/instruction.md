# Build the Vento template engine

Implement **Vento**, a minimal `{{ }}` template engine for the Deno/JavaScript
runtime. Vento compiles a template string into JavaScript and runs it against a
data object, producing a rendered string. Everything inside `{{ ... }}` is real
JavaScript executed at render time; everything outside is emitted verbatim.

Your deliverable is a Deno module at **`/app/mod.ts`**. The hidden test suite
imports it as:

```ts
import tmpl from "/app/mod.ts";
```

The engine has **zero runtime dependencies** (do not import anything from the
network or `jsr:`/`npm:` — only the standard runtime is available; the eval is
offline).

---

## 1. Public API

`/app/mod.ts` **default-exports a factory function**:

```ts
export default function (options?: Options): Environment;

export interface Options {
  includes?: string | Loader; // include resolver (see §7). Tests always pass a Loader object.
  dataVarname?: string;       // default "it"
  autoDataVarname?: boolean;  // default true
  autoescape?: boolean;       // default false
  strict?: boolean;           // default false
  maxRenderConcurrency?: number; // default 10000
}
```

The returned `Environment` must expose at least:

```ts
interface Environment {
  runString(template: string, data?: Record<string, unknown>): Promise<{ content: string }>;
  filters: Record<string, (this: FilterContext, ...args: any[]) => unknown>;
  use(plugin: (env: Environment) => void): void; // plugin hook; tests never require extra plugins
}
```

- `runString(template, data)` compiles `template` and renders it with `data`,
  resolving to an object whose **`content`** property is the rendered string.
  It is `async` and returns a `Promise`.
- `env.filters` is a mutable object of named filters. The test harness registers
  custom filters by assigning to it **after** the environment is created
  (`env.filters.slugify = ...`). Built-in filters (§6) must already be present.
- All rendering is asynchronous: templates may contain `await`, and filters may
  return promises.

Everything below describes the exact surface the tests exercise.

---

## 2. Data access & variable resolution

- `dataVarname` (default `"it"`) is the name of the object holding the render
  data. `{{ it.message }}` reads `data.message`.
- When `autoDataVarname` is `true` (the default), a **bare identifier is
  auto-resolved from the data object**: `{{ message }}` behaves like
  `{{ it.message }}`. This must work for reads inside any expression
  (`{{ message || "x" }}`, `{{ messages[0] }}`, `{{ name == "Óscar" }}`, loop
  sources, filter arguments, etc.).
- Auto-resolution only applies to identifiers that are **not** otherwise defined
  in scope (a `{{ set }}` variable, a `{{ function }}`, a `{{> const x }}`
  declaration, a loop variable, an imported binding, etc. shadow the data).
- The host runtime's ambient globals take **no part** in this resolution: a bare
  identifier the template does not declare resolves from the data object, and is
  `undefined` when the data has no such property. Standard built-ins used
  directly in an expression (`JSON`, `Date`, `Array`, `NaN`, …) and globals used
  as filter names (§5) still resolve as globals.
- When `autoDataVarname` is `false`, bare identifiers are **not** auto-resolved.
  Referencing an undefined bare identifier is then a runtime error (see §11).
  You must still use `{{ it.message }}` to reach data.
- An identifier that resolves to nothing (undeclared, and not in data) prints as
  the empty string `""` (unless `strict` is on — see §11). `undefined` and
  `null` also print as `""`.

---

## 3. Output tag `{{ expression }}`

`{{ <js-expression> }}` evaluates the expression and appends its string value to
the output.

- `null` and `undefined` produce `""`.
- Any other value is coerced with `String(value)`.
- The expression is arbitrary JavaScript: string/number/boolean literals,
  `||`, `??`, ternary `a ? b : c`, member/index access `a.b` / `a[k]`, function
  calls, template literals, object/array literals, spread `{...foo}`, regex
  literals, `await`, etc. Examples that must render exactly:
  - `{{ "Hello world" }}` → `Hello world`
  - `{{ message || "Hello world" }}` with `message=false` → `Hello world`
  - `{{ message ?? "no" }}` with no `message` → `no`
  - `{{ message ? "yes" : "no" }}` with `message=null` → `no`
  - `{{ messages[0] }}` with `messages=["yes","no"]` → `yes`
  - `{{ {...foo} |> JSON.stringify }}` with `foo={bar:23}` → `{"bar":23}`

The tokenizer must treat `{{`/`}}` correctly even when they appear inside the
expression's string literals, template literals, regex literals, comments, or
nested braces — e.g. `{{ message + "{{}}" }}`, `{{ `message {}}` }}`,
`{{ !/}}/.test(foo) }}`, `{{ message /* }} */ }}` are single tags.

---

## 4. Whitespace control (trim markers)

A dash immediately inside a tag trims adjacent template whitespace:

- `{{-` removes all whitespace in the **preceding** static text.
- `-}}` removes all whitespace in the **following** static text.

These work on every tag form (output, `set`, `echo`, `for`, `if`, `include`,
`layout`, `slot`, comments, `{{> ... }}`). Examples:

- `Hello {{- "World" }} !` → `HelloWorld !`
- `Hello {{ "World" -}} !` → `Hello World!`
- `Hello {{- "World" -}} !` → `HelloWorld!`
- `{{> let foo = -2 }}\n1 + 1 = {{--foo}}` → `1 + 1 =2` (the leading `{{-` is the trim marker, so the JS expression is `-foo` — a unary minus; with `foo = -2` it evaluates to `2`, and the trim removes the preceding space)

> The hidden suite trims the final rendered string (leading/trailing whitespace)
> before comparing, so surrounding template indentation does not matter — only
> whitespace **between** and **inside** rendered chunks does.

---

## 5. Filter pipeline `|>`

`value |> filter` / `value |> filter(arg1, arg2)` transforms `value` through a
pipeline. Chaining is left-to-right:
`{{ a |> f |> g(x) }}` = `g(f(a), x)`.

**Filter name resolution** (in order), for `value |> name(...args)`:

1. If `env.filters[name]` is a function → call
   `env.filters[name].call(context, value, ...args)`.
2. Else if `name` resolves to a callable value in scope (a global such as
   `JSON.stringify` or `fetch`, or a declared variable) →
   `name(value, ...args)`.
3. Else → call it as a **method of the value**: `value.name(...args)` (e.g.
   `toUpperCase`, `toLowerCase`, `toString`, `trim`, `join`, `replace`,
   `filter`, `map`).

Extra rules:

- **Every filter result is awaited.** A filter (registered, global, or method) may be `async` /
  return a Promise; the pipeline renders the resolved value with no explicit `await` needed, e.g.
  `{{ "foo" |> getAsync }}` with an async `getAsync` renders the resolved string. A leading `await`
  in a pipeline step additionally awaits *within* the step's expression, e.g.
  `x |> await fetch |> await json` → `await (await fetch(x)).json()`.
- A leading `!` negates the step's (boolean) result, e.g. `v |> !empty`.
- **Method steps are null-safe.** When the piped value is `null`/`undefined`, a rule-3
  method step is **not** invoked — the value passes through unchanged instead of throwing. A
  method-filter chain over a nullish value therefore stays nullish and renders as `""`, e.g.
  `{{ message |> toString |> toUpperCase }}` with no `message` → `""`.
- `name` may contain a dot (`JSON.stringify`) — treated under rule 2.
- The `context` (the `this`) passed to registered filters exposes `context.data`
  (current data/scope object) and `context.env` (the environment, so
  `this.env.filters` is reachable).

Filters may be applied wherever an expression is produced: output tags, `if`
conditions (`{{ if "one" |> isOne }}`), `for` sources (`{{ for x of arr |> double }}`),
`set` values/blocks, `include`/`layout`/`slot`/`echo`/`function` (see those
sections).

---

## 6. Built-in filters

These must be pre-registered on every environment:

### `escape`
HTML-escapes a **string**: `&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;`, `"`→`&quot;`,
`'`→`&#39;`. Non-strings are returned unchanged (`100 |> escape` → `100`);
`undefined`/`null` render as `""`. Its output is treated as **safe** (§8).

- `{{ "<h1>Hello world</h1>" |> escape }}` → `&lt;h1&gt;Hello world&lt;/h1&gt;`
- `{{ object |> JSON.stringify |> escape }}` with `{bar:23}` → `{&quot;bar&quot;:23}`

### `unescape`
Reverses HTML entities in a string: the named entities `&amp; &lt; &gt; &quot;
&#39;` **and** numeric entities, decimal `&#60;` and hexadecimal `&#x3C;` /
`&#X03e;` (case-insensitive `x`). Non-strings unchanged; `undefined` → `""`.

- `{{ "&lt;h1&gt;Hello world&lt;/h1&gt;" |> unescape }}` → `<h1>Hello world</h1>`
- `{{ "&#x3C;h1&#X03e;Hello world&#60;/h1&#062;" |> unescape }}` → `<h1>Hello world</h1>`

### `safe`
Returns the value unchanged but marks it **safe** so autoescape (§8) will not
escape it. Overrides autoescaping.

### `empty` / `!empty`
Returns `true` when the value is "empty":

- `null`, `undefined`, `false` → true
- number: `NaN` or `0` → true; any other number → false
- string: **trimmed** length `0` → true (so `" \n\t "` → true); `"0"` → false
- array: length `0` → true; a sparse `Array(1)` (length 1) → false
- plain object (constructor `Object`): no own enumerable keys → true; otherwise
  false. **Non-plain objects (e.g. `new Date()`) are never empty** → false.

`!empty` negates the result. Examples: `{{ NaN |> empty }}` → `true`;
`{{ " \n\t " |> !empty }}` → `false`; `{{ new Date() |> empty }}` → `false`;
`{{ Array(1) |> empty }}` → `false`; `{{ "0" |> empty }}` → `false`.

---

## 7. Includes and the Loader interface

`{{ include "<path>" [data] [|> filters] }}` renders another template inline.

The include source comes from a **Loader**, provided via `options.includes`. The
tests always pass a Loader object implementing:

```ts
interface Loader {
  resolve(from: string, file: string): string;   // -> absolute path
  load(file: string): Promise<{ source: string; data?: Record<string, unknown> }>;
}
```

The engine must:

1. Evaluate the path expression (it is JS: `"/my-file.vto"`, `file`,
   `"/my-file" + ext`, `` `/${file}.vto` ``, `resolve({path:"..."})`, …).
2. Resolve it via `loader.resolve(currentFile, path)`. The **top-level**
   template's path is treated as `"/"`; a relative path (`"./other.vto"`) is
   resolved against the **including file's** directory. Absolute paths
   (`"/sub/x.vto"`) resolve to themselves.
3. `await loader.load(resolvedPath)` to obtain `{ source, data }` and render
   `source`.

**Data scope of an include** = the parent data merged with the loader's returned
`data` (front matter) merged with the optional inline `data` argument — later
sources win:
`{ ...parentData, ...loaderData, ...inlineData }`.

- `{{ include "/my-file.vto" }}` with `/my-file.vto` = `Hello {{ name }}` and
  parent `name="world"` → `Hello world`.
- `{{ include "/my-file.vto" {salute: "Good bye"} }}` where the file is
  `{{ salute }} {{ name }}` and parent has `salute="Hello", name="world"` →
  `Good bye world` (inline `salute` overrides, `name` inherited).
- `{{ include "/my-file.vto" { name } }}` — object-shorthand data works.
- Includes may carry a filter pipeline applied to the rendered result:
  `{{ include "/sub/my-file.vto" |> replace(" ", "-") }}` where the sub-file is
  `{{ include './other-file.vto' |> toUpperCase }}` and `other-file` is
  `Hello world` → `HELLO-WORLD`.
- Front matter: if the loader's `load` returns `data`, those values are in scope
  (used by the test loader to surface YAML front matter). If the file provides
  `salute` via front matter and nothing overrides it, `{{ salute }}` prints it.
- **Recursion guard**: nested include rendering is bounded by
  `maxRenderConcurrency` (default 10000). A chain that reaches depth
  `maxRenderConcurrency` must reject (throw); one strictly below it renders
  normally.

---

## 8. Autoescape

When `autoescape` is `true`, the string value of every **output tag**
`{{ expr }}` is HTML-escaped (like the `escape` filter) **unless the value is
safe**. Static template text is emitted verbatim (never escaped).

A value is **safe** (not escaped) when it is produced by: the `safe` filter, the
`escape`/`unescape` filters, the rendered output of an `include`, a `layout`, a
`{{ function }}` call, or a `slot`. Nested renders are therefore not
double-escaped.

Consequences the tests rely on (with `autoescape: true`):

- `{{ "<h1>Hello world</h1>" }}` → `&lt;h1&gt;Hello world&lt;/h1&gt;`
- `{{ "<h1>Hello world&lt;/h1&gt;" |> safe }}` → `<h1>Hello world&lt;/h1&gt;`
- Include of `<strong>Hello world</strong>` → emitted unescaped.
- A `{{ function }}`'s return value is a **safe** value: with `autoescape:true`,
  `typeof hello() === "string"` is `false` (it is a safe wrapper object); with
  `autoescape:false` it is `true` (a plain string).

With `autoescape: false` (default) nothing is auto-escaped.

---

## 9. Tags

All tags use `{{ ... }}`. Block tags have a matching `{{ /tag }}`.

### `{{ if }}` / `{{ else if }}` / `{{ else }}` / `{{ /if }}`
Standard conditional; the condition is any JS expression (and may use `|>`).
Multi-line conditions are allowed. Truthiness is JS truthiness.

```
{{ if name == "Óscar" }}...{{ else if name == "Laura" }}Is Laura{{ /if }}
{{ if "one" |> isOne }}<p>True</p>{{ /if }}
```

### `{{ for }}` / `{{ /for }}`
Iterates. Supported source forms (right of `of`) and variable forms (left):

- `{{ for x of <iterable> }}` and `{{ for key, x of <iterable> }}` — the first
  variable is the **key/index**.
- Iterables: numbers (`for n of 3` yields `1,2,3` with keys `0,1,2`), strings
  (per character, keys are indices), arrays (values, keys are indices), plain
  objects (values, keys are the property names), functions (called, then
  iterated over the returned value), and (async) generators/iterators (keys are
  a running index).
- `null`/`undefined` sources iterate zero times.
- Destructuring targets: `{{ for {name, value} of items }}`,
  `{{ for [name, value] of items }}`, nested (`{{ for [[n]] of ... }}`),
  and with a leading key var (`{{ for i, {name,value} of items }}`).
- A filter pipeline may transform the source:
  `{{ for x of [1,2,3] |> double }}`, `{{ for x of [1,2,3] |> filter(n=>n===2) }}`.
- Classic C-style: `{{ for let i = 0; i < 10; i += 2 }}...{{ /for }}` and the
  comma form `{{ for var i = 0, j = 0; i < 10; i += 2, j += i }}`.
- `{{ for await key, x of asyncIterable }}` for async iteration.
- `{{ break }}` and `{{ continue }}` inside the body behave as in JS.

Examples:
- `{{ for key, number of 3 }}{{number}}({{key}}) - {{ /for }}` → `1(0) - 2(1) - 3(2) -`
- `{{ for key, name of "hello" }}{{name}}({{key}})-{{ /for }}` → `h(0)-e(1)-l(2)-l(3)-o(4)-`
- `{{ for key, name of { one:"1", two:"2" } }}{{name}}({{key}})-{{ /for }}` → `1(one)-2(two)-`
- `{{ for {name, value} of items }}{{ name }}:{{ value }}-{{ /for }}` → `one:2-two:4-three:6-`

### `{{ set }}` / `{{ /set }}` and `{{ default }}` / `{{ /default }}`
- Inline assignment: `{{ set message = <expr> }}` — the expression may use `|>`
  (`{{ set message = ["Hello","world"] |> join(" ") }}`). Variable names may
  include `$`.
- Destructuring assignment: `{{ set { foo, bar } = obj }}`, rest
  (`{{ set { one, ...other } = ... }}`), renaming (`{{ set { bar: bar2 } = ... }}`),
  nested (`{{ set { a, b: { c, d } } = ... }}`), arrays
  (`{{ set [one, two] = [...] }}`, nested `{{ set [x, [y, z]] = ... }}`).
- Block capture: `{{ set message }}...body...{{ /set }}` sets `message` to the
  rendered body (trimmed). A filter pipeline may be applied to the captured
  body: `{{ set message |> toUpperCase }}...{{ /set }}`.
- A `set` variable is visible for the rest of the current scope and is passed
  into includes.
- `{{ default name = <expr> }}` / block `{{ default name }}...{{ /default }}`
  assigns only if the variable is currently `undefined`/`null` (leaves an
  existing value untouched). Works in `strict` mode.

### `{{ function }}` / `{{ /function }}`, `{{ export }}` / `{{ /export }}`, `{{ async function }}`
- Declares a reusable template function: `{{ function hello(name="World") }}Hello {{ name }}{{ /function }}`,
  then `{{ hello() }}` / `{{ hello("Vento") }}`.
- Parameters are ordinary JS parameter lists, including defaults and destructured
  defaults (`{{ function hello ({name="World"}={}) }}`), and defaults that call
  other functions.
- **Hoisting**: a function may be called before its declaration in the template.
- **Scope isolation**: a function body has its own scope — `{{> const x }}`
  declared inside a function does not leak out, and a nested function is not
  visible in the outer scope.
- Calling a function returns its rendered body (a **safe** value under
  autoescape, §8). A filter pipeline may be attached to the declaration:
  `{{ export function hello |> toUpperCase }}...{{ /export }}`.
- `{{ export ... }}`/`{{ /export }}` is like `function` but also marks the
  binding for `import` (§10). `{{ async function name }}` allows `await` in the
  body and is called as `{{ await name() }}`.

### `{{ echo }}` / `{{ /echo }}`
Emits its content **literally**, without interpreting inner `{{ }}`:

- `{{echo}} Hello {{ world }} {{/echo}}` → `Hello {{ world }}`
- Inline string form: `{{ echo "Hello {{ world }}" }}` → `Hello {{ world }}`
- A filter pipeline applies to the echoed text: `{{echo |> toUpperCase }} Hello {{ world }} {{/echo}}` → `HELLO {{ WORLD }}`
- Trim markers work: `Hello {{-echo-}} beautiful {{-/echo-}} world!` → `Hellobeautifulworld!`

### Comments `{{# ... #}}`
Produce no output. Trim markers use `{{#-` and `-#}}`:

- `{{# "Hello world" #}}` → ``
- `<h1> {{#- -#}} </h1>` → `<h1></h1>`

### Inline JavaScript `{{> ... }}`
Runs raw JavaScript statements (declarations, etc.) with no output:

- `{{> const message = "Hello world" }}` then `{{ message }}` → `Hello world`
- May span multiple lines and contain JS comments (`//`, `/* */`), string/regex
  literals, etc. `{{> const { a = 2 } = {}; }}` is valid.

### `{{ layout }}` / `{{ /layout }}` and `{{ slot }}` / `{{ /slot }}`
Wraps rendered content in a parent template. The child's rendered body is exposed
to the layout file as `content`.

- `{{ layout "/my-file.vto" }}Hello world{{ /layout }}` with layout file
  `<h1>{{ content }}</h1>` → `<h1>Hello world</h1>`.
- Extra data: `{{ layout "/my-file.vto" { tag: "h1" } }}...{{ /layout }}`.
- A filter pipeline on the `layout` tag applies to the **rendered child body** (the block's
  content) *before* it is passed to the layout file as `content` — **not** to the final wrapped
  output: `{{ layout "/my-file.vto" |> toUpperCase }}Hello world{{ /layout }}` with layout file
  `<h1>{{ content }}</h1>` → `<h1>HELLO WORLD</h1>` (the layout's own `<h1>` text is untouched;
  only the child content is uppercased, then the layout renders normally around it).
- Layouts nest.
- **Slots**: inside a layout body, `{{ slot name }}...{{ /slot }}` defines a
  named block that the layout file reads as `{{ name }}`. Multiple slots with the
  **same name concatenate** in order. A slot block body is captured **verbatim** —
  unlike a `{{ set }}` block capture (which is trimmed), slot bodies are **not**
  trimmed, so their internal/trailing whitespace is preserved on concatenation.
  Slot definitions may carry filters
  (`{{ slot message |> toLowerCase() }}...{{ /slot }}`). Slots do not leak
  between sibling layouts.

Example (slots):
```
{{ layout "/my-file.vto" }}
  {{ slot greeting }}Hello{{ /slot }}
  {{ slot target }}world{{ /slot }}
{{ /layout }}
```
with `/my-file.vto` = `{{ greeting }} {{ target }}` → `Hello world`.

---

## 10. Import / export

`{{ import ... from "<path>" }}` pulls exported bindings from another template.
Exports come from `{{ export ... }}` (function or value) in the target file.

- Named import of a function:
  `{{ import { hello } from "/my-file.vto" }}` then `{{ hello() }}`, where the
  file declares `{{ export function hello (name="world") }}Hello {{ name }}{{ /export }}`.
- Value exports: `{{ export hello = "Hello " + name }}` (or block
  `{{ export hello }}...{{ /export }}`) — imported as a value: `{{ hello }}`.
- Namespace import: `{{ import vars from "/my-file.vto" }}` then `{{ vars.hello }}`.
- Aliases on both sides: `{{ import { hi as hey } from "/file.vto" }}` and
  `{{ export { hello as hi } }}`.
- **Data scope**: an imported template is rendered against the importing
  template's render data (as an include is, §7), so a free identifier such as
  `name` in `{{ export hello = "Hello " + name }}` (or a `{{ set }}` value that is
  then exported) resolves against the importer's data.

---

## 11. Errors & strict mode

`runString` must **reject** (throw) in these cases (the tests use
`assertRejects`):

- `strict: true` and a referenced variable is undefined:
  `{{ hello }}` with no `hello` in data/scope rejects. (In non-strict mode it
  prints `""`.) Note strict only complains about variables that are actually
  reached at runtime — `{{ if false }}{{ hello }}{{ /if }}` does not throw.
- `autoDataVarname: false` and a bare identifier is used that is not defined
  (e.g. template `Hello {{ world }}` — `world` must be reached via `it.world`).
- An include chain that reaches `maxRenderConcurrency` depth (§7).

In non-strict mode, reading an undefined/undeclared variable yields `""`.

---

## 12. Notes

- Match the observable behavior described above exactly; the hidden suite asserts
  exact rendered strings (both sides are `.trim()`-ed before comparison).
- Nearly all tags/filters can be implemented as plugins registered on the
  Environment, but only the behavior above is graded. `env.use(plugin)` must
  exist but the suite does not depend on any non-default plugin.
