## Description

Creates a global external Application Load Balancer in front of one or more
instance groups, optionally behind Identity-Aware Proxy.

Nothing about this module is workload-specific. It exists because Cluster
Toolkit has no way to put a cluster's web interface behind a Google-managed
front door: `modules/network/global-static-ip` reserves an address and
`modules/iam/iap-policy` grants access to a backend service, but nothing
creates the backend service, health check, URL map, target proxy, forwarding
rule or certificate between them.

Suitable for any HTTP service running on cluster VMs - a remote desktop broker,
a notebook server, a dashboard.

## Example

```yaml
  - id: desktop-lb
    source: community/modules/network/https-load-balancer
    settings:
      project_id: $(vars.project_id)
      deployment_name: $(vars.deployment_name)
      name: vdi

      backend_instances:
      - zone: us-central1-a
        self_links: $(viz-desktop.self_links)
      port: 6080
      port_name: novnc

      timeout_sec: 86400
      session_affinity: GENERATED_COOKIE
      health_check:
        request_path: /healthz

      network_self_link: $(network.network_self_link)
      target_tags: [$(viz-desktop.network_tag)]

      address_name: vdi
      domains: [desktop.example.com]

      enable_iap: true
      iap_members: [user:someone@example.com]
```

## Two settings that are wrong by default for interactive traffic

**`timeout_sec` is the lifetime of a connection, not an idle timeout.** It
defaults to 30 seconds. A WebSocket, an SSE stream or a long poll is therefore
closed roughly every 30 seconds, mid-stream, and the backend logs nothing to
explain it. Any interactive service needs this raised.

**`session_affinity` defaults to `NONE`.** Where a backend holds per-user state
that its siblings cannot serve - an interactive session pinned to one host - a
request that lands elsewhere finds nothing. Affinity is best effort: it lapses
when the cookie expires or the client's address changes. Where that is not
acceptable, give each backend its own hostname with `url_map_rules` instead.

## Certificates and DNS

A Google-managed certificate only validates once `domains` already resolve to
this load balancer's address, and provisioning then takes roughly 15 to 60
minutes. Until it completes the load balancer serves errors, which looks like a
failed deploy.

Reserve the address and create the DNS record *before* the first apply, then
pass the address by name:

```sh
gcloud compute addresses create vdi --global --ip-version=IPV4
gcloud compute addresses describe vdi --global --format='value(address)'
```

Leaving `address_name` unset makes the module create an address instead, which
means DNS cannot exist until after the first apply and the certificate cannot
validate until a second one.

## Identity-Aware Proxy

With `enable_iap`, Google authenticates every request before it reaches a
backend and forwards a signed assertion naming the user. Backends should verify
that assertion rather than trusting a header.

`oauth2_client_id` is optional. Left unset, IAP uses a Google-managed client:
no OAuth client to create, no redirect URI to configure, no client secret to
store. Supply one only where the consent screen must be controlled directly, in
which case its authorised redirect URI is
`https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect`.

