"""Prompt-independent, adversarial source-only attestation tests.

The same proof engine must work for any resource name, craft, or genre,
and must fail closed when the actual world or persistence effect disappears.
"""
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.source_transition_attestation import (
    attest_compound_state_transition,
)

WORLD = "src/server/GatherServer.luau"
CRAFT = "src/server/VehicleServer.luau"
WORLD_SOURCE = """--!strict
local Service = {}
local function validSource(part)
    return part:IsDescendantOf(workspace)
end
local stockByPart = {}
local function getStock(part)
    if not validSource(part) then return nil end
    if not stockByPart[part] then stockByPart[part] = { remaining = 100 } end
    return stockByPart[part]
end
function Service.handleAction(player, services, ...)
    if not validSource(part) then return false end
    local distance = (root.Position - part.Position).Magnitude
    if distance > 12 then return false end
    local stock = getStock(part)
    if not stock then return false end
    if stock.remaining > 0 then
        local profile = services.PlayerDataManager.GetState(player, "GatherState")
        if not profile then return false end
        local prior = profile.items
        if prior == nil then prior = 0 end
        if type(prior) ~= "number" then return false end
        stock.remaining -= 1
        profile.items = prior + 1
        part:SetAttribute("ItemsLeft", stock.remaining)
        return { success = true, items = profile.items }
    end
    return false
end
return Service
"""
CRAFT_SOURCE = """--!strict
local Service = {}
local function makePart(parts, id)
    local part = Instance.new("Part")
    part.Parent = parts
end
function Service.start(services)
    services.PlayerDataManager.OnReady(function(player)
        local profile = services.PlayerDataManager.GetState(player, "CraftState")
        for id in pairs(profile.slots) do
            local saved = profile.slots[id]
            if saved then makePart(parts, id) end
        end
    end)
end
function Service.handleAction(player, services, ...)
    local profile = services.PlayerDataManager.GetState(player, "CraftState")
    local inventory = services.PlayerDataManager.GetState(player, "CurrencyState")
    if profile.slots[id] then
        return { success = false }
    end
    inventory.points = points - cost
    profile.slots[id] = { owned = true }
    makePart(parts, id)
    return { success = true, section = id }
end
return Service
"""
PROVIDER = """local PlayerDataManager = {}
function PlayerDataManager.GetState(player, namespace)
    if type(data.gameState) ~= "table" then data.gameState = {} end
    return data.gameState[namespace]
end
function PlayerDataManager.OnReady(callback) end
local savePlayerData
savePlayerData = function(player)
    local snapshot = HttpService:JSONDecode(HttpService:JSONEncode(data))
    store:UpdateAsync(key, function(current)
        return snapshot
    end)
end
local function onPlayerRemoving(player)
    savePlayerData(player)
end
Players.PlayerRemoving:Connect(onPlayerRemoving)
return PlayerDataManager
"""
WORLD_EFFECT = (
    "When gathering from the world, the player's owned items increase "
    "while the validated world's source stock decreases"
)
CRAFT_EFFECT = (
    "The owned vehicle assembly slot is persisted in the player's "
    "server-owned profile and restored as a physical component"
)


def _source_attestation(tmp_path, *, world=WORLD_SOURCE,
                        craft=CRAFT_SOURCE, provider=PROVIDER):
    db = tmp_path / "src/server/PlayerDataManager.luau"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_text(provider, encoding="utf-8")
    sources = {WORLD: world, CRAFT: craft}
    roles = [
        SimpleNamespace(
            file_path=WORLD,
            description="World gather source and owned inventory items progress",
        ),
        SimpleNamespace(
            file_path=CRAFT,
            description="Persist assembled vehicle slot and restore component",
        ),
    ]
    return sources, roles


def test_source_proves_both_independent_compound_transitions(tmp_path):
    sources, roles = _source_attestation(tmp_path)
    proof, meta = attest_compound_state_transition(
        WORLD_EFFECT, sources, roles, tmp_path,
    )
    assert meta["status"] == "deterministic_compound_source_witness", meta
    assert len(proof["proof_lines"]) == 2, proof
    assert {x["quote"] for x in proof["proof_lines"]} == {
        "stock.remaining -= 1", "profile.items = prior + 1",
    }
    proof, meta = attest_compound_state_transition(
        CRAFT_EFFECT, sources, roles, tmp_path,
    )
    assert meta["status"] == "deterministic_compound_source_witness", meta
    assert len(proof["proof_lines"]) == 3, proof
    assert proof["quote"] == "part.Parent = parts", proof


