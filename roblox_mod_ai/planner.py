"""Roblox experience planner and feature decomposition engine."""

from __future__ import annotations

import re
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .creator_store import RobloxCreatorStoreCatalog
from .model_router import ModelRouter
from .playtest_runner import RobloxPlaytestRunner
from .spec import (
    ModuleKind,
    RobloxAssetSpec,
    RobloxModuleSpec,
    RobloxProposal,
    RobloxService,
    RobloxTarget,
    RobloxTestSpec,
)


class RobloxGameDesignPlanner:
    """Transforms natural-language game requests into structured Roblox plans."""

    def __init__(
        self,
        router: ModelRouter | None = None,
        creator_store: RobloxCreatorStoreCatalog | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.creator_store = creator_store or RobloxCreatorStoreCatalog()
        self.test_runner = RobloxPlaytestRunner()

    def plan(self, prompt: str) -> RobloxAuthoredPlan:
        """Decompose prompt into functional subsystems, assets, and Luau architecture."""
        # 1. Generate Game Title & Summary
        title_match = re.search(r"['\"]([^'\"]+)['\"]", prompt)
        if title_match:
            raw_title = title_match.group(1)
        else:
            first_words = "".join(w.capitalize() for w in re.findall(r"\w+", prompt)[:3])
            raw_title = first_words or "RobloxExperience"
        game_title = re.sub(r"[^\w]", "", raw_title) or "RobloxExperience"

        # 2. Decompose into Subsystems / Modules
        modules: list[RobloxModuleSpec] = [
            RobloxModuleSpec(
                module_id="mod_player_data",
                name="PlayerDataManager",
                kind=ModuleKind.DATA_STORE,
                file_path="src/server/PlayerDataManager.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                description="Server-authoritative player stats, level, coins, and DataStoreService persistence.",
            ),
            RobloxModuleSpec(
                module_id="mod_combat_core",
                name="CombatSystem",
                kind=ModuleKind.SERVER_SCRIPT,
                file_path="src/server/CombatSystem.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                description="Core gameplay loop, damage validation, hit registration, and knockout logic.",
            ),
            RobloxModuleSpec(
                module_id="mod_network_bridge",
                name="NetworkRemotes",
                kind=ModuleKind.SHARED_MODULE,
                file_path="src/shared/NetworkRemotes.luau",
                roblox_service=RobloxService.REPLICATED_STORAGE,
                description="Shared RemoteEvent channel declarations, game constants, and strict type definitions.",
            ),
            RobloxModuleSpec(
                module_id="mod_client_controller",
                name="CombatController",
                kind=ModuleKind.CLIENT_SCRIPT,
                file_path="src/client/CombatController.client.luau",
                roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                description="Client mouse/touch input handling, attack prediction, and visual effect rendering.",
            ),
            RobloxModuleSpec(
                module_id="mod_hud_controller",
                name="HUDController",
                kind=ModuleKind.CLIENT_SCRIPT,
                file_path="src/client/HUDController.client.luau",
                roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                description="Dynamic UI controller for health bars, coin counter, and in-game notifications.",
            ),
        ]

        # 3. Explore existing assets on Roblox Creator Store
        discovered_assets: list[RobloxAssetSpec] = []
        # Search for weapon / core model
        models = self.creator_store.search(f"{prompt} model", asset_type="Model", limit=2)
        discovered_assets.extend(models)
        # Search for sound effects
        sounds = self.creator_store.search("collect hit sound", asset_type="Audio", limit=2)
        discovered_assets.extend(sounds)

        # 4. Generate Test Specs
        test_specs: list[RobloxTestSpec] = self.test_runner.generate_default_test_specs(
            RobloxProposal(
                requested_prompt=prompt,
                game_title=game_title,
                description=f"Automated Roblox Experience for: {prompt}",
                game_design={},
                modules=modules,
                assets=discovered_assets,
            )
        )

        proposal = RobloxProposal(
            requested_prompt=prompt,
            game_title=game_title,
            description=f"Generated Roblox experience based on prompt: '{prompt}'",
            game_design={
                "core_mechanic": "Server-authoritative interactive gameplay",
                "networking": "RemoteEvents with rate limiting & anti-exploit distance check",
                "storage": "DataStoreService with session-locking & exponential backoff pcall",
                "client_ux": "Responsive UI with TweenService visual feedback",
            },
            modules=modules,
            assets=discovered_assets,
            tests=test_specs,
            target=RobloxTarget(),
        )

        # 5. Render Authored Plan Text
        text = self._render_plan_markdown(proposal)

        authored_plan = RobloxAuthoredPlan(
            requested_prompt=prompt,
            text=text,
            proposal=proposal,
            structured_sections={
                "game_title": game_title,
                "modules": [m.to_dict() for m in modules],
                "assets": [a.to_dict() for a in discovered_assets],
                "tests": [t.to_dict() for t in test_specs],
            },
        )
        authored_plan.create_checkpoint(note="Initial plan generation")
        return authored_plan

    def revise(self, plan: RobloxAuthoredPlan, feedback: str) -> RobloxAuthoredPlan:
        """Revise an existing authored plan based on feedback, preserving unaffected modules."""
        proposal = plan.proposal
        proposal.requested_prompt += f" | Revision: {feedback}"

        # Analyze feedback for additions
        lower_feedback = feedback.lower()
        if "shop" in lower_feedback or "merchant" in lower_feedback:
            shop_module = RobloxModuleSpec(
                module_id="mod_shop_system",
                name="ShopSystem",
                kind=ModuleKind.SERVER_SCRIPT,
                file_path="src/server/ShopSystem.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                description="Server shop transaction validator and inventory item granter.",
            )
            if not any(m.name == "ShopSystem" for m in proposal.modules):
                proposal.modules.append(shop_module)

        if "magic" in lower_feedback or "spell" in lower_feedback or "staff" in lower_feedback:
            magic_module = RobloxModuleSpec(
                module_id="mod_magic_system",
                name="MagicAbilities",
                kind=ModuleKind.SERVER_SCRIPT,
                file_path="src/server/MagicAbilities.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                description="Cooldown-managed magic spells and projectile raycasting.",
            )
            if not any(m.name == "MagicAbilities" for m in proposal.modules):
                proposal.modules.append(magic_module)

        # Query Creator Store for additional assets requested in revision
        new_assets = self.creator_store.search(feedback, limit=2)
        for a in new_assets:
            if not any(existing.asset_id == a.asset_id for existing in proposal.assets):
                proposal.assets.append(a)

        # Update plan text and checkpoint
        plan.revision_count += 1
        plan.text = self._render_plan_markdown(proposal)
        plan.create_checkpoint(note=f"Revision {plan.revision_count}: {feedback}")
        return plan

    def _render_plan_markdown(self, proposal: RobloxProposal) -> str:
        modules_md = "\n".join(
            f"- **`{m.name}`** (`{m.file_path}`):\n  - Service: `{m.roblox_service}`\n  - Role: {m.description}"
            for m in proposal.modules
        )
        assets_md = "\n".join(
            f"- **`{a.name}`** (`{a.asset_id}`):\n  - Type: `{a.asset_type}` | Destination: `{a.destination_service}`\n  - {a.description}"
            for a in proposal.assets
        )
        tests_md = "\n".join(
            f"- **`{t.name}`** (`{t.file_path}`):\n  - Target: `{t.target_module}`"
            for t in proposal.tests
        )

        return f"""# 🎮 Roblox Experience Plan: {proposal.game_title}

> **Prompt**: {proposal.requested_prompt}
> **Target**: Roblox Studio (Luau {proposal.target.luau_version}, Rojo {proposal.target.rojo_version})

## 1. Architectural Architecture & Subsystems
{modules_md}

## 2. Creator Store Assets (Marketplace)
{assets_md}

## 3. Playtest & TestEZ Specifications
{tests_md}

## 4. Production Strategy
- **Client/Server Division**: Strict server authority over health, damage, and currency to prevent client exploits.
- **Data Persistence**: Safe DataStoreService with automatic retry and BindToClose graceful flushing.
- **Sync & Deployment**: Full Rojo `default.project.json` live-sync and `.rbxlx` direct Studio launcher.
"""
