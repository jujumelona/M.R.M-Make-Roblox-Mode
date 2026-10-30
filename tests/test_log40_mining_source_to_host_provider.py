"""Log40: exact source-owned harvest regression and executable host mining handoff.

The uploaded 40th log failed on "자원파밍" despite a verified atomic
source action "Server marks the authoritative mineable world source as
harvested and extracts the corresponding resource into the player's owned
resource inventory." This is both a harvest and a directed inventory grant.
The old grounded gate required the literal verb "increment", and the host
miner previously required a Mining-labelled service. Neither requirement
is a legitimate gameplay constraint.
"""
from copy import deepcopy

from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems
from roblox_mod_ai.grounded_atomic_source_effects import (
    preserved_world_inventory_extraction,
)
from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.model_action_authority import unproven_model_actions
from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec, ModuleKind, RobloxService


CLAUSE = "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 부위마다 만들어서 만들수있고"
ACTION = {
    "source_quote": "자원파밍",
    "action": (
        "Server marks the authoritative mineable world source as harvested "
        "and extracts the corresponding resource into the player's owned "
        "resource inventory."
    ),
}


class ForbidModel:
    supports_host_standard_transport = True

    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Do not rewrite a complete source-owned mining effect")


def test_log40_exact_source_is_recognized_as_owned_inventory_gain():
    result = preserved_world_inventory_extraction(
        ACTION, original_prompt=CLAUSE,
    )
    assert result is not None
    assert ACTION["action"] in result["server_behavior"]
    assert "inventory increases" in result["observable_result"]
    assert result["world_entities"] == []


def test_log40_full_atomic_author_accepts_same_source_without_model_rephrasing():
    output = author_verified_atomic_systems(
        ForbidModel(), [ACTION], source_clause=CLAUSE,
        original_prompt=CLAUSE,
        json_schema={"type": "object", "properties": {
            "systems": {"type": "array", "items": {"type": "object"}},
        }},
    )
    assert len(output) == 1
    assert output[0]["name"].startswith("SourceOwnedExtraction")


def test_log40_reverse_transfer_or_missing_source_is_not_extraction():
    for description in (
        "Server extracts the player's owned resource inventory into a mineable node.",
        "Server views a mineable world source and grants a reward in the UI.",
        "Server extracts ore from inventory into the world deposit.",
        "Server extracts resource from a mineable world source but does not add it to the player's owned inventory.",
        "Server checks a mineable deposit and extracts a resource but does not change the player's owned inventory.",
    ):
        assert preserved_world_inventory_extraction(
            dict(ACTION, action=description), original_prompt=CLAUSE,
        ) is None, description


def mining_plan():
    # An action whose generated NAME is not an English mining keyword.
    server = RobloxModuleSpec(
        module_id="dyn_log40_server",
        name="SourceOwnedExtractionA1Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/SourceOwnedExtractionA1Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=ACTION["action"],
    )
    client = RobloxModuleSpec(
        module_id="dyn_log40_client",
        name="SourceOwnedExtractionA1Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/SourceOwnedExtractionA1Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Player collects the harvested resource into owned inventory.",
    )
    remote = "SourceOwnedExtractionA1Action"
    return RobloxProposal(
        requested_prompt=CLAUSE,
        game_title="UserMining",
        description="Source-authored resource acquisition",
        game_design={"dynamic_design": {
            "host_actions": {remote: {
                "service": server.name, "kind": "RemoteFunction",
                "max_args": 2,
            }},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {server.module_id: [remote], client.module_id: [remote]},
            "module_world_objects": {server.module_id: [], client.module_id: []},
            "host_typed_actions": {remote: {
                "transport_only": True,
                "server": server.name, "client": client.name,
                "contract": {
                    "inputs": [
                        {"id": "selection", "label": "Selection", "type": "string"},
                        {"id": "quantity", "label": "Quantity", "type": "integer"},
                    ],
                    "target": {"kind": "none"},
                    "state_changes": [],
                },
            }},
            "world_objects": [],
            "host_world_actions": {},
        }},
        modules=[server, client],
    )


def test_log40_rebase_creates_real_resource_node_and_host_luau_both_roles():
    p = mining_plan()
    design = p.game_design["dynamic_design"]
    before = deepcopy(design)
    assert render_host_mining(p.modules[0], p) is None
    updates = ensure_mining_world_contract(p)
    assert len(updates) == 1
    assert updates[0]["transport_rebased"] is True
    assert updates[0]["input"] == "RemoteFunction_server_selected_nearest_Part"
    assert design["host_typed_actions"] == {}
    assert design["host_actions"]["SourceOwnedExtractionA1Action"]["max_args"] == 0
    assert len(design["world_objects"]) == 1
    node = design["world_objects"][0]
    assert node["class"] == "Part" and node["name"].startswith("ResourceNode")
    server_code = render_host_mining(p.modules[0], p)
    client_code = render_host_mining(p.modules[1], p)
    assert server_code is not None
    assert client_code is not None
    assert "GetState(player, \"RMMInventory\")" in server_code
    assert "node.remaining -= 1" in server_code
    assert "progress.resources = balance + 1" in server_code
    assert "select(\"#\", ...) ~= 0" in server_code
    assert "remote:InvokeServer()" in client_code
    assert not ensure_mining_world_contract(p)
    scope = generation_scope(p)
    routed = {row["name"]: row["strategy"] for row in scope["modules"]}
    assert routed[p.modules[0].name] == "host_verified_template"
    assert routed[p.modules[1].name] == "host_verified_template"
    assert unproven_model_actions(p, scope) == []


