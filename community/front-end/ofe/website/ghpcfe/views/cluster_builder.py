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

"""Gemini-assisted cluster builder (separate from the classic cluster views).

The page is a small client-side app; these views are its JSON API. Every
value the page or the agent proposes is re-checked by ofe_agent.toolkit.
"""

import asyncio
import contextlib
import json
import logging
import re
import tempfile

import yaml
from asgiref.sync import sync_to_async
from django.http import JsonResponse, StreamingHttpResponse
from django.views import View, generic

from ofe_agent.chat import propose
from ofe_agent.prompts import tailor_request
from ofe_agent.rank import rank
from ofe_agent.toolkit import capacity, catalog, stages
from ofe_agent.toolkit.blueprint import blueprint_data, module_data
from ofe_agent.toolkit.changes import blueprint_copy, check_changes, has_changes
from ofe_agent.toolkit.deployment import (build_deployment, configured_blueprint, deployment_defaults,
                                          implied_vars, validate)
from ofe_agent.toolkit.paths import REPO_ROOT
from ofe_agent.toolkit.values import ZONE_RE
from ofe_agent.toolkit.view import clean_text, view_text

from ..cluster_manager import cloud_info, utils
from ..models import Credential, Filesystem, FilesystemImpl, VirtualNetwork, VirtualSubnet
from ..permissions import SuperUserRequiredMixin

logger = logging.getLogger(__name__)

SESSION_KEY = "cluster_builder"
MAX_PROMPT = 4000  # several chosen approaches can be long

EXAMPLE_PROMPTS = [
    "Small Slurm cluster for GROMACS, Spot VMs, at most 4 compute nodes",
    "GPU cluster for training a medium LLM on H100s, with fast shared storage",
    "Cheap Slurm cluster for teaching: a few small CPU nodes and a shared home directory",
    "OpenFOAM CFD runs on up to 16 compute-optimised nodes",
    "High-throughput genomics pipeline with many short single-node jobs",
    "GKE cluster for batch inference on L4 GPUs",
]
REGIONS = ["us-central1", "us-east4", "us-west4", "europe-west1",
           "europe-west4", "asia-southeast1"]
_REGION_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]+$")
_MACHINE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
_prices = {}  # (zone, machine type) -> $/hr or None; the catalog is slow
_READY = ("m", "i")  # cloud_state: running (managed) or imported


class ClusterBuilderView(SuperUserRequiredMixin, generic.TemplateView):
    """The page; loading it starts a new conversation."""

    template_name = "cluster_builder/builder.html"

    def get_context_data(self, **kwargs):
        self.request.session.pop(SESSION_KEY, None)
        context = super().get_context_data(**kwargs)
        context["navtab"] = "cluster"
        context["page_data"] = {
            "credentials": [
                {"id": c.id, "name": c.name, "project": _project_of(c)}
                for c in Credential.objects.all()
            ],
            "examples": EXAMPLE_PROMPTS,
            "regions": REGIONS,
            "subnets": [
                {"id": sn.id, "credential": sn.vpc.cloud_credential_id, "vpc": sn.vpc.name,
                 "source": _origin(sn.vpc), "name": sn.cloud_id, "region": sn.cloud_region,
                 "cidr": sn.cidr}
                for sn in _ready_subnets()
            ],
        }
        return context


def _origin(vpc):
    """How an OFE network came about, for the network pickers."""
    return "Imported" if vpc.cloud_state == "i" else "Created in OFE"


def _ready_subnets():
    """Subnets of running or imported OFE networks, for an existing-network choice."""
    return (VirtualSubnet.objects.filter(cloud_state__in=_READY, vpc__cloud_state__in=_READY)
            .select_related("vpc").order_by("vpc__name", "cloud_region", "cloud_id"))


def _chosen_network(cred, subnet_id):
    """The wizard's existing-network choice, from OFE's records, or None for
    a new network created with the cluster."""
    if subnet_id in (None, ""):
        return None
    sn = _ready_subnets().filter(pk=subnet_id, vpc__cloud_credential=cred).first()
    if not sn:
        raise ValueError("That network is not available for this credential")
    return {"network_name": sn.vpc.cloud_id, "subnetwork_name": sn.cloud_id, "region": sn.cloud_region}


