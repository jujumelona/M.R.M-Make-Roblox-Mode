# Generic gameplay compilation: contract-first boundary

This document describes **implemented** code, not a claim that any arbitrary
Roblox game can already be generated or that Studio gameplay was tested.

## Verified implementation paths

- `roblox_mod_ai/host_atomic_effect.py` accepts an explicitly declared
  `rmm/atomic-effect-v1` contract for **one bounded persistent integer
  transition**. It works without testing game/module names, translates a
  validated typed action into server-owned Luau and leaves the existing
  `render_typed_client` responsible for the UI. The single transition
  supports `increment`, `decrement`, and `set`.
- `roblox_mod_ai/host_ordered_assembly.py` uses source-declared world Part
  sizes to place an ordered component graph. It checks for unique source
  ownership, rejects invalid geometry, computes external pilot seating from
  actual component bounds, and provides an owner-checked physical boarding
  prompt. The existing *actor assembly protocol* is still specialized and
  must not be represented as a genre-neutral system.
- `roblox_mod_ai/host_hud.py` discovers Remote-bound action ScreenGuis from
  generated client source. It no longer uses a list of action GUI names.
  It uses a SHA-256 receipt to regenerate host-owned UI when the design
  changes while refusing to overwrite user-edited files.

## Example atomic action declaration

This block supplements an already validated `dynamic_design.host_actions`
RemoteFunction route, matching `host_typed_actions`, source-linked module
mapping, and an injected `PlayerDataManager` ModuleScript. It is **not**
a user prompt or an independent freeform server program:

```json
{
  "host_typed_actions": {
    "CollectSeeds": {
      "server": "ActionServer",
      "client": "ActionClient",
      "transport_only": false,
      "world_entities": [],
      "contract": {
        "inputs": [
          {"id": "quantity", "label": "Quantity", "type": "integer",
           "min": 1, "max": 10}
        ],
        "target": {"kind": "none"},
        "state_changes": [
          {"scope": "player", "key": "GardenState.seeds",
           "operation": "increment"}
        ]
      }
    }
  },
  "host_executable_actions": {
    "CollectSeeds": {
      "schema": "rmm/atomic-effect-v1",
      "namespace": "GardenState",
      "field": "seeds",
      "operation": "increment",
      "amount": {"input": "quantity"},
      "limit": 500
    }
  }
}
```

The host rejects undeclared state keys, unvalidated inputs, unavailable
persistence, invalid Remote arity, unbound world objects, and unsupported
operations. Server requests do not accept a user ID or client-supplied state
namespace. This minimal contract must not be used for activities that need
additional guards (e.g. mining yield only after a real hit, timed cooldown,
purchase with a price deduction, physical building, hostile combat).
A planner must provide those semantics through a separately verified
contract; **never** synthesize free currency from prose.

## Still missing

1. Automatic, source-verified model-to-executable-contract authoring.
   Currently `host_executable_actions` is opt-in input data, not supplied
   automatically by the general dynamic planner.
2. Multi-state transactions with cross-resource preconditions, inventory
   ownership, and external side effects. A valid purchase is not a single
   unconditional integer addition.
3. Generalized object/actor/world generation and a real engine playtest.
   The older genre-specific adapters remain for backward compatibility.
4. A green CI suite: unrelated pre-existing test failures cannot be claimed
   repaired by these changes.

**Rule:** feature metadata must be tied to original request evidence and
an actual module/Remote/world/typed ABI. Unknown mechanics must fail
explicitly; passing by inventing a module name or hardcoded coordinate is not
acceptable.

## Targeted verification

```bash
python -m pytest -q tests/test_generic_atomic_action_compiler.py \
  tests/test_57_host_hud.py tests/test_59_pilot_seat_collision.py \
  tests/test_plan83_ordered_assembly_launch.py
```

The CI Rojo smoke test validates build tooling for the repository. It does
not replace a Roblox Studio multiplayer and persistence playtest.
