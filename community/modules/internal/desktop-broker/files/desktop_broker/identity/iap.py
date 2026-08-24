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

"""Identity from an Identity-Aware Proxy assertion.

IAP puts a signed assertion in "x-goog-iap-jwt-assertion" on every request it
forwards. It is deliberately *not* an OIDC ID token and the 'token' mode cannot
verify it: the algorithm is ES256 rather than RS256, the keys come from IAP's
own JWK set rather than Google's OIDC certs, the issuer is
"https://cloud.google.com/iap", and the audience names a backend service rather
than an OAuth client.

The audience is the security boundary. Without it, an assertion minted for any
other IAP-protected service in any project would verify here, so a missing
audience is a hard failure rather than a skipped check.

Resolving that audience is awkward by construction: it contains the numeric ID
of the backend service fronting this instance, which does not exist until the
load balancer is built, while the load balancer cannot be built until the
instance exists. Terraform therefore cannot hand it to us at deploy time
without a dependency cycle. Two ways out, in order of preference:

  1. identity_audience set explicitly, once the backend service ID is known
     (a second apply, or a value the operator supplies).
  2. iap_backend_service naming the backend service, which is looked up through
     the Compute API at first use. This is what Google's own
     guacamole-auth-googleiap extension does, and it needs
     roles/compute.viewer on the instance service account.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from ..errors import BrokerError
from . import jwt
from .common import identity

LOG = logging.getLogger("ghpc-desktop-broker")

# IAP signs with ES256 and publishes its keys separately from Google's OIDC
# certificates.
CERTS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk"
ISSUER = "https://cloud.google.com/iap"

_METADATA_ROOT = "http://metadata.google.internal/computeMetadata/v1"
_BACKEND_SERVICES_URL = (
    "https://compute.googleapis.com/compute/v1/projects/{project}"
    "/global/backendServices/{name}"
)

AUDIENCE_TEMPLATE = "/projects/{project_number}/global/backendServices/{backend_id}"


def _metadata(path):
    request = urllib.request.Request(
        f"{_METADATA_ROOT}/{path}", headers={"Metadata-Flavor": "Google"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8").strip()
    except (urllib.error.URLError, OSError) as err:
        raise BrokerError(
            502, f"Metadata lookup for {path} failed: {err}"
        ) from err


class AudienceResolver:
    """Supplies the expected "aud" claim, resolving it lazily if need be.

    Cached for the process lifetime: a backend service's numeric ID is stable,
    so re-resolving per request would add a Compute API call to every desktop
    hand-off for no benefit.
    """

    def __init__(self, config):
        self._configured = config.identity_audience
        self._backend_service = config.iap_backend_service
        self._resolved = None

    def get(self):
        if self._configured:
            return self._configured
        if self._resolved:
            return self._resolved
        self._resolved = self._lookup()
        LOG.info("Resolved IAP audience to %s", self._resolved)
        return self._resolved

    def _lookup(self):
        project_number = _metadata("project/numeric-project-id")
        project_id = _metadata("project/project-id")
        token = json.loads(
            _metadata("instance/service-accounts/default/token")
        )["access_token"]

        url = _BACKEND_SERVICES_URL.format(
            project=urllib.parse.quote(project_id),
            name=urllib.parse.quote(self._backend_service),
        )
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                backend = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            hint = (
                " The instance service account needs roles/compute.viewer to "
                "read the backend service."
                if err.code in (401, 403)
                else ""
            )
            raise BrokerError(
                502,
                f"Could not look up backend service "
                f"{self._backend_service!r} (HTTP {err.code}).{hint}",
            ) from err
        except (urllib.error.URLError, ValueError) as err:
            raise BrokerError(
                502,
                f"Could not look up backend service "
                f"{self._backend_service!r}: {err}",
            ) from err

        backend_id = str(backend.get("id") or "").strip()
        if not backend_id:
            raise BrokerError(
                502,
                f"Backend service {self._backend_service!r} returned no id.",
            )
        return AUDIENCE_TEMPLATE.format(
            project_number=project_number, backend_id=backend_id
        )


def resolve(presented, config, key_store, audience_resolver=None):
    raw_assertion = presented["iap_assertion"]
    if not raw_assertion:
        raise BrokerError(
            403,
            "Missing IAP assertion. This broker expects to be reached through "
            "Identity-Aware Proxy.",
        )

    resolver = audience_resolver or AudienceResolver(config)
    claims = jwt.verify(
        key_store,
        jwt.strip_bearer(raw_assertion),
        CERTS_URL,
        resolver.get(),
    )

    if str(claims.get("iss") or "").strip() != ISSUER:
        raise BrokerError(403, "IAP assertion has an unexpected issuer.")

    email = str(claims.get("email") or "").strip().lower()
    # IAP's subject is prefixed with the identity provider, as
    # "accounts.google.com:123456789". OS Login joins on the bare numeric
    # subject, so keep only the part after the last colon.
    subject = str(claims.get("sub") or "").strip()
    login_uid = subject.rsplit(":", 1)[-1] if subject else ""
    if not email and not login_uid:
        raise BrokerError(
            403, "IAP assertion carries neither an email nor a subject."
        )
    return identity(email=email, login_uid=login_uid)
