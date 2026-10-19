"""Host-owned, auditable implementation blueprint for every generated experience.

A feature keyword selects candidate owners; it never proves that those owners
implement a complete game.  This blueprint is a planning contract, not an
assertion of successful Studio execution.
"""
from __future__ import annotations

from typing import Any

SCHEMA = "rmm/implementation-blueprint-v1"

# Required module ownership for each known stock mechanic.
OWNERS: dict[str, tuple[str, ...]] = {
    "is_shop": ("ShopService", "ShopController"),
    "is_coin_collect": ("CoinCollector", "PlayerDataManager"),
    "is_combat": ("CombatSystem", "CombatController"),
    "is_leaderboard": ("PlayerDataManager", "HUDController"),
    "is_obby": ("ObbyService", "ObbyController"),
    "is_tycoon": ("TycoonService", "TycoonController"),
    "is_simulator": ("SimulatorService", "SimulatorController"),
    "is_magic": ("MagicAbilities",),
}

# Each coupling is a distinct behavior to implement and verify.  Do not
# conflate independent systems with a working end-to-end experience.
LINKS = (
    ("is_coin_collect", "is_shop", "coin_to_purchase", "Collected currency funds server-validated purchases",
     ("CoinCollector", "ShopService")),
    ("is_coin_collect", "is_leaderboard", "coin_to_leaderboard", "Collected coins update visible leaderstats",
     ("CoinCollector", "PlayerDataManager")),
    ("is_shop", "is_combat", "purchase_to_combat", "Purchased combat equipment cannot bypass arena authority",
     ("ShopService", "CombatSystem")),
    ("is_combat", "is_leaderboard", "combat_to_leaderboard", "Combat result updates authoritative player statistics",
     ("CombatSystem", "PlayerDataManager")),
    ("is_combat", "is_shop", "combat_to_economy", "Combat rewards cannot bypass the server currency ledger",
     ("CombatSystem", "ShopService")),
)

