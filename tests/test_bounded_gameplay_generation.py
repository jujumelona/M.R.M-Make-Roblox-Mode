"""Never escalate a failed short gameplay body into long full-file model output.

Reproduces the shared route/ABI issue behind many uploaded model failures.
Fake model answers deliberately emulate repeated invalid Luau, without
claiming local GGUF end-to-end runtime validation.
"""
import pytest

from roblox_mod_ai.agent_loop import LuauGenerationError
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_lifecycle_codegen import try_scaffolded_lifecycle
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.scaffold_policy import (
    single_client_action, single_host_action, single_passive_service,
)
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)
from test_host_scaffolded_client import plan_single_action


class RecordingRouter:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, prompt, **kwargs):
        self.requests.append((prompt, kwargs))
        return next(self.replies)


def passive_plan():
    module = RobloxModuleSpec(
        module_id="dyn_world_setup01",
        name="CustomMeteorEnvironment",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/CustomMeteorEnvironment.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server automatically creates a decorative meteor field and "
            "a passive background atmosphere before players arrive."
        ),
    )
    return RobloxProposal(
        game_title="PassiveWorld", description="World setup",
        requested_prompt="A meteor-themed world for a multiplayer game",
        game_design={"dynamic_design": {
            "host_actions": {}, "host_world_actions": {},
            "world_objects": [], "module_world_objects": {module.module_id: []},
        }},
        modules=[module],
    )


def test_eligible_client_cannot_fall_back_to_6000_token_whole_luau():
    p = plan_single_action()
    mod = p.modules[1]
    router = RecordingRouter(["--!strict\nfunction x:: end"] * 3)
    assert single_client_action(p, mod)
    with pytest.raises(LuauGenerationError, match="SCOPED_CLIENT_UI_EXHAUSTED") as e:
        LuauCodeGenerator(router).generate_module_code(mod, p)
    assert len(router.requests) == 2
    assert all(c["max_tokens"] <= 900 for _, c in router.requests)
    assert len(e.value.history) == 2
    assert all(a["mode"] == "host_scaffolded_client_ui" for a in e.value.history)
    assert "function x" in e.value.candidate


def test_eligible_server_cannot_fall_back_to_full_file_repair():
    p = plan_single_action()
    mod = p.modules[0]
    assert single_host_action(p, mod)
    router = RecordingRouter(["--!strict\nfunction Service.start() end"] * 3)
    with pytest.raises(LuauGenerationError, match="SCOPED_SERVER_ACTION_EXHAUSTED") as e:
        LuauCodeGenerator(router).generate_module_code(mod, p)
    assert len(router.requests) == 2
    assert all(c["max_tokens"] <= 1500 for _, c in router.requests)
    assert len(e.value.history) == 2


def test_unrouted_passive_server_generated_from_statements_in_host_start():
    p = passive_plan()
    mod = p.modules[0]
    assert single_passive_service(p, mod)
    code = """local meteor = Instance.new("Part")
meteor.Name = "MeteorWorldEnvironment"
meteor.Size = Vector3.new(40, 4, 40)
meteor.Anchored = true
meteor.Parent = workspace
"""
    router = RecordingRouter([code])
    output = LuauCodeGenerator(router).generate_module_code(mod, p)
    assert 'function Service.start(services)' in output
    assert "meteor.Parent = workspace" in output
    assert output.rstrip().endswith("return Service")
    assert "function Service.handleAction" not in output
    assert len(router.requests) == 1
    assert router.requests[0][1]["max_tokens"] <= 1200
    assert not [d for d in LuauStaticAnalyzer().analyze_source(output, mod.file_path)
                if d.severity == "ERROR"]


def test_passive_start_failure_is_bounded_and_has_real_rejected_source():
    p = passive_plan()
    router = RecordingRouter(["function Service.start() end"] * 4)
    with pytest.raises(LuauGenerationError, match="SCOPED_PASSIVE_START_EXHAUSTED") as e:
        LuauCodeGenerator(router).generate_module_code(p.modules[0], p)
    assert len(router.requests) == 2
    assert len(e.value.history) == 2
    assert all(c["max_tokens"] <= 1200 for _, c in router.requests)


