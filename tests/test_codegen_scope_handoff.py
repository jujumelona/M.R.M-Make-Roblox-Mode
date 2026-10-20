"""Reproduce proposal15's lost ownership and cross-module repair context.

The local model transport is deterministic; these checks exercise production
planning, serialization and coder prompts, without claiming GGUF inference.
"""
from copy import deepcopy
import json

from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal
from test_dynamic_architecture import _session
from test_uploaded_service_recovery import _plan


GOOD = (
    "local Service = {}\nfunction Service.start(services)\n"
    "workspace:SetAttribute('ModeActive', true)\nend\nreturn Service"
)
BAD = (
    "--!strict\nlocal Service = {}\nfunction Service.start(services)\n"
    "local x = (number)[]\n"
)


class Recorder:
    def __init__(self, *responses):
        self.responses = iter(responses or (GOOD,))
        self.queries = []

    def complete(self, prompt, **kwargs):
        self.queries.append(prompt)
        return next(self.responses)


def test_planner_keeps_world_ownership_in_saved_plan_and_actual_coder(tmp_path, monkeypatch):
    session, _ = _session(tmp_path, monkeypatch)
    monkeypatch.setenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", "0")
    session.plan("펫 부화")
    saved = json.loads((tmp_path / "proposal.json").read_text(encoding="utf-8"))
    proposal = RobloxProposal.from_dict(saved["proposal"])
    domain = next(m for m in proposal.modules if m.name == "CustomPetHatching")
    design = proposal.game_design["dynamic_design"]
    assert design.get("module_world_objects", {}).get(domain.module_id) == ["PetEggStand"]
    design["world_objects"].append({"name": "UnrelatedAlien", "class": "Part",
                                    "position": [20, 2, 0], "size": [4, 4, 4]})
    model = Recorder()
    RobloxCodeRepairAgent(model).repair(domain, proposal, attempts=1)
    assert "PetEggStand" in model.queries[0]
    assert "UnrelatedAlien" not in model.queries[0]


def _detailed_plan(module, *, shared):
    owners = [module.name, "SiblingMiningService"] if shared else [module.name]
    return {
        "required_functions": [{
            "id": "r-mode", "original_request": "발사 구역을 활성화한다",
            "owner_modules": owners,
            "owner_files": [module.file_path],
            "expected_outcome": "MINE_SIBLING_ORE" if shared else "ACTIVATE_OWN_ZONE",
            "invalid_or_edge_inputs": ["REJECT_INACTIVE_ZONE"],
        }],
        "ai_planning": {"requirements": {"r-mode": {
            "steps": ["MINE_SIBLING_ORE" if shared else "ACTIVATE_OWN_ZONE"],
        }}},
    }


def test_shared_requirement_does_not_assign_sibling_gameplay_to_each_module(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, proposal = _plan()
    detail = _detailed_plan(module, shared=True)
    sibling = RobloxModuleSpec(
        module_id="dyn_sibling", name="SiblingMiningService", kind="server_module",
        file_path="src/server/SiblingMiningService.luau",
        roblox_service="ServerScriptService")
    proposal.modules.append(sibling)
    proposal.game_design["dynamic_design"]["module_facets"] = {
        module.module_id: ["mode"], sibling.module_id: ["mode"]}
    proposal.game_design["detailed_implementation_plan"] = detail
    original = deepcopy(proposal.to_dict())
    model = Recorder(BAD, GOOD)
    RobloxCodeRepairAgent(model).repair(module, proposal, attempts=2)
    assert len(model.queries) == 2
    for prompt in model.queries:
        assert "MINE_SIBLING_ORE" not in prompt
        assert "SiblingMiningService" not in prompt
        assert module.description in prompt
        assert "발사 구역을 활성화한다" in prompt
    assert proposal.to_dict() == original, "Scope the prompt without rewriting the approved game plan"


def test_exclusive_requirement_keeps_its_steps_and_edge_cases_on_retry(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, proposal = _plan()
    proposal.game_design["detailed_implementation_plan"] = _detailed_plan(module, shared=False)
    model = Recorder(BAD, GOOD)
    RobloxCodeRepairAgent(model).repair(module, proposal, attempts=2)
    for prompt in model.queries:
        assert "ACTIVATE_OWN_ZONE" in prompt
        assert "REJECT_INACTIVE_ZONE" in prompt
        assert "ModeClient.client.luau" not in prompt


def test_server_client_owners_of_one_mechanic_keep_approved_constraints(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, proposal = _plan()
    client = RobloxModuleSpec(
        module_id="dyn_mode_client", name="ModeClient", kind="client_script",
        file_path="src/client/ModeClient.client.luau",
        roblox_service="StarterPlayer.StarterPlayerScripts")
    proposal.modules.append(client)
    detail = _detailed_plan(module, shared=False)
    detail["required_functions"][0]["owner_modules"].append(client.name)
    detail["required_functions"][0]["owner_files"].append(client.file_path)
    proposal.game_design["detailed_implementation_plan"] = detail
    proposal.game_design["dynamic_design"]["module_facets"] = {
        module.module_id: ["mode"], client.module_id: ["mode"]}
    model = Recorder(BAD, GOOD)
    RobloxCodeRepairAgent(model).repair(module, proposal, attempts=2)
    for prompt in model.queries:
        assert "ACTIVATE_OWN_ZONE" in prompt
        assert "REJECT_INACTIVE_ZONE" in prompt


def test_initial_recovery_checks_malformed_existing_source_before_building_prompt(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, proposal = _plan()
    model = Recorder()
    RobloxCodeRepairAgent(model).repair(
        module, proposal, existing_code=BAD,
        diagnostics="UNBALANCED_BLOCKS: previous candidate is incomplete", attempts=1,
    )
    prompt = model.queries[0]
    assert "Existing source:\n" + BAD not in prompt
    assert "Failed source excerpt" in prompt
    assert "4: local x = (number)[]" in prompt
