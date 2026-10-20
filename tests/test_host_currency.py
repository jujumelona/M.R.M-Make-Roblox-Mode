"""Regression: currency accumulation cannot become another player-controlled mint."""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_currency import render_host_currency
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService


class NoModel:
    def complete(self, *_a, **_kw):
        raise AssertionError("Host-owned earned currency must never prompt the model")

    def complete_json(self, *_a, **_kw):
        raise AssertionError("Host-owned earned currency must never prompt the model")


def fixture():
    def module(name, kind, description):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name, kind=kind,
            file_path=("src/server/" + name + ".luau" if kind == ModuleKind.SERVER_MODULE
                       else "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=description,
        )
    mining = module(
        "ResourceMiningEconomy0388601Server", ModuleKind.SERVER_MODULE,
        "Server validates mining near a resource node and adds earned currency.")
    server = module(
        "CurrencyAccumulation0388602Server", ModuleKind.SERVER_MODULE,
        "The server maintains the player's currency balance as a server-owned value. "
        "Currency is only modified through validated mining and trading actions.")
    client = module(
        "CurrencyAccumulation0388602Client", ModuleKind.CLIENT_SCRIPT,
        "The client displays currency balance received from the server.")
    design = {
        "world_objects": [{"name": "ResourceNode03886011", "class": "Part"}],
        "host_actions": {
            "ResourceMiningEconomy0388601Action": {
                "kind": "RemoteFunction", "service": mining.name},
            "CurrencyAccumulation0388602Action": {
                "kind": "RemoteEvent", "service": server.name},
        },
    }
    proposal = SimpleNamespace(game_design={"dynamic_design": design},
                               modules=[mining, server, client],
                               requested_prompt="Mine resources, sell them and save credits")
    return mining, server, client, proposal


def test_logged_currency_module_is_host_owned_and_cannot_grant_client_requested_money():
    _mining, server, client, proposal = fixture()
    generator = LuauCodeGenerator(router=NoModel())
    code = generator.generate_module_code(server, proposal)
    user_code = generator.generate_module_code(client, proposal)
    assert code == render_host_currency(server, proposal)
    assert user_code == render_host_gameplay(client, proposal)
    assert "coins.Value +=" not in code
    assert "coins.Value =" not in code
    assert "SetAttribute(\"RMMCurrencyBalance\", coins.Value)" in code
    assert 'player:FindFirstChild("leaderstats")' in code
    assert "if select(\"#\", ...) ~= 0 then return false end" in code
    assert "services.PlayerDataManager.OnReady" in code
    assert "remote:FireServer()" in user_code
    assert "local Service = {}" in code
    assert code.rstrip().endswith("return Service")


def test_cannot_make_host_currency_without_producer_or_trusted_ingress():
    mining, server, client, proposal = fixture()
    proposal.modules.remove(mining)
    assert render_host_currency(server, proposal) is None
    proposal.modules.insert(0, mining)
    del proposal.game_design["dynamic_design"]["host_actions"]["CurrencyAccumulation0388602Action"]
    assert render_host_currency(server, proposal) is None
    assert render_host_currency(client, proposal) is None


def test_host_currency_static_parses_without_model():
    _mining, server, client, proposal = fixture()
    analyzer = LuauStaticAnalyzer()
    for module in (server, client):
        code = render_host_gameplay(module, proposal)
        errors = [d for d in analyzer.analyze_source(code, module.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.line_number, d.message) for d in errors]


def test_earned_currency_acquisition_also_projects_validated_balance():
    _mining, server, client, proposal = fixture()
    server.name = "EarnedCurrencyAcquisitionF063104Server"
    client.name = "EarnedCurrencyAcquisitionF063104Client"
    proposal.game_design["dynamic_design"]["host_actions"]["CurrencyAccumulation0388602Action"]["service"] = server.name
    assert render_host_currency(server, proposal)
    assert render_host_currency(client, proposal)
