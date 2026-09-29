# Authlib — The Ultimate Python Library for OAuth and OpenID Connect

Implement `authlib`, a comprehensive Python library for building OAuth and OpenID Connect servers and clients. The library provides JOSE (JWT/JWS/JWE/JWK), OAuth 1.0, OAuth 2.0, and OpenID Connect, with framework integrations for Flask, requests, and httpx.

## Dependencies

The environment is **offline**: all dependencies below are **already installed**, and the project
is installed for you by a `setup.sh` that runs offline (no network). **Do not install anything** —
there is no internet access, so `pip install` will fail. Just import and use these packages:

- `cryptography` (for RSA, EC, EdDSA key operations, AES encryption)
- `joserfc` (the underlying JOSE primitives that `authlib.jose` delegates to)
- `flask` (for Flask OAuth2 server and client integrations)
- `flask-sqlalchemy` (for Flask + SQLAlchemy integration in OAuth2 server)
- `sqlalchemy` (for SQLAlchemy token/client storage mixins; installed via `flask-sqlalchemy`)
- `requests` (for requests-based OAuth2 client)
- `httpx` (for httpx-based OAuth2 client, also required by the Starlette client integration)
- `django` (for Django OAuth client integration)
- `starlette` (for Starlette OAuth client integration)
- `cachelib` (for cache-based OAuth1 nonce/temporary credential storage)

---

## 1. Keys (JWK — RFC 7517/7518/8037)

The library supports four key types for cryptographic operations: `OctKey` (symmetric/HMAC, `kty="oct"`), `RSAKey` (`kty="RSA"`), `ECKey` (curves P-256, P-384, P-521, `kty="EC"`), and `OKPKey` (Ed25519, X25519, `kty="OKP"`). Keys are generated via `generate_key(size_or_crv, is_private=...)` with optional `options` dict, exported via `as_dict(is_private=...)` and `as_pem(is_private=...)`, and identified via `kid` and `thumbprint`. `thumbprint()` returns the RFC 7638 JWK thumbprint. Asymmetric keys provide `get_private_key()` for the raw key object. `JsonWebKey.import_key` auto-detects format and returns the appropriate key type, and `JsonWebKey.import_key_set` loads JWK Sets into a `KeySet` with `find_by_kid` for lookup.

---

## 2. JWS — JSON Web Signature (RFC 7515)

`JsonWebSignature` signs and verifies payloads. It is constructed with a list of allowed algorithm names and an optional `private_headers` set restricting allowed non-standard header fields (`InvalidHeaderParameterNameError` if violated). It raises `UnsupportedAlgorithmError` if a disallowed algorithm is requested, or `MissingAlgorithmError` if no `alg` header is provided. It supports both compact serialization (`serialize_compact`/`deserialize_compact` returning bytes with 3 base64url segments) and flattened JSON serialization (`serialize_json`/`deserialize_json`). For the flattened JSON form, `serialize_json` takes a header object of the shape `{"protected": {...}}` — a dict whose `"protected"` value is the protected header dict carrying `"alg"` (an optional unprotected `"header"` dict may accompany it) — and returns a dict with `"protected"`, `"payload"`, and `"signature"` keys; `deserialize_json` accepts that returned structure. Deserialization returns a `JWSObject` with `header` and `payload`, supporting dict-style access (e.g., `result["payload"]`). The `crit` header parameter enforces that declared-critical parameters are present, raising `InvalidCritHeaderParameterNameError` otherwise. `deserialize_compact` distinguishes malformed input from verification failure: it raises `DecodeError` when the input is not a well-formed compact serialization (wrong number of segments, undecodable base64url segments, or an unparseable header), whereas `BadSignatureError` is raised only for a structurally valid token whose signature fails to verify (such as verifying with the wrong key). Algorithms: HS256/384/512, RS256/384/512, ES256/384/512, PS256/384/512, EdDSA.

---

## 3. JWE — JSON Web Encryption (RFC 7516)

