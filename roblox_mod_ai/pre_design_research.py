"""Host-owned, request-first Roblox research before architecture selection.

Adapted from MMM's pre-design evidence handoff concept, not its Minecraft-specific
CurseForge search.  User requirements remain authoritative.  Providers cannot invent
features; lookup results cannot masquerade as inspected or compiled source code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import inspect
from typing import Any
from .model_router import ModelRouter

from .creator_store import RobloxCreatorStoreCatalog
from .official_docs import RobloxOfficialDocs
from .roblox_api_catalog import RobloxAPICatalog

# Search vocabulary only. These hints are never compulsory game systems.
# Unknown requirements are kept in the ledger instead of being mapped to combat.
FACETS: tuple[tuple[str, tuple[str, ...], str, str | None], ...] = (
    ("shop", ("상점", "구매", "판매", "거래", "shop", "merchant", "trade", "purchase"),
     "Roblox ProximityPrompt RemoteFunction secure shop inventory purchase", "is_shop"),
    ("coins", ("코인", "동전", "수집", "currency", "collect coins", "coin", "coins"),
     "Roblox BasePart Touched collectible currency server authority", "is_coin_collect"),
    ("combat", ("전투", "검투", "검", "공격", "배틀", "pvp", "combat", "sword", "arena"),
     "Roblox combat RemoteEvent raycasting server validation ContextActionService", "is_combat"),
    ("obby", ("점프맵", "파쿠르", "오비", "장애물", "용암", "obby", "parkour", "checkpoint"),
     "Roblox obby checkpoints SpawnLocation hazard Touched", "is_obby"),
    ("tycoon", ("타이쿤", "드롭퍼", "컨베이어", "공장", "tycoon", "dropper", "conveyor"),
     "Roblox tycoon conveyor assembly physics ownership collection", "is_tycoon"),
    ("simulator", ("시뮬레이터", "채광", "클릭", "simulator", "mining", "clicker"),
     "Roblox simulator RemoteEvent server validated increment marketplace", "is_simulator"),
    ("magic", ("마법", "주문", "스킬", "지팡이", "magic", "spell", "ability", "staff"),
     "Roblox spell casting cooldown raycast RemoteEvent VFX", "is_magic"),
    ("leaderboard", ("순위", "리더보드", "leaderstats", "leaderboard"),
     "Roblox player leaderstats DataStoreService OrderedDataStore", "is_leaderboard"),
    ("persistence", ("저장", "불러오기", "데이터", "save", "datastore", "persist", "profilestore"),
     "Roblox DataStoreService UpdateAsync sessions persistence", None),
    ("interface", ("ui", "gui", "메뉴", "인벤토리", "화면", "hud"),
     "Roblox PlayerGui ScreenGui GuiButton cross platform input", None),
    ("pets", ("펫", "애완동물", "부화", "알뽑기", "pet", "hatching"),
     "Roblox pet follower PathfindingService CollectionService pet inventory", None),
    ("quests", ("퀘스트", "임무", "미션", "quest", "mission"),
     "Roblox quest objective progression server persistence", None),
    ("vehicles", ("자동차", "차량", "비행기", "운전", "vehicle", "car", "driving"),
     "Roblox VehicleSeat vehicle assembly physics constraints", None),
    ("teleport", ("텔레포트", "이동포탈", "다른맵", "teleport", "portal", "places"),
     "Roblox TeleportService TeleportAsync cross place experience", None),
    ("npc", ("npc", "엔피씨", "몬스터", "적 ai", "pathfinding"),
     "Roblox NPC Humanoid PathfindingService AI navigation", None),
    ("world", ("지형", "월드", "건축", "terrain", "world", "building"),
     "Roblox Terrain procedural models workspace streaming", None),
    ("animation", ("애니메이션", "모션", "animation", "emote"),
     "Roblox Animator AnimationTrack Humanoid animation", None),
)

# Art assets are searched only when an authored request actually asks for them.
ASSET_HINTS: tuple[tuple[str, str], ...] = (
    ("npc", "Model"), ("모델", "Model"), ("캐릭터", "Model"),
    ("차량", "Model"), ("vehicle", "Model"), ("건물", "Model"),
    ("사운드", "Audio"), ("효과음", "Audio"), ("음악", "Audio"), ("sound", "Audio"),
)

_DOC_LIMIT = 2
_MAX_FACETS = 10


def _clean(s: str) -> str:
    return " ".join(str(s).split()).strip()


def _wordmatch(needle: str, haystack: str) -> bool:
    if needle.isascii() and needle.isalpha() and len(needle) <= 4:
        return bool(re.search(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", haystack))
    return needle in haystack


def _fragments(prompt: str) -> list[str]:
    from .request_contract import clauses
    return clauses(prompt)


def _ledger_with_requirements(original: str, requirements: list[dict[str, Any]],
                              atomic_intents: list[dict[str, str]] | None = None,
                              decomposition_pending: list[str] | None = None) -> dict[str, Any]:
    from .request_contract import clean
    intents = atomic_intents or []
    pending_clauses = decomposition_pending or []
    facets: list[dict[str, Any]] = []
    for name, aliases, query, implementation_key in FACETS:
        matches = [entry["id"] for entry in requirements
                   if any(_wordmatch(alias, entry["statement"].casefold()) for alias in aliases)]
        if matches:
            facets.append({
                "id": name, "requirements": matches,
                "search_query": query, "implementation_key": implementation_key,
                "implemented_by_builtin": implementation_key is not None,
            })
    # Every model-extracted behavior is a distinct, NOT-yet-implemented gameplay
    # obligation. A 'shop' keyword in the same span cannot certify the behavior.
    for intent in intents:
        facets.append({
            "id": intent["facet_id"],
            "requirements": [intent["requirement_id"]],
            "search_query": "Roblox " + clean(intent["english_query"])[:150],
            "implementation_key": None,
            "implemented_by_builtin": False,
            "source_span": intent["source_span"],
        })
    covered = {rid for facet in facets for rid in facet["requirements"]}
    unmatched = [r["id"] for r in requirements if r["id"] not in covered]
    pending = sorted({f["id"] for f in facets if f["implementation_key"] is None
                      and f["id"] not in {"persistence", "interface"}})
    if pending_clauses:
        pending.append("semantic_decomposition_required")
    return {
        "schema": "rmm/request-ledger-v1",
        "original_prompt": original,
        "requirements": requirements,
        "facets": facets,
        "unmatched_requirements": unmatched,
        "unimplemented_facets": sorted(set(pending)),
        "decomposition_pending": pending_clauses,
        "decomposition_method": "source_anchored_model" if intents else "not_required",
        "atomic_intents": intents,
        "request_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
    }


def build_request_ledger(prompt: str) -> dict[str, Any]:
    from .request_contract import is_composite
    original = str(prompt)
    if not original.strip():
        raise ValueError("Cannot research an empty Roblox request")
    clauses = _fragments(original) or [_clean(original)]
    requirements = [
        {"id": f"req-{index:03d}", "statement": statement, "source": "user_prompt"}
        for index, statement in enumerate(clauses, 1)
    ]
    uncertain = [item["id"] for item in requirements if is_composite(item["statement"])]
    return _ledger_with_requirements(original, requirements,
                                     decomposition_pending=uncertain)


class RobloxPreDesignResearch:
    """Search official documentation, an audited local API index, and optional assets.

    The indexed and network sources are labelled separately. Every external record
    is copied with a URL and content hash. Missing sources remain visible.
    """
    def __init__(self, docs: RobloxOfficialDocs | None = None,
                 creator_store: RobloxCreatorStoreCatalog | None = None,
                 *, live_enabled: bool | None = None,
                 router: ModelRouter | None = None) -> None:
        self.docs = docs if docs is not None else RobloxOfficialDocs()
        self.router = router
        self.creator_store = creator_store if creator_store is not None else RobloxCreatorStoreCatalog()
        self.live_enabled = (os.environ.get("RMM_PREDESIGN_LIVE_SEARCH", "1") == "1"
                             if live_enabled is None else live_enabled)
        self.api = RobloxAPICatalog()
        self.model_query_error: str | None = None
        self.decomposition_error: str | None = None

    def _decompose_compound(self, prompt: str, ledger: dict[str, Any]) -> dict[str, Any]:
        """LLM proposes atoms; host verifies exact source spans and full clause coverage."""
        from .request_contract import validate_model_behaviors, clean
        pending = set(ledger.get("decomposition_pending", []))
        if not pending:
            return ledger
        setting = os.environ.get("RMM_ENABLE_MODEL_DECOMPOSITION", "auto").lower()
        enabled = setting == "1" or (setting == "auto"
                  and bool(os.environ.get("ROBLOX_LLAMA_SERVER_URL")
                           or os.environ.get("RMM_MODEL_BASE_URL")))
        if not enabled or self.router is None:
            self.decomposition_error = "Compound request requires a configured local model"
            return ledger
        for attempt in range(3):
            try:
                raw = self.router.complete_json(
                    "Decompose EACH compound Roblox game request clause into distinct "
                    "atomic gameplay behaviors. Return JSON object "
                    "{behaviors:[{clause_id,source_span,intent,english_query}]}. "
                    "source_span MUST be an exact, SHORT, contiguous quote from its clause; "
                    "cover at least 80 percent of each compound clause with multiple "
                    "distinct spans. Include resource gathering, crafting, travel, "
                    "progression, enemies, and other requested mechanics ONLY when present "
                    "in the original text; never invent gameplay. "
                    "Do NOT combine different mechanics merely because they use a shop. "
                    "A query must describe the specific implementation and Roblox APIs. "
                    "Translate intent into a concrete English verb phrase. "
                    "Maximum 24 behaviors per clause.\n"
                    + json.dumps({"original_prompt": prompt, "clauses": [
                        item for item in ledger["requirements"]
                        if item["id"] in pending]}, ensure_ascii=False)
                    + ("\nPREVIOUS INVALID OUTPUT: " + self.decomposition_error
                       + "\nReturn corrected complete JSON with exact user quote spans."
                       if attempt and self.decomposition_error else ""),
                    role="planner", temperature=0.1
                )
                rows = raw.get("behaviors", []) if isinstance(raw, dict) else []
                if not isinstance(rows, list) or len(rows) > 48:
                    raise ValueError("Invalid model decomposition response size")
                new_requirements: list[dict[str, str]] = []
                atomic_intents: list[dict[str, str]] = []
                for clause in ledger["requirements"]:
                    parts = [x for x in rows if isinstance(x, dict)
                             and x.get("clause_id") == clause["id"]]
                    if clause["id"] in pending:
                        if not validate_model_behaviors(clause["statement"], parts):
                            raise ValueError("Model omitted or merged mechanics in " + clause["id"])
                    else:
                        parts = [{"source_span": clause["statement"], "intent": "",
                                  "english_query": ""}]
                    for part in parts:
                        rid = f"req-{len(new_requirements)+1:03d}"
                        span = clean(part["source_span"])
                        new_requirements.append({"id": rid, "statement": span, "source": "user_prompt"})
                        if clause["id"] in pending:
                            fid = "intent-" + hashlib.sha256((rid + span).encode("utf-8")).hexdigest()[:10]
                            atomic_intents.append({
                                "facet_id": fid, "requirement_id": rid, "source_span": span,
                                "intent": clean(part["intent"]),
                                "english_query": clean(part["english_query"])
                            })
                result = _ledger_with_requirements(prompt, new_requirements,
                                                    atomic_intents=atomic_intents)
                # Independently verify that a valid decomposition of the ENTIRE request
                # survives, not just that the model supplied plausible JSON.
                from .request_contract import ledger_complete
                # Pending novel implementation is legitimate at design time; only this
                # structural check temporarily excludes implementation coverage fields.
                structural = dict(result, unimplemented_facets=[], unmatched_requirements=[])
                if not ledger_complete(prompt, structural):
                    raise ValueError("Atomic source spans did not cover the original prompt")
                return result
            except Exception as exc:
                self.decomposition_error = type(exc).__name__ + ": " + str(exc)[:220]
                if attempt == 2:
                    return ledger

        return ledger
    def _propose_semantic_searches(self, prompt: str, ledger: dict) -> list[dict]:
        """Model proposes queries only, never source evidence or game success."""
        setting = os.environ.get("RMM_ENABLE_MODEL_QUERY_EXPANSION", "auto").lower()
        enabled = setting == "1" or (setting == "auto"
                  and bool(os.environ.get("ROBLOX_LLAMA_SERVER_URL")))
        if not enabled or self.router is None:
            return []
        self.model_query_error = None
        requirements = ledger["requirements"]
        try:
            output = self.router.complete_json(
                "Return JSON object {searches:[{source_span:string, english_query:string}]} "
                "with at most six Roblox API/documentation queries for distinct "
                "features in the user request. source_span must be an exact substring "
                "of the user request. Translate Korean into English API terms. "
                "Do not add gameplay features not present in the request.\n"
                + json.dumps({"original_prompt":prompt,
                              "requirements":requirements},ensure_ascii=False),
                role="planner", temperature=0.1
            )
        except Exception as exc:
            # Optional model/network failures are recorded, not trusted as evidence.
            self.model_query_error = type(exc).__name__ + ": " + str(exc)[:200]
            return []
        proposed=[]
        if not isinstance(output,dict): return []
        for entry in output.get("searches",[])[:6]:
            if not isinstance(entry,dict): continue
            span=_clean(entry.get("source_span",""))
            query=_clean(entry.get("english_query",""))
            if not span or span.casefold() not in prompt.casefold(): continue
            if not query or len(query)>160 or not re.search(r"[a-zA-Z]{3,}",query):
                continue
            if not query.lower().startswith("roblox "): query="Roblox "+query
            matched=[r["id"] for r in requirements
                     if span.casefold() in r["statement"].casefold()]
            if not matched: continue
            facet_id="semantic-"+hashlib.sha256((span+query).encode("utf-8")).hexdigest()[:8]
            proposed.append({"id":facet_id,"requirements":matched,
                             "search_query":query,"implementation_key":None,
                             "implemented_by_builtin":False,
                             "model_query_only":True})
        return proposed

    def research(self, prompt: str) -> dict[str, Any]:
        self.model_query_error = None
        self.decomposition_error = None
        ledger = self._decompose_compound(prompt, build_request_ledger(prompt))
        # A source-anchored atomic decomposition already supplies its own exact,
        # feature-specific searches. Query expansion cannot supersede it.
        semantic = ([] if ledger.get("atomic_intents") else
                    self._propose_semantic_searches(prompt, ledger))
        if semantic:
            ledger["facets"] = ledger["facets"] + semantic
            ledger["unimplemented_facets"] = sorted(set(
                ledger["unimplemented_facets"] + [x["id"] for x in semantic]
            ))
            covered={rid for f in ledger["facets"] for rid in f["requirements"]}
            ledger["unmatched_requirements"] = [r["id"] for r in ledger["requirements"]
                                                  if r["id"] not in covered]
        if not ledger["facets"]:
            # A domain-unknown request still gets a traceable search attempt.
            ledger["facets"]=[{
                "id":"unclassified",
                "requirements":[r["id"] for r in ledger["requirements"]],
                "search_query":"Roblox "+_clean(prompt)[:115],
                "implementation_key":None,
                "implemented_by_builtin":False
            }]
            ledger["unimplemented_facets"]=sorted(set(
                ledger["unimplemented_facets"]+["unclassified"]
            ))
        evidence: list[dict[str, Any]] = []
        queries: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        if self.model_query_error:
            failures.append({"facet":"model_query_expansion", "provider":"local_small_model",
                             "reason":self.model_query_error})
        if self.decomposition_error:
            failures.append({"facet": "semantic_decomposition",
                             "provider": "local_small_model", "reason": self.decomposition_error})
        asset_candidates: list[dict[str, Any]] = []
        reuse_candidates: list[dict[str, str]] = []
        requested={facet["id"] for facet in ledger["facets"]}
        for facet, name, package, upstream in (
            ("persistence","ProfileStore","lm-loleris/profilestore@1.0.3",
             "https://github.com/MadStudioRoblox/ProfileStore"),
            ("interface","Fusion","elttob/fusion@0.3.0",
             "https://github.com/dphfox/Fusion"),
        ):
            if facet in requested:
                reuse_candidates.append({
                    "facet":facet,"name":name,"package":package,"url":upstream,
                    "status":"known_package_candidate_only",
                    "source_inspected":False, "wally_resolution_required":True,
                })
        seen_urls: set[tuple[str, str]] = set()

        # Bound transport work, not the user's actual feature ledger. Newly
        # extracted actions are most informative: a generic shop query must not
        # exhaust the live-docs budget before custom ship/mining/travel actions.
        max_live_queries = 8
        prioritized_facets = sorted(ledger["facets"], key=lambda facet: (
            not bool(facet.get("source_span")),
            facet.get("id", ""),
        ))
        for index, facet in enumerate(prioritized_facets):
            query = facet["search_query"]
            entry = {"facet": facet["id"], "query": query,
                     "providers": ["official_docs", "local_api_index"], "status": "pending",
                     "requirement_ids": facet["requirements"]}
            # Exact first-party generator source can be inspected and reused;
            # it is NOT proof of compatibility, runtime tests or external licensing.
            from .code_generator import LuauCodeGenerator
            method_names = {
                "shop":("_generate_shop_service","_generate_shop_controller"),
                "coins":("_generate_coin_collector",),
                "combat":("_generate_combat_service","_generate_combat_controller"),
                "obby":("_generate_obby_service",),
                "tycoon":("_generate_tycoon_service",),
                "simulator":("_generate_simulator_service",),
            }.get(facet["id"], ())
            local_source_count=0
            for name in method_names[:2]:
                method=getattr(LuauCodeGenerator,name,None)
                if method is None: continue
                try:
                    body=inspect.getsource(method)
                except (OSError,TypeError): continue
                evidence.append({
                    "facet":facet["id"],
                    "provider":"local_project_source",
                    "source_path":"roblox_mod_ai/code_generator.py",
                    "symbol":name,
                    "excerpt":body[:1000],
                    "content_sha256":hashlib.sha256(body[:1000].encode("utf-8")).hexdigest(),
                    "source_sha256":hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "grounding":"inspected_first_party_source_candidate",
                    "query":query,
                })
                local_source_count+=1
            entry["local_source_matches"]=local_source_count
            # Local source inspection is a candidate, not official live evidence.
            local_api_hits = self.api.search(query, limit=3)
            for hit in local_api_hits:
                evidence.append({
                    "facet": facet["id"],
                    "provider": "local_api_index",
                    "url": "https://create.roblox.com/docs/reference/engine/classes/" + hit["class_name"],
                    "excerpt": hit["signature"] + " — " + hit["description"],
                    "content_sha256": hashlib.sha256(
                        (hit["signature"] + " — " + hit["description"]).encode("utf-8")
                    ).hexdigest(),
                    "grounding": "curated_local_reference_not_live_verified",
                    "query": query,
                })
            entry["local_api_matches"] = len(local_api_hits)
            queries.append(entry)
            if not self.live_enabled:
                entry["status"] = "live_disabled"
                continue
            if index >= max_live_queries:
                entry["status"] = "deferred_budget"
                continue
            try:
                result = self.docs.search(query, limit=_DOC_LIMIT, with_excerpt=True)
                if result.get("error"):
                    failures.append({"facet": facet["id"], "provider": "official_docs",
                                     "reason": str(result["error"])[:250]})
                count = 0
                for hit in result.get("results", []):
                    url, body = hit.get("url", ""), hit.get("excerpt", "")
                    if not url or not body or not RobloxOfficialDocs.safe_url(url):
                        continue
                    key = (facet["id"], url)
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    evidence.append({
                        "facet": facet["id"],
                        "provider": "official_docs",
                        "url": url,
                        "excerpt": body[:1500],
                        "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                        "grounding": "fetched_official_document",
                        "query": query,
                    })
                    count += 1
                entry["status"] = "evidence_found" if count else "no_fetched_evidence"
                entry["evidence_count"] = count
            except Exception as exc:
                failures.append({"facet": facet["id"], "provider": "official_docs",
                                 "reason": f"{type(exc).__name__}: {str(exc)[:200]}"})
                entry["status"] = "provider_error"

        # Caller-supplied asset intent is distinct from games' gameplay logic.
        asset_types = {kind for cue, kind in ASSET_HINTS
                       if _wordmatch(cue, prompt.casefold())}
        if self.live_enabled and asset_types:
            # One request-grounded asset query, no generic hardcoded NPC/sound searches.
            keyword = _clean(prompt)[:110]
            for asset_type in sorted(asset_types):
                try:
                    records = self.creator_store.search(keyword, asset_type=asset_type, limit=2)
                    for asset in records:
                        asset_candidates.append({
                            **asset.to_dict(),
                            "usage_permission_verified": False,
                            "content_inspected": False,
                            "status": "metadata_candidate_only",
                            "search_query": keyword,
                        })
                except Exception as exc:
                    failures.append({"facet": "assets", "provider": "creator_store",
                                     "reason": f"{type(exc).__name__}: {str(exc)[:200]}"})
        # Local manually curated signatures are useful hints but NOT proof
        # that current official documentation was actually fetched.
        covered = {item["facet"] for item in evidence
                   if item.get("grounding") == "fetched_official_document"}
        desired = {facet["id"] for facet in ledger["facets"]}
        if not self.live_enabled:
            status = "live_disabled"
        elif desired and covered == desired and not ledger.get("decomposition_pending"):
            status = "grounded"
        elif covered:
            status = "partial"
        else:
            status = "unresolved"
        return {
            "schema": "rmm/pre-design-rag-v1",
            "ledger": ledger,
            "queries": queries,
            "evidence": evidence,
            "asset_candidates": asset_candidates,
            "reuse_candidates": reuse_candidates,
            "provider_failures": failures,
            "status": status,
            "covered_facets": sorted(covered),
            "missing_facets": sorted(desired - covered),
            "source_handoff": "verified_excerpt_only",
            "model_is_evidence_authority": False,
        }
