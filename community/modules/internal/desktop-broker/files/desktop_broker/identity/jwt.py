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

"""JWT signature, audience and expiry verification with a certificate cache.

Split out so that each identity mode says only which keys to trust and which
claims to require, and no mode reimplements verification.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from google.auth import jwt as google_jwt

from ..errors import BrokerError

LOG = logging.getLogger("ghpc-desktop-broker")


def cache_control_max_age(header_value):
    for directive in str(header_value or "").split(","):
        name, _, value = directive.strip().partition("=")
        if name.lower() == "max-age":
            try:
                return max(int(value), 0)
            except ValueError:
                return None
    return None


class KeyStore:
    """Signing certificates, keyed by the endpoint they came from.

    Different modes trust different issuers - Google's OIDC certs, a service
    account's x509 certs, IAP's JWK set - so the cache is per URL rather than
    global.
    """

    def __init__(self):
        self._caches = {}

    def get(self, certs_url, refresh=False):
        now = time.time()
        cached = self._caches.get(certs_url)
        if not refresh and cached and cached["certs"] and now < cached["expires_at"]:
            return cached["certs"]

        request = urllib.request.Request(certs_url)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                certs = json.loads(response.read().decode("utf-8"))
                max_age = cache_control_max_age(
                    response.headers.get("Cache-Control")
                )
        except (urllib.error.URLError, ValueError) as err:
            if cached and cached["certs"]:
                LOG.warning(
                    "Reusing cached signing certificates from %s: %s",
                    certs_url,
                    err,
                )
                return cached["certs"]
            raise BrokerError(
                502, "Could not fetch token signing certificates."
            ) from err

        self._caches[certs_url] = {
            "certs": certs,
            "expires_at": now + (max_age or 3600),
        }
        return certs


def verify(key_store, raw_token, certs_url, audience):
    """Verify signature, audience and expiry of a JWT.

    google.auth.jwt.decode checks "aud" and "exp" but not "iss", so every
    caller is responsible for validating the issuer itself.
    """
    try:
        header = google_jwt.decode_header(raw_token)
    except ValueError as err:
        raise BrokerError(403, "Invalid desktop identity token.") from err

    key_id = header.get("kid")
    certs = key_store.get(certs_url)
    if key_id and key_id not in certs:
        # Signing keys rotate; refresh once before rejecting.
        certs = key_store.get(certs_url, refresh=True)

    try:
        return google_jwt.decode(raw_token, certs=certs, audience=audience)
    except ValueError as err:
        LOG.warning("Rejected desktop identity token: %s", err)
        raise BrokerError(
            403, "Desktop identity token could not be verified."
        ) from err


def strip_bearer(raw_token):
    if raw_token.lower().startswith("bearer "):
        return raw_token.split(None, 1)[1].strip()
    return raw_token
