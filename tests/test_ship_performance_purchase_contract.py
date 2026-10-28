"""A purchased performance boost must preserve ownership of an installed ship part."""
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
from roblox_mod_ai.host_ship_performance_purchase import (
    eligible_ship_performance_purchase, render_ship_performance_purchase,
)
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.code_generator import LuauCodeGenerator


def test_owned_ship_performance_purchase_preserves_installed_section(monkeypatch):
    import roblox_mod_ai.host_ship_performance_purchase as compiler
    builder = RobloxModuleSpec("dyn_builder", "BuiltShipServer",
        ModuleKind.SERVER_MODULE, "src/server/BuiltShipServer.luau",
        "ServerScriptService", "Physically owned ship assembly")
    server = RobloxModuleSpec("dyn_stat", "ShipStatUpgradeServer",
        ModuleKind.SERVER_MODULE, "src/server/ShipStatUpgradeServer.luau",
        "ServerScriptService",
        "Validate purchase against server-owned currency balance, reject "
        "invalid requests, and persist the spaceship performance upgrade "
        "record after deducting a server-verified price")
    client = RobloxModuleSpec("dyn_ui", "ShipStatUpgradeClient",
        ModuleKind.CLIENT_SCRIPT, "src/client/ShipStatUpgradeClient.client.luau",
        "StarterPlayerScripts", "Upgrade panel")
    data = RobloxModuleSpec("mod_data", "PlayerDataManager",
        ModuleKind.DATA_STORE, "src/server/PlayerDataManager.luau",
        "ServerScriptService", "Persistent player data")
    monkeypatch.setattr(compiler, "eligible_ship_attachment",
                        lambda m, p: ("verified",) if m is builder else None)
    remote = "ShipStatsUpgradeAction"
    design = {"host_actions": {
                    remote: {"service": server.name,
                             "kind": "RemoteFunction", "max_args": 1}},
              "remotes": {remote: "RemoteFunction"},
              "module_remotes": {server.module_id: [remote],
                                 client.module_id: [remote]},
              "host_typed_actions": {remote: {
                  "server": server.name, "client": client.name,
                  "transport_only": True,
                  "contract": {
                      "inputs": [
                          {"id": "selection", "label": "Ship section",
                           "type": "text"},
                          {"id": "quantity", "label": "Units",
                           "type": "integer", "min": 1, "max": 10000},
                      ], "target": {"kind": "none"},
                      "state_changes": [],
                  }}},
              "host_flight_ready_builders": {builder.name: "section_attachment"}}
    plan = RobloxProposal("Build and upgrade a ship",
        "Ships", "Ships", {"dynamic_design": design},
        [builder, server, client, data])
    assert eligible_ship_performance_purchase(server, plan) == builder.name
    scope = {m["name"]: m["strategy"] for m in generation_scope(plan)["modules"]}
    assert scope[server.name] == "host_ship_performance_purchase"
    source = LuauCodeGenerator().generate_module_code(server, plan)
    assert "section.owned~=true" in source
    assert "section.performance=perf+2" in source
    assert "section.owned=false" not in source
    assert "coins.Value-=cost" in source
    assert "return Service" in source


def test_unverified_ship_builder_cannot_mint_upgrade(monkeypatch):
    import roblox_mod_ai.host_ship_performance_purchase as compiler
    monkeypatch.setattr(compiler, "eligible_ship_attachment", lambda _m, _p: None)
    server = RobloxModuleSpec("dyn_stat", "ShipStatUpgradeServer",
        ModuleKind.SERVER_MODULE, "src/server/ShipStatUpgradeServer.luau",
        "ServerScriptService", "spaceship performance upgrade purchase")
    plan = RobloxProposal("upgrade", "Ships", "Ships",
        {"dynamic_design": {}}, [server])
    assert render_ship_performance_purchase(server, plan) is None
