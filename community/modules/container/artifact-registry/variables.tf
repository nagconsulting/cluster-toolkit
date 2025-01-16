# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

variable "project_id" {
  description = "Project ID where the artifact registry and secret are created."
  type        = string
}

variable "region" {
  description = "Region for the artifact registry."
  type        = string
}

variable "deployment_name" {
  description = "The name of the current deployment."
  type        = string
}

variable "labels" {
  description = "Labels to add to the artifact registry. Key-value pairs."
  type        = map(string)
  default     = {}
}

variable "repo_password" {
  description = "Optional password/API key. If null, one will be randomly generated."
  type        = string
  default     = null
}

variable "user_managed_replication" {
  description = <<-DOC
    (Optional) A list of objects to enable user-managed replication.
    Each object can have:
      location        = string
      kms_key_name    = optional(string) 
    If empty, auto replication is used.
  DOC
  type    = list(object({
    location        = string
    kms_key_name    = optional(string)
  }))
  default = []
}

variable "format" {
  description = "Artifact Registry format (e.g., DOCKER)."
  type        = string
  default     = "DOCKER"
}

variable "repo_mode" {
  description = "Artifact Registry mode (STANDARD_REPOSITORY, REMOTE_REPOSITORY, etc.)."
  type        = string
  default     = "STANDARD_REPOSITORY"
}

variable "repo_public_repository" {
  description = <<-DOC
    For REMOTE_REPOSITORY, name of a known public repo 
    (e.g., DOCKER_HUB) or null for custom repo.
  DOC
  type        = string
  default     = null
}

variable "repo_mirror_url" {
  description = "For REMOTE_REPOSITORY, URL for a custom or common mirror."
  type        = string
  default     = null
}

variable "use_service_account_auth" {
  description = <<-DOC
    If true, a username/password is used for the REMOTE_REPOSITORY mirror.  
    If false (or if repo_password == null), no password is created at all.
  DOC
  type    = bool
  default = false
}

variable "repo_username" {
  description = "Username for external repository."
  type        = string
  default     = null
}

variable "repository_base" {
  description = "For APT/YUM public repos, repository_base (e.g., 'DEBIAN', 'UBUNTU')."
  type        = string
  default     = null
}

variable "repository_path" {
  description = "For APT/YUM public repos, repository_path (e.g., 'debian/dists/buster')."
  type        = string
  default     = null
}
