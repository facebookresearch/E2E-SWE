// Hidden WRG grading suite for the Vento template engine.
// Curated from ventojs/vento's real, verified {template, expected} pairs.
// Flat Deno.test cases only (no t.step); the JUnit count == lines in expected.txt.
//
// Imports the model's engine from /app/mod.ts. Assertions come from the offline
// pre-cached jsr:@std/assert@1.0.19. The include loader is a self-contained
// in-memory Loader (resolve + load), mirroring vento's test loader, including a
// minimal YAML front-matter extractor (no external deps).

import tmpl from "/app/mod.ts";
import { assertEquals } from "jsr:@std/assert@1.0.19/equals";
import { assertRejects } from "jsr:@std/assert@1.0.19/rejects";

// deno-lint-ignore no-explicit-any
type Any = any;

// ---------- in-memory include loader ----------
function normalize(path: string): string {
  const segs: string[] = [];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") segs.pop();
    else segs.push(part);
  }
  return "/" + segs.join("/");
}
function dirname(p: string): string {
  const i = p.lastIndexOf("/");
  return i <= 0 ? "/" : p.slice(0, i);
}
function frontmatter(
  src: string,
): { source: string; data: Record<string, unknown> } {
  const m = /^\s*---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
  if (!m) return { source: src, data: {} };
  const data: Record<string, unknown> = {};
  for (const line of m[1].split(/\r?\n/)) {
    const mm = /^\s*([A-Za-z0-9_$-]+)\s*:\s*(.*?)\s*$/.exec(line);
    if (!mm) continue;
    let v: unknown = mm[2];
    if (v === "true") v = true;
    else if (v === "false") v = false;
    else if (/^-?\d+$/.test(v as string)) v = Number(v);
    data[mm[1]] = v;
  }
  return { source: src.slice(m[0].length), data };
}
class MemoryLoader {
  #files: Record<string, string>;
  constructor(files: Record<string, string> = {}) {
    this.#files = files;
  }
  resolve(from: string, file: string): string {
    if (file.startsWith(".")) {
      return normalize(dirname(from || "/") + "/" + file);
    }
    return normalize(file);
  }
  // deno-lint-ignore require-await
  async load(file: string) {
    const src = this.#files[file];
    if (src === undefined) throw new Error(`Template not found: ${file}`);
    return frontmatter(src);
  }
}

// ---------- test helpers ----------
interface TestOptions {
  template: string;
  data?: Record<string, unknown>;
  filters?: Record<string, (this: Any, ...args: Any[]) => unknown>;
  expected: string;
  init?: (env: Any) => void;
  includes?: Record<string, string>;
  options?: Record<string, unknown>;
}

function build(options: Omit<TestOptions, "expected">) {
  const env = tmpl({
    includes: new MemoryLoader(options.includes || {}),
    ...(options.options || {}),
  });
  options.init?.(env);
  if (options.filters) {
    for (const [name, filter] of Object.entries(options.filters)) {
      env.filters[name] = filter;
    }
  }
  return async () => await env.runString(options.template, options.data);
}

async function test(options: TestOptions) {
  const result = await build(options)();
  assertEquals(result.content.trim(), options.expected.trim());
}

function testThrows(options: Omit<TestOptions, "expected">) {
  return assertRejects(build(options));
}

// ============================================================
// Output / expressions
// ============================================================
Deno.test("print: nullish coalescing default", async () => {
  await test({
    template: `{{ message ?? "no" }}`,
    expected: "no",
    data: {},
  });
});

Deno.test("print: undeclared variable renders empty", async () => {
  await test({
    template: `{{ foo }}`,
    expected: "",
  });
});

Deno.test("print: trim markers on both sides", async () => {
  await test({
    template: `Hello {{- "World" -}} !`,
    expected: "HelloWorld!",
  });
});

Deno.test("print: decrement expression with left trim", async () => {
  await test({
    template: `
    {{> let foo = -2 }}
    1 + 1 = {{--foo}}
    `,
    expected: "1 + 1 =2",
  });
});

// ============================================================
// Filter pipeline |>
// ============================================================
Deno.test("filter: method toUpperCase", async () => {
  await test({
    template: `{{ message |> toUpperCase }}`,
    expected: "HELLO WORLD",
    data: { message: "Hello World" },
  });
});

Deno.test("filter: chained toString then toUpperCase on number", async () => {
  await test({
    template: `{{ message |> toString |> toUpperCase }}`,
    expected: "12",
    data: { message: 12 },
  });
});

Deno.test("filter: chained methods on undefined", async () => {
  await test({
    template: `{{ message |> toString |> toUpperCase }}`,
    expected: "",
  });
});

