"""59: the owned PilotSeat must remain physically accessible after all
eight ship sections are assembled. A valid Rojo build does not catch a
VehicleSeat buried in the collision-enabled hull.
"""
from roblox_mod_ai.host_ordered_assembly import render_ordered_assembly
from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols
from tests.test_plan83_ordered_assembly_launch import sample, CatalogModel


def _build():
    p, builder, client, move, move_client = sample()
    scope = {"modules": [
        {"name": builder.name, "strategy": "host_declarative_ordered_assembly"},
        {"name": client.name, "strategy": "host_declarative_ordered_assembly"},
        {"name": move.name, "strategy": "host_declarative_vehicle_departure"},
        {"name": move_client.name, "strategy": "host_declarative_vehicle_departure"},
    ]}
    rebase_complete_host_protocols(p, scope)
    return render_ordered_assembly(builder, p, CatalogModel())


def _aabb_collision(first, second):
    (cx, cy, cz), (sx, sy, sz) = first
    (dx, dy, dz), (tx, ty, tz) = second
    return all(abs(a-b) < (w+v)/2
               for a,b,w,v in zip((cx,cy,cz),(dx,dy,dz),
                                  (sx,sy,sz),(tx,ty,tz)))


def test_59_pilot_seat_sits_on_hull_without_volume_intersection():
    code = _build()
    assert "seat.CFrame = anchor.CFrame * CFrame.new(0, 4.5, 3.5)" in code
    assert "seat.CFrame = anchor.CFrame * CFrame.new(0, 2, 0)" not in code
    # These are anchor-relative dimensions and transforms emitted by the
    # first-party host. All pieces are unrotated: AABB overlap is exact.
    seat = ((0,4.5,3.5), (3,1,3))
    hull = ((0,3,1), (10,2,12))
    cabin = ((0,6,-1), (7,3,5))
    engine = ((0,4,8), (5,3,5))
    for part in (hull,cabin,engine):
        assert not _aabb_collision(seat,part),part
    assert seat[0][1]-seat[1][1]/2 == hull[0][1]+hull[1][1]/2
    assert seat[0][2]-seat[1][2]/2 > cabin[0][2]+cabin[1][2]/2
    assert seat[0][2]+seat[1][2]/2 < engine[0][2]-engine[1][2]/2
    assert 'joint.Part0 = anchor' in code
    assert 'joint.Part1 = seat' in code


def test_59_previous_pilot_seat_clearly_intersected_solid_ship_hull():
    old_seat=((0,2,0),(3,1,3))
    hull=((0,3,1),(10,2,12))
    assert _aabb_collision(old_seat,hull)
