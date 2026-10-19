--!strict
-- Run actual generated host persistence; only engine/storage boundaries are mocked.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local serde = require("@lune/serde")
local process = require("@lune/process")
local source = fs.readFile(process.env.RMM_PLAYER_DATA_SOURCE)
local function clone(value)
    return serde.decode("json", serde.encode("json", value))
end
local queue, sleeping = {}, {}
local blockedJob, blockNextSave
local function spawn(fn, ...)
    table.insert(queue, {coroutine.create(fn), table.pack(...)})
end
local function resume(job)
    local ok, delay = coroutine.resume(job[1], table.unpack(job[2], 1, job[2].n))
    assert(ok, tostring(delay))
    if coroutine.status(job[1]) ~= "dead" then
        local nextJob = {job[1], table.pack()}
        if delay == "blocked_store" then blockedJob = nextJob
        else table.insert(sleeping, nextJob) end
    end
end
local function drain()
    while #queue > 0 do resume(table.remove(queue, 1)) end
end
local tasks = {spawn = spawn}
function tasks.wait(seconds)
    if seconds == 45 then return coroutine.yield(45) end
    if blockedJob then
        local pending = blockedJob
        blockedJob = nil
        resume(pending)
    end
    drain()
    return seconds
end
local function signal()
    local callbacks = {}
    return {
        Connect = function(_, callback)
            table.insert(callbacks, callback)
            return {Disconnect = function() end}
        end,
        Fire = function(_, ...)
            for _, callback in callbacks do callback(...) end
        end,
        Count = function() return #callbacks end,
    }
end
local function instance(class)
    local value = {ClassName = class, Name = "", children = {}, Value = 0}
    function value:IsA(name) return self.ClassName == name end
    function value:FindFirstChild(name) return self.children[name] end
    function value:GetChildren()
        local result = {}
        for _, child in self.children do table.insert(result, child) end
        return result
    end
    return setmetatable(value, {__newindex = function(self, key, child)
        rawset(self, key, child)
        if key == "Parent" and child ~= nil and child.children then
            child.children[self.Name] = self
        end
    end})
end
local online = {}
local players = {PlayerAdded = signal(), PlayerRemoving = signal()}
function players:GetPlayers() return table.clone(online) end
local function player(id)
    local p = instance("Player")
    p.UserId = id
    p.Name = "Player" .. id
    p.Parent = players
    function p:Kick(message) self.kicked = message end
    return p
end
local stored, fail, disconnectDuringLoad = {}, false, nil
local loadReplacement
local store = {}
function store:UpdateAsync(key, transform)
    if fail then error("injected storage unavailable") end
    if blockNextSave then
        blockNextSave = false
        coroutine.yield("blocked_store")
    end
    local result = transform(stored[key] and clone(stored[key]) or nil)
    if disconnectDuringLoad then
        disconnectDuringLoad.Parent = nil
        loadReplacement = player(disconnectDuringLoad.UserId)
        players.PlayerAdded:Fire(loadReplacement)
        disconnectDuringLoad = nil
    end
    if result ~= nil then stored[key] = clone(result) end
    return result and clone(result) or nil
end
local ids = 0
local http = {}
function http:GenerateGUID(_)
    ids += 1
    return "session-" .. ids
end
function http:JSONEncode(value) return serde.encode("json", value) end
function http:JSONDecode(value) return serde.decode("json", value) end
local dataStoreService = {}
function dataStoreService:GetDataStore(_) return store end
local close
local gameMock = {}
function gameMock:GetService(name)
    return ({Players = players, HttpService = http, DataStoreService = dataStoreService})[name]
