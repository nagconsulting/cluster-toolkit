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

variable "project_id" {
  description = "Project in which Google Cloud resources will be created."
  type        = string
}

variable "deployment_name" {
  description = "Cluster Toolkit deployment name. Used to prefix resource names."
  type        = string
}

variable "name" {
  description = "Short name distinguishing this load balancer from others in the same deployment."
  type        = string
  default     = "lb"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,20}[a-z0-9])?$", var.name))
    error_message = "name must be a valid Compute Engine name component: lowercase, up to 22 characters, starting with a letter."
  }
}

variable "labels" {
  description = "Labels to add to the resources that accept them."
  type        = map(string)
  default     = {}
}

###############################################################################
# Backends
###############################################################################

variable "instances" {
  description = <<-EOT
    Instances to serve, as a map of zone to a list of instance self links. An
    unmanaged instance group is created per zone. Use this for individual VMs,
    such as those from the vm-instance module.

    Example:
      instances = {
        "us-central1-a" = [module.desktop.self_links[0]]
      }
    EOT
  type        = map(list(string))
  default     = {}
}

variable "instance_groups" {
  description = <<-EOT
    Self links of existing instance groups to serve, managed or unmanaged. Use
    this for a MIG, for example the self_link output of the mig module. Combined
    with any groups created from var.instances.

    Each group must expose a named port matching var.port_name.
    EOT
  type        = list(string)
  default     = []
}

variable "port" {
  description = "Port on the backends that serves traffic."
  type        = number
  default     = 80
}

variable "port_name" {
  description = <<-EOT
    Named port used by the backend service to find var.port on each group.
    Instance groups created from var.instances are given this name
    automatically; existing groups in var.instance_groups must already define
    it.
    EOT
  type        = string
  default     = "http"
}

variable "protocol" {
  description = "Protocol the load balancer speaks to the backends."
  type        = string
  default     = "HTTP"

  validation {
    condition     = contains(["HTTP", "HTTPS", "HTTP2"], upper(trimspace(var.protocol)))
    error_message = "protocol must be one of: HTTP, HTTPS, HTTP2."
  }
}

###############################################################################
# Backend behaviour
###############################################################################

variable "timeout_sec" {
  description = <<-EOT
    How long the load balancer waits on a backend response before giving up.

    This is the whole lifetime of a streamed or upgraded connection, not an idle
    timeout, so any backend serving WebSockets, server-sent events or long polls
    must raise it well above the Google default of 30 seconds. Left at the
    default, such a connection is closed mid-stream roughly every 30 seconds and
    the backend logs nothing to explain it.
    EOT
  type        = number
  default     = 30
}

variable "session_affinity" {
  description = <<-EOT
    Keeps a client returning to the same backend. Required when a backend holds
    per-user state that other backends cannot serve, such as an interactive
    session pinned to one host.

    One of: NONE, CLIENT_IP, GENERATED_COOKIE, HEADER_FIELD, HTTP_COOKIE.

    Affinity is best effort: it lapses when the cookie expires or the client's
    address changes, and the client then reaches a backend that has no state for
    it. Where that is not acceptable, route each backend under its own host or
    path with var.url_map_rules instead.
    EOT
  type        = string
  default     = "NONE"

  validation {
    condition = contains(
      ["NONE", "CLIENT_IP", "GENERATED_COOKIE", "HEADER_FIELD", "HTTP_COOKIE"],
      upper(trimspace(var.session_affinity))
    )
    error_message = "session_affinity must be one of: NONE, CLIENT_IP, GENERATED_COOKIE, HEADER_FIELD, HTTP_COOKIE."
  }
}

variable "affinity_cookie_ttl_sec" {
  description = "Lifetime of the affinity cookie when session_affinity is GENERATED_COOKIE. Null uses the Google default."
  type        = number
  default     = null
}

variable "connection_draining_timeout_sec" {
  description = "How long existing requests may finish after a backend is removed."
  type        = number
  default     = 300
}

variable "enable_cdn" {
  description = "Serve responses through Cloud CDN. Leave off for dynamic or per-user content."
  type        = bool
  default     = false
}

variable "enable_logging" {
  description = "Emit load balancer request logs."
  type        = bool
  default     = false
}

variable "logging_sample_rate" {
  description = "Fraction of requests logged when enable_logging is true, between 0.0 and 1.0."
  type        = number
  default     = 1.0

  validation {
    condition     = var.logging_sample_rate >= 0.0 && var.logging_sample_rate <= 1.0
    error_message = "logging_sample_rate must be between 0.0 and 1.0."
  }
}

variable "security_policy" {
  description = "Self link of a Cloud Armor security policy to attach to the backend service."
  type        = string
  default     = null
}

