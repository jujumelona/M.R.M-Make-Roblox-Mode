---
name: generate-luau-client
description: Guide for small AI models to write responsive client-side controllers and UI in StarterPlayerScripts and StarterGui.
---

# Generate Luau Client Skill

Client scripts handle player inputs, camera, animations, and UI visual feedback:

## 1. Input Processing
Use `UserInputService`:
```lua
local UserInputService = game:GetService("UserInputService")

UserInputService.InputBegan:Connect(function(input, gameProcessed)
    if gameProcessed then return end -- Ignore when player is typing in chat
    if input.UserInputType == Enum.UserInputType.MouseButton1 then
        attackRemote:FireServer(mouse.Target)
    end
end)
```

## 2. Tween Animations
Never use while-loops with `wait()` to animate UI. Use `TweenService`:
```lua
local TweenService = game:GetService("TweenService")
local info = TweenInfo.new(0.3, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
local tween = TweenService:Create(frame, info, { Size = UDim2.new(1, 0, 1, 0) })
tween:Play()
```

## 3. Remote Event Listening
Listen for server broadcasts using `OnClientEvent`:
```lua
damageRemote.OnClientEvent:Connect(function(hitPosition)
    spawnDamageParticle(hitPosition)
end)
```
