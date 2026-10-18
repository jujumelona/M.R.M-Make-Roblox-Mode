
"""Bounded retrieval-grounded Luau implementation and repair agent.

Only enabled explicitly for unsupported modules or actual tool diagnostics.
Never executes arbitrary commands from model outputs. Hard failures remain hard.
"""
from __future__ import annotations

import os
import re

from .official_docs import RobloxOfficialDocs
from .code_output_guard import LiveCodeRepetitionGuard, RepeatedCodeOutput
from .model_router import ModelRouter
from .luau_analyzer import LuauStaticAnalyzer
from .spec import RobloxModuleSpec, RobloxProposal

class LuauGenerationError(ValueError):
    """Model generation exhausted; carry the actual source and validator output."""

    def __init__(self, module: str, candidate: str, diagnostics: list[str]):
        self.module = module
        self.candidate = candidate
        self.diagnostics = list(diagnostics)
        super().__init__(
            "Luau generation failed for " + module + ": " +
            "; ".join(self.diagnostics[:12])
        )


class RobloxCodeRepairAgent:
    def __init__(self, router: ModelRouter | None = None,
                 docs: RobloxOfficialDocs | None = None) -> None:
        self.router = router or ModelRouter()
        self.docs = docs or RobloxOfficialDocs()
        self.analyzer = LuauStaticAnalyzer()

    @staticmethod
    def _clean_code(response: str) -> str:
        response = (response or "").strip()
        # Do not transform an EMPTY completion into '--!strict' and treat it
        # as a Luau candidate. This was the exact failed EconomyLedger file.
        if not response:
            return ""
        response = re.sub(r"(?is)^<think>[\s\S]*?</think>\s*", "", response).strip()
        match=re.search(r"```(?:luau|lua)?\s*([\s\S]*?)\s*```",response,re.IGNORECASE)
        if match: response=match.group(1).strip()
        if not response:
            return ""
        if not response.startswith("--!strict"): response="--!strict\n"+response
        return response

    def repair(self, module: RobloxModuleSpec, proposal: RobloxProposal,
               existing_code: str = "", diagnostics: str = "",
               attempts: int = 3) -> str:
        setting = os.environ.get("RMM_ENABLE_MODEL_GENERATION", "auto").lower()
        enabled = setting == "1" or (setting == "auto" and
                                   bool(os.environ.get("ROBLOX_LLAMA_SERVER_URL")
                                        or os.environ.get("RMM_MODEL_BASE_URL")))
        if not enabled:
            raise RuntimeError("Small-model Luau generator disabled; "
                               "configure ROBLOX_LLAMA_SERVER_URL or RMM_ENABLE_MODEL_GENERATION=1")
        if attempts < 1 or attempts > 5:
            raise ValueError("Repair attempts must be 1..5")
        pre = proposal.game_design.get("pre_design_research", {})
        # Reuse actual plan-time source evidence; don't silently replace the user's
        # research scope with another untracked request at code generation time.
        design = proposal.game_design.get("dynamic_design") or {}
        # Do not feed the economy coder random planet/avatar documents:
        # use only official evidence owned by this exact requested facet.
        owned = set(design.get("module_facets", {}).get(module.module_id, []))
        observed = [record for record in pre.get("evidence", [])
                    if record.get("provider") == "official_docs"
                    and record.get("grounding") == "fetched_official_document"
                    and record.get("excerpt") and record.get("url")
                    and (not owned or record.get("facet") in owned)]
        if observed:
            # Rank against the specific implementation, preserving original URL/hash.
            tokens = set(re.findall(r"[a-zA-Z]{4,}",(module.name+" "+module.description).lower()))
            selected = sorted(observed, key=lambda rec: -sum(
                word in (rec.get("excerpt","")+" "+rec.get("url","")).lower()
                for word in tokens
            ))[:2]
            source_urls=[rec["url"] for rec in selected]
            snippets="\n".join(
                f"[UNTRUSTED DOCUMENT {rec['url']} sha256:{rec['content_sha256']}] "
                +rec["excerpt"][:360] for rec in selected
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
        # A previous degenerate generated source is diagnostic evidence,
        # not a useful few-shot example for the model. Never copy hundreds
        # of repeated declarations into its next generation prompt.
        try:
            LiveCodeRepetitionGuard.inspect(existing_code)
        except RepeatedCodeOutput as loop:
            diagnostics += ("\nPrevious source had pathological repeated lines: " +
                            str(loop))
            existing_code = ""
        prompt=(
            "Implement a complete Luau Roblox gameplay module. Output only code.\n"
            "Do not repeat identical assignments or statements in a loop; "
            "create minimal reusable functions for each actual game action.\n"
            "Do not create stubs/TODOs, no unsafe require(assetId), no loadstring.\n"
            "Server must validate all incoming client data and remote actions.\n"
            f"User request: {proposal.requested_prompt}\n"
            f"File: {module.file_path}\nModule: {module.name}\n"
            f"Module intent: {module.description}\n"
            f"Required dependencies: {module.depends_on}\n"
            f"Model architecture: {proposal.game_design.get('dynamic_design', {}).get('module_behaviors', {}).get(module.module_id, '') if isinstance(proposal.game_design.get('dynamic_design'),dict) else ''}\n"
            f"Declared remotes and type: {proposal.game_design.get('dynamic_design', {}).get('remotes', {}) if isinstance(proposal.game_design.get('dynamic_design'),dict) else {}}\n"
            f"Available world objects: {proposal.game_design.get('dynamic_design', {}).get('world_objects', []) if isinstance(proposal.game_design.get('dynamic_design'),dict) else []}\n"
            f"Roblox docs (untrusted evidence, verify APIs): {source_urls}\n{snippets}\n"
            f"Existing source:\n{existing_code[:12000]}\n"
            f"Tool diagnostics:\n{diagnostics[:6500]}"
        )
        candidate = existing_code
        errors: list[str] = []
        degenerate_attempt = False
        for attempt in range(attempts):
            if attempt:
                # The original loop repeatedly appended long source+diagnostics
                # to the same prompt, making each expensive call harder for 9B.
                # Regenerate a compact per-file repair request instead.
                compact = (
                    "Generate ONLY valid Roblox Luau source for ONE file. "
                    "Do not output reasoning, JSON, markdown or placeholders. "
                    "Include functional state and handlers. "
                    "Use only the declared remotes and server-authoritative logic.\n"
                    f"User request: {proposal.requested_prompt[:1000]}\n"
                    f"File: {module.file_path}\n"
                    f"Required behavior: {module.description}\n"
                    f"Remote types: {design.get('remotes', {})}\n"
                    "Previous validator errors: " + "; ".join(errors[:10]) + "\n"
                )
                if candidate and len(candidate) > 75 and not degenerate_attempt:
                    compact += "Previous invalid Luau source:\n" + candidate[:9000] + "\n"
                elif degenerate_attempt:
                    compact += (
                        "Previous output was caught repeating identical assignments. "
                        "DO NOT continue it. Start over with concise functional "
                        "Luau handling only this file's gameplay behavior.\n"
                    )
                else:
                    compact += "Previous attempt produced no functional code. Start directly with --!strict and actual statements.\n"
                query = compact
            else:
                query = prompt
            try:
                # A distinct recovery mode, not another identical code call.
                # JSON mode already produces visible answers with non-thinking
                # templates on the user's MiMo GGUF. Request the actual Luau
                # code in an escaped JSON string if plain completion is empty.
                last_report = getattr(self.router, "last_generation_report", {})
                ran_out_thinking = (
                    isinstance(last_report, dict) and (
                        last_report.get("finish_reason") == "length" or
                        "finish_reason=length" in str(last_report.get("error", ""))
                    )
                )
                json_fallback = (
                    attempt >= 1 and hasattr(self.router, "complete_json") and
                    (degenerate_attempt or
                     (len(candidate.strip()) < 75 and
                      (attempt >= 2 or ran_out_thinking)))
                )
                if json_fallback:
                    model_output = self.router.complete_json(
                        query + "\nReturn JSON with exactly one key 'luau' "
                        "containing the COMPLETE Luau script as a string. "
                        "Start its value with --!strict and include actual "
                        "functional statements; no TODO or explanation.",
                        role="coder", temperature=0.1, max_tokens=6000,
                        system_prompt="Write complete runnable Roblox Luau in the JSON field 'luau'.",
                    )
                    raw_code = (model_output.get("luau", "")
                                if isinstance(model_output, dict) else "")
                else:
                    raw_code = self.router.complete(
                        query, role="coder",
                        system_prompt="You are a Roblox Luau programmer. Return source code only; no reasoning or commentary.",
                        temperature=0.1, max_tokens=6000,
                    )
            except Exception as exc:
                runtime_observation = getattr(self.router, "last_generation_report", {})
                errors = [
                    "Model completion failed: " + type(exc).__name__ + ": " + str(exc),
                    "Model runtime observation: " + str(runtime_observation),
                ]
                if isinstance(exc, RepeatedCodeOutput):
                    degenerate_attempt = True
                    candidate = exc.partial_output
                    errors.insert(0, "Streaming repetition aborted before token budget exhaustion")
                print("[RMM coder] " + module.name + " attempt " +
                      str(attempt + 1) + ": " + errors[0][:600], flush=True)
                continue
            candidate = self._clean_code(raw_code)
            try:
                LiveCodeRepetitionGuard.inspect(candidate)
                degenerate_attempt = False
            except RepeatedCodeOutput as loop:
                degenerate_attempt = True
                errors = ["Generated source is stuck in repeated statements: " + str(loop)]
                print("[RMM coder] " + module.name + " attempt " +
                      str(attempt + 1) + ": " + errors[0][:600], flush=True)
                continue
            errors = [d.message for d in self.analyzer.analyze_source(candidate,module.file_path)
                      if d.severity=="ERROR"]
            if not candidate:
                errors.append("Model returned no visible Luau implementation")
            if not candidate.strip() or len(candidate)<75:
                errors.append("Unimplemented or empty module")
            if re.search(r"\b(?:TODO|FIXME|not implemented|placeholder)\b",candidate,re.IGNORECASE):
                errors.append("Placeholder code is prohibited")
            if re.search(r"\b(?:loadstring|getfenv|setfenv)\s*\(",candidate):
                errors.append("Unsafe dynamic code")
            if re.search(r"\brequire\s*\(\s*\d{5,}\s*\)",candidate):
                errors.append("External numeric asset require is forbidden until source/license inspection")
            if re.search(r"\bInsertService\b|:LoadAsset\s*\(",candidate):
                errors.append("Dynamic third-party asset loading is forbidden")
            if re.search(r"\b(?:HttpService|http)\s*[:.]\s*(?:GetAsync|PostAsync|RequestAsync)\s*\(",candidate):
                errors.append("Unexpected outbound network code in generated gameplay")
            if module.file_path.endswith(".server.luau") and re.search(
                    r"\bLocalPlayer\b|:FireServer\s*\(",candidate):
                errors.append("Server source contains client-only API")
            if module.file_path.endswith(".client.luau") and re.search(
                    r"\bDataStoreService\b|\bOnServerEvent\b|\bOnServerInvoke\b",candidate):
                errors.append("Client source contains server-only API")
            if not errors:
                return candidate
            runtime_info = getattr(self.router, "last_generation_report", None)
            if isinstance(runtime_info, dict) and runtime_info:
                errors.append("Runtime completion: " + str(runtime_info)[:700])
            print("[RMM coder] " + module.name + " attempt " + str(attempt + 1) +
                  " invalid: " + "; ".join(errors[:5])[:700], flush=True)
        raise LuauGenerationError(module.name, candidate, errors)
