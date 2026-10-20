"""Shared plan-authorized action IDs prevent guessed client/server commands.

When the semantic architect supplies selectable choices, both Remote endpoints
receive the SAME allowed IDs. The client UI is 100% deterministic host Luau.
"""
import pytest
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_architecture import HostArchitectureError, expand_semantic_facet
from roblox_mod_ai.host_service_codegen import _shell
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from test_host_scaffolded_client import plan_single_action


class NoCoder:
    def complete(self, *args, **kwargs):
        raise AssertionError("Approved buttons should never need model-generated Luau")


def test_declared_options_render_buttons_without_model_and_match_server_guard():
    proposal = plan_single_action()
    design = proposal.game_design["dynamic_design"]
    design["host_action_choices"] = {
        "BuyShipComponent": [
            {"id": "hull", "label": "Construct hull"},
            {"id": "engine", "label": "Construct engine"},
        ]
    }
    client = proposal.modules[1]
    source = LuauCodeGenerator(NoCoder()).generate_module_code(client, proposal)
    assert 'request("hull")' in source
    assert 'request("engine")' in source
    assert "remote:InvokeServer(actionId)" in source
    assert "Coins.Value +=" not in source
    assert not generated_module_errors(client, proposal, source, LuauStaticAnalyzer())

    server = _shell("""local choice = ...
if choice ~= "hull" and choice ~= "engine" then return false end
local stats = player:FindFirstChild("leaderstats")
local coins = stats and stats:FindFirstChild("Coins")
if not coins or coins.Value < 5 then return false end
coins.Value -= 5
return {success = true}
""", ["hull", "engine"])
    assert '["hull"] = true' in server
    assert '["engine"] = true' in server
    assert "if select(\"#\", ...) ~= 1 then return false end" in server
    assert "not __rmmAllowed[__rmmActionId]" in server


def test_semantic_source_preserves_only_approved_action_ids():
    data = {"systems": [{
        "name": "ShipParts",
        "server_behavior": (
            "Server validates each spaceship part purchase against coins "
            "and deducts the cost before storing permanent ownership."
        ),
        "client_behavior": (
            "A ship part selection UI sends the chosen part identifier and "
            "displays server-approved purchase results."
        ),
        "interaction": "request_response",
        "input_mode": "custom",
        "action_choices": [
            {"id": "hull", "label": "Build hull"},
            {"id": "engine", "label": "Build engine"},
        ],
        "observable_result": "Player receives a paid ship section in saved inventory.",
        "world_entities": [],
    }]}
    result = expand_semantic_facet(
        data, facet_id="ship-build", requirement_ids=["ship-req"],
        source_requirements=[{"id": "ship-req", "statement": "Buy ship components"}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
    )
    remote = result["remotes"][0]["name"]
    assert result["_host_action_choices"][remote] == data["systems"][0]["action_choices"]


@pytest.mark.parametrize("bad_options", [
    [{"id": "hull", "label": "Hull"}, {"id": "hull", "label": "Again"}],
    [{"id": "hull; coins.Value = 999", "label": "Hack"}],
    [{"id": "", "label": "No ID"}],
    [{"id": "hull", "label": ""}],
])
def test_architect_rejects_invalid_untrusted_option_identifiers(bad_options):
    data = {"systems": [{
        "name": "ShipOptions",
        "server_behavior": "Server validates purchases and stores spaceship upgrade ownership.",
        "client_behavior": "Client displays selectable ship component purchase options.",
        "interaction": "request_response", "input_mode": "custom",
        "action_choices": bad_options, "world_entities": [],
        "observable_result": "Ship parts can be purchased through validated inventory.",
    }]}
    with pytest.raises(HostArchitectureError):
        expand_semantic_facet(
            data, facet_id="ship-choices", requirement_ids=["req1"],
            source_requirements=[{"id": "req1", "statement": "Buy parts"}],
            reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
        )


def test_server_scaffold_receives_whitelist_and_checks_actual_client_choice():
    from roblox_mod_ai.host_service_codegen import try_scaffolded_server

    proposal = plan_single_action()
    design = proposal.game_design["dynamic_design"]
    design["host_action_choices"] = {
        "BuyShipComponent": [{"id": "hull", "label": "Build hull"}],
    }
    class OneShortResponse:
        def __init__(self):
            self.prompts = []
        def complete(self, prompt, **kwargs):
            self.prompts.append((prompt, kwargs))
            return """local choice = ...
if choice ~= "hull" then return false end
local leaderstats = player:FindFirstChild("leaderstats")
local coins = leaderstats and leaderstats:FindFirstChild("Coins")
if not coins or coins.Value < 5 then return false end
coins.Value -= 5
player:SetAttribute("HullPurchased", true)
return {success = true}
"""
    router = OneShortResponse()
    server = proposal.modules[0]
    code = try_scaffolded_server(server, proposal, router, LuauStaticAnalyzer())
    assert code is not None
    assert '["hull"] = true' in code
    assert "not __rmmAllowed[__rmmActionId]" in code
    assert "Only these approved client action IDs are valid: hull" in router.prompts[0][0]
    assert router.prompts[0][1]["max_tokens"] <= 1500
    assert not generated_module_errors(server, proposal, code, LuauStaticAnalyzer())
