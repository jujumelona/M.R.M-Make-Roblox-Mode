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
local PetHatching = {}
function PetHatching.start(_services)
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
end
return PetHatching
"""

def _session(tmp_path,monkeypatch):
    # This fixture explicitly verifies backwards compatibility of old full-JSON model.
    monkeypatch.setenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL","1")
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
    assert result.success is True  # Source generation completed; no engine verdict implied.
    assert result.metadata["release_status"] == "source_only"
    assert result.playtest_report.total_tests == 0 and not result.playtest_report.passed
    root=Path(result.project_dir)
    generated=(root/"src/server/CustomPetHatching.luau").read_text(encoding="utf-8")
    assert (root/"src/server/RMMServerBootstrap.server.luau").is_file()
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
    # The agent now catches this structurally impossible server-only remote
    # BEFORE wasting GPU tokens generating Luau, and preserves the diagnosis.
    assert not reply.ready_to_build
    research = reply.authored_plan.proposal.game_design["pre_design_research"]
    assert "dynamic_architecture_failed" in research["ledger"]["unimplemented_facets"]
    assert any("no client Luau controller" in x.get("reason", "")
               for x in research["provider_failures"])
    assert (tmp_path / "plan_failure_logs.zip").is_file()


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
    # An old model may echo the redundant shop/combat taxonomy labels.
    # They are accepted for compatibility, but never replace the two intents.
    echoed = copy.deepcopy(raw)
    echoed["modules"][0]["facet_ids"].extend(["shop", "combat"])
    echoed["acceptance_facets"].extend([
        {"facet_id": "shop", "observable_result": "Players can trade using a purchase menu."},
        {"facet_id": "combat", "observable_result": "Players can fight opponents with weapons."},
    ])
    echoed_result = _clean_model_json(echoed, ledger, set())
    assert set(echoed_result["acceptance_facets"]) == {"intent-buy", "intent-fight"}
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


def test_planner_accepts_source_covered_trade_without_redundant_shop_model_label(monkeypatch):
    """Exercise full request->architect handoff, not only the JSON validator."""
    from roblox_mod_ai.planner import RobloxGameDesignPlanner
    from roblox_mod_ai.pre_design_research import _ledger_with_requirements

    prompt = "우주선 거래 구매 그리고 외계인 전투"
    requirements = [
        {"id": "req-001", "statement": "우주선 거래 구매", "source": "user_prompt"},
        {"id": "req-002", "statement": "외계인 전투", "source": "user_prompt"},
    ]
    atomic_intents = [
        {"facet_id": "intent-purchase", "requirement_id": "req-001",
         "source_span": "우주선 거래 구매",
         "intent": "Purchase spaceship parts for credits",
         "english_query": "Roblox server trade and purchases"},
        {"facet_id": "intent-combat", "requirement_id": "req-002",
         "source_span": "외계인 전투",
         "intent": "Fight alien enemies",
         "english_query": "Roblox alien combat server authority"},
    ]
    ledger = _ledger_with_requirements(prompt, requirements, atomic_intents=atomic_intents)
    assert "shop" in {f["id"] for f in ledger["facets"]}
    research = {
        "ledger": ledger,
        "schema": "rmm/pre-design-rag-v1",
        "status": "live_disabled", "queries": [], "evidence": [],
        "asset_candidates": [], "reuse_candidates": [], "provider_failures": [],
    }
    class ArchitectRouter:
        def complete_json(self, query, **kwargs):
            # The architect should send exactly the source-backed obligations,
            # not duplicate generic taxonomy from its keyword classifier.
            payload = json.loads(query[query.index('{"original_prompt"'):])
            facets = {f["id"] for f in payload["facets"]}
            assert facets == {"intent-purchase", "intent-combat"}
            modules = []
            for i, (req, facet) in enumerate(zip(requirements, atomic_intents)):
                modules.append({
                    "name": f"GameplaySystem{i+1}",
                    "role": "server", "requirement_ids": [req["id"]],
                    "facet_ids": [facet["facet_id"]],
                    "behavior": "Server validates and commits gameplay actions for " + req["statement"],
                })
            return {
                "modules": modules, "remotes": [], "world_objects": [],
                "acceptance": [
                    {"requirement_id": req["id"],
                     "observable_result": "Players can perform requested " + req["statement"]}
                    for req in requirements
                ],
                "acceptance_facets": [
                    {"facet_id": facet["facet_id"],
                     "observable_result": "Players can perform the assigned " + facet["intent"]}
                    for facet in atomic_intents
                ],
            }
    class Research:
        def research(self, actual_prompt):
            assert actual_prompt == prompt
            return research
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", "1")
    plan = RobloxGameDesignPlanner(
        router=ArchitectRouter(), pre_design_research=Research()
    ).plan(prompt)
    dyn = plan.proposal.game_design["dynamic_design"]
    assert dyn is not None
    assert set(dyn["acceptance_facets"]) == {"intent-purchase", "intent-combat"}
    assert "shop" not in dyn["acceptance_facets"]
    assert {x.name for x in plan.proposal.modules if x.module_id.startswith("dyn_")} == {
        "GameplaySystem1", "GameplaySystem2"
    }



@pytest.mark.parametrize("raw,expected", [
    ([{"name":"PurchaseShip", "type":"RemoteFunction"}],
     {"PurchaseShip":"RemoteFunction"}),
    ([{"name":"MineOre", "type":"RemoteEvent"}],
     {"MineOre":"RemoteEvent"}),
    ([{"Name":"MineOre", "Type":"Event"}],
     {"MineOre":"RemoteEvent"}),
    ([{"remote_name":"BuyPart", "remote_type":"request-response"}],
     {"BuyPart":"RemoteFunction"}),
    ([{"name":"MineOre", "className":"RemoteEvent"}],
     {"MineOre":"RemoteEvent"}),
    ({"BuyPart":"RemoteFunction", "MineOre":"RemoteEvent"},
     {"BuyPart":"RemoteFunction", "MineOre":"RemoteEvent"}),
    (["MineOre: event", "BuyPart: RPC"],
     {"MineOre":"RemoteEvent", "BuyPart":"RemoteFunction"}),
])
def test_remote_contract_normalizes_only_known_equivalent_forms(raw, expected):
    from roblox_mod_ai.dynamic_architect import _normalize_remote_rows
    rows, unresolved = _normalize_remote_rows(raw)
    assert unresolved == []
    assert {entry["name"]: entry["type"] for entry in rows} == expected


@pytest.mark.parametrize("raw", [
    [{"name":"MineOre", "type":"RemoteEvent"},
     {"name":"MineOre", "type":"RemoteFunction"}],
    [{"name":"../../evil", "type":"RemoteEvent"}],
    ["MineOre"],
    [{"name":"MineOre", "type":"BindableEvent"}],
])
def test_remote_contract_does_not_silently_approve_unsafe_protocol(raw):
    from roblox_mod_ai.dynamic_architect import _normalize_remote_rows
    if raw == [{"name":"MineOre", "type":"BindableEvent"}]:
        rows, missing = _normalize_remote_rows(raw)
        assert missing == ["MineOre"]
        assert rows[0]["type"] == ""
    else:
        with pytest.raises(DynamicDesignError):
            _normalize_remote_rows(raw)


def test_remote_type_targeted_model_repair_preserves_game_architecture():
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
    class RepairRouter:
        def __init__(self):
            self.prompts = []
        def complete_json(self, prompt, **kwargs):
            self.prompts.append(prompt)
            assert "unresolved_remote_names" in prompt
            return {"remotes": [
                {"name":"UpgradeShip", "type":"RemoteFunction"},
                {"name":"MineOre", "type":"RemoteEvent"},
                {"name":"ExtraneousRemote", "type":"RemoteEvent"},
            ]}
    fake = RepairRouter()
    source = {
        "modules": [{"name":"ShipBuildService","role":"server",
                     "behavior":"Validate resource inventory and purchase ship module."}],
        "remotes":[{"name":"UpgradeShip","type":"Remote"},
                   {"name":"MineOre","kind":"signal"}],
        "world_objects":[{"name":"ShipBuilder","class":"Part",
                          "position":[0,5,0],"size":[6,2,6]}],
        "acceptance":[{"requirement_id":"req-001","observable_result":
                       "Purchases commit atomically to the player's inventory."}],
    }
    before = copy.deepcopy(source)
    result = RobloxDynamicArchitect(router=fake)._resolve_remote_declarations(source)
    assert result["remotes"] == [
        {"name":"UpgradeShip","type":"RemoteFunction"},
        {"name":"MineOre","type":"RemoteEvent"},
    ]
    assert result["modules"] == before["modules"]
    assert result["world_objects"] == before["world_objects"]
    assert result["acceptance"] == before["acceptance"]
    assert source == before
    assert len(fake.prompts) == 1


def test_remote_type_unrepairable_cannot_silently_become_event():
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
    class BadRouter:
        def complete_json(self, *args, **kwargs):
            return {"remotes":[{"name":"BuyPart","type":"Remote"}]}
    with pytest.raises(DynamicDesignError, match="Cannot determine"):
        RobloxDynamicArchitect(router=BadRouter())._resolve_remote_declarations(
            {"remotes":[{"name":"BuyPart","type":"Remote"}]})



def test_full_architect_recovers_ambiguous_remote_without_rebuilding_valid_modules(monkeypatch):
    """Regression: the complete plan API keeps the first architecture after targeted repair."""
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", "1")
    class TwoStepModel:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append(prompt)
            if "Choose exact Roblox transport semantics" in prompt:
                return {"remotes": [{"name": "TradePurchase", "type": "RemoteFunction"}]}
            assert "Design NEW Roblox Luau modules" in prompt
            if len([p for p in self.calls if "Design NEW" in p]) > 1:
                pytest.fail("Complete architecture should NOT be regenerated")
            return {
                "modules": [
                    {"name": "TradeService", "role": "server",
                     "requirement_ids": ["req-001"], "facet_ids": ["intent-trade"],
                     "behavior": "Server validates credits and commits atomic shop purchases."},
                    {"name": "TradeController", "role": "client",
                     "requirement_ids": ["req-001"], "facet_ids": ["intent-trade"],
                     "behavior": "Client purchase menu invokes server and shows returned result."}
                ],
                "remotes": [{"name": "TradePurchase", "type": "Remote"}],
                "world_objects": [{"name": "TradingTerminal", "class": "Part",
                                   "position": [0, 3, 0], "size": [2, 4, 2]}],
                "acceptance": [{"requirement_id": "req-001",
                                "observable_result": "Player purchases debit credits exactly once."}],
                "acceptance_facets": [{"facet_id": "intent-trade",
                                       "observable_result": "Players purchase a ship part with sufficient credits."}],
            }
    router = TwoStepModel()
    result = RobloxDynamicArchitect(router=router).design(
        "우주선 부품 거래", {
            "ledger": {
                "requirements": [{"id": "req-001", "statement": "우주선 부품 거래"}],
                "facets": [{"id": "intent-trade", "requirements": ["req-001"],
                            "source_span": "우주선 부품 거래"}],
                "atomic_intents": [
                    {"requirement_id": "req-001", "facet_id": "intent-trade",
                     "source_span": "우주선 부품 거래"}
                ],
                "decomposition_method": "source_anchored_model",
            },
            "evidence": [], "reuse_candidates": []
        }, []
    )
    assert result["remotes"] == {"TradePurchase": "RemoteFunction"}
    assert {m.name for m in result["modules"]} == {"TradeService", "TradeController"}
    assert len(router.calls) == 2



def test_server_only_space_game_with_remotes_is_repaired_before_luau_generation(monkeypatch):
    """User's proposal(3).json had eleven server modules, sixteen remotes and no client."""
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", "1")
    class RoleRepairModel:
        def __init__(self): self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append(prompt)
            original = {
                "modules": [
                    {"name": "ShipService", "role": "server",
                     "requirement_ids": ["req-001"], "facet_ids": ["intent-launch"],
                     "behavior": "Server checks that purchased ship parts allow space launch."}
                ],
                "remotes": [{"name": "LaunchShip", "type": "RemoteFunction"}],
                "world_objects": [],
                "acceptance": [{"requirement_id": "req-001",
                                "observable_result": "After equipping parts, ship launch is allowed."}],
                "acceptance_facets": [{"facet_id": "intent-launch",
                                       "observable_result": "Client can launch assembled ship after validation."}],
            }
            if len(self.calls) == 1:
                return original
            assert "no client Luau controller" in prompt
            assert "Previous JSON:" in prompt
            original["modules"].append({
                "name": "LaunchController", "role": "client",
                "requirement_ids": ["req-001"], "facet_ids": ["intent-launch"],
                "behavior": "Client invokes launch request after user presses the launch button."
            })
            return original
    router = RoleRepairModel()
    result = RobloxDynamicArchitect(router=router).design(
        "우주선 조립 후 발사", {
            "ledger": {
                "requirements": [{"id": "req-001", "statement": "우주선 조립 후 발사"}],
                "facets": [{"id": "intent-launch", "requirements": ["req-001"]}],
            },
            "evidence": [], "reuse_candidates": [],
        }, [],
    )
    assert {m.name for m in result["modules"]} == {"ShipService", "LaunchController"}
    assert len(router.calls) == 2


