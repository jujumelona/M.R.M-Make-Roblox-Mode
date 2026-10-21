"""The ZIP 16 next purchase module must not repeat scoped-body generation."""
from copy import deepcopy

import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_upgrade_declarative import (
    eligible_declarative_upgrade, try_declarative_upgrade, _validate,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class NoLuau:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"upgrades": [
            {"id": "HeavyBlaster", "label": "Weapon damage", "category": "weapon",
             "cost": 20, "bonus": 4},
            {"id": "CrewSlots", "label": "Crew capacity", "category": "crew",
             "cost": 30, "bonus": 2},
            {"id": "Drive", "label": "Ship performance", "category": "ship",
             "cost": 60, "bonus": 12},
        ]}
    def complete(self, *args, **kwargs):
        raise AssertionError("Short model must never author purchases or Roblox APIs")
    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt,kwargs))
        return deepcopy(self.result)


def _plan(name="TradingPurchaseOfWeaponsCFEA0A71Server"):
    owner = RobloxModuleSpec(
        module_id="dyn_8c91360ab4bb", name=name, kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/" + name + ".luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server validates each purchase request against the player's "
            "in-game currency balance, deducts the exact cost, and applies "
            "the corresponding upgrade to the player's weapon, crew, or "
            "spaceship performance. Purchases are recorded as owned upgrades "
            "and are not duplicated across sessions or characters."
        ),
    )
    client_name = name.removesuffix("Server") + "Client"
    client = RobloxModuleSpec(
        module_id="dyn_89d9f872a936", name=client_name,
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/" + client_name + ".client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Display purchasable upgrades and server confirmed currency.",
    )
    action = name.removesuffix("Server") + "Action"
    proposal = RobloxProposal(
        requested_prompt="Customize my vehicle and crew",
        game_title="Generic upgrade game",
        description="Equipment purchases",
        modules=[owner,client],
        game_design={"dynamic_design": {
            "host_actions": {action: {"service":name,"kind":"RemoteFunction"}},
            "remotes": {action:"RemoteFunction"},
            "module_remotes": {owner.module_id:[action],client.module_id:[action]},
        }},
    )
    return proposal,owner,client


def test_actual_followup_purchase_is_bounded_catalog_and_server_owned():
    proposal, owner, client = _plan()
    assert eligible_declarative_upgrade(owner, proposal)
    assert eligible_declarative_upgrade(client, proposal)
    strategy = {row["name"]:row["strategy"] for row in generation_scope(proposal)["modules"]}
    assert strategy[owner.name] == "host_declarative_general_upgrades"
    assert strategy[client.name] == "host_declarative_general_upgrades"
    router = NoLuau()
    gen = LuauCodeGenerator(router)
    source = gen.generate_with_self_correction(owner,proposal)
    ui = gen.generate_with_self_correction(client,proposal)
    assert len(router.calls) == 1
    assert router.calls[0][1]["max_tokens"] <= 850
    assert source == try_declarative_upgrade(owner,proposal,None)
    assert ui == try_declarative_upgrade(client,proposal,None)
    for key in [
        '["HeavyBlaster"] = {kind = "weapon", cost = 20, bonus = 4}',
        '["CrewSlots"] = {kind = "crew", cost = 30, bonus = 2}',
        '["Drive"] = {kind = "ship", cost = 60, bonus = 12}',
        'GetState(player, "RMMUpgradePurchases")',
        'coins.Value -= item.cost',
        'purchases[id] = {owned = true, kind = item.kind, bonus = item.bonus}',
        'RMMGeneralPurchasedShipPower',
        'return reject("already_purchased")',
        'return reject("insufficient_currency")',
    ]:
        assert key in source, key
    assert 'remote:InvokeServer(upgrade.id)' in ui
    assert 'button.Active = false' in ui
    assert 'GetState(player, "RMMInventory")' not in source
    for module, code in ((owner,source),(client,ui)):
        errors = [d for d in LuauStaticAnalyzer().analyze_source(code,module.file_path)
                  if d.severity=="ERROR"]
        assert not errors, [(d.rule,d.line_number,d.message) for d in errors]


def test_semantics_not_example_name_or_user_prompt_select_purchase_route():
    proposal,owner,client = _plan("AnyGenericUpgradeServiceServer")
    assert eligible_declarative_upgrade(owner,proposal)
    assert eligible_declarative_upgrade(client,proposal)
    owner.description = "The server displays catalog images and links to cosmetics."
    assert eligible_declarative_upgrade(owner,proposal) is None


@pytest.mark.parametrize("bad", [
    {"upgrades":[]},
    {"upgrades":[{"id":"Gun","label":"Gun","category":"weapon","cost":20,"bonus":1}]},
    {"upgrades":[{"id":"Gun","label":"Gun","category":"weapon","cost":True,"bonus":1}]},
    {"upgrades":[{"id":"Gun","label":"Gun","category":"weapon","cost":20,"bonus":1},
                 {"id":"gun","label":"Dup","category":"weapon","cost":20,"bonus":1}]},
])
def test_malformed_or_incomplete_catalog_fails_closed(bad):
    with pytest.raises(ValueError):
        _validate(bad)


def test_invalid_transport_and_unowned_client_cannot_claim_upgrade():
    proposal,owner,client = _plan()
    key=next(iter(proposal.game_design["dynamic_design"]["host_actions"]))
    proposal.game_design["dynamic_design"]["host_actions"][key]["max_args"] = 0
    assert eligible_declarative_upgrade(owner,proposal) is None
    proposal,owner,client = _plan()
    key=next(iter(proposal.game_design["dynamic_design"]["host_actions"]))
    proposal.game_design["dynamic_design"]["module_remotes"][client.module_id] = ["Fake"]
    assert eligible_declarative_upgrade(client,proposal) is None


def test_resume_catalog_is_revalidated_no_extra_model_call():
    proposal,owner,client = _plan()
    coder = NoLuau()
    assert try_declarative_upgrade(owner,proposal,coder)
    assert try_declarative_upgrade(client,proposal,None)
    assert len(coder.calls)==1
    proposal.game_design["_host_general_upgrades"][owner.name][0]["cost"]=-1
    with pytest.raises(ValueError):
        try_declarative_upgrade(owner,proposal,None)
