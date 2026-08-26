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

"""The desktop chooser.

Two properties matter beyond "it renders": the page is built from values that
reach it through configuration, so anything injectable must be escaped; and
listing desktops must not start one, or merely deciding which desktop you want
would spawn an Xvnc on whichever host served the page.
"""

import pytest

from conftest import base_config
from desktop_broker import index
from desktop_broker.config import Config, ConfigError

ENTRIES = [
    {"name": "viz", "url": "https://viz.example.com", "description": "GPU"},
    {"name": "login", "url": "https://login.example.com"},
]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_entries_are_listed():
    page = index.render(ENTRIES)
    assert "viz" in page and "https://viz.example.com" in page
    assert "login" in page and "https://login.example.com" in page
    assert page.startswith("<!doctype html>")


def test_description_is_shown_when_present():
    assert "viz - GPU" in index.render(ENTRIES)


def test_signed_in_user_is_shown():
    assert "someone@example.com" in index.render(ENTRIES, "someone@example.com")


def test_no_user_line_when_unknown():
    assert "Signed in as" not in index.render(ENTRIES)


def test_empty_list_says_so_rather_than_rendering_nothing():
    assert "No desktops are configured" in index.render([])


def test_entries_missing_a_name_or_url_are_skipped():
    page = index.render([{"name": "", "url": "https://a.example.com"},
                         {"name": "b", "url": ""},
                         {"name": "c", "url": "https://c.example.com"}])
    assert "c.example.com" in page
    assert "a.example.com" not in page


# --------------------------------------------------------------------------
# Escaping and link safety
# --------------------------------------------------------------------------


def test_names_are_escaped():
    page = index.render([{"name": "<script>alert(1)</script>",
                          "url": "https://x.example.com"}])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_descriptions_are_escaped():
    page = index.render([{"name": "a", "url": "https://x.example.com",
                          "description": "<img onerror=x>"}])
    assert "<img" not in page


def test_url_quotes_cannot_break_out_of_the_attribute():
    page = index.render([{"name": "a",
                          "url": 'https://x.example.com/"><script>alert(1)</script>'}])
    assert "<script>alert(1)</script>" not in page


@pytest.mark.parametrize("scheme", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
])
def test_only_http_urls_become_links(scheme):
    """A non-browsable scheme in configuration must not become a link."""
    page = index.render([{"name": "bad", "url": scheme}])
    assert "bad" not in page
    assert "No desktops are configured" in page


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_index_is_off_by_default(tmp_path):
    config = Config(base_config(tmp_path))
    assert config.desktop_index == []
    assert config.desktop_index_path == ""


def test_index_path_is_accepted(tmp_path):
    config = Config(base_config(
        tmp_path, desktop_index_path="/desktops", desktop_index=ENTRIES))
    assert config.desktop_index_path == "/desktops"
    assert len(config.desktop_index) == 2


def test_index_path_must_be_absolute(tmp_path):
    with pytest.raises(ConfigError, match="must start with"):
        Config(base_config(tmp_path, desktop_index_path="desktops"))


def test_index_path_cannot_shadow_healthz(tmp_path):
    """/healthz is served unauthenticated; the listing must never land there."""
    with pytest.raises(ConfigError, match="healthz"):
        Config(base_config(tmp_path, desktop_index_path="/healthz"))


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def test_route_is_registered_only_when_configured(tmp_path, monkeypatch):
    from desktop_broker import app as app_module

    monkeypatch.setattr(app_module, "Broker", lambda config: _StubBroker())

    without = app_module.build(Config(base_config(tmp_path)))
    with_index = app_module.build(Config(base_config(
        tmp_path, desktop_index_path="/desktops", desktop_index=ENTRIES)))

    def paths(application):
        return {getattr(r.resource, "canonical", None) for r in application.router.routes()}

    assert "/desktops" not in paths(without)
    assert "/desktops" in paths(with_index)


class _StubBroker:
    """Stands in for Broker, which would touch the filesystem on construction."""

    async def handle_health(self, request):
        return None

    async def handle_index(self, request):
        return None

    async def handle(self, request):
        return None

    async def start(self):
        return None

    async def stop(self):
        return None
