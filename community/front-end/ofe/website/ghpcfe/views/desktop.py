# Copyright 2026 "Google LLC"
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import base
import logging
import socket

from ..cluster_manager import c2
from ..models import Cluster

logger = logging.getLogger(__name__)

DESKTOP_TARGET_LOGIN = "login"
DESKTOP_TARGET_VIZ = "viz"

DESKTOP_TARGET_LABELS = {
    DESKTOP_TARGET_LOGIN: "Login Desktop",
    DESKTOP_TARGET_VIZ: "Visualization Desktop",
}

DESKTOP_JOB_TRANSITIONAL_STATES = {
    "PENDING",
    "CONFIGURING",
    "BOOTSTRAPPING",
    "STOPPING",
}
DESKTOP_JOB_FINAL_STATES = {
    "CANCELLED",
    "COMPLETED",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "TIMEOUT",
}


def _get_google_login_uid(user):
    social_account = user.socialaccount_set.first()
    return getattr(social_account, "uid", None)


def _check_cluster_access(user, cluster):
    if user.has_admin_role():
        return
    if cluster.status != "r":
        # These denials are logged because they surface as a bare "403
        # Forbidden" from nginx with no indication of which check failed.
        logger.warning(
            "Desktop access denied: cluster=%s status=%r is not running ('r') "
            "and user=%s is not an admin",
            cluster.id,
            cluster.status,
            user.id,
        )
        raise PermissionDenied
    if user not in cluster.authorised_users.all():
        logger.warning(
            "Desktop access denied: user=%s is not in authorised_users for "
            "cluster=%s and is not an admin",
            user.id,
            cluster.id,
        )
        raise PermissionDenied


def _enabled_targets(cluster):
    targets = []
    if cluster.login_desktop_enabled:
        targets.append(DESKTOP_TARGET_LOGIN)
    if cluster.viz_desktop_enabled:
        targets.append(DESKTOP_TARGET_VIZ)
    return targets


def _check_desktop_access(request, cluster, target=None):
    _check_cluster_access(request.user, cluster)
    if not cluster.has_any_desktop:
        logger.warning(
            "Desktop access denied: cluster=%s has neither login_desktop_enabled "
            "nor viz_desktop_enabled",
            cluster.id,
        )
        raise PermissionDenied
    if target and target not in _enabled_targets(cluster):
        logger.warning(
            "Desktop access denied: target=%r is not enabled on cluster=%s "
            "(enabled: %s)",
            target,
            cluster.id,
            _enabled_targets(cluster) or "none",
        )
        raise PermissionDenied
    if not request.user.email:
        # The broker keys sessions and OS Login lookups on the email address, so
        # an account without one cannot be given a desktop.
        logger.warning(
            "Desktop access denied: user=%s has no email address on their "
            "account, which the desktop broker requires to identify them",
            request.user.id,
        )
        raise PermissionDenied


def _desktop_target_label(target):
    return DESKTOP_TARGET_LABELS[target]


def _desktop_service_metadata(cluster, target):
    if target == DESKTOP_TARGET_LOGIN:
        return {
            "host": cluster.login_desktop_service_host,
            "name": cluster.login_desktop_service_name,
            "zone": cluster.login_desktop_service_zone,
            "port": cluster.login_desktop_service_port or 6080,
        }
    return {
        "host": cluster.desktop_service_host,
        "name": cluster.desktop_service_name,
        # Unlike the login desktop's zone (read from Terraform state), nothing
        # ever reports the viz desktop's zone: it is a dynamically scheduled
        # Slurm node, not a static Terraform-managed resource, and the c2
        # daemon's START_DESKTOP response never includes one. There is no
        # model field to read here.
        "zone": None,
        "port": cluster.desktop_service_port or 6080,
    }


def _desktop_state(cluster, target):
    if target == DESKTOP_TARGET_VIZ:
        return cluster.desktop_job_state or "STOPPED"
    if _desktop_service_metadata(cluster, target)["host"]:
        return "RUNNING"
    return None


def _desktop_state_display(state):
    if not state:
        return None
    return state.replace("_", " ").title()


