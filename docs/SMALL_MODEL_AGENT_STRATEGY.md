# RMM small-model agent execution contract

## Why this replaces giant-plan retries

The reproducible space-game failure (`proposal (10).json`) has seven source-anchored gameplay intents.
The local model previously returned 24 architecture modules, 26 Remotes, and no client controllers.
The next calls either regenerated the same invalid design or produced malformed long JSON.
Accepting a two-module infrastructure-only plan is **not** evidence of a playable game.

RMM now uses a **host-directed sequence of scoped model calls** for three or more independently
authored gameplay intents. A single local model may fill all roles sequentially; this is
*not* a framework requiring many simultaneously loaded models.

## Responsibility and execution

| Stage | Host responsibilities | Small model's narrow task | Pass condition |
|---|---|---|---|
| 1. Requirements | Preserve the original clauses, source spans, IDs and missing obligations | Extract source-anchored intents | No lost clause or invented requirement |
| 2. Official API evidence | Fetch and bind docs to *the relevant feature* | Interpret relevant API snippets | Source provenance survives |
| 3. Scoped architect | Schedule one facet; preserve successful contracts | Describe only its server/client/shared modules, Remotes, world instances and acceptance | Scoped schema and request-coverage validation |
| 4. Remote ownership | Validate declared names and client/server owners | Assign `uses_remotes` explicitly to each module | Both endpoints identified for each Remote |
| 5. Integration | Merge accepted contracts; reject duplicate names, collisions and missing gameplay | No wholesale re-planning | Full original-request validation |
| 6. Per-file implementation | Provide only one module's contract and its exact Remote set | Generate one real Luau file | Parser, security and static API checks |
| 7. Targeted repair | Supply failing original source plus exact diagnostics | Repair just the failed module or interface | Re-run failing checks; retain passing modules |
| 8. Game execution | Run Rojo/Studio tests, validate behaviors and persistence | Assist based on runtime observations | Tests must pass before claiming gameplay complete |

### Error-driven recovery

- Missing client for a scoped contract: request **only client modules**, and append them to the
  existing validated server design. Do not reprint the whole game's JSON.
- Broken JSON or a token-length completion: invalidate **only that feature's response**,
  retain already accepted features, and retry that small feature. Do not silently interpret a
  truncated response as a complete contract.
- Unknown or colliding Remote: return the exact collision or missing endpoint to the *current*
  feature. Never rewrite a prior accepted feature to accommodate it.
- Failed compiler, static analyzer, network-wiring audit, or Studio gameplay: preserve the
  actual source and diagnostic history for the file-level coder. An architecture pass is not
  equivalent to successful Luau execution.

### Constrained outputs

Local llama.cpp accepts a JSON Schema response format. RMM forwards that format directly for
scoped planner and client-repair outputs and disables hidden thinking for local JSON by default
(unless `RMM_JSON_ENABLE_THINKING=1`). The schema enforces **structure**, not playable gameplay.
Host validators still enforce semantic requirements and explicit Remote ownership.

For remote OpenAI-compatible endpoints, the current router falls back to JSON-object mode;
different providers can require provider-specific JSON Schema envelopes.

## Demonstrated vs not demonstrated

- **Covered by deterministic Python regression tests:** scoped request ownership, no large-plan
  re-emission for missing client, local JSON failure retry, full merge, naming collisions,
  explicit Remote owner validation, schema payload and truncation detection.
- **Not demonstrated by these tests:** inference accuracy of the user's actual 9B GGUF,
  runtime functioning of the generated game, Roblox Studio playtesting, assets, or UI quality.
  Those need a real model-backed end-to-end run and Studio execution receipt.
- `architecture_subplans` retains accepted feature metadata **within the current plan**.
  It does not yet persist executable feature contracts between independent Colab sessions.

## Regression commands

```bash
python -m pytest -q tests/test_dynamic_architecture.py tests/test_mimo_structured_output.py tests/test_dynamic_wiring.py
python -m pytest -q
```

Review the architecture attempt history in the plan failure report. A single green parser or CI
unit-test status is not evidence that the requested game exists.

## References (patterns, not bundled dependencies)

- [Aider architect/editor separation](https://aider.chat/docs/usage/modes.html):
  design reasoning and edit generation need not happen in the same completion.
- [Aider diff edits](https://github.com/Aider-AI/aider/blob/main/aider/website/docs/more/edit-formats.md):
  avoid returning entire files for small source modifications.
- [llama.cpp JSON Schema](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md):
  constrained JSON shapes on local inference.
- [SWE-agent ACI](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md):
  diagnostics, concise tools and immediate syntax checks.
- [mini-SWE-agent](https://mini-swe-agent.com/latest/):
  small auditable agent loops and visible trajectories; more agents is not automatically better.
- [Agentless](https://arxiv.org/abs/2407.01489):
  localization, repair, validation are important baselines.
- [LangGraph durable execution](https://langchain-ai.github.io/langgraph/concepts/durable_execution/):
  distinct state and recovery checkpoints.
- [DSPy optimizers](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/optimizers.md):
  optimize prompts against measured outcomes, not subjective claims.

RMM follows the underlying patterns above. It does not install or claim to run these frameworks.
