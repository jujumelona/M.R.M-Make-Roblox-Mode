"""Generates Roblox Studio Rojo project trees, native .rbxlx XML Place files, and 3D Workspace objects."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .creator_store import RobloxCreatorStoreCatalog
from .request_traceability import build_request_traceability
from .project_modes import EXISTING_ADDON, write_addon_manifest
from .spec import RobloxAssetSpec, RobloxModuleSpec, RobloxProposal


class RobloxProjectGenerator:
    """Creates Rojo project layouts, Luau file trees, native .rbxlx Place files, and real 3D instances."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.creator_store = RobloxCreatorStoreCatalog()

    def generate_rojo_project_json(self, proposal: RobloxProposal) -> dict[str, Any]:
        """Builds standard Rojo 7.x default.project.json configuration with dynamic remotes."""
        remotes_dict: dict[str, Any] = {"$className": "Folder"}

        # Built-in sample remotes are for generic starter experiences ONLY.
        # A custom architecture defines its own RPC contract; including
        # unrelated combat/obby/tycoon defaults makes the actual project
        # disagree with its source modules and creates useless channels.
        dynamic = proposal.game_design.get("dynamic_design") or {}
        # A dynamic server-only mechanic can legitimately need ZERO Remotes.
        # Never inject unrelated combat/obby/shop defaults merely because
        # the semantic architect declared an empty Remote map.
        declared_remotes: dict[str, str] = {}
        if not dynamic:
            owned = {module.name for module in proposal.modules}
            if "CombatSystem" in owned:
                declared_remotes["AttackRequest"] = "RemoteEvent"
            if "ShopService" in owned:
                declared_remotes["ShopPurchase"] = "RemoteFunction"
                declared_remotes["ShopWeaponUse"] = "RemoteEvent"
            if "ObbyService" in owned:
                declared_remotes["StageChanged"] = "RemoteEvent"
                declared_remotes["ResetToStage"] = "RemoteEvent"
            if "SimulatorService" in owned:
                declared_remotes["ClickRequest"] = "RemoteEvent"
            if "TycoonService" in owned:
                declared_remotes["ButtonPurchased"] = "RemoteEvent"
        # A round is inserted only for an explicit arena request. Keep the
        # private server-owned lifecycle event out of unrelated game genres.
        if any(m.module_id == "mod_arena_round" for m in proposal.modules):
            declared_remotes["RoundStatus"] = "RemoteEvent"
        for remote_name, class_type in dynamic.get("remotes", {}).items():
            if remote_name in declared_remotes and declared_remotes[remote_name] != class_type:
                raise ValueError("Dynamic Remote cannot override an engine contract: " + remote_name)
            declared_remotes[remote_name] = class_type
        for remote_name, class_type in declared_remotes.items():
            remotes_dict[remote_name] = {"$className": class_type}

        features = proposal.game_design.get("features", {})
        counts = proposal.game_design.get("requested_counts", {})
        # In round-based games, lobby spawn and economy points must not be
        # placed inside the combat ring (which is centered on world origin).
        round_lobby = any(m.module_id == "mod_arena_round" for m in proposal.modules)
        world: dict[str, Any] = {"$className": "Workspace"}
        host_world_actions = dynamic.get("host_world_actions") or {}
        declared_world_names = {
            instance["name"] for instance in dynamic.get("world_objects", [])
        }
        if set(host_world_actions) - declared_world_names:
            raise ValueError("Host world prompt references undeclared Part")
        for instance in dynamic.get("world_objects", []):
            name = instance["name"]
            if name in ("Baseplate", "SpawnLocation"):
                raise ValueError("Dynamic world cannot replace existing spawn/baseplate")
            world[name] = {
                "$className": instance["class"],
                "$properties": {
                    "Anchored": True,
                    "Size": instance["size"],
                    "Position": instance["position"],
                },
            }
            if name in host_world_actions:
                route = host_world_actions[name]
                if (instance["class"] != "Part"
                        or not isinstance(route, dict)
                        or not isinstance(route.get("action_text"), str)
                        or not route["action_text"].strip()):
                    raise ValueError("ProximityPrompt must attach to supported world Part")
                world[name]["RMMInteract"] = {
                    "$className": "ProximityPrompt",
                    "$properties": {
                        "ActionText": route["action_text"][:44],
                        "ObjectText": name,
                        "MaxActivationDistance": 10,
                        "RequiresLineOfSight": True,
                    },
                }
        if features.get("is_coin_collect"):
            coins: dict[str, Any] = {"$className": "Folder"}
            for index in range(max(1, min(int(counts.get("coins", 6)), 128))):
                coins[f"Coin{index + 1}"] = {
                    "$className": "Part",
                    "$properties": {
                        "Anchored": True, "CanCollide": False, "CanTouch": True,
                        "Size": [2, 2, 2], "Position": [index * 6 - 15, 3, 68 if round_lobby else 8],
                        "Color": [1, 0.82, 0], "Shape": "Ball",
                    },
                }
            world["Coins"] = coins
        if features.get("is_shop"):
            world["ShopStalls"] = {
                "$className": "Folder",
                "ShopCounter": {
                    "$className": "Part",
                    "$properties": {"Anchored": True, "Size": [10, 4, 4], "Position": [15, 2, 60 if round_lobby else 0]},
                    "ShopPrompt": {
                        "$className": "ProximityPrompt",
                        "$properties": {"ActionText": "Open Shop", "ObjectText": "Merchant"},
                    },
                },
            }
        if features.get("is_combat"):
            walls = {"$className": "Model"}
            for name, size, pos in (
                ("North", [40, 6, 2], [0, 3, 20]),
                ("South", [40, 6, 2], [0, 3, -20]),
                ("East", [2, 6, 40], [20, 3, 0]),
                ("West", [2, 6, 40], [-20, 3, 0]),
            ):
                walls[name] = {"$className": "Part", "$properties": {
                    "Anchored": True, "Size": size, "Position": pos,
                }}
            world["CombatArena"] = walls
        if features.get("is_obby"):
            world["Checkpoints"] = {"$className": "Folder"}
            for stage in range(1, max(1, min(int(counts.get("stages", 5)), 128)) + 1):
                world["Checkpoints"][f"Stage{stage}"] = {"$className": "Part",
                    "$properties": {"Anchored": True, "Size": [8, 1, 8],
                                    "Position": [0, 1 + (stage - 1) * 3, stage * 25]}}
            world["KillBricks"] = {"$className": "Folder",
                "LavaHazard": {"$className": "Part", "$properties": {
                    "Anchored": True, "Size": [20, 1, 10], "Position": [0, 0.5, 35]}}}
        if features.get("is_tycoon"):
            world["TycoonPlots"] = {"$className": "Folder"}
            for name, size, pos in (
                ("Dropper", [4, 2, 4], [-20, 10, 0]),
                ("Conveyor", [6, 1, 24], [-20, 0.5, 12]),
                ("Collector", [8, 2, 8], [-20, 1, 28]),
            ):
                world["TycoonPlots"][name] = {"$className": "Part",
                    "$properties": {"Anchored": True, "Size": size, "Position": pos}}
        if features.get("is_simulator"):
            world["SellZones"] = {"$className": "Folder",
                "SellPad": {"$className": "Part", "$properties": {
                    "Anchored": True, "Size": [12, 1, 12], "Position": [30, 0.5, 0]}}}
        world["Baseplate"] = {"$className": "Part", "$properties": {
            "Anchored": True, "Size": [512, 20, 512], "Position": [0, -10, 0],
        }}
        world["SpawnLocation"] = {"$className": "SpawnLocation", "$properties": {
            "Anchored": True, "Size": [12, 1, 12], "Position": [0, 1, 60 if round_lobby else 0],
        }}
        rep_packages = proposal.game_design.get("ui_backend") == "fusion"
        server_packages = proposal.game_design.get("storage_backend") == "profilestore"
        return {
            "name": proposal.game_title,
            "tree": {
                "$className": "DataModel",
                "ReplicatedStorage": {
                    "$className": "ReplicatedStorage",
                    "Shared": {
                        "$path": "src/shared",
                    },
                    **({"Packages": {"$path": "Packages"}} if rep_packages else {}),
                    "Remotes": remotes_dict,
                },
                "ServerScriptService": {
                    "$className": "ServerScriptService",
                    "$path": "src/server",
                    **({"ServerPackages": {"$path": "ServerPackages"}} if server_packages else {}),
                },
                "StarterPlayer": {
                    "$className": "StarterPlayer",
                    "StarterPlayerScripts": {
                        "$className": "StarterPlayerScripts",
                        "$path": "src/client",
                    },
                },
                "StarterGui": {
                    "$className": "StarterGui",
                    "$path": "src/gui",
                },
                "Workspace": world,
                "SoundService": {
                    "$className": "SoundService",
                },
            },
        }

    def generate_wally_toml(self, proposal: RobloxProposal) -> str:
        """Builds standard Wally package manifest (wally.toml) for dependency management."""
        import hashlib
        clean_name = "game-" + hashlib.sha256(proposal.game_title.encode("utf-8")).hexdigest()[:12]
        safe_description = json.dumps(proposal.description or "Roblox Experience generated by R.M.M", ensure_ascii=False)
        profile = proposal.game_design.get("storage_backend") == "profilestore"
        fusion = proposal.game_design.get("ui_backend") == "fusion"
        fusion_dependency = 'Fusion = "elttob/fusion@0.3.0"\n' if fusion else ""
        profile_dependency = 'ProfileStore = "lm-loleris/profilestore@1.0.3"\n' if profile else ""
        return f"""[package]
name = "rmm/{clean_name}"
description = {safe_description}
version = "0.1.0"
registry = "https://github.com/UpliftGames/wally-index"
realm = "shared"

[dependencies]
Promise = "evaera/promise@^4.0.0"
Signal = "sleitnick/signal@^2.0.1"
{fusion_dependency}
[server-dependencies]
{profile_dependency}
[dev-dependencies]
Jest = "roblox/jest@=3.20.0"
JestGlobals = "roblox/jest-globals@=3.20.0"
"""

    def materialize_project_tree(
        self,
        proposal: RobloxProposal,
        target_dir: Path,
    ) -> dict[str, Path]:
        """Writes all Luau files, default.project.json, wally.toml, and asset loaders to target directory."""
        from .artifact_path_safety import validate_project_layout
        validate_project_layout(target_dir, proposal.modules, proposal.tests)
        target_dir.mkdir(parents=True, exist_ok=True)
        paths_created: dict[str, Path] = {}

        # 1. Write default.project.json
        if proposal.game_design.get("project_mode") == EXISTING_ADDON:
            # No synthetic standalone Place may ever replace the owner's world here.
            pass
        else:
            rojo_config = self.generate_rojo_project_json(proposal)
            rojo_path = target_dir / "default.project.json"
            rojo_path.write_text(json.dumps(rojo_config, indent=2), encoding="utf-8")
            paths_created["rojo_config"] = rojo_path

        research = proposal.game_design.get("pre_design_research")
        if research:
            research_path = target_dir / "pre_design_research.json"
            research_path.write_text(json.dumps(research, indent=2, ensure_ascii=False), encoding="utf-8")
            paths_created["pre_design_research"] = research_path

        blueprint = proposal.game_design.get("implementation_blueprint")
        if blueprint:
            blueprint_path = target_dir / "implementation_blueprint.json"
            blueprint_path.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8")
            paths_created["implementation_blueprint"] = blueprint_path

        # Persist a source-aware ledger alongside the Rojo project. Planned
        # modules cannot masquerade as executed Roblox gameplay.
        trace_path = target_dir / "request_traceability.json"
        trace_path.write_text(json.dumps(build_request_traceability(proposal),
                                         indent=2, ensure_ascii=False), encoding="utf-8")
        paths_created["request_traceability"] = trace_path

        # 2. Write wally.toml for package dependencies
        wally_content = self.generate_wally_toml(proposal)
        wally_path = target_dir / "wally.toml"
        wally_path.write_text(wally_content, encoding="utf-8")
        paths_created["wally_config"] = wally_path

        # Roblox-specific standard library definitions for actual Selene linting
        selene = target_dir / "selene.toml"
        selene.write_text('std = "roblox"\n', encoding="utf-8")
        paths_created["selene_config"] = selene

        from .artifact_path_safety import safe_project_file

        # 3. Write generated Luau modules into src directories
        for module in proposal.modules:
            file_rel = module.file_path
            dest = safe_project_file(
                target_dir, file_rel, prefixes=("src",))
            dest.parent.mkdir(parents=True, exist_ok=True)
            # A previous .server.luau variant auto-runs even after the same
            # service is migrated to a requireable .luau ModuleScript. Rojo
            # includes the entire source folder, so retire that exact stale
            # variant outside src while preserving its original bytes.
            if (module.file_path.startswith("src/server/")
                    and module.file_path.endswith(".luau")
                    and not module.file_path.endswith(".server.luau")):
                legacy = dest.with_name(dest.stem + ".server.luau")
                if legacy.is_file():
                    digest = hashlib.sha256(legacy.read_bytes()).hexdigest()[:12]
                    retired = target_dir / "retired_sources" / (legacy.stem + "-" + digest + ".luau")
                    retired.parent.mkdir(parents=True, exist_ok=True)
                    legacy.replace(retired)
            dest.write_text(module.code, encoding="utf-8")
            paths_created[module.name] = dest

        # The independently generated RMM actions used to stack several
        # purchase, launch, alien, and ship-building GUIs on the same screen
        # coordinates. Install a single host-owned tabbed dock once at least
        # three actual first-party action panels have been generated. Preserve
        # each module's button and event handlers; the dock changes layout only.
        action_panels = (
            "RMMMiningPanel", "RMMResourceMarket", "RMMShipAssembly",
            "RMMRankUpgrade", "RMM_WeaponPerformanceUpgrade",
            "RMMVehicleDeparture", "RMM_AlienCombat",
            "RMM_MarkPlanetColonized", "RMM_ExtractOtherPlanetMineral",
        )
        panel_owners = [
            m for m in proposal.modules
            if m.file_path.startswith("src/client/")
            and any(('gui.Name = "' + name + '"') in (m.code or "")
                    for name in action_panels)
        ]
        if len(panel_owners) >= 3:
            dock_path = safe_project_file(
                target_dir, "src/client/RMMHUDLayout.client.luau",
                prefixes=("src",),
            )
            if dock_path.exists():
                raise ValueError(
                    "RMM_HUD_LAYOUT_CONFLICT: first-party docking source "
                    "would overwrite an authored client"
                )
            source = Path(__file__).with_name("rmm_action_dock.client.luau")
            dock_path.parent.mkdir(parents=True, exist_ok=True)
            dock_path.write_bytes(source.read_bytes())
            paths_created["RMMHUDLayout"] = dock_path

        if proposal.game_design.get("features", {}).get("is_shop"):
            economy_source = Path(__file__).with_name("economy_rules.luau")
            dest = target_dir / "src" / "shared" / "EconomyRules.luau"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(economy_source.read_bytes())
            paths_created["EconomyRules"] = dest

        # Creator Store metadata does NOT imply InsertService loading permission.
        # Do NOT run third-party model insertion inside a live server.
        if proposal.assets:
            asset_plan = target_dir / "creator_store_assets.json"
            asset_plan.write_text(json.dumps({
                "schema": "rmm/asset-import-review-v1",
                "automatic_runtime_import": False,
                "requires_owner_approval_in_studio": True,
                "assets": [{
                    **asset.to_dict(),
                    "creator_badge_only": bool(asset.verified),
                    "content_sanitized": False,
                    "game_usage_permission_verified": False,
                } for asset in proposal.assets],
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            paths_created["creator_store_assets"] = asset_plan

        # 5. Write test specs
        for test in proposal.tests:
            test_rel = test.file_path
            dest = safe_project_file(
                target_dir, test_rel, prefixes=("tests",))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(test.test_code, encoding="utf-8")
            paths_created[test.test_id] = dest

        # Jest Roblox discovery config for engine-side structural tests.
        jest_config = target_dir / "tests" / "jest.config.lua"
        jest_config.parent.mkdir(parents=True, exist_ok=True)
        jest_config.write_text('return { testMatch = {"**/*.spec"} }\n', encoding="utf-8")
        paths_created["jest_config"] = jest_config

        if proposal.game_design.get("project_mode") == EXISTING_ADDON:
            manifest = write_addon_manifest(proposal, self, target_dir)
            paths_created["addon_manifest"] = manifest

        # 6. Write README in project
        readme_path = target_dir / "README.md"
        readme_content = f"""# {proposal.game_title}

Generated by **R.M.M (Roblox Mod & Experience AI)**.

## Project Structure
- `src/server/`: Server-authoritative Luau scripts for `ServerScriptService`.
- `src/client/`: LocalScripts for `StarterPlayerScripts` and UI controllers.
- `src/shared/`: Shared ModuleScripts and networking types for `ReplicatedStorage`.
- `src/gui/`: ScreenGui definitions for `StarterGui`.
- `tests/`: Jest Roblox `.spec.luau` structural smoke tests (real gameplay requires Studio).
- `default.project.json`: Rojo configuration for new Experiences only.
- `addon.manifest.json`: additive patch blueprint for explicitly authorized existing Experiences; never a place replacement.

## How to Run
1. **Studio Direct Launch**: Extract the ZIP and open `compiled_place.rbxlx` in Roblox Studio.
   No Open Cloud API key, Universe ID, Place ID or publishing required.
2. **Offline structural smoke** (optional, on the Windows Studio PC):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\\local_studio\\run_smoke.ps1
   ```
   This checks instantiated scripts, world objects and remotes, not gameplay.
3. **Actual gameplay testing**: Use Studio Play manually, or connect a trusted
   local AI client to the **built-in Studio MCP server** (Assistant > Manage MCP
   Servers). Configuration example: `local_studio/studio_mcp.windows.json`.
   RMM on Colab cannot reach a different computer's Studio by itself.
4. **Rojo Live Sync** (optional): Install the official Rojo Studio plugin,
   run `rojo serve` from this folder, then click **Connect** inside Studio.
"""
        readme_path.write_text(readme_content, encoding="utf-8")
        paths_created["readme"] = readme_path

        return paths_created

    def build_rbxlx_place_file(self, proposal: RobloxProposal, output_file: Path) -> Path:
        """Generates a complete, native Roblox Studio XML place file (.rbxlx) with real 3D objects."""
        output_file.parent.mkdir(parents=True, exist_ok=True)

        roblox = ET.Element(
            "roblox",
            {
                "xmlns:xmime": "http://www.w3.org/2005/05/xmlmime",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:noNamespaceSchemaLocation": "http://www.roblox.com/roblox.xsd",
                "version": "4",
            },
        )

        def add_item(parent: ET.Element, class_name: str, name: str) -> ET.Element:
            item = ET.SubElement(parent, "Item", {"class": class_name, "referent": f"RBX_{name}_{abs(hash(name)) % 10000000}"})
            props = ET.SubElement(item, "Properties")
            string_elem = ET.SubElement(props, "string", {"name": "Name"})
            string_elem.text = name
            return item

        def add_script(parent: ET.Element, class_name: str, name: str, source_code: str) -> ET.Element:
            item = add_item(parent, class_name, name)
            props = item.find("Properties")
            if props is not None:
                source_elem = ET.SubElement(props, "ProtectedString", {"name": "Source"})
                source_elem.text = source_code
            return item

        def add_part(parent: ET.Element, name: str, size: tuple[float, float, float], pos: tuple[float, float, float], color: str = "1001", material: str = "256") -> ET.Element:
            part = add_item(parent, "Part", name)
            props = part.find("Properties")
            if props is not None:
                anchored = ET.SubElement(props, "bool", {"name": "Anchored"})
                anchored.text = "true"
                size_elem = ET.SubElement(props, "Vector3", {"name": "size"})
                ET.SubElement(size_elem, "X").text = str(size[0])
                ET.SubElement(size_elem, "Y").text = str(size[1])
                ET.SubElement(size_elem, "Z").text = str(size[2])
                cframe_elem = ET.SubElement(props, "CoordinateFrame", {"name": "CFrame"})
                ET.SubElement(cframe_elem, "X").text = str(pos[0])
                ET.SubElement(cframe_elem, "Y").text = str(pos[1])
                ET.SubElement(cframe_elem, "Z").text = str(pos[2])
            return part

        # 1. Workspace
        workspace = add_item(roblox, "Workspace", "Workspace")

        # Baseplate
        add_part(workspace, "Baseplate", (512, 20, 512), (0, -10, 0))

        # SpawnLocation
        spawn = add_item(workspace, "SpawnLocation", "SpawnLocation")
        spawn_props = spawn.find("Properties")
        if spawn_props is not None:
            ET.SubElement(spawn_props, "bool", {"name": "Anchored"}).text = "true"
            sp_size = ET.SubElement(spawn_props, "Vector3", {"name": "size"})
            ET.SubElement(sp_size, "X").text = "12"
            ET.SubElement(sp_size, "Y").text = "1"
            ET.SubElement(sp_size, "Z").text = "12"

        # 1b. Real Genre 3D Workspace Objects
        genre = proposal.game_design.get("genre", "Action")
        features = proposal.game_design.get("features", {})

        if features.get("is_obby") or genre == "Obby":
            checkpoints = add_item(workspace, "Folder", "Checkpoints")
            for i in range(1, 6):
                add_part(checkpoints, f"Stage{i}", (8, 1, 8), (0, 1 + (i - 1) * 3, i * 25))
            kill_bricks = add_item(workspace, "Folder", "KillBricks")
            add_part(kill_bricks, "LavaHazard", (20, 1, 10), (0, 0.5, 35))

        if features.get("is_shop") or genre == "Shop":
            shop_stalls = add_item(workspace, "Folder", "ShopStalls")
            counter = add_part(shop_stalls, "ShopCounter", (10, 4, 4), (15, 2, 0))
            # Attach ProximityPrompt
            prompt = add_item(counter, "ProximityPrompt", "ShopPrompt")
            prompt_props = prompt.find("Properties")
            if prompt_props is not None:
                ET.SubElement(prompt_props, "string", {"name": "ActionText"}).text = "Browse Shop"
                ET.SubElement(prompt_props, "string", {"name": "ObjectText"}).text = "Merchant"

        if features.get("is_tycoon") or genre == "Tycoon":
            tycoon_plots = add_item(workspace, "Folder", "TycoonPlots")
            add_part(tycoon_plots, "Dropper", (4, 2, 4), (-20, 10, 0))
            add_part(tycoon_plots, "Conveyor", (6, 1, 24), (-20, 0.5, 12))
            add_part(tycoon_plots, "Collector", (8, 2, 8), (-20, 1, 28))

        if features.get("is_simulator") or genre == "Simulator":
            sell_zones = add_item(workspace, "Folder", "SellZones")
            add_part(sell_zones, "SellPad", (12, 1, 12), (30, 0.5, 0))

        if features.get("is_combat") or genre == "Combat":
            arena = add_item(workspace, "Model", "CombatArena")
            add_part(arena, "ArenaRingWall_N", (40, 6, 2), (0, 3, 20))
            add_part(arena, "ArenaRingWall_S", (40, 6, 2), (0, 3, -20))
            add_part(arena, "ArenaRingWall_E", (2, 6, 40), (20, 3, 0))
            add_part(arena, "ArenaRingWall_W", (2, 6, 40), (-20, 3, 0))

        # 2. Lighting
        add_item(roblox, "Lighting", "Lighting")

        # 3. ReplicatedStorage & Dynamic Remotes
        replicated_storage = add_item(roblox, "ReplicatedStorage", "ReplicatedStorage")
        remotes_folder = add_item(replicated_storage, "Folder", "Remotes")
        add_item(remotes_folder, "RemoteEvent", "AttackRequest")
        add_item(remotes_folder, "RemoteEvent", "DamageEvent")
        add_item(remotes_folder, "RemoteFunction", "ShopPurchase")
        add_item(remotes_folder, "RemoteEvent", "ClickRequest")
        add_item(remotes_folder, "RemoteEvent", "StageChanged")

        # 4. ServerScriptService
        server_script_service = add_item(roblox, "ServerScriptService", "ServerScriptService")

        # 5. StarterGui
        add_item(roblox, "StarterGui", "StarterGui")

        # 6. StarterPlayer
        starter_player = add_item(roblox, "StarterPlayer", "StarterPlayer")
        starter_player_scripts = add_item(starter_player, "StarterPlayerScripts", "StarterPlayerScripts")

        # 7. SoundService: Materialize discovered sound assets directly
        sound_service = add_item(roblox, "SoundService", "SoundService")
        for asset in proposal.assets:
            if asset.asset_type == "Audio":
                clean_name = "".join(c for c in asset.name if c.isalnum()) or "SoundAsset"
                sound_item = add_item(sound_service, "Sound", clean_name)
                snd_props = sound_item.find("Properties")
                if snd_props is not None:
                    ET.SubElement(snd_props, "Content", {"name": "SoundId"}).text = asset.asset_id
                    ET.SubElement(snd_props, "float", {"name": "Volume"}).text = "0.7"

        # 8. Populate Luau scripts from modules into the appropriate services
        for module in proposal.modules:
            code = module.code
            file_name = Path(module.file_path).name

            if module.file_path.endswith(".server.luau") or "server" in module.kind:
                clean_name = file_name.replace(".server.luau", "").replace(".luau", "")
                add_script(server_script_service, "Script", clean_name, code)
            elif module.file_path.endswith(".client.luau") or "client" in module.kind:
                clean_name = file_name.replace(".client.luau", "").replace(".luau", "")
                add_script(starter_player_scripts, "LocalScript", clean_name, code)
            elif "shared" in module.kind or "module" in module.kind or module.file_path.endswith(".luau"):
                clean_name = file_name.replace(".luau", "")
                add_script(replicated_storage, "ModuleScript", clean_name, code)

        tree = ET.ElementTree(roblox)
        ET.indent(tree, space="  ")
        tree.write(str(output_file), encoding="utf-8", xml_declaration=True)
        return output_file

    def pack_project_zip(self, project_dir: Path, zip_output_path: Path) -> Path:
        """Packs the entire project directory into a distribution ZIP."""
        zip_output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_output_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, _, files in os.walk(project_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(project_dir)
                    zip_file.write(file_path, arcname)
        return zip_output_path
