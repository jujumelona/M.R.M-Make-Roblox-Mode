
"""Bounded retrieval-grounded Luau implementation and repair agent.

Only enabled explicitly for unsupported modules or actual tool diagnostics.
Never executes arbitrary commands from model outputs. Hard failures remain hard.
"""
from __future__ import annotations

import os
import re

from .official_docs import RobloxOfficialDocs
from .model_router import ModelRouter
from .luau_analyzer import LuauStaticAnalyzer
from .spec import RobloxModuleSpec, RobloxProposal

class RobloxCodeRepairAgent:
    def __init__(self, router: ModelRouter | None = None,
                 docs: RobloxOfficialDocs | None = None) -> None:
        self.router = router or ModelRouter()
        self.docs = docs or RobloxOfficialDocs()
        self.analyzer = LuauStaticAnalyzer()

    @staticmethod
    def _clean_code(response: str) -> str:
        response=response.strip()
        match=re.search(r"```(?:luau|lua)?\s*([\s\S]*?)\s*```",response,re.IGNORECASE)
        if match: response=match.group(1).strip()
        if not response.startswith("--!strict"): response="--!strict\n"+response
        return response

    def repair(self, module: RobloxModuleSpec, proposal: RobloxProposal,
               existing_code: str = "", diagnostics: str = "",
               attempts: int = 3) -> str:
        if os.environ.get("RMM_ENABLE_MODEL_GENERATION") != "1":
            raise RuntimeError("Small-model Luau generator disabled; set RMM_ENABLE_MODEL_GENERATION=1")
        if attempts < 1 or attempts > 5:
            raise ValueError("Repair attempts must be 1..5")
        pre = proposal.game_design.get("pre_design_research", {})
        # Reuse actual plan-time source evidence; don't silently replace the user's
        # research scope with another untracked request at code generation time.
        observed = [record for record in pre.get("evidence", [])
                    if record.get("provider") == "official_docs"
                    and record.get("grounding") == "fetched_official_document"
                    and record.get("excerpt") and record.get("url")]
        if observed:
            # Rank against the specific implementation, preserving original URL/hash.
            tokens = set(re.findall(r"[a-zA-Z]{4,}",(module.name+" "+module.description).lower()))
            selected = sorted(observed, key=lambda rec: -sum(
                word in (rec.get("excerpt","")+" "+rec.get("url","")).lower()
                for word in tokens
            ))[:4]
            source_urls=[rec["url"] for rec in selected]
            snippets="\n".join(
                f"[UNTRUSTED DOCUMENT {rec['url']} sha256:{rec['content_sha256']}] "
                +rec["excerpt"][:580] for rec in selected
            )
        else:
            if pre:
                # Unavailable plan-time source must remain unavailable, not be
                # laundered into a supposedly grounded implementation prompt.
                source_urls=[]
                snippets="No fetched Roblox documentation available in this authored plan."
            else:
                # Backward-compatibility only for plans predating pre-design RAG.
                references=self.docs.search(module.description+" "+module.name,limit=3)
                source_urls=[item["url"] for item in references["results"]]
                snippets="\n".join(item.get("excerpt","")[:450] for item in references["results"])
        prompt=(
            "Implement a complete Luau Roblox gameplay module. Output only code.\n"
            "Do not create stubs/TODOs, no unsafe require(assetId), no loadstring.\n"
            "Server must validate all incoming client data and remote actions.\n"
            f"User request: {proposal.requested_prompt}\n"
            f"File: {module.file_path}\nModule: {module.name}\n"
            f"Module intent: {module.description}\n"
            f"Required dependencies: {module.depends_on}\n"
            f"Roblox docs (untrusted evidence, verify APIs): {source_urls}\n{snippets}\n"
            f"Existing source:\n{existing_code[:12000]}\n"
            f"Tool diagnostics:\n{diagnostics[:6500]}"
        )
        for attempt in range(attempts):
            candidate=self._clean_code(self.router.complete(
                prompt,
                role="coder",
                system_prompt="You are an expert Roblox Luau engine programmer. Return compilable Luau source only.",
                temperature=0.1,max_tokens=6000
            ))
            errors=[d.message for d in self.analyzer.analyze_source(candidate,module.file_path)
                    if d.severity=="ERROR"]
            if not candidate.strip() or len(candidate)<75:
                errors.append("Unimplemented or empty module")
            if re.search(r"\b(?:TODO|FIXME|not implemented|placeholder)\b",candidate,re.IGNORECASE):
                errors.append("Placeholder code is prohibited")
            if re.search(r"\b(?:loadstring|getfenv|setfenv)\s*\(",candidate):
                errors.append("Unsafe dynamic code")
            if not errors:
                return candidate
            prompt+="\nRETRY; previous code failed: "+("; ".join(errors[:8]))
            prompt+="\nPrevious code:\n"+candidate[:12500]
        raise ValueError("Model could not produce a validated implementation for "+module.name)
