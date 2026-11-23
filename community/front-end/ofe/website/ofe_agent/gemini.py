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

"""Gemini (Vertex AI) client and settings, overridable by environment."""

import os
import time

from google import genai

DEFAULT_MODEL = os.environ.get("OFE_AGENT_MODEL", "gemini-3.8-flash")
DEFAULT_LOCATION = os.environ.get("OFE_AGENT_LOCATION", "global")
# Gemini "thinking" dominates latency (about 100 thinking tokens/s). LOW gave
# the same rankings in a third less time and halves builder turns; see the
# eval suite (ofe_agent.evals) before raising it.
RANK_THINKING = os.environ.get("OFE_AGENT_RANK_THINKING", "LOW")
CHAT_THINKING = os.environ.get("OFE_AGENT_CHAT_THINKING", "LOW")


def client(project):
    """Vertex AI client billed to project, using ambient credentials. Keep a
    reference while calling it: a collected client closes its connection."""
    return genai.Client(vertexai=True, project=project, location=DEFAULT_LOCATION)


class Usage:
    """What one wizard call or builder turn cost: Gemini calls, tokens by
    kind and wall time, for the log line each turn writes."""

    _FIELDS = {"input": "prompt_token_count", "cached": "cached_content_token_count",
               "output": "candidates_token_count", "thinking": "thoughts_token_count"}

    def __init__(self):
        self.start = time.monotonic()
        self.calls = 0
        self.tokens = dict.fromkeys(self._FIELDS, 0)

    def add(self, response):
        self.calls += 1
        meta = response.usage_metadata
        for key, attr in self._FIELDS.items():
            self.tokens[key] += (getattr(meta, attr, None) or 0) if meta else 0

    def as_dict(self, **extra):
        return {"seconds": round(time.monotonic() - self.start, 1),
                "gemini_calls": self.calls, **self.tokens, **extra}
