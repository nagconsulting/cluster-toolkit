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

"""A catalog blueprint as the Cluster Builder form sees it: its modules and
settings, where each var is used, and module metadata from `explain`."""

import functools
import re

import yaml

from . import catalog
from .errors import ToolError
from .gcluster import MODULE_RE, describe, module_explain
from .paths import REPO_ROOT
from .values import VAR_REF_ANY_RE, VAR_REF_RE
from .stages import image, stages
from .view import clean_text, view_text


@functools.cache
def template(path):
    """Parsed catalog blueprint: module id -> (source, settings)."""
    doc = yaml.safe_load((REPO_ROOT / path).read_text())
    return {
        m["id"]: (m["source"], m.get("settings") or {})
        for g in doc.get("deployment_groups", []) for m in g.get("modules", [])
    }


def input_info(source, name):
    """explain's entry for one module input, or None."""
    ex = module_explain(source) or {}
    return next((i for i in (ex.get("required_inputs") or []) + (ex.get("optional_inputs") or [])
                 if i["name"] == name), None)


_DOCS_MAX = 8000
_GENERATED_DOCS_RE = re.compile(
    r"<!-- BEGINNING OF PRE-COMMIT-TERRAFORM DOCS HOOK -->.*?<!-- END OF PRE-COMMIT-TERRAFORM DOCS HOOK -->", re.S)


@functools.cache
def module_docs(source):
    """A local module's README as guidance: its own text and examples (use
    cases, related modules, how to reach what it creates), without the
    generated inputs/outputs tables `describe` already gives, comments or
    the licence header; cut at _DOCS_MAX characters."""
    if not (module_explain(source) and MODULE_RE.match(source)):
        raise ToolError(f"{source!r} is not a module under modules/ or community/modules/")
    readme = REPO_ROOT / source / "README.md"
    if not readme.is_file():
        return "(this module has no README)"
    text = _GENERATED_DOCS_RE.sub("", readme.read_text())
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= _DOCS_MAX else text[:_DOCS_MAX] + "\n…(truncated)"


def module_data(source):
    """Form metadata for one in-repo module."""
    ex = module_explain(source)
    if not ex:
        raise ToolError(f"{source!r} is not a module under modules/ or community/modules/")
    wiring = catalog.catalog_doc().get("module_wiring", {}).get(source, {})
    return {
        "source": source,
        "kind": ex.get("kind"),
        "deprecated": ex.get("deprecated"),
        "inputs": (ex.get("required_inputs") or []) + (ex.get("optional_inputs") or []),
        "required": [i["name"] for i in ex.get("required_inputs") or []],
        "auto": ex.get("auto_injected_inputs") or [],
        "recommended_use": wiring.get("recommended_use", []),
        "consumed_by": wiring.get("consumed_by", []),
    }


def var_uses(path):
    """Where each var is used in the blueprint's module settings, so a var's
    meaning comes from the module input it populates:
    {var: [{"module", "input", "path", "exact"}]} where path is the location
    inside the input (e.g. "subnetworks[0].subnet_name") and exact means the
    var is the whole value of the input."""
    uses = {}

    def walk(value, mid, inp, where):
        if isinstance(value, str):
            for var in VAR_REF_ANY_RE.findall(value):
                uses.setdefault(var, []).append({
                    "module": mid, "input": inp, "path": where,
                    "exact": where == inp and VAR_REF_RE.match(value) is not None,
                })
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, mid, inp, f"{where}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, mid, inp, f"{where}[{i}]")

    for mid, (_, settings) in template(path).items():
        for inp, value in settings.items():
            walk(value, mid, inp, inp)
    return uses


def _kind(type_name):
    """A type as `gcluster explain` names a blueprint var's: string, number,
    bool, list or map/object (a module input's `type` is the full constraint,
    e.g. list(object({...})))."""
    base = type_name.split("(", 1)[0]
    return {"set": "list", "tuple": "list", "map": "map/object", "object": "map/object"}.get(base, base)


def unwired_inputs(path):
    """Module inputs a var could also set: the var is only used inside other
    values, and a module leaves an input of the same name and type unset, so
    it sets its own value and the two can differ. E.g. the A3 Slurm
    blueprints use slurm_cluster_name in SSH host patterns while
    slurm_controller names the cluster itself. {var: [{"module", "input"}]}."""
    uses, out = var_uses(path), {}
    for v in describe(path)["variables"]:
        u = uses.get(v["name"], [])
        if v.get("global") or not u or any(x["exact"] for x in u):
            continue
        for mid, (source, settings) in template(path).items():
            info = input_info(source, v["name"])
            if info and not info.get("deprecated") and _kind(info["type"]) == _kind(v["type"]) \
                    and v["name"] not in settings:
                out.setdefault(v["name"], []).append({"module": mid, "input": v["name"]})
    return out


EXISTING_NETWORK = "modules/network/pre-existing-vpc"
MAX_NAME = 63  # GCP resource names


def _outputs(source):
    return [o if isinstance(o, str) else o.get("name", "") for o in (module_explain(source) or {}).get("outputs") or []]


def creates_network(source):
    """Whether the module creates networks: `gcluster explain` shows it
    provides them (a network_self_link(s) output) and it is not the
    existing-network module, which only looks one up."""
    return source != EXISTING_NETWORK and bool({"network_self_link", "network_self_links"} & set(_outputs(source)))


