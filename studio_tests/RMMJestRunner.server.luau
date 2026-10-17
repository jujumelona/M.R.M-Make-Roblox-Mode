--!strict
-- Runs Jest Roblox ONLY during a StudioTestService RMM E2E test.
local RunService = game:GetService("RunService")
if not RunService:IsStudio() then return end
local StudioTestService = game:GetService("StudioTestService")
local args = StudioTestService:GetTestArgs()
if type(args) ~= "table" or args.suite ~= "RMM_E2E_V1" or args.phase ~= "play" then return end

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local suites = ReplicatedStorage:WaitForChild("TestSuites", 15)
local dev = ReplicatedStorage:WaitForChild("DevPackages", 15)
if not suites or not dev then
    ReplicatedStorage:SetAttribute("RMM_JEST_STATUS", "FAILED")
    warn("RMM: Jest suites or development packages missing")
    return
end

local ok, message = pcall(function()
    local Jest = require(dev:WaitForChild("Jest"))
    local status, result = Jest.runCLI(suites, { verbose = false, ci = true }, { suites }):awaitStatus()
    if status == "Rejected" then error(tostring(result)) end
    if not result or not result.results or not result.results.success then
        error("Jest returned a failing test result")
    end
end)
ReplicatedStorage:SetAttribute("RMM_JEST_STATUS", ok and "PASSED" or "FAILED")
if not ok then warn("RMM real Jest test failure: " .. tostring(message)) end
