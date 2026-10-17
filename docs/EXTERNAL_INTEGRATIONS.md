# External Roblox integrations and execution evidence

This implementation reuses the Roblox ecosystem rather than inventing game
assets or claiming source inspection equals a real playtest.

## Official Creator docs / RAG

MCP `roblox_official_docs_search` retrieves the real
https://create.roblox.com/docs/llms.txt index and bounded official Markdown
excerpts on an allowlisted host. The generator's bounded small-model
implementation loop uses these documents in its prompts when
`RMM_ENABLE_MODEL_GENERATION=1`. No fetched text is executed as code.

## Roblox official Studio MCP

`python tools/studio_mcp_config.py --os windows` (or `--os darwin`)
generates an official stdio client config. Studio must be running with the
built-in MCP server enabled; it does not run on a GPU Colab runtime.
Install the local optional dependency with `pip install -e ".[studio]"`.
MRM MCP exposes `roblox_studio_status` and an explicitly-authorized
`roblox_studio_playtest`. Unavailable Studio never passes tests.

## Creator Store asset policy

Assets are retrieved via the recommended POST Creator Store search endpoint,
then validated with GET details; no hardcoded fallback IDs.
Creator badging identifies account status, not a content security guarantee.
Scripts inside inserted third-party models are removed; unverified models
must not be auto-inserted. Restrict InsertService access and approve models
in Studio before production. API key: `ROBLOX_CREATOR_STORE_API_KEY`
(or `ROBLOX_OPEN_CLOUD_API_KEY`).

## Reusable runtime packages

Set `RMM_STORAGE_BACKEND=profilestore` or mention ProfileStore in the prompt
for the **optional** server-side `lm-loleris/profilestore@1.0.3` backend.
Wally installs it in ServerPackages; the generated server script imports it
and uses its native session and autosave API. Do not combine it with the
legacy DataStore backend for the same saved key. ProfileStore is Apache-2.0.

Set `RMM_UI_BACKEND=fusion` or mention Fusion for the **optional**
`elttob/fusion@0.3.0` HUD. Wally installs it in shared Packages.
The code imports actual Fusion scoped UI state. Fusion is MIT.

The default built-in generators remain available until real gameplay,
DataStore reload and GUI interactivity are validated in Roblox Studio.
Rojo CI compiles both the default and opt-in library variant, but compiled
Luau code has not necessarily executed.

## Test levels

- Python: proposal and source-policy unit tests
- Selene / StyLua: generated Luau source checks
- Wally / Rojo: actual dependency resolve + place compilation
- Open Cloud: opt-in real server smoke and test DataStore write-read
- Studio MCP / StudioTestService: actual client/server and persistence checks

Jest Roblox, Lune, and rbx-dom are useful test/serialization projects.
They are **not** mandatory in this build until their test runners and
contracts can be verified. The existing deprecated TestEZ examples are
structural-only and are not presented as gameplay proof.

## Bounded error repair

For modules without an implementation template, MRM no longer returns
a placeholder Lua table as a supposed completed game. Enable a real
local model with `RMM_ENABLE_MODEL_GENERATION=1` plus a working
`ROBLOX_LLAMA_SERVER_URL` to attempt bounded, docs-grounded Luau
generation. Missing model or repeated syntax failures cause build failure.
The agent never silently falls back to a fake game.