class _ApiView(View):
    """JSON POST endpoint for superusers.

    Async so slow calls (Gemini, gcluster, the billing catalog) run off
    Django's shared sync thread and don't block other requests.
    """

    http_method_names = ["post"]

    async def post(self, request):
        status, data = await sync_to_async(self._run, thread_sensitive=False)(request)
        return JsonResponse(data, status=status)

    def _run(self, request):
        """(HTTP status, JSON data) for the request."""
        if not request.user.is_superuser:
            return 403, {"error": "Superuser access required"}
        try:
            body = json.loads(request.body or b"{}")
            return 200, self.handle(request, body)
        except (ValueError, Credential.DoesNotExist) as err:  # ToolError is a ValueError
            logger.warning("Cluster builder %s rejected: %s", type(self).__name__, err)
            return 400, {"error": str(err)}
        except Exception as err:  # pylint: disable=broad-except
            logger.exception("Cluster builder %s failed", type(self).__name__)
            return 500, {"error": str(err)}

    def handle(self, request, body):
        raise NotImplementedError


def _project_of(cred):
    try:
        return json.loads(cred.detail).get("project_id", "")
    except ValueError:
        return ""


def _state(request):
    return request.session.get(SESSION_KEY, {"history": []})


def _credential(request, body):
    """The conversation's credential: fixed by the first request that names one."""
    state = _state(request)
    cred = Credential.objects.get(pk=state.get("credential_id") or body.get("credential_id"))
    state["credential_id"] = cred.id
    request.session[SESSION_KEY] = state
    return cred


@contextlib.contextmanager
def _credentials_file(cred):
    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:  # 0600
        f.write(cred.detail)
        f.flush()
        yield f.name


def _lookups(cred):
    """The agent's cloud lookups, via the same cached cloud_info queries as
    the classic cluster form, with the conversation's credential."""

    def machine_types(zone):
        # cloud_info gives each type's GPUs as {type: {min_count, max_count}}:
        # built into the machine type when min_count is set (a2, a3, g2, ...),
        # attachable in this zone (0 to max_count, via guest_accelerator) when not.
        # cloud_info lists every accelerator type in the zone as attachable to
        # n1; only GPUs no machine type has built in (and not their "-vws"
        # Virtual Workstation variants, nor TPUs) can be attached.
        found = cloud_info.get_machine_types("GCP", cred.detail, None, zone)
        any_built_in = {a for m in found.values() for a, v in m["accelerators"].items() if v.get("min_count")}

        def attachable_gpu(a):
            return a.startswith("nvidia-") and a.removesuffix("-vws") not in any_built_in

        out = []
        for n, m in sorted(found.items()):
            entry = {"name": n, "vcpus": m["vCPU"], "memory_gb": round(m["memory"] / 1024, 1)}
            built_in = {a: v["max_count"] for a, v in m["accelerators"].items() if v.get("min_count")}
            attachable = {a: v["max_count"] for a, v in m["accelerators"].items()
                          if not v.get("min_count") and attachable_gpu(a)}
            if built_in:
                entry["gpus_built_in"] = built_in
            if attachable:
                entry["gpus_attachable"] = attachable
            out.append(entry)
        return out

    def reservations(zone):
        found = cloud_info.get_vm_reservations("GCP", cred.detail, None, zone)
        return [{"name": r["name"], "status": r["status"],
                 "machine_type": r["instanceProperties"]["machineType"],
                 "vm_count": r["instanceProperties"]["availableCount"],
                 "must_be_named": r["specificReservationRequired"]}
                for r in found.values()]

    def networks():
        return [{"name": n.name, "network_name": n.cloud_id, "source": _origin(n),
                 "subnets": [{"subnetwork_name": s.cloud_id, "region": s.cloud_region, "cidr": s.cidr}
                             for s in n.subnets.filter(cloud_state__in=_READY)]}
                for n in VirtualNetwork.objects.filter(cloud_credential=cred, cloud_state__in=_READY)]

    def filesystems():
        found = (Filesystem.objects.filter(cloud_credential=cred, cloud_state__in=_READY)
                 .exclude(impl_type=FilesystemImpl.BUILT_IN).exclude(hostname_or_ip__isnull=True)
                 .exclude(hostname_or_ip=""))
        return [{"name": f.name, "kind": f.get_impl_type_display(), "fs_type": f.fstype_name,
                 "server_ip": f.hostname_or_ip, "exports": [e.export_name for e in f.exports.all()],
                 "network_name": f.vpc.cloud_id if f.vpc else None,
                 "region": f.cloud_region, "zone": f.cloud_zone}
                for f in found]

    def subnet_usage(region, subnet):
        found = next((s for s in cloud_info.get_subnets("GCP", cred.detail) if s[1] == region and s[2] == subnet), None)
        if not found:
            return None
        return {"cidr": found[3], "in_use": cloud_info.get_subnet_usage("GCP", cred.detail).get((region, subnet), 0)}

    def firewall_rules(network_name):
        return cloud_info.get_firewall_rules("GCP", cred.detail, network_name)

    def prices(zone, machine_types):
        return {mt: _price(cred, zone, mt) for mt in machine_types
                if isinstance(mt, str) and _MACHINE_RE.match(mt)}

    return {"machine_types": machine_types, "reservations": reservations,
            "networks": networks, "filesystems": filesystems, "firewall_rules": firewall_rules,
            "subnet_usage": subnet_usage, "prices": prices}


