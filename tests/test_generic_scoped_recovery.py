"""Prompt-invariant scoped repair and world-ABI regression tests."""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from roblox_mod_ai.scoped_action_recovery import (
    attempt_fingerprint, scoped_action_retry_prompt,
)
from roblox_mod_ai.world_object_abi import world_lookup_guidance


class GenericRecoveryTests(unittest.TestCase):
    def test_earliest_type_error_is_not_trimmed_out(self):
        attempts = [{
            "candidate": "local target = workspace:FindFirstChild('Artifact')",
            "diagnostics": [
                "WORLD_INSTANCE_TYPE_IMPOSSIBLE: Artifact is Part, not Model",
                "DEPENDENCY_SERVICE_UNKNOWN: no InventoryService",
                "SELENE_UNDEFINED_VARIABLE: missing state",
            ],
        }]
        prompt = scoped_action_retry_prompt(attempts)
        self.assertIn("WORLD_INSTANCE_TYPE_IMPOSSIBLE", prompt)
        self.assertIn("DEPENDENCY_SERVICE_UNKNOWN", prompt)
        self.assertIn("SELENE_UNDEFINED_VARIABLE", prompt)
        self.assertIn("Part is not a Model", prompt)
        self.assertIn("exported methods", prompt)
        self.assertIn("GetState", prompt)

    def test_repeating_same_body_changes_repair_strategy(self):
        row = {"candidate": "local bad = nonexistent", "diagnostics": [
            "SELENE_UNDEFINED_VARIABLE: nonexistent"]}
        prompt = scoped_action_retry_prompt([row, dict(row)])
        self.assertIn("REPEATED FAILURE", prompt)
        self.assertIn("requested mutation", prompt)
        self.assertNotIn("workspace.Spaceship", prompt)

    def test_changed_body_does_not_count_as_identical(self):
        self.assertNotEqual(attempt_fingerprint("a = 1"),
                            attempt_fingerprint("a = 2"))

    def test_empty_history_does_not_add_repair(self):
        self.assertEqual(scoped_action_retry_prompt([]), "")

    def test_materialized_classes_are_explicit_and_locally_scoped(self):
        design = {
            "world_objects": [
                {"name": "Artifact", "class": "Part"},
                {"name": "Machine", "class": "Model"},
                {"name": "Unrelated", "class": "MeshPart"},
            ],
            "module_world_objects": {"dyn_test": ["Artifact", "Machine"]},
        }
        proposal = SimpleNamespace(game_design={"dynamic_design": design})
        module = SimpleNamespace(module_id="dyn_test", kind="client_script",
                                 name="GenericActionClient")
        result = world_lookup_guidance(proposal, module)
        self.assertIn('"name": "Artifact", "class": "Part"', result)
        self.assertIn('"name": "Machine", "class": "Model"', result)
        self.assertNotIn("Unrelated", result)
        self.assertNotIn("Spaceship", result)
        self.assertIn("architectural", result)


if __name__ == "__main__":
    unittest.main()
