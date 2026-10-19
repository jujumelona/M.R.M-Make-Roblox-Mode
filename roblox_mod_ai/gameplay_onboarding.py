"""Host-owned onboarding for every new Roblox experience.

Shows the user's requested activity and a grounded, bounded instruction.
No generated UI can grant currency or decide outcomes client-side.
"""
from __future__ import annotations

import json
import re

from .spec import RobloxProposal


def render_game_objectives(proposal: RobloxProposal) -> str:
    contract = proposal.game_design.get("gameplay_contract") or {}
    actions = [x.get("action", "") for x in contract.get("units", [])
               if x.get("id") != "onboarding"]
    # Show a playable objective, never a development instruction such as
    # "create a game". Use the actual plan's mode and selected mechanics.
    features = proposal.game_design.get("features") or {}
    mode = contract.get("mode")
    korean = bool(re.search(r"[가-힣]", proposal.requested_prompt))
    if korean:
        if mode == "round":
            steps = []
            if features.get("is_coin_collect"):
                steps.append("코인을 모으고")
            if features.get("is_shop"):
                steps.append("장비를 구매해")
            goal = " ".join(steps + ["아레나 경기에서 승리하세요."])
            hint = ("코인을 터치해 모으세요." if features.get("is_coin_collect")
                    else "다른 플레이어가 입장하면 경기가 시작됩니다.")
        elif mode == "stage":
            goal = "체크포인트를 순서대로 지나 마지막 스테이지를 완료하세요."
            hint = "첫 번째 체크포인트로 이동하세요."
        else:
            # Custom genres cannot be assigned an invented win condition.
            goal = re.sub(
                r"(?:게임|모드)?\\s*(?:을|를)?\\s*(?:만들어\\s*줘|만들어주세요|제작해\\s*줘|제작해주세요)[.!?\\s]*$",
                "", proposal.requested_prompt.strip(), flags=re.I
            ).strip(" ,.!?")[:130] or str(contract.get("objective", "활동을 진행하세요."))
            hint = actions[0][:125] if actions else "맵을 탐색하세요."
    else:
        if mode == "round":
            goal = ("Collect coins, buy equipment and win the arena round."
                    if features.get("is_coin_collect") and features.get("is_shop")
                    else "Win a match by being the last fighter standing.")
            hint = "Collect coins to purchase equipment." if features.get("is_coin_collect") else "Wait for another fighter."
        elif mode == "stage":
            goal, hint = "Reach the final checkpoint.", "Move to the first checkpoint."
        else:
            goal = re.sub(r"^(?:create|make|build)\\s+(?:me\\s+)?(?:a\\s+)?", "",
                          proposal.requested_prompt.strip(), flags=re.I)[:130]
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
goal.Text = ''' + json.dumps("목표: " if korean else "Goal: ") + ''' .. ''' + quote_goal + '''
goal.Parent = gui

local hint = Instance.new("TextLabel")
hint.Name = "GameActionHint"
hint.Size = UDim2.fromOffset(460, 36)
hint.Position = UDim2.new(0.5, -230, 0, 86)
hint.TextWrapped = true
hint.TextScaled = true
hint.BackgroundTransparency = 0.3
hint.Text = ''' + json.dumps("시작: " if korean else "Start: ") + ''' .. ''' + quote_hint + '''
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
