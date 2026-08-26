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

locals {
  # This label allows for billing report tracking based on module.
  labels = merge(var.labels, { ghpc_module = "https-load-balancer", ghpc_role = "network" })
}

locals {
  prefix = "${substr(var.deployment_name, 0, 30)}-${var.name}"

  # Google's health check probes originate here. A backend that admits no
  # traffic from these ranges fails every probe and never serves.
  health_check_ranges = ["35.191.0.0/16", "130.211.0.0/22"]

  managed_certificate = length(var.domains) > 0
  iap_oauth_client    = var.oauth2_client_id != null

  backends = { for b in var.backend_services : b.name => b }

  root_redirect_hosts = var.root_redirect == null ? [] : var.root_redirect.hosts

  # One pool catches everything the host rules do not. It may also own
  # hostnames of its own, so this is a flag rather than an absence of hosts.
  default_backend = one([for b in var.backend_services : b.name if b.default])
  routed_backends = { for b in var.backend_services : b.name => b if length(b.hosts) > 0 }

  # Unmanaged instance groups are zonal, so one per backend service per zone.
  # Flattened to a single map because for_each takes one collection.
  instance_groups = merge([
    for b in var.backend_services : {
      for i in b.instances : "${b.name}-${i.zone}" => {
        backend    = b.name
        zone       = i.zone
        self_links = i.self_links
        port_name  = b.port_name
        port       = b.port
      }
    }
  ]...)

  # Groups this module creates for a backend, plus any the caller already had.
  groups_for = {
    for name, b in local.backends : name => concat(
      [for key, g in google_compute_instance_group.backends : g.self_link if local.instance_groups[key].backend == name],
      b.instance_groups,
    )
  }

  # One firewall rule covering every port any backend serves or is probed on.
  probe_ports = distinct(flatten([
    for b in var.backend_services : [
      tostring(b.port),
      tostring(coalesce(b.health_check.port, b.port)),
    ]
  ]))
}

###############################################################################
# Preconditions
#
# Each of these is a configuration that applies cleanly and then fails at
# runtime in a way that is slow to diagnose, so fail at plan time instead.
###############################################################################

resource "terraform_data" "validation" {
  lifecycle {
    precondition {
      condition     = length(var.domains) > 0 || length(var.ssl_certificates) > 0
      error_message = "Set either domains, for a Google-managed certificate, or ssl_certificates. An HTTPS load balancer cannot serve without one."
    }

    precondition {
      condition     = !(length(var.domains) > 0 && length(var.ssl_certificates) > 0)
      error_message = "domains and ssl_certificates are mutually exclusive: choose a Google-managed certificate or supply your own."
    }

    precondition {
      # A hostname routed here but absent from the certificate fails TLS before
      # routing is ever reached, which looks like a broken load balancer rather
      # than a missing name.
      condition = !local.managed_certificate || alltrue(flatten([
        for b in var.backend_services : [for h in b.hosts : contains(var.domains, h)]
      ]))
      error_message = "Every hostname in backend_services hosts must also appear in domains, or requests to it fail TLS before routing is considered."
    }

    precondition {
      condition = !local.managed_certificate || alltrue([
        for h in local.root_redirect_hosts : contains(var.domains, h)
      ])
      error_message = "Every hostname in root_redirect.hosts must also appear in domains, or requests to it fail TLS before the redirect is reached."
    }

    precondition {
      # A hostname cannot both redirect its root and route to its own pool.
      condition = length(setintersection(
        toset(local.root_redirect_hosts),
        toset(flatten([for b in var.backend_services : b.hosts])),
      )) == 0
      error_message = "A hostname in root_redirect.hosts also appears in a backend_services entry's hosts. Choose one: a landing page, or a pool of its own."
    }

    precondition {
      condition     = !var.create_health_check_firewall || var.network_self_link != null
      error_message = "network_self_link is required when create_health_check_firewall is true. Set it, or set create_health_check_firewall = false if an equivalent rule already exists."
    }

    precondition {
      condition     = !var.create_health_check_firewall || length(var.target_tags) > 0
      error_message = "target_tags is required when create_health_check_firewall is true, so the rule reaches only the intended instances."
    }

    precondition {
      condition     = (var.oauth2_client_id == null) == (var.oauth2_client_secret == null)
      error_message = "oauth2_client_id and oauth2_client_secret must be set together, or both left null to use a Google-managed IAP client."
    }

    precondition {
      condition     = !var.enable_iap || length(var.iap_members) > 0
      error_message = "enable_iap is set but iap_members is empty, which would deny everyone including you. Grant at least one principal."
    }
  }
}

