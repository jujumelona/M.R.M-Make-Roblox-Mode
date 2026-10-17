import os
import pytest
from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal
from roblox_mod_ai.planner import RobloxGameDesignPlanner

class FakeRouter:
    def __init__(self): self.calls=0
    def complete(self, *args, **kwargs):
        self.calls+=1
        return "--!strict\nlocal ReplicatedStorage = game:GetService('ReplicatedStorage')\nlocal result = ReplicatedStorage:WaitForChild('Remotes')\nreturn result\n"

class FakeDocs:
    def search(self,*args,**kwargs):
        return {"results":[{"url":"https://create.roblox.com/docs/llms.txt","excerpt":"RemoteEvent"}]}

def setup():
    return RobloxModuleSpec(module_id="m",name="DynamicCraft",kind="shared_module",
       file_path="src/shared/DynamicCraft.luau",roblox_service="ReplicatedStorage",
       description="Craft a game system"), RobloxProposal(
       requested_prompt="make crafting",game_title="Game",description="",game_design={},modules=[])

def test_model_loop_requires_explicit_optin(monkeypatch):
    monkeypatch.delenv("RMM_ENABLE_MODEL_GENERATION",raising=False)
    m,p=setup()
    with pytest.raises(RuntimeError):
        RobloxCodeRepairAgent(FakeRouter(),FakeDocs()).repair(m,p)

def test_model_loop_returns_nonplaceholder_code(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION","1")
    m,p=setup()
    router=FakeRouter()
    result=RobloxCodeRepairAgent(router,FakeDocs()).repair(m,p)
    assert router.calls==1
    assert "WaitForChild" in result

def test_unknown_genre_cannot_pass_as_game():
    with pytest.raises(ValueError):
        RobloxGameDesignPlanner().plan("Write a fully novel cooking recipe manager")
