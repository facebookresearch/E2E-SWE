// Recall-resistant corners: behaviours that a plausible-but-approximate engine gets subtly wrong.
// Each targets a DISTINCT branch (static schema sampling, forced-code range/default fallback,
// deprecation signalling, HEAD handling, missing-example errors, accept-ignored-when-no-content),
// so a failure of any one points at a specific gap rather than overlapping with another test.

import { call, expectOk, expectError, header } from './_helpers';

function spec(paths: any): any {
  return { openapi: '3.0.0', info: { title: 't', version: '1' }, paths };
}
function jsonResponse(fields: any): any {
  return { description: 'r', content: { 'application/json': fields } };
}

describe('corners: static schema sampling', () => {
  it('generates the first enum value for a bare enum schema (no example)', async () => {
    const s = spec({
      '/x': { get: { responses: { '200': jsonResponse({ schema: { type: 'string', enum: ['red', 'green', 'blue'] } }) } } },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(out.body).toBe('red');
  });
});

describe('corners: forced status code fallbacks', () => {
  it('matches a forced code against a range response (404 -> 4XX)', async () => {
    const s = spec({
      '/x': { get: { responses: {
        '201': jsonResponse({ schema: { type: 'string' }, example: 'created' }),
        '4XX': jsonResponse({ schema: { type: 'string' }, example: 'clienterr' }),
      } } },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: false, code: 404 } }));
    expect(out.statusCode).toBe(404);
    expect(out.body).toBe('clienterr');
  });

  it('falls back to the default response for a forced code that is not defined', async () => {
    const s = spec({
      '/x': { get: { responses: {
        '200': jsonResponse({ schema: { type: 'string' }, example: 'ok' }),
        'default': jsonResponse({ schema: { type: 'string' }, example: 'def' }),
      } } },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: false, code: 404 } }));
    expect(out.statusCode).toBe(404);
    expect(out.body).toBe('def');
  });
});

describe('corners: example selection errors', () => {
  it('rejects with 404 when a requested example key does not exist', async () => {
    const s = spec({
      '/x': { get: { responses: { '200': jsonResponse({ schema: { type: 'string' }, examples: { a: { value: 'A' } } }) } } },
    });
    const err = expectError(await call(s, { method: 'get', url: { path: '/x' } }, { mock: { dynamic: false, exampleKey: 'zzz' } }));
    expect(err.status).toBe(404);
  });
});

describe('corners: deprecation signalling', () => {
  it('adds a deprecation header when the operation is deprecated', async () => {
    const s = spec({
      '/x': { get: { deprecated: true, responses: { '200': jsonResponse({ schema: { type: 'string' }, example: 'ok' }) } } },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/x' } }));
    expect(header(out, 'deprecation')).toBe('true');
  });
});

describe('corners: HEAD requests', () => {
  it('responds to a HEAD request with the status code but no body', async () => {
    const s = spec({
      '/ping': { head: { responses: { '200': jsonResponse({ schema: { type: 'string' }, example: 'pong' }) } } },
    });
    const out = expectOk(await call(s, { method: 'head', url: { path: '/ping' } }));
    expect(out.statusCode).toBe(200);
    expect(out.body).toBeUndefined();
  });
});

describe('corners: accept header with a bodyless response', () => {
  it('ignores an unsatisfiable Accept header when the response defines no body (no 406)', async () => {
    const s = spec({
      '/x': { get: { responses: { '200': { description: 'no body' } } } },
    });
    const out = expectOk(await call(s, {
      method: 'get',
      url: { path: '/x' },
      headers: { accept: 'application/xml' },
    }));
    expect(out.statusCode).toBe(200);
  });
});
