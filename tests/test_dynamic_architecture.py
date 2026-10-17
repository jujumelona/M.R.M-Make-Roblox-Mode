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
        facets = ["pets", "shop"] if "상점" in prompt else ["pets"]
        return {
            "modules":[{"name":"CustomPetHatching",
                        "role":"server",
                        "requirement_ids":["req-001"],
                        "facet_ids":facets,
                        "behavior":"Server checks egg distance, handles hatching and writes player owned items."}],
            "remotes":[{"name":"HatchPet","type":"RemoteEvent"}],
            "world_objects":[{"name":"PetEggStand","class":"Part","position":[9,2,0],"size":[3,3,3]}],
            "acceptance":[{"requirement_id":"req-001",
                           "observable_result":"Nearby players can hatch an egg, distant players cannot."}],
            "acceptance_facets":[{"facet_id":f,"observable_result":
                                  "Server implements the requested "+f+" gameplay interaction."}
                                 for f in facets],
        }
    def complete(self, prompt, **kwargs):
        self.prompt_history.append(("code",prompt))
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
    assert "CombatSystem" not in modules and "ShopService" not in modules
    assert plan.game_design["dynamic_design"]["source_reuse"]=="none_unless_validated"
    result=session.build(source_only=True)
    assert result.metadata["acceptance"]["passed"], result.metadata["acceptance"]
    assert result.success is False # No Roblox engine used.
    root=Path(result.project_dir)
    generated=(root/"src/server/CustomPetHatching.server.luau").read_text(encoding="utf-8")
    assert "HatchPet" in generated and "OwnedItems" in generated
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
