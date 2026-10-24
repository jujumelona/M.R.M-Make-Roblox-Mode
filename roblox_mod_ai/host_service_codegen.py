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
from .dynamic_wiring import _mask_strings, _without_comments
from .host_mining import render_host_mining
from .host_ship_attachment import eligible_ship_attachment
from .host_capped_ship_parts import eligible_capped_ship_parts
from .luau_api_sanity import invalid_luau_apis
from .roblox_value_contract import roblox_value_contract_errors
from .luau_service_contract import service_contract_checks
from .server_interface_audit import dependency_api_errors
from .scoped_luau_abi import (
    host_abi_guidance, normalize_trusted_player_aliases,
    typed_input_abi_errors, typed_input_fields_used,
    remove_redundant_state_commit, normalize_verified_peer_abi,
)
from .request_semantics import request_semantic_errors
from .world_motion_contract import vehicle_motion_code_errors
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal
from .typed_action_contract import (
    lua_server_guard, validate_contract, TypedActionContractError,
)


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
    r"ApplyImpulse|LoadCharacter)\s*\(|"
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]]+\])\s*(?:\+=|-=|=(?!=))", re.I,
)


def scoped_body_completion_budget(attempt: int, previous: dict[str, Any] | None) -> int:
    """Escalate ONLY after a recorded truncated completion, never by genre."""
    if not previous:
        return 1200
    runtime = previous.get("model_runtime") or {}
    truncated = bool(runtime.get("finish_reason") == "length" or any(
        "finish_reason=length" in str(error)
        for error in previous.get("diagnostics", [])
    ))
    return (1800 if attempt == 1 else 2600) if truncated else 1200


def _clean_body(raw: str) -> str:
    body = (raw or "").strip()
    fenced = re.search(r"```(?:luau|lua)?\s*([\s\S]*?)\s*```", body, re.I)
    if fenced:
        body = fenced.group(1).strip()
    return body



# Reject leaked chat/tool delimiters as data corruption, not as Luau that can
# be repaired by guessing missing 'end' tokens.
_MODEL_PROTOCOL = re.compile(
    r"</?(?:parameter|tool_call|function)(?:[=>\s]|>)|"
    r"<\s*function\s*=",
    re.I,
)
_SHADOW_HOST_PLAYER = re.compile(
    r"\blocal\s+(?:player|services)\s*(?::\s*\w+)?\s*=", re.I,
)
_UNBOUND_DATA_MANAGER = re.compile(
    r"(?<![\w.])PlayerDataManager\s*[.:]\s*GetState\s*\(",
    re.I,
)


def normalize_verified_server_body(body: str, proposal: RobloxProposal) -> str:
    """Make only an ABI-proven, semantics-preserving dot/colon correction.

    A server method exported as '.', unlike ':', receives no implicit self.
    Only the exact known PlayerDataManager.GetState peer is normalized;
    arbitrary invented methods and unknown peer ABIs still fail validation.
    """
    body = normalize_trusted_player_aliases(body)
    body = normalize_verified_peer_abi(body, proposal)
    if _MODEL_PROTOCOL.search(body):
        raise ValueError(
            "MODEL_PROTOCOL_CONTAMINATION: coder returned tool-call or chat "
            "markup instead of isolated Luau statements"
        )
    executable = _mask_strings(_without_comments(body))
    if _SHADOW_HOST_PLAYER.search(executable):
        raise ValueError(
            "HOST_IDENTITY_SHADOWED: use the trusted player and services "
            "parameters, never redeclare them from client args"
        )
    if _UNBOUND_DATA_MANAGER.search(executable):
        raise ValueError(
            "DEPENDENCY_API_UNBOUND: access GetState only through "
            "services.PlayerDataManager.GetState(player, namespace)"
        )
    from .luau_service_contract import exported_methods
    peer = next(
        (module for module in getattr(proposal, "modules", [])
         if module.name == "PlayerDataManager"
         and module.file_path.startswith("src/server/")
         and module.code), None
    )
    if peer is None:
        return body
    methods = exported_methods(peer.code)[1]
    method = methods.get("GetState")
    if not isinstance(method, dict) or method.get("separator") != ".":
        return body
    # A trusted module's exported ABI, not guessed functionality, proves this
    # repair. Mask comments/strings so literal messages are never modified.
    wrong = re.compile(
        r"\bservices\s*\.\s*PlayerDataManager\s*:\s*GetState\s*\("
    )
    masked = _mask_strings(_without_comments(body))
    matches = [
        match for match in wrong.finditer(body)
        if masked[match.start():match.start()+8] == "services"
    ]
    for match in reversed(matches):
        body = (
            body[:match.start()] +
            "services.PlayerDataManager.GetState(" +
            body[match.end():]
        )
    if "SetState" not in methods:
        body = remove_redundant_state_commit(body)
    return body


