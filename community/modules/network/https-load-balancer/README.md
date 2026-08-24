## Description

Creates a global external Application Load Balancer in front of one or more
instance groups, optionally behind Identity-Aware Proxy.

Nothing about this module is workload-specific. It exists because Cluster
Toolkit has no way to put a cluster's web interface behind a Google-managed
front door.

- `modules/network/global-static-ip` reserves an address and
- `modules/iam/iap-policy` grants access to a backend service, but nothing
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
      name: remote-desktop

      backend_services:
      - name: viz
        instances:
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

      address_name: remote-desktop
      domains: [desktop.example.com]

      enable_iap: true
      iap_members: [user:someone@example.com]
```

## Serving more than one pool

Several `backend_services` entries share one address, one certificate and one
proxy. Give each its own `hosts` and a request reaches the right pool by name:

```yaml
      backend_services:
      - name: cpu            # no hosts: serves anything unmatched
        instances: [...]
      - name: gpu
        hosts: [gpu.example.com]
        instances: [...]
      domains: [desktop.example.com, gpu.example.com]
```

Exactly one entry must have no `hosts`. Every hostname used must also appear in
`domains`, or requests to it fail TLS before routing is considered - the module
refuses both mistakes at plan time.

Prefer this over `session_affinity` wherever the pools are not
interchangeable. Affinity keeps a user on one host only while their cookie
lasts; hostnames route deterministically.

## Two settings that are wrong by default for interactive traffic

**`timeout_sec` is the lifetime of a connection, not an idle timeout.** It
defaults to 30 seconds. A WebSocket, an SSE stream or a long poll is therefore
closed roughly every 30 seconds, mid-stream, and the backend logs nothing to
explain it. Any interactive service needs this raised. Some possible options:

| Use case                          | `timeout_sec` |
|------------------------------------|---------------|
| Standard API / REST backend        | 30 (default)  |
| Long poll                          | 60–120        |
| SSE (server-sent events)           | 3600 (1 hr)   |
| WebSocket (chat, dashboards)       | 3600 (1 hr)   |
| WebSocket (remote desktop, Guacamole/RDP-style) | 86400 (24 hr) |
| File upload/download, batch jobs   | 3600–14400    |

**`session_affinity` defaults to `NONE`.** Where a backend holds per-user state
that its siblings cannot serve - an interactive session pinned to one host - a
request that lands elsewhere finds nothing. Affinity is best effort: it lapses
when the cookie expires or the client's address changes. Where that is not
acceptable, split the pools and route by hostname as above.

## Certificates and DNS

A Google-managed certificate only validates once `domains` already resolve to
this load balancer's address, and provisioning then takes roughly 15 to 60
minutes. Until it completes the load balancer serves errors, which looks like a
failed deploy.

Reserve the address and create the DNS record *before* the first apply, then
pass the address by name:

```sh
gcloud compute addresses create remote-desktop --global --ip-version=IPV4
gcloud compute addresses describe remote-desktop --global --format='value(address)'
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
| <a name="input_backend_services"></a> [backend\_services](#input\_backend\_services) | Pools of servers behind this load balancer, one backend service each.<br/><br/>One entry is the common case. Use several where the pools are not<br/>interchangeable - a CPU and a GPU desktop pool, say - and give each its own<br/>hosts so a request reaches the right one deterministically. They share this<br/>load balancer's address, certificate and proxy.<br/><br/>Exactly one entry must have no hosts: it serves anything matching no other<br/>rule, and is what a bare visit to the domain reaches.<br/><br/>Fields that are easy to get wrong:<br/><br/>  timeout\_sec       lifetime of a connection, NOT an idle timeout. Anything<br/>                    serving WebSockets, SSE or long polls must raise it well<br/>                    above the Google default of 30 seconds, or such a<br/>                    connection is closed mid-stream roughly every 30 seconds<br/>                    with nothing logged to explain it.<br/>  session\_affinity  keeps a client returning to the same backend, needed<br/>                    where a backend holds per-user state its siblings cannot<br/>                    serve. Best effort: it lapses when the cookie expires or<br/>                    the client address changes, and the client then reaches<br/>                    a backend with nothing for it. Where that is not<br/>                    acceptable, give each pool its own hosts instead.<br/>  health\_check      the path must be reachable without authentication.<br/>                    Probes come from Google's ranges and bypass IAP, so a<br/>                    path behind a login check fails every probe and the<br/>                    backend never serves.<br/><br/>Example:<br/>  backend\_services:<br/>  - name: viz<br/>    instances:<br/>    - zone: $(vars.zone)<br/>      self\_links: $(viz-desktop.self\_links)<br/>    port: 6080<br/>    port\_name: novnc<br/>    timeout\_sec: 86400<br/>    session\_affinity: GENERATED\_COOKIE<br/>    health\_check:<br/>      request\_path: /healthz | <pre>list(object({<br/>    name = string<br/>    instances = optional(list(object({<br/>      zone       = string<br/>      self_links = list(string)<br/>    })), [])<br/>    instance_groups                 = optional(list(string), [])<br/>    port                            = optional(number, 80)<br/>    port_name                       = optional(string, "http")<br/>    protocol                        = optional(string, "HTTP")<br/>    timeout_sec                     = optional(number, 30)<br/>    session_affinity                = optional(string, "NONE")<br/>    affinity_cookie_ttl_sec         = optional(number)<br/>    connection_draining_timeout_sec = optional(number, 300)<br/>    enable_cdn                      = optional(bool, false)<br/>    security_policy                 = optional(string)<br/>    health_check = optional(object({<br/>      protocol            = optional(string, "HTTP")<br/>      port                = optional(number)<br/>      request_path        = optional(string, "/")<br/>      check_interval_sec  = optional(number, 10)<br/>      timeout_sec         = optional(number, 5)<br/>      healthy_threshold   = optional(number, 2)<br/>      unhealthy_threshold = optional(number, 3)<br/>    }), {})<br/>    hosts = optional(list(string), [])<br/>    paths = optional(list(string), ["/*"])<br/>  }))</pre> | n/a | yes |
| <a name="input_create_health_check_firewall"></a> [create\_health\_check\_firewall](#input\_create\_health\_check\_firewall) | Create the ingress rule admitting Google's health check ranges,<br/>35.191.0.0/16 and 130.211.0.0/22, to every backend port on the tagged<br/>instances. Without a rule from these ranges every probe fails. Set false<br/>only where an equivalent rule already exists. | `bool` | `true` | no |
| <a name="input_deployment_name"></a> [deployment\_name](#input\_deployment\_name) | Cluster Toolkit deployment name. Used to prefix resource names. | `string` | n/a | yes |
| <a name="input_domains"></a> [domains](#input\_domains) | Domains for a Google-managed TLS certificate. Each must already resolve to<br/>this load balancer's address, or the certificate stays in PROVISIONING and<br/>the load balancer serves errors.<br/><br/>Include every hostname named in backend\_services hosts, or requests to those<br/>names fail TLS before routing is ever considered.<br/><br/>Mutually exclusive with ssl\_certificates. Provisioning typically takes 15 to<br/>60 minutes on first apply. | `list(string)` | `[]` | no |
| <a name="input_enable_http_redirect"></a> [enable\_http\_redirect](#input\_enable\_http\_redirect) | Also listen on port 80 and redirect to HTTPS. | `bool` | `true` | no |
| <a name="input_enable_iap"></a> [enable\_iap](#input\_enable\_iap) | Put Identity-Aware Proxy in front of every backend service, so Google<br/>authenticates each request before it reaches a backend and forwards a<br/>signed assertion of who the user is. | `bool` | `false` | no |
| <a name="input_enable_logging"></a> [enable\_logging](#input\_enable\_logging) | Emit load balancer request logs for every backend service. | `bool` | `false` | no |
| <a name="input_iap_members"></a> [iap\_members](#input\_iap\_members) | Principals granted roles/iap.httpsResourceAccessor on every backend service,<br/>and so allowed through IAP. For example ["user:someone@example.com",<br/>"group:team@example.com"].<br/><br/>Enabling IAP without granting anyone this role locks everyone out,<br/>including the person who deployed it. | `set(string)` | `[]` | no |
| <a name="input_labels"></a> [labels](#input\_labels) | Labels to add to the resources that accept them. | `map(string)` | `{}` | no |
| <a name="input_logging_sample_rate"></a> [logging\_sample\_rate](#input\_logging\_sample\_rate) | Fraction of requests logged when enable\_logging is true, between 0.0 and 1.0. | `number` | `1` | no |
| <a name="input_name"></a> [name](#input\_name) | Short name distinguishing this load balancer from others in the same deployment. | `string` | `"lb"` | no |
| <a name="input_network_self_link"></a> [network\_self\_link](#input\_network\_self\_link) | Self link of the network holding the backends. Required when create\_health\_check\_firewall is true. | `string` | `null` | no |
| <a name="input_oauth2_client_id"></a> [oauth2\_client\_id](#input\_oauth2\_client\_id) | OAuth client ID for IAP. Leave null to use a Google-managed client, which<br/>needs no client to be created and no redirect URI to be configured.<br/><br/>Supply a client only where the consent screen must be controlled directly.<br/>Its authorised redirect URI is then<br/>https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect | `string` | `null` | no |
| <a name="input_oauth2_client_secret"></a> [oauth2\_client\_secret](#input\_oauth2\_client\_secret) | OAuth client secret matching oauth2\_client\_id. Required when that is set. | `string` | `null` | no |
| <a name="input_project_id"></a> [project\_id](#input\_project\_id) | Project in which Google Cloud resources will be created. | `string` | n/a | yes |
| <a name="input_ssl_certificates"></a> [ssl\_certificates](#input\_ssl\_certificates) | Self links of existing SSL certificates to serve, instead of a Google-managed one. Mutually exclusive with domains. | `list(string)` | `[]` | no |
| <a name="input_ssl_policy"></a> [ssl\_policy](#input\_ssl\_policy) | Self link of an SSL policy constraining TLS versions and ciphers. Null uses the Google default. | `string` | `null` | no |
| <a name="input_target_tags"></a> [target\_tags](#input\_target\_tags) | Network tags the health check firewall rule applies to. Must match tags on the backend instances. | `list(string)` | `[]` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_backend_service_ids"></a> [backend\_service\_ids](#output\_backend\_service\_ids) | Full resource ID of each backend service, keyed by its backend\_services name. |
| <a name="output_backend_service_names"></a> [backend\_service\_names](#output\_backend\_service\_names) | Name of each backend service, keyed by its backend\_services name. A workload<br/>verifying IAP assertions needs its own name to resolve the audience they are<br/>minted for.<br/><br/>The names are deterministic - "DEPLOYMENT-NAME-BACKEND-backend" - so a<br/>blueprint can also spell one out directly where referencing this output<br/>would create a dependency cycle. |
| <a name="output_backend_service_self_links"></a> [backend\_service\_self\_links](#output\_backend\_service\_self\_links) | Self link of each backend service, keyed by its backend\_services name. |
| <a name="output_instance_group_self_links"></a> [instance\_group\_self\_links](#output\_instance\_group\_self\_links) | Self links of the unmanaged instance groups created from backend\_services instances. |
| <a name="output_ip_address"></a> [ip\_address](#output\_ip\_address) | External IP address the load balancer serves on. Point DNS here. |
| <a name="output_url"></a> [url](#output\_url) | HTTPS URL of the load balancer, using the first configured domain where there is one. |
| <a name="output_urls_by_backend"></a> [urls\_by\_backend](#output\_urls\_by\_backend) | HTTPS URL that reaches each backend service, using its first host or the default domain. |
<!-- END OF PRE-COMMIT-TERRAFORM DOCS HOOK -->
