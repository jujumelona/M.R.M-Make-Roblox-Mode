"""Actual failure pattern: clients repeatedly produced malformed entire Luau files.

The platform/Remote/GUI shell must be deterministic. This regression asks a
fake small model for ONLY short controls and asserts final source can be parsed.
"""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_client_codegen import try_scaffolded_client
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class SmallUIModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, prompt, **options):
        self.calls.append((prompt, options))
        return next(self.replies)


_BODY = """local button = Instance.new("TextButton")
button.Name = "Purchase"
button.Text = "Purchase part"
button.Size = UDim2.fromOffset(210, 37)
button.Parent = panel
button.Activated:Connect(function()
    request("hull")
end)
"""


def plan_single_action():
    owner = RobloxModuleSpec(
        module_id="dyn_customserver01", name="CustomShipPurchaseServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/CustomShipPurchaseServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Server validates a hull purchase and server-owned inventory.",
    )
    client = RobloxModuleSpec(
        module_id="dyn_customclient01", name="CustomShipPurchaseClient",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/CustomShipPurchaseClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="GUI button that requests a server-authorized hull part purchase.",
    )
    remote = "BuyShipComponent"
    return RobloxProposal(
        requested_prompt="Build a ship by purchasing real hull parts using earned money",
        game_title="HostClientShell", description="Controlled UI rendering",
        game_design={"dynamic_design": {
            "host_actions": {
                remote: {"service": owner.name, "kind": "RemoteFunction"}
            },
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {
                owner.module_id: [remote], client.module_id: [remote],
            },
            "world_objects": [],
        }},
        modules=[owner, client],
    )


def test_custom_client_never_requires_a_full_model_luau_file():
    proposal = plan_single_action()
    ui_model = SmallUIModel([_BODY])
    client = proposal.modules[1]
    code = LuauCodeGenerator(ui_model).generate_module_code(client, proposal)
    assert len(ui_model.calls) == 1
    assert ui_model.calls[0][1]["max_tokens"] <= 900
    assert "Only" in ui_model.calls[0][0] or "ONLY" in ui_model.calls[0][0]
    assert 'game:GetService("Players")' in code
    assert 'WaitForChild("BuyShipComponent")' in code
    assert 'local function request(actionId)' in code
    assert 'remote:InvokeServer(actionId)' in code
    assert 'request("hull")' in code
    assert "request(\"coins\")" not in code
    assert "require(mod_network_bridge)" not in code
    assert not generated_module_errors(client, proposal, code, LuauStaticAnalyzer())


def test_server_authority_in_client_body_cannot_be_adopted_as_host_scaffold():
    proposal = plan_single_action()
    client = proposal.modules[1]
    dangerous = (
        _BODY.replace('request("hull")',
                      'game:GetService("DataStoreService"):GetAsync("wallet")\n    request("hull")')
    )
    model = SmallUIModel([dangerous, dangerous])
    code = try_scaffolded_client(client, proposal, model, LuauStaticAnalyzer())
    assert code is None
    assert len(model.calls) == 2
    assert len(model.last_client_scaffold_attempts) == 2


def test_unowned_remote_or_incorrect_transport_does_not_generate_gui():
    proposal = plan_single_action()
    client = proposal.modules[1]
    model = SmallUIModel([_BODY])
    actions = proposal.game_design["dynamic_design"]["host_actions"]
    actions["BuyShipComponent"]["kind"] = "RemoteEvent"
    assert try_scaffolded_client(client, proposal, model, LuauStaticAnalyzer()) is None
    assert not model.calls
    actions["BuyShipComponent"]["kind"] = "RemoteFunction"
    proposal.game_design["dynamic_design"]["module_remotes"][client.module_id] = []
    assert try_scaffolded_client(client, proposal, model, LuauStaticAnalyzer()) is None
    assert not model.calls
