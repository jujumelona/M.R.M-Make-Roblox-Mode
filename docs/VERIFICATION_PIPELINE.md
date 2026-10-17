# MRM production verification and agent design

## External implementations studied

- Roblox official Studio MCP agent workflow: https://create.roblox.com/docs/ai/accelerated-workflows
- Roblox official StudioTestService (real simulated clients): https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- BloxForge (scoped changes, Rojo/Rokit/Wally, rollback): https://github.com/princeofscale/bloxforge
- Roblox archived place CI/CD reference (Luau execution): https://github.com/Roblox/place-ci-cd-demo
- Rojo v7 project format: https://rojo.space/docs/v7/project-format/

## Release gates

1. Explicit requested mechanics must appear in the persisted feature graph, generated scripts, RemoteEvents and Rojo Workspace. Source checks are obligations, not real gameplay proof.
2. Missing dependencies and cycles cause failure; no success from a partial plan.
3. StyLua, Wally, Selene, and luau-analyze must be installed and actually succeed.
4. Rojo is the only compiler allowed to produce the place. No XML fallback is used.
5. The project ZIP contains a hash manifest for every source file and the Rojo place hash. The package checks source content hashes after ZIP creation.
6. Actual engine smoke and DataStore roundtrip run via Open Cloud on an isolated test place (with explicit user opt-in).
7. Client-server transactions, coin touching, shop effects, and player data restoration must be verified by a separate real StudioTestService multiplayer run. A matching Studio evidence receipt is required.

## Test-place setup

Create a separate disposable TEST experience/place. Never configure a production place as the test target.
Set ROBLOX_OPEN_CLOUD_API_KEY, ROBLOX_TEST_UNIVERSE_ID, ROBLOX_TEST_PLACE_ID, and RMM_ALLOW_TEST_PLACE_PUBLISH=1.
The key requires places:write and luau-execution-sessions:write scopes for this TEST experience.
Without these inputs the runtime check reports unexecuted, not successful.

## Real Studio multiplayer receipt

StudioTestService can create a server and two simulated clients and exercise the player lifecycle.
After performing real checks, export a JSON object with runner=StudioTestService,
place_sha256 equal to SHA-256 of the exact compiled .rbxlx,
and checks = {client_server:true, coin_pickup:true, shop_purchase:true, datastore_restore:true}.
Set RMM_STUDIO_E2E_RECEIPT to the file path. A missing or mismatching receipt blocks success.
This is self-attested evidence, not a cryptographically signed statement from Studio.
Do not set any check to true without a real executed test.

## Status interpretation

- source_only: source tree generated, never release ready.
- source acceptance: files and implementation obligations present, not engine execution.
- Open Cloud smoke: real server DataModel and a separate test DataStore write/read/delete; does not prove multiplayer.
- StudioTestService: must explicitly prove actual server/client and player restore with real players.
- Final success is true only when all required phases have passed.

GitHub Python CI cannot itself perform Windows/macOS Roblox Studio tests. CI success does not certify a playable game.

## Studio E2E harness (actual, not simulated success)

Run `python tools/build_studio_test_place.py <your-generated-project-folder>`.
It creates a **separate** `studio-tests.project.json` mapping the guarded server/client
scripts in `studio_tests/`, leaving `default.project.json` and release files unchanged.
Use `rojo build studio-tests.project.json -o studio-e2e.rbxlx`, open that file in Studio,
and install `studio_tests/RMMQualityRunner.plugin.luau` as a local Studio plugin.
Enable Studio API services for the isolated TEST experience so DataStore can be exercised.
The plugin button runs two actual StudioTestService multiplayer sessions, first
checking 2 clients, real physical pickups, RemoteFunction purchase, item effect,
on-leave save, and then a second session checking same-user data restoration.
If simulated UserIds change across sessions, the restore check correctly fails
instead of assuming success.

The plugin prints a structured RMM_STUDIO_E2E_RESULT only if all phases pass.
Attach the SHA256 of the exact matching release place and record as
RMM_STUDIO_E2E_RECEIPT. The harness is added only to the instrumented test
project; never publish that project to your production game.

Limitation: GitHub Actions validates and builds the Studio test project,
but actual Studio plugin execution requires a running Roblox Studio instance
which is not provided by GitHub Python CI.

### Manually execute real Open Cloud smoke in GitHub Actions

Use the `Roblox Open Cloud smoke (TEST place only)` Actions workflow, not the ordinary
Python CI, after creating a **disposable, isolated Roblox test universe/place**.
Configure the `roblox-test` GitHub environment with the three required secrets:
`ROBLOX_OPEN_CLOUD_API_KEY`, `ROBLOX_TEST_UNIVERSE_ID`,
and `ROBLOX_TEST_PLACE_ID`. Restrict deployment to a dedicated test environment.
The action requires manual `workflow_dispatch` and publishes *only* to the explicitly
configured test IDs. It compiles via Rojo and runs the real server smoke task.
Without credentials it fails closed; ordinary CI never deploys.

This checks server instance structure and the test DataStore only. It does NOT
complete StudioTestService multiplayer testing or certify the production game.

### Produce the Studio receipt from actual Output

After you have compiled both a release place and a `studio-e2e.rbxlx` test place,
open the Studio test place and run the `RMMQualityRunner.plugin.luau` plugin.
Copy the Output containing the `RMM_STUDIO_E2E_RESULT` JSON record into a UTF-8 file
(e.g. `studio-output.txt`). Then run:

```bash
python tools/make_studio_receipt.py --studio-log studio-output.txt \
  --release-place compiled.rbxlx --studio-place studio-e2e.rbxlx \
  --output studio_receipt.json
```

Set `RMM_STUDIO_E2E_RECEIPT` to `studio_receipt.json` when running the production
verification. The converter rejects absent/failed checks and calculates hashes of both
compiled files; it does not invent gameplay results. Studio console output is
**self-attested**, not a cryptographic Roblox certificate.
