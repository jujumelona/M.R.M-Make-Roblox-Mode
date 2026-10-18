"""Deterministic Roblox cross-platform UI for ZERO-argument actions only.

The host owns LocalPlayer, PlayerGui, button layout and Remote transport.
Custom target selection, inventory forms, drag/drop, aiming, equipment
selection and argument-bearing requests still require game-specific client
Luau and are explicitly NOT covered by this template.
"""
from __future__ import annotations

import json
from typing import Any

from .spec import RobloxModuleSpec, RobloxProposal


def render_host_client(module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
    design = proposal.game_design.get("dynamic_design") or {}
    bindings = design.get("host_client_actions") or {}
    binding: dict[str, Any] | None = bindings.get(module.name)
    if (not isinstance(binding, dict)
            or not module.module_id.startswith("dyn_")
            or not module.file_path.endswith(".client.luau")):
        raise ValueError("Not a declared host-owned client controller")
    remote_name = binding.get("remote")
    kind = binding.get("kind")
    if (kind not in {"RemoteEvent", "RemoteFunction"}
            or binding.get("input_mode") != "host_button"
            or binding.get("argument_count") != 0
            or design.get("remotes", {}).get(remote_name) != kind
            or remote_name not in design.get("module_remotes", {}).get(
                module.module_id, [])
            or not isinstance(remote_name, str)):
        raise ValueError("Host client must bind exact zero-argument declared Remote")
    label = binding.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("Host client needs a real action label")
    label = label.strip()[:44]
    order = sorted(bindings).index(module.name) + 1
    encoded_remote = json.dumps(remote_name, ensure_ascii=False)
    encoded_label = json.dumps(label, ensure_ascii=False)
    encoded_button = json.dumps(module.name, ensure_ascii=False)
    encoded_kind = json.dumps(kind)
    # All host controller Scripts create UI in one PlayerGui ScreenGui.
    # The UIListLayout prevents buttons from overlaying when there are many
    # independently generated mechanics, unlike a fixed E-key action.
    return (
        "--!strict\n"
        "-- Host-generated no-argument UI. Not a custom target picker.\n"
        'local Players = game:GetService("Players")\n'
        'local ReplicatedStorage = game:GetService("ReplicatedStorage")\n'
        "local player = Players.LocalPlayer\n"
        'local playerGui = player:WaitForChild("PlayerGui")\n'
        'local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild('
        + encoded_remote + ')\n'
        'if not remote:IsA(' + encoded_kind + ') then error("Remote class mismatch") end\n'
        'local gui = playerGui:FindFirstChild("RMMHostActions")\n'
        "if not gui then\n"
        '    gui = Instance.new("ScreenGui")\n'
        '    gui.Name = "RMMHostActions"\n'
        "    gui.ResetOnSpawn = false\n"
        "    gui.DisplayOrder = 3\n"
        "    gui.Parent = playerGui\n"
        "end\n"
        'local panel = gui:FindFirstChild("ActionList")\n'
        "if not panel then\n"
        '    panel = Instance.new("ScrollingFrame")\n'
        '    panel.Name = "ActionList"\n'
        '    panel.Size = UDim2.fromOffset(215, 240)\n'
        '    panel.Position = UDim2.new(1, -230, 1, -270)\n'
        "    panel.BackgroundTransparency = 0.25\n"
        "    panel.ScrollBarThickness = 6\n"
        "    panel.AutomaticCanvasSize = Enum.AutomaticSize.Y\n"
        "    panel.CanvasSize = UDim2.fromOffset(0, 0)\n"
        "    panel.Parent = gui\n"
        '    local layout = Instance.new("UIListLayout")\n'
        "    layout.Padding = UDim.new(0, 5)\n"
        "    layout.SortOrder = Enum.SortOrder.LayoutOrder\n"
        "    layout.Parent = panel\n"
        "end\n"
        'local button = Instance.new("TextButton")\n'
        'button.Name = ' + encoded_button + '\n'
        'button.Text = ' + encoded_label + '\n'
        "button.LayoutOrder = " + str(order) + "\n"
        "button.Size = UDim2.new(1, -12, 0, 38)\n"
        "button.TextSize = 16\n"
        "button.TextScaled = false\n"
        "button.Selectable = true\n"
        "button.Parent = panel\n"
        "local lastClientAction = 0\n"
        "button.Activated:Connect(function()\n"
        "    local now = os.clock()\n"
        "    if now - lastClientAction < 0.15 then return end\n"
        "    lastClientAction = now\n"
        + (
            "    remote:FireServer()\n"
            if kind == "RemoteEvent" else
            "    button.Active = false\n"
            "    local ok, response = pcall(function()\n"
            "        return remote:InvokeServer()\n"
            "    end)\n"
            "    button.Active = true\n"
            '    if ok then button.Text = ' + encoded_label +
            ' .. ": " .. string.sub(tostring(response), 1, 40)\n'
            '    else button.Text = ' + encoded_label + ' .. ": unavailable" end\n'
        )
        + "end)\n"
    )
