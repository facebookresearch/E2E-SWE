# HTTP Mock & Validation Engine

Build the **HTTP engine** for an OpenAPI-driven mock server: given an OpenAPI (v2 or v3)
description, a request, and a configuration, it resolves the request to an operation, validates it,
enforces security, and produces a mocked HTTP response — all in-process, with no network I/O.

Your code lives under `src/` and its root entry point is `src/index.ts`. The grading suite imports
that entry (as a module named `prismhttp`) and drives the engine exclusively through the single
high-level function described below, asserting on the **observable HTTP result** (status code,
`Content-type`, body, the validation record, and — for rejected requests — the numeric HTTP status
carried by the error). How you organise the code beneath `src/index.ts` is entirely up to you.

## What is already provided

You do **not** need to implement or install any of the following — they are pre-installed and
importable:

- The full npm dependency tree (JSON-Schema tooling, a fake-data generator, a content-negotiation
  helper, `lodash`, `fp-ts`, `content-type`, etc.).
- A **platform core package**, importable as `@stoplight/prism-core`, that supplies the generic
  request-pipeline machinery. In particular it exports:
  - `factory(defaultConfig, components)` — builds a Prism instance. The returned instance exposes
    `request(input, resources)`, a `TaskEither`-returning thunk (call it, then `await` it) that runs
    your components in order: **route → validate input → validate security → mock (or forward) →
    validate output**.
  - `createLogger(name, opts)` — a `pino`-style logger (the suite passes a disabled one).
  - Types such as `IPrismOutput`, `IPrismComponents`, `IPrismDiagnostic`.
- OpenAPI parsing: use the provided `@stoplight/http-spec` transformers together with a JSON-Schema
  `$ref` dereferencer to turn a spec (file path **or** in-memory object) into an array of resolved
  `IHttpOperation` objects (`@stoplight/types`). Expose this as `getHttpOperationsFromSpec(spec)`.

The grader compiles your `src/` itself, with the project's own TypeScript configuration
(`module: commonjs`, `allowSyntheticDefaultImports` on, **`esModuleInterop` off**) — your own
`tsconfig.json` and any build output are not used. Import the CommonJS dependencies as
`import * as x from 'x'` (or `require('x')`); a default import `import x from 'x'` type-checks under
that configuration but resolves to `undefined` at run time.

You implement the HTTP-specific components (router, input/output/security validators, mocker,
forwarder) and the entry that wires them to `factory`.

## The entry contract

`src/index.ts` must export:

```ts
async function createAndCallPrismInstanceWithSpec(
  spec: string | object,          // OpenAPI 2/3 document, as a path or an in-memory object
  config: IHttpConfig,            // see below
  request: IHttpRequest,          // see below
  logger: Logger,                 // from createLogger
): Promise<PrismOkResult | PrismErrorResult>
```

with the result shapes:

```ts
type PrismOkResult    = { result: 'ok';    response: IPrismOutput<IHttpResponse> };
type PrismErrorResult = { result: 'error'; error: Error };
```

`IPrismOutput` (from the core package) carries `output` (the `IHttpResponse` = `{ statusCode,
headers, body }`) and `validations` (`{ input: IPrismDiagnostic[], output: IPrismDiagnostic[] }`).
On the error branch, `error` is an `Error` that also carries a **numeric `status`** property equal to
the HTTP status the failure maps to (e.g. `404`, `422`).

You must also export `createInstance(config, components)` (a thin wrapper over `factory` that
supplies your default components) and `getHttpOperationsFromSpec`.

### Request / config shapes

```ts
interface IHttpRequest {
  method: string;                                   // case-insensitive
  url: { path: string; baseUrl?: string; query?: Dictionary<string | string[]> };
  headers?: Dictionary<string>;
  body?: unknown;
}
// config used by the suite (a "mock" config):
interface IHttpConfig {
  validateRequest: boolean; checkSecurity: boolean; validateResponse: boolean;
  errors: boolean; isProxy: boolean; upstreamProxy?: unknown;
  mock: { dynamic: boolean; code?: number; exampleKey?: string;
          mediaTypes?: string[]; ignoreExamples?: boolean };
}
```

## Behaviour to implement

### 1. Routing & disambiguation

- A request path matches an operation path **segment by segment**. A templated segment `{param}`
  matches any single non-empty segment; a concrete segment must match literally. The two paths must
  have the **same number of segments** (different counts never match).
