// Security: an operation's security requirement list is an OR of ANDs — the outer list is
// alternatives, each alternative is a set of schemes that must ALL be satisfied. A request is
// authorised if any single alternative is fully satisfied. A failing check is rejected with 401
// (unless the spec defines a 401 response, which is then mocked instead).

import { call, expectOk, expectError } from './_helpers';

const SCHEMES = {
  KeyA: { type: 'apiKey', in: 'header', name: 'X-Key-A' },
  KeyB: { type: 'apiKey', in: 'header', name: 'X-Key-B' },
};

function secSpec(security: any, extraResponses: any = {}): any {
  return {
    openapi: '3.0.0',
    info: { title: 't', version: '1' },
    components: { securitySchemes: SCHEMES },
    paths: {
      '/secure': {
        get: {
          security,
          responses: {
            '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'authorized' } } },
            ...extraResponses,
          },
        },
      },
    },
  };
}

describe('security: single scheme', () => {
  it('rejects a request that omits the required credential with 401', async () => {
    const err = expectError(await call(secSpec([{ KeyA: [] }]), { method: 'get', url: { path: '/secure' } }));
    expect(err.status).toBe(401);
  });

  it('authorises a request that supplies the required credential', async () => {
    const out = expectOk(await call(secSpec([{ KeyA: [] }]), {
      method: 'get',
      url: { path: '/secure' },
      headers: { 'x-key-a': 'secret' },
    }));
    expect(out.statusCode).toBe(200);
  });
});

describe('security: OR of alternatives', () => {
  it('authorises when any one alternative is satisfied', async () => {
    const out = expectOk(await call(secSpec([{ KeyA: [] }, { KeyB: [] }]), {
      method: 'get',
      url: { path: '/secure' },
      headers: { 'x-key-b': 'secret' },
    }));
    expect(out.statusCode).toBe(200);
  });

  it('rejects when no alternative is satisfied', async () => {
    const err = expectError(await call(secSpec([{ KeyA: [] }, { KeyB: [] }]), { method: 'get', url: { path: '/secure' } }));
    expect(err.status).toBe(401);
  });
});

describe('security: AND within an alternative', () => {
  it('rejects when only part of a multi-scheme alternative is satisfied', async () => {
    const err = expectError(await call(secSpec([{ KeyA: [], KeyB: [] }]), {
      method: 'get',
      url: { path: '/secure' },
      headers: { 'x-key-a': 'secret' },
    }));
    expect(err.status).toBe(401);
  });

  it('authorises when every scheme in the alternative is satisfied', async () => {
    const out = expectOk(await call(secSpec([{ KeyA: [], KeyB: [] }]), {
      method: 'get',
      url: { path: '/secure' },
      headers: { 'x-key-a': 'secret', 'x-key-b': 'secret' },
    }));
    expect(out.statusCode).toBe(200);
  });
});

describe('security: spec-defined 401 is mocked', () => {
  it('mocks the spec\'s 401 response instead of synthesising an error', async () => {
    const s = secSpec([{ KeyA: [] }], {
      '401': { description: 'unauth', content: { 'application/json': { schema: { type: 'object' }, example: { error: 'no-access' } } } },
    });
    const out = expectOk(await call(s, { method: 'get', url: { path: '/secure' } }));
    expect(out.statusCode).toBe(401);
    expect(out.body).toEqual({ error: 'no-access' });
  });
});