def test_remote_without_client_cannot_be_accepted_from_saved_model_json():
    raw = {
        "modules": [{
            "name": "PlanetaryMining", "role": "server",
            "requirement_ids": ["req-001"], "facet_ids": ["mining"],
            "behavior": "Server validates ore mining reach and credits currency."
        }],
        "remotes": [{"name": "MineOre", "type": "RemoteEvent"}],
        "world_objects": [],
        "acceptance": [{"requirement_id": "req-001",
                        "observable_result": "Player receives credits after mining ore."}],
        "acceptance_facets": [{"facet_id": "mining",
                               "observable_result": "Valid ore deposits pay mining credits."}]
    }
    with pytest.raises(DynamicDesignError, match="no client Luau controller"):
        _clean_model_json(raw, {
            "requirements": [{"id": "req-001", "statement": "Mine ore"}],
            "facets": [{"id": "mining", "requirements": ["req-001"]}],
        }, set())



def _space_game_size_regression():
    """Match the actual user's failed plan: 22 modules, 17 remotes, 7 obligations."""
    from roblox_mod_ai.request_contract import clean
    names = [
        "ShipyardCatalog", "ShipyardBuilder", "CrewRoster", "WeaponCatalog",
        "ShipPerformanceCatalog", "EconomyLedger", "TradeBoard",
        "Marketplace", "LaunchGate", "PlanetRegistry", "MineralHarvest",
        "AlienCombat", "ColonizationService", "GameModeRouter",
        "ClientShipyardUI", "ClientCrewUI", "ClientWeaponUI",
        "ClientEconomyUI", "ClientLaunchUI", "ClientPlanetUI",
        "ClientCombatUI", "ClientColonizationUI",
    ]
    remote_names = [
        "RequestShipSection", "RequestShipUpgrade", "RequestCrewRecruit",
        "RequestCrewAssign", "RequestWeaponPurchase", "RequestWeaponUpgrade",
        "RequestPerformanceUpgrade", "RequestCurrencySpend", "RequestCurrencyEarn",
        "RequestTradeOffer", "RequestMarketPurchase", "RequestLaunch",
        "RequestPlanetSelect", "RequestMineralHarvest", "RequestCombatAction",
        "RequestColonize", "RequestGameModeTransition",
    ]
    requirements = [{"id": f"req-{i:03}", "statement": f"Requested gameplay clause {i}"}
                    for i in range(1, 8)]
    facets = [{"id": f"intent-{i}", "requirements": [f"req-{i:03}"],
               "source_span": f"Requested gameplay clause {i}"}
              for i in range(1, 8)]
    ledger = {
        "decomposition_method": "source_anchored_model",
        "requirements": requirements,
        "facets": facets,
        "atomic_intents": [
            {"facet_id": f["id"], "requirement_id": f["requirements"][0],
             "source_span": f["source_span"]}
            for f in facets
        ],
    }
    modules = [
        {"name": name, "role": "server" if i < 14 else "client",
         "requirement_ids": [f"req-{i % 7 + 1:03}"],
         "facet_ids": [f"intent-{i % 7 + 1}"],
         "behavior": "Server validates gameplay operations and reconciles "
                     "the requested user-visible action for " + name}
        for i, name in enumerate(names)
    ]
    raw = {
        "modules": modules,
        "remotes": [{"name": name, "type": "RemoteFunction"}
                    for name in remote_names],
        "world_objects": [
            {"name": "ShipyardPlatform", "class": "Part",
             "position": [0, 0, 0], "size": [10, 2, 10]},
            {"name": "LaunchPad", "class": "Part",
             "position": [0, 0, 20], "size": [8, 1, 8]},
            {"name": "PlanetSurface", "class": "Part",
             "position": [0, 0, 0], "size": [100, 1, 100]},
        ],
        "acceptance": [
            {"requirement_id": r["id"],
             "observable_result": "Players can carry out this requested game action: " + r["statement"]}
            for r in requirements
        ],
        "acceptance_facets": [
            {"facet_id": f["id"],
             "observable_result": "Players can carry out a real " + f["source_span"]}
            for f in facets
        ],
    }
    return ledger, raw


