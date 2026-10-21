"""Regression for conditional ground/space mode and missing launch-state ABI."""
from copy import deepcopy

import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_mode_unlock import eligible_mode_unlock, _validate, try_mode_unlock
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


class OnlyData:
    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer if answer is not None else {
            "minimumCoins": 250,
            "minimumOwnedParts": 3,
            "minimumPurchasedUpgrades": 2,
        }

    def complete(self, *_args, **_kwargs):
        raise AssertionError("Do not use the small model for Luau mode code")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return deepcopy(self.answer)


def plan():
    def module(name, desc, client=False):
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

    mode = module("FlightModeSwitchServer",
        "The server owns the space-mode state and validates every unlock, "
        "travel, and return transition. Entering space requires an unlock threshold "
        "derived from game currency and completed ship upgrades. The server records "
        "the player's current mode as ground or space. This is server-authoritative, "
        "validates transitions, and restores ground after a confirmed return.")
    ui = module("FlightModeSwitchClient",
                "Display the current mode, unlock progress and a return button", True)
    builder = module("ModularCraftServer",
                     "The server owns the ship builder state and validates each "
                     "part in occupied ship part slots and construction currency.")
    upgrades = module("CrewWeaponsUpgradeServer",
                      "The server validates each upgrade purchase for weapon, crew "
                      "and ship performance and records the paid upgrade.")
    launch = module("VehicleLaunchServer",
                    "The server validates launch state and carries the spaceship "
                    "from the planet surface into space.")
    design = {"host_actions": {
        "ModeAction": {"service": mode.name, "kind": "RemoteFunction"},
    }, "remotes": {"ModeAction": "RemoteFunction"},
        "module_remotes": {mode.module_id: ["ModeAction"], ui.module_id: ["ModeAction"]}}
    proposal = RobloxProposal(
        game_title="Generic progress game",
        description="Craft a vehicle and unlock a gated mode",
        requested_prompt="Collect resources, build and launch",
        game_design={"dynamic_design": design},
        modules=[mode, ui, builder, upgrades, launch],
    )
    return proposal, mode, ui


def test_source_owns_mode_rules_and_requires_real_flight_before_entering():
    proposal, mode, ui = plan()
    assert eligible_mode_unlock(mode, proposal) == (mode.name, "ModeAction")
    assert eligible_mode_unlock(ui, proposal) == (mode.name, "ModeAction")
    scope = generation_scope(proposal)
    assert [r["strategy"] for r in scope["modules"][:2]] == [
        "host_declarative_mode_unlock", "host_declarative_mode_unlock"]
    statuses = [r["status"] for r in scope["unverified_cross_module_dependencies"]]
    assert "unverified_mode_launch_producer" in statuses
    assert "unverified_mode_ship_upgrade_producers" in statuses
    coder = LuauCodeGenerator(OnlyData())
    code = coder.generate_with_self_correction(mode, proposal)
    client = coder.generate_with_self_correction(ui, proposal)
    assert len(coder.router.calls) == 1
    assert coder.router.calls[0][1]["json_schema"]["required"] == [
        "minimumCoins", "minimumOwnedParts", "minimumPurchasedUpgrades"]
    assert "local MIN_COINS = 250" in code
    assert "local MIN_PARTS = 3" in code
    assert "local MIN_UPGRADES = 2" in code
    assert 'manager.GetState(player, "RMMShipSections")' in code
    assert 'manager.GetState(player, "RMMUpgradePurchases")' in code
    assert 'manager.GetState(player, "RMMTravelProgress")' in code
    assert 'if not state.flightConfirmed then' in code
    assert 'reason = "launch_not_confirmed"' in code
    assert 'reason = "return_flight_not_confirmed"' in code
    assert 'state.mode.activeMode = MODE' in code
    assert 'state.mode.activeMode = GROUND' in code
    assert 'state.flight.inSpace = true' not in code
    assert 'coins.Value -=' not in code
    assert 'remote:InvokeServer(kind)' in client
    assert 'WaitForChild("ModeAction", 20)' in client
    for m, source in ((mode, code), (ui, client)):
        errors = [e for e in LuauStaticAnalyzer().analyze_source(
            source, m.file_path) if e.severity == "ERROR"]
        assert not errors, [(e.rule, e.line_number, e.message) for e in errors]


@pytest.mark.parametrize("bad", [
    {"minimumCoins": True, "minimumOwnedParts": 2, "minimumPurchasedUpgrades": 1},
    {"minimumCoins": 0, "minimumOwnedParts": 2, "minimumPurchasedUpgrades": 1},
    {"minimumCoins": 30, "minimumOwnedParts": 0, "minimumPurchasedUpgrades": 1},
    {"minimumCoins": 30, "minimumOwnedParts": 2, "minimumPurchasedUpgrades": -1},
    {"minimumCoins": 30, "minimumOwnedParts": 9, "minimumPurchasedUpgrades": 1},
])
def test_invalid_rules_are_not_accepted(bad):
    with pytest.raises(ValueError):
        _validate(bad)


def test_invalid_or_uncached_data_fails_closed_with_no_luau_fallback():
    p, m, _ = plan()
    bad = OnlyData({"minimumCoins": -100})
    with pytest.raises(ValueError, match="HOST_MODE_UNLOCK_RULE_EXHAUSTED"):
        LuauCodeGenerator(bad).generate_module_code(m, p)
    assert len(bad.calls) == 2


def test_cached_rules_work_with_no_model_and_wrong_transport_does_not_claim():
    p, m, client = plan()
    coder = LuauCodeGenerator(OnlyData())
    s = coder.generate_module_code(m, p)
    saved = deepcopy(p.game_design["_host_mode_unlock_rules"])
    p2, m2, client2 = plan()
    p2.game_design["_host_mode_unlock_rules"] = saved
    assert try_mode_unlock(m2, p2, None) == s
    assert try_mode_unlock(client2, p2, None) is not None

    p, m, client = plan()
    p.game_design["dynamic_design"]["host_actions"]["ModeAction"]["kind"] = "RemoteEvent"
    assert eligible_mode_unlock(m, p) is None

    p, m, client = plan()
    p.modules.pop()
    assert eligible_mode_unlock(m, p) is None

    p, m, client = plan()
    m.description = "The client switches to space without any prerequisites."
    assert eligible_mode_unlock(m, p) is None