###############################################################################
# Address
###############################################################################

data "google_compute_global_address" "existing" {
  count   = var.address_name != null ? 1 : 0
  project = var.project_id
  name    = var.address_name
}

resource "google_compute_global_address" "lb" {
  count   = var.address_name == null ? 1 : 0
  project = var.project_id
  name    = "${local.prefix}-ip"
  labels  = local.labels

  description = "External address for the ${local.prefix} HTTPS load balancer."
}

locals {
  address = var.address_name != null ? data.google_compute_global_address.existing[0].address : google_compute_global_address.lb[0].address
}

###############################################################################
# Backends
###############################################################################

resource "google_compute_instance_group" "backends" {
  for_each = local.instance_groups

  project   = var.project_id
  name      = "${local.prefix}-${each.key}"
  zone      = each.value.zone
  instances = each.value.self_links

  named_port {
    name = each.value.port_name
    port = each.value.port
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_health_check" "lb" {
  for_each = local.backends

  project = var.project_id
  name    = "${local.prefix}-${each.key}-hc"

  check_interval_sec  = each.value.health_check.check_interval_sec
  timeout_sec         = each.value.health_check.timeout_sec
  healthy_threshold   = each.value.health_check.healthy_threshold
  unhealthy_threshold = each.value.health_check.unhealthy_threshold

  dynamic "http_health_check" {
    for_each = upper(each.value.health_check.protocol) == "HTTP" ? [1] : []
    content {
      port         = coalesce(each.value.health_check.port, each.value.port)
      request_path = each.value.health_check.request_path
    }
  }

  dynamic "https_health_check" {
    for_each = upper(each.value.health_check.protocol) == "HTTPS" ? [1] : []
    content {
      port         = coalesce(each.value.health_check.port, each.value.port)
      request_path = each.value.health_check.request_path
    }
  }

  dynamic "http2_health_check" {
    for_each = upper(each.value.health_check.protocol) == "HTTP2" ? [1] : []
    content {
      port         = coalesce(each.value.health_check.port, each.value.port)
      request_path = each.value.health_check.request_path
    }
  }

  dynamic "tcp_health_check" {
    for_each = upper(each.value.health_check.protocol) == "TCP" ? [1] : []
    content {
      port = coalesce(each.value.health_check.port, each.value.port)
    }
  }
}

resource "google_compute_backend_service" "lb" {
  for_each = local.backends

  project = var.project_id
  name    = "${local.prefix}-${each.key}-backend"

  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = upper(each.value.protocol)
  port_name             = each.value.port_name
  health_checks         = [google_compute_health_check.lb[each.key].id]

  timeout_sec                     = each.value.timeout_sec
  session_affinity                = upper(each.value.session_affinity)
  affinity_cookie_ttl_sec         = each.value.affinity_cookie_ttl_sec
  connection_draining_timeout_sec = each.value.connection_draining_timeout_sec
  enable_cdn                      = each.value.enable_cdn
  security_policy                 = each.value.security_policy

  # Iterated as a list rather than a set: group self links are unknown until
  # the instance groups are created, and toset() on unknown values makes the
  # collection itself unknown, which for_each cannot plan over.
  dynamic "backend" {
    for_each = local.groups_for[each.key]
    content {
      group = backend.value
    }
  }

  dynamic "iap" {
    for_each = var.enable_iap ? [1] : []
    content {
      enabled = true
      # Omitted entirely for a Google-managed client, which is the default and
      # needs no OAuth client or redirect URI to be configured.
      oauth2_client_id     = local.iap_oauth_client ? var.oauth2_client_id : null
      oauth2_client_secret = local.iap_oauth_client ? var.oauth2_client_secret : null
    }
  }

  log_config {
    enable      = var.enable_logging
    sample_rate = var.enable_logging ? var.logging_sample_rate : null
  }

  depends_on = [terraform_data.validation]
}

###############################################################################
# Health check ingress
###############################################################################

resource "google_compute_firewall" "health_check" {
  count = var.create_health_check_firewall ? 1 : 0

  project = var.project_id
  name    = "${local.prefix}-hc-allow"
  network = var.network_self_link

  description = "Admits Google's health check ranges to the ${local.prefix} backends."

  direction     = "INGRESS"
  source_ranges = local.health_check_ranges
  target_tags   = var.target_tags

  allow {
    protocol = "tcp"
    ports    = local.probe_ports
  }
}

###############################################################################
# Certificates and routing
###############################################################################

resource "google_compute_managed_ssl_certificate" "lb" {
  count = local.managed_certificate ? 1 : 0

  project = var.project_id
  name    = "${local.prefix}-cert"

  managed {
    domains = var.domains
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_url_map" "lb" {
  project         = var.project_id
  name            = "${local.prefix}-urlmap"
  default_service = google_compute_backend_service.lb[local.default_backend].id

  dynamic "host_rule" {
    for_each = local.routed_backends
    content {
      hosts        = host_rule.value.hosts
      path_matcher = host_rule.key
    }
  }

  dynamic "host_rule" {
    for_each = length(local.root_redirect_hosts) > 0 ? [1] : []
    content {
      hosts        = local.root_redirect_hosts
      path_matcher = local.root_redirect_matcher
    }
  }

  dynamic "path_matcher" {
    for_each = length(local.root_redirect_hosts) > 0 ? [1] : []
    content {
      name            = local.root_redirect_matcher
      default_service = google_compute_backend_service.lb[local.default_backend].id

      path_rule {
        # Exact "/" only, so assets and other paths still reach the backend.
        paths = ["/"]
        url_redirect {
          path_redirect          = var.root_redirect.path
          redirect_response_code = "FOUND"
          strip_query            = false
        }
      }
    }
  }

  dynamic "path_matcher" {
    for_each = local.routed_backends
    content {
      name            = path_matcher.key
      default_service = google_compute_backend_service.lb[path_matcher.key].id

      dynamic "path_rule" {
        for_each = length(path_matcher.value.paths) > 0 ? [1] : []
        content {
          paths   = path_matcher.value.paths
          service = google_compute_backend_service.lb[path_matcher.key].id
        }
      }
    }
  }
}

locals {
  # Redirected hosts share one matcher; its default service keeps other paths
  # on that hostname working.
  root_redirect_matcher = "root-redirect"
}

resource "google_compute_target_https_proxy" "lb" {
  project = var.project_id
  name    = "${local.prefix}-https-proxy"
  url_map = google_compute_url_map.lb.id

  ssl_certificates = local.managed_certificate ? [google_compute_managed_ssl_certificate.lb[0].id] : var.ssl_certificates
  ssl_policy       = var.ssl_policy
}

resource "google_compute_global_forwarding_rule" "https" {
  project    = var.project_id
  name       = "${local.prefix}-https"
  labels     = local.labels
  target     = google_compute_target_https_proxy.lb.id
  ip_address = local.address
  port_range = "443"

  load_balancing_scheme = "EXTERNAL_MANAGED"
}

###############################################################################
# Optional HTTP to HTTPS redirect
###############################################################################

resource "google_compute_url_map" "redirect" {
  count = var.enable_http_redirect ? 1 : 0

  project = var.project_id
  name    = "${local.prefix}-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  count = var.enable_http_redirect ? 1 : 0

  project = var.project_id
  name    = "${local.prefix}-http-proxy"
  url_map = google_compute_url_map.redirect[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count = var.enable_http_redirect ? 1 : 0

  project    = var.project_id
  name       = "${local.prefix}-http"
  labels     = local.labels
  target     = google_compute_target_http_proxy.redirect[0].id
  ip_address = local.address
  port_range = "80"

  load_balancing_scheme = "EXTERNAL_MANAGED"
}

###############################################################################
# IAP access
###############################################################################

module "iap_policy" {
  source   = "../../../../modules/iam/iap-policy"
  for_each = var.enable_iap ? local.backends : {}

  project_id         = var.project_id
  backend_service_id = google_compute_backend_service.lb[each.key].name
  iap_members        = var.iap_members
}
