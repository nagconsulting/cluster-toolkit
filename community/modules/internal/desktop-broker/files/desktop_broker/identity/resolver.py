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

"""Deciding which user a request belongs to.

Each trust model lives in its own module and returns the same shape, so adding
one means adding a module and an entry in _RESOLVERS - nothing else in the
broker changes.
"""

import hmac
import importlib
import logging

from ..errors import BrokerError

LOG = logging.getLogger("ghpc-desktop-broker")

# Mode -> the module implementing it. Backends are imported on first use rather
# than here, because main.tf installs each mode's dependencies only when that
# mode is selected: google-auth and cryptography are iap-only. Importing every
# backend eagerly made a trusted_proxy broker fail at startup on the iap import
# chain (iap -> jwt -> cryptography), for dependencies it was deliberately never
# given.
_RESOLVERS = {
    "trusted_proxy": "trusted_proxy",
    "iap": "iap",
}


def _backend(mode):
    """Import the backend module implementing `mode`."""
    return importlib.import_module(f".{_RESOLVERS[mode]}", __package__)


# Headers the broker reads. Named once here so the set is auditable.
HEADERS = {
    "secret": "X-Cluster-Desktop-Secret",
    "email": "X-Cluster-Desktop-Email",
    "login_uid": "X-Cluster-Desktop-Login-Uid",
    "username": "X-Cluster-Desktop-Username",
    "iap_assertion": "x-goog-iap-jwt-assertion",
}


def presented_from_headers(headers):
    """Extract every header the resolvers may look at."""
    return {
        key: str(headers.get(header, "") or "").strip()
        for key, header in HEADERS.items()
    }


class Resolver:
    """Applies the configured trust model to a request's headers."""

    def __init__(self, config):
        self.config = config
        self._resolve = _backend(config.identity_mode).resolve
        self._key_store = None
        self._audience = None

        if config.identity_mode == "trusted_proxy":
            LOG.warning(
                "identity_mode=trusted_proxy: desktop identity is taken from "
                "request headers with no token verification. Only use this "
                "where an authenticating proxy is the sole route to this "
                "broker."
            )

        if config.identity_mode == "iap":
            # Imported here for the same reason as the backends above: these
            # carry the google-auth and cryptography dependencies that only an
            # iap deployment installs.
            jwt = importlib.import_module(".jwt", __package__)
            self._key_store = jwt.KeyStore()
            self._audience = _backend("iap").AudienceResolver(config)

    def resolve(self, presented):
        """Verify the shared secret where one is set, then apply the mode.

        The secret proves a request arrived through the intended front end. In
        iap mode the assertion proves that cryptographically and names the
        backend service it was minted for, so the secret is optional there and
        omitting it keeps the value out of the load balancer's configuration.
        """
        if self.config.proxy_secret:
            if not hmac.compare_digest(
                presented["secret"].encode("utf-8"),
                self.config.proxy_secret.encode("utf-8"),
            ):
                raise BrokerError(403, "Missing or invalid desktop proxy secret.")

        if self.config.identity_mode == "iap":
            return self._resolve(
                presented,
                self.config,
                self._key_store,
                audience_resolver=self._audience,
            )
        return self._resolve(presented, self.config)
