"""Regression for uploaded failure_logs (25): three exhausted 9B bodies.

A source-owned, typed, single-remote action must be implemented by the host
when its validated effect and real world/persistence prerequisites are known.
This test checks source generation and parser gates, NOT Roblox Studio play.
"""
from __future__ import annotations

from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_verified_typed_effects import (
    eligible_verified_effect, render_verified_effect,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


DESCRIPTIONS = {
    "purchase": (
        "Validate the request against a server-owned purchase record for the "
        "weapon upgrade, debit the buyer's owned currency and apply the "
        "upgrade state. Reject invalid identifiers and expired records."
    ),
    "combat": (
        "Validate that the player is on the alien planet and that the target "
        "is a server-owned alien entity within range; apply a real server-owned "
        "damage mutation and resolve the combat result server-side."
    ),
    "harvest": (
        "Validate that the player is within range of a server-owned special "
        "mineral deposit and that the deposit has remaining extractable "
        "quantity. Mutate the deposit count and the player's owned inventory."
    ),
}


def _fixture(role: str) -> tuple[RobloxProposal, RobloxModuleSpec]:
    assert role in DESCRIPTIONS
    server_name = "ActionSomethingServer"
    client_name = "ActionSomethingClient"
    remote = "ActionSomethingRemote"
    source = RobloxModuleSpec(
        module_id="dyn_effect_server",
        name=server_name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ActionSomethingServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=DESCRIPTIONS[role],
    )
    ui = RobloxModuleSpec(
        module_id="dyn_effect_client",
        name=client_name,
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ActionSomethingClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Host-owned typed action UI",
    )
    data = RobloxModuleSpec(
        module_id="mod_player_data",
        name="PlayerDataManager",
        kind=ModuleKind.DATA_STORE,
        file_path="src/server/PlayerDataManager.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )
    builder = RobloxModuleSpec(
        module_id="dyn_builder",
        name="CraftBuilderServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/CraftBuilderServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )
    launcher = RobloxModuleSpec(
        module_id="dyn_launcher",
        name="CraftLauncherServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/CraftLauncherServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )
    design = {
        "host_actions": {remote: {
            "service": server_name, "kind": "RemoteFunction", "max_args": 1,
        }},
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {source.module_id: [remote], ui.module_id: [remote]},
        "host_typed_actions": {remote: {
            "server": server_name,
            "client": client_name,
            "transport_only": True,
            "world_entities": ([] if role == "purchase"
                               else ["Alien entities on planet"] if role == "combat"
                               else ["Special mineral deposit"]),
            "contract": {
                "inputs": [
                    {"id": "selection", "label": "Target", "type": "text"},
                    {"id": "quantity", "label": "Quantity",
                     "type": "integer", "min": 1, "max": 10000},
                ],
                "target": {"kind": "none"}, "state_changes": [],
            },
        }},
        "module_world_objects": {
            source.module_id: ["AlienEntities1", "SpecialMineralDeposit1"],
        },
        "world_objects": [
            {"name": "AlienEntities1", "class": "Part", "position": [0, 0, 0]},
            {"name": "SpecialMineralDeposit1", "class": "Part",
             "position": [0, 0, 0]},
            {"name": "OrbitArrival", "class": "Part", "position": [0, 8000, 0]},
        ],
        "host_vehicle_identity_bindings": [
            {"server": launcher.name, "builder": builder.name},
        ],
        "host_arrival_materializations": [
            {"server": launcher.name, "builder": builder.name,
             "arrival": "OrbitArrival"},
        ],
    }
    proposal = RobloxProposal(
        requested_prompt="Mine resources, buy weapon upgrades and travel to alien planet",
        game_title="UnrelatedGameTitle",
        description="space experience",
        game_design={"dynamic_design": design},
        modules=[data, builder, launcher, source, ui],
    )
    return proposal, source


class NeverCallCoder:
    def complete(self, *_a, **_kw):
        raise AssertionError("The 9B model must not write these server bodies")

    def complete_json(self, *_a, **_kw):
        raise AssertionError("The 9B model must not write these server bodies")


def test_log25_all_three_host_compiled_no_small_model():
    for role in ("purchase", "combat", "harvest"):
        p, server = _fixture(role)
        chosen = eligible_verified_effect(server, p)
        assert chosen is not None, role
        assert chosen[0] == {
            "purchase": "owned_tool_purchase",
            "combat": "world_damage",
            "harvest": "world_harvest",
        }[role]
        code = render_verified_effect(server, p)
        assert code and "function Service.handleAction" in code
        assert "function Service.start" in code
        assert "local actionArgs = ..." in code
        assert "GetState(player" in code
        assert "return {success = true" in code
        assert LuauCodeGenerator(NeverCallCoder()).generate_module_code(server, p) == code
        strategies = {m["name"]: m["strategy"]
                      for m in generation_scope(p)["modules"]}
        assert strategies[server.name] == "host_verified_typed_effect"
        parser_errors = [
            diag for diag in LuauStaticAnalyzer().analyze_source(
                code, server.file_path) if diag.severity == "ERROR"
        ]
        assert parser_errors == [], [(x.rule, x.message) for x in parser_errors]


def test_log25_world_parts_are_not_treated_as_models_and_effects_are_real():
    for role, attr in (
        ("combat", "RMMAlienHealth"),
        ("harvest", "RMMSpecialMineralStock"),
    ):
        p, server = _fixture(role)
        source = render_verified_effect(server, p)
        assert source and 'target:IsA("BasePart")' in source
        assert 'marker:IsA("BasePart")' in source
        assert f'target:GetAttribute("{attr}")' in source
        assert f'target:SetAttribute("{attr}"' in source
        assert 'RMMFlightState' in source
        assert 'root.Position - target.Position' in source
        assert "Model" not in source


def test_log25_purchase_checks_owned_tool_balance_and_entitlement():
    p, server = _fixture("purchase")
    source = render_verified_effect(server, p)
    assert source
    assert 'tool:IsA("Tool")' in source
    assert 'coins.Value < offer.cost' in source
    assert 'saved[tool.Name] ~= nil' in source
    assert 'licenses[key] ~= nil' in source
    assert 'coins.Value -= offer.cost' in source
    assert 'licenses[key] = {purchased = true, kind = "weapon"}' in source
    assert 'GetState(player, "RMMTradeEntitlements")' in source


def test_log25_fails_closed_when_physical_or_action_contract_is_unbound():
    for role in ("combat", "harvest"):
        p, module = _fixture(role)
        d = p.game_design["dynamic_design"]
        missing = deepcopy(p)
        missing.game_design["dynamic_design"]["host_arrival_materializations"] = []
        assert render_verified_effect(module, missing) is None
        changed = deepcopy(p)
        world = changed.game_design["dynamic_design"]["world_objects"]
        for part in world:
            if part["name"] != "OrbitArrival":
                part["class"] = "Model"
        assert render_verified_effect(module, changed) is None
    p, module = _fixture("purchase")
    d = p.game_design["dynamic_design"]
    d["host_typed_actions"]["ActionSomethingRemote"]["contract"]["inputs"][1]["id"] = "clientPrice"
    assert render_verified_effect(module, p) is None
    p, module = _fixture("purchase")
    p.game_design["dynamic_design"]["host_actions"]["ActionSomethingRemote"]["max_args"] = 2
    assert render_verified_effect(module, p) is None


def test_log25_compiler_never_selects_from_original_prompt_text():
    p, source = _fixture("combat")
    expected = render_verified_effect(source, p)
    assert expected
    p.requested_prompt = "Different wording: a completely unrelated game"
    assert render_verified_effect(source, p) == expected
    source.description = "Merely show a decorative alien planet icon"
    assert render_verified_effect(source, p) is None


def test_log25_typed_ui_uses_bound_world_id_not_empty_guesswork():
    from roblox_mod_ai.typed_action_contract import render_typed_client

    for role, selected in (
        ("combat", "AlienEntities1"),
        ("harvest", "SpecialMineralDeposit1"),
    ):
        p, server = _fixture(role)
        ui = next(m for m in p.modules
                  if m.kind == ModuleKind.CLIENT_SCRIPT)
        code = render_typed_client(ui, p)
        assert code is not None
        assert 'box.Text = "' + selected + '"' in code
        assert 'remote:InvokeServer(payload)' in code
        assert 'if type(actionArgs["selection"])' not in code
    p, _ = _fixture("purchase")
    ui = next(m for m in p.modules if m.kind == ModuleKind.CLIENT_SCRIPT)
    code = render_typed_client(ui, p)
    assert code and 'box.Text = ""' in code
