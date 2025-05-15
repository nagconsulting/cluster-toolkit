locals {
  labels = merge(var.labels, { ghpc_module = "spack-setup", ghpc_role = "scripts" })
}

# Create a tar.gz of roles/ directory
data "archive_file" "roles_tar" {
  type        = "tar.gz"
  source_dir  = "${path.module}/roles"
  output_path = "${path.module}/roles.tar.gz"
}

# Render vars file for Ansible
locals {
  vdi_vars_content = templatefile("${path.module}/templates/vars.yaml.tftpl", {
    deployment_name = var.deployment_name
    project_id      = var.project_id
    user_provision  = var.user_provision
    vnc_flavor      = var.vnc_flavor
    vdi_tool        = var.vdi_tool
    vdi_user_group  = var.vdi_user_group
    vdi_resolution  = var.vdi_resolution
    vdi_webapp_port = var.vdi_webapp_port
    vdi_users       = var.vdi_users
  })
}

# Assemble runners
locals {
  runners = [
    # Install 'google.cloud' collection for 'gcp_secret_manager' role
    # and other deps
    {
      type        = "shell"
      destination = "install-deps.sh"
      content     = <<-EOT
        #!/bin/bash
        set -eux
        /usr/local/ghpc-venv/bin/python3 -m pip install requests google-auth
        ansible-galaxy collection install google.cloud
      EOT
    },
    # Stage roles.tar.gz
    {
      type        = "data"
      source      = data.archive_file.roles_tar.output_path
      destination = "/tmp/vdi/roles.tar.gz"
    },

    # Unpack into /tmp/vdi/roles
    {
      type        = "shell"
      destination = "unpack_roles.sh"
      content     = <<-EOT
        #!/bin/bash
        set -eux
        mkdir -p /tmp/vdi/roles
        tar xzf /tmp/vdi/roles.tar.gz -C /tmp/vdi/roles
      EOT
    },

    # write out vars file as YAML
    {
      type        = "data"
      content     = local.vdi_vars_content
      destination = "/tmp/vdi/vars.yaml"
    },

    # Run the rendered playbook via ansible-local
    {
      type        = "ansible-local"
      content     = templatefile("${path.module}/templates/install.yaml.tftpl",
        {
          roles           = ["base_os", "secret_manager", "user_provision", "vnc", "vdi_tool"],
        }
      )
      destination = "/tmp/vdi/install.yaml"
      # Todo: turn off debug '-v' later:
      args        = "--extra-vars @/tmp/vdi/vars.yaml -v"
    },
    # Todo: another runner here to delete /tmp/vdi afterwards?
  ]

  required_apis = [
    "compute.googleapis.com",
    "secretmanager.googleapis.com",
  ]

  bucket_name = "${substr(var.deployment_name,0,39)}-vdi-scripts-${substr(md5(var.deployment_name),0,8)}"
}

# Bucket to stage runners
resource "google_storage_bucket" "bucket" {
  labels                      = local.labels
  project                     = var.project_id
  name                        = local.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  storage_class               = "REGIONAL"
}

# Use the startup-script module to push and execute them
module "startup_script" {
  labels          = local.labels
  source          = "../../../../modules/scripts/startup-script"
  project_id      = var.project_id
  deployment_name = var.deployment_name
  region          = var.region

  runners         = local.runners
  gcs_bucket_path = "gs://${google_storage_bucket.bucket.name}"

  docker = {
    enabled = true
  }
}

# Expose the combined startup script
locals {
  combined_runner = {
    type        = "shell"
    content     = module.startup_script.startup_script
    destination = "install-vdi-and-setup.sh"
  }
}
