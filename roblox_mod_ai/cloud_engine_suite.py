"""Plan-derived, genre-independent Roblox Open Cloud server-engine assertions.

The host compiles checks from the exact requested Place contract. It never
claims these checks simulate clients, player identity, real gameplay, or Studio.
All emitted Luau identifiers are encoded as literals, not model-authored code.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import RobloxProposal


def _lit(value: str) -> str:
    # Roblox Luau supports double-quoted JSON string escapes for ASCII names.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,120}", value):
        raise ValueError("Untrusted or non-Rojo instance identifier in engine contract")
    return json.dumps(value)


def engine_contract_checks(proposal: RobloxProposal) -> list[tuple[str, str]]:
    """Return stable evidence IDs and executable ASSERTIONS (not source guesses)."""
    checks: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(identifier: str, assertion: str) -> None:
        if identifier in seen:
            raise ValueError("Duplicate engine assertion: " + identifier)
        seen.add(identifier)
        checks.append((identifier, assertion))

    for module in proposal.modules:
        path = getattr(module, "file_path", "") or ""
        name = getattr(module, "name", "")
        kind = getattr(getattr(module, "kind", ""), "value", getattr(module, "kind", ""))
        folder = None
        expected = None
        if path.startswith("src/server/") and path.endswith(".luau"):
            folder = 'game:GetService("ServerScriptService")'
            expected = "Script" if path.endswith(".server.luau") else "ModuleScript"
        elif path.startswith("src/client/") and path.endswith(".luau"):
            folder = 'game:GetService("StarterPlayer").StarterPlayerScripts'
            expected = "LocalScript" if path.endswith(".client.luau") else "ModuleScript"
        elif path.startswith("src/shared/") and path.endswith(".luau"):
            folder = 'game:GetService("ReplicatedStorage"):WaitForChild("Shared",10)'
            expected = "ModuleScript"
        # Only validate actual Rojo-managed script paths, not external assets.
        if folder is None:
            continue
        filename = path.rsplit("/", 1)[-1].removesuffix(".luau").removesuffix(".client").removesuffix(".server")
        # Roblox determines script instance name from its filename. Verify both
        # the file-derived name and expected instance class in the REAL place.
        runtime_require = (
            '; local ok,value=pcall(require,item); '
            'assert(ok, "module failed to load in Roblox engine: "..tostring(value)); '
            'assert(type(value)=="table" or type(value)=="function", '
            '"server module exported no callable contract")'
            if kind == "server_module" and str(getattr(module, "module_id", "")).startswith("dyn_")
            else ""
        )
        add("module:" + path,
            f'local container={folder}; '
            f'local item=container and container:FindFirstChild({_lit(filename)}); '
            f'assert(item and item:IsA({_lit(expected)}), "missing or wrong script class")'
            + runtime_require)

    design = (proposal.game_design or {}).get("dynamic_design") or {}
    if not isinstance(design, dict):
        raise ValueError("Malformed dynamic design")
    remotes = design.get("remotes") or {}
    if not isinstance(remotes, dict):
        raise ValueError("Malformed Remote roster")
    for name, kind in sorted(remotes.items()):
        if kind not in ("RemoteEvent", "RemoteFunction"):
            raise ValueError("Unexpected Remote class")
        add("remote:" + name,
            'local f=game:GetService("ReplicatedStorage"):FindFirstChild("Remotes"); '
            f'local r=f and f:FindFirstChild({_lit(name)}); '
            f'assert(r and r:IsA({_lit(kind)}), "missing or wrong Remote")')

    actions = design.get("host_world_actions") or {}
    if not isinstance(actions, dict):
        raise ValueError("Malformed world interaction roster")
    for name in sorted(actions):
        add("interaction:" + str(name),
            f'local o=workspace:FindFirstChild({_lit(name)}); '
            'local prompt=o and o:FindFirstChild("RMMInteract"); '
            'assert(prompt and prompt:IsA("ProximityPrompt"), "missing world interaction"); '
            'assert(prompt.Enabled and prompt.MaxActivationDistance>0, '
            '"unusable interaction prompt")')

    objects = design.get("world_objects") or []
    if not isinstance(objects, list):
        raise ValueError("Malformed world roster")
    for obj in objects:
        if not isinstance(obj, dict):
            raise ValueError("Malformed world object")
        name, kind = obj.get("name"), obj.get("class")
        if kind not in ("Part", "MeshPart", "SpawnLocation", "Model", "Folder"):
            # Unknown generated classes are checked by Rojo structure verifier;
            # never make up a runtime property contract for them.
            continue
        add("world:" + str(name),
            f'local o=workspace:FindFirstChild({_lit(name)}); '
            f'assert(o and o:IsA({_lit(kind)}), "missing or wrong world instance"); '
            + ('assert(o.Size.X>0 and o.Size.Y>0 and o.Size.Z>0 '
               'and o.Size.X<1e7 and o.Size.Y<1e7 and o.Size.Z<1e7, '
               '"invalid physical dimensions"); '
               'assert(o.Position.X==o.Position.X and o.Position.Y==o.Position.Y '
               'and o.Position.Z==o.Position.Z,"non-finite position")'
               if kind in ("Part", "MeshPart", "SpawnLocation") else ""))
    # The test script itself must remain under the Open Cloud API script limit
    # and return explicit failure rather than silently truncating checks.
    if len(checks) > 1000:
        raise ValueError("Engine suite too large; split into bounded tasks")
    return checks


def make_engine_suite_script(proposal: RobloxProposal) -> str:
    checks = engine_contract_checks(proposal)
    lines = [
        "--!strict",
        "-- RMM Open Cloud real server DataModel contract (not Studio gameplay)",
        "local failures={}",
        "local verified=0",
        "local function check(id,fn)",
        "    local ok,err=pcall(fn)",
        '    if not ok then table.insert(failures,id..": "..tostring(err))',
        "    else verified+=1 end",
        "end",
        'task.wait(0.5) -- Give server bootstrap a chance to initialize.',
    ]
    for ident, assertion in checks:
        lines.append("check(" + json.dumps(ident, ensure_ascii=True) + ",function() "
                     + assertion + " end)")
    lines.extend([
        'if #failures>0 then error("RMM_ENGINE_ASSERTIONS_FAILED "'
        '..tostring(#failures).."/"..tostring(#failures+verified).."\\n"'
        '..table.concat(failures,"\\n")) end',
        'print("RMM_ENGINE_ASSERTIONS_PASSED "..tostring(verified))',
        "return true",
    ])
    script = "\n".join(lines) + "\n"
    if len(script.encode("utf-8")) > 250_000:
        raise ValueError("Engine assertion script exceeds safe upload size")
    return script
