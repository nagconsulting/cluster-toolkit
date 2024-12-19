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
  description = "Project ID where the artifact registry is created."
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

variable "repo_mode" {
  description = "Mode of the artifact registry. Options: STANDARD_REPOSITORY, VIRTUAL_REPOSITORY, REMOTE_REPOSITORY."
  type        = string
  default     = "STANDARD_REPOSITORY"
}

variable "format" {
  description = <<-DOC
    The format of packages stored in the repository:
    - DOCKER, MAVEN, NPM, PYTHON: public_repository is a single attribute (e.g. DOCKER_HUB, MAVEN_CENTRAL, NPMJS, PYPI)
    - APT, YUM: public_repository is a nested block requiring repository_base and repository_path
    - COMMON: uses a common_repository with a uri
  DOC
  type        = string
  default     = "DOCKER"
}

variable "repo_public_repository" {
  description = <<-DOC
    Name of a known public repository to use:
    - For DOCKER: "DOCKER_HUB"
    - For MAVEN: "MAVEN_CENTRAL"
    - For NPM: "NPMJS"
    - For PYTHON: "PYPI"
    For APT/YUM: specify the public repository by providing repository_base and repository_path.
    If null, then use a custom or common repository.
  DOC
  type        = string
  default     = null
}

variable "repo_mirror_url" {
  description = <<-DOC
    URL for a custom repository if not using a public repository.
    Required if repo_public_repository is null and you want a remote custom repository.
    For COMMON, this must be a URI to another Artifact Registry or an external registry.
  DOC
  type        = string
  default     = null
}

variable "repo_username" {
  description = "Username for the external repository if credentials are needed."
  type        = string
  default     = null
}

variable "repo_password" {
  description = "The password or API key to be stored as a secret in Secret Manager."
  type        = string
  default     = null
}

variable "repo_secret_name" {
  description = "The name of the secret to be created in Secret Manager."
  type        = string
  default     = null
}

variable "repo_password_version" {
  description = "The Secret Manager version to use for the password. Default is 'latest'."
  type        = string
  default     = "latest"
}

variable "repository_base" {
  description = <<-DOC
    Used for APT/YUM formats if using a public repository.
    E.g., for YUM: "ROCKY", "CENTOS", etc.
    for APT: "DEBIAN" or "UBUNTU".
    Leave null if not using APT/YUM public repositories.
  DOC
  type        = string
  default     = null
}

variable "repository_path" {
  description = <<-DOC
    Used for APT/YUM formats if using a public repository.
    Example for YUM: "pub/rocky/9/BaseOS/x86_64/os"
    Example for APT: "debian/dists/buster"
    Leave null if not using APT/YUM public repositories.
  DOC
  type        = string
  default     = null
}