`JsonWebEncryption` encrypts and decrypts payloads. It supports compact serialization (`serialize_compact`/`deserialize_compact` with 5 base64url segments) and general JSON serialization for multiple recipients (`serialize_json`/`deserialize_json`). Deserialization returns a dict-like result with `"payload"` and `"header"` keys. For multi-recipient JSON, the header object contains `"protected"` and `"recipients"` keys. On the encrypt side, `serialize_json` accepts a plain list of keys aligned positionally to the `"recipients"` array (the i-th key encrypts the content-encryption key for the i-th recipient), so each recipient is encrypted under its corresponding key even when those keys carry no `kid`. Decryption accepts a `(kid, key)` tuple to select the recipient. Key management algorithms (`alg`): RSA-OAEP, RSA1_5, A128KW/A192KW/A256KW, dir, ECDH-ES, ECDH-ES+A128KW/A192KW/A256KW, A128GCMKW/A192GCMKW/A256GCMKW. Content encryption (`enc`): A128CBC-HS256, A192CBC-HS384, A256CBC-HS512, A128GCM/A192GCM/A256GCM. Compression (`zip`): DEF.

---

## 4. JWT — JSON Web Token (RFC 7519)

A pre-configured module-level `jwt` instance (`JsonWebToken`) is available. `jwt.encode(header, payload, key)` produces a token as bytes (datetime objects in `exp`, `iat`, `nbf` are auto-converted to UTC epoch-second integers). The `key` argument accepts a single key/secret or a `KeySet` (from `import_key_set`): when a `KeySet` is passed to `encode`, the signing key is selected by the header's `kid` (and if the header carries no `kid`, one key is chosen and its `kid` is written into the header); when a `KeySet` is passed to `decode`, the verification key is resolved from the decoded token header's `kid`. By default, `encode` rejects payloads containing sensitive claim names (such as `password`) by raising `InsecureClaimError`; pass `check=False` to disable this check. `JsonWebToken` (and the module-level `jwt`) also handle **encrypted** JWTs: when the header carries a JWE key-management algorithm (`alg`) together with a content-encryption `enc` value, `encode` returns a 5-segment encrypted token (delegating to the JWE layer) and `decode` transparently decrypts it; otherwise it produces/reads a 3-segment signed token. `jwt.decode(s, key, claims_options)` returns `JWTClaims`, a dict subclass with registered claims (`iss`, `sub`, `aud`, `exp`, `nbf`, `iat`, `jti`) accessible as attributes (non-registered attribute access raises `AttributeError`). `claims.validate()` checks time-based claims (`ExpiredTokenError`, `InvalidTokenError`) and option-based constraints. Claims options use `essential` (bool, raises `MissingClaimError`), `value` (single match), and `values` (list match) keys per claim, raising `InvalidClaimError` on mismatch.

The JOSE layers compose as a chain — generate a key, then sign/encode, then verify/decode, then validate:

```python
from authlib.jose import JsonWebSignature, OctKey, jwt

# JWS: low-level sign/verify of an arbitrary payload.
jws = JsonWebSignature(["HS256"])
key = OctKey.generate_key(256)
token = jws.serialize_compact({"alg": "HS256"}, b"payload", key)   # 3-segment bytes
obj = jws.deserialize_compact(token, key)                          # obj["payload"] == b"payload"

# JWT: encode a claims dict, decode it back, then validate.
jwt_token = jwt.encode({"alg": "HS256"}, {"sub": "alice", "iss": "issuer"}, "secret")
claims = jwt.decode(jwt_token, "secret", claims_options={"iss": {"values": ["issuer"]}})
claims.validate()                                                  # raises on invalid/expired claims
```

---

## 5. Errors (`authlib.jose.errors`)

JOSE errors all inherit from `JoseError`: `DecodeError`, `BadSignatureError`, `MissingAlgorithmError`, `UnsupportedAlgorithmError`, `InvalidClaimError`, `MissingClaimError`, `ExpiredTokenError`, `InvalidTokenError`, `InsecureClaimError`, `InvalidCritHeaderParameterNameError`, `InvalidHeaderParameterNameError`.

