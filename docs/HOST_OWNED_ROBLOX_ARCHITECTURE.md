# MRM Roblox architecture: engine belongs to host, game rules belong to model

## Clarify the Roblox target

MRM is a generator for a Roblox **experience / Place** and optionally an
**add-on that changes an owned existing Place**, not a Fabric-style mod loader.
The deliverables are Luau Scripts, ModuleScripts, Instances and Rojo
`default.project.json` built to `.rbxlx`. Roblox Studio publishes and
tests the resulting experience. Files under ServerScriptService do not
replicate to the client; ReplicatedStorage is shared. Do **not** mistake an
unpublished `.rbxlx` for a functioning published game.

Official references:
- DataModel / server and replicated services:
  https://create.roblox.com/docs/projects/data-model
- RemoteEvent/RemoteFunction transport:
  https://create.roblox.com/docs/scripting/events/remote
- Secure client/server boundary, rate limiting, permission/proximity checks:
  https://create.roblox.com/docs/scripting/security/client-server-boundary
- Persistent data stores, local caching, UpdateAsync:
  https://create.roblox.com/docs/cloud-services/data-stores/best-practices
- Rojo project format: https://rojo.space/docs/v7/project-format/
- Studio multiplayer testing: https://create.roblox.com/docs/studio/testing-modes
- Official reusable Roblox packages:
  https://create.roblox.com/docs/projects/assets/packages

Roblox Packages are real assets, permissioned/versioned. This is not
authorization to pull arbitrary existing game code from Creator Store or
to copy scripts whose source/license/version have not been inspected.

## Actual responsibility boundary

| Element | Owner | Proof |
|---|---|---|
| Source requirements and immutable IDs | Host | Match exact request ledger |
| Roblox module roles / Instance service placement | Host | Server-only code in ServerScriptService, client scripts in StarterPlayerScripts |
| ModuleScript paths and game-specific module/Remote identifiers | Host | Legal names, no collisions |
| RemoteEvent vs RemoteFunction class | Host | Map gameplay interaction intent; verify class in Rojo |
| Initial object placement and safe bounded geometry | Host | Part greybox is NOT a finished map |
| Network ingress event/function registration | Host for semantic plans | RMMServerBootstrap binds each named Remote |
| Generic server Player identity and per-action cooldown | Host for semantic plans | Roblox security guard, no client-side reliance |
| Basic persistent profile/economy service | Host when audited built-in match | No independent per-feature currency databases |
| Game-specific damage/loot/reach/purchase/crew/planet rules | AI | Actual behavior, server checks, player-visible result |
| Specific UI and world mechanics | AI | Only where games vary; server authority retained |
| StyLua/Selene/Rojo source+compiled audits | Host | Independent failure gates |
| Studio multiplayer / persistence | Engine test runner | Must be executed, not assumed |

## Small-model initial response (semantic only)

The default architect requests the same semantic-only format for **every positive source-feature count (1, 2, 3, ...)**:

```json
{
  "systems": [
    {
      "name": "OreMining",
      "server_behavior": "Check actual ore object proximity and mining equipment; grant validated ore inventory on server.",
      "client_behavior": "Show context action for ore mining and server-confirmed inventory feedback.",
      "interaction": "event",
      "observable_result": "A nearby mineable ore node grants verified ore to the player's inventory.",
      "world_entities": ["OreNode"]
    }
  ]
}
```

## Native world interactions: Roblox ProximityPrompt needs no client Lua or Remote

When the semantic planner declares `input_mode: "world_prompt"`,
`interaction: "event"` and **exactly one** `world_entities` target, the
host compiles a native, anchored Part with a `ProximityPrompt` child.
`RMMServerBootstrap` connects `ProximityPrompt.Triggered(player)` on the
server and verifies valid Player membership, living Humanoid, server-side
distance, and per-player/per-action cooldown before delegating to
`Service.handleAction(player, services, targetPart)`.

For these actions the host produces **zero client modules and zero Remotes**.
A single simple world action can therefore require only one source-facet
semantic planning call and one game-specific server Lua generation call,
instead of one planner + server + client writer. A server-only world prompt
still needs a gameplay handler that checks permissions, item ownership and
state transitions; the greybox Part is not a finished model.

`input_mode: "world_prompt"` is rejected for server-only periodic
tasks, synchronous request-response, no world object, or multiple target
objects requiring selection. It does not silently turn arbitrary user
games into a proximity-based clicker.

Roblox references:
- https://create.roblox.com/docs/reference/engine/classes/ProximityPrompt
- https://create.roblox.com/docs/scripting/security/client-server-boundary

CI: `tests/test_host_world_prompt.py` and
`NativeWorldPrompt` in `tools/verify_diverse_host_assembly_e2e.py`.
The latter compiles the server-only Part + Prompt through real Rojo,
without calling the coder to author client Lua.

## New reduction: host-generated cross-platform input without another LLM call

The semantic-only model can now declare **`input_mode: "host_button"`**
*only* for a zero-argument action with no selected world target and
`world_entities: []`. For this contract:

