"""Ordered parent-linked construction protocol compiled by first-party Luau.

A small model writes an allowlisted catalog {id,parent,cost,performance};
never executable Luau. The host checks physical parent, ordered attachment,
saved ownership, resource balance, and creates actual welded player models.
This reuses the source-audited base construction UI/transaction template.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .spec import ModuleKind
from .host_ship_attachment import _SERVER, _CLIENT, _validated_sections

_ID=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,59}$")
_PARENT=re.compile(r"\bparent\s+part\b|\bparent\s+attachment\b",re.I)
_ATTACH=re.compile(r"\battach\w*|\bassembl\w*|\bconstruct\w*",re.I)
_ORDER=re.compile(r"\bbuild\s+order\b|\border\w*\s+of\s+construction\b",re.I)
_SAVE=re.compile(r"\b(?:persist\w*|sav\w*|record\w*)\b",re.I)
_SCHEMA={"type":"object","properties":{"sections":{"type":"array","items":{
    "type":"object","properties":{
        "id":{"type":"string"},"parent":{"type":"string"},
        "label":{"type":"string"},"cost":{"type":"integer"},
        "performance":{"type":"integer"}},
    "required":["id","parent","label","cost","performance"],
    "additionalProperties":False}}},"required":["sections"],"additionalProperties":False}


def eligible_ordered_assembly(m:Any,p:Any)->tuple[str,str,str,list[str]]|None:
    if not m.module_id.startswith("dyn_") or m.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT):return None
    server=m.name if m.kind==ModuleKind.SERVER_MODULE else m.name.removesuffix("Client")+"Server"
    owner=next((x for x in p.modules if x.name==server and x.kind==ModuleKind.SERVER_MODULE),None)
    if owner is None or not all(rx.search(owner.description) for rx in (_PARENT,_ATTACH,_ORDER,_SAVE)):return None
    d=p.game_design.get("dynamic_design") or {}
    rows=[(k,v) for k,v in (d.get("host_actions") or {}).items()
          if isinstance(v,dict) and v.get("service")==server]
    if len(rows)!=1:return None
    remote,route=rows[0]
    if route.get("kind")!="RemoteFunction" or (d.get("remotes") or {}).get(remote)!="RemoteFunction":return None
    spec=((d.get("host_typed_actions") or {}).get(remote)
          or (d.get("host_ordered_assembly_contracts") or {}).get(remote))
    if not isinstance(spec,dict) or spec.get("transport_only") is not True:return None
    if spec.get("server")!=server or spec.get("client")!=server.removesuffix("Server")+"Client":return None
    ids=spec.get("world_entities") or []
    if any(not isinstance(x,str) or not _ID.fullmatch(x) for x in ids):return None
    roots=[x for x in ids if re.search("root|anchor",x,re.I)]
    parts=[x for x in ids if x not in roots]
    if len(roots)!=1 or not 2<=len(parts)<=8:return None
    if m.kind==ModuleKind.CLIENT_SCRIPT and not m.file_path.endswith(".client.luau"):return None
    if m.kind==ModuleKind.SERVER_MODULE and not m.file_path.startswith("src/server/"):return None
    linked=(d.get("module_remotes") or {}).get(m.module_id)
    if linked is not None and linked!=[remote]:return None
    return server,remote,roots[0],parts


def _catalog(p:Any,server:str,root:str,parts:list[str],router:Any)->list[dict]:
    store=p.game_design.setdefault("_host_ordered_assembly_data",{})
    if server in store:return _validate(store[server],root,parts)
    if not hasattr(router,"complete_json"):raise ValueError("ORDERED_ASSEMBLY_REQUIRES_DATA_ROUTER")
    source=next(x.description for x in p.modules if x.name==server)
    last=""
    for _ in range(2):
        try:
            data=router.complete_json(
                "Return JSON {sections:[{id,parent,label,cost,performance}]}. "
                "List EXACTLY the allowed named parts in valid build order, "
                "each once. Parent is the exact root ID or an EARLIER part ID. "
                "All costs are positive mined resources, all performance "
                "contributions are positive integers. Output no Luau. "
                "Real root ID: "+root+". Allowed part IDs in order: "+
                json.dumps(parts)+". Original action: "+source[:700]+
                ("\nInvalid prior data: "+last if last else ""),
                role="planner",temperature=0,max_tokens=650,json_schema=_SCHEMA)
            rows=_validate(data,root,parts)
            store[server]={"sections":rows}
            return rows
        except (TypeError,ValueError) as exc:last=str(exc)[:250]
    raise ValueError("ORDERED_ASSEMBLY_CATALOG_INVALID: "+last)


def _validate(data:Any,root:str,parts:list[str])->list[dict]:
    if not isinstance(data,dict) or set(data)!={"sections"}:raise ValueError("INVALID_SECTION_CATALOG")
    sections=data["sections"]
    if not isinstance(sections,list) or len(sections)!=len(parts):raise ValueError("MISSING_SECTION")
    rows=[]
    seen={root}
    for i,part in enumerate(sections):
        if not isinstance(part,dict) or set(part)!={"id","parent","label","cost","performance"}:
            raise ValueError("INVALID_SECTION_ROW")
        if part["id"]!=parts[i] or part["parent"] not in seen:raise ValueError("INVALID_PARENT_OR_BUILD_ORDER")
        checked=_validated_sections({"sections":[{
            "id":part["id"],"label":part["label"],"cost":part["cost"],
            "performance":part["performance"]}]})[0]
        rows.append(dict(checked,parent=part["parent"]))
        seen.add(part["id"])
    return rows


def _replace_exact(source:str,old:str,new:str)->str:
    if source.count(old)!=1:
        raise ValueError("HOST_ASSEMBLY_TEMPLATE_ABI_CHANGED: "+old[:65])
    return source.replace(old,new)


def render_ordered_assembly(m:Any,p:Any,router:Any)->str|None:
    eligible=eligible_ordered_assembly(m,p)
    if eligible is None:return None
    server,remote,root,ids=eligible
    rows=_catalog(p,server,root,ids,router)
    if m.kind==ModuleKind.CLIENT_SCRIPT:
        entries=",\n".join(
            "{id = "+json.dumps(v["id"])+", label = "+
            json.dumps(v["label"],ensure_ascii=False)+", cost = "+
            str(v["cost"])+"}" for v in rows)
        return _CLIENT.replace("__REMOTE__",json.dumps(remote)).replace("__SECTIONS__",entries)
    declarations=",\n".join(
        "["+json.dumps(v["id"])+"] = {cost = "+str(v["cost"])+
        ", performance = "+str(v["performance"])+", ordinal = "+
        str(i+1)+", parent = "+json.dumps(v["parent"])+"}" for i,v in enumerate(rows))
    result=_SERVER.replace("__SECTIONS__",declarations)
    result=_replace_exact(result,"local RANGE = 26",
        "local RANGE = 26\nlocal ROOT_ID = "+json.dumps(root)+
        "\nlocal ORDER = {"+", ".join(json.dumps(v["id"]) for v in rows)+"}")
    start=result.index("local function placePart(parts, anchor, id)\n")
    end=result.index("\nfunction Service.start(services)",start)
    revised=r'''local function placePart(parts, anchor, id)
    local definition = SECTIONS[id]
    if not definition then return false end
    if parts:FindFirstChild(id) then return true end
    local parent = definition.parent == ROOT_ID and anchor
        or parts:FindFirstChild(definition.parent)
    if not parent or not parent:IsA("BasePart") then return false end
    local part = Instance.new("Part")
    part.Name = id
    part.Anchored = false
    part.Size = Vector3.new(5, 2, 6)
    part.CFrame = parent.CFrame * CFrame.new(0, 3, 6)
    part:SetAttribute("RMMAssemblySection", id)
    part.Parent = parts
    local weld = Instance.new("WeldConstraint")
    weld.Part0 = parent
    weld.Part1 = part
    weld.Parent = part
    return true
end'''
    result=result[:start]+revised+result[end:]
    # A passenger stays physically attached during Model:PivotTo, rather than
    # being teleported separately or silently ejected. The actual occupant
    # must be checked by the departure host before moving the assembled model.
    seat_anchor='''    local parts = ship:FindFirstChild("AssembledSections")'''
    seat_code='''    local seat = ship:FindFirstChild("PilotSeat")
    if seat and not seat:IsA("VehicleSeat") then return nil end
    if not seat then
        seat = Instance.new("VehicleSeat")
        seat.Name = "PilotSeat"
        seat.Anchored = false
        seat.Size = Vector3.new(3, 1, 3)
        seat.CFrame = anchor.CFrame * CFrame.new(0, 2, 0)
        seat.Parent = ship
        local joint = Instance.new("WeldConstraint")
        joint.Part0 = anchor
        joint.Part1 = seat
        joint.Parent = seat
    end
'''
    result=_replace_exact(result,seat_anchor,seat_code+seat_anchor)
    result=_replace_exact(result,"function Service.start(services)\n",
        "function Service.start(services)\n    Service._services = services\n")
    original='''        for id in pairs(SECTIONS) do
            local saved = profile.sections[id]
            if type(saved) == "table" and saved.owned == true then
                placePart(parts, anchor, id)
            end
        end'''
    ordered='''        for _, id in ipairs(ORDER) do
            local saved = profile.sections[id]
            if type(saved) == "table" and saved.owned == true then
                if not placePart(parts, anchor, id) then return end
            end
        end'''
    result=_replace_exact(result,original,ordered)
    original='''    local definition = SECTIONS[id]
    if resources < definition.cost then'''
    changed='''    local definition = SECTIONS[id]
    if definition.parent ~= ROOT_ID then
        local previous = profile.sections[definition.parent]
        if type(previous) ~= "table" or previous.owned ~= true then
            return {success = false, reason = "parent_not_built"}
        end
    end
    if resources < definition.cost then'''
    result=_replace_exact(result,original,changed)
    original='''    inventory.resources = resources - definition.cost
    profile.sections[id] = {owned = true, level = 1,
        performance = definition.performance}
    placePart(parts, anchor, id)'''
    changed='''    if not placePart(parts, anchor, id) then
        return {success = false, reason = "attachment_failed"}
    end
    inventory.resources = resources - definition.cost
    profile.sections[id] = {owned = true, level = 1,
        performance = definition.performance}'''
    result=_replace_exact(result,original,changed)
    method=r'''
-- Expose the SAME player-owned welded actor to a host departure service.
-- Incomplete or unverified physical assembly is not a launchable craft.
function Service.GetOwnedActor(player)
    local services = Service._services
    if not services or typeof(player) ~= "Instance"
        or not player:IsA("Player") or player.Parent ~= Players then return nil end
    local profile = services.PlayerDataManager.GetState(player, "RMMShipSections")
    if not profile or type(profile.sections) ~= "table" then return nil end
    for _, id in ipairs(ORDER) do
        local state = profile.sections[id]
        if type(state) ~= "table" or state.owned ~= true then return nil end
    end
    local ship = shipModels[player]
    if not ship or not ship:IsA("Model")
        or ship:GetAttribute("OwnerUserId") ~= player.UserId then return nil end
    local parts = ship:FindFirstChild("AssembledSections")
    if not parts then return nil end
    for _, id in ipairs(ORDER) do
        if not parts:FindFirstChild(id) then return nil end
    end
    return ship
end
'''
    return _replace_exact(result,"return Service\n",method+"return Service\n")
