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

"""CLI: python -m ofe_agent --project my-proj "cheap GROMACS cluster" """

import argparse
import dataclasses
import json
import os
import sys

import yaml

from .chat import propose
from .gemini import DEFAULT_MODEL


def main():
    parser = argparse.ArgumentParser(prog="ofe_agent")
    parser.add_argument("prompt")
    parser.add_argument(
        "--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="raw result")
    args = parser.parse_args()
    if not args.project:
        parser.error("--project or GOOGLE_CLOUD_PROJECT is required")

    result = propose(args.prompt, args.project, model=args.model)

    if args.json:
        json.dump(dataclasses.asdict(result), sys.stdout, indent=2)
        print()
        return

    for step in result.trace:
        err = f"  -> {step['error']}" if step["error"] else ""
        print(f"[tool] {step['tool']} {step['args']}{err}")
    print("\n" + result.answer)
    if result.question:
        print(f"\nQuestion: {result.question}" + (f"  {result.choices}" if result.choices else ""))
    for n, approach in enumerate(result.approaches, 1):
        print(f"\nApproach {n}: {approach['title']}\n  {approach['description']}")
    for n, option in enumerate(result.options, 1):
        p = result.proposals[option["proposal"]]
        status = "VALID" if p["validation"]["valid"] else "INVALID"
        print(f"\n--- Option {n}: {option['title']} ({status}) ---\n{option['reason']}\n{p['blueprint']}")
        print(yaml.safe_dump(p["deployment"], sort_keys=False), end="")
        changes = {k: v for k, v in p["changes"].items() if v}
        if changes:
            print(yaml.safe_dump({"changes": changes}, sort_keys=False), end="")
        if not p["validation"]["valid"]:
            print(p["validation"]["output"])


if __name__ == "__main__":
    main()