Deno.test("filter: custom registered slugify", async () => {
  await test({
    template: `{{ message |> slugify }}`,
    expected: "hello-world",
    data: { message: "Hello World" },
    init(env) {
      env.filters.slugify = (value: string) =>
        value.toLowerCase().replace(/\s/g, "-");
    },
  });
});

// ============================================================
// escape / unescape / safe
// ============================================================
Deno.test("escape: HTML entities", async () => {
  await test({
    template: `{{ "<h1>Hello world</h1>" |> escape }}`,
    expected: "&lt;h1&gt;Hello world&lt;/h1&gt;",
  });
});

Deno.test("escape: JSON.stringify then escape", async () => {
  await test({
    template: `{{ object |> JSON.stringify |> escape }}`,
    expected: "{&quot;bar&quot;:23}",
    data: { object: { bar: 23 } },
  });
});

Deno.test("unescape: named entities", async () => {
  await test({
    template: `{{ "&lt;h1&gt;Hello world&lt;/h1&gt;" |> unescape }}`,
    expected: "<h1>Hello world</h1>",
  });
});

Deno.test("safe: overrides autoescape", async () => {
  await test({
    options: { autoescape: true },
    template: `{{ "<h1>Hello world&lt;/h1&gt;" |> safe }}`,
    expected: "<h1>Hello world&lt;/h1&gt;",
  });
});

// ============================================================
// empty filter
// ============================================================
Deno.test("empty: NaN is empty", async () => {
  await test({
    template: `NaN: {{ NaN |> empty }}`,
    expected: "NaN: true",
  });
});

Deno.test("empty: negated whitespace-only string", async () => {
  await test({
    template: String.raw`Whitespace only: {{ " \n\t " |> !empty }}`,
    expected: "Whitespace only: false",
  });
});

Deno.test("empty: Date is not empty", async () => {
  await test({
    template: `Object 3: {{ new Date() |> empty }}`,
    expected: "Object 3: false",
  });
});

// ============================================================
// for
// ============================================================
Deno.test("for: number with key var", async () => {
  await test({
    template: `{{ for key, number of 3 }}{{number}}({{key}}) - {{ /for }}`,
    expected: "1(0) - 2(1) - 3(2) -",
  });
});

Deno.test("for: object with key var", async () => {
  await test({
    template:
      `{{ for key, name of { one: "1", two: "2" } }}{{name}}({{key}})-{{ /for }}`,
    expected: "1(one)-2(two)-",
  });
});

Deno.test("for: destructured object props", async () => {
  await test({
    template:
      `{{ for {name, value} of items }}{{ name }}:{{ value }}-{{ /for }}`,
    expected: "one:2-two:4-three:6-",
    data: {
      items: [
        { name: "one", value: 2 },
        { name: "two", value: 4 },
        { name: "three", value: 6 },
      ],
    },
  });
});

Deno.test("for: nested array destructuring", async () => {
  await test({
    template: `{{ for [[n]] of [[[1]], [[2]]] }}{{ n }}{{ /for }}`,
    expected: "12",
  });
});

Deno.test("for: source with pipe filter", async () => {
  await test({
    template: `{{ for name of [1, 2, 3] |> double }}{{ name }}-{{ /for }}`,
    expected: "2-4-6-",
    filters: {
      double: (values: number[]) => values.map((value) => value * 2),
    },
  });
});

Deno.test("for: source with inline method filter", async () => {
  await test({
    template:
      `{{ for name of [1, 2, 3] |> filter(n => n === 2) }}{{ name }}-{{ /for }}`,
    expected: "2-",
  });
});

Deno.test("for: classic C-style loop", async () => {
  await test({
    template: `{{ for let i = 0; i < 10; i += 2 }}{{ i }}{{ /for }}`,
    expected: "02468",
  });
});

Deno.test("for: continue", async () => {
  await test({
    template:
      `{{ for n of [1, 2, 3, 4] }}{{ if n == 3 }}{{ continue }}{{ /if }}{{ n }}{{ /for }}`,
    expected: "124",
  });
});

// ============================================================
// if
// ============================================================
Deno.test("if: else-if chain", async () => {
  await test({
    template: `
    {{ if name == "Óscar" }}
      <p>Is Óscar</p>
    {{ else if name == "Laura" }}
      <p>Is Laura</p>
    {{ /if }}
    `,
    expected: "<p>Is Laura</p>",
    data: { name: "Laura" },
  });
});

