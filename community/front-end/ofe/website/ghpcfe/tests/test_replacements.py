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

"""Modules that use an existing resource in place of one a blueprint
creates (ofe_agent.toolkit.blueprint.replacements), found from catalog.yaml
and `gcluster explain` alone. Needs the gcluster binary at the repo root."""

import os
import unittest

from ofe_agent.toolkit.blueprint import replacements, uses_existing
from ofe_agent.toolkit.errors import ToolError
from ofe_agent.toolkit.paths import GCLUSTER

HPC_SLURM = "examples/hpc-slurm.yaml"


def sources(path, module_id):
    return [r["source"] for r in replacements(path, module_id)["replacements"]]


class UsesExistingTests(unittest.TestCase):
    def test_by_module_name(self):
        self.assertTrue(uses_existing("modules/network/pre-existing-vpc"))
        self.assertFalse(uses_existing("modules/network/vpc"))


@unittest.skipUnless(os.access(GCLUSTER, os.X_OK), "gcluster is not built")
class ReplacementTests(unittest.TestCase):
    def test_network(self):
        self.assertIn("modules/network/pre-existing-vpc", sources(HPC_SLURM, "network"))

    def test_filesystem(self):
        self.assertEqual(sources(HPC_SLURM, "homefs"), ["modules/file-system/pre-existing-network-storage"])

    def test_only_pre_existing_modules(self):
        for path, mid in ((HPC_SLURM, "network"), (HPC_SLURM, "homefs")):
            self.assertTrue(all(uses_existing(s) for s in sources(path, mid)))

    def test_none_for_modules_without_an_existing_form(self):
        self.assertEqual(sources(HPC_SLURM, "compute_nodeset"), [])

    def test_unknown_module(self):
        with self.assertRaises(ToolError):
            replacements(HPC_SLURM, "nope")


if __name__ == "__main__":
    unittest.main()
