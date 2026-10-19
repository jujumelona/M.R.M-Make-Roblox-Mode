"""Prompt-agnostic implementation specification owned by the host.

The plan is derived from the request ledger and model-authored architecture.
It describes *what must be implemented*, not a claim that an engine ran.
"""
from __future__ import annotations

import os
from typing import Any

SCHEMA = "rmm/detailed-implementation-plan-v1"


def build_detailed_plan(proposal: Any) -> dict[str, Any]:
    design = proposal.game_design
    blueprint = design.get("implementation_blueprint") or {}
    ledger = ((design.get("pre_design_research") or {}).get("ledger") or {})
    dynamic = design.get("dynamic_design") or {}
    modules = {m.name: m for m in proposal.modules}
    mechanisms = {str(m.get("id")): m for m in blueprint.get("mechanics", [])
                  if isinstance(m, dict)}
    requirements = []
    for req in blueprint.get("requirements", []):
        rid = str(req.get("id", ""))
        owners = list(req.get("owners") or [])
        related = [m for m in mechanisms.values()
                   if set(m.get("owners", [])) & set(owners)]
        # Acceptance is taken from the authored request/architecture, never
        # replaced by a fabricated 'game ends' or a generic demo objective.
        requirements.append({
            "id": rid,
            "original_request": req.get("source", ""),
            "expected_outcome": req.get("acceptance", ""),
            "owner_modules": owners,
            "owner_files": [modules[n].file_path for n in owners if n in modules],
            "input_or_trigger": [m.get("interaction", m.get("action", ""))
                                 for m in related if m.get("interaction", m.get("action"))],
            "preconditions": [m["precondition"] for m in related if m.get("precondition")],
            "server_state_changes": [m.get("postcondition", m.get("acceptance"))
                                     for m in related if m.get("postcondition", m.get("acceptance"))],
            "invalid_or_edge_inputs": [m["rejection"] for m in related if m.get("rejection")],
            "persisted_state": [m["persistence"] for m in related if m.get("persistence")],
            "client_feedback": [m.get("postcondition", m.get("acceptance"))
                                for m in related if m.get("postcondition", m.get("acceptance"))],
            "verification": {
                "host": "Verify owner source exists and requirement IDs trace to implementation",
                "offline": "Run explicit pure Luau tests if authored (NOT an engine test)",
                "engine": "not_executable_in_colab",
            },
        })

    modules_plan = []
    for module in proposal.modules:
        mid = module.module_id
        owned = sorted([str(k) for k in
                        (dynamic.get("module_requirements") or {}).get(mid, [])])
        if not owned:
            owned = sorted([r["id"] for r in requirements
                            if module.name in r["owner_modules"]])
        modules_plan.append({
            "id": mid, "name": module.name, "file": module.file_path,
            "service": str(module.roblox_service),
            "role": str(module.kind),
            "responsibility": module.description,
            "requirements": owned,
            "depends_on": list(module.depends_on or []),
            "observable_behaviors": [
                m.get("postcondition") or m.get("acceptance") or ""
                for m in mechanisms.values() if module.name in m.get("owners", [])
            ] or [str((dynamic.get("module_behaviors") or {}).get(mid, ""))],
            "authoritative_state": ("server_owned"
                                    if module.file_path.startswith("src/server/")
                                    else "client_or_shared_no_authoritative_mutations"),
            "must_handle": [
                "initialization and missing dependencies",
                "invalid input and duplicate/out-of-order events",
                "cleanup, reconnection or repeated execution where applicable",
            ],
        })
    integrations = [{
        "id": row.get("id", ""), "modules": list(row.get("owners", [])),
        "prerequisites": row.get("depends_on", []),
        "expected_transition": row.get("expected", ""),
        "negative_case": row.get("negative_test", ""),
        "validation": "source_interface_contract_and_offline_test_if_available",
    } for row in blueprint.get("integration_contracts", [])]
    for rid, item in (dynamic.get("acceptance") or {}).items():
        if rid and rid not in {r["id"] for r in requirements}:
            # Never silently invent a requirement: preserve inconsistent
            # architecture as an unowned explicit issue in audit.
            requirements.append({
                "id": rid, "original_request": "", "expected_outcome": item,
                "owner_modules": [], "owner_files": [], "input_or_trigger": [],
                "preconditions": [], "server_state_changes": [],
                "invalid_or_edge_inputs": [], "persisted_state": [],
                "client_feedback": [], "verification": {"engine": "not_executable_in_colab"},
            })
    issues = list(blueprint.get("blocking_issues") or [])
    issues.extend("no implementation owner for " + r["id"]
                  for r in requirements if not r["owner_modules"])
    issues.extend("no observable result for " + r["id"]
                  for r in requirements if not str(r["expected_outcome"]).strip())
    return {
        "schema": SCHEMA,
        "original_prompt": proposal.requested_prompt,
        "scope": design.get("project_mode", "new_experience"),
        "required_functions": requirements,
        "implementation_modules": modules_plan,
        "cross_module_connections": integrations,
        "runtime_execution": "excluded_from_colab",
        "review_protocol": [
            "Compare EACH original requirement with planned owner and actual code",
            "Inspect actual module source, dependencies, state transitions and failure paths",
            "Demand exact source quotation for every defect; never guess code exists",
            "Re-run deterministic static and offline tests after any repair",
        ],
        "blocking_issues": sorted(set(issues)),
    }


