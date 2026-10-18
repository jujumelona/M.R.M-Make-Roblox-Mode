"""Host UI/Remote generation actually eliminates a model coding call when safe.

Only explicit *no-argument* actions qualify. Selection, inventory, aim and
world target mechanics continue down bespoke AI client-code path.
"""
import pytest

from roblox_mod_ai.host_architecture import expand_semantic_facet
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.server_modules import (
    normalize_dynamic_server_modules, render_dynamic_server_bootstrap,
)
from roblox_mod_ai.spec import RobloxProposal


def _semantic(input_mode, interaction="event", world=None):
    return {"systems": [{
        "name": "PauseClock",
        "server_behavior": "Server verifies this player's authority to pause a shared simulation safely.",
        "client_behavior": "Show an action button and display the server response if one is expected.",
        "interaction": interaction,
        "input_mode": input_mode,
        "observable_result": "An authorized player can toggle the simulation time.",
        "world_entities": list(world or []),
    }]}


def _architecture(input_mode="host_button", interaction="event", world=None):
    facet = "clock-feature"
    statement = "Allow player to toggle the game-wide clock"
    req = "clock-requirement"
    ledger = {
        "original_prompt": statement,
        "requirements": [{"id": req, "statement": statement}],
        "facets": [{"id": facet, "requirements": [req], "source_span": statement}],
    }
    class Model:
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            return _semantic(input_mode, interaction, world)
    model = Model()
    result = RobloxDynamicArchitect(model).design(
        statement, {"ledger": ledger, "evidence": []}, [])
    proposal = RobloxProposal(
        requested_prompt=statement, game_title="ClockHost",
        description="", modules=list(result["modules"]),
        game_design={"dynamic_design": {k: v for k, v in result.items()
                                        if k != "modules"},
                     "pre_design_research": {"ledger": ledger}},
    )
    normalize_dynamic_server_modules(proposal)
    return proposal, model, result


@pytest.mark.parametrize("interaction,method", [
    ("event", "FireServer()"),
    ("request_response", "InvokeServer()"),
])
def test_host_button_client_is_generated_without_any_small_model_code_call(
        interaction, method):
    proposal, planner, result = _architecture(interaction=interaction)
    clients = [m for m in proposal.modules if m.file_path.endswith(".client.luau")]
    assert len(clients) == 1
    route = result["host_client_actions"][clients[0].name]
    remote = route["remote"]
    assert result["host_actions"][remote]["max_args"] == 0
    class NeverCoder:
        def complete(self, *args, **kwargs):
            raise AssertionError("Host should generate the whole generic input module")
    module_source = LuauCodeGenerator(NeverCoder()).generate_module_code(
        clients[0], proposal)
    assert "Activated:Connect" in module_source
    assert "ScreenGui" in module_source
    assert "UIListLayout" in module_source
    assert "LocalPlayer" in module_source
    assert method in module_source
    assert remote in module_source
    assert planner.calls == 1
    boot = render_dynamic_server_bootstrap(proposal)
    assert 'select("#", ...) ~= 0' in boot
    assert remote in boot
    assert "service.handleAction(player, services, ...)" in boot


def test_custom_selection_still_requires_real_domain_client_code():
    proposal, model, result = _architecture(input_mode="custom", world=["ClockDial"])
    assert not result.get("host_client_actions")
    client = next(m for m in proposal.modules if m.file_path.endswith(".client.luau"))
    from roblox_mod_ai.host_client import render_host_client
    with pytest.raises(ValueError, match="Not a declared"):
        render_host_client(client, proposal)
    assert model.calls == 1


@pytest.mark.parametrize("interaction,world", [
    ("none", []), ("event", ["MineableRock"]),
    ("request_response", ["EnemyNPC"]),
])
def test_zero_arg_button_must_not_masquerade_as_world_targeting(interaction, world):
    from roblox_mod_ai.host_architecture import HostArchitectureError
    with pytest.raises(HostArchitectureError):
        expand_semantic_facet(
            _semantic("host_button", interaction=interaction, world=world),
            facet_id="clock-feature", requirement_ids=["r1"],
            source_requirements=[{"id": "r1", "statement": "clock"}],
            reserved_modules=set(), reserved_remotes=set(),
            reserved_objects=set(),
        )


def test_invalid_route_or_remotekind_does_not_generate_trusted_code():
    proposal, model, result = _architecture()
    client = next(m for m in proposal.modules if m.file_path.endswith(".client.luau"))
    binding = proposal.game_design["dynamic_design"]["host_client_actions"][client.name]
    binding["kind"] = "RemoteFunction"
    from roblox_mod_ai.host_client import render_host_client
    with pytest.raises(ValueError, match="zero-argument"):
        render_host_client(client, proposal)


def test_bulk_generation_replaces_saved_host_client_and_bootstrap_instead_of_model_code():
    proposal, model, result = _architecture()
    server = next(m for m in proposal.modules
                  if m.module_id.startswith("dyn_")
                  and m.file_path.startswith("src/server/"))
    client = next(m for m in proposal.modules
                  if m.file_path.endswith(".client.luau"))
    bootstrap = next(m for m in proposal.modules
                     if m.module_id == "mod_dynamic_server_bootstrap")
    server.code = ("--!strict\nlocal Service = {}\n"
                   "function Service.start(_services) end\n"
                   "function Service.handleAction(player, _services)\n"
                   "    return player ~= nil\nend\nreturn Service\n")
    client.code = "--!strict\nprint('untrusted stale custom client')\n"
    bootstrap.code = "--!strict\nprint('untrusted stale gateway')\n"
    class NoModel:
        def complete(self, *args, **kwargs):
            raise AssertionError("Only first-party source can run here")
    modules = LuauCodeGenerator(NoModel()).generate_all_modules(proposal)
    assert client.code != "--!strict\nprint('untrusted stale custom client')\n"
    assert 'button.Activated:Connect' in client.code
    assert "Remote class mismatch" in client.code
    assert "untrusted stale gateway" not in bootstrap.code
    assert 'select("#", ...) ~= 0' in bootstrap.code
    assert "service.handleAction(player, services, ...)" in bootstrap.code


def test_forecast_discounts_only_verified_host_client_codegen():
    from roblox_mod_ai.generation_forecast import forecast_generation
    proposal, model, result = _architecture(interaction="request_response")
    ledger = proposal.game_design["pre_design_research"]["ledger"]
    modules = [m.to_dict() for m in proposal.modules]
    counts = forecast_generation(
        requested_prompt=proposal.requested_prompt,
        ledger=ledger, modules=modules,
        remotes=result["remotes"],
        host_client_actions=result["host_client_actions"],
    )["source_counts"]
    assert counts["generated_module_count"] == 2
    assert counts["host_rendered_client_module_count"] == 1
    assert counts["estimated_model_code_completions"] == 1
    assert counts["minimum_sequential_model_completions"] == 2
