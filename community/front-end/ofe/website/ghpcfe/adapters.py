# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Adapters for social accounts"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from .models import AuthorisedUser

import logging

logger = logging.getLogger(__name__)


class CustomAccountAdapter(DefaultAccountAdapter):
    """Simple adapter disallowing signupts"""

    def is_open_for_signup(self, request):
        return False  # No signups allowed


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Adapter allowing simple whitelisting of users"""

    def pre_social_login(self, request, sociallogin):
        """Link a Google login to an existing OFE user with the same email.

        Without this, a user created before Google login was enabled cannot
        subsequently sign in with "Login with Google" using their own email -
        allauth treats it as a new signup and is_open_for_signup below has no
        way to associate it with their existing account. It also matters for
        the desktop broker: identity resolution needs a Google login uid
        (see views/desktop.py _get_google_login_uid), which only exists once
        the social account is linked.
        """
        if sociallogin.is_existing:
            return

        email = (sociallogin.user.email or "").strip().lower()
        if not email:
            return

        user_model = get_user_model()
        try:
            existing_user = user_model.objects.get(email__iexact=email)
        except user_model.DoesNotExist:
            return
        except user_model.MultipleObjectsReturned:
            logger.warning(
                "Multiple OFE users share the email %s; not linking the Google "
                "social account automatically",
                email,
            )
            return

        logger.info(
            "Linking Google social account for %s to existing OFE user %s",
            email,
            existing_user.username,
        )
        sociallogin.connect(request, existing_user)

    def is_open_for_signup(self, request, sociallogin):
        u = sociallogin.user
        ret = False
        authorised = AuthorisedUser.objects.all()
        for entry in authorised:
            if u.email == entry.pattern:  # exact email address match
                ret = True
                break
            if u.email.endswith(entry.pattern):  # domain name match
                ret = True
                break
        if ret:
            logger.info("User %s logged in with Google account.", u.email)
        else:
            logger.info(
                "User %s not authorised to access this system.", u.email
            )
        return ret
