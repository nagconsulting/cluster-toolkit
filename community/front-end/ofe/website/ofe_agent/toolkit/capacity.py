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

"""Whether an existing subnet suits a configuration.

Room: VMs are counted the way gcluster's quota validator counts them
(pkg/validators/quota.go getModuleCount): a module with a machine_type
runs node_count_static + node_count_dynamic_max VMs, else node_count,
instance_count or vm_count, else one. Each VM takes one address from its
subnet's primary range.

Overlap: the networks the blueprint still creates (e.g. GPU networks for
the VMs' other interfaces) must not use ranges that overlap the existing
subnet, as one VM's interfaces cannot be on overlapping subnets. Their
ranges are the private CIDRs in the settings (else the input defaults) of
the modules `gcluster explain` shows provide networks (network_* outputs).
"""

import ipaddress
import re

import yaml

from .blueprint import creates_network, uses_existing
from .gcluster import module_explain
from .values import default_value

# A whole-value var reference: $(vars.x) in a blueprint, ((var.x)) after `gcluster expand`.
_VAR_RE = re.compile(r"^(?:\$\(vars\.([a-z0-9_]+)\)|\(\(var\.([a-z0-9_]+)\)\))$")
GCP_RESERVED_PER_SUBNET = 4  # network, gateway, second-to-last and broadcast


def _resolver(doc):
    variables = doc.get("vars") or {}

    def value(v):
        """v with var references resolved, at any depth."""
        if isinstance(v, dict):
            return {k: value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [value(x) for x in v]
        m = _VAR_RE.match(v) if isinstance(v, str) else None
        return variables.get(m.group(1) or m.group(2)) if m else v

    return value


def _modules(doc):
    return [m for g in doc.get("deployment_groups") or [] for m in g.get("modules") or []]


def _number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def vms(blueprint_text):
    """Every module that runs VMs: [{"module", "machine_type", "static",
    "dynamic_max", "spot", "machine_type_default"}]. Counted as gcluster's quota validator does, but
    a value the blueprint leaves unset comes from the module's default
    (gcluster explain), e.g. a nodeset's default machine_type. static and
    dynamic_max are None when not a plain value; spot follows quota.go's
    checkSpotSettings (enable_spot_vm, spot, preemptible, provisioning_model).
    Packer modules are left out: their VM only runs while building an image."""
    doc = yaml.safe_load(blueprint_text)
    value = _resolver(doc)
    out = []
    for m in _modules(doc):
        ex = module_explain(m.get("source", "")) or {}
        if ex.get("kind") == "packer":
            continue
        inputs = {i["name"]: i for i in (ex.get("required_inputs") or []) + (ex.get("optional_inputs") or [])}
        s = {k: value(v) for k, v in (m.get("settings") or {}).items()}
        type_is_default = "machine_type" not in s
        s.update({k: default_value(i) for k, i in inputs.items() if k not in s and "default" in i})
        if s.get("machine_type") is None:
            continue
        if "node_count_static" in s or "node_count_dynamic_max" in s:
            static, dynamic = _number(s.get("node_count_static", 0)), _number(s.get("node_count_dynamic_max", 0))
        else:
            key = next((k for k in ("node_count", "instance_count", "vm_count") if k in s), None)
            static, dynamic = (_number(s[key]) if key else 1), 0
        spot = any(s.get(k) is True for k in ("enable_spot_vm", "spot", "preemptible")) or \
            str(s.get("provisioning_model", "")).upper() == "SPOT"
        out.append({"module": m["id"], "machine_type": s["machine_type"], "static": static,
                    "dynamic_max": dynamic, "spot": spot, "machine_type_default": type_is_default})
    return out


def vm_demand(expanded):
    """VMs the blueprint can run at most: {"vms", "unknown": [module ids
    whose count is not a plain value]}."""
    rows = vms(expanded)
    unknown = [r["module"] for r in rows if r["static"] is None or r["dynamic_max"] is None]
    return {"vms": int(sum((r["static"] or 0) + (r["dynamic_max"] or 0) for r in rows if r["module"] not in unknown)),
            "unknown": unknown}


def existing_subnet(expanded):
    """(region, subnetwork name) when the configuration uses an existing
    subnet through a pre-existing-* network module, else None."""
    doc = yaml.safe_load(expanded)
    value = _resolver(doc)
    for m in _modules(doc):
        s = m.get("settings") or {}
        if uses_existing(m.get("source", "")) and s.get("subnetwork_name"):
            region = value(s.get("region")) or (doc.get("vars") or {}).get("region")
            return region, value(s["subnetwork_name"])
    return None


def _cidrs(value):
    """Private IPv4 ranges anywhere in a setting's value."""
    if isinstance(value, dict):
        return [c for v in value.values() for c in _cidrs(v)]
    if isinstance(value, list):
        return [c for v in value for c in _cidrs(v)]
    try:
        net = ipaddress.ip_network(value, strict=False) if isinstance(value, str) and "/" in value else None
    except ValueError:
        return []
    return [net] if net and net.version == 4 and net.is_private else []


def network_ranges(expanded):
    """[(module id, input, range)] for every module that provides networks
    (other than an existing one): the ranges set in its settings or, when it
    sets none, those in its input defaults (e.g. the vpc module's default
    network_address_range, from which its default subnet is carved)."""
    doc = yaml.safe_load(expanded)
    value = _resolver(doc)
    out = []
    for m in _modules(doc):
        if not creates_network(m.get("source", "")):
            continue
        ex = module_explain(m.get("source", "")) or {}
        settings = m.get("settings") or {}
        inputs = (ex.get("required_inputs") or []) + (ex.get("optional_inputs") or [])
        found = [(m["id"], i["name"], str(c)) for i in inputs if i["name"] in settings
                 for c in _cidrs(value(settings[i["name"]]))]
        out += found or [(m["id"], i["name"], str(c)) for i in inputs if i["name"] not in settings
                         for c in _cidrs(default_value(i))]
    return out


def usable_addresses(cidr):
    return ipaddress.ip_network(cidr).num_addresses - GCP_RESERVED_PER_SUBNET


def check(expanded, usage):
    """Room for the configuration in the existing subnet it uses, or None when
    it creates its own network. usage(region, subnet) -> {"cidr", "in_use"}
    or None when the subnet is not found."""
    found = existing_subnet(expanded)
    if not found:
        return None
    region, subnet = found
    demand = vm_demand(expanded)
    info = usage(region, subnet)
    if not info:
        return {"subnet": subnet, "region": region, "found": False, "needed": demand["vms"],
                "unknown": demand["unknown"], "ok": False}
    free = usable_addresses(info["cidr"]) - info["in_use"]
    subnet_range = ipaddress.ip_network(info["cidr"])
    overlaps = [{"module": mid, "input": name, "range": rng} for mid, name, rng in network_ranges(expanded)
                if ipaddress.ip_network(rng).overlaps(subnet_range)]
    return {"subnet": subnet, "region": region, "found": True, "cidr": info["cidr"],
            "usable": usable_addresses(info["cidr"]), "in_use": info["in_use"], "free": free,
            "needed": demand["vms"], "unknown": demand["unknown"], "fits": demand["vms"] <= free,
            "overlaps": overlaps, "ok": demand["vms"] <= free and not overlaps}
