"""Plan96: paid rank -> real consumer, weapon purchase -> Tool -> damage.

Prevents source-review hallucinations about literal TARGET aliases, and
prevents attribute-only weapon upgrades from being counted as gameplay.
All checks are offline; they do not claim Roblox Studio execution.
"""
from pathlib import Path

from roblox_mod_ai.host_level_upgrade import _SERVER as RANK_SERVER
from roblox_mod_ai.host_verified_typed_effects import render_verified_effect
from roblox_mod_ai.host_owned_weapon_performance import (
    _SERVER as WEAPON_SERVER, eligible_owned_weapon_performance,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.source_upgrade_contract import attest_paid_upgrade
from test_log25_verified_typed_effects import _fixture as effect_fixture
from test_source_upgrade_contract import scene, ROOT


def test_rank_literal_alias_reaches_world_damage_attribute(tmp_path):
    modules, owners = scene(tmp_path)
    combat = tmp_path / ROOT / "AlienCombat.luau"
    combat.write_text("""
local ranks = services.PlayerDataManager.GetState(player, "RMMRankProgress")
local crew = ranks.crew_performance_state or 0
local weapon = ranks.owned_weapon or 0
local target = workspace:FindFirstChild("ActualWorldTarget", true)
local hp = target:GetAttribute("ActualWorldHealth")
local damage = math.min(70, 20 + 2 * crew + 3 * weapon)
local remaining = math.max(0, hp - damage)
target:SetAttribute("ActualWorldHealth", remaining)
""")
    owner, target, original = owners[0]
    source = (tmp_path / owner.file_path).read_text()
    proof = attest_paid_upgrade(
        source, owner.file_path, original,
        {m.file_path: m for m in modules}, tmp_path)
    assert proof is not None
    assert proof["target"] == "crew_performance_state"
    assert proof["server_effect_consumer"] == ROOT + "AlienCombat.luau"


def test_cosmetic_rank_attribute_does_not_falsely_certify_world_effect(tmp_path):
    modules, owners = scene(tmp_path)
    combat = tmp_path / ROOT / "AlienCombat.luau"
    combat.write_text("""
local ranks = services.PlayerDataManager.GetState(player, "RMMRankProgress")
local crew = ranks.crew_performance_state or 0
local target = workspace:FindFirstChild("ActualWorldTarget", true)
local hp = target:GetAttribute("ActualWorldHealth")
local damage = math.min(70, 20 + 2 * crew)
local remaining = math.max(0, hp - damage)
player:SetAttribute("DisplayedRank", remaining)
""")
    owner, _target, original = owners[0]
    assert attest_paid_upgrade(
        (tmp_path / owner.file_path).read_text(), owner.file_path,
        original, {m.file_path: m for m in modules}, tmp_path) is None


def test_paid_first_weapon_purchases_real_owned_tool_and_entitlement():
    assert "local GRANT_TOOL=@GRANT_TOOL@" in RANK_SERVER
    assert "entitlements[script.Name..\"/\"..TARGET]" in RANK_SERVER
    assert "tool=Instance.new(\"Tool\")" in RANK_SERVER
    assert "tool.Parent=backpack" in RANK_SERVER
    assert "inventory.items[TARGET]=1" in RANK_SERVER
    assert "coins.Value-=COST" in RANK_SERVER
    assert RANK_SERVER.index("coins.Value-=COST") < RANK_SERVER.index("tool.Parent=backpack") or (
        # ensureOwnedTool function is declared early, but called in the
        # acquisition success branch AFTER server price is debited.
        RANK_SERVER.index("coins.Value-=COST") < RANK_SERVER.index(
            "assert(ensureOwnedTool(player)")
    )
    assert "task.defer(function() ensureOwnedTool(player) end)" in RANK_SERVER


def _add_weapon_upgrade_peer(proposal):
    purchase, _ = effect_fixture("purchase")
    original = purchase.game_design["dynamic_design"]
    design = proposal.game_design["dynamic_design"]
    owned = [m for m in purchase.modules
             if m.name.startswith("VerifiedWeaponPerformance")]
    assert len(owned) == 2
    proposal.modules.extend(owned)
    for peer in owned:
        design["module_remotes"][peer.module_id] = original["module_remotes"][peer.module_id]
    for name, row in original["host_actions"].items():
        if row["service"] == "VerifiedWeaponPerformanceServer":
            design["host_actions"][name] = row
            design["remotes"][name] = original["remotes"][name]
            design["host_typed_actions"][name] = original["host_typed_actions"][name]
    assert eligible_owned_weapon_performance(owned[0], proposal) is not None


def test_paid_weapon_rank_changes_damage_rate_and_ammo_in_real_host_combat():
    proposal, combat = effect_fixture("combat")
    _add_weapon_upgrade_peer(proposal)
    code = render_verified_effect(combat, proposal)
    assert code is not None
    assert 'GetState(player, "RMMWeaponPerformance")' in code
    assert 'GetState(player, "RMMWeaponAmmo")' in code
    assert '4 * upgradedLevel' in code
    assert 'local fireInterval = 0.3 / (1 + 0.1 * upgradedLevel)' in code
    assert 'now - recent[player] < fireInterval' in code
    assert 'now - recent[player] < 0.3 then' not in code
    assert 'weaponAmmo.remaining -= 1' in code
    assert 'weaponAmmoStore[equipped.Name] = weaponAmmo' in code
    assert 'target:SetAttribute("RMMAlienHealth", remaining)' in code
    assert code.index('weaponAmmo.remaining -= 1') < code.index(
        'target:SetAttribute("RMMAlienHealth", remaining)')
    errors = [x for x in LuauStaticAnalyzer().analyze_source(
        code, combat.file_path) if x.severity == "ERROR"]
    assert not errors, [(x.rule, x.message) for x in errors]


def test_weapon_upgrade_not_claimed_when_world_combat_peer_missing():
    proposal, combat = effect_fixture("combat")
    code = render_verified_effect(combat, proposal)
    assert code is not None
    assert 'GetState(player, "RMMWeaponPerformance")' not in code


def test_tool_mirrors_are_not_the_server_authority_source():
    assert 'saved[tool.Name] = {level = level + 1}' in WEAPON_SERVER
    assert 'tool:SetAttribute("RMMMagazineSize", 6 + 2 * level)' in WEAPON_SERVER
    assert 'tool:SetAttribute("RMMFireInterval", 0.3 / (1 + 0.1 * level))' in WEAPON_SERVER


def test_source_reviewer_sees_true_per_item_weapon_effect_consumer(tmp_path):
    from roblox_mod_ai.requirement_effect_review import _downstream_effect_evidence
    proposal, combat = effect_fixture("combat")
    _add_weapon_upgrade_peer(proposal)
    code = render_verified_effect(combat, proposal)
    assert code
    upgrade = next(m for m in proposal.modules
                   if m.name == "VerifiedWeaponPerformanceServer")
    files = {upgrade.file_path: upgrade, combat.file_path: combat}
    for path, source in ((upgrade.file_path, WEAPON_SERVER),
                         (combat.file_path, code)):
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source, encoding="utf-8")
    evidence = _downstream_effect_evidence(
        upgrade.file_path, WEAPON_SERVER, files, tmp_path)
    consumer = next((e for e in evidence
                     if e["file"] == combat.file_path), None)
    assert consumer is not None
    assert "RMMWeaponPerformance" in consumer["shared_persisted_state"]
    assert "upgradedLevel" in consumer["source_excerpt"]
    assert "damage" in consumer["source_excerpt"]
    assert "fireInterval" in consumer["source_excerpt"]
    assert "weaponAmmo" in consumer["source_excerpt"]


def test_consumer_hint_never_uses_unrelated_read_only_inventory(tmp_path):
    from roblox_mod_ai.requirement_effect_review import _downstream_effect_evidence
    producer = "src/server/Purchase.luau"
    consumer = "src/server/Decorative.luau"
    source = '''
local inventory = manager.GetState(player, "RMMInventory")
local upgraded = manager.GetState(player, "RMMGearRank")
upgraded[item] = {level = 2}
'''
    other = '''
local inventory = manager.GetState(player, "RMMInventory")
player:SetAttribute("DisplayRank", 8)
'''
    for name, code in ((producer, source), (consumer, other)):
        out = tmp_path / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(code)
    class File:
        pass
    modules = {producer: File(), consumer: File()}
    assert _downstream_effect_evidence(producer, source, modules, tmp_path) == []


def test_no_nil_weapon_inventory_probe_or_payment_before_preflight():
    assert "and inventory.items[TARGET]>=1" not in RANK_SERVER
    assert "and (inventory.items[TARGET] or 0)>=1" in RANK_SERVER
    assert RANK_SERVER.index("invalid_owned_weapon_instance") < RANK_SERVER.index(
        "coins.Value-=COST")
    assert 'existing and not existing:IsA("Tool")' in RANK_SERVER