end
function gameMock:BindToClose(callback) close = callback end
local profile = luau.load(source, {environment = {
    game = gameMock, Instance = {new = instance}, task = tasks,
    typeof = function(value)
        return type(value) == "table" and value.ClassName and "Instance" or type(value)
    end,
}, injectGlobals = true})()
assert(type(profile) == "table", "Host profile must return a callable service")
assert(players.PlayerAdded.Count() == 0, "Requiring a service must not start connections")
local first = player(11)
online = {first}
profile.start({})
local ready = {}
profile.OnReady(function(p) ready[p.UserId] = (ready[p.UserId] or 0) + 1 end)
assert(profile.GetState(first, "ShipService") == nil, "No fake profile before storage load")
drain()
assert(ready[11] == 1, "Current player was not announced ready exactly once")
local state = profile.GetState(first, "ShipService")
state.parts = {"hull", "engine"}
state.ore = 17
first:FindFirstChild("leaderstats"):FindFirstChild("Coins").Value = 140
local beforeRenew = sleeping
sleeping = {}
for _, job in beforeRenew do resume(job) end
drain()
assert(stored.Player_11.gameState.ShipService.ore == 17, "Periodic save lost custom progress")
assert(stored.Player_11.coins == 140, "Periodic save lost authoritative currency")
assert(stored.Player_11.lockToken ~= nil, "Periodic save released an active lease")
local retained = stored.Player_11.lockToken
assert(profile.GetState(first, "OtherService").ore == nil, "Namespaces shared a table")
state.ore = 25
blockNextSave = true
local inFlight = sleeping
sleeping = {}
for _, job in inFlight do resume(job) end
assert(blockedJob ~= nil, "Autosave did not enter injected storage wait")
state.ore = 29
first.Parent = nil
local earlyRejoin = player(11)
online = {earlyRejoin}
players.PlayerAdded:Fire(earlyRejoin)
players.PlayerRemoving:Fire(first)
if blockedJob then
    local pending = blockedJob
    blockedJob = nil
    resume(pending)
end
assert(stored.Player_11.gameState.ShipService.ore == 29, "Leaving during autosave lost a newer game mutation")
assert(stored.Player_11.lockToken == nil, "Disconnect did not release lease")
assert(stored.Player_11.gameState.ShipService.ore == 29, "Disconnect lost progress")
assert(profile.GetState(first, "ShipService") == nil)
drain()
local second = earlyRejoin
assert(profile.GetState(second, "ShipService") ~= nil, "Joining during final save lost the replacement player")
players.PlayerRemoving:Fire(first)
assert(profile.GetState(second, "ShipService") ~= nil, "Late old-player removal cleared the replacement profile")
assert(profile.GetState(second, "ShipService").parts[2] == "engine", "Rejoin lost assembled parts")
assert(profile.GetState(second, "ShipService").ore == 29, "Rejoin reset ore")
assert(stored.Player_11.lockToken ~= retained, "Rejoin reused another session's token")
local startCount = players.PlayerAdded.Count()
profile.start({})
assert(players.PlayerAdded.Count() == startCount, "start registered duplicate events")
local locked = player(12)
stored.Player_12 = {coins = 900, lockToken = "another-server", lockUntil = os.time() + 120}
players.PlayerAdded:Fire(locked)
assert(locked.kicked ~= nil and profile.GetState(locked, "ShipService") == nil)
assert(stored.Player_12.coins == 900, "Locked profile was overwritten")
fail = true
local unavailable = player(13)
players.PlayerAdded:Fire(unavailable)
assert(unavailable.kicked ~= nil, "Storage failure created a fake new profile")
assert(stored.Player_13 == nil)
fail = false
local left = player(14)
disconnectDuringLoad = left
players.PlayerAdded:Fire(left)
assert(stored.Player_14.lockToken == nil, "Player leaving during load stranded its lease")
assert(profile.GetState(left, "ShipService") == nil)
drain()
assert(profile.GetState(loadReplacement, "ShipService") ~= nil, "Joining during old load lost the replacement player")
assert(type(close) == "function", "Shutdown flushing not registered")
close()
assert(stored.Player_11.lockToken == nil, "Shutdown did not release lease")
assert(stored.Player_11.gameState.ShipService.ore == 29)
print("PLAYER DATA E2E PASS: readiness, namespaces, save/reload, currency, leases, failure, leave-during-load, shutdown")