---

## 6. OAuth1 (`authlib.oauth1`)

OAuth 1.0 request signing per RFC 5849. `ClientAuth` signs HTTP requests via `sign(method, uri, headers, body)` returning `(uri, headers, body)` with OAuth parameters added. It accepts `client_id`, `client_secret`, `token`, `token_secret`, `redirect_uri`, `verifier`, `signature_method`, and `signature_type`. Signature methods: `SIGNATURE_HMAC_SHA1`, `SIGNATURE_RSA_SHA1`, `SIGNATURE_PLAINTEXT`. Signature placement: `SIGNATURE_TYPE_HEADER`, `SIGNATURE_TYPE_QUERY`, `SIGNATURE_TYPE_BODY`.

---

## 7. OAuth2 (`authlib.oauth2`)

OAuth 2.0 client and server implementation per RFC 6749. `OAuth2Token` (`authlib.oauth2.rfc6749.OAuth2Token`) is a dict subclass with `is_expired()`. At construction, if the token carries an `expires_in` but no `expires_at`, an absolute `expires_at` is derived as "now + `expires_in`" (i.e. the lifetime is measured relative to construction time); `is_expired()` then reports expiry against that `expires_at` (returning `None` when the token carries neither). `ClientAuth` (`authlib.oauth2.auth.ClientAuth`) handles client authentication for token endpoints; constructed with `client_id`, `client_secret`, and `auth_method` (one of `"client_secret_basic"`, `"client_secret_post"`, `"none"`); applies via `prepare(method, uri, headers, body)`. `TokenAuth` (`authlib.oauth2.auth.TokenAuth`) attaches bearer tokens; constructed with `token` and `token_placement` (e.g., `"header"`); applies via `prepare(uri, headers, body)`. With `token_placement="header"`, `prepare` sets the `Authorization` header to `"Bearer <access_token>"` using the capitalized `"Bearer"` scheme, regardless of the casing of any `token_type` carried in the token dict (e.g. a token dict with `token_type="bearer"` still yields `"Bearer <access_token>"`). Utility functions at `authlib.oauth2.rfc6749`: `parameters.prepare_grant_uri`, `parameters.parse_authorization_code_response`, `util.scope_to_list` (returns `None` for `None` input), `util.list_to_scope` (returns `None` for `None` input), `util.extract_basic_authorization`. Standard error classes at `authlib.oauth2.rfc6749.errors`: `InvalidRequestError`, `UnauthorizedClientError`, `AccessDeniedError`, `InvalidScopeError`, `InvalidGrantError`, `UnsupportedGrantTypeError`, etc. PKCE support via `create_s256_code_challenge` at `authlib.oauth2.rfc7636`. `CodeChallenge` is a grant extension registered via `server.register_grant(AuthorizationCodeGrant, [CodeChallenge(required=True)])`. `generate_token` at `authlib.common.security` produces random tokens.

---

## 8. OIDC — OpenID Connect (`authlib.oidc`)

