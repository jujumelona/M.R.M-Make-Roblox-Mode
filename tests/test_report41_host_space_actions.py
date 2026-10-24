"""Regression: report-40 codegen must use server-owned state, not small coder.

Run `python -m pytest tests/test_report40_host_space_actions.py -q`.
"""
from copy import deepcopy

from roblox_mod_ai.host_space_actions import render_host_space_action
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def fixture():
    servers = [
        ('AlienCombat77D3DB1Server', 'combat target and combat state'),
        ('MarkPlanetColonized77D3DB2Server', 'planet owned and colonized state'),
        ('ExtractOtherPlanetMineral77D3DB3Server', 'mineral deposit and owned mineral'),
        ('WeaponPerformanceUpgrade213E1D1Server', "weapon's owner and performance state"),
    ]
    modules = [RobloxModuleSpec(module_id='dyn_builder', name='ShipBuilderServer',
                 kind='server_module', file_path='src/server/ShipBuilderServer.luau',
                 roblox_service='ServerScriptService')]
    remotes, links, typed = {}, {}, {}
    for n, desc in servers:
        rid = n.removesuffix('Server') + 'Action'
        sid = 'dyn_' + n + '_server'
        cid = 'dyn_' + n + '_client'
        modules.extend([
            RobloxModuleSpec(module_id=sid, name=n, kind='server_module',
                file_path='src/server/' + n + '.luau', roblox_service='ServerScriptService',
                description=desc),
            RobloxModuleSpec(module_id=cid, name=n.removesuffix('Server')+'Client',
                kind='client_script', file_path='src/client/' + n + 'Client.client.luau',
                roblox_service='StarterPlayer.StarterPlayerScripts'),
        ])
        remotes[rid] = 'RemoteFunction'
        links[sid], links[cid] = [rid], [rid]
        typed[rid] = {'server':n, 'client':n.removesuffix('Server')+'Client',
             'transport_only':True,
             'contract': {'inputs':[{'id':'selection','type':'text'},
                                    {'id':'quantity','type':'integer'}],
                          'target':{'kind':'none'}}}
    world = [{'name':k, 'class':'Part'} for k in ('AlienTarget77D3DB11',
        'PlayerOwnedPlanet77D3DB21','OtherPlanetMineralDepos77D3DB31',
        'RMMOrbitArrival_7c3d1fecc9')]
    design = {'dynamic_design': {
        'module_remotes':links, 'host_typed_actions':typed, 'remotes':remotes,
        'world_objects':world,
        'host_vehicle_identity_bindings':[{'builder':'ShipBuilderServer', 'server':'LaunchCraftServer'}],
        'host_arrival_materializations':[{'builder':'ShipBuilderServer', 'server':'LaunchCraftServer', 'arrival':'RMMOrbitArrival_7c3d1fecc9'}],
    }}
    return RobloxProposal(requested_prompt='space game', game_title='space',
        description='', game_design=design, modules=modules)


def test_generate_all_eight_not_model_authored():
    proposal = fixture()
    generated = {m.name:render_host_space_action(m, proposal)
                 for m in proposal.modules}
    assert sum(s is not None for s in generated.values()) == 8
    assert generated['ShipBuilderServer'] is None
    for n, code in generated.items():
        if code is None: continue
        assert all(placeholder not in code for placeholder in
                   ('__ACTION__','__ARRIVAL__','__TARGET__','__NAMESPACE__',
                    '__BUILDER__','__PLACE_TARGET__','__ENSURE_TARGET__','__OFFSET_X__', '__OFFSET_Z__'))
        if n.endswith('Server'):
            assert 'function Service.handleAction' in code
            assert 'services.PlayerDataManager.GetState' in code
            assert 'recent[player]' in code
            if n.startswith('AlienCombat'):
                assert 'state.planetOwned=true' in code
            if n.startswith('MarkPlanetColonized'):
                assert 'state.planetOwned~=true' in code
            if n.startswith('ExtractOtherPlanetMineral'):
                assert 'state.colonized~=true' in code
            if n.startswith('WeaponPerformanceUpgrade'):
                assert 'coins.Value-=100' in code
        else:
            assert 'remote:InvokeServer' in code
            assert 'selection=' in code


def test_incomplete_world_and_builder_fail_closed():
    proposal = fixture()
    combat = next(x for x in proposal.modules if x.name=='AlienCombat77D3DB1Server')
    proposal.game_design['dynamic_design']['world_objects'] = []
    assert render_host_space_action(combat, proposal) is None
    proposal = fixture()
    proposal.game_design['dynamic_design']['host_vehicle_identity_bindings'] = []
    assert render_host_space_action(combat, proposal) is None


def test_mismatched_action_contract_does_not_bypass_guard():
    proposal = fixture()
    combat = next(x for x in proposal.modules if x.name=='AlienCombat77D3DB1Server')
    d = proposal.game_design['dynamic_design']
    d['host_typed_actions']['AlienCombat77D3DB1Action']['contract']['inputs'][0]['id'] = 'targetUserId'
    assert render_host_space_action(combat, proposal) is None


def test_valid_world_relocated_within_arrival_range():
    proposal = fixture()
    for name in ('AlienCombat77D3DB1Server', 'MarkPlanetColonized77D3DB2Server',
                 'ExtractOtherPlanetMineral77D3DB3Server'):
        module = next(x for x in proposal.modules if x.name == name)
        code = render_host_space_action(module, proposal)
        assert code is not None
        assert 'placePlanetActionTarget' in code
        assert 'if not placePlanetActionTarget() then return' in code
        assert 'RMMOrbitArrival_7c3d1fecc9' in code
        assert 'target.CFrame=marker.CFrame*CFrame.new(' in code


def test_no_invented_or_unlinked_arrival():
    proposal = fixture()
    module = next(x for x in proposal.modules if x.name == 'AlienCombat77D3DB1Server')
    proposal.game_design['dynamic_design']['host_arrival_materializations'][0]['arrival'] = 'Unknown'
    assert render_host_space_action(module, proposal) is None