def test_valid_22_modules_and_17_remotes_are_not_discarded_by_arbitrary_quota():
    ledger, raw = _space_game_size_regression()
    design = _clean_model_json(raw, ledger, set())
    assert len(design["modules"]) == 22
    assert len(design["remotes"]) == 17
    assert len(design["world_objects"]) == 3
    assert len(design["acceptance"]) == 7
    assert len(design["acceptance_facets"]) == 7
    assert {m.name for m in design["modules"]} == {
        m["name"] for m in raw["modules"]
    }


def test_large_design_cannot_hide_missing_user_gameplay_or_duplicate_remote():
    ledger, raw = _space_game_size_regression()
    missing = copy.deepcopy(raw)
    for module in missing["modules"]:
        if "intent-4" in module["facet_ids"]:
            # Reassign rather than leaving an empty module declaration:
            # simulate a plausibly formed model answer omitting one mechanic.
            module["facet_ids"] = ["intent-3"]
    with pytest.raises(DynamicDesignError, match="Unimplemented gameplay facets"):
        _clean_model_json(missing, ledger, set())
    duplicate = copy.deepcopy(raw)
    duplicate["remotes"].append(copy.deepcopy(duplicate["remotes"][0]))
    with pytest.raises(DynamicDesignError, match="Duplicate remote"):
        _clean_model_json(duplicate, ledger, set())