def _desktop_access_scope(target):
    if target == DESKTOP_TARGET_VIZ:
        return "Per-user browser sessions on a shared visualization desktop host"
    return "Per-user browser sessions on the cluster login node desktop service"


def _desktop_vnc_backend_display(cluster, target):
    if target == DESKTOP_TARGET_VIZ:
        return cluster.viz_desktop_vnc_backend_display
    return cluster.login_desktop_vnc_backend_display


def _desktop_can_start(cluster, target):
    if target != DESKTOP_TARGET_VIZ:
        return False
    state = _desktop_state(cluster, target)
    if state in DESKTOP_JOB_TRANSITIONAL_STATES:
        return False
    return not cluster.desktop_job_id or state in DESKTOP_JOB_FINAL_STATES


def _desktop_is_stoppable_by(cluster, user):
    # The job runs under the account that started it, and stopping it powers the
    # node down and takes every session on it with it. Admins can always stop.
    # A desktop with no recorded starter predates this field, so it stays open.
    started_by = cluster.desktop_started_by
    return started_by is None or started_by == user or user.has_admin_role()


def _desktop_can_stop(cluster, target, user):
    if target != DESKTOP_TARGET_VIZ:
        return False
    state = _desktop_state(cluster, target)
    if not cluster.desktop_job_id or state in DESKTOP_JOB_FINAL_STATES:
        return False
    return _desktop_is_stoppable_by(cluster, user)


def _desktop_should_poll(cluster, target):
    return _desktop_state(cluster, target) in DESKTOP_JOB_TRANSITIONAL_STATES


def _update_desktop_cluster_state(cluster_id, message):
    try:
        cluster = Cluster.objects.get(pk=cluster_id)
    except Cluster.DoesNotExist:
        return

    update_fields = set()
    desktop_job_id = message.get("desktop_job_id", message.get("slurm_job_id"))
    desktop_state = message.get("desktop_state")

    if desktop_job_id is not None:
        cluster.desktop_job_id = desktop_job_id
        update_fields.add("desktop_job_id")
    if desktop_state:
        cluster.desktop_job_state = desktop_state
        update_fields.add("desktop_job_state")
    elif message.get("status") == "e":
        cluster.desktop_job_state = "FAILED"
        update_fields.add("desktop_job_state")

    if "desktop_service_host" in message:
        cluster.desktop_service_host = message.get("desktop_service_host")
        update_fields.add("desktop_service_host")
    if "desktop_service_name" in message:
        cluster.desktop_service_name = message.get("desktop_service_name")
        update_fields.add("desktop_service_name")
    if message.get("desktop_service_port"):
        cluster.desktop_service_port = message["desktop_service_port"]
        update_fields.add("desktop_service_port")

    if cluster.desktop_job_state in DESKTOP_JOB_FINAL_STATES:
        cluster.desktop_job_id = None
        cluster.desktop_service_host = None
        cluster.desktop_service_name = None
        update_fields.update(
            [
                "desktop_job_id",
                "desktop_service_host",
                "desktop_service_name",
            ]
        )

    if update_fields:
        cluster.save(update_fields=sorted(update_fields))


def _desktop_connectivity_error(cluster, target):
    if target == DESKTOP_TARGET_VIZ:
        desktop_state = _desktop_state(cluster, target)
        if not cluster.desktop_job_id:
            return (
                "The visualization desktop host is stopped. Start it from this page."
            )
        if desktop_state in DESKTOP_JOB_TRANSITIONAL_STATES:
            return (
                "The visualization desktop job is currently "
                f"{desktop_state.lower()}. This page refreshes automatically."
            )
        if desktop_state and desktop_state in DESKTOP_JOB_FINAL_STATES:
            return (
                "The visualization desktop job is currently "
                f"{desktop_state.lower()}. Start it again if needed."
            )

    service = _desktop_service_metadata(cluster, target)
    if not service["host"]:
        return "Desktop service host metadata is not available yet."

    try:
        with socket.create_connection(
            (service["host"], service["port"]),
            timeout=2,
        ):
            return None
    except OSError:
        if target == DESKTOP_TARGET_LOGIN:
            node_label = service["name"] or "the login node"
            return (
                f"The login desktop service at {service['host']}:{service['port']} "
                "is not listening yet. The login node may still be bootstrapping, "
                f"or the desktop broker may have failed to start on {node_label}. "
                "Refresh in a few minutes and retry."
            )
        return (
            f"The desktop service at {service['host']}:{service['port']} is not "
            "listening yet. The desktop node may still be bootstrapping, or the "
            "desktop broker may have failed to start."
        )


