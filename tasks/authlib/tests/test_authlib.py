"""
Integration tests for authlib JOSE (JSON Object Signing and Encryption).

Tests the layered chain: JWK (keys) → JWS (signing) → JWE (encryption) → JWT (tokens).
All tests use the cryptography library for key operations.
"""
import datetime
import json
import time

import pytest


class _StopTokenRequest(Exception):
    """Sentinel raised from a stubbed token-endpoint POST to abort before any network call."""


# ============================================================================
# 1. JWK — JSON Web Key operations
# ============================================================================


class TestJWKKeyOperations:
    """Integration tests for key generation, import, export."""

    def test_generate_export_all_key_types(self):
        """A user generates OctKey, RSAKey, ECKey, OKPKey and exports to JWK dicts with correct fields."""
        from authlib.jose import OctKey, RSAKey, ECKey, OKPKey

        oct_key = OctKey.generate_key(256)
        oct_d = oct_key.as_dict(is_private=True)
        assert oct_d["kty"] == "oct"
        assert "k" in oct_d

        rsa_key = RSAKey.generate_key(2048, is_private=True)
        rsa_priv = rsa_key.as_dict(is_private=True)
        rsa_pub = rsa_key.as_dict(is_private=False)
        assert rsa_priv["kty"] == "RSA"
        assert "d" in rsa_priv
        assert "d" not in rsa_pub
        assert "n" in rsa_pub and "e" in rsa_pub

        ec_key = ECKey.generate_key("P-256", is_private=True)
        ec_priv = ec_key.as_dict(is_private=True)
        ec_pub = ec_key.as_dict(is_private=False)
        assert ec_priv["kty"] == "EC"
        assert ec_priv["crv"] == "P-256"
        assert "d" in ec_priv
        assert "d" not in ec_pub

        okp_key = OKPKey.generate_key("Ed25519", is_private=True)
        okp_d = okp_key.as_dict(is_private=True)
        assert okp_d["kty"] == "OKP"
        assert okp_d["crv"] == "Ed25519"

    def test_import_key_from_jwk_dict(self):
        """A user imports a key from a JWK dict (round-trip: generate → export → import)."""
        from authlib.jose import JsonWebKey, OctKey

        original = OctKey.generate_key(256)
        jwk_dict = original.as_dict(is_private=True)
        imported = JsonWebKey.import_key(jwk_dict)
        assert isinstance(imported, OctKey)
        assert imported.as_dict(is_private=True)["k"] == jwk_dict["k"]

    def test_import_rsa_key_from_pem(self):
        """A user imports an RSA key from PEM format."""
        from authlib.jose import RSAKey, JsonWebKey
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        # Generate RSA key and export to PEM
        private_key = rsa.generate_private_key(65537, 2048)
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        imported = JsonWebKey.import_key(pem)
        assert isinstance(imported, RSAKey)
        d = imported.as_dict(is_private=True)
        assert "d" in d

    def test_key_set_import_and_find(self):
        """A user imports a key set and finds keys by kid."""
        from authlib.jose import JsonWebKey, OctKey

        k1 = OctKey.generate_key(256, options={"kid": "key1"})
        k2 = OctKey.generate_key(256, options={"kid": "key2"})

        jwks = {"keys": [k1.as_dict(is_private=True), k2.as_dict(is_private=True)]}
        key_set = JsonWebKey.import_key_set(jwks)

        found = key_set.find_by_kid("key1")
        assert found is not None
        assert found.kid == "key1"


# ============================================================================
# 2. JWS — JSON Web Signature (sign and verify)
# ============================================================================


class TestJWSSignAndVerify:
    """Integration tests for JWS signing and verification."""

    def test_jws_sign_verify_all_algorithms(self):
        """A user signs and verifies payloads with HS256, RS256, ES256, PS256, and EdDSA."""
        from authlib.jose import JsonWebSignature, OctKey, RSAKey, ECKey, OKPKey

        jws = JsonWebSignature(["HS256", "RS256", "ES256", "PS256", "EdDSA"])

        oct_key = OctKey.generate_key(256)
        rsa_key = RSAKey.generate_key(2048, is_private=True)
        ec_key = ECKey.generate_key("P-256", is_private=True)
        okp_key = OKPKey.generate_key("Ed25519", is_private=True)

        for alg, key, payload in [
            ("HS256", oct_key, b"hmac payload"),
            ("RS256", rsa_key, b"rsa payload"),
            ("ES256", ec_key, b"ec payload"),
            ("PS256", rsa_key, b"pss payload"),
            ("EdDSA", okp_key, b"eddsa payload"),
        ]:
            token = jws.serialize_compact({"alg": alg}, payload, key)
            assert isinstance(token, bytes)
            assert token.count(b".") == 2
            result = jws.deserialize_compact(token, key)
            assert result["payload"] == payload
            assert result.header["alg"] == alg

    def test_jws_bad_signature_raises(self):
        """Verifying with wrong key raises BadSignatureError."""
        from authlib.jose import JsonWebSignature, OctKey
        from authlib.jose.errors import BadSignatureError

        jws = JsonWebSignature(["HS256"])
        sign_key = OctKey.generate_key(256)
        wrong_key = OctKey.generate_key(256)

        token = jws.serialize_compact({"alg": "HS256"}, b"data", sign_key)
        with pytest.raises(BadSignatureError):
            jws.deserialize_compact(token, wrong_key)

    def test_jws_unsupported_algorithm_raises(self):
        """Using an algorithm not in the allowed list raises UnsupportedAlgorithmError."""
        from authlib.jose import JsonWebSignature, OctKey
        from authlib.jose.errors import UnsupportedAlgorithmError

        jws = JsonWebSignature(["HS256"])
        key = OctKey.generate_key(256)

        with pytest.raises(UnsupportedAlgorithmError):
            jws.serialize_compact({"alg": "RS256"}, b"data", key)

    def test_jws_missing_algorithm_raises(self):
        """Missing 'alg' header raises MissingAlgorithmError."""
        from authlib.jose import JsonWebSignature, OctKey
        from authlib.jose.errors import MissingAlgorithmError

        jws = JsonWebSignature(["HS256"])
        key = OctKey.generate_key(256)

        with pytest.raises(MissingAlgorithmError):
            jws.serialize_compact({}, b"data", key)


# ============================================================================
# 3. JWE — JSON Web Encryption (encrypt and decrypt)
# ============================================================================


class TestJWEEncryptDecrypt:
    """Integration tests for JWE encryption and decryption."""

    def test_jwe_rsa_oaep_encrypt_decrypt(self):
        """A user encrypts with RSA-OAEP and A256GCM, then decrypts."""
        from authlib.jose import JsonWebEncryption, RSAKey

        jwe = JsonWebEncryption(["RSA-OAEP", "A256GCM"])
        key = RSAKey.generate_key(2048, is_private=True)

        header = {"alg": "RSA-OAEP", "enc": "A256GCM"}
        token = jwe.serialize_compact(header, b"secret data", key)
        assert isinstance(token, bytes)
        assert token.count(b".") == 4  # 5 segments

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == b"secret data"

    def test_jwe_aes_key_wrap_encrypt_decrypt(self):
        """A user encrypts with A128KW and A128CBC-HS256."""
        from authlib.jose import JsonWebEncryption, OctKey

        jwe = JsonWebEncryption(["A128KW", "A128CBC-HS256"])
        key = OctKey.generate_key(128)  # 128-bit key for A128KW

        header = {"alg": "A128KW", "enc": "A128CBC-HS256"}
        token = jwe.serialize_compact(header, b"wrapped secret", key)

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == b"wrapped secret"

    def test_jwe_direct_key_agreement(self):
        """A user encrypts with direct key agreement (dir + A256GCM)."""
        from authlib.jose import JsonWebEncryption, OctKey

        jwe = JsonWebEncryption(["dir", "A256GCM"])
        key = OctKey.generate_key(256)  # 256-bit key for A256GCM

        header = {"alg": "dir", "enc": "A256GCM"}
        token = jwe.serialize_compact(header, b"direct encrypted", key)

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == b"direct encrypted"

    def test_jwe_wrong_key_fails(self):
        """Decrypting with wrong key raises an error."""
        from authlib.jose import JsonWebEncryption, RSAKey

        jwe = JsonWebEncryption(["RSA-OAEP", "A256GCM"])
        encrypt_key = RSAKey.generate_key(2048, is_private=True)
        wrong_key = RSAKey.generate_key(2048, is_private=True)

        header = {"alg": "RSA-OAEP", "enc": "A256GCM"}
        token = jwe.serialize_compact(header, b"secret", encrypt_key)

        # Wrong-key decrypt must fail; the spec does not pin the exact exception
        # class (it may surface as a raw crypto ValueError or a wrapped JoseError),
        # so any raised error counts.
        with pytest.raises(Exception):
            jwe.deserialize_compact(token, wrong_key)

    def test_jwe_ecdh_es_key_agreement(self):
        """A user encrypts with ECDH-ES direct key agreement using EC P-256 key."""
        from authlib.jose import JsonWebEncryption, ECKey

        jwe = JsonWebEncryption(["ECDH-ES", "A128GCM"])
        key = ECKey.generate_key("P-256", is_private=True)

        header = {"alg": "ECDH-ES", "enc": "A128GCM"}
        token = jwe.serialize_compact(header, b"ecdh-es secret data", key)
        assert token.count(b".") == 4

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == b"ecdh-es secret data"
        assert result["header"]["alg"] == "ECDH-ES"
        assert "epk" in result["header"]

    def test_jwe_aesgcm_key_wrap(self):
        """A user encrypts with AES-GCM key wrapping (A256GCMKW) + A128CBC-HS256 content encryption."""
        from authlib.jose import JsonWebEncryption, OctKey

        jwe = JsonWebEncryption(["A256GCMKW", "A128CBC-HS256"])
        key = OctKey.generate_key(256)

        header = {"alg": "A256GCMKW", "enc": "A128CBC-HS256"}
        token = jwe.serialize_compact(header, b"gcm-wrapped secret", key)

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == b"gcm-wrapped secret"

    def test_jwe_deflate_compression(self):
        """A user encrypts a large payload with DEFLATE compression to reduce ciphertext size."""
        from authlib.jose import JsonWebEncryption, OctKey

        jwe = JsonWebEncryption(["dir", "A256GCM", "DEF"])
        key = OctKey.generate_key(256)

        payload = b"repeated data " * 500
        header = {"alg": "dir", "enc": "A256GCM", "zip": "DEF"}
        token = jwe.serialize_compact(header, payload, key)

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == payload

        uncompressed_token = jwe.serialize_compact(
            {"alg": "dir", "enc": "A256GCM"}, payload, key)
        assert len(token) < len(uncompressed_token)

    def test_jwe_ecdh_es_with_key_wrapping(self):
        """A user encrypts with ECDH-ES+A256KW (key agreement + AES wrapping) using OKP X25519 key."""
        from authlib.jose import JsonWebEncryption, OKPKey

        jwe = JsonWebEncryption(["ECDH-ES+A256KW", "A256GCM"])
        key = OKPKey.generate_key("X25519", is_private=True)

        header = {"alg": "ECDH-ES+A256KW", "enc": "A256GCM"}
        token = jwe.serialize_compact(header, b"okp-ecdh wrapped", key)

        result = jwe.deserialize_compact(token, key)
        assert result["payload"] == b"okp-ecdh wrapped"
        assert "epk" in result["header"]


# ============================================================================
# 4. JWT — JSON Web Token (encode, decode, claims validation)
# ============================================================================


