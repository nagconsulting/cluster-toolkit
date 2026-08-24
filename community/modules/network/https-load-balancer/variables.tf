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

variable "backend_services" {
  description = <<-EOT
    Pools of servers behind this load balancer, one backend service each.

    One entry is the common case. Use several where the pools are not
    interchangeable - a CPU and a GPU desktop pool, say - and give each its own
    hosts so a request reaches the right one deterministically. They share this
    load balancer's address, certificate and proxy.

    Exactly one entry must have no hosts: it serves anything matching no other
    rule, and is what a bare visit to the domain reaches.

    Fields that are easy to get wrong:

      timeout_sec       lifetime of a connection, NOT an idle timeout. Anything
                        serving WebSockets, SSE or long polls must raise it well
                        above the Google default of 30 seconds, or such a
                        connection is closed mid-stream roughly every 30 seconds
                        with nothing logged to explain it.
      session_affinity  keeps a client returning to the same backend, needed
                        where a backend holds per-user state its siblings cannot
                        serve. Best effort: it lapses when the cookie expires or
                        the client address changes, and the client then reaches
                        a backend with nothing for it. Where that is not
                        acceptable, give each pool its own hosts instead.
      health_check      the path must be reachable without authentication.
                        Probes come from Google's ranges and bypass IAP, so a
                        path behind a login check fails every probe and the
                        backend never serves.

    Example:
      backend_services:
      - name: viz
        instances:
        - zone: $(vars.zone)
          self_links: $(viz-desktop.self_links)
        port: 6080
        port_name: novnc
        timeout_sec: 86400
        session_affinity: GENERATED_COOKIE
        health_check:
          request_path: /healthz
    EOT
  type = list(object({
    name = string
    instances = optional(list(object({
      zone       = string
      self_links = list(string)
    })), [])
    instance_groups                 = optional(list(string), [])
    port                            = optional(number, 80)
    port_name                       = optional(string, "http")
    protocol                        = optional(string, "HTTP")
    timeout_sec                     = optional(number, 30)
    session_affinity                = optional(string, "NONE")
    affinity_cookie_ttl_sec         = optional(number)
    connection_draining_timeout_sec = optional(number, 300)
    enable_cdn                      = optional(bool, false)
    security_policy                 = optional(string)
    health_check = optional(object({
      protocol            = optional(string, "HTTP")
      port                = optional(number)
      request_path        = optional(string, "/")
      check_interval_sec  = optional(number, 10)
      timeout_sec         = optional(number, 5)
      healthy_threshold   = optional(number, 2)
      unhealthy_threshold = optional(number, 3)
    }), {})
    hosts = optional(list(string), [])
    paths = optional(list(string), ["/*"])
  }))

  validation {
    condition     = length(var.backend_services) > 0
    error_message = "At least one backend service is required."
  }

  validation {
    condition     = length(distinct([for b in var.backend_services : b.name])) == length(var.backend_services)
    error_message = "Each backend_services entry needs a distinct name; it becomes part of the backend service resource name."
  }

  validation {
    condition     = alltrue([for b in var.backend_services : can(regex("^[a-z]([-a-z0-9]{0,20}[a-z0-9])?$", b.name))])
    error_message = "Each backend_services name must be lowercase, up to 22 characters, starting with a letter."
  }

  validation {
    condition     = length([for b in var.backend_services : b.name if length(b.hosts) == 0]) == 1
    error_message = "Exactly one backend_services entry must have no hosts. That one serves anything matching no other rule; without it a bare visit to the domain has nowhere to go, and with two the routing is ambiguous."
  }

  validation {
    condition     = alltrue([for b in var.backend_services : length(b.instances) + length(b.instance_groups) > 0])
    error_message = "Every backend_services entry needs instances, instance_groups, or both."
  }

  validation {
    condition = alltrue(flatten([
      for b in var.backend_services : [
        for i in b.instances : can(regex("^[a-z]+-[a-z]+[0-9]+-[a-z]$", i.zone))
      ]
    ]))
    error_message = "Every instances entry needs a real zone such as us-central1-a. An unexpanded zone variable reaches the API as a literal and fails with a 403 naming no cause."
  }

  validation {
    condition     = alltrue([for b in var.backend_services : contains(["HTTP", "HTTPS", "HTTP2"], upper(trimspace(b.protocol)))])
    error_message = "backend_services protocol must be one of: HTTP, HTTPS, HTTP2."
  }

  validation {
    condition = alltrue([
      for b in var.backend_services : contains(
        ["NONE", "CLIENT_IP", "GENERATED_COOKIE", "HEADER_FIELD", "HTTP_COOKIE"],
        upper(trimspace(b.session_affinity))
      )
    ])
    error_message = "backend_services session_affinity must be one of: NONE, CLIENT_IP, GENERATED_COOKIE, HEADER_FIELD, HTTP_COOKIE."
  }

  validation {
    condition     = alltrue([for b in var.backend_services : contains(["HTTP", "HTTPS", "HTTP2", "TCP"], upper(trimspace(b.health_check.protocol)))])
    error_message = "backend_services health_check.protocol must be one of: HTTP, HTTPS, HTTP2, TCP."
  }

  validation {
    condition     = length(distinct(flatten([for b in var.backend_services : b.hosts]))) == length(flatten([for b in var.backend_services : b.hosts]))
    error_message = "A hostname may appear in only one backend_services entry."
  }
}

###############################################################################
# Health check ingress
###############################################################################

variable "create_health_check_firewall" {
  description = <<-EOT
    Create the ingress rule admitting Google's health check ranges,
    35.191.0.0/16 and 130.211.0.0/22, to every backend port on the tagged
    instances. Without a rule from these ranges every probe fails. Set false
    only where an equivalent rule already exists.
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

    Include every hostname named in backend_services hosts, or requests to those
    names fail TLS before routing is ever considered.

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

variable "enable_logging" {
  description = "Emit load balancer request logs for every backend service."
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

###############################################################################
# Identity-Aware Proxy
###############################################################################

variable "enable_iap" {
  description = <<-EOT
    Put Identity-Aware Proxy in front of every backend service, so Google
    authenticates each request before it reaches a backend and forwards a
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
    Principals granted roles/iap.httpsResourceAccessor on every backend service,
    and so allowed through IAP. For example ["user:someone@example.com",
    "group:team@example.com"].

    Enabling IAP without granting anyone this role locks everyone out,
    including the person who deployed it.
    EOT
  type        = set(string)
  default     = []
}
