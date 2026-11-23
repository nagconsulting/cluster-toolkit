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

"""A blueprint as the Cluster Builder shows and downloads it.

The page shows the blueprint without its vars: block (view_text): values
live in deployment.yaml, and the template's defaults and their comments are
listed separately (catalog.blueprint_hints, the page's Defaults view). The
download (clean_text) keeps vars: with every default, so it still works with
deployment.yaml alone, but without the example's comments, and is marked
ai_assisted."""

import io
import re

import yaml
from ruamel.yaml import YAML

# Comments and blank lines up to the document marker (the licence header).
_HEADER_RE = re.compile(r"(?:[ \t]*(?:#[^\n]*)?\n)*---[ \t]*\n(?:[ \t]*\n)*")
_TOP_KEY_RE = re.compile(r"^[^\s#]")


def _split(text):
    """(header, before, vars_block, after): the licence header, the text
    before the top-level vars: block, the block itself, and the rest. A run
    of comments at the start of a line that ends the block, after a blank
    line, introduces the next key, so it goes with the rest."""
    header = _HEADER_RE.match(text)
    head = header.group(0) if header else ""
    lines = text[len(head):].splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("vars:")), None)
    if start is None:
        return head, "".join(lines), "", ""
    end = next((i for i in range(start + 1, len(lines)) if _TOP_KEY_RE.match(lines[i])), len(lines))
    keep = end
    while keep > start + 1 and lines[keep - 1].startswith("#"):
        keep -= 1
    if keep == end or lines[keep - 1].strip():  # no comments, or not set apart by a blank line
        keep = end
    return head, "".join(lines[:start]), "".join(lines[start:keep]), "".join(lines[keep:])


def view_text(text):
    """The blueprint without its licence header and top-level vars: block
    (from `vars:` to the next top-level key, its comments included)."""
    _, before, _, after = _split(text)
    return re.sub(r"\n{3,}", "\n\n", before + after).lstrip("\n")


def clean_text(text):
    """The blueprint with ai_assisted: true and its vars: block rewritten
    without comments (the example's notes and commented-out alternatives);
    everything else, comments included, unchanged."""
    head, before, block, after = _split(text)
    if not re.search(r"^ai_assisted:", before + after, re.M):
        name = re.search(r"^blueprint_name:.*\n", before, re.M)
        at = name.end() if name else 0
        before = before[:at] + "ai_assisted: true\n" + before[at:]
    if block:
        y = YAML()
        y.width = 4096
        buf = io.StringIO()
        y.dump({"vars": yaml.safe_load(block)["vars"]}, buf)
        block = buf.getvalue() + "\n"
    return head + before + block + after
