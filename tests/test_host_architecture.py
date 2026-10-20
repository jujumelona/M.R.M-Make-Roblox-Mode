"""Roblox semantic-to-architecture contract: no LLM-owned engine wiring.

The model is asked for gameplay rules, NEVER trustworthy Roblox service
placement, remote kind/name, generated source IDs or coordinate geometry.
"""
import copy
import json

import pytest

from roblox_mod_ai.host_architecture import (
    HostArchitectureError, SEMANTIC_FACET_SCHEMA, expand_semantic_facet,
)
from roblox_mod_ai.dynamic_architect import (
    RobloxDynamicArchitect, _clean_model_json,
)
from test_space_seven_facets_e2e import _PROMPT, _user_space_ledger, _SPACE


def _semantic(name="OreMining", interaction="event", world=None):
    return {"systems": [{
        "name": name,
        "server_behavior": "Server verifies proximity and mining permissions then awards actual ore to inventory.",
        "client_behavior": (
            "Show a mine button, send the requested ore node, display server-confirmed results."
            if interaction != "none" else ""
        ),
        "interaction": interaction,
        "observable_result": "Mining a nearby ore node adds ore to persistent server inventory.",
        "world_entities": ["OreNode"] if world is None else world,
    }]}


def _convert(input_data=None, *, names=None, remotes=None, objects=None):
    return expand_semantic_facet(
        copy.deepcopy(input_data or _semantic()),
        facet_id="intent-mining",
        requirement_ids=["req-001"],
        source_requirements=[{"id": "req-001", "statement": "Mine ore on planets"}],
        reserved_modules=set(names or []),
        reserved_remotes=set(remotes or []),
        reserved_objects=set(objects or []),
    )


def test_host_not_model_decides_every_roblox_specific_field():
    content = _semantic()
    content["remotes"] = [{"name": "UntrustedMoney", "type": "FakeRemote"}]
    content["world_objects"] = [{"class": "Script", "position": [10_000, 0, 0]}]
    content["modules"] = [{"role": "client", "file_path": "src/server/Evil.server.luau"}]
    result = _convert(content)
    server, client = result["modules"]
    assert server["role"] == "server" and client["role"] == "client"
    assert server["name"].endswith("Server")
    assert client["name"].endswith("Client")
    assert server["requirement_ids"] == client["requirement_ids"] == ["req-001"]
    assert server["facet_ids"] == client["facet_ids"] == ["intent-mining"]
    assert server["uses_remotes"] == client["uses_remotes"]
    remote = server["uses_remotes"][0]
    assert result["remotes"] == [{"name": remote, "type": "RemoteEvent"}]
    assert remote != "UntrustedMoney"
    assert len(result["world_objects"]) == 1
    assert result["world_objects"][0]["class"] == "Part"
    assert result["world_objects"][0]["position"] != [10_000, 0, 0]
    assert "Evil" not in json.dumps(result)
    ledger = {
        "requirements": [{"id": "req-001", "statement": "Mine ore on planets"}],
        "facets": [{"id": "intent-mining", "requirements": ["req-001"],
                    "source_span": "Mine ore on planets"}],
        "original_prompt": "Mine ore on planets",
    }
    full = _clean_model_json(result, ledger, set())
    assert len(full["modules"]) == 2
    assert len(full["remotes"]) == 1
    assert len(full["module_remotes"]) == 2


@pytest.mark.parametrize("mode,expected", [
    ("none", None), ("event", "RemoteEvent"),
    ("request_response", "RemoteFunction"),
])
def test_host_owns_remote_type_and_player_role(mode, expected):
    data = _semantic(interaction=mode)
    if mode == "none":
        data["systems"][0].update(
            name="AmbientWorldRegeneration",
            server_behavior="Server periodically regenerates world ore deposits automatically without player input.",
            observable_result="World resource deposits reappear after the automatic regeneration cycle.",
        )
    result = _convert(data)
    if expected:
        assert len(result["modules"]) == 2
        assert result["remotes"][0]["type"] == expected
    else:
        assert len(result["modules"]) == 1
        assert result["remotes"] == []


@pytest.mark.parametrize("mutation", [
    lambda p: p["systems"][0].update(server_behavior="TODO"),
    lambda p: p["systems"][0].update(interaction="RemoteServerInvoke"),
    lambda p: p["systems"][0].update(client_behavior=""),
    lambda p: p["systems"][0].update(observable_result="ok"),
    lambda p: p["systems"][0].update(world_entities=[{"name": "Ore"}]),
    lambda p: p.update(systems=[]),
])
def test_host_rejects_empty_or_unverifiable_gameplay(mutation):
    data = _semantic()
    mutation(data)
    with pytest.raises(HostArchitectureError):
        _convert(data)


def test_rejected_host_name_collision_and_unique_cross_feature_geometry():
    first = _convert()
    with pytest.raises(HostArchitectureError, match="module name collision"):
        _convert(_semantic(),
                 names={x["name"] for x in first["modules"]})
    different = expand_semantic_facet(
        _semantic(), facet_id="intent-second", requirement_ids=["req-002"],
        source_requirements=[{"id": "req-002", "statement": "Mine other ore"}],
        reserved_modules={x["name"] for x in first["modules"]},
        reserved_remotes={x["name"] for x in first["remotes"]},
        reserved_objects={x["name"] for x in first["world_objects"]},
    )
    assert first["world_objects"][0]["name"] != different["world_objects"][0]["name"]
    assert first["world_objects"][0]["position"] != different["world_objects"][0]["position"]


