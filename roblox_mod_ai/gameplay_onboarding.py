"""Host-owned onboarding for every new Roblox experience.

Shows the user's requested activity and a grounded, bounded instruction.
No generated UI can grant currency or decide outcomes client-side.
"""
from __future__ import annotations

import json

from .spec import RobloxProposal


def render_game_objectives(proposal: RobloxProposal) -> str:
    contract = proposal.game_design.get("gameplay_contract") or {}
    actions = [x.get("action", "") for x in contract.get("units", [])
               if x.get("id") != "onboarding"]
    goal = proposal.requested_prompt.strip()[:130] or contract.get("objective", "")
    hint = actions[0][:125] if actions else "Explore the game world"
    quote_goal = json.dumps(goal, ensure_ascii=False)
    quote_hint = json.dumps(hint, ensure_ascii=False)
    return '''--!strict
local Players = game:GetService("Players")
local player = Players.LocalPlayer
local gui = Instance.new("ScreenGui")
gui.Name = "RMMOnboarding"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")

local goal = Instance.new("TextLabel")
goal.Name = "GameObjective"
goal.Size = UDim2.fromOffset(460, 66)
goal.Position = UDim2.new(0.5, -230, 0, 18)
goal.TextWrapped = true
goal.TextScaled = true
goal.BackgroundTransparency = 0.3
goal.Text = "Goal: " .. ''' + quote_goal + '''
goal.Parent = gui

local hint = Instance.new("TextLabel")
hint.Name = "GameActionHint"
hint.Size = UDim2.fromOffset(460, 36)
hint.Position = UDim2.new(0.5, -230, 0, 86)
hint.TextWrapped = true
hint.TextScaled = true
hint.BackgroundTransparency = 0.3
hint.Text = "Start: " .. ''' + quote_hint + '''
hint.Parent = gui

local toggle = Instance.new("TextButton")
toggle.Name = "ToggleObjective"
toggle.Size = UDim2.fromOffset(130, 32)
toggle.Position = UDim2.new(0.5, 100, 0, 125)
toggle.Text = "Hide objective"
toggle.Parent = gui
toggle.Activated:Connect(function()
    local show = not goal.Visible
    goal.Visible = show
    hint.Visible = show
    toggle.Text = show and "Hide objective" or "Show objective"
end)
'''
