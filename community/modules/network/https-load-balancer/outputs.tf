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

output "backend_service_id" {
  description = "Full resource ID of the backend service."
  value       = google_compute_backend_service.lb.id
}

output "backend_service_name" {
  description = <<-EOT
    Name of the backend service. A workload verifying IAP assertions needs this
    to resolve the audience they are minted for.
    EOT
  value       = google_compute_backend_service.lb.name
}

output "backend_service_self_link" {
  description = "Self link of the backend service, for use in another load balancer's url_map_rules."
  value       = google_compute_backend_service.lb.self_link
}

output "ip_address" {
  description = "External IP address the load balancer serves on. Point DNS here."
  value       = local.address
}

output "url" {
  description = "HTTPS URL of the load balancer, using the first configured domain where there is one."
  value       = length(var.domains) > 0 ? "https://${var.domains[0]}" : "https://${local.address}"
}

output "instance_group_self_links" {
  description = "Self links of the unmanaged instance groups created from var.instances."
  value       = [for g in google_compute_instance_group.backends : g.self_link]
}
