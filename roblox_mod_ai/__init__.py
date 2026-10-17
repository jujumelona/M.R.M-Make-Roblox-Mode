"""R.M.M: Roblox Mod & Experience AI.

Scalable Luau code and Roblox Studio experience production tools using local GGUF models,
Creator Store asset discovery, Rojo sync, TestEZ playtesting, and native .rbxlx generation.
"""

from .api import (
    CompleteChatReply,
    CompleteModAISession,
    CompleteRobloxAISession,
    CompleteSession,
)
from .authored_plan import RobloxAuthoredPlan
from .code_generator import LuauCodeGenerator
from .creator_store import RobloxCreatorStoreCatalog
from .luau_analyzer import LuauAnalysisReport, LuauDiagnostic, LuauStaticAnalyzer
from .model_adapters import LlamaCppAdapter, OpenAICompatibleAdapter
from .model_router import ModelRouter
from .open_cloud import RobloxOpenCloudClient
from .orchestrator import RobloxPipelineResult, RobloxProductionOrchestrator
from .planner import RobloxGameDesignPlanner
from .playtest_runner import PlaytestReport, RobloxPlaytestRunner
from .project_generator import RobloxProjectGenerator
from .roblox_toolchain import RobloxToolchainManager, ToolchainStatus
from .spec import (
    ModuleKind,
    RobloxAssetSpec,
    RobloxModuleSpec,
    RobloxProposal,
    RobloxService,
    RobloxTarget,
    RobloxTestSpec,
)

__version__ = "0.1.0"

__all__ = [
    "CompleteChatReply",
    "CompleteModAISession",
    "CompleteRobloxAISession",
    "CompleteSession",
    "RobloxAuthoredPlan",
    "LuauCodeGenerator",
    "RobloxCreatorStoreCatalog",
    "LuauAnalysisReport",
    "LuauDiagnostic",
    "LuauStaticAnalyzer",
    "LlamaCppAdapter",
    "OpenAICompatibleAdapter",
    "ModelRouter",
    "RobloxOpenCloudClient",
    "RobloxPipelineResult",
    "RobloxProductionOrchestrator",
    "RobloxGameDesignPlanner",
    "PlaytestReport",
    "RobloxPlaytestRunner",
    "RobloxProjectGenerator",
    "ModuleKind",
    "RobloxAssetSpec",
    "RobloxModuleSpec",
    "RobloxProposal",
    "RobloxService",
    "RobloxTarget",
    "RobloxTestSpec",
    "__version__",
]