Deno.test("if: condition with pipe filter", async () => {
  await test({
    template: `
    {{ if "one" |> isOne }}<p>True</p>{{ /if }}
    {{ if "two" |> isOne }}<p>True</p>{{ /if }}
    `,
    filters: {
      isOne: (value: string) => value === "one",
    },
    expected: "<p>True</p>",
  });
});

Deno.test("if: multiline condition", async () => {
  await test({
    template: `
    {{ if names
        .length > 0 }}
      <p>True</p>
    {{ /if }}
    `,
    expected: "<p>True</p>",
    data: { names: ["Óscar", "Laura"] },
  });
});

// ============================================================
// set
// ============================================================
Deno.test("set: block capture", async () => {
  await test({
    template: `
    {{ set message }}
      Hello world
    {{ /set }}

    {{ message }}
    `,
    expected: "Hello world",
  });
});

Deno.test("set: value with pipe join", async () => {
  await test({
    template: `
    {{ set message = ["Hello", "world"] |> join(" ") }}
    {{ message }}
    `,
    expected: "Hello world",
  });
});

Deno.test("set: destructuring with rest", async () => {
  await test({
    template: `
    {{ set { one, ...other } = { one: 1, two: 2, three: 3 } }}
    {{ one }} {{ other.two }} {{ other.three }}
    `,
    expected: "1 2 3",
  });
});

Deno.test("set: nested object destructuring", async () => {
  await test({
    template: `
    {{ set { a, b: { c, d } } = { a: "A", b: { c: "C", d: "D" } } }}
    {{ a }} {{ c }} {{ d }}
    `,
    expected: "A C D",
  });
});

// ============================================================
// function / import
// ============================================================
Deno.test("function: default parameter", async () => {
  await test({
    template: `
    {{ function hello (name = "World") }}Hello {{ name }}{{ /function }}

    {{ hello() }} / {{ hello("Vento") }}
    `,
    expected: "Hello World / Hello Vento",
  });
});

Deno.test("function: hoisting", async () => {
  await test({
    template: `
    {{ hello("world") }}

    {{ function hello(name) }}
    {{ name }}
    {{ /function }}
    `,
    expected: "world",
  });
});

Deno.test("function: scope isolation of nested declarations", async () => {
  await test({
    template: `
    {{ function hello }}
      {{ function inner }}
        {{> const message = "I shouldn't print" }}
      {{ /function }}
    {{ /function }}

    {{> const message = "Hello world" }}

    {{ message }} / {{ inner ?? "Doesn't exist" }} / {{ hello ? "Exists" : "Doesn't exist" }}
    `,
    expected: "Hello world / Doesn't exist / Exists",
  });
});

Deno.test("function: autoescape and safe interplay", async () => {
  await test({
    template: `
    {{ hello("world") }}

    {{ function hello(name) }}
      <strong>{{ name }}</strong>-{{ "<strong>world</strong>" |> safe }}-{{ "<strong>world</strong>" }}
    {{ /function }}
    `,
    expected:
      "<strong>world</strong>-<strong>world</strong>-&lt;strong&gt;world&lt;/strong&gt;",
    options: { autoescape: true },
  });
});

Deno.test("import: aliased export and import", async () => {
  await test({
    template: `
    {{ import { hi as hey } from "/my-file.vto" }}
    {{ hey }}
    `,
    expected: "Hello Vento",
    data: { name: "Vento" },
    includes: {
      "/my-file.vto": `
      {{ set hello = "Hello " + name }}
      {{ export { hello as hi } }}
      `,
    },
  });
});

// ============================================================
// include
// ============================================================
Deno.test("include: basic", async () => {
  await test({
    template: `{{ include "/my-file.vto" }}`,
    expected: "Hello world",
    includes: { "/my-file.vto": "Hello world" },
  });
});

Deno.test("include: relative nested with filters", async () => {
  await test({
    template: `{{ include "/sub/my-file.vto" |> replace(" ", "-") }}`,
    expected: "HELLO-WORLD",
    includes: {
      "/sub/my-file.vto": "{{ include './other-file.vto' |> toUpperCase }}",
      "/sub/other-file.vto": "Hello world",
    },
  });
});

Deno.test("include: with custom inline data", async () => {
  await test({
    template: `{{ include "/my-file.vto" {salute: "Good bye"} }}`,
    expected: "Good bye world",
    includes: { "/my-file.vto": "{{ salute }} {{ name }}" },
    data: { salute: "Hello", name: "world" },
  });
});

Deno.test("include: object shorthand data", async () => {
  await test({
    template: `{{ include "/my-file.vto" { name } }}`,
    expected: "Hello Vento",
    includes: { "/my-file.vto": "Hello {{ name }}" },
    data: { name: "Vento" },
  });
});

