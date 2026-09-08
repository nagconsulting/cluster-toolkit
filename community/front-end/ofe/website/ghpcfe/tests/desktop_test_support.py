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

"""Shared fixtures. Boots Django for the whole suite, without a deployment.

Two things normally stand between this app and a test process, and both are
handled here rather than in each module:

* ``GHPCFEConfig.ready()`` starts the c2 daemon, which reads the deployed
  server's ``configuration.yaml`` and then opens a live Pub/Sub subscription.
  The daemon is stubbed out before the app registry runs, so the app loads with
  neither. ``cluster_manager.c2`` deliberately imports no models, which is what
  makes it reachable this early.
* ``utils.load_config()`` reads that same file. Anything needing a config (such
  as ``ClusterInfo``) should take the ``ofe_config`` fixture.

No database is configured. These are template-rendering, form-validation and
blueprint-generation tests; none of them need one, and requiring a database
would mean requiring migrations, which this project generates at deploy time.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

WEBSITE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WEBSITE_DIR) not in sys.path:
    sys.path.insert(0, str(WEBSITE_DIR))

# Skip the whole suite where the front end's dependencies are absent, rather
# than erroring at collection: the repo's shared pytest hook does not install
# Django or allauth.
django = pytest.importorskip("django", reason="OFE requires Django")
pytest.importorskip("allauth", reason="OFE requires django-allauth")


def _configure_django():
    from django.conf import settings

    if settings.configured:
        return

    settings.configure(
        DEBUG=True,
        USE_TZ=True,
        # Deliberately empty: see the module docstring.
        DATABASES={},
        MIDDLEWARE=["allauth.account.middleware.AccountMiddleware"],
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "allauth",
            "allauth.account",
            "allauth.socialaccount",
            "ghpcfe",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [str(WEBSITE_DIR / "ghpcfe" / "templates")],
                "APP_DIRS": False,
                "OPTIONS": {},
            }
        ],
    )

    # Must happen before django.setup() triggers GHPCFEConfig.ready().
    from ghpcfe.cluster_manager import c2

    c2.startup = lambda: None
    c2.start_cloud_build_log_subscriber = lambda: None

    django.setup()


_configure_django()


class FakeSubnet:
    """Stands in for VirtualSubnet, which the blueprint reads by attribute."""

    def __init__(self, cloud_id="cluster-subnet", vpc_cloud_id="hosting-net"):
        self.cloud_id = cloud_id
        self.name = cloud_id
        self.cloud_region = "europe-west4"
        self.vpc = type("FakeVpc", (), {"cloud_id": vpc_cloud_id, "name": vpc_cloud_id})()


class FakeCluster:
    """The attributes the desktop blueprint and ClusterInfo actually read.

    A real Cluster needs a credential, a subnet and a saved row; none of that
    changes what the template emits, and going through the ORM would drag in a
    database. The desktop properties mirror models.Cluster so that a rename
    there shows up as a failure here.
    """

    def __init__(self, **overrides):
        self.id = 1
        self.cloud_id = "testcluster-abcd1234"
        self.name = "testcluster"
        self.project_id = "test-project"
        self.cloud_region = "europe-west4"
        self.cloud_zone = "europe-west4-a"
        self.subnet = FakeSubnet()
        self.use_bigquery = False
        self.enable_slurm_auth = True
        self.controller_instance_type = "c2-standard-4"
        self.controller_disk_type = "pd-standard"
        self.controller_disk_size = 50
        self.controller_node_image = None
        self.login_node_image = None
        self.num_login_nodes = 1
        self.login_node_instance_type = "c2-standard-4"
        self.login_node_disk_type = "pd-standard"
        self.login_node_disk_size = 50

        # Desktop configuration.
        self.enable_web_desktop = False
        self.enable_viz_desktop = False
        self.desktop_proxy_secret = "test-desktop-secret"
        self.desktop_instance_type = "n2-standard-4"
        self.desktop_partition_mode = "dynamic"
        self.desktop_placement_mode = "cluster_zone"
        self.desktop_reservation_name = ""
        self.desktop_gpu_type = ""
        self.desktop_gpu_count = 0
        self.login_desktop_vnc_backend = "tigervnc"
        self.viz_desktop_vnc_backend = "turbovnc"

        for key, value in overrides.items():
            setattr(self, key, value)

    # Mirrors models.Cluster's read-only helpers.
    @property
    def login_desktop_enabled(self):
        return self.enable_web_desktop

    @property
    def viz_desktop_enabled(self):
        return self.enable_viz_desktop

    @property
    def has_any_desktop(self):
        return self.login_desktop_enabled or self.viz_desktop_enabled

    @property
    def viz_desktop_has_gpu(self):
        return bool(self.desktop_gpu_type and self.desktop_gpu_count > 0)

    @property
    def viz_desktop_partition_name(self):
        return f"ghpcfe-viz-{self.id}"


def fake_cluster(**overrides):
    """A cluster with no desktop enabled, plus whatever a test changes."""
    return FakeCluster(**overrides)


def blueprint_context(cluster, **overrides):
    """The context ClusterInfo._prepare_ghpc_yaml builds, with fakes for the
    pre-rendered fragments a desktop test does not exercise.

    The GPU-acceleration flag is computed by the real ClusterInfo helper rather
    than restated here, so the rule stays under test rather than duplicated.
    The helper reads only ``self.cluster``, so an unbound call is enough.
    """
    from django.template import engines

    from ghpcfe.cluster_manager.clusterinfo import ClusterInfo

    # login_yaml is computed via the real ClusterInfo methods, not restated
    # here, for the same reason as the GPU-acceleration flag below: the
    # rendering rule stays under test in one place. Both methods read only
    # self.cluster/self.env/self.indent_text, so a namespace stand-in for
    # self is enough without a full ClusterInfo (which needs a saved cluster
    # row and a config-backed cluster_dir).
    fake_self = SimpleNamespace(cluster=cluster, env=engines["django"])
    fake_self.indent_text = lambda text, level: ClusterInfo.indent_text(
        fake_self, text, level
    )
    login_yaml, _login_refs = ClusterInfo._prepare_login_yaml(fake_self)

    context = {
        "project_id": cluster.project_id,
        "site_name": "OFE",
        "filesystems_yaml": "",
        "partitions_yaml": "",
        "artifact_registry_yaml": "",
        "cloudsql_yaml": "",
        "desktop_network_yaml": "",
        "desktop_partition_yaml": "",
        "desktop_allowed_ingress_cidrs": [],
        "desktop_identity_mode": "trusted_proxy",
        "viz_desktop_gpu_acceleration": ClusterInfo._viz_desktop_gpu_acceleration(
            fake_self
        ),
        "controller_image_yaml": "",
        "login_image_yaml": "",
        "login_yaml": login_yaml,
        "cluster": cluster,
        "controller_uses": "    - hpc_network",
        "login_uses": "    - hpc_network",
        "controller_sa": "sa",
        "startup_bucket": "test-startup-bucket",
    }
    context.update(overrides)
    return context


def render_blueprint(cluster, **overrides):
    """Render cluster_config.yaml.j2 the way ClusterInfo does."""
    from django.template import engines

    template = engines["django"].get_template("blueprint/cluster_config.yaml.j2")
    return template.render(blueprint_context(cluster, **overrides))


@pytest.fixture
def ofe_config(tmp_path, monkeypatch):
    """Stand in for the deployed server's configuration.yaml.

    Returned so a test can assert against the same values ClusterInfo sees.
    """
    config = {
        "baseDir": tmp_path,
        "server": {
            "gcs_bucket": "test-startup-bucket",
            "host_type": "GCP",
        },
        "loaded": True,
    }

    from ghpcfe.cluster_manager import utils

    monkeypatch.setattr(utils, "load_config", lambda *a, **kw: config)
    return config
