// Parameter serialization styles and raw JSON-Schema validation. Query parameters are deserialized
// according to their OpenAPI `style`/`explode` (form arrays, pipe-delimited arrays, deepObject
// objects) before being validated against their schema. Body validation applies the full JSON Schema
// (nested requireds, enums, string constraints).

import { call, expectOk, expectError } from './_helpers';

function queryParamSpec(param: any): any {
  return {
    openapi: '3.0.0',
    info: { title: 't', version: '1' },
    paths: {
      '/q': {
        get: {
          parameters: [param],
          responses: { '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'ok' } } } },
        },
      },
    },
  };
}

describe('query serialization styles', () => {
  it('deserializes a form-style exploded array and validates its items', async () => {
    const spec = queryParamSpec({
      name: 'tags', in: 'query', style: 'form', explode: true,
      schema: { type: 'array', items: { type: 'string', enum: ['a', 'b', 'c'] } },
    });
    const out = expectOk(await call(spec, { method: 'get', url: { path: '/q', query: { tags: ['a', 'b'] } } }));
    expect(out.statusCode).toBe(200);
  });

  it('rejects a form-style array whose item breaks the enum with 422', async () => {
    const spec = queryParamSpec({
      name: 'tags', in: 'query', style: 'form', explode: true,
      schema: { type: 'array', items: { type: 'string', enum: ['a', 'b', 'c'] } },
    });
    const err = expectError(await call(spec, { method: 'get', url: { path: '/q', query: { tags: ['a', 'z'] } } }));
    expect(err.status).toBe(422);
  });

  it('deserializes a pipe-delimited array from a single raw query value', async () => {
    const spec = queryParamSpec({
      name: 'ids', in: 'query', style: 'pipeDelimited', explode: false,
      schema: { type: 'array', items: { type: 'string', enum: ['a', 'b', 'c'] } },
    });
    // The value is a single raw query string "a|b|c" (not a pre-split array), so the deserializer
    // must split it on "|" into ["a","b","c"]. The item enum makes this discriminating: if the
    // split does not happen, the lone "a|b|c" is not a valid enum member and validation fails.
    const out = expectOk(await call(spec, { method: 'get', url: { path: '/q', query: { ids: 'a|b|c' } } }));
    expect(out.statusCode).toBe(200);
  });

  it('deserializes a deepObject-style object', async () => {
    const spec = queryParamSpec({
      name: 'filter', in: 'query', required: true, style: 'deepObject', explode: true,
      schema: {
        type: 'object', required: ['role', 'city'],
        properties: { role: { type: 'string', enum: ['admin', 'user'] }, city: { type: 'string' } },
      },
    });
    // deepObject sends each object property as a bracketed key (filter[role]/filter[city]). The param
    // is required and `role` is enum-constrained, so success DEPENDS on correctly rebuilding the
    // object: a no-op deserializer leaves the bracketed keys as unknown params, `filter` stays unset,
    // and the required check fails with 422 — only a correct deepObject parse reaches 200.
    const out = expectOk(await call(spec, {
      method: 'get',
      url: { path: '/q', query: { 'filter[role]': 'admin', 'filter[city]': 'paris' } },
    }));
    expect(out.statusCode).toBe(200);
  });
});

describe('raw JSON-Schema body validation', () => {
  function bodySpec(schema: any): any {
    return {
      openapi: '3.0.0',
      info: { title: 't', version: '1' },
      paths: {
        '/b': {
          post: {
            requestBody: { required: true, content: { 'application/json': { schema } } },
            responses: { '200': { description: 'ok', content: { 'application/json': { schema: { type: 'string' }, example: 'ok' } } } },
          },
        },
      },
    };
  }
  const withBody = (body: any) => ({
    method: 'post',
    url: { path: '/b' },
    headers: { 'content-type': 'application/json', 'content-length': '50' },
    body,
  });

  const nested = {
    type: 'object',
    required: ['user'],
    properties: {
      user: { type: 'object', required: ['name'], properties: { name: { type: 'string', minLength: 2 } } },
    },
  };

  it('accepts a body satisfying a nested schema', async () => {
    const out = expectOk(await call(bodySpec(nested), withBody({ user: { name: 'Ann' } })));
    expect(out.statusCode).toBe(200);
  });

  it('rejects a body missing a deeply-nested required property with 422', async () => {
    const err = expectError(await call(bodySpec(nested), withBody({ user: {} })));
    expect(err.status).toBe(422);
  });
});
