variable "project_id" {
  description = "Project in which the HPC deployment will be created."
  type        = string
}

variable "deployment_name" {
  description = "Name of deployment, used to name bucket containing startup script."
  type        = string
}

variable "region" {
  description = "Region to place bucket containing startup script."
  type        = string
}

variable "labels" {
  description = "Key-value pairs of labels to be added to created resources."
  type        = map(string)
}

variable "vnc_flavor" {
  type        = string
  description = "VNC server implementation to install (tigervnc|tightvnc)."
  default     = "tigervnc"
}

variable "vdi_tool" {
  type        = string
  description = "VDI tool to deploy (guacamole|nomachine|workspot)."
  default     = "guacamole"
}

variable "user_provision" {
  type        = string
  description = "Whether to create local users (true) or use os-login for authentication to VMs."
  default     = "local_users"
}

variable "vdi_user_group" {
  type        = string
  description = "Unix group for VDI users."
  default     = "vdiusers"
}

variable "vdi_resolution" {
  type        = string
  description = "Desktop resolution for VNC sessions (e.g. 1920x1080)."
  default     = "1920x1080"
}

variable "vdi_webapp_port" {
  type        = string
  description = "Port to serve the Webapp interface from (recommend reverse proxy (ie. nginx container) or LB in front of this?)"
  default     = "8080"
}

variable "vdi_users" {
  description = <<-DOC
    List of VDI users, each with username, VNC port, and one of: blueprint password OR a Secret Manager secret name.
    If neither a password or a secret_name is set then a password will be randomly generated and saved.
  DOC
  type = list(object({
    username    = string
    port        = number
    password    = optional(string)
    secret_name = optional(string)
  }))
  default = []
}
