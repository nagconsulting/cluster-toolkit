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

"""Builder step: a tool-using Gemini chat turn that proposes a validated
configuration. The tools are thin wrappers over ofe_agent.toolkit, which
enforces every rule."""

import json
import logging
import re
from dataclasses import dataclass, field

from google.genai import types

from . import gemini
from .prompts import CHAT_INSTRUCTION, skill_rules
from .toolkit import capacity, catalog
from .toolkit.blueprint import input_info, module_docs, summary, template
from .toolkit.changes import check_changes
from .toolkit.deployment import build_deployment, configured_blueprint, validate
from .toolkit.errors import ToolError
from .toolkit.gcluster import describe as explain_describe
from .toolkit.gcluster import find_blueprints as explain_find
from .toolkit.values import VAR_REF_RE, ZONE_RE

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 15  # model steps that call tools; then it must answer
MAX_OPTIONS = 3
MAX_APPROACHES = 5
MAX_CHOICES = 4
MAX_LISTED = 60  # machine types per list_machine_types call
_NETWORK_NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
# gcluster output when a zone/machine type is unavailable: the named
# validators, or the machine type lookup during expansion.
_LOCATION_FAILURE_RE = re.compile(
    r"test_machine_type_in_zone|test_zone_in_region|failed to get machine type info"
)


@dataclass
class Result:
    answer: str
    # Serialised chat history; pass back to propose() to continue the chat.
    history: list = field(default_factory=list)
    # proposal id -> {"blueprint", "deployment", "changes", "validation"},
    # one per propose_deployment call.
    proposals: dict = field(default_factory=dict)
    # What the user can choose between: [{"proposal", "title", "reason"}],
    # each a distinct approach (up to MAX_OPTIONS).
    options: list = field(default_factory=list)
    # Approaches described in text only (nothing built yet), for the user to
    # pick from; the next turn builds the chosen ones together:
    # [{"title", "description", "group"}]. Approaches with the same non-empty
    # group replace each other (pick one); the rest combine freely.
    approaches: list = field(default_factory=list)
    # A decision the agent needs from the user, if any, with short answers
    # to offer as buttons (e.g. ["Yes", "No"]); empty choices = free text.
    question: str = ""
    choices: list = field(default_factory=list)
    multi_select: bool = False  # the user may pick several choices
    trace: list = field(default_factory=list)
    # Gemini calls, tokens and time for the turn (also logged).
    usage: dict = field(default_factory=dict)


def _for_model(explained):
    """explain output without what the agent does not use: commands, APIs,
    and long descriptions."""
    out = {k: v for k, v in explained.items()
           if k not in ("required_apis", "gcloud_enable_command", "deploy_command", "snippet")}
    for key in ("required_inputs", "optional_inputs"):
        if key in out:
            out[key] = [
                {**i, "description": (i.get("description") or "")[:200]}
                for i in out[key]
            ]
    return out


