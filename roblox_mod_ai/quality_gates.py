"""Source-level acceptance obligations. These are NOT substitutes for engine playtests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .spec import RobloxProposal


def acceptance_obligations(proposal: RobloxProposal, project_root: Path) -> dict:
    """Trace requested mechanics through module source, world, and dependencies.

    Conservative: missing evidence fails. Static proof alone never marks a release tested.
    """
    root = Path(project_root)
    source = {m.name: m.code for m in proposal.modules}
    files = {m.name: root / m.file_path for m in proposal.modules}
    features = proposal.game_design.get("features", {})
    prompt = proposal.requested_prompt.lower()
    checks = []

    def check(identifier: str, ok: bool, detail: str) -> None:
        checks.append({"id": identifier, "passed": bool(ok), "detail": detail})

    def has(name: str, *tokens: str) -> bool:
        return name in files and files[name].is_file() and all(t in source.get(name, "") for t in tokens)

    addon_mode = proposal.game_design.get("project_mode") == "existing_experience_addon"
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
    if coin_requested:
        check("coin.world", bool(world.get("Coins", {}).get("Coin1")), "Collectible coin Instances in Rojo Workspace")
        check("coin.touch_award", has("CoinCollector", ".Touched:Connect", "Coins", ".Value +=", "GetPlayerFromCharacter"),
              "Server Touched handler increments Coins")
        check("coin.respawn", has("CoinCollector", "task.delay", "CanTouch"), "Collectible cooldown and respawn")
    if features.get("is_shop"):
        check("shop.currency", has("ShopService", "EconomyRules.canAfford", "EconomyRules.charge", "OnServerInvoke"),
              "Server validates and deducts balance")
        check("shop.effect", has("ShopService", "speed_boots", "WalkSpeed", "health_potion", "Humanoid", "Activated:Connect"),
              "Shop has measurable speed/health/combat effects, not empty items")
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
        check("combat.server", has("CombatSystem", "OnServerEvent", "MAX_REACH", "TakeDamage"),
              "Server validates hit distance and applies damage")
        check("combat.client", has("CombatController", "FireServer", "InputBegan"),
              "Client submits attack request")
        check("combat.arena", bool(world.get("CombatArena")), "Arena walls in Rojo Workspace")
    if features.get("is_obby"):
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
    check("network.remotes", remotes_present,
          "Declared network Remotes in new Place or additive owner-only overlay")
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
