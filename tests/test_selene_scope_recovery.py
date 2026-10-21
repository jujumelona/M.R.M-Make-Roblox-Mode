"""Replays a syntactically valid but undefined-global host-scaffolded module."""
import shutil
import pytest

from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer

_BAD = """--!strict
local Players = game:GetService("Players")
local Service = {}
function Service.start(services)
    assert(type(services) == "table")
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") then return false end
    if not Services.PlayerDataManager.GetState(player, "RMMInventory") then return false end
    local profile = services.PlayerDataManager.GetState(player, "RMMInventory")
    if table.find(profile.items, hullId) == nil then return false end
    if player.leaderstats.Coins.Value < costPerSection then return false end
    profile.items.hull = true
    return true
end
return Service
"""

_GOOD = """--!strict
local Players = game:GetService("Players")
local Service = {}
function Service.start(services)
    Service._services = services
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") then return false end
    local profile = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not profile then return false end
    local hullId, costPerSection = "hull", 10
    if type(profile.items) ~= "table" then return false end
    if profile.items[hullId] then return false end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or coins.Value < costPerSection then return false end
    coins.Value -= costPerSection
    profile.items[hullId] = true
    return true
end
return Service
"""


@pytest.mark.skipif(not shutil.which("selene"), reason="Real Selene is required")
def test_real_selene_rejects_undefined_globals_missed_by_luau_parser():
    analyzer = LuauStaticAnalyzer()
    bad = analyzer.analyze_source(_BAD, "src/server/ShipAssembly.luau")
    errors = [d.rule for d in bad if d.severity == "ERROR"]
    assert "SELENE_UNDEFINED_VARIABLE" in errors, [(d.rule, d.message) for d in bad]
    assert "LUAU_PARSER_SYNTAX" not in errors


@pytest.mark.skipif(not shutil.which("selene"), reason="Real Selene is required")
def test_real_selene_accepts_same_gameplay_with_declared_variables():
    analyzer = LuauStaticAnalyzer()
    good = analyzer.analyze_source(_GOOD, "src/server/ShipAssembly.luau")
    assert not [d for d in good if d.rule.startswith("SELENE_") and d.severity == "ERROR"], [
        (d.rule, d.message) for d in good]