def build_implementation_blueprint(proposal: Any) -> dict[str, Any]:
    design = proposal.game_design
    selected = [name for name, enabled in design.get("features", {}).items()
                if enabled and name in OWNERS]
    modules = {m.name: m for m in proposal.modules}
    dyn = design.get("dynamic_design") or {}
    ledger = (design.get("pre_design_research") or {}).get("ledger") or {}
    mechanics: list[dict[str, Any]] = []
    for feature in selected:
        owner_names = list(OWNERS[feature])
        mechanics.append({
            "id": feature,
            "owners": owner_names,
            "files": [modules[n].file_path for n in owner_names if n in modules],
            "missing_owners": [n for n in owner_names if n not in modules],
            "authority": "server" if feature not in ("is_leaderboard",) else "server_stats_client_display",
            "implementation_status": "source_unverified",
            "runtime_verified": False,
        })
    # Novel modules have independent, source-anchored model acceptance. Keep
    # their original facet ownership instead of substituting a stock prefab.
    for facet, expected in sorted((dyn.get("acceptance_facets") or {}).items()):
        assigned = [
            m.name for m in proposal.modules if facet in
            (dyn.get("module_facets") or {}).get(m.module_id, [])
        ]
        mechanics.append({
            "id": facet, "owners": assigned,
            "files": [modules[n].file_path for n in assigned],
            "missing_owners": [] if assigned else ["unassigned_dynamic_facet"],
            "acceptance": expected, "implementation_status": "source_unverified",
            "runtime_verified": False,
        })
    integrations = []
    for left, right, key, outcome, owner_names in LINKS:
        if left in selected and right in selected:
            integrations.append({
                "id": key, "depends_on": [left, right],
                "owners": list(owner_names), "expected": outcome,
                "negative_test": "Reject forged, duplicated or out-of-state client requests",
                "studio_verified": False,
            })
    if any(m.name == "ArenaRoundService" for m in proposal.modules):
        integrations.append({
            "id": "arena_lifecycle", "depends_on": ["is_combat"],
            "owners": ["ArenaRoundService", "CombatSystem", "PlayerDataManager"],
            "expected": "Minimum players, teleport/spawn placement, active combat, winner/draw, rewards and replay",
            "negative_test": "Solo player, late joiner, disconnect and out-of-round attack",
            "studio_verified": False,
        })
    requirements = []
    for entry in ledger.get("requirements", []):
        rid = entry.get("id", "")
        stock = [
            f.get("implementation_key") for f in ledger.get("facets", [])
            if rid in f.get("requirements", []) and f.get("implementation_key") in selected
        ]
        novel = [
            mid for mid, ids in (dyn.get("module_requirements") or {}).items()
            if rid in ids
        ]
        owners = sorted(set(
            name for feature in stock for name in OWNERS[feature]
        ) | set(
            m.name for m in proposal.modules if m.module_id in novel
        ))
        requirements.append({
            "id": rid, "source": entry.get("statement", ""),
            "owners": owners,
            "missing": not owners,
            "acceptance": (dyn.get("acceptance") or {}).get(rid, ""),
        })
    scenarios = [{
        "id": "mechanic." + m["id"], "action": "Perform the authored " + m["id"] + " interaction",
        "expect": "State change and client feedback agree with server authority",
        "status": "not_run",
    } for m in mechanics]
    scenarios.extend({
        "id": "integration." + row["id"],
        "action": row["expected"],
        "expect": row["expected"],
        "negative": row["negative_test"],
        "status": "not_run",
    } for row in integrations)
    scenarios.extend([
        {"id": "data.rejoin", "action": "Change persistent player data, leave and rejoin",
         "expect": "No duplicated or lost balance, inventory or statistics", "status": "not_run"},
        {"id": "security.remote", "action": "Send bad types, repeated requests and unauthorized action",
         "expect": "Server rejects without state mutation", "status": "not_run"},
    ])
    blocked = [
        m["id"] + ": missing " + ", ".join(m["missing_owners"])
        for m in mechanics if m["missing_owners"]
    ]
    blocked += ["unowned requirement " + r["id"] for r in requirements if r["missing"]]
    for name in ("decomposition_pending", "unimplemented_facets", "unmatched_requirements"):
        if ledger.get(name):
            blocked.append(name + ": " + ", ".join(map(str, ledger[name])))
    return {
        "schema": SCHEMA, "original_prompt": proposal.requested_prompt,
        "source_of_truth": "request_ledger_and_modules",
        "requirements": requirements, "mechanics": mechanics,
        "integration_contracts": integrations, "studio_scenarios": scenarios,
        "module_order": [m.module_id for m in proposal.modules],
        "verification_pipeline": [
            "requirements_and_design", "module_and_remote_contracts",
            "Luau_static_and_API", "Rojo_place_build",
            "Studio_MCP_or_Studio_CLI_runtime", "multiplayer_and_persistence",
        ],
        "mcp": {
            "host_tools": ["roblox_plan_experience", "roblox_plan_audit",
                           "roblox_api_search", "roblox_official_docs_search",
                           "roblox_luau_validate", "roblox_rbxlx_build"],
            "optional_local_studio": ["get_studio_state", "search_game_tree",
                "script_read", "start_stop_play", "execute_luau",
                "get_console_output", "user_keyboard_input", "user_mouse_input"],
            "runtime_required_for_verified_status": True,
        },
        "blocking_issues": blocked,
        "ready_for_codegen": not blocked,
        "studio_verified": False,
    }


def audit_implementation_blueprint(proposal: Any) -> dict[str, Any]:
    expected = build_implementation_blueprint(proposal)
    actual = proposal.game_design.get("implementation_blueprint")
    errors = []
    if not isinstance(actual, dict):
        errors.append("implementation_blueprint missing")
    else:
        for field in ("schema", "original_prompt", "requirements", "mechanics",
                      "integration_contracts", "studio_scenarios", "module_order",
                      "verification_pipeline", "blocking_issues", "ready_for_codegen"):
            if actual.get(field) != expected.get(field):
                errors.append(field + " mismatches current requirement/module graph")
        if actual.get("studio_verified") is not False:
            errors.append("Static plan cannot mark Studio gameplay as verified")
    errors.extend(expected["blocking_issues"])
    return {"passed": not errors, "errors": errors, "blueprint": expected}
