"""Reproduce the user's SECOND SpaceModeManager 6000-token failure.

The model repeated whole 100-line declarations rather than adjacent lines,
then stopped with an unclosed Luau code fence. Gameplay scope was also wrong:
one server module received the full 20-remote game-wide contract.
"""
import pytest

from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
from roblox_mod_ai.code_output_guard import LiveCodeRepetitionGuard, RepeatedCodeOutput
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.module_prompt_scope import relevant_remotes
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def _plan():
    bridge = RobloxModuleSpec(
        module_id="mod_network_bridge", name="NetworkRemotes",
        kind="shared_module", roblox_service="ReplicatedStorage",
        file_path="src/shared/NetworkRemotes.luau",
        description="Shared game remote contract",
    )
    space = RobloxModuleSpec(
        module_id="dyn_space", name="SpaceModeManager",
        kind="server_script", roblox_service="ServerScriptService",
        file_path="src/server/SpaceModeManager.server.luau",
        description="Server authoritative space phase machine LaunchPad "
                    "Launching Space Planet Combat Colonization",
    )
    remotes = {
        "SpacePhaseRequest": "RemoteFunction",
        "SpacePhaseState": "RemoteFunction",
        "MiningAction": "RemoteEvent",
        "MiningResult": "RemoteFunction",
        "TradeRequest": "RemoteEvent",
        "TradeResult": "RemoteFunction",
        "CombatAction": "RemoteEvent",
        "CombatResult": "RemoteFunction",
        "ColonizerAction": "RemoteEvent",
        "ColonizerResult": "RemoteFunction",
    }
    plan = RobloxProposal(
        requested_prompt="자원 채굴, 거래, 우주선 제작, 발사, 외계인 전투, 식민지화",
        game_title="SpaceExperience", description="Space gameplay",
        game_design={
            "pre_design_research": {"evidence": []},
            "dynamic_design": {
                "remotes": remotes,
                "module_behaviors": {space.module_id: space.description},
                "module_facets": {space.module_id: ["intent-space"]},
                "world_objects": [],
            },
        }, modules=[bridge, space],
    )
    return plan, bridge, space


def test_second_failure_repeated_entire_module_detected_before_fifth_copy():
    block = (
        "--[[ SpaceModeManager ]]--\n"
        'local PlayersService = game:GetService("Players")\n'
        'local ReplicatedStorageService = game:GetService("ReplicatedStorage")\n'
        'type PhaseName = "LaunchPad" | "Launching" | "Space"\n'
        "local function GetPlayer(playerId: number)\n"
        "    local player = PlayersService:GetPlayerByUserId(playerId)\n"
        "    return player\n"
        "end\n"
        "local function GetPhaseName(playerId: number): string\n"
        '    return "LaunchPad"\n'
        "end\n"
    )
    source = "--!strict\n" + block * 5
    with pytest.raises(RepeatedCodeOutput) as error:
        LiveCodeRepetitionGuard.inspect(source)
    assert len(error.value.partial_output.splitlines()) < 34
    assert "redeclared" in str(error.value) or "repeated code block" in str(error.value)


def test_repeated_function_body_without_redeclaring_module_still_detected():
    block = [
        "    local currentPhase = currentPlayer:GetAttribute('SpacePhase')",
        "    local nextPhase = transitionTable[currentPhase]",
        "    if nextPhase ~= nil and nextPhase ~= 'Planet' then",
        "        currentPlayer:SetAttribute('SpacePhase', nextPhase)",
        "        return nextPhase, true",
        "    end",
    ]
    with pytest.raises(RepeatedCodeOutput, match="repeated code block"):
        LiveCodeRepetitionGuard.inspect("--!strict\n" + "\n".join(block * 4))


def test_space_manager_only_receives_its_own_rpc_family(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    plan, _, module = _plan()
    scoped = relevant_remotes(module, plan.game_design["dynamic_design"])
    assert set(scoped) == {"SpacePhaseRequest", "SpacePhaseState"}
    class Router:
        def __init__(self): self.prompts = []
        def complete(self, prompt, **kwargs):
            self.prompts.append(prompt)
            return ("--!strict\nlocal function getPhase(player: Player): string\n"
                    "    return player:GetAttribute('SpacePhase') or 'LaunchPad'\n"
                    "end\nprint(getPhase)\n")
    fake = Router()
    result = RobloxCodeRepairAgent(router=fake).repair(module, plan)
    assert "getPhase" in result
    assert "SpacePhaseRequest" in fake.prompts[0]
    assert "MiningAction" not in fake.prompts[0]
    assert "TradeRequest" not in fake.prompts[0]
    assert "CombatAction" not in fake.prompts[0]


def test_unclosed_markdown_fence_is_removed_from_luau_source():
    fence = chr(96) * 3
    raw = "--!strict\n" + fence + "luau\nlocal function x() return 5 end\n"
    clean = RobloxCodeRepairAgent._clean_code(raw)
    assert clean.startswith("--!strict\nlocal function x")
    assert fence not in clean


def test_rojo_remote_map_and_shared_bridge_match_custom_game(tmp_path):
    plan, bridge, _ = _plan()
    source = LuauCodeGenerator().generate_module_code(bridge, plan)
    remotes = plan.game_design["dynamic_design"]["remotes"]
    for name in remotes:
        assert name + " = " in source
    assert "StageChanged" not in source
    assert "ClickRequest" not in source
    rojo = RobloxProjectGenerator(tmp_path).generate_rojo_project_json(plan)
    emitted = rojo["tree"]["ReplicatedStorage"]["Remotes"]
    assert {name for name in emitted if not name.startswith("$")} == set(remotes)
    assert "StageChanged" not in emitted


def test_truncated_6000_token_visible_source_pivots_to_fresh_plain_repair(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    plan, _, module = _plan()
    class Model:
        def __init__(self):
            self.plain, self.structured = 0, 0
            self.last_generation_report = {}
        def complete(self, prompt, **kwargs):
            self.plain += 1
            if self.plain == 1:
                self.last_generation_report = {"finish_reason": "length",
                                               "completion_tokens": 6000}
                return "--!strict\nlocal unfinished = function()\n" + "print('more code')\n" * 120
            assert "Previous invalid Luau source" not in prompt
            assert "print('more code')" not in prompt
            self.last_generation_report = {"finish_reason": "stop",
                                           "completion_tokens": 102}
            return ("--!strict\n"
                    "local function getSpaceState(player: Player): string\n"
                    "    return player:GetAttribute('SpacePhase') or 'LaunchPad'\n"
                    "end\nprint(getSpaceState)\n")
        def complete_json(self, prompt, **kwargs):
            self.structured += 1
            raise AssertionError("Never JSON wrap an oversized visible source")
    model = Model()
    result = RobloxCodeRepairAgent(router=model).repair(module, plan, attempts=3)
    assert "getSpaceState" in result
    assert model.plain == 2 and model.structured == 0