@functools.cache
def generated_names(path):
    """Vars the blueprint leaves to the user (no value; its example
    deployment file says "supply ...") that only name networks it creates,
    so OFE names them from the deployment name instead of asking. They
    cannot be left to the module (whose own default would name the
    network): gcluster rejects a declared var with no value.

    {var: suffix}: the module id, plus the attribute for a name inside a
    larger value (<id>.subnetworks[0].subnet_name -> "-<id>-subnet"). Vars that
    refer to existing things (reservations, servers) are not used only
    inside network-creating modules, so never match."""
    uses, modules, out = var_uses(path), template(path), {}
    for v in describe(path)["variables"]:
        u = uses.get(v["name"])
        if not v.get("required") or v.get("global") or v["type"] != "string" or not u:
            continue
        if all(x["module"] in modules and creates_network(modules[x["module"]][0]) for x in u):
            first = u[0]
            leaf = re.split(r"[.\[]", first["path"])[-1].removesuffix("_name")
            out[v["name"]] = f"-{first['module']}" + ("" if first["exact"] else f"-{leaf}")
    return out


def generated_value(deployment_name, suffix):
    """A valid GCP name: lowercase letters, digits and hyphens, at most 63
    characters, not ending in a hyphen. Kept in step with builder.html genName."""
    name = re.sub(r"[^a-z0-9-]", "-", f"{deployment_name}{suffix}".lower())[:MAX_NAME]
    return name.rstrip("-")


def blueprint_data(path):
    """Everything the Cluster Builder form needs for one catalog blueprint:
    declared vars, hints from its vars: comments and companion deployment
    file, the template as shown (without vars:) and as downloaded (see
    view.py), each module's settings and, for local modules, their inputs
    with validations from `gcluster explain`."""
    catalog.check_blueprint(path)
    modules = template(path)
    text = (REPO_ROOT / path).read_text()
    use = {m["id"]: m.get("use", []) for m in catalog.blueprints()[path].get("modules", [])}
    module_meta = {}
    for source, _ in modules.values():
        if source not in module_meta and module_explain(source):
            module_meta[source] = module_data(source)
    return {
        "path": path,
        "variables": describe(path)["variables"],
        "uses": var_uses(path),
        "unwired": unwired_inputs(path),
        "generated": generated_names(path),
        "hints": catalog.blueprint_hints(path),
        "template_view": view_text(text),
        "template_clean": clean_text(text),
        "modules": [{"id": i, "source": src, "use": use.get(i, [])} for i, (src, _) in modules.items()],
        "module_settings": {i: settings for i, (_, settings) in modules.items()},
        "module_meta": module_meta,
        "stages": stages(path),
        "image": image(path),
    }


def _short(value, limit=120):
    """value with long strings cut, for the model's summary."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {k: _short(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_short(v, limit) for v in value]
    return value


@functools.cache
def summary(path):
    """A blueprint as the agent needs it, given up front so it rarely has to
    call describe: each var with what it feeds (module.input path) and any
    note from the blueprint's or its example deployment file's comments;
    each module's source, use and settings (long strings cut); its
    deployment groups by role and the custom image it builds, if any
    (stages.py)."""
    catalog.check_blueprint(path)
    uses, hints, generated = var_uses(path), catalog.blueprint_hints(path), generated_names(path)
    variables = []
    for v in describe(path)["variables"]:
        entry = {k: v[k] for k in ("name", "type", "default", "required", "global") if v.get(k)}
        if v["name"] in generated:
            entry.pop("required", None)
            entry["generated"] = f"OFE sets it to <deployment_name>{generated[v['name']]}; do not ask for it"
        if uses.get(v["name"]):
            entry["feeds"] = [f"{u['module']}.{u['path']}" for u in uses[v["name"]]]
        if hints.get(v["name"], {}).get("comment"):
            entry["note"] = hints[v["name"]]["comment"]
        variables.append(entry)
    use = {m["id"]: m.get("use", []) for m in catalog.blueprints()[path].get("modules", [])}
    img = image(path)
    return {
        "blueprint": path,
        "stages": [{k: s[k] for k in ("group", "role", "modules") if k in s} for s in stages(path)],
        **({"image": {k: img[k] for k in ("groups", "family", "family_var", "image_only")}} if img else {}),
        "variables": variables,
        "modules": [{"id": i, "source": src, "use": use.get(i, []), "settings": _short(settings)}
                    for i, (src, settings) in template(path).items()],
    }


def warm(workers=4):
    """Fill the explain and template caches for every catalog blueprint and
    the local modules they and module_wiring use. The repo only changes on
    redeploy, which restarts the server, so nothing ever expires."""
    from concurrent.futures import ThreadPoolExecutor  # pylint: disable=import-outside-toplevel

    paths = list(catalog.blueprints())
    sources = set(catalog.catalog_doc().get("module_wiring", {}))
    for p in paths:
        sources.update(src for src, _ in template(p).values())
    try:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(_quietly(summary), paths))
            list(pool.map(_quietly(module_explain), sorted(sources)))
    except RuntimeError:  # the server is shutting down (e.g. a reload) mid-warm-up
        return 0, 0
    return len(paths), len(sources)


def _quietly(fn):
    def call(arg):
        try:
            fn(arg)
        except Exception:  # pylint: disable=broad-except
            pass  # the request that needs it reports the error
    return call
