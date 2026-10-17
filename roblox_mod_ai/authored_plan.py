"""Authored plan and checkpoint management for Roblox Mod & Experience AI."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .spec import RobloxProposal


@dataclass
class RobloxAuthoredPlan:
    """Player-approved or authored game design plan for Roblox."""

    requested_prompt: str
    text: str
    proposal: RobloxProposal
    schema_version: str = "rmm/authored-plan-v1"
    structured_sections: dict[str, Any] = field(default_factory=dict)
    revision_count: int = 0
    checkpoints: list[dict[str, Any]] = field(default_factory=list)

    def calculate_hash(self) -> str:
        payload = json.dumps(
            {
                "schema_version": self.schema_version,
                "requested_prompt": self.requested_prompt,
                "proposal_hash": self.proposal.calculate_hash(),
                "revision_count": self.revision_count,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def create_checkpoint(self, note: str = "") -> dict[str, Any]:
        checkpoint = {
            "checkpoint_id": hashlib.sha256(
                f"{self.revision_count}:{self.requested_prompt}".encode("utf-8")
            ).hexdigest()[:12],
            "revision": self.revision_count,
            "note": note,
            "hash": self.calculate_hash(),
            "module_count": len(self.proposal.modules),
            "asset_count": len(self.proposal.assets),
            "test_count": len(self.proposal.tests),
        }
        self.checkpoints.append(checkpoint)
        return checkpoint

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requested_prompt": self.requested_prompt,
            "text": self.text,
            "proposal": self.proposal.to_dict(),
            "structured_sections": deepcopy(self.structured_sections),
            "revision_count": self.revision_count,
            "checkpoints": deepcopy(self.checkpoints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobloxAuthoredPlan:
        schema = data.get("schema_version")
        if schema != "rmm/authored-plan-v1":
            raise ValueError(f"Unsupported plan schema version: {schema}")
        proposal_data = data.get("proposal", {})
        proposal = RobloxProposal.from_dict(proposal_data)
        return cls(
            requested_prompt=data.get("requested_prompt", ""),
            text=data.get("text", ""),
            proposal=proposal,
            schema_version=schema,
            structured_sections=data.get("structured_sections", {}),
            revision_count=data.get("revision_count", 0),
            checkpoints=data.get("checkpoints", []),
        )