def test_log40_no_world_or_route_mutation_for_unrequested_or_weak_extraction():
    p = mining_plan()
    p.requested_prompt = "Build a spaceship without gathering resources"
    before = deepcopy(p.game_design["dynamic_design"])
    assert not ensure_mining_world_contract(p)
    assert before == p.game_design["dynamic_design"]

    p = mining_plan()
    p.modules[0].description = (
        "Server checks a mineable world source then displays resource gains "
        "but does not extract into the player's owned inventory."
    )
    before = deepcopy(p.game_design["dynamic_design"])
    assert not ensure_mining_world_contract(p)
    assert before == p.game_design["dynamic_design"]


def test_two_source_owned_mining_intents_never_merge_ordinary_and_special_inventory():
    """Resource identity follows specific original requirement, not module names."""
    ordinary = mining_plan()
    special = mining_plan()
    ordinary_source = "Gather ordinary ore and trade it"
    special_source = "Mine special minerals on another planet"
    for proposal, statement in ((ordinary, ordinary_source),
                                (special, special_source)):
        source_server = proposal.modules[0]
        source_client = proposal.modules[1]
        proposal.requested_prompt = statement
        proposal.game_design["pre_design_research"] = {
            "ledger": {"requirements": [{"id": "r", "statement": statement}]}
        }
        proposal.game_design["dynamic_design"]["module_requirements"] = {
            source_server.module_id: ["r"], source_client.module_id: ["r"],
        }
        ensure_mining_world_contract(proposal)
        if proposal is special:
            dynamic = proposal.game_design["dynamic_design"]
            dynamic["world_objects"].append({
                "name": "VerifiedOrbitArrival", "class": "Part",
                "position": [0, 8000, 0],
            })
            dynamic["host_arrival_materializations"] = [{
                "server": "VerifiedSpaceLaunchServer",
                "arrival": "VerifiedOrbitArrival",
                "builder": "OwnedVehicleBuilderServer",
            }]
        server = render_host_mining(source_server, proposal)
        client = render_host_mining(source_client, proposal)
        assert server is not None and client is not None
        if proposal is special:
            assert "progress.specialMinerals = balance + 1" in server
            assert "progress.resources = balance + 1" not in server
            assert "specialMinerals = progress.specialMinerals" in server
            assert "result.specialMinerals" in client
            assert "result.resources" not in client
            assert 'workspace:FindFirstChild("VerifiedOrbitArrival", true)' in server
            assert 'part.CFrame = arrival.CFrame * CFrame.new(' in server
            assert 'player:GetAttribute("RMMFlightState") ~= "arrived"' in server
        else:
            assert "progress.resources = balance + 1" in server
            assert "progress.specialMinerals" not in server
            assert "result.resources" in client
            assert "result.specialMinerals" not in client
        from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
        analyzer = LuauStaticAnalyzer()
        for module, source in ((source_server, server), (source_client, client)):
            errors = [row for row in analyzer.analyze_source(source, module.file_path)
                      if row.severity == "ERROR"]
            assert not errors, [(row.rule, row.message) for row in errors]


def test_unrelated_prompt_cannot_turn_plain_mining_into_special_currency():
    proposal = mining_plan()
    proposal.requested_prompt = "There is also a quest for special minerals elsewhere"
    proposal.game_design["dynamic_design"]["module_requirements"] = {
        proposal.modules[0].module_id: ["r"],
    }
    proposal.game_design["pre_design_research"] = {
        "ledger": {"requirements": [{"id": "r", "statement": "Harvest ordinary ore"}]}
    }
    ensure_mining_world_contract(proposal)
    source = render_host_mining(proposal.modules[0], proposal)
    assert source and "progress.resources = balance + 1" in source
    assert "progress.specialMinerals" not in source


def test_offworld_special_mineral_without_real_destination_is_not_host_certified():
    proposal = mining_plan()
    statement = "Mine special minerals on another planet"
    proposal.game_design["pre_design_research"] = {
        "ledger": {"requirements": [{"id": "req", "statement": statement}]}
    }
    proposal.game_design["dynamic_design"]["module_requirements"] = {
        m.module_id: ["req"] for m in proposal.modules
    }
    ensure_mining_world_contract(proposal)
    assert render_host_mining(proposal.modules[0], proposal) is None
    assert render_host_mining(proposal.modules[1], proposal) is None
