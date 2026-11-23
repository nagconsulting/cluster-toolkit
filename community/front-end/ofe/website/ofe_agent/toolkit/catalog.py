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
import re

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
    (catalog `deployment_path`), or None. Read-only reference: its comments
    say what each required var needs; its values are placeholders."""
    check_blueprint(path)
    rel = blueprints()[path].get("deployment_path")
    return (REPO_ROOT / rel).read_text() if rel else None


_HINT_LINE_RE = re.compile(r"^  (#\s*)?([a-z][a-z0-9_]*):\s*([^#]*?)\s*(?:#\s*(.*))?$")


def deployment_hints(path):
    """Per-var guidance from the companion deployment file:
    {var: {"comment": ..., "example": ...}}. Comments on the line itself or
    the comment lines directly above it; examples only when not empty."""
    text = companion_deployment(path)
    return vars_hints(text) if text else {}


def blueprint_hints(path):
    """deployment_hints merged with the comments in the blueprint's own
    vars: block (e.g. "pick only one" above a set of provisioning vars), so
    they survive when the page shows the blueprint without its vars. The
    blueprint's comment comes first; examples only come from the deployment
    file (the blueprint's values are its defaults)."""
    check_blueprint(path)
    own = vars_hints((REPO_ROOT / path).read_text())
    hints = {k: dict(v) for k, v in deployment_hints(path).items()}
    for name, h in own.items():
        entry = hints.setdefault(name, {"comment": "", "example": None, "notes": []})
        notes = list(dict.fromkeys(h["notes"] + entry["notes"]))  # same note in both files: once
        entry.update(notes=notes, comment=" ".join(notes)[:300])
    return {k: v for k, v in hints.items() if v["comment"] or v["example"]}


def vars_hints(text):
    """Per-var comments and values in the top-level vars: block of a
    blueprint or deployment file: {var: {"comment": ..., "example": ...,
    "notes": [...]}}. Comments on the line itself or the comment lines
    directly above it (notes, each once; comment joins them); examples only
    when not empty."""
    hints, above, in_vars = {}, [], False
    for line in text.splitlines():
        if re.match(r"^\S", line) and not line.startswith("#"):
            in_vars = line.startswith("vars:")
            above = []
            continue
        if not in_vars:
            continue
        m = _HINT_LINE_RE.match(line)
        if m:
            _, name, value, comment = m.groups()
            notes = list(dict.fromkeys(c for c in above + [_note(comment or "")] if c))
            example = value.strip().strip('"').strip("'")
            hints[name] = {"comment": " ".join(notes)[:300], "example": example or None, "notes": notes}
            above = []
        elif line.strip().startswith("#"):
            note = _note(line.strip().lstrip("#"))
            if note:
                above.append(note)
        elif not line.strip():
            above = []
    return hints


def _note(text):
    """A comment as a note: without the dashes or equals signs that frame
    section headers (# --- Optional overrides ---); "" if nothing is left."""
    return text.strip().strip("-=").strip()
