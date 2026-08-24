# Copyright 2026 "Google LLC"
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Token signature verification.

The regression these guard against reached a live cluster: IAP publishes its
signing keys as a JWK Set, google.auth.jwt.decode wants a mapping of key id to
key, and handing the former to the latter fails every lookup with
"Certificate for key id ... not found" no matter how valid the assertion is.
Only an end-to-end sign-in showed it, because the audience, issuer and
signature were all correct - the key was simply never found.
"""

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from google.auth import jwt as google_jwt
from google.auth.crypt import es256

from desktop_broker.errors import BrokerError
from desktop_broker.identity import jwt

AUDIENCE = "/projects/123/global/backendServices/456"
ISSUER = "https://cloud.google.com/iap"


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@pytest.fixture
def signing_key():
    """An ES256 key pair plus the JWK a server would publish for it."""
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    size = 32  # P-256 coordinates are always 32 bytes.
    jwk = {
        "kid": "testkid",
        "alg": "ES256",
        "kty": "EC",
        "crv": "P-256",
        "use": "sig",
        "x": b64(numbers.x.to_bytes(size, "big")),
        "y": b64(numbers.y.to_bytes(size, "big")),
    }
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return {"jwk": jwk, "signer": es256.ES256Signer.from_string(pem, key_id="testkid")}


def make_token(signing_key, **claims):
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "email": "someone@example.com",
        "sub": "accounts.google.com:123456789",
        "iat": now,
        "exp": now + 600,
    }
    payload.update(claims)
    return google_jwt.encode(signing_key["signer"], payload)


class FakeResponse:
    def __init__(self, body, cache_control=None):
        self._body = body
        self.headers = {"Cache-Control": cache_control} if cache_control else {}

    def read(self):
        return json.dumps(self._body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# --------------------------------------------------------------------------
# Key normalisation
# --------------------------------------------------------------------------


def test_jwk_set_is_converted_to_a_key_id_mapping(signing_key):
    certs = jwt.certs_by_key_id({"keys": [signing_key["jwk"]]})
    assert list(certs) == ["testkid"]
    assert certs["testkid"].startswith(b"-----BEGIN PUBLIC KEY-----")


def test_x509_mapping_is_passed_through_unchanged():
    """Google's OIDC certs are already the shape decode() wants."""
    payload = {"somekid": "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----"}
    assert jwt.certs_by_key_id(payload) == payload


def test_unsupported_curve_is_rejected(signing_key):
    jwk = dict(signing_key["jwk"], crv="P-192")
    with pytest.raises(BrokerError, match="Unsupported signing key curve"):
        jwt.certs_by_key_id({"keys": [jwk]})


def test_malformed_jwk_set_is_rejected():
    with pytest.raises(BrokerError, match="Could not read signing keys"):
        jwt.certs_by_key_id({"keys": [{"kid": "k"}]})


# --------------------------------------------------------------------------
# Verification, end to end through the KeyStore
# --------------------------------------------------------------------------


def test_valid_token_verifies_against_a_jwk_set(signing_key, monkeypatch):
    store = jwt.KeyStore()
    monkeypatch.setattr(
        jwt.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse({"keys": [signing_key["jwk"]]}))
    claims = jwt.verify(store, make_token(signing_key), "https://certs", AUDIENCE)
    assert claims["email"] == "someone@example.com"


def test_raw_jwk_set_would_fail_every_lookup(signing_key, monkeypatch):
    """Pins the bug itself: without normalisation the key is never found."""
    with pytest.raises(ValueError, match="not found"):
        google_jwt.decode(
            make_token(signing_key),
            certs={"keys": [signing_key["jwk"]]},
            audience=AUDIENCE,
        )


def test_wrong_audience_is_rejected(signing_key, monkeypatch):
    store = jwt.KeyStore()
    monkeypatch.setattr(
        jwt.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse({"keys": [signing_key["jwk"]]}))
    with pytest.raises(BrokerError, match="could not be verified"):
        jwt.verify(store, make_token(signing_key), "https://certs",
                   "/projects/999/global/backendServices/999")


def test_expired_token_is_rejected(signing_key, monkeypatch):
    store = jwt.KeyStore()
    monkeypatch.setattr(
        jwt.urllib.request, "urlopen",
        lambda request, timeout=None: FakeResponse({"keys": [signing_key["jwk"]]}))
    stale = make_token(signing_key, iat=int(time.time()) - 7200,
                       exp=int(time.time()) - 3600)
    with pytest.raises(BrokerError, match="could not be verified"):
        jwt.verify(store, stale, "https://certs", AUDIENCE)


def test_unknown_key_id_triggers_one_refresh(signing_key, monkeypatch):
    """Signing keys rotate, so a miss should refetch once before giving up."""
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(1)
        # Empty first, correct on refresh.
        if len(calls) == 1:
            return FakeResponse({"keys": []})
        return FakeResponse({"keys": [signing_key["jwk"]]})

    monkeypatch.setattr(jwt.urllib.request, "urlopen", fake_urlopen)
    claims = jwt.verify(jwt.KeyStore(), make_token(signing_key), "https://certs",
                        AUDIENCE)
    assert claims["email"] == "someone@example.com"
    assert len(calls) == 2


def test_malformed_token_is_rejected():
    with pytest.raises(BrokerError, match="Invalid desktop identity token"):
        jwt.verify(jwt.KeyStore(), "not-a-jwt", "https://certs", AUDIENCE)


def test_bearer_prefix_is_stripped():
    assert jwt.strip_bearer("Bearer abc.def") == "abc.def"
    assert jwt.strip_bearer("bearer abc.def") == "abc.def"
    assert jwt.strip_bearer("abc.def") == "abc.def"


def test_cache_control_max_age_is_read():
    assert jwt.cache_control_max_age("public, max-age=3600") == 3600
    assert jwt.cache_control_max_age("no-cache") is None
    assert jwt.cache_control_max_age(None) is None
