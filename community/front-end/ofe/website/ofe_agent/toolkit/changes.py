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

"""Template changes (promoted inputs, added and removed modules) and the
ai_assisted copy they produce. The tracked template is never modified."""

import io
import json
import re

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from . import catalog
from .blueprint import input_info, template, var_uses
from .errors import ToolError
from .gcluster import describe, module_explain
from .paths import REPO_ROOT
from .stages import stages
from .values import ID_RE, MODULE_ID_RE, SCALAR_TYPES, VAR_REF_RE, check_module_value, default_value

_MAX_CHANGES = 20


def check_changes(blueprint, changes):
    """Validate template changes and return them normalised:

    {"promoted": [{module, input, var, type, def, required, link}],  # existing module input -> new var;
                                                     # required: no default, the user supplies it;
                                                     # link: an existing var instead (see unwired_inputs)
     "add_modules": [{id, source, use, used_by, settings}],
     "remove_modules": [id],
     "settings": [{module, input, value}],  # a list/object value set on an existing module
     "drop_vars": [var]}  # derived: vars only the removed modules used

    An added module may reuse the id of a removed one to replace it (e.g.
    the vpc module by pre-existing-vpc): it takes the removed module's place
    and the modules that used it keep using it; gcluster expand checks the
    replacement provides what they use.

    Each is applied to an ai_assisted copy (see blueprint_copy)."""
    changes = changes or {}
    if not isinstance(changes, dict):
        raise ToolError("changes must be an object")
    modules = template(blueprint)
    declared = {v["name"] for v in describe(blueprint)["variables"]}
    out = {"promoted": [], "add_modules": [], "remove_modules": [], "settings": [], "drop_vars": []}

    removed = changes.get("remove_modules") or []
    if not isinstance(removed, list) or len(removed) > _MAX_CHANGES:
        raise ToolError("remove_modules must be a short list of module ids")
    for mid in removed:
        if mid not in modules:
            raise ToolError(f"cannot remove {mid!r}: not a module of {blueprint}")
    out["remove_modules"] = list(dict.fromkeys(removed))
    remaining = set(modules) - set(removed)
    replaced = {a.get("id") for a in changes.get("add_modules") or [] if isinstance(a, dict)} & set(removed)

    added_ids = set()
    adds = changes.get("add_modules") or []
    if not isinstance(adds, list) or len(adds) > _MAX_CHANGES:
        raise ToolError("add_modules must be a short list")
    for a in adds:
        mid, source = a.get("id"), a.get("source")
        if (not isinstance(mid, str) or not MODULE_ID_RE.match(mid) or mid in added_ids
                or (mid in modules and mid not in removed)):
            raise ToolError(f"invalid or duplicate module id {mid!r}")
        ex = module_explain(source) if isinstance(source, str) else None
        if not ex:
            raise ToolError(f"{source!r} is not a module under modules/ or community/modules/")
        if ex.get("deprecated"):
            raise ToolError(f"{source} is deprecated")
        added_ids.add(mid)
    for a in adds:
        use, used_by = a.get("use") or [], a.get("used_by") or []
        for ref in use + used_by:
            if ref not in remaining and ref not in added_ids or ref == a["id"]:
                raise ToolError(f"{a['id']}: unknown module {ref!r} in use/used_by")
        settings = a.get("settings") or {}
        if not isinstance(settings, dict):
            raise ToolError(f"{a['id']}: settings must be an object")
        if a["id"] in replaced:
            used_by = []  # a replacement keeps exactly the replaced module's users
        out["add_modules"].append({"id": a["id"], "source": a["source"], "use": list(use),
                                   "used_by": list(used_by), "settings": settings})

    seen_vars = set()
    var_types = {v["name"]: v["type"] for v in describe(blueprint)["variables"]}
    promoted = changes.get("promoted") or []
    refs = declared | {p.get("var") for p in promoted if isinstance(p.get("var"), str)}
    if not isinstance(promoted, list) or len(promoted) > _MAX_CHANGES:
        raise ToolError("promoted must be a short list")
    for p in promoted:
        mod, inp, var = p.get("module"), p.get("input"), p.get("var")
        if mod not in remaining:
            raise ToolError(f"module {mod!r} is not in {blueprint}" + (" (it is replaced)" if mod in replaced else ""))
        source, settings = modules[mod]
        info = input_info(source, inp)
        if info is None:
            raise ToolError(f"{inp!r} is not an input of module {mod!r}")
        if info.get("deprecated"):
            raise ToolError(f"{mod}.{inp} is deprecated: {info['deprecated']}")
        if info["type"] not in SCALAR_TYPES:
            raise ToolError(f"{mod}.{inp} has type {info['type']}; only string, number and bool inputs can become"
                            " form fields. To change it, replace the module (remove_modules plus add_modules"
                            " with the same id and the settings you need)")
        if p.get("link"):  # an existing var also sets this input
            if var not in declared or var_types.get(var) != info["type"]:
                raise ToolError(f"{var!r} is not a {info['type']} variable of {blueprint}")
            if inp in settings:
                raise ToolError(f"{mod}.{inp} is already set in the template")
            out["promoted"].append({"module": mod, "input": inp, "var": var, "type": info["type"],
                                    "def": None, "required": False, "link": True})
            continue
        if isinstance(settings.get(inp), str) and VAR_REF_RE.match(settings[inp]):
            raise ToolError(f"{mod}.{inp} is already set by a variable")
        if not isinstance(var, str) or not ID_RE.match(var) or var in declared or var in seen_vars:
            raise ToolError(f"invalid or duplicate variable name {var!r}")
        seen_vars.add(var)
        required = p.get("required") is True
        out["promoted"].append({"module": mod, "input": inp, "var": var, "type": info["type"],
                                "def": None if required else settings[inp] if inp in settings
                                else default_value(info), "required": required})

    set_values = changes.get("settings") or []
    if not isinstance(set_values, list) or len(set_values) > _MAX_CHANGES:
        raise ToolError("settings must be a short list")
    for sv in set_values:
        mod, inp = sv.get("module"), sv.get("input")
        if mod not in remaining:
            raise ToolError(f"module {mod!r} is not in {blueprint}")
        source, settings = modules[mod]
        info = input_info(source, inp)
        if info is None or info.get("deprecated"):
            raise ToolError(f"{inp!r} is not a usable input of module {mod!r}")
        ref = VAR_REF_RE.match(settings[inp]) if isinstance(settings.get(inp), str) else None
        if ref:
            raise ToolError(f"{mod}.{inp} is set by variable {ref.group(1)!r}; change that instead")
        if any(p["module"] == mod and p["input"] == inp for p in out["promoted"]):
            raise ToolError(f"{mod}.{inp} is also promoted to a variable")
        check_module_value(f"{mod}.{inp}", info, sv.get("value"), refs, remaining | added_ids)
        out["settings"].append({"module": mod, "input": inp, "value": sv["value"]})

    for a in out["add_modules"]:
        for name, value in a["settings"].items():
            info = input_info(a["source"], name)
            if info is None or info.get("deprecated"):
                raise ToolError(f"{a['id']}: {name!r} is not a usable input of {a['source']}")
            check_module_value(f"{a['id']}.{name}", info, value, refs, remaining | added_ids)
    out["drop_vars"] = _orphaned_vars(blueprint, set(out["remove_modules"]),
                                      [a["settings"] for a in out["add_modules"]] + [s["value"] for s in out["settings"]])
    return out


