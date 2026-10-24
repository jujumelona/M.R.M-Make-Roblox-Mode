"""Host-owned, auditable implementation blueprint for every generated experience.

A feature keyword selects candidate owners; it never proves that those owners
implement a complete game.  This blueprint is a planning contract, not an
assertion of successful Studio execution.
"""
from __future__ import annotations

from typing import Any

from .semantic_preservation import source_intent_conflicts

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

# Concrete behavioral contracts for stock mechanics, not generic genre labels.
# Every row becomes an observable Studio scenario, including negative paths.
STOCK_BEHAVIORS: dict[str, dict[str, str]] = {
    "is_coin_collect": {
        "interaction": "Player touches an available coin part",
        "precondition": "Player character and server balance are initialized; coin is active",
        "postcondition": "Server increments Coins once, hides coin and respawns it after cooldown",
        "rejection": "Non-player contact and concurrent duplicate touches grant nothing",
        "persistence": "Coins survive reconnect on a published experience",
    },
    "is_shop": {
        "interaction": "Player opens shop prompt and buys a selected item",
        "precondition": "Alive player is near shop; item exists; balance covers price",
        "postcondition": "Server deducts exact price, grants real gameplay effect and client shows result",
        "rejection": "Forged item IDs, insufficient balance, remote spam and duplicates are rejected",
        "persistence": "Permanent purchases survive respawn and reconnect",
    },
    "is_combat": {
        "interaction": "Player attacks an eligible opponent from valid reach",
        "precondition": "Attacker and target are alive; server verifies range, sight and round enrollment",
        "postcondition": "Only validated target loses health; lethal attack awards knockout credit once",
        "rejection": "Out-of-range, spectator, cooldown and spoofed target are rejected",
        "persistence": "Authoritative knockout record persists if leaderboard is requested",
    },
    "is_leaderboard": {
        "interaction": "Player gains currency, wins or knockouts",
        "precondition": "Server owns leaderstats and loads saved profile",
        "postcondition": "Visible stats match authoritative Coins, Wins and KOs where applicable",
        "rejection": "Clients cannot submit arbitrary score increments",
        "persistence": "Stats are restored from the same versioned player profile",
    },
    "is_obby": {
        "interaction": "Player visits checkpoints and reaches the requested finish",
        "precondition": "Checkpoint order and quantity match user request",
        "postcondition": "Server records progress and respawn position; completion is visible",
        "rejection": "Stage skipping and non-player checkpoint touches cannot fake completion",
        "persistence": "Saved checkpoint progresses according to declared game policy",
    },
    "is_tycoon": {
        "interaction": "Player claims a plot, earns cash and unlocks a purchase pad",
        "precondition": "Plot belongs to that player; production and price are valid",
        "postcondition": "Server activates purchased equipment and reflects economy change",
        "rejection": "Other players cannot steal claimed plot rewards or free upgrades",
        "persistence": "Saved unlocks are restored from server profile",
    },
    "is_simulator": {
        "interaction": "Player performs the core collection action and sells at a zone",
        "precondition": "Player capacity, cooldown and zone access are valid",
        "postcondition": "Server increases stored resource then exchanges it for currency",
        "rejection": "Client resource injection and oversized sell requests are rejected",
        "persistence": "Persistent progress follows authored save policy",
    },
    "is_magic": {
        "interaction": "Player activates a purchased or unlocked magic ability",
        "precondition": "Ability is owned, ready, and target is valid",
        "postcondition": "Server applies documented effect and broadcasts visuals to clients",
        "rejection": "Non-owners, cooldown bypass and out-of-round target are rejected",
        "persistence": "Permanent ability ownership is restored",
    },
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

def _matches_source_motion(actual: Any, mandatory: dict[str, str]) -> bool:
    """Require every source-owned movement obligation, permit extra host ABI.

    Identity/materialization metadata added by the host is not a change to
    the source promise. An absent or altered required property still fails.
    """
    return (isinstance(actual, dict) and
            all(actual.get(key) == value for key, value in mandatory.items()))


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
            **STOCK_BEHAVIORS[feature],
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
        selected_behaviors = sorted(set(stock))
        acceptance_items = [STOCK_BEHAVIORS[name]["postcondition"]
                            for name in selected_behaviors if name in STOCK_BEHAVIORS]
        if "is_combat" in selected_behaviors and any(
            module.name == "ArenaRoundService" for module in proposal.modules
        ):
            acceptance_items.append(
                "A minimum two-player match begins after countdown, pays the actual "
                "survivor, handles disconnect/draw and returns everyone to the lobby")
            owners = sorted(set(owners) | {"ArenaRoundService", "RoundController"})
        authored_acceptance = (dyn.get("acceptance") or {}).get(rid, "")
        acceptance = authored_acceptance or "; ".join(acceptance_items)
        requirements.append({
            "id": rid, "source": entry.get("statement", ""),
            "owners": owners,
            "missing": not owners or not acceptance.strip(),
            "acceptance": acceptance,
            "acceptance_status": "planned_not_run",
        })
    scenarios = [{
        "id": "mechanic." + m["id"],
        "setup": m.get("precondition", "Real Studio with generated modules available"),
        "action": m.get("interaction", "Perform requested mechanic " + m["id"]),
        "expect": m.get("postcondition", m.get("acceptance", "Observed game state changes")),
        "negative": m.get("rejection", "Reject invalid client input"),
        "persistence": m.get("persistence", "Verify authored save policy"),
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
    # Imported pre-fix plans can have a source-verified spacecraft launch
    # but lose the physical movement obligation when the architect metadata
    # is serialized. Rebuild that obligation from the ORIGINAL requirement
    # and other source clauses; never infer launch from a model search query.
    if dyn and isinstance(ledger.get("requirements"), list):
        from .world_motion_contract import source_motion_contract
        source_reqs = [
            (row["id"], row["statement"])
            for row in ledger["requirements"]
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and isinstance(row.get("statement"), str)
        ]
        motion_map = dyn.get("host_world_motion") or {}
        for requirement_id, statement in source_reqs:
            contract = source_motion_contract(
                statement,
                [span for other_id, span in source_reqs
                 if other_id != requirement_id],
            )
            if contract is None:
                continue
            server_owners = [
                module for module in proposal.modules
                if getattr(getattr(module, "kind", None), "value", None)
                   in ("server_module", "server_script")
                and requirement_id in
                   (dyn.get("module_requirements") or {}).get(module.module_id, [])
            ]
            if not any(
                isinstance(motion_map, dict)
                and _matches_source_motion(motion_map.get(module.name), contract)
                for module in server_owners
            ):
                blocked.append(
                    requirement_id +
                    ": SOURCE_WORLD_TRANSITION_CONTRACT_LOST: original request "
                    "requires physical craft movement with players aboard, "
                    "but the saved design has no server-owned motion obligation"
                )
    # Architecture-based recovery must survive beyond planning: the original
    # classifier did NOT succeed, so its placeholder cannot be rechecked as
    # though it were a model classification. Conversely, merely writing
    # architecture_recovered_chunks into a JSON file must never bypass source
    # fidelity. Re-certify the CURRENT server owners and acceptance contracts
    # whenever a blueprint is built or audited after a code/plan revision.
    recovered_chunks: set[str] = set()
    recovered_raw = ledger.get("architecture_recovered_chunks") or []
    if recovered_raw:
        atoms = {
            item.get("chunk_id"): item
            for item in ledger.get("atomic_intents", [])
            if isinstance(item, dict) and isinstance(item.get("chunk_id"), str)
        }
        if (not isinstance(recovered_raw, list)
                or any(not isinstance(cid, str) or not cid for cid in recovered_raw)
                or len(set(recovered_raw)) != len(recovered_raw)
                or any(atoms.get(cid, {}).get("classification_origin")
                       != "architecture_source_verified" for cid in recovered_raw)):
            blocked.append("SOURCE_ARCHITECTURE_RECOVERY_INVALID: missing or forged source provenance")
        else:
            from .source_architecture_recovery import (
                SourceArchitectureRecoveryError, certify_unclassified_chunks,
            )
            try:
                current = certify_unclassified_chunks(
                    dict(ledger, classification_unverified=recovered_raw),
                    dyn, proposal.modules,
                )
                if set(current) != set(recovered_raw):
                    raise SourceArchitectureRecoveryError(
                        "Architecture did not re-certify every recovered source chunk")
                recovered_chunks = set(current)
            except SourceArchitectureRecoveryError as exc:
                blocked.append("SOURCE_ARCHITECTURE_RECOVERY_INVALID: " + str(exc))
    # Every ordinarily classified source span still needs a truthful model
    # classification. Architecture-recovered spans instead require the
    # stricter, independently re-certified owner/outcome evidence above.
    # All spans, regardless of classification, need actual server behavior.
    for atom in ledger.get("atomic_intents", []):
        if not isinstance(atom, dict):
            continue
        span = atom.get("source_span", "")
        facet = atom.get("facet_id", "")
        classification = str(atom.get("intent", "")) + " " + str(atom.get("english_query", ""))
        if atom.get("chunk_id") not in recovered_chunks:
            for mismatch in source_intent_conflicts(
                    span, classification, require_implementation=False):
                blocked.append(str(facet) + ": classifier " + mismatch)
        server_owners = [
            m for m in proposal.modules
            if m.kind.value in ("server_module", "server_script")
            and facet in (dyn.get("module_facets") or {}).get(m.module_id, [])
        ]
        if server_owners:
            implementation = " ".join(m.description for m in server_owners)
            # Authoritative server behavior must satisfy the original action
            # ON ITS OWN. Previously concatenating client acceptance could
            # turn an unrelated ship-upgrade server into a "valid launcher"
            # just by mentioning launch in the UI. Never allow a client-side
            # promise to fulfill absent backend mechanics.
            for mismatch in source_intent_conflicts(span, implementation):
                blocked.append(str(facet) + ": implementation " + mismatch)
    # Exact text ownership is not semantic implementation. Previously a failed
    # source classifier inserted "Implement only the requested gameplay ..." and
    # the architect could replace an enemy encounter with PvP or omit settlement
    # state while the blueprint claimed every requirement was implemented.
    # A missing semantic classification must be resolved *before* any Luau.
    # Recovered chunks were independently certified against current server
    # owners and acceptance above. Do not keep them in the unresolved list;
    # unverified or forged recovery stays blocked as before.
    unknown_chunks = [
        chunk for chunk in (ledger.get("classification_unverified") or [])
        if chunk not in recovered_chunks
    ]
    if unknown_chunks:
        blocked.append(
            "unclassified_gameplay_requirements: " +
            ", ".join(str(chunk) for chunk in unknown_chunks[:16]) +
            " (reclassify source-anchored actions before designing game modules)"
        )
    for name in ("decomposition_pending", "unimplemented_facets", "unmatched_requirements"):
        if ledger.get(name):
            blocked.append(name + ": " + ", ".join(map(str, ledger[name])))
    return {
        "schema": SCHEMA, "original_prompt": proposal.requested_prompt,
        "source_of_truth": "request_ledger_and_modules",
        "requirements": requirements, "mechanics": mechanics,
        "integration_contracts": integrations, "studio_scenarios": scenarios,
        # Stable roster fingerprint. Topological scheduling is allowed to reorder
        # modules without changing the requirements or verified ownership.
        "module_order": sorted(m.module_id for m in proposal.modules),
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
