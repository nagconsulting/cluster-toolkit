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

"""The Cluster Builder's blueprint views (ofe_agent.toolkit.view).

The page shows a blueprint without its vars: and lists the defaults
separately; the download keeps every default but not the
example's comments. Neither may change what the blueprint means.
"""

import unittest

import yaml

from ofe_agent.toolkit import view

BLUEPRINT = """\
# Copyright 2026 Google LLC
# (licence text)

---

blueprint_name: demo

vars:
  project_id:  ## Set GCP Project ID Here ##
  deployment_name: demo
  # --- Provisioning (pick only one) ---
  reservation_name: ""  # supply reservation name
  enable_spot: false
# A note at the start of a line, still inside vars:
  image:
    family: $(vars.image_family)
    project: $(vars.project_id)

# Modules are deployed in this order.
deployment_groups:
- group: primary
  modules:
  - id: network  # the cluster network
    source: modules/network/vpc
"""


class ViewTextTests(unittest.TestCase):
    def test_leaves_out_vars_and_the_licence(self):
        text = view.view_text(BLUEPRINT)
        self.assertNotIn("vars:", text)
        self.assertNotIn("Copyright", text)
        self.assertNotIn("pick only one", text)
        self.assertTrue(text.startswith("blueprint_name: demo"))

    def test_keeps_everything_else(self):
        text = view.view_text(BLUEPRINT)
        self.assertIn("# Modules are deployed in this order.", text)
        self.assertIn("# the cluster network", text)
        expected = yaml.safe_load(BLUEPRINT)
        del expected["vars"]
        self.assertEqual(yaml.safe_load(text), expected)


class CleanTextTests(unittest.TestCase):
    def test_same_blueprint_plus_ai_assisted(self):
        doc = yaml.safe_load(view.clean_text(BLUEPRINT))
        self.assertIs(doc.pop("ai_assisted"), True)
        self.assertEqual(doc, yaml.safe_load(BLUEPRINT))

    def test_vars_without_comments_rest_unchanged(self):
        text = view.clean_text(BLUEPRINT)
        vars_block = text[text.index("\nvars:"):text.index("deployment_groups:")]
        self.assertNotIn("#", vars_block.replace("# Modules are deployed in this order.", ""))
        self.assertTrue(text.startswith("# Copyright 2026 Google LLC"))
        self.assertIn("# the cluster network", text)

    def test_ai_assisted_not_repeated(self):
        once = view.clean_text(BLUEPRINT)
        self.assertEqual(view.clean_text(once).count("ai_assisted"), 1)


if __name__ == "__main__":
    unittest.main()
