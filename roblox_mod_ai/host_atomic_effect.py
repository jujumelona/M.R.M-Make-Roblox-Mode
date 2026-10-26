"""Generic, explicit state-transition compiler for bounded typed actions.

This is an opt-in mechanism keyed by the existing authenticated Remote
contract, NOT by genre, module name, natural-language keywords, or templates.
A small planner supplies data only. Any unsupported effect is rejected rather
than being replaced with a pretend success or a 6K-token model-generated
ModuleScript.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind
from .typed_action_contract import validate_contract, lua_server_guard

_ID=re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")


def executable_spec(module:Any,proposal:Any)->tuple[str,dict,dict]|None:
    if module.kind != ModuleKind.SERVER_MODULE or not module.module_id.startswith("dyn_"):
        return None
    design=(proposal.game_design or {}).get("dynamic_design") or {}
    routes=[(remote,v) for remote,v in (design.get("host_actions") or {}).items()
            if isinstance(v,dict) and v.get("service")==module.name]
    if len(routes)!=1:
        return None
    remote,route=routes[0]
    if (route.get("kind")!="RemoteFunction" or route.get("max_args")==0
            or (design.get("remotes") or {}).get(remote)!="RemoteFunction"):
        return None
    if (design.get("module_remotes") or {}).get(module.module_id)!=[remote]:
        return None
    typed=(design.get("host_typed_actions") or {}).get(remote)
    effect=(design.get("host_executable_actions") or {}).get(remote)
    if not isinstance(typed,dict) or not isinstance(effect,dict):
        return None
    if typed.get("server")!=module.name or typed.get("transport_only") is True:
        return None
    clients=[m for m in proposal.modules if m.kind==ModuleKind.CLIENT_SCRIPT
             and m.name==typed.get("client")
             and (design.get("module_remotes") or {}).get(m.module_id)==[remote]
             and m.file_path.startswith("src/client/")
             and m.file_path.endswith(".client.luau")]
    if len(clients)!=1:
        return None
    if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
        return None
    contract=validate_contract(typed.get("contract"),
        world_entities=typed.get("world_entities") or [])
    if contract["target"]["kind"]=="world_entity":
        target=contract["target"]["name"]
        world=[w for w in design.get("world_objects",[])
               if isinstance(w,dict) and w.get("name")==target
               and w.get("class") in ("Part","MeshPart")]
        owned=(design.get("module_world_objects") or {}).get(module.module_id) or []
        if len(world)!=1 or owned.count(target)!=1:
            raise ValueError("EXECUTABLE_ACTION_UNBOUND_WORLD_TARGET")
    changes=contract["state_changes"]
    if len(changes)!=1 or changes[0]["scope"]!="player":
        return None
    if set(effect)!={"schema","namespace","field","operation","amount","limit"}:
        raise ValueError("EXECUTABLE_ACTION_UNSUPPORTED_SCHEMA")
    if effect["schema"]!="rmm/atomic-effect-v1":
        raise ValueError("EXECUTABLE_ACTION_UNSUPPORTED_VERSION")
    namespace,field=effect["namespace"],effect["field"]
    op=effect["operation"]
    if (not isinstance(namespace,str) or not _ID.fullmatch(namespace)
            or not isinstance(field,str) or not _ID.fullmatch(field)
            or op not in ("increment","decrement","set")):
        raise ValueError("EXECUTABLE_ACTION_UNSUPPORTED_OPERATION_OR_STATE")
    declared=changes[0]
    if declared["key"]!=namespace+"."+field or declared["operation"]!=op:
        raise ValueError("EXECUTABLE_ACTION_UNDECLARED_STATE_EFFECT")
    limit=effect["limit"]
    if type(limit) is not int or not 1<=limit<=1000000000:
        raise ValueError("EXECUTABLE_ACTION_UNSAFE_STATE_BOUND")
    amount=effect["amount"]
    if not isinstance(amount,dict):
        raise ValueError("EXECUTABLE_ACTION_INVALID_AMOUNT")
    if set(amount)=={"constant"}:
        val=amount["constant"]
        if type(val) is not int or not 0<=val<=limit:
            raise ValueError("EXECUTABLE_ACTION_INVALID_CONSTANT")
        amount_code=str(val)
    elif set(amount)=={"input"}:
        field_id=amount["input"]
        if not isinstance(field_id,str) or not _ID.fullmatch(field_id):
            raise ValueError("EXECUTABLE_ACTION_INVALID_INPUT")
        matches=[x for x in contract["inputs"]
                 if x["id"]==field_id and x["type"]=="integer"
                 and x["min"]>=0 and x["max"]<=limit]
        if len(matches)!=1:
            raise ValueError("EXECUTABLE_ACTION_INPUT_NOT_VALIDATED")
        amount_code="args."+field_id
    else:
        raise ValueError("EXECUTABLE_ACTION_INVALID_AMOUNT")
    if not any(m.name=="PlayerDataManager" and m.kind in
               (ModuleKind.DATA_STORE,ModuleKind.SERVER_MODULE)
               and m.file_path.startswith("src/server/")
               and m.file_path.endswith(".luau")
               and not m.file_path.endswith(".server.luau")
               for m in proposal.modules):
        raise ValueError("EXECUTABLE_ACTION_MISSING_PERSISTENCE_SERVICE")
    return remote,contract,{**effect,"amount_code":amount_code}


def render_atomic_server(module:Any,proposal:Any)->str|None:
    transaction = render_transaction_server(module, proposal)
    if transaction is not None:
        return transaction
    chosen=executable_spec(module,proposal)
    if chosen is None:
        return None
    remote,contract,effect=chosen
    namespace=effect["namespace"]
    field=effect["field"]
    amount=effect["amount_code"]
    operation=effect["operation"]
    limit=effect["limit"]
    guard=lua_server_guard(contract,
        world_name=contract["target"].get("name"))
    # lua_server_guard returns false on malformed payload; inside a named
    # validator this remains a fail-closed server boundary.
    if operation=="increment":
        next_value="current + amount"
        bound="current > MAXIMUM - amount"
    elif operation=="decrement":
        next_value="current - amount"
        bound="current < amount"
    else:
        next_value="amount"
        bound="false"
    source=r'''--!strict
-- Generic host-compiled atomic state transition. No model-authored Luau.
local Players=game:GetService("Players")
local Service={}
local MAXIMUM=__LIMIT__
local function validInput(player,...)
__GUARD__
    return true,args
end
function Service.start(services)
    assert(type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function",
        "Atomic action requires player persistence")
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players then
        return {success=false,reason="invalid_player"}
    end
    local ok,args=validInput(player,...)
    if not ok then return {success=false,reason="invalid_input"} end
    local state=services.PlayerDataManager.GetState(player,__NAMESPACE__)
    if type(state)~="table" then
        return {success=false,reason="profile_not_loaded"}
    end
    local current=state.__FIELD__
    if current==nil then current=0 end
    if type(current)~="number" or current~=current or current%1~=0
        or current<0 or current>MAXIMUM then
        return {success=false,reason="invalid_state"}
    end
    local amount=__AMOUNT__
    if type(amount)~="number" or amount%1~=0 or amount<0
        or amount>MAXIMUM or (__BOUND__) then
        return {success=false,reason="insufficient_or_exceeds_limit"}
    end
    local updated=__NEXT__
    -- No yield, Remote call or DataStore call between checking and writing.
    state.__FIELD__=updated
    return {success=true,value=updated}
end
return Service
'''
    return (source.replace("__LIMIT__",str(limit))
            .replace("__GUARD__",guard.rstrip())
            .replace("__NAMESPACE__",json.dumps(namespace))
            .replace("__FIELD__",field)
            .replace("__AMOUNT__",amount)
            .replace("__BOUND__",bound)
            .replace("__NEXT__",next_value))


def render_transaction_server(module: Any, proposal: Any) -> str | None:
    """Compile a bounded multi-field transaction, with one durable namespace.

    This is a generic opt-in execution program, never derived from names,
    genres or the wording of a request. All preconditions are checked before
    any field is changed. There is no yield inside the transaction.
    """
    if module.kind != ModuleKind.SERVER_MODULE or not module.module_id.startswith("dyn_"):
        return None
    design = (proposal.game_design or {}).get("dynamic_design") or {}
    routes = [(remote, route) for remote, route in
              (design.get("host_actions") or {}).items()
              if isinstance(route, dict) and route.get("service") == module.name]
    if len(routes) != 1:
        return None
    remote, route = routes[0]
    program = (design.get("host_executable_actions") or {}).get(remote)
    if not isinstance(program, dict) or program.get("schema") != "rmm/transaction-effect-v1":
        return None
    if (route.get("kind") != "RemoteFunction" or route.get("max_args") != 1
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (design.get("module_remotes") or {}).get(module.module_id) != [remote]):
        raise ValueError("TRANSACTION_REMOTE_CONTRACT_INVALID")
    typed = (design.get("host_typed_actions") or {}).get(remote)
    if (not isinstance(typed, dict) or typed.get("server") != module.name
            or typed.get("transport_only") is True):
        raise ValueError("TRANSACTION_TYPED_ACTION_REQUIRED")
    clients = [m for m in proposal.modules
               if m.kind == ModuleKind.CLIENT_SCRIPT and m.name == typed.get("client")
               and (design.get("module_remotes") or {}).get(m.module_id) == [remote]
               and m.file_path.startswith("src/client/")
               and m.file_path.endswith(".client.luau")]
    if (len(clients) != 1 or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        raise ValueError("TRANSACTION_CLIENT_OR_SERVER_ABI_INVALID")
    contract = validate_contract(typed.get("contract"),
                                 world_entities=typed.get("world_entities") or [])
    if contract["target"]["kind"] != "none":
        # A world-space action additionally needs an authoritative spatial
        # binding. Do not mistake an arbitrary UI selection for proximity.
        raise ValueError("TRANSACTION_WORLD_TARGET_REQUIRES_VERIFIED_BINDING")
    if set(program) != {"schema", "namespace", "changes"}:
        raise ValueError("TRANSACTION_UNSUPPORTED_FIELDS")
    namespace = program["namespace"]
    rows = program["changes"]
    if (not isinstance(namespace, str) or not _ID.fullmatch(namespace)
            or not isinstance(rows, list) or not 1 <= len(rows) <= 5):
        raise ValueError("TRANSACTION_INVALID_NAMESPACE_OR_LENGTH")
    declarations = contract["state_changes"]
    if len(declarations) != len(rows):
        raise ValueError("TRANSACTION_UNDECLARED_EFFECT_COUNT")
    identifiers = set()
    checks = []
    commits = []
    updates = []
    for idx, (row, declared) in enumerate(zip(rows, declarations)):
        if not isinstance(row, dict) or set(row) != {"field", "operation", "amount", "limit"}:
            raise ValueError("TRANSACTION_INVALID_CHANGE_SHAPE")
        field, operation = row["field"], row["operation"]
        if (not isinstance(field, str) or not _ID.fullmatch(field)
                or field in identifiers or operation not in ("increment", "decrement", "set")):
            raise ValueError("TRANSACTION_DUPLICATE_OR_UNSUPPORTED_STATE")
        identifiers.add(field)
        if declared != {"scope": "player", "key": namespace + "." + field,
                        "operation": operation}:
            raise ValueError("TRANSACTION_CHANGE_DIFFERS_FROM_DECLARATION")
        limit = row["limit"]
        if type(limit) is not int or not 1 <= limit <= 1000000000:
            raise ValueError("TRANSACTION_UNBOUNDED_INTEGER")
        amount = row["amount"]
        if not isinstance(amount, dict):
            raise ValueError("TRANSACTION_INVALID_AMOUNT")
        if set(amount) == {"constant"}:
            n = amount["constant"]
            if type(n) is not int or not 0 <= n <= limit:
                raise ValueError("TRANSACTION_INVALID_CONSTANT")
            expr = str(n)
        elif set(amount) == {"input"}:
            field_id = amount["input"]
            if (not isinstance(field_id, str) or not _ID.fullmatch(field_id)
                    or len([f for f in contract["inputs"]
                            if f["id"] == field_id and f["type"] == "integer"
                            and f["min"] >= 0 and f["max"] <= limit]) != 1):
                raise ValueError("TRANSACTION_UNVALIDATED_AMOUNT")
            expr = "args." + field_id
        else:
            raise ValueError("TRANSACTION_INVALID_AMOUNT")
        n = idx + 1
        old, delta, next_value = f"old{n}", f"amount{n}", f"next{n}"
        checks.append(
            f"    local {old}=state.{field}\\n"
            f"    if {old}==nil then {old}=0 end\\n"
            f"    if type({old})~=\"number\" or {old}~={old} or {old}%1~=0 "
            f"or {old}<0 or {old}>{limit} then\\n"
            f"        return {{success=false,reason=\"invalid_state\"}} end\\n"
            f"    local {delta}={expr}\\n"
            f"    if type({delta})~=\"number\" or {delta}~={delta} or {delta}%1~=0 "
            f"or {delta}<0 or {delta}>{limit} then\\n"
            f"        return {{success=false,reason=\"invalid_amount\"}} end\\n"
        )
        if operation == "increment":
            checks.append(
                f"    if {old}>{limit}-{delta} then "
                'return {success=false,reason="limit"} end\\n'
            )
            checks.append(f"    local {next_value}={old}+{delta}\\n")
        elif operation == "decrement":
            checks.append(
                f"    if {old}<{delta} then "
                'return {success=false,reason="insufficient"} end\\n'
            )
            checks.append(f"    local {next_value}={old}-{delta}\\n")
        else:
            checks.append(f"    local {next_value}={delta}\\n")
        commits.append(f"    state.{field}={next_value}\\n")
        updates.append(field + "=" + next_value)
    if not any(m.name == "PlayerDataManager"
               and m.kind in (ModuleKind.DATA_STORE, ModuleKind.SERVER_MODULE)
               and m.file_path.startswith("src/server/")
               and m.file_path.endswith(".luau")
               and not m.file_path.endswith(".server.luau")
               for m in proposal.modules):
        raise ValueError("TRANSACTION_MISSING_PLAYER_PERSISTENCE")
    guard = lua_server_guard(contract, world_name=None)
    return ('''--!strict
-- Host-compiled declarative multi-field transaction; not LLM-authored Luau.
local Players=game:GetService("Players")
local Service={}
local function validInput(player,...)
__GUARD__
    return true,args
end
function Service.start(services)
    assert(type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function",
        "Transaction requires PlayerDataManager")
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players then
        return {success=false,reason="invalid_player"} end
    local ok,args=validInput(player,...)
    if not ok then return {success=false,reason="invalid_input"} end
    local state=services.PlayerDataManager.GetState(player,__NAMESPACE__)
    if type(state)~="table" then
        return {success=false,reason="profile_not_loaded"} end
__PRECONDITIONS__
    -- All checks completed. No yielding calls or intermediate persistence writes.
__COMMIT__
    return {success=true,values={__RESULT__}}
end
return Service
'''.replace("__GUARD__", guard.rstrip())
      .replace("__NAMESPACE__", json.dumps(namespace))
      .replace("__PRECONDITIONS__", "".join(checks).rstrip())
      .replace("__COMMIT__", "".join(commits).rstrip())
      .replace("__RESULT__", ",".join(updates)))