Deno.test("include: front matter data", async () => {
  await test({
    template: `{{ include "/my-file.vto" }}`,
    expected: "Hello from front matter",
    includes: {
      "/my-file.vto": `---
salute: Hello from front matter
---
      {{ salute }}
      `,
    },
  });
});

// ============================================================
// layout / slots
// ============================================================
Deno.test("layout: basic content", async () => {
  await test({
    template: `{{ layout "/my-file.vto" }}Hello world{{ /layout }}`,
    expected: "<h1>Hello world</h1>",
    includes: { "/my-file.vto": "<h1>{{ content }}</h1>" },
  });
});

Deno.test("layout: nested layouts", async () => {
  await test({
    template:
      `{{ layout "/my-file.vto" }}{{ layout "/my-file.vto" }}Hello world{{ /layout }}{{ /layout }}`,
    expected: "<h1><h1>Hello world</h1></h1>",
    includes: { "/my-file.vto": "<h1>{{ content }}</h1>" },
  });
});

Deno.test("layout: with filter on rendered output", async () => {
  await test({
    template:
      `{{ layout "/my-file.vto" |> toUpperCase }}Hello world{{ /layout }}`,
    expected: "<h1>HELLO WORLD</h1>",
    includes: { "/my-file.vto": "<h1>{{ content }}</h1>" },
  });
});

Deno.test("layout: named slots", async () => {
  await test({
    template: `
    {{ layout "/my-file.vto" }}
      {{ slot greeting }}Hello{{ /slot }}
      {{ slot target }}world{{ /slot }}
    {{ /layout }}
    `,
    expected: "Hello world",
    includes: { "/my-file.vto": "{{ greeting }} {{ target }}" },
  });
});

Deno.test("layout: same-named slots with filters concatenate", async () => {
  await test({
    template: `
    {{ layout "/my-file.vto" { target: "world" } }}
      {{ slot message |> toLowerCase() }}HELLO {{ /slot }}
      {{ slot message |> toUpperCase() }}world{{ /slot }}
    {{ /layout }}
    `,
    expected: "hello WORLD",
    includes: { "/my-file.vto": "{{ message }}" },
  });
});

// ============================================================
// echo / comment / inline JS
// ============================================================
Deno.test("echo: block preserves inner tags literally", async () => {
  await test({
    template: `{{echo}} Hello {{ world }} {{/echo}}`,
    expected: "Hello {{ world }}",
  });
});

Deno.test("echo: block with filter", async () => {
  await test({
    template: `{{echo |> toUpperCase }} Hello {{ world }} {{/echo}}`,
    expected: "HELLO {{ WORLD }}",
  });
});

Deno.test("echo: trim markers", async () => {
  await test({
    template: `Hello {{-echo-}} beautiful {{-/echo-}} world!`,
    expected: "Hellobeautifulworld!",
  });
});

Deno.test("comment: trims both sides", async () => {
  await test({
    template: `<h1> {{#- -#}} </h1>`,
    expected: "<h1></h1>",
  });
});

Deno.test("js: object spread piped to JSON.stringify", async () => {
  await test({
    template: "{{ {...foo} |> JSON.stringify }}",
    data: { foo: { bar: 23 } },
    expected: `{"bar":23}`,
  });
});

// ============================================================
// default / errors
// ============================================================
Deno.test("default: sets only undefined values", async () => {
  await test({
    template: `
    {{ set greeting = "Hello" }}
    {{ default message = "Hi" }}
    {{ default target = "world" }}
    {{ greeting }} {{ target }}
    `,
    expected: "Hello world",
  });
});

Deno.test("strict: throws on undefined variable", async () => {
  await testThrows({
    options: { strict: true },
    template: `
      {{ hello }}
    `,
  });
});

Deno.test("autoDataVarname false throws on bare identifier", async () => {
  await testThrows({
    options: { autoDataVarname: false },
    template: `
    Hello {{ world }}
    `,
    data: { world: "world" },
  });
});

Deno.test("include: infinite nesting rejects", async () => {
  await testThrows({
    template: `
    {{ include "/nest.vto" { depth: 10_000 } }}
    `,
    includes: {
      "/nest.vto": `
        {{ if depth > 0 }}
          {{ include "/nest.vto" { depth: depth - 1 } }}
        {{ else }}
          Bottom reached!
        {{ /if }}
      `,
    },
  });
});

// ============================================================ enrichment: fail-area concentration
Deno.test("filter: array method chain then registered filter", async () => {
  await test({
    template: `
    {{ set foo = arr.filter(a => a !== 'bar') |> filt }}

    {{ foo }}
    `,
    expected: "FOO BAZ",
    data: { arr: ["foo", "bar", "baz"] },
    filters: { filt: (arr: string[]) => arr.map((a) => a.toUpperCase()).join(" ") },
  });
});

