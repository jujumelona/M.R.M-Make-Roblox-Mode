# MRM: real-model E2E success contract

**Do not report a Minecraft/Roblox game as completed on the basis of mocked model CI.**

## Exact failure chain from uploaded space-game reports

- **proposal (12)**: The model returned non-source IDs (`fac-001`,
  `fac-002`) rather than source-ledger `intent-...` IDs. Three 9B
  completions failed before any Luau was generated. In the first candidate,
  the mining-only task also authored ship building modules and **14 remotes**.
- **Previous failure ZIP**: The completed 22-module architecture failed at
  `EconomyLedger`, after only two actual modules were saved. Three code
  attempts (plus recovery) were unable to produce valid Luau, with 6,000-token
  completions and unterminated JSON. This is not the same failure stage as
  proposal (12).

## Source-level changes

1. Bind local model aliases to the **single immutable current source facet**
   on the host, without trusting cross-facet labels or inventing acceptance.
2. Feed the small planner **only one source clause** per call, not the seven
   other gameplay systems. No silent dropping of the original seven facets.
3. Persist every validated design slice in
   `architecture_subplans_checkpoint.json`, keyed by request, original ledger,
   validated evidence, and actual code policy hash. Revalidate on replay.
4. Generate loadable server ModuleScripts under a host-owned bootstrap.
5. Before claiming even static source acceptance, check cross-file
   `services.<Service>.<method>()` references against actually exported
   functions. Route errors to the caller, with callee's actual exports.
6. Include agent code and design contracts in codegen checkpoint signatures.
   A changed agent implementation must not resume stale unverified source.

## Execute **real** small-model E2E

With the *same real* llama.cpp model configured in the user's Colab/runtime:

```bash
python tools/run_real_model_e2e.py \
  --model-url http://127.0.0.1:8910/v1 \
  --prompt-file space_request.txt \
  --output rmm-real-e2e
```

The command writes `rmm-real-e2e/real_model_e2e_receipt.json`.
On failure, preserve `plan_failure_logs.zip`,
`*_failure_logs.zip`, and per-module
`failed_candidates/*.attempts.json`. Use `--resume-plan` for a validated
saved proposal and `--source-only` only when intentionally skipping the
compiler/runtime, never to claim success.

The command exits unsuccessfully unless full production verification succeeds.
Unavailable model endpoints, missing toolchain, absent Roblox Studio / Cloud
credentials, and failed gameplay tests remain separate explicit failures.

## Distinct levels of evidence

| Evidence | Actual claim supported |
|---|---|
| pytest tests with FakeRouter | Host orchestration and negative-test coverage |
| Real StyLua / Selene / Rojo / Lune mock engine | Syntax, assembled Place structure, bounded mocked behaviors |
| Real MiMo 9B plan + code, same user request | Real small-model agent can generate these outputs |
| Roblox Studio engine and multiplayer tests | Real engine behavior and persistence |
| All previous rows with all seven requested features | **Complete user-requested game** |

The first two rows do **not** imply the last three. If a result is missing,
report it explicitly as unverified. No arbitrary timeout/retry increase is a
substitute for error-based design, smaller work units and real execution.