def _desktop_identity_error(user):
    if _get_google_login_uid(user):
        return None
    return (
        "Desktop access requires your OFE account to be linked to Google sign-in "
        "so OS Login can map you to a Linux account. Log out, sign in with Google, "
        "then retry."
    )


def _desktop_status_banner(cluster, user, target):
    identity_error = _desktop_identity_error(user)
    if identity_error:
        return {
            "level": "warning",
            "message": identity_error,
            "ready": False,
        }

    connectivity_error = _desktop_connectivity_error(cluster, target)
    if connectivity_error:
        return {
            "level": "info" if target == DESKTOP_TARGET_VIZ else "warning",
            "message": connectivity_error,
            "ready": False,
        }

    return {
        "level": "success",
        "message": (
            f"{_desktop_target_label(target)} is ready. OFE will open a per-user "
            "session using your Google and OS Login identity."
        ),
        "ready": True,
    }


def _desktop_diagnostics(cluster, target):
    diagnostics = [
        {
            "label": "Access Model",
            "value": _desktop_access_scope(target),
        },
        {
            "label": "VNC Backend",
            "value": _desktop_vnc_backend_display(cluster, target),
        }
    ]

    desktop_state = _desktop_state_display(_desktop_state(cluster, target))
    if desktop_state:
        diagnostics.append(
            {
                "label": "Infrastructure State",
                "value": desktop_state,
            }
        )
    if target == DESKTOP_TARGET_VIZ:
        diagnostics.append(
            {
                "label": "Partition Mode",
                "value": cluster.get_desktop_partition_mode_display(),
            }
        )
        diagnostics.append(
            {
                "label": "Host Type",
                "value": cluster.desktop_instance_type,
            }
        )
        # Placement decides whether a zone running out of capacity leaves the
        # desktop queued, so it belongs with the other facts about the host.
        placement = cluster.get_desktop_placement_mode_display()
        if cluster.desktop_placement_mode == Cluster.DESKTOP_PLACEMENT_RESERVATION:
            placement = f"{placement} ({cluster.desktop_reservation_name})"
        diagnostics.append(
            {
                "label": "Placement",
                "value": placement,
            }
        )
        if cluster.desktop_gpu_type:
            diagnostics.append(
                {
                    "label": "GPU",
                    "value": f"{cluster.desktop_gpu_type} x {cluster.desktop_gpu_count}",
                }
            )
        if cluster.desktop_job_id:
            diagnostics.append(
                {
                    "label": "Slurm Job ID",
                    "value": str(cluster.desktop_job_id),
                }
            )

    service = _desktop_service_metadata(cluster, target)
    if service["name"]:
        diagnostics.append(
            {
                "label": "Desktop Node",
                "value": service["name"],
            }
        )
    if service["zone"]:
        diagnostics.append(
            {
                "label": "Desktop Zone",
                "value": service["zone"],
            }
        )
    if service["host"]:
        diagnostics.append(
            {
                "label": "Service Endpoint",
                "value": f"{service['host']}:{service['port']}",
            }
        )

    return diagnostics


def _desktop_target_card(cluster, user, target):
    status_banner = _desktop_status_banner(cluster, user, target)
    diagnostics = []
    for item in _desktop_diagnostics(cluster, target):
        if item["label"] == "Access Model":
            continue
        if item["label"] == "Service Endpoint" and status_banner["ready"]:
            continue
        diagnostics.append(item)
    return {
        "key": target,
        "label": _desktop_target_label(target),
        "state": _desktop_state_display(_desktop_state(cluster, target)) or "Unavailable",
        "summary": status_banner["message"],
        "ready": status_banner["ready"],
        "status_level": status_banner["level"],
        "can_start": _desktop_can_start(cluster, target),
        "can_stop": _desktop_can_stop(cluster, target, user),
        "poll": _desktop_should_poll(cluster, target),
        "diagnostics": diagnostics,
        "url": reverse("cluster-desktop-target", args=[cluster.id, target]),
    }


