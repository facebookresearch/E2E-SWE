// Content negotiation: the `Accept` request header (or a configured media-type list) chooses which
// of a response's media types is served, following HTTP semantics (exact match, wildcards, quality
// values). With no Accept header the engine defaults to `application/json`. If the client asks for a
// media type the response cannot produce — and the response *does* define a body — the request is
// rejected with 406; a `*/*` acceptance always succeeds. A response media type of `*/*` is served as
// `text/plain`.

import { call, expectOk, expectError, header } from './_helpers';

function multiSpec(contents: any): any {
  return {
    openapi: '3.0.0',
    info: { title: 't', version: '1' },
    paths: {
      '/x': { get: { responses: { '200': { description: 'r', content: contents } } } },
    },
  };
}

const JSON_AND_TEXT = {
  'application/json': { schema: { type: 'object' }, example: { kind: 'json' } },
  'text/plain': { schema: { type: 'string' }, example: 'kind=text' },
};

describe('content negotiation', () => {
  it('defaults to application/json when no Accept header is sent', async () => {
    const out = expectOk(await call(multiSpec(JSON_AND_TEXT), { method: 'get', url: { path: '/x' } }));
    expect(header(out, 'content-type')).toBe('application/json');
    expect(out.body).toEqual({ kind: 'json' });
  });

  it('serves the media type named in the Accept header', async () => {
    const out = expectOk(await call(multiSpec(JSON_AND_TEXT), {
      method: 'get',
      url: { path: '/x' },
      headers: { accept: 'text/plain' },
    }));
    expect(header(out, 'content-type')).toBe('text/plain');
    expect(out.body).toBe('kind=text');
  });

  it('honours quality values, choosing the higher-q media type', async () => {
    const out = expectOk(await call(multiSpec(JSON_AND_TEXT), {
      method: 'get',
      url: { path: '/x' },
      headers: { accept: 'application/json;q=0.2, text/plain;q=0.9' },
    }));
    expect(header(out, 'content-type')).toBe('text/plain');
  });

  it('accepts */* and serves an available representation', async () => {
    const out = expectOk(await call(multiSpec({ 'application/json': { schema: { type: 'object' }, example: { kind: 'json' } } }), {
      method: 'get',
      url: { path: '/x' },
      headers: { accept: '*/*' },
    }));
    expect(header(out, 'content-type')).toBe('application/json');
  });

  it('rejects with 406 when the Accept header cannot be satisfied', async () => {
    const err = expectError(await call(multiSpec({ 'application/json': { schema: { type: 'object' }, example: { kind: 'json' } } }), {
      method: 'get',
      url: { path: '/x' },
      headers: { accept: 'application/xml' },
    }));
    expect(err.status).toBe(406);
  });

  it('serves a response whose only media type is */* (defaulting with no Accept header)', async () => {
    const out = expectOk(await call(multiSpec({ '*/*': { schema: { type: 'string' }, example: 'anything' } }), {
      method: 'get',
      url: { path: '/x' },
    }));
    expect(out.statusCode).toBe(200);
    expect(out.body).toBe('anything');
  });
});
