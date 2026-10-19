# Uploaded code generation failures implementation plan

> Execute inline using superpowers:executing-plans. User authorizes continuous fixes and checkpoint commits/pushes to main.

**Goal:** Correct the uploaded Roblox planning/generation failures and the failing current CI without claiming untested gameplay success.

**Architecture:** The host owns engine scaffolding and explicit service interfaces. Models implement scoped gameplay using original request context. Actual failed responses remain diagnostic evidence and must never pass as empty services.

**Tech Stack:** Python, pytest, Roblox Luau, StyLua, Selene, Rojo, Lune, local MiMo router.

**Spec:** Uploaded failure ZIP and authored proposal; original game request remains binding.

## Global constraints
- Work in this dedicated checkout; push verified checkpoints to main as requested.
- Retain complete failed source/history and checkpoints. Do not silently ship missing mechanics.
- No unsupported claims about a running model or Roblox Studio playtest.
- Do not turn in-game currency into Robux monetization without explicit original request.

## Review focus
- Source fragments lose context and introduce monetization or unnecessary mode scaffolding.
- Invalid Luau retry drops behavior, world, data and service contract information.
- Empty start functions and undefined service tables are accepted by string checks.
- Player data host is an auto-running Script with no callable registry API.
- Latest failure evidence can differ from the first error saved to ZIP.

### Task 1: Restore current CI contracts
- [x] Reproduce both failing tests in full baseline.
- [x] Return explicit empty host client action map for native world-only designs.
- [x] Trace missing MagicAbilities revision module; fix ownership or stale fixture according to actual behavior.
- [x] Run full tests, commit and push this checkpoint.

### Task 2: Ground planning in complete request semantics
- [ ] Add regressions for original in-game purchases and incomplete source clauses.
- [ ] Supply complete request as context while limiting each facet's implementation ownership.
- [ ] Reject unsolicited Robux requirements with repair diagnostics.
- [ ] Run tests, commit and push.

### Task 3: Make repair use a concrete host service contract
- [ ] Reproduce uploaded malformed/empty/undefined service outputs before implementation.
- [ ] Preserve scoped facts across retries and give concrete simple Luau scaffold, exact API usage and failure lines.
- [ ] Reject undefined export tables, incompatible start signatures and empty gameplay implementations.
- [ ] Trace host persistence access and fix callable registry contract if needed.
- [ ] Verify source recovery/failure history, tests, commit and push.

### Task 4: Verify complete pipeline and record evidence
- [ ] Run full Python suite with coverage, notebook validation and real available Luau tooling.
- [ ] Check pushed SHA CI, investigate failures while continuing local verification.
- [ ] Review final diff; document actual scope and unresolved environment/model/Studio limits.
- [ ] Commit and push final evidence.
