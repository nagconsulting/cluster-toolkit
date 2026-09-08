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

"""ClusterForm rejects the desktop combinations that cannot be deployed.

Each of these is a combination Terraform or Slurm would accept and then fail
on, or silently mis-serve, so the form is the only place it is caught. The
assertion is on the field the error is attached to, not on the message: an
error on the wrong field never reaches the user's eye on the form.
"""

import pytest

import desktop_test_support  # noqa: F401 - configures Django before ghpcfe imports

from ghpcfe.forms import ClusterForm
from ghpcfe.models import Cluster


def submit(**overrides):
    """Bind ClusterForm to a desktop configuration and return its errors.

    Only the desktop-relevant fields are supplied. The rest (credential,
    subnet, name) are left out deliberately: they are required, so they collect
    their own errors, and supplying them would need database rows that say
    nothing about the rules under test. clean() runs regardless, which is what
    these assert on.
    """
    data = {
        "num_login_nodes": "1",
        "enable_web_desktop": "",
        "enable_viz_desktop": "",
        "login_desktop_vnc_backend": Cluster.DESKTOP_VNC_BACKEND_TIGER,
        "viz_desktop_vnc_backend": Cluster.DESKTOP_VNC_BACKEND_TURBO,
        "desktop_partition_mode": Cluster.DESKTOP_PARTITION_MODE_DYNAMIC,
        "desktop_instance_type": "n2-standard-4",
        "desktop_gpu_type": "",
        "desktop_gpu_count": "0",
        "desktop_placement_mode": Cluster.DESKTOP_PLACEMENT_CLUSTER_ZONE,
        "desktop_reservation_name": "",
    }
    data.update(overrides)

    form = ClusterForm(data=data, initial={})
    form.is_valid()
    return form.errors


@pytest.mark.parametrize(
    "field,overrides",
    [
        # No login node and no desktop leaves the cluster with no Slurm client
        # of any kind, so nothing can submit a job to it.
        ("num_login_nodes", {"num_login_nodes": "0"}),
        # The login desktop runs *on* the login node, so removing the node
        # removes the thing that would host it.
        (
            "num_login_nodes",
            {"num_login_nodes": "0", "enable_web_desktop": "on"},
        ),
        # TigerVNC offloads GL only through -rendernode, and GCE's NVIDIA
        # images create no DRM render node, so the GPU would be billed and
        # never used.
        (
            "viz_desktop_vnc_backend",
            {
                "enable_viz_desktop": "on",
                "viz_desktop_vnc_backend": Cluster.DESKTOP_VNC_BACKEND_TIGER,
                "desktop_gpu_type": "nvidia-tesla-t4",
                "desktop_gpu_count": "1",
            },
        ),
        # Reserved capacity with no name would emit no reservation at all, and
        # the desktop would quietly fall back to on-demand capacity.
        (
            "desktop_reservation_name",
            {
                "enable_viz_desktop": "on",
                "desktop_placement_mode": Cluster.DESKTOP_PLACEMENT_RESERVATION,
                "desktop_reservation_name": "",
            },
        ),
    ],
)
def test_rejected_desktop_combinations(field, overrides):
    assert field in submit(**overrides)


def test_zero_login_nodes_are_allowed_with_the_viz_desktop():
    """The viz desktop is a Slurm client, so it can stand in for a login node."""
    errors = submit(num_login_nodes="0", enable_viz_desktop="on")

    assert "num_login_nodes" not in errors


def test_a_stale_reservation_name_is_cleared_when_unused():
    """Left set, it would emit a reservation the chosen placement never asked
    for - and the nodeset rejects a reservation alongside extra zones."""
    form = ClusterForm(
        data={
            "num_login_nodes": "1",
            "enable_viz_desktop": "on",
            "viz_desktop_vnc_backend": Cluster.DESKTOP_VNC_BACKEND_TURBO,
            "desktop_partition_mode": Cluster.DESKTOP_PARTITION_MODE_DYNAMIC,
            "desktop_instance_type": "n2-standard-4",
            "desktop_gpu_count": "0",
            "desktop_placement_mode": Cluster.DESKTOP_PLACEMENT_ANY_ZONE,
            "desktop_reservation_name": "left-over",
        },
        initial={},
    )
    form.is_valid()

    assert form.cleaned_data["desktop_reservation_name"] == ""


def test_the_viz_desktop_machine_cascade_ids_match_updateMachineAvailability():
    """update_form.html's updateMachineAvailability() derives its GPU-field
    selectors by stripping everything after the last "-" in the machine-type
    select's own id, and looks up "<prefix>-GPU_type" / "<prefix>-GPU_per_node"
    from there - the same shape a partition formset row gets for free from
    Django's own numbered field naming. The desktop fields are not part of any
    formset, so forms.py gives them that shape explicitly; this pins the
    contract between the two rather than letting a widget attrs edit silently
    break the cascade with no visible error (a missing element is simply not
    found by jQuery, not an exception)."""
    form = ClusterForm(data={}, initial={})

    machine_type_id = form.fields["desktop_instance_type"].widget.attrs["id"]
    prefix = machine_type_id.rsplit("-", 1)[0]

    assert form.fields["desktop_gpu_type"].widget.attrs["id"] == f"{prefix}-GPU_type"
    assert (
        form.fields["desktop_gpu_count"].widget.attrs["id"]
        == f"{prefix}-GPU_per_node"
    )
