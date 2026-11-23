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

"""Deployment group roles and custom-image detection (ofe_agent.toolkit.stages)
on catalog blueprints from this checkout. Reads YAML only: no gcluster."""

import unittest

from ofe_agent.toolkit import stages

A3MEGA = "examples/machine-learning/a3-megagpu-8g/a3mega-slurm-blueprint.yaml"
A4XMAX = "examples/machine-learning/a4x-maxgpu-4g-metal/a4xmax-bm-slurm-blueprint.yaml"
IMAGE_ONLY = "examples/machine-learning/build-service-images/common/blueprint.yaml"
NO_IMAGE = "examples/machine-learning/a4-highgpu-8g/a4high-slurm-blueprint.yaml"


def roles(path):
    return {s["group"]: s["role"] for s in stages.stages(path)}


class RoleTests(unittest.TestCase):
    def test_image_build_groups(self):
        self.assertEqual(roles(A3MEGA), {"primary": "cluster", "build_script": "image-support",
                                         "slurm-build": "image", "cluster": "cluster"})

    def test_network_the_build_uses_is_shared(self):
        shared = {s["group"] for s in stages.stages(A3MEGA) if s.get("shared")}
        self.assertEqual(shared, {"primary"})

    def test_network_only_the_build_uses_is_image_support(self):
        self.assertEqual(roles(A4XMAX)["image-env"], "image-support")
        self.assertEqual(roles(A4XMAX)["cluster-env"], "cluster")

    def test_no_packer_group_no_image(self):
        self.assertEqual(set(roles(NO_IMAGE).values()), {"cluster"})
        self.assertIsNone(stages.image(NO_IMAGE))


class ImageTests(unittest.TestCase):
    def test_family_from_its_var(self):
        im = stages.image(A3MEGA)
        self.assertEqual(im["family_var"], "final_image_family")
        self.assertEqual(im["family"], "slurm-a3mega")
        self.assertFalse(im["image_only"])
        self.assertEqual(im["groups"], ["build_script", "slurm-build"])

    def test_image_only_recipe(self):
        self.assertTrue(stages.image(IMAGE_ONLY)["image_only"])

    def test_hash_ignores_where_and_for_whom(self):
        base = stages.recipe_hash(A3MEGA)
        self.assertRegex(base, r"^[0-9a-f]{16}$")
        self.assertEqual(base, stages.recipe_hash(A3MEGA, {
            "project_id": "other", "deployment_name": "two", "zone": "europe-west4-b",
            "image_build_machine_type": "n2-standard-8", "final_image_family": "another-family",
            "a3mega_cluster_size": 64,
        }))

    def test_hash_follows_what_goes_into_the_image(self):
        base = stages.recipe_hash(A3MEGA)
        self.assertNotEqual(base, stages.recipe_hash(A3MEGA, {"build_slurm_from_git_ref": "6.9.0"}))
        self.assertNotEqual(base, stages.recipe_hash(A3MEGA, {"base_image": {"project": "p", "image": "i"}}))


class ResolveTests(unittest.TestCase):
    def test_nested_and_per_deployment_refs(self):
        values = {"img": {"family": "$(vars.fam)"}, "fam": "f1"}
        self.assertEqual(stages.resolve("$(vars.img.family)", values), "f1")
        self.assertEqual(stages.resolve("$(vars.deployment_name)-x", values), "<deployment_name>-x")
        self.assertEqual(stages.resolve({"a": ["$(vars.fam)"]}, values), {"a": ["f1"]})


if __name__ == "__main__":
    unittest.main()