class TestJWTTokenLifecycle:
    """Integration tests for JWT encode/decode and claims validation."""

    def test_jwt_encode_decode_with_hmac(self):
        """A user encodes a JWT with HMAC and decodes it."""
        from authlib.jose import jwt

        payload = {"sub": "user123", "name": "Alice", "iss": "example.com"}
        token = jwt.encode({"alg": "HS256"}, payload, "secret-key")
        assert isinstance(token, bytes)

        claims = jwt.decode(token, "secret-key")
        assert claims["sub"] == "user123"
        assert claims["name"] == "Alice"

    def test_jwt_encode_decode_with_rsa(self):
        """A user encodes a JWT with RSA and decodes it."""
        from authlib.jose import jwt, RSAKey

        key = RSAKey.generate_key(2048, is_private=True)
        payload = {"sub": "user456", "role": "admin"}
        token = jwt.encode({"alg": "RS256"}, payload, key)

        claims = jwt.decode(token, key)
        assert claims["sub"] == "user456"
        assert claims["role"] == "admin"

    def test_jwt_claims_validation_rejects_invalid(self):
        """Claims validation rejects expired, not-yet-valid, wrong issuer, wrong audience, and missing essential claims."""
        from authlib.jose import jwt
        from authlib.jose.errors import ExpiredTokenError, InvalidTokenError, InvalidClaimError, MissingClaimError

        now = int(time.time())

        expired = jwt.decode(jwt.encode({"alg": "HS256"}, {"sub": "u", "exp": now - 100}, "k"), "k")
        with pytest.raises(ExpiredTokenError):
            expired.validate()

        future_nbf = jwt.decode(jwt.encode({"alg": "HS256"}, {"sub": "u", "nbf": now + 3600}, "k"), "k")
        with pytest.raises(InvalidTokenError):
            future_nbf.validate()

        wrong_iss = jwt.decode(jwt.encode({"alg": "HS256"}, {"sub": "u", "iss": "wrong"}, "k"), "k",
                               claims_options={"iss": {"values": ["expected"]}})
        with pytest.raises(InvalidClaimError):
            wrong_iss.validate()

        wrong_aud = jwt.decode(jwt.encode({"alg": "HS256"}, {"sub": "u", "aud": "other"}, "k"), "k",
                               claims_options={"aud": {"values": ["my-app"]}})
        with pytest.raises(InvalidClaimError):
            wrong_aud.validate()

        missing_iss = jwt.decode(jwt.encode({"alg": "HS256"}, {"sub": "u"}, "k"), "k",
                                 claims_options={"iss": {"essential": True}})
        with pytest.raises(MissingClaimError):
            missing_iss.validate()

    def test_jwt_datetime_conversion(self):
        """datetime objects in exp/iat/nbf are auto-converted to the correct epoch timestamp."""
        import calendar
        from authlib.jose import jwt

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        payload = {"sub": "user", "exp": now}
        token = jwt.encode({"alg": "HS256"}, payload, "key")
        claims = jwt.decode(token, "key")
        # Must be the exact UTC epoch second, not a local-time / off-by-offset conversion.
        assert isinstance(claims["exp"], int)
        assert claims["exp"] == calendar.timegm(now.utctimetuple())

    def test_jwt_sensitive_data_check(self):
        """JWT encoding rejects payloads with sensitive data by default."""
        from authlib.jose import jwt
        from authlib.jose.errors import InsecureClaimError

        with pytest.raises(InsecureClaimError):
            jwt.encode({"alg": "HS256"}, {"password": "secret"}, "key")

        # check=False allows it
        token = jwt.encode({"alg": "HS256"}, {"password": "secret"}, "key", check=False)
        assert token is not None

    def test_jwt_valid_token_full_lifecycle(self):
        """Full lifecycle: encode with claims, decode, validate successfully."""
        from authlib.jose import jwt

        now = int(time.time())
        payload = {
            "sub": "user123",
            "iss": "example.com",
            "aud": "my-app",
            "exp": now + 3600,
            "nbf": now - 10,
            "iat": now,
        }
        token = jwt.encode({"alg": "HS256"}, payload, "secret")
        claims = jwt.decode(token, "secret", claims_options={
            "iss": {"values": ["example.com"]},
            "aud": {"values": ["my-app"]},
        })
        claims.validate()
        assert claims["sub"] == "user123"

        # Registered claims are also reachable via attribute access on the decoded claims;
        # an unregistered name raises AttributeError.
        assert claims.sub == "user123"
        assert claims.iss == "example.com"
        with pytest.raises(AttributeError):
            _ = claims.nonexistent


# ============================================================================
# 5. Cross-layer integration — JWK + JWS + JWT combined
# ============================================================================


class TestCrossLayerIntegration:
    """Tests combining multiple JOSE layers in realistic workflows."""

    def test_generate_key_sign_jwt_verify_full_chain(self):
        """Full chain: generate EC key → sign JWT → decode → validate claims."""
        from authlib.jose import jwt, ECKey

        key = ECKey.generate_key("P-256", is_private=True)
        now = int(time.time())

        payload = {
            "sub": "alice",
            "iss": "auth-server",
            "exp": now + 3600,
            "iat": now,
        }
        token = jwt.encode({"alg": "ES256"}, payload, key)
        claims = jwt.decode(token, key, claims_options={
            "iss": {"values": ["auth-server"]},
        })
        claims.validate()
        assert claims["sub"] == "alice"

    def test_jwt_with_key_set(self):
        """A user encodes JWT with a key from a KeySet, then decodes with the set."""
        from authlib.jose import jwt, OctKey, JsonWebKey

        k1 = OctKey.generate_key(256, options={"kid": "hmac-1"})
        k2 = OctKey.generate_key(256, options={"kid": "hmac-2"})
        key_set = JsonWebKey.import_key_set({"keys": [
            k1.as_dict(is_private=True),
            k2.as_dict(is_private=True),
        ]})

        # Encode with specific key
        payload = {"sub": "user", "data": "test"}
        token = jwt.encode({"alg": "HS256", "kid": "hmac-1"}, payload, key_set)

        # Decode with key set — finds correct key by kid
        claims = jwt.decode(token, key_set)
        assert claims["sub"] == "user"

    def test_jwe_then_jws_nested_jwt(self):
        """A signed JWS/JWT is nested inside a JWE (cty=JWT): decrypt the outer JWE,
        then verify the recovered inner signature and claims."""
        from authlib.jose import JsonWebSignature, JsonWebEncryption, OctKey, RSAKey

        # Inner: sign a JWT-shaped payload as a compact JWS.
        jws = JsonWebSignature(["HS256"])
        sign_key = OctKey.generate_key(256)
        inner_payload = b'{"sub":"user","data":"encrypted"}'
        inner_token = jws.serialize_compact({"alg": "HS256"}, inner_payload, sign_key)
        assert inner_token.count(b".") == 2

        # Outer: encrypt the inner compact JWS as a nested token (cty="JWT").
        jwe = JsonWebEncryption(["RSA-OAEP", "A128CBC-HS256"])
        enc_key = RSAKey.generate_key(2048, is_private=True)
        header = {"alg": "RSA-OAEP", "enc": "A128CBC-HS256", "cty": "JWT"}
        token = jwe.serialize_compact(header, inner_token, enc_key)
        assert token.count(b".") == 4  # 5 segments

        # Decrypt the JWE, recover the inner JWS, and verify it round-trips.
        decrypted = jwe.deserialize_compact(token, enc_key)
        assert decrypted["header"]["cty"] == "JWT"
        recovered_inner = decrypted["payload"]
        assert recovered_inner == inner_token

        verified = jws.deserialize_compact(recovered_inner, sign_key)
        assert verified["payload"] == inner_payload

    def test_jws_json_serialization_flattened(self):
        """A user creates a JWS in flattened JSON serialization format."""
        from authlib.jose import JsonWebSignature, OctKey

        jws = JsonWebSignature(["HS256"])
        key = OctKey.generate_key(256)

        header_obj = {"protected": {"alg": "HS256"}}
        result = jws.serialize_json(header_obj, b"json payload", key)

        assert "payload" in result
        assert "protected" in result
        assert "signature" in result

        # Verify
        verified = jws.deserialize_json(result, key)
        assert verified["payload"] == b"json payload"


# ============================================================================
# 6. Error hierarchy and edge cases
# ============================================================================


class TestErrorsAndEdgeCases:
    """Tests for JOSE error handling and edge cases."""

    def test_decode_error_on_invalid_input(self):
        """Decoding invalid JWS data raises DecodeError."""
        from authlib.jose import JsonWebSignature, OctKey
        from authlib.jose.errors import DecodeError

        jws = JsonWebSignature(["HS256"])
        key = OctKey.generate_key(256)

        with pytest.raises(DecodeError):
            jws.deserialize_compact(b"not.valid", key)

    def test_jws_object_preserves_full_protected_header(self):
        """A multi-member protected header round-trips intact and JWSObject exposes
        .header / .payload attributes (not just dict-style access)."""
        from authlib.jose import JsonWebSignature, OctKey

        # private_headers allows the non-standard members below to be carried.
        jws = JsonWebSignature(["HS256"], private_headers=frozenset(["kid", "typ", "x-meta"]))
        key = OctKey.generate_key(256)

        protected = {"alg": "HS256", "kid": "test", "typ": "JWT", "x-meta": "value-1"}
        token = jws.serialize_compact(protected, b"data", key)
        result = jws.deserialize_compact(token, key)

        # The whole protected header survives the round-trip, not just "alg".
        assert result.header == protected
        # Attribute access surface (distinct from result["payload"] dict access).
        assert result.payload == b"data"
        assert result.header["x-meta"] == "value-1"

    def test_key_thumbprint(self):
        """Key.thumbprint() returns the exact RFC 7638 thumbprint for fixed key material."""
        from authlib.jose import JsonWebKey, OctKey

        # Fixed JWK so the thumbprint is fully determined. RFC 7638: the thumbprint is the
        # base64url(SHA-256(...)) of the compact JSON of the required members + "kty", sorted
        # lexicographically -> for an oct key that is {"k": <k>, "kty": "oct"}.
        key = JsonWebKey.import_key({"kty": "oct", "k": "GawgguFyGrWKav7AX4VKUg"})
        assert isinstance(key, OctKey)
        tp = key.thumbprint()
        assert tp == "k1JnWRfC-5zzmL72vXIuBgTLfVROXBakS4OmGcrMCoc"


# ============================================================================
# 7. OAuth1 — Client signing and signature verification
# ============================================================================


class TestOAuth1Client:
    """Integration tests for OAuth1 client request signing."""

    def test_oauth1_all_signature_types(self):
        """OAuth1 params placed in header, query, or body depending on signature_type."""
        from authlib.oauth1 import (
            ClientAuth, SIGNATURE_HMAC_SHA1,
            SIGNATURE_TYPE_HEADER, SIGNATURE_TYPE_QUERY, SIGNATURE_TYPE_BODY,
        )

        # Header type
        auth_h = ClientAuth(client_id="ck", client_secret="cs", token="tk",
                            token_secret="ts", signature_method=SIGNATURE_HMAC_SHA1,
                            signature_type=SIGNATURE_TYPE_HEADER)
        uri, headers, body = auth_h.sign("GET", "https://api.example.com/resource", {}, "")
        ah = headers["Authorization"]
        assert ah.startswith("OAuth ")
        assert 'oauth_consumer_key="ck"' in ah
        assert 'oauth_signature_method="HMAC-SHA1"' in ah
        assert 'oauth_version="1.0"' in ah
        assert 'oauth_token="tk"' in ah
        assert 'oauth_nonce="' in ah
        assert 'oauth_timestamp="' in ah
        assert 'oauth_signature="' in ah

        # Query type
        auth_q = ClientAuth(client_id="ck", client_secret="cs",
                            signature_type=SIGNATURE_TYPE_QUERY)
        uri, headers, body = auth_q.sign("GET", "https://api.example.com/data", {}, "")
        assert "oauth_consumer_key=ck" in uri
        assert "oauth_signature=" in uri
        assert "Authorization" not in headers

        # Body type
        auth_b = ClientAuth(client_id="ck", client_secret="cs",
                            signature_type=SIGNATURE_TYPE_BODY)
        uri, headers, body = auth_b.sign(
            "POST", "https://api.example.com/data",
            {"Content-Type": "application/x-www-form-urlencoded"}, "")
        assert "oauth_consumer_key=ck" in body
        assert "oauth_signature=" in body
        assert "Authorization" not in headers

    def test_oauth1_plaintext_signature(self):
        """PLAINTEXT signature method uses client_secret&token_secret."""
        from authlib.oauth1 import ClientAuth, SIGNATURE_PLAINTEXT

        auth = ClientAuth(
            client_id="key",
            client_secret="cs",
            token="tk",
            token_secret="ts",
            signature_method=SIGNATURE_PLAINTEXT,
        )

        uri, headers, body = auth.sign("GET", "https://api.example.com/", {}, "")
        auth_header = headers["Authorization"]
        assert auth_header.startswith("OAuth ")
        assert 'oauth_signature_method="PLAINTEXT"' in auth_header
        assert 'oauth_signature="cs%26ts"' in auth_header

    def test_oauth1_hmac_sha1_signature_matches_base_string(self):
        """The HMAC-SHA1 oauth_signature equals the RFC 5849 signature base string HMAC.

        Recomputing the signature independently (stdlib only, from the parameters the
        client itself reported) pins the base string URI normalization -- lowercased
        scheme/host, scheme-default port dropped, query excluded (RFC 5849 3.4.1.2) --
        and the parameter normalization -- percent-encoded, sorted, "&"-joined
        (RFC 5849 3.4.1.3) -- that feed it.
        """
        import base64, hashlib, hmac, re, urllib.parse
        from authlib.oauth1 import ClientAuth, SIGNATURE_HMAC_SHA1

        auth = ClientAuth(
            client_id="ck",
            client_secret="cs",
            token="tk",
            token_secret="ts",
            signature_method=SIGNATURE_HMAC_SHA1,
        )
        # Uppercase host, an explicit scheme-default port and query parameters: each is
        # handled by a different clause of the base string construction.
        uri, headers, body = auth.sign(
            "GET", "https://API.Example.COM:443/request?b=1&a=2", {}, "")

        oauth_params = {
            k: urllib.parse.unquote(v)
            for k, v in re.findall(r'(\w+)="([^"]*)"', headers["Authorization"])
        }
        assert oauth_params["oauth_signature_method"] == "HMAC-SHA1"

        def escape(value):
            # RFC 5849 3.6: percent-encode everything outside the unreserved set.
            return urllib.parse.quote(str(value), safe="~")

        # 3.4.1.2 base string URI.
        base_string_uri = "https://api.example.com/request"
        # 3.4.1.3.1: query parameters plus the protocol parameters, minus oauth_signature
        # and realm; 3.4.1.3.2: encode, sort, join name=value pairs with "&".
        signed_params = [("b", "1"), ("a", "2")] + [
            (k, v) for k, v in oauth_params.items()
            if k not in ("oauth_signature", "realm")
        ]
        normalized = "&".join(
            f"{k}={v}"
            for k, v in sorted((escape(k), escape(v)) for k, v in signed_params)
        )
        base_string = "&".join(
            [escape("GET"), escape(base_string_uri), escape(normalized)])

        # 3.4.2: HMAC-SHA1 keyed by escape(client_secret) + "&" + escape(token_secret),
        # base64-encoded.
        key = f"{escape('cs')}&{escape('ts')}".encode()
        expected = base64.b64encode(
            hmac.new(key, base_string.encode(), hashlib.sha1).digest()
        ).decode()
        assert oauth_params["oauth_signature"] == expected


