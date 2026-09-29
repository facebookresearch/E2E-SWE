// Mocker: once an operation is resolved, which response and which body does it produce?
//   * Response code (when the caller does not force one): the lowest 2xx wins; if there is no 2xx,
//     a `default` response is used (surfaced as 200); otherwise the first declared response is used.
//     Range codes like `2XX` are normalised to `200`.
//   * A caller may force a status code, selecting that response (or `default`).
//   * Body precedence in static mode: a media type's named `examples` (first one) or single
//     `example` is returned verbatim; with none, a value is generated from the schema (which honours
//     the schema's own `example`). Forcing `ignoreExamples` skips examples and generates instead.
//   * A specific named example can be selected by key.

import { call, expectOk } from './_helpers';

function op(responses: any): any {
  return { responses };
}
function spec(paths: any): any {
  return { openapi: '3.0.0', info: { title: 't', version: '1' }, paths };
}
function jsonResponse(fields: any): any {
  return { description: 'r', content: { 'application/json': fields } };
}

describe('mocker: response code selection', () => {
  it('selects the lowest 2xx response when several are defined', async () => {
    const s = spec({
      '/x': { get: op({
        '201': jsonResponse({ schema: { type: 'string' }, example: 'twoOhOne' }),
        '200': jsonResponse({ schema: { type: 'string' }, example: 'twoHundred' }),
      }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.statusCode).toBe(200);
    expect(out.body).toBe('twoHundred');
  });

  it('selects the lowest available 2xx even when 200 is absent', async () => {
    const s = spec({
      '/x': { get: op({
        '204': { description: 'no content' },
        '201': jsonResponse({ schema: { type: 'string' }, example: 'created' }),
      }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.statusCode).toBe(201);
    expect(out.body).toBe('created');
  });

  it('normalises a 2XX range code to 200', async () => {
    const s = spec({
      '/x': { get: op({
        '2XX': jsonResponse({ schema: { type: 'string' }, example: 'ranged' }),
      }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.statusCode).toBe(200);
  });

  it('uses the default response (as 200) when there is no 2xx', async () => {
    const s = spec({
      '/x': { get: op({
        'default': jsonResponse({ schema: { type: 'string' }, example: 'fallback' }),
      }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.statusCode).toBe(200);
    expect(out.body).toBe('fallback');
  });

  it('uses the first declared response when there is neither a 2xx nor a default', async () => {
    const s = spec({
      '/x': { get: op({
        '400': jsonResponse({ schema: { type: 'string' }, example: 'bad' }),
        '404': jsonResponse({ schema: { type: 'string' }, example: 'missing' }),
      }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.statusCode).toBe(400);
    expect(out.body).toBe('bad');
  });

  it('honours a caller-forced status code', async () => {
    const s = spec({
      '/x': { get: op({
        '200': jsonResponse({ schema: { type: 'string' }, example: 'ok200' }),
        '404': jsonResponse({ schema: { type: 'string' }, example: 'nope404' }),
      }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: false, code: 404 } }));
    expect(out.statusCode).toBe(404);
    expect(out.body).toBe('nope404');
  });
});

describe('mocker: body/example precedence (static)', () => {
  it('returns a single media-type example verbatim', async () => {
    const s = spec({
      '/x': { get: op({ '200': jsonResponse({ schema: { type: 'object' }, example: { hello: 'world' } }) }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.body).toEqual({ hello: 'world' });
  });

  it('returns the first named example when several are defined', async () => {
    const s = spec({
      '/x': { get: op({ '200': jsonResponse({
        schema: { type: 'string' },
        examples: {
          first: { value: 'the-first' },
          second: { value: 'the-second' },
        },
      }) }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.body).toBe('the-first');
  });

  it('selects a named example by key', async () => {
    const s = spec({
      '/x': { get: op({ '200': jsonResponse({
        schema: { type: 'string' },
        examples: {
          first: { value: 'the-first' },
          second: { value: 'the-second' },
        },
      }) }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: false, exampleKey: 'second' } }));
    expect(out.body).toBe('the-second');
  });

  it('generates from the schema (honouring the schema example) when no media example is present', async () => {
    const s = spec({
      '/x': { get: op({ '200': jsonResponse({ schema: { type: 'string', example: 'from-schema' } }) }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.body).toBe('from-schema');
  });

  it('ignores examples and generates from the schema when ignoreExamples is set', async () => {
    const s = spec({
      '/x': { get: op({ '200': jsonResponse({
        schema: { type: 'string', example: 'from-schema' },
        example: 'from-example',
      }) }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: false, ignoreExamples: true } }));
    expect(out.body).toBe('from-schema');
  });
});

describe('mocker: dynamic generation', () => {
  it('generates a schema-shaped body that satisfies the declared types', async () => {
    const s = spec({
      '/x': { get: op({ '200': jsonResponse({
        schema: {
          type: 'object',
          required: ['id', 'name'],
          properties: { id: { type: 'integer' }, name: { type: 'string' } },
        },
      }) }) },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: true } }));
    expect(typeof out.body).toBe('object');
    expect(typeof out.body.id).toBe('number');
    expect(typeof out.body.name).toBe('string');
  });
});
