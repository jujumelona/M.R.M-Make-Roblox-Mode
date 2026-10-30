"""Regression: a host-owned mine may read its verified launch arrival.

Failure log 57: SourceOwnedExtraction...Server used a *real* orbit arrival
created by another first-party module. The per-module ABI saw only the
mineral resource node and rejected the legitimate placement reference.
No generic/model-authored world lookup is newly authorized.
"""
from copy import deepcopy

from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.world_object_abi import world_names, world_lookup_errors
from test_host_space_mineral import fixture


def _offworld_mining_fixture():
    proposal, server, client, _remote = fixture()
    design = proposal.game_design["dynamic_design"]
    # Without an action-owned vehicle gate, this is the standalone mining
    # renderer that generated the code rejected in failure_logs (57).
    materialization = design["host_materialized_world"][0]
    materialization.pop("vehicle_context")
    requirement_id = "req-offworld-mineral"
    design["module_requirements"] = {
        server.module_id: [requirement_id],
        client.module_id: [requirement_id],
    }
    proposal.game_design["pre_design_research"] = {
        "ledger": {"requirements": [{
            "id": requirement_id,
            "statement": "Gather special minerals on other planets",
        }]},
    }
    return proposal, server, client, materialization["resource_node"], (
        design["host_arrival_materializations"][0]["arrival"]
    )


def test_log57_real_host_mine_accepts_exact_cross_module_arrival():
    proposal, server, _client, node, arrival = _offworld_mining_fixture()
    source = render_host_mining(server, proposal)
    assert source is not None
    assert f'workspace:FindFirstChild("{arrival}", true)' in source
    assert f'"{node}"' in source
    _declared, authorized = world_names(proposal, server)
    assert node in authorized
    assert arrival in authorized
    assert world_lookup_errors(source, proposal, server) == []
    problems = generated_module_errors(
        server, proposal, source, LuauStaticAnalyzer()
    )
    assert not any("WORLD_OBJECT_NAME_UNDECLARED" in x for x in problems), problems


def test_log57_unrelated_or_fabricated_world_names_stay_forbidden():
    proposal, server, _client, _node, arrival = _offworld_mining_fixture()
    code = render_host_mining(server, proposal)
    assert code is not None
    forged = code.replace(arrival, "InventedOrbitPad")
    assert any("WORLD_OBJECT_NAME_UNDECLARED" in x
               for x in world_lookup_errors(forged, proposal, server))
    unrelated = 'local p = workspace:FindFirstChild("Craft52E67D11", true)'
    assert world_lookup_errors(unrelated, proposal, server)


def test_log57_unlinked_or_ambiguous_arrival_is_never_authorized():
    for change in ("no_binding", "wrong_builder", "no_arrival",
                   "duplicate_arrival", "wrong_class", "wrong_node"):
        proposal, server, _client, node, arrival = _offworld_mining_fixture()
        design = proposal.game_design["dynamic_design"]
        if change == "no_binding":
            design["host_vehicle_identity_bindings"].clear()
        elif change == "wrong_builder":
            design["host_vehicle_identity_bindings"][0]["builder"] = "UnrelatedBuilder"
        elif change == "no_arrival":
            design["host_arrival_materializations"].clear()
        elif change == "duplicate_arrival":
            design["host_arrival_materializations"].append(deepcopy(
                design["host_arrival_materializations"][0]
            ))
        elif change == "wrong_class":
            for row in design["world_objects"]:
                if row["name"] == arrival:
                    row["class"] = "Model"
        elif change == "wrong_node":
            design["host_materialized_world"][0]["resource_node"] = "UnownedDeposit"
        _, authorized = world_names(proposal, server)
        assert arrival not in authorized, (change, authorized)
        lookup = f'local p = workspace:FindFirstChild("{arrival}", true)'
        assert world_lookup_errors(lookup, proposal, server), change


def test_log57_other_modules_and_client_do_not_inherit_arrival():
    proposal, server, client, node, arrival = _offworld_mining_fixture()
    lookup = f'local p = workspace:FindFirstChild("{arrival}", true)'
    assert world_lookup_errors(lookup, proposal, client)
    builder = next(
        m for m in proposal.modules
        if m.name == "PiecewiseShipCraft4533283Server"
    )
    assert world_lookup_errors(lookup, proposal, builder)
    # A generic different action with only this node's name in its own
    # world manifest is not enough to inherit the offworld read privilege.
    other = deepcopy(server)
    other.name = "UnrelatedActionServer"
    other.module_id = "dyn_unrelated_action"
    other.description = "Display a decorative marker"
    proposal.modules.append(other)
    proposal.game_design["dynamic_design"]["module_world_objects"][other.module_id] = [node]
    assert world_lookup_errors(lookup, proposal, other)


def test_log57_plain_mining_never_requires_arrival():
    proposal, server, _client, node, arrival = _offworld_mining_fixture()
    proposal.game_design["pre_design_research"]["ledger"]["requirements"][0][
        "statement"
    ] = "Gather resources in the current village"
    code = render_host_mining(server, proposal)
    assert code is not None
    assert f'workspace:FindFirstChild("{arrival}", true)' not in code
    _declared, authorized = world_names(proposal, server)
    assert node in authorized
    assert arrival not in authorized
