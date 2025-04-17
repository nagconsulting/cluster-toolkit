""" VDI integration views """

import json
import logging
from django.views import generic
from django.conf import settings
from django.shortcuts import render
from ..models import GuacamoleInstance, GuacamoleConnection
from ..permissions import LoginRequiredMixin
from ..cluster_manager import cloud_info
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views import View
from django.shortcuts import get_object_or_404


logger = logging.getLogger(__name__)


class VDIListView(LoginRequiredMixin, generic.ListView):
    """
    Displays one row per GuacamoleInstance (VDI server).
    In each row, we show the user's two connections (VDI & SSH).
    """
    template_name = "vdi/list.html"
    context_object_name = "vdi_list"

    def get_queryset(self):
        """
        Return a combined queryset of all known VDI types.

        """
        # Example if you only have Guacamole so far:
        return GuacamoleInstance.objects.filter(
            cluster__authorised_users=self.request.user
        )

        # Future: if you have multiple subclasses:
        # from django.db.models import Q
        # qs_guac = GuacamoleInstance.objects.all()
        # qs_novnc = NoVNCInstance.objects.all()
        # return qs_guac.union(qs_novnc)
        #
        # Or chain them etc.

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # The GuacamoleInstance objects returned by get_queryset()
        instance_list = context["vdi_list"]  

        rows = []
        for inst in instance_list:
            # Grab all connections for this user & instance:
            user_conns = inst.connections.filter(user=self.request.user)

            # Determine the protocol by the port number:
            vnc_conn = user_conns.filter(port__gte=5901).first()
            ssh_conn = user_conns.filter(port=22).first()

            rows.append({
                "instance": inst,
                "vnc_conn": vnc_conn,
                "ssh_conn": ssh_conn,
            })

        # This list of dicts holds the instance plus the two connections above
        context["rows"] = rows

        # For auto-refresh
        loading = any(inst.status in ["n", "i"] for inst in instance_list)
        context["loading"] = 1 if loading else 0

        context["navtab"] = "vdi"

        return context


class VDIGetPasswordView(LoginRequiredMixin, View):
    """
    Returns the latest VNC password (server or user) for a given VDI instance.
    Accepts a query parameter 'type' with values 'vnc_server' or 'vdi_user'
    (defaults to 'vdi_user').
    """

    def get(self, request, pk, *args, **kwargs):
        # Retrieve the instance (only GuacamoleInstance for now)
        conn = get_object_or_404(GuacamoleConnection, pk=pk)
        
        # security: optionally confirm that the requesting user 
        # is either a superuser or the same user who owns this connection
        if not (request.user.is_superuser or request.user == conn.user):
            return HttpResponseForbidden("Not allowed to view this password.")

        # Grab the “cloud_info” from the cluster
        credentials_json = conn.instance.cluster.cloud_credential.detail
        cred_dict = json.loads(credentials_json)
        project_id = cred_dict.get("project_id")

        # For the user’s personal password:
        password_type = request.GET.get('type', 'vdi_user')

        try:
            if password_type == "vnc_server":
                password = cloud_info.get_vnc_server_password(credentials_json, project_id, conn)
            if password_type == "vdi_user":
                # we pass the username or the full GuacamoleConnection to the function
                password = cloud_info.get_vdi_user_password(credentials_json, project_id, conn)
                return JsonResponse({"password": password})
            elif password_type == "guac_password":
                password = cloud_info.get_guac_admin_password(credentials_json, project_id, conn.instance)
                encoded_conn = conn.generate_connection_string()
                return JsonResponse({
                    "password": password,
                    "connection_string": encoded_conn,
                    "instance_id": conn.instance.id
                })
            elif password_type == "auth_token":
                token = cloud_info.get_guac_auth_token(credentials_json, project_id, conn.instance)
                password = token
            else:
                return HttpResponseBadRequest("Invalid password type requested.")
        except Exception as e:
            logger.exception("Error retrieving password:")
            return JsonResponse({"error": str(e)}, status=500)

        return JsonResponse({"password": password})

