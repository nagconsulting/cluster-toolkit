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

data "google_project" "this" {
  project_id = var.project_id
}

resource "random_id" "resource_name_suffix" {
  byte_length = 2
}

locals {
  # This label allows for billing report tracking based on module.
  labels = merge(var.labels, { ghpc_module = "artifact-registry", ghpc_role = "container" })
}

locals {
  mirror_url_no_proto = var.repo_mirror_url != null ? replace(replace(var.repo_mirror_url, "https://", ""), "http://", "") : ""
  mirror_host         = local.mirror_url_no_proto != "" ? split("/", local.mirror_url_no_proto)[0] : ""

  base_component = replace(
    replace(
      replace(
        lower(
          local.mirror_host != ""
          ? "${var.format}-${var.repo_mode}-${local.mirror_host}"
          : "${var.format}-${var.repo_mode}-nohost"
        ),
        "\\.", "-"
      ),
      "/", "-"
    ),
    "_", "-"
  )
}

resource "google_secret_manager_secret" "repo_password_secret" {
  count     = var.repo_password != null ? 1 : 0
  secret_id = var.repo_secret_name
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "repo_password_secret_version" {
  count       = var.repo_password != null ? 1 : 0
  secret      = google_secret_manager_secret.repo_password_secret[0].id
  secret_data = var.repo_password
}

resource "google_secret_manager_secret_iam_member" "artifactregistry_secret_access_for_ar_sa" {
  count     = var.repo_password != null ? 1 : 0
  secret_id = google_secret_manager_secret.repo_password_secret[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-artifactregistry.iam.gserviceaccount.com"
}

resource "google_artifact_registry_repository" "artifact_registry" {
  project     = var.project_id
  location    = var.region
  format      = var.format
  mode        = var.repo_mode
  description = var.deployment_name
  labels      = local.labels

  repository_id = replace(
    replace(
      lower(format(
        "%s-%s",
        local.base_component,
        random_id.resource_name_suffix.id
      )),
      ".", "-"
    ),
    "/", "-"
  )

  dynamic "remote_repository_config" {
    for_each = var.repo_mode == "REMOTE_REPOSITORY" ? [1] : []
    content {
      description = "Pull-through cache"

      dynamic "docker_repository" {
        for_each = var.format == "DOCKER" && var.repo_public_repository != null ? [1] : []
        content {
          public_repository = var.repo_public_repository
        }
      }

      dynamic "docker_repository" {
        for_each = var.format == "DOCKER" && var.repo_public_repository == null && var.repo_mirror_url != null ? [1] : []
        content {
          custom_repository {
            uri = var.repo_mirror_url
          }
        }
      }

      dynamic "maven_repository" {
        for_each = var.format == "MAVEN" && var.repo_public_repository != null ? [1] : []
        content {
          public_repository = var.repo_public_repository
        }
      }

      dynamic "maven_repository" {
        for_each = var.format == "MAVEN" && var.repo_public_repository == null && var.repo_mirror_url != null ? [1] : []
        content {
          custom_repository {
            uri = var.repo_mirror_url
          }
        }
      }

      dynamic "npm_repository" {
        for_each = var.format == "NPM" && var.repo_public_repository != null ? [1] : []
        content {
          public_repository = var.repo_public_repository
        }
      }

      dynamic "npm_repository" {
        for_each = var.format == "NPM" && var.repo_public_repository == null && var.repo_mirror_url != null ? [1] : []
        content {
          custom_repository {
            uri = var.repo_mirror_url
          }
        }
      }

      dynamic "python_repository" {
        for_each = var.format == "PYTHON" && var.repo_public_repository != null ? [1] : []
        content {
          public_repository = var.repo_public_repository
        }
      }

      dynamic "python_repository" {
        for_each = var.format == "PYTHON" && var.repo_public_repository == null && var.repo_mirror_url != null ? [1] : []
        content {
          custom_repository {
            uri = var.repo_mirror_url
          }
        }
      }

      dynamic "apt_repository" {
        for_each = var.format == "APT" && var.repo_public_repository != null ? [1] : []
        content {
          public_repository {
            repository_base = var.repository_base
            repository_path = var.repository_path
          }
        }
      }

      dynamic "apt_repository" {
        for_each = var.format == "APT" && var.repo_public_repository == null && var.repo_mirror_url != null ? [1] : []
        content {
          custom_repository {
            uri = var.repo_mirror_url
          }
        }
      }

      dynamic "yum_repository" {
        for_each = var.format == "YUM" && var.repo_public_repository != null ? [1] : []
        content {
          public_repository {
            repository_base = var.repository_base
            repository_path = var.repository_path
          }
        }
      }

      dynamic "yum_repository" {
        for_each = var.format == "YUM" && var.repo_public_repository == null && var.repo_mirror_url != null ? [1] : []
        content {
          custom_repository {
            uri = var.repo_mirror_url
          }
        }
      }

      dynamic "common_repository" {
        for_each = var.format == "COMMON" ? [1] : []
        content {
          uri = var.repo_mirror_url
        }
      }

      dynamic "upstream_credentials" {
        for_each = var.repo_password != null ? [1] : []
        content {
          username_password_credentials {
            username                = var.repo_username
            password_secret_version = "${google_secret_manager_secret.repo_password_secret[0].id}/versions/${var.repo_password_version}"
          }
        }
      }
    }
  }
}
