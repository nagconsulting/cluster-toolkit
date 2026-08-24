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

output "backend_service_ids" {
  description = "Full resource ID of each backend service, keyed by its backend_services name."
  value       = { for k, v in google_compute_backend_service.lb : k => v.id }
}

output "backend_service_names" {
  description = <<-EOT
    Name of each backend service, keyed by its backend_services name. A workload
    verifying IAP assertions needs its own name to resolve the audience they are
    minted for.

    The names are deterministic - "DEPLOYMENT-NAME-BACKEND-backend" - so a
    blueprint can also spell one out directly where referencing this output
    would create a dependency cycle.
    EOT
  value       = { for k, v in google_compute_backend_service.lb : k => v.name }
}

output "backend_service_self_links" {
  description = "Self link of each backend service, keyed by its backend_services name."
  value       = { for k, v in google_compute_backend_service.lb : k => v.self_link }
}

output "ip_address" {
  description = "External IP address the load balancer serves on. Point DNS here."
  value       = local.address
}

output "url" {
  description = "HTTPS URL of the load balancer, using the first configured domain where there is one."
  value       = length(var.domains) > 0 ? "https://${var.domains[0]}" : "https://${local.address}"
}

output "urls_by_backend" {
  description = "HTTPS URL that reaches each backend service, using its first host or the default domain."
  value = {
    for k, b in local.backends : k => (
      length(b.hosts) > 0
      ? "https://${b.hosts[0]}"
      : (length(var.domains) > 0 ? "https://${var.domains[0]}" : "https://${local.address}")
    )
  }
}

output "instance_group_self_links" {
  description = "Self links of the unmanaged instance groups created from backend_services instances."
  value       = { for k, g in google_compute_instance_group.backends : k => g.self_link }
}
