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
    # Host shell + model-authored domain body is still model code generation.
    assert report["model_action_risk_modules"] == [p.modules[0].name]
    assert report["model_action_risk_count"] == 1
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
    assert "CustomPetHatching" in scope["model_action_risk_modules"]
    assert scope["counts"]["whole_file_model_legacy"] == 1
    assert scope["scope"] != "gameplay_verified"

def test_report45_preflight_matches_actual_typed_client_and_server_dispatch():
    from roblox_mod_ai.dynamic_architect import _clean_model_json
    from roblox_mod_ai.code_generator import LuauCodeGenerator
    from roblox_mod_ai.server_modules import normalize_dynamic_server_modules
    from test_typed_action_contract import _convert, _contract, _system

    source = "Trade resources for earned credits"
    raw = _convert(dict(_system(), action_contract=_contract()))
    ledger = {
        "original_prompt": source,
        "requirements": [{"id": "r-trade", "statement": source}],
        "facets": [{"id": "f-trade", "requirements": ["r-trade"],
                    "source_span": source}],
    }
    cleaned = _clean_model_json(raw, ledger, set())
    design = dict(cleaned)
    design.pop("modules", None)
    design.update(
        host_typed_actions=raw["_host_typed_actions"],
        host_actions={
            name: {"kind": "RemoteFunction", "service": spec["server"],
                   "max_args": 1}
            for name, spec in raw["_host_typed_actions"].items()
        },
    )
    p = RobloxProposal(
        requested_prompt=source, game_title="TypedTrade",
        description="Typed trade source-owned fixture",
        modules=cleaned["modules"],
        game_design={"dynamic_design": design},
    )
    normalize_dynamic_server_modules(p)
    scope = {row["name"]: row["strategy"]
             for row in generation_scope(p)["modules"]}
    client = next(m for m in p.modules if m.kind == ModuleKind.CLIENT_SCRIPT)
    server = next(m for m in p.modules if m.kind == ModuleKind.SERVER_MODULE
                  and m.module_id.startswith("dyn_"))
    assert scope[client.name] == "host_typed_client_ui"
    assert scope[server.name] == "bounded_typed_server_action"
    class NoClientModel:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("Typed client should be compiled by host")
    generated = LuauCodeGenerator(router=NoClientModel()).generate_module_code(client, p)
    assert "-- Host-owned typed input UI." in generated
    assert "InvokeServer(payload)" in generated
    assert server.name in generation_scope(p)["model_action_risk_modules"]
    assert client.name not in generation_scope(p)["model_action_risk_modules"]
