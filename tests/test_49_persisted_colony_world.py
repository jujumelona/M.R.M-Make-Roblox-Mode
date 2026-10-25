"""Report49: persisted colonization must spawn a real per-player habitat.

Source-only checks are not a Roblox Studio runtime test.
"""
from tests.test_report41_host_space_actions import fixture
from roblox_mod_ai.host_space_actions import render_host_space_action


def test_planet_colonization_builds_physical_owned_settlement():
    proposal=fixture()
    server=next(m for m in proposal.modules if m.name.startswith("MarkPlanetColonized")
                and m.name.endswith("Server"))
    code=render_host_space_action(server,proposal)
    assert code is not None
    for required in (
        'local function spawnColony(player,markerName)',
        'local name="RMMColony_"..tostring(player.UserId)',
        'colony:SetAttribute("OwnerUserId",player.UserId)',
        'colony:SetAttribute("RMMColonyEstablished",true)',
        'base.Anchored=true',
        'tower.Name="Habitat"',
        'mast.Name="SignalBeacon"',
        'colony.Parent=folder',
        'return {success=false,reason="settlement_unavailable"}',
        'state.colonized=true',
        'if saved.colonized==true then spawnColony(p,',
        'removeColony(p)',
        'settlement="built"',
    ):
        assert required in code,required
    assert code.index('if not spawnColony(player,') < code.index('state.colonized=true')
    assert '__COLONY_CLEANUP__' not in code


def test_non_colony_actions_never_materialize_a_settlement():
    proposal=fixture()
    for name in ("AlienCombat77D3DB1Server","ExtractOtherPlanetMineral77D3DB3Server",
                 "WeaponPerformanceUpgrade213E1D1Server"):
        server=next(m for m in proposal.modules if m.name==name)
        code=render_host_space_action(server,proposal)
        assert code is not None
        assert "local function spawnColony" not in code
        assert "__COLONY_CLEANUP__" not in code


def test_colony_still_requires_real_owned_ship_arrival():
    proposal=fixture()
    server=next(m for m in proposal.modules if m.name.startswith("MarkPlanetColonized")
                and m.name.endswith("Server"))
    code=render_host_space_action(server,proposal)
    assert 'not arrived(player,services,' in code
    assert 'state.planetOwned~=true' in code
    assert 'already_colonized' in code
    assert 'if not placePlanetActionTarget()' in code
