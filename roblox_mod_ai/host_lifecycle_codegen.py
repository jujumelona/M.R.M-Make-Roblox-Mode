"""Small bounded model body for passive Roblox server lifecycle.

When the plan deliberately has NO player ingress, host still owns start(),
service registry, ModuleScript return, and all Roblox bootstrap operations.
The model only authors short initialization statements. We never fabricate
gameplay behavior or silently replace a failed body with a no-op.
"""
from __future__ import annotations

import re
from typing import Any

from .code_output_guard import LiveCodeRepetitionGuard
from .host_service_codegen import _clean_body, _EFFECT
from .luau_api_sanity import invalid_luau_apis
from .luau_service_contract import service_contract_checks
from .spec import RobloxModuleSpec, RobloxProposal

_FORBIDDEN = re.compile(
    r"\b(?:function\s+Service\b|function\s+Service\.|return\s+Service\b|"
    r"OnServerEvent|OnServerInvoke|FireServer|InvokeServer|LocalPlayer|"
    r"DataStoreService|InsertService|HttpService|loadstring|setfenv|getfenv)\b|"
    r"\b(?:TODO|FIXME|placeholder|not implemented)\b", re.I,
)


def _passive_shell(body: str) -> str:
    return (
        '--!strict\n'
        '-- Host-owned passive service lifecycle and registry. No player action.\n'
        'local Service = {}\n'
        'function Service.start(services)\n'
        '    assert(type(services) == "table", "Missing service registry")\n'
        + "\n".join("    " + row for row in body.splitlines()) + "\n"
        'end\n'
        'return Service\n'
    )


def try_scaffolded_lifecycle(
    module: RobloxModuleSpec, proposal: RobloxProposal,
    router: Any, analyzer: Any,
) -> str | None:
    from .scaffold_policy import single_passive_service
    if not single_passive_service(proposal, module):
        return None
    prompt = (
        "Write ONLY short Roblox Luau startup STATEMENTS inside an existing "
        "function Service.start(services). Host already declares local Service={}, "
        "checks the service registry, and returns Service. Do not write functions "
        "or Remote handlers, no module return, no Markdown, no TODO, no fake "
        "success. Passive startup must perform real scene/setup/automatic behavior. "
        "Never grant player inventory, money, or launch rights in startup. "
        "Only use real Roblox APIs. Max 30 lines. Example of format: "
        "local part = Instance.new('Part'); part.Anchored = true; "
        "part.Parent = workspace. Use no typed annotations.\n"
        "Mechanic: " + module.description[:1100] + "\n"
        "Owned request: " + proposal.requested_prompt[:350]
    )
    attempts: list[dict[str, Any]] = []
    for attempt in range(3):
        if attempt == 2 and not hasattr(router, "complete_json"):
            break
        body = ""
        try:
            if attempt:
                query = (
                    prompt + "\nLast body failed; rewrite only initializations. "
                    + "; ".join(attempts[-1]["diagnostics"])[:550]
                )
            else:
                query = prompt
            if attempt == 2:
                recovered = router.complete_json(
                    query + "\nReturn JSON {body:string} with ONLY short "
                    "Luau initialization statements.",
                    role="coder", temperature=0.0, max_tokens=1000,
                    json_schema={
                        "type": "object", "properties": {"body": {"type": "string"}},
                        "required": ["body"],
                    },
                )
                response = recovered.get("body", "") if isinstance(recovered, dict) else ""
            else:
                response = router.complete(
                    query, role="coder", temperature=0.0, max_tokens=1200,
                    system_prompt="Luau startup statements only. Platform shell is prebuilt.",
                )
            body = _clean_body(response)
            if (not 60 <= len(body) <= 4500 or body.startswith("--!strict")
                    or _FORBIDDEN.search(body) or not _EFFECT.search(body)):
                raise ValueError(
                    "Passive startup needs real bounded world/state behavior, "
                    "no Service/Remote boilerplate or empty stub"
                )
            LiveCodeRepetitionGuard.inspect(body)
            source = _passive_shell(body)
            errors = [
                f"{d.rule} {d.file_path}:{d.line_number}: {d.message}"
                for d in analyzer.analyze_source(source, module.file_path)
                if d.severity == "ERROR"
            ]
            errors.extend(
                c["detail"] for c in service_contract_checks(
                    module.name, source, require_start=True, needs_action=False
                ) if not c["passed"]
            )
            errors.extend(invalid_luau_apis(source))
            if errors:
                raise ValueError("; ".join(errors[:5]))
            router.last_lifecycle_scaffold_attempts = attempts
            return source
        except Exception as exc:
            attempts.append({
                "attempt": attempt + 1, "module": module.name,
                "mode": ("host_scaffolded_passive_json_start"
                         if attempt == 2 else "host_scaffolded_passive_start"),
                "diagnostics": [type(exc).__name__ + ": " + str(exc)[:1200]],
                "candidate": body[:4500],
            })
    router.last_lifecycle_scaffold_attempts = attempts
    return None
