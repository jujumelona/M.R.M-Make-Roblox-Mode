"""Host-owned, bounded gameplay input contracts and Luau transport.

The local planner provides a small declaration, NEVER a Remote/UI/validator.
The host validates the declaration and generates both ends of the protocol.
Server-side game-specific *effects* remain separately implemented and tested;
the transition ledger is a mandatory contract, not proof of execution.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
_STATE = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,79}\Z")

# Names are inserted as unquoted Luau table members (args.<id> and
# state.<field>). Lexically valid names such as "end" are still keywords.
_LUAU_RESERVED = frozenset((
    "and", "break", "continue", "do", "else", "elseif", "end", "export",
    "false", "for", "function", "if", "in", "local", "nil", "not", "or",
    "repeat", "return", "then", "true", "type", "until", "while",
))

def safe_luau_identifier(value: Any) -> bool:
    return (isinstance(value, str) and bool(_ID.fullmatch(value))
            and value not in _LUAU_RESERVED)

def safe_luau_state_path(value: Any) -> bool:
    return (isinstance(value, str) and bool(_STATE.fullmatch(value))
            and all(safe_luau_identifier(part) for part in value.split(".")))

SCHEMA = {
    "type": "object",
    "properties": {
        "inputs": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "properties": {
                "id": {"type": "string"},
                "label": {"type": "string"},
                "type": {"type": "string", "enum": [
                    "text", "integer", "choice"]},
                "min": {"type": "integer"}, "max": {"type": "integer"},
                "options": {"type": "array", "maxItems": 8, "items": {
                    "type": "object", "properties": {
                        "id": {"type": "string"}, "label": {"type": "string"},
                    }, "required": ["id", "label"]}},
            }, "required": ["id", "label", "type"]}},
        "target": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["none", "world_entity"]},
            "name": {"type": "string"},
        }, "required": ["kind"]},
        "state_changes": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "properties": {
                "scope": {"type": "string", "enum": ["player", "world"]},
                "key": {"type": "string"},
                "operation": {"type": "string", "enum": [
                    "increment", "decrement", "set", "create", "remove"]},
            }, "required": ["scope", "key", "operation"]}},
    },
    "required": ["inputs", "target", "state_changes"],
}


class TypedActionContractError(ValueError):
    pass


def _text(value: Any, *, limit: int = 70) -> bool:
    return isinstance(value, str) and 1 <= len(value.strip()) <= limit


def validate_contract(
    raw: Any, *, world_entities: list[str],
    transport_only: bool = False,
) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {
        "inputs", "target", "state_changes",
    }:
        raise TypedActionContractError("Action contract needs exactly inputs, target, state_changes")
    fields, target, effects = raw["inputs"], raw["target"], raw["state_changes"]
    if (not isinstance(fields, list) or not 0 <= len(fields) <= 4
            or not isinstance(effects, list)
            or not (0 if transport_only else 1) <= len(effects) <= 5):
        raise TypedActionContractError("Bounded typed inputs and at least one state change required")
    seen: set[str] = set()
    clean_fields = []
    for field in fields:
        if not isinstance(field, dict):
            raise TypedActionContractError("Input must be an object")
        field_id, kind = field.get("id"), field.get("type")
        if (not isinstance(field_id, str) or not safe_luau_identifier(field_id)
                or field_id in seen or not _text(field.get("label"))
                or kind not in ("text", "integer", "choice")):
            raise TypedActionContractError("Invalid, duplicated or unsupported typed input")
        seen.add(field_id)
        # The shared JSON grammar exposes min/max/options for every field
        # kind. Constrained local models may materialize those optional
        # siblings even on TEXT fields. Reject unknown metadata, but let
        # the discriminator (type) own the meaning of known siblings.
        # Discard inapplicable siblings; NEVER pass them to UI or server.
        allowed_metadata = {"id", "label", "type", "min", "max", "options"}
        if set(field) - allowed_metadata:
            raise TypedActionContractError("Input contains unknown metadata")
        if kind == "integer":
            low, high = field.get("min"), field.get("max")
            if (type(low) is not int or type(high) is not int
                    or not -1000000 <= low <= high <= 1000000):
                raise TypedActionContractError("Integer input requires bounded min/max")
            # options belongs only to choice; a generated empty options
            # array is inactive and cannot change integer semantics.
            clean_fields.append({"id": field_id, "label": field["label"].strip(),
                                 "type": kind, "min": low, "max": high})
        elif kind == "choice":
            options = field.get("options")
            if not isinstance(options, list) or not 1 <= len(options) <= 8:
                raise TypedActionContractError("Choice needs 1-8 fixed options")
            items, option_ids = [], set()
            for option in options:
                if (not isinstance(option, dict)
                        or set(option) != {"id", "label"}
                        or not isinstance(option["id"], str)
                        or not safe_luau_identifier(option["id"])
                        or option["id"] in option_ids
                        or not _text(option["label"])):
                    raise TypedActionContractError("Invalid choice option")
                option_ids.add(option["id"])
                items.append({"id": option["id"], "label": option["label"].strip()})
            clean_fields.append({"id": field_id, "label": field["label"].strip(),
                                 "type": kind, "options": items})
        else:
            # min/max/options are inert for text. Keep the canonical
            # text field only; its length is enforced on the server.
            clean_fields.append({"id": field_id, "label": field["label"].strip(), "type": kind})
    if not isinstance(target, dict) or target.get("kind") not in ("none", "world_entity"):
        raise TypedActionContractError("Unsupported input target")
    if target["kind"] == "none":
        if set(target) - {"kind", "name"}:
            raise TypedActionContractError("No-target action has unknown fields")
        # Constrained JSON can emit name="" for an unselected target.
        # A nonblank target name must not be silently disregarded.
        if target.get("name") not in (None, ""):
            raise TypedActionContractError("No-target action cannot claim a world object")
        clean_target = {"kind": "none"}
    else:
        name = target.get("name")
        if (set(target) != {"kind", "name"} or not isinstance(name, str)
                or name not in world_entities
                or world_entities.count(name) != 1):
            raise TypedActionContractError("World target must reference one declared object")
        clean_target = {"kind": "world_entity", "name": name}
    # Zero-field player actions are still valid: the host renders a submit
    # button carrying one empty, validated table. Do not send this case
    # back to the small model just to rename it host_button.
    changes = []
    for effect in effects:
        if (not isinstance(effect, dict)
                or set(effect) != {"scope", "key", "operation"}
                or effect["scope"] not in ("player", "world")
                or not isinstance(effect["key"], str)
                or not safe_luau_state_path(effect["key"])
                or effect["operation"] not in (
                    "increment", "decrement", "set", "create", "remove")):
            raise TypedActionContractError("Invalid declarative server state change")
        changes.append(dict(effect))
    return {"inputs": clean_fields, "target": clean_target, "state_changes": changes}



def complete_typed_contract(
    router: Any, *, system: dict[str, Any],
    source_requirements: list[dict[str, Any]],
    attempts_log: list[dict[str, Any]],
    system_index: int,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """A single recoverable microtask. Never re-author the gameplay plan.

    The model returns only the schema. The host normalizes inactive metadata
    and enforces all active constraints. If it remains invalid, retry ONLY
    this contract with exact error feedback. Store raw output for diagnostics.
    """
    context = {
        "source_requirements": source_requirements,
        "name": system.get("name"),
        "server_behavior": system.get("server_behavior"),
        "world_entities": system.get("world_entities", []),
    }
    prompt = (
        "Describe typed player INPUT and server state changes for this "
        "ALREADY-EXISTING action. Never redesign the server behavior. "
        "JSON {inputs:[{id,label,type,min,max,options}],target:{kind,name},"
        "state_changes:[{scope,key,operation}]}. input type=text needs "
        "id/label/type only, integer needs min/max integer bounds, choice "
        "needs options id/label array. Target is {kind:none} unless the "
        "existing action targets ONE declared world entity. State changes "
        "name the actual server-owned fields already changed by the "
        "existing action (1-5). Zero input fields are permitted when "
        "the player only presses Submit; never invent dummy fields. "
        "Do not add new mechanics, purchases, targets or outcomes. "
        "The host generates the UI and server validator. JSON only.\\n"
        + json.dumps(context, ensure_ascii=False)
    )
    last_error = ""
    for attempt in range(max_attempts):
        response: Any = None
        try:
            instruction = prompt
            if last_error:
                instruction += (
                    "\\nPrevious contract was rejected: " + last_error[:500] +
                    ". Correct ONLY this short input contract. Do NOT "
                    "regenerate the gameplay or return a systems array."
                )
            response = router.complete_json(
                instruction, role="planner", temperature=0.0,
                max_tokens=500, json_schema=SCHEMA,
            )
            valid = validate_contract(
                response, world_entities=system.get("world_entities", []))
            attempts_log.append({
                "system_index": system_index, "system_name": system.get("name"),
                "attempt": attempt + 1, "passed": True,
                "normalization": response != valid,
            })
            return valid
        except Exception as exc:
            last_error = type(exc).__name__ + ": " + str(exc)[:500]
            try:
                emitted = json.dumps(response, ensure_ascii=False)
            except (TypeError, ValueError):
                emitted = repr(response)
            attempts_log.append({
                "system_index": system_index, "system_name": system.get("name"),
                "attempt": attempt + 1, "passed": False,
                "error": last_error,
                "raw_contract": emitted[:6000],
                "model_runtime": getattr(router, "last_generation_report", {}),
            })
    raise TypedActionContractError(
        "TYPED_ACTION_CONTRACT_EXHAUSTED: " + str(system.get("name"))
        + ": " + last_error
    )


def lua_server_guard(contract: dict[str, Any], *, world_name: str | None = None) -> str:
    """Generate server-side type/bounds/allowlist validation. Never trust UI."""
    fields = contract["inputs"]
    lines = [
        '    if select("#", ...) ~= 1 then return false end',
        '    local actionArgs = ...',
        '    if typeof(actionArgs) ~= "table" then return false end',
        '    local __rmmAllowedFields = {}',
    ]
    for field in fields:
        name = json.dumps(field["id"])
        lines.append("    __rmmAllowedFields[" + name + "] = true")
    lines += [
        '    for key, _ in pairs(actionArgs) do',
        '        if type(key) ~= "string" or not __rmmAllowedFields[key] then return false end',
        '    end',
    ]
    for field in fields:
        ref = "actionArgs[" + json.dumps(field["id"]) + "]"
        if field["type"] == "integer":
            lines.append(
                '    if type(' + ref + ') ~= "number" or ' + ref +
                ' % 1 ~= 0 or ' + ref + ' < ' + str(field["min"]) +
                ' or ' + ref + ' > ' + str(field["max"]) +
                ' then return false end')
        elif field["type"] == "text":
            lines.append(
                '    if type(' + ref + ') ~= "string" or #' + ref +
                ' < 1 or #' + ref + ' > 120 then return false end')
        else:
            allowed = ", ".join(
                "[" + json.dumps(option["id"]) + "] = true"
                for option in field["options"])
            lines.append(
                '    if type(' + ref + ') ~= "string" or not ({' +
                allowed + '})[' + ref + '] then return false end')
    if contract["target"]["kind"] == "world_entity":
        if not world_name:
            raise TypedActionContractError("Host world target was not resolved")
        lines += [
            '    local __rmmTarget = workspace:FindFirstChild(' +
            json.dumps(world_name) + ', true)',
            '    if not __rmmTarget or not __rmmTarget:IsA("BasePart") then return false end',
            '    local __rmmCharacter = player.Character',
            '    local __rmmRoot = __rmmCharacter and __rmmCharacter:FindFirstChild("HumanoidRootPart")',
            '    if not __rmmRoot or not __rmmRoot:IsA("BasePart") then return false end',
            '    if (__rmmRoot.Position - __rmmTarget.Position).Magnitude > 24 then return false end',
            '    local actionTarget = __rmmTarget',
        ]
    lines.append('    local args = actionArgs')
    return "\n".join(lines) + "\n"


def render_typed_client(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    """Generate fully deterministic cross-platform form UI and Remote call."""
    if module.kind != ModuleKind.CLIENT_SCRIPT or not module.module_id.startswith("dyn_"):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if not isinstance(linked, list) or len(linked) != 1:
        return None
    remote = linked[0]
    spec = (design.get("host_typed_actions") or {}).get(remote)
    if spec is None:
        return None
    contract = validate_contract(
        spec["contract"], world_entities=spec.get("world_entities", []),
        transport_only=spec.get("transport_only") is True,
    )
    # A verified physical-world Part has an exact server-owned identity.
    # Prefill its typed selection instead of forcing players to guess an
    # opaque generated Workspace name. The server still validates all fields.
    default_selection = None
    owner = next((m for m in getattr(proposal, "modules", ())
                  if m.kind == ModuleKind.SERVER_MODULE
                  and m.name == spec.get("server")), None)
    if owner is not None:
        from .host_verified_typed_effects import eligible_verified_effect
        verified = eligible_verified_effect(owner, proposal)
        if verified is not None and verified[1] == remote:
            default_selection = verified[2]
    kind = (design.get("remotes") or {}).get(remote)
    if kind not in ("RemoteEvent", "RemoteFunction"):
        raise TypedActionContractError("Typed UI remote does not exist")
    if spec.get("client") != module.name:
        return None
    lines = [
        '--!strict',
        '-- Host-owned typed input UI. No model-authored network code.',
        'local Players = game:GetService("Players")',
        'local ReplicatedStorage = game:GetService("ReplicatedStorage")',
        'local player = Players.LocalPlayer',
        'local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(' +
        json.dumps(remote) + ')',
        'if not remote:IsA(' + json.dumps(kind) + ') then error("Remote mismatch") end',
        'local gui = Instance.new("ScreenGui")',
        'gui.Name = ' + json.dumps(module.name),
        'gui.ResetOnSpawn = false',
        'gui.Parent = player:WaitForChild("PlayerGui")',
        'local panel = Instance.new("ScrollingFrame")',
        'panel.Name = "TypedActionForm"',
        'panel.Position = UDim2.new(1, -275, 0, 140)',
        'panel.Size = UDim2.fromOffset(255, 320)',
        'panel.AutomaticCanvasSize = Enum.AutomaticSize.Y',
        'panel.CanvasSize = UDim2.fromOffset(0, 0)',
        'panel.Parent = gui',
        'local layout = Instance.new("UIListLayout")',
        'layout.Padding = UDim.new(0, 5)',
        'layout.Parent = panel',
        'local status = Instance.new("TextLabel")',
        'status.Size = UDim2.new(1, 0, 0, 32)',
        'status.Text = "Choose action inputs"',
        'status.Parent = panel',
        'local controls = {}',
    ]
    for field in contract["inputs"]:
        field_id, label = json.dumps(field["id"]), json.dumps(field["label"], ensure_ascii=False)
        lines += [
            'do',
            '    local caption = Instance.new("TextLabel")',
            '    caption.Size = UDim2.new(1, 0, 0, 25)',
            '    caption.Text = ' + label,
            '    caption.Parent = panel',
        ]
        if field["type"] == "choice":
            opts = field["options"]
            ids = "{" + ", ".join(json.dumps(o["id"]) for o in opts) + "}"
            labels = "{" + ", ".join(json.dumps(o["label"], ensure_ascii=False) for o in opts) + "}"
            lines += [
                '    local ids = ' + ids,
                '    local labels = ' + labels,
                '    local selected = 1',
                '    local button = Instance.new("TextButton")',
                '    button.Size = UDim2.new(1, 0, 0, 35)',
                '    button.Text = labels[selected]',
                '    button.Parent = panel',
                '    button.Activated:Connect(function()',
                '        selected = selected % #ids + 1',
                '        button.Text = labels[selected]',
                '    end)',
                '    controls[' + field_id + '] = function() return ids[selected] end',
            ]
        else:
            lines += [
                '    local box = Instance.new("TextBox")',
                '    box.Size = UDim2.new(1, 0, 0, 35)',
                '    box.Text = ' + ('"1"' if field["type"] == "integer"
                                      else json.dumps(default_selection)
                                      if field["id"] == "selection" and default_selection
                                      else '""'),
                '    box.PlaceholderText = ' + label,
                '    box.ClearTextOnFocus = false',
                '    box.Parent = panel',
            ]
            if field["type"] == "integer":
                lines.append('    controls[' + field_id + '] = function() return tonumber(box.Text) end')
            else:
                lines.append('    controls[' + field_id + '] = function() return box.Text end')
        lines.append('end')
    lines += [
        'local submit = Instance.new("TextButton")',
        'submit.Size = UDim2.new(1, 0, 0, 38)',
        'submit.Text = "Submit action"',
        'submit.Parent = panel',
        'local busy = false',
        'submit.Activated:Connect(function()',
        '    if busy then return end',
        '    local payload = {}',
        '    for key, read in pairs(controls) do payload[key] = read() end',
        '    busy = true',
    ]
    if kind == "RemoteFunction":
        lines += [
            '    local ok, result = pcall(function() return remote:InvokeServer(payload) end)',
            '    status.Text = ok and (result == true or (type(result) == "table" and result.success == true)) and "Action confirmed" or "Action rejected"',
        ]
    else:
        lines += [
            '    local ok = pcall(function() remote:FireServer(payload) end)',
            '    status.Text = ok and "Request sent" or "Request unavailable"',
        ]
    lines += ['    busy = false', 'end)']
    return "\n".join(lines) + "\n"


def validated_host_choice_options(raw: Any) -> list[dict[str, str]]:
    """Admit only a complete, bounded host-enforceable option table.

    Model-produced arrays of strings or partial option objects are NOT an
    authorization list. Do not guess IDs or reinterpret labels as privileged
    server actions. With no valid allowlist the host uses a validated text
    selection and the server must resolve and authorize its meaning.
    """
    import re

    if not isinstance(raw, list) or not 1 <= len(raw) <= 8:
        return []
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"id", "label"}:
            return []
        ident, label = item["id"], item["label"]
        if (not isinstance(ident, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", ident)
                or ident in seen
                or not isinstance(label, str)
                or not 1 <= len(label.strip()) <= 70):
            return []
        seen.add(ident)
        clean.append({"id": ident, "label": label.strip()})
    return clean


def host_owned_action_contract(
    choices: Any = None, *,
    world_entities: list[str] | None = None,
    host_selects_target: bool = False,
) -> dict[str, Any]:
    """Compile a transport schema from known action requirements, not defaults.

    A one-target action already bound to a concrete world entity, or a host-
    selected world transition, has no reason to ask the user for a free-text
    ID or quantity. For a missing choice catalog, retain the legacy generic
    form for multi-target interactive actions so the server must authorize
    whatever identifier is submitted. No game mechanic is inferred here.
    """
    approved = validated_host_choice_options(choices)
    # The number of MATERIALIZED world objects does NOT tell us whether
    # the player must choose an item, quantity or upgrade tier. A crew
    # performance STATE Part is not the player's chosen crew member. Plan83
    # gave the purchase handler a zero-field payload solely because one
    # world object existed, then rejected every legitimate item selection.
    # Zero inputs require an explicit host-selected-target contract.
    if host_selects_target:
        inputs: list[dict[str, Any]] = []
    elif approved:
        # A verified choice list establishes selection IDs, not whether the
        # operation accepts quantities. Preserve the prior quantity contract
        # until an explicit typed cardinality is authored and validated.
        inputs = [
            {"id": "selection", "label": "Allowed action choice",
             "type": "choice", "options": approved},
            {"id": "quantity", "label": "Requested quantity",
             "type": "integer", "min": 1, "max": 10000},
        ]
    else:
        inputs = [
            {"id": "selection", "label": "Item, action, or target ID",
             "type": "text"},
            {"id": "quantity", "label": "Requested quantity",
             "type": "integer", "min": 1, "max": 10000},
        ]
    return {
        "inputs": inputs,
        "target": {"kind": "none"},
        "state_changes": [],
    }
