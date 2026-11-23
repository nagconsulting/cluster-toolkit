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

"""Wizard step: rank catalog blueprints for a workload in one Gemini call."""

import json
import logging

from google.genai import types
from pydantic import BaseModel

from . import gemini
from .prompts import RANK_INSTRUCTION
from .toolkit.catalog import list_blueprints

MAX_CANDIDATES = 5
logger = logging.getLogger(__name__)


class _Candidate(BaseModel):
    blueprint: str
    score: int
    reason: str


class _Ranking(BaseModel):
    summary: str
    candidates: list[_Candidate]


def rank(prompt, vertex_project, model=gemini.DEFAULT_MODEL):
    """One Gemini call, no tools: rank catalog blueprints for a workload
    description. Returns {"summary": str, "candidates": [{blueprint, score, reason}]}."""
    catalog = list_blueprints()
    paths = {b["path"] for b in catalog}
    client = gemini.client(vertex_project)
    usage = gemini.Usage()
    response = client.models.generate_content(
        model=model,
        contents=(
            f"<catalog>\n{json.dumps(catalog)}\n</catalog>\n"
            f"<user_request>\n{prompt}\n</user_request>"
        ),
        config=types.GenerateContentConfig(
            system_instruction=RANK_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=_Ranking,
            thinking_config=types.ThinkingConfig(thinking_level=gemini.RANK_THINKING),
        ),
    )
    usage.add(response)
    logger.info("ofe_agent rank: %s", json.dumps(usage.as_dict(model=model)))
    ranking = _Ranking.model_validate_json(response.text)
    seen, candidates = set(), []
    for c in ranking.candidates:
        if c.blueprint in paths and c.blueprint not in seen:  # never trust a path the catalog lacks
            seen.add(c.blueprint)
            candidates.append({"blueprint": c.blueprint, "score": max(0, min(100, c.score)),
                               "reason": c.reason[:500]})
    return {"summary": ranking.summary[:1000], "candidates": candidates[:MAX_CANDIDATES]}
