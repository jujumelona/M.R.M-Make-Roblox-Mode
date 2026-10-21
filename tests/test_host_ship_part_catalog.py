"""Currency-funded ship construction must not depend on small-model Luau.

Tests a general catalog/slot/currency/performance action with arbitrary
module names. Checks actual host contract, malformed model data and routing.
"""
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_part_catalog import (
    eligible_ship_part_catalog, try_ship_part_catalog, validate_parts,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


def make_currency_ship_plan():
    server = "CustomModularVesselPartsServer"
    remote = "BuildVesselPartAction"
    owner = RobloxModuleSpec(
        module_id="dyn_parts_01", name=server, kind=ModuleKind.SERVER_MODULE,
        file_path=f"src/server/{server}.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server maintains a finite, server-owned catalog of spaceship "
            "part definitions with stable part ID, required build slot and upgrade "
            "choices. Requests are validated against the part ID and slot. The "
            "player must have earned game currency and cannot install a part "
            "in an occupied slot. The server records installed parts and their "
            "performance contribution while deducting currency."
        ),
    )
    client = RobloxModuleSpec(
        module_id="dyn_parts_02", name="CustomModularVesselPartsClient",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/CustomModularVesselPartsClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Client displays selectable ship part cards, upgrades and costs.",
    )
    design = {"host_actions": {remote: {"service": server, "kind": "RemoteFunction"}},
              "remotes": {remote: "RemoteFunction"},
              "module_remotes": {owner.module_id: [remote], client.module_id: [remote]}}
    return RobloxProposal(
        game_title="Test ship construction", description="Parts purchased with currency",
        requested_prompt="Build a customizable spaceship with parts",
        game_design={"dynamic_design": design}, modules=[owner, client],
    )


class CatalogOnly:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {"parts": [
            {"id": "engine", "label": "Engine", "slot": "propulsion", "cost": 65,
             "performance": 12, "upgrades": [
                {"id": "boost", "label": "Engine boost", "cost": 20, "bonus": 7}]},
            {"id": "hull", "label": "Hull", "slot": "defense", "cost": 35,
             "performance": 4, "upgrades": []},
        ]}

    def complete(self, *_args, **_kwargs):
        raise AssertionError("Host catalog action MUST NOT call full-file Luau model")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.result


def test_part_catalog_is_full_host_code_from_one_small_data_reply():
    p = make_currency_ship_plan()
    router = CatalogOnly()
    assert generation_scope(p)["counts"]["host_declarative_ship_part_catalog"] == 2
    coder = LuauCodeGenerator(router)
    server = coder.generate_module_code(p.modules[0], p)
    client = coder.generate_module_code(p.modules[1], p)
    assert len(router.calls) == 1
    assert router.calls[0][1]["max_tokens"] <= 1350
    assert router.calls[0][1]["json_schema"]["required"] == ["parts"]
    assert '["engine"] = {slot = "propulsion", cost = 65' in server
    assert 'GetState(player, "RMMShipSections")' in server
    assert 'FindFirstChild("Coins")' in server
    assert 'coins.Value -= price' in server
    assert 'existing and existing.owned' in server
    assert 'profile.sections[part.slot] = {owned = true' in server
    assert 'player:SetAttribute("RMMShipPerformance", performance)' in server
    assert 'existing.upgrades[optionId] = true' in server
    assert 'if not bonus then return reject("unknown_upgrade") end' in server
    assert 'remote:InvokeServer(table.unpack(args, 1, args.n))' in client
    assert 'request("upgrade", part.id, choice.id)' in client
    assert 'WaitForChild("BuildVesselPartAction", 20)' in client
    analyzer = LuauStaticAnalyzer()
    for module, code in zip(p.modules, (server, client)):
        errors = [d for d in analyzer.analyze_source(code, module.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.line_number, d.message) for d in errors]


@pytest.mark.parametrize("field,value", [
    ("id", "bad; code()"), ("slot", "x\nend"), ("cost", 0),
    ("cost", True), ("performance", -1), ("upgrades", [{"id": "x", "cost": 0}]),
])
def test_catalog_fails_closed_on_non_declarative_or_invalid_data(field, value):
    part = {"id": "engine", "label": "Engine", "slot": "propulsion", "cost": 65,
            "performance": 12, "upgrades": []}
    part[field] = value
    with pytest.raises(ValueError):
        validate_parts({"parts": [part]})


def test_wrong_route_or_missing_bilateral_contract_does_not_claim_module():
    p = make_currency_ship_plan()
    p.game_design["dynamic_design"]["host_actions"]["BuildVesselPartAction"]["kind"] = "RemoteEvent"
    assert eligible_ship_part_catalog(p.modules[0], p) is None
    p = make_currency_ship_plan()
    p.modules[0].description = "Create a decorative space-themed world and GUI."
    assert eligible_ship_part_catalog(p.modules[0], p) is None
    p = make_currency_ship_plan()
    p.game_design["dynamic_design"]["host_actions"]["BuildVesselPartAction"]["max_args"] = 1
    assert eligible_ship_part_catalog(p.modules[0], p) is None


def test_invalid_catalog_retry_never_substitutes_fake_purchased_parts():
    p = make_currency_ship_plan()
    router = CatalogOnly({"parts": [{"id": "x", "cost": -10}]})
    with pytest.raises(ValueError, match="HOST_SHIP_PART_CATALOG_EXHAUSTED"):
        try_ship_part_catalog(p.modules[0], p, router)
    assert len(router.calls) == 2


def test_server_and_client_share_cached_part_catalog_without_more_inference():
    p = make_currency_ship_plan()
    router = CatalogOnly()
    server = try_ship_part_catalog(p.modules[0], p, router)
    assert server
    assert try_ship_part_catalog(p.modules[1], p, None)
    assert len(router.calls) == 1



def test_invalid_host_owned_source_never_escalates_to_model_repair():
    from types import SimpleNamespace
    p = make_currency_ship_plan()
    model = CatalogOnly()
    coder = LuauCodeGenerator(model)

    class BrokenSourceAnalyzer:
        def analyze_source(self, code, file_path=""):
            return [SimpleNamespace(
                rule="LUAU_PARSER_SYNTAX", file_path=file_path, line_number=2,
                message="invalid template", severity="ERROR")]

    coder.analyzer = BrokenSourceAnalyzer()
    with pytest.raises(ValueError, match="Host-owned Luau template failed"):
        coder.generate_with_self_correction(p.modules[0], p)
    assert len(model.calls) == 1
