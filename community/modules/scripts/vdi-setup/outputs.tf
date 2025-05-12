output "startup_script" {
  description = "Combined startup script that installs VDI (VNC, Guacamole, users)."
  value       = module.startup_script.startup_script
}

output "vdi_runner" {
  description = "Shell runner wrapping Ansible playbook + roles (for custom-image or direct use)."
  value       = local.combined_runner
}