def test_passive_start_never_claims_an_interactive_player_route():
    p = passive_plan()
    m = p.modules[0]
    p.game_design["dynamic_design"]["host_actions"] = {
        "MeteorActivate": {"service": m.name, "kind": "RemoteFunction"}
    }
    assert single_host_action(p, m)
    assert not single_passive_service(p, m)
    p.game_design["dynamic_design"]["host_actions"].clear()
    m.description = "Players purchase weapon upgrades with earned coins"
    assert not single_passive_service(p, m)
    assert try_scaffolded_lifecycle(m, p, RecordingRouter([]), LuauStaticAnalyzer()) is None


def test_missing_host_route_does_not_mean_passive_pet_or_custom_gameplay():
    p = passive_plan()
    module = p.modules[0]
    module.name = "CustomPetHatching"
    module.description = (
        "A player can hatch a pet egg after paying an earned game currency. "
        "The system creates the pet and sends the client a hatching response."
    )
    assert not single_passive_service(p, module), (
        "Pet hatching with a player interaction must not become a passive "
        "start-only service"
    )


def test_roblox_server_recovers_short_action_via_structured_json_only():
    p = plan_single_action()
    class StructuredRouter:
        def __init__(self):
            self.calls = []
        def complete(self, prompt, **kwargs):
            self.calls.append(("plain", kwargs["max_tokens"]))
            return "function Service.start() : invalid"
        def complete_json(self, prompt, **kwargs):
            self.calls.append(("json_body", kwargs["max_tokens"]))
            assert kwargs["json_schema"]["required"] == ["body"]
            return {"body": """local stats = player:FindFirstChild("leaderstats")
local coins = stats and stats:FindFirstChild("Coins")
if not coins or coins.Value < 6 then return false end
coins.Value -= 6
player:SetAttribute("HullPurchased", true)
return {success = true}
"""}
    router = StructuredRouter()
    code = LuauCodeGenerator(router).generate_module_code(p.modules[0], p)
    assert router.calls == [("plain", 1500), ("plain", 1500), ("json_body", 1200)]
    assert 'coins.Value -= 6' in code
    assert code.rstrip().endswith("return Service")


def test_client_recovers_short_ui_via_json_not_6k_module_code():
    from test_host_scaffolded_client import _BODY
    p = plan_single_action()
    class StructuredRouter:
        def __init__(self):
            self.calls = []
        def complete(self, prompt, **kwargs):
            self.calls.append(("plain", kwargs["max_tokens"]))
            return "function Service.handleAction :: invalid"
        def complete_json(self, prompt, **kwargs):
            self.calls.append(("json_body", kwargs["max_tokens"]))
            return {"body": _BODY}
    router = StructuredRouter()
    code = LuauCodeGenerator(router).generate_module_code(p.modules[1], p)
    assert router.calls == [("plain", 850), ("plain", 850), ("json_body", 750)]
    assert "request(\"hull\")" in code
    assert "remote:InvokeServer(actionId)" in code


def test_passive_world_recovers_short_startup_via_json_only():
    p = passive_plan()
    class StructuredRouter:
        def __init__(self): self.calls = []
        def complete(self, prompt, **kwargs):
            self.calls.append(("plain", kwargs["max_tokens"]))
            return "return Service"
        def complete_json(self, prompt, **kwargs):
            self.calls.append(("json_body", kwargs["max_tokens"]))
            return {"body": """local platform = Instance.new("Part")
platform.Name = "MeteorPlatform"
platform.Anchored = true
platform.Size = Vector3.new(44, 3, 44)
platform.Parent = workspace
"""}
    router = StructuredRouter()
    code = LuauCodeGenerator(router).generate_module_code(p.modules[0], p)
    assert router.calls == [("plain", 1200), ("plain", 1200), ("json_body", 1000)]
    assert 'platform.Parent = workspace' in code
    assert 'function Service.start(services)' in code
