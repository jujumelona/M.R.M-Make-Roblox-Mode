"""Regression tests for small-model scoped action-body generation."""
from types import SimpleNamespace

from roblox_mod_ai.host_service_codegen import try_scaffolded_server
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService


class FakeRouter:
    def __init__(self, output):
        self.output = output
        self.calls = []
        self.last_generation_report = {"finish_reason": "stop"}

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.output


class NoDiagnosticAnalyzer:
    def analyze_source(self, code, file_path):
        return []


def inputs(*, routed=True):
    name = "ShipPartUpgradeServer"
    module = RobloxModuleSpec(
        module_id="dyn_000123", name=name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ShipPartUpgradeServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Server validates ownership, then spends earned credits and upgrades a ship component.",
        depends_on=[],
    )
    design = {"host_actions": {}, "host_world_actions": {}}
    if routed:
        design["host_actions"]["UpgradeShipAction"] = {
            "service": name, "kind": "RemoteFunction",
        }
    proposal = SimpleNamespace(
        requested_prompt="Earn credits and upgrade the spaceship.",
        game_design={"dynamic_design": design},
    )
    return module, proposal


def test_host_owns_service_abi_while_model_generates_only_action_body():
    model = FakeRouter(
        'local data = services.PlayerDataManager.GetState(player, "ShipPartUpgradeServer")\n'
        'if not data then return false end\n'
        'data.upgradeLevel = (data.upgradeLevel or 0) + 1\n'
        'return true'
    )
    result = try_scaffolded_server(*inputs(), model, NoDiagnosticAnalyzer())
    assert result is not None
    assert result.startswith("--!strict\n")
    assert result.count("function Service.start(") == 1
    assert result.count("function Service.handleAction(") == 1
    assert result.rstrip().endswith("return Service")
    assert "GetState(player" in result
    assert "data.upgradeLevel" in result
    assert "It does NOT prepend actionName" in model.calls[0][0]
    assert len(model.calls) == 1


def test_unrouted_model_service_is_not_given_a_fake_action_handler():
    model = FakeRouter("return true")
    assert try_scaffolded_server(
        *inputs(routed=False), model, NoDiagnosticAnalyzer()) is None
    assert not model.calls


def test_noop_model_response_never_counts_as_gameplay():
    model = FakeRouter("return true")
    assert try_scaffolded_server(*inputs(), model, NoDiagnosticAnalyzer()) is None
    assert len(model.calls) == 2
    assert len(model.last_scaffold_attempts) == 2
    assert all(x["mode"] == "host_scaffolded_action_body"
               for x in model.last_scaffold_attempts)


def test_host_rejects_duplicate_lifecycle_from_model_body():
    model = FakeRouter(
        "function Service.start(services)\n"
        "  Service._services = services\n"
        "end\n"
        "local state = services.PlayerDataManager.GetState(player, 'Ship')"
    )
    assert try_scaffolded_server(*inputs(), model, NoDiagnosticAnalyzer()) is None
    assert "host-owned" in model.last_scaffold_attempts[0]["diagnostics"][0]


def test_scoped_repair_uses_exact_rejected_body_and_diagnostic():
    class CorrectingRouter(FakeRouter):
        def complete(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return ("Service.handleAction(player, services) " * 4)
            assert "LAST REJECTED BODY" in prompt
            assert "Body contains host-owned" in prompt
            assert "Service.handleAction(player, services)" in prompt
            assert "EXACT VALIDATOR ERRORS" in prompt
            return (
                'local profile = services.PlayerDataManager.GetState(player, "ShipPartUpgradeServer")\n'
                'if not profile then return false end\n'
                'profile.shipUpgrade = (profile.shipUpgrade or 0) + 1\n'
                'return true'
            )
    model = CorrectingRouter("unused")
    generated = try_scaffolded_server(*inputs(), model, NoDiagnosticAnalyzer())
    assert generated is not None
    assert len(model.calls) == 2
    assert model.last_scaffold_attempts[0]["mode"] == "host_scaffolded_action_body"
    assert "profile.shipUpgrade" in generated
