# R.M.M generator code audit — 2026-10-28

Baseline: main `014ca6744c989e51a48fba580a45949106dbd114`; code fixes on main through `f0e949c3126bbfa98f102a0fa3b6cef996ce2242`.
Review scope: full recursive repository tree (~454 files), content-pattern scan of all 149 Python source files in `roblox_mod_ai/`, deeper function-level inspection of planning, routing, host compiler, validation, and delivery. This is **not** a claim of executing every branch or reviewing every line manually.

## CI and verification meaning

- Baseline GitHub CI: 31 failed, 1,527 passed, 3 skipped (Ubuntu/Python 3.11).
- Latest fully observed intermediate CI after routing and keyword validation changes: 31 failed, 1,530 passed, 3 skipped.
- Rojo smoke after the changes through `dcaeee45`: passed; `f0e949c` CI requires separate check.
- A Rojo build or static source check is not an actual Roblox Studio gameplay, persistence, economy, multiplayer or motion playtest.
- `RobloxPipelineResult.success` on `source_only=True` indicates an offline artifact workflow result, **not** completed gameplay.

## P0: architectural correctness

### P0.1 Routing manifest disagreed with executable dispatcher — **patched**

`generation_scope.py:generation_scope` formerly classified `render_host_gameplay` before vehicle departure, assembly, rank, catalog and ship adapters. `code_generator.py:generate_module_code` selected most specialized adapters first, then `render_host_gameplay`.

**Impact:** wrong generator attribution, provenance/checkpoint drift, misleading static coverage and possible incorrect handoff. **Change:** aligned priority and added collision regressions to `tests/test_generation_scope.py`. **Follow-up:** consolidate routing into a single registry shared by manifest and generator, and compare the actual emitted source's route with its signed receipt. Two separately maintained lists can diverge again.

### P0.2 Model-created numeric execution programs do not have independent semantic equivalence proof

`host_effect_ir_planner.py:try_plan_effect_data` calls a small model to invent a compact `changes` array; `compile_effect_data` checks numeric bounds and shape, but no independent proof compares the chosen quantities, currencies, recipes, cooldown, actor, etc. with every source requirement. A data-only IR prevents malformed Luau but is not evidence of correct **game rules**.

**Required:** immutable source-owned action IDs, effect-to-source alignment, reference amounts anchored in a validated spec, multi-effect completeness, and a source-semantic admission gate. Do not mark a valid JSON schema as a verified game.

### P0.3 Unsupported dynamic actions still fall back to arbitrary whole-file Luau generation

`code_generator.py:generate_module_code` falls back to `RobloxCodeRepairAgent(...).repair(module,proposal)` for dynamic actions not covered by the bounded server/client/passive routes. This reintroduces long-output and cross-module API invention risks for small local models.

**Required:** expand typed effect IR and host-owned world/NPC/movement primitives; isolate action responsibilities by bounded program type. Unsupported semantics must remain explicitly unimplemented, with source-bound diagnostic—not success-shaped default modules.

### P0.4 Raw prompt text still changes gameplay details after architecture approval

Actual code paths:
- `host_level_upgrade.py:_allows_paid_first_ownership`: reads `proposal.requested_prompt` and selectively grants first paid weapon ownership.
- `host_mining_contract.py:_is_named_mining_service` and `ensure_mining_world_contract`: consult raw prompt to choose mining services, create a world node and rebase input transport.
- `host_space_colonization.py:eligible_colony_alias`: reads raw prompt and matches service naming to choose an alias.

`generation_scope.py:assert_prompt_invariant_routing` compares only generator **strategy**, not the **exact output bytes** or side effects on the design. This is a partial check. **Required:** move all action-authorizing facts into one verified source contract, pass data-only permissions to codegen, disallow downstream raw-prompt decision branches, assert output equality under raw-prompt removal, and detect any preflight mutation caused by the raw words.

### P0.5 Cross-service action delegation is not consistently audited