Deno.test("filter: async registered getAsync", async () => {
  await test({
    template: `<{{ "foo" |> getAsync }}>`,
    expected: "<FOO>",
    filters: {
      async getAsync(text: string) {
        return await new Promise((resolve) => setTimeout(() => resolve(text.toUpperCase()), 10));
      },
    },
  });
});

Deno.test("escape: number passes through unchanged", async () => {
  await test({ template: `{{ 100 |> escape }}`, expected: "100" });
});

Deno.test("filter: block capture with toUpperCase", async () => {
  await test({
    template: `
    {{ set message |> toUpperCase }}
      Hello {{ if true }}world{{ /if }}
    {{ /set }}

    {{ message }}
    `,
    expected: "HELLO WORLD",
  });
});

Deno.test("layout: outer filter over inner content filter", async () => {
  await test({
    template: `{{ layout "/my-file.vto" |> toUpperCase }}Hello world{{ /layout }}`,
    expected: "<h1>hello world</h1>",
    includes: { "/my-file.vto": "<h1>{{ content |> toLowerCase }}</h1>" },
  });
});

Deno.test("layout: extra data object with filter", async () => {
  await test({
    template: `
    {{ layout "/my-file.vto" {
      tag: "h1"
    } |> toUpperCase }}Hello world{{ /layout }}
    `,
    expected: "<h1>HELLO WORLD</h1>",
    includes: { "/my-file.vto": "<{{ tag }}>{{ content }}</{{ tag }}>" },
  });
});

Deno.test("layout: autoescape filter escapes rendered content", async () => {
  await test({
    template: `
    {{ layout "/my-file.vto" |> toUpperCase }}Hello <strong>world</strong>{{ /layout }}
    `,
    expected: "<h1>HELLO <STRONG>WORLD</STRONG></h1>",
    options: { autoescape: true },
    includes: { "/my-file.vto": "<h1>{{ content }}</h1>" },
  });
});

Deno.test("layout: same-named greeting slots wrap element", async () => {
  await test({
    template: `
    {{ layout "/my-file.vto" { target: "world" } }}
      {{- slot greeting }}<em>Hello{{ /slot -}}
      world
      {{- slot greeting }}</em>{{ /slot -}}
    {{ /layout }}
    `,
    expected: "<em>Hello</em> world",
    options: { autoescape: true },
    includes: { "/my-file.vto": "{{ greeting }} {{ content }}" },
  });
});

Deno.test("layout: slot filter over nested echo filter", async () => {
  await test({
    template: `
    {{ layout "/base.vto" }}
      {{ slot greeting |> toLowerCase }}
        {{ echo |> toUpperCase }}
          Hello world
        {{ /echo }}
      {{ /slot }}
    {{ /layout }}
    `,
    expected: "hello world",
    includes: { "/base.vto": "{{ greeting |> trim }}" },
  });
});

Deno.test("function: async function tag with await", async () => {
  await test({
    template: `
    {{ async function hello }}
    {{> const text = await Promise.resolve("Hello world") }}
    {{ text }}
    {{ /function }}

    {{ await hello() }}
    `,
    expected: "Hello world",
  });
});

Deno.test("function: parameter reassignment stays local", async () => {
  await test({
    template: `
    {{ function hello(name) -}}
    {{> name = "Hello world!" }}
    {{- name -}}
    {{ /function }}

    {{ name ?? "No name" }} / {{ hello("world") }}
    `,
    expected: "No name / Hello world!",
  });
});

Deno.test("function: export scope isolation hides const", async () => {
  await test({
    template: `
    {{ export function hello }}
    {{> const message = "Hello world" }}
    {{ /export }}

    {{ message }}
    `,
    expected: "",
  });
});

Deno.test("function: autoescape false leaves safe and raw intact", async () => {
  await test({
    template: `
    {{ hello("world") }}

    {{ function hello(name) }}
      <strong>{{ name }}</strong>-{{ "<strong>world</strong>" |> safe }}-{{ "<strong>world</strong>" }}
    {{ /function }}
    `,
    expected: "<strong>world</strong>-<strong>world</strong>-<strong>world</strong>",
    options: { autoescape: false },
  });
});

Deno.test("function: return value not string under autoescape", async () => {
  await test({
    template: `
    {{ typeof hello() === "string" ? "true" : "false" }}

    {{ function hello }}
      Hello
    {{ /function }}
    `,
    expected: "false",
    options: { autoescape: true },
  });
});
