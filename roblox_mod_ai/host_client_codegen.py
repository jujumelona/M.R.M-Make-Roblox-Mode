"""Host-owned Roblox client shell; the small model supplies only button controls.

Only apply when an accepted dynamic plan maps one client to one server-owned
RemoteFunction. For an empty/no-argument action the existing deterministic
host_client renderer remains the authority. No fabricated generic success.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .code_output_guard import LiveCodeRepetitionGuard
from .luau_api_sanity import invalid_luau_apis
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal

_FORBIDDEN = re.compile(
    r"\b(?:GetService|LocalPlayer|require|OnServerEvent|OnServerInvoke|"
    r"InvokeServer|FireServer|FireClient|RemoteFunction|RemoteEvent|"
    r"DataStoreService|ServerScriptService|ServerStorage|HttpService|"
    r"PlayerDataManager|Service|loadstring|setfenv|getfenv)\b|"
    r"\b(?:TODO|FIXME|placeholder|not implemented)\b|"
    r":(?:SetAttribute|Destroy|Kick|Teleport)\s*\(", re.I
)
_BUTTON = re.compile(r'Instance\.new\s*\(\s*["\x27]TextButton["\x27]\s*\)')
_HANDLER = re.compile(r'\.Activated\s*:\s*Connect\s*\(')
_REQUEST = re.compile(r'\brequest\s*\(\s*["\x27][^"\x27]{1,80}["\x27]\s*\)')


def _client_shell(body: str, remote: str, name: str) -> str:
    return (
        '--!strict\n'
        '-- The host owns Roblox services, Remote transport, and feedback.\n'
        'local Players = game:GetService("Players")\n'
        'local ReplicatedStorage = game:GetService("ReplicatedStorage")\n'
        'local player = Players.LocalPlayer\n'
        'local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild('
        + json.dumps(remote) + ')\n'
        'if not remote:IsA("RemoteFunction") then error("Remote kind mismatch") end\n'
        'local gui = Instance.new("ScreenGui")\n'
        'gui.Name = ' + json.dumps(name) + '\n'
        'gui.ResetOnSpawn = false\n'
        'gui.Parent = player:WaitForChild("PlayerGui")\n'
        'local panel = Instance.new("Frame")\n'
        'panel.Size = UDim2.fromOffset(245, 250)\n'
        'panel.Position = UDim2.new(1, -265, 0, 145)\n'
        'panel.Parent = gui\n'
        'local layout = Instance.new("UIListLayout")\n'
        'layout.Parent = panel\n'
        'local status = Instance.new("TextLabel")\n'
        'status.Size = UDim2.new(1, 0, 0, 35)\n'
        'status.Text = "Select an action"\n'
        'status.Parent = panel\n'
        'local busy = false\n'
        'local lastCall = 0\n'
        'local function request(actionId)\n'
        '    if busy or type(actionId) ~= "string" or #actionId > 80 then return end\n'
        '    if os.clock() - lastCall < 0.2 then return end\n'
        '    busy = true\n'
        '    lastCall = os.clock()\n'
        '    local ok, answer = pcall(function() return remote:InvokeServer(actionId) end)\n'
        '    busy = false\n'
        '    if ok and type(answer) == "table" and answer.success == true then\n'
        '        status.Text = "Confirmed"\n'
        '    elseif ok and answer == true then status.Text = "Confirmed"\n'
        '    else status.Text = "Server rejected the request" end\n'
        'end\n'
        '-- Model-authored controls; no Roblox platform or networking code.\n'
        + body + '\n'
    )


def try_scaffolded_client(
    module: RobloxModuleSpec, proposal: RobloxProposal,
    router: Any, analyzer: Any,
) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.CLIENT_SCRIPT
            or not module.file_path.startswith("src/client/")
            or not module.file_path.endswith(".client.luau")):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if not isinstance(linked, list) or len(linked) != 1:
        return None
    remote = linked[0]
    owner_route = (design.get("host_actions") or {}).get(remote)
    if (not isinstance(owner_route, dict)
            or owner_route.get("kind") != "RemoteFunction"
            or owner_route.get("max_args") == 0
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"):
        return None
    server_name = owner_route.get("service")
    server = next((peer for peer in proposal.modules
                   if peer.kind == ModuleKind.SERVER_MODULE
                   and peer.name == server_name), None)
    if (server is None or not isinstance(server_name, str)
            or module.name != server_name.removesuffix("Server") + "Client"):
        return None
    # New semantic plans supply explicit server-owned action IDs. Those can
    # produce the entire client UI deterministically, with ZERO model code.
    # Never let a 9B client invent an ID the server was not told about.
    declared = (design.get("host_action_choices") or {}).get(remote)
    if declared is not None:
        if (not isinstance(declared, list) or not declared
                or any(not isinstance(choice, dict)
                       or not isinstance(choice.get("id"), str)
                       or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", choice["id"])
                       or not isinstance(choice.get("label"), str)
                       or not choice["label"].strip()
                       for choice in declared)
                or len({x["id"] for x in declared}) != len(declared)):
            return None
        lines = []
        for choice in declared:
            lines += [
                "do",
                '    local button = Instance.new("TextButton")',
                "    button.Name = " + json.dumps(choice["id"]),
                "    button.Text = " + json.dumps(choice["label"], ensure_ascii=False),
                "    button.Size = UDim2.new(1, 0, 0, 40)",
                "    button.Parent = panel",
                "    button.Activated:Connect(function()",
                "        request(" + json.dumps(choice["id"]) + ")",
                "    end)",
                "end",
            ]
        source = _client_shell("\n".join(lines), remote, module.name)
        if any(d.severity == "ERROR" for d in analyzer.analyze_source(
                source, module.file_path)):
            return None
        return source
    prompt = (
        "Write ONLY 1-3 Roblox Luau TextButton controls inside an EXISTING "
        "panel. Available identifiers are panel, status, request(actionId). "
        "Create buttons with Instance.new('TextButton'), set Parent = panel "
        "and Text, and bind .Activated:Connect(function() request('actionId') end). "
        "Write maximum 25 short lines, no Markdown, no Service functions, "
        "GetService, networking, require, local currency, data storage, "
        "data modification, custom helpers or type annotations. "
        "Send only stable user-selectable action identifiers; the server "
        "validates ownership, prices, inventory and effects. "
        "Never display success before the server confirms it.\n"
        "Client: " + module.description[:700] + "\n"
        "Server behavior: " + server.description[:850] + "\n"
        "Remote contract: " + remote
    )
    attempts = []
    for attempt in range(3):
        if attempt == 2 and not hasattr(router, "complete_json"):
            break
        body = ""
        try:
            retry_prompt = (
                prompt if not attempt else
                prompt + "\nPrevious control body was rejected: " +
                "; ".join(attempts[-1]["diagnostics"])[:400] +
                "\nGenerate clean UI statements only."
            )
            if attempt == 2:
                recovered = router.complete_json(
                    retry_prompt + "\nReturn JSON {body:string}, with ONLY button statements.",
                    role="coder", temperature=0.0, max_tokens=750,
                    json_schema={"type": "object",
                                 "properties": {"body": {"type": "string"}},
                                 "required": ["body"]},
                )
                raw = recovered.get("body", "") if isinstance(recovered, dict) else ""
            else:
                raw = router.complete(
                    retry_prompt,
                    role="coder", temperature=0.0, max_tokens=850,
                    system_prompt="Luau statements for UI controls only; no platform wiring.",
                )
            body = (raw or "").strip()
            fenced = re.search(r"\x60\x60\x60(?:lua|luau)?\s*([\s\S]*?)\x60\x60\x60", body, re.I)
            if fenced:
                body = fenced.group(1).strip()
            if (not 65 <= len(body) <= 3500
                    or _FORBIDDEN.search(body)
                    or not (_BUTTON.search(body) and _HANDLER.search(body)
                            and _REQUEST.search(body))):
                raise ValueError("UI must create an actionable button using host request('id')")
            LiveCodeRepetitionGuard.inspect(body)
            output = _client_shell(body, remote, module.name)
            errors = [
                d.rule + ": " + d.message for d in
                analyzer.analyze_source(output, module.file_path)
                if d.severity == "ERROR"
            ]
            errors.extend(invalid_luau_apis(output))
            if errors:
                raise ValueError("; ".join(errors[:4]))
            router.last_client_scaffold_attempts = attempts
            return output
        except Exception as exc:
            attempts.append({
                "module": module.name, "attempt": attempt + 1,
                "mode": ("host_scaffolded_client_json_ui"
                         if attempt == 2 else "host_scaffolded_client_ui"),
                "candidate": body[:4500],
                "diagnostics": [type(exc).__name__ + ": " + str(exc)[:1500]],
            })
    router.last_client_scaffold_attempts = attempts
    return None
