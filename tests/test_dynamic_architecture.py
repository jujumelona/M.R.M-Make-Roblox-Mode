"""Novel mechanics need authored functionality, not recycled shop/combat stubs."""
import copy
import json
import os
from pathlib import Path

import pytest

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.dynamic_architect import (
    _clean_model_json, choose_reuse, DynamicDesignError
)

class LocalGameModel:
    def __init__(self): self.prompt_history=[]
    def complete_json(self, prompt, **kwargs):
        self.prompt_history.append(("plan",prompt))
        # The architecture is tied to exact authored clause ids.
        payload = (json.loads(prompt[prompt.index('{"original_prompt"'):])
                   if '{"original_prompt"' in prompt else {})
        clauses = [entry["id"] for entry in payload.get("requirements", [])] or ["req-001"]
        facets = [entry["id"] for entry in payload.get("facets", [])] or ["pets"]
        return {
            "modules":[{"name":"CustomPetHatching",
                        "role":"server",
                        "requirement_ids":clauses,
                        "facet_ids":facets,
                        "behavior":"Server checks egg distance, handles hatching and writes player owned items."},
                       {"name":"PetHatchController",
                        "role":"client",
                        "requirement_ids":clauses,
                        "facet_ids":facets,
                        "behavior":"Mobile keyboard and gamepad hatch button sends server validated pet hatch request."}],
            "remotes":[{"name":"HatchPet","type":"RemoteEvent"}],
            "world_objects":[{"name":"PetEggStand","class":"Part","position":[9,2,0],"size":[3,3,3]}],
            "acceptance":[{"requirement_id":rid,
                           "observable_result":"Nearby players can hatch an egg, distant players cannot."}
                          for rid in clauses],
            "acceptance_facets":[{"facet_id":f,"observable_result":
                                  "Server implements the requested "+f+" gameplay interaction."}
                                 for f in facets],
        }
    def complete(self, prompt, **kwargs):
        self.prompt_history.append(("code",prompt))
        if "PetHatchController.client.luau" in prompt:
            return """--!strict
local ContextActionService = game:GetService("ContextActionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("HatchPet")
local function hatch(_action: string, state: Enum.UserInputState, _input: InputObject)
    if state ~= Enum.UserInputState.Begin then return Enum.ContextActionResult.Pass end
    remote:FireServer()
    return Enum.ContextActionResult.Sink
end
ContextActionService:BindAction("HatchPetAction", hatch, true,
    Enum.KeyCode.E, Enum.KeyCode.ButtonX)
ContextActionService:SetTitle("HatchPetAction", "Hatch")
"""
        return """--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("HatchPet")
local egg = workspace:WaitForChild("PetEggStand")
remote.OnServerEvent:Connect(function(player)
    local char = player.Character
    local root = char and char:FindFirstChild("HumanoidRootPart")
    local hum = char and char:FindFirstChildOfClass("Humanoid")
    if not root or not hum or hum.Health <= 0 then return end
    if (root.Position - egg.Position).Magnitude > 12 then return end
    local inventory = player:FindFirstChild("OwnedItems")
    if not inventory then return end
    local pet = Instance.new("StringValue")
    pet.Name = "Pet" .. tostring(math.random(1, 9999))
    pet.Value = "Pet"
    pet.Parent = inventory
end)
"""

