"""Real failure regression: do not let MiMo invent missing persistence.

The checked host purchase transaction is server-owned and its saved rank is
used by a DIFFERENT server module. Verify this chain without relying on a
9B model's interpretation of individual isolated source lines.
"""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from roblox_mod_ai.host_level_upgrade import _SERVER
from roblox_mod_ai.requirement_effect_review import review_requirement_effects
from roblox_mod_ai.source_upgrade_contract import attest_paid_upgrade


ROOT = "src/server/"

PROFILE = """
local sessionData = {}
local data = sessionData[player.UserId]
local coinsVal = Instance.new("IntValue")
coinsVal.Value = data.coins
data.coins = coins.Value
savePlayerData = function(player, release)
    return store:UpdateAsync(key, function(current)
        return data
    end)
end
function PlayerDataManager.GetState(player, namespace)
    return data.gameState[namespace]
end
"""

COMBAT = """
local inv = services.PlayerDataManager.GetState(player, "RMMInventory")
local weapon = services.PlayerDataManager.GetState(player, "RMMWeaponProgress")
local ranks = services.PlayerDataManager.GetState(player, "RMMRankProgress")
local items = inv.items
local owned = type(items) == "table" and items.owned_weapon or 0
local crew = ranks.crew_performance_state or 0
local weaponRank = ranks.owned_weapon or 0
local damage = 1
if crew >= 3 then damage += 1 end
if owned >= 1 then
    if weaponRank >= 3 then damage += 1 end
end
hp = math.max(0, hp - damage)
state.alienHp = hp
"""

LAUNCH = """
local progress = services.PlayerDataManager.GetState(player, "RMMRankProgress")
local rank = progress.Spaceship or 0
local duration = math.max(3, 7 - 0.4 * rank)
local alpha = math.clamp((os.clock() - begin) / duration, 0, 1)
vehicle:PivotTo(start:Lerp(target, alpha))
"""

OWNERS = (
    ("CrewPerformanceUpgradeServer", "crew_performance_state",
     "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"),
    ("UpgradeSpaceshipPerformanServer", "Spaceship",
     "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"),
    ("WeaponUpgradePurchaseServer", "owned_weapon",
     "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"),
)


def scene(tmp_path):
    modules = []
    owners = []
    for name, target, original in OWNERS:
        path = ROOT + name + ".luau"
        code = _SERVER
        for before, after in (
            ("@TARGET@", '"' + target + '"'),
            ("@COST@", "25"), ("@STEP@", "1"),
            ("@MAX@", "10"), ("@OWNED@", "true"),
            ("@ACQUIRE_FIRST@", "false"), ("@ATTR@", '"Rank"'),
        ):
            code = code.replace(before, after)
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")
        owner = NS(file_path=path, name=name, module_id="dyn_" + name,
                   description="Server purchase that changes a real upgrade", code=code)
        modules.append(owner)
        owners.append((owner, target, original))
    for name, code in (
        ("PlayerDataManager", PROFILE), ("AlienCombat", COMBAT),
        ("LaunchCraftIntoSpace", LAUNCH),
    ):
        path = ROOT + name + ".luau"
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")
        modules.append(NS(file_path=path, name=name, module_id="dyn_" + name,
                          description="Server behavior", code=code))
    return modules, owners


@pytest.mark.parametrize("index", [0, 1, 2])
def test_verifies_real_saved_currency_and_downstream_effect(tmp_path, index):
    modules, owners = scene(tmp_path)
    module, target, original = owners[index]
    proof = attest_paid_upgrade(
        (tmp_path / module.file_path).read_text(),
        module.file_path, original,
        {m.file_path: m for m in modules}, tmp_path,
    )
    assert proof is not None
    assert proof["target"] == target
    assert proof["server_effect_consumer"].startswith(ROOT)
    assert proof["coin_persistence_owner"] == ROOT + "PlayerDataManager.luau"
    assert proof["method"] == "deterministic_persisted_upgrade_source_contract"


