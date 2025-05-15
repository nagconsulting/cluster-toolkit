## Description

Mostly tested with Rocky. Working on Debian and Ubuntu images (commented in blueprint example below).
Distro / VDI 'flavour' variations are handled in the 'base_os' role for the most part.

## Example Usage

```
# Default compute SA will require IAM role: Secret Manager Secret Accessor

blueprint_name: vdi-test

vars:
  deployment_name: vdi-test
  project_id: * project name here *
  region: us-central1
  zone: us-central1-a

deployment_groups:
- group: primary
  modules:
  - id: network1
    source: modules/network/vpc
    settings:
      extra_iap_ports: [8080]
      firewall_rules:
      - name: allow-guacamole-8080-ext
        description: Allow external ingress to Guacamole on TCP port 8080
        direction: INGRESS
        ranges: ["0.0.0.0/0"] # or rev proxy address?
        allow:
          - protocol: tcp
            ports: ["8080"]

  - id: enable-apis
    source: community/modules/project/service-enablement
    settings:
      gcp_service_list:
      - secretmanager.googleapis.com
      - storage.googleapis.com
      - compute.googleapis.com

  - id: vdi-setup
    source: community/modules/scripts/vdi-setup
    settings:
      vnc_flavor: tigervnc
      vdi_tool: guacamole
      user_provision: local_users
      vdi_user_group: vdiusers
      vdi_resolution: 1920x1080
      vdi_users:
      # Alice: assigned password from blueprint (todo: MD5 hashing for .tfvars)
      # Bob: password is retrieved from Secret Mgr. (todo: handle fails when secret doesn't exist etc)
      # Charlie: random generated password assigned and saved to Secret Mgr.
      - username: alice
        port: 5901
        password: "Ch4ng3Me!"
      - username: bob
        port: 5902
        secret_name: a-password-for-bob
      - username: charlie
        port: 5903

  - id: guac_vm
    source: modules/compute/vm-instance
    settings:
      instance_image:
        # family: debian-11
        # project: debian-cloud
        # family: ubuntu-2004-lts
        # project: ubuntu-os-cloud
        family: hpc-rocky-linux-8
        project: cloud-hpc-image-public
      machine_type: e2-highcpu-8
      tags: ["guacamole"]
    use:
     - network1
     - vdi-setup
```

### Test Guac' connections:

Tunnel over IAP using this command:
```
gcloud compute start-iap-tunnel vdi-test-0 8080  \
    --local-host-port=localhost:8080 \
    --zone=us-central1-a
```
Then open http://localhost:8080/guacamole/

Login using `guacadmin` as the username and the secret for `webapp-server-password-vdi-test` as password.

Notes: 
1. It would be best to have a reverse proxy or LB in front of the VDI VM for prod. (var to enable one as NGINX container?)
2. Todo: User accounts will need added to Guac webui too so they only have visbility of specific connections assigned to them.