def test_transfer_fails_if_world_stock_or_inventory_credit_is_missing(tmp_path):
    for broken in (
        WORLD_SOURCE.replace("stock.remaining -= 1", "local sample = 1"),
        WORLD_SOURCE.replace("profile.items = prior + 1", "local sample = prior + 1"),
        WORLD_SOURCE.replace("type(prior)", "typeof(counter)"),
        WORLD_SOURCE.replace("IsDescendantOf(workspace)", "IsA('Part')"),
        WORLD_SOURCE.replace("local stock = getStock(part)", "local stock = {}"),
        WORLD_SOURCE.replace('part:SetAttribute("ItemsLeft", stock.remaining)',
                             'local ignored = stock.remaining'),
        WORLD_SOURCE.replace("stock.remaining -= 1", "stock.remaining -= 1\n        task.wait(1)"),
    ):
        sources, roles = _source_attestation(tmp_path, world=broken)
        result, _ = attest_compound_state_transition(
            WORLD_EFFECT, sources, roles, tmp_path,
        )
        assert result is None, broken


def test_projection_fails_if_real_storage_or_world_replay_is_missing(tmp_path):
    for broken in (
        {"craft": CRAFT_SOURCE.replace("part.Parent = parts", "local ignored = parts")},
        {"craft": CRAFT_SOURCE.replace("OnReady(function(player)", "OnNotReady(function(player)")},
        {"craft": CRAFT_SOURCE.replace('GetState(player, "CraftState")',
                                        'GetState(player, "OtherNamespace")', 1)},
        {"provider": PROVIDER.replace("return snapshot", "return current")},
        {"provider": PROVIDER.replace("JSONEncode(data)", "JSONEncode({})")},
        {"provider": PROVIDER.replace("Players.PlayerRemoving:Connect(onPlayerRemoving)",
                                       "local neverConnected = true")},
        {"craft": CRAFT_SOURCE.replace("profile.slots[id] = { owned = true }",
                                        "local localValue = true")},
    ):
        sources, roles = _source_attestation(tmp_path, **broken)
        proof, _ = attest_compound_state_transition(
            CRAFT_EFFECT, sources, roles, tmp_path,
        )
        assert proof is None, broken


def test_unrelated_service_and_ambiguous_duplicate_owners_fail_closed(tmp_path):
    sources, roles = _source_attestation(tmp_path)
    no_match, _ = attest_compound_state_transition(
        "Aliens are defeated and persistent trophies are awarded",
        sources, roles, tmp_path,
    )
    assert no_match is None
    another = "src/server/AnotherGatherServer.luau"
    sources[another] = WORLD_SOURCE
    roles.append(SimpleNamespace(
        file_path=another,
        description="World gather source and owned inventory items progress",
    ))
    no_match, details = attest_compound_state_transition(
        WORLD_EFFECT, sources, roles, tmp_path,
    )
    assert no_match is None
    assert details["candidate_count"] == 2



def test_whole_requirement_audit_uses_compound_proof_without_model_guess(tmp_path):
    """Integration: two independently sourced effects, no LLM witness choice."""
    from roblox_mod_ai.requirement_completion_audit import (
        audit_whole_requirement_completion,
    )
    sources, roles = _source_attestation(tmp_path)
    for path, source in sources.items():
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    proposal = SimpleNamespace(
        modules=[SimpleNamespace(name="WorldService", file_path=WORLD,
                                 description=roles[0].description),
                 SimpleNamespace(name="CraftService", file_path=CRAFT,
                                 description=roles[1].description)],
        game_design={"detailed_implementation_plan": {"required_functions": [{
            "id": "req-universal",
            "original_request": "Gather from world sources and construct saved craft",
            "server_state_changes": [WORLD_EFFECT, CRAFT_EFFECT],
            "owner_files": [WORLD, CRAFT],
        }]}}
    )
    class NoModelWitnesses:
        def __init__(self):
            self.requests = []
        def complete_json(self, **kwargs):
            self.requests.append(kwargs["prompt"])
            assert kwargs["prompt"].startswith("Find user-requested"), kwargs["prompt"][:100]
            return {"missing_actions": []}
    model = NoModelWitnesses()
    report = audit_whole_requirement_completion(
        proposal, tmp_path, model, host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert len(report["checks"]) == 2
    assert sorted(x["stage"] for x in report["recovery"]
                  if x.get("status") == "deterministic_compound_source_witness") == [
        "deterministic_compound_audit", "deterministic_compound_audit",
    ]
    assert all(x.startswith("Find user-requested") for x in model.requests)
