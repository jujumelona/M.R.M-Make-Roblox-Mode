"""Paid physical inventory grants: real source proofs, negative mutations, full audit.

The item identity and surrounding genre are intentionally variable. A true
source witness includes actual Tool delivery, funds debit, saved inventory,
entitlement, and respawn restoration; a UI claim is never sufficient.
"""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.host_level_upgrade import _SERVER
from roblox_mod_ai.paid_inventory_grant_attestation import (
    attest_paid_inventory_grant,
)
from roblox_mod_ai.requirement_completion_audit import (
    _is_effectful_source_line, audit_whole_requirement_completion,
)

PATH = "src/server/PurchasedGearService.luau"
EFFECT = "After the paid purchase the item upgrade is added to their inventory"
MODULES = [
    SimpleNamespace(name="PurchasedGearService", file_path=PATH,
                    description="Grant purchased gear in the player's inventory")
]


def make_source(target="generic_sword"):
    result = _SERVER
    for key, val in {
        "@TARGET@": '"' + target + '"',
        "@COST@": "65",
        "@STEP@": "1",
        "@MAX@": "7",
        "@OWNED@": "true",
        "@ACQUIRE_FIRST@": "true",
        "@GRANT_TOOL@": "true",
        "@ATTR@": '"GearRank"',
    }.items():
        result = result.replace(key, val)
    assert "@" not in result
    return result


def verify(source, behavior=EFFECT):
    return attest_paid_inventory_grant(behavior, {PATH: source}, MODULES)


def test_independent_non_space_item_purchase_is_proven():
    src = make_source("sword_from_arena")
    entry, details = verify(src)
    assert entry is not None, details
    assert entry["verdict"] == "implemented"
    assert details["method"] == "predebit_tool_grant_to_saved_inventory_and_respawn"
    assert len(entry["proof_lines"]) == 4
    assert entry["line"] in {x["line"] for x in entry["proof_lines"]}
    assert "inventory.items[TARGET]=1" in entry["quote"]
    for proof in entry["proof_lines"]:
        assert src.splitlines()[proof["line"] - 1].strip() == proof["quote"]
        assert _is_effectful_source_line(src, proof["line"])


def test_formatter_spacing_and_multiline_blocks_keep_proof():
    src = make_source("guitar_for_music_game")
    src = (src.replace("coins.Value-=COST", "coins.Value -= COST")
           .replace("tool.Parent=backpack", "tool.Parent = backpack")
           .replace("inventory.items[TARGET]=1", "inventory.items[TARGET] = 1")
           .replace("local created, granted=pcall(ensureOwnedTool,player)",
                    "local created, granted = pcall(ensureOwnedTool, player)")
           .replace(
               "if inventory.items==nil then inventory.items={} end",
               "if inventory.items == nil then\n"
               "    inventory.items = {}\nend"
           )
           .replace(
               'entitlements[script.Name.."/"..TARGET]={',
               'entitlements[script.Name .. "/" .. TARGET] = {',
           )
           .replace(
               'return {success=true,acquired=true,level=1,coins=coins.Value}',
               'return { success = true, acquired = true, level = 1, coins = coins.Value }',
           ))
    entry, details = verify(src)
    assert entry is not None, details
    assert len(entry["proof_lines"]) == 4
    for row in entry["proof_lines"]:
        assert src.splitlines()[row["line"] - 1].strip() == row["quote"]


@pytest.mark.parametrize("old,new", [
    ("local GRANT_TOOL=true", "local GRANT_TOOL=false"),
    ("local OWNED=true", "local OWNED=false"),
    ("local ACQUIRE_FIRST=true", "local ACQUIRE_FIRST=false"),
    ("tool.Parent=backpack", "tool.Parent=nil"),
    ('tool.Name=TARGET', 'tool.Name="fake_other_item"'),
    ('local inventory=services.PlayerDataManager.GetState(player,"RMMInventory")',
     'local inventory=services.PlayerDataManager.GetState(player,"FakeInventory")'),
    ("inventory.items[TARGET]=1", "inventory.items[TARGET]=0"),
    ("coins.Value-=COST", "coins.Value-=0"),
    ('local created, granted=pcall(ensureOwnedTool,player)',
     'local created, granted=true,true'),
    ('return {success=false,reason="weapon_grant_failed"}',
     'return {success=true}'),
    ('entitlements[script.Name.."/"..TARGET]={',
     'local unusedEntitlement={'),
    ('task.defer(restoreIfOwned)', 'task.defer(function() end)'),
    ('player.CharacterAdded:Connect(function()', 'player.ChildAdded:Connect(function()'),
])
def test_unimplemented_or_corrupted_paid_grant_fails_closed(old, new):
    src = make_source()
    assert old in src, "The mutation fixture must target real source"
    mutated = src.replace(old, new)
    assert mutated != src
    assert verify(mutated)[0] is None


def test_unrelated_inventory_mutation_does_not_claim_paid_gear():
    src = make_source()
    entry, info = verify(src, "The player purchases a decorative map background")
    assert entry is None
    assert info["reason"] == "not_a_paid_inventory_grant_effect"


def test_two_equal_owners_do_not_get_arbitrary_witness():
    src = make_source()
    entry, info = attest_paid_inventory_grant(
        EFFECT, {PATH: src, "src/server/DuplicateGearService.luau": src},
        MODULES,
    )
    assert entry is None
    assert info["candidate_count"] == 2


def test_full_requirement_audit_of_paid_item_does_not_call_small_ai(tmp_path):
    source = make_source("purchased_guitar")
    path = tmp_path / PATH
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    proposal = SimpleNamespace(
        modules=MODULES,
        game_design={"detailed_implementation_plan": {
            "required_functions": [{
                "id": "req-any-purchase",
                "original_request": "Buy an instrument for in-game currency",
                "expected_outcome": EFFECT,
                "server_state_changes": [EFFECT],
                "owner_files": [PATH],
            }],
        }},
    )

    class ModelMustNotInventCodeEvidence:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            raise AssertionError("A deterministic proof must not ask the model")

    report = audit_whole_requirement_completion(
        proposal, tmp_path, ModelMustNotInventCodeEvidence(),
        host_witness_only=True,
    )
    assert report["status"] == "reviewed_no_blockers", report
    assert report["fully_covered"], report
    assert len(report["checks"]) == 1
    assert len(report["checks"][0]["proof_lines"]) == 4
    assert any(
        r.get("stage") == "deterministic_paid_inventory_audit"
        for r in report.get("recovery", [])
    )