def _session(tmp_path,monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH","0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN","1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION","1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION","0")
    fake=LocalGameModel()
    session=CompleteRobloxAISession(output_root=tmp_path)
    session.planner.router=fake
    session.orchestrator.code_generator.router=fake
    return session,fake

def test_generic_pet_game_generates_custom_luau_world_and_remote(tmp_path,monkeypatch):
    session,fake=_session(tmp_path,monkeypatch)
    reply=session.plan("펫 부화")
    assert reply.ready_to_build,reply.message
    plan=reply.authored_plan.proposal
    modules={m.name for m in plan.modules}
    assert "CustomPetHatching" in modules
    assert "PetHatchController" in modules
    assert "CombatSystem" not in modules and "ShopService" not in modules
    assert plan.game_design["dynamic_design"]["source_reuse"]=="none_unless_validated"
    novel_test=next(x for x in plan.tests if x.test_id=="test_dynamic_structure")
    assert 'CustomPetHatching' in novel_test.test_code
    assert 'HatchPet' in novel_test.test_code
    assert 'PetEggStand' in novel_test.test_code
    assert "not gameplay behavior" in novel_test.test_code
    result=session.build(source_only=True)
    assert result.metadata["acceptance"]["passed"], result.metadata["acceptance"]
    assert result.success is False # No Roblox engine used.
    root=Path(result.project_dir)
    generated=(root/"src/server/CustomPetHatching.server.luau").read_text(encoding="utf-8")
    assert "HatchPet" in generated and "OwnedItems" in generated
    client=(root/"src/client/PetHatchController.client.luau").read_text(encoding="utf-8")
    assert "FireServer" in client and "BindAction" in client
    config=json.loads((root/"default.project.json").read_text(encoding="utf-8"))
    assert config["tree"]["Workspace"]["PetEggStand"]["$className"]=="Part"
    assert config["tree"]["ReplicatedStorage"]["Remotes"]["HatchPet"]["$className"]=="RemoteEvent"
    assert [x for x in fake.prompt_history if x[0]=="code"]

def test_mixed_pet_shop_does_not_transplant_boots_potion_shop(tmp_path,monkeypatch):
    session,fake=_session(tmp_path,monkeypatch)
    session.plan("펫 부화와 펫 상점")
    proposal=session.authored_plan.proposal
    assert "ShopService" not in {m.name for m in proposal.modules}
    assert "CustomPetHatching" in {m.name for m in proposal.modules}
    assert proposal.game_design["features"]["is_shop"] is False

def test_no_model_for_unknown_genre_fails_not_dummy_game(tmp_path,monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH","0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN","0")
    session=CompleteRobloxAISession(output_root=tmp_path)
    result=session.plan("펫 부화")
    assert not result.ready_to_build
    built=session.build(source_only=True)
    assert not built.success
    assert not built.metadata["acceptance"]["passed"]

@pytest.mark.parametrize("mutate",[
    lambda x: x.update({"modules":[]}),
    lambda x: x["modules"][0].update({"requirement_ids":["req-999"]}),
    lambda x: x["modules"][0].update({"name":"../../evil"}),
    lambda x: x["world_objects"][0].update({"class":"Script"}),
    lambda x: x["world_objects"][0].update({"position":[0,1,100000]}),
    lambda x: x.update({"acceptance":[]}),
    lambda x: x["remotes"][0].update({"type":"BindableEvent"}),
])
def test_dynamic_architecture_rejects_fake_invalid_models(mutate):
    raw=LocalGameModel().complete_json("")
    bad=copy.deepcopy(raw)
    mutate(bad)
    with pytest.raises(DynamicDesignError):
        _clean_model_json(bad,{"requirements":[{"id":"req-001","statement":"펫 부화"}]},
                          {"NetworkRemotes","PlayerDataManager"})

def test_reuse_requires_verified_license_exact_source_and_capability():
    assert not choose_reuse("made_up_lib", ["pet economy"], "safe",license_confirmed=True)["reuse"]
    assert not choose_reuse("shop_purchase", ["pet purchases"], "RemoteEvent",license_confirmed=True)["reuse"]
    assert not choose_reuse("shop_purchase", ["boots"], "OnServerInvoke Coins EconomyRules",
                            license_confirmed=False)["reuse"]


def test_model_may_not_ignore_part_of_multi_feature_request():
    raw=LocalGameModel().complete_json("")
    ledger={"requirements":[{"id":"req-001","statement":"펫 부화와 펫 상점"}],
            "facets":[{"id":"pets"},{"id":"shop"}]}
    with pytest.raises(DynamicDesignError, match="Unimplemented gameplay facets"):
        _clean_model_json(raw,ledger,{"NetworkRemotes","PlayerDataManager"})


def test_dynamic_revision_does_not_insert_irrelevant_fixed_shop(tmp_path,monkeypatch):
    session,fake=_session(tmp_path,monkeypatch)
    session.plan("펫 부화")
    reply=session.revise("펫 상점 추가")
    names={m.name for m in reply.authored_plan.proposal.modules}
    assert "CustomPetHatching" in names
    assert "ShopService" not in names
    assert reply.authored_plan.revision_count == 1
    assert reply.ready_to_build


class BrokenDesignRouter:
    def complete_json(self, prompt, **kwargs):
        raise RuntimeError("real local model endpoint is down")

def test_failed_model_architecture_does_not_return_successful_stock_game(tmp_path,monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH","0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN","1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION","0")
    session=CompleteRobloxAISession(output_root=tmp_path)
    session.planner.router=BrokenDesignRouter()
    reply=session.plan("코인 상점과 전투")
    assert not reply.ready_to_build
    ledger=reply.authored_plan.proposal.game_design["pre_design_research"]["ledger"]
    assert "dynamic_architecture_failed" in ledger["unimplemented_facets"]
    assert reply.authored_plan.proposal.game_design["dynamic_design"] is None
    build=session.build(source_only=True)
    assert not build.metadata["acceptance"]["passed"]


@pytest.mark.parametrize("unsafe",[
    "return require(123456789)",
    'local InsertService=game:GetService("InsertService"); InsertService:LoadAsset(12345)',
    'local HttpService=game:GetService("HttpService"); HttpService:GetAsync("https://evil.example")',
    'local player=game:GetService("Players").LocalPlayer; player:Kick("x")',
])
def test_model_code_with_unsafe_asset_or_client_only_api_rejected(tmp_path,monkeypatch,unsafe):
    from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
    from roblox_mod_ai.spec import RobloxModuleSpec,RobloxProposal
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION","1")
    class UnsafeRouter:
        def complete(self,*args,**kwargs): return "--!strict\n"+unsafe+"\n" * 100
    module=RobloxModuleSpec(module_id="dyn_unsafe",name="UnsafeExample",kind="server_script",
         file_path="src/server/UnsafeExample.server.luau",roblox_service="ServerScriptService")
    proposal=RobloxProposal(requested_prompt="펫 부화",game_title="X",description="",
                            game_design={"pre_design_research":{"evidence":[]}},modules=[module])
    with pytest.raises(ValueError):
        RobloxCodeRepairAgent(router=UnsafeRouter()).repair(module,proposal,attempts=1)


def test_missing_client_to_server_remote_connection_must_fail(tmp_path, monkeypatch):
    """Before this check a server-only remote was accepted as a complete game."""
    session, fake = _session(tmp_path, monkeypatch)
    def server_only(prompt, **kwargs):
        result = LocalGameModel.complete_json(fake, prompt, **kwargs)
        result["modules"] = [row for row in result["modules"] if row["role"] == "server"]
        return result
    fake.complete_json = server_only
    reply = session.plan("펫 부화")
    assert reply.ready_to_build  # Architecture itself is only a proposal.
    built = session.build(source_only=True)
    failed = {c["id"] for c in built.metadata["acceptance"]["checks"] if not c["passed"]}
    assert "wiring.HatchPet" in failed
    assert not built.metadata["acceptance"]["passed"]
    assert not built.success


def test_disconnected_client_string_reference_is_not_remote_sender(tmp_path, monkeypatch):
    session, fake = _session(tmp_path, monkeypatch)
    actual = fake.complete
    def disconnected(prompt, **kwargs):
        source = actual(prompt, **kwargs)
        if "PetHatchController.client.luau" in prompt:
            return source.replace("remote:FireServer()", "print(remote.Name)")
        return source
    fake.complete = disconnected
    session.plan("펫 부화")
    built = session.build(source_only=True)
    failures = {x["id"] for x in built.metadata["acceptance"]["checks"] if not x["passed"]}
    assert "wiring.HatchPet" in failures



def test_dynamic_doc_refs_are_bound_to_owned_facets(tmp_path, monkeypatch):
    from roblox_mod_ai.pre_design_research import build_request_ledger
    session, _ = _session(tmp_path, monkeypatch)
    ledger = build_request_ledger("펫 부화")
    research = {
        "ledger": ledger, "status": "partial", "queries": [],
        "evidence": [
            {"facet": "shop", "provider": "official_docs", "url": "https://create.roblox.com/docs/en-us/shop.md", "content_sha256": "a" * 64},
            {"facet": "pets", "provider": "official_docs", "url": "https://create.roblox.com/docs/en-us/pets.md", "content_sha256": "b" * 64},
        ],
        "asset_candidates": [], "reuse_candidates": [], "provider_failures": [],
    }
    monkeypatch.setattr(session.planner.researcher, "research", lambda prompt: research)
    reply = session.plan("펫 부화")
    assert reply.ready_to_build
    for module in reply.authored_plan.proposal.modules:
        if module.module_id.startswith("dyn_"):
            assert module.evidence_refs == ["https://create.roblox.com/docs/en-us/pets.md"]


def test_source_anchored_trade_and_combat_do_not_require_duplicate_shop_facet():
    """Reproduce the user error: all requested intents are assigned; shop is a taxonomy alias."""
    from roblox_mod_ai.request_contract import implementation_facets
    from roblox_mod_ai.dynamic_architect import _clean_model_json
    ledger = {
        "decomposition_method": "source_anchored_model",
        "requirements": [
            {"id": "req-001", "statement": "거래 구매", "source": "user_prompt"},
            {"id": "req-002", "statement": "외계인 전투", "source": "user_prompt"},
        ],
        "facets": [
            {"id": "shop", "requirements": ["req-001"], "implementation_key": "is_shop"},
            {"id": "combat", "requirements": ["req-002"], "implementation_key": "is_combat"},
            {"id": "intent-buy", "requirements": ["req-001"], "source_span": "거래 구매"},
            {"id": "intent-fight", "requirements": ["req-002"], "source_span": "외계인 전투"},
        ],
        "atomic_intents": [
            {"requirement_id": "req-001", "facet_id": "intent-buy", "source_span": "거래 구매"},
            {"requirement_id": "req-002", "facet_id": "intent-fight", "source_span": "외계인 전투"},
        ],
    }
    assert {f["id"] for f in implementation_facets(ledger)} == {"intent-buy", "intent-fight"}
    raw = {
        "modules": [{"name": "SpaceCommerceCombat", "role": "server",
                     "requirement_ids": ["req-001", "req-002"],
                     "facet_ids": ["intent-buy", "intent-fight"],
                     "behavior": "Server validates player trade funds and alien combat damage."}],
        "remotes": [], "world_objects": [],
        "acceptance": [
            {"requirement_id": "req-001", "observable_result": "Players purchase ship parts for credits."},
            {"requirement_id": "req-002", "observable_result": "Players attack aliens and receive verified damage."},
        ],
        "acceptance_facets": [
            {"facet_id": "intent-buy", "observable_result": "Players can purchase items and trade credits."},
            {"facet_id": "intent-fight", "observable_result": "Aliens lose health when an attack is validated."},
        ],
    }
    result = _clean_model_json(raw, ledger, set())
    assert set(result["module_facets"][result["modules"][0].module_id]) == {"intent-buy", "intent-fight"}
    assert set(result["acceptance_facets"]) == {"intent-buy", "intent-fight"}
    bad = copy.deepcopy(raw)
    bad["modules"][0]["facet_ids"] = ["intent-buy"]
    with pytest.raises(DynamicDesignError, match="Unimplemented gameplay facets"):
        _clean_model_json(bad, ledger, set())


def test_keyword_facet_still_required_when_no_source_anchored_atom_owns_it():
    from roblox_mod_ai.request_contract import implementation_facets
    ledger = {
        "decomposition_method": "source_anchored_model",
        "requirements": [{"id": "req-001", "statement": "거래 구매"},
                         {"id": "req-002", "statement": "외계인 전투"}],
        "facets": [
            {"id": "shop", "requirements": ["req-001"]},
            {"id": "intent-fight", "requirements": ["req-002"],
             "source_span": "외계인 전투"},
        ],
        "atomic_intents": [
            {"requirement_id": "req-002", "facet_id": "intent-fight",
             "source_span": "외계인 전투"},
        ],
    }
    # Buying is not atom-owned, so the host cannot silently drop shopping.
    assert {f["id"] for f in implementation_facets(ledger)} == {"shop", "intent-fight"}
