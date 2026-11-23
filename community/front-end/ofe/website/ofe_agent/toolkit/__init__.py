# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Deterministic layer behind the Cluster Builder and its Gemini agent,
backed by gcluster and the cluster-blueprint-assistant skill's catalog.yaml.

Every guardrail lives here, not in the prompt: only catalog blueprints and
in-repo modules can be used, values are type- and rule-checked, and any
template change (promoted inputs, added or removed modules) produces an
`ai_assisted` copy; the tracked template is never modified. There is
intentionally no deploy function.

    paths       repo, gcluster and skill locations
    errors      ToolError
    gcluster    running gcluster; `explain` for blueprints and modules
    catalog     catalog.yaml and companion example deployment files
    blueprint   template parsing, where vars are used, form data
    values      value/type rules for overrides and module settings
    changes     template changes and the ai_assisted copy
    deployment  deployment.yaml, missing values, `gcluster expand`
"""
