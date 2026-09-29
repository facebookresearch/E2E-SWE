// Router: which operation does a request resolve to? Path matching is segment-by-segment (a
// templated `{param}` segment matches any single segment; segment counts must be equal), and when
// several operations match the same request the router disambiguates by preferring concrete
// segments over templated ones. Method matching is case-insensitive. When a base URL is supplied it
// is matched against the operation's servers. These tests pin the resolution *outcome* by giving
// each candidate operation a distinct response body and asserting which body comes back.

import { call, expectOk, expectError } from './_helpers';

// Build a minimal OAS3 spec from a map of "METHOD path" -> a marker string returned as the body.
function spec(routes: Array<{ method: string; path: string; marker: string; servers?: any[] }>): any {
  const paths: any = {};
  for (const r of routes) {
    paths[r.path] = paths[r.path] || {};
    paths[r.path][r.method] = {
      responses: {
        '200': {
          description: 'ok',
          content: {
            'application/json': {
              schema: { type: 'string' },
              example: r.marker,
            },
          },
        },
      },
      ...(r.servers ? { servers: r.servers } : {}),
    };
  }
  return { openapi: '3.0.0', info: { title: 't', version: '1' }, paths };
}

describe('router: path disambiguation', () => {
  it('prefers a fully concrete path over a templated one that also matches', async () => {
    const s = spec([
      { method: 'get', path: '/pet/{petId}', marker: 'templated' },
      { method: 'get', path: '/pet/findByStatus', marker: 'concrete' },
    ]);
    const out = expectOk(await call(s, { method: 'get', url: { path: '/pet/findByStatus' } }));
    expect(out.body).toBe('concrete');
  });

  it('prefers the concrete path regardless of declaration order', async () => {
    const s = spec([
      { method: 'get', path: '/pet/findByStatus', marker: 'concrete' },
      { method: 'get', path: '/pet/{petId}', marker: 'templated' },
    ]);
    const out = expectOk(await call(s, { method: 'get', url: { path: '/pet/findByStatus' } }));
    expect(out.body).toBe('concrete');
  });

  it('falls back to the templated path when no concrete path matches', async () => {
    const s = spec([
      { method: 'get', path: '/pet/{petId}', marker: 'templated' },
      { method: 'get', path: '/pet/findByStatus', marker: 'concrete' },
    ]);
    const out = expectOk(await call(s, { method: 'get', url: { path: '/pet/42' } }));
    expect(out.body).toBe('templated');
  });

  it('resolves the more-concrete of two templated paths by match score', async () => {
    // For request /store/order/5 both templates match; the one whose concrete prefix ("order")
    // lines up with the request should win over the all-templated one.
    const s = spec([
      { method: 'get', path: '/store/{a}/{b}', marker: 'all-templated' },
      { method: 'get', path: '/store/order/{id}', marker: 'concrete-prefix' },
    ]);
    const out = expectOk(await call(s, { method: 'get', url: { path: '/store/order/5' } }));
    expect(out.body).toBe('concrete-prefix');
  });

  it('prefers the fully concrete multi-segment path over a mid-templated one', async () => {
    const s = spec([
      { method: 'get', path: '/a/{x}/c', marker: 'mid-templated' },
      { method: 'get', path: '/a/b/c', marker: 'all-concrete' },
    ]);
    const out = expectOk(await call(s, { method: 'get', url: { path: '/a/b/c' } }));
    expect(out.body).toBe('all-concrete');
  });
});

describe('router: non-matches', () => {
  it('rejects an unknown path with a 404', async () => {
    const s = spec([{ method: 'get', path: '/pet', marker: 'x' }]);
    const err = expectError(await call(s, { method: 'get', url: { path: '/unknown' } }));
    expect(err.status).toBe(404);
  });

  it('does not match when the segment count differs', async () => {
    const s = spec([{ method: 'get', path: '/pet/{petId}', marker: 'x' }]);
    const err = expectError(await call(s, { method: 'get', url: { path: '/pet/42/toys' } }));
    expect(err.status).toBe(404);
  });

  it('rejects a matched path with an undefined method using 405', async () => {
    const s = spec([{ method: 'get', path: '/pet', marker: 'x' }]);
    const err = expectError(await call(s, { method: 'post', url: { path: '/pet' } }));
    expect(err.status).toBe(405);
  });
});

describe('router: method + server matching', () => {
  it('matches the method case-insensitively', async () => {
    const s = spec([{ method: 'get', path: '/pet', marker: 'ok' }]);
    const out = expectOk(await call(s, { method: 'GET', url: { path: '/pet' } }));
    expect(out.body).toBe('ok');
  });

  it('resolves when a supplied baseUrl matches a declared server', async () => {
    const s = {
      openapi: '3.0.0',
      info: { title: 't', version: '1' },
      servers: [{ url: 'http://example.com/api' }],
      paths: {
        '/pet': {
          get: {
            responses: { '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'served' } } } },
          },
        },
      },
    };
    const out = expectOk(await call(s, { method: 'get', url: { path: '/pet', baseUrl: 'http://example.com/api' } }));
    expect(out.body).toBe('served');
  });

  it('rejects a baseUrl whose host matches no declared server with a 404', async () => {
    const s = {
      openapi: '3.0.0',
      info: { title: 't', version: '1' },
      servers: [{ url: 'http://example.com/api' }],
      paths: {
        '/pet': {
          get: { responses: { '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'served' } } } } },
        },
      },
    };
    const err = expectError(await call(s, { method: 'get', url: { path: '/pet', baseUrl: 'http://acme.com/api' } }));
    expect(err.status).toBe(404);
  });

  it('ignores server validation entirely when no baseUrl is supplied', async () => {
    const s = {
      openapi: '3.0.0',
      info: { title: 't', version: '1' },
      servers: [{ url: 'http://example.com/api' }],
      paths: {
        '/pet': {
          get: { responses: { '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'served' } } } } },
        },
      },
    };
    const out = expectOk(await call(s, { method: 'get', url: { path: '/pet' } }));
    expect(out.statusCode).toBe(200);
  });
});
