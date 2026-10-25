"""Install a deterministic, order-preserving client HUD for generated actions.

The built-in rank/ship/space modules create ScreenGuis independently. Without
an aggregator several rank buttons occupy exactly the same coordinates and are
inaccessible. This program is added to src/client before static/Place build,
without changing their gameplay code or server action contracts.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
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
-- Names are derived from actual generated Remote-bound UI sources, never
-- from a genre, hand-picked action name, or an assumed prefix.
local actionGuis=__ACTION_GUI_ALLOWLIST__
local function isActionGui(candidate)
    return candidate:IsA("ScreenGui") and candidate~=gui
        and actionGuis[candidate.Name]==true
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


# Require a declared ScreenGui produced by a client actually calling a server
# Remote. Only this attested subset is docked; unrelated inventory/menu/chat
# screens and non-Roblox overlays are never reparented.
_GUI_NEW=re.compile(
    r'\b(?:local\s+)?([A-Za-z_]\w*)\s*=\s*Instance\.new\(\s*'
    r'["\x27]ScreenGui["\x27]\s*\)')
_REMOTE_CALL=re.compile(r':(?:InvokeServer|FireServer)\s*\(')
_GUI_NAME_TEMPLATE=r'\b%s\s*\.\s*Name\s*=\s*["\x27]([A-Za-z_][A-Za-z0-9_]{0,79})["\x27]'


def action_gui_names(project_dir: Path) -> list[str]:
    """Discover action screens from actual executable client source.

    A ScreenGui name/prefix is NOT evidence that the screen is an action.
    A client Remote call plus a locally created, literal-named ScreenGui
    is required; that is sufficient to preserve unrelated UI verbatim.
    """
    client=Path(project_dir)/"src"/"client"
    if not client.is_dir():
        return []
    names=set()
    for path in client.glob("*.client.luau"):
        if path.name==HUD_FILE:
            continue
        source=path.read_text(encoding="utf-8")
        if not _REMOTE_CALL.search(source):
            continue
        for matched in _GUI_NEW.finditer(source):
            pat=re.compile(_GUI_NAME_TEMPLATE % re.escape(matched.group(1)))
            name=pat.search(source,matched.end())
            if name:
                names.add(name.group(1))
    return sorted(names)


def render_host_hud(names: list[str]) -> str:
    if not isinstance(names,list) or len(names)<2 or len(set(names))!=len(names):
        raise ValueError("HUD requires two or more distinct source-backed action GUIs")
    if any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}',n)
           for n in names):
        raise ValueError("HUD names must be bounded literal identifiers")
    mapping="{" + ", ".join("["+repr(n)+"]=true" for n in sorted(names)) + "}"
    return HUD_SOURCE.replace("__ACTION_GUI_ALLOWLIST__",mapping)


def install_host_hud(project_dir: Path) -> bool:
    """Install a generic Remote-bound UI dock before Rojo packaging.

    This code never guesses a game genre, screen prefix or UI coordinate.
    In case of an existing user-authored script, fail without overwriting it.
    """
    client=Path(project_dir)/"src"/"client"
    names=action_gui_names(project_dir)
    if len(names)<2:
        return False
    source=render_host_hud(names)
    target=client/HUD_FILE
    receipt=Path(project_dir)/".rmm_hud_source_receipt.json"
    if target.exists() and target.read_text(encoding="utf-8")!=source:
        # A project rerun can legitimately add or remove action modules.
        # Regenerate a PRIOR host-owned script only when its byte hash was
        # sealed by our earlier receipt; never overwrite user-authored Lua.
        try:
            saved=json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            saved={}
        observed=hashlib.sha256(target.read_bytes()).hexdigest()
        if saved.get("source_sha256")!=observed or saved.get("file")!=HUD_FILE:
            raise ValueError("HUD source conflicts with a preexisting project file")
    target.write_text(source,encoding="utf-8")
    receipt.write_text(json.dumps({
        "schema":"rmm/generated-source-receipt-v1",
        "file":HUD_FILE,
        "action_guis":names,
        "source_sha256":hashlib.sha256(source.encode("utf-8")).hexdigest(),
    },sort_keys=True,indent=2),encoding="utf-8")
    return True
