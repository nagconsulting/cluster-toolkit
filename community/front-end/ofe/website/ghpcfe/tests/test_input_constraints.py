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

"""The Cluster Builder's checks of module input values against the
`constraints` `gcluster explain` reports (ofe_agent.toolkit.values)."""

import unittest

from ofe_agent.toolkit.errors import ToolError
from ofe_agent.toolkit.values import check_input_value


def info(type_="string", **constraints):
    return {"type": type_, "constraints": constraints or None}


class InputConstraintTests(unittest.TestCase):

    def test_no_constraints_accepts_any_value_of_the_type(self):
        check_input_value("x", info(), "anything")
        check_input_value("x", info("number"), -5)

    def test_allowed_values(self):
        i = info(allowed_values=["BASIC_HDD", "BASIC_SSD"])
        check_input_value("tier", i, "BASIC_SSD")
        with self.assertRaisesRegex(ToolError, "must be one of"):
            check_input_value("tier", i, "basic_ssd")

    def test_case_insensitive_allowed_values(self):
        i = info(allowed_values=["tigervnc", "turbovnc"], case_insensitive=True)
        check_input_value("vnc_backend", i, "TigerVNC")
        with self.assertRaisesRegex(ToolError, "must be one of"):
            check_input_value("vnc_backend", i, "x11vnc")

    def test_inclusive_bounds(self):
        i = info("number", min=1024, max=2048)
        check_input_value("size_gb", i, 1024)
        check_input_value("size_gb", i, 2048)
        with self.assertRaisesRegex(ToolError, "at least 1024"):
            check_input_value("size_gb", i, 1000)
        with self.assertRaisesRegex(ToolError, "at most 2048"):
            check_input_value("size_gb", i, 4096)

    def test_exclusive_bounds(self):
        i = info("number", min=0, min_exclusive=True, max=65536, max_exclusive=True)
        check_input_value("resume_timeout", i, 1)
        with self.assertRaisesRegex(ToolError, "more than 0"):
            check_input_value("resume_timeout", i, 0)
        with self.assertRaisesRegex(ToolError, "less than 65536"):
            check_input_value("resume_timeout", i, 65536)

    def test_pattern_matches_anywhere_unless_anchored(self):
        check_input_value("name", info(pattern="[0-9]"), "abc1def")
        i = info(pattern="^[a-z](?:[a-z0-9-]*)$")
        check_input_value("partition_name", i, "debug-1")
        with self.assertRaisesRegex(ToolError, "must match"):
            check_input_value("partition_name", i, "Debug")

    def test_var_references_are_left_to_gcluster(self):
        i = info(allowed_values=["a"])
        check_input_value("x", i, "$(vars.zone)", refs=("zone",))


if __name__ == "__main__":
    unittest.main()
