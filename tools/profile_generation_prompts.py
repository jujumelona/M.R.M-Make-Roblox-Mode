"""Capture the ACTUAL per-module codegen prompts without running an LLM.

This is a static prompt-size/ownership profile, not model tokenization nor an
empirical generation benchmark. Source scopes and lengths can be checked in CI
before the user spends time on the local GGUF.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent, LuauGenerationError
from roblox_mod_ai.spec import RobloxProposal


class PromptRecorder:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.last_generation_report = {}
    def complete(self, prompt: str, **kwargs: object) -> str:
        self.prompts.append(prompt)
        raise RuntimeError("CI PROMPT INTERCEPTION: NO MODEL WAS INFERRED")


def capture(proposal: RobloxProposal) -> dict:
    os.environ["RMM_ENABLE_MODEL_GENERATION"] = "1"
    research = proposal.game_design.get("pre_design_research") or {}
    ledger = research.get("ledger") or {}
    requirements = {r["id"]: r.get("statement", "")
                    for r in ledger.get("requirements", [])
                    if isinstance(r, dict) and r.get("id")}
    owned_map = (proposal.game_design.get("dynamic_design") or {}).get(
        "module_requirements", {})
    rows = []
    for module in proposal.modules:
        if not module.module_id.startswith("dyn_"):
            continue
        recorder = PromptRecorder()
        try:
            RobloxCodeRepairAgent(recorder).repair(
                module, proposal, attempts=1)
        except LuauGenerationError:
            pass
        if len(recorder.prompts) != 1:
            raise AssertionError("Expected exactly one captured initial coder prompt")
        prompt = recorder.prompts[0]
        owned = set(owned_map.get(module.module_id, []))
        unrelated = [
            rid for rid, text in requirements.items()
            if rid not in owned and len(text) >= 12 and text in prompt
        ]
        rows.append({
            "module": module.name, "module_id": module.module_id,
            "file": module.file_path, "prompt_chars": len(prompt),
            "prompt_utf8_bytes": len(prompt.encode("utf-8")),
            "unrelated_source_requirements_leaked": unrelated,
            "has_declared_own_requirement": (
                any(text in prompt for rid, text in requirements.items()
                    if rid in owned) if owned else None),
            "has_remote_contract": "Relevant remotes for THIS module only:" in prompt,
            "has_module_file_path": module.file_path in prompt,
        })
    return {
        "schema": "rmm/coder-prompt-profile-v1",
        "model_executed": False, "token_counts_measured": False,
        "source": "production RobloxCodeRepairAgent prompts",
        "module_count": len(rows),
        "maximum_prompt_chars": max((r["prompt_chars"] for r in rows), default=0),
        "minimum_prompt_chars": min((r["prompt_chars"] for r in rows), default=0),
        "average_prompt_chars": (sum(r["prompt_chars"] for r in rows) / len(rows)
                                  if rows else 0),
        "requirements_leak_detected": any(
            bool(r["unrelated_source_requirements_leaked"]) for r in rows),
        "modules": rows,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--proposal", required=True, type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    proposal = RobloxProposal.from_dict(
        json.loads(args.proposal.read_text(encoding="utf-8")))
    profile = capture(proposal)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "module_count": profile["module_count"],
        "maximum_prompt_chars": profile["maximum_prompt_chars"],
        "average_prompt_chars": profile["average_prompt_chars"],
        "requirements_leak_detected": profile["requirements_leak_detected"],
        "model_executed": False,
    }, ensure_ascii=False))
    if profile["requirements_leak_detected"]:
        raise SystemExit("Coder prompt leaked unrelated full source requirement")


if __name__ == "__main__":
    main()