class ClusterDesktopView(LoginRequiredMixin, base.TemplateView):
    template_name = "cluster/desktop_index.html"

    def dispatch(self, request, *args, **kwargs):
        self.cluster = get_object_or_404(Cluster, pk=kwargs["pk"])
        _check_desktop_access(request, self.cluster)
        targets = _enabled_targets(self.cluster)
        if len(targets) == 1:
            return HttpResponseRedirect(
                reverse("cluster-desktop-target", args=[self.cluster.id, targets[0]])
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["navtab"] = "cluster"
        context["object"] = self.cluster
        context["desktop_targets"] = [
            _desktop_target_card(self.cluster, self.request.user, target)
            for target in _enabled_targets(self.cluster)
        ]
        return context


class ClusterDesktopTargetView(LoginRequiredMixin, base.TemplateView):
    template_name = "cluster/desktop.html"

    def dispatch(self, request, *args, **kwargs):
        self.cluster = get_object_or_404(Cluster, pk=kwargs["pk"])
        self.target = kwargs["target"]
        _check_desktop_access(request, self.cluster, self.target)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["navtab"] = "cluster"
        context["object"] = self.cluster
        context["desktop_target"] = self.target
        context["desktop_target_label"] = _desktop_target_label(self.target)
        context["desktop_state"] = _desktop_state(self.cluster, self.target)
        context["desktop_state_display"] = _desktop_state_display(
            context["desktop_state"]
        )
        context["desktop_can_start"] = _desktop_can_start(self.cluster, self.target)
        context["desktop_can_stop"] = _desktop_can_stop(
            self.cluster, self.target, self.request.user
        )
        context["desktop_started_by"] = self.cluster.desktop_started_by
        context["desktop_poll"] = _desktop_should_poll(self.cluster, self.target)
        context["desktop_status_banner"] = _desktop_status_banner(
            self.cluster, self.request.user, self.target
        )
        context["desktop_diagnostics"] = _desktop_diagnostics(
            self.cluster, self.target
        )
        if context["desktop_status_banner"]["ready"]:
            context["proxy_url"] = (
                reverse(
                    "cluster-desktop-proxy",
                    args=[self.cluster.id, self.target, "vnc.html"],
                )
                + "?autoconnect=1&resize=remote&path=websockify"
            )
        return context


class ClusterDesktopAuthView(base.View):
    http_method_names = ["get", "head"]

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponse(status=401)
        self.cluster = get_object_or_404(Cluster, pk=kwargs["pk"])
        self.target = kwargs["target"]
        _check_desktop_access(request, self.cluster, self.target)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return self._response(request)

    def head(self, request, *args, **kwargs):
        return self._response(request)

    def _response(self, request):
        service = _desktop_service_metadata(self.cluster, self.target)
        if not service["host"]:
            # nginx collapses any auth_request status other than 401/403 into a
            # bare "500 Internal Server Error", so this is logged here or the
            # cause is invisible. An empty host means the desktop's address was
            # never discovered from the cluster's Terraform state - see
            # ClusterInfo._update_desktop_service_details, which warns when it
            # cannot find the instance.
            logger.warning(
                "No desktop address recorded for cluster=%s target=%s; the "
                "browser will see a 500 from nginx. Check the cluster finished "
                "deploying and that desktop discovery found the instance.",
                self.cluster.id,
                self.target,
            )
            return HttpResponse(status=503)
        response = HttpResponse()
        response["Cache-Control"] = "no-store"
        response["X-Desktop-Upstream"] = (
            f"http://{service['host']}:{service['port']}"
        )
        response["X-Cluster-Desktop-Email"] = request.user.email
        login_uid = _get_google_login_uid(request.user)
        if login_uid:
            response["X-Cluster-Desktop-Login-Uid"] = login_uid
        if self.cluster.desktop_proxy_secret:
            response["X-Cluster-Desktop-Secret"] = (
                self.cluster.desktop_proxy_secret
            )

        # Brokers run in trusted_proxy mode: the broker takes these headers on
        # trust rather than verifying a signed assertion, so the only thing
        # standing between "any request that reaches the broker" and "an
        # authenticated desktop session" is that nginx's auth_request always
        # calls this view first and the broker port is unreachable by any
        # other route (see community/front-end/ofe/website/nginx.conf and the
        # firewall rule ClusterInfo._prepare_desktop_networking emits). Do not
        # widen network access to the broker port without moving to a verified
        # identity mode.
        return response


class ClusterDesktopProxyView(LoginRequiredMixin, base.View):
    def dispatch(self, request, pk, target, path):
        cluster = get_object_or_404(Cluster, pk=pk)
        _check_desktop_access(request, cluster, target)
        return HttpResponse(
            "Cluster desktop proxying is handled by the OFE nginx frontend.",
            status=502,
        )


class ClusterDesktopPowerView(LoginRequiredMixin, base.View):
    http_method_names = ["post"]

    def post(self, request, pk, target, action):
        cluster = get_object_or_404(Cluster, pk=pk)
        _check_cluster_access(request.user, cluster)

        if target != DESKTOP_TARGET_VIZ:
            raise PermissionDenied
        if action not in ["start", "stop"]:
            raise PermissionDenied

        try:
            if action == "start":
                login_uid = _get_google_login_uid(request.user)
                if not login_uid:
                    messages.error(
                        request,
                        "Desktop start requires Google sign-in so OS Login can map your Linux account.",
                    )
                    return HttpResponseRedirect(
                        reverse("cluster-desktop-target", args=[cluster.id, target])
                    )
                if not _desktop_can_start(cluster, target):
                    messages.info(
                        request,
                        "The visualization desktop is already starting or running.",
                    )
                else:

                    def start_response(message, cluster_id=cluster.id):
                        _update_desktop_cluster_state(cluster_id, message)

                    cluster.desktop_job_id = None
                    cluster.desktop_job_state = "PENDING"
                    cluster.desktop_service_host = None
                    cluster.desktop_service_name = None
                    cluster.desktop_started_by = request.user
                    cluster.save(
                        update_fields=[
                            "desktop_job_id",
                            "desktop_job_state",
                            "desktop_service_host",
                            "desktop_service_name",
                            "desktop_started_by",
                        ]
                    )
                    c2.send_command(
                        cluster.id,
                        "START_DESKTOP",
                        data={
                            "job_name": cluster.viz_desktop_job_name,
                            "login_uid": login_uid,
                            "partition": cluster.viz_desktop_partition_name,
                            "desktop_service_port": cluster.desktop_service_port,
                        },
                        on_response=start_response,
                    )
                    messages.info(
                        request,
                        "Requested start for the visualization desktop job. "
                        "This page refreshes while the node is allocated and the desktop broker starts.",
                    )
            else:
                if not cluster.desktop_job_id:
                    messages.info(
                        request,
                        "The visualization desktop is already stopped.",
                    )
                elif not _desktop_is_stoppable_by(cluster, request.user):
                    messages.error(
                        request,
                        "This desktop was started by "
                        f"{cluster.desktop_started_by.username}. Stopping it "
                        "would end their session, so only they or an admin can "
                        "stop it.",
                    )
                else:

                    def stop_response(message, cluster_id=cluster.id):
                        _update_desktop_cluster_state(cluster_id, message)

                    cluster.desktop_job_state = "STOPPING"
                    cluster.save(update_fields=["desktop_job_state"])
                    c2.send_command(
                        cluster.id,
                        "STOP_DESKTOP",
                        data={
                            "desktop_job_id": cluster.desktop_job_id,
                        },
                        on_response=stop_response,
                    )
                    messages.info(
                        request,
                        "Requested stop for the visualization desktop job.",
                    )
        except Exception as exc:
            messages.error(
                request,
                f"Desktop power action failed: {exc}",
            )

        return HttpResponseRedirect(
            reverse("cluster-desktop-target", args=[cluster.id, target])
        )
