---
name: generate-luau-service
description: Guide for small AI models to write bulletproof, server-authoritative Luau backend services in ServerScriptService.
---

# Generate Luau Service Skill

Small models must adhere to strict Roblox backend design patterns to avoid security exploits and data loss:

## 1. Always Start with Strict Typing
Every file must start with:
```lua
--!strict
```

## 2. Server-Authoritative Anti-Cheat Pattern
Never trust data sent from clients via RemoteEvent:
- Validate Player Identity: First argument of `OnServerEvent` is always `player: Player`.
- Rate Limiting / Cooldowns:
  ```lua
  local cooldowns = {}
  if os.clock() - (cooldowns[player.UserId] or 0) < COOLDOWN then return end
  cooldowns[player.UserId] = os.clock()
  ```
- Distance / Reach Validation:
  ```lua
  local dist = (character.HumanoidRootPart.Position - target.Position).Magnitude
  if dist > MAX_REACH then return end
  ```

## 3. Safe DataStore Handling Pattern
DataStore network calls can fail or throttle. Always wrap in `pcall`:
```lua
local success, result = pcall(function()
    return myDataStore:GetAsync(key)
end)
```
Always connect `game:BindToClose` to flush all pending player data when server shuts down.

## 4. Tool Verification
Before finalizing code, call `roblox_luau_validate` to verify block balance and linter rules.
