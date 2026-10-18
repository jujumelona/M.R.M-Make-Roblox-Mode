"""Core data contracts and specifications for R.M.M (Roblox Mod & Experience Maker)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ModuleKind(str, Enum):
    SERVER_SCRIPT = "server_script"
    SERVER_MODULE = "server_module"
    CLIENT_SCRIPT = "client_script"
    SHARED_MODULE = "shared_module"
    REMOTE_BRIDGE = "remote_bridge"
    DATA_STORE = "data_store"
    GUI_CONTROLLER = "gui_controller"
    WORKSPACE_OBJECT = "workspace_object"
    SOUND_SYSTEM = "sound_system"


class RobloxService(str, Enum):
    WORKSPACE = "Workspace"
    LIGHTING = "Lighting"
    REPLICATED_STORAGE = "ReplicatedStorage"
    SERVER_SCRIPT_SERVICE = "ServerScriptService"
    SERVER_STORAGE = "ServerStorage"
    STARTER_GUI = "StarterGui"
    STARTER_PACK = "StarterPack"
    STARTER_PLAYER_SCRIPTS = "StarterPlayer.StarterPlayerScripts"
    STARTER_CHARACTER_SCRIPTS = "StarterPlayer.StarterCharacterScripts"
    SOUND_SERVICE = "SoundService"


@dataclass
class RobloxTarget:
    """Roblox engine target constraints."""

    roblox_version: str = "latest"
    luau_version: str = "0.600+"
    rojo_version: str = "7.4.4"
    strict_typing: bool = True
    server_authoritative: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RobloxAssetSpec:
    """Asset specification discovered from Roblox Creator Store."""

    asset_id: str
    name: str
    asset_type: str = "Model"  # Model, Audio, Decal, MeshPart, Plugin
    creator: str = "Roblox"
    destination_service: str = "Workspace"
    description: str = ""
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobloxAssetSpec:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RobloxModuleSpec:
    """Specification for an executable Luau script or module."""

    module_id: str
    name: str
    kind: str  # server_script, client_script, shared_module, etc.
    file_path: str  # e.g., src/server/GameManager.server.luau
    roblox_service: str  # e.g., ServerScriptService
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobloxModuleSpec:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RobloxTestSpec:
    """Playtest and TestEZ specification."""

    test_id: str
    name: str
    target_module: str
    file_path: str  # tests/Combat.spec.luau
    test_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobloxTestSpec:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RobloxProposal:
    """Complete blueprint and implementation proposal for a Roblox experience."""

    requested_prompt: str
    game_title: str
    description: str
    game_design: dict[str, Any]
    modules: list[RobloxModuleSpec] = field(default_factory=list)
    assets: list[RobloxAssetSpec] = field(default_factory=list)
    tests: list[RobloxTestSpec] = field(default_factory=list)
    target: RobloxTarget = field(default_factory=RobloxTarget)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def calculate_hash(self) -> str:
        payload = json.dumps(
            {
                "prompt": self.requested_prompt,
                "game_title": self.game_title,
                "game_design": self.game_design,
                "modules": [m.to_dict() for m in self.modules],
                "assets": [a.to_dict() for a in self.assets],
                "target": self.target.to_dict(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_prompt": self.requested_prompt,
            "game_title": self.game_title,
            "description": self.description,
            "game_design": self.game_design,
            "modules": [m.to_dict() for m in self.modules],
            "assets": [a.to_dict() for a in self.assets],
            "tests": [t.to_dict() for t in self.tests],
            "target": self.target.to_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RobloxProposal:
        modules = [RobloxModuleSpec.from_dict(m) for m in data.get("modules", [])]
        assets = [RobloxAssetSpec.from_dict(a) for a in data.get("assets", [])]
        tests = [RobloxTestSpec.from_dict(t) for t in data.get("tests", [])]
        target = RobloxTarget(**data.get("target", {}))
        return cls(
            requested_prompt=data.get("requested_prompt", ""),
            game_title=data.get("game_title", "RobloxExperience"),
            description=data.get("description", ""),
            game_design=data.get("game_design", {}),
            modules=modules,
            assets=assets,
            tests=tests,
            target=target,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )
