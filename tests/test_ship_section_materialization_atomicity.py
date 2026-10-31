"""A resource-paid physical assembly must not charge for an absent part.

The host owns section materialization; the tiny planning model only supplies
bounded section IDs/prices. Both launchable and standalone builders must
preserve the payment-to-world-result invariant.
"""
from roblox_mod_ai.host_ship_attachment import _SERVER
from roblox_mod_ai.host_flight_ready_attachment import render_flight_ready_attachment


def _check_paid_assembly(source):
    p = source.index("local placed, physicallyCreated = pcall(placePart, parts, anchor, id)")
    rollback = source.index('reason = "section_materialization_failed"')
    debit = source.index("inventory.resources = resources - definition.cost")
    grant = source.index("profile.sections[id] = {owned = true")
    assert p < rollback < debit < grant
    assert source.index('if parts:FindFirstChild(id) then', p-230) < p
    assert 'if not placed or physicallyCreated ~= true then' in source
    assert 'if orphan then orphan:Destroy() end' in source
    assert 'if parts:FindFirstChild(id) then' in source
    # Code cannot return a successful purchased section when Part creation
    # threw or returned a failure. The reward record is after guarded Part.
    success = source.index('return {success = true, section = id')
    assert grant < success
    assert 'placePart(parts, anchor, id)\n    local score' not in source


def test_standalone_builder_paid_world_creation_is_fail_closed():
    _check_paid_assembly(_SERVER)


def test_flight_ready_builder_inherits_the_same_atomic_purchase():
    generated = render_flight_ready_attachment(_SERVER)
    _check_paid_assembly(generated)
    assert 'joint.Part0 = anchor' in generated
    assert 'joint.Part1 = part' in generated
    assert 'joint.Parent = part' in generated
    assert 'ship.PrimaryPart = anchor' in generated
    assert 'function Service.GetOwnedActor(player)' in generated