Health probes come from Google's ranges and bypass IAP, so `health_check.
request_path` must be reachable without authentication or every probe fails and
the backend never serves.

Enabling IAP without granting anyone `iap_members` locks out everyone,
including whoever deployed it. The module refuses that configuration.

## License

<!-- BEGINNING OF PRE-COMMIT-TERRAFORM DOCS HOOK -->
## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.12.2 |
| <a name="requirement_google"></a> [google](#requirement\_google) | >= 4.42 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_google"></a> [google](#provider\_google) | >= 4.42 |
| <a name="provider_terraform"></a> [terraform](#provider\_terraform) | n/a |

## Modules

| Name | Source | Version |
| ---- | ------ | ------- |
| <a name="module_iap_policy"></a> [iap\_policy](#module\_iap\_policy) | ../../../../modules/iam/iap-policy | n/a |

## Resources

| Name | Type |
| ---- | ---- |
| [google_compute_backend_service.lb](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_backend_service) | resource |
| [google_compute_firewall.health_check](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_firewall) | resource |
| [google_compute_global_address.lb](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_global_address) | resource |
| [google_compute_global_forwarding_rule.http](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_global_forwarding_rule) | resource |
| [google_compute_global_forwarding_rule.https](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_global_forwarding_rule) | resource |
| [google_compute_health_check.lb](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_health_check) | resource |
| [google_compute_instance_group.backends](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_instance_group) | resource |
| [google_compute_managed_ssl_certificate.lb](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_managed_ssl_certificate) | resource |
| [google_compute_target_http_proxy.redirect](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_target_http_proxy) | resource |
| [google_compute_target_https_proxy.lb](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_target_https_proxy) | resource |
| [google_compute_url_map.lb](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_url_map) | resource |
| [google_compute_url_map.redirect](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_url_map) | resource |
| [terraform_data.validation](https://registry.terraform.io/providers/hashicorp/terraform/latest/docs/resources/data) | resource |
| [google_compute_global_address.existing](https://registry.terraform.io/providers/hashicorp/google/latest/docs/data-sources/compute_global_address) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_address_name"></a> [address\_name](#input\_address\_name) | Name of an existing global external address to serve on. When null, one is<br/>created for this load balancer.<br/><br/>Reserve the address ahead of the first apply when using a Google-managed<br/>certificate: the certificate only validates once DNS already resolves to the<br/>address, so letting Terraform mint it means the first apply cannot succeed<br/>until a second one. The global-static-ip module can reserve one, or use<br/>gcloud directly. | `string` | `null` | no |
| <a name="input_affinity_cookie_ttl_sec"></a> [affinity\_cookie\_ttl\_sec](#input\_affinity\_cookie\_ttl\_sec) | Lifetime of the affinity cookie when session\_affinity is GENERATED\_COOKIE. Null uses the Google default. | `number` | `null` | no |
| <a name="input_backend_instances"></a> [backend\_instances](#input\_backend\_instances) | Instances to serve, grouped by zone. An unmanaged instance group is created<br/>per entry. Use this for individual VMs, such as those from the vm-instance<br/>module.<br/><br/>A list rather than a map keyed by zone because Cluster Toolkit expands<br/>blueprint variables in values but not in mapping keys, so a zone key of<br/>$(vars.zone) would reach Terraform unexpanded.<br/><br/>Example:<br/>  backend\_instances:<br/>  - zone: $(vars.zone)<br/>    self\_links: $(viz-desktop.self\_links) | <pre>list(object({<br/>    zone       = string<br/>    self_links = list(string)<br/>  }))</pre> | `[]` | no |
| <a name="input_connection_draining_timeout_sec"></a> [connection\_draining\_timeout\_sec](#input\_connection\_draining\_timeout\_sec) | How long existing requests may finish after a backend is removed. | `number` | `300` | no |
| <a name="input_create_health_check_firewall"></a> [create\_health\_check\_firewall](#input\_create\_health\_check\_firewall) | Create the ingress rule admitting Google's health check ranges,<br/>35.191.0.0/16 and 130.211.0.0/22, to var.port on the tagged instances.<br/>Without a rule from these ranges every probe fails. Set false only where an<br/>equivalent rule already exists. | `bool` | `true` | no |
| <a name="input_deployment_name"></a> [deployment\_name](#input\_deployment\_name) | Cluster Toolkit deployment name. Used to prefix resource names. | `string` | n/a | yes |
| <a name="input_domains"></a> [domains](#input\_domains) | Domains for a Google-managed TLS certificate. Each must already resolve to<br/>this load balancer's address, or the certificate stays in PROVISIONING and<br/>the load balancer serves errors.<br/><br/>Mutually exclusive with ssl\_certificates. Provisioning typically takes 15 to<br/>60 minutes on first apply. | `list(string)` | `[]` | no |
| <a name="input_enable_cdn"></a> [enable\_cdn](#input\_enable\_cdn) | Serve responses through Cloud CDN. Leave off for dynamic or per-user content. | `bool` | `false` | no |
| <a name="input_enable_http_redirect"></a> [enable\_http\_redirect](#input\_enable\_http\_redirect) | Also listen on port 80 and redirect to HTTPS. | `bool` | `true` | no |
| <a name="input_enable_iap"></a> [enable\_iap](#input\_enable\_iap) | Put Identity-Aware Proxy in front of the backend service, so Google<br/>authenticates every request before it reaches a backend and forwards a<br/>signed assertion of who the user is. | `bool` | `false` | no |
| <a name="input_enable_logging"></a> [enable\_logging](#input\_enable\_logging) | Emit load balancer request logs. | `bool` | `false` | no |
| <a name="input_health_check"></a> [health\_check](#input\_health\_check) | Health check applied to the backends. The path must be reachable without<br/>authentication: health probes come from Google's ranges and bypass IAP, so a<br/>path behind a login check fails every probe and the backend never serves. | <pre>object({<br/>    protocol            = optional(string, "HTTP")<br/>    port                = optional(number)<br/>    request_path        = optional(string, "/")<br/>    check_interval_sec  = optional(number, 10)<br/>    timeout_sec         = optional(number, 5)<br/>    healthy_threshold   = optional(number, 2)<br/>    unhealthy_threshold = optional(number, 3)<br/>  })</pre> | `{}` | no |
| <a name="input_iap_members"></a> [iap\_members](#input\_iap\_members) | Principals granted roles/iap.httpsResourceAccessor, and so allowed through<br/>IAP. For example ["user:someone@example.com", "group:team@example.com"].<br/><br/>Enabling IAP without granting anyone this role locks everyone out,<br/>including the person who deployed it. | `set(string)` | `[]` | no |
| <a name="input_instance_groups"></a> [instance\_groups](#input\_instance\_groups) | Self links of existing instance groups to serve, managed or unmanaged. Use<br/>this for a MIG, for example the self\_link output of the mig module. Combined<br/>with any groups created from var.backend\_instances.<br/><br/>Each group must expose a named port matching var.port\_name. | `list(string)` | `[]` | no |
| <a name="input_labels"></a> [labels](#input\_labels) | Labels to add to the resources that accept them. | `map(string)` | `{}` | no |
| <a name="input_logging_sample_rate"></a> [logging\_sample\_rate](#input\_logging\_sample\_rate) | Fraction of requests logged when enable\_logging is true, between 0.0 and 1.0. | `number` | `1` | no |
| <a name="input_name"></a> [name](#input\_name) | Short name distinguishing this load balancer from others in the same deployment. | `string` | `"lb"` | no |
| <a name="input_network_self_link"></a> [network\_self\_link](#input\_network\_self\_link) | Self link of the network holding the backends. Required when create\_health\_check\_firewall is true. | `string` | `null` | no |
| <a name="input_oauth2_client_id"></a> [oauth2\_client\_id](#input\_oauth2\_client\_id) | OAuth client ID for IAP. Leave null to use a Google-managed client, which<br/>needs no client to be created and no redirect URI to be configured.<br/><br/>Supply a client only where the consent screen must be controlled directly.<br/>Its authorised redirect URI is then<br/>https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect | `string` | `null` | no |
| <a name="input_oauth2_client_secret"></a> [oauth2\_client\_secret](#input\_oauth2\_client\_secret) | OAuth client secret matching oauth2\_client\_id. Required when that is set. | `string` | `null` | no |
| <a name="input_port"></a> [port](#input\_port) | Port on the backends that serves traffic. | `number` | `80` | no |
| <a name="input_port_name"></a> [port\_name](#input\_port\_name) | Named port used by the backend service to find var.port on each group.<br/>Instance groups created from var.backend\_instances are given this name<br/>automatically; existing groups in var.instance\_groups must already define<br/>it. | `string` | `"http"` | no |
| <a name="input_project_id"></a> [project\_id](#input\_project\_id) | Project in which Google Cloud resources will be created. | `string` | n/a | yes |
| <a name="input_protocol"></a> [protocol](#input\_protocol) | Protocol the load balancer speaks to the backends. | `string` | `"HTTP"` | no |
| <a name="input_security_policy"></a> [security\_policy](#input\_security\_policy) | Self link of a Cloud Armor security policy to attach to the backend service. | `string` | `null` | no |
| <a name="input_session_affinity"></a> [session\_affinity](#input\_session\_affinity) | Keeps a client returning to the same backend. Required when a backend holds<br/>per-user state that other backends cannot serve, such as an interactive<br/>session pinned to one host.<br/><br/>One of: NONE, CLIENT\_IP, GENERATED\_COOKIE, HEADER\_FIELD, HTTP\_COOKIE.<br/><br/>Affinity is best effort: it lapses when the cookie expires or the client's<br/>address changes, and the client then reaches a backend that has no state for<br/>it. Where that is not acceptable, route each backend under its own host or<br/>path with var.url\_map\_rules instead. | `string` | `"NONE"` | no |
| <a name="input_ssl_certificates"></a> [ssl\_certificates](#input\_ssl\_certificates) | Self links of existing SSL certificates to serve, instead of a Google-managed one. Mutually exclusive with domains. | `list(string)` | `[]` | no |
| <a name="input_ssl_policy"></a> [ssl\_policy](#input\_ssl\_policy) | Self link of an SSL policy constraining TLS versions and ciphers. Null uses the Google default. | `string` | `null` | no |
| <a name="input_target_tags"></a> [target\_tags](#input\_target\_tags) | Network tags the health check firewall rule applies to. Must match tags on the backend instances. | `list(string)` | `[]` | no |
| <a name="input_timeout_sec"></a> [timeout\_sec](#input\_timeout\_sec) | How long the load balancer waits on a backend response before giving up.<br/><br/>This is the whole lifetime of a streamed or upgraded connection, not an idle<br/>timeout, so any backend serving WebSockets, server-sent events or long polls<br/>must raise it well above the Google default of 30 seconds. Left at the<br/>default, such a connection is closed mid-stream roughly every 30 seconds and<br/>the backend logs nothing to explain it. | `number` | `30` | no |
| <a name="input_url_map_rules"></a> [url\_map\_rules](#input\_url\_map\_rules) | Host and path routing to backends other than the default. Use this to give<br/>each backend its own hostname or path prefix, which reaches a specific<br/>backend deterministically rather than relying on session affinity.<br/><br/>Each entry routes its hosts, and optionally specific path prefixes, to the<br/>named backend service self link.<br/><br/>Example:<br/>  url\_map\_rules = [{<br/>    hosts           = ["viz1.example.com"]<br/>    backend\_service = module.other\_lb.backend\_service\_id<br/>  }] | <pre>list(object({<br/>    hosts           = list(string)<br/>    backend_service = string<br/>    paths           = optional(list(string), ["/*"])<br/>  }))</pre> | `[]` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_backend_service_id"></a> [backend\_service\_id](#output\_backend\_service\_id) | Full resource ID of the backend service. |
| <a name="output_backend_service_name"></a> [backend\_service\_name](#output\_backend\_service\_name) | Name of the backend service. A workload verifying IAP assertions needs this<br/>to resolve the audience they are minted for. |
| <a name="output_backend_service_self_link"></a> [backend\_service\_self\_link](#output\_backend\_service\_self\_link) | Self link of the backend service, for use in another load balancer's url\_map\_rules. |
| <a name="output_instance_group_self_links"></a> [instance\_group\_self\_links](#output\_instance\_group\_self\_links) | Self links of the unmanaged instance groups created from var.backend\_instances. |
| <a name="output_ip_address"></a> [ip\_address](#output\_ip\_address) | External IP address the load balancer serves on. Point DNS here. |
| <a name="output_url"></a> [url](#output\_url) | HTTPS URL of the load balancer, using the first configured domain where there is one. |
<!-- END OF PRE-COMMIT-TERRAFORM DOCS HOOK -->
