"""Full scoped-architect regression for plan (65): missing actions fail closed."""
import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect, DynamicDesignError


def test_craft_only_output_does_not_certify_resource_farming_and_trade(
        monkeypatch, tmp_path):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_DISABLE_ARCHITECTURE_CACHE", "1")
    source = (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
        "우주선을 부위마다 만들어서 만들수있고"
    )
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [
            {"id": "req-001", "statement": source, "source": "user_prompt"},
        ],
        "facets": [{
            "id": "intent-craft-economy",
            "requirements": ["req-001"], "source_span": source,
            "search_query": "Gather resources trade and build craft parts",
        }],
    }, "evidence": []}

    class CraftOnlyModel:
        def __init__(self):
            self.calls = 0

        def complete_json(self, *_args, **_kwargs):
            self.calls += 1
            return {"systems": [{
                "name": "CraftSectionBuild",
                "server_behavior": (
                    "Server validates existing materials and consumes them "
                    "before attaching the requested section to the craft."
                ),
                "client_behavior": (
                    "Client sends craft section selection and displays "
                    "the newly attached module."
                ),
                "observable_result": (
                    "The spacecraft visibly gains a built craft section."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": ["Craft"],
            }]}

    model = CraftOnlyModel()
    with pytest.raises(DynamicDesignError, match="SOURCE_ACTION_COVERAGE"):
        RobloxDynamicArchitect(model, checkpoint_dir=tmp_path).design(
            source, research, [],
        )
    assert model.calls >= 1
    assert not research.get("architecture_subplans", [])
