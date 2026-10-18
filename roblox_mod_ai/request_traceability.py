"""Trace user-authored Roblox requirements to generated files without claiming playtests."""
from __future__ import annotations

import hashlib
from typing import Any

from .spec import RobloxProposal


_BUILTIN_FACET_MODULES = {
    "shop": ("ShopService", "ShopController"),
    "coins": ("CoinCollector", "PlayerDataManager"),
    "combat": ("CombatSystem", "CombatController"),
    "obby": ("ObbyService", "ObbyController"),
    "tycoon": ("TycoonService", "TycoonController"),
    "simulator": ("SimulatorService", "SimulatorController"),
    "magic": ("MagicAbilities",),
    "leaderboard": ("PlayerDataManager", "HUDController"),
    "persistence": ("PlayerDataManager",),
    "interface": ("HUDController",),
}


def build_request_traceability(proposal: RobloxProposal,
                               *, acceptance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report *planned* and *saved-source* evidence, never invent actual gameplay proof."""
    research = proposal.game_design.get("pre_design_research") or {}
    ledger = research.get("ledger") or {}
    dynamic = proposal.game_design.get("dynamic_design") or {}
    source_modules = {module.name: module for module in proposal.modules}
    assignments = dynamic.get("module_requirements") or {}
    facet_assignments = dynamic.get("module_facets") or {}
    entries = []
    unresolved = set(ledger.get("unmatched_requirements") or [])
    unimplemented = set(ledger.get("unimplemented_facets") or [])
    pending = set(ledger.get("decomposition_pending") or [])
    for requirement in ledger.get("requirements", []):
        rid = requirement["id"]
        relevant = [facet for facet in ledger.get("facets", [])
                    if rid in facet.get("requirements", [])]
        relevant_ids = {facet["id"] for facet in relevant}
        owned = {}
        if dynamic:
            for module in proposal.modules:
                linked = (rid in assignments.get(module.module_id, []) or
                          bool(relevant_ids & set(facet_assignments.get(module.module_id, []))))
                if linked and module.module_id.startswith("dyn_"):
                    owned[module.name] = module
        else:
            for facet in relevant:
                for name in _BUILTIN_FACET_MODULES.get(facet["id"], ()):
                    if name in source_modules:
                        owned[name] = source_modules[name]
        files = [{
            "module": module.name,
            "path": module.file_path,
            "source_present": bool(module.code.strip()),
            "source_sha256": (hashlib.sha256(module.code.encode("utf-8")).hexdigest()
                              if module.code.strip() else None),
        } for module in owned.values()]
        blocked = rid in unresolved or rid in pending or bool(relevant_ids & unimplemented)
        acceptance_text = dynamic.get("acceptance", {}).get(rid) if dynamic else None
        if blocked or not files:
            stage = "unresolved"
        elif all(item["source_present"] for item in files):
            stage = "source_generated_not_engine_verified"
        else:
            stage = "architecture_only"
        entries.append({
            "requirement_id": rid,
            "user_source_span": requirement["statement"],
            "facets": sorted(relevant_ids),
            "module_files": files,
            "acceptance_criterion_proposed": acceptance_text,
            "status": stage,
            "runtime_observed": False,
        })
    return {
        "schema": "rmm/request-traceability-v1",
        "original_prompt_sha256": hashlib.sha256(
            proposal.requested_prompt.encode("utf-8")).hexdigest(),
        "research_status": research.get("status", "not_recorded"),
        "requirements": entries,
        "pending_decomposition": sorted(pending),
        "unimplemented_facets": sorted(unimplemented),
        "static_acceptance_passed": (None if acceptance is None
                                     else bool(acceptance.get("passed"))),
        "roblox_engine_executed": False,
        "note": ("Generated Luau files and acceptance descriptions are not Roblox Studio "
                 "gameplay verification. Runtime proof requires an independently "
                 "recorded Roblox engine execution."),
    }
