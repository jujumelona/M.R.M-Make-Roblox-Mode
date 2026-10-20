"""Host-owned Luau service shell; the small model writes only gameplay statements.

A full ModuleScript is the wrong generation unit for a small coder: the host
already knows service ABI, lifecycle and routing. Never fill in a failed model
snippet with a fake successful implementation.
"""
from __future__ import annotations

import re
from typing import Any

from .code_output_guard import LiveCodeRepetitionGuard
from .luau_api_sanity import invalid_luau_apis
from .luau_service_contract import service_contract_checks
from .request_semantics import request_semantic_errors
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


_FORBIDDEN = re.compile(
    r"\b(?:function\s+Service\.|OnServerEvent|OnServerInvoke|"
    r"FireServer|DataStoreService|loadstring|setfenv|getfenv|"
    r"InsertService|HttpService|LocalPlayer)\b|"
    r"\brequire\s*\(\s*\d{5,}\s*\)|"
    r"\b(?:TODO|FIXME|placeholder|not implemented)\b", re.I,
)
_EFFECT = re.compile(
    r"\b(?:TrySpend|Grant|SetAttribute|PivotTo|Teleport|"
    r"TakeDamage|Create|Destroy|AddItem|RemoveItem|SetPrimaryPartCFrame|"
    r"FireClient|FireAllClients|ApplyImpulse|LoadCharacter)\s*\(|"
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]]+\])\s*(?:\+=|-=|=(?!=))|"
    r"\bInstance\.new\s*\(", re.I,
)


def _clean_body(raw: str) -> str:
    body = (raw or "").strip()
    fenced = re.search(r"```(?:luau|lua)?\s*([\s\S]*?)\s*```", body, re.I)
    if fenced:
        body = fenced.group(1).strip()
    return body


def _shell(body: str) -> str:
    return (
        "--!strict\n"
        "-- Host-authored lifecycle, input validation and exported ABI.\n"
        "local Players = game:GetService(\"Players\")\n"
        "local Service = {}\n"
        "function Service.start(services)\n"
        "    assert(type(services) == \"table\", \"Missing service registry\")\n"
        "    Service._services = services\n"
        "end\n"
        "function Service.handleAction(player, services, ...)\n"
        "    if typeof(player) ~= \"Instance\" or not player:IsA(\"Player\") then return false end\n"
        "    if player.Parent ~= Players then return false end\n"
        + "\n".join("    " + line for line in body.splitlines()) + "\n"
        "end\n"
        "return Service\n"
    )


def try_scaffolded_server(
    module: RobloxModuleSpec, proposal: RobloxProposal,
    router: Any, analyzer: Any,
) -> str | None:
    """Attempt a small, server-authoritative action BODY, never fake a fallback.

    Applicable only to one genuinely host-routed dynamic server service.
    Without a route, no model-authored handleAction could be reached.
    """
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.SERVER_MODULE
            or not module.file_path.startswith("src/server/")):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    actions = {
        k: v for k, v in (design.get("host_actions") or {}).items()
        if isinstance(v, dict) and v.get("service") == module.name
    }
    world = {
        k: v for k, v in (design.get("host_world_actions") or {}).items()
        if isinstance(v, dict) and v.get("service") == module.name
    }
    if len(actions) + len(world) != 1:
        return None
    kind = "world" if world else "remote"
    route = next(iter(world or actions))
    route_info = (world or actions)[route]
    if kind == "world":
        input_contract = (
            "The host calls handleAction(player, services, targetPart). "
            "Your BODY receives targetPart as the first vararg. "
            "Use local targetPart = ... and validate the target's game permissions."
        )
    else:
        input_contract = (
            "The host calls handleAction(player, services, ...) with EXACTLY the "
            "client-supplied Remote arguments. It does NOT prepend actionName. "
            "Use local arg = ... only if this game action has a client argument. "
            + ("This host action takes ZERO arguments; do not expect any payload."
               if route_info.get("max_args") == 0 else
               "Validate every client argument against server-owned data.")
        )
    prompt = (
        "Write ONLY the BODY statements of one Roblox Luau server "
        "Service.handleAction(player, services, ...). "
        "No function header, no final function end, no return Service, "
        "no Markdown, no comments, no type annotations. "
        "Real gameplay is required, not TODO or return true. "
        "The host supplies a local Players service, Service.start(), "
        "the Service table, player identity checking, Remote/ProximityPrompt "
        "wiring and return Service. Never duplicate them. "
        "Server state and prices must come from trusted server data, never "
        "client-supplied balances or amounts. Do not invent methods on "
        "other services. If player profile state is required, the known host API "
        "is services.PlayerDataManager.GetState(player, namespace) and it "
        "returns a mutable server-owned table or nil until ready. "
        "Keep the body short, syntactically complete, and scoped to ONE action.\n"
        + "Module: " + module.name + "\n"
        + "Game-specific behavior: " + module.description[:950] + "\n"
        + "Route: " + route + " (" + kind + ")\n"
        + input_contract + "\n"
        + "Return false for rejected requests; perform observable game state "
        "changes for valid requests. Use actual Roblox APIs only."
    )
    attempts = []
    for attempt in range(2):
        try:
            raw = router.complete(
                prompt + (
                    "\nPrevious attempt was invalid; output only concise "
                    "body statements with balanced Lua blocks."
                    if attempt else ""
                ),
                role="coder", temperature=0.1, max_tokens=2000,
                system_prompt="Roblox Luau coding assistant. Output function body only.",
            )
            body = _clean_body(raw)
            if not body or len(body) < 60:
                raise ValueError("Empty or trivially short gameplay body")
            if body.startswith("--!strict") or _FORBIDDEN.search(body):
                raise ValueError("Body contains host-owned, unsafe or placeholder code")
            if not _EFFECT.search(body):
                raise ValueError("Body lacks observable server-owned state change")
            LiveCodeRepetitionGuard.inspect(body)
            candidate = _shell(body)
            diagnostics = [
                f"{d.rule} {d.file_path}:{d.line_number}: {d.message}"
                for d in analyzer.analyze_source(candidate, module.file_path)
                if d.severity == "ERROR"
            ]
            diagnostics.extend(
                c["detail"] for c in service_contract_checks(
                    module.name, candidate, require_start=True, needs_action=True
                ) if not c["passed"]
            )
            diagnostics.extend("ROBLOX_API_INVALID: " + m
                               for m in invalid_luau_apis(candidate))
            diagnostics.extend(request_semantic_errors(
                candidate, proposal.requested_prompt))
            if diagnostics:
                raise ValueError("; ".join(diagnostics[:6]))
            router.last_scaffold_attempts = attempts
            return candidate
        except Exception as exc:
            attempts.append({
                "attempt": attempt + 1,
                "mode": "host_scaffolded_action_body",
                "module": module.name,
                "diagnostics": [type(exc).__name__ + ": " + str(exc)[:1800]],
                "model_runtime": getattr(router, "last_generation_report", {}),
                "candidate": (locals().get("body") or "")[:10000],
            })
    router.last_scaffold_attempts = attempts
    return None