def _orphaned_vars(blueprint, removed, new_values):
    """Vars that only removed modules use. gcluster rejects unused vars
    (test_deployment_variable_not_used), so the copy must drop them.
    gcluster's globals (region, zone, ...) stay: modules get them by input
    name without a reference."""
    if not removed:
        return []
    doc = yaml.safe_load((REPO_ROOT / blueprint).read_text())
    elsewhere = json.dumps([doc.get("vars") or {}, new_values])
    globals_ = {v["name"] for v in describe(blueprint)["variables"] if v.get("global")}
    return sorted(
        var for var, uses in var_uses(blueprint).items()
        if uses and all(u["module"] in removed for u in uses) and f"$(vars.{var})" not in elsewhere
        and var not in globals_
    )


def has_changes(changes):
    return bool(changes and any(changes.get(k) for k in ("promoted", "add_modules", "remove_modules", "settings")))


def _last_map(m):
    """The mapping holding the last line of a block (ruamel keeps the
    comment lines after a block on that mapping's last key)."""
    while m and isinstance(m[list(m)[-1]], CommentedMap) and m[list(m)[-1]]:
        m = m[list(m)[-1]]
    return m


def _move_trailing_comment(old, new):
    """Keep the comment lines after a replaced block (they usually
    introduce the next module)."""
    src, dst = _last_map(old), _last_map(new)
    if list(src)[-1] in src.ca.items and not isinstance(dst[list(dst)[-1]], (dict, list)):
        dst.ca.items[list(dst)[-1]] = src.ca.items.pop(list(src)[-1])


