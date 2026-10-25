"""Regression: physical assembly uses world dimensions, not a ship-specific seat offset."""
from copy import deepcopy
import pytest
from roblox_mod_ai.host_ordered_assembly import (
    section_spatial_layout, render_ordered_assembly,
)
from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols
from tests.test_plan83_ordered_assembly_launch import sample, CatalogModel


def _fixture():
    p,build,ui,move,move_ui=sample()
    rebase_complete_host_protocols(p,{"modules":[
        {"name":build.name,"strategy":"host_declarative_ordered_assembly"},
        {"name":ui.name,"strategy":"host_declarative_ordered_assembly"},
        {"name":move.name,"strategy":"host_declarative_vehicle_departure"},
        {"name":move_ui.name,"strategy":"host_declarative_vehicle_departure"},
    ]})
    return p,build


def _intersect(a,b):
    return all(abs(a["center"][i]-b["center"][i]) <
               (a["size"][i]+b["size"][i])/2 for i in range(3))


def test_generic_model_assembly_boxes_do_not_intersect_for_any_named_sections():
    p,build=_fixture()
    d=p.game_design["dynamic_design"]
    base=("Vehicle_ROOT","Vehicle_PART_HULL","Vehicle_PART_ENGINE")
    names=("WorkshopRoot","Cabinet","Rotor","Arm","Wheel","PowerCell")
    d["world_objects"]=[{"name":name,"class":"Part",
                        "size":[3+i,1+i%3,5+i%2]}
                        for i,name in enumerate(names)]
    d["module_world_objects"][build.module_id]=list(names)
    d["host_ordered_assembly_contracts"]["ConstructionRoute"]["world_entities"]=list(names)
    rows=section_spatial_layout(p,build.name,list(names[1:]))
    assert len(rows)==5
    assert all(not _intersect(a,b)
               for i,a in enumerate(rows) for b in rows[i+1:])
    assert rows[0]["size"]==(4.,2.,6.)
    assert rows[-1]["size"]==(8.,3.,6.)
    assert [x["id"] for x in rows]==list(names[1:])


def test_generated_seat_uses_actual_geometry_and_secure_boarding_not_constant_offset():
    p,build=_fixture()
    code=render_ordered_assembly(build,p,CatalogModel())
    assert "updatePilotSeat(parts.Parent, anchor)" in code
    assert "PointToObjectSpace(corner).Y" in code
    assert "upper+seat.Size.Y/2+0.05" in code
    assert "PilotWeld" in code
    assert "ProximityPrompt" in code
    assert 'Service.GetOwnedActor(player) ~= ship' in code
    assert 'requester ~= player' in code
    assert "seat:Sit(humanoid)" in code
    assert "CFrame.new(0, 4.5, 3.5)" not in code
    assert "[3] = {Vector3.new(" not in code


def test_malformed_world_geometry_must_fail_before_luau_generation():
    p,build=_fixture()
    parts=p.game_design["dynamic_design"]["world_objects"]
    parts[1]["size"]=[float("inf"),1,1]
    with pytest.raises(ValueError,match="LAYOUT_INVALID_SIZE"):
        section_spatial_layout(p,build.name,
                               ["Vehicle_PART_HULL","Vehicle_PART_ENGINE"])


def test_missing_assigned_part_must_fail_closed():
    p,build=_fixture()
    d=p.game_design["dynamic_design"]
    d["module_world_objects"][build.module_id].remove("Vehicle_PART_ENGINE")
    with pytest.raises(ValueError,match="LAYOUT_UNBOUND_PART"):
        section_spatial_layout(p,build.name,
                               ["Vehicle_PART_HULL","Vehicle_PART_ENGINE"])
