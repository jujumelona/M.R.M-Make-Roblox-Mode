"""Host-owned Luau service shell; the small model writes only gameplay statements.

A full ModuleScript is the wrong generation unit for a small coder: the host
already knows service ABI, lifecycle and routing. Never fill in a failed model
snippet with a fake successful implementation.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .code_output_guard import LiveCodeRepetitionGuard
from .host_mining import render_host_mining
from .host_ship_attachment import eligible_ship_attachment
from .host_capped_ship_parts import eligible_capped_ship_parts
from .luau_api_sanity import invalid_luau_apis
from .luau_service_contract import service_contract_checks
from .server_interface_audit import dependency_api_errors
from .request_semantics import request_semantic_errors
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


_FORBIDDEN = re.compile(
    r"\b(?:function\s+Service\.|Service\.handleAction|OnServerEvent|OnServerInvoke|"
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


def _shell(body: str, allowed_choices: list[str] | None = None) -> str:
    choice_guard = '    local args = {...}\n'
    if allowed_choices:
        entries = ", ".join("[" + json.dumps(x) + "] = true" for x in allowed_choices)
        choice_guard = (
            '    if select("#", ...) ~= 1 then return false end\n'
            '    local actionId = ...\n'
            '    local __rmmAllowed = {' + entries + '}\n'
            '    if type(actionId) ~= "string" or not __rmmAllowed[actionId] then return false end\n'
            '    local args = {}\n'
        )
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
        + choice_guard
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
    choices = ((design.get("host_action_choices") or {}).get(route)
               if kind == "remote" else None)
    if choices is not None and (
            not isinstance(choices, list) or not choices
            or any(not isinstance(x, dict)
                   or not isinstance(x.get("id"), str)
                   or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", x["id"])
                   for x in choices)):
        return None
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
            "The host provides local args = {...}; use args[1] for the first client argument. Do not refer to an undeclared actionName. "
            + ("This host action takes ZERO arguments; do not expect any payload."
               if route_info.get("max_args") == 0 else
               "Validate every client argument against server-owned data.")
        )
    # A scoped short-model task must see the same concrete host economy ABI
    # as full-module generation. Otherwise it invents ExchangeLedger and
    # transaction methods that do not exist at runtime.
    host_mining_available = any(
        render_host_mining(peer, proposal) is not None
        for peer in getattr(proposal, "modules", [])
        if peer.kind == ModuleKind.SERVER_MODULE and peer.name != module.name
    )
    shared_economy_abi = (
        'Verified host ledger: services.PlayerDataManager.GetState(player, '
        '"RMMInventory").resources is an integer resource count; '
        'player.leaderstats.Coins.Value is earned server currency. '
        'For optional game-defined items read the server-owned '
        'RMMInventory.items table, never invent an item ID or give items '
        'without checking ownership. Do NOT call nonexistent trading '
        'methods or manufacture parallel credit balances.\\n'
        if host_mining_available else ""
    )
    # Expose the verified assembly ABI to later ship, crew, upgrade and
    # launch action bodies; never let them call imaginary service methods.
    resource_ship_assembly = any(
        eligible_ship_attachment(peer, proposal) is not None
        for peer in getattr(proposal, "modules", [])
        if peer.kind == ModuleKind.SERVER_MODULE and peer.name != module.name
    )
    capped_ship_assembly = any(
        eligible_capped_ship_parts(peer, proposal) is not None
        for peer in getattr(proposal, "modules", [])
        if peer.kind == ModuleKind.SERVER_MODULE and peer.name != module.name
    )
    shared_assembly_abi = (
        'Verified ship assembly: the authoritative persistent table is '
        'services.PlayerDataManager.GetState(player, "RMMShipSections").sections. '
        'Each installed part is keyed by its catalog ID with owned=true, level=1. '
        + (
            'For resource-built sections each record has a positive performance '
            'contribution. The host publishes player attribute '
            'RMMShipAssemblyPerformance as the total contribution. '
            if resource_ship_assembly else ''
        )
        + (
            'For capped coin-purchased parts each record has a fixed paid cost; '
            'the host publishes RMMShipPartCount and RMMShipPartTotalCost. '
            'These counts are NOT combat power. '
            if capped_ship_assembly else ''
        )
        + 'Never invent getAssembly, applyAttachment, GetShip, SaveShip or GetSection '
        'methods on sibling services. Reject absent ownership, bad amounts and '
        'unloaded profiles.\n'
        if resource_ship_assembly or capped_ship_assembly else ""
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
        "GetState is a DOT function, never call :GetState. "
        "PlayerDataManager has no SetState method; mutate only the loaded "
        "GetState table after server-side validation. Client-provided amounts "
        "are not earned rewards or authorized prices. "
        "Keep the body short, syntactically complete, and scoped to ONE action. "
        "Never destroy unrelated Workspace objects or PlayerGui. "
        "Luau tables cannot use + for array addition; use table.insert. "
        "Validate prerequisites before deducting currency or mutating state.\n"
        + shared_economy_abi
        + shared_assembly_abi
        + "Module: " + module.name + "\n"
        + "Game-specific behavior: " + module.description[:950] + "\n"
        + "Route: " + route + " (" + kind + ")\n"
        + input_contract + "\n"
        + ("Only these approved client action IDs are valid: "
           + ", ".join(x["id"] for x in choices) + ". "
           + "The host defines local actionId and local args = {}; branch by actionId without redeclaring it; "
           + "the host rejects any other client action.\n"
           if choices else "")
        + "Return false for rejected requests; perform observable game state "
        "changes for valid requests. Use actual Roblox APIs only."
    )
    attempts = []
    for attempt in range(3):
        # A third SHORT JSON-body response can recover malformed plaintext
        # without encoding an entire 6000-token ModuleScript as a JSON string.
        if attempt == 2 and not hasattr(router, "complete_json"):
            break
        body = ""
        try:
            previous = attempts[-1] if attempts else None
            feedback = (
                "\nLAST REJECTED BODY (NOT VALID CODE; DO NOT COPY):\n"
                + previous["candidate"][:1300]
                + "\nEXACT VALIDATOR ERRORS:\n"
                + "; ".join(previous["diagnostics"])[:1100]
                + "\nRewrite ONLY the game-action body from scratch. "
                "Do not include function declarations, Service methods, "
                "Remote event wiring, explanations, or final end."
                if previous else ""
            )
            if attempt == 2:
                recovered = router.complete_json(
                    prompt + "\nOnly JSON {body:string} containing short action statements. "
                    "Do not output a whole module, function header or platform shell. "
                    + feedback[-800:],
                    role="coder", temperature=0.0, max_tokens=1200,
                    json_schema={
                        "type": "object", "properties": {"body": {"type": "string"}},
                        "required": ["body"],
                    },
                )
                raw = recovered.get("body", "") if isinstance(recovered, dict) else ""
            else:
                raw = router.complete(
                    prompt + feedback,
                    role="coder", temperature=0.0, max_tokens=1500,
                    system_prompt="Roblox Luau coder. Output statements inside existing function only.",
                )
            body = _clean_body(raw)
            if not body or len(body) < 60:
                raise ValueError("Empty or trivially short gameplay body")
            if body.startswith("--!strict") or _FORBIDDEN.search(body):
                raise ValueError("Body contains host-owned, unsafe or placeholder code")
            # Known destructive or unsupported operations are never acceptable gameplay.
            if re.search(r'workspace\\s*\\.\\s*Workspace|PlayerDataManager\\s*[:.]\\s*SetState|Instance\\s*\\.\\s*new\\s*\\(\\s*["\\\']ScreenGlow|\\w+\\s*\\.\\s*\\w+\\s*=\\s*\\w+(?:\\.\\w+)*\\s*\\+\\s*\\{', body):
                raise ValueError("Unsafe or unsupported Luau mutation")
            if not _EFFECT.search(body):
                raise ValueError("Body lacks observable server-owned state change")
            LiveCodeRepetitionGuard.inspect(body)
            candidate = _shell(body, [x["id"] for x in choices] if choices else None)
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
            # The project-specific peer ABI must be checked at EVERY bounded
            # attempt, not only after the orchestrator has already exhausted
            # the scoped unit. Retry the short body with exact exported APIs.
            diagnostics.extend(dependency_api_errors(module, proposal, candidate))
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
                "mode": ("host_scaffolded_action_json_body"
                         if attempt == 2 else "host_scaffolded_action_body"),
                "module": module.name,
                "diagnostics": [type(exc).__name__ + ": " + str(exc)[:1800]],
                "model_runtime": getattr(router, "last_generation_report", {}),
                "candidate": body[:10000],
            })
    router.last_scaffold_attempts = attempts
    return None