def _drop_key(m, key):
    """Remove key with the comment lines above it. ruamel keeps those on the
    previous key (after its end-of-line comment), and the lines after key,
    which introduce the next one, on key itself: they move to the previous
    key, which keeps its own end-of-line comment."""
    if key not in m:
        return
    keys = list(m)
    i = keys.index(key)
    after = m.ca.items.pop(key, None)
    if i > 0:
        prev = keys[i - 1]
        token = (m.ca.items.get(prev) or [None, None, None, None])[2]
        eol = token.value.split("\n", 1)[0] if token and not token.value.startswith("\n") else ""
        lines = after[2].value if after and after[2] else "\n"
        if eol or after:
            entry = m.ca.items.setdefault(prev, [None, None, None, None])
            entry[2] = CommentToken(eol + (lines if lines.startswith("\n") else "\n" + lines.split("\n", 1)[-1]),
                                    token.start_mark if eol else CommentMark(0), None)
        elif prev in m.ca.items:
            m.ca.items.pop(prev)
    del m[key]


def _block(a):
    """YAML block for an added module."""
    block = CommentedMap([("id", a["id"]), ("source", a["source"])])
    if a["use"]:
        block["use"] = CommentedSeq(a["use"])
        block["use"].fa.set_flow_style()
    if a["settings"]:
        block["settings"] = CommentedMap(a["settings"])
    return block


def _ruamel():
    y = YAML()  # round-trip: keeps comments and layout of the template
    y.preserve_quotes = True
    y.width = 4096
    return y


def blueprint_copy(blueprint, changes):
    """Text of an ai_assisted copy of the template with changes applied
    (comments preserved). The tracked template is never modified."""
    catalog.check_blueprint(blueprint)
    changes = check_changes(blueprint, changes)
    y = _ruamel()
    text = (REPO_ROOT / blueprint).read_text()
    # ruamel drops comments before the document marker (the licence header).
    prefix = re.match(r"(?:[ \t]*(?:#[^\n]*)?\n)*---[ \t]*\n(?:[ \t]*\n)*", text)
    prefix = prefix.group(0) if prefix else ""
    doc = y.load(text[len(prefix):])
    keys = list(doc.keys())
    doc.insert(keys.index("blueprint_name") + 1 if "blueprint_name" in keys else 0, "ai_assisted", True)

    for var in changes["drop_vars"]:
        _drop_key(doc.get("vars") or CommentedMap(), var)  # some are declared only by the example deployment file
    for p in changes["promoted"]:
        if not p.get("link"):  # a linked var is already declared
            doc.setdefault("vars", CommentedMap())[p["var"]] = p["def"]
            doc["vars"].yaml_add_eol_comment(f"added: {p['module']}.{p['input']}", p["var"])
    groups = doc.get("deployment_groups") or []
    all_mods = [m for g in groups for m in g.get("modules") or []]
    for p in changes["promoted"]:
        for m in all_mods:
            if m["id"] == p["module"]:
                if m.get("settings") is None:
                    m["settings"] = CommentedMap()
                m["settings"][p["input"]] = f"$(vars.{p['var']})"
    for sv in changes["settings"]:
        for m in all_mods:
            if m["id"] == sv["module"]:
                if m.get("settings") is None:
                    m["settings"] = CommentedMap()
                m["settings"][sv["input"]] = sv["value"]

    removed = set(changes["remove_modules"])
    replaced = {a["id"]: _block(a) for a in changes["add_modules"] if a["id"] in removed}
    for g in groups:
        mods = g.get("modules") or []
        for i in reversed(range(len(mods))):
            if mods[i]["id"] in replaced:
                old, new = mods[i], replaced[mods[i]["id"]]  # same place; its users keep it
                _move_trailing_comment(old, new)
                mods[i] = new
            elif mods[i]["id"] in removed:
                del mods[i]
    for m in all_mods:
        if m.get("use"):
            for i in reversed(range(len(m["use"]))):
                if m["use"][i] in removed and m["use"][i] not in replaced:
                    del m["use"][i]

    for a in changes["add_modules"]:
        if a["id"] in replaced:
            continue
        block = _block(a)
        # Before its first consumer (same group), else at the end of the first
        # cluster group: not in groups that only build the custom image.
        cluster_groups = {s["group"] for s in stages(blueprint) if s["role"] == "cluster"}
        target = next((g for g in groups if g["group"] in cluster_groups), groups[0] if groups else None)
        pos = None
        for g in groups:
            ids = [m["id"] for m in g.get("modules") or []]
            hit = next((ids.index(u) for u in a["used_by"] if u in ids), None)
            if hit is not None:
                target, pos = g, hit
                break
        mods = target["modules"]
        mods.insert(len(mods) if pos is None else pos, block)
        for m in [m for g in groups for m in g.get("modules") or []]:
            if m["id"] in a["used_by"]:
                if m.get("use") is None:
                    m["use"] = CommentedSeq()
                    m["use"].fa.set_flow_style()
                if a["id"] not in m["use"]:
                    m["use"].append(a["id"])
    buf = io.StringIO()
    y.dump(doc, buf)
    return prefix + buf.getvalue()
