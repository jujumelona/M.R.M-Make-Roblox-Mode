"""Install a deterministic, order-preserving client HUD for generated actions.

The built-in rank/ship/space modules create ScreenGuis independently. Without
an aggregator several rank buttons occupy exactly the same coordinates and are
inaccessible. This program is added to src/client before static/Place build,
without changing their gameplay code or server action contracts.
"""
from __future__ import annotations
from pathlib import Path
import re

HUD_FILE="RMMHUDLayout.client.luau"

HUD_SOURCE=r'''--!strict
-- Central, single-owner visual layout. Individual action LocalScripts still
-- own their original buttons, callbacks, network validation, and status.
local Players=game:GetService("Players")
local player=Players.LocalPlayer
local playerGui=player:WaitForChild("PlayerGui")
local gui=Instance.new("ScreenGui")
gui.Name="RMMUnifiedHUD"
gui.ResetOnSpawn=false
gui.DisplayOrder=25
gui.Parent=playerGui

local toggle=Instance.new("TextButton")
toggle.Name="ToggleHUD"
toggle.AnchorPoint=Vector2.new(1,0)
toggle.Position=UDim2.new(1,-12,0,40)
toggle.Size=UDim2.fromOffset(112,36)
toggle.Text="Actions: Hide"
toggle.Parent=gui

local scroll=Instance.new("ScrollingFrame")
scroll.Name="ActionList"
scroll.AnchorPoint=Vector2.new(1,0)
scroll.Position=UDim2.new(1,-12,0,82)
scroll.Size=UDim2.new(0,302,1,-106)
scroll.CanvasSize=UDim2.new(0,0,0,0)
scroll.AutomaticCanvasSize=Enum.AutomaticSize.Y
scroll.ScrollBarThickness=7
scroll.BackgroundTransparency=0.16
scroll.Parent=gui
local list=Instance.new("UIListLayout")
list.Padding=UDim.new(0,8)
list.SortOrder=Enum.SortOrder.LayoutOrder
list.Parent=scroll
local padding=Instance.new("UIPadding")
padding.PaddingLeft=UDim.new(0,5)
padding.PaddingRight=UDim.new(0,5)
padding.PaddingTop=UDim.new(0,5)
padding.PaddingBottom=UDim.new(0,8)
padding.Parent=scroll

toggle.Activated:Connect(function()
    scroll.Visible=not scroll.Visible
    toggle.Text=scroll.Visible and "Actions: Hide" or "Actions: Show"
end)

local nextSection=0
local sections=setmetatable({},{__mode="k"})
local function isActionGui(candidate)
    if not candidate:IsA("ScreenGui") or candidate==gui then return false end
    if candidate.Name=="RMMOnboarding" or candidate.Name=="RMMUnifiedHUD" then return false end
    return candidate.Name=="RMMRankUpgrade"
        or candidate.Name=="RMMShipAssembly"
        or candidate.Name=="RMMResourceMarket"
        or candidate.Name=="RMMVehicleDeparture"
        or candidate.Name=="RMMMiningPanel"
        or candidate.Name=="RMMPlayerTrading"
        or candidate.Name=="RMMCurrencyExchange"
        or candidate.Name=="RMMColonyAlias"
        or string.sub(candidate.Name,1,4)=="RMM_"
end

local function sectionFor(candidate)
    if sections[candidate] then return sections[candidate] end
    nextSection+=1
    local frame=Instance.new("Frame")
    frame.Name="ActionSection"..tostring(nextSection)
    frame.LayoutOrder=nextSection
    frame.Size=UDim2.new(1,-3,0,0)
    frame.AutomaticSize=Enum.AutomaticSize.Y
    frame.BackgroundTransparency=0.2
    frame.Parent=scroll
    local layout=Instance.new("UIListLayout")
    layout.SortOrder=Enum.SortOrder.LayoutOrder
    layout.Padding=UDim.new(0,3)
    layout.Parent=frame
    local heading=Instance.new("TextLabel")
    heading.Name="ActionTitle"
    heading.LayoutOrder=0
    heading.Size=UDim2.new(1,0,0,23)
    heading.BackgroundTransparency=0.25
    heading.Text=candidate.Name
    heading.TextScaled=false
    heading.TextSize=14
    heading.TextWrapped=true
    heading.Parent=frame
    sections[candidate]={frame=frame,index=0}
    return sections[candidate]
end

local function moveControl(candidate,child)
    if not child:IsA("GuiObject") then return end
    if child.Parent~=candidate then return end
    local section=sectionFor(candidate)
    section.index+=1
    child.LayoutOrder=section.index
    local originalHeight=child.Size.Y.Offset
    local height=math.max(32,math.min(originalHeight>0 and originalHeight or 44,370))
    child.AnchorPoint=Vector2.new(0,0)
    child.Position=UDim2.fromOffset(0,0)
    child.Size=UDim2.new(1,0,0,height)
    child.Parent=section.frame
end

local function register(candidate)
    if not isActionGui(candidate) or sections[candidate] then return end
    -- Connect BEFORE scanning so controls created just after Parent assignment
    -- are never lost. Removing a moved child does not retrigger ChildAdded.
    candidate.ChildAdded:Connect(function(child)
        moveControl(candidate,child)
    end)
    for _,child in candidate:GetChildren() do
        moveControl(candidate,child)
    end
end
playerGui.ChildAdded:Connect(register)
for _,child in playerGui:GetChildren() do register(child) end
'''


def install_host_hud(project_dir: Path) -> bool:
    """Include a real LocalScript whenever multiple generated action UIs exist.

    No source-string substitution and no boilerplate appends inside player
    model code; Rojo discovers the file from src/client. Idempotent on retries.
    """
    client=Path(project_dir)/"src"/"client"
    if not client.is_dir():
        return False
    eligible=0
    for path in client.glob("*.client.luau"):
        if path.name==HUD_FILE:
            continue
        source=path.read_text(encoding="utf-8")
        if (re.search(r'Instance\.new\(\s*["\x27]ScreenGui["\x27]\s*\)', source)
                and re.search(r'gui\.Name\s*=\s*["\x27]RMM', source)
                and 'RMMOnboarding' not in source):
            eligible+=1
    if eligible<2:
        return False
    target=client/HUD_FILE
    if target.exists() and target.read_text(encoding="utf-8")!=HUD_SOURCE:
        raise ValueError("RMM HUD source conflicts with a preexisting project file")
    target.write_text(HUD_SOURCE,encoding="utf-8")
    return True
