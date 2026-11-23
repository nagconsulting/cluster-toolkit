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

"""Run the cluster-blueprint-assistant skill's EVAL.yaml against the OFE agent.

    python -m ofe_agent.evals --project my-proj [--case lustre] [--out results.json]

Scored like `tools/run_eval.py --live`: the verdict comes from hard
evidence, keyword assertions are reported but do not change it. The live
oracles map onto OFE as follows:
- tracked templates edited     -> `git status` of examples/ before/after
- copy without ai_assisted     -> every proposed copy must carry it
- output does not expand       -> the selected proposal must be valid, or
                                  missing only values the form collects
- .tf reads, terraform/deploy  -> impossible: the agent has no such tools
Keywords are checked with run_eval.verify_assertions (boundary-aware) on the
turn rendered as a transcript: tool calls become the gcluster commands they
run, followed by the deployment.yaml and copy they produce, then the answer.
live_setup steps need a shell and are skipped (reported per case).
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time

import yaml

from .chat import propose
from .toolkit.changes import blueprint_copy, has_changes
from .toolkit.paths import REPO_ROOT, SKILL_DIR


def _actions(result):
    """The agent's tool calls as the commands and files they correspond to."""
    out = []
    for step in result.trace:
        a = step["args"]
        if step["tool"] == "describe":
            out.append(f"./gcluster explain {a['path']}")
        elif step["tool"] == "find_blueprints":
            out.append(f"./gcluster explain {' '.join(a['specs'])}")
        elif step["tool"] == "list_blueprints":
            out.append("read references/catalog.yaml")
        elif step["tool"] == "list_modules":
            out.append("read references/catalog.yaml module_wiring")
    for p in result.proposals.values():
        bp = target = p["blueprint"]
        if has_changes(p["changes"]):
            target = bp.replace(".yaml", "-ai.yaml")
            out.append(f"# copy {bp} -> new file {target} (ai_assisted: true)")
            out.append(blueprint_copy(bp, p["changes"]))
        out.append("# deployment.yaml")
        out.append(yaml.safe_dump(p["deployment"], sort_keys=False))
        out.append(f"./gcluster expand {target} -d deployment.yaml")
    return "\n".join(out)


def _run_eval():
    """The skill suite's own assertion engine (tools/run_eval.py)."""
    spec = importlib.util.spec_from_file_location("run_eval", REPO_ROOT / "tools" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def template_status():
    """git status of the example blueprints, ignoring the hidden copies
    validation writes next to a template for the length of one expand."""
    out = subprocess.run(["git", "status", "--porcelain", "--", "examples", "community/examples"],
                         cwd=REPO_ROOT, capture_output=True, text=True, check=False).stdout
    return "\n".join(l for l in out.splitlines() if not re.search(r"/\.ofe-[^/]*-ai\.yaml$", l))


def hard_failures(result, status_before):
    """Evidence of a broken rule, whatever the case: tracked templates
    edited, a copy without ai_assisted, or an offered option that fails
    gcluster expand for anything but values the form collects."""
    hard = []
    if template_status() != status_before:
        hard.append("tracked templates changed")
    for p in result.proposals.values():
        if has_changes(p["changes"]) and "ai_assisted: true" not in blueprint_copy(p["blueprint"], p["changes"]):
            hard.append(f"copy of {p['blueprint']} lacks ai_assisted: true")
    for option in result.options:
        v = result.proposals[option["proposal"]]["validation"]
        if not v["valid"] and not v["missing"]:
            hard.append(f"offered option {option['title']!r} does not expand: " + v["output"][-300:])
    return hard


def score(case, result, status_before):
    """Returns (hard failures, keyword report)."""
    hard = hard_failures(result, status_before)
    transcript = "\n".join([_actions(result), result.answer, result.question, *result.choices,
                            *(f"{o['title']}: {o['reason']}" for o in result.options),
                            *(f"{a['title']}: {a['description']}" for a in result.approaches)])
    ok, message = _run_eval().verify_assertions(transcript, case)
    return hard, "ok" if ok else message


def main():
    parser = argparse.ArgumentParser(prog="ofe_agent.evals")
    parser.add_argument("--project", required=True, help="target project for validators")
    parser.add_argument("--case", default="", help="only cases whose name contains this")
    parser.add_argument("--out", help="write per-case results as JSON")
    args = parser.parse_args()

    suite = yaml.safe_load((SKILL_DIR / "EVAL.yaml").read_text())
    cases = [c for c in suite["cases"] if args.case in c["name"]]
    results = []
    for case in cases:
        start = time.time()
        status = template_status()
        try:
            result = propose(case["prompt"].strip(), args.project)
            failures, keywords = score(case, result, status)
            calls, answer = len(result.trace), result.answer
        except Exception as err:  # pylint: disable=broad-except
            failures, keywords, calls, answer = [f"error: {err}"], "not run", 0, ""
        took = time.time() - start
        notes = (["live_setup skipped"] if case.get("live_setup") else []) + [f"keywords: {keywords}"]
        results.append({"name": case["name"], "passed": not failures, "failures": failures,
                        "notes": notes, "seconds": round(took, 1), "tool_calls": calls, "answer": answer})
        print(f"{'PASS' if not failures else 'FAIL'} {case['name']} ({took:.0f}s, {calls} calls)"
              + "".join(f"\n     - {f}" for f in failures)
              + "".join(f"\n     . {n}" for n in notes), flush=True)
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