def test_compound_game_architecture_shards_and_repairs_without_reprinting_game(monkeypatch):
    """Regress the 2026 space-game failures: missing client, malformed JSON.

    A client-only response must retain the approved server/remote contract.
    Later feature failures must never regenerate earlier accepted features.
    """
    from collections import Counter
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    ledger, _ = _space_game_size_regression()

    class Router:
        def __init__(self):
            self.calls = []
            self.attempts = Counter()

        def complete_json(self, query, **kwargs):
            if query.startswith("Return ONLY JSON"):
                payload = json.JSONDecoder().raw_decode(
                    query[query.index('{"feature"'):])[0]
                facet = payload["feature"]["id"]
                self.calls.append(("client-patch", facet))
                return {"modules": [self.module(facet, "client")]}

            payload = json.JSONDecoder().raw_decode(
                query[query.index('{"feature_id"'):])[0]
            facet = payload["feature_id"]
            self.calls.append(("facet", facet))
            self.attempts[facet] += 1
            if facet == "intent-2" and self.attempts[facet] == 1:
                raise ValueError("JSONDecodeError: model output was truncated")
            index = int(facet.removeprefix("intent-"))
            modules = [self.module(facet, "server")]
            if facet != "intent-1":
                modules.append(self.module(facet, "client"))
            return {
                "modules": modules,
                "remotes": [{"name": f"RequestFeature{index}",
                             "type": "RemoteFunction"}],
                "world_objects": [],
                "acceptance": [{"requirement_id": f"req-{index:03}",
                                "observable_result":
                                "Player can use the requested feature in the game."}],
                "acceptance_facets": [{"facet_id": facet,
                                       "observable_result":
                                       "The player sees an observable gameplay result."}],
            }

        @staticmethod
        def module(facet, role):
            index = int(facet.removeprefix("intent-"))
            return {
                "name": f"Feature{index}{'ClientUI' if role == 'client' else 'Server'}",
                "role": role,
                "requirement_ids": [f"req-{index:03}"],
                "facet_ids": [facet],
                "uses_remotes": [f"RequestFeature{index}"],
                "behavior": (
                    "Client displays controls, sends request and shows a visible result."
                    if role == "client" else
                    "Server validates action, applies rules and returns a safe result."
                ),
            }

    router = Router()
    research = {"ledger": ledger, "evidence": [], "reuse_candidates": []}
    answer = RobloxDynamicArchitect(router).design(
        "Build modular spaceship, trade, visit planets, colonize", research, []
    )
    assert len(answer["modules"]) == 14
    assert len(answer["remotes"]) == 7
    assert sum(x["passed"] for x in research["architecture_attempts"]) == 7
    assert sum(not x["passed"] for x in research["architecture_attempts"]) == 2
    assert router.calls.count(("facet", "intent-1")) == 1
    assert router.calls.count(("client-patch", "intent-1")) == 1
    assert router.calls.count(("facet", "intent-2")) == 2
    assert all(router.calls.count(("facet", f"intent-{n}")) == 1
               for n in (1, 3, 4, 5, 6, 7))
    assert len(research["architecture_subplans"]) == 7
    assert research["architecture_assembly"]["validated"] is True
    assert research["architecture_assembly"]["gameplay_verified"] is False


