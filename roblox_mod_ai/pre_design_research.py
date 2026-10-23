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
import ast
from pathlib import Path
from typing import Any
from .model_router import ModelRouter
from .request_semantics import request_semantic_errors

from .creator_store import RobloxCreatorStoreCatalog
from .official_docs import RobloxOfficialDocs
from .roblox_api_catalog import RobloxAPICatalog

def _fresh_generator_method_source(name: str) -> str | None:
    """Read a method from the current on-disk AST, never notebook linecache.

    inspect.getsource(method) can report an unrelated line when Colab has
    imported an older module and Git sync shifted function line numbers.
    Invalid/missing source is not evidence and must not get a source hash.
    """
    source_path = Path(__file__).resolve().with_name("code_generator.py")
    try:
        content = source_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(source_path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "LuauCodeGenerator":
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name:
                    if child.end_lineno is None:
                        return None
                    lines = content.splitlines(keepends=True)
                    extracted = "".join(lines[child.lineno - 1:child.end_lineno])
                    if "def " + name + "(" not in extracted:
                        return None
                    return extracted
    return None


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

# Host-owned API lookup for known mechanics. A large natural-language query
# ranks generic words like "validation" / "inventory" above relevant classes.
# Preserve the user's full query in the audit; use exact relevant class names
# to select documentation, without inventing signatures or live observations.
_FOCUSED_DOC_QUERY = {
    "coins": "BasePart Touched",
    "shop": "ProximityPrompt Triggered",
    "combat": "Humanoid TakeDamage",
    "leaderboard": "DataStoreService GetOrderedDataStore",
    "obby": "SpawnLocation checkpoint Touched",
    "tycoon": "BasePart AssemblyLinearVelocity",
    "simulator": "RemoteEvent OnServerEvent",
    "magic": "Workspace Raycast",
}
# Direct official API member references for well-known host-owned mechanics.
# Generic indexed search is a fallback, not allowed to replace an exact failed
# call with a loosely related tutorial or avatar modeling page.
_EXACT_DOC_MEMBERS = {
    "coins": ("https://create.roblox.com/docs/reference/engine/classes/BasePart.md",
              "BasePart.Touched"),
    "combat": ("https://create.roblox.com/docs/reference/engine/classes/Humanoid.md",
               "TakeDamage"),
    "shop": ("https://create.roblox.com/docs/reference/engine/classes/ProximityPrompt.md",
             "ProximityPrompt.Triggered"),
    "leaderboard": ("https://create.roblox.com/docs/reference/engine/classes/DataStoreService.md",
                    "GetOrderedDataStore"),
}

# Reject unrelated reference pages even if the lexical search returned them.
# Dynamic/user-authored facets remain unfiltered since their API identity is
# not known a priori.
_REQUIRED_DOC_TERMS = {
    "coins": ("basepart", "touched"),
    "shop": ("proximityprompt",),
    "combat": ("humanoid", "takedamage"),
    "leaderboard": ("leaderstats", "ordereddatastore", "datastoreservice"),
    "obby": ("spawnlocation", "basepart", "touched"),
    "tycoon": ("basepart", "assemblylinearvelocity"),
    "simulator": ("remoteevent", "onserverevent"),
    "magic": ("raycast",),
}


def _documentation_relevant(facet: str, url: str, excerpt: str) -> bool:
    """Official origin is necessary but not sufficient to claim task grounding."""
    terms = _REQUIRED_DOC_TERMS.get(facet)
    if not terms:
        return True
    # Search snippets can include generic "Humanoid" on art/rigging pages;
    # these are not evidence for CombatSystem's TakeDamage API.
    url_text = str(url).casefold()
    body = str(excerpt).casefold()
    if facet == "combat":
        return ("takedamage" in body
                and ("/reference/engine/classes/humanoid" in url_text
                     or "humanoid:takedamage" in body
                     or "humanoid.takedamage" in body))
    if facet == "coins":
        return ("/reference/engine/classes/basepart" in url_text
                and ("basepart.touched" in body or "event: basepart.touched" in body))
    if facet == "shop":
        return ("/reference/engine/classes/proximityprompt" in url_text
                and ("triggered" in body or "proximityprompt" in body))
    # For other known facets, a concrete class/member signal in an official
    # Creator page is still required. Unknown novel mechanics remain unfiltered.
    searchable = (url_text + " " + body)
    return any(term in searchable for term in terms)



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
                 router: ModelRouter | None = None,
                 classification_cache: Path | None = None) -> None:
        self.classification_cache = Path(classification_cache) if classification_cache else None
        self.docs = docs if docs is not None else RobloxOfficialDocs()
        self.router = router
        self.creator_store = creator_store if creator_store is not None else RobloxCreatorStoreCatalog()
        self.live_enabled = (os.environ.get("RMM_PREDESIGN_LIVE_SEARCH", "1") == "1"
                             if live_enabled is None else live_enabled)
        self.api = RobloxAPICatalog()
        self.model_query_error: str | None = None
        self.decomposition_error: str | None = None

    def _decompose_compound(self, prompt: str, ledger: dict[str, Any]) -> dict[str, Any]:
        """Audit whole-clause LLM extraction, then recover with host-owned chunks.

        The old 3x whole-prompt retry returned semantic_decomposition_required
        whenever a small model missed one long clause. The recovery path sends
        only short exact original spans, and requires a distinct model description
        for EVERY span; one response cannot certify the rest of the game.
        """
        from .request_contract import validate_model_behaviors, clean, ledger_complete
        from .source_decomposition import (
            source_chunks, valid_chunk_classification, classification_context,
            recover_unseparated_actions,
        )

        # Once the model has validated an entire source decomposition, keep
        # THAT exact source-to-facet graph across later architecture failures.
        # Otherwise the same prompt alternates between 9 and 15+ unrelated
        # module contracts, invalidating scoped architecture checkpoints.
        checkpoint = (self.classification_cache.with_name(
            "semantic_decomposition_checkpoint.json")
            if self.classification_cache is not None else None)
        source_dir = Path(__file__).resolve().parent
        source_policy = [
            "pre_design_research.py", "request_contract.py",
            "source_decomposition.py", "request_semantics.py",
            "semantic_preservation.py",
        ]
        input_sha = hashlib.sha256(json.dumps({
            "original_prompt": prompt,
            "source_requirements": ledger.get("requirements"),
            "policy": {
                name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
                for name in source_policy
            },
        }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

        def complete_verified(candidate: Any) -> bool:
            if not isinstance(candidate, dict):
                return False
            if candidate.get("classification_unverified"):
                return False
            structural = dict(candidate, unimplemented_facets=[],
                              unmatched_requirements=[])
            return ledger_complete(prompt, structural)

        def persist_verified(candidate: dict[str, Any]) -> None:
            if checkpoint is None or not complete_verified(candidate):
                return
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temp = checkpoint.with_suffix(".json.tmp")
            temp.write_text(json.dumps({
                "schema": "rmm/verified-decomposition-v1",
                "input_sha256": input_sha, "ledger": candidate,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(checkpoint)

        if checkpoint is not None and checkpoint.is_file():
            try:
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                if (saved.get("schema") == "rmm/verified-decomposition-v1"
                        and saved.get("input_sha256") == input_sha
                        and complete_verified(saved.get("ledger"))):
                    return saved["ledger"]
            except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
                pass

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

        # Fast path: keep existing well-formed whole-clause behavior extraction.
        whole_error = ""
        try:
            raw = self.router.complete_json(
                "Decompose EACH compound Roblox game request clause into distinct "
                "atomic gameplay behaviors. Return JSON object "
                "{behaviors:[{clause_id,source_span,intent,english_query}]}. "
                "source_span MUST be an exact, SHORT, contiguous quote from its clause; "
                "cover at least 80 percent of each compound clause with multiple "
                "distinct spans. Include only the requested mechanics. "
                "Do NOT combine different actions into a single behavior. "
                "A setting or theme prefix ending in '인데 / and this is a ... game' "
                "belongs to subsequent gameplay and must NOT be emitted as "
                "a standalone toggle, unlock, key press or mode activation. "
                "Each query must describe the actual mechanic and applicable Roblox APIs. "
                "Use original_prompt to resolve fragments; ordinary game buying/trading "
                "uses earned game currency, never unsolicited Robux monetization. "
                "Do not turn unspecified trade into peer-to-peer item transfers. "
                "Maximum 24 behaviors per clause.\\n"
                + json.dumps({"original_prompt": prompt, "clauses": [
                    item for item in ledger["requirements"] if item["id"] in pending
                ]}, ensure_ascii=False),
                role="planner", temperature=0.1,
            )
            rows = raw.get("behaviors", []) if isinstance(raw, dict) else []
            semantic_errors = request_semantic_errors(rows, prompt)
            if semantic_errors:
                raise ValueError("; ".join(semantic_errors))
            if not isinstance(rows, list) or len(rows) > 48:
                raise ValueError("Invalid response length")
            new_requirements: list[dict[str, str]] = []
            intents: list[dict[str, str]] = []
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
                    new_requirements.append({
                        "id": rid, "statement": span, "source": "user_prompt"
                    })
                    if clause["id"] in pending:
                        fid = "intent-" + hashlib.sha256(
                            (rid + span).encode("utf-8")).hexdigest()[:10]
                        intents.append({
                            "facet_id": fid, "requirement_id": rid,
                            "source_span": span, "intent": clean(part["intent"]),
                            "english_query": clean(part["english_query"]),
                        })
            result = _ledger_with_requirements(prompt, new_requirements, atomic_intents=intents)
            structural = dict(result, unimplemented_facets=[], unmatched_requirements=[])
            if not ledger_complete(prompt, structural):
                raise ValueError("Atomic spans do not cover full original request")
            persist_verified(result)
            return result
        except Exception as exc:
            whole_error = type(exc).__name__ + ": " + str(exc)[:200]
            print("[RMM research] Whole-request decomposition incomplete; "
                  "recovering by individually source-anchored chunks: " + whole_error,
                  flush=True)

        try:
            chunks: list[dict[str, str]] = []
            host_bound_actions: dict[str, dict[str, str]] = {}
            for clause in ledger["requirements"]:
                if clause["id"] not in pending:
                    continue
                spans = source_chunks(clause["statement"])
                if len(spans) < 2:
                    # A word-count boundary is not proof of an independent
                    # game mechanic. Let the local model select two or three
                    # different ORIGINAL source IDs and verify coverage first.
                    # If it cannot do so, retain failure rather than mint
                    # two fake requirements from a character midpoint.
                    recovered = recover_unseparated_actions(
                        self.router, clause["statement"])
                    for row in recovered:
                        chunk_id = f"chunk-{len(chunks)+1:03d}"
                        chunks.append({
                            "chunk_id": chunk_id,
                            "clause_id": clause["id"],
                            "source_span": row["source_span"],
                        })
                        host_bound_actions[chunk_id] = {
                            "intent": row["intent"],
                            "english_query": row["english_query"],
                        }
                    continue
                for span in spans:
                    chunks.append({
                        "chunk_id": f"chunk-{len(chunks)+1:03d}",
                        "clause_id": clause["id"],
                        "source_span": span,
                    })
            if len(chunks) > 80:
                raise ValueError("Too many source chunks to audit in a single plan")
            classified: dict[str, dict[str, str]] = dict(host_bound_actions)
            # An architecture cannot safely resume if earlier small-model
            # classification calls are all repeated on every failed run.
            # Cache ONLY validator-accepted exact source spans, bound to the
            # complete request and current decomposition+semantic code.
            chunk_checkpoint = self.classification_cache
            cache_key = hashlib.sha256(json.dumps({
                "prompt": prompt,
                "chunks": chunks,
                "decomposer_sha": hashlib.sha256(
                    (Path(__file__).parent / "source_decomposition.py").read_bytes()
                ).hexdigest(),
                "semantic_sha": hashlib.sha256(
                    (Path(__file__).parent / "semantic_preservation.py").read_bytes()
                ).hexdigest(),
                "request_policy_sha": hashlib.sha256(
                    (Path(__file__).parent / "request_semantics.py").read_bytes()
                ).hexdigest(),
            }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            if chunk_checkpoint is not None:
                try:
                    saved = json.loads(chunk_checkpoint.read_text(encoding="utf-8"))
                    if (saved.get("schema") == "rmm/semantic-chunk-cache-v1"
                            and saved.get("input_sha256") == cache_key):
                        rows = saved.get("behaviors")
                        if isinstance(rows, list):
                            # Cached JSON is never authoritative: apply the
                            # same current semantic policy as fresh model
                            # output, per exact source chunk. This avoids
                            # reusing a previously hallucinated P2P trade or
                            # monetization claim after the policy changes.
                            safe_rows = [
                                row for row in rows
                                if not request_semantic_errors(row, prompt)
                            ]
                            classified.update(valid_chunk_classification(
                                {"behaviors": safe_rows}, chunks))
                except (OSError, ValueError, TypeError, AttributeError):
                    pass

            def persist_verified_chunks() -> None:
                if chunk_checkpoint is None:
                    return
                chunk_checkpoint.parent.mkdir(parents=True, exist_ok=True)
                rows = [{"chunk_id": cid, **row}
                        for cid, row in classified.items()
                        if not row["intent"].startswith(
                            "Implement only the requested gameplay in: ")]
                temp = chunk_checkpoint.with_suffix(chunk_checkpoint.suffix + ".tmp")
                temp.write_text(json.dumps({
                    "schema": "rmm/semantic-chunk-cache-v1",
                    "input_sha256": cache_key, "behaviors": rows,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(chunk_checkpoint)

            unclassified_source_chunks: list[str] = []
            # One-to-one classification in bounded groups; only missing source
            # chunks are retried, not all previously verified capabilities.
            for offset in range(0, len(chunks), 3):
                group = chunks[offset:offset+3]
                missing = [c for c in group if c["chunk_id"] not in classified]
                for retry in range(2):
                    if not missing:
                        break
                    try:
                        output = self.router.complete_json(
                            "Describe EACH provided user-authored Roblox gameplay chunk. "
                            "Return ONLY JSON {behaviors:[{chunk_id,intent,english_query}]}. "
                            "One entry per chunk_id; NEVER merge, skip, add or rename IDs. "
                            "Use the provided previous/next/source_clause as contextual "
                            "evidence for incomplete fragments; describe the role of each "
                            "source_span in its clause, not an invented standalone action. "
                            "A thematic setting is NOT a player-triggered mode change "
                            "unless the user explicitly asks for a toggle/unlock action. "
                            "If a source_span includes two independently requested "
                            "actions without punctuation, retain BOTH in the intent; "
                            "the later planner can create separate server actions. "
                            "Unspecified trading is not player-to-player trading. "
                            "Do not describe UI feedback as a substitute for the requested "
                            "server-side gameplay. Limit intent to 90 characters and query "
                            "to 90 characters; output only the requested IDs.\\n"
                            + json.dumps({"chunks": classification_context(
                                              chunks, missing, ledger["requirements"]),
                                          "scope": "classify_only_provided_chunks"}, ensure_ascii=False),
                            role="planner", temperature=0.0, max_tokens=750,
                        )
                        semantic_errors = request_semantic_errors(output, prompt)
                        if semantic_errors:
                            raise ValueError("; ".join(semantic_errors))
                        classified.update(valid_chunk_classification(output, missing))
                    except Exception as exc:
                        print("[RMM research] Chunk classification retry " +
                              str(retry+1) + ": " + type(exc).__name__, flush=True)
                    missing = [c for c in missing if c["chunk_id"] not in classified]
                # Small models may still omit one entry when decoding six chunks
                # in a batch. Reask only those missing, one source span per call.
                for chunk in missing:
                    for retry in range(3):
                        try:
                            output = self.router.complete_json(
                                "Return JSON {behaviors:[{chunk_id,intent,english_query}]}. "
                                "Describe this ONE user-authored source_span in its "
                                "original clause, using previous/next context for "
                                "incomplete fragments. Name ALL separately requested "
                                "actions in the span, without inventing new ones. "
                                "Return concise concrete gameplay "
                                "intent and API query (max 90 characters each). Do not "
                                "invent actions or confuse UI text with saved game state. "
                                "Do not invent peer-to-peer exchange without user authorization.\\n" +
                                json.dumps({"chunks": classification_context(
                                    chunks, [chunk], ledger["requirements"]),
                                    "scope": "classify_only_provided_chunks"}, ensure_ascii=False),
                                role="planner", temperature=0.0, max_tokens=360,
                            )
                            semantic_errors = request_semantic_errors(output, prompt)
                            if semantic_errors:
                                raise ValueError("; ".join(semantic_errors))
                            classified.update(valid_chunk_classification(output, [chunk]))
                            if chunk["chunk_id"] in classified:
                                break
                        except Exception as exc:
                            print("[RMM research] Single-chunk retry " +
                                  str(retry+1) + ": " + type(exc).__name__, flush=True)
                missing = [c for c in group if c["chunk_id"] not in classified]
                persist_verified_chunks()
                if missing:
                    # The HOST already established exact, lossless source ownership.
                    # Missing classifier prose is not permission to discard user
                    # requirements or block the architecture model. Keep the raw
                    # original text as the intent, explicitly *unverified*, rather
                    # than hallucinating a gameplay system or pretending it passed
                    # the optional classifier.
                    for chunk in missing:
                        span = clean(chunk["source_span"])
                        classified[chunk["chunk_id"]] = {
                            "intent": "Implement only the requested gameplay in: " + span,
                            "english_query": "Roblox gameplay scripting for " + span,
                        }
                        unclassified_source_chunks.append(chunk["chunk_id"])
            new_requirements = []
            intents = []
            for clause in ledger["requirements"]:
                if clause["id"] in pending:
                    parts = [entry for entry in chunks
                             if entry["clause_id"] == clause["id"]]
                else:
                    parts = [{"source_span": clause["statement"], "chunk_id": ""}]
                for part in parts:
                    rid = f"req-{len(new_requirements)+1:03d}"
                    span = clean(part["source_span"])
                    new_requirements.append({
                        "id": rid, "statement": span, "source": "user_prompt"
                    })
                    if clause["id"] in pending:
                        learned = classified[part["chunk_id"]]
                        fid = "intent-" + hashlib.sha256(
                            (rid + span).encode("utf-8")).hexdigest()[:10]
                        intents.append({
                            "facet_id": fid, "requirement_id": rid,
                            "source_span": span,
                            "intent": learned["intent"],
                            "english_query": learned["english_query"],
                            "chunk_id": part["chunk_id"],
                            "classification_origin": (
                                "host_source_only"
                                if part["chunk_id"] in unclassified_source_chunks
                                else "model_classified"),
                        })
            result = _ledger_with_requirements(prompt, new_requirements,
                                                atomic_intents=intents)
            if unclassified_source_chunks:
                result["decomposition_method"] = "source_anchored_host"
                result["classification_unverified"] = list(unclassified_source_chunks)
                self.decomposition_error = (
                    "Model did not classify " + str(len(unclassified_source_chunks)) +
                    " source chunks; host retained exact user wording for "
                    "later game-specific architecture validation")
            result["decomposition_strategy"] = (
                "source_chunk_host_recovery" if unclassified_source_chunks
                else "source_chunk_model_classification")
            result["decomposition_chunk_count"] = len(chunks)
            structural = dict(result, unimplemented_facets=[], unmatched_requirements=[])
            if not ledger_complete(prompt, structural):
                raise ValueError("Recovered chunks did not cover entire original prompt")
            print("[RMM research] Source-owned " + str(len(chunks)) +
                  " gameplay chunks; model-unclassified: " +
                  str(len(unclassified_source_chunks)), flush=True)
            if not unclassified_source_chunks:
                self.decomposition_error = None
                persist_verified(result)
            return result
        except Exception as exc:
            self.decomposition_error = (
                "Whole-request: " + whole_error + "; chunk recovery: " +
                type(exc).__name__ + ": " + str(exc)[:240]
            )
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
        requested_ids = {r["id"] for r in ledger.get("requirements", [])}
        covered_by_host = {
            rid for facet in ledger.get("facets", [])
            if facet.get("implemented_by_builtin") and facet.get("implementation_key")
            for rid in facet.get("requirements", [])
        }
        # A stock in-game shop does not need an unrelated Marketplace service,
        # and ordinary coins do not imply DataStore2. Never ask the small AI
        # to invent supplementary search facets when all original requested
        # actions already have concrete, host-owned implementation owners.
        semantic = ([] if ledger.get("atomic_intents") or
                    ledger.get("decomposition_pending") or
                    (requested_ids and requested_ids <= covered_by_host
                     and not ledger.get("unimplemented_facets")
                     and not ledger.get("unmatched_requirements")) else
                    self._propose_semantic_searches(prompt, ledger))
        if semantic:
            # Search expansion is evidence retrieval, NOT a user-authored
            # gameplay requirement. The previous promotion to
            # unimplemented_facets forced stock coin/shop/combat requests into
            # extra LLM-authored services (DataStore2 and fictitious marketplace
            # APIs), duplicating the actual currency and purchase writers.
            # Keep the searches and their source IDs for audit/retrieval only.
            ledger["facets"] = ledger["facets"] + semantic
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
        # Atomic intents describe the game action. Long LLM-authored search
        # strings often inject optional services (e.g. DataStoreService into
        # every mechanic), producing the same unrelated docs for each action.
        # Search the requested gameplay intent first, but preserve the full
        # model query in the audit record for later targeted API lookup.
        intent_queries = {
            str(item.get("facet_id")): "Roblox " + str(item.get("intent", "")).strip()
            for item in ledger.get("atomic_intents", [])
            if item.get("facet_id") and len(str(item.get("intent", "")).split()) >= 3
        }
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
            retrieval_query = intent_queries.get(facet["id"], query)
            entry = {"facet": facet["id"], "query": query,
                     "retrieval_query": retrieval_query,
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
                body = _fresh_generator_method_source(name)
                if not body:
                    failures.append({
                        "facet": facet["id"],
                        "provider": "local_project_source",
                        "reason": "Cannot verify on-disk source for " + name,
                    })
                    continue
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
            local_api_hits = self.api.search(retrieval_query, limit=3)
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
                focused_query = _FOCUSED_DOC_QUERY.get(facet["id"], retrieval_query)
                entry["official_lookup_query"] = focused_query
                exact = _EXACT_DOC_MEMBERS.get(facet["id"])
                if exact:
                    result = self.docs.read_exact(*exact)
                    entry["official_lookup_url"] = exact[0]
                    if result.get("error"):
                        entry["exact_api_lookup_error"] = str(result["error"])[:220]
                        result = self.docs.search(focused_query, limit=_DOC_LIMIT,
                                                  with_excerpt=True)
                else:
                    result = self.docs.search(focused_query, limit=_DOC_LIMIT,
                                              with_excerpt=True)
                if result.get("error"):
                    failures.append({"facet": facet["id"], "provider": "official_docs",
                                     "reason": str(result["error"])[:250]})
                count = 0
                for hit in result.get("results", []):
                    url, body = hit.get("url", ""), hit.get("excerpt", "")
                    if not url or not body or not RobloxOfficialDocs.safe_url(url):
                        continue
                    if not _documentation_relevant(facet["id"], url, body):
                        entry["rejected_irrelevant_documents"] = (
                            entry.get("rejected_irrelevant_documents", 0) + 1
                        )
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
                entry["status"] = "evidence_found" if count else "no_fetched_relevant_evidence"
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
