# R.M.M. universal tool-using generation protocol

This is a **general implementation path for model-authored Roblox work**.
It is not a list of hard-coded space-game keywords or a claim that an LLM
can always complete an arbitrary user request.

## Decision and execution boundaries

1. The existing planner captures the original request, module ownership,
   Remote schemas, module dependencies, and real world objects. Planning and
   coding are separate; an unowned request does not become an implemented game.
2. Host-generated modules are compiled from verified first-party code and
   remain host-owned. They need no AI tool research.
3. Every small-model-authored server body, dynamic client control, passive
   lifecycle block or full-module repair first calls
   `roblox_module_contract_inspect` **in-process**. This returns the exact
   source-owned facts from the active proposal.
4. An OpenAI-compatible native tool-call round exposes approved **read-only**
   Roblox MCP tools to the local model. A local llama.cpp server must support
   the `tools` / `tool_calls` message protocol. The model can inspect the
   source contract, look up official API/docs, validate candidate Luau, inspect
   a connected Studio, or check toolchain availability. Each call is
   dispatched and its response returned to the model with the matching
   `tool_call_id`. Nothing is inferred from a successful textual response.
5. Tool requests are schema-bound, capped and logged. Unsupported names,
   malformed arguments, duplicate requests and over-budget loops are never
   executed as side effects. A 9B model cannot call project-write, Studio
   mutation/play, Rojo build or Open Cloud deploy from its coding loop.
6. The host assembles and independently validates generated code. Existing
   source-owner, input, sibling-method, Luau syntax, state-change, world
   identity, and construction gates remain mandatory. Tool research does not
   waive a failing codegen gate.
7. After all modules pass their gates, the existing orchestrator runs
   StyLua, Selene, Luau checks, Lune tests and Rojo place compilation as
   available. The game is not marked engine-verified without real Roblox
   Studio playtest evidence, including multiplayer and persistence where
   applicable. Unavailable tooling must remain unverified, not PASS.

## Allowed coding-stage MCP calls

| MCP call | Scope | Notes |
| --- | --- | --- |
| `roblox_api_search` | Curated Roblox API reference | In-process catalog |
| `roblox_official_docs_search` | Roblox Creator documentation | Network result may be unavailable |
| `roblox_luau_validate` | Static Luau validation | Not execution or typechecked Studio proof |
| `roblox_toolchain_status` | Installed CLI tool discovery | Read-only |
| `roblox_studio_status` | Actual local Studio status | Requires a real Studio connection |
| `roblox_studio_inspect` | Read-only tree, source, console, state | No `execute_luau`, mouse/keyboard or play from the model |
| `roblox_module_contract_inspect` | Current module's declared source authority | Host local tool, not an external MCP server call |

The Studio inspection sub-tool is restricted again to a separate allowlist.
The fact that a user installed an MCP server is **not** itself proof that
Studio is connected or any developer action ran.

## Tool and result evidence

The orchestrator saves `agent_tool_receipts.json` on the generation path,
including failed production runs via `tool_results.agent_tool_calls`:

- Module ID and tool protocol status
- Bounded arguments/results previews (untrusted observations)
- SHA-256 digests of tool inputs and outputs
- Tool success/failure or denied permission
- Number of native tool calls

For prompt construction, results are marked **source data, not instructions**;
the model never receives arbitrary access to the host filesystem or a Roblox
account merely because an MCP server exposed those operations.

## Limits / required future engine work

This provides a *real generic tool protocol and auditable source-verified
generation path*. It cannot guarantee a correctly implemented custom mechanic
without a source-defined state producer/consumer chain, applicable tests and
actual Roblox execution. Rojo successfully producing `.rbxlx` is a compile
artifact, **not** proof of working physics, NPCs, UI or multiplayer. If Studio
is unavailable, `runtime_required_for_verified_status` stays true and the
game must remain **unverified**. Production still needs explicit runtime
scenario and exploit testing when a Studio connector is present.

## Regression gate

```sh
python -m pytest -q tests/test_universal_agent_tools.py
```

The dedicated GitHub Actions job runs this test alongside existing typed
action source-contract regressions. A full-suite pre-existing failure is
not evidence that the game was verified.
