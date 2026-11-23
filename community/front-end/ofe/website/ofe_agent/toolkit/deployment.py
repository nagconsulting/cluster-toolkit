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

"""deployment.yaml for a configuration, and validating it with
`gcluster expand`."""

import json
import os
import tempfile
from pathlib import Path

import yaml

from . import catalog, gcluster
from .blueprint import generated_names, generated_value, input_info, template
from .changes import blueprint_copy, check_changes, has_changes
from .errors import ToolError
from .gcluster import describe, module_explain
from .paths import REPO_ROOT
from .values import NAME_RE, check_input_value, check_value, default_value

# Set by the server, never by the model or the page.
SERVER_VARS = {"project_id"}


def missing_required(blueprint, overrides, changes=None):
    """Values gcluster would reject as missing: template vars with no default
    (explain `required`) and inputs promoted as required left unset, and
    required inputs of added modules (explain `required_inputs` already
    excludes ones `use:` can provide). project_id is set by the server."""
    dropped = set((changes or {}).get("drop_vars") or []) | set(generated_names(blueprint))
    missing = [
        v["name"] for v in describe(blueprint)["variables"]
        if v.get("required") and v["name"] not in SERVER_VARS and v["name"] not in overrides
        and v["name"] not in dropped
    ]
    missing += [p["var"] for p in (changes or {}).get("promoted") or []
                if p.get("required") and p["var"] not in overrides]
    for a in (changes or {}).get("add_modules") or []:
        ex = module_explain(a["source"]) or {}
        missing += [f"{a['id']}.{i['name']}" for i in ex.get("required_inputs") or []
                    if i["name"] not in (a.get("settings") or {})]
    return missing


def build_deployment(blueprint, overrides, project_id, changes=None, notes=None):
    """Validate overrides against the blueprint's declared vars plus any
    promoted inputs. Returns the deployment.yaml content as a dict.

    With a notes list, harmless mistakes (setting a server var, a var the
    removed modules used, or a var to its default) are fixed by dropping the
    override and explained in notes instead of being rejected."""
    catalog.check_blueprint(blueprint)
    if not isinstance(overrides, dict):
        raise ToolError("overrides must be an object")
    changes = check_changes(blueprint, changes)
    variables = {v["name"]: v for v in describe(blueprint)["variables"]}
    for p in changes["promoted"]:
        if not p.get("link"):
            variables[p["var"]] = {"name": p["var"], "type": p["type"], "default": json.dumps(p["def"])}

    def drop(name, why):
        if notes is None:
            raise ToolError(f"{name!r} {why}; omit it")
        notes.append(f"dropped {name!r}: {why}")
        del overrides[name]

    overrides = dict(overrides)
    for name, value in list(overrides.items()):
        if name in SERVER_VARS:
            drop(name, "is set by the server")
            continue
        if name in changes["drop_vars"]:
            drop(name, "is only used by removed modules and is dropped from the copy")
            continue
        if name not in variables:
            raise ToolError(
                f"{name!r} is not a var of {blueprint}; to change a module"
                " input the template does not expose, promote it in changes"
            )
        check_value(name, variables[name]["type"], value)
        if default_value(variables[name]) == value:
            drop(name, f"is already {value!r} by default")
    for p in changes["promoted"]:
        if p["var"] in overrides:
            check_input_value(p["var"], input_info(template(blueprint)[p["module"]][0], p["input"]),
                              overrides[p["var"]])
    if "deployment_name" in overrides and not NAME_RE.match(
        overrides["deployment_name"]
    ):
        raise ToolError("deployment_name must be lowercase letters, digits, - or _ and start with a letter")
    return {
        "ai_assisted": True,
        "vars": {"project_id": project_id, **implied_vars(blueprint, changes, overrides), **overrides},
    }