OpenID Connect layer at `authlib.oidc.core`. ID token claim classes `CodeIDToken` and `ImplicitIDToken` inherit from `JWTClaims` and validate OIDC-required claims via `validate()`. ID-token `validate(now=...)` accepts an optional `now` timestamp (and `leeway`) for time-based checks, and reads its expected verification context from a `params` dict attribute set on the claims object before validation: `params["nonce"]` carries the expected nonce (compared against the token's `nonce` claim), and `params["code"]` carries the authorization code used for `c_hash` verification. For `ImplicitIDToken` (a pure implicit-flow id_token with no accompanying access token), `nonce` is an essential claim (required, and matched against `params["nonce"]`) but `at_hash` is **not** required — `validate()` must succeed when `at_hash` is absent. Across all the id_token classes (`CodeIDToken`, `ImplicitIDToken`, and `HybridIDToken`), `at_hash` is validated **only when an access token is present** (supplied via `params["access_token"]`): when no access token is present, `at_hash` is not required and `validate()` must succeed without it. `get_claim_cls_by_response_type(response_type)` maps response types to the correct class. `UserInfo` is a dict subclass with standard OIDC claims accessible as attributes; `filter(scope)` returns only claims appropriate for the given scope string, following the standard OpenID Connect scope-to-claims mapping (e.g., `"openid profile"` returns name-related claims, `"openid email"` returns email claims). `OpenIDCode` is an extension for `AuthorizationCodeGrant` that adds `id_token` to token responses, registered via `server.register_grant(AuthorizationCodeGrant, [MyOpenIDCode()])`. A subclass implements these abstract methods, which the extension invokes with exactly these arguments: `exists_nonce(self, nonce, request)` (returns whether the nonce has been seen), `generate_user_info(self, user, scope)` (returns a `UserInfo`/dict of id_token claims), and `resolve_client_private_key(self, client)` (takes only the client and returns the key used to sign the id_token — no other arguments are passed). The generated `id_token` is signed with the key returned by `resolve_client_private_key`, so it round-trips via `jwt.decode(id_token, that_key)` and carries `sub`, `aud`, `nonce`, `iat`, and `exp`. `OpenIDHybridGrant` handles hybrid response types (`code id_token`, `code token`, `code id_token token`) returning tokens in the authorization response alongside a code. `HybridIDToken` validates hybrid-flow ID tokens including `c_hash` (the hash of the authorization code, supplied via `params["code"]`); it inherits the access-token-conditional `at_hash` rule above (so with no access token present, `validate()` succeeds on `c_hash` alone, without `at_hash`).

---

## 9. Framework Integrations (`authlib.integrations`)

OAuth client registries for Flask (`authlib.integrations.flask_client.OAuth`), Django (`authlib.integrations.django_client.OAuth`), and Starlette (`authlib.integrations.starlette_client.OAuth`) share a common pattern: `register(name, ...)` adds a provider, `create_client(name)` returns a client. A registered client exposes `create_authorization_url(redirect_uri=None, **kwargs)`, which assembles the OAuth request (using the registered `authorize_url`) and returns a dict containing at least `"url"` (the authorization URL, carrying `client_id`, `response_type=code`, and a generated `state`) and `"state"`. The Flask and Django clients are synchronous; the Starlette client's `create_authorization_url` is a coroutine (await it). `OAuth2Session` (`authlib.integrations.requests_client`) wraps `requests.Session` and its `create_authorization_url(url)` instead returns a `(url, state)` tuple. Its `fetch_token(url=None, *, authorization_response=None, state=None, **kwargs)` completes the token exchange: when given `authorization_response` (the full redirect URL the provider sent back), it parses the authorization `code` out of that URL, sets `grant_type` to `"authorization_code"`, and issues an HTTP POST to the token endpoint whose form body carries that `code` and `grant_type` (along with the client credentials); on success it returns/stores an `OAuth2Token`.

The Flask OAuth2 server (`authlib.integrations.flask_oauth2.AuthorizationServer`) takes `query_client` and `save_token` callbacks, and registers grant types via `register_grant`. Key methods: `get_consent_grant(end_user=...)`, `create_authorization_response(grant=..., grant_user=...)`, `create_token_response()`. Extra endpoints are added via `register_endpoint` and dispatched via `create_endpoint_response(name)`. `ResourceProtector` validates bearer tokens; use `register_token_validator(validator)` and `acquire(scope)` as a context manager. Config key `OAUTH2_REFRESH_TOKEN_GENERATOR = True` enables refresh tokens. `OAuth2Error` (`authlib.oauth2.OAuth2Error`) is the base error class. When the token endpoint's client authentication fails or is absent for a grant whose allowed auth methods include `client_secret_basic` (the default), `create_token_response` rejects the request with HTTP status `401` and a JSON body carrying `error = "invalid_client"`. This holds identically for the Flask and Django `AuthorizationServer`.

These public methods compose into the standard server wiring — an authorize route turns a request into a grant then issues the authorization response, the token route returns the token response, a protected route guards a scope, and a registered extra endpoint is dispatched by its `ENDPOINT_NAME`:

```python
# server = AuthorizationServer(app, query_client, save_token), grants/endpoints registered.

@app.route("/oauth/authorize", methods=["GET", "POST"])
def authorize():
    grant = server.get_consent_grant(end_user=current_user)   # raises OAuth2Error on a bad request
    if request.method == "GET":
        return grant.prompt or "ok"                            # show the consent screen
    return server.create_authorization_response(grant=grant, grant_user=current_user)

@app.route("/oauth/token", methods=["POST"])
def issue_token():
    return server.create_token_response()

@app.route("/api/me")
def me():
    with require_oauth.acquire("profile") as token:            # 401 if invalid, 403 if scope insufficient
        return {"user_id": token.user_id}

@app.route("/oauth/introspect", methods=["POST"])
def introspect():
    return server.create_endpoint_response("introspection")    # the registered endpoint's ENDPOINT_NAME
```

Grant types at `authlib.oauth2.rfc6749.grants`: `AuthorizationCodeGrant` (abstract: `save_authorization_code`, `query_authorization_code`, `delete_authorization_code`, `authenticate_user`; set `TOKEN_ENDPOINT_AUTH_METHODS` to control allowed auth methods), `ClientCredentialsGrant`, `ResourceOwnerPasswordCredentialsGrant` (abstract: `authenticate_user`), `RefreshTokenGrant` (abstract: `authenticate_refresh_token`, `authenticate_user`, `revoke_old_credential`; set `INCLUDE_NEW_REFRESH_TOKEN = True`).

Inside these overridable methods, the current grant `request` object exposes: `request.client` (the resolved client, with `.client_id`), `request.user` (the resolved end user, with `.id`), `request.scope` (the requested scope string), and `request.payload`, which carries the raw request parameters — `request.payload.redirect_uri`, `request.payload.scope`, and the full parameter dict via `request.payload.data` (e.g. `request.payload.data.get("nonce")`, `request.payload.data.get("code_challenge")`).

Django OAuth2 server at `authlib.integrations.django_oauth2.AuthorizationServer` uses the same grant registration API; `create_token_response(request)` returns a Django response.

SQLAlchemy mixins at `authlib.integrations.sqla_oauth2`: `OAuth2ClientMixin` (with `set_client_metadata` for configuring client properties such as `redirect_uris`, `scope`, `grant_types`, `response_types`, and `token_endpoint_auth_method`), `OAuth2TokenMixin`, `OAuth2AuthorizationCodeMixin`, plus factories `create_query_client_func`, `create_save_token_func`, and `create_bearer_token_validator`. These three storage mixins declare the standard OAuth2 fields as mapped SQLAlchemy columns, which a concrete model inherits: a persisted model subclasses the mixin (`class Client(db.Model, OAuth2ClientMixin)`) and adds only its own `id`/`user_id` (etc.), inheriting the OAuth2 columns from the mixin — so constructing e.g. `Client(client_id=..., client_secret=...)` and calling `set_client_metadata(...)` is valid. `OAuth2ClientMixin` provides `client_id` and `client_secret` columns plus a client-metadata column backing `set_client_metadata` and the metadata-derived properties. `OAuth2AuthorizationCodeMixin` provides `code`, `client_id`, `redirect_uri`, `scope`, `nonce`, and an authorization-time column, plus an `is_expired()` method returning whether the stored authorization code has passed its expiry window (measured relative to the authorization-time column). `OAuth2TokenMixin` provides `client_id`, `access_token`, `refresh_token`, `token_type`, `scope`, and `expires_in` columns (in addition to the `access_token_revoked_at`/`refresh_token_revoked_at` columns below). Each factory takes `(session, model_class)`. `create_query_client_func` and `create_save_token_func` return a plain **callable** (the `query_client` / `save_token` callback, used directly). `create_bearer_token_validator`, by contrast, returns a `BearerTokenValidator` **subclass** (a class, not an instance and not a bare function); the caller instantiates it with no arguments and registers that instance, e.g. `require_oauth.register_token_validator(create_bearer_token_validator(session, Token)())`. The produced validator authenticates a bearer token by looking up the token whose `access_token` column equals the presented bearer string. `OAuth2TokenMixin` tracks revocation through `access_token_revoked_at` and `refresh_token_revoked_at` timestamp columns (default `0`/unset); the bearer-token validator treats a token whose `access_token_revoked_at` is set as revoked (rejecting protected-resource access), and refresh-token validity is tracked via `refresh_token_revoked_at`.

---

## 10. OAuth2 RFC Extensions

Token revocation (`authlib.oauth2.rfc7009.RevocationEndpoint`, `ENDPOINT_NAME = "revocation"`) and token introspection (`authlib.oauth2.rfc7662.IntrospectionEndpoint`, `ENDPOINT_NAME = "introspection"`) are server endpoints registered via `register_endpoint`. A subclass implements these abstract methods, which the endpoint invokes with exactly these arguments: `query_token(self, token_string, token_type_hint)` (shared by both, returns the stored token); for revocation, `revoke_token(self, token, request)` (the current request object is passed as the second argument); for introspection, `introspect_token(self, token)` (returns the introspection response dict) and `check_permission(self, token, client, request)` (returns whether the client may introspect the token). A successful `create_endpoint_response("revocation")` returns HTTP `200`.

JWT bearer assertion helpers at `authlib.oauth2.rfc7523`: `client_secret_jwt_sign(client_secret, client_id, token_endpoint, ...)` and `private_key_jwt_sign(private_key, client_id, token_endpoint, ...)` create signed JWT assertions for client authentication. They accept an optional `claims` dict whose entries are merged into the generated assertion payload, **overriding** the auto-generated defaults (`iss`/`sub` = `client_id`, `aud` = `token_endpoint`, `iat`, `exp`, and a random `jti`) for any keys it supplies — e.g. passing `claims={"jti": "unique-id-123"}` makes the decoded assertion's `jti` exactly `"unique-id-123"` instead of the auto-generated token.

`ClientMetadataClaims` (`authlib.oauth2.rfc7591`) validates dynamic client registration metadata; constructed as `ClientMetadataClaims(data, header)`. `validate()` rejects (raises) when a `redirect_uris` entry is not a well-formed absolute URI — a bare string like `"not-a-url"` (no scheme/host) is rejected, while `"https://client.test/callback"` is accepted. The exact exception class is unspecified. `AuthorizationServerMetadata` (`authlib.oauth2.rfc8414`) validates OAuth2 server metadata. It exposes a `validate_<field>()` method for each standard server-metadata field it carries — in particular `validate_issuer()`, `validate_authorization_endpoint()`, `validate_token_endpoint()`, and `validate_response_types_supported()` (validating the `response_types_supported` field, which must be present and a JSON array). `get_well_known_url(issuer, external=False)` is a **module-level function** importable directly from `authlib.oauth2.rfc8414` (e.g. `from authlib.oauth2.rfc8414 import get_well_known_url`), not a method on the metadata class. With the default `external=False` and an issuer that carries no path (e.g. `"https://auth.example.com"`), it returns the bare path `"/.well-known/oauth-authorization-server"` (with `external=True` it prepends the issuer's scheme and host).

`DeviceAuthorizationEndpoint` (`authlib.oauth2.rfc8628`, `ENDPOINT_NAME = "device_authorization"`) handles device authorization. A subclass implements these abstract methods, which the endpoint invokes with exactly these arguments: `get_verification_uri(self)` and `save_device_credential(self, client_id, scope, data)` — the latter called while the endpoint builds the device authorization response, with `data` being that response payload (the dict returned to the client).

JWT Access Tokens (`authlib.oauth2.rfc9068`): `JWTBearerTokenGenerator(issuer)` generates self-contained JWT access tokens with `typ: "at+jwt"` header and claims including `iss`, `client_id`, `scope`, `aud`, `exp`, `iat`, `jti`. Register as token generator via `server.register_token_generator("default", gen)`. Abstract: `get_jwks()` (returns JWKS dict with signing keys). Override `get_audiences(client, user, scope)` to set `aud`. `JWTBearerTokenValidator(issuer, resource_server)` validates JWT access tokens without DB lookup by decoding and checking claims. Abstract: `get_jwks()` (returns JWKS dict with public keys). The validated token is a `JWTAccessTokenClaims` (dict subclass) with claims accessible via dict keys.

---

## 11. OIDC Discovery and Registration

`OpenIDProviderMetadata` (`authlib.oidc.discovery`) validates OIDC server metadata (requires `jwks_uri`; `validate_jwks_uri()` enforces this) with `validate()`. `get_well_known_url(issuer, external=False)` is a **module-level function** importable directly from `authlib.oidc.discovery` (e.g. `from authlib.oidc.discovery import get_well_known_url`), not a method on the metadata class. With the default `external=False` and an issuer that carries no path (e.g. `"https://auth.example.com"`), it returns the bare path `"/.well-known/openid-configuration"` (with `external=True` it prepends the issuer, stripped of any trailing slash). `ClientMetadataClaims` (`authlib.oidc.registration`) validates OIDC client registration fields; constructed as `ClientMetadataClaims(data, header)`. Like its rfc7591 counterpart, `validate()` rejects (raises) when a URI-valued field is not a well-formed absolute URI; in particular a `request_uris` entry such as `"not-a-url"` (no scheme/host) is rejected. The exact exception class is unspecified.

---

## 12. Flask OAuth1 Server (`authlib.integrations.flask_oauth1`)

Flask OAuth1 server via `AuthorizationServer(app, query_client)` with cache-based hooks. `register_nonce_hooks` and `register_temporary_credential_hooks` are **module-level functions** importable directly from `authlib.integrations.flask_oauth1` (e.g. `from authlib.integrations.flask_oauth1 import register_nonce_hooks, register_temporary_credential_hooks`), not methods on `AuthorizationServer`; each takes `(server, cache)` where `cache` is a cachelib-compatible cache, and wires the server's nonce / temporary-credential storage to that cache. Server methods: `create_temporary_credentials_response`, `create_authorization_response`, `create_token_response`. Token creation via `register_hook("create_token_credential", callback)`: the server itself generates the new token-credential pair and invokes that callback with exactly these arguments — `callback(token, temporary_credential)`, where `token` is the generated token dict carrying `oauth_token` and `oauth_token_secret`, and `temporary_credential` is the temporary credential being exchanged; the callback persists and returns the token credential. `ResourceProtector` validates OAuth1 credentials; the Flask variant is constructed as `ResourceProtector(app, query_client, query_token, exists_nonce)`.

The resource-owner-authorization step, `create_authorization_response(grant_user=...)`, grants the request's temporary credential to `grant_user`: it generates the `oauth_verifier` (recording it against the credential) and returns an **HTTP 302 redirect** whose `Location` is the callback URI with `oauth_token` and `oauth_verifier` appended as query parameters. The callback is the temporary credential's recorded `oauth_callback` (`get_redirect_uri()`); when that recorded callback is `"oob"` or absent, the server falls back to the client's `get_default_redirect_uri()`. (This differs from RFC 5849's out-of-band display convention: an `"oob"` callback still yields a redirect to the client's default URI here, never a bare verifier-in-body response.)

Models use `ClientMixin`, `TemporaryCredentialMixin`, `TokenCredentialMixin` from `authlib.oauth1`. The RFC 5849 server logic invokes these getter methods on the credential models, which the model must implement:

- `ClientMixin`: `get_default_redirect_uri()`, `get_client_secret()`, `get_rsa_public_key()`.
- `TemporaryCredentialMixin`: `get_client_id()`, `get_redirect_uri()` (the recorded `oauth_callback`), `check_verifier(verifier)` (returns whether the supplied verifier matches), plus `get_oauth_token()` and `get_oauth_token_secret()`.
- `TokenCredentialMixin`: `get_oauth_token()`, `get_oauth_token_secret()`.
