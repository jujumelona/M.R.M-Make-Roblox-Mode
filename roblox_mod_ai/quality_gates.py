"""Source-level acceptance obligations. These are NOT substitutes for engine playtests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .spec import RobloxProposal
from .dynamic_wiring import inspect_dynamic_remote_wiring, _mask_strings, _without_comments
from .server_interface_audit import inspect_dynamic_server_interfaces
from .luau_api_sanity import invalid_luau_apis
from .request_contract import ledger_complete, implementation_facets
from .gameplay_contract import validate_gameplay_contract
from .implementation_blueprint import audit_implementation_blueprint
from .detailed_plan import audit_detailed_plan


def _contains_source_placeholder(body: str) -> bool:
    """Inspect executable tokens, not legitimate Roblox PlaceholderText UI.

    A case-insensitive substring search incorrectly rejected working TextBox
    code and could leave the final static repair loop retrying indefinitely.
    """
    active = _mask_strings(_without_comments(body))
    return bool(re.search(
        r"\b(?:TODO|FIXME|placeholder|not\s+implemented|loadstring)\b",
        active, flags=re.IGNORECASE))


def acceptance_obligations(proposal: RobloxProposal, project_root: Path) -> dict:
    """Trace requested mechanics through module source, world, and dependencies.

    Conservative: missing evidence fails. Static proof alone never marks a release tested.
    """
    root = Path(project_root)
    source = {m.name: m.code for m in proposal.modules}
    files = {m.name: root / m.file_path for m in proposal.modules}
    features = proposal.game_design.get("features", {})
    prompt = proposal.requested_prompt.lower()
    pre = proposal.game_design.get("pre_design_research", {})
    ledger = pre.get("ledger", {})
    checks = []

    def check(identifier: str, ok: bool, detail: str) -> None:
        checks.append({"id": identifier, "passed": bool(ok), "detail": detail})

    def has(name: str, *tokens: str) -> bool:
        return name in files and files[name].is_file() and all(t in source.get(name, "") for t in tokens)

    addon_mode = proposal.game_design.get("project_mode") == "existing_experience_addon"
    config: dict = {}
    try:
        if addon_mode:
            manifest = json.loads((root / "addon.manifest.json").read_text(encoding="utf-8"))
            world = manifest["workspace_additions"]
            remotes_present = bool(manifest.get("remote_additions"))
        else:
            config = json.loads((root / "default.project.json").read_text(encoding="utf-8"))
            world = config["tree"]["Workspace"]
            remotes_present = bool(config.get("tree", {}).get("ReplicatedStorage", {}).get("Remotes"))
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        world = {}
        remotes_present = False
    coin_requested = bool(features.get("is_coin_collect")) or any(
        word in prompt for word in ("코인 수집", "동전 수집", "collect coins", "coin collection")
    )
    leaderboard = bool(features.get("is_leaderboard")) or any(
        word in prompt for word in ("리더보드", "leaderboard", "leaderstats")
    )
    if pre:
        check("planning.ledger", ledger.get("original_prompt") == proposal.requested_prompt
              and bool(ledger.get("requirements")) and pre.get("schema") == "rmm/pre-design-rag-v1",
              "Same original request and feature ledger used for pre-design and production")
        check("planning.request_coverage", ledger_complete(proposal.requested_prompt, ledger),
              "No known requested gameplay silently omitted from implementation")
    # A plan is not complete merely because its individual modules exist.
    # Recompute from the current requirements/modules to detect stale revisions.
    if pre or "implementation_blueprint" in proposal.game_design:
        blueprint_audit = audit_implementation_blueprint(proposal)
        check("planning.integration_blueprint", blueprint_audit["passed"],
              "Source-bound blueprint matches current requirements and has no unowned mechanics: "
              + "; ".join(blueprint_audit["errors"]))
    if "detailed_implementation_plan" in proposal.game_design:
        detail_audit = audit_detailed_plan(proposal)
        check("planning.detailed_specification", detail_audit["passed"],
              "Detailed requirement ownership, preconditions, transitions, "
              "edge cases, dependencies and validation match current plan: "
              + "; ".join(detail_audit["errors"]))
    # A newer authored game plan has a source-bound gameplay lifecycle.
    # Legacy isolated module tests are still source-only fixtures; do not
    # invent a verified ending for older incomplete saved proposals.
    if "gameplay_contract" in proposal.game_design:
        for lifecycle in validate_gameplay_contract(proposal, root):
            check(lifecycle["id"], lifecycle["passed"], lifecycle["detail"])
    elif pre and proposal.game_design.get("project_mode") == "new_experience":
        check("lifecycle.present", False,
              "Re-plan this legacy game to include objectives, progression and outcome ownership")
    if coin_requested:
        requested_count = int(proposal.game_design.get("requested_counts", {}).get("coins", 6))
        actual_count = len([k for k in world.get("Coins", {}) if k.startswith("Coin")])
        check("coin.requested_count", requested_count <= 128 and actual_count == requested_count,
              "Generated coin count satisfies authored quantitative request")
        check("coin.world", bool(world.get("Coins", {}).get("Coin1")), "Collectible coin Instances in Rojo Workspace")
        check("coin.touch_award", has("CoinCollector", ".Touched:Connect", "Coins", ".Value +=", "GetPlayerFromCharacter"),
              "Server Touched handler increments Coins")
        check("coin.respawn", has("CoinCollector", "task.delay", "CanTouch"), "Collectible cooldown and respawn")
    if features.get("is_shop"):
        check("shop.currency", has("ShopService", "EconomyRules.canAfford", "EconomyRules.charge", "OnServerInvoke"),
              "Server validates and deducts balance")
        check("shop.remote_security", has("ShopService",
            'typeof(itemId) ~= "string"', 'PURCHASE_COOLDOWN', 'MAX_SHOP_DISTANCE',
            'humanoid.Health <= 0', 'ShopStalls'),
              "RemoteFunction type, distance, character and rate validated by server")
        check("shop.effect", has("ShopService", "speed_boots", "WalkSpeed", "health_potion", "Humanoid",
                                  "weaponUse.OnServerEvent", 'typeof(weaponId) ~= "string"')
              and has("ShopController", "child.Activated:Connect", 'weaponUse:FireServer("magic_staff")')
              and "tool.Activated:Connect" not in source.get("ShopService", ""),
              "Tool.Activated is client-only; authoritative server validates every weapon request")
        check("shop.ui", has("ShopController", "ScreenGui", "TextButton", "InvokeServer", "ProximityPrompt"),
              "GUI buttons invoke purchase RemoteFunction")
        check("shop.world", bool(world.get("ShopStalls", {}).get("ShopCounter", {}).get("ShopPrompt")),
              "Shop ProximityPrompt included by Rojo")
        if coin_requested:
            check("coin.to.shop", has("CoinCollector", "Coins", ".Value +=") and has("ShopService", "Coins", "EconomyRules.charge"),
                  "Producer and consumer share authoritative leaderstats Coins")
    if leaderboard:
        check("leaderboard.stats", (
            has("PlayerDataManager", 'stats.Name = "leaderstats"', '"Coins"', '"Level"', 'stats.Parent = player')
            if proposal.game_design.get("storage_backend") == "profilestore"
            else has("PlayerDataManager", 'leaderstats.Name = "leaderstats"', '"Coins"', '"Level"')
        ), "Player stats replicated as leaderstats folder")
        check("leaderboard.hud", (
            has("HUDController", "ScreenGui", "TextLabel", "coins.Changed")
            if proposal.game_design.get("ui_backend") != "fusion"
            else has("HUDController", "scope:New", "coinState:set", "CoinsDisplay")
        ),
              "HUD reflects changing coin balance")
    if features.get("is_combat"):
        check("combat.server", has("CombatSystem", "OnServerEvent", "MAX_REACH", "TakeDamage",
                                         "FilterDescendantsInstances", "IsDescendantOf"),
              "Server validates hit distance and applies damage")
        check("combat.client", has("CombatController", "FireServer", "BindAction",
                "MouseButton1", "ButtonR2", "SetTitle"),
              "Client submits attack request")
        check("combat.arena", bool(world.get("CombatArena")), "Arena walls in Rojo Workspace")
    has_arena_round = any(m.module_id == "mod_arena_round" for m in proposal.modules)
    if has_arena_round:
        check("arena.placement", has("ArenaRoundService", "CombatArena", "PivotTo", "spawnSlot"),
              "Each enrolled arena fighter must be placed inside the combat ring")
        # A working round arena needs an out-of-combat lobby. A spawn, shop or
        # collectible placed between its walls lets spectators enter combat.
        arena = world.get("CombatArena", {})
        def position(row: dict) -> list:
            return row.get("$properties", {}).get("Position", [])
        west, east = position(arena.get("West", {})), position(arena.get("East", {}))
        south, north = position(arena.get("South", {})), position(arena.get("North", {}))
        if all(len(p) == 3 for p in (west, east, south, north)):
            def inside_ring(p: list) -> bool:
                return len(p) == 3 and west[0] < p[0] < east[0] and south[2] < p[2] < north[2]
            spawn = position(world.get("SpawnLocation", {}))
            shop = position(world.get("ShopStalls", {}).get("ShopCounter", {}))
            coins = [position(value) for key, value in world.get("Coins", {}).items()
                     if key.startswith("Coin")]
            check("arena.lobby_separation", not inside_ring(spawn)
                  and (not features.get("is_shop") or not inside_ring(shop))
                  and not any(inside_ring(p) for p in coins),
                  "Lobby spawn, shop and pickups must be outside the fighting ring")
        else:
            check("arena.lobby_separation", False, "Arena walls are missing positional geometry")
        check("arena.result_statistics", has("ArenaRoundService", '"Wins"', "wins.Value += 1"),
              "Every match winner receives a persisted win statistic")
        check("arena.unauthorized_damage", has("CombatSystem", "ArenaRoundActive", "InArenaRound"),
              "Combat server rejects attacks outside the active round")
    if features.get("is_combat") and leaderboard:
        if proposal.game_design.get("storage_backend") == "profilestore":
            persisted_records = has("PlayerDataManager", "profile.Data", '"Wins"', '"KOs"',
                                    'wins=0', 'kos=0')
        else:
            persisted_records = has("PlayerDataManager", '"Wins"', '"KOs"',
                                    "stored.wins", "stored.kos", "data.wins", "data.kos")
        check("leaderboard.combat_records", persisted_records
              and has("CombatSystem", '"KOs"', "kos.Value += 1"),
              "PvP win and knockout totals are saved and available as leaderstats")
    if features.get("is_shop") and features.get("is_combat"):
        check("combat.shop_credit", has("ShopService", "RMMCombatCredit", "credit:Fire")
              and has("CombatSystem", "RMMCombatCredit", "trackKnockout"),
              "Purchased weapon credits kills through the server combat pipeline")
        if has_arena_round:
            check("arena.shop_weapon_security",
                  has("ShopService", "ArenaRoundActive", "InArenaRound",
                      "GetPlayerFromCharacter"),
                  "Shop weapons cannot damage spectators or bypass the round state")

    if features.get("is_obby"):
        requested = int(proposal.game_design.get("requested_counts", {}).get("stages", 5))
        actual = len([key for key in world.get("Checkpoints", {}) if key.startswith("Stage")])
        check("obby.requested_stages", requested <= 128 and actual == requested,
              "Checkpoint count matches explicit user request; never silently compress 50 stages to 5")
        check("obby.world", bool(world.get("Checkpoints")), "Checkpoint instances available")
    if features.get("is_tycoon"):
        check("tycoon.world", bool(world.get("TycoonPlots")), "Tycoon parts available")
    if features.get("is_simulator"):
        check("simulator.world", bool(world.get("SellZones")), "Sell zone available")

    if proposal.game_design.get("storage_backend") == "profilestore":
        check("persistence.handler", has("PlayerDataManager", "ProfileStore.New",
              "StartSessionAsync", "EndSession", "OwnedItems", "OnSessionEnd"),
              "External ProfileStore sessions, autosave and inventory replication configured")
    else:
        check("persistence.handler", has("PlayerDataManager", "UpdateAsync", "BindToClose",
                                          "lockUntil", "sessionLocks", "OwnedItems", "retryWithBackoff"),
              "Built-in atomic DataStore session lease and inventory configured")
    if proposal.game_design.get("ui_backend") == "fusion":
        check("ui.fusion", has("HUDController", "Fusion.scoped", "Fusion.Children", "scope:Computed"),
              "Fusion reactive HUD generated")
    if features.get("is_magic"):
        check("magic.ability", has("MagicAbilities", "OnServerEvent", "Raycast", "cooldown"),
              "Requested magic may not be replaced with a generic stub")
    dyn = proposal.game_design.get("dynamic_design") or {}
    if dyn:
        interfaces = inspect_dynamic_server_interfaces(proposal)
        for contract in interfaces["checks"]:
            check(contract["id"], contract["passed"], contract["detail"])
        wiring = inspect_dynamic_remote_wiring(proposal)
        for entry in wiring["checks"]:
            check(entry["id"], entry["passed"],
                  "Code-level client Remote call and server handler connected: " +
                  str(entry["detail"]))
        requirements = set(dyn.get("acceptance", {}))
        check("dynamic.no_unverified_reuse", dyn.get("source_reuse") == "none_unless_validated"
              and not any(m.name not in {"NetworkRemotes", "PlayerDataManager", "GameObjectiveController"}
                          and m.module_id != "mod_dynamic_server_bootstrap"
                          and not m.module_id.startswith("dyn_") for m in proposal.modules),
              "Unsupported request does not re-use incomplete fixed game templates")
        assignments = dyn.get("module_requirements", {})
        model_modules = [m for m in proposal.modules if m.module_id.startswith("dyn_")]
        covered = {req for m in model_modules for req in assignments.get(m.module_id, [])}
        # Require every original source-anchored mechanic, without double-counting
        # a generic keyword category already represented by that same source.
        authored_facets = {item["id"] for item in implementation_facets(ledger)}
        implemented_facets = {facet for m in model_modules for facet in
                              dyn.get("module_facets", {}).get(m.module_id, [])}
        check("dynamic.facets", implemented_facets == authored_facets
              and set(dyn.get("acceptance_facets", {})) == authored_facets,
              "Every requested gameplay capability has implementation ownership and acceptance criteria")
        check("dynamic.requirements", requirements and requirements == covered,
              "Each user requirement has assigned novel implementation and observable acceptance case")
        for module in model_modules:
            body = source.get(module.name, "")
            # Reject acceptance of a different code snapshot from the saved
            # file that Rojo actually builds. In production the orchestrator
            # updates code from the formatted source immediately before audit.
            saved = root / module.file_path
            try:
                on_disk = saved.read_text(encoding="utf-8")
            except OSError:
                on_disk = None
            check("dynamic.source." + module.name,
                  on_disk is not None and on_disk == body,
                  "Production must validate exactly the same saved Luau that Rojo builds")
            # Generator-side role checks do not protect sources restored
            # from checkpoints or rewritten by formatter/repair tools.
            # Check the actual file used for compilation, excluding literals.
            active_source = _mask_strings(_without_comments(
                on_disk if on_disk is not None else body))
            is_server = module.file_path.startswith("src/server/")
            is_client = module.file_path.endswith(".client.luau")
            forbidden = (
                (r"\bLocalPlayer\b|\bFireServer\s*\(|\bInvokeServer\s*\("
                 r"|\bOnClientEvent\b|\bOnClientInvoke\b")
                if is_server else
                (r"\bDataStoreService\b|\bOnServerEvent\b|\bOnServerInvoke\b"
                 r"|\bFireClient\s*\(|\bFireAllClients\s*\(")
                if is_client else ""
            )
            api_faults = invalid_luau_apis(
                on_disk if on_disk is not None else body)
            check("dynamic.api." + module.name, not api_faults,
                  "Invalid Roblox methods detected: " + "; ".join(api_faults))
            # Recheck the FINAL on-disk source, not only the initial model
            # body. World-movement obligations must survive formatting,
            # source review repair, and imported generation checkpoints.
            motion_spec = (dyn.get("host_world_motion") or {}).get(module.name)
            if motion_spec is not None:
                from .world_motion_contract import vehicle_motion_code_errors
                motion_errors = (
                    vehicle_motion_code_errors(on_disk or "")
                    if is_server else ["Vehicle movement must be server-owned"]
                )
                check("dynamic.world_motion." + module.name,
                      on_disk is not None and not motion_errors,
                      "Physical craft relocation in final generated server Luau: " +
                      "; ".join(motion_errors))
            # Some Roblox service names occur inside the string argument to
            # GetService, so a correctly string-masked scan cannot match them
            # directly. Accept the name only when the GetService call prefix
            # exists as real code at the same offset, not in comments/strings.
            stripped = _without_comments(on_disk if on_disk is not None else body)
            forbidden_service = False
            if is_client:
                for match in re.finditer(
                    r"""\bgame\s*:\s*GetService\s*\(\s*(['"])(?:DataStoreService|ServerStorage|ServerScriptService)\1\s*\)""",
                    stripped,
                ):
                    if re.match(
                        r"\bgame\s*:\s*GetService\s*\(",
                        active_source[match.start():],
                    ):
                        forbidden_service = True
                        break
            invalid_realm = bool(forbidden and re.search(
                forbidden, active_source)) or forbidden_service
            check("dynamic.realm." + module.name,
                  not invalid_realm,
                  "Client-only/server-only Roblox APIs must not cross Luau realms")
            check("dynamic.code." + module.name,
                  bool(body.strip()) and len(body) >= 75
                  and not _contains_source_placeholder(body)
                  and has(module.name, "--!strict"),
                  "Novel gameplay must contain actual saved Luau source; no placeholder or empty table")
        for name, remote_type in dyn.get("remotes", {}).items():
            check("dynamic.remote." + name,
                  (not addon_mode and (root / "default.project.json").exists()
                   and json.loads((root / "default.project.json").read_text(encoding="utf-8"))
                   ["tree"]["ReplicatedStorage"]["Remotes"].get(name, {}).get("$className") == remote_type)
                  or (addon_mode and manifest.get("remote_additions", {}).get(name, {}).get("$className") == remote_type),
                  "Model-proposed Remotes must be instantiated in Rojo, not merely discussed")
        for item in dyn.get("world_objects", []):
            check("dynamic.world." + item["name"],
                  world.get(item["name"], {}).get("$className") == item["class"],
                  "Model-declared 3D objects materialized in real Rojo tree")
    check("network.remotes", remotes_present,
          "Declared network Remotes in new Place or additive owner-only overlay")
    if not addon_mode and not proposal.game_design.get("dynamic_design"):
        actual_remotes = config.get("tree", {}).get("ReplicatedStorage", {}).get("Remotes", {})
        expected = set()
        owned_names = {m.name for m in proposal.modules}
        for owner_name, remote_names in (
            ("CombatSystem", ("AttackRequest",)),
            ("ShopService", ("ShopPurchase", "ShopWeaponUse")),
            ("ArenaRoundService", ("RoundStatus",)),
            ("ObbyService", ("StageChanged", "ResetToStage")),
            ("TycoonService", ("ButtonPurchased",)),
            ("SimulatorService", ("ClickRequest",)),
        ):
            if owner_name in owned_names:
                expected.update(remote_names)
        check("network.exact_owned_remotes", set(actual_remotes) - {"$className"} == expected,
              "Every published Remote belongs to an installed subsystem; no generic unused attack/stage channels")
        bridge = source.get("NetworkRemotes", "")
        check("network.shared_matches_rojo", all(f'{name} = "{name}"' in bridge for name in expected),
              "Shared Remote names match the built Studio project")
    if addon_mode:
        check("addon.non_destructive", not (root / "default.project.json").exists()
              and (root / "addon.manifest.json").exists()
              and "Baseplate" not in world and "SpawnLocation" not in world,
              "Existing Experience add-on never replaces base world")
    return {
        "passed": bool(checks) and all(c["passed"] for c in checks),
        "checks": checks,
        "requested_prompt": proposal.requested_prompt,
        "note": "Source-level obligations only; no Roblox engine execution was performed.",
    }


def make_artifact_manifest(project_root: Path, place_file: Path) -> dict:
    """Content hashes bind ZIP's Rojo sources to its Rojo-compiled place."""
    root = Path(project_root)
    files = {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file() and p.name != "artifact_manifest.json"
    }
    return {
        "schema": "rmm/artifacts-v1",
        "builder": "rojo-only",
        "source_files": files,
        "place_sha256": hashlib.sha256(Path(place_file).read_bytes()).hexdigest(),
    }
