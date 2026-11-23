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

"""Gemini blueprint agent for the OFE Cluster Builder.

Deliberately free of Django imports so it runs standalone
(`python -m ofe_agent "..."`, `python -m ofe_agent.evals`) as well as from
the ghpcfe views.

    toolkit/    deterministic layer: gcluster, catalog, blueprint data,
                value rules, template changes, deployment and validation
    gemini      Vertex AI client and settings
    prompts     instructions (core rules come from the skill's SKILL.md)
    rank        wizard: rank catalog blueprints in one call
    chat        builder: tool-using turns that propose configurations
    evals       the skill's EVAL.yaml run against this agent
    behaviour   OFE builder behaviour cases (behaviour.yaml)
"""