def _price(cred, zone, machine_type):
    """On-demand $/hr from cloud_info, or None; cached per process."""
    if (zone, machine_type) not in _prices:
        try:
            _prices[(zone, machine_type)] = cloud_info.get_instance_pricing(
                "GCP", cred.detail, zone.rsplit("-", 1)[0], zone, machine_type
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("No price for %s in %s", machine_type, zone, exc_info=True)
            _prices[(zone, machine_type)] = None
    return _prices[(zone, machine_type)]


def _catalog_info(path):
    b = catalog.blueprints().get(path, {})
    img = stages.image(path) if b else None
    return {
        "path": path,
        "scheduler": b.get("scheduler"),
        "description": b.get("description", ""),
        "machine_types": b.get("machine_types", []),
        # The wizard notes that the blueprint builds a custom image first.
        "image": {k: img[k] for k in ("family", "image_only")} if img else None,
    }


def _prompt(body):
    prompt = str(body.get("prompt", "")).strip()[:MAX_PROMPT]
    if not prompt:
        raise ValueError("Enter a prompt")
    return prompt


class RankView(_ApiView):
    """Wizard: one Gemini call ranking catalog blueprints for the workload.
    Body: {prompt, credential_id, preferences?}."""

    def handle(self, request, body):
        prompt = _prompt(body)
        prefs = body.get("preferences") or {}
        notes = []
        if prefs.get("scheduler") in ("slurm", "gke"):
            notes.append(f"scheduler {prefs['scheduler']}")
        cred = _credential(request, body)  # fixes the conversation's credential
        network = _chosen_network(cred, prefs.get("subnet_id"))
        if network:
            prefs["region"] = network["region"]
            notes.append("an existing network (any blueprint's network can be swapped for it)")
        if _REGION_RE.match(str(prefs.get("region", ""))):
            notes.append(f"region {prefs['region']}")
        if notes:
            prompt += "\nPreferences: " + "; ".join(notes) + "."
        state = _state(request)
        state["workload"] = prompt
        state["network"] = network
        request.session[SESSION_KEY] = state
        result = rank(prompt, utils.load_config()["server"]["gcp_project"])
        return {
            "summary": result["summary"],
            "candidates": [
                {**_catalog_info(c["blueprint"]), "score": c["score"], "reason": c["reason"]}
                for c in result["candidates"]
            ],
        }


class ChatView(_ApiView):
    """One builder agent turn. Body: {prompt | initial, credential_id, current?}
    where current = {blueprint, overrides, changes}. initial asks for the
    tailoring proposal right after the wizard (prompt fixed by the server).

    Streams newline-delimited JSON so the page can show each step as it
    happens: {"progress": event} lines (see ofe_agent.chat.propose), then
    {"status": http status, "data": result or {"error"}}.
    """

    progress = None

    async def post(self, request):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        self.progress = lambda event: loop.call_soon_threadsafe(queue.put_nowait, {"progress": event})

        def run():
            status, data = self._run(request)
            loop.call_soon_threadsafe(queue.put_nowait, {"status": status, "data": data})

        async def lines():
            task = asyncio.ensure_future(sync_to_async(run, thread_sensitive=False)())
            while True:
                event = await queue.get()
                yield json.dumps(event) + "\n"
                if "status" in event:
                    break
            await task

        return StreamingHttpResponse(
            lines(), content_type="application/x-ndjson",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},  # nginx: don't buffer
        )

    def handle(self, request, body):
        prompt = tailor_request(_state(request).get("network")) if body.get("initial") else _prompt(body)
        current = body.get("current")
        if not (isinstance(current, dict) and current.get("blueprint") in catalog.blueprints()):
            current = None

        cred = _credential(request, body)
        state = _state(request)
        with _credentials_file(cred) as cred_file:
            result = propose(
                prompt,
                json.loads(cred.detail)["project_id"],
                vertex_project=utils.load_config()["server"]["gcp_project"],
                credentials_file=cred_file,
                history=state["history"],
                workload=state.get("workload"),
                current=current and {
                    "blueprint": current["blueprint"],
                    "overrides": current.get("overrides") or {},
                    "changes": current.get("changes") or {},
                },
                on_progress=self.progress,
                lookups=_lookups(cred),
            )
        state["history"] = result.history
        request.session[SESSION_KEY] = state
        # The session middleware has already run for a streamed response.
        request.session.save()

        options = []
        for option in result.options:
            p = result.proposals[option["proposal"]]
            implied = implied_vars(p["blueprint"], p["changes"], p["deployment"]["vars"])  # not the user's overrides
            options.append({
                "id": option["proposal"],
                "title": option["title"],
                "reason": option["reason"],
                "blueprint": p["blueprint"],
                "overrides": {k: v for k, v in p["deployment"]["vars"].items()
                              if k != "project_id" and not (k in implied and implied[k] == v)},
                "changes": p["changes"],
                "valid": p["validation"]["valid"],
                "missing": p["validation"]["missing"],
                "output": p["validation"]["output"],
                "capacity": p["validation"].get("capacity"),
            })
        return {
            "answer": result.answer,
            "options": options,
            "approaches": result.approaches,
            "question": result.question,
            "choices": result.choices,
            "multi_select": result.multi_select,
            "trace": result.trace,
            "usage": result.usage,
        }


