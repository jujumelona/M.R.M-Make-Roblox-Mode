--!strict
-- Host-managed panel for RMM-generated actions. Buttons retain their
-- original Activated handlers; only screen layout is consolidated.
local Players = game:GetService("Players")
local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")
local definitions = {
    RMMMiningPanel = {"Ground",10},
    RMMResourceMarket = {"Ground",20},
    RMMShipAssembly = {"Ship",10},
    RMMRankUpgrade = {"Ship",30},
    RMM_WeaponPerformanceUpgrade = {"Ship",40},
    RMMVehicleDeparture = {"Ship",90},
    RMM_AlienCombat = {"Space",10},
    RMM_MarkPlanetColonized = {"Space",20},
    RMM_ExtractOtherPlanetMineral = {"Space",30},
}
local gui = Instance.new("ScreenGui")
gui.Name="RMMActionDock"
gui.ResetOnSpawn=false
gui.DisplayOrder=75
gui.Parent=playerGui
local dock=Instance.new("Frame")
dock.Name="Panel"
dock.BackgroundColor3=Color3.fromRGB(19,28,44)
dock.BorderSizePixel=0
dock.Parent=gui
local corner=Instance.new("UICorner")
corner.CornerRadius=UDim.new(0,12)
corner.Parent=dock
local pad=Instance.new("UIPadding")
pad.PaddingLeft=UDim.new(0,9)
pad.PaddingRight=UDim.new(0,9)
pad.PaddingTop=UDim.new(0,9)
pad.PaddingBottom=UDim.new(0,9)
pad.Parent=dock
local title=Instance.new("TextLabel")
title.Size=UDim2.new(1,-35,0,28)
title.BackgroundTransparency=1
title.Text="RMM | ACTIONS"
title.TextColor3=Color3.fromRGB(244,247,255)
title.TextSize=17
title.TextXAlignment=Enum.TextXAlignment.Left
title.Parent=dock
local toggle=Instance.new("TextButton")
toggle.Size=UDim2.fromOffset(30,28)
toggle.Position=UDim2.new(1,-30,0,0)
toggle.Text="−"
toggle.Parent=dock
local pages={}
local tabs={}
local active="Ground"
local collapsed=false
for n,category in ipairs({"Ground","Ship","Space"}) do
    local tab=Instance.new("TextButton")
    tab.Name=category
    tab.Size=UDim2.new(1/3,-4,0,34)
    tab.Position=UDim2.new((n-1)/3,3,0,35)
    tab.Text=category
    tab.Parent=dock
    tabs[category]=tab
    local page=Instance.new("ScrollingFrame")
    page.Name=category.."Page"
    page.Size=UDim2.new(1,0,1,-80)
    page.Position=UDim2.fromOffset(0,78)
    page.BackgroundTransparency=1
    page.ScrollBarThickness=5
    page.CanvasSize=UDim2.new()
    page.AutomaticCanvasSize=Enum.AutomaticSize.Y
    page.ScrollingDirection=Enum.ScrollingDirection.Y
    page.Parent=dock
    local order=Instance.new("UIListLayout")
    order.SortOrder=Enum.SortOrder.LayoutOrder
    order.Padding=UDim.new(0,8)
    order.Parent=page
    pages[category]=page
end
local camera=workspace.CurrentCamera
local function refresh()
    local viewport=camera and camera.ViewportSize.X or 950
    local width=math.floor(math.clamp(viewport*0.35,218,320))
    dock.Size=collapsed and UDim2.fromOffset(width,48) or UDim2.new(0,width,0.79,0)
    dock.Position=UDim2.new(1,-width-12,0.1,0)
    toggle.Text=collapsed and "+" or "−"
    for category,tab in pairs(tabs) do
        tab.BackgroundColor3=category==active
            and Color3.fromRGB(50,117,169) or Color3.fromRGB(48,57,70)
        tab.Visible=not collapsed
        pages[category].Visible=not collapsed and category==active
    end
end
for category,tab in pairs(tabs) do
    tab.Activated:Connect(function()
        active=category
        collapsed=false
        refresh()
    end)
end
toggle.Activated:Connect(function()
    collapsed=not collapsed
    refresh()
end)
if camera then camera:GetPropertyChangedSignal("ViewportSize"):Connect(refresh) end
refresh()
local seen={}
local watchers={}
local function dockAction(other)
    if seen[other] or not other:IsA("ScreenGui") then return end
    local contract=definitions[other.Name]
    if not contract then return end
    local scroll=other:FindFirstChildWhichIsA("ScrollingFrame")
    local button=other:FindFirstChildWhichIsA("TextButton")
    local result=other:FindFirstChildWhichIsA("TextLabel")
    if not scroll and (not button or not result) then return end
    seen[other]=true
    if watchers[other] then watchers[other]:Disconnect();watchers[other]=nil end
    local card=Instance.new("Frame")
    card.Name="Action_"..other.Name
    card.LayoutOrder=contract[2]
    card.Size=scroll and UDim2.new(1,-8,0,265) or UDim2.new(1,-8,0,102)
    card.BackgroundColor3=Color3.fromRGB(31,43,64)
    card.BorderSizePixel=0
    card.Parent=pages[contract[1]]
    local round=Instance.new("UICorner")
    round.CornerRadius=UDim.new(0,8)
    round.Parent=card
    if scroll then
        scroll.Size=UDim2.new(1,-12,1,-12)
        scroll.Position=UDim2.fromOffset(6,6)
        scroll.Parent=card
    else
        button.Size=UDim2.new(1,-12,0,43)
        button.Position=UDim2.fromOffset(6,6)
        button.TextWrapped=true
        button.Parent=card
        result.Size=UDim2.new(1,-12,0,45)
        result.Position=UDim2.fromOffset(6,52)
        result.TextWrapped=true
        result.Parent=card
    end
    other:Destroy()
end
local function observe(child)
    if not child:IsA("ScreenGui") or not definitions[child.Name] then return end
    if not watchers[child] then
        watchers[child]=child.ChildAdded:Connect(function() dockAction(child) end)
    end
    dockAction(child)
end
playerGui.ChildAdded:Connect(observe)
for _,existing in playerGui:GetChildren() do observe(existing) end
