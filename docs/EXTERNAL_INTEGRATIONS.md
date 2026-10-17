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

Jest Roblox 3.20 is a concrete Wally dev dependency and its structural
specs are mounted into the test-only Rojo project, where an explicit
StudioTestService phase calls Jest.runCLI. Lune 0.11 is installed by Rokit
in CI and executes the exact same pure EconomyRules.luau used in generated
shops: malformed prices, negative balances and insufficient coins are
rejected. Rojo internally uses Roblox's rbx-dom ecosystem; MRM additionally
audits the actual Rojo .rbxlx instances and scripts with its Python
compiled-place inspector. A separate Rust rbx-dom consumer is not yet
integrated because this existing pathway already validates emitted Roblox
XML, while game runtime still requires Studio.

## Bounded error repair

For modules without an implementation template, MRM no longer returns
a placeholder Lua table as a supposed completed game. Enable a real
local model with `RMM_ENABLE_MODEL_GENERATION=1` plus a working
`ROBLOX_LLAMA_SERVER_URL` to attempt bounded, docs-grounded Luau
generation. Missing model or repeated syntax failures cause build failure.
The agent never silently falls back to a fake game.

## Real Jest execution in Studio

The generated structural Jest specs are only mounted into the separate
`studio-tests.project.json` project. When StudioTestService starts a
two-client `RMM_E2E_V1` play phase, `RMMJestRunner.server.luau` calls the
actual `Jest.runCLI` API and reports PASSED/FAILED via a server attribute.
The multiplayer E2E test refuses to pass if Jest never ran or failed.
The Studio receipt requires a separate `jest_suites=true` evidence bit.

Python tests, Wally dependency install and Rojo compilation validate only
that the runner was included, not that a real Studio environment executed it.

## Current CI evidence and boundaries

The Rojo smoke workflow runs Wally, StyLua, Selene, standalone Lune economy
assertions, actual default/optional ProfileStore+Fusion Rojo builds, and
compiled .rbxlx object audits. Studio tests only *compile* on GitHub Linux
runners; there is no actual Roblox Studio executable in that CI.

The TestEZ arithmetic placeholders have been replaced with Jest Roblox
instance-presence tests; these are intentionally not a full multiplayer
behavior or DataStore restore test. Use the separately configured isolated
test-place Open Cloud workflow and StudioTestService with actual credentials
to obtain runtime approval.

## MMM-style request-first design RAG

The game plan calls `RobloxPreDesignResearch.research` **before** module selection.
It preserves the full original request and each separable requirement as a
ledger, creates Roblox-specific English API queries by requested capability,
retrieves official `/docs/llms.txt` links and real Markdown excerpts, and stores
`content_sha256` for every observed passage. The authoring plan, checkpoint
hash, generated project `pre_design_research.json` and subsequent small-model
Luau coder reuse the same evidence. A provider outage or skipped search is
reported as such; local API index matches and Wally package candidates are
separately labelled and never counted as retrieved official documentation.

Normal use attempts live doc lookup by default. Set
`RMM_PREDESIGN_LIVE_SEARCH=0` for air-gapped CI/offline work, visibly marked
`live_disabled`. Set `RMM_ENABLE_MODEL_QUERY_EXPANSION=1` with a working
small-model router to generate additional English search queries from exact
text spans in the user's request. The model can suggest queries but **cannot**
create source references, remove user requirements or certify working code.
The retrieval budget defers surplus queries without truncating the ledger.

Known reusable ProfileStore and Fusion packages are only *candidates* until
Wally resolves them and real Studio behavior is tested. An unsupported game
mechanic remains explicitly unimplemented; source-only builds never become
false success. This mirrors MMM's authority split without importing
Minecraft-specific CurseForge, loader, or mod semantics.
