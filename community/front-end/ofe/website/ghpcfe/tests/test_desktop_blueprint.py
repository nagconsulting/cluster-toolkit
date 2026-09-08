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

"""cluster_config.yaml.j2 renders a valid blueprint for each desktop shape.

These assert on the parsed document rather than on substrings wherever the
structure allows it: the template is whitespace-sensitive YAML built from
conditional blocks, and a misplaced block produces a file that still contains
every expected string while no longer parsing.
"""

import pytest
import yaml

from desktop_test_support import fake_cluster, render_blueprint

NOVNC_RUNTIME_SOURCE = "community/modules/remote-desktop/novnc-runtime"


def modules_by_id(cluster, **overrides):
    """Render the blueprint and return {module id: module} from the parsed YAML.

    Parsing is the assertion that matters most here; every caller gets it.
    """
    rendered = render_blueprint(cluster, **overrides)
    document = yaml.safe_load(rendered)
    modules = document["deployment_groups"][0]["modules"]
    return {module["id"]: module for module in modules if "id" in module}


def desktop_runtimes(modules):
    return {
        module_id: module
        for module_id, module in modules.items()
        if module["source"] == NOVNC_RUNTIME_SOURCE
    }


def test_no_desktop_emits_no_desktop_modules():
    modules = modules_by_id(fake_cluster())

    assert desktop_runtimes(modules) == {}
    assert "web_desktop_firewall" not in modules
    assert "slurm_login" in modules
    # The login timeout is raised only for a desktop; the no-desktop path must
    # stay byte-identical to the pre-desktop blueprint (Verification item 7).
    assert "login_startup_scripts_timeout" not in modules["slurm_controller"]["settings"]


def test_login_desktop_wires_the_login_node():
    modules = modules_by_id(fake_cluster(enable_web_desktop=True))

    assert set(desktop_runtimes(modules)) == {"login_desktop_runtime"}
    settings = modules["login_desktop_runtime"]["settings"]
    assert settings["desktop_endpoint_name"] == "login"
    assert settings["novnc_identity_mode"] == "trusted_proxy"
    assert settings["vnc_backend"] == "tigervnc"

    # The login node runs the desktop, so it needs the firewall target tag and
    # the longer startup timeout, and its startup script becomes the runtime's.
    assert modules["slurm_login"]["settings"]["tags"] == ["ghpc-novnc-desktop"]
    controller_settings = modules["slurm_controller"]["settings"]
    assert controller_settings["login_startup_scripts_timeout"] == 1200
    assert (
        controller_settings["login_startup_script"]
        == "$(login_desktop_startup.startup_script)"
    )


def test_viz_desktop_does_not_disturb_the_login_node():
    modules = modules_by_id(fake_cluster(enable_viz_desktop=True))

    assert set(desktop_runtimes(modules)) == {"viz_desktop_runtime"}
    settings = modules["viz_desktop_runtime"]["settings"]
    assert settings["desktop_endpoint_name"] == "viz"
    assert settings["novnc_identity_mode"] == "trusted_proxy"

    # The visualisation desktop lives in its own partition, so the login node
    # keeps the stock startup script and no desktop tag.
    assert "tags" not in modules["slurm_login"]["settings"]
    assert (
        "login_startup_scripts_timeout"
        not in modules["slurm_controller"]["settings"]
    )


def test_both_desktops_declare_the_identity_mode_once_each():
    modules = modules_by_id(
        fake_cluster(enable_web_desktop=True, enable_viz_desktop=True)
    )
    runtimes = desktop_runtimes(modules)

    assert set(runtimes) == {"login_desktop_runtime", "viz_desktop_runtime"}
    assert [
        module["settings"]["novnc_identity_mode"] for module in runtimes.values()
    ] == ["trusted_proxy", "trusted_proxy"]
    # Distinct endpoint names: they share one endpoint directory on the shared
    # filesystem, so a collision would make the two desktops indistinguishable.
    assert {module["settings"]["desktop_endpoint_name"] for module in runtimes.values()} == {
        "login",
        "viz",
    }


# GPU acceleration needs both a GPU and TurboVNC. Setting it without a GPU
# fails novnc-desktop's precondition, and TigerVNC has no offload path on these
# images at all, so the flag must not appear for either.
@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, False),
        ({"desktop_gpu_type": "nvidia-tesla-t4", "desktop_gpu_count": 1}, True),
        (
            {
                "desktop_gpu_type": "nvidia-tesla-t4",
                "desktop_gpu_count": 1,
                "viz_desktop_vnc_backend": "tigervnc",
            },
            False,
        ),
        # G2 and the A-families carry their GPU in the machine type rather than
        # in guest_accelerator, so desktop_gpu_type stays empty.
        ({"desktop_instance_type": "g2-standard-8"}, True),
        (
            {
                "desktop_instance_type": "g2-standard-8",
                "viz_desktop_vnc_backend": "tigervnc",
            },
            False,
        ),
    ],
)
def test_gpu_acceleration_needs_a_gpu_and_turbovnc(overrides, expected):
    modules = modules_by_id(fake_cluster(enable_viz_desktop=True, **overrides))
    settings = modules["viz_desktop_runtime"]["settings"]

    assert settings.get("enable_gpu_acceleration", False) is expected


def test_the_firewall_rule_is_scoped_to_the_supplied_cidrs():
    modules = modules_by_id(
        fake_cluster(enable_viz_desktop=True),
        desktop_allowed_ingress_cidrs=["10.2.0.0/28"],
    )

    rule = modules["web_desktop_firewall"]["settings"]["ingress_rules"][0]
    assert rule["source_ranges"] == ["10.2.0.0/28"]
    assert rule["target_tags"] == ["ghpc-novnc-desktop"]
    assert rule["allow"] == [{"protocol": "tcp", "ports": ["6080"]}]


def test_zero_login_nodes_omits_the_login_module():
    """The viz desktop is a Slurm client on its own, so the cluster does not
    need a login node - and the controller must not reference a module that
    was never emitted."""
    modules = modules_by_id(
        fake_cluster(enable_viz_desktop=True, num_login_nodes=0)
    )

    assert "slurm_login" not in modules
    controller_settings = modules["slurm_controller"]["settings"]
    assert "login_startup_script" not in controller_settings
    assert "login_startup_scripts_timeout" not in controller_settings


def test_one_login_node_still_renders_the_login_module():
    modules = modules_by_id(fake_cluster(num_login_nodes=1))

    assert modules["slurm_login"]["settings"]["num_instances"] == 1
    assert (
        "login_startup_script"
        in modules["slurm_controller"]["settings"]
    )
