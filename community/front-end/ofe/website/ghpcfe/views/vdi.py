""" VDI integration views """

import json
import logging
from django.views import generic
from django.conf import settings
from django.shortcuts import render
from ..models import GuacamoleInstance
from ..permissions import SuperUserRequiredMixin
from ..cluster_manager import cloud_info
from django.http import JsonResponse, HttpResponseBadRequest
from django.views import View
from django.shortcuts import get_object_or_404


logger = logging.getLogger(__name__)


class VDIListView(SuperUserRequiredMixin, generic.ListView):
    """
    Used for a single list view of all VDI instance types (Guacamole, etc.).
    Only Guac' exists for now...
    """
    template_name = "vdi/list.html"
    context_object_name = "vdi_list"

    def get_queryset(self):
        """
        Return a combined queryset of all known VDI types.

        """
        # Example if you only have Guacamole so far:
        return GuacamoleInstance.objects.all()

        # Future: if you have multiple subclasses:
        # from django.db.models import Q
        # qs_guac = GuacamoleInstance.objects.all()
        # qs_novnc = NoVNCInstance.objects.all()
        # return qs_guac.union(qs_novnc)
        #
        # Or chain them etc.

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["navtab"] = "vdi"

        loading = 0

        auth_tokens = {}

        # For each Guacamole instance, retrieve its cloud credential from the related cluster.
        for instance in context["vdi_list"]:
            try:
                # Enable autorefresh of divs if new or initialising
                if "n" in instance.status or "i" in instance.status:
                    loading = 1
                    break
                # Use the cloud_credential field stored in the cluster.
                credentials_json = instance.cluster.cloud_credential.detail
                # Parse the credential JSON to extract the project ID.
                cred_dict = json.loads(credentials_json)
                project_id = cred_dict["project_id"]

                # Use helper functions to get the API key and passwords
                auth_token = cloud_info.get_guac_auth_token(
                    credentials_json,
                    project_id,
                    instance
                )
                
                auth_tokens[instance.id] = auth_token

            except Exception as e:
                # If retrieval fails, store an error message.
                auth_tokens[instance.id] = f"Error: {str(e)}"

        context["auth_tokens"] = auth_tokens
        context["loading"] = loading

        return context


class VDIGetPasswordView(SuperUserRequiredMixin, View):
    """
    Returns the latest VNC password (server or user) for a given VDI instance.
    Accepts a query parameter 'type' with values 'vnc_server' or 'vnc_user'
    (defaults to 'vnc_user').
    """

    def get(self, request, pk, *args, **kwargs):
        # Retrieve the instance (only GuacamoleInstance for now)
        instance = get_object_or_404(GuacamoleInstance, pk=pk)
        # Decide which password to return; default to vnc_server
        password_type = request.GET.get('type', 'vnc_user')

        try:
            # Retrieve cloud credential JSON and project ID from the instance’s cluster.
            credentials_json = instance.cluster.cloud_credential.detail

            logger.debug("credentials_json: %s", credentials_json)

            cred_dict = json.loads(credentials_json)
            project_id = cred_dict.get("project_id")

            if password_type == "vnc_server":
                password = cloud_info.get_vnc_server_password(credentials_json, project_id, instance)
            elif password_type == "vnc_user":
                password = cloud_info.get_vnc_user_password(credentials_json, project_id, instance)
            else:
                return HttpResponseBadRequest("Invalid password type requested.")
        except Exception as e:
            logger.exception("Error retrieving password:")
            return JsonResponse({"error": str(e)}, status=500)

        return JsonResponse({"password": password})

