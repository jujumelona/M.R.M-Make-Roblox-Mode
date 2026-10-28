"""Regression for failure_logs (27), proposal (63), commit 3b2537ff.

Two independently host-compiled typed actions legally read the arrival pad
owned by their verified launcher/builder chain. An unrelated or forged
workspace read must still be rejected at module generation.
"""
from copy import deepcopy
from roblox_mod_ai.host_verified_typed_effects import render_verified_effect
from roblox_mod_ai.world_object_abi import world_names, world_lookup_errors
from roblox_mod_ai.spec import ModuleKind
from test_log26_real_proposal_regression import _log26_fixture

LOG27_ARRIVAL = "RMMOrbitArrival_c2be30531a"


def _log27(role):
    proposal, module = _log26_fixture(role)
    design = proposal.game_design["dynamic_design"]
    old_arrival = design["host_arrival_materializations"][0]["arrival"]
    design["host_arrival_materializations"][0]["arrival"] = LOG27_ARRIVAL
    for obj in design["world_objects"]:
        if obj["name"] == old_arrival:
            obj["name"] = LOG27_ARRIVAL
    return proposal, module


def test_log27_verified_actions_can_read_only_their_exact_arrival():
    for role, target in (
        ("combat", "AlienEntitiesSpawnedOnT77D3DB11"),
        ("harvest", "SpecialMineralDeposit77D3DB31"),
    ):
        p, module = _log27(role)
        assert module.kind == ModuleKind.SERVER_MODULE
        generated = render_verified_effect(module, p)
        assert generated is not None
        assert f'workspace:FindFirstChild("{LOG27_ARRIVAL}", true)' in generated
        _, allowed = world_names(p, module)
        assert LOG27_ARRIVAL in allowed
        assert target in allowed
        assert "ResourceNode45332811" not in allowed
        assert world_lookup_errors(generated, p, module) == []


def test_log27_reject_undeclared_or_unlinked_arrival_even_for_host_action():
    for role in ("combat", "harvest"):
        p, module = _log27(role)
        generated = render_verified_effect(module, p)
        assert generated is not None
        forged = generated.replace(LOG27_ARRIVAL, "RMMOrbitArrival_forged")
        assert "WORLD_OBJECT_NAME_UNDECLARED" in "\n".join(
            world_lookup_errors(forged, p, module))
        wrong = deepcopy(p)
        wrong.game_design["dynamic_design"]["host_arrival_materializations"] = []
        assert render_verified_effect(module, wrong) is None
        _, allowed = world_names(wrong, module)
        assert LOG27_ARRIVAL not in allowed
        assert "WORLD_OBJECT_NAME_UNDECLARED" in "\n".join(
            world_lookup_errors(generated, wrong, module))


def test_log27_non_verified_model_module_cannot_read_orbit_pad():
    p, module = _log27("combat")
    model_authored = deepcopy(module)
    model_authored.description = "Only draw an unrelated decorative HUD marker"
    assert render_verified_effect(model_authored, p) is None
    _, allowed = world_names(p, model_authored)
    assert LOG27_ARRIVAL not in allowed
    code = f'local pad = workspace:FindFirstChild("{LOG27_ARRIVAL}", true)'
    assert world_lookup_errors(code, p, model_authored)


def test_log27_client_and_other_server_cannot_inherit_world_read():
    p, module = _log27("harvest")
    client = next(m for m in p.modules if m.kind == ModuleKind.CLIENT_SCRIPT)
    _, allowed = world_names(p, client)
    assert LOG27_ARRIVAL not in allowed
    code = f'local pad = workspace:FindFirstChild("{LOG27_ARRIVAL}", true)'
    assert world_lookup_errors(code, p, client)
    builder = next(m for m in p.modules if m.name == "CraftBuilderServer")
    assert world_lookup_errors(code, p, builder)


def test_log27_renaming_bound_target_breaks_authorization():
    p, module = _log27("combat")
    design = p.game_design["dynamic_design"]
    design["module_world_objects"][module.module_id] = [
        "SpecialMineralDeposit77D3DB31"
    ]
    assert render_verified_effect(module, p) is None
    _, allowed = world_names(p, module)
    assert LOG27_ARRIVAL not in allowed
