# ts-json-schema-generator

Build `ts-json-schema-generator`, a TypeScript library and CLI that generates draft-07 JSON Schema from TypeScript type definitions. It parses TypeScript source with the compiler API, builds an intermediate type representation, formats it to JSON Schema, and outputs a schema with definitions and $ref links.

## Dependencies

- Node 20 runtime. TypeScript compiler is provided and pinned at `/opt/toolchain` — use that version, do not install from npm. Build with `tsc` or `npm run build` offline.
- Runtime npm dependencies preinstalled: `typescript`, `commander`, `glob`, `json5`, `normalize-path`, `safe-stable-stringify`, `tslib`, `@types/json-schema`.
- No network access.

## Project Location

Your working directory is `/app`. Place your implementation in `/app` and ensure `setup.sh` builds and installs the package from `/app` offline via `npm run build` or `tsc` followed by `npm link` or equivalent local install. The grader runs tests importing from the package name after setup.

## Package Structure

Programmatic entry from package root:

```ts
import { createGenerator, createProgram, createParser, createFormatter, SchemaGenerator } from 'ts-json-schema-generator'
import type { Config, Definition } from 'ts-json-schema-generator'
```

CLI binary `ts-json-schema-generator` invokes the CLI module. Tests import from package root only.

## API Reference

### Programmatic

`createGenerator(config: Config): SchemaGenerator`

`createProgram(config): ts.Program` — respects tsconfig, path, skipTypeCheck.

`createParser(program, config, nodeParser?)` and `createFormatter(config, nodeParser?)` construct parser and formatter chains.

`new SchemaGenerator(program, nodeParser, typeFormatter, config?)` then `createSchema(fullTypeName?: string): Definition` returns JSON Schema draft-07. Uses config.type if argument omitted; throws if neither provided.

### Config

- `path: string` — glob or file, required for CLI `-p`.
- `type: string` — root type name, required for CLI `-t`.
- `tsconfig?: string`
- `expose?: 'all'|'none'|'export'` default `'export'`. Controls which types become top-level definitions versus inlined.
- `topRef?: boolean` default true. True emits root as `{$ref:'#/definitions/Name'}`; false inlines root.
- `jsDoc?: 'none'|'basic'|'extended'` default `'extended'`.
- `markdownDescription?: boolean` default false.
- `sortProps?: boolean` default true. Properties emit in declaration order; required arrays in merged intersections are sorted.
- `strictTuples?: boolean` default false. When true tuples enforce exact length via minItems/maxItems.
- `skipTypeCheck?: boolean` default false.
- `encodeRefs?: boolean` default true. URL-encodes $ref values, not definition keys.
- `extraTags?: string[]` — additional JSDoc tags treated as annotations.
- `additionalProperties?: boolean` default false.
- `discriminatorType?: 'json-schema'|'open-api'` default `'json-schema'`.
- `functions?: 'fail'|'comment'|'hide'` default `'comment'`.
- `schemaId?: string` — sets $id.
- `minify?: boolean` default false.
- `fullDescription?: boolean` default false.
- `tsProgram?: ts.Program` — supply existing program programmatically.

### CLI

```
ts-json-schema-generator -p <path> -t <type> [options]
```

Flags: `-p --path`, `-t --type`, `-i --id`, `-f --tsconfig`, `-e --expose`, `-j --jsDoc`, `--markdown-description`, `--full-description`, `--functions`, `--minify`, `--unstable` sets sortProps false, `--strict-tuples`, `--no-top-ref`, `--no-type-check`, `--no-ref-encode`, `-o --out`, `--validation-keywords` for extraTags, `--additional-properties`. No CLI flags for discriminatorType or tsProgram; use programmatic API.

Output JSON to stdout unless `-o` specified.

### Output format

Always draft-07:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "...",
  "$ref": "#/definitions/Root",
  "definitions": { ... }
}
```

Key order fixed: optional $id, then $schema, then root $ref or inlined properties, then definitions. Definitions contain deduplicated types only; unreachable definitions are pruned. $ref uses `#/definitions/Name` form, URL-encoded when encodeRefs true. Definition keys themselves are not encoded.

Shared and recursive types emit $ref rather than inline duplication. Generic instantiations produce distinct schemas per argument set, each keyed by the TypeScript type expression `Name<Arg1, Arg2, ...>`. Each type argument is rendered in its checker-resolved form, so an awaited or conditional-inferred argument collapses to its resolved inner type in the key.