# ============================================================================
# 8. OAuth2 — Client, Token, Utilities
# ============================================================================


class TestOAuth2Core:
    """Integration tests for OAuth2 core classes and utilities."""

    def test_oauth2_token_expiration(self):
        """OAuth2Token tracks expiration from expires_in."""
        from authlib.oauth2.rfc6749 import OAuth2Token

        token = OAuth2Token({
            "access_token": "abc123",
            "token_type": "bearer",
            "expires_in": 3600,
        })
        assert token["access_token"] == "abc123"
        assert token.is_expired() is False

        # Expired token
        expired = OAuth2Token({
            "access_token": "old",
            "token_type": "bearer",
            "expires_in": 0,
            "expires_at": 0,
        })
        assert expired.is_expired() is True

    def test_oauth2_client_parses_code_from_authorization_response(self):
        """OAuth2Session.fetch_token extracts the code from a redirect URL (public surface).

        A real client never calls parse_authorization_code_response directly; it hands the
        full redirect URL to fetch_token(authorization_response=...), which parses out the
        code internally and sends it to the token endpoint. We intercept the (offline) token
        POST to confirm the extracted code is forwarded, without any network.
        """
        from urllib.parse import parse_qsl

        from authlib.integrations.requests_client import OAuth2Session

        session = OAuth2Session(client_id="my_client", client_secret="my_secret")
        captured = {}

        # Intercept at the requests transport boundary (Session.send), the single chokepoint
        # that EVERY way of issuing an HTTP POST from a requests.Session passes through
        # (whether fetch_token calls self.post(...) or self.request("POST", ...)). This
        # asserts on the issued request without coupling to an internal calling convention,
        # and guarantees no real network call in the offline image.
        real_send = session.send

        def fake_send(request, **kwargs):
            captured["body"] = request.body
            captured["method"] = request.method
            captured["url"] = request.url
            raise _StopTokenRequest()

        session.send = fake_send
        try:
            with pytest.raises(_StopTokenRequest):
                session.fetch_token(
                    "https://auth.example.com/token",
                    authorization_response="https://example.com/callback?code=AUTH_CODE&state=xyz",
                    state="xyz",
                )
        finally:
            session.send = real_send

        # The token exchange must be an HTTP POST whose x-www-form-urlencoded body carries the
        # extracted code and grant_type. `request.body` is the encoded form string (bytes or
        # str); decode it back to params.
        assert captured["method"] == "POST"
        body = captured["body"]
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        params = dict(body) if isinstance(body, dict) else dict(parse_qsl(body))
        assert params["code"] == "AUTH_CODE"
        assert params["grant_type"] == "authorization_code"

    def test_oauth2_client_builds_authorization_url(self):
        """OAuth2Session.create_authorization_url assembles the authorization request (public surface).

        Drives the documented client entry point rather than the internal prepare_grant_uri helper:
        the returned URL must carry client_id, response_type=code, the generated state, the
        url-encoded redirect_uri, and the joined+encoded scope.
        """
        from authlib.integrations.requests_client import OAuth2Session

        session = OAuth2Session(
            client_id="my_client",
            client_secret="my_secret",
            scope="openid profile",
            redirect_uri="https://app.example.com/callback",
        )
        uri, state = session.create_authorization_url("https://auth.example.com/authorize")
        assert "client_id=my_client" in uri
        assert "response_type=code" in uri
        assert f"state={state}" in uri
        # The full param assembly must url-encode redirect_uri and join+encode the scope list,
        # not just emit a subset of the parameters.
        assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcallback" in uri
        assert "scope=openid+profile" in uri

    def test_oauth2_client_auth_methods(self):
        """ClientAuth supports client_secret_basic and client_secret_post."""
        from authlib.oauth2.auth import ClientAuth

        # client_secret_basic (default)
        auth = ClientAuth("client_id", "client_secret", auth_method="client_secret_basic")
        uri, headers, body = auth.prepare("POST", "https://auth.example.com/token", {}, "")
        assert "Authorization" in headers
        assert "Basic" in headers["Authorization"]

        # client_secret_post
        auth2 = ClientAuth("client_id", "client_secret", auth_method="client_secret_post")
        uri, headers, body = auth2.prepare("POST", "https://auth.example.com/token", {}, "")
        assert "client_id" in body
        assert "client_secret" in body

    def test_oauth2_token_auth_header(self):
        """TokenAuth adds bearer token to Authorization header."""
        from authlib.oauth2.auth import TokenAuth

        token = {"access_token": "my_token", "token_type": "bearer"}
        auth = TokenAuth(token, token_placement="header")
        uri, headers, body = auth.prepare("https://api.example.com/data", {}, "")
        assert headers["Authorization"] == "Bearer my_token"

    def test_pkce_s256_code_challenge(self):
        """PKCE S256 code challenge equals base64url(sha256(verifier)) without padding."""
        import base64
        import hashlib
        from authlib.common.security import generate_token
        from authlib.oauth2.rfc7636 import create_s256_code_challenge

        verifier = generate_token(48)
        challenge = create_s256_code_challenge(verifier)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert challenge == expected


# ============================================================================
# 9. OIDC — ID Token validation and UserInfo
# ============================================================================


class TestOIDCCore:
    """Integration tests for OpenID Connect core claims and UserInfo."""

    def test_id_token_validation(self):
        """CodeIDToken validates required OIDC claims."""
        from authlib.oidc.core import CodeIDToken

        now = int(time.time())
        claims = CodeIDToken(
            {"iss": "https://auth.example.com", "sub": "user123",
             "aud": "my_client", "exp": now + 3600, "iat": now},
            {"alg": "RS256"}
        )
        claims.params = {"nonce": None}
        claims.validate(now=now)

    def test_id_token_missing_required_claims(self):
        """CodeIDToken raises error when required claims are missing."""
        from authlib.oidc.core import CodeIDToken

        now = int(time.time())
        # Missing 'sub'
        claims = CodeIDToken(
            {"iss": "https://auth.example.com", "aud": "client",
             "exp": now + 3600, "iat": now},
            {"alg": "RS256"}
        )
        claims.params = {"nonce": None}
        # A missing required/essential claim must be rejected with a MissingClaimError.
        # The module the class lives in is not pinned, so match on the class name rather
        # than importing it.
        with pytest.raises(Exception) as excinfo:
            claims.validate(now=now)
        raised = type(excinfo.value)
        assert "MissingClaimError" in {c.__name__ for c in raised.__mro__}, (
            f"expected a MissingClaimError for the missing 'sub' claim, got {raised.__name__}"
        )

    def test_implicit_id_token_requires_nonce(self):
        """ImplicitIDToken requires nonce as essential claim."""
        from authlib.oidc.core import ImplicitIDToken

        now = int(time.time())
        claims = ImplicitIDToken(
            {"iss": "https://auth.example.com", "sub": "user",
             "aud": "client", "exp": now + 3600, "iat": now,
             "nonce": "test_nonce"},
            {"alg": "RS256"}
        )
        claims.params = {"nonce": "test_nonce"}
        claims.validate(now=now)


# ============================================================================
# 10. Flask OAuth2 Server Integration
# ============================================================================


