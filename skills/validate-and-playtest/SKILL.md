---
name: validate-and-playtest
description: How a small AI model runs static Luau validation and headless TestEZ playtests, and patches failures iteratively.
---

# Validate and Playtest Skill

Small models should follow this self-correction loop to achieve zero syntax errors and passing tests:

## 1. Static Validation
1. Call MCP tool:
   ```json
   {
     "name": "roblox_luau_validate",
     "arguments": { "code": "<generated_luau_source>" }
   }
   ```
2. If `diagnostics` contains errors:
   - Check unbalanced keywords (`function`, `if ... then`, `for ... do`, `end`).
   - Replace any legacy `wait()` with `task.wait()`.
   - Wrap DataStore calls in `pcall`.

## 2. Playtest Verification
1. Call MCP tool:
   ```json
   {
     "name": "roblox_playtest_run",
     "arguments": {}
   }
   ```
2. Inspect the returned `results`:
   - If leaderstats binding failed: Check `PlayerDataManager.server.luau`.
   - If Remote replication failed: Ensure remotes folder is created in `ReplicatedStorage`.
3. Re-run until `passed: true`.
