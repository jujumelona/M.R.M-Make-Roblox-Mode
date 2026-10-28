"""Codegen authority must be earned by a player/world-rooted executable write.

Real log40 source preflight found transport-only authority contracts. The
planner may now defer their proof to model Luau authoring, but a scratch-table
write must never complete an authority obligation.
"""
import pytest

from roblox_mod_ai.deferred_producer_evidence import (
    has_authoritative_producer_write,
)


def shell(body):
    return (
        "--!strict\n"
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        + body + "\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )


@pytest.mark.parametrize("body", [
    "local scratch = {}\nscratch.value = 1\nreturn true",
    "local state = {}\nstate.resources += 1\nreturn true",
    "Service._services = services\nreturn true",
    "local bogus = {level=0}\nbogus.level += 1\nreturn true",
    "local player = {}\nplayer.level = 1\nreturn true",
    "local targetPart = {}\ntargetPart.level = 1\nreturn true",
])
def test_rejects_local_or_shadowed_state_as_deferred_authority(body):
    assert not has_authoritative_producer_write(shell(body))


@pytest.mark.parametrize("body", [
    'local state = services.PlayerDataManager.GetState(player, "Inventory")\n'
    'if state == nil then return false end\nstate.resources += 1\nreturn true',
    'player:SetAttribute("ShipPerformance", 4)\nreturn true',
    'player.leaderstats.Coins.Value -= 10\nreturn true',
    'local owned = services.PlayerDataManager.GetState(player, "Upgrades")\n'
    'if not owned then return false end\n'
    'local upgrade = owned.entries\nupgrade.level += 1\nreturn true',
    'local node = workspace:FindFirstChild("HarvestNode")\n'
    'if not node then return false end\nnode:SetAttribute("Harvested", true)\nreturn true',
    'targetPart:SetAttribute("Remaining", 0)\nreturn true',
    'local p = Instance.new("Part")\np.Parent = workspace\nreturn true',
])
def test_accepts_rooted_candidate_server_mutation(body):
    assert has_authoritative_producer_write(shell(body))


def test_comments_strings_and_missing_body_are_not_mutations():
    assert not has_authoritative_producer_write(
        shell('-- state.resources += 1\nprint("player:SetAttribute()")\nreturn false')
    )
    assert not has_authoritative_producer_write("local cache={}\ncache.Value=3")


def test_local_untrusted_table_cannot_gain_authority_from_displayed_player_name():
    body = (
        'local state = {}\n'
        'state.players = player.UserId\n'
        'state.Coins = 999\n'
    )
    assert not has_authoritative_producer_write(shell(body))
