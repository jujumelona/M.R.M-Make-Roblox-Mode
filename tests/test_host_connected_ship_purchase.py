"""Contract-level replay: separate part constructor and upgrade purchase share
validated host-owned state without asking the small model to emit Luau."""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_catalog_purchase import eligible_catalog_purchase
from roblox_mod_ai.host_ship_part_catalog import eligible_ship_part_catalog
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class ShortCatalogsOnly:
    def __init__(self, *, invalid_upgrade=False):
        self.calls = []
        self.invalid_upgrade = invalid_upgrade

    def complete(self, *_a, **_kw):
        raise AssertionError("Never send these trusted transactions as model Luau")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        required = kwargs["json_schema"]["required"]
        if required == ["parts"]:
            return {"parts": [
                {"id": "engine", "label": "Engine", "slot": "propulsion",
                 "cost": 50, "performance": 11, "upgrades": []},
                {"id": "hull", "label": "Hull", "slot": "defense",
                 "cost": 30, "performance": 6, "upgrades": []},
            ]}
        assert required == ["entries"]
        return {"entries": [{
            "id": "engineBoost", "label": "Engine boost", "cost": 15,
            "slot": "invented" if self.invalid_upgrade else "propulsion",
            "effect": "speed", "bonus": 7,
        }]}


def make_plan():
    def mod(name, desc, client=False):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name,
            kind=ModuleKind.CLIENT_SCRIPT if client else ModuleKind.SERVER_MODULE,
            file_path=("src/client/" + name + ".client.luau" if client
                       else "src/server/" + name + ".luau"),
            roblox_service=(RobloxService.STARTER_PLAYER_SCRIPTS if client
                            else RobloxService.SERVER_SCRIPT_SERVICE),
            description=desc,
        )

    purchase = mod("OptionalShipEnhancementServer",
        "The server owns the ship upgrade catalog and validates every purchase. "
        "Each upgrade is a finite server-defined choice with a stable action ID, "
        "a visible label, and a fixed cost in earned currency. The server checks "
        "the player's currency, deducts the cost, applies the upgrade to the "
        "ship's corresponding part, and records the performance change. "
        "Invalid purchases are rejected without modifying the ship.")
    purchase_client = mod("OptionalShipEnhancementClient",
        "Display purchase choices and confirmed upgrades", True)
    builder = mod("ModularShipFabricationServer",
        "The server owns the ship assembly state and validates every construction "
        "action. When a player requests a ship part, the server checks enough "
        "earned currency, that the part is available for construction, and that "
        "the player has not already built that part. On success it deducts "
        "the required currency, marks the part as built, and emits a visible "
        "result; failure rejects the build.")
    builder_client = mod("ModularShipFabricationClient",
        "Show available ship parts and server-confirmed construction", True)
    actions = {
        "EnhanceAction": {"service": purchase.name, "kind": "RemoteFunction"},
        "BuildAction": {"service": builder.name, "kind": "RemoteFunction"},
    }
    remotes = {"EnhanceAction": "RemoteFunction", "BuildAction": "RemoteFunction"}
    return RobloxProposal(
        game_title="Any game", requested_prompt="Purchase and build modular ship parts",
        description="Host-owned ship construction and upgrades",
        game_design={"dynamic_design": {
            "host_actions": actions, "remotes": remotes,
            "module_remotes": {
                purchase.module_id: ["EnhanceAction"],
                purchase_client.module_id: ["EnhanceAction"],
                builder.module_id: ["BuildAction"],
                builder_client.module_id: ["BuildAction"],
            },
        }},
        modules=[purchase, purchase_client, builder, builder_client],
    )


def test_upgrade_before_builder_compiles_from_two_small_catalogs():
    p = make_plan()
    purchase, purchase_client, builder, builder_client = p.modules
    assert eligible_ship_part_catalog(builder, p) is not None
    assert eligible_ship_part_catalog(builder_client, p) is not None
    assert eligible_catalog_purchase(purchase, p) is not None
    assert eligible_catalog_purchase(purchase_client, p) is not None
    scope = generation_scope(p)
    assert [x["strategy"] for x in scope["modules"]] == [
        "host_declarative_catalog", "host_declarative_catalog",
        "host_declarative_ship_part_catalog", "host_declarative_ship_part_catalog",
    ]
    model = ShortCatalogsOnly()
    coder = LuauCodeGenerator(model)
    # This is deliberately the *wrong* topological order for a naive reader.
    sources = [coder.generate_module_code(m, p) for m in p.modules]
    assert len(model.calls) == 2
    assert [kwargs["json_schema"]["required"] for _, kwargs in model.calls] == [
        ["parts"], ["entries"]]
    assert '["engineBoost"] = {cost = 15, slot = "propulsion"' in sources[0]
    assert 'ship.sections[item.slot]' in sources[0]
    assert 'section.owned ~= true then return false' in sources[0]
    assert 'coins.Value -= item.cost' in sources[0]
    assert '["engine"] = {slot = "propulsion", cost = 50' in sources[2]
    assert 'profile.sections[part.slot] = {owned = true' in sources[2]
    assert 'coins.Value -= price' in sources[2]
    for mod, source in zip(p.modules, sources):
        errors = [x for x in LuauStaticAnalyzer().analyze_source(source, mod.file_path)
                  if x.severity == "ERROR"]
        assert not errors, [(x.rule, x.message) for x in errors]


def test_purchase_rejects_model_invented_undocumented_builder_slot():
    from pytest import raises
    p = make_plan()
    router = ShortCatalogsOnly(invalid_upgrade=True)
    with raises(ValueError, match="HOST_DECLARATIVE_CATALOG_EXHAUSTED"):
        LuauCodeGenerator(router).generate_module_code(p.modules[0], p)
    assert len(router.calls) == 3  # one real builder catalog, two upgrade retries


def test_missing_builder_does_not_claim_unverified_purchase_ownership():
    p = make_plan()
    p.modules = p.modules[:2]
    assert eligible_catalog_purchase(p.modules[0], p) is None
    p = make_plan()
    p.game_design["dynamic_design"]["host_actions"]["BuildAction"]["kind"] = "RemoteEvent"
    assert eligible_ship_part_catalog(p.modules[2], p) is None
    assert eligible_catalog_purchase(p.modules[0], p) is None
