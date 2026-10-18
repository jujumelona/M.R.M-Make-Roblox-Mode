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

The default **multi-facet** architect requests ONLY:

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

The model never outputs `src/server`/`StarterPlayerScripts` paths,
`uses_remotes`, `intent-...` source IDs, RemoteEvent types, world coordinates,
or server/client owner lists. Host expansion attaches those fields using one
source-anchored feature. This removes several classes of format-induced 9B
failures and reduces JSON/schema output length. The model still must describe
actual non-placeholder gameplay and must not omit user requirements.

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

The second command exercises the 7-source-facet semantic conversion into
14 generated-role Luau source fixtures, seven host-built Remotes, a real Rojo
Place and independent StyLua/Selene validation. This does **not** claim
a game automatically created by the real MiMo model.
