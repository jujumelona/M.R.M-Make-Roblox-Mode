"""Architect integration: three partial 9B replies can form one valid facet."""
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect


def test_three_partial_actions_accumulate_instead_of_overwriting_each_other(
        monkeypatch, tmp_path):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_DISABLE_ARCHITECTURE_CACHE", "1")
    source = (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
        "우주선을 부위마다 만들어서 만들수있고"
    )
    actions = [
        {
            "name": "CraftSectionConstruction",
            "server_behavior": (
                "Server validates resource availability and creates a real "
                "craft section attached to the owned spacecraft, deducting "
                "the required materials and rejecting duplicate sections."
            ),
            "client_behavior": (
                "Player selects a craft section in the builder and "
                "receives the server-confirmed newly attached component."
            ),
            "observable_result": (
                "The newly built section appears attached to the spacecraft."
            ),
            "world_entities": ["Spacecraft"],
            "interaction": "request_response",
            "input_mode": "custom",
        },
        {
            "name": "MarketPurchaseTrade",
            "server_behavior": (
                "Server validates a catalog purchase against currency balance "
                "and item availability; on success deducts the required credits "
                "and transfers the purchased item into player inventory."
            ),
            "client_behavior": (
                "Player selects a catalog item and the client shows "
                "the confirmed delivery and the balance change."
            ),
            "observable_result": (
                "The purchased item enters player inventory and credits decrease."
            ),
            "world_entities": ["MarketTerminal"],
            "interaction": "request_response",
            "input_mode": "custom",
        },
        {
            "name": "ResourceNodeHarvest",
            "server_behavior": (
                "Server validates a player gathering a reachable resource node, "
                "harvests ore from the world source, depletes that deposit and "
                "awards the harvested resources to player inventory."
            ),
            "client_behavior": (
                "Player targets a resource node and client displays "
                "its depletion plus the server-confirmed harvested resource."
            ),
            "observable_result": (
                "The resource deposit becomes depleted and inventory rises."
            ),
            "world_entities": ["OreDeposit"],
            "interaction": "request_response",
            "input_mode": "custom",
        },
    ]

    class PartialRouter:
        def __init__(self):
            self.calls = 0

        def complete_json(self, _prompt, **_kwargs):
            idx = self.calls
            self.calls += 1
            if idx >= len(actions):
                raise AssertionError("Planner regenerated instead of merging")
            return {"systems": [actions[idx]]}

    router = PartialRouter()
    report = {
        "ledger": {
            "original_prompt": source,
            "requirements": [
                {"id": "req-001", "statement": source, "source": "user_prompt"},
            ],
            "facets": [{
                "id": "intent-craft-economy",
                "requirements": ["req-001"],
                "source_span": source,
                "search_query": "Roblox resource gathering trade build ship sections",
            }],
        },
        "evidence": [],
    }
    output = RobloxDynamicArchitect(
        router, checkpoint_dir=tmp_path,
    ).design(source, report, [])
    assert router.calls == 3, report["architecture_attempts"]
    assert len(output["modules"]) == 6
    assert len(output["remotes"]) == 3
    assert len(report["architecture_subplans"]) == 1
    assert report["architecture_subplans"][0]["validated"]