class SemanticOnlySevenFeatureModel:
    def __init__(self):
        self.calls = []
    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        payload = json.loads(prompt.split("\n")[-1])
        fid = payload["feature_id"]
        match = next(row for row in _SPACE if row[1] == fid)
        rid, _, statement, label = match
        assert payload["source_requirements"] == [
            {"id": rid, "statement": statement, "source": "user_prompt"}]
        assert kwargs["json_schema"] == SEMANTIC_FACET_SCHEMA
        assert "module_remotes" not in prompt
        return {"systems": [{
            "name": label,
            "server_behavior": (
                "Server validates alien NPC enemy combat damage health and defeat."
                if "alien" in fid else
                "Server implements and validates " + label +
                " player actions and authoritative gameplay state."
            ),
            "client_behavior": "Client displays " + label +
                               " UI and sends a validated player action to the server.",
            "interaction": "event",
            "observable_result": "User performs " + label +
                                 " actions and sees server-confirmed state updates.",
            "world_entities": ["OreNode"] if "mining" in fid else [],
        }]}


def test_seven_feature_semantic_model_creates_complete_host_owned_contract(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    ledger = _user_space_ledger()
    model = SemanticOnlySevenFeatureModel()
    report = {"ledger": copy.deepcopy(ledger), "evidence": []}
    result = RobloxDynamicArchitect(model).design(_PROMPT, report, [])
    assert len(model.calls) == 7
    assert len(result["modules"]) == 14
    assert len(result["remotes"]) == 7
    assert len(result["module_remotes"]) == 14
    assert len(result["world_objects"]) == 1
    assert len({m.name for m in result["modules"]}) == 14
    assert {f for facets in result["module_facets"].values() for f in facets} == {
        fid for _, fid, _, _ in _SPACE
    }
    assert report["architecture_assembly"]["validated"]
    assert not report["architecture_assembly"]["gameplay_verified"]

@pytest.mark.parametrize("server,client", [
    (
        "The server validates proximity, decrements the resource node and "
        "updates the player's inventory with the mined material.",
        "When the player harvests a node, the client shows the granted "
        "resource amount on success and displays the changed inventory.",
    ),
    (
        "Server validates destination access and teleports the ship to "
        "the chosen planet, recording the destination in player progression.",
        "After a successful launch, the client displays the new planet and "
        "shows a confirmed destination notification.",
    ),
])
def test_host_recovers_missing_observable_from_concrete_model_behavior(server, client):
    """Regression: uploaded mining log omitted observable_result on all tries."""
    data = _semantic()
    system = data["systems"][0]
    system["server_behavior"] = server
    system["client_behavior"] = client
    system.pop("observable_result")
    result = _convert(data)
    assert result["acceptance"][0]["observable_result"] == client
    assert result["acceptance_facets"][0]["observable_result"] == client
    assert "observable_result" not in SEMANTIC_FACET_SCHEMA[
        "properties"]["systems"]["items"]["required"]


@pytest.mark.parametrize("server,client,interaction", [
    (
        "Server validates that requests are well formed and responds with "
        "an error if any validation fails.",
        "Client shows a button to send a request with no gameplay result.",
        "event",
    ),
    (
        "Server grants a resource reward after a validated harvest action.",
        "Client presents an interact button without showing any outcome.",
        "event",
    ),
    (
        "Server updates the resource yield for all players in a world.",
        "Client shows the resulting world yield after update confirmation.",
        "none",
    ),
])
def test_host_missing_observable_does_not_invent_unproven_gameplay(
        server, client, interaction):
    data = _semantic(interaction=interaction)
    system = data["systems"][0]
    system["server_behavior"] = server
    system["client_behavior"] = client
    system.pop("observable_result")
    with pytest.raises(HostArchitectureError, match="observable result"):
        _convert(data)


def test_host_explicit_invalid_observable_is_not_silently_replaced():
    data = _semantic()
    data["systems"][0]["observable_result"] = "ok"
    with pytest.raises(HostArchitectureError, match="observable result"):
        _convert(data)


def test_host_deduplicates_identical_gameplay_with_different_labels():
    raw = _semantic()
    repeated = copy.deepcopy(raw["systems"][0])
    repeated["name"] = "SameMiningUnderAnotherLabel"
    raw["systems"].append(repeated)
    result = _convert(raw)
    assert len(result["modules"]) == 2
    assert len(result["remotes"]) == 1
    assert len(result["acceptance"]) == 1
    assert len(result["world_objects"]) == 1


def test_host_keeps_two_distinct_actions_when_effects_differ():
    raw = _semantic()
    other = copy.deepcopy(raw["systems"][0])
    other["name"] = "SpecialOreMining"
    other["server_behavior"] = (
        "Server checks proximity to rare ore and updates a separate mineral inventory.")
    raw["systems"].append(other)
    result = _convert(raw)
    assert len(result["modules"]) == 4
    assert len(result["remotes"]) == 2


@pytest.mark.parametrize("name,behavior", [
    ("SpaceModeUnlockAndTravel", "Server validates player travel prerequisites then teleports the player to space."),
    ("ResourceMining", "Server validates node mining permission then adds resources to player inventory."),
    ("ShipPartUpgrade", "Server validates ship upgrades then deducts player currency and improves ship stats."),
])
def test_player_driven_mechanics_must_have_a_host_wired_action(name, behavior):
    data = _semantic(name=name, interaction="none", world=[])
    data["systems"][0]["server_behavior"] = behavior
    with pytest.raises(HostArchitectureError, match="interaction=none"):
        _convert(data)


def test_genuinely_autonomous_server_behavior_still_permitted():
    data = _semantic(name="AmbientWorldRegeneration", interaction="none", world=[])
    data["systems"][0]["server_behavior"] = (
        "Server periodically regenerates ore deposits automatically without player input."
    )
    assert len(_convert(data)["modules"]) == 1
