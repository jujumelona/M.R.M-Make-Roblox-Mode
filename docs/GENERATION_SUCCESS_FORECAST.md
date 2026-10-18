# Small-model MRM: predictive generation risk and evidence

This document is a code-derived **sensitivity analysis**, not proof that the
MiMo-V2.6-Distill-Qwen-9B Q4 model can produce a finished Roblox experience.

## What the source code actually asks the model to do

1. `_decompose_compound`: decompose all user clauses, or partition and
   recover short source chunks. Models must preserve exact spans.
2. `_design_by_facets`: for each immutable source facet, return a JSON
   object with `modules`, `remotes`, `world_objects`,
   `acceptance`, `acceptance_facets`, and per-module `uses_remotes`.
   llama.cpp is given a JSON Schema; **maximum 5000 output tokens per facet**.
3. `RobloxCodeRepairAgent.repair`: for each generated Luau file, return
   **plain Luau source**. **Maximum 6000 output tokens per attempt**.
   A malformed, nonempty or visibly truncated source is re-requested as
   scoped *plain code*, not escaped into another 6000-token JSON string.
   JSON transport is only a recovery for empty or near-empty visible output.
4. `RMMServerBootstrap` loads requireable server ModuleScripts. Source
   checks verify exports, declared Remote owners, Roblox API/realm contracts,
   and exact saved source before Rojo building.
5. Real Studio multiplayer, persistence and gameplay require *separate*
   engine evidence. Source compilation does not prove game completion.

## Source-based workload

The seven source facets represented in
`tests/test_space_seven_facets_e2e.py` produce a baseline of **14 generated
server/client modules and 7 remotes**. This is 7 design calls + 14 coder
calls = **at least 21 separate model completions** before static build. If
each call takes three attempts it can become 63 calls (excluding decomposition,
remote-type clarification, repair, and extra tools). The previously uploaded
22-module plan would need at least 29 completions for the same 7 facets.

### Why the whole-game pass rate can be much smaller

For a *hypothetical* per-facet design pass chance `p_d`, independent
per-module code pass chance `p_c`, and independent static assembly chance
`p_a`, the **one-attempt** full static build chance is:

```
P(static success) = p_d ** number_of_facets
                  * p_c ** number_of_generated_modules
                  * p_a
```

These are deliberately **unfitted scenario assumptions**, NOT empirical
per-call MiMo accuracy. They exclude Roblox Studio runtime probability.

| Hypothesis (design, code, assembly) | 7 facets + 14 modules | 7 facets + 22 modules |
|---|---:|---:|
| Difficult (0.60, 0.60, 0.80) | 0.0018% | 0.000029% |
| Medium (0.80, 0.80, 0.90) | 0.83% | 0.14% |
| Favorable (0.95, 0.95, 0.95) | 32.35% | 21.46% |

**These figures do not forecast the actual MiMo pass rate.** The stage-pass
assumptions are examples chosen to demonstrate compounding risk. Errors in
coding modules can be strongly correlated (same invented API, same wrong
prompt interpretation, same truncation), so treating each of three retries
as independent gives an **unjustifiably optimistic** result. The generated
JSON report includes that three-independent-attempt sensitivity solely to
show its dependency on the assumption.

## Existing *observed* user failures

- A 7-facet design where model-generated `fac-001/fac-002` aliases were not
  the source-backed `intent-...` IDs; attempts failed validation.
- A space game with **22 planned modules** stopped at `EconomyLedger`
  after only **two** prior modules were saved. Some visible Luau outputs
  hit 6000 tokens and were invalid.
- Other outputs repeated entire code blocks or misused Roblox methods.

**These are failure case reports, not a random sample of attempts and
successes.** No reliable overall success percentage follows from them.

## What CI tests and what CI cannot test

The CI checks that:

- a complete seven-facet **mock transport** is scoped correctly, preserved and
  reassembled;
- JSON Schema fields and output token limits remain explicit;
- truncated but *visible* Luau is not wrapped into more JSON;
- unrelated functionality does not leak into the coder's single owned clause;
- module-to-module services, owner-bound Remote calls, and wrong Roblox APIs
  fail static verification;
- StyLua, Selene, Rojo, and Lune tests execute against generated fixtures;
- the forecast does not treat CI fixtures as measured MiMo successes.

CI cannot measure true completion frequency without running the actual
model and engine under the same inputs. An unmodified mock's `pass` signal
cannot be used as `p_d` or `p_c`.

## Reproducible forecast for the saved architecture

```bash
python tools/forecast_generation.py \
  --proposal .rmm-space-assembly/proposal.json \
  --output .rmm-space-assembly/generation_forecast.json
```

Run the actual game generator on the local MiMo service and retain the output:

```bash
python tools/run_real_model_e2e.py \
  --model-url http://127.0.0.1:8910/v1 \
  --prompt-file space_request.txt \
  --output rmm-real-run-01
```

The real runner saves a SHA-256 fingerprint of the full request, model ID,
endpoint and decoding settings. **Only runs with identical fingerprints**
can be pooled for a conditional empirical pass rate; each result also gets
a Wilson 95% interval to show sampling uncertainty. A failed startup before
the model runs does not count as a full-generation attempt. Full verified
success requires actual engine completion receipts, not only Rojo.

```bash
python tools/forecast_generation.py \
  --proposal rmm-real-run-01/proposal.json \
  --model-run-receipt rmm-real-run-01/real_model_e2e_receipt.json \
  --input-fingerprint <fingerprint-from-that-receipt> \
  --output rmm-real-run-01/generation_forecast.json
```

For a meaningful estimate, repeat the *same* full game request with the same
model, quantization, prompts and toolchain across many independent runs and
record **every** failure as well as successes; log model seeds and runtime
versions. Even 0 successes in 10 completed comparable attempts leaves a
substantial 95% uncertainty upper bound (~28% by Wilson). No arbitrary number
of mocked CI runs eliminates this uncertainty.

### Interpretation of improvement

The actual optimization targets are measurable per-facet design success,
per-file valid Luau success, explicit failure reason (syntax, API, missing
client/server, backend, truncation), retries spent, source compile success,
real Studio completion and median/95th-percentile runtime. Do not optimize
only the mock fixture's binary CI green status.
