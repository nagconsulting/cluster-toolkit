resource "terraform_data" "input_validation" {
  lifecycle {
    precondition {
      condition     = alltrue([
        for user in var.vdi_users : (
          user.secret_name == null || user.password == null
        )
      ])
      error_message = "Each vdi_users entry must not have both password and secret_name set; choose one or neither."
    }

    precondition {
      condition     = contains(["tigervnc", "tightvnc"], var.vnc_flavor)
      error_message = "vnc_flavor must be either \"tigervnc\" or \"tightvnc\"."
    }

    precondition {
      condition     = contains(["guacamole", "nomachine", "workspot"], var.vdi_tool)
      error_message = "vdi_tool must be one of: guacamole, nomachine, workspot."
    }

    precondition {
      condition     = contains(["local_users", "os_login"], var.user_provision)
      error_message = "user_provision must be \"local_users\" or \"os_login\"."
    }

    precondition {
      condition     = can(regex("^[1-9][0-9]*x[1-9][0-9]*$", var.vdi_resolution))
      error_message = "vdi_resolution must be in the form WIDTHxHEIGHT (e.g. 1920x1080)."
    }

    precondition {
      condition     = var.user_provision == "local_users" || length(var.vdi_users) == 0
      error_message = "vdi_users may only be set when user_provision = local_users."
    }
  }
}
