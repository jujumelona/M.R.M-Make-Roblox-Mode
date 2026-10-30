"""Roblox experience planner and feature decomposition engine."""

from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .creator_store import RobloxCreatorStoreCatalog
from .pre_design_research import RobloxPreDesignResearch
from .dynamic_architect import RobloxDynamicArchitect, DynamicDesignError, dynamic_design_enabled
from .gameplay_contract import build_gameplay_contract, arena_round_requested
from .implementation_blueprint import build_implementation_blueprint
from .authority_architecture_repair import carried_codegen_authority
from .detailed_plan import build_detailed_plan, enrich_detailed_plan
from .server_modules import normalize_dynamic_server_modules
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
        output_root: Path | str | None = None,
    ) -> None:
        self.router = router or ModelRouter()
        self.output_root = output_root
        self.creator_store = creator_store or RobloxCreatorStoreCatalog()
        self.test_runner = RobloxPlaytestRunner()
        self.researcher = pre_design_research or RobloxPreDesignResearch(
            creator_store=self.creator_store, router=self.router,
            classification_cache=(
                Path(self.output_root) / "semantic_classification_checkpoint.json"
                if self.output_root is not None else None
            ),
        )

    def detect_genres_and_features(self, prompt: str) -> dict[str, bool]:
        """Classifies the gameplay genres and subsystems requested in prompt."""
        p = prompt.lower()
        return {
            "is_shop": any(w in p for w in ["shop", "store", "buy", "merchant", "상점", "구매", "상점가", "아이템샵"]),
            "is_obby": any(w in p for w in ["obby", "parkour", "jump", "checkpoint", "점프맵", "파쿠르", "스테이지", "용암"]),
            "is_tycoon": any(w in p for w in ["tycoon", "dropper", "conveyor", "타이쿤", "드롭퍼", "컨베이어", "공장"]),
            # Inventories/bags and ordinary mining are mechanics, NOT proof
            # that the user requested a click-simulator prefab.
            "is_simulator": any(w in p for w in ["simulator", "시뮬레이터", "clicker", "클릭 시뮬레이터"]),
            "is_magic": any(w in p for w in ["magic", "spell", "staff", "ability", "마법", "스킬", "지팡이"]),
            # Buying/upgrading a weapon is not itself a combat action.
            "is_combat": any(w in p for w in ["combat", "arena", "battle", "fight", "attack", "pvp", "pve", "검투", "아레나", "전투", "배틀", "싸움", "싸우", "공격"]),
            # Gathering any resources must not invent a coin-pickup system.
            "is_coin_collect": any(w in p for w in ["coin", "coins", "코인", "동전"]),
            "is_leaderboard": any(w in p for w in ["leaderboard", "leaderstats", "리더보드", "순위"]),
        }

    def plan(self, prompt: str, *, project_mode: str = "new_experience",
             compile_architecture: bool = False) -> RobloxAuthoredPlan:
        """Capture user intent as a durable draft before implementation.

        Planning MUST NOT fail because a small LLM cannot certify individual
        Luau-level effects or server payment semantics. Only the explicitly
        requested implementation pass compiles an executable architecture;
        code generation and engine verification retain their strict gates.
        """
        validate_mode(project_mode)
        # The legacy full-architecture protocol explicitly requests a
        # compiled model design during PLAN, including direct planner calls.
        # Default modern planning remains an intent-only draft.
        if (os.environ.get("RMM_LEGACY_ARCHITECTURE_PROTOCOL", "0") == "1"
                and os.environ.get("RMM_ENABLE_DYNAMIC_DESIGN", "auto") == "1"):
            compile_architecture = True
        # MMM request-first contract: retrieve before selecting mechanics/modules.
        research = self.researcher.research(prompt)
        # An unclassified source chunk with a complete immutable source span
        # needs an owner check before a plan can claim model-derived scope.
        # This preflight is bounded to chunks that have already finished
        # decomposition, and does not turn ordinary intent drafts into
        # compulsory full implementation planning.
        if (not compile_architecture
                and research.get("ledger", {}).get("classification_unverified")
                and not research.get("ledger", {}).get("decomposition_pending")
                and dynamic_design_enabled()):
            compile_architecture = True
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
        # With a local model available, do NOT guess that a keyword such as
        # "combat" proves the entire game is a matching combat prefab. Ask for
        # the complete architecture and implement it as new gameplay by default.
        # An available LLM is a capability, not evidence that existing tested
        # templates should be replaced. Keep exact stock gameplay when the
        # audited request ledger has no unsupported requirement.
        explicit_dynamic_required = os.environ.get("RMM_ENABLE_DYNAMIC_DESIGN", "auto").lower() == "1"
        # Explicit model-only mode is a build obligation. Even when all keywords
        # happen to match stock templates, never accept them if model design was
        # requested but not completed (or cannot run).
        if explicit_dynamic_required:
            research["ledger"]["unimplemented_facets"] = sorted(set(
                research["ledger"].get("unimplemented_facets", []) +
                ["dynamic_architecture_required"]
            ))
        needs_novel = bool(explicit_dynamic_required or
                           research["ledger"].get("unimplemented_facets") or
                           research["ledger"].get("unmatched_requirements") or
                           research["ledger"].get("decomposition_pending") or
                           not any(features.values()))
        # Failure to translate one source chunk into optional English classifier
        # prose must not deadlock the entire planner. The architect already
        # receives the original immutable source requirements and independently
        # validates server-side state transitions and their observable results.
        # Attempt that bounded recovery; certify exact owners and acceptance
        # for EVERY missing chunk before lifting any blocking status.
        missing_semantics = research["ledger"].get("classification_unverified") or []
        # The interactive plan phase captures ALL original requirements,
        # source spans and research, but never runs expensive high-assurance
        # implementation authoring. Doing both here made a malformed single
        # field abort the entire plan before any Luau was generated.
        if (compile_architecture and needs_novel and dynamic_design_enabled()
                and not research["ledger"].get("decomposition_pending")):
            try:
                # A fixed shop/sword/obby template cannot implement bespoke
                # mechanics (pet shop, procedural RPG, etc.). Do not transplant
                # these even when one keyword also matches.
                infrastructure = {"NetworkRemotes", "PlayerDataManager"}
                existing = [m for m in modules if m.name in infrastructure]
                dynamic_design = RobloxDynamicArchitect(
                    self.router, checkpoint_dir=self.output_root
                ).design(
                    prompt, research, existing
                )
                # Failure 33: the architectural source validator originally
                # approved two transport-only actions requiring nonexistent
                # persistent owner/catalog state. Instead of marking the game
                # "planned" and making production fail immediately, return the
                # exact missing producer evidence to the SCOPED architect.
                # Accept only a new architecture that also clears the same
                # independently computed production authority gate.
                from .authority_architecture_repair import (
                    replan_unproven_authority, AuthorityArchitectureExhausted,
                )
                try:
                    dynamic_design = replan_unproven_authority(
                        dynamic_design,
                        existing_modules=existing,
                        requested_prompt=prompt,
                        research=research,
                        # Never defer an unproven state producer to a BODY
                        # generator. A transport-only Remote cannot prove
                        # gameplay ownership, catalog, world actor or effect.
                        # This requires a SOURCE-OWNED architecture replan
                        # before spending tokens on unrelated Lua modules.
                        allow_codegen_deferral=False,
                        redesign=lambda: RobloxDynamicArchitect(
                            self.router, checkpoint_dir=self.output_root
                        ).design(prompt, research, existing),
                    )
                except AuthorityArchitectureExhausted as exc:
                    raise DynamicDesignError(str(exc)) from exc
                modules = existing
                features = {key: False for key in features}
                for row in dynamic_design["modules"]:
                    # Bind evidence ONLY to this module's owned capabilities.
                    # An unrelated document is not evidence for its gameplay.
                    owned_facets = set(dynamic_design["module_facets"].get(
                        row.module_id, []
                    ))
                    row.evidence_refs = list(dict.fromkeys(
                        e["url"] for e in research.get("evidence", [])
                        if e.get("provider") == "official_docs"
                        and e.get("facet") in owned_facets and e.get("url")
                    ))[:5]
                modules.extend(dynamic_design["modules"])
                if missing_semantics:
                    from .source_architecture_recovery import (
                        certify_unclassified_chunks, SourceArchitectureRecoveryError,
                    )
                    try:
                        certified_chunks = certify_unclassified_chunks(
                            research["ledger"], dynamic_design, modules)
                    except SourceArchitectureRecoveryError as exc:
                        raise DynamicDesignError(
                            "SOURCE_ARCHITECTURE_RECOVERY_FAILED: " + str(exc)
                        ) from exc
                    # A missing classifier is now replaced with independently
                    # validated original-source architecture ownership, NOT a
                    # fabricated model classification or a runtime PASS.
                    research["ledger"]["classification_unverified"] = []
                    research["ledger"]["architecture_recovered_chunks"] = certified_chunks
                    for atom in research["ledger"].get("atomic_intents", []):
                        if atom.get("chunk_id") in certified_chunks:
                            atom["classification_origin"] = "architecture_source_verified"
                # Known host-owned server primitives must be requireable by
                # later gameplay Scripts, not auto-running standalone Scripts.
                from .economy_core import normalize_economy_ledger
                temp = RobloxProposal(requested_prompt=prompt, game_title=game_title,
                                      description="", game_design={"dynamic_design": dynamic_design},
                                      modules=modules)
                normalize_economy_ledger(temp)
                # Design must cover every authored requirement. This is NOT
                # an assertion that its Luau will work in the engine.
                research["ledger"]["unimplemented_facets"] = [
                    f for f in research["ledger"].get("unimplemented_facets", [])
                    if f == "requested_count_exceeds_safe_build_limit"
                ]
                research["ledger"]["unmatched_requirements"] = []
            except DynamicDesignError as exc:
                # A failed source-recovery certification must not leave behind
                # a model-authored module graph or a truthy dynamic_design.
                # Retain only diagnostics/infrastructure, never unverified
                # gameplay services that can suppress incomplete-plan blocking.
                dynamic_design = None
                # Model-enabled design failures cannot silently return a stock
                # shop, sword or arena and claim the user's custom game was made.
                research["ledger"]["unimplemented_facets"] = sorted(set(
                    research["ledger"].get("unimplemented_facets", []) +
                    ["dynamic_architecture_failed"]
                ))
                research.setdefault("provider_failures", []).append({
                    "provider": "local_small_model",
                    "facet": "dynamic_game_design",
                    "reason": str(exc),
                })

        # Never serialize an incomplete custom request as a runnable prefab game.
        # Keep shared infrastructure for diagnostics but discard stock shop/combat
        # implementations that only happened to match incidental keywords.
        if (dynamic_design is None and (
                research["ledger"].get("decomposition_pending") or
                research["ledger"].get("unimplemented_facets") or
                research["ledger"].get("unmatched_requirements"))):
            modules = [m for m in modules if m.name in
                       {"NetworkRemotes", "PlayerDataManager"}]
            features = {key: False for key in features}

        # Only explicitly round-based *new* arena experiences get a finite
        # match loop. Do not impose PvP endings on tycoons, sandboxes or addons.
        if arena_round_requested(prompt, features, dynamic=bool(dynamic_design),
                                 addon=project_mode == "existing_experience_addon"):
            modules.extend([
                RobloxModuleSpec(
                    module_id="mod_arena_round",
                    name="ArenaRoundService",
                    kind=ModuleKind.SERVER_SCRIPT,
                    file_path="src/server/ArenaRoundService.server.luau",
                    roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                    description="Host-owned waiting, countdown, match, win/draw/timeout, payout and replay lifecycle.",
                    depends_on=["mod_network_bridge", "mod_player_data", "mod_combat_core"],
                ),
                RobloxModuleSpec(
                    module_id="mod_arena_round_controller",
                    name="RoundController",
                    kind=ModuleKind.CLIENT_SCRIPT,
                    file_path="src/client/RoundController.client.luau",
                    roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                    description="Visible waiting/round/result UI; never decides winners client-side.",
                    depends_on=["mod_network_bridge", "mod_arena_round"],
                ),
            ])

        # New games always explain their concrete authored objective to players.
        # Existing Experience addons must not install unrelated global UI.
        if project_mode == "new_experience":
            modules.append(RobloxModuleSpec(
                module_id="mod_game_objective",
                name="GameObjectiveController",
                kind=ModuleKind.CLIENT_SCRIPT,
                file_path="src/client/GameObjectiveController.client.luau",
                roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                description="Player-visible task briefing and first action with a toggle.",
                depends_on=[],
            ))

        # 4. Generate Test Specs tailored to the generated modules
        unresolved = bool(research["ledger"].get("decomposition_pending") or
                          research["ledger"].get("unimplemented_facets") or
                          research["ledger"].get("unmatched_requirements"))
        primary_genre = "Custom" if dynamic_design or unresolved or not any(features.values()) else "Combat"
        if not (dynamic_design or unresolved):
            # Genre is the primary game loop, not the first incidental system.
            for g_name, active in [("Combat", features["is_combat"]), ("Obby", features["is_obby"]), ("Tycoon", features["is_tycoon"]), ("Simulator", features["is_simulator"]), ("Shop", features["is_shop"])]:
                if active:
                    primary_genre = g_name
                    break

        from .request_semantics import source_action_authorizations
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
                "planning_phase": ("implementation_contract" if compile_architecture
                                   else "intent_draft"),
                "planning_status": ("implementation_pending" if not compile_architecture
                                    and needs_novel else "implementation_compiled"
                                    if dynamic_design is not None else "source_draft"),
                "pre_design_research": research,
                "dynamic_design": ({
                    "schema": "rmm/dynamic-design-v1",
                    "source_action_authorizations": source_action_authorizations(prompt),
                    "module_requirements": dynamic_design["module_requirements"],
                    "module_behaviors": dynamic_design["module_behaviors"],
                    "module_facets": dynamic_design["module_facets"],
                    "module_remotes": dynamic_design.get("module_remotes", {}),
                    "module_world_objects": dynamic_design.get("module_world_objects", {}),
                    "host_actions": dynamic_design.get("host_actions", {}),
                    "host_client_actions": dynamic_design.get("host_client_actions", {}),
                    "host_action_choices": dynamic_design.get("host_action_choices", {}),
                    "host_typed_actions": dynamic_design.get("host_typed_actions", {}),
                    "host_executable_actions": dynamic_design.get("host_executable_actions", {}),
                    # Codegen is the authoritative effect proof for source-owned
                    # transport-only model actions. Preserve the planner's
                    # bounded, explicitly UNVERIFIED obligation list: losing
                    # it here turns an approved deferral into a false hard
                    # architecture error in resolve_dependencies.
                    "deferred_model_authority": carried_codegen_authority(dynamic_design),
                    "host_world_actions": dynamic_design.get("host_world_actions", {}),
                    "host_world_motion": dynamic_design.get("host_world_motion", {}),
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

        # Canonicalize host-owned dynamic services *before* freezing the
        # requirement-to-module blueprint. Execution must never introduce
        # surprise bootstrap modules after the plan was signed.
        normalize_dynamic_server_modules(proto_proposal)
        proto_proposal.game_design["gameplay_contract"] = build_gameplay_contract(proto_proposal)
        proto_proposal.game_design["implementation_blueprint"] = build_implementation_blueprint(proto_proposal)
        proto_proposal.game_design["detailed_implementation_plan"] = enrich_detailed_plan(
            build_detailed_plan(proto_proposal), self.router)
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
                "planning_phase": proto_proposal.game_design["planning_phase"],
                "planning_status": proto_proposal.game_design["planning_status"],
                "gameplay_contract": proto_proposal.game_design["gameplay_contract"],
                "implementation_blueprint": proto_proposal.game_design["implementation_blueprint"],
                "detailed_implementation_plan": proto_proposal.game_design["detailed_implementation_plan"],
            },
        )
        authored_plan.create_checkpoint(note=f"Initial {primary_genre} plan generation")
        return authored_plan

    def revise(self, plan: RobloxAuthoredPlan, feedback: str) -> RobloxAuthoredPlan:
        """Replan the entire combined request, never splice stale game modules.

        A new shop, weapon, UI or world feature changes cross-feature security,
        DataStore and playtest contracts. Incremental keyword appends previously
        left the saved module graph and authored plan out of sync.
        """
        if not feedback or not feedback.strip():
            raise ValueError("Revision feedback must not be empty")
        updated = self.plan(
            plan.proposal.requested_prompt + "\n" + feedback,
            project_mode=plan.proposal.game_design.get("project_mode", "new_experience"),
            # Preserve the caller-selected architectural phase across a
            # revision. Otherwise every verified dynamic subsystem disappears
            # when an implementation contract is revised as an intent draft.
            compile_architecture=(
                plan.proposal.game_design.get("planning_phase")
                == "implementation_contract"
            ),
        )
        revised = updated.proposal
        research = revised.game_design.get("pre_design_research") or {}
        ledger = research.get("ledger") or {}
        unresolved = any(ledger.get(name) for name in (
            "unimplemented_facets", "unmatched_requirements",
            "decomposition_pending", "classification_unverified"))
        # The new model can fail to author a newly requested feature. That
        # failure blocks approval, but must NOT erase valid previously-owned
        # shop/combat/obby modules. Preserve the old trusted host subsystem
        # definitions while recording the new requirement as unresolved.
        # Do NOT bring back old dynamic code when a new architect succeeded,
        # or reuse arbitrary model-authored source from incompatible state.
        # A revision is based on the original request PLUS feedback. A new
        # architecture draft, including a partially authored dynamic draft,
        # must not erase already assigned deterministic services from that
        # retained original scope. The previous branch performed this merge
        # only when dynamic_design was empty; partial model results therefore
        # silently removed ShopService and its client wiring.
        prior = plan.proposal
        missing_owned_host = any(
            not m.module_id.startswith("dyn_")
            and m.module_id != "mod_game_objective"
            and m.name not in {n.name for n in revised.modules}
            for m in prior.modules
        )
        if unresolved or missing_owned_host:
            existing_names = {m.name for m in revised.modules}
            for prior_module in prior.modules:
                if (prior_module.module_id.startswith("dyn_")
                        or prior_module.name in existing_names):
                    continue
                if prior_module.module_id == "mod_game_objective":
                    continue
                # Retain the previous module contract, not an old generated
                # binary/source. Codegen must revalidate against the new plan.
                preserved = RobloxModuleSpec.from_dict(prior_module.to_dict())
                preserved.code = ""
                revised.modules.append(preserved)
                existing_names.add(preserved.name)
            old_features = prior.game_design.get("features") or {}
            features = revised.game_design.get("features") or {}
            revised.game_design["features"] = {
                key: bool(old_features.get(key) or features.get(key))
                for key in set(old_features) | set(features)
            }
            revised.game_design["gameplay_contract"] = build_gameplay_contract(revised)
            revised.game_design["implementation_blueprint"] = build_implementation_blueprint(revised)
            revised.game_design["detailed_implementation_plan"] = build_detailed_plan(revised)
            updated.structured_sections.update({
                "modules": [m.to_dict() for m in revised.modules],
                "gameplay_contract": revised.game_design["gameplay_contract"],
                "implementation_blueprint": revised.game_design["implementation_blueprint"],
                "detailed_implementation_plan": revised.game_design["detailed_implementation_plan"],
            })
            updated.text = self._render_plan_markdown(revised)
        updated.revision_count = plan.revision_count + 1
        updated.checkpoints = list(plan.checkpoints)
        updated.create_checkpoint(note="Full blueprint and requirement replan")
        return updated

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
        contract = proposal.game_design.get("gameplay_contract", {})
        blueprint = proposal.game_design.get("implementation_blueprint") or {}
        detailed = proposal.game_design.get("detailed_implementation_plan") or {}
        model_plan = detailed.get("ai_planning") or {}
        detailed_md = "\n".join(
            f"- **{row['id']}** {row['original_request']}\n"
            f"  - Expected outcome: {row['expected_outcome']}\n"
            f"  - Owner source: {', '.join(row['owner_files']) or 'UNASSIGNED'}\n"
            f"  - Preconditions: {row['preconditions']}\n"
            f"  - Trigger/input: {row['input_or_trigger']}\n"
            f"  - State change: {row['server_state_changes']}\n"
            f"  - Invalid/edge inputs: {row['invalid_or_edge_inputs']}\n"
            f"  - Persistence: {row['persisted_state']}\n"
            f"  - AI implementation steps: {model_plan.get('requirements', {}).get(row['id'], 'NOT RUN')}"
            for row in detailed.get("required_functions", [])
        ) or "- No detailed requirements registered"
        requirement_acceptance_md = "\n".join(
            f"- **{item['id']}** {item['source']} -> {item['acceptance'] or 'BLOCKED: NO ACCEPTANCE'} "
            f"(owners: {', '.join(item['owners']) or 'UNASSIGNED'})"
            for item in blueprint.get("requirements", [])
        ) or "- No source-bound requirement acceptance"
        mechanics_md = "\n".join(
            f"- **{m['id']}**: owners={', '.join(m['owners']) or 'UNASSIGNED'}; "
            f"files={', '.join(m['files']) or 'NONE'}; runtime=NOT RUN\n"
            f"  - Precondition: {m.get('precondition', 'Covered by authored novel contract')}\n"
            f"  - Interaction: {m.get('interaction', m.get('acceptance', 'Novel authored action'))}\n"
            f"  - Observable: {m.get('postcondition', m.get('acceptance', 'No observable outcome'))}\n"
            f"  - Invalid inputs: {m.get('rejection', 'Reject unauthorized input')}\n"
            f"  - Persistence: {m.get('persistence', 'Declared by game contract')}"
            for m in blueprint.get("mechanics", [])
        ) or "- No assigned mechanics"
        integrations_md = "\n".join(
            f"- **{row['id']}** ({', '.join(row['owners'])}): {row['expected']}; "
            f"negative: {row['negative_test']}"
            for row in blueprint.get("integration_contracts", [])
        ) or "- No multi-system edge requested"
        scenarios_md = "\n".join(
            f"- **{case['id']}**: {case['action']} -> {case['expect']} [NOT RUN]"
            for case in blueprint.get("studio_scenarios", [])
        ) or "- No scenarios"
        blocked_md = "\n".join(
            "- " + issue for issue in blueprint.get("blocking_issues", [])
        ) or "- none (design readiness only, not engine verification)"
        is_draft = proposal.game_design.get("planning_phase") == "intent_draft"
        if is_draft:
            # These are implementation WORK ITEMS, not failed planning.
            requirement_acceptance_md = "\n".join(
                f"- **{row['id']}** {row['source']} -> implementation pending "
                "(owner/acceptance assigned during production)"
                for row in blueprint.get("requirements", [])
            )
        phase_label = ("INTENT DRAFT SAVED; implementation NOT STARTED"
                       if is_draft else "IMPLEMENTATION CONTRACT")
        units_md = "\n".join(
            f"- **{unit['id']}**: {unit['action']} → {unit['observable']} "
            f"(owner: `{unit['owner']}`)"
            for unit in contract.get("units", [])
        ) or "- No implemented gameplay action owned yet"
        return f"""# 🎮 Roblox Experience Plan: {proposal.game_title} (Genre: {genre})

> **Prompt**: {proposal.requested_prompt}
> **Target**: Roblox Studio (Luau {proposal.target.luau_version}, Rojo {proposal.target.rojo_version})
> **Project mode**: {proposal.game_design.get("project_mode", "new_experience")}
> **Planning phase**: {phase_label}

## 0. Request-first RAG (before game design)
- Research status: {pre.get("status", "not_run")} (NOT gameplay verified)
- Original user request: {original}
- Unimplemented requested facets: {pending}
### Original requirement ledger
{required_lines}
### Fetched Roblox Creator documentation
{evidence_lines}

## 1. Lifecycle & Completion Contract
- **Loop type**: {contract.get("mode", "not_defined")}
- **Objective**: {contract.get("objective", "not_defined")}
- **Outcome**: {contract.get("completion_kind", "not_defined")}
- **Replay**: {contract.get("reentry", "not_defined")}
- **Exceptions**: {", ".join(contract.get("exceptions", []))}
- **Engine status**: NOT RUN (source-only plan)
### Authored gameplay connections
{units_md}

## 2. Implementation Blueprint (before code generation)
- **Schema**: {blueprint.get("schema", "MISSING")}
- **Ready for code generation**: {blueprint.get("ready_for_codegen", False)} (not Studio verified)
### Requirement-specific observable acceptance
{requirement_acceptance_md}
### Module implementation and responsibility map
{mechanics_md}
### Cross-system contracts and exploit cases
{integrations_md}
### Detailed acceptance and real Studio/MCP test plan
{scenarios_md}
### {"Pending implementation work (not planning failures)" if is_draft else "Blocking design gaps"}
{blocked_md}

## 3. Detailed requirement implementation (before source code)
- Model planning: {model_plan.get("status", "not_run")}
- Colab engine execution: EXCLUDED (source review and offline tests only)
{detailed_md}

## 4. Architectural Subsystems (Topological Order)
{modules_md}

## 5. Creator Store Assets (Verified & Sanitized)
{assets_md}

## 6. Engine-only scenarios (NOT run in Colab)
{tests_md}

## 7. Production Strategy
- **Client/Server Division**: Strict server authority over transactions, health, and physics to eliminate client injection.
- **Data Persistence**: Safe DataStoreService with session-locking, exponential backoff, and BindToClose completion waiting.
- **Sync & Deployment**: Full Rojo `default.project.json` live-sync and `.rbxlx` direct Studio launcher.
"""
