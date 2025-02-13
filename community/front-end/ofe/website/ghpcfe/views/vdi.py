""" Grafana integration views """

import json
from django.views import generic
from django.conf import settings
from django.shortcuts import render
from ..models import GuacamoleInstance
from ..permissions import SuperUserRequiredMixin
from ..cluster_manager import cloud_info


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

        api_keys = {}

        # For each Guacamole instance, retrieve its cloud credential from the related cluster.
        for instance in context["vdi_list"]:
            try:
                # Use the cloud_credential field stored in the cluster.
                credentials_json = instance.cluster.cloud_credential.detail
                # Parse the credential JSON to extract the project ID.
                cred_dict = json.loads(credentials_json)
                project_id = cred_dict["project_id"]

                # Use your helper function to get the API key.
                api_key = cloud_info.get_guac_api_key(credentials_json, project_id, instance)
                api_keys[instance.id] = api_key
            except Exception as e:
                # If retrieval fails, store an error message.
                api_keys[instance.id] = f"Error: {str(e)}"
        context["api_keys"] = api_keys

        return context