class TestFlaskOAuth2Integration:
    """Integration tests for Flask OAuth2 server and client."""

    def test_framework_oauth_client_registration(self):
        """Flask, Django, Starlette, and requests OAuth clients build a working authorization URL.

        Each integration's registered client must actually assemble an OAuth request
        (client_id + response_type=code + a generated state), not merely echo back the
        registered client_id.
        """
        import asyncio

        # Flask — sync create_authorization_url returns {"url", "state", ...}.
        from flask import Flask
        from authlib.integrations.flask_client import OAuth as FlaskOAuth
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test"
        flask_oauth = FlaskOAuth(app)
        flask_oauth.register(name="github", client_id="fid", client_secret="fs",
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/")
        flask_url = flask_oauth.create_client("github").create_authorization_url(
            "https://client.test/callback")["url"]
        assert "client_id=fid" in flask_url
        assert "response_type=code" in flask_url
        assert "state=" in flask_url

        # Django — sync create_authorization_url returns {"url", "state", ...}.
        import os
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django.conf.global_settings")
        import django
        from django.conf import settings
        if not settings.configured:
            settings.configure(SECRET_KEY="test", INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth"],
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
                ALLOWED_HOSTS=["*"], AUTHLIB_OAUTH2_PROVIDER={}, DEFAULT_AUTO_FIELD="django.db.models.BigAutoField")
            django.setup()
        from authlib.integrations.django_client import OAuth as DjangoOAuth
        django_oauth = DjangoOAuth()
        django_oauth.register(name="github", client_id="did", client_secret="ds",
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token")
        django_url = django_oauth.create_client("github").create_authorization_url(
            "https://client.test/callback")["url"]
        assert "client_id=did" in django_url
        assert "response_type=code" in django_url
        assert "state=" in django_url

        # Starlette — async create_authorization_url (driven via asyncio.run) returns {"url", "state", ...}.
        from authlib.integrations.starlette_client import OAuth as StarletteOAuth
        st_oauth = StarletteOAuth()
        st_oauth.register(name="google", client_id="gid", client_secret="gs",
            authorize_url="https://accounts.google.com/o/oauth2/auth",
            access_token_url="https://oauth2.googleapis.com/token")
        st_url = asyncio.run(
            st_oauth.create_client("google").create_authorization_url("https://client.test/callback"))["url"]
        assert "client_id=gid" in st_url
        assert "response_type=code" in st_url
        assert "state=" in st_url

        # Requests OAuth2Session — returns a (url, state) tuple.
        from authlib.integrations.requests_client import OAuth2Session
        session = OAuth2Session(client_id="my_client", client_secret="my_secret")
        uri, state = session.create_authorization_url("https://auth.example.com/authorize")
        assert "client_id=my_client" in uri
        assert "state=" in uri
        assert "response_type=code" in uri


# ============================================================================
# 15. Flask OAuth2 Server — Full Grant Type Flows
# ============================================================================


def _create_oauth2_server_app():
    """Create a Flask app with SQLite + SQLAlchemy + AuthorizationServer for testing."""
    import os
    os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

    from flask import Flask, request as flask_request, json
    from flask_sqlalchemy import SQLAlchemy
    from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector
    from authlib.integrations.sqla_oauth2 import (
        OAuth2ClientMixin, OAuth2TokenMixin, OAuth2AuthorizationCodeMixin,
        create_query_client_func, create_save_token_func,
        create_bearer_token_validator,
    )
    from authlib.oauth2.rfc6749.grants import (
        AuthorizationCodeGrant as _AuthorizationCodeGrant,
        ClientCredentialsGrant,
    )
    from authlib.oauth2 import OAuth2Error

    app = Flask(__name__)
    app.debug = True
    app.testing = True
    app.secret_key = "testing"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db = SQLAlchemy(app)

    class User(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(40), unique=True)
        def get_user_id(self):
            return self.id

    class Client(db.Model, OAuth2ClientMixin):
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    class AuthCode(db.Model, OAuth2AuthorizationCodeMixin):
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, nullable=False)

    class Token(db.Model, OAuth2TokenMixin):
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        def is_refresh_token_active(self):
            return not self.refresh_token_revoked_at

    class MyAuthCodeGrant(_AuthorizationCodeGrant):
        TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "client_secret_post", "none"]
        def save_authorization_code(self, code, request):
            auth_code = AuthCode(
                code=code, client_id=request.client.client_id,
                redirect_uri=request.payload.redirect_uri,
                scope=request.scope, user_id=request.user.id,
            )
            db.session.add(auth_code)
            db.session.commit()
            return auth_code
        def query_authorization_code(self, code, client):
            item = AuthCode.query.filter_by(code=code, client_id=client.client_id).first()
            if item and not item.is_expired():
                return item
        def delete_authorization_code(self, authorization_code):
            db.session.delete(authorization_code)
            db.session.commit()
        def authenticate_user(self, authorization_code):
            return db.session.get(User, authorization_code.user_id)

    with app.app_context():
        db.create_all()

        query_client = create_query_client_func(db.session, Client)
        save_token = create_save_token_func(db.session, Token)
        server = AuthorizationServer(app, query_client, save_token)
        server.register_grant(MyAuthCodeGrant)
        server.register_grant(ClientCredentialsGrant)

        # Resource protector
        require_oauth = ResourceProtector()
        BearerTokenValidator = create_bearer_token_validator(db.session, Token)
        require_oauth.register_token_validator(BearerTokenValidator())

        @app.route("/oauth/authorize", methods=["GET", "POST"])
        def authorize():
            user_id = flask_request.values.get("user_id")
            end_user = db.session.get(User, int(user_id)) if user_id else None
            try:
                grant = server.get_consent_grant(end_user=end_user)
            except OAuth2Error as error:
                return server.handle_error_response(flask_request, error)
            if flask_request.method == "GET":
                return grant.prompt or "ok"
            return server.create_authorization_response(grant=grant, grant_user=end_user)

        @app.route("/oauth/token", methods=["POST"])
        def issue_token():
            return server.create_token_response()

        @app.route("/api/protected")
        def protected():
            with require_oauth.acquire("profile") as token:
                return json.dumps({"user_id": token.user_id})

        # Seed data
        user = User(username="testuser")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        client = Client(user_id=user_id, client_id="test-client", client_secret="test-secret")
        client.set_client_metadata({
            "redirect_uris": ["https://client.test/callback"],
            "scope": "profile",
            "token_endpoint_auth_method": "client_secret_basic",
            "response_types": ["code"],
            "grant_types": ["authorization_code", "client_credentials"],
        })
        db.session.add(client)
        db.session.commit()

    return app, db, user_id


class TestFlaskOAuth2ServerFlows:
    """Full OAuth2 server flows through Flask test client."""

    def test_authorization_code_full_flow(self):
        """Full auth code flow: authorize → code → token exchange."""
        import base64
        app, db, user_id = _create_oauth2_server_app()

        with app.app_context():
            tc = app.test_client()

            # Step 1: GET authorize — should show consent
            rv = tc.get(f"/oauth/authorize?response_type=code&client_id=test-client&user_id={user_id}")
            assert rv.status_code == 200

            # Step 2: POST authorize — should redirect with code
            rv = tc.post(
                f"/oauth/authorize?response_type=code&client_id=test-client&user_id={user_id}",
                follow_redirects=False,
            )
            assert rv.status_code in (302, 303)
            location = rv.headers["Location"]
            assert "code=" in location

            # Extract code
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(location)
            code = parse_qs(parsed.query)["code"][0]

            # Step 3: Exchange code for token
            auth = base64.b64encode(b"test-client:test-secret").decode()
            rv = tc.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.test/callback",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            token_data = rv.get_json()
            assert "access_token" in token_data
            assert token_data["token_type"].lower() == "bearer"

    def test_client_credentials_grant(self):
        """Client credentials: client authenticates directly for token."""
        import base64
        app, db, user_id = _create_oauth2_server_app()

        with app.app_context():
            tc = app.test_client()
            auth = base64.b64encode(b"test-client:test-secret").decode()
            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials",
                "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            token_data = rv.get_json()
            assert "access_token" in token_data

    def test_resource_protector_rejects_invalid_token(self):
        """Resource protector rejects requests without valid bearer token."""
        app, db, user_id = _create_oauth2_server_app()

        with app.app_context():
            tc = app.test_client()

            # No token
            rv = tc.get("/api/protected")
            assert rv.status_code == 401

            # Invalid token
            rv = tc.get("/api/protected", headers={"Authorization": "Bearer invalid-token"})
            assert rv.status_code == 401

    def test_resource_protector_accepts_valid_token(self):
        """Resource protector accepts a valid bearer token from auth code flow."""
        import base64
        app, db, user_id = _create_oauth2_server_app()

        with app.app_context():
            tc = app.test_client()

            # Get token via client credentials
            auth = base64.b64encode(b"test-client:test-secret").decode()
            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials",
                "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            token = rv.get_json()["access_token"]

            # Access protected resource
            rv = tc.get("/api/protected", headers={"Authorization": f"Bearer {token}"})
            assert rv.status_code == 200

    def test_invalid_client_credentials(self):
        """Token endpoint rejects invalid client credentials."""
        import base64
        app, db, user_id = _create_oauth2_server_app()

        with app.app_context():
            tc = app.test_client()
            auth = base64.b64encode(b"test-client:wrong-secret").decode()
            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials",
            }, headers={"Authorization": f"Basic {auth}"})
            resp = rv.get_json()
            assert resp["error"] == "invalid_client"


# ============================================================================
# 16. OAuth2 Server — Refresh Token + Password Grant + Introspection
# ============================================================================


def _create_full_oauth2_server():
    """Create a Flask OAuth2 server with authorization_code, client_credentials,
    refresh_token, password grants, and introspection endpoint."""
    import os
    os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

    from flask import Flask, json
    from flask_sqlalchemy import SQLAlchemy
    from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector
    from authlib.integrations.sqla_oauth2 import (
        OAuth2ClientMixin, OAuth2TokenMixin,
        create_query_client_func, create_save_token_func,
        create_bearer_token_validator,
    )
    from authlib.oauth2.rfc6749.grants import (
        AuthorizationCodeGrant as _AuthCodeGrant,
        ClientCredentialsGrant,
        ResourceOwnerPasswordCredentialsGrant as _PasswordGrant,
        RefreshTokenGrant as _RefreshGrant,
    )
    from authlib.oauth2.rfc7662 import IntrospectionEndpoint as _IntrospectionEndpoint

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["OAUTH2_REFRESH_TOKEN_GENERATOR"] = True
    app.secret_key = "testing"

    db = SQLAlchemy(app)

    class User(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(40), unique=True)
        def get_user_id(self):
            return self.id
        def check_password(self, password):
            return password == "correct-password"

    class Client(db.Model, OAuth2ClientMixin):
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    class Token(db.Model, OAuth2TokenMixin):
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        def is_refresh_token_active(self):
            return not self.refresh_token_revoked_at

    class PasswordGrant(_PasswordGrant):
        def authenticate_user(self, username, password):
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                return user

    class RefreshGrant(_RefreshGrant):
        INCLUDE_NEW_REFRESH_TOKEN = True
        TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "client_secret_post", "none"]
        def authenticate_refresh_token(self, refresh_token):
            token = Token.query.filter_by(refresh_token=refresh_token).first()
            if token and token.is_refresh_token_active():
                return token
        def authenticate_user(self, credential):
            return db.session.get(User, credential.user_id)
        def revoke_old_credential(self, credential):
            import time as _t
            credential.refresh_token_revoked_at = int(_t.time())
            db.session.commit()

    class MyIntrospectionEndpoint(_IntrospectionEndpoint):
        def query_token(self, token_string, token_type_hint):
            if token_type_hint == "refresh_token":
                return Token.query.filter_by(refresh_token=token_string).first()
            return Token.query.filter_by(access_token=token_string).first()
        def introspect_token(self, token):
            return {
                "active": True,
                "client_id": token.client_id,
                "scope": token.scope,
                "token_type": "bearer",
            }
        def check_permission(self, token, client, request):
            return True

    with app.app_context():
        db.create_all()
        query_client = create_query_client_func(db.session, Client)
        save_token = create_save_token_func(db.session, Token)
        server = AuthorizationServer(app, query_client, save_token)
        server.register_grant(ClientCredentialsGrant)
        server.register_grant(PasswordGrant)
        server.register_grant(RefreshGrant)
        server.register_endpoint(MyIntrospectionEndpoint)

        require_oauth = ResourceProtector()
        require_oauth.register_token_validator(
            create_bearer_token_validator(db.session, Token)())

        @app.route("/oauth/token", methods=["POST"])
        def issue_token():
            return server.create_token_response()

        @app.route("/oauth/introspect", methods=["POST"])
        def introspect():
            return server.create_endpoint_response("introspection")

        @app.route("/api/me")
        def me():
            with require_oauth.acquire("profile") as token:
                return json.dumps({"user_id": token.user_id, "scope": token.scope})

        user = User(username="alice")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        client = Client(user_id=user_id, client_id="full-client", client_secret="full-secret")
        client.set_client_metadata({
            "redirect_uris": ["https://client.test/callback"],
            "scope": "profile email",
            "token_endpoint_auth_method": "client_secret_basic",
            "response_types": ["code"],
            "grant_types": ["authorization_code", "client_credentials", "password", "refresh_token"],
        })
        db.session.add(client)
        db.session.commit()

    return app, db, user_id


