"""Validate exact planner/coder prompt wire format without inventing MiMo samples.

The original failed 6000-token code was re-encoded into JSON and failed
again. A visible truncated source must instead receive a scoped plain-code
repair. Schema calls must cover one source clause at a time.
"""
import json

from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal
from test_space_seven_facets_e2e import _PROMPT, _user_space_ledger, FakeLocalModel


def test_actual_scoped_planner_prompts_not_whole_game(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    class CapturingModel(FakeLocalModel):
        def __init__(self):
            super().__init__()
            self.meta = []
        def complete_json(self, prompt, **kwargs):
            self.meta.append(kwargs)
            return super().complete_json(prompt, **kwargs)

    m = CapturingModel()
    report = {"ledger": _user_space_ledger(), "evidence": []}
    plan = RobloxDynamicArchitect(router=m).design(_PROMPT, report, [])
    assert len(plan["modules"]) == 14
    assert len(m.calls) == 7
    for idx, (prompt, meta) in enumerate(zip(m.calls, m.meta)):
        payload = json.loads(prompt.split("\n")[-1])
        assert payload["feature_id"] in {
            f["id"] for f in report["ledger"]["facets"]}
        assert len(payload["source_requirements"]) == 1
        assert meta["role"] == "planner"
        assert meta["max_tokens"] == 5000
        schema = meta["json_schema"]
        assert schema["type"] == "object"
        assert "uses_remotes" in schema["properties"]["modules"]["items"]["required"]
        assert "remotes" in schema["required"]
        assert "overall_game_context" not in payload
        assert "Luau scripts are to be written separately" not in prompt


def test_long_nonempty_truncation_uses_plain_scoped_repair_not_whole_json(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module = RobloxModuleSpec(
        module_id="dyn_space", name="SpaceModeManager",
        kind="server_script", roblox_service="ServerScriptService",
        file_path="src/server/SpaceModeManager.server.luau",
        description="Server validates spaceship launch phase and player progression.",
    )
    plan = RobloxProposal(
        requested_prompt="Build spaceship and mine ore on planets",
        game_title="Space", description="",
        game_design={"dynamic_design": {"remotes": {}},
                     "pre_design_research": {"ledger": {
                         "requirements": [
                             {"id": "req-001", "statement": "validate spaceship launch"},
                             {"id": "req-002", "statement": "mine ore on planets"},
                         ]
                     }},
                     },
        modules=[module],
    )
    plan.game_design["dynamic_design"]["module_requirements"] = {
        module.module_id: ["req-001"]
    }

    good = ("--!strict\nlocal function validateLaunch(player): boolean\n"
            "    if player == nil then return false end\n"
            "    return player.Parent ~= nil\nend\n"
            "print(validateLaunch)\n")
    # A plausible >75-char visible completion cut mid-function at 6000 tokens.
    truncated = ("--!strict\nlocal function validateLaunch(player): boolean\n"
                 "    local function incomplete()\n"
                 "        if player == nil then return false end\n"
                 "        return player.Parent ~= nil\n")
    class Router:
        def __init__(self):
            self.calls = []
            self.json_calls = 0
            self.last_generation_report = {}
        def complete(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            self.last_generation_report = {
                "finish_reason": "length" if len(self.calls) == 1 else "stop",
                "completion_tokens": 6000 if len(self.calls) == 1 else 86,
            }
            return truncated if len(self.calls) == 1 else good
        def complete_json(self, *args, **kwargs):
            self.json_calls += 1
            raise AssertionError("Never repeat a visibly truncated Luau in JSON")
    model = Router()
    result = RobloxCodeRepairAgent(router=model).repair(
        module, plan, attempts=3,
    )
    assert "validateLaunch" in result
    assert len(model.calls) == 2
    assert model.json_calls == 0
    initial, repair = model.calls[0][0], model.calls[1][0]
    assert "validate spaceship launch" in initial
    assert "mine ore on planets" not in initial
    assert "Relevant remotes for THIS module only" in initial
    assert "Owned user requirement" in repair
    assert "Model ran out of output tokens" in repair
    assert model.calls[0][1]["max_tokens"] == 6000
    assert model.calls[1][1]["max_tokens"] == 6000
    assert "Return JSON" not in repair
