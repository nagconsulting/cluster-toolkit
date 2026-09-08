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

"""ClusterInfo._prepare_desktop_networking() must hard-fail closed.

trusted_proxy identity has no cryptographic verification: it is safe only
because OFE's own subnet is the sole route to the desktop broker port. That
guarantee depends on knowing OFE's hosting network, so when the instance
metadata lookup that supplies it fails, the code must refuse to deploy a
desktop rather than fall back to an unrestricted firewall rule.
"""

import pytest

from desktop_test_support import fake_cluster, ofe_config  # noqa: F401 - fixture

from ghpcfe.cluster_manager.clusterinfo import (
    ClusterInfo,
    DesktopNetworkIsolationError,
)


def make_cluster_info(cluster):
    """A ClusterInfo bound to a fake cluster, without touching the filesystem.

    __init__ only reads self.config (stubbed by ofe_config) and self.cluster;
    it does not touch the cluster directory, so no cluster row or deploy
    directory is needed for this test.
    """
    return ClusterInfo(cluster)


def test_no_desktop_skips_the_network_lookup_entirely(ofe_config, monkeypatch):
    """No desktop means no broker port to isolate, so the metadata probe that
    would otherwise be required must never run."""
    info = make_cluster_info(fake_cluster())

    def fail(*args, **kwargs):
        raise AssertionError("metadata lookup must not run with no desktop enabled")

    monkeypatch.setattr(info, "_gcp_instance_metadata", fail)

    assert info._prepare_desktop_networking() == ("", [])


def test_a_failed_hosting_network_lookup_hard_fails(ofe_config, monkeypatch):
    info = make_cluster_info(fake_cluster(enable_viz_desktop=True))
    monkeypatch.setattr(
        info,
        "_gcp_instance_metadata",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("metadata unreachable")),
    )

    with pytest.raises(DesktopNetworkIsolationError):
        info._prepare_desktop_networking()


def test_a_non_gcp_host_type_hard_fails_the_same_way(ofe_config):
    """_get_hosting_network_info() also returns {} outright off GCP - the same
    failure mode as a broken metadata probe, and it must be refused the same
    way rather than silently skipping isolation."""
    ofe_config["server"]["host_type"] = "on_prem"
    info = make_cluster_info(fake_cluster(enable_web_desktop=True))

    with pytest.raises(DesktopNetworkIsolationError):
        info._prepare_desktop_networking()


def test_a_working_lookup_scopes_the_firewall_to_ofes_subnet(ofe_config, monkeypatch):
    """The success path, for contrast: a resolvable hosting network yields the
    CIDR to restrict the broker's firewall rule to, with no peering emitted
    when OFE and the cluster already share a network."""
    # FakeCluster's default subnet already sits on vpc "hosting-net" - the
    # same network name instance metadata reports below.
    info = make_cluster_info(fake_cluster(enable_viz_desktop=True))
    responses = {
        "network-interfaces/0/network": "projects/p/global/networks/hosting-net",
        "network-interfaces/0/ip": "10.2.0.5",
        "network-interfaces/0/subnetmask": "255.255.255.240",
    }
    monkeypatch.setattr(
        info, "_gcp_instance_metadata", lambda path: responses[path]
    )

    rendered_yaml, allowed_cidrs = info._prepare_desktop_networking()

    assert allowed_cidrs == ["10.2.0.0/28"]
    # Same network on both sides: no VPC peering module to emit.
    assert rendered_yaml == ""
