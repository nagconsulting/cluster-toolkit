## Description



## Example Usage

### Build a custom image with VDI pre-installed
```
blueprint_name: vdi-test

vars:
  deployment_name: vdi-test
  project_id: "hpc-discovery-external"
  region: "us-central1"
  zone: "us-central1-a"

deployment_groups:
- group: primary
  modules:
  - id: network1
    source: modules/network/vpc

  - id: vdi-setup
    source: community/modules/scripts/vdi-setup
    settings:
      vnc_flavor:      "tigervnc"
      vdi_tool:        "guacamole"
      user_provision:  "local_users"
      vdi_user_group:  "vdiusers"
      vdi_resolution:  "1920x1080"
      vdi_users:
      - username: alice
        port: 5901
        password: "ChangeMe123!"
      - username: bob
        port: 5902
        password: "ChangeMe456!"
      - username: charlie
        port: 5903

  - id: machine
    source: modules/compute/vm-instance
    use:
     - network1
     - vdi-setup
```