class _Session:
    """Tool functions handed to Gemini, recording every call."""

    def __init__(self, project_id, credentials_file, on_progress=None, lookups=None):
        self.project_id = project_id
        self.credentials_file = credentials_file
        self.lookups = lookups or {}
        self.result = Result(answer="")
        self.progress = on_progress or (lambda event: None)

    def _call(self, name, fn, **kwargs):
        self.progress({"running": {"tool": name, "args": kwargs}})
        try:
            out = fn()
        except (ToolError, json.JSONDecodeError) as e:
            out = {"error": str(e)}
        step = {"tool": name, "args": kwargs, "error": None, "notes": []}
        if isinstance(out, dict):
            step["error"], step["notes"] = out.get("error"), out.get("notes") or []
        self.result.trace.append(step)
        self.progress({"step": step})
        return out

    def functions(self):
        def list_blueprints() -> list:
            """List every catalog blueprint with path, scheduler, description,
            machine types and module names."""
            return self._call("list_blueprints", catalog.list_blueprints)

        def find_blueprints(specs: list[str]) -> dict:
            """Find the closest blueprint for short lowercase keyword specs,
            e.g. ["slurm", "a3-megagpu", "lustre"]."""
            return self._call(
                "find_blueprints", lambda: explain_find(specs),
                specs=specs,
            )

        def describe(path: str) -> dict:
            """Describe a catalog blueprint (vars with what they feed, and
            modules with settings; the current one is already in
            <blueprint_summary>) or a module under modules/ or
            community/modules/ (inputs with validations)."""

            def run():
                if path in catalog.blueprints():
                    return summary(path)
                return _for_model(explain_describe(path))

            return self._call("describe", run, path=path)

        def read_module_docs(path: str) -> dict:
            """A module's README (under modules/ or community/modules/):
            what it is for, when to use it or a related module instead,
            examples and how users reach what it creates. describe gives its
            inputs; read this when explaining a module or choosing how to
            add it."""
            return self._call("read_module_docs", lambda: {"module": path, "readme": module_docs(path)}, path=path)

        def list_modules() -> list:
            """List modules from the catalog's module_wiring with their
            required_inputs, recommended_use and consumed_by."""
            return self._call("list_modules", catalog.list_modules)

        def propose_deployment(blueprint: str, overrides_json: str, changes_json: str) -> dict:
            """Build deployment.yaml (and, with changes, an ai_assisted copy
            of the template) and validate with gcluster expand.
            overrides_json: JSON object of declared var names to values, e.g.
            {"compute_enable_spot_vm": true}.
            changes_json: JSON object, "{}" for none, with optional
            "add_modules": [{"id", "source", "use": [ids], "used_by": [ids],
            "settings": {input: value}}], "remove_modules": [ids] and
            "set_inputs": [{"module", "input", "value"}] for inputs of
            existing modules the template does not expose as vars; leave
            out "value" when only the user knows it (e.g. their reservation
            name) and the page asks them for it as a required field. A list
            or object value (e.g. guest_accelerator: [{"type":
            "nvidia-tesla-t4", "count": 1}]) is set on the module as is,
            checked against the input's type from describe; so is a
            reference to another module's output ("$(<module>.<output>)") or
            concat/flatten/merge over such references and vars (e.g.
            "$(flatten([a.runners, b.runners]))"), the only expressions
            allowed. Settings of modules you add may use them too.
            `use` is not an input: wire a module with "use"/"used_by" on
            the module you add (existing modules' use lists change only
            through that)."""

            def run():
                overrides = json.loads(overrides_json or "{}")
                changes = json.loads(changes_json or "{}")
                if not isinstance(overrides, dict) or not isinstance(changes, dict):
                    raise ToolError("overrides_json and changes_json must be objects")
                notes = []
                # set_inputs -> promoted vars + overrides, as the form does;
                # an input a var already sets is changed through that var.
                promoted = []
                added = {a.get("id"): a for a in changes.get("add_modules") or [] if isinstance(a, dict)}
                for s in changes.pop("set_inputs", None) or []:
                    mod, inp = s.get("module"), s.get("input")
                    if inp == "use":  # wiring, not an input: the added module's used_by
                        refs = s.get("value") if isinstance(s.get("value"), list) else []
                        if not refs or any(r not in added for r in refs):
                            raise ToolError(f"`use` is not an input. {mod} can be wired only to modules you add:"
                                            f" put {mod!r} in their used_by")
                        for r in refs:
                            added[r].setdefault("used_by", [])
                            if mod not in added[r]["used_by"]:
                                added[r]["used_by"].append(mod)
                        notes.append(f"{mod}.use is wiring, not an input: added {mod!r} to used_by of {refs}")
                        continue
                    current = template(blueprint).get(mod, (None, {}))[1].get(inp)
                    ref = VAR_REF_RE.match(current) if isinstance(current, str) else None
                    if ref and "value" not in s:
                        notes.append(f"{mod}.{inp} is already a form field (var {ref.group(1)!r})")
                        continue
                    if ref:
                        notes.append(f"{mod}.{inp} is set by var {ref.group(1)!r}; overrode that instead")
                        overrides[ref.group(1)] = s["value"]
                        continue
                    if isinstance(s.get("value"), (list, dict)) or (  # set on the module as is: structured,
                            isinstance(s.get("value"), str) and s["value"].startswith("$(")  # or referencing modules
                            and not VAR_REF_RE.match(s["value"])):
                        changes.setdefault("settings", []).append({"module": mod, "input": inp, "value": s["value"]})
                        continue
                    var = re.sub(r"[^a-z0-9_]", "_", f"{mod}_{inp}")  # module ids may have hyphens
                    if "value" not in s or s["value"] is None:
                        promoted.append({"module": mod, "input": inp, "var": var, "required": True})
                        continue
                    promoted.append({"module": mod, "input": inp, "var": var})
                    overrides[var] = s["value"]
                changes["promoted"] = promoted + (changes.get("promoted") or [])
                normalised = check_changes(blueprint, changes)
                dep = build_deployment(blueprint, overrides, self.project_id, normalised, notes)
                validation = validate(blueprint, dep, self.credentials_file, normalised)
                if "subnet_usage" in self.lookups:
                    validation["capacity"] = capacity.check(
                        configured_blueprint(blueprint, dep, normalised), self.lookups["subnet_usage"])
                del validation["expanded"]  # too large to send to the model
                proposal_id = f"p{len(self.result.proposals) + 1}"
                self.result.proposals[proposal_id] = {
                    "blueprint": blueprint, "deployment": dep, "changes": normalised,
                    "validation": validation,
                }
                out = {"proposal_id": proposal_id, **validation, "deployment": dep}
                if notes:
                    out["notes"] = notes  # mistakes fixed for the model, so it learns
                if normalised["remove_modules"]:
                    # What the removed modules provided, so a replacement can keep it.
                    out["removed_module_settings"] = {
                        mid: template(blueprint)[mid][1] for mid in normalised["remove_modules"]
                    }
                    # Settings of a replaced module its replacement has no input for.
                    lost = {a["id"]: [k for k in template(blueprint)[a["id"]][1]
                                      if input_info(a["source"], k) is None]
                            for a in normalised["add_modules"] if a["id"] in normalised["remove_modules"]}
                    if any(lost.values()):
                        out["replaced_settings_not_carried_over"] = {k: v for k, v in lost.items() if v}
                    # A network replaced by an existing one: its firewall rules are that network's.
                    if any(a["id"] in normalised["remove_modules"] and a["source"].startswith("modules/network/")
                           for a in normalised["add_modules"]):
                        out.setdefault("next_step", (
                            "The cluster now uses an existing network, so only that network's firewall"
                            " rules apply" + (" (list_firewall_rules shows them)" if "firewall_rules" in self.lookups
                                              else "") + ". If its services need traffic those rules do not"
                            " allow (e.g. Managed Lustre: tcp 988 from the private service access range;"
                            " internal traffic; IAP SSH), add modules/network/firewall-rules with use:"
                            " [<network id>] and those rules, named $(vars.deployment_name)-<purpose>."))
                if _LOCATION_FAILURE_RE.search(validation["output"]):
                    out["next_step"] = (
                        "A zone or machine type check failed. Do not guess another zone or"
                        " machine type and do not offer this proposal: call ask_user for a"
                        " supported zone or machine type (SKILL.md rule 5)"
                        + (", with choices from list_machine_types for the zone."
                           if "machine_types" in self.lookups else ".")
                    )
                elif (validation.get("capacity") or {}).get("overlaps"):
                    out["next_step"] = (
                        "Networks this blueprint still creates use ranges that overlap the existing subnet"
                        f" {validation['capacity']['cidr']} (capacity.overlaps); a VM's interfaces cannot be on"
                        " overlapping subnets. Change each listed module input to a private range that overlaps"
                        " neither that subnet nor the other networks (set_inputs for a module setting, or the var"
                        " that sets it), and propose again.")
                elif validation.get("capacity") and not validation["capacity"]["ok"]:
                    out["next_step"] = (
                        "The existing subnet does not have enough free addresses for this cluster's maximum"
                        " size (capacity: needed vs free). Offer this proposal only with that caveat in the"
                        " reason, or reduce node counts, or ask the user to choose or create a larger subnet.")
                elif validation["missing"]:
                    out["next_step"] = (
                        "Only values the form collects are missing. Do not retry to fill"
                        " them; offer this proposal with offer_option (unless it is wrong)."
                    )
                return out

            return self._call(
                "propose_deployment", run,
                blueprint=blueprint, overrides=overrides_json, changes=changes_json,
            )

        def offer_option(proposal_id: str, title: str, reason: str) -> dict:
            """Offer a proposal from this turn to the user as one option they
            can accept. title: a few words naming the approach (e.g. "Shrink
            the Filestore"); reason: one sentence on the trade-off. Offer up
            to three distinct approaches; best first."""

            def run():
                if proposal_id not in self.result.proposals:
                    raise ToolError(f"{proposal_id!r} is not a proposal from this turn")
                if any(o["proposal"] == proposal_id for o in self.result.options):
                    raise ToolError(f"{proposal_id!r} is already offered")
                if len(self.result.options) >= MAX_OPTIONS:
                    raise ToolError(f"at most {MAX_OPTIONS} options")
                self.result.options.append(
                    {"proposal": proposal_id, "title": title[:80], "reason": reason[:500]}
                )
                return {"offered": proposal_id}

            return self._call("offer_option", run, proposal_id=proposal_id, title=title)

        def offer_approach(title: str, description: str, exclusive_group: str) -> dict:
            """Describe one way to meet the request, without building it.
            The user ticks the ones they want and the next turn builds those
            together. title: a few words (e.g. "Replace with a VM-based NFS
            server"); description: one sentence on what changes and the
            trade-off. exclusive_group: the same short word for approaches
            that replace each other, so only one can be picked (e.g.
            "storage" for a smaller Filestore vs an NFS server); "" for one
            that combines with any other (e.g. fewer nodes). Up to five;
            best first."""

            def run():
                if len(self.result.approaches) >= MAX_APPROACHES:
                    raise ToolError(f"at most {MAX_APPROACHES} approaches")
                self.result.approaches.append({"title": title[:80], "description": description[:500],
                                               "group": str(exclusive_group or "").strip()[:30]})
                return {"offered": title}

            return self._call("offer_approach", run, title=title, group=exclusive_group)

        def ask_user(question: str, choices: list[str], multi_select: bool) -> dict:
            """Ask the user one question about a decision you cannot make,
            with up to four short answers (e.g. ["Yes", "No"] or the
            alternatives), or [] for a free-text answer. multi_select: true
            when several answers can apply together (e.g. which partitions
            to keep), false when they exclude each other. Do not ask for
            values the form collects."""

            def run():
                self.result.question = question[:500]
                self.result.choices = [str(c)[:60] for c in (choices or [])][:MAX_CHOICES]
                self.result.multi_select = bool(multi_select) and len(self.result.choices) > 1
                return {"asked": True}

            return self._call("ask_user", run)

        def list_machine_types(zone: str, prefix: str) -> dict:
            """Machine types the user's project can use in a zone, with
            vCPUs, memory and GPUs: gpus_built_in come with the machine type
            (e.g. a2, a3, g2); gpus_attachable can be added to it, up to the
            count given, with the compute module's guest_accelerator setting.
            prefix filters by name, e.g. "n1-" or "a3-"; "" lists all
            (truncated). Use it for any question about GPUs."""

            def run():
                if not ZONE_RE.match(zone):
                    raise ToolError(f"invalid zone {zone!r}")
                found = [m for m in self.lookups["machine_types"](zone) if m["name"].startswith(prefix)]
                return {"zone": zone, "machine_types": found[:MAX_LISTED], "truncated": len(found) > MAX_LISTED}

            return self._call("list_machine_types", run, zone=zone, prefix=prefix)

        def list_reservations(zone: str) -> dict:
            """The user's VM reservations in a zone: name, machine type,
            VM count, and whether VMs must name it to use it."""

            def run():
                if not ZONE_RE.match(zone):
                    raise ToolError(f"invalid zone {zone!r}")
                return {"zone": zone, "reservations": self.lookups["reservations"](zone)}

            return self._call("list_reservations", run, zone=zone)

        def list_networks() -> dict:
            """Networks (VPCs) OFE manages or has imported for the user's
            credential, with their subnets and regions, ready to use with
            modules/network/pre-existing-vpc."""
            return self._call("list_networks", lambda: {"networks": self.lookups["networks"]()})

        def list_filesystems() -> dict:
            """Filesystems OFE manages or has imported for the user's
            credential (server, exports, type, network), ready to mount with
            modules/file-system/pre-existing-network-storage."""
            return self._call("list_filesystems", lambda: {"filesystems": self.lookups["filesystems"]()})

        def list_firewall_rules(network_name: str) -> dict:
            """Every VPC firewall rule on a network (from list_networks),
            whoever created it: direction, allow/deny, protocols and ports,
            source/destination ranges, target tags."""

            def run():
                if not _NETWORK_NAME_RE.match(network_name):
                    raise ToolError(f"invalid network name {network_name!r}")
                return {"network": network_name, "rules": self.lookups["firewall_rules"](network_name)}

            return self._call("list_firewall_rules", run, network_name=network_name)

        def machine_prices(zone: str, machine_types: list[str]) -> dict:
            """On-demand $/hour per VM for up to 10 machine types in a zone
            (null when unknown), to compare the cost of options."""

            def run():
                if not ZONE_RE.match(zone):
                    raise ToolError(f"invalid zone {zone!r}")
                return {"zone": zone, "usd_per_hour": self.lookups["prices"](zone, machine_types[:10])}

            return self._call("machine_prices", run, zone=zone, machine_types=machine_types)

        tools = [
            list_blueprints, find_blueprints, describe, read_module_docs, list_modules,
            propose_deployment, offer_option, offer_approach, ask_user,
        ]
        # Lookups the caller (OFE) provides with the user's credential.
        optional = {"machine_types": list_machine_types, "reservations": list_reservations,
                    "networks": list_networks, "filesystems": list_filesystems,
                    "firewall_rules": list_firewall_rules, "prices": machine_prices}
        return tools + [f for name, f in optional.items() if name in self.lookups]