- `host_architecture.py` gives the action a canonical unique client name,
  Remote name/type, argument count **zero**, and label.
- `host_client.py` produces the entire client LocalScript from first-party
  code. It creates one shared PlayerGui `ScreenGui` with a scrolling
  `UIListLayout`, `TextButton.Activated` callbacks (mouse/touch/gamepad),
  and RemoteEvent or RemoteFunction transport. The user never needs a model
  call to write this client script.
- `RMMServerBootstrap` binds the action on the server, checks the Player and
  cooldown, and rejects client calls containing unexpected arguments.
- The host **regenerates** its client source and server bootstrap from the
  current contract, even if an imported proposal contains stale or
  model-written source. A saved model module cannot replace this infrastructure.
- Forecast/prompt-profiling report the *actual number* of remaining small-model
  code-generation calls, excluding those rendered by host.
- For `input_mode: "custom"` (default), the small AI still writes a
  specialized client controller, because a fixed button cannot implement
  aiming, selecting an ore node, constructing a 3D spaceship, interacting with
  inventory choices or dragging objects. A request needing an explicit world
  target cannot masquerade as a zero-argument host button.

This feature reduces model workload without falsely turning every unusual
Roblox game into a generic clicker. It does **not** prove that host-produced
buttons make bespoke gameplay functional: the server action handler must
still implement the requested semantics and must be tested in Studio.

The model never outputs `src/server`/`StarterPlayerScripts` paths,
`uses_remotes`, `intent-...` source IDs, RemoteEvent types, world coordinates,
or server/client owner lists. Host expansion attaches those fields using one
source-anchored feature. This removes several classes of format-induced 9B
failures and reduces JSON/schema output length. The model still must describe
actual non-placeholder gameplay and must not omit user requirements.

This is NOT a fixed seven-feature space-game pipeline. The number of source
requirements, semantic gameplay systems, Luau modules, generated Remotes and
world objects is derived separately from each new user request. A weather-only
request may use one server module and no Remotes; a puzzle plus pet-care request
may need event and request/response channels; a large custom experience may
require many independent systems. The older full-infrastructure JSON format
remains available only via the explicit
`RMM_LEGACY_ARCHITECTURE_PROTOCOL=1` compatibility option.

The original seven-feature test remains a **regression for one historical
failure**. It does not establish prompt generalization. New CI includes
`tests/test_generalized_host_prompt_matrix.py`: 1, 2, 3, 5, 7, 8, 10
and 12 feature variants from different genres and languages, differing
interaction modes and sometimes two systems per feature. In addition,
`tools/verify_diverse_host_assembly_e2e.py` compiles distinct non-space
1-, 3- and 9-feature projects through StyLua, Selene and Rojo. A one-feature
server-only request must produce exactly **zero** default Remotes.

All these CI examples use **deterministic model substitutes**. They prove that
host architecture does not depend on a magic list of specific prompt words
or the previous seven-feature count. They do NOT prove that a real 9B model
interprets every novel mechanic correctly, implements it correctly in Luau,
or passes Studio gameplay testing. Those require real-model execution and
behavioral tests for each proposed game.


The code generator then receives a single module and its owned action
contract. For semantic server actions it exports
`Service.start(services)` and
`Service.handleAction(player, services, ...)` but **never**
`OnServerEvent` / `OnServerInvoke`.
`RMMServerBootstrap` binds validated RemoteEvent/RemoteFunction
and provides basic server-side `Player` / membership checks and per-player,
per-action request frequency control.

**Security limit:** A generic gateway cannot validate game-specific reach,
item prices, target authority, resource exhaustion, NPC health, transaction
atomicity or data persistence. Each AI-defined server handler must do so,
and production checks / Studio tests must establish it. The host guard by
itself does NOT make arbitrary gameplay safe.

## Compatibility and failures

- Previously saved JSON designs containing `modules/remotes/acceptance`
  continue through the strict legacy validator and legacy network wiring.
  Only new semantic responses set `host_actions`; do not alter old projects
  silently.
- The host still requires each declared Remote to have a client and server
  owner. The source wiring audit only credits server gateway ownership if
  the **compiled bootstrap source** routes the correct named Remote to the
  actual domain `handleAction` export.
- Plans are not execution: `design_verified=false` persists. Basic host
  Part geometry is for initial greyboxing.
- Unit CI uses deterministic behavior descriptions, not a real MiMo 9B run.
  Genuine model+Studio proof must have a separate E2E receipt.

## Verification

```bash
python -m pytest tests/test_host_architecture.py tests/test_host_remote_gateway.py -q
python tools/verify_space_assembly_e2e.py
```

The host UI reduction is additionally checked in
`tests/test_host_client_transport.py` and in the
`HostButtonsTwo` compiled case in
`tools/verify_diverse_host_assembly_e2e.py`.
The latter uses two no-argument event/function actions and verifies they
compile without *any* client-code model call.

The second command exercises the 7-source-facet semantic conversion into
14 generated-role Luau source fixtures, seven host-built Remotes, a real Rojo
Place and independent StyLua/Selene validation. This does **not** claim
a game automatically created by the real MiMo model.