def test_scoped_failure_does_not_claim_a_partial_game_as_complete(monkeypatch):
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    ledger, _ = _space_game_size_regression()

    class Router:
        def __init__(self): self.calls = 0
        def complete_json(self, query, **kwargs):
            self.calls += 1
            raise ValueError("malformed or unavailable JSON")

    research = {"ledger": ledger, "evidence": [], "reuse_candidates": []}
    with pytest.raises(DynamicDesignError, match="Feature intent-1"):
        RobloxDynamicArchitect(Router()).design("a space game", research, [])
    assert not research["architecture_subplans"]
    assert len(research["architecture_attempts"]) == 3
    assert all(not item["passed"] for item in research["architecture_attempts"])


def test_explicit_scoped_remotes_require_both_endpoints():
    from roblox_mod_ai.dynamic_architect import _clean_model_json
    ledger = {
        "requirements": [{"id": "req-001", "statement": "Trade resources"}],
        "facets": [{"id": "trade", "requirements": ["req-001"]}],
    }
    modules = [
        {"name": "TradeServer", "role": "server",
         "requirement_ids": ["req-001"], "facet_ids": ["trade"],
         "uses_remotes": ["BuyResource"],
         "behavior": "Validate a player's credit balance and confirm resource purchase."},
        {"name": "TradeClient", "role": "client",
         "requirement_ids": ["req-001"], "facet_ids": ["trade"],
         "uses_remotes": [],
         "behavior": "Present a trade window and send validated shopping requests."},
    ]
    plan = {
        "modules": modules,
        "remotes": [{"name": "BuyResource", "type": "RemoteFunction"}],
        "world_objects": [],
        "acceptance": [{"requirement_id": "req-001",
                        "observable_result": "Players can purchase a resource."}],
        "acceptance_facets": [{"facet_id": "trade",
                               "observable_result": "Trade inventory changes after purchase."}],
    }
    with pytest.raises(DynamicDesignError, match="needs explicit client and server"):
        _clean_model_json(plan, ledger, set())
    plan["modules"][1]["uses_remotes"] = ["BuyResource"]
    accepted = _clean_model_json(plan, ledger, set())
    assert accepted["module_remotes"]
    assert all(names == ["BuyResource"]
               for names in accepted["module_remotes"].values())
