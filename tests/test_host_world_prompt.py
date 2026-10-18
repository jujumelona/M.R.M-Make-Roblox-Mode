"""Roblox-native ProximityPrompt cuts client code AND Remote from world actions.

World target/validation remains server-authoritative. The generic Part is
greybox geometry, not proof of fully implemented item/combat mechanics.
"""
import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.host_architecture import (
    expand_semantic_facet, HostArchitectureError,
)
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.server_modules import (
    normalize_dynamic_server_modules, render_dynamic_server_bootstrap,
    module_bootstrap_contract,
)
from roblox_mod_ai.server_interface_audit import inspect_dynamic_server_interfaces
from roblox_mod_ai.spec import RobloxProposal


def _world_model(world=None, mode="world_prompt", interaction="event"):
    return {"systems": [{
        "name": "OpenSecretDoor",
        "server_behavior": "Check server-verified door state and player permission before unlocking door.",
        "client_behavior": "Show nearby world interaction prompt and confirm door state changes.",
        "interaction": interaction, "input_mode": mode,
        "observable_result": "Nearby authorized users unlock the door with a prompt.",
        "world_entities": ["VaultDoor"] if world is None else world,
    }]}


def _world_plan():
    prompt = "Players can interact with a nearby authorized vault door"
    ledger = {
        "original_prompt": prompt,
        "requirements": [{"id": "r-door", "statement": prompt}],
        "facets": [{"id": "f-door", "requirements": ["r-door"],
                    "source_span": prompt}],
    }
    class Model:
        def __init__(self): self.calls = 0
        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            return _world_model()
    model = Model()
    result = RobloxDynamicArchitect(model).design(
        prompt, {"ledger": ledger, "evidence": []}, [])
    p = RobloxProposal(
        requested_prompt=prompt, game_title="VaultPrompt",
        description="", modules=list(result["modules"]),
        game_design={"dynamic_design": {
            k: v for k, v in result.items() if k != "modules"},
                     "pre_design_research": {"ledger": ledger}},
    )
    normalize_dynamic_server_modules(p)
    return p, result, model


def test_native_world_prompt_needs_one_server_zero_clients_zero_remotes():
    p, result, model = _world_plan()
    assert model.calls == 1
    assert len(result["modules"]) == 1
    assert result["remotes"] == {}
    assert result.get("host_actions") == {}
    assert result.get("host_client_actions") == {}
    assert len(result["host_world_actions"]) == 1
    name, binding = next(iter(result["host_world_actions"].items()))
    assert binding["service"] == result["modules"][0].name
    assert name == result["world_objects"][0]["name"]
    assert not any(m.file_path.endswith(".client.luau") for m in p.modules)
    bootstrap = render_dynamic_server_bootstrap(p)
    assert 'prompt.Triggered:Connect(function(player)' in bootstrap
    assert 'humanoid.Health <= 0' in bootstrap
    assert 'prompt.MaxActivationDistance + 2' in bootstrap
    assert 'player.Parent ~= Players' in bootstrap
    assert 'service.handleAction(player, services, part)' in bootstrap
    assert "OnServerEvent" not in bootstrap
    assert "OnServerInvoke" not in bootstrap
    project = RobloxProjectGenerator(".").generate_rojo_project_json(p)
    world = project["tree"]["Workspace"][name]
    assert world["$properties"]["Anchored"] is True
    assert world["RMMInteract"]["$className"] == "ProximityPrompt"
    assert world["RMMInteract"]["$properties"]["MaxActivationDistance"] == 10
    domain = next(m for m in p.modules if m.module_id.startswith("dyn_"))
    assert "HOST-OWNED PROXIMITY" in module_bootstrap_contract(domain, p)


@pytest.mark.parametrize("input_mode,interaction,world", [
    ("world_prompt", "request_response", ["Door"]),
    ("world_prompt", "none", ["Door"]),
    ("world_prompt", "event", []),
    ("world_prompt", "event", ["Door", "Wall"]),
])
def test_never_replace_complex_world_selection_with_one_prompt(input_mode, interaction, world):
    with pytest.raises(HostArchitectureError):
        expand_semantic_facet(
            _world_model(world=world, mode=input_mode, interaction=interaction),
            facet_id="f", requirement_ids=["r"],
            source_requirements=[{"id": "r", "statement": "door"}],
            reserved_modules=set(), reserved_remotes=set(), reserved_objects=set())


def test_host_world_requires_server_handler_and_rejects_tampered_action():
    p, result, model = _world_plan()
    target = next(m for m in p.modules if m.module_id.startswith("dyn_"))
    target.code = (
        "--!strict\nlocal Door = {}\n"
        "function Door.start(_services) end\n"
        "return Door\n"
    )
    bad = inspect_dynamic_server_interfaces(p)
    assert not bad["passed"]
    assert any(c["id"] == "service.handleAction." + target.name
               and not c["passed"] for c in bad["checks"])
    target.code = target.code.replace(
        "return Door", "function Door.handleAction(player, services, targetPart)\n"
        "    return player ~= nil and services ~= nil and targetPart ~= nil\n"
        "end\nreturn Door"
    )
    assert inspect_dynamic_server_interfaces(p)["passed"]
    world_name = next(iter(result["host_world_actions"]))
    p.game_design["dynamic_design"]["host_world_actions"][world_name]["service"] = "FakeService"
    with pytest.raises(ValueError, match="unknown world Part/service"):
        render_dynamic_server_bootstrap(p)
