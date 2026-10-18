--!strict
-- Execute the ACTUAL model-produced Luau in Lune with mocked Roblox APIs.
-- This is behavioral source E2E, NOT Roblox Studio engine execution.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local process = require("@lune/process")

local project = process.env.RMM_PET_E2E_PROJECT
assert(type(project) == "string" and #project > 0, "RMM_PET_E2E_PROJECT not set")
local serverSource = fs.readFile(project .. "/src/server/CustomPetHatching.luau")
local clientSource = fs.readFile(project .. "/src/client/PetHatchController.client.luau")
assert(#serverSource > 100 and #clientSource > 100, "Missing generated gameplay sources")

local function vector(x: number, y: number, z: number)
    local value = { X = x, Y = y, Z = z, Magnitude = math.sqrt(x * x + y * y + z * z) }
    return setmetatable(value, {
        __sub = function(a, b)
            return vector(a.X - b.X, a.Y - b.Y, a.Z - b.Z)
        end,
    })
end

local egg = { Position = vector(9, 2, 0) }
local remote = { OnServerEvent = {} }
function remote.OnServerEvent:Connect(callback)
    remote.serverCallback = callback
end

local inventory = { children = {} }
local player = { OwnedItems = inventory }
local humanoid = { Health = 100 }
local root = { Position = vector(9, 2, 4) }
local character = {}
function character:FindFirstChild(name)
    if name == "HumanoidRootPart" then return root end
    return nil
end
function character:FindFirstChildOfClass(kind)
    if kind == "Humanoid" then return humanoid end
    return nil
end
player.Character = character
function player:FindFirstChild(name)
    if name == "OwnedItems" then return self.OwnedItems end
    return nil
end
function remote:FireServer(...)
    assert(type(self.serverCallback) == "function", "Missing executable server OnServerEvent")
    self.serverCallback(player, ...)
end

local remotes = {}
function remotes:WaitForChild(name)
    assert(name == "HatchPet", "Unknown Remote: " .. tostring(name))
    return remote
end
local replicatedStorage = {}
function replicatedStorage:WaitForChild(name)
    assert(name == "Remotes", "Unknown folder: " .. tostring(name))
    return remotes
end
local context = {}
function context:BindAction(name, callback, touch, keyboard, gamepad)
    self.callback = callback
    self.name = name
    self.touch = touch
    self.keyboard = keyboard
    self.gamepad = gamepad
end
function context:SetTitle(name, title)
    self.title = title
end
local services = { ReplicatedStorage = replicatedStorage, ContextActionService = context }
local gameMock = {}
function gameMock:GetService(service)
    assert(services[service] ~= nil, "Unknown mocked service: " .. tostring(service))
    return services[service]
end
local workspaceMock = {}
function workspaceMock:WaitForChild(name)
    assert(name == "PetEggStand")
    return egg
end

local instanceMock = {}
function instanceMock.new(kind)
    assert(kind == "StringValue", "Unexpected instance type")
    return setmetatable({}, {
        __newindex = function(self, key, value)
            rawset(self, key, value)
            if key == "Parent" then
                table.insert(value.children, self)
            end
        end,
    })
end
local enum = {
    UserInputState = { Begin = "Begin", End = "End" },
    ContextActionResult = { Pass = "Pass", Sink = "Sink" },
    KeyCode = { E = "E", ButtonX = "ButtonX" },
}

-- Do not expose filesystem, network or OS to the executed gameplay snippets.
local environment = {
    game = gameMock, workspace = workspaceMock, Instance = instanceMock, Enum = enum,
}
local serverModule = luau.load(serverSource, { environment = environment, injectGlobals = true })()
assert(type(serverModule) == "table", "Expected loadable server ModuleScript")
assert(type(serverModule.start) == "function", "Expected server module startup function")
serverModule.start({})
luau.load(clientSource, { environment = environment, injectGlobals = true })()

assert(type(context.callback) == "function", "Missing client input action")
assert(context.touch == true, "Touch input not registered")
assert(context.keyboard == "E" and context.gamepad == "ButtonX", "Missing PC/gamepad bindings")
assert(context.title == "Hatch", "Missing usable touch button title")

local function press(state)
    return context.callback("HatchPetAction", state, {})
end
local function count()
    return #inventory.children
end
assert(count() == 0)
assert(press(enum.UserInputState.Begin) == enum.ContextActionResult.Sink)
assert(count() == 1, "Nearby living player should receive one pet")
assert(inventory.children[1].Value == "Pet")
assert(string.sub(inventory.children[1].Name, 1, 3) == "Pet")

assert(press(enum.UserInputState.End) == enum.ContextActionResult.Pass)
assert(count() == 1, "Key release must not grant a pet")

root.Position = vector(100, 2, 0)
press(enum.UserInputState.Begin)
assert(count() == 1, "Remote may not grant pet to distant player")

root.Position = vector(9, 2, 4)
humanoid.Health = 0
press(enum.UserInputState.Begin)
assert(count() == 1, "Dead humanoid may not receive pet")

humanoid.Health = 100
player.OwnedItems = nil
press(enum.UserInputState.Begin)
assert(count() == 1, "Missing inventory must fail gracefully")

player.OwnedItems = inventory
player.Character = nil
press(enum.UserInputState.Begin)
assert(count() == 1, "Missing character must fail gracefully")

print("LUAAU GAMEPLAY E2E PASS: client action -> Remote -> server state; 6 scenarios")
