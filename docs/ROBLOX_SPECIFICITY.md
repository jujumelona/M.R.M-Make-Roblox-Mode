# Roblox-specific mod architecture in MRM

The word "mod" means something different in Roblox than in Minecraft.
Roblox does **not** expose a generic mechanism for installing Forge/Fabric-style
client/server code in another creator's live game. The owner or someone with
Studio Edit privileges must control the underlying Experience. A game can
contain multiple Places, and a reusable asset/package can be shared into
separate Experiences.

Authoritative primary references:
- [Publish Experiences / Places](https://create.roblox.com/docs/production/publishing/publish-games-and-places)
- [Instance packages / versioned PackageLink](https://create.roblox.com/docs/projects/assets/packages)
- [Client/server replication](https://create.roblox.com/docs/projects/client-server)
- [Remote & ProximityPrompt security](https://create.roblox.com/docs/scripting/security/client-server-boundary)
- [Third-party assets & malicious scripts](https://create.roblox.com/docs/scripting/security/third-party-vulnerabilities)
- [InsertService ownership restrictions](https://create.roblox.com/docs/reference/engine/classes/InsertService)
- [Cross-platform input](https://create.roblox.com/docs/projects/cross-platform)
- [Workspace streaming](https://create.roblox.com/docs/workspace/streaming)

## Supported targets

| Project mode | Files emitted | Can auto-publish? |
| --- | --- | --- |
| `new_experience` (default) | Standalone Rojo world/scripts, Wally, place ZIP | Only through separately verified owner test target |
| `existing_experience_addon` | New Luau code, additive world/Remote overlay, add-on ZIP | **Never** |
| Reusable Studio/Creator Store PackageLink | Not yet implemented | Not supported |

MRM must never silently substitute a new baseplate/SpawnLocation for an
existing Place, nor claim the user may edit someone else's Experience.

### Generating an owned-Experience add-on

```sh
rmm plan "코인 수집 상점을 추가해줘" --mode existing_experience_addon
rmm build --source-only
```

The plan creates `addon.manifest.json`, which specifies required Remotes,
additive Workspace parts, source hashes and human review requirements.
An add-on ZIP is prepared, but `success=false` remains the *game runtime*
verdict; `metadata.addon_prepared=true` means only that staging passed.
There is **no .rbxlx replacement** and no automatic online publishing.

Preview the patch against a *local Rojo source project you control*:

```sh
python tools/install_owned_addon.py --addon /path/to/staged_addon \
  --existing-project /path/to/my-own-rojo-project
```

The preview checks destination mappings, script/file collisions, Remote class
collisions, Workspace object collisions, source file hashes and optional
Wally prerequisites. It never edits the original game.

To apply **only after verifying that you have Studio editing rights**:

```sh
python tools/install_owned_addon.py --addon /path/to/staged_addon \
  --existing-project /path/to/my-own-rojo-project --apply \
  --i-own-this-experience --reviewed-player-data
```

The owner flag is a *declaration*, not a Roblox permission check. Actual
edit/publish rights must still be checked using the owner's Studio account.
The player-data review flag acknowledges an architectural risk: overwriting
or replacing an existing profile/leaderstats backend may destroy or fork
saved currency, items or progression. Never apply a new
`PlayerDataManager` over a running Experience without planning migration
and verifying datastore names and data schema. This tool does **not**
migrate data, install new ProfileStore/Fusion dependencies, modify other
Places, or publish to any live game. It also cannot infer files embedded
in an opaque `.rbxlx` from Rojo source alone.

A typical non-MRM Rojo project may not have
`ReplicatedStorage.Shared`/`src/shared` or a `Workspace` Rojo hierarchy.
The current integration tool **rejects** incompatible layouts rather than
guessing or rewriting them.

## Roblox-specific safeguards

1. **Server authority.** Shop `RemoteFunction` inputs are treated as
   adversarial. Validate type, size, server character alive, shop reach,
   currency and per-player request cooldown. Combat still checks server
   reach and now independently raycasts line-of-sight to prevent hits through
   solid world obstacles. A success receipt does not replace exploit testing.
2. **Cross-platform actions.** Combat actions are bound via
   `ContextActionService` for mouse, touch button and gamepad trigger.
   Mobile camera, reticle placement, UI scaling and actual gamepad/touch
   interaction still require device emulation in Roblox Studio.
3. **Asset permissions.** Creator Store search and account badging are
   metadata, not proof the Experience can load the asset, nor proof its
   scripts are secure. MRM now writes `creator_store_assets.json` and
   will not insert Creator Store Models dynamically into live servers.
   Import manually through the owner's Studio, review provenance,
   scripts, model ownership and any restricted textures/audio before use.
4. **Multi-Place Experiences.** A generated Place is not automatically
   the whole Universe. Teleports, IDs, private instances and profile data
   shared across Places require separate test cases. One-place CI does not
   verify these cross-place properties.
5. **StreamingEnabled.** Client code cannot assume all Workspace assets
   exist immediately. Test client joins, streaming out/in and missing
   parts, especially for dynamic interaction locations.
6. **Versioned Packages.** Reusable model/package distribution should
   eventually generate owner-published `PackageLink` assets with appropriate
   permissions. Current add-on ZIPs are **not** Roblox Packages and must not
   be represented as Marketplace-installable mods.
7. **Engine tests.** Python, Lune, Wally, Selene and Rojo checks are
   real but not Roblox player sessions. StudioTestService and Open Cloud
   tests still require a genuine owner-controlled test Experience; absence
   of engine results remains unverified.

## Remaining integration work

- Runtime gameplay tests of the **patched owner's actual Place**, not
  only the sample stand-alone arena.
- Compatibility adapters for arbitrary external Rojo directory layouts,
  in-place existing scripts, and heterogeneous DataStore schemas.
- Real package publishing/versioning and permissions via Studio.
- Multi-Place and streaming/mobile/device playtests.

These are not silently marked complete merely because static CI passes.
