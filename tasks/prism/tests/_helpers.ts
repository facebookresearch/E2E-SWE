// Shared black-box harness for the hidden suite. Every test drives the engine ONLY through its
// public entry (`createAndCallPrismInstanceWithSpec`, imported under the neutral alias `prismhttp`)
// and asserts on observable HTTP output — status code, `Content-type`, body, the `validations`
// record, and, for rejected requests, the numeric HTTP `status` carried by the error. No internal
// module, constant, or error string is referenced, so an implementation is free to organise its
// code however it likes as long as the observable behaviour matches.

import { createLogger } from '@stoplight/prism-core';
import { createAndCallPrismInstanceWithSpec } from 'prismhttp';

export const logger: any = createLogger('TEST', { enabled: false });

// The default operating mode used across the suite: validate the request, enforce security, validate
// the produced response, and mock statically (prefer examples over freshly generated data). `errors:
// false` means Prism does not turn response *violations* into transport errors — routing, request
// validation and security decisions are still surfaced.
export const BASE_CONFIG: any = {
  validateRequest: true,
  checkSecurity: true,
  validateResponse: true,
  mock: { dynamic: false },
  errors: false,
  upstreamProxy: undefined,
  isProxy: false,
};

function mergeConfig(override: any): any {
  const { mock: mockOverride, ...rest } = override || {};
  return {
    ...BASE_CONFIG,
    ...rest,
    mock: { ...BASE_CONFIG.mock, ...(mockOverride || {}) },
  };
}

// Call the engine with an inline spec + request. `configOverride` is shallow-merged over BASE_CONFIG
// (with `mock` merged one level deeper), so a test can flip a single knob (e.g. dynamic generation
// or a forced status code) without restating the whole config.
export async function call(spec: any, request: any, configOverride: any = {}): Promise<any> {
  return createAndCallPrismInstanceWithSpec(spec, mergeConfig(configOverride), request, logger);
}

// Assert the call resolved successfully and return the HTTP output ({ statusCode, headers, body }).
export function expectOk(result: any): any {
  expect(result.result).toBe('ok');
  return result.response.output;
}

// Assert the call was rejected and return the error (a ProblemJson-shaped Error exposing `.status`).
export function expectError(result: any): any {
  expect(result.result).toBe('error');
  return result.error;
}

// Case-insensitive header lookup on a mocked response (Prism emits `Content-type`).
export function header(output: any, name: string): any {
  const headers = output.headers || {};
  const key = Object.keys(headers).find(k => k.toLowerCase() === name.toLowerCase());
  return key === undefined ? undefined : headers[key];
}
