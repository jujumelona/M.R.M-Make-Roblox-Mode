"""Preflight source routing must never confuse static CI success with 9B results."""
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)
from test_host_scaffolded_client import plan_single_action
from test_bounded_gameplay_generation import passive_plan


def test_source_routes_are_accounted_without_running_the_model():
    p = plan_single_action()
    report = generation_scope(p)
    assert report["counts"] == {
        "bounded_server_action": 1, "bounded_client_ui": 1,
    }
    assert report["whole_file_model_risk_modules"] == []
    assert report["scope"].endswith("not_success_or_gameplay_evidence")
    p.game_design["dynamic_design"]["host_action_choices"] = {
        "BuyShipComponent": [{"id": "hull", "label": "Hull"}],
    }
    report = generation_scope(p)
    assert report["counts"]["host_declarative_options"] == 1
    assert report["counts"]["bounded_server_action"] == 1


def test_unrouted_interactive_service_stays_visible_as_whole_file_risk():
    p = passive_plan()
    service = p.modules[0]
    assert generation_scope(p)["counts"]["bounded_passive_start"] == 1
    service.name = "CustomPetHatching"
    service.description = "The player interacts to hatch a pet and earn its ownership"
    scope = generation_scope(p)
    assert scope["whole_file_model_risk_modules"] == ["CustomPetHatching"]
    assert scope["counts"]["whole_file_model_legacy"] == 1
    assert scope["scope"] != "gameplay_verified"