def enrich_detailed_plan(plan: dict[str, Any], router: Any) -> dict[str, Any]:
    """Have the planning model flesh out EACH source-bound requirement.

    This is separate from module code generation, so the coding agent receives
    an explicit pre-approved stepwise specification rather than improvising.
    """
    option = os.environ.get("RMM_ENABLE_AI_DETAILED_PLAN", "auto").lower()
    enabled = option == "1" or (
        option == "auto"
        and os.environ.get("RMM_ENABLE_MODEL_GENERATION") != "0"
        and bool(os.environ.get("ROBLOX_LLAMA_SERVER_URL")
                 or os.environ.get("RMM_MODEL_BASE_URL"))
    )
    plan["ai_planning"] = {"status": "not_run", "requirements": {},
                           "reason": "No local planning model configured"}
    if not enabled:
        return plan
    keys = ("steps", "preconditions", "server_state_changes",
            "client_feedback", "failure_cases", "cross_module_interfaces",
            "offline_verification")
    outputs: dict[str, dict[str, list[str]]] = {}
    try:
        for req in plan["required_functions"]:
            rid = req["id"]
            prompt = (
                "Create a DETAILED implementation specification for ONE original "
                "Roblox game requirement. Keep the user's intended scope exactly. "
                "Do NOT claim execution in Roblox Studio or invent additional "
                "endings/features. Never write code yet. Return JSON with exactly "
                "these arrays of actionable, specific statements: "
                + ", ".join(keys) + ". All arrays must be nonempty. "
                "Identify server authority, initial state, event or user input, "
                "state transitions, player-visible feedback, edge cases and "
                "dependencies. Prefer concrete state invariants over narration. "
                "Original requirement: " + str(req["original_request"])[:500] +
                "\nExpected outcome: " + str(req["expected_outcome"])[:650] +
                "\nOwners: " + str(req["owner_files"])[:500] +
                "\nKnown interfaces: " + str(plan["cross_module_connections"])[:1500]
            )
            data = router.complete_json(
                prompt=prompt, role="planner", temperature=0,
                max_tokens=1000)
            if not isinstance(data, dict) or any(
                not isinstance(data.get(k), list) or
                not data[k] or not all(isinstance(v, str) and v.strip()
                                      for v in data[k]) for k in keys
            ):
                raise ValueError("Invalid detailed requirement response: " + rid)
            outputs[rid] = {k: [x.strip()[:400] for x in data[k][:8]]
                            for k in keys}
        plan["ai_planning"] = {
            "status": "enriched", "requirements": outputs,
            "reason": "Model-generated details require subsequent source review",
        }
    except (ValueError, TypeError, RuntimeError, KeyError, OSError) as exc:
        plan["ai_planning"] = {
            "status": "failed", "requirements": outputs,
            "reason": type(exc).__name__ + ": " + str(exc)[:300],
        }
    return plan


def audit_detailed_plan(proposal: Any) -> dict[str, Any]:
    actual = proposal.game_design.get("detailed_implementation_plan")
    expected = build_detailed_plan(proposal)
    issues = []
    if not isinstance(actual, dict):
        issues.append("detailed implementation plan missing")
    else:
        for key in ("schema", "original_prompt", "scope", "required_functions",
                    "implementation_modules", "cross_module_connections",
                    "runtime_execution", "review_protocol", "blocking_issues"):
            if actual.get(key) != expected.get(key):
                issues.append(key + " stale or does not match request and module graph")
    issues += expected["blocking_issues"]
    model = (actual or {}).get("ai_planning") if isinstance(actual, dict) else None
    if isinstance(model, dict):
        if model.get("status") == "failed":
            issues.append("AI detailed plan failed: " + str(model.get("reason", "")))
        if model.get("status") == "enriched":
            known = {r["id"] for r in expected["required_functions"]}
            if set(model.get("requirements", {})) != known:
                issues.append("AI detailed planning did not cover every authored requirement")
    return {"passed": not issues, "errors": issues, "expected": expected}