def implied_vars(blueprint, changes, overrides):
    """deployment.yaml values OFE sets besides the user's overrides, so the
    file holds every runtime value and the blueprint (or its copy) keeps its
    own defaults: gcluster's globals (deployment_name, region, zone, ...)
    with their effective values, vars only the example deployment file sets
    (deployment_defaults) and generated network names (generated_names).
    builder.html deploymentText shows the same. Only overrides'
    deployment_name is used (for the generated names)."""
    dropped = set((changes or {}).get("drop_vars") or [])
    variables = describe(blueprint)["variables"]
    out = {v["name"]: default_value(v) for v in variables
           if v.get("global") and v["name"] not in SERVER_VARS and default_value(v) is not None}
    out.update(deployment_defaults(blueprint, changes))
    deployment_name = overrides.get("deployment_name", out.get("deployment_name"))
    out.update({var: generated_value(deployment_name, suffix) for var, suffix in generated_names(blueprint).items()
                if deployment_name and var not in dropped})
    return out


def deployment_defaults(blueprint, changes=None):
    """Values for vars the blueprint leaves to its example deployment file
    (explain lists them, with that file's value as default, but the
    blueprint's vars: does not declare them); gcluster needs them set."""
    declared = yaml.safe_load((REPO_ROOT / blueprint).read_text()).get("vars") or {}
    dropped = set((changes or {}).get("drop_vars") or [])
    return {
        v["name"]: default_value(v) for v in describe(blueprint)["variables"]
        if v["name"] not in declared and v["name"] not in dropped and "default" in v
        and not v.get("global")
    }


def configured_blueprint(blueprint, deployment, changes=None):
    """The blueprint (or its ai_assisted copy) with the deployment's values
    as its vars: what `gcluster expand` would read, available even when
    validation fails (e.g. for ofe_agent.toolkit.capacity)."""
    text = blueprint_copy(blueprint, changes) if has_changes(changes) else (REPO_ROOT / blueprint).read_text()
    doc = yaml.safe_load(text)
    doc["vars"] = {**(doc.get("vars") or {}), **deployment["vars"]}
    return yaml.safe_dump(doc, sort_keys=False)


def validate(blueprint, deployment, credentials_file=None, changes=None):
    """Run `gcluster expand` on the blueprint (or its ai_assisted copy when
    there are changes) plus deployment.

    Missing required vars are reported without running gcluster. The copy is
    written next to the template (hidden, removed afterwards) because
    blueprints reference sibling files with $(ghpc_stage("./...")). Uses the
    default validation level; there is no way to lower it. credentials_file,
    if given, is what validators use to query GCP.
    """
    catalog.check_blueprint(blueprint)
    missing = missing_required(blueprint, deployment["vars"], changes)
    if missing:
        return {"valid": False, "missing": missing, "expanded": None,
                "output": "Missing required values: " + ", ".join(missing)
                + ". The page asks the user for these; gcluster expand runs once they are set."}
    with tempfile.TemporaryDirectory(prefix="ofe-agent-") as tmp:
        target, copy_file = blueprint, None
        if has_changes(changes):
            fd, copy_file = tempfile.mkstemp(
                dir=(REPO_ROOT / blueprint).parent, prefix=".ofe-", suffix="-ai.yaml")
            with os.fdopen(fd, "w") as f:
                f.write(blueprint_copy(blueprint, changes))
            target = copy_file
        try:
            dep_file = Path(tmp) / "deployment.yaml"
            dep_file.write_text(yaml.safe_dump(deployment, sort_keys=False))
            expanded = Path(tmp) / "expanded.yaml"
            code, out, err = gcluster.run(
                "expand", target, "-d", str(dep_file), "-o", str(expanded),
                credentials_file=credentials_file,
            )
            return {
                "valid": code == 0,
                "missing": [],
                "output": (out + err).strip()[-4000:],
                "expanded": expanded.read_text() if code == 0 and expanded.exists() else None,
            }
        finally:
            if copy_file:
                Path(copy_file).unlink(missing_ok=True)
