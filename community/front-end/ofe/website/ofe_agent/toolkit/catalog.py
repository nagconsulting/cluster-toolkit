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

"""The cluster-blueprint-assistant skill's catalog.yaml, and the companion
example deployment files it points to."""

import functools

import yaml

from .errors import ToolError
from .paths import CATALOG, REPO_ROOT


@functools.cache
def catalog_doc():
    with CATALOG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def blueprints():
    """Catalog blueprints by path."""
    return {b["path"]: b for b in catalog_doc()["blueprints"]}


def check_blueprint(path):
    if path not in blueprints():
        raise ToolError(f"{path!r} is not a catalog blueprint")


def list_blueprints():
    """Compact view of every catalog blueprint, used for ranking."""
    return [
        {
            "path": b["path"],
            "scheduler": b.get("scheduler"),
            "description": b.get("description", "")[:300],
            "machine_types": b.get("machine_types", []),
            "modules": sorted({m["source"].rsplit("/", 1)[-1] for m in b.get("modules", [])}),
        }
        for b in blueprints().values()
    ]


def list_modules():
    """Catalog module_wiring: which modules satisfy each module's required
    inputs (recommended_use) and which consume its outputs (consumed_by)."""
    return [
        {"source": src, **{k: v for k, v in w.items() if k != "required_services"}}
        for src, w in catalog_doc().get("module_wiring", {}).items()
    ]


def companion_deployment(path):
    """Text of the tracked example deployment file for a catalog blueprint
    (catalog `deployment_path`), or None. Read-only reference: its values
    are placeholders."""
    check_blueprint(path)
    rel = blueprints()[path].get("deployment_path")
    return (REPO_ROOT / rel).read_text() if rel else None
