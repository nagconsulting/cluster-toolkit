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

"""Run the Cluster Builder behaviour cases (behaviour.yaml) live.

    python -m ofe_agent.behaviour --project my-proj [--case storage] [--out results.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from .chat import propose
from .evals import hard_failures, template_status
from .prompts import tailor_request

CASES = Path(__file__).with_name("behaviour.yaml")


def kind(result):
    if result.options:
        return "option"
    if result.approaches:
        return "approaches"
    if result.question:
        return "question"
    return "answer"


def check(expect, result):
    """Failures of the case's expectations."""
    fails = []
    got = kind(result)
    wanted = expect.get("kind")
    if wanted and got not in ([wanted] if isinstance(wanted, str) else wanted):
        fails.append(f"replied with {got}, expected {wanted}")
    offered = [result.proposals[o["proposal"]] for o in result.options]
    if offered:
        removed = set(offered[0]["changes"]["remove_modules"])
        added = {a["id"]: a["source"] for a in offered[0]["changes"]["add_modules"]}
        fails += [f"did not remove {m}" for m in expect.get("removes_modules", []) if m not in removed]
        fails += [f"removed {m}" for m in expect.get("keeps_modules", []) if m in removed]
        fails += [f"did not replace {m} with {src}" for m, src in (expect.get("replaces_modules") or {}).items()
                  if not (m in removed and added.get(m) == src)]
        fails += [f"did not add a {src} module" for src in expect.get("adds_modules", [])
                  if not any(s == src and m not in removed for m, s in added.items())]
        cap = offered[0]["validation"].get("capacity")
        if expect.get("subnet_ok") and cap and not cap["ok"]:
            fails.append(f"existing subnet: fits={cap.get('fits')}, overlaps={cap.get('overlaps')}")
        set_vars = offered[0]["deployment"]["vars"]
        fails += [f"{k} is {set_vars.get(k)!r}, expected {v!r}"
                  for k, v in (expect.get("overrides") or {}).items() if set_vars.get(k) != v]
        fails += [f"{k} is {set_vars.get(k)!r}, expected to match {rx!r}"
                  for k, rx in (expect.get("overrides_matching") or {}).items()
                  if not re.search(rx, str(set_vars.get(k, "")))]
        set_on = {f"{x['module']}.{x['input']}" for x in offered[0]["changes"].get("settings") or []}
        fails += [f"did not set {x}" for x in expect.get("sets_inputs", []) if x not in set_on]
    for pattern in expect.get("no_override_matching", []):
        for p in offered:
            fails += [f"override {k!r} matches {pattern!r}" for k in p["deployment"]["vars"] if re.search(pattern, k)]
    if len(result.choices) < expect.get("min_choices", 0):
        fails.append(f"{len(result.choices)} choices offered, expected at least {expect['min_choices']}")
    if "multi_select" in expect and result.multi_select != expect["multi_select"]:
        fails.append(f"multi_select is {result.multi_select}")
    if expect.get("combinable_approaches"):
        # At least two approaches the user could pick together (no group, or different groups).
        groups = [a["group"] or f"#{n}" for n, a in enumerate(result.approaches)]
        if len(set(groups)) < 2:
            fails.append(f"approaches cannot be combined: groups {groups}")
    reply = "\n".join([result.answer, result.question, *(a["description"] for a in result.approaches)])
    fails += [f"reply contains {t!r}" for t in expect.get("answer_excludes", []) if t.lower() in reply.lower()]
    used = {t["tool"] for t in result.trace}
    fails += [f"did not call {t}" for t in expect.get("uses_tools", []) if t not in used]
    fails += [f"called {t}" for t in expect.get("avoids_tools", []) if t in used]
    if "max_tool_calls" in expect and len(result.trace) > expect["max_tool_calls"]:
        fails.append(f"{len(result.trace)} tool calls > {expect['max_tool_calls']}")
    if "max_seconds" in expect and result.usage["seconds"] > expect["max_seconds"]:
        fails.append(f"took {result.usage['seconds']}s > {expect['max_seconds']}s")
    return fails


def run_case(case, project):
    current = case.get("current")
    if current:
        current = {"blueprint": current["blueprint"], "overrides": current.get("overrides") or {},
                   "changes": current.get("changes") or {}}
    status = template_status()
    # Lookups answer from the case's fixed data, as OFE's would from its records.
    lookups = {name: (lambda *_, data=data: data) for name, data in (case.get("lookups") or {}).items()}
    # Earlier turns of the conversation, if any (e.g. the answer to a question).
    history = None
    for earlier in case.get("before", []):
        history = propose(earlier, project, current=current, workload=case.get("workload"), lookups=lookups,
                          history=history).history
    result = propose(tailor_request(case.get("network")) if case.get("tailor") else case["prompt"].strip(), project,
                     current=current, workload=case.get("workload"), lookups=lookups, history=history)
    return result, hard_failures(result, status) + check(case.get("expect") or {}, result)


def main():
    parser = argparse.ArgumentParser(prog="ofe_agent.behaviour")
    parser.add_argument("--project", required=True, help="target project for validators")
    parser.add_argument("--case", default="", help="only cases whose name contains this")
    parser.add_argument("--out", help="write per-case results as JSON")
    args = parser.parse_args()

    results = []
    for case in yaml.safe_load(CASES.read_text())["cases"]:
        if args.case not in case["name"]:
            continue
        try:
            result, fails = run_case(case, args.project)
            usage, reply = result.usage, kind(result)
        except Exception as err:  # pylint: disable=broad-except
            fails, usage, reply = [f"error: {err}"], {}, None
        results.append({"name": case["name"], "passed": not fails, "failures": fails,
                        "reply": reply, "usage": usage})
        print(f"{'PASS' if not fails else 'FAIL'} {case['name']} ({reply}, {usage.get('seconds')}s,"
              f" {usage.get('gemini_calls')} Gemini calls, {usage.get('tool_calls')} tools)"
              + "".join(f"\n     - {f}" for f in fails), flush=True)
    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
