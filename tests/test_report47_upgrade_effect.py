"""Report47: server-owned upgrades must be consumed by gameplay, not UI-only stats."""

from roblox_mod_ai.host_space_actions import render_host_space_action
from tests.test_report41_host_space_actions import fixture


def test_space_combat_consumes_owned_weapon_and_crew_progress():
    p = fixture()
    combat = next(m for m in p.modules
                  if m.name == "AlienCombat77D3DB1Server")
    code = render_host_space_action(combat, p)
    assert code is not None
    for marker in (
        'GetState(player,"RMMInventory")',
        'GetState(player,"RMMWeaponProgress")',
        'GetState(player,"RMMRankProgress")',
        'items.owned_weapon',
        'ranks.crew_performance_state',
        'ranks.owned_weapon',
        'if owned>=1 then',
        'if tier>=1 then damage+=1 end',
        'if crew>=3 then damage+=1 end',
        'damage=math.min(3,damage)',
        'hp=math.max(0,hp-damage)',
        'return {success=true,hp=hp,damage=damage',
    ):
        assert marker in code, marker
    assert "hp-=1" not in code
    assert 'damage=args.quantity' not in code
    assert 'invalid_upgrade_state' in code


def test_source_linked_combat_rejects_missing_world_or_actor():
    p = fixture()
    combat = next(m for m in p.modules
                  if m.name == "AlienCombat77D3DB1Server")
    p.game_design["dynamic_design"]["host_vehicle_identity_bindings"] = []
    assert render_host_space_action(combat, p) is None
