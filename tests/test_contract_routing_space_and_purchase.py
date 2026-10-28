"""Contract-level regressions for host-owned typed actions.

No real Studio or model is required: these tests verify that a generic
source-owned plan routes to executable first-party handlers, with the same
server/client Remote ABI and actual Part types.
"""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal


def _module(name, kind, description, i):
    is_client = kind == ModuleKind.CLIENT_SCRIPT
    return RobloxModuleSpec(
        module_id=f"dyn_{i:012d}", name=name, kind=kind,
        file_path=f"src/{'client' if is_client else 'server'}/{name}" +
                  (".client.luau" if is_client else ".luau"),
        roblox_service="StarterPlayerScripts" if is_client else "ServerScriptService",
        description=description,
    )


def _typed(server, client):
    return {
        "server": server.name, "client": client.name,
        "transport_only": True,
        "contract": {
            "inputs": [
                {"id": "selection", "label": "ID", "type": "text"},
                {"id": "quantity", "label": "Count", "type": "integer",
                 "min": 1, "max": 10000},
            ],
            "target": {"kind": "none"}, "state_changes": [],
        },
    }


def _space_fixture():
    behaviors = [
        ("AlienEncounterServer", "AlienEncounterClient",
         "Validate a server-owned alien entity target within range and "
         "apply real damage in an alien combat action", "AlienPatrolZone"),
        ("FoundColonyServer", "FoundColonyClient",
         "Validate a player-owned planet and its owner, then mark that "
         "planet colonized in the server-owned colony record", None),
        ("OreGatherServer", "OreGatherClient",
         "Validate a server-owned mineral deposit and extract quantity "
         "into the player inventory", "CrystalOreDeposit"),
    ]
    modules = [_module("BuilderServer", ModuleKind.SERVER_MODULE,
                       "Real physical spaceship builder", 900)]
    design = {"host_actions": {}, "host_typed_actions": {}, "remotes": {},
              "module_remotes": {}, "module_world_objects": {},
              "host_vehicle_identity_bindings": [
                  {"server": "LaunchServer", "builder": "BuilderServer"}],
              "host_arrival_materializations": [
                  {"server": "LaunchServer", "builder": "BuilderServer",
                   "arrival": "PlanetArrivalPad"}],
              "world_objects": [
                  {"name": "PlanetArrivalPad", "class": "Part"},
                  {"name": "AlienPatrolZone", "class": "Part"},
                  {"name": "CrystalOreDeposit", "class": "Part"},
              ]}
    for index, (server_name, client_name, description, target) in enumerate(behaviors):
        server = _module(server_name, ModuleKind.SERVER_MODULE,
                         description, index * 2 + 1)
        client = _module(client_name, ModuleKind.CLIENT_SCRIPT,
                         "Typed gameplay control", index * 2 + 2)
        modules += [server, client]
        remote = server_name.removesuffix("Server") + "Action"
        design["host_actions"][remote] = {
            "service": server_name, "kind": "RemoteFunction", "max_args": 1}
        design["remotes"][remote] = "RemoteFunction"
        typed = _typed(server, client)
        typed["world_entities"] = [target] if target else []
        design["host_typed_actions"][remote] = typed
        design["module_remotes"][server.module_id] = [remote]
        design["module_remotes"][client.module_id] = [remote]
        design["module_world_objects"][server.module_id] = [target] if target else []
    proposal = RobloxProposal(
        requested_prompt="Build, fight alien enemies, colonize, collect ore",
        game_title="Space loop", description="Space loop",
        game_design={"dynamic_design": design}, modules=modules,
    )
    return proposal, modules[1:]


def test_semantic_space_actions_compile_without_model_and_keep_world_part_contract():
    proposal, actions = _space_fixture()
    scope = {row["name"]: row["strategy"]
             for row in generation_scope(proposal)["modules"]}
    generator = LuauCodeGenerator()
    for module in actions:
        assert scope[module.name] == "host_space_action"
        script = generator.generate_module_code(module, proposal)
        assert "__TARGET__" not in script and "__ARRIVAL__" not in script
        if module.kind == ModuleKind.SERVER_MODULE:
            assert "function Service.handleAction" in script
            assert "return Service" in script
            assert 'target:IsA("BasePart")' in script
        else:
            assert "InvokeServer" in script
    # Destination ownership is never confused with an arbitrary Part.
    colony = next(m for m in actions if m.name == "FoundColonyServer")
    script = generator.generate_module_code(colony, proposal)
    assert "Shared arrival surface is never relocated" in script


def test_purchase_alias_calls_verified_owner_once_without_second_debit():
    canonical = _module("ImproveWeaponServer", ModuleKind.SERVER_MODULE,
        "Validate the player-owned weapon instance in the server-owned "
        "registry; upgrade its performance state by increasing damage, "
        "persisting the record and rejecting invalid purchases", 81)
    canonical_ui = _module("ImproveWeaponClient", ModuleKind.CLIENT_SCRIPT,
        "Weapon enhancement control", 82)
    alias = _module("PayWeaponUpgradeServer", ModuleKind.SERVER_MODULE,
        "Validate a weapon upgrade purchase, reject invalid balance, "
        "and debit currency at the server-set price for the weapon upgrade", 83)
    alias_ui = _module("PayWeaponUpgradeClient", ModuleKind.CLIENT_SCRIPT,
        "Weapon purchase control", 84)
    modules = [canonical, canonical_ui, alias, alias_ui]
    remotes = {"ImproveWeaponAction": "ImproveWeaponServer",
               "PayWeaponUpgradeAction": "PayWeaponUpgradeServer"}
    design = {"host_actions": {}, "remotes": {}, "host_typed_actions": {},
              "module_remotes": {}}
    for remote, server_name in remotes.items():
        server = next(m for m in modules if m.name == server_name)
        client = next(m for m in modules if m.name == server_name.replace("Server", "Client"))
        design["host_actions"][remote] = {
            "service": server_name, "kind": "RemoteFunction", "max_args": 1}
        design["remotes"][remote] = "RemoteFunction"
        design["host_typed_actions"][remote] = _typed(server, client)
        design["module_remotes"][server.module_id] = [remote]
        design["module_remotes"][client.module_id] = [remote]
    data = RobloxModuleSpec("mod_player_data", "PlayerDataManager",
        ModuleKind.DATA_STORE, "src/server/PlayerDataManager.luau", "ServerScriptService")
    proposal = RobloxProposal(
        requested_prompt="Buy and improve owned weapons",
        game_title="Owned gear", description="Owned gear",
        game_design={"dynamic_design": design}, modules=[data] + modules,
    )
    scope = {row["name"]: row["strategy"]
             for row in generation_scope(proposal)["modules"]}
    assert scope[canonical.name] == "host_owned_weapon_performance"
    assert scope[alias.name] == "host_verified_upgrade_alias"
    script = LuauCodeGenerator().generate_module_code(alias, proposal)
    assert '"ImproveWeaponServer"' in script
    assert "return owner.handleAction(player, services, args)" in script
    assert "Coins.Value -=" not in script