### Parsing and formatting

Parser walks TypeScript AST using compiler API and dispatches by syntax kind to specialized sub-parsers covering declarations, operators, references, keywords, literals, expressions, functions, mapped types, conditional types with infer, indexed access, template literals, and more. Decorators add JSDoc, expose filtering, circular handling, and topRef wrapping. Results are memoized per node and context.

Formatter dispatches by intermediate type class to sub-formatters, with a circular reference handler that caches before recursing to avoid infinite loops.

Emitted shapes:

- Object types emit type object with properties in declaration order, required array, and additionalProperties boolean defaulting false unless index signature or config overrides. A type that declares no properties omits the `properties` key entirely rather than emitting an empty object.
- Unions emit anyOf unless discriminated; a union of only primitive types (e.g. `string | number | null`) instead collapses to a single schema whose `type` is the array of those primitive type names.
- `keyof` over an object type yields a string schema with an `enum` of the property names.
- Discriminated unions (a union annotated with `@discriminator <prop>`) do NOT use `anyOf`. With discriminatorType `json-schema` the union definition is an object carrying `type: "object"`, a `properties.<prop>` holding an `enum` of the discriminator literal values, `required: ["<prop>"]`, and an `allOf` array; each `allOf` entry is `{ "if": { "properties": { "<prop>": { "type": "string", "const": "<value>" } } }, "then": { "$ref": "#/definitions/<Member>" } }` in member declaration order. With discriminatorType `open-api` the union definition is an object with `type: "object"`, `discriminator: { "propertyName": "<prop>" }`, `required: ["<prop>"]`, and `oneOf` of `$ref`s to the members (no if/then).
- Intersections of object types are merged into a single object schema (not `allOf`): the merged `properties` and `required` are emitted in sorted (alphabetical) order, and `additionalProperties` is false. `allOf` is only used when a member cannot be structurally merged (e.g. it is a `$ref` or union).
- Tuples: fixed elements are emitted as an `items` array (one schema per position) with `minItems` equal to the number of required leading elements; a rest element `...T[]` becomes `additionalItems` (its element schema). Named/labeled tuple members (`[first: number, ...]`) emit their label as a `title` on the element schema. `strictTuples` true adds `maxItems`; a fixed-length tuple with no rest also emits `maxItems`.
- Enums: single value becomes const, multiple becomes enum. String-literal-union type aliases (`"a" | "b"`) behave the same as string enums — a string schema with an `enum`. Literals similarly.
- Template-literal types (e.g. `` `/api/${string}` ``) collapse to a plain `{"type":"string"}` schema; the template placeholders are discarded and no `pattern` is generated from them.
- Utility types resolve to their computed shape: `Partial<T>` makes every property optional (no `required`), `Pick<T,K>`/`Omit<T,K>` emit the selected/remaining properties, `Record<K,V>` emits an object with typed `additionalProperties`. `readonly` modifiers are ignored.
- Required array computed from TypeScript optionality, mapped type modifiers, Partial, and intersection merging.

### Annotations

JSDoc tags from an allowlist map to JSON Schema keywords. Text tags and JSON5-parsed tags supported. Dollar-prefixed tags @id @comment @ref map to schema fields. Extended mode includes description text, @asType, @example, @nullable. `@nullable` reshapes the annotated property's type to allow null: a primitive becomes a `type` array including `"null"` (e.g. `{"type":["string","null"]}`). Annotations override generated fields on merge.

### TypeScript checker usage

Implementation creates a TypeScript Program and uses type checker for symbol and alias resolution, un-annotated member type inference, enum constant value folding, assignability checks, and awaited type resolution. Utility logic handles conditional type narrowing, mapped type key extraction, indexed access dereferencing, and type dereferencing for correctness.

### Behavior tests assert

- Required properties match TypeScript optionality across intersections, mapped types, Partial and optional modifiers.
- additionalProperties defaults false; index signatures enable true or typed form.
- Discriminated unions encode per chosen discriminatorType.
- JSDoc annotations appear with correct precedence over inferred types.
- Expose modes control definitions versus inlining.
- topRef true wraps root in $ref; false inlines.
- encodeRefs true URL-encodes $ref strings.
- Regular object properties keep declaration order; merged-intersection properties and required arrays are sorted alphabetically.
- Circular and recursive types terminate via $ref and deduplicate shared types.
- Generic instantiations distinct per type arguments.
- Output validates as draft-07 and deep-equals expected fixtures.