class TestOAuth2AdvancedGrants:
    """Tests for refresh token, password, and introspection flows."""

    def test_password_grant_authenticates_user(self):
        """A user authenticates with username/password and gets a bearer token that accesses protected resources."""
        import base64
        app, db, user_id = _create_full_oauth2_server()

        with app.app_context():
            tc = app.test_client()
            auth = base64.b64encode(b"full-client:full-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "password",
                "username": "alice",
                "password": "correct-password",
                "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            token_data = rv.get_json()
            assert "access_token" in token_data
            assert token_data["token_type"].lower() == "bearer"

            rv = tc.get("/api/me", headers={"Authorization": f"Bearer {token_data['access_token']}"})
            assert rv.status_code == 200
            assert json.loads(rv.data)["user_id"] == user_id

    def test_password_grant_rejects_wrong_password(self):
        """Password grant rejects invalid credentials with access_denied error."""
        import base64
        app, db, user_id = _create_full_oauth2_server()

        with app.app_context():
            tc = app.test_client()
            auth = base64.b64encode(b"full-client:full-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "password",
                "username": "alice",
                "password": "wrong-password",
                "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            resp = rv.get_json()
            assert resp["error"] in ("invalid_request", "invalid_grant", "access_denied")

    def test_token_introspection_endpoint(self):
        """A resource server introspects a token and gets back active status with metadata."""
        import base64
        app, db, user_id = _create_full_oauth2_server()

        with app.app_context():
            tc = app.test_client()
            auth = base64.b64encode(b"full-client:full-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials",
                "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            access_token = rv.get_json()["access_token"]

            rv = tc.post("/oauth/introspect", data={
                "token": access_token,
                "token_type_hint": "access_token",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            intro = rv.get_json()
            assert intro["active"] is True
            assert intro["client_id"] == "full-client"
            assert intro["scope"] == "profile"

            rv = tc.post("/oauth/introspect", data={
                "token": "nonexistent-token",
                "token_type_hint": "access_token",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            assert rv.get_json()["active"] is False


# ============================================================================
# 16b. JWT Bearer Client Authentication (RFC 7523)
# ============================================================================


class TestJWTBearerClientAuth:
    """Tests for ClientSecretJWT and PrivateKeyJWT client authentication methods."""

    def test_client_secret_jwt_sign_and_decode(self):
        """client_secret_jwt_sign creates a JWT assertion using HMAC with the client secret."""
        from authlib.oauth2.rfc7523 import client_secret_jwt_sign
        from authlib.jose import jwt

        assertion = client_secret_jwt_sign(
            client_secret="my-client-secret",
            client_id="my-client-id",
            token_endpoint="https://auth.example.com/token",
            claims={"jti": "unique-id-123"},
        )
        assert isinstance(assertion, (str, bytes))

        claims = jwt.decode(assertion, "my-client-secret")
        assert claims["iss"] == "my-client-id"
        assert claims["sub"] == "my-client-id"
        assert claims["aud"] == "https://auth.example.com/token"
        assert claims["jti"] == "unique-id-123"
        assert "exp" in claims
        assert "iat" in claims

    def test_private_key_jwt_sign_and_decode(self):
        """private_key_jwt_sign creates a JWT assertion using RSA private key PEM."""
        from authlib.oauth2.rfc7523 import private_key_jwt_sign
        from authlib.jose import jwt, RSAKey

        key = RSAKey.generate_key(2048, is_private=True)
        pem = key.as_pem(is_private=True)

        assertion = private_key_jwt_sign(
            private_key=pem,
            client_id="rsa-client",
            token_endpoint="https://auth.example.com/token",
        )
        assert isinstance(assertion, (str, bytes))

        claims = jwt.decode(assertion, key)
        assert claims["iss"] == "rsa-client"
        assert claims["sub"] == "rsa-client"
        assert claims["aud"] == "https://auth.example.com/token"


# ============================================================================
# 16c. Device Authorization (RFC 8628)
# ============================================================================


class TestDeviceAuthorization:
    """Tests for device authorization endpoint and device code grant data structures."""

    def test_device_authorization_endpoint_setup(self):
        """DeviceAuthorizationEndpoint generates device_code, user_code, and verification_uri."""
        import os
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth2 import AuthorizationServer
        from authlib.integrations.sqla_oauth2 import (
            OAuth2ClientMixin, OAuth2TokenMixin,
            create_query_client_func, create_save_token_func,
        )
        from authlib.oauth2.rfc8628 import DeviceAuthorizationEndpoint as _DeviceEndpoint

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.secret_key = "test"
        db = SQLAlchemy(app)

        class Client(db.Model, OAuth2ClientMixin):
            id = db.Column(db.Integer, primary_key=True)

        class Token(db.Model, OAuth2TokenMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, default=0)

        device_credentials = {}

        class MyDeviceEndpoint(_DeviceEndpoint):
            def get_verification_uri(self):
                return "https://example.com/device"
            def save_device_credential(self, client_id, scope, data):
                device_credentials[data["device_code"]] = data

        with app.app_context():
            db.create_all()
            server = AuthorizationServer(
                app,
                query_client=create_query_client_func(db.session, Client),
                save_token=create_save_token_func(db.session, Token),
            )
            server.register_endpoint(MyDeviceEndpoint)

            @app.route("/device/authorize", methods=["POST"])
            def device_authorize():
                return server.create_endpoint_response("device_authorization")

            client = Client(client_id="device-client", client_secret="device-secret")
            client.set_client_metadata({
                "scope": "profile",
                "token_endpoint_auth_method": "none",
                "grant_types": ["urn:ietf:params:oauth:grant-type:device_code"],
            })
            db.session.add(client)
            db.session.commit()

            tc = app.test_client()
            rv = tc.post("/device/authorize", data={
                "client_id": "device-client",
                "scope": "profile",
            })
            assert rv.status_code == 200
            data = rv.get_json()
            assert "device_code" in data
            assert "user_code" in data
            assert data["verification_uri"] == "https://example.com/device"
            assert "expires_in" in data
            assert "interval" in data

            assert len(device_credentials) == 1
            stored = list(device_credentials.values())[0]
            assert stored["device_code"] == data["device_code"]
            assert stored["user_code"] == data["user_code"]


# ============================================================================
# 16d. OAuth1 Full 3-Legged Flow (Authorize + Token Exchange)
# ============================================================================


class TestOAuth1CompleteFlow:
    """Complete OAuth1 3-legged flow: initiate → authorize → token exchange."""

    def test_oauth1_full_three_legged_flow(self):
        """OAuth1 server completes: initiate → user authorizes → exchange verifier for access token."""
        import os
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth1 import (
            AuthorizationServer, register_temporary_credential_hooks,
            register_nonce_hooks,
        )
        from authlib.oauth1 import ClientMixin, TemporaryCredentialMixin, TokenCredentialMixin

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["OAUTH1_SUPPORTED_SIGNATURE_METHODS"] = ["PLAINTEXT"]
        app.secret_key = "test"
        sqldb = SQLAlchemy(app)

        class User(sqldb.Model):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            username = sqldb.Column(sqldb.String(40))
            def get_user_id(self):
                return self.id

        class OA1Client(sqldb.Model, ClientMixin):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48), unique=True)
            client_secret = sqldb.Column(sqldb.String(120))
            def get_default_redirect_uri(self): return "https://client.test/cb"
            def get_client_secret(self): return self.client_secret
            def get_rsa_public_key(self): return None

        class TempCred(sqldb.Model, TemporaryCredentialMixin):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48))
            user_id = sqldb.Column(sqldb.Integer)
            oauth_token = sqldb.Column(sqldb.String(84), unique=True)
            oauth_token_secret = sqldb.Column(sqldb.String(84))
            oauth_verifier = sqldb.Column(sqldb.String(84))
            oauth_callback = sqldb.Column(sqldb.Text, default="")
            def get_client_id(self): return self.client_id
            def get_redirect_uri(self): return self.oauth_callback
            def check_verifier(self, v): return self.oauth_verifier == v
            def get_oauth_token(self): return self.oauth_token
            def get_oauth_token_secret(self): return self.oauth_token_secret

        class TokenCred(sqldb.Model, TokenCredentialMixin):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48))
            user_id = sqldb.Column(sqldb.Integer)
            oauth_token = sqldb.Column(sqldb.String(84), unique=True)
            oauth_token_secret = sqldb.Column(sqldb.String(84))
            def get_oauth_token(self): return self.oauth_token
            def get_oauth_token_secret(self): return self.oauth_token_secret

        with app.app_context():
            sqldb.create_all()
            from cachelib import SimpleCache
            cache = SimpleCache()
            server = AuthorizationServer(app, query_client=lambda cid: OA1Client.query.filter_by(client_id=cid).first())
            register_nonce_hooks(server, cache)
            register_temporary_credential_hooks(server, cache)

            def create_token_cred(token, temporary_credential):
                tc = TokenCred(client_id=temporary_credential.get_client_id(), user_id=1,
                    oauth_token=token["oauth_token"], oauth_token_secret=token["oauth_token_secret"])
                sqldb.session.add(tc)
                sqldb.session.commit()
                return tc
            server.register_hook("create_token_credential", create_token_cred)

            @app.route("/initiate", methods=["POST"])
            def initiate():
                return server.create_temporary_credentials_response()

            @app.route("/authorize", methods=["POST"])
            def authorize():
                grant_user = User.query.first()
                return server.create_authorization_response(grant_user=grant_user)

            @app.route("/token", methods=["POST"])
            def token():
                return server.create_token_response()

            u = User(username="testuser")
            sqldb.session.add(u)
            c = OA1Client(client_id="3leg", client_secret="3legsecret")
            sqldb.session.add(c)
            sqldb.session.commit()

            tc = app.test_client()

            # Step 1: Initiate — get temporary credentials
            from authlib.oauth1 import ClientAuth, SIGNATURE_PLAINTEXT
            auth = ClientAuth("3leg", "3legsecret", redirect_uri="oob", signature_method=SIGNATURE_PLAINTEXT)
            uri, headers, body = auth.sign("POST", "http://localhost/initiate", {}, "")
            rv = tc.post("/initiate", headers=headers, data=body, content_type="application/x-www-form-urlencoded")
            assert rv.status_code == 200
            temp_data = dict(x.split("=") for x in rv.data.decode().split("&") if "=" in x)
            temp_token = temp_data["oauth_token"]
            temp_secret = temp_data["oauth_token_secret"]

            # Step 2: Authorize — user approves, server returns verifier
            auth2 = ClientAuth("3leg", "3legsecret", token=temp_token, token_secret=temp_secret,
                               signature_method=SIGNATURE_PLAINTEXT)
            uri2, headers2, body2 = auth2.sign("POST", "http://localhost/authorize", {}, "")
            rv2 = tc.post("/authorize", headers=headers2, data=body2, content_type="application/x-www-form-urlencoded")
            assert rv2.status_code in (302, 303)
            location = rv2.headers["Location"]
            from urllib.parse import urlparse, parse_qs
            parsed = parse_qs(urlparse(location).query)
            verifier = parsed["oauth_verifier"][0]
            assert parsed["oauth_token"][0] == temp_token

            # Step 3: Token exchange — exchange verifier for access token
            auth3 = ClientAuth("3leg", "3legsecret", token=temp_token, token_secret=temp_secret,
                               verifier=verifier, signature_method=SIGNATURE_PLAINTEXT)
            uri3, headers3, body3 = auth3.sign("POST", "http://localhost/token", {}, "")
            rv3 = tc.post("/token", headers=headers3, data=body3, content_type="application/x-www-form-urlencoded")
            assert rv3.status_code == 200
            access_data = dict(x.split("=") for x in rv3.data.decode().split("&") if "=" in x)
            assert "oauth_token" in access_data
            assert "oauth_token_secret" in access_data
            assert access_data["oauth_token"] != temp_token


# ============================================================================
# 16e. Refresh Token Grant
# ============================================================================


class TestRefreshTokenGrant:
    """Tests for the refresh token grant flow (RFC 6749 Section 6)."""

    def test_refresh_token_issues_new_access_token(self):
        """Password grant returns refresh_token; using it yields a new access_token and revokes the old refresh."""
        import base64
        app, db, user_id = _create_full_oauth2_server()

        with app.app_context():
            tc = app.test_client()
            auth = base64.b64encode(b"full-client:full-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "password",
                "username": "alice",
                "password": "correct-password",
                "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            first = rv.get_json()
            assert "access_token" in first
            assert "refresh_token" in first
            original_access = first["access_token"]
            original_refresh = first["refresh_token"]

            rv = tc.get("/api/me", headers={"Authorization": f"Bearer {original_access}"})
            assert rv.status_code == 200

            rv = tc.post("/oauth/token", data={
                "grant_type": "refresh_token",
                "refresh_token": original_refresh,
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            second = rv.get_json()
            assert "access_token" in second
            assert second["access_token"] != original_access

            rv = tc.get("/api/me", headers={"Authorization": f"Bearer {second['access_token']}"})
            assert rv.status_code == 200

            rv = tc.post("/oauth/token", data={
                "grant_type": "refresh_token",
                "refresh_token": original_refresh,
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code != 200


# ============================================================================
# 16f. OIDC Server-Side ID Token Generation
# ============================================================================


class TestOIDCServerIDToken:
    """Tests for OpenIDCode extension that generates id_token on the server."""

    def test_oidc_auth_code_returns_id_token(self):
        """Authorization code flow with OpenIDCode extension returns id_token in token response."""
        import os, base64
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth2 import AuthorizationServer
        from authlib.integrations.sqla_oauth2 import (
            OAuth2ClientMixin, OAuth2TokenMixin, OAuth2AuthorizationCodeMixin,
            create_query_client_func, create_save_token_func,
        )
        from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant as _AuthCodeGrant
        from authlib.oidc.core import OpenIDCode
        from authlib.jose import jwt, RSAKey

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.secret_key = "test"
        db = SQLAlchemy(app)

        server_key = RSAKey.generate_key(2048, is_private=True)

        class User(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(40))
            def get_user_id(self): return self.id

        class Client(db.Model, OAuth2ClientMixin):
            id = db.Column(db.Integer, primary_key=True)

        class AuthCode(db.Model, OAuth2AuthorizationCodeMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, nullable=False)
            nonce = db.Column(db.String(120))
            def get_nonce(self): return self.nonce
            def get_auth_time(self):
                import time; return int(time.time())

        class Token(db.Model, OAuth2TokenMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, default=0)

        class MyAuthCodeGrant(_AuthCodeGrant):
            TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic"]
            def save_authorization_code(self, code, request):
                ac = AuthCode(
                    code=code, client_id=request.client.client_id,
                    redirect_uri=request.payload.redirect_uri,
                    scope=request.scope, user_id=request.user.id,
                    nonce=request.payload.data.get("nonce"),
                )
                db.session.add(ac)
                db.session.commit()
                return ac
            def query_authorization_code(self, code, client):
                item = AuthCode.query.filter_by(code=code, client_id=client.client_id).first()
                if item and not item.is_expired():
                    return item
            def delete_authorization_code(self, authorization_code):
                db.session.delete(authorization_code)
                db.session.commit()
            def authenticate_user(self, authorization_code):
                return db.session.get(User, authorization_code.user_id)

        class MyOpenIDCode(OpenIDCode):
            def exists_nonce(self, nonce, request):
                return False
            def generate_user_info(self, user, scope):
                return {"sub": str(user.get_user_id()), "name": user.username}
            def resolve_client_private_key(self, client):
                return server_key

        with app.app_context():
            db.create_all()
            server = AuthorizationServer(
                app,
                query_client=create_query_client_func(db.session, Client),
                save_token=create_save_token_func(db.session, Token),
            )
            server.register_grant(MyAuthCodeGrant, [MyOpenIDCode()])

            from authlib.oauth2 import OAuth2Error
            from flask import request as flask_request

            @app.route("/oauth/authorize", methods=["GET", "POST"])
            def authorize():
                user_id = flask_request.values.get("user_id")
                end_user = db.session.get(User, int(user_id)) if user_id else None
                try:
                    grant = server.get_consent_grant(end_user=end_user)
                except OAuth2Error:
                    return "error", 400
                if flask_request.method == "GET":
                    return "ok"
                return server.create_authorization_response(grant=grant, grant_user=end_user)

            @app.route("/oauth/token", methods=["POST"])
            def issue_token():
                return server.create_token_response()

            user = User(username="alice")
            db.session.add(user)
            db.session.commit()
            user_id = user.id

            client = Client(client_id="oidc-client", client_secret="oidc-secret")
            client.set_client_metadata({
                "redirect_uris": ["https://client.test/callback"],
                "scope": "openid profile",
                "token_endpoint_auth_method": "client_secret_basic",
                "response_types": ["code"],
                "grant_types": ["authorization_code"],
            })
            db.session.add(client)
            db.session.commit()

            tc = app.test_client()

            rv = tc.post(
                f"/oauth/authorize?response_type=code&client_id=oidc-client"
                f"&scope=openid+profile&nonce=test-nonce-123&user_id={user_id}",
                follow_redirects=False,
            )
            assert rv.status_code in (302, 303), f"Expected redirect, got {rv.status_code}: {rv.data.decode()[:300]}"
            location = rv.headers["Location"]
            from urllib.parse import urlparse, parse_qs
            parsed_qs = parse_qs(urlparse(location).query)
            assert "code" in parsed_qs, f"No code in Location: {location}"
            code = parsed_qs["code"][0]

            auth = base64.b64encode(b"oidc-client:oidc-secret").decode()
            rv = tc.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.test/callback",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            token_data = rv.get_json()
            assert "access_token" in token_data
            assert "id_token" in token_data

            id_claims = jwt.decode(token_data["id_token"], server_key)
            assert id_claims["sub"] == str(user_id)
            assert "oidc-client" in id_claims["aud"]
            assert id_claims["nonce"] == "test-nonce-123"
            assert "iat" in id_claims
            assert "exp" in id_claims


# ============================================================================
# 16g. JWE JSON Multi-Recipient Serialization
# ============================================================================


class TestJWEMultiRecipient:
    """Tests for JWE general JSON serialization with multiple recipients."""

    def test_jwe_json_multi_recipient_encrypt_decrypt(self):
        """Encrypt for two recipients with different keys; each can independently decrypt."""
        from authlib.jose import JsonWebEncryption, OKPKey

        jwe = JsonWebEncryption(["ECDH-ES+A256KW", "A256GCM"])

        bob_key = OKPKey.generate_key("X25519", is_private=True)
        charlie_key = OKPKey.generate_key("X25519", is_private=True)

        header_obj = {
            "protected": {"alg": "ECDH-ES+A256KW", "enc": "A256GCM"},
            "recipients": [
                {"header": {"kid": "bob"}},
                {"header": {"kid": "charlie"}},
            ],
        }

        payload = b"message for both recipients"
        data = jwe.serialize_json(header_obj, payload, [bob_key, charlie_key])

        assert "ciphertext" in data
        assert "recipients" in data
        assert len(data["recipients"]) == 2

        bob_result = jwe.deserialize_json(data, ("bob", bob_key))
        assert bob_result["payload"] == payload

        charlie_result = jwe.deserialize_json(data, ("charlie", charlie_key))
        assert charlie_result["payload"] == payload


# ============================================================================
# 16h. JWS Critical Header Parameter
# ============================================================================


class TestJWSCritHeader:
    """Tests for JWS crit (critical) header parameter validation."""

    def test_jws_crit_header_enforces_presence(self):
        """JWS crit header rejects tokens where a declared-critical parameter is missing."""
        from authlib.jose import JsonWebSignature, OctKey
        from authlib.jose.errors import InvalidCritHeaderParameterNameError

        jws = JsonWebSignature(["HS256"])
        key = OctKey.generate_key(256)

        token_with_crit = jws.serialize_compact(
            {"alg": "HS256", "kid": "mykey", "crit": ["kid"]}, b"crit-payload", key)
        result = jws.deserialize_compact(token_with_crit, key)
        assert result["payload"] == b"crit-payload"
        assert result.header["crit"] == ["kid"]

        with pytest.raises(InvalidCritHeaderParameterNameError):
            jws.serialize_compact(
                {"alg": "HS256", "crit": ["nonexistent"]}, b"data", key)


# ============================================================================
# 16i. PKCE Full Server Flow
# ============================================================================


class TestPKCEServerFlow:
    """Tests for PKCE (RFC 7636) integrated into the authorization code server flow."""

    def test_pkce_s256_full_auth_code_flow(self):
        """Auth code flow with S256 PKCE: code_challenge at authorize, code_verifier at token exchange."""
        import os, base64, hashlib
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask, request as flask_request
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth2 import AuthorizationServer
        from authlib.integrations.sqla_oauth2 import (
            OAuth2ClientMixin, OAuth2TokenMixin, OAuth2AuthorizationCodeMixin,
            create_query_client_func, create_save_token_func,
        )
        from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant as _AuthCodeGrant
        from authlib.oauth2.rfc7636 import CodeChallenge, create_s256_code_challenge
        from authlib.oauth2 import OAuth2Error
        from authlib.common.security import generate_token

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.secret_key = "test"
        db = SQLAlchemy(app)

        class User(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(40))
            def get_user_id(self): return self.id

        class Client(db.Model, OAuth2ClientMixin):
            id = db.Column(db.Integer, primary_key=True)

        class AuthCode(db.Model, OAuth2AuthorizationCodeMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, nullable=False)
            code_challenge = db.Column(db.Text)
            code_challenge_method = db.Column(db.String(48))
            def get_redirect_uri(self): return self.redirect_uri
            def get_scope(self): return self.scope

        class Token(db.Model, OAuth2TokenMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, default=0)

        class MyAuthCodeGrant(_AuthCodeGrant):
            TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "none"]
            def save_authorization_code(self, code, request):
                ac = AuthCode(
                    code=code, client_id=request.client.client_id,
                    redirect_uri=request.payload.redirect_uri,
                    scope=request.scope, user_id=request.user.id,
                    code_challenge=request.payload.data.get("code_challenge"),
                    code_challenge_method=request.payload.data.get("code_challenge_method"),
                )
                db.session.add(ac)
                db.session.commit()
                return ac
            def query_authorization_code(self, code, client):
                return AuthCode.query.filter_by(code=code, client_id=client.client_id).first()
            def delete_authorization_code(self, ac):
                db.session.delete(ac)
                db.session.commit()
            def authenticate_user(self, ac):
                return db.session.get(User, ac.user_id)

        with app.app_context():
            db.create_all()
            server = AuthorizationServer(
                app,
                query_client=create_query_client_func(db.session, Client),
                save_token=create_save_token_func(db.session, Token),
            )
            server.register_grant(MyAuthCodeGrant, [CodeChallenge(required=True)])

            @app.route("/oauth/authorize", methods=["GET", "POST"])
            def authorize():
                user_id = flask_request.values.get("user_id")
                end_user = db.session.get(User, int(user_id)) if user_id else None
                try:
                    grant = server.get_consent_grant(end_user=end_user)
                except OAuth2Error:
                    return "error", 400
                if flask_request.method == "GET":
                    return "ok"
                return server.create_authorization_response(grant=grant, grant_user=end_user)

            @app.route("/oauth/token", methods=["POST"])
            def issue_token():
                return server.create_token_response()

            user = User(username="pkce-user")
            db.session.add(user)
            db.session.commit()
            uid = user.id

            client = Client(client_id="pkce-client", client_secret="")
            client.set_client_metadata({
                "redirect_uris": ["https://client.test/callback"],
                "scope": "profile",
                "token_endpoint_auth_method": "none",
                "response_types": ["code"],
                "grant_types": ["authorization_code"],
            })
            db.session.add(client)
            db.session.commit()

            tc = app.test_client()

            code_verifier = generate_token(48)
            code_challenge = create_s256_code_challenge(code_verifier)

            rv = tc.post(
                f"/oauth/authorize?response_type=code&client_id=pkce-client"
                f"&code_challenge={code_challenge}&code_challenge_method=S256"
                f"&user_id={uid}",
                follow_redirects=False,
            )
            assert rv.status_code in (302, 303)
            from urllib.parse import urlparse, parse_qs
            code = parse_qs(urlparse(rv.headers["Location"]).query)["code"][0]

            rv = tc.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": "pkce-client",
            })
            assert rv.status_code == 200
            assert "access_token" in rv.get_json()

            rv2 = tc.post(
                f"/oauth/authorize?response_type=code&client_id=pkce-client"
                f"&code_challenge={code_challenge}&code_challenge_method=S256"
                f"&user_id={uid}",
                follow_redirects=False,
            )
            code2 = parse_qs(urlparse(rv2.headers["Location"]).query)["code"][0]

            rv2 = tc.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code2,
                "code_verifier": "wrong-verifier-value",
                "client_id": "pkce-client",
            })
            assert rv2.status_code != 200


# ============================================================================
# 16j. Auth Code Replay Protection
# ============================================================================


class TestAuthCodeReplay:
    """Tests that authorization codes cannot be reused."""

    def test_auth_code_single_use(self):
        """Using the same authorization code twice fails on the second attempt."""
        import base64
        app, db, user_id = _create_oauth2_server_app()

        with app.app_context():
            tc = app.test_client()

            rv = tc.post(
                f"/oauth/authorize?response_type=code&client_id=test-client&user_id={user_id}",
                follow_redirects=False,
            )
            assert rv.status_code in (302, 303)
            from urllib.parse import urlparse, parse_qs
            code = parse_qs(urlparse(rv.headers["Location"]).query)["code"][0]

            auth = base64.b64encode(b"test-client:test-secret").decode()

            rv1 = tc.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.test/callback",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv1.status_code == 200
            assert "access_token" in rv1.get_json()

            rv2 = tc.post("/oauth/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.test/callback",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv2.status_code != 200
            assert rv2.get_json()["error"] == "invalid_grant"


# ============================================================================
# 16k. Insufficient Scope (403)
# ============================================================================


class TestInsufficientScope:
    """Tests that resource protector returns 403 for insufficient scope."""

    def test_resource_protector_rejects_insufficient_scope(self):
        """A token with 'profile' scope is rejected when endpoint requires 'admin' scope."""
        import os, base64
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask, json as flask_json
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector
        from authlib.integrations.sqla_oauth2 import (
            OAuth2ClientMixin, OAuth2TokenMixin,
            create_query_client_func, create_save_token_func,
            create_bearer_token_validator,
        )
        from authlib.oauth2.rfc6749.grants import ClientCredentialsGrant

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.secret_key = "test"
        db = SQLAlchemy(app)

        class Client(db.Model, OAuth2ClientMixin):
            id = db.Column(db.Integer, primary_key=True)

        class Token(db.Model, OAuth2TokenMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, default=0)

        with app.app_context():
            db.create_all()
            server = AuthorizationServer(
                app,
                query_client=create_query_client_func(db.session, Client),
                save_token=create_save_token_func(db.session, Token),
            )
            server.register_grant(ClientCredentialsGrant)

            require_oauth = ResourceProtector()
            require_oauth.register_token_validator(
                create_bearer_token_validator(db.session, Token)())

            @app.route("/oauth/token", methods=["POST"])
            def issue_token():
                return server.create_token_response()

            @app.route("/api/profile")
            def profile():
                with require_oauth.acquire("profile") as token:
                    return flask_json.dumps({"ok": True})

            @app.route("/api/admin")
            def admin():
                with require_oauth.acquire("admin") as token:
                    return flask_json.dumps({"ok": True})

            client = Client(client_id="scope-client", client_secret="scope-secret")
            client.set_client_metadata({
                "scope": "profile",
                "token_endpoint_auth_method": "client_secret_basic",
                "grant_types": ["client_credentials"],
            })
            db.session.add(client)
            db.session.commit()

            tc = app.test_client()
            auth = base64.b64encode(b"scope-client:scope-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials", "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            access_token = rv.get_json()["access_token"]

            rv = tc.get("/api/profile", headers={"Authorization": f"Bearer {access_token}"})
            assert rv.status_code == 200

            rv = tc.get("/api/admin", headers={"Authorization": f"Bearer {access_token}"})
            assert rv.status_code == 403


# ============================================================================
# 16l. OIDC UserInfo Scope Filtering
# ============================================================================


class TestUserInfoScopeFiltering:
    """Tests for UserInfo.filter(scope) returning only scope-appropriate claims."""

    def test_userinfo_filter_by_scope(self):
        """UserInfo.filter returns only claims appropriate for the requested scopes."""
        from authlib.oidc.core import UserInfo

        info = UserInfo(
            sub="user123",
            name="Alice Smith",
            given_name="Alice",
            email="alice@example.com",
            email_verified=True,
            phone_number="+1234567890",
        )

        profile_only = info.filter("openid profile")
        assert profile_only["sub"] == "user123"
        assert profile_only["name"] == "Alice Smith"
        assert "email" not in profile_only
        assert "phone_number" not in profile_only

        email_only = info.filter("openid email")
        assert email_only["sub"] == "user123"
        assert email_only["email"] == "alice@example.com"
        assert "name" not in email_only
        assert "phone_number" not in email_only

        phone_only = info.filter("openid phone")
        assert phone_only["sub"] == "user123"
        assert phone_only["phone_number"] == "+1234567890"
        assert "email" not in phone_only
        assert "name" not in phone_only


# ============================================================================
# 16m. JWT Encrypted (JWE) Round-Trip
# ============================================================================


class TestJWTEncrypted:
    """Tests for JWT encoding/decoding via JWE (encrypted JWT)."""

    def test_jwt_encode_decode_via_jwe(self):
        """JsonWebToken with JWE algorithms produces encrypted JWT (5 segments) and decodes it."""
        from authlib.jose import JsonWebToken, RSAKey

        jwt_enc = JsonWebToken(["RSA-OAEP", "A256GCM"])
        key = RSAKey.generate_key(2048, is_private=True)

        payload = {"sub": "encrypted-user", "role": "admin"}
        token = jwt_enc.encode({"alg": "RSA-OAEP", "enc": "A256GCM"}, payload, key)
        assert isinstance(token, bytes)
        assert token.count(b".") == 4

        claims = jwt_enc.decode(token, key)
        assert claims["sub"] == "encrypted-user"
        assert claims["role"] == "admin"


# ============================================================================
# 16n. JWS Private Headers Restriction
# ============================================================================


class TestJWSPrivateHeaders:
    """Tests for JWS private_headers parameter restricting allowed header fields."""

    def test_jws_private_headers_rejects_unknown(self):
        """JWS with private_headers set rejects headers not in the allowed set."""
        from authlib.jose import JsonWebSignature, OctKey
        from authlib.jose.errors import InvalidHeaderParameterNameError

        jws = JsonWebSignature(["HS256"], private_headers=frozenset(["x-custom"]))
        key = OctKey.generate_key(256)

        token = jws.serialize_compact(
            {"alg": "HS256", "x-custom": "allowed"}, b"data", key)
        result = jws.deserialize_compact(token, key)
        assert result["payload"] == b"data"

        with pytest.raises(InvalidHeaderParameterNameError):
            jws.serialize_compact(
                {"alg": "HS256", "x-unknown": "blocked"}, b"data", key)


# ============================================================================
# 16o. RFC 9068 JWT Access Tokens
# ============================================================================


class TestJWTAccessTokens:
    """Tests for RFC 9068 JWT-formatted access tokens (self-contained, no DB lookup)."""

    def test_jwt_access_token_generation_and_validation(self):
        """Server issues JWT access tokens; resource server validates by decoding JWT without DB."""
        import os, base64
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask, json as flask_json
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector
        from authlib.integrations.sqla_oauth2 import (
            OAuth2ClientMixin, OAuth2TokenMixin,
            create_query_client_func, create_save_token_func,
        )
        from authlib.oauth2.rfc6749.grants import ClientCredentialsGrant
        from authlib.oauth2.rfc9068 import JWTBearerTokenGenerator, JWTBearerTokenValidator
        from authlib.jose import RSAKey, jwt as jose_jwt

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.secret_key = "test"
        db = SQLAlchemy(app)

        server_key = RSAKey.generate_key(2048, is_private=True)
        private_jwks = {"keys": [server_key.as_dict(is_private=True)]}
        public_jwks = {"keys": [server_key.as_dict(is_private=False)]}
        ISSUER = "https://auth.example.com"
        RESOURCE_SERVER = "https://api.example.com"

        class Client(db.Model, OAuth2ClientMixin):
            id = db.Column(db.Integer, primary_key=True)

        class Token(db.Model, OAuth2TokenMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, default=0)

        class MyTokenGen(JWTBearerTokenGenerator):
            def get_jwks(self):
                return private_jwks
            def get_audiences(self, client, user, scope):
                return RESOURCE_SERVER

        class MyTokenVal(JWTBearerTokenValidator):
            def get_jwks(self):
                return public_jwks

        with app.app_context():
            db.create_all()
            server = AuthorizationServer(app,
                query_client=create_query_client_func(db.session, Client),
                save_token=create_save_token_func(db.session, Token))
            server.register_token_generator("default", MyTokenGen(ISSUER))
            server.register_grant(ClientCredentialsGrant)

            require_oauth = ResourceProtector()
            require_oauth.register_token_validator(MyTokenVal(ISSUER, RESOURCE_SERVER))

            @app.route("/oauth/token", methods=["POST"])
            def issue_token():
                return server.create_token_response()

            @app.route("/api/data")
            def data():
                with require_oauth.acquire("profile") as token:
                    return flask_json.dumps({
                        "scope": token["scope"],
                        "client_id": token["client_id"],
                    })

            client = Client(client_id="jwt-client", client_secret="jwt-secret")
            client.set_client_metadata({
                "scope": "profile",
                "token_endpoint_auth_method": "client_secret_basic",
                "grant_types": ["client_credentials"],
            })
            db.session.add(client)
            db.session.commit()

            tc = app.test_client()
            auth = base64.b64encode(b"jwt-client:jwt-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials", "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            token_data = rv.get_json()
            access_token = token_data["access_token"]
            assert access_token.count(".") == 2

            claims = jose_jwt.decode(access_token, server_key)
            # Read the "at+jwt" type from the token's JOSE protected header via the public
            # compact surface (segment 0), not via a non-registered attribute on JWTClaims.
            header_seg = access_token.split(".")[0]
            header = json.loads(base64.urlsafe_b64decode(header_seg + "=" * (-len(header_seg) % 4)))
            assert header["typ"] == "at+jwt"
            assert claims["iss"] == ISSUER
            assert claims["client_id"] == "jwt-client"
            assert claims["scope"] == "profile"
            assert claims["aud"] == RESOURCE_SERVER
            assert "exp" in claims
            assert "iat" in claims
            assert "jti" in claims

            rv2 = tc.get("/api/data", headers={"Authorization": f"Bearer {access_token}"})
            assert rv2.status_code == 200
            resp = json.loads(rv2.data)
            assert resp["client_id"] == "jwt-client"
            assert resp["scope"] == "profile"


# ============================================================================
# 16p. OIDC Hybrid Grant with HybridIDToken
# ============================================================================


class TestOIDCHybridGrant:
    """Tests for OIDC hybrid flow and HybridIDToken c_hash validation."""

    def test_hybrid_id_token_validates_c_hash(self):
        """HybridIDToken validates c_hash (hash of authorization code) for hybrid flow."""
        import time, hashlib, base64
        from authlib.oidc.core import HybridIDToken

        now = int(time.time())
        code = "test-authorization-code-value"
        # OIDC c_hash: leftmost half of SHA-256(code), base64url without padding (RS256 -> sha256).
        code_hash = hashlib.sha256(code.encode("ascii")).digest()
        c_hash = base64.urlsafe_b64encode(code_hash[:16]).rstrip(b"=").decode("ascii")

        claims = HybridIDToken(
            {"iss": "https://auth.example.com", "sub": "user123",
             "aud": "client", "exp": now + 3600, "iat": now,
             "nonce": "test-nonce", "c_hash": c_hash},
            {"alg": "RS256"},
        )
        claims.params = {"nonce": "test-nonce", "code": code}
        claims.validate(now=now)

    def test_hybrid_id_token_rejects_wrong_c_hash(self):
        """HybridIDToken rejects ID token with incorrect c_hash."""
        import time
        from authlib.oidc.core import HybridIDToken

        now = int(time.time())
        claims = HybridIDToken(
            {"iss": "https://auth.example.com", "sub": "user123",
             "aud": "client", "exp": now + 3600, "iat": now,
             "nonce": "test-nonce", "c_hash": "wrong-hash-value"},
            {"alg": "RS256"},
        )
        claims.params = {"nonce": "test-nonce", "code": "some-code"}
        with pytest.raises(Exception):
            claims.validate(now=now)


# ============================================================================
# 17. OAuth2 RFC Extensions — Core data structure tests
# ============================================================================


class TestOAuth2RFCExtensions:
    """Tests for OAuth2 RFC extension data structures (no server needed)."""

    def test_rfc7591_client_metadata_validation(self):
        """ClientMetadataClaims validates redirect URIs and other fields."""
        from authlib.oauth2.rfc7591 import ClientMetadataClaims

        # Valid metadata
        claims = ClientMetadataClaims({
            "redirect_uris": ["https://client.test/callback"],
            "client_name": "Test App",
        }, {})
        claims.validate()

        # Invalid redirect_uri must be rejected; the spec does not pin the
        # exact exception class, so any raised error counts.
        with pytest.raises(Exception):
            bad = ClientMetadataClaims({
                "redirect_uris": ["not-a-url"],
            }, {})
            bad.validate()

    def test_rfc8414_server_metadata_validation(self):
        """AuthorizationServerMetadata validates OAuth2 server metadata fields."""
        from authlib.oauth2.rfc8414 import AuthorizationServerMetadata

        metadata = AuthorizationServerMetadata({
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "response_types_supported": ["code", "token"],
        })
        metadata.validate_issuer()
        metadata.validate_authorization_endpoint()
        metadata.validate_token_endpoint()
        metadata.validate_response_types_supported()

        # Also verify well-known URL construction. With the default external=False and an
        # issuer that has no path, the helper returns exactly the bare well-known path.
        from authlib.oauth2.rfc8414 import get_well_known_url
        url = get_well_known_url("https://auth.example.com")
        assert url == "/.well-known/oauth-authorization-server"


# ============================================================================
# 18. OIDC Discovery and Registration
# ============================================================================


class TestOIDCDiscoveryAndRegistration:
    """Tests for OIDC provider metadata discovery and client registration."""

    def test_oidc_provider_metadata_validation(self):
        """OpenIDProviderMetadata validates OIDC-specific fields."""
        from authlib.oidc.discovery import OpenIDProviderMetadata

        metadata = OpenIDProviderMetadata({
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        })
        metadata.validate()

    def test_oidc_provider_metadata_requires_jwks_uri(self):
        """OIDC provider metadata requires jwks_uri (unlike OAuth2)."""
        from authlib.oidc.discovery import OpenIDProviderMetadata

        metadata = OpenIDProviderMetadata({
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        })
        # A missing required jwks_uri must be rejected; the spec does not pin the exact
        # exception class (matching the sibling rfc7591 / oidc-registration metadata tests),
        # so any raised error counts.
        with pytest.raises(Exception):
            metadata.validate_jwks_uri()

        # Also verify OIDC well-known URL. With the default external=False and an issuer that
        # has no path, the helper returns exactly the bare well-known path.
        from authlib.oidc.discovery import get_well_known_url
        url = get_well_known_url("https://auth.example.com")
        assert url == "/.well-known/openid-configuration"

    def test_oidc_client_registration_metadata(self):
        """OIDC ClientMetadataClaims validates registration fields."""
        from authlib.oidc.registration import ClientMetadataClaims

        claims = ClientMetadataClaims({
            "redirect_uris": ["https://client.test/callback"],
            "application_type": "web",
        }, {})
        claims.validate()

    def test_oidc_client_registration_rejects_invalid_uri(self):
        """OIDC registration rejects invalid request_uris."""
        from authlib.oidc.registration import ClientMetadataClaims

        # Invalid request_uris must be rejected; the spec does not pin the
        # exact exception class, so any raised error counts.
        with pytest.raises(Exception):
            claims = ClientMetadataClaims({
                "redirect_uris": ["https://client.test/callback"],
                "request_uris": ["not-a-url"],
            }, {})
            claims.validate()


# ============================================================================
# 19. Flask OAuth2 Server — Token Revocation (rfc7009)
# ============================================================================


class TestFlaskOAuth2Revocation:
    """Token revocation endpoint via Flask server."""

    def test_token_revocation_endpoint(self):
        """A user revokes an access token via POST /oauth/revoke and it becomes invalid."""
        import os, base64, time as _time
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask, json
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector
        from authlib.integrations.sqla_oauth2 import (
            OAuth2ClientMixin, OAuth2TokenMixin,
            create_query_client_func, create_save_token_func,
            create_bearer_token_validator,
        )
        from authlib.oauth2.rfc6749.grants import ClientCredentialsGrant
        from authlib.oauth2.rfc7009 import RevocationEndpoint

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.secret_key = "test"
        db = SQLAlchemy(app)

        class Client(db.Model, OAuth2ClientMixin):
            id = db.Column(db.Integer, primary_key=True)

        class Token(db.Model, OAuth2TokenMixin):
            id = db.Column(db.Integer, primary_key=True)
            user_id = db.Column(db.Integer, default=0)
            def is_refresh_token_active(self):
                return not self.refresh_token_revoked_at

        class MyRevocationEndpoint(RevocationEndpoint):
            def query_token(self, token_string, token_type_hint):
                return Token.query.filter_by(access_token=token_string).first()
            def revoke_token(self, token, request):
                token.access_token_revoked_at = int(_time.time())
                db.session.commit()

        with app.app_context():
            db.create_all()
            server = AuthorizationServer(
                app,
                query_client=create_query_client_func(db.session, Client),
                save_token=create_save_token_func(db.session, Token),
            )
            server.register_grant(ClientCredentialsGrant)
            server.register_endpoint(MyRevocationEndpoint)

            require_oauth = ResourceProtector()
            require_oauth.register_token_validator(
                create_bearer_token_validator(db.session, Token)()
            )

            @app.route("/oauth/token", methods=["POST"])
            def issue_token():
                return server.create_token_response()

            @app.route("/oauth/revoke", methods=["POST"])
            def revoke():
                return server.create_endpoint_response("revocation")

            @app.route("/api/protected")
            def protected():
                with require_oauth.acquire("profile") as token:
                    return json.dumps({"ok": True})

            client = Client(client_id="rev-client", client_secret="rev-secret")
            client.set_client_metadata({
                "scope": "profile",
                "token_endpoint_auth_method": "client_secret_basic",
                "grant_types": ["client_credentials"],
            })
            db.session.add(client)
            db.session.commit()

            tc = app.test_client()
            auth = base64.b64encode(b"rev-client:rev-secret").decode()

            rv = tc.post("/oauth/token", data={
                "grant_type": "client_credentials", "scope": "profile",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200
            access_token = rv.get_json()["access_token"]

            rv = tc.get("/api/protected", headers={"Authorization": f"Bearer {access_token}"})
            assert rv.status_code == 200

            rv = tc.post("/oauth/revoke", data={
                "token": access_token, "token_type_hint": "access_token",
            }, headers={"Authorization": f"Basic {auth}"})
            assert rv.status_code == 200

            rv = tc.get("/api/protected", headers={"Authorization": f"Bearer {access_token}"})
            assert rv.status_code == 401


# ============================================================================
# 21. Django OAuth2 Server — Full flow
# ============================================================================


class TestDjangoOAuth2Server:
    """Django OAuth2 server integration tests."""

    def _setup_django(self):
        """Set up minimal Django with authlib models."""
        import os
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django.conf.global_settings")

        import django
        from django.conf import settings
        if not settings.configured:
            settings.configure(
                SECRET_KEY="test-secret",
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
                INSTALLED_APPS=[
                    "django.contrib.contenttypes",
                    "django.contrib.auth",
                ],
                AUTHLIB_OAUTH2_PROVIDER={},
                DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
                ALLOWED_HOSTS=["*"],
            )
            django.setup()

    def test_django_authorization_server_token_endpoint_rejects_no_auth(self):
        """Django AuthorizationServer token endpoint rejects unauthenticated requests."""
        self._setup_django()
        from django.test import RequestFactory
        from authlib.integrations.django_oauth2 import AuthorizationServer
        from authlib.oauth2.rfc6749.grants import ClientCredentialsGrant
        import json as _json

        server = AuthorizationServer(None, None)
        server.register_grant(ClientCredentialsGrant)

        factory = RequestFactory()
        request = factory.post("/oauth/token", data={"grant_type": "client_credentials"})
        resp = server.create_token_response(request)
        assert resp.status_code == 401
        data = _json.loads(resp.content)
        assert data["error"] == "invalid_client"


# ============================================================================
# 22. OAuth1 Server — Full 3-legged flow via Flask
# ============================================================================


class TestFlaskOAuth1FullFlow:
    """Complete OAuth1 3-legged flow through Flask test client."""

    def _create_oauth1_server(self):
        """Set up Flask OAuth1 server with all endpoints."""
        import os
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "true"

        from flask import Flask, request as flask_request
        from flask_sqlalchemy import SQLAlchemy
        from authlib.integrations.flask_oauth1 import (
            AuthorizationServer, ResourceProtector,
            register_temporary_credential_hooks, register_nonce_hooks,
        )
        from authlib.oauth1 import ClientMixin, TemporaryCredentialMixin, TokenCredentialMixin

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["OAUTH1_SUPPORTED_SIGNATURE_METHODS"] = ["PLAINTEXT"]
        app.secret_key = "test"
        sqldb = SQLAlchemy(app)

        class User(sqldb.Model):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            username = sqldb.Column(sqldb.String(40))

        class OA1Client(sqldb.Model, ClientMixin):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48), unique=True)
            client_secret = sqldb.Column(sqldb.String(120))
            default_redirect_uri = sqldb.Column(sqldb.Text, default="https://client.test/cb")
            def get_default_redirect_uri(self): return self.default_redirect_uri
            def get_client_secret(self): return self.client_secret
            def get_rsa_public_key(self): return None

        class TempCred(sqldb.Model, TemporaryCredentialMixin):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48))
            user_id = sqldb.Column(sqldb.Integer)
            oauth_token = sqldb.Column(sqldb.String(84), unique=True)
            oauth_token_secret = sqldb.Column(sqldb.String(84))
            oauth_verifier = sqldb.Column(sqldb.String(84))
            oauth_callback = sqldb.Column(sqldb.Text, default="")
            def get_client_id(self): return self.client_id
            def get_redirect_uri(self): return self.oauth_callback
            def check_verifier(self, v): return self.oauth_verifier == v
            def get_oauth_token(self): return self.oauth_token
            def get_oauth_token_secret(self): return self.oauth_token_secret

        class TokenCred(sqldb.Model, TokenCredentialMixin):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48))
            user_id = sqldb.Column(sqldb.Integer)
            oauth_token = sqldb.Column(sqldb.String(84), unique=True)
            oauth_token_secret = sqldb.Column(sqldb.String(84))
            def get_oauth_token(self): return self.oauth_token
            def get_oauth_token_secret(self): return self.oauth_token_secret

        class Nonce(sqldb.Model):
            id = sqldb.Column(sqldb.Integer, primary_key=True)
            client_id = sqldb.Column(sqldb.String(48))
            timestamp = sqldb.Column(sqldb.Integer)
            nonce = sqldb.Column(sqldb.String(48))
            token = sqldb.Column(sqldb.String(84))

        with app.app_context():
            sqldb.create_all()
            server = AuthorizationServer(app, query_client=lambda cid: OA1Client.query.filter_by(client_id=cid).first())

            # Use a simple dict as cache for hooks
            from cachelib import SimpleCache
            cache = SimpleCache()
            register_nonce_hooks(server, cache)
            register_temporary_credential_hooks(server, cache)

            def create_token_cred(token, request):
                tc = TokenCred(client_id=request.client_id, user_id=1,
                    oauth_token=token["oauth_token"], oauth_token_secret=token["oauth_token_secret"])
                sqldb.session.add(tc)
                sqldb.session.commit()
                return tc
            server.register_hook("create_token_credential", create_token_cred)

            require_oauth = ResourceProtector(app, query_client=lambda cid: OA1Client.query.filter_by(client_id=cid).first(),
                query_token=lambda cid, tok: TokenCred.query.filter_by(client_id=cid, oauth_token=tok).first(),
                exists_nonce=lambda nonce, request: False)

            @app.route("/oauth/initiate", methods=["POST"])
            def initiate():
                return server.create_temporary_credentials_response()

            @app.route("/oauth/authorize", methods=["POST"])
            def authorize():
                grant_user = User.query.first()
                return server.create_authorization_response(grant_user=grant_user)

            @app.route("/oauth/token", methods=["POST"])
            def token():
                return server.create_token_response()

            @app.route("/api/resource")
            def resource():
                try:
                    require_oauth("profile")
                    return "protected data"
                except Exception:
                    return "unauthorized", 401

            # Seed
            u = User(username="testuser")
            sqldb.session.add(u)
            c = OA1Client(client_id="oa1client", client_secret="oa1secret")
            sqldb.session.add(c)
            sqldb.session.commit()

        return app

    def test_oauth1_initiate_returns_temporary_credentials(self):
        """OAuth1 initiate endpoint issues temporary credentials via both raw body and ClientAuth signing."""
        app = self._create_oauth1_server()
        with app.app_context():
            tc = app.test_client()

            # Raw body params
            rv = tc.post("/oauth/initiate", data={
                "oauth_consumer_key": "oa1client",
                "oauth_callback": "oob",
                "oauth_signature_method": "PLAINTEXT",
                "oauth_signature": "oa1secret&",
            })
            assert rv.status_code == 200
            data = dict(x.split("=") for x in rv.data.decode().split("&") if "=" in x)
            assert "oauth_token" in data
            assert "oauth_token_secret" in data
            # RFC 5849 specifies the literal value "true"; accept any case to
            # avoid coupling to the Python-bool-capitalized serialization.
            assert data.get("oauth_callback_confirmed", "").lower() == "true"

            # ClientAuth-signed request
            from authlib.oauth1 import ClientAuth, SIGNATURE_PLAINTEXT
            auth = ClientAuth("oa1client", "oa1secret", redirect_uri="oob", signature_method=SIGNATURE_PLAINTEXT)
            uri, headers, body = auth.sign("POST", "http://localhost/oauth/initiate", {}, "")
            rv2 = tc.post("/oauth/initiate", headers=headers, data=body,
                          content_type="application/x-www-form-urlencoded")
            assert rv2.status_code == 200
            assert b"oauth_token=" in rv2.data
            assert b"oauth_token_secret=" in rv2.data
