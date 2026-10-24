"""Actual plan-77 failure classes, asserted across unrelated gameplay genres.

No source prompt or game-specific proper name is used by production rules.
Tests prevent 'successful' static acceptance of nonexistent service fields,
shadow wallet payments and payments made before the last reject path.
"""
from types import SimpleNamespace as Obj

from roblox_mod_ai.server_interface_audit import dependency_api_errors
from roblox_mod_ai.gameplay_effect_safety import game_effect_safety_errors
from roblox_mod_ai.scoped_luau_abi import remove_redundant_state_commit
from roblox_mod_ai.host_service_codegen import scoped_body_completion_budget


def service(body: str, *, name="GenericUpgradeServer"):
    return (
        "--!strict\n"
        "local Service = {}\n"
        "function Service.start(services)\n"
        "    Service._services = services\n"
        "end\n"
        "function Service.handleAction(player, services, ...)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        + body +
        "\n    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )


def module(name="GenericUpgradeServer", code=""):
    return Obj(name=name, module_id="dyn_unrelated",
               kind="server_module", code=code,
               file_path=f"src/server/{name}.luau")


def errors(name, source, others=()):
    this = module(name)
    proposal = Obj(modules=[this, *others])
    return dependency_api_errors(this, proposal, source)


def test_undocumented_self_state_is_not_real_gameplay_api():
    source = service(
        'local catalog = services.GenericUpgradeServer.catalog\n'
        'local roster = services.GenericUpgradeServer.crew\n'
        'if not catalog or not roster then return false end\n'
        'roster.level = 2\nreturn true'
    )
    problems = errors("GenericUpgradeServer", source)
    assert any("DEPENDENCY_STATE_FIELD_UNDECLARED" in x
               and "catalog" in x for x in problems), problems
    assert any("DEPENDENCY_STATE_FIELD_UNDECLARED" in x
               and "crew" in x for x in problems), problems


def test_initialized_self_state_field_is_valid():
    source = (
        "local Service = {}\n"
        "Service.catalog = {one = {price = 1}}\n"
        "function Service.handleAction(player, services, ...)\n"
        "  local x = services.GenericUpgradeServer.catalog.one\n"
        "  return x ~= nil\n"
        "end\nreturn Service\n"
    )
    assert not any("STATE_FIELD_UNDECLARED" in x
                   for x in errors("GenericUpgradeServer", source))


def test_nonexistent_peer_field_checked_after_owner_generated():
    peer_code = (
        "local Service = {}\n"
        "function Service.GetState(player, namespace)\nreturn {}\nend\n"
        "return Service\n"
    )
    peer = module("ProfileStore", peer_code)
    generated = service(
        'local missing = services.ProfileStore.catalog\n'
        'local state = services.ProfileStore.GetState(player, "Own")\n'
        'return state ~= nil'
    )
    problems = errors("GenericUpgradeServer", generated, [peer])
    assert any("ProfileStore.catalog" in x for x in problems), problems
    assert not any("ProfileStore.GetState" in x for x in problems), problems


def test_local_wallet_balance_deduction_is_not_payment():
    source = service(
        'local coins = player.leaderstats.Coins.Value\n'
        'coins = coins - 5\n'
        'state.level = state.level + 1\n'
        'return true'
    )
    assert any("WALLET_SHADOW_DEBIT" in x
               for x in game_effect_safety_errors(source))


def test_debit_before_later_validation_is_not_atomic():
    source = service(
        'local balance = player.leaderstats.Coins.Value\n'
        'if balance < 5 then return false end\n'
        'player.leaderstats.Coins.Value = balance - 5\n'
        'local owned = services.ProfileStore.catalog\n'
        'if not owned then return false end\n'
        'owned.level = owned.level + 1\nreturn true'
    )
    assert any("NONATOMIC_PAYMENT" in x
               for x in game_effect_safety_errors(source))


def test_valid_prepay_checks_and_actual_wallet_change_pass():
    source = service(
        'local owned = services.PlayerDataManager.GetState(player, "Owned")\n'
        'if not owned or not owned.sword then return false end\n'
        'local current = player.leaderstats.Coins.Value\n'
        'if current < 5 then return false end\n'
        'player.leaderstats.Coins.Value = current - 5\n'
        'owned.sword.level = owned.sword.level + 1\nreturn true'
    )
    assert game_effect_safety_errors(source) == []


def test_state_commit_removed_only_for_same_live_profile_reference():
    code = (
        'local state = services.PlayerDataManager.GetState(player, "Items")\n'
        'if not state then return false end\n'
        'state.count = (state.count or 0) + 1\n'
        'services.PlayerDataManager:SetState(player, "Items", state)\n'
        'return true'
    )
    output = remove_redundant_state_commit(code)
    assert "SetState" not in output
    assert "GetState" in output
    assert "state.count =" in output


def test_state_commit_different_namespace_and_overwritten_reference_not_removed():
    source = (
        'local state = services.PlayerDataManager.GetState(player, "Items")\n'
        'services.PlayerDataManager.SetState(player, "Different", state)\n'
    )
    assert remove_redundant_state_commit(source) == source
    reassigned = (
        'local state = services.PlayerDataManager.GetState(player, "Items")\n'
        'state = {}\n'
        'services.PlayerDataManager.SetState(player, "Items", state)\n'
    )
    assert remove_redundant_state_commit(reassigned) == reassigned


def test_9b_length_overflow_raises_budget_not_repeats_identical_cap():
    truncated = {
        "diagnostics": ["ValueError: Model JSON completion truncated "
                        "(finish_reason=length)"],
        "model_runtime": {"finish_reason": "length"},
        "candidate": "",
    }
    assert scoped_body_completion_budget(0, None) == 1200
    assert scoped_body_completion_budget(1, truncated) == 1800
    assert scoped_body_completion_budget(2, truncated) == 2600
    invalid_api = {"diagnostics": ["DEPENDENCY_API: not exported"],
                   "model_runtime": {"finish_reason": "stop"}}
    assert scoped_body_completion_budget(2, invalid_api) == 1200
