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

"""IAP identity mode.

The assertion is the only thing standing between a request and someone else's
desktop, so these tests are mostly about what must be *rejected*: a valid
signature is not enough if the audience, issuer or subject are wrong.
"""

import pytest

from conftest import base_config
from desktop_broker.config import Config, ConfigError
from desktop_broker.errors import BrokerError
from desktop_broker.identity import iap, resolver


AUDIENCE = "/projects/123/global/backendServices/456"


def iap_raw(tmp_path, **overrides):
    raw = base_config(tmp_path, identity_mode="iap", identity_audience=AUDIENCE)
    raw.update(overrides)
    return raw


class FakeJWT:
    """Stands in for the signature check, which google-auth owns."""

    def __init__(self, claims=None, error=None):
        self.claims = claims or {}
        self.error = error
        self.seen_audience = None
        self.seen_token = None

    def verify(self, key_store, raw_token, certs_url, audience):
        self.seen_audience = audience
        self.seen_token = raw_token
        if self.error:
            raise self.error
        return self.claims


def install(monkeypatch, fake):
    monkeypatch.setattr(iap.jwt, "verify", fake.verify)


def presented(**overrides):
    values = {
        "secret": "",
        "email": "",
        "login_uid": "",
        "username": "",
        "iap_assertion": "header.payload.signature",
    }
    values.update(overrides)
    return values


class StaticAudience:
    def __init__(self, value=AUDIENCE):
        self.value = value

    def get(self):
        return self.value


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_iap_mode_is_accepted(tmp_path):
    config = Config(iap_raw(tmp_path))
    assert config.identity_mode == "iap"
    assert config.identity_audience == AUDIENCE


def test_iap_without_audience_or_backend_service_is_rejected(tmp_path):
    raw = base_config(tmp_path, identity_mode="iap")
    with pytest.raises(ConfigError, match="identity_audience or"):
        Config(raw)


def test_backend_service_alone_is_enough(tmp_path):
    raw = base_config(tmp_path, identity_mode="iap", iap_backend_service="be")
    assert Config(raw).iap_backend_service == "be"


def test_secret_is_optional_under_iap(tmp_path):
    raw = iap_raw(tmp_path)
    raw.pop("proxy_secret")
    assert Config(raw).proxy_secret == ""


def test_secret_is_still_required_for_trusted_proxy(tmp_path):
    raw = base_config(tmp_path)
    raw.pop("proxy_secret")
    with pytest.raises(ConfigError, match="proxy_secret is required"):
        Config(raw)


# --------------------------------------------------------------------------
# Assertion verification
# --------------------------------------------------------------------------


def test_valid_assertion_yields_identity(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))
    install(monkeypatch, FakeJWT({
        "iss": iap.ISSUER,
        "email": "Someone@Example.com",
        "sub": "accounts.google.com:123456789",
    }))
    result = iap.resolve(presented(), config, None, StaticAudience())
    assert result["email"] == "someone@example.com"
    assert result["login_uid"] == "123456789"


def test_missing_assertion_is_rejected(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))
    install(monkeypatch, FakeJWT({"iss": iap.ISSUER, "email": "a@b.c"}))
    with pytest.raises(BrokerError) as err:
        iap.resolve(presented(iap_assertion=""), config, None, StaticAudience())
    assert err.value.status == 403


def test_wrong_issuer_is_rejected(tmp_path, monkeypatch):
    """A correctly signed token from elsewhere must not be accepted.

    google-auth checks aud and exp but never iss, so this check exists only in
    our code - and would fail open if it were dropped.
    """
    config = Config(iap_raw(tmp_path))
    install(monkeypatch, FakeJWT({
        "iss": "https://accounts.google.com",
        "email": "someone@example.com",
        "sub": "accounts.google.com:1",
    }))
    with pytest.raises(BrokerError, match="unexpected issuer"):
        iap.resolve(presented(), config, None, StaticAudience())


def test_audience_is_passed_to_verification(tmp_path, monkeypatch):
    """The audience must reach the verifier, not merely be configured."""
    config = Config(iap_raw(tmp_path))
    fake = FakeJWT({
        "iss": iap.ISSUER, "email": "a@b.c", "sub": "accounts.google.com:1",
    })
    install(monkeypatch, fake)
    iap.resolve(presented(), config, None, StaticAudience())
    assert fake.seen_audience == AUDIENCE


