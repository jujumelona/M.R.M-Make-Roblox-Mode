"""Regression for actual orbital mining Part/Model hallucinations in RMM logs.

The server and UI must be first-party and no-argument; neither can be sent
to a short coding model to invent workspace Model types and remotes.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_space_mineral import eligible_space_mineral, render_space_mineral
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind


class NoModel:
    def complete(self, *a, **kw):
        raise AssertionError("The 9B model must not write mineral-harvest Luau")
    def complete_json(self, *a, **kw):
        raise AssertionError("The 9B model must not write mineral-harvest JSON bodies")


def fixture():
    server = NS(
        module_id="dyn_201810400968",
        name="SpecialMineralHarvesting52E67D2Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/SpecialMineralHarvesting52E67D2Server.luau",
        description=("Server-owned mineral harvesting state is enabled only "
                     "while the craft is in space; player input is required "
                     "to harvest, and invalid inputs are rejected when the "
                     "craft is not in space or the player is not aboard."),
        code="",
    )
    client = NS(
        module_id="dyn_5ec49d07c67d",
        name="SpecialMineralHarvesting52E67D2Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/SpecialMineralHarvesting52E67D2Client.client.luau",
        description="Host sends validated player input fields to server Remote",
        code="",
    )
    builder = NS(
        module_id="dyn_real_ship", name="PiecewiseShipCraft4533283Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/PiecewiseShipCraft4533283Server.luau",
        description="Server-owned ship assembly with GetOwnedActor",
        code="",
    )
    launch = NS(
        module_id="dyn_launch", name="LaunchCraftIntoSpace52E67D1Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/LaunchCraftIntoSpace52E67D1Server.luau",
        description="Launch real craft to orbit",
        code="",
    )
    remote = "SpecialMineralHarvesting52E67D2Action"
    node = "ResourceNode4E4CE2163F1"
    arrival = "RMMOrbitArrival_ced7651c1e"
    plan = NS(
        requested_prompt="우주로 나가면 다른 행성에서 특수 광물 채굴하는 게임",
        game_design={"dynamic_design": {
            "host_actions": {remote: {
                "service": server.name, "kind": "RemoteFunction", "max_args": 0,
            }},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {
                server.module_id: [remote], client.module_id: [remote],
            },
            "host_materialized_world": [{
                "service": server.name, "resource_node": node,
                "transport_rebased": True,
                "input": "RemoteFunction_server_selected_nearest_Part",
                "reward": {"namespace": "RMMInventory", "key": "specialMinerals",
                           "attribute": "RMMSpecialMinerals",
                           "label": "Collect special minerals"},
            }],
            "module_world_objects": {
                server.module_id: [
                    "Craft52E67D11", "Occupants52E67D12", node,
                ],
            },
            "world_objects": [
                {"name": "Craft52E67D11", "class": "Part"},
                {"name": "Occupants52E67D12", "class": "Part"},
                {"name": node, "class": "Part"},
                {"name": arrival, "class": "Part"},
            ],
            "host_vehicle_identity_bindings": [{
                "server": launch.name, "builder": builder.name,
                "actor_provider": "GetOwnedActor",
                "physical_assembly_verified": False,
            }],
            "host_arrival_materializations": [{
                "server": launch.name, "builder": builder.name,
                "arrival": arrival, "studio_verified": False,
            }],
        }},
        modules=[builder, launch, server, client],
    )
    return plan, server, client, remote


def test_failed_codegen_uses_both_verified_host_adapters():
    plan, server, client, remote = fixture()
    for module in (server, client):
        match = eligible_space_mineral(module, plan)
        assert match and match[1] == remote
    scope = generation_scope(plan)
    strategy = {r["name"]: r["strategy"] for r in scope["modules"]}
    assert strategy[server.name] == "host_contextual_harvest"
    assert strategy[client.name] == "host_contextual_harvest"
    coder = LuauCodeGenerator(NoModel())
    server_code = coder.generate_with_self_correction(server, plan)
    client_code = coder.generate_with_self_correction(client, plan)
    assert server_code == render_space_mineral(server, plan)
    assert client_code == render_space_mineral(client, plan)
    assert 'GetOwnedActor(player)' in server_code
    assert 'GetState(player, "RMMInventory")' in server_code
    assert 'local INVENTORY_FIELD = "specialMinerals"' in server_code
    assert 'inventory[INVENTORY_FIELD] = count + 1' in server_code
    assert 'services.PlayerDataManager.OnReady(function(player)' in server_code
    assert 'local RESOURCE_ATTRIBUTE = "RMMSpecialMinerals"' in server_code
    assert 'player:SetAttribute(RESOURCE_ATTRIBUTE, count)' in server_code
    assert 'select("#", ...) ~= 0' in server_code
    assert 'seat.Occupant ~= humanoid' in server_code
    assert 'node:IsA("BasePart")' in server_code
    assert "IsA('Model')" not in server_code
    assert '"Craft52E67D11"' not in server_code
    assert 'remote:InvokeServer()' in client_code
    assert 'local ReplicatedStorage = game:GetService("ReplicatedStorage")' in client_code
    assert "services.ReplicatedStorage" not in client_code
    assert "modNetworkBridge" not in client_code
    assert "type = number" not in client_code
    for module, source in ((server, server_code), (client, client_code)):
        errors = [row for row in LuauStaticAnalyzer().analyze_source(
            source, module.file_path
        ) if row.severity == "ERROR"]
        assert not errors, [(row.rule, row.line_number, row.message) for row in errors]


def test_does_not_mask_invalid_world_contract():
    plan, server, client, remote = fixture()
    plan.game_design["dynamic_design"]["world_objects"][2]["class"] = "Model"
    assert eligible_space_mineral(server, plan) is None
    plan, server, client, remote = fixture()
    plan.game_design["dynamic_design"]["host_actions"][remote]["max_args"] = 1
    assert eligible_space_mineral(server, plan) is None
    plan, server, client, remote = fixture()
    plan.game_design["dynamic_design"]["host_vehicle_identity_bindings"][0]["builder"] = "GhostShip"
    assert eligible_space_mineral(server, plan) is None
    plan, server, client, remote = fixture()
    # A future unrelated genre with the SAME explicit action contract must
    # use the same host implementation regardless of its prompt wording.
    plan.requested_prompt = "농장 상점만 있는 게임"
    assert eligible_space_mineral(server, plan) is not None
    plan, server, client, remote = fixture()
    plan.game_design["dynamic_design"]["host_arrival_materializations"].clear()
    assert eligible_space_mineral(server, plan) is None


def test_real_generic_vehicle_resource_uses_declared_state_not_game_words():
    plan, server, client, remote = fixture()
    server.name = "CollectCargoServer"
    server.description = "Driver collects cargo at an authorized destination"
    client.name = "CargoControls"
    client.description = "Driver controls"
    plan.requested_prompt = "Farm delivery jobs with driving and cargo"
    design = plan.game_design["dynamic_design"]
    design["host_actions"][remote]["service"] = server.name
    design["host_materialized_world"][0]["service"] = server.name
    design["host_materialized_world"][0]["reward"] = {
        "namespace": "RMMInventory",
        "key": "farmProduce",
        "attribute": "ProduceCount",
        "label": "Load produce",
    }
    plan.modules[2] = server
    plan.modules[3] = client
    assert eligible_space_mineral(server, plan) is not None
    assert eligible_space_mineral(client, plan) is not None
    srv = render_space_mineral(server, plan)
    cli = render_space_mineral(client, plan)
    assert 'local INVENTORY_FIELD = "farmProduce"' in srv
    assert 'local RESOURCE_ATTRIBUTE = "ProduceCount"' in srv
    assert 'button.Text = "Load produce"' in cli
    assert 'RMMFlightState' not in srv
    assert 'RMMFlightState' not in cli
    assert 'PilotSeat' not in srv
    assert 'CFrame.new(18, 7, 12)' not in srv
    assert 'craft:FindFirstChildWhichIsA("VehicleSeat", true)' in srv


def test_invalid_declared_reward_or_range_does_not_fall_back_to_guessed_code():
    plan, server, client, remote = fixture()
    record = plan.game_design["dynamic_design"]["host_materialized_world"][0]
    import pytest
    record["reward"]["key"] = "bad.name"
    with pytest.raises(ValueError, match="INVALID_CONTEXTUAL_HARVEST_CONTRACT"):
        render_space_mineral(server, plan)
    record["reward"]["key"] = "fruit"
    record["interaction_range"] = -2
    with pytest.raises(ValueError, match="INVALID_CONTEXTUAL_HARVEST_CONTRACT"):
        render_space_mineral(server, plan)
