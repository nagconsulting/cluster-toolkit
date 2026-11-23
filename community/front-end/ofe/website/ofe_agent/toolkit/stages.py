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

"""A catalog blueprint's deployment groups by what they are for, and the
custom image it builds, if any.

Blueprints that build an image (a Packer group, e.g. a3mega-slurm) build it
in the same deployment as the cluster. OFE flags them so the image can be
built once, separately, and reused by later clusters:

- role "image": a Packer group.
- role "image-support": a Terraform group whose modules only image groups
  use (e.g. the startup script a Packer group runs).
- role "cluster": the rest. `shared` marks cluster groups an image group
  also uses (usually the network the build VM runs on).

recipe_hash identifies what goes into the image (sources, settings, staged
files), not where it is built, so an image built for one deployment can be
recognised as the right one for another.
"""

import functools
import hashlib
import json
import re

import yaml

from . import catalog
from .paths import REPO_ROOT

# Values that differ per deployment and do not change what is in the image.
PER_DEPLOYMENT_VARS = {"project_id", "deployment_name", "region", "zone", "labels"}
PER_DEPLOYMENT_SETTINGS = {
    "deployment_name", "project_id", "region", "zone", "labels", "network_name", "network_project_id",
    "subnetwork_name", "subnetwork_project", "image_name", "image_family", "machine_type",
    "state_timeout", "use_iap", "omit_external_ip", "service_account_email", "service_account_scopes",
    "tags", "image_storage_locations",
}
_WHOLE_REF_RE = re.compile(r"^\$\(vars\.([a-z0-9_]+(?:\.[a-z0-9_]+)*)\)$")
_REF_RE = re.compile(r"\$\(vars\.([a-z0-9_]+(?:\.[a-z0-9_]+)*)\)")
_STAGE_RE = re.compile(r"ghpc_stage\(\"([^\"]+)\"\)")
_MAX_DEPTH = 8


def _doc(path):
    return yaml.safe_load((REPO_ROOT / path).read_text())


def _var_values(path, overrides=None):
    """Blueprint vars, then the example deployment file's, then overrides."""
    values = dict(_doc(path).get("vars") or {})
    companion = catalog.companion_deployment(path)
    if companion:
        values.update((yaml.safe_load(companion) or {}).get("vars") or {})
    values.update(overrides or {})
    return values


def _lookup(values, ref):
    name, *attrs = ref.split(".")
    if name in PER_DEPLOYMENT_VARS:
        return f"<{ref}>"
    value = values.get(name)
    for a in attrs:
        value = value.get(a) if isinstance(value, dict) else None
    return value


def resolve(value, values, depth=0):
    """value with $(vars.x[.attr]) references replaced by their values (whole
    references keep the value's type); per-deployment vars become <name>."""
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        whole = _WHOLE_REF_RE.match(value)
        if whole:
            return resolve(_lookup(values, whole.group(1)), values, depth + 1)
        return _REF_RE.sub(lambda m: str(resolve(_lookup(values, m.group(1)), values, depth + 1)), value)
    if isinstance(value, dict):
        return {k: resolve(v, values, depth) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, values, depth) for v in value]
    return value


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _depends_on(module, ids):
    """Ids of the modules this module uses: its `use` list and module
    outputs referenced in its settings ($(<id>.<output>), also inside
    expressions such as $(flatten([a.x, b.y])))."""
    out = set(module.get("use") or [])
    for s in _strings(module.get("settings") or {}):
        if "$(" in s:
            out |= {i for i in ids if re.search(rf"(?<![\w.-]){re.escape(i)}\.[A-Za-z_]", s)}
    return out - {module["id"]}


