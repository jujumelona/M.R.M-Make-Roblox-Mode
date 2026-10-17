# Prompt-first Roblox game-design RAG (MMM-inspired)

MRM now runs design research **before** choosing Luau modules. The original
Korean or English request remains the source of scope. Provider matches and
small-model suggestions are never allowed to silently delete gameplay.

## Planning execution

1. Preserve original `prompt` and split only explicit comma/conjunction
   clauses into `request_ledger`; one clause may map to several facets.
2. Map feature intent to Roblox-specific, English search questions: remote
   security and shop prompts, obby checkpoints, pets, vehicle physics,
   cross-Place TeleportService, and so forth.
3. When `ROBLOX_LLAMA_SERVER_URL` is configured, ask the local model for
   additional search queries. Reject suggestions without an exact span in
   the user's original text. The model does not invent evidence URLs.
   Toggle `RMM_ENABLE_MODEL_QUERY_EXPANSION=0|1|auto` (default auto).
4. Retrieve **real** official Creator Hub `/docs/llms.txt` index entries and
   exact `.md` excerpts through allowlisted HTTPS. Preserve excerpt hashes.
   Independently index audited first-party generator source, local Engine API
   signatures and known Wally reuse candidates. These are **not** described
   as fresh official documentation or compatible third-party code.
5. Search Creator Store only if the user actually asks for asset types;
   returned assets are metadata candidates, never executable Model scripts.
6. Preserve provider errors, deferred/empty queries, unknown mechanics and
   unimplemented facets. No fallback to arbitrary sword/arena gameplay.
7. Bind topic-relevant official document URLs to corresponding module specs.
   Persist `pre_design_research` in the saved plan, its checksum, and source
   project `pre_design_research.json`. The Luau implementation agent uses
   the *same* real doc excerpts instead of a new untracked research scope.
8. Contract-check meaningful numeric requests: `50단계` produces 50
   checkpoints, `코인 30개` produces 30 pickups. Requests above the current
   128-object per-type budget are recorded as unimplemented, never truncated
   and reported successful.

## Commands

With normal network access, live retrieval is enabled:

```bash
rmm research "50단계 용암 점프맵에 NPC 상점과 펫 부화를 넣어줘" --output rmm-output/research.json
rmm plan "코인 30개를 수집하고 상점에서 구매하는 게임"
rmm build --source-only
```

`rmm research` exits nonzero when retrieval is unresolved/partial; its
source receipts are written even on incomplete research.

Use `RMM_PREDESIGN_LIVE_SEARCH=0` for deliberately offline work; this emits
`live_disabled`, not fake documentation. Python and Rojo CI run deterministic
local/mocked network tests and real Wally/StyLua/Selene/Rojo builds. They do
**not** prove production docs availability or a Roblox Studio play session.

## Current boundary

The pre-design evidence pipeline is real and mechanically attached to
generation. The set of available built-in gameplay templates remains limited.
Search results cannot create working unsupported game systems by themselves,
and an unknown request remains explicitly unresolved until its implementation
and Studio tests are supplied. Ownership and publisher permissions for existing
Experiences continue to be checked separately.