def _context(history, current, workload):
    """Data sent ahead of the request: the workload on the first turn, the
    configuration being edited, and a summary of its blueprint the first
    time that blueprint comes up (so the agent can skip describe)."""
    context = ""
    if workload and not history:
        context += f"<workload>\n{workload}\n</workload>\n"
    if current:
        tag = f"<blueprint_summary for={current['blueprint']}>"
        if tag not in json.dumps(history or []):
            context += f"{tag}\n{json.dumps(summary(current['blueprint']))}\n</blueprint_summary>\n"
        context += f"<current_configuration>\n{json.dumps(current)}\n</current_configuration>\n"
    return context


def _respond(tools, calls):
    """Run the model's function calls; the parts that answer them."""
    by_name = {f.__name__: f for f in tools}
    parts = []
    for call in calls:
        fn = by_name.get(call.name)
        try:
            out = fn(**(call.args or {})) if fn else {"error": f"no tool {call.name!r}"}
        except TypeError as err:  # wrong arguments
            out = {"error": str(err)}
        parts.append(types.Part.from_function_response(name=call.name, response={"result": out}))
    return parts


def propose(
    prompt,
    project_id,
    *,
    vertex_project=None,
    credentials_file=None,
    history=None,
    current=None,
    workload=None,
    model=gemini.DEFAULT_MODEL,
    on_progress=None,
    lookups=None,
):
    """Run one user turn.

    project_id is the deployment target; vertex_project (default: the same)
    pays for Gemini using ambient credentials. credentials_file, if given, is
    what gcluster validators use for the target project. current, if given,
    is the configuration the user is editing:
    {"blueprint": path, "overrides": {...}, "changes": {...}}. workload is
    the original description from the wizard. on_progress, if given, is
    called with {"thinking": n} before each Gemini call, and {"running":
    step} / {"step": step} around each tool call. lookups, if given, adds
    tools backed by the caller's cloud and OFE queries: {"machine_types":
    fn(zone), "reservations": fn(zone), "networks": fn(), "filesystems":
    fn(), "firewall_rules": fn(network_name), "prices": fn(zone, machine_types)},
    each returning plain JSON.

    The tool loop is run here rather than by the SDK so each step can be
    reported as it happens and every call's token usage counted.
    """
    session = _Session(project_id, credentials_file, on_progress, lookups)
    usage = gemini.Usage()
    tools = session.functions()
    client = gemini.client(vertex_project or project_id)
    config = types.GenerateContentConfig(
        system_instruction=CHAT_INSTRUCTION + skill_rules(),
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=gemini.CHAT_THINKING),
    )
    contents = [types.Content.model_validate(c) for c in history or []]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(
        text=f"{_context(history, current, workload)}<user_request>\n{prompt}\n</user_request>")]))
    for rounds in range(MAX_TOOL_ROUNDS + 1):
        if rounds == MAX_TOOL_ROUNDS:  # out of steps: answer with what there is
            config = config.model_copy(update={"tool_config": types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE"))})
        session.progress({"thinking": rounds + 1})
        response = client.models.generate_content(model=model, contents=contents, config=config)
        usage.add(response)
        if not response.candidates or not response.candidates[0].content:
            break
        contents.append(response.candidates[0].content)
        if not response.function_calls:
            break
        contents.append(types.Content(role="user", parts=_respond(tools, response.function_calls)))

    result = session.result
    result.answer = response.text or ""
    result.history = [c.model_dump(mode="json", exclude_none=True) for c in contents]
    result.usage = usage.as_dict(
        model=model, tool_calls=len(result.trace),
        tool_errors=sum(bool(t["error"]) for t in result.trace),
        fixes=sum(len(t["notes"]) for t in result.trace),
        proposals=len(result.proposals), options=len(result.options),
        approaches=len(result.approaches))
    logger.info("ofe_agent turn: %s", json.dumps(result.usage))
    for step in result.trace:  # what went wrong or was fixed, for tuning the tools and prompt
        if step["error"] or step["notes"]:
            logger.info("ofe_agent step: %s %s", step["tool"],
                        json.dumps({"args": {k: str(v)[:300] for k, v in step["args"].items()},
                                    "error": step["error"], "notes": step["notes"]}))
    return result
