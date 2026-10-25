"""Report50: unique colony leases and recovery of persisted world projection.

Source generator contract tests; actual physics/multiplayer needs Roblox Studio.
"""
from roblox_mod_ai.host_space_actions import render_host_space_action
from tests.test_report41_host_space_actions import fixture


def _colony_source():
    p=fixture()
    m=next(x for x in p.modules if x.name.startswith("MarkPlanetColonized")
           and x.name.endswith("Server"))
    return render_host_space_action(m,p)


def test_colony_slots_scan_existing_owners_before_assignment():
    src=_colony_source()
    assert src is not None
    assert 'for _,other in folder:GetChildren() do' in src
    assert 'local ownedSlot=other:GetAttribute("RMMColonySlot")' in src
    assert 'local candidate=(preferred+offset)%20' in src
    assert 'if not used[candidate] then slot=candidate;break end' in src
    assert 'if slot==nil then return false end' in src
    assert 'colony:SetAttribute("RMMColonySlot",slot)' in src
    assert src.index('if slot==nil then return false end') < src.index('colony.Parent=folder')


def test_colony_can_reproject_without_duplicate_ownership_write():
    src=_colony_source()
    assert src is not None
    assert 'if state.colonized==true then' in src
    assert 'settlement="restored",already=true' in src
    a=src.index('if state.colonized==true then')
    b=src.index('state.colonized=true',a)
    assert 'spawnColony(player,' in src[a:b]
    assert src[a:b].count('state.colonized=')==0
    assert 'reason="already_colonized"' not in src
    assert 'removeColony(p)' in src
    assert '__COLONY_CLEANUP__' not in src


def test_other_space_roles_do_not_allocate_colony_slots():
    p=fixture()
    for role in ("AlienCombat","ExtractOtherPlanetMineral","WeaponPerformanceUpgrade"):
        m=next(x for x in p.modules if x.name.startswith(role) and x.name.endswith("Server"))
        src=render_host_space_action(m,p)
        assert src and 'RMMColonySlot' not in src
