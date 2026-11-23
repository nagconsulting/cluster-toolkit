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

"""Running gcluster, and `gcluster explain` for blueprints and modules."""

import difflib
import functools
import json
import os
import re
import subprocess

from . import catalog
from .errors import ToolError
from .paths import GCLUSTER, REPO_ROOT

_SPEC_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
MODULE_RE = re.compile(r"^(community/)?modules/[a-z0-9_-]+(/[a-z0-9_-]+)*$")


def run(*args, credentials_file=None, timeout=180):
    """Run gcluster from the repo root; returns (returncode, stdout, stderr)."""
    env = dict(os.environ)
    if credentials_file:
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_file)
    proc = subprocess.run(
        [str(GCLUSTER), "--no-color", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def explain_json(*args):
    code, out, err = run("explain", *args, "-f", "json")
    if code != 0:
        raise ToolError(f"gcluster explain failed: {err.strip()[-2000:]}")
    return json.loads(out)


def find_blueprints(specs):
    """Closest blueprint for keyword specs via `gcluster explain <specs>`."""
    if not 1 <= len(specs) <= 8:
        raise ToolError("give between 1 and 8 specs")
    for s in specs:
        if not _SPEC_RE.match(s):
            raise ToolError(f"spec {s!r} must be a short lowercase word")
    return explain_json(*specs)


@functools.cache
def describe(path):
    """`gcluster explain` for a catalog blueprint or an in-repo module.
    Cached: the repo does not change while the server runs."""
    if path in catalog.blueprints():
        return explain_json(path)
    if MODULE_RE.match(path) and (REPO_ROOT / path).is_dir():
        return _with_deprecated_inputs(explain_json(path))
    close = difflib.get_close_matches(path, list(catalog.blueprints()) + _module_paths(), n=3, cutoff=0.5)
    raise ToolError(
        f"{path!r} is neither a catalog blueprint nor a module under"
        " modules/ or community/modules/"
        + (f"; did you mean {close}?" if close else "; list_blueprints lists the catalog")
    )


def _with_deprecated_inputs(ex):
    """Module explain output with its deprecated_inputs back among
    optional_inputs, each with "deprecated" set to its replacement guidance,
    so a blueprint that already sets one still finds its metadata (forms show
    it with a warning; nothing offers it for new use)."""
    ex["optional_inputs"] = sorted(
        (ex.get("optional_inputs") or []) + [
            {**i, "deprecated": i.get("description") or "deprecated"} for i in ex.get("deprecated_inputs") or []],
        key=lambda i: i["name"])
    return ex


@functools.cache
def _module_paths():
    """Every local module (a directory with metadata.yaml) under modules/ and community/modules/."""
    return sorted(str(m.parent.relative_to(REPO_ROOT)) for top in ("modules", "community/modules")
                  for m in (REPO_ROOT / top).rglob("metadata.yaml"))


@functools.cache
def module_explain(source):
    """`describe` for an in-repo module source, or None for remote or
    packer-only sources (no form metadata)."""
    if MODULE_RE.match(source) and (REPO_ROOT / source).is_dir():
        return describe(source)
    return None
