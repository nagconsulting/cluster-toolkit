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

variable "install_root" {
  description = "Directory under which the broker and front-end assets are installed."
  type        = string
  default     = "/opt/ghpc-remote-desktop"
}

variable "network_storage" {
  description = "An array of network attached storage mounts to be configured."
  type = list(object({
    server_ip             = string
    remote_mount          = string
    local_mount           = string
    fs_type               = string
    mount_options         = string
    client_install_runner = map(string)
    mount_runner          = map(string)
  }))
  default = []
}

variable "startup_script" {
  description = "Optional additional startup script prepended before the desktop runtime setup."
  type        = string
  default     = null
}

variable "slurm_auth_mode" {
  description = "Slurm authentication mode on the host: none, munge, native or auto."
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "munge", "native", "auto"], lower(trimspace(var.slurm_auth_mode)))
    error_message = "slurm_auth_mode must be one of: none, munge, native, auto."
  }
}

variable "vnc_backend" {
  description = "VNC server backend for per-user sessions: tigervnc or turbovnc."
  type        = string
  default     = "tigervnc"

  validation {
    condition     = contains(["tigervnc", "turbovnc"], lower(trimspace(var.vnc_backend)))
    error_message = "vnc_backend must be one of: tigervnc, turbovnc."
  }
}

variable "enable_gpu_acceleration" {
  description = "Use hardware OpenGL for desktop sessions where a usable GPU is present."
  type        = bool
  default     = false
}

variable "session_resolution" {
  description = "Desktop resolution used for each per-user session."
  type        = string
  default     = "1920x1080"
}

variable "vnc_display_number" {
  description = "First X display number reserved for per-user sessions."
  type        = number
  default     = 1
}

variable "max_user_sessions" {
  description = "Maximum number of concurrent per-user desktop sessions."
  type        = number
  default     = 32
}

variable "session_idle_timeout_seconds" {
  description = "Idle timeout after which a session is cleaned up. 0 disables cleanup."
  type        = number
  default     = 43200
}

variable "broker_listen_port" {
  description = "Port on which the broker accepts requests from the fronting proxy."
  type        = number
  default     = 6080
}

variable "identity_mode" {
  description = <<-EOT
    How the broker establishes which user a request belongs to.

    "trusted_proxy" takes the identity from request headers with no
    verification, so it is only safe where an authenticating proxy is the sole
    route to the broker.

    "iap" verifies the assertion Identity-Aware Proxy signs onto every request
    it forwards, checking signature, issuer and audience. Nothing is trusted on
    the caller's word, so the broker may be reached directly without becoming
    impersonatable.
    EOT
  type        = string
  default     = "trusted_proxy"

  validation {
    condition     = contains(["trusted_proxy", "iap"], lower(trimspace(var.identity_mode)))
    error_message = "identity_mode must be one of: trusted_proxy, iap."
  }
}

variable "identity_audience" {
  description = <<-EOT
    Audience an IAP assertion must carry, of the form
    /projects/PROJECT_NUMBER/global/backendServices/BACKEND_ID.

    The audience is the security boundary: without it an assertion minted for
    any other IAP-protected service in any project would verify here. Set this
    or iap_backend_service when identity_mode is "iap".
    EOT
  type        = string
  default     = null
}

variable "iap_backend_service" {
  description = <<-EOT
    Name of the backend service fronting this host, from which the broker
    resolves the expected audience through the Compute API at first use.

    Use this rather than identity_audience to avoid a dependency cycle: the
    audience contains the backend service's numeric ID, which does not exist
    until the load balancer is built, while the load balancer needs the
    instances. The name is chosen in Terraform, so it is known in advance.

    The instance service account needs roles/compute.viewer to read it.
    EOT
  type        = string
  default     = null
}

variable "secret_project_id" {
  description = "Project holding the Secret Manager secrets. Defaults to the instance's own project."
  type        = string
  default     = null
}

variable "proxy_secret" {
  description = <<-EOT
    Shared secret the broker requires in the X-Cluster-Desktop-Secret header,
    supplied directly. Mutually exclusive with proxy_secret_id.

    Use this where the caller already owns the value and has to hold the
    plaintext anyway - a front end that sends the header on every request, for
    instance, gains nothing from a round trip through Secret Manager. Otherwise
    prefer proxy_secret_id: a literal is carried in the startup script staged in
    Cloud Storage and appears in Terraform state.
    EOT
  type        = string
  sensitive   = true
  default     = null
}

variable "proxy_secret_id" {
  description = <<-EOT
    Secret Manager secret ID holding the shared secret the broker requires in
    the X-Cluster-Desktop-Secret header. Mutually exclusive with proxy_secret.

    Fetched on the instance at boot, so the value never enters Terraform state
    or the startup script staged in Cloud Storage. The instance service account
    needs roles/secretmanager.secretAccessor.
    EOT
  type        = string
  default     = null
}

variable "proxy_secret_version" {
  description = "Version of proxy_secret_id to read."
  type        = string
  default     = "latest"
}

variable "novnc_version" {
  description = "noVNC release version to install. Only used when front_end is novnc."
  type        = string
  default     = "1.7.0"
}

variable "desktop_index" {
  description = <<-EOT
    Desktops to list on the chooser page, each with a name and the URL that
    reaches it. Served by every host, so a user finds the list wherever they
    land rather than depending on one host staying up.

    Build it from the load balancer's own backend services, so the page cannot
    advertise a desktop that was never deployed.

    Example:
      desktop_index:
      - name: Visualisation
        url: https://viz.example.com
        description: GPU accelerated
    EOT
  type = list(object({
    name        = string
    url         = string
    description = optional(string, "")
  }))
  default = []
}

variable "desktop_index_path" {
  description = <<-EOT
    Path at which the chooser is served, for example "/desktops". Empty
    disables it.

    Must not be "/", which is where the desktop itself is served, and cannot be
    "/healthz", which is deliberately unauthenticated for load balancer probes.
    EOT
  type        = string
  default     = ""
}

variable "desktop_endpoint_dir" {
  description = "Optional directory where the runtime publishes DESKTOP_* endpoint metadata."
  type        = string
  default     = null
}

variable "desktop_endpoint_name" {
  description = "Endpoint metadata file name used when desktop_endpoint_dir is set."
  type        = string
  default     = "desktop"
}