- Method matching is **case-insensitive**.
- When several operations match one request, disambiguate by preferring **concrete (literal)
  segments over templated ones**: the candidate that aligns more of the request with literal segments
  wins, and a fully-concrete path always beats a templated path that also matches.
- If a `baseUrl` is supplied on the request and the operation declares `servers`, the base URL must
  match one of them (host + base path); a concrete server match is preferred over a templated one.
  When no `baseUrl` is supplied, server matching is skipped entirely.
- Failure statuses (returned on the error branch): unknown path → **404**; path matched but the
  method is not defined → **405**; `baseUrl` supplied but no declared server matches → **404**.

### 2. Response selection & body generation (mocker)

- **Status code** (when the caller does not force one): choose the **lowest `2xx`** response; if
  there is none, use a `default` response (served as status **200**); otherwise use the **first**
  declared response. A range code like `2XX` is normalised to `200`. If the caller sets `mock.code`,
  select that response: match it exactly, else against a matching range response (e.g. `404` matches
  a `4XX` response, served as `404`), else fall back to the `default` response served with the
  requested code.
- **Body** in static mode (`mock.dynamic === false`): if the chosen media type defines named
  `examples`, return the **first** one's value; else if it defines a single `example`, return it;
  otherwise **generate a canonical value from the schema** — deterministically, honouring the
  schema's own `example`, and otherwise producing a stable representative value (e.g. the **first**
  `enum` member for an enum schema). `mock.exampleKey` selects a named example by key; if that key
  does not exist the request is rejected with **404**. `mock.ignoreExamples === true` skips examples
  and always generates from the schema.
- In dynamic mode (`mock.dynamic === true`), generate a value from the schema that conforms to the
  declared types (required object properties present, correct primitive types).
- The response's `Content-type` header is set to the negotiated media type. When the matched
  operation is marked `deprecated`, the response also carries a `deprecation: 'true'` header.
- A `HEAD` request selects a response as usual but returns **no body**.

### 3. Content negotiation

- The request `Accept` header (comma-separated, honouring `q` quality values and wildcards) chooses
  which of the response's media types to serve. With **no** `Accept` header, default to
  `application/json`.
- `*/*` in `Accept` matches any available representation.
- If the client asks for a media type the response cannot produce **and** the response defines a
  body, reject with **406**.
- A response whose **only** declared media type is `*/*` can produce any representation, so it
  satisfies any `Accept` value (including the `application/json` default) and is **never** rejected
  with 406.

### 4. Request validation

- Validate query/path/header parameters and the request body against their schemas, applying the
  full JSON Schema (nested `required`, `enum`, `minLength`/`pattern`, numeric `minimum`/`maximum`,
  type coercion of string-encoded scalars, etc.). A scalar parameter supplied as an array is a type
  violation.
- Parameters are deserialized per their OpenAPI `style`/`explode` before validation: form arrays
  (exploded), delimited arrays (`pipeDelimited`, `spaceDelimited`), and `deepObject` objects
  (`name[prop]=value`).
- Unknown query parameters are ignored.
- On a validation failure, first try to mock a **spec-defined error response** (a `422` or `400`
  for a generic violation): if the operation declares one, return it on the **ok** branch with that
  status and body. Only when no such response exists, reject with a synthesised **422**.
- A valid request passes with `validations.input === []`.

### 5. Security

- An operation's security requirement list is an **OR of ANDs**: the outer list is alternatives, and
  each alternative is a set of schemes that must **all** be satisfied. The request is authorised if
  **any one** alternative is fully satisfied. Credential presence (e.g. an `apiKey` header) is
  detected by header/query/cookie name, case-insensitively.
- A failing security check rejects with **401** — unless the operation declares a `401` response, in
  which case that response is mocked (ok branch, status 401).

### 6. Response validation

- When `validateResponse` is on, validate the produced response body/headers against the matched
  response definition. With `errors: false`, response-level violations are recorded but do not turn a
  successful mock into a transport error.

## Notes

- Everything runs offline and synchronously with respect to I/O; no HTTP calls are made for mocking.
- Grading is on observable output only — status codes, `Content-type`, bodies, the `validations`
  record, and `error.status`. Internal type names, error message text, and module layout are not
  inspected.