def _shell(
    body: str, allowed_choices: list[str] | None = None,
    *, typed_contract: dict[str, Any] | None = None,
    world_name: str | None = None,
) -> str:
    choice_guard = (
        lua_server_guard(typed_contract, world_name=world_name)
        if typed_contract is not None else
        '    local args = {...}\n'
    )
    if allowed_choices:
        entries = ", ".join("[" + json.dumps(x) + "] = true" for x in allowed_choices)
        choice_guard = (
            '    if select("#", ...) ~= 1 then return false end\n'
            '    local __rmmActionId = ...\n'
            '    local actionId = __rmmActionId\n'
            '    local __rmmAllowed = {' + entries + '}\n'
            '    if type(__rmmActionId) ~= "string" or not __rmmAllowed[__rmmActionId] then return false end\n'
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
        + "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        + "\n".join("    " + line for line in body.splitlines()) + "\n"
        + "    -- RMM_GAMEPLAY_BODY_END\n"
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
    motion_spec = (design.get("host_world_motion") or {}).get(module.name)
    route = next(iter(world or actions))
    route_info = (world or actions)[route]
    choices = ((design.get("host_action_choices") or {}).get(route)
               if kind == "remote" else None)
    typed_spec = ((design.get("host_typed_actions") or {}).get(route)
                  if kind == "remote" else None)
    typed = None
    if typed_spec is not None:
        if (not isinstance(typed_spec, dict)
                or typed_spec.get("server") != module.name
                or route_info.get("max_args") != 1
                or choices is not None):
            return None
        try:
            typed = validate_contract(
                typed_spec.get("contract"),
                world_entities=typed_spec.get("world_entities", []),
                transport_only=typed_spec.get("transport_only") is True,
            )
            if typed["target"]["kind"] == "world_entity" and not isinstance(
                    typed_spec.get("world_name"), str):
                return None
        except TypedActionContractError:
            return None
    if choices is not None and (
            not isinstance(choices, list) or not choices
            or any(not isinstance(x, dict)
                   or not isinstance(x.get("id"), str)
                   or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", x["id"])
                   for x in choices)):
        return None
    if typed is not None:
        input_contract = (
            "The HOST validates ONE table payload and exposes local "
            "actionArgs with named, typed fields; the host also defines "
            "local args = actionArgs as an exact ALIAS, so use args.selection "
            "or actionArgs.selection, NEVER args[1]/args[2]. "
            "The shell rejects "
            "missing, unknown, out-of-range or forged fields BEFORE "
            "your body runs. Use ONLY the EXACT field IDs listed below "
            "for required user parameters (never invent fieldId), and "
            "still verify ownership, available "
            "balances and real server-side game conditions. " +
            ("This is a HOST STANDARD INPUT TRANSPORT, not a game "
             "state effect specification. Input selection is a user-provided "
             "item/choice/target ID; quantity is a requested integer (NOT "
             "a reward or authorized price). Interpret fields only when "
             "needed for the actual game action. Implement real game-side "
             "state mutations described by the module behavior; never "
             "invent state variables or claim a successful action without "
             "an observable server-authoritative mutation. "
             if typed_spec and typed_spec.get("transport_only") is True else
             "The required state changes are declarations, not proof "
             "of implementation. Reference EVERY EXACT declared state field "
             "name in the server code, perform its real mutation, and do not "
             "substitute an unrelated field or other game action. "
             "Implement the actual transitions: " +
             json.dumps(typed["state_changes"], ensure_ascii=False) + ". ") +
            ("The host validates one world target and exposes "
             "local actionTarget; mutate only the authorized object. "
             if typed["target"]["kind"] == "world_entity" else "") +
            "Never trust client-provided cost or rewards."
        )
    elif kind == "world":
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
    from .luau_service_contract import exported_methods
    peer_methods = {
        peer.name: sorted(exported_methods(peer.code)[1])
        for peer in getattr(proposal, "modules", [])
        if peer.name != module.name and peer.file_path.startswith("src/server/")
        and peer.code and peer.file_path.endswith(".luau")
        and not peer.file_path.endswith(".server.luau")
    }
    # Exact inspected module exports and immutable input keys, not guessed
    # service interfaces or prompt-specific cookbook snippets.
    compiled_abi = host_abi_guidance(typed, peer_methods)
    prompt = (
        compiled_abi +
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
        "GetState returns an initially EMPTY state table for a new namespace; "
        "do not reject valid users merely because a GroundMode or other "
        "starting value was never initialized. Use the trusted player "
        "parameter directly: args[1] is client input, NOT a Player. "
        "Do NOT redeclare local player or local services. "
        "Never output tool-call XML delimiters or control-plane text. "
        "PlayerDataManager has no SetState method; mutate only the loaded "
        "GetState table after server-side validation. Client-provided amounts "
        "are not earned rewards or authorized prices. "
        "Keep the body short, syntactically complete, and scoped to ONE action. "
        "Never destroy unrelated Workspace objects or PlayerGui. "
        "Luau tables cannot use + for array addition; use table.insert. "
        "Validate prerequisites before deducting currency or mutating state.\n"
        + shared_economy_abi
        + shared_assembly_abi
        + ("HOST-BOUND WORLD TRANSITION: " +
           json.dumps(motion_spec, ensure_ascii=False) +
           ". Move the actual owned craft Instance with Model:PivotTo or "
           "BasePart.CFrame/MoveTo, preserving its aboard players. Do not "
           "replace vehicle travel with a character-only teleport, mode "
           "flag, disembarkation or crew removal. Resolve real server-side "
           "instances and validate vehicle ownership first.\n"
           if motion_spec else "")
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
    use_json_body = bool(
        getattr(router, "supports_scoped_json_body", False)
        and hasattr(router, "complete_json")
    )
    for attempt in range(3):
        # The production coder always uses constrained JSON for a bounded
        # action body. Keep legacy plaintext only for explicit test routers.
        if attempt == 2 and not hasattr(router, "complete_json"):
            break
        body = ""
        try:
            previous = attempts[-1] if attempts else None
            overlength = scoped_body_completion_budget(attempt, previous) > 1200
            # Actual plan 77 returned 1200/1200 tokens three times and no
            # candidate bytes. Escalate the bounded BODY budget only after an
            # observed truncation; do not ask the same 9B model to repeat the
            # same impossible maximum length on every attempt.
            body_budget = scoped_body_completion_budget(attempt, previous)
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
            if use_json_body or attempt == 2:
                recovered = router.complete_json(
                    prompt + "\nOnly JSON {body:string} containing short action statements. "
                    "Do not output a whole module, function header or platform shell. "
                    "Use compact executable statements, ideally 20-60 lines, "
                    "not a 200-line tutorial or repeated prose. "
                    + ("The previous response ended before JSON closed; "
                       "finish the JSON response in the new output budget. "
                       if overlength else "")
                    + feedback[-650:],
                    role="coder", temperature=0.0, max_tokens=body_budget,
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
            # Reject leaked control-plane tokens in the entire response,
            # including text outside Markdown fences that _clean_body would
            # otherwise silently discard.
            if _MODEL_PROTOCOL.search(str(raw or "")):
                raise ValueError(
                    "MODEL_PROTOCOL_CONTAMINATION: unexpected tool markup "
                    "in the code-generation response"
                )
            body = _clean_body(raw)
            body = normalize_verified_server_body(body, proposal)
            input_errors = typed_input_abi_errors(body, typed)
            if input_errors:
                raise ValueError("; ".join(input_errors))
            if not body or len(body) < 60:
                raise ValueError("Empty or trivially short gameplay body")
            if body.startswith("--!strict") or _FORBIDDEN.search(body):
                raise ValueError("Body contains host-owned, unsafe or placeholder code")
            # Known destructive or unsupported operations are never acceptable gameplay.
            if "workspace.Workspace" in body:
                raise ValueError("Unsafe or unsupported Luau mutation")
            # Client notifications and unparented Instance.new() calls
            # change neither an authoritative player/world state nor a live
            # world object. They must never satisfy a real gameplay action.
            # Model prose/comments/strings are not executable game changes.
            # Reuse the same Luau-aware masking employed by Remote validation,
            # so a printed string containing SetAttribute(...) cannot certify
            # a gameplay effect.
            executable = _mask_strings(_without_comments(body))
            if not _EFFECT.search(executable):
                raise ValueError(
                    "Body lacks authoritative gameplay mutation; Remote "
                    "notifications, comments and unparented Instances are not effects")
            LiveCodeRepetitionGuard.inspect(body)
            if motion_spec is not None:
                motion_errors = vehicle_motion_code_errors(body)
                if motion_errors:
                    raise ValueError("; ".join(motion_errors))
            if typed is not None:
                # Declarative effects must be referenced in the concrete
                # Luau action, not merely repeated in planning metadata.
                # Runtime behavior still needs an actual Studio test.
                from .gameplay_source_evidence import state_key_used_by_executable_code
                missing_effect_keys = [
                    effect["key"] for effect in typed["state_changes"]
                    if not state_key_used_by_executable_code(body, effect["key"])
                ]
                if missing_effect_keys:
                    raise ValueError(
                        "Server code does not reference declared state keys: " +
                        ", ".join(missing_effect_keys))
                # lua_server_guard aliases 'local args = actionArgs'. Both
                # args.quantity and actionArgs["quantity"] are the SAME
                # validated named input; a string substring check wrongly
                # rejected correct Luau three times in production (plan 76).
                if typed["inputs"] and not typed_input_fields_used(body, typed):
                    raise ValueError(
                        "Typed server implementation ignores validated named "
                        "player inputs: " + ", ".join(
                            field["id"] for field in typed["inputs"]))
            candidate = _shell(
                body, [x["id"] for x in choices] if choices else None,
                typed_contract=typed,
                world_name=(typed_spec.get("world_name")
                            if typed_spec else None),
            )
            diagnostics = [
                f"{d.rule} {d.file_path}:{d.line_number}: {d.message}"
                for d in analyzer.analyze_source(candidate, module.file_path)
                if d.severity == "ERROR"
            ]
            # Luau syntax diagnostics, NOT a textual guess, authorize one
            # deterministic cleanup of a stray terminal function 'end' in
            # a body that the host already wraps in handleAction. Only keep
            # the shorter candidate when the real parser becomes error-free;
            # peer ABI, effect and security checks still run afterwards.
            if (diagnostics and any("unexpected token `end`" in err
                                    for err in diagnostics)
                    and re.search(r"\n\s*end\s*$", body)):
                trimmed = re.sub(r"\n\s*end\s*$", "", body)
                alternative = _shell(
                    trimmed,
                    [x["id"] for x in choices] if choices else None,
                    typed_contract=typed,
                    world_name=(typed_spec.get("world_name")
                                if typed_spec else None),
                )
                alt_errors = [
                    d for d in analyzer.analyze_source(
                        alternative, module.file_path)
                    if d.severity == "ERROR"
                ]
                if not alt_errors:
                    body, candidate, diagnostics = trimmed, alternative, []
            diagnostics.extend(
                c["detail"] for c in service_contract_checks(
                    module.name, candidate, require_start=True, needs_action=True
                ) if not c["passed"]
            )
            # The project-specific peer ABI must be checked at EVERY bounded
            # attempt, not only after the orchestrator has already exhausted
            # the scoped unit. Retry the short body with exact exported APIs.
            diagnostics.extend(dependency_api_errors(module, proposal, candidate))
            from .gameplay_effect_safety import game_effect_safety_errors
            diagnostics.extend(game_effect_safety_errors(
                candidate, routed_action=True))
            diagnostics.extend("ROBLOX_API_INVALID: " + m
                               for m in invalid_luau_apis(candidate))
            diagnostics.extend(roblox_value_contract_errors(candidate))
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
                         if use_json_body or attempt == 2
                         else "host_scaffolded_action_body"),
                "module": module.name,
                "diagnostics": [type(exc).__name__ + ": " + str(exc)[:1800]],
                "model_runtime": getattr(router, "last_generation_report", {}),
                "candidate": body[:10000],
            })
    router.last_scaffold_attempts = attempts
    return None
