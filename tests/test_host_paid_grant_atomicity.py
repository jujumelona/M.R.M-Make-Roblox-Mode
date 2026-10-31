"""Host-owned paid grants must not debit on a failed grant or disappear at respawn.

These are emitted-source contract regressions, not a Roblox Studio playtest.
"""
from roblox_mod_ai.host_level_upgrade import _SERVER


def test_owned_tool_grant_has_fail_closed_preflight_before_payment():
    src = _SERVER
    preflight = src.index('local created, granted=pcall(ensureOwnedTool,player)')
    rejection = src.index('return {success=false,reason="weapon_grant_failed"}')
    debit = src.index("coins.Value-=COST")
    ownership = src.index("inventory.items[TARGET]=1")
    assert preflight < rejection < debit < ownership
    assert 'assert(ensureOwnedTool(player)' not in src


def test_respawn_listener_is_not_conditioned_on_ownership_at_login():
    src = _SERVER
    on_ready = src.index("services.PlayerDataManager.OnReady(function(player)")
    handler = src.index("function Service.handleAction", on_ready)
    ready = src[on_ready:handler]
    assert "local function restoreIfOwned()" in ready
    assert "player.CharacterAdded:Connect(function()" in ready
    assert ready.index("player.CharacterAdded:Connect(function()") > ready.index(
        "local function restoreIfOwned()"
    )
    # Purchased state is re-read on each respawn rather than captured at
    # initial OnReady (when first-time customers do not yet own the Tool).
    assert 'GetState(player,"RMMInventory")' in ready
    assert "task.defer(restoreIfOwned)" in ready
    assert "and (inventory.items[TARGET] or 0)>=1" in ready