class ResetView(_ApiView):
    def handle(self, request, body):
        request.session.pop(SESSION_KEY, None)
        return {}


class BlueprintView(_ApiView):
    """Form data for a catalog blueprint. Body: {path}."""

    def handle(self, request, body):
        path = str(body.get("path", ""))
        # Shown in the page's deployment.yaml with the user's values (implied_vars).
        return {**blueprint_data(path), "deployment_defaults": deployment_defaults(path)}


class ValidateView(_ApiView):
    """gcluster expand on the user's configuration.
    Body: {blueprint, overrides, changes, credential_id?}."""

    def handle(self, request, body):
        blueprint = str(body.get("blueprint", ""))
        cred = _credential(request, body)
        project = json.loads(cred.detail)["project_id"]
        changes = check_changes(blueprint, body.get("changes"))
        notes = []  # harmless leftovers (e.g. a default restated) are dropped, not rejected
        deployment = build_deployment(blueprint, body.get("overrides") or {}, project, changes, notes)
        with _credentials_file(cred) as cred_file:
            result = validate(blueprint, deployment, cred_file, changes)
        result["capacity"] = capacity.check(configured_blueprint(blueprint, deployment, changes),
                                            _lookups(cred)["subnet_usage"])
        return {
            **result,
            "notes": notes,
            "dropped": [k for k in body.get("overrides") or {} if k not in deployment["vars"]],
            "deployment_yaml": yaml.safe_dump(deployment, sort_keys=False),
            # What the page downloads: the template or its ai_assisted copy, cleaned (view.clean_text).
            "blueprint_yaml": clean_text(blueprint_copy(blueprint, changes) if has_changes(changes)
                                         else (REPO_ROOT / blueprint).read_text()),
        }


class PreviewView(_ApiView):
    """The ai_assisted copy for a set of changes, as the YAML and Changes
    tabs show it (no vars:) and as downloaded. Body: {blueprint, changes}."""

    def handle(self, request, body):
        blueprint = str(body.get("blueprint", ""))
        changes = check_changes(blueprint, body.get("changes"))
        copy = blueprint_copy(blueprint, changes)
        return {"changes": changes, "view_yaml": view_text(copy), "clean_yaml": clean_text(copy)}


class ModuleView(_ApiView):
    """Form data for one module. Body: {source}."""

    def handle(self, request, body):
        return module_data(str(body.get("source", "")))


class ModulesView(_ApiView):
    """Modules that can be added (catalog module_wiring, not deprecated)."""

    def handle(self, request, body):
        return {"modules": catalog.list_modules()}


class ZonesView(_ApiView):
    """Regions and zones the conversation's credential can use, via the
    same cloud_info lookup as the classic cluster form."""

    def handle(self, request, body):
        cred = _credential(request, body)
        info = cloud_info.get_region_zone_info("GCP", cred.detail)
        return {"regions": {r: sorted(z) for r, z in sorted(info.items())}}


class CostView(_ApiView):
    """The configuration's VMs (every module with a machine type, its count
    and Spot, from ofe_agent.toolkit.capacity.vms) and on-demand $/hr per
    machine type via cloud_info. Body: {blueprint, overrides, changes,
    zone, credential_id?}."""

    def handle(self, request, body):
        blueprint = str(body.get("blueprint", ""))
        cred = _credential(request, body)
        changes = check_changes(blueprint, body.get("changes"))
        deployment = build_deployment(blueprint, body.get("overrides") or {}, "project", changes, notes=[])
        rows = capacity.vms(configured_blueprint(blueprint, deployment, changes))
        zone = str(body.get("zone") or "")
        prices = {}
        if ZONE_RE.match(zone):
            prices = {mt: _price(cred, zone, mt) for mt in {r["machine_type"] for r in rows}
                      if isinstance(mt, str) and _MACHINE_RE.match(mt)}
        return {"vms": rows, "prices": prices, "zone": zone if prices else None}
