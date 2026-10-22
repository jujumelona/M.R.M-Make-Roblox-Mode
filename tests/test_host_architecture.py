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
    lambda p: p["systems"][0].update(world_entities=[{"name": "Ore", "position": [1, 2, 3]}]),
    lambda p: p.update(systems=[]),
])
def test_host_rejects_empty_or_unverifiable_gameplay(mutation):
    data = _semantic()
    mutation(data)
    with pytest.raises(HostArchitectureError):
        _convert(data)



@pytest.mark.parametrize("world", [
    ["OreNode"],
    [{"name": "OreNode"}],
    [{"name": " OreNode "}],
    ["OreNode", {"name": "CrystalRock"}],
    [{"name": "외계인"}],
    ["특수 광물"],
])
def test_host_canonicalizes_world_names_without_trusting_engine_metadata(world):
    result = _convert(_semantic(world=world))
    assert len(result["world_objects"]) == len(world)
    assert all(entry["class"] == "Part" for entry in result["world_objects"])
    assert all(entry["position"] != [10_000, 0, 0]
               for entry in result["world_objects"])


@pytest.mark.parametrize("world", [
    [{"name": "OreNode", "size": [4, 4, 4]}],
    [{"name": "OreNode", "class": "Script"}],
    [{"name": "OreNode", "id": "unsafe"}],
    [{"name": 10}],
    [{"name": "OreNode", "position": [9999, 0, 0]}],
    [{"name": ""}],
])
def test_host_world_name_normalization_never_accepts_geometry_or_engine_fields(world):
    with pytest.raises(HostArchitectureError, match="world_entities"):
        _convert(_semantic(world=world))


@pytest.mark.parametrize("server,client", [
    (
        "Server validates the offer, applies the trade transfer and persists both inventories after settlement.",
        "After confirmation the client displays the trade result and the resulting inventory balances.",
    ),
    (
        "The server validates attacks, applies damage and resolves the defeated enemy.",
        "The client renders enemy health, damage numbers, hit confirmation and defeat feedback.",
    ),
    (
        "The server applies damage from a validated attack and removes the defeated enemy.",
        "The client displays the server's confirmed attack outcome and observable combat feedback.",
    ),
])
def test_host_recovers_explicit_player_visible_outcomes_without_extra_model_call(server, client):
    data = _semantic(interaction="request_response")
    data["systems"][0].update(server_behavior=server, client_behavior=client)
    data["systems"][0].pop("observable_result")
    result = _convert(data)
    assert result["acceptance"][0]["observable_result"] == client


@pytest.mark.parametrize("client", [
    "The client shows a request button with no gameplay result or confirmation.",
    "The client renders the interface without showing any outcome.",
])
def test_host_never_invents_results_from_explicitly_empty_feedback(client):
    data = _semantic()
    data["systems"][0]["client_behavior"] = client
    data["systems"][0].pop("observable_result")
    with pytest.raises(HostArchitectureError, match="observable result"):
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
                "Server validates colonization, records a persistent owned settlement "
                "on the planet and updates the colony world state."
                if "colony" in fid else
                "Server implements and validates " + label +
                " player actions and authoritative gameplay state."
            ),
            "client_behavior": "Client displays " + label +
                               " UI and sends a validated player action to the server.",
            "interaction": "event",
            "observable_result": (
                "The player establishes a saved colony settlement and the "
                "planet shows its new owner and territory."
                if "colony" in fid else
                "User performs " + label +
                " actions and sees server-confirmed state updates."
            ),
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


def test_semantic_architect_rejects_pvp_when_requested_hostile_npc_and_settlement():
    wrong = {"systems": [{
        "name": "TargetPlayerCombat",
        "server_behavior": (
            "The server verifies player attack coordinates and damages the "
            "target player health based on proximity."
        ),
        "client_behavior": (
            "The client shows enemy feedback and target player hit damage "
            "after the server confirms."
        ),
        "interaction": "request_response",
        "observable_result": "The target player's health decreases after being shot",
        "world_entities": [],
    }]}
    source = [{"id": "req-001",
               "statement": "Fight alien enemies and colonize a planet"}]
    with pytest.raises(HostArchitectureError, match="SEMANTIC_SOURCE_CONTRACT"):
        expand_semantic_facet(
            wrong, facet_id="intent-combined", requirement_ids=["req-001"],
            source_requirements=source, reserved_modules=set(),
            reserved_remotes=set(), reserved_objects=set())

    correct = {"systems": [
        {"name": "AlienEncounter",
         "server_behavior": (
             "The server validates a player's weapon attacks against "
             "hostile alien NPC enemies, updates enemy health and grants loot."
         ),
         "client_behavior": (
             "The client shows the alien NPC health and a server-confirmed hit."
         ),
         "interaction": "request_response",
         "observable_result": "Enemy aliens receive damage and drop loot.",
         "world_entities": ["AlienEnemy"]},
        {"name": "PlanetSettlement",
         "server_behavior": (
             "The server validates colonization, deducts real resources and "
             "records a persistent owned colony settlement on the planet."
         ),
         "client_behavior": (
             "The client displays the confirmed colony and settlement status."
         ),
         "interaction": "request_response",
         "observable_result": "The planet becomes colonized with persistent settlement.",
         "world_entities": ["Planet"]},
    ]}
    built = expand_semantic_facet(
        correct, facet_id="intent-combined", requirement_ids=["req-001"],
        source_requirements=source, reserved_modules=set(),
        reserved_remotes=set(), reserved_objects=set())
    assert len([m for m in built["modules"] if m["role"] == "server"]) == 2
    assert len(built["remotes"]) == 2


