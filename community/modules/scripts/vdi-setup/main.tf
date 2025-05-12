locals {
  labels = merge(var.labels, { ghpc_module = "spack-setup", ghpc_role = "scripts" })
}

# Create a tar.gz of roles/ directory
data "archive_file" "roles_tar" {
  type        = "tar.gz"
  source_dir  = "${path.module}/roles"
  output_path = "${path.module}/roles.tar.gz"
}

# Generate a fully-flat playbook via templatefile()
locals {
  playbook = templatefile(
    "${path.module}/templates/playbook.tftpl",
    {
      vnc_flavor     = var.vnc_flavor,
      vdi_tool       = var.vdi_tool,
      user_provision = var.user_provision,
      vdi_user_group = var.vdi_user_group,
      vdi_resolution = var.vdi_resolution,
      vdi_users      = var.vdi_users,
      roles          = ["secret_manager", "base_os", "vnc", "vdi_tool", "user_provision"],
    }
  )
}

# Assemble runners
locals {
  runners = [
    # Install 'google.cloud' collection for 'gcp_secret_manager' role
    {
      type        = "shell"
      destination = "install-collections.sh"
      content     = <<-EOT
        #!/bin/bash
        set -eux
        ansible-galaxy collection install google.cloud
      EOT
    },
    # Stage roles.tar.gz
    {
      type        = "data"
      source      = data.archive_file.roles_tar.output_path
      destination = "/tmp/roles.tar.gz"
    },

    # Unpack into /tmp/roles
    {
      type        = "shell"
      destination = "unpack_roles.sh"
      content     = <<-EOT
        #!/bin/bash
        set -eux
        mkdir -p /tmp/roles
        tar xzf /tmp/roles.tar.gz -C /tmp/roles
      EOT
    },

    # Run the rendered playbook via ansible-local
    {
      type        = "ansible-local"
      content     = local.playbook
      destination = "/tmp/install-vdi.yaml"
      # any extra-vars are appended after the built-in flags:
      args        = join(" ", [
        "-e vnc_flavor=${var.vnc_flavor}",
        "-e vdi_tool=${var.vdi_tool}",
        "-e user_provision=${var.user_provision}",
        "-e vdi_user_group=${var.vdi_user_group}",
        "-e vdi_resolution=${var.vdi_resolution}",
        "-e vdi_users=${jsonencode(var.vdi_users)}",
        "-v"
      ])
    },
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
}

# Expose the combined startup script
locals {
  combined_runner = {
    type        = "shell"
    content     = module.startup_script.startup_script
    destination = "install-vdi-and-setup.sh"
  }
}
