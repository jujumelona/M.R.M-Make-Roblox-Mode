"""Regression from real 2026-10-27 failed architecture ZIP (four systems).

The 9B gameplay planner can describe good world-state semantics but omit,
invert or defer its interaction protocol. The host owns that transport:
logical data must never be made into Workspace Parts just because a Remote
was not attached yet. Preserve real world objects and all original actions.
"""
from copy import deepcopy
from roblox_mod_ai.semantic_world_entities import (
    normalize_logical_state_references, assert_physical_world_entities,
)
from roblox_mod_ai.semantic_input_contract import bind_host_standard_transport


def _raw_system(name, entities, interaction=None, *, mode="custom", physical=""):
    return {
        "name": name,
        "server_behavior": (
            "Server verifies the selected game action, updates server-owned "
            "state, and reports the accepted result. " + physical
        ),
        "observable_result": "The game reflects the accepted server transition.",
        "client_behavior": "Player requests an authenticated game action.",
        "input_mode": mode,
        "interaction": interaction,
        "world_entities": list(entities),
    }


def test_real_four_system_architecture_does_not_create_account_balance_parts():
    raw = {"systems": [
        _raw_system("ResourceGather", ["ResourceBalance"], "none"),
        _raw_system("save_money", ["player_money_balance"]),
        _raw_system("ServerMarketTrade",
                    ["PlayerResourceInventory", "PlayerCurrencyBalance"], "none"),
        _raw_system("InstallShipComponent", [
            "ServerShipAssembly", "PlayerShipComponent", "ShipComponentAttachment",
        ], "none"),
    ]}
    original = deepcopy(raw)
    cleaned, notes = normalize_logical_state_references(raw)
    assert {entry["name"] for entry in notes} == {
        "ResourceBalance", "player_money_balance",
        "PlayerResourceInventory", "PlayerCurrencyBalance",
    }
    assert cleaned["systems"][0]["world_entities"] == []
    assert cleaned["systems"][1]["world_entities"] == []
    assert cleaned["systems"][2]["world_entities"] == []
    assert cleaned["systems"][3]["world_entities"] == [
        "ServerShipAssembly", "PlayerShipComponent", "ShipComponentAttachment",
    ]
    assert [row["name"] for row in cleaned["systems"]] == [
        row["name"] for row in original["systems"]
    ]
    for before, after in zip(original["systems"], cleaned["systems"]):
        assert after["server_behavior"] == before["server_behavior"]
        assert after["observable_result"] == before["observable_result"]
        assert_physical_world_entities(after["world_entities"])
    assert raw == original


def test_host_binding_after_normalization_cannot_resurrect_pseudo_parts():
    raw = {"systems": [
        _raw_system("Earn", ["player_money_balance"], "none"),
        _raw_system("Harvest", ["OreDeposit", "ResourceBalance"], "event"),
    ]}
    normalized, notes = normalize_logical_state_references(raw)
    bound, indexes = bind_host_standard_transport(normalized)
    assert len(notes) == 2
    for row in bound["systems"]:
        assert "ResourceBalance" not in row["world_entities"]
        assert "player_money_balance" not in row["world_entities"]
        assert_physical_world_entities(row["world_entities"])
    assert bound["systems"][1]["world_entities"] == ["OreDeposit"]


def test_true_world_prompt_and_explicit_real_object_keep_strict_physical_check():
    world_prompt = {"systems": [
        _raw_system("Tap", ["TradeRequest"], "event", mode="world_prompt"),
        _raw_system(
            "ReachRequest", ["TradeRequest"], None, mode="custom",
            physical="Player clicks the Trade Request near its Workspace position.",
        ),
    ]}
    unchanged, notes = normalize_logical_state_references(world_prompt)
    assert not notes and unchanged == world_prompt
    # The physical validator still rejects an improperly named physical
    # target if the model explicitly claims one; do not hide that defect.
    from pytest import raises
    with raises(ValueError, match="WORLD_ENTITY_LOGICAL_STATE_NOT_PHYSICAL"):
        assert_physical_world_entities(["TradeRequest"])


def test_typed_explicit_target_is_never_silently_demoted_into_server_state():
    raw = {"systems": [
        dict(_raw_system("Selected", ["PlayerCurrencyBalance"]),
             action_contract={"target": {"kind": "world_entity",
                                          "name": "PlayerCurrencyBalance"}}),
    ]}
    cleaned, notes = normalize_logical_state_references(raw)
    assert cleaned == raw
    assert notes == []