def test_single_facet_rejects_monolithic_multisystem_response_even_if_json_parses():
    """A model must not turn one source action into the whole game's server."""
    from copy import deepcopy
    full = _semantic()
    oversized = deepcopy(full)
    oversized["systems"][0]["server_behavior"] = (
        "The server independently owns player actions, currency, ship building, "
        "combat, navigation, colony founding, space travel and all other gameplay. "
    ) * 12
    with pytest.raises(HostArchitectureError, match="SCOPED_FEATURE_TOO_LARGE"):
        _convert(oversized)
    oversized = deepcopy(full)
    oversized["systems"] = [deepcopy(full["systems"][0]) for _ in range(4)]
    with pytest.raises(HostArchitectureError, match="SCOPED_FEATURE_TOO_LARGE"):
        _convert(oversized)


def test_colony_requires_server_settlement_commit_and_observable_world_result():
    from copy import deepcopy
    raw = _semantic()
    raw["systems"][0]["name"] = "PlanetSettlement"
    raw["systems"][0]["server_behavior"] = (
        "Server saves the weapon inventory and currency. "
        "Server validates a requested planet colonization is allowed."
    )
    raw["systems"][0]["observable_result"] = (
        "The colonization menu displays a successful planet feedback message."
    )
    requirement = [{"id": "req-001", "statement": "Colonize another planet"}]
    with pytest.raises(HostArchitectureError, match="SEMANTIC_SOURCE_CONTRACT"):
        expand_semantic_facet(
            raw, facet_id="intent-colony", requirement_ids=["req-001"],
            source_requirements=requirement,
            reserved_modules=set(), reserved_remotes=set(),
            reserved_objects=set())
    raw = deepcopy(raw)
    raw["systems"][0]["server_behavior"] = (
        "Server validates colonization, charges the known resource cost, "
        "and saves an owned persistent colony settlement on the planet."
    )
    raw["systems"][0]["observable_result"] = (
        "An owned colony settlement is established on the planet and saved."
    )
    result = expand_semantic_facet(
        raw, facet_id="intent-colony", requirement_ids=["req-001"],
        source_requirements=requirement,
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set())
    assert result["modules"]


def test_long_valid_server_action_is_not_rejected_by_arbitrary_prose_length():
    """Reproduce length-only failures: valid trading/mining safety needs >550 chars."""
    from copy import deepcopy
    plan = _semantic()
    service = deepcopy(plan["systems"][0])
    service["server_behavior"] = (
        "The server validates the authenticated player, their owned mining "
        "tool, the nearest resource node, the node's remaining amount, a "
        "reasonable interaction distance and a per-player mining cooldown. "
        "If every condition is valid, it deducts one unit from the node, "
        "increments a stored resource counter and adds an earned currency "
        "reward through the authoritative profile manager. Any malformed "
        "request, deleted node, missing tool or insufficient resource amount "
        "returns a rejection without modifying the profile. The server "
        "serializes concurrent actions by the same player and persists the "
        "updated balance through the profile service. Disconnects cannot "
        "create a second reward and duplicate requests do not produce items. "
        "A valid mining result includes the amount extracted, server current "
        "balance and remaining node capacity."
    )
    assert 550 < len(service["server_behavior"]) < 4096
    service["client_behavior"] = (
        "The player receives the server's validated resource extraction "
        "response and displays the updated owned resources and currency. "
        "The UI shows rejection details for invalid or repeated requests."
    )
    plan["systems"] = [service]
    result = _convert(plan)
    assert result["modules"] and result["acceptance"]


def test_repetitive_description_is_rejected_instead_of_legitimate_detail():
    from copy import deepcopy
    bad = deepcopy(_semantic())
    bad["systems"][0]["server_behavior"] = (
        "The server owns all gameplay and validates the action before processing. "
    ) * 8
    with pytest.raises(HostArchitectureError, match="SCOPED_FEATURE_TOO_LARGE"):
        _convert(bad)


def test_accepted_facet_design_survives_external_document_snippet_churn(
        tmp_path, monkeypatch):
    """Only source + host policy, not search-result ordering, owns plan identity."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    first_model = SemanticOnlySevenFeatureModel()
    original = {"ledger": _user_space_ledger(), "evidence": [{
        "facet": "intent-mining", "provider": "official_docs",
        "grounding": "fetched_official_document",
        "url": "https://create.roblox.com/docs/reference/engine/classes/BasePart",
        "excerpt": "Server validates nearby ore nodes",
        "content_sha256": "stable-source-doc-v1",
    }]}
    first = RobloxDynamicArchitect(
        first_model, checkpoint_dir=tmp_path
    ).design(_PROMPT, original, [])
    assert len(first_model.calls) == 7
    assert len(first["modules"]) == 14
    next_model = SemanticOnlySevenFeatureModel()
    updated_docs = {"ledger": _user_space_ledger(), "evidence": [{
        "facet": "intent-mining", "provider": "official_docs",
        "grounding": "fetched_official_document",
        "url": "https://create.roblox.com/docs/reference/engine/classes/BasePart",
        "excerpt": "Updated API excerpt and publication timestamp",
        "content_sha256": "changed-after-research-refresh",
    }]}
    second = RobloxDynamicArchitect(
        next_model, checkpoint_dir=tmp_path
    ).design(_PROMPT, updated_docs, [])
    assert next_model.calls == []
    assert [x.name for x in second["modules"]] == [
        x.name for x in first["modules"]
    ]
    assert all(row["cache_hit"] for row in updated_docs["architecture_subplans"])
