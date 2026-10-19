"""Make the inspected builtin profile template callable for generated games.

Stock games keep their existing auto-running Script. Dynamic games use the
same lease/loading/leaderstats implementation behind a host-owned service.
Anchored replacements fail loudly if that first-party template changes.
"""
from __future__ import annotations


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Builtin player-data template adapter anchor changed: " + old[:70])
    return source.replace(old, new, 1)


def render_callable_player_data(source: str) -> str:
    source = _replace(source, "local sessionData:", """local PlayerDataManager = {}
local started = false
local loading = {}
local profilePlayers = {}
local queuedPlayers = {}
local onPlayerAdded
local function restartQueued(userId)
    local nextPlayer = queuedPlayers[userId]
    queuedPlayers[userId] = nil
    if nextPlayer and nextPlayer.Parent == Players then
        task.spawn(onPlayerAdded, nextPlayer)
    end
end
local readyCallbacks = {}
local savePlayerData

local sessionData:""")
    source = _replace(source, "    lockUntil: number?,\n}",
                      "    lockUntil: number?,\n    gameState: {[string]: any}?,\n}")
    source = _replace(source, "    local key = getPlayerKey(userId)\n    local sessionToken", """    if sessionData[userId] or loading[userId] then
        if profilePlayers[userId] ~= player and loading[userId] ~= player then
            queuedPlayers[userId] = player
        end
        return
    end
    loading[userId] = player
    local key = getPlayerKey(userId)
    local sessionToken""")
    source = _replace(source, "local function onPlayerAdded(player: Player)", "onPlayerAdded = function(player: Player)")
    source = _replace(source, "    if not success or lockedByOther or rawData == nil then\n", """    loading[userId] = nil
    if not success or lockedByOther or rawData == nil then
        restartQueued(userId)
""")
    source = _replace(source, "    sessionLocks[userId] = sessionToken\n", """    sessionLocks[userId] = sessionToken
    profilePlayers[userId] = player
    if player.Parent ~= Players then
        savePlayerData(player, true)
        sessionData[userId] = nil
        sessionLocks[userId] = nil
        profilePlayers[userId] = nil
        restartQueued(userId)
        return
    end
""")
    source = _replace(source, "    stageVal.Parent = leaderstats\n", """    stageVal.Parent = leaderstats
    for _, callback in readyCallbacks do
        task.spawn(callback, player)
    end
""")
    # The standalone Script now snapshots Coins/Level/Stage/OwnedItems before
    # every session renewal. This callable host variant instead delegates that
    # entire operation to savePlayerData(player, false), which performs the
    # same snapshot and keeps the session lease. Remove the template's
    # redundant pre-renewal snapshot, otherwise Selene correctly reports
    # shadowing and four unused variables in generated PlayerDataManager.luau.
    snapshot_start = source.index(
        "            -- Persist live session progress during each lease renewal."
    )
    renewal_start = source.index(
        "            local renewed, current = retryWithBackoff", snapshot_start
    )
    source = source[:snapshot_start] + source[renewal_start:]
    begin = source.index("            local renewed, current = retryWithBackoff")
    end = source.index('                player:Kick("Your profile session lock', begin)
    source = source[:begin] + "            if not savePlayerData(player, false) then\n" + source[end:]
    source = _replace(source, "local function savePlayerData(player: Player): boolean", "savePlayerData = function(player: Player, release: boolean?): boolean")
    source = _replace(source, "    if isSaving[userId] then return false end", """    if isSaving[userId] and release == false then return false end
    while isSaving[userId] do task.wait(0.1) end
    if sessionData[userId] ~= data then return true end""")
    source = _replace(source, "    local success, savedData, err = retryWithBackoff(function()", """    local sessionToken = sessionLocks[userId]
    local copied, snapshot = pcall(function()
        return HttpService:JSONDecode(HttpService:JSONEncode(data))
    end)
    if not copied or not sessionToken then
        isSaving[userId] = false
        warn("Profile contains non-serializable state or no session lease for " .. tostring(userId))
        return false
    end
    if release == false then
        snapshot.lockToken = sessionToken
        snapshot.lockUntil = os.time() + 120
    else
        snapshot.lockToken = nil
        snapshot.lockUntil = nil
    end
    local success, savedData, err = retryWithBackoff(function()""")
    source = _replace(source, "current.lockToken ~= sessionLocks[userId]", "current.lockToken ~= sessionToken")
    source = _replace(source, "            data.lockToken = nil\n            data.lockUntil = nil\n            return data", "            return snapshot")
    source = _replace(source, """    savePlayerData(player)
    sessionData[userId] = nil
    sessionLocks[userId] = nil
    studioEphemeral[userId] = nil
end""", """    if profilePlayers[userId] ~= player then return end
    savePlayerData(player)
    sessionData[userId] = nil
    sessionLocks[userId] = nil
    studioEphemeral[userId] = nil
    profilePlayers[userId] = nil
    restartQueued(userId)
end""")
    marker = "Players.PlayerAdded:Connect(onPlayerAdded)"
    if source.count(marker) != 1:
        raise ValueError("Builtin profile startup anchor changed")
    definitions, startup = source.split(marker)
    return definitions + '''
-- Server-only, live JSON-compatible state. Never return this table to a client.
-- No state is fabricated before the exclusive profile load has completed.
function PlayerDataManager.GetState(player, namespace)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or player.Parent ~= Players then return nil end
    if type(namespace) ~= "string" or #namespace == 0 or #namespace > 100 then return nil end
    local data = sessionData[player.UserId]
    if not data or profilePlayers[player.UserId] ~= player then return nil end
    if type(data.gameState) ~= "table" then data.gameState = {} end
    if type(data.gameState[namespace]) ~= "table" then data.gameState[namespace] = {} end
    return data.gameState[namespace]
end

function PlayerDataManager.OnReady(callback)
    assert(type(callback) == "function", "OnReady requires a callback")
    table.insert(readyCallbacks, callback)
    for _, player in Players:GetPlayers() do
        if sessionData[player.UserId] and profilePlayers[player.UserId] == player then task.spawn(callback, player) end
    end
    return function()
        local index = table.find(readyCallbacks, callback)
        if index then table.remove(readyCallbacks, index) end
    end
end

function PlayerDataManager.start(_services)
    if started then return end
    started = true
''' + marker + startup + '''
    for _, player in Players:GetPlayers() do
        task.spawn(onPlayerAdded, player)
    end
end
return PlayerDataManager
'''
