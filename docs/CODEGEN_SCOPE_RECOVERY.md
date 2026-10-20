# Per-module code generation and recovery

## Scope handoff

The scoped architect's `module_world_objects` map must survive planning and
proposal serialization, including explicit empty lists. The coder must not
receive unrelated world objects after this handoff.

A source requirement can have several implementation owners. For multiple
server responsibilities, project its detailed plan onto the current module's
declared behavior. Preserve the approved original proposal. A single server and
its clients for the same facet retain their shared prerequisites, rejection
conditions and implementation steps, with file ownership projected to the
current coder task. Retries receive the same scoped requirements.

Saved proposals that predate the ownership field retain their legacy world
references. Regenerate their design to obtain authoritative object ownership;
do not infer ownership from object-name similarity.

## Recovery and interfaces

Inspect an existing source before constructing the first recovery prompt.
Parser-invalid source is supplied as numbered diagnostic context around the
actual failure, rather than as a full implementation to continue. The original
source and complete diagnostics remain in the local failure report.

Gameplay modules must use actual exported dependency APIs. A generated service
is not a Roblox engine service. Only bootstrap may call dependency `start`, and
gameplay must not replace dependency methods. Apply these checks both during
generation and at the final source interface audit. Recognize simple local
aliases conservatively; returned values, shadowed names and unrelated table
members must not be treated as dependency tables.

## Regression coverage

- Planner -> saved proposal -> coder object ownership.
- Multiple server owners isolated even within one facet.
- Shared server/client prerequisites preserved on retries.
- First recovery call preflights malformed source.
- Engine lookup, lifecycle call, dependency overwrite and missing API rejected.
- Real dependency APIs, method return values and unrelated members accepted.

The tests use deterministic model transports. Real StyLua validates source
grammar; Rojo validates packaging. Neither establishes real GGUF generation
success or Roblox Studio gameplay execution.
