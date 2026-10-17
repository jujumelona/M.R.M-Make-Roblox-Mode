"""Roblox experience planner and feature decomposition engine."""

from __future__ import annotations

import re
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .creator_store import RobloxCreatorStoreCatalog
from .pre_design_research import RobloxPreDesignResearch
from .dynamic_architect import RobloxDynamicArchitect, DynamicDesignError, dynamic_design_enabled
from .project_modes import validate_mode
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
    """Transforms natural-language game requests into structured, genre-specific Roblox plans."""

    def __init__(
        self,
        router: ModelRouter | None = None,
        creator_store: RobloxCreatorStoreCatalog | None = None,
        pre_design_research: RobloxPreDesignResearch | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.creator_store = creator_store or RobloxCreatorStoreCatalog()
        self.test_runner = RobloxPlaytestRunner()
        self.researcher = pre_design_research or RobloxPreDesignResearch(creator_store=self.creator_store, router=self.router)

    def detect_genres_and_features(self, prompt: str) -> dict[str, bool]:
        """Classifies the gameplay genres and subsystems requested in prompt."""
        p = prompt.lower()
        return {
            "is_shop": any(w in p for w in ["shop", "store", "buy", "merchant", "상점", "구매", "상점가", "아이템샵"]),
            "is_obby": any(w in p for w in ["obby", "parkour", "jump", "checkpoint", "점프맵", "파쿠르", "스테이지", "용암"]),
            "is_tycoon": any(w in p for w in ["tycoon", "dropper", "conveyor", "타이쿤", "드롭퍼", "컨베이어", "공장"]),
            "is_simulator": any(w in p for w in ["simulator", "click", "mining", "bag", "시뮬레이터", "클릭", "가방", "채광"]),
            "is_magic": any(w in p for w in ["magic", "spell", "staff", "ability", "마법", "스킬", "지팡이"]),
            "is_combat": any(w in p for w in ["combat", "sword", "arena", "battle", "pvp", "pve", "검투", "아레나", "전투", "배틀", "무기"]),
            "is_coin_collect": any(w in p for w in ["coin", "coins", "코인", "동전", "수집"]),
            "is_leaderboard": any(w in p for w in ["leaderboard", "leaderstats", "리더보드", "순위"]),
        }

    def plan(self, prompt: str, *, project_mode: str = "new_experience") -> RobloxAuthoredPlan:
        """Decompose prompt into functional subsystems, assets, and Luau architecture."""
        validate_mode(project_mode)
        # MMM request-first contract: retrieve before selecting mechanics/modules.
        research = self.researcher.research(prompt)
        # 1. Generate Game Title
        title_match = re.search(r"['\"]([^'\"]+)['\"]", prompt)
        if title_match:
            raw_title = title_match.group(1)
        else:
            first_words = "".join(w.capitalize() for w in re.findall(r"\w+", prompt)[:3])
            raw_title = first_words or "RobloxExperience"
        game_title = re.sub(r"[^\w]", "", raw_title) or "RobloxExperience"

        # 2. Detect requested subsystems dynamically
        features = self.detect_genres_and_features(prompt)
        # Unsupported gameplay is recorded and fails quality checks at build time.
        # It must never silently become a generic combat or empty valid world.
        if not any(features.values()):
            research["ledger"]["unimplemented_facets"] = sorted(set(
                research["ledger"]["unimplemented_facets"] + ["unclassified_gameplay"]
            ))
        import os
        storage_backend = "profilestore" if (
            "profilestore" in prompt.lower() or os.environ.get("RMM_STORAGE_BACKEND") == "profilestore"
        ) else "builtin"
        ui_backend = "fusion" if (
            "fusion" in prompt.lower() or os.environ.get("RMM_UI_BACKEND") == "fusion"
        ) else "builtin"

        # Quantitative requirements come from authored text, not hardcoded demo sizes.
        counts: dict[str, int] = {}
        stage_match = re.search(r"(\d{1,4})\s*(?:단계|스테이지|stages?|checkpoints?)", prompt, re.IGNORECASE)
        if stage_match:
            counts["stages"] = int(stage_match.group(1))
        coin_match = re.search(r"(\d{1,4})\s*(?:개(?:의)?\s*)?(?:코인|동전|coins?)", prompt, re.IGNORECASE)
        if coin_match:
            counts["coins"] = int(coin_match.group(1))
        else:
            reverse_coin = re.search(r"(?:코인|동전|coins?)\s*(\d{1,4})\s*개?", prompt, re.IGNORECASE)
            if reverse_coin:
                counts["coins"] = int(reverse_coin.group(1))
        if any(n <= 0 or n > 128 for n in counts.values()):
            research["ledger"]["unimplemented_facets"] = sorted(set(
                research["ledger"]["unimplemented_facets"] + ["requested_count_exceeds_safe_build_limit"]
            ))

        # Base modules required by every safe Roblox project: NetworkRemotes & PlayerDataManager
        modules: list[RobloxModuleSpec] = [
            RobloxModuleSpec(
                module_id="mod_network_bridge",
                name="NetworkRemotes",
                kind=ModuleKind.SHARED_MODULE,
                file_path="src/shared/NetworkRemotes.luau",
                roblox_service=RobloxService.REPLICATED_STORAGE,
                description="Shared RemoteEvent/RemoteFunction definitions, game constants, and strict Luau type contracts.",
                depends_on=[],
            ),
            RobloxModuleSpec(
                module_id="mod_player_data",
                name="PlayerDataManager",
                kind=ModuleKind.DATA_STORE,
                file_path="src/server/PlayerDataManager.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                description="Server-authoritative player data persistence with session locking, exponential backoff, and BindToClose completion waiting.",
                depends_on=["mod_network_bridge"],
            ),
        ]

        discovered_assets: list[RobloxAssetSpec] = [
            RobloxAssetSpec.from_dict(asset) for asset in research["asset_candidates"]
        ]

        # Add Genre-Specific Subsystems
        if features["is_shop"]:
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_shop_service",
                    name="ShopService",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/ShopService.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Server-authoritative economy and shop transaction system: validates player coins, grants items, and updates inventory.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_shop_controller",
                    name="ShopController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/ShopController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Client shop interface handler: connects ProximityPrompts and shop GUI buy buttons with sound and TweenService animations.",
                    depends_on=["mod_network_bridge", "mod_shop_service"],
                )
            )



        if features["is_obby"]:
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_obby_service",
                    name="ObbyService",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/ObbyService.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Server-authoritative parkour manager: stage checkpoint tracking in workspace.Checkpoints and kill brick collision handling.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_obby_controller",
                    name="ObbyController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/ObbyController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Client stage progress HUD, victory sound playback, and respawn effect controller.",
                    depends_on=["mod_network_bridge", "mod_obby_service"],
                )
            )



        if features["is_tycoon"]:
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_tycoon_service",
                    name="TycoonService",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/TycoonService.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Server tycoon core: physics ore drop timer, conveyor velocity regulation, collector cash payouts, and buy pad unlocks.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_tycoon_controller",
                    name="TycoonController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/TycoonController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Client tycoon feedback: cash collection floaters and button proximity highlights.",
                    depends_on=["mod_network_bridge", "mod_tycoon_service"],
                )
            )



        if features["is_simulator"]:
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_simulator_service",
                    name="SimulatorService",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/SimulatorService.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Server click accumulator, backpack capacity enforcement, and sell zone coin exchange in workspace.SellZones.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_simulator_controller",
                    name="SimulatorController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/SimulatorController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Client click listener, swing animations, and backpack capacity progress bar.",
                    depends_on=["mod_network_bridge", "mod_simulator_service"],
                )
            )



        # Only request-proven combat gets a combat system.
        if features["is_combat"]:
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_combat_core",
                    name="CombatSystem",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/CombatSystem.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Server-authoritative combat: distance sanity checks, damage calculation, cooldown tracking, and knockout rewards.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_combat_controller",
                    name="CombatController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/CombatController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Client mouse/touch input listener, attack visual effects, and weapon swing animations.",
                    depends_on=["mod_network_bridge", "mod_combat_core"],
                )
            )



        if features["is_coin_collect"]:
            modules.append(
                RobloxModuleSpec(
                    module_id="mod_coin_collector",
                    name="CoinCollector",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/CoinCollector.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Physical collectible coins grant server-authoritative Coins with debounce and respawn.",
                    depends_on=["mod_player_data"],
                )
            )

        # Add HUDController
        modules.append(
            RobloxModuleSpec(
                module_id="mod_hud_controller",
                name="HUDController",
                kind=ModuleKind.CLIENT_SCRIPT,
                file_path="src/client/HUDController.client.luau",
                roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                description="Responsive client UI controller for health bars, coins counter, and notifications.",
                depends_on=["mod_network_bridge"],
            )
        )

        # 3. Creator Store Asset Deduplication
        unique_assets: list[RobloxAssetSpec] = []
        seen_ids: set[str] = set()
        for a in discovered_assets:
            if a.asset_id not in seen_ids:
                seen_ids.add(a.asset_id)
                unique_assets.append(a)

        # Evidence handoff is module-specific: a shop module sees shop docs,
        # rather than an unrelated generic RAG summary.
        module_facet = {
            "ShopService":"shop", "ShopController":"shop",
            "CoinCollector":"coins", "CombatSystem":"combat",
            "CombatController":"combat", "ObbyService":"obby",
            "ObbyController":"obby", "TycoonService":"tycoon",
            "TycoonController":"tycoon", "SimulatorService":"simulator",
            "SimulatorController":"simulator", "MagicAbilities":"magic",
            "PlayerDataManager":"persistence", "HUDController":"interface",
        }
        for module in modules:
            facet = module_facet.get(module.name)
            module.evidence_refs = list(dict.fromkeys(
                item["url"] for item in research["evidence"]
                if item.get("provider") == "official_docs" and
                   item.get("facet") == facet and item.get("url")
            ))

        # An unsupported request is never mapped to an unrelated template by
        # keyword similarity. Invoke the local architect only if it is configured.
        dynamic_design = None
        needs_novel = bool(research["ledger"].get("unimplemented_facets") or
                           research["ledger"].get("unmatched_requirements") or
                           not any(features.values()))
        if needs_novel and dynamic_design_enabled():
            try:
                # A fixed shop/sword/obby template cannot implement bespoke
                # mechanics (pet shop, procedural RPG, etc.). Do not transplant
                # these even when one keyword also matches.
                infrastructure = {"NetworkRemotes", "PlayerDataManager"}
                existing = [m for m in modules if m.name in infrastructure]
                dynamic_design = RobloxDynamicArchitect(self.router).design(
                    prompt, research, existing
                )
                modules = existing
                features = {key: False for key in features}
                for row in dynamic_design["modules"]:
                    row.evidence_refs = list(dict.fromkeys(
                        e["url"] for e in research.get("evidence", [])
                        if e.get("provider") == "official_docs" and e.get("url")
                    ))[:5]
                modules.extend(dynamic_design["modules"])
                # Design must cover every authored requirement. This is NOT
                # an assertion that its Luau will work in the engine.
                research["ledger"]["unimplemented_facets"] = [
                    f for f in research["ledger"].get("unimplemented_facets", [])
                    if f == "requested_count_exceeds_safe_build_limit"
                ]
                research["ledger"]["unmatched_requirements"] = []
            except DynamicDesignError as exc:
                research.setdefault("provider_failures", []).append({
                    "provider": "local_small_model",
                    "facet": "dynamic_game_design",
                    "reason": str(exc),
                })

        # 4. Generate Test Specs tailored to the generated modules
        primary_genre = "Combat"
        for g_name, active in [("Obby", features["is_obby"]), ("Shop", features["is_shop"]), ("Tycoon", features["is_tycoon"]), ("Simulator", features["is_simulator"]), ("Combat", features["is_combat"])]:
            if active:
                primary_genre = g_name
                break

        proto_proposal = RobloxProposal(
            requested_prompt=prompt,
            game_title=game_title,
            description=f"Generated Roblox {primary_genre} experience based on prompt: '{prompt}'",
            game_design={
                "genre": primary_genre,
                "features": features,
                "storage": "ProfileStore" if storage_backend == "profilestore" else "DataStoreService with session-locking & exponential backoff pcall",
                "storage_backend": storage_backend,
                "project_mode": project_mode,
                "requested_counts": counts,
                "ui_backend": ui_backend,
                "networking": "RemoteEvents/RemoteFunctions with server authority & reach checks",
                "pre_design_research": research,
                "dynamic_design": ({
                    "schema": "rmm/dynamic-design-v1",
                    "module_requirements": dynamic_design["module_requirements"],
                    "module_behaviors": dynamic_design["module_behaviors"],
                    "module_facets": dynamic_design["module_facets"],
                    "acceptance_facets": dynamic_design["acceptance_facets"],
                    "remotes": dynamic_design["remotes"],
                    "world_objects": dynamic_design["world_objects"],
                    "acceptance": dynamic_design["acceptance"],
                    "design_verified": False,
                    "source_reuse": "none_unless_validated",
                } if dynamic_design else None),
            },
            modules=modules,
            assets=unique_assets,
        )

        test_specs: list[RobloxTestSpec] = self.test_runner.generate_default_test_specs(proto_proposal)
        proto_proposal.tests = test_specs
        proto_proposal.target = RobloxTarget()

        # 5. Render Authored Plan Text
        text = self._render_plan_markdown(proto_proposal)

        authored_plan = RobloxAuthoredPlan(
            requested_prompt=prompt,
            text=text,
            proposal=proto_proposal,
            structured_sections={
                "game_title": game_title,
                "genre": primary_genre,
                "modules": [m.to_dict() for m in modules],
                "assets": [a.to_dict() for a in unique_assets],
                "tests": [t.to_dict() for t in test_specs],
                "request_ledger": research["ledger"],
                "research_queries": research["queries"],
                "research_status": research["status"],
                "dynamic_design": "model_proposed_unverified" if dynamic_design else "none",
            },
        )
        authored_plan.create_checkpoint(note=f"Initial {primary_genre} plan generation")
        return authored_plan

    def revise(self, plan: RobloxAuthoredPlan, feedback: str) -> RobloxAuthoredPlan:
        """Revise an existing authored plan based on feedback, adding requested systems."""
        proposal = plan.proposal
        proposal.requested_prompt += f" | Revision: {feedback}"

        # Same original request + revision is the search authority for every revision.
        research = self.researcher.research(proposal.requested_prompt)
        proposal.game_design["pre_design_research"] = research
        plan.structured_sections["request_ledger"] = research["ledger"]
        plan.structured_sections["research_queries"] = research["queries"]
        plan.structured_sections["research_status"] = research["status"]
        rev_features = self.detect_genres_and_features(feedback)
        current_features = proposal.game_design.get("features", {})
        for key, is_requested in rev_features.items():
            if is_requested:
                current_features[key] = True

        # Dynamically append requested subsystems without duplicating
        if rev_features["is_shop"] and not any(m.name == "ShopService" for m in proposal.modules):
            proposal.modules.append(
                RobloxModuleSpec(
                    module_id="mod_shop_service",
                    name="ShopService",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/ShopService.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Server-authoritative economy and shop transaction system.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )
            proposal.modules.append(
                RobloxModuleSpec(
                    module_id="mod_shop_controller",
                    name="ShopController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/ShopController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Client shop interface handler.",
                    depends_on=["mod_network_bridge", "mod_shop_service"],
                )
            )
            for a in self.creator_store.search("Shop NPC", limit=1):
                if not any(x.asset_id == a.asset_id for x in proposal.assets):
                    proposal.assets.append(a)

        if rev_features["is_magic"] and not any(m.name == "MagicAbilities" for m in proposal.modules):
            proposal.modules.append(
                RobloxModuleSpec(
                    module_id="mod_magic_system",
                    name="MagicAbilities",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/MagicAbilities.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Cooldown-managed magic spells and projectile raycasting.",
                    depends_on=["mod_network_bridge", "mod_player_data"],
                )
            )

        # Re-bind module evidence after every revision; old citations may refer
        # to a different request or document state.
        for module in proposal.modules:
            topic = ("shop" if "Shop" in module.name else
                     "magic" if "Magic" in module.name else
                     "combat" if "Combat" in module.name else
                     "coins" if "Coin" in module.name else None)
            if topic:
                module.evidence_refs = list(dict.fromkeys(
                    item["url"] for item in research["evidence"]
                    if item.get("provider") == "official_docs"
                    and item.get("facet") == topic and item.get("url")
                ))
        # Update test specs
        proposal.tests = self.test_runner.generate_default_test_specs(proposal)

        # Update plan text and checkpoint
        plan.revision_count += 1
        plan.text = self._render_plan_markdown(proposal)
        plan.create_checkpoint(note=f"Revision {plan.revision_count}: {feedback}")
        return plan

    def _render_plan_markdown(self, proposal: RobloxProposal) -> str:
        genre = proposal.game_design.get("genre", "Action")
        modules_md = "\n".join(
            f"- **`{m.name}`** (`{m.file_path}`):\n  - Service: `{m.roblox_service}`\n  - Role: {m.description}\n  - Depends on: `{m.depends_on}`"
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

        pre = proposal.game_design.get("pre_design_research", {})
        ledger = pre.get("ledger", {})
        original = ledger.get("original_prompt", proposal.requested_prompt)
        required_lines = "\n".join(
            f"- [{item['id']}] {item['statement']}"
            for item in ledger.get("requirements", [])
        ) or "- No requirement details recorded"
        evidence_lines = "\n".join(
            f"- [{item['facet']}] {item['url']} (sha256: {item['content_sha256'][:16]})"
            for item in pre.get("evidence", [])
            if item.get("provider") == "official_docs" and item.get("url")
        ) or "- No official document content fetched; not evidence-grounded"
        pending = ", ".join(ledger.get("unimplemented_facets", [])) or "none"
        return f"""# 🎮 Roblox Experience Plan: {proposal.game_title} (Genre: {genre})

> **Prompt**: {proposal.requested_prompt}
> **Target**: Roblox Studio (Luau {proposal.target.luau_version}, Rojo {proposal.target.rojo_version})
> **Project mode**: {proposal.game_design.get("project_mode", "new_experience")}

## 0. Request-first RAG (before game design)
- Research status: {pre.get("status", "not_run")} (NOT gameplay verified)
- Original user request: {original}
- Unimplemented requested facets: {pending}
### Original requirement ledger
{required_lines}
### Fetched Roblox Creator documentation
{evidence_lines}

## 1. Architectural Subsystems (Topological Order)
{modules_md}

## 2. Creator Store Assets (Verified & Sanitized)
{assets_md}

## 3. Playtest & TestEZ Specifications
{tests_md}

## 4. Production Strategy
- **Client/Server Division**: Strict server authority over transactions, health, and physics to eliminate client injection.
- **Data Persistence**: Safe DataStoreService with session-locking, exponential backoff, and BindToClose completion waiting.
- **Sync & Deployment**: Full Rojo `default.project.json` live-sync and `.rbxlx` direct Studio launcher.
"""
