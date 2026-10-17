---
name: plan-roblox-experience
description: How a small AI model breaks down a natural language game description into decoupled Roblox subsystems, services, remotes, and Creator Store assets.
---

# Plan Roblox Experience Skill

When tasked with generating or designing a Roblox game or mode from a prompt, follow this step-by-step procedure:

## Step 1: Subsystem Decomposition
Break the user request into the 5 core Roblox engine services:
1. **ServerScriptService (`src/server/`)**:
   - `PlayerDataManager`: DataStore persistence for coins, levels, inventory using `pcall`.
   - `GameManager` / `CombatSystem`: Server-authoritative mechanics, cooldowns, and damage checks.
2. **ReplicatedStorage (`src/shared/`)**:
   - `NetworkRemotes`: RemoteEvents and RemoteFunctions declarations.
   - `SharedConstants`: Game rules, pricing tables, max players.
   - `ModdingSystem`: In-game data-driven mod registration table.
3. **StarterPlayer.StarterPlayerScripts (`src/client/`)**:
   - `PlayerController`: Input binding via `UserInputService`.
   - `HUDController`: ScreenGui, Healthbars, and shop tweens.
4. **StarterGui (`src/gui/`)**:
   - UI layout definitions.
5. **SoundService & Workspace**:
   - Audio effects and 3D models.

## Step 2: Query MCP Tools
Call the following MCP tools:
- `roblox_api_search`: Check required method signatures (e.g. `DataStore:GetAsync`, `RemoteEvent:FireServer`).
- `roblox_creator_store_search`: Search for existing community models and sounds.

## Step 3: Emit Plan
Call `roblox_plan_experience` or save the authored plan checkpoint.
