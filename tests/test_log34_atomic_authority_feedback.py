"""Log34: compact/atomic LLM path must RECEIVE authority replan evidence."""
import json

from roblox_mod_ai.compact_atomic_authoring import author_compact_atomic_system


class CapturingPlanner:
    def __init__(self):
        self.prompts = []

    def complete_json(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if len(self.prompts) % 2 == 1:
            return {
                "name": "ClaimOutpost",
                "server_behavior": (
                    "The server validates the arrival and that the player "
                    "is authorized for the planet, then writes the ownership "
                    "record to authoritative saved state, rejecting duplicates."
                ),
                "world_entities": ["OutpostPlanet"],
            }
        return {"observable_result": (
            "The planet ownership state is saved and the outpost appears "
            "to the authorized colonizing player."
        )}


def test_log34_authority_diagnostics_reach_actual_compact_model_call():
    planner = CapturingPlanner()
    action = {"source_quote": "식민지화", "action": (
        "Colonize a visited planet and persist its true server-owned owner"
    )}
    gaps = [{
        "source_module": "ColonizePlanet77D3DB2Server",
        "error": "AUTHORITY_PRODUCER_NOT_DECLARED",
        "observed": {"transport_only": True, "state_changes": 0},
        "missing_contract": "A real planet ownership producer is required",
    }]
    result = author_compact_atomic_system(
        planner, action, previous_issues={}, authority_gaps=gaps,
    )
    assert result["name"] == "ClaimOutpost"
    assert len(planner.prompts) == 2
    payload = json.loads(planner.prompts[0].split("\n")[-1])
    assert payload["source_quote"] == action["source_quote"]
    assert payload["authority_replan_observations"] == gaps
    assert "AUTHORITY_PRODUCER_NOT_DECLARED" in planner.prompts[0]
    # These observations never become a forged authoritative effect claim.
    assert result["world_entities"] == ["OutpostPlanet"]


def test_log34_unrelated_atomic_action_does_not_receive_authority_gaps():
    planner = CapturingPlanner()
    action = {"source_quote": "자원 채굴", "action": "Mine a resource"}
    author_compact_atomic_system(
        planner, action, previous_issues={}, authority_gaps=[],
    )
    assert json.loads(planner.prompts[0].split("\n")[-1])[
        "authority_replan_observations"] == []