def test_real_upgrade_review_no_longer_requires_9b_hallucinated_coin_api(tmp_path):
    modules, owners = scene(tmp_path)
    selected = [owner for owner, _target, _original in owners]
    req = {
        "id": "req-002",
        "original_request": owners[0][2],
        "expected_outcome": "Paid crew, ship and weapon upgrades affect gameplay",
        "owner_modules": [m.name for m in selected],
        "owner_files": [m.file_path for m in selected],
    }
    plan = NS(modules=modules, game_design={
        "detailed_implementation_plan": {"required_functions": [req]},
    })
    class NoModel:
        def complete_json(self, **kwargs):
            raise AssertionError("Fully verified source should not invoke 9B semantic guesses")
    report = review_requirement_effects(plan, tmp_path, NoModel())
    assert report["status"] == "reviewed_no_blockers" and report["fully_covered"]
    assert len(report["requirements"]) == 3
    assert len(report["cross_module_contracts"]) == 3
    assert report["findings"] == []


@pytest.mark.parametrize("mutation", [
    ("PlayerDataManager.luau", "data.coins = coins.Value", "-- missing save"),
    ("AlienCombat.luau", "if crew >= 3 then damage += 1 end", "-- unused rank"),
    ("LaunchCraftIntoSpace.luau", "vehicle:PivotTo(start:Lerp(target, alpha))",
     "-- never moves ship"),
    ("WeaponUpgradePurchaseServer.luau", "coins.Value-=COST", "-- free upgrade"),
])
def test_missing_chain_disables_attestation(tmp_path, mutation):
    modules, owners = scene(tmp_path)
    filename, old, new = mutation
    target = tmp_path / ROOT / filename
    current = target.read_text()
    assert old in current
    target.write_text(current.replace(old, new, 1))
    relevant = {
        "AlienCombat.luau": 0,
        "LaunchCraftIntoSpace.luau": 1,
        "WeaponUpgradePurchaseServer.luau": 2,
        "PlayerDataManager.luau": 0,
    }[filename]
    module, _target, original = owners[relevant]
    assert attest_paid_upgrade(
        (tmp_path / module.file_path).read_text(), module.file_path,
        original, {m.file_path: m for m in modules}, tmp_path,
    ) is None


def test_explicit_thrust_not_disguised_as_voyage_duration(tmp_path):
    modules, owners = scene(tmp_path)
    module, _target, _ = owners[1]
    assert attest_paid_upgrade(
        (tmp_path / module.file_path).read_text(), module.file_path,
        "Ship upgrade must change thrust and speed, not just arrival time",
        {m.file_path: m for m in modules}, tmp_path,
    ) is None


def test_unrelated_farm_upgrade_target_is_discovered_from_source_not_whitelist(tmp_path):
    modules, owners = scene(tmp_path)
    owner, _, _ = owners[0]
    source = (tmp_path / owner.file_path).read_text()
    (tmp_path / owner.file_path).write_text(
        source.replace('"crew_performance_state"', '"honeyProduction"')
    )
    consumer = tmp_path / ROOT / "AlienCombat.luau"
    code = consumer.read_text().replace(
        "crew_performance_state", "honeyProduction"
    ).replace("state.alienHp = hp", "state.honeyHarvested = hp")
    consumer.write_text(code)
    result = attest_paid_upgrade(
        (tmp_path / owner.file_path).read_text(),
        owner.file_path, "Purchase improved hive honey production",
        {m.file_path: m for m in modules}, tmp_path,
    )
    assert result is not None
    assert result["target"] == "honeyProduction"
    assert result["server_effect_consumer"].endswith("AlienCombat.luau")


def test_a_rank_mentioned_in_comments_and_ui_is_not_a_gameplay_effect(tmp_path):
    modules, owners = scene(tmp_path)
    owner, _, _ = owners[0]
    for path in (ROOT + "AlienCombat.luau", ROOT + "LaunchCraftIntoSpace.luau"):
        target = tmp_path / path
        target.write_text(
            '-- ranks.crew_performance_state or 0\n'
            'local ranks = services.PlayerDataManager.GetState(player, "RMMRankProgress")\n'
            'local crew = ranks.crew_performance_state or 0\n'
            'player:SetAttribute("CrewTier", crew)\n'
            'return {tier=crew}\n'
        )
    assert attest_paid_upgrade(
        (tmp_path / owner.file_path).read_text(), owner.file_path,
        "Buy crew upgrades that affect actions",
        {m.file_path: m for m in modules}, tmp_path,
    ) is None
