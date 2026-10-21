"""Regression for source-owned world resource gathering and cross-service coins."""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_mining import mining_rewards_currency, render_host_mining
from roblox_mod_ai.host_mining_nodes import mining_world_nodes
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


class NoLuau:
    def complete(self, *args, **kwargs):
        raise AssertionError("Host should not request Luau from the model")


def plan(*, extra_currency=True, label="ResourceDeposit"):
    harvesting = RobloxModuleSpec(
        module_id="dyn_harvesting", name="GenericResourceGatheringServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/GenericResourceGatheringServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server owns all resource-gathering validation. A player action "
                     "is accepted only when the player is within the gathering radius "
                     "of the target resource object, the target is not depleted, "
                     "and the player has not already triggered the same gathering "
                     "action within the cooldown window. On a valid action the "
                     "server decrements the target's remaining quantity, grants "
                     "the player the corresponding resource amount, and updates "
                     "the target's depleted state. Invalid actions are rejected."),
    )
    currency = RobloxModuleSpec(
        module_id="dyn_currency", name="CurrencyBalanceServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/CurrencyBalanceServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server maintains earned-game-currency balance. "
                     "Resource-gathering actions award a fixed, server-defined "
                     "amount of earned currency."),
    )
    deposit = label + "BD361B11"
    design = {
        "world_objects": [
            {"name": deposit, "class": "Part"},
            {"name": "SpecialMineralDeposit75F66611", "class": "Part"},
            {"name": "Alien9044DE11", "class": "Part"},
        ],
        "module_world_objects": {
            harvesting.module_id: [deposit],
            currency.module_id: [],
        },
        "host_actions": {},
        "host_world_actions": {
            deposit: {"service": harvesting.name, "action_text": "Resource Gathering"},
            "SpecialMineralDeposit75F66611": {
                "service": "PlanetSpecialMineralServer", "action_text": "Extract",
            },
        },
        "remotes": {},
    }
    modules = [harvesting] + ([currency] if extra_currency else [])
    p = RobloxProposal(
        requested_prompt="Gather and build using server-earned resources",
        game_title="An arbitrary resource world",
        description="Resource gathering",
        game_design={"dynamic_design": design}, modules=modules,
    )
    return p, harvesting, currency


def test_uploaded_world_resource_gathering_uses_host_not_model():
    p, harvest, currency = plan()
    assert mining_world_nodes(p, harvest) == ["ResourceDepositBD361B11"]
    assert mining_rewards_currency(harvest, p)
    scope = generation_scope(p)
    chosen = next(x for x in scope["modules"] if x["name"] == harvest.name)
    assert chosen["strategy"] == "host_verified_template"
    source = LuauCodeGenerator(NoLuau()).generate_module_code(harvest, p)
    assert source == render_host_mining(harvest, p)
    assert 'local NODE_NAMES = {"ResourceDepositBD361B11"}' in source
    assert 'GetState(player, "RMMInventory")' in source
    assert 'progress.resources = balance + 1' in source
    assert "coins.Value += 1" in source
    assert "node.remaining -= 1" in source
    assert 'part:SetAttribute("ResourceDepleted", node.remaining == 0)' in source
    assert "PlayerDataManager:GetState" not in source
    assert "player:GiveResource(" not in source
    assert 'serviceActionWindowSeconds' not in source
    assert "OnServerInvoke" not in source
    errors = [d for d in LuauStaticAnalyzer().analyze_source(source, harvest.file_path)
              if d.severity == "ERROR"]
    assert not errors, [(x.rule, x.line_number, x.message) for x in errors]


def test_source_owned_nonstandard_world_name_does_not_require_english_node_regex():
    p, harvest, _ = plan(extra_currency=False, label="HarvestingSite")
    assert mining_world_nodes(p, harvest) == ["HarvestingSiteBD361B11"]
    assert render_host_mining(harvest, p) is not None
    source = render_host_mining(harvest, p)
    assert "coins.Value" not in source
    assert "coins.Value +=" not in source
    assert "progress.resources = balance + 1" in source
    assert 'credits = coins.Value' not in source


def test_resource_only_world_harvest_does_not_claim_money_minting():
    p, harvest, _ = plan(extra_currency=False)
    assert mining_rewards_currency(harvest, p) is False
    source = LuauCodeGenerator(NoLuau()).generate_module_code(harvest, p)
    assert 'coins.Value' not in source
    assert 'node.remaining -= 1' in source


def test_reject_unowned_or_wrong_service_world_actions():
    p, harvest, _ = plan()
    p.game_design["dynamic_design"]["module_world_objects"][harvest.module_id] = []
    assert render_host_mining(harvest, p) is None
    p, harvest, _ = plan()
    p.game_design["dynamic_design"]["host_world_actions"]["ResourceDepositBD361B11"] = {
        "service": "OtherServer", "action_text": "Other action",
    }
    assert render_host_mining(harvest, p) is None
    p, harvest, _ = plan()
    p.game_design["dynamic_design"]["host_actions"]["ExtraAction"] = {
        "service": harvest.name, "kind": "RemoteFunction",
    }
    assert render_host_mining(harvest, p) is None


def test_actual_failing_module_name_is_irrelevant_to_generic_adapter():
    p, harvest, _ = plan()
    harvest.name = "ResourceGatheringBD361B1Server"
    harvest.file_path = "src/server/ResourceGatheringBD361B1Server.luau"
    p.game_design["dynamic_design"]["host_world_actions"]["ResourceDepositBD361B11"]["service"] = harvest.name
    assert render_host_mining(harvest, p) is not None
