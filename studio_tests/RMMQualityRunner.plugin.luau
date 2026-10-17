--!strict
-- Install as a local Roblox Studio plugin, then click Run RMM E2E.
-- The corresponding test-only Rojo project must be open in Studio.
local StudioTestService = game:GetService("StudioTestService")
local HttpService = game:GetService("HttpService")
local toolbar = plugin:CreateToolbar("RMM Quality")
local button = toolbar:CreateButton("Run RMM E2E", "Test client/server coin, shop and saved-state restoration", "")
button.Click:Connect(function()
    button.Enabled = false
    local ok, result = pcall(function()
        local first = StudioTestService:ExecuteMultiplayerTestAsync(2, {
            suite = "RMM_E2E_V1",
            phase = "play",
        })
        if type(first) ~= "table" or not first.ok then
            error("Client/server run failed: " .. HttpService:JSONEncode(first))
        end
        local second = StudioTestService:ExecuteMultiplayerTestAsync(1, {
            suite = "RMM_E2E_V1",
            phase = "restore",
            userId = first.userId,
            coins = first.coins,
        })
        if type(second) ~= "table" or not second.ok then
            error("Same-user restore run failed: " .. HttpService:JSONEncode(second))
        end
        if not first.jest_suites then error("Jest suites were not verified in Studio") end
        return {
            runner = "StudioTestService",
            checks = {
                jest_suites = first.jest_suites == true,
                client_server = first.client_server == true,
                coin_pickup = first.coin_pickup == true,
                shop_purchase = first.shop_purchase == true,
                datastore_restore = second.ok == true,
            },
            note = "Set place_sha256 from the exact compiled test place before recording receipt.",
        }
    end)
    if ok then
        print("RMM_STUDIO_E2E_RESULT " .. HttpService:JSONEncode(result))
    else
        warn("RMM Studio E2E failed: " .. tostring(result))
    end
    button.Enabled = true
end)