###############################################################################
# Health check
###############################################################################

variable "health_check" {
  description = <<-EOT
    Health check applied to the backends. The path must be reachable without
    authentication: health probes come from Google's ranges and bypass IAP, so a
    path behind a login check fails every probe and the backend never serves.
    EOT
  type = object({
    protocol            = optional(string, "HTTP")
    port                = optional(number)
    request_path        = optional(string, "/")
    check_interval_sec  = optional(number, 10)
    timeout_sec         = optional(number, 5)
    healthy_threshold   = optional(number, 2)
    unhealthy_threshold = optional(number, 3)
  })
  default = {}

  validation {
    condition     = contains(["HTTP", "HTTPS", "HTTP2", "TCP"], upper(trimspace(var.health_check.protocol)))
    error_message = "health_check.protocol must be one of: HTTP, HTTPS, HTTP2, TCP."
  }
}

variable "create_health_check_firewall" {
  description = <<-EOT
    Create the ingress rule admitting Google's health check ranges,
    35.191.0.0/16 and 130.211.0.0/22, to var.port on the tagged instances.
    Without a rule from these ranges every probe fails. Set false only where an
    equivalent rule already exists.
    EOT
  type        = bool
  default     = true
}

variable "network_self_link" {
  description = "Self link of the network holding the backends. Required when create_health_check_firewall is true."
  type        = string
  default     = null
}

variable "target_tags" {
  description = "Network tags the health check firewall rule applies to. Must match tags on the backend instances."
  type        = list(string)
  default     = []
}

###############################################################################
# Front end: address, certificates, routing
###############################################################################

variable "address_name" {
  description = <<-EOT
    Name of an existing global external address to serve on. When null, one is
    created for this load balancer.

    Reserve the address ahead of the first apply when using a Google-managed
    certificate: the certificate only validates once DNS already resolves to the
    address, so letting Terraform mint it means the first apply cannot succeed
    until a second one. The global-static-ip module can reserve one, or use
    gcloud directly.
    EOT
  type        = string
  default     = null
}

variable "domains" {
  description = <<-EOT
    Domains for a Google-managed TLS certificate. Each must already resolve to
    this load balancer's address, or the certificate stays in PROVISIONING and
    the load balancer serves errors.

    Mutually exclusive with ssl_certificates. Provisioning typically takes 15 to
    60 minutes on first apply.
    EOT
  type        = list(string)
  default     = []
}

variable "ssl_certificates" {
  description = "Self links of existing SSL certificates to serve, instead of a Google-managed one. Mutually exclusive with domains."
  type        = list(string)
  default     = []
}

variable "ssl_policy" {
  description = "Self link of an SSL policy constraining TLS versions and ciphers. Null uses the Google default."
  type        = string
  default     = null
}

variable "enable_http_redirect" {
  description = "Also listen on port 80 and redirect to HTTPS."
  type        = bool
  default     = true
}

variable "url_map_rules" {
  description = <<-EOT
    Host and path routing to backends other than the default. Use this to give
    each backend its own hostname or path prefix, which reaches a specific
    backend deterministically rather than relying on session affinity.

    Each entry routes its hosts, and optionally specific path prefixes, to the
    named backend service self link.

    Example:
      url_map_rules = [{
        hosts           = ["viz1.example.com"]
        backend_service = module.other_lb.backend_service_id
      }]
    EOT
  type = list(object({
    hosts           = list(string)
    backend_service = string
    paths           = optional(list(string), ["/*"])
  }))
  default = []
}

###############################################################################
# Identity-Aware Proxy
###############################################################################

variable "enable_iap" {
  description = <<-EOT
    Put Identity-Aware Proxy in front of the backend service, so Google
    authenticates every request before it reaches a backend and forwards a
    signed assertion of who the user is.
    EOT
  type        = bool
  default     = false
}

variable "oauth2_client_id" {
  description = <<-EOT
    OAuth client ID for IAP. Leave null to use a Google-managed client, which
    needs no client to be created and no redirect URI to be configured.

    Supply a client only where the consent screen must be controlled directly.
    Its authorised redirect URI is then
    https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect
    EOT
  type        = string
  default     = null
}

variable "oauth2_client_secret" {
  description = "OAuth client secret matching oauth2_client_id. Required when that is set."
  type        = string
  sensitive   = true
  default     = null
}

variable "iap_members" {
  description = <<-EOT
    Principals granted roles/iap.httpsResourceAccessor, and so allowed through
    IAP. For example ["user:someone@example.com", "group:team@example.com"].

    Enabling IAP without granting anyone this role locks everyone out,
    including the person who deployed it.
    EOT
  type        = set(string)
  default     = []
}
