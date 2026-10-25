"""Genre-independent executable action ABI: no natural-language dispatch.

The very same host compiler must support mining, garden supplies,
crafting, or arbitrary named counters. Test input attacks and a missing
persistence owner, without invoking any language-model Luau coding.
"""
from copy import deepcopy
import pytest

from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_atomic_effect import render_atomic_server, executable_spec
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer


class NoModel:
    def complete(self,*args,**kwargs):
        raise AssertionError("Executable atomic effects must never ask a model for Luau")


def plan(remote="CollectSupplies",namespace="GardenState",field="seeds",
         op="increment",amount=None):
    server=RobloxModuleSpec(module_id="dyn_action",
        name="FlexibleActionServer",kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/FlexibleActionServer.luau",
        roblox_service="ServerScriptService")
    client=RobloxModuleSpec(module_id="dyn_client",
        name="FlexibleActionClient",kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/FlexibleActionClient.client.luau",
        roblox_service="StarterPlayer.StarterPlayerScripts")
    persist=RobloxModuleSpec(module_id="mod_player_data",
        name="PlayerDataManager",kind=ModuleKind.DATA_STORE,
        file_path="src/server/PlayerDataManager.luau",
        roblox_service="ServerScriptService")
    typed={"server":server.name,"client":client.name,"transport_only":False,
           "contract":{"inputs":[{"id":"quantity","label":"Quantity","type":"integer","min":1,"max":10}],
                       "target":{"kind":"none"},
                       "state_changes":[{"scope":"player","key":namespace+"."+field,
                                         "operation":op}]},
           "world_entities":[]}
    effect={"schema":"rmm/atomic-effect-v1","namespace":namespace,"field":field,
            "operation":op,"amount":amount or {"input":"quantity"},"limit":500}
    dynamic={"host_actions":{remote:{"service":server.name,"kind":"RemoteFunction","max_args":1}},
             "host_typed_actions":{remote:typed},
             "host_executable_actions":{remote:effect},
             "remotes":{remote:"RemoteFunction"},
             "module_remotes":{server.module_id:[remote],client.module_id:[remote]}}
    proposal=RobloxProposal(requested_prompt="generic original user action",
                            game_title="Example",description="",
                            game_design={"dynamic_design":dynamic},
                            modules=[persist,server,client])
    return proposal,server


@pytest.mark.parametrize("namespace,field,op",[
    ("GardenState","seeds","increment"),
    ("RobotFuel","battery","decrement"),
    ("PuzzleProgress","score","set"),
])
def test_generic_atomic_does_not_depend_on_genre_names(namespace,field,op):
    p,m=plan(namespace=namespace,field=field,op=op)
    source=render_atomic_server(m,p)
    assert source is not None
    assert "state."+field+"=updated" in source
    assert 'GetState(player,"'+namespace+'")' in source
    assert "if current < amount" in source if op=="decrement" else True
    assert "state."+field+"=updated" in LuauCodeGenerator(router=NoModel()).generate_module_code(m,p)
    scope={x["name"]:x["strategy"] for x in generation_scope(p)["modules"]}
    assert scope[m.name]=="host_atomic_effect"
    assert generated_module_errors(m,p,source,LuauStaticAnalyzer())==[]


def test_atomic_cannot_write_undeclared_field_or_skip_balance_guard():
    p,m=plan()
    p.game_design["dynamic_design"]["host_executable_actions"]["CollectSupplies"]["field"]="extra"
    with pytest.raises(ValueError,match="UNDECLARED_STATE"):
        render_atomic_server(m,p)
    p,m=plan(op="decrement")
    source=render_atomic_server(m,p)
    assert "current < amount" in source
    assert "current - amount" in source
    assert "amount>MAXIMUM" in source
    assert 'select("#", ...) ~= 1' in source
    assert "__rmmAllowedFields" in source


def test_atomic_never_guesses_a_value_or_namespace_from_free_text():
    p,m=plan()
    p.game_design["dynamic_design"]["host_executable_actions"].clear()
    assert render_atomic_server(m,p) is None
    p,m=plan()
    p.game_design["dynamic_design"]["host_executable_actions"]["CollectSupplies"]["amount"]={"input":"secret"}
    with pytest.raises(ValueError,match="INPUT_NOT_VALIDATED"):
        render_atomic_server(m,p)
    p,m=plan()
    p.game_design["dynamic_design"]["host_executable_actions"]["CollectSupplies"]["amount"]={"constant":10000000}
    with pytest.raises(ValueError,match="INVALID_CONSTANT"):
        render_atomic_server(m,p)


def test_missing_persistent_source_never_produces_a_write():
    p,m=plan()
    p.modules=[x for x in p.modules if x.name!="PlayerDataManager"]
    with pytest.raises(ValueError,match="MISSING_PERSISTENCE"):
        render_atomic_server(m,p)
