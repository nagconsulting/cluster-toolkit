# Remote Desktop Examples

These blueprints deploy browser-based Linux desktops alongside a Slurm cluster,
using the [novnc-runtime](../../modules/remote-desktop/novnc-runtime/README.md)
and [novnc-desktop](../../modules/remote-desktop/novnc-desktop/README.md)
modules. Users reach an XFCE session over noVNC in a browser, with sessions
created per user from their OS Login identity.

## Architecture

Each blueprint deploys a Slurm cluster with one or both desktop types:

- **Login desktop**: `novnc-runtime` layered onto the Slurm login node, using
  TigerVNC. Suited to 2D and general interactive use.
- **Visualization desktop**: `novnc-desktop` on a dedicated VM, using TurboVNC.
  Suited to 3D, and the only backend supporting GPU acceleration on GCE.

Both hosts run a per-user broker that publishes endpoint metadata into
`/shared/ghpc-remote-desktop/endpoints`. Each display listens on a `0700`
per-user unix socket with no TCP port, so it is not reachable by other local
users on a shared login node.

## Blueprints

- [hpc-slurm-remote-desktop.yaml](./hpc-slurm-remote-desktop.yaml): login and
  visualization desktops, reached over an IAP tunnel.

Both blueprints use `novnc_identity_mode: trusted_proxy`: the broker trusts an
unverified identity header and the shared secret is the only control. Reached
over an SSH tunnel with no proxy in front, the identity headers must be supplied
by hand. Treat these as validation blueprints, not a production posture.

## GPU desktops

The visualization desktop can use hardware OpenGL. Rather than ship a
near-identical second blueprint, apply these four changes to
`hpc-slurm-remote-desktop.yaml`:

```yaml
vars:
  # Debian is the only slurm-gcp family shipping an NVIDIA driver with graphics
  # (not merely compute) support. A compute driver ships no libEGL_nvidia and
  # cannot render.
  slurm_image:
    family: slurm-gcp-6-12-debian-12
    project: schedmd-slurm-public
  viz_machine_type: g2-standard-8

# on the viz-desktop module
      enable_gpu_acceleration: true
      on_host_maintenance: TERMINATE
```

`vnc_backend: turbovnc` is required and is already the visualization desktop's
setting. TurboVNC reaches the GPU through VirtualGL's EGL back end; TigerVNC
offloads GL only through `-rendernode`, which needs a DRM render node that GCE's
NVIDIA images never create. Without a usable GPU the session falls back to
software rendering rather than failing, and the broker logs why at startup.

## Reaching desktops through Identity-Aware Proxy

`hpc-slurm-remote-desktop-iap.yaml` puts the visualisation desktop behind a
Google-managed HTTPS load balancer with IAP, so it is reachable at a hostname in
a browser with no tunnel and no proxy to run locally. Google authenticates every
request and forwards a signed assertion, which the broker verifies.

The login-node desktop in that blueprint stays on the tunnel: its instances are
created inside the Slurm controller module, so there is no instance group to
attach to a backend service.

Before deploying it:

1. Reserve a global address and point DNS at it. Do this first - a
   Google-managed certificate only validates once the name already resolves.

   ```sh
   gcloud compute addresses create vdi --global --ip-version=IPV4
   gcloud compute addresses describe vdi --global --format='value(address)'
   ```

2. Configure the OAuth consent screen for the project, once.

3. Set `desktop_domain`, `desktop_address_name` and `desktop_iap_members` in the
   blueprint.

Certificate provisioning takes roughly 15 to 60 minutes on the first apply, and
the load balancer serves errors until it finishes. Check progress with:

```sh
gcloud compute ssl-certificates list --global \
  --format='value(name,managed.status,managed.domainStatus)'
```

Under IAP the blueprint sets no shared secret. The assertion authenticates the
request cryptographically and names the backend service it was minted for, so a
secret would add configuration surface without adding security - and injecting
one would mean putting it in the load balancer's request headers, and so into
Terraform state.

## Getting Started

Before you start, make sure your prerequisites and dependencies are set up:
[Set up Cluster Toolkit](https://cloud.google.com/cluster-toolkit/docs/setup/configure-environment).

Set the following blueprint variables:

- `project_id`, `region` and `zone`
- `desktop_proxy_secret`, generated with `openssl rand -base64 48`. The brokers
  will not start without it.

## Deployment Instructions

> [!WARNING]
> Deploying these blueprints uses billable components of Google Cloud, including
> Compute Engine instances that run continuously until destroyed. GPU machine
> types are billed at a significantly higher rate.

Create and deploy a blueprint, replacing `BLUEPRINT` with the file you want:

```bash
./gcluster create community/examples/remote-desktop/BLUEPRINT.yaml -w
./gcluster deploy BLUEPRINT
```

## Verify

On each desktop host, confirm the broker is running and has published its
endpoint:

```bash
systemctl status ghpc-desktop-broker
sudo journalctl -u ghpc-desktop-broker --no-pager
ls /shared/ghpc-remote-desktop/endpoints/
```

Reach a desktop through an IAP tunnel and
browse to `http://localhost:6080/vnc.html`:

```bash
gcloud compute start-iap-tunnel LOGIN-NODE 6080 --local-host-port=localhost:6080 --zone ZONE
```

## Reaching a desktop in a browser

The broker requires the identity headers on every request, including the
websocket upgrade, so browsing straight to the tunnelled port returns 403. That
is the cost of `trusted_proxy` with no proxy in front, and it is deliberate.

To confirm the broker itself works, `curl` is enough:

```bash
SECRET=$(gcloud secrets versions access latest \
  --secret ghpc-desktop-proxy-secret --project PROJECT_ID)

curl -s http://localhost:6080/healthz          # -> ok

curl -s -o /dev/null -w '%{http_code}\n' \
  -H "X-Cluster-Desktop-Secret: $SECRET" \
  -H "X-Cluster-Desktop-Email: you@example.com" \
  -H "X-Cluster-Desktop-Username: YOUR_OSLOGIN_NAME" \
  http://localhost:6080/vnc.html               # -> 200, and starts your session
```

For an actual desktop in a browser, run
[local-desktop-proxy.conf](./local-desktop-proxy.conf) on your own machine in
front of the tunnel; it injects the headers, including on the websocket. Fill in
the three `CHANGEME` values, then:

```bash
nginx -c /full/path/to/local-desktop-proxy.conf
# browse to http://localhost:8888/vnc.html
```

That proxy is deliberately local rather than a VM in the blueprint. A proxy
deployed in the cluster would have to assert a fixed identity - making anyone who
can reach its port that user - and would hold the shared secret, so the secret
would stop being a control. An authenticating proxy that verifies who the user
is belongs with a verified identity mode, not with `trusted_proxy`.

## Teardown Instructions

Replace `BLUEPRINT` with the `deployment_name` used in the blueprint vars block.

```bash
./gcluster destroy BLUEPRINT
```
