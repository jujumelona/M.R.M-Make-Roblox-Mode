# Universal Roblox gameplay pipeline and source reuse decisions

## Generality vs static templates

Older MRM chose built-in Obby/Shop/Combat/Tycoon/Simulator templates from
keyword matches alone. A request for a pet shop or tower-defense PvP game
could accidentally receive potion/boots shop code or the stock arena.

The current pipeline distinguishes `builtin` (explicit simple games with
no local architecture model configured) from `dynamic` (novel authored
behavior designed by the user's connected local model).

**When a real `ROBLOX_LLAMA_SERVER_URL` or `RMM_MODEL_BASE_URL` is set,
dynamic architecture is the default even for ordinary genre keywords.**
Do not silently substitute a fixed game template when the model fails.

### Execution contract

1. Original prompt is decomposed into requirement IDs and Roblox mechanics;
   Creator Hub documentation and local inspected source are retrieved and
   source-labelled separately.
2. The local model proposes an exact requirement/facet-to-module mapping,
   client/server/shared roles, bounded world objects, Remotes and observable
   acceptance criteria. The host validates identities, constraints,
   dependency names, cardinality and reserved paths.
3. **No external code is transplanted solely on a matching name, description
   or Creator Store metadata.** For dynamic games only first-party
   network/persistence infrastructure is kept. The novel gameplay is
   generated afresh. The existence of a reusable library is a candidate,
   not verified suitability.
4. The local coder receives the approved plan and exact fetched official
   document excerpts (not claimed to be executed proof). It writes the Luau
   implementation module-by-module, with bounded repairs of static errors.
5. Novel module scripts, user-authorized world objects and Remotes are
   materialized to Rojo, and the same name/class contracts are checked
   against the actual compiled .rbxlx.
6. If a Selene/Luau tool identifies a novel source path, the system can
   repair **that exact file** and rerun the failed tool plus static quality
   gates. Missing binaries, unrelated template errors and repeated
   failures never pass as successful.
7. Jest Roblox structural tests are emitted for novel modules, Remotes
   and world instances and can run in an owner's Studio test Place.
   These only prove real DataModel presence, not custom gameplay behavior.

### Connect a small model

Provide an OpenAI-compatible local llama.cpp model endpoint. Examples:

```bash
export ROBLOX_LLAMA_SERVER_URL=http://127.0.0.1:8910/v1
export RMM_ENABLE_DYNAMIC_DESIGN=1
export RMM_ENABLE_MODEL_GENERATION=1
rmm plan "몬스터가 나타나고 타워를 지어 방어하는 게임"
rmm build --source-only
```

The default setting is `auto`: both architecture and code-generation
paths are enabled when a model URL is configured. `RMM_MODEL_BASE_URL`
(the Colab notebook's REMOTE_BASE_URL) is accepted too. An unavailable
model is an explicit failure, not a hidden switch back to stock combat.

The sample Rojo CI injects a **deterministic mock model**, then really
executes StyLua, Selene and Rojo on its novel generated source. This
validates contracts/tool wiring only. It is not a real-model benchmark.

### Limits that remain real

- The model still must write functional code. No finite architecture
  validator guarantees correctness of arbitrary game mechanics.
- Repo CI cannot run Roblox Studio, live multiplayer or persistence
  restoration without a connected authorized test Experience.
- New gameplay's observable acceptance criteria require user/game-specific
  *real* Studio automation to be proven. Structural Jest and Luau analysis
  do not replace that validation.
- The generic world object schema currently permits bounded Part and
  SpawnLocation additions, while more elaborate worlds must be constructed
  in game-specific Luau scripts and separately engine-tested.
- Robust third-party source adaptation requires compatible versions,
  original code inspection, rights/license checks, dependency audit,
  actual compilation and game-specific behavior tests. Nothing is
  transplanted before those checks.
