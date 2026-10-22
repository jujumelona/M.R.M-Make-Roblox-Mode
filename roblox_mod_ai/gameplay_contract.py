"""Host-owned game lifecycle contract: objective, action, feedback, outcome, replay.

This is a *source-level* design/acceptance contract. It never claims that a
Roblox Studio gameplay test ran. Contracts are derived from scoped authored
requirements and module ownership, not invented global game-ending templates.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

SCHEMA = "rmm/gameplay-contract-v1"
CYCLE = ("entry", "interaction", "feedback", "outcome", "reentry")
FINITE_CUES = ("엔딩", "결말", "최종 보스", "최종보스", "ending",
               "final boss", "story finale", "엔드 크레딧")


def arena_round_requested(prompt: str, features: dict, *, dynamic: bool = False,
                          addon: bool = False) -> bool:
    """Rounds belong only to explicit arena PvP requests, not all combat."""
    if dynamic or addon or not features.get("is_combat"):
        return False
    p = prompt.lower()
    return any(x in p for x in ("아레나", "검투", "arena", "pvp", "결투", "duel"))


def _unit(identifier: str, owner: str, markers: list[str],
          action: str, observable: str) -> dict:
    return {"id": identifier, "owner": owner, "source_markers": markers,
            "action": action, "observable": observable,
            "studio_verified": False}


def build_gameplay_contract(proposal: Any) -> dict[str, Any]:
    """Generate a bounded contract from actual module ownership.

    A repeated game session has an *outcome*, not necessarily a story ending.
    Existing-Experience addons must NOT replace the host game's lifecycle.
    """
    gd = proposal.game_design
    features = gd.get("features") or {}
    dynamic = gd.get("dynamic_design") or {}
    addon = gd.get("project_mode") == "existing_experience_addon"
    names = {m.name for m in proposal.modules}
    round_mode = arena_round_requested(proposal.requested_prompt, features,
                                      dynamic=bool(dynamic), addon=addon)
    if addon:
        mode, ending = "addon", "host_game_unchanged"
    elif round_mode:
        mode, ending = "round", "victory_defeat_draw"
    elif features.get("is_obby"):
        mode, ending = "stage", "final_checkpoint"
    elif dynamic:
        mode, ending = "custom_activity", "observable_activity_outcome"
    else:
        mode, ending = "open_ended", "repeatable_progress"
    units: list[dict] = []
    if "GameObjectiveController" in names:
        units.append(_unit("onboarding", "GameObjectiveController",
            ["GameObjective", "GameActionHint", "toggle.Activated"],
            "read the objective and the first action",
            "briefing is visible and can be toggled"))
    if "CoinCollector" in names:
        units.append(_unit("collect", "CoinCollector",
            ["GetPlayerFromCharacter", ".Touched:Connect", ".Value +="],
            "touch a coin", "server updates Coins"))
    if "ShopService" in names:
        units.append(_unit("purchase", "ShopService",
            ["OnServerInvoke", "EconomyRules.charge", "OwnedItems"],
            "buy an item", "server charges coins and grants the item"))
    if "CombatSystem" in names:
        units.append(_unit("attack", "CombatSystem",
            ["OnServerEvent", "MAX_REACH", "TakeDamage"],
            "attack an opponent", "server validates and damages target"))
    for feature, owner, markers, action, outcome in (
        ("is_obby", "ObbyService", ["pad.Touched", "stageVal.Value"],
         "reach checkpoints", "stage advances"),
        ("is_tycoon", "TycoonService", ["collector.Touched", "coins.Value +="],
         "collect output", "cash increases"),
        ("is_simulator", "SimulatorService", ["clickRemote.OnServerEvent", "Coins"],
         "perform simulation action", "currency increases"),
    ):
        if features.get(feature) and owner in names:
            units.append(_unit(feature, owner, markers, action, outcome))
    if round_mode:
        units.append(_unit("round", "ArenaRoundService",
            ["MIN_PLAYERS", "ROUND_DURATION", "Humanoid", "winner", "RoundStatus"],
            "participate in a match", "server announces winner or draw"))
        units.append(_unit("round_feedback", "RoundController",
            ["RoundStatus", "OnClientEvent", "TextLabel"],
            "observe result", "round state displayed to each player"))
    if mode == "stage":
        units.append(_unit("stage_finish", "ObbyService",
            ['"ObbyComplete"', "lastStage", "stageVal.Value"],
            "reach final checkpoint", "server marks the stage run complete"))
        units.append(_unit("stage_feedback", "ObbyController",
            ['"ObbyComplete"', "GetAttributeChangedSignal"],
            "complete stage run", "completion displayed to player"))
    # Custom features are only accepted when a real authored acceptance facet
    # is bound to an actual generated module. Never invent a named boss/ending.
    if dynamic:
        module_facets = dynamic.get("module_facets", {})
        acceptance = dynamic.get("acceptance_facets", {})
        for facet_id, observable in sorted(acceptance.items()):
            owners = [m.name for m in proposal.modules
                      if m.module_id.startswith("dyn_")
                      and facet_id in module_facets.get(m.module_id, [])]
            if owners:
                # A strict-mode pragma is NOT evidence of gameplay. The
                # corresponding on-disk server source must include executable
                # mutation, checked independently below. An empty marker
                # list avoids certifying any custom behavior from boilerplate.
                units.append(_unit("custom." + facet_id, owners[0], [],
                                   "execute requested " + facet_id,
                                   str(observable).strip()[:300]))
    graph = [
        {"from": "entry", "to": "interaction", "trigger": "player ready"},
        {"from": "interaction", "to": "feedback", "trigger": "action accepted or rejected"},
        {"from": "feedback", "to": "outcome", "trigger": "state change evaluated"},
        {"from": "outcome", "to": "reentry", "trigger": "result delivered"},
        {"from": "reentry", "to": "interaction", "trigger": "repeat or next session"},
    ]
    exceptions = (["insufficient_opponents", "opponent_left",
                   "draw_or_timeout", "server_validation_reject"]
                  if round_mode else
                  ["invalid_input", "missing_state", "rejected_action"])
    finite_requested = any(x in proposal.requested_prompt.lower() for x in FINITE_CUES)
    # A finite narrative ending for an unknown genre requires authored model
    # coverage. Repetitive stock mechanics cannot silently count as that end.
    finite_covered = not finite_requested or (
        mode == "stage" or any(
            word in str(row).lower()
            for row in (dynamic.get("acceptance") or {}).values()
            for word in FINITE_CUES
        )
    )
    return {
        "schema": SCHEMA, "mode": mode,
        "completion_kind": ending,
        "objective": ("Complete matches and play again" if round_mode else
                      "Reach the last requested checkpoint" if mode == "stage" else
                      "Complete the requested addon interaction without replacing its host" if addon else
                      "Produce observable progress through requested activities"),
        "reentry": "next round" if round_mode else "restart or continue activity",
        "graph": graph,
        "units": units,
        "exceptions": exceptions,
        "finite_ending_requested": finite_requested,
        "finite_ending_covered": finite_covered,
        "evidence_scope": "static_source_only",
        "engine_playtested": False,
    }


def validate_gameplay_contract(proposal: Any, project_root: Path) -> list[dict]:
    """Fail missing state transitions, source owners and observable outcomes.

    This is deliberately stricter than an architectural document: each unit
    must exist in the *on-disk* script shipped to Rojo.
    """
    contract = proposal.game_design.get("gameplay_contract")
    checks: list[dict] = []
    def check(key: str, passed: bool, reason: str) -> None:
        checks.append({"id": "lifecycle." + key, "passed": bool(passed),
                       "detail": reason})
    check("present", isinstance(contract, dict) and contract.get("schema") == SCHEMA,
          "Host-created lifecycle contract exists on authored proposal")
    if not isinstance(contract, dict) or contract.get("schema") != SCHEMA:
        return checks
    expected = build_gameplay_contract(proposal)
    # Old/stale saved plans may not change the lifecycle mode or owners silently.
    check("binding", contract == expected,
          "Contract matches current request, module owners and scoped plan")
    graph = contract.get("graph", [])
    links = {}
    for entry in graph:
        if not isinstance(entry, dict):
            continue
        if entry.get("from") in CYCLE and entry.get("to") in CYCLE and entry.get("trigger"):
            links.setdefault(entry["from"], []).append(entry["to"])
    visited = {"entry"}
    q = deque(["entry"])
    while q:
        for nxt in links.get(q.popleft(), []):
            if nxt not in visited:
                visited.add(nxt)
                q.append(nxt)
    check("reachable", set(CYCLE) <= visited and
          "interaction" in links.get("reentry", []),
          "Start, action, feedback, outcome, replay are reachable and connected")
    check("outcome", bool(contract.get("completion_kind"))
          and bool(contract.get("reentry")) and bool(contract.get("objective"))
          and bool(contract.get("exceptions")),
          "Goal, session outcome, replay and edge cases explicitly designed")
    check("finite", bool(contract.get("finite_ending_covered")),
          "Finite ending requested by user must be supported by authored design")
    modules = {m.name: m for m in proposal.modules}
    units = contract.get("units", [])
    check("actions", bool(units) and all(
        isinstance(u.get("observable"), str) and u["observable"].strip() and
        isinstance(u.get("action"), str) and u["action"].strip()
        for u in units if isinstance(u, dict)),
        "Actions have source ownership and observable outcomes")
    for unit in units:
        if not isinstance(unit, dict):
            continue
        owner = modules.get(unit.get("owner"))
        source = (Path(project_root) / owner.file_path) if owner else None
        try:
            code = source.read_text(encoding="utf-8") if source else ""
        except OSError:
            code = ""
        # Do not certify a dynamic server action merely because its module
        # exists and begins with --!strict. Only actual executable code
        # exhibiting a plausible authoritative mutation is even a candidate
        # for source-level coverage; semantic/playtest proof is still separate.
        source_ok = bool(code) and bool(owner) and all(
            token in code for token in unit.get("source_markers", []))
        if str(unit.get("id") or "").startswith("custom."):
            from .dynamic_wiring import _mask_strings, _without_comments
            from .host_service_codegen import _EFFECT
            executable = _mask_strings(_without_comments(code))
            source_ok = (
                source_ok
                and bool(owner.file_path.startswith("src/server/"))
                and bool(_EFFECT.search(executable))
            )
        check("source." + unit.get("id", "unknown"), source_ok,
              "Actual packaged source supplies executable server mutation "
              "candidate for " + str(unit.get("observable")) +
              "; static evidence is not a Roblox engine playtest")
    if contract.get("mode") == "round":
        check("round_modules",
              "ArenaRoundService" in modules and "RoundController" in modules,
              "A round-based arena needs an authoritative scheduler and result UI")
    if contract.get("mode") == "stage":
        check("stage_modules", "ObbyService" in modules and "ObbyController" in modules,
              "Stage completion must be delivered to the player")
    check("engine_unverified", contract.get("engine_playtested") is False,
          "Static contract must never assert a Roblox Studio playtest happened")
    return checks


def make_studio_playtest_scenarios(contract: dict[str, Any]) -> dict[str, Any]:
    """Generate executable-intent scenarios for a local Studio MCP tester.

    These are instructions and expected outcomes, NOT evidence they passed.
    The local tester must collect its own actual run data before certification.
    """
    mode = contract.get("mode")
    scenarios: list[dict[str, Any]] = []
    for unit in contract.get("units", []):
        scenarios.append({
            "id": "interaction." + unit["id"],
            "setup": "Open the generated .rbxlx in Roblox Studio Play mode",
            "action": unit["action"],
            "expect": unit["observable"],
            "executed": False,
        })
    if mode == "round":
        scenarios += [
            {"id": "round.solo", "setup": "Only one test client connected",
             "action": "Wait for game to start",
             "expect": "Waiting state; no false victory and no damage before round start",
             "executed": False},
            {"id": "round.win", "setup": "Two test clients in the active round",
             "action": "Defeat the other contestant with a valid attack",
             "expect": "Server selects the last survivor, displays result and pays 100 coins",
             "executed": False},
            {"id": "round.disconnect", "setup": "Two contestants in an active round",
             "action": "Disconnect one contestant",
             "expect": "Disconnected player is ineligible; survivor wins",
             "executed": False},
            {"id": "round.draw", "setup": "Two contestants remain alive",
             "action": "Let the match timer expire",
             "expect": "Draw announced and no winner reward granted",
             "executed": False},
            {"id": "round.replay", "setup": "One completed match",
             "action": "Remain connected through intermission",
             "expect": "Characters reset, state returns to waiting or countdown, another round starts",
             "executed": False},
        ]
    elif mode == "stage":
        scenarios += [
            {"id": "stage.finish", "setup": "Start at first checkpoint",
             "action": "Visit each checkpoint in order and touch final platform",
             "expect": "Server marks ObbyComplete and client displays completion",
             "executed": False},
            {"id": "stage.respawn", "setup": "Reach a checkpoint, then touch lava",
             "action": "Respawn",
             "expect": "Player returns to the most recent saved checkpoint",
             "executed": False},
        ]
    elif mode == "addon":
        scenarios.append({
            "id": "addon.non_destructive",
            "setup": "Owner opens an existing experience copy",
            "action": "Install only the requested addon",
            "expect": "Host world, saved player data and existing scripts stay intact",
            "executed": False,
        })
    scenarios.append({
        "id": "invalid-input", "setup": "Use a client with an invalid purchase or action",
        "action": "Attempt an invalid, duplicate or unauthorized request",
        "expect": "Server rejects it without granting unearned value",
        "executed": False,
    })
    return {
        "schema": "rmm/studio-playtest-scenarios-v1",
        "mode": mode,
        "verification": "not_run",
        "note": "Descriptions of required local Roblox Studio scenarios, not passed tests",
        "scenarios": scenarios,
    }