@functools.cache
def stages(path):
    """[{"group", "kind", "role", "modules", "shared"?}] in deployment order."""
    catalog.check_blueprint(path)
    groups = _doc(path).get("deployment_groups") or []
    mods = {m["id"]: (g["group"], m) for g in groups for m in g.get("modules") or []}
    consumers = {i: set() for i in mods}  # module id -> groups of modules that use it
    for i, (_, m) in mods.items():
        for dep in _depends_on(m, mods):
            if dep in consumers:
                consumers[dep].add(mods[i][0])
    kind = {g["group"]: "packer" if any(m.get("kind") == "packer" for m in g.get("modules") or []) else "terraform"
            for g in groups}
    role = {name: "image" for name, k in kind.items() if k == "packer"}
    for g in reversed(groups):  # later groups first: support of support is support
        name = g["group"]
        if name in role:
            continue
        used_by = set().union(*(consumers[m["id"]] for m in g.get("modules") or [])) - {name}
        role[name] = "image-support" if used_by and used_by <= {n for n, r in role.items() if r != "cluster"} \
            else "cluster"
    image_groups = {n for n, r in role.items() if r != "cluster"}
    out = []
    for g in groups:
        name = g["group"]
        entry = {"group": name, "kind": kind[name], "role": role[name],
                 "modules": [m["id"] for m in g.get("modules") or []]}
        if role[name] == "cluster" and any(consumers[m["id"]] & image_groups for m in g.get("modules") or []):
            entry["shared"] = True
        out.append(entry)
    return out


def image(path, overrides=None):
    """The custom image a blueprint builds, or None:
    {"groups": image and image-support groups, "module": the Packer module
    id, "family": its image family (None: the deployment name, so a new
    family per deployment), "family_var": the var that sets it, if any,
    "image_only": no cluster groups (an image recipe, e.g.
    build-service-images), "recipe_hash"}."""
    st = stages(path)
    image_groups = [s["group"] for s in st if s["role"] != "cluster"]
    packer = [s for s in st if s["role"] == "image"]
    if not packer:
        return None
    values = _var_values(path, overrides)
    module = next(m for g in _doc(path)["deployment_groups"] if g["group"] == packer[0]["group"]
                  for m in g["modules"])
    family_setting = (module.get("settings") or {}).get("image_family")
    family = resolve(family_setting, values) if family_setting is not None else None
    var = _WHOLE_REF_RE.match(family_setting) if isinstance(family_setting, str) else None
    return {
        "groups": image_groups,
        "module": module["id"],
        "family": family if isinstance(family, str) and not family.startswith("<") else None,
        "family_var": var.group(1) if var else None,
        "image_only": all(s["role"] != "cluster" for s in st),
        "recipe_hash": recipe_hash(path, overrides),
    }


def recipe_hash(path, overrides=None):
    """16 hex characters (a valid GCE label value) identifying what the image
    groups put into the image: each module's source, kind, use and settings
    with vars resolved, leaving out per-deployment settings (names, project,
    location, labels, build machine), plus the content of files they stage
    with ghpc_stage(). The same recipe in another deployment, project or
    zone gives the same hash; a changed script or setting does not."""
    st = stages(path)
    image_groups = {s["group"] for s in st if s["role"] != "cluster"}
    values = _var_values(path, overrides)
    recipe = []
    for g in _doc(path).get("deployment_groups") or []:
        if g["group"] not in image_groups:
            continue
        for m in g.get("modules") or []:
            settings = {k: v for k, v in (m.get("settings") or {}).items() if k not in PER_DEPLOYMENT_SETTINGS}
            resolved = resolve(settings, values)
            recipe.append({"source": m["source"], "kind": m.get("kind", "terraform"), "use": sorted(m.get("use") or []),
                           "settings": resolved, "files": _staged_files(path, resolved)})
    blob = json.dumps(recipe, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _staged_files(path, settings):
    """{staged path: sha256 of its content (a directory: of every file in it)}."""
    base = (REPO_ROOT / path).parent
    out = {}
    for s in _strings(settings):
        for rel in _STAGE_RE.findall(s):
            target = (base / rel).resolve()
            files = sorted(p for p in target.rglob("*") if p.is_file()) if target.is_dir() else [target]
            h = hashlib.sha256()
            for f in files:
                if f.is_file():
                    h.update(str(f.relative_to(target) if target.is_dir() else f.name).encode())
                    h.update(f.read_bytes())
            out[rel] = h.hexdigest()
    return out