`server_interface_audit.py:dependency_api_errors` rejects arbitrary `services.Other.handleAction` because host bootstrap owns ingress. But `host_space_colonization.py` emits a generated alias whose `services[canonicalName].handleAction` calls the canonical service. Dynamic bracket keys may evade literal-name regex in `server_interface_audit.py`, leaving a policy/implementation mismatch.

**Required:** a declared, typed host-internal command API distinct from remote entrypoints, or an explicit source-verified adapter exception with complete validation and source ownership.

## P1: correctness and operational readiness

### P1.1 Plan admission and implementation completion share an ambiguous status

`api.py:CompleteChatReply.ready_to_build` returns True for an `intent_draft` with matching source hash, even if every requested implementation is pending; `implementation_ready` does not. This explains several failures (e.g., unknown genre or unavailable model accepted as ready). It also risks clients showing a misleading success state.

**Required:** version the public API; separate `can_start_compilation`, `implementation_contract_ready` and `engine_verified`. Update plan caches, UI and failure bundles together without blocking safe intent-draft admission or falsely marking the game implemented.

### P1.2 CI failures are not one bug

The baseline has 31 failures: incomplete plan reporting, source decomposition & ownership, scoped atomic repair, source-preserving semantic patch, declarative market recovery, motion acceptance, server/player data dependencies, and the typed action server ABI. Several tests encode older plan semantics, but each needs a code-vs-test contract review; never delete failures or broadly relax gates just to green the build.

Examples:
- `tests/test_atomic_action_local_repair.py`: local repair payload no longer matches exact-error fixture.
- `tests/test_semantic_field_repair.py`: repair loses scoped contract or re-generates whole feature instead of only rejected field.
- `tests/test_typed_action_contract.py`: dynamic server source references `PlayerDataManager` absent from its actual registered peers.
- `tests/test_plan65_motion_regressions.py`: source movement acceptance false-negative on fully described relocation.
- `tests/test_plan71_trade_repair.py`, `tests/test_plan77_host_market_contract.py`: model/host market fallback expectations diverge.
- `tests/test_session.py`, `tests/test_agent_trajectory.py`: plan admission vs finished implementation status.

### P1.3 Model-proposed identifiers can be Luau keywords — **patched**

`typed_action_contract.py:validate_contract` accepted identifiers like `end`, `local`, `function` as input/state fields, which become `args.end` or `state.end` in Luau. Added reserved-word filtering and state-path checks. Added regression coverage `test_typed_input_and_state_names_cannot_be_luau_keywords`.

### P1.4 No-op arithmetic can masquerade as gameplay — **patched**

`host_atomic_effect.py:executable_spec` previously accepted `increment 0` or `decrement 0`. Changed to reject. Multi-state transaction compiler already rejects zero constant arithmetic. Regression added in `tests/test_generic_transaction_effect.py`.

### P1.5 Static acceptance is not executable behavior proof

`quality_gates.py` retains hardcoded `ShopService` / `CombatSystem` checks and token-presence heuristics. `server_interface_audit.py` checks some cross-service calls but does not prove business-rule ownership or live engine behavior.

**Required:** typed producer–consumer state contract graph, executable contract tests, server/client ABI test, and separately attested Studio multiplayer/playtest; distinguish source-build, static-contract, and engine-gameplay verdicts.

## Verification commands / follow-up gates

```bash
python -m pytest -q tests/test_generation_scope.py tests/test_typed_action_contract.py tests/test_generic_transaction_effect.py
python -m pytest -q tests
python -m compileall -q roblox_mod_ai tests
```

Run Rojo real build smoke CI and inspect exact failure traces. A passing CI must not be relabeled a Roblox Studio playtest. For production consider evaluating three dissimilar unseen requests, with no prompt-specific template changes, to measure source coverage, contract parity, playable inputs and persistent state.

## Preservation rule

Never satisfy a failing test by merely returning success, inserting a dummy world object that has no legitimate rule/effect, replacing a requested mechanic with an unrelated fixed-price store, or skipping unfinished requirements. Keep original source spans, rejected code, validation evidence, and checkpoint provenance in failure receipts.
