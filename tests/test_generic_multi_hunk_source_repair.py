"""Multiple independent source edits, one owner and transactional validation."""
import pytest

from roblox_mod_ai.source_repair_cycle import (
    _apply_scoped_hunks,
    _repair_host_action_scoped,
)


SOURCE = (
    "--!strict\n"
    "local function apply(player, state)\n"
    "    if not player then return false end\n"
    "    state.level += 1\n"
    "    return {success = true, level = state.level}\n"
    "end\n"
)


def test_server_effect_can_be_repaired_at_three_independent_sites():
    edits = [
        {"before": "    if not player then return false end",
         "after": "    if not player or not state then return false end"},
        {"before": "    state.level += 1",
         "after": "    state.level += 1\n    state.power += 1"},
        {"before": "    return {success = true, level = state.level}",
         "after": "    return {success = true, level = state.level, power = state.power}"},
    ]
    result = _apply_scoped_hunks(SOURCE, edits, [SOURCE])
    assert result.count("state.power += 1") == 1
    assert "power = state.power" in result
    assert "if not player or not state" in result
    assert "local function apply" in result


@pytest.mark.parametrize("edits", [
    [{"before": "state.level += 1", "after": "state.level += 2"},
     {"before": "state.level += 1", "after": "state.level += 3"}],
    [{"before": "    state.level += 1",
      "after": "    state.level += 2"},
     {"before": "    state.level += 1\n    return {success = true",
      "after": "    state.power += 1"}],
    [{"before": "    state.level += 1", "after": "    -- no operation"}],
    [],
    [{"before": "    state.level += 1", "after": "    state.level += 2"}] * 5,
])
def test_invalid_or_overlapping_patches_fail(edits):
    with pytest.raises(ValueError):
        _apply_scoped_hunks(SOURCE, edits, [SOURCE])


def test_bounded_host_repair_accepts_model_multi_hunk_json():
    class Model:
        def complete_json(self, **kwargs):
            assert "source_windows" in kwargs["prompt"]
            return {"edits": [
                {"before": "    state.level += 1",
                 "after": "    state.level += 1\n    state.power += 1"},
                {"before": "    return {success = true, level = state.level}",
                 "after": "    return {success = true, level = state.level, power = state.power}"},
            ]}
    modified = _repair_host_action_scoped(
        SOURCE, "src/server/Upgrade.luau",
        [{"quote": "state.level += 1",
          "issue": "Only an inert level is updated",
          "repair": "Persist real ship power and return the new power"}],
        {"root_cause": "Missing consumed performance effect",
         "change_strategy": "Update actual owned state and client result"},
        Model(),
    )
    assert "state.power += 1" in modified
    assert "power = state.power" in modified


def test_old_single_hunk_response_remains_compatible():
    class Legacy:
        def complete_json(self, **kwargs):
            return {"before": "    state.level += 1",
                    "after": "    state.power += 1"}
    changed = _repair_host_action_scoped(
        SOURCE, "src/server/Upgrade.luau",
        [{"quote": "state.level += 1"}],
        {"root_cause": "Level is disconnected", "change_strategy": "Update power"},
        Legacy(),
    )
    assert "state.power += 1" in changed
