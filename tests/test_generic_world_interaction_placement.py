"""Generic scene layout, with unrelated genres and authored spawn transforms."""
import math
import pytest

from roblox_mod_ai.world_interaction_placement import (
    place_first_interaction, spawn_anchor, spawn_size,
)
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.spec import RobloxProposal


def test_farm_spawn_changes_actual_rojo_spawn_and_resource_placement(tmp_path):
    plan = RobloxProposal(
        requested_prompt="Farm delivery jobs", game_title="Farm",
        description="", modules=[], game_design={"dynamic_design": {
            "spawn_position": [380, 7, -125],
            "spawn_size": [14, 2, 14],
            "world_objects": [],
            "remotes": {},
        }},
    )
    anchor = spawn_anchor(plan.game_design)
    dims = spawn_size(plan.game_design)
    props = RobloxProjectGenerator(tmp_path).generate_rojo_project_json(
        plan)["tree"]["Workspace"]["SpawnLocation"]["$properties"]
    assert props["CFrame"][:3] == list(anchor)
    assert props["Size"] == list(dims)
    pos = place_first_interaction(
        [], anchor=anchor, spawn_bounds=dims,
        max_distance=18
    )
    assert pos[0] > 300 and pos[2] < -50
    assert math.dist(anchor, pos) < 18
    # No intersection with the actual extended SpawnLocation footprint.
    assert abs(pos[0] - anchor[0]) >= (14 + 4) / 2 + 1 or (
        abs(pos[2] - anchor[2]) >= (14 + 4) / 2 + 1
    )


def test_other_altitude_structures_do_not_block_ground_resource():
    near = place_first_interaction(
        [{"name": "Airship", "class": "Part",
          "position": [0, 300, 0], "size": [200, 20, 200]}],
        anchor=(0, 1, 0),
    )
    assert math.dist(near, (0, 1, 0)) < 18


def test_impassable_occupied_scene_raises_instead_of_faraway_fake_node():
    with pytest.raises(ValueError, match="No collision-free"):
        place_first_interaction(
            [{"name": "EntireArena", "class": "Part",
              "position": [0, 4, 0], "size": [100, 12, 100]}],
            anchor=(0, 1, 0),
        )


def test_invalid_scene_or_spawn_geometry_never_guesses():
    with pytest.raises(ValueError):
        spawn_anchor({"dynamic_design": {
            "spawn_position": ["wrong", 1, 2],
        }})
    with pytest.raises(ValueError):
        place_first_interaction(
            [{"name": "Broken", "position": [1, 2, 3]}],
            anchor=(0, 1, 0),
        )