def test_verification_failure_propagates(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))
    install(monkeypatch, FakeJWT(error=BrokerError(403, "bad signature")))
    with pytest.raises(BrokerError) as err:
        iap.resolve(presented(), config, None, StaticAudience())
    assert err.value.status == 403


def test_assertion_without_email_or_subject_is_rejected(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))
    install(monkeypatch, FakeJWT({"iss": iap.ISSUER}))
    with pytest.raises(BrokerError, match="neither an email nor a subject"):
        iap.resolve(presented(), config, None, StaticAudience())


def test_bearer_prefix_is_stripped(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))
    fake = FakeJWT({
        "iss": iap.ISSUER, "email": "a@b.c", "sub": "accounts.google.com:1",
    })
    install(monkeypatch, fake)
    iap.resolve(presented(iap_assertion="Bearer abc.def.ghi"), config, None,
                StaticAudience())
    assert fake.seen_token == "abc.def.ghi"


def test_subject_without_provider_prefix_is_kept_whole(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))
    install(monkeypatch, FakeJWT({
        "iss": iap.ISSUER, "email": "a@b.c", "sub": "987654321",
    }))
    assert iap.resolve(presented(), config, None,
                       StaticAudience())["login_uid"] == "987654321"


# --------------------------------------------------------------------------
# Audience resolution
# --------------------------------------------------------------------------


def test_explicit_audience_needs_no_lookup(tmp_path, monkeypatch):
    config = Config(iap_raw(tmp_path))

    def explode(path):
        raise AssertionError("metadata must not be consulted")

    monkeypatch.setattr(iap, "_metadata", explode)
    assert iap.AudienceResolver(config).get() == AUDIENCE


def test_backend_service_is_resolved_and_cached(tmp_path, monkeypatch):
    config = Config(base_config(
        tmp_path, identity_mode="iap", iap_backend_service="desk-backend"))

    calls = []
    monkeypatch.setattr(iap, "_metadata", lambda path: {
        "project/numeric-project-id": "881313903456",
        "project/project-id": "sgordon-project",
        "instance/service-accounts/default/token": '{"access_token": "tok"}',
    }[path])

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)

        class Response:
            def read(self):
                return b'{"id": "7788"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Response()

    monkeypatch.setattr(iap.urllib.request, "urlopen", fake_urlopen)

    audience = iap.AudienceResolver(config)
    first = audience.get()
    second = audience.get()

    assert first == "/projects/881313903456/global/backendServices/7788"
    assert second == first
    # A backend service ID is stable; re-resolving would add an API call to
    # every desktop hand-off.
    assert len(calls) == 1
    assert "desk-backend" in calls[0]


# --------------------------------------------------------------------------
# Resolver wiring
# --------------------------------------------------------------------------


def test_resolver_registers_iap_mode(tmp_path):
    assert resolver.Resolver(Config(iap_raw(tmp_path)))._resolve is iap.resolve


def test_iap_assertion_header_is_read(tmp_path):
    assert resolver.HEADERS["iap_assertion"] == "x-goog-iap-jwt-assertion"
    values = resolver.presented_from_headers(
        {"x-goog-iap-jwt-assertion": " abc "})
    assert values["iap_assertion"] == "abc"


def test_resolver_skips_secret_check_when_none_configured(tmp_path, monkeypatch):
    raw = iap_raw(tmp_path)
    raw.pop("proxy_secret")
    config = Config(raw)
    install(monkeypatch, FakeJWT({
        "iss": iap.ISSUER, "email": "a@b.c", "sub": "accounts.google.com:5",
    }))
    monkeypatch.setattr(
        iap, "AudienceResolver", lambda cfg: StaticAudience())
    assert resolver.Resolver(config).resolve(
        presented())["login_uid"] == "5"


def test_resolver_still_enforces_secret_when_one_is_set(tmp_path, monkeypatch):
    """Setting a secret under iap must not become decorative."""
    config = Config(iap_raw(tmp_path, proxy_secret="s3cret"))
    install(monkeypatch, FakeJWT({
        "iss": iap.ISSUER, "email": "a@b.c", "sub": "accounts.google.com:5",
    }))
    monkeypatch.setattr(
        iap, "AudienceResolver", lambda cfg: StaticAudience())
    with pytest.raises(BrokerError, match="desktop proxy secret"):
        resolver.Resolver(config).resolve(presented(secret="wrong"))
