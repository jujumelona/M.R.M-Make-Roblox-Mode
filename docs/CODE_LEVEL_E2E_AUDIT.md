# Code-level E2E verification — 2026-10-18

## Test scope and actual invocation

A genuine code-path E2E now executes `CompleteRobloxAISession.plan()` and
`CompleteRobloxAISession.build(source_only=False)` with a **deterministic model
fixture** and **real** Rokit-installed Wally, StyLua, Selene and Rojo binaries.
It exercises actual pipeline orchestration, source generation, linting,
package installation, compiled Place production, receipt creation and
artifact ZIP integrity (not only a separate manual Rojo build).

Run in a configured CI environment:

```bash
python -m pytest tests/test_dynamic_architecture.py tests/test_dynamic_wiring.py tests/test_compiled_place_inspector.py -q
python tools/verify_code_e2e.py
```

The second command needs Wally, StyLua, Selene and Rojo in PATH, and emits
`.rmm-code-e2e/code_e2e_receipt.json`. The GitHub workflow uploads its
actual compiled sources and receipt as an artifact.

## Defects reproduced and fixed

| Failure exposed | Previous false assurance | Current action |
| --- | --- | --- |
| Server listens to HatchPet but no client calls it | A generated pet game passed source-only structural checks | Dynamic Remote tracing now requires a valid caller/receiver pair in compatible client/server scripts |
| Generated Jest config contained literal backslash-n text | Manual CI formatted only src, so full StyLua formatting failed | Emit real newline and regression-test config |
| Compiled Place contains same script name with wrong implementation | Inspector checked script names only | Compare full Source text to the actual generated Lua file and check expected Roblox service hierarchy |
| The complete production orchestrator was never executed by smoke CI | Manual Rojo build passed, but build(source_only=False) was untested | CI now invokes the real public plan/build path, checks ZIP SHA-256 and actual tool execution |
| Standalone luau-analyze unavailable in the canonical toolchain | Production path aborted before Rojo despite successful mandatory tools | Record typechecking as **unverified** and require real Selene/Rojo success; never claim full typing verification |
| RemoteEvent only audited one direction | Valid server-to-client broadcast would be incorrectly rejected | Support Client→Server and Server→Client for RemoteEvents and RemoteFunctions |
| Commented or string-only Remote call | Text-based reference could masquerade as a callable link | Strip comments and mask strings for call-site analysis |

## Acceptance / evidence levels

1. **Fixture + real toolchain succeeded:** requirements, generated modules,
   same-module source hashes, Remote declaration/client-server wiring, world
   objects, Wally, StyLua, Selene, Rojo, compiled Source equality, ZIP content
   hashes. The resulting `code_e2e_receipt.json` records each status.
2. **Negative-path tests succeeded:** unsupported/unsafe model output,
   fake compiled source, wrong Roblox service, unconnected Remote, missing
   Remote client, fake comment/string-only invocation, invalid architecture
   and absence of real release verification.
3. **Not verified:** a real MiMo/llama.cpp model generating arbitrary games,
   functional combat/pets/economy behaviors inside Roblox Studio, true client
   networking, multiplayer sessions, DataStore persistence, production publish
   permissions. The tested model fixture is a fixed source sample, not a
   sample of actual model reliability.
4. **Scope limitation:** static wiring proves direct API references and
   compatible endpoint direction, not that a player can actually perform the
   input, that server state will change as intended, or that the same
   behavior works on all devices. Missing `luau-analyze` remains a visible
   typecheck gap, even though Selene and real Rojo both execute.

## Fail-closed release rule

The code E2E intentionally asserts `result.success == False`,
`playtest_report.passed == False`, and `runtime.passed == False` without
authorized Studio/Open Cloud engine evidence. A valid .rbxlx is a *build
artifact*, not a verified playable Roblox game.

Implementation and reproductions:
- `roblox_mod_ai/dynamic_wiring.py`
- `roblox_mod_ai/rbxlx_inspector.py`
- `roblox_mod_ai/orchestrator.py`
- `tools/verify_code_e2e.py`
- `tests/test_dynamic_architecture.py`
- `tests/test_dynamic_wiring.py`
- `tests/test_compiled_place_inspector.py`
- `.github/workflows/rojo-smoke.yml`
