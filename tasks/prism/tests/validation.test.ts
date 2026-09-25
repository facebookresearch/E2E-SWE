// Request validation: parameters and bodies are validated against the operation's schema. A failing
// request does NOT simply 500 — the engine first looks for a suitable error response *in the spec*
// (422/400 for a generic violation) and mocks that; only when the spec defines no such response does
// it synthesise a 422. A well-formed request passes with empty `validations.input`. Unknown query
// parameters are ignored.

import { call, expectOk, expectError } from './_helpers';

// GET /search?q=<string, required>&limit=<integer 1..100>, 200 returns a fixed example.
function searchSpec(extraResponses: any = {}): any {
  return {
    openapi: '3.0.0',
    info: { title: 't', version: '1' },
    paths: {
      '/search': {
        get: {
          parameters: [
            { name: 'q', in: 'query', required: true, schema: { type: 'string' } },
            { name: 'limit', in: 'query', required: false, schema: { type: 'integer', minimum: 1, maximum: 100 } },
          ],
          responses: {
            '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'results' } } },
            ...extraResponses,
          },
        },
      },
    },
  };
}

describe('request validation: rejections', () => {
  it('rejects a missing required query parameter with 422', async () => {
    const err = expectError(await call(searchSpec(), { method: 'get', url: { path: '/search' } }));
    expect(err.status).toBe(422);
  });

  it('rejects a query parameter that violates its numeric bounds with 422', async () => {
    const err = expectError(await call(searchSpec(), {
      method: 'get',
      url: { path: '/search', query: { q: 'hi', limit: '999' } },
    }));
    expect(err.status).toBe(422);
  });

  it('rejects a required-but-missing request body with 422', async () => {
    const s = {
      openapi: '3.0.0',
      info: { title: 't', version: '1' },
      paths: {
        '/items': {
          post: {
            requestBody: { required: true, content: { 'application/json': { schema: { type: 'object', required: ['name'], properties: { name: { type: 'string' } } } } } },
            responses: { '201': { description: 'created', content: { 'application/json': { schema: { type: 'string' }, example: 'made' } } } },
          },
        },
      },
    };
    const err = expectError(await call(s, { method: 'post', url: { path: '/items' } }));
    expect(err.status).toBe(422);
  });
});

describe('request validation: spec-defined error responses are mocked', () => {
  it('mocks the spec\'s 422 response (instead of synthesising an error) when the request is invalid', async () => {
    const s = searchSpec({
      '422': { description: 'invalid', content: { 'application/json': { schema: { type: 'object' }, example: { error: 'bad-input' } } } },
    });
    // q is required and missing -> validation fails, but the spec HAS a 422 response to mock.
    const out = expectOk(await call(s, { method: 'get', url: { path: '/search' } }));
    expect(out.statusCode).toBe(422);
    expect(out.body).toEqual({ error: 'bad-input' });
  });
});

describe('request validation: acceptance', () => {
  it('passes a valid request with no input validation issues', async () => {
    const result = await call(searchSpec(), { method: 'get', url: { path: '/search', query: { q: 'hello', limit: '10' } } });
    expect(result.result).toBe('ok');
    expect(result.response.validations.input).toEqual([]);
  });

  it('ignores unknown query parameters', async () => {
    const out = expectOk(await call(searchSpec(), {
      method: 'get',
      url: { path: '/search', query: { q: 'hello', nonsense: 'whatever' } },
    }));
    expect(out.statusCode).toBe(200);
  });
});
