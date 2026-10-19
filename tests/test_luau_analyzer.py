"""Tests for LuauStaticAnalyzer."""

from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer


def test_luau_analyzer_clean_code():
    analyzer = LuauStaticAnalyzer()
    clean_code = """--!strict
local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")

local function onPlayerAdded(player: Player)
    local success, data = pcall(function()
        return DataStoreService:GetDataStore("Stats"):GetAsync("Player_" .. player.UserId)
    end)
    task.wait(1)
end

Players.PlayerAdded:Connect(onPlayerAdded)
"""
    diags = analyzer.analyze_source(clean_code)
    errors = [d for d in diags if d.severity == "ERROR"]
    warnings = [d for d in diags if d.severity == "WARNING"]
    assert len(errors) == 0
    assert len(warnings) == 0


def test_luau_analyzer_catches_deprecated_and_unsafe_calls():
    analyzer = LuauStaticAnalyzer()
    bad_code = """
local Players = game.Players -- direct indexing warning
local ds = game.DataStoreService:GetDataStore("Test")
local val = ds:GetAsync("Key") -- datastore without pcall

function badFunction()
    wait(2) -- deprecated global wait
    spawn(function() -- deprecated global spawn
        print("Delayed")
    end)
-- missing end for function
"""
    diags = analyzer.analyze_source(bad_code)
    rules_triggered = {d.rule for d in diags}

    assert "DIRECT_SERVICE_INDEXING" in rules_triggered
    assert "DATASTORE_UNSAFE_PCALL" in rules_triggered
    assert "DEPRECATED_GLOBAL_WAIT" in rules_triggered
    assert "DEPRECATED_GLOBAL_SPAWN" in rules_triggered
    assert rules_triggered & {"UNBALANCED_BLOCKS", "LUAU_PARSER_SYNTAX"}


def test_multiline_elseif_does_not_create_phantom_block(monkeypatch):
    """A real generated ShopService uses a two-line elseif expression."""
    from roblox_mod_ai import luau_analyzer
    original = luau_analyzer.shutil.which
    monkeypatch.setattr(luau_analyzer.shutil, "which",
                        lambda name: None if name == "stylua" else original(name))
    source = """--!strict
local function handle(player)
    if not player then
        return false
    elseif (player.Name == "Backpack")
        or (player.Name == "StarterGear") then
        return true
    end
end
return handle
"""
    analyzer = luau_analyzer.LuauStaticAnalyzer()
    errors = [x for x in analyzer.analyze_source(source)
              if x.rule == "UNBALANCED_BLOCKS" and x.severity == "ERROR"]
    assert not errors, errors


def test_fallback_still_rejects_genuinely_unclosed_if(monkeypatch):
    from roblox_mod_ai import luau_analyzer
    original = luau_analyzer.shutil.which
    monkeypatch.setattr(luau_analyzer.shutil, "which",
                        lambda name: None if name == "stylua" else original(name))
    source = """--!strict
if true then
    print('missing end')
"""
    analyzer = luau_analyzer.LuauStaticAnalyzer()
    assert any(d.rule == "UNBALANCED_BLOCKS" for d in analyzer.analyze_source(source))
