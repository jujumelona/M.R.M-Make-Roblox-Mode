"""Incremental code-generation gate: validate every saved module, not only full build.

A Luau parser can accept a script that calls an invented Roblox service or a
non-exported sibling API. Those faults previously survived as checkpoints and
were discovered only after the whole small-model generation queue completed.
The gate is deliberately per-module and checks the source actually written.
It does not certify Roblox Studio runtime behavior.
"""
from __future__ import annotations

import re
from typing import Any

from .dynamic_wiring import _mask_strings, _without_comments
from .luau_api_sanity import invalid_luau_apis
from .luau_service_contract import service_contract_checks
from .server_interface_audit import dependency_api_errors
from .gameplay_effect_safety import game_effect_safety_errors
from .roblox_value_contract import roblox_value_contract_errors
from .world_object_abi import world_lookup_guidance, world_lookup_errors
from .spec import ModuleKind, RobloxProposal


class ModuleGenerationContractError(ValueError):
    def __init__(self, module: str, errors: list[str]):
        self.module = module
        self.diagnostics = errors
        super().__init__(
            "MODULE_CONTRACT_INVALID " + module + ": " + "; ".join(errors[:9])
        )


def generated_module_errors(
    module: Any, proposal: RobloxProposal, code: str, analyzer: Any,
) -> list[str]:
    """Return actionable errors before checkpointing *this* module.

    Peer API references are verified against available real exports. Unbuilt
    peers cannot be guessed and will be verified again by the full source gate.
    """
    errors = [
        f"{d.rule} {d.file_path}:{d.line_number}: {d.message}"
        for d in analyzer.analyze_source(code, file_path=module.file_path)
        if d.severity == "ERROR"
    ]
    # Synthetic adapter/checkpoint tests and legacy free-form scripts can
    # use dyn_* IDs without an authored dynamic_design. No route/peer ABI was
    # declared for those examples. Production dynamic games must have one.
    if (not module.module_id.startswith("dyn_")
            or not proposal.game_design.get("dynamic_design")):
        return errors
    if not code.strip() or len(code) < 75:
        errors.append("EMPTY_DYNAMIC_MODULE: gameplay code is absent")
        return errors

    stripped = _without_comments(code)
    masked = _mask_strings(stripped)
    errors.extend("ROBLOX_API_INVALID: " + item for item in invalid_luau_apis(code))
    errors.extend(roblox_value_contract_errors(code))
    errors.extend(world_lookup_errors(code, proposal, module))
    errors.extend(dependency_api_errors(module, proposal, code))
    if (module.kind == ModuleKind.SERVER_MODULE and
            "-- RMM_GAMEPLAY_BODY_BEGIN" in code):
        errors.extend(game_effect_safety_errors(
            code, routed_action=True,
            declared_behavior=str(module.description or ""),
        ))
    # A plan module_id is a Python-side identifier, NOT a Lua variable holding
    # a ModuleScript. Prior accepted clients emitted require(mod_network_bridge)
    # without declaring that name; the code parses but fails at runtime.
    declared_ids = {peer.module_id for peer in proposal.modules}
    for match in re.finditer(r"\brequire\s*\(\s*([A-Za-z_]\w*)\s*\)", masked):
        identifier = match.group(1)
        if identifier in declared_ids and not re.search(
                r"\blocal\s+" + re.escape(identifier) + r"\b", masked[:match.start()]):
            errors.append(
                "UNBOUND_MODULE_REQUIRE: " + identifier +
                " is a plan ID, not an in-scope Roblox ModuleScript Instance"
            )

    if re.search(r"\b(?:TODO|FIXME|not implemented|placeholder)\b", masked, re.I):
        errors.append("PLACEHOLDER: model did not implement requested gameplay")
    if re.search(r"\b(?:loadstring|getfenv|setfenv)\s*\(", masked):
        errors.append("UNSAFE_DYNAMIC_CODE: forbidden Luau dynamic evaluation")
    if re.search(r"\brequire\s*\(\s*\d{5,}\s*\)", masked):
        errors.append("UNVERIFIED_REQUIRE: numeric external asset is not audited")

    is_server = module.file_path.startswith("src/server/")
    is_client = module.file_path.endswith(".client.luau")
    # A previously saved model module is revalidated at every checkpoint.
    # Do not rely exclusively on the first scaffolded body generator: it
    # may not have run when resuming/importing the approved design. A valid
    # generic attribute change is NOT physical spacecraft departure.
    movement = (proposal.game_design.get("dynamic_design") or {}).get(
        "host_world_motion") or {}
    if is_server and module.name in movement:
        from .world_motion_contract import vehicle_motion_code_errors
        errors.extend(
            "WORLD_MOTION_CONTRACT: " + error
            for error in vehicle_motion_code_errors(code)
        )
    if is_server and re.search(r"\bLocalPlayer\b|:FireServer\s*\(|:InvokeServer\s*\(", masked):
        errors.append("REALM: client-only API used from server")
    if is_client:
        if re.search(r"\bDataStoreService\b|\bOnServerEvent\b|\bOnServerInvoke\b|:FireClient\s*\(", masked):
            errors.append("REALM: server-only API used from client")
        # GetService class names are literals and must be inspected before
        # string-masking. Cross-check the literal call start in masked code.
        for match in re.finditer(
            r"""\bgame\s*:\s*GetService\s*\(\s*(['"])(?:DataStoreService|ServerScriptService|ServerStorage)\1\s*\)""",
            stripped,
        ):
            if re.match(r"\bgame\s*:\s*GetService\s*\(", masked[match.start():]):
                errors.append("REALM: client attempts a server-only Roblox service")
                break

    if module.kind == ModuleKind.SERVER_MODULE and is_server:
        design = proposal.game_design.get("dynamic_design") or {}
        host_routes = [
            v for v in (design.get("host_actions") or {}).values()
            if isinstance(v, dict) and v.get("service") == module.name
        ]
        world_routes = [
            v for v in (design.get("host_world_actions") or {}).values()
            if isinstance(v, dict) and v.get("service") == module.name
        ]
        checks = service_contract_checks(
            module.name, code, require_start=True,
            needs_action=bool(host_routes or world_routes),
        )
        errors.extend(
            "SERVICE_ABI: " + item["detail"] for item in checks if not item["passed"]
        )
        if host_routes or world_routes:
            if re.search(r"\bOnServerEvent\b|\bOnServerInvoke\b", masked):
                errors.append("GATEWAY_DUPLICATE: bootstrap already owns Remote callbacks")
            from .gameplay_source_evidence import has_gameplay_mutation
            # Host-scaffolded source has a bounded authored action body.
            # First-party composition adapters may legitimately delegate
            # handleAction to a separate local Mine/Trade function that
            # owns the concrete world write. For those templates inspect
            # the complete module, excluding service registry boilerplate.
            scaffolded = ("-- Host-authored lifecycle, input validation and "
                          "exported ABI.") in code
            if not has_gameplay_mutation(code, routed_action=scaffolded):
                errors.append(
                    "ACTION_EFFECT_UNIMPLEMENTED: no executable gameplay "
                    "mutation in the source-owned action. Service.start "
                    "registry setup, logging and comments are not effects")

    # Typed state contracts were checked only during FIRST generation of a
    # scaffolded action. A resumed checkpoint, imported plan, or post-review
    # patch must not be allowed to substitute an unrelated mutation while
    # retaining the old approved state-change metadata.
    if is_server and module.kind == ModuleKind.SERVER_MODULE:
        design = proposal.game_design.get("dynamic_design") or {}
        typed_routes = [
            entry for entry in (design.get("host_typed_actions") or {}).values()
            if isinstance(entry, dict) and entry.get("server") == module.name
        ]
        if typed_routes:
            from .gameplay_source_evidence import (
                authored_action_body, state_key_used_by_executable_code,
            )
            body = authored_action_body(code)
            from .scoped_luau_abi import (
                typed_input_abi_errors, typed_input_fields_used,
            )
            for typed in typed_routes:
                contract = typed.get("contract") or {}
                # The same schema must be enforced for fresh model snippets,
                # checkpoint restores and manually imported files. A model
                # may write 'args[2]' against a NAMED actionArgs table; Luau
                # parses it but the value is nil at runtime.
                if "-- RMM_GAMEPLAY_BODY_BEGIN" in code and isinstance(contract, dict):
                    errors.extend(typed_input_abi_errors(body, contract))
                    required_inputs = contract.get("inputs") or []
                    if required_inputs and not typed_input_fields_used(body, contract):
                        errors.append(
                            "TYPED_INPUT_UNUSED: no declared named player "
                            "input is read in the server gameplay body")
                changes = (contract.get("state_changes", [])
                           if isinstance(contract, dict) else [])
                # transport_only declares ONLY the input/Remote ABI. By
                # design it has no model-approved state key; codegen must
                # still prove a real source mutation via the mandatory
                # ACTION_EFFECT_UNIMPLEMENTED gate above. Treating an empty
                # transport declaration as a missing state-change contract
                # contradicted validate_contract(transport_only=True) and
                # caused every scaffolded module to fail at checkpoint.
                transport_only = typed.get("transport_only") is True
                if not isinstance(changes, list):
                    errors.append("TYPED_STATE_CONTRACT_INVALID: state_changes must be a list")
                    continue
                if not changes:
                    if not transport_only:
                        errors.append("TYPED_STATE_CONTRACT_MISSING: no approved state changes")
                    continue
                for effect in changes:
                    key = effect.get("key") if isinstance(effect, dict) else None
                    if (not isinstance(key, str) or not key
                            or not state_key_used_by_executable_code(body, key)):
                        errors.append(
                            "TYPED_STATE_EFFECT_MISSING: declared server state "
                            "mutation absent from action body: " + str(key)
                        )

    return list(dict.fromkeys(errors))


def require_generated_module_contract(
    module: Any, proposal: RobloxProposal, code: str, analyzer: Any,
) -> None:
    errors = generated_module_errors(module, proposal, code, analyzer)
    if errors:
        raise ModuleGenerationContractError(module.name, errors)
