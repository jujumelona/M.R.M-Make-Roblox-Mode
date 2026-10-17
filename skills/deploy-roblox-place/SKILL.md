---
name: deploy-roblox-place
description: How a small AI compiles the final .rbxlx XML place file and optionally deploys to Roblox Open Cloud.
---

# Deploy Roblox Place Skill

## 1. Local Compile (.rbxlx & ZIP)
Call MCP tool:
```json
{
  "name": "roblox_rbxlx_build",
  "arguments": { "run_name": "release-build" }
}
```
Outputs:
- `<GameTitle>.rbxlx`: Standalone Roblox Studio Place file.
- `<GameTitle>_roblox_project.zip`: Project ZIP containing Rojo source layout and wally.toml.

## 2. Open Cloud Deployment (Optional)
If user provides `ROBLOX_OPEN_CLOUD_API_KEY`, publish directly:
```json
{
  "name": "roblox_open_cloud_deploy",
  "arguments": {
    "universe_id": "<UNIVERSE_ID>",
    "place_id": "<PLACE_ID>",
    "file_path": "rmm-output/release-build/MyGame.rbxlx"
  }
}
```
