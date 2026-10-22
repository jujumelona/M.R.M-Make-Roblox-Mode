"""Small-model failures must not erase already-good semantics in other fields."""
from copy import deepcopy

import pytest

from roblox_mod_ai.dynamic_architect import (
    RobloxDynamicArchitect, _SCOPED_SEMANTIC_REPAIR_SCHEMA,
)


PROMPT = "Fight alien enemies and colonize planets"
SOURCE = "Fight alien enemies and colonize planets"
SERVER_GOOD = (
    "The server validates attacks against hostile alien NPC enemies and "
    "applies enemy health damage. After successful colonization, it "
    "records the planet's owned persistent colony settlement state."
)
CLIENT_GOOD = (
    "The client renders server-confirmed alien enemy combat results, "
    "and displays the planet's colonization status after an action."
)
RESULT_GOOD = (
    "The player sees alien enemies take damage, and the planet becomes "
    "colonized with an established settlement after a valid request."
)


def _research():
    return {"ledger": {
        "original_prompt": PROMPT,
        "requirements": [
            {"id": "req-001", "statement": SOURCE, "source": "user_prompt"}
        ],
        "facets": [{
            "id": "intent-npc-colony", "requirements": ["req-001"],
            "source_span": SOURCE, "search_query": "Roblox NPC colony ownership",
        }],
    }, "evidence": []}


@pytest.mark.parametrize("failed_field,first,replacement", [
    ("observable_result",
     "The client shows alien combat feedback and a generic colony menu.",
     RESULT_GOOD),
    ("server_behavior",
     "The server validates each alien enemy combat hit and shows "
     "the current planet colony screen after client selection.",
     SERVER_GOOD),
])
def test_field_repair_preserves_correct_server_or_outcome(
        monkeypatch, failed_field, first, replacement):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")

    original = {"systems": [{
        "name": "AlienSettlement",
        "server_behavior": SERVER_GOOD,
        "client_behavior": CLIENT_GOOD,
        "observable_result": RESULT_GOOD,
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }]}
    original["systems"][0][failed_field] = first

    class MiniModel:
        def __init__(self):
            self.calls = []

        def complete_json(self, request, **options):
            self.calls.append((request, options))
            if len(self.calls) == 1:
                return deepcopy(original)
            assert len(self.calls) == 2, "Never regenerate the whole feature"
            assert options["json_schema"] == _SCOPED_SEMANTIC_REPAIR_SCHEMA
            assert '"field": "' + failed_field + '"' in request
            return {"replacement": replacement}

    model = MiniModel()
    audit = _research()
    final = RobloxDynamicArchitect(model).design(PROMPT, audit, [])
    assert len(model.calls) == 2
    assert len(final["modules"]) == 2
    servers = [m for m in final["modules"] if "Server" in m.name]
    assert len(servers) == 1
    assert (SERVER_GOOD if failed_field == "observable_result" else replacement) \
           in servers[0].description
    assert RESULT_GOOD in final["acceptance"]["req-001"]
    assert [row["passed"] for row in audit["architecture_attempts"]] == [
        False, True
    ]



def test_real_failure_47_colony_delta_cannot_erase_existing_alien_combat(
        monkeypatch):
    """The original successful NPC hit logic must survive a colony-only patch.

    In plan_failure_logs (7), the old replacement policy dropped alien combat
    on both retry 2 and retry 3 even though the initial JSON had working
    server-owned alien damage and weapon validation.
    """
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    initial_server = (
        "The server runs a space-mode gameplay loop where players fight aliens "
        "and colonize planets. The server owns all combat resolution, planet "
        "colonization state, and progression validation. When a player "
        "activates a combat action, the server validates the player's weapon "
        "and target, applies damage to the alien, and resolves the outcome. "
        "When a player activates a colonization action, the server validates "
        "the player's settlement progress and applies the colonization result. "
        "The server tracks player-owned resources, earned game currency, and "
        "progression state."
    )
    delta = (
        "The server records a colony as established only when the player's "
        "settlement progress reaches the required completion threshold, then "
        "transitions the colony from a label to an established colony state "
        "and confirms the settlement outcome to the player."
    )
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append((prompt, options))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "AlienColonization",
                    "server_behavior": initial_server,
                    "client_behavior": (
                        "The client displays alien combat results and confirmed "
                        "changes to colonization progress after server actions."
                    ),
                    "observable_result": (
                        "The player sees alien enemies taking damage and the "
                        "planet becomes colonized after a successful mission."
                    ),
                    "interaction": "request_response", "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert len(self.calls) == 2
            assert options["json_schema"] == _SCOPED_SEMANTIC_REPAIR_SCHEMA
            assert "server_behavior" in prompt
            return {"replacement": delta}
    model = Model()
    report = _research()
    result = RobloxDynamicArchitect(model).design(PROMPT, report, [])
    server = next(m for m in result["modules"] if "Server" in m.name)
    assert "applies damage to the alien" in server.description
    assert "validates the player's weapon" in server.description
    assert "records a colony as established" in server.description
    assert len(model.calls) == 2
    assert [row["passed"] for row in report["architecture_attempts"]] == [
        False, True
    ]


def test_semantic_repair_cannot_accept_an_unrelated_new_feature(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    class Model:
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **options):
            self.calls += 1
            if self.calls == 1:
                return {"systems": [{
                    "name": "Settlement",
                    "server_behavior": (
                        "The server validates an alien NPC combat hit and "
                        "opens the selected planet colonization menu."
                    ),
                    "client_behavior": (
                        "The client displays alien combat results and "
                        "shows the colony status panel after requests."
                    ),
                    "observable_result": RESULT_GOOD,
                    "interaction": "request_response", "input_mode": "custom",
                    "world_entities": [],
                }]}
            return {"replacement": (
                "The game displays a victory animation after trading Robux "
                "with other players without needing to persist a settlement."
            )}
    from roblox_mod_ai.dynamic_architect import DynamicDesignError
    model = Model()
    with pytest.raises(DynamicDesignError):
        RobloxDynamicArchitect(model).design(PROMPT, _research(), [])

def test_multi_contract_repair_preserves_enemy_combat_and_commits_colony(monkeypatch):
    """Reproduce the plan-49 case: colony write and visible outcome fail together."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    class SmallPlanner:
        def __init__(self):
            self.calls = []

        def complete_json(self, request, **options):
            self.calls.append((request, options))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "CombatAndSettlement",
                    "server_behavior": (
                        "The server validates attacks against hostile alien NPC "
                        "enemies and applies weapon damage to their health. "
                        "For colonization it checks player resources and "
                        "the selected planet's existing state."
                    ),
                    "client_behavior": (
                        "The player sees combat feedback and colony feedback "
                        "after submitting the chosen action."
                    ),
                    "interaction": "request_response",
                    "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert len(self.calls) == 2, "Both deficits must be repaired together"
            from roblox_mod_ai.dynamic_architect import (
                _SCOPED_DUAL_SEMANTIC_REPAIR_SCHEMA,
            )
            assert options["json_schema"] == _SCOPED_DUAL_SEMANTIC_REPAIR_SCHEMA
            assert '"server_behavior"' in request
            assert '"observable_result"' in request
            return {
                "server_addition": (
                    "After successful colonization the server records a newly "
                    "established colony settlement and persists ownership "
                    "of the chosen planet in the player profile."
                ),
                "outcome_addition": (
                    "Hostile alien NPC enemies visibly lose health from "
                    "successful attacks, and the planet becomes colonized "
                    "with an established owned settlement in the world."
                ),
            }

    research = _research()
    model = SmallPlanner()
    result = RobloxDynamicArchitect(model).design(PROMPT, research, [])
    assert len(model.calls) == 2
    assert [attempt["passed"] for attempt in
            research["architecture_attempts"]] == [False, True]
    server = next(m for m in result["modules"] if m.name.endswith("Server"))
    assert "applies weapon damage" in server.description
    assert "records a newly established colony settlement" in server.description
    visible = result["acceptance"]["req-001"]
    assert "Hostile alien NPC enemies visibly lose health" in visible
    assert "planet becomes colonized" in visible

def test_plan50_wrong_ship_upgrade_replanned_as_actual_space_departure(monkeypatch):
    """A wrong action needs a small fresh system, not a prose append or
    another long 1,400-token generation that can truncate.
    """
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    prompt = "그렇게해서 우주로 나갈수있고"
    research = {"ledger": {
        "original_prompt": prompt,
        "requirements": [{"id": "req-007", "statement": prompt,
                          "source": "user_prompt"}],
        "facets": [{"id": "intent-launch", "requirements": ["req-007"],
                    "source_span": prompt,
                    "search_query": "Roblox launch built ship into space"}],
    }, "evidence": []}

    class SmallModel:
        def __init__(self):
            self.calls = []
        def complete_json(self, request, **options):
            self.calls.append((request, options))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "ShipUpgradeMenu",
                    "server_behavior": (
                        "The server validates the ship's parts and charges "
                        "currency for upgrading each installed module."
                    ),
                    "client_behavior": (
                        "The client shows upgrade and purchase buttons "
                        "and confirms selected ship modifications."
                    ),
                    "interaction": "request_response",
                    "input_mode": "custom",
                    "observable_result": (
                        "The player sees an upgraded ship part and new "
                        "configuration options available on screen."
                    ),
                    "world_entities": [],
                }]}
            assert len(self.calls) == 2
            assert options["max_tokens"] <= 1024
            assert "missing_obligations" in request
            assert "source_requirements" in request
            assert len(request) < 1400
            return {"systems": [{
                "name": "ShipLaunch",
                "server_behavior": (
                    "The server checks that the spacecraft is assembled and "
                    "powered, validates the requested departure, records "
                    "the ship entering space and moves the player into "
                    "the playable space region."
                ),
                "client_behavior": (
                    "The client offers a launch control and then shows "
                    "the ship traveling into space on success."
                ),
                "observable_result": (
                    "The spacecraft launches into space, and the player "
                    "arrives in the orbital exploration region."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": [],
            }]}
    model = SmallModel()
    result = RobloxDynamicArchitect(model).design(prompt, research, [])
    assert len(model.calls) == 2
    assert "launch" in result["acceptance"]["req-007"].lower()
    assert all("charge" not in m.description.lower()
               for m in result["modules"])


def test_semantic_repair_accepts_field_named_output_from_small_model(monkeypatch):
    """Plan 50's schema-key mismatch must not drop a valid semantic delta."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    class Model:
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **options):
            self.calls += 1
            if self.calls == 1:
                return {"systems": [{
                    "name": "AlienColony",
                    "server_behavior": (
                        "The server validates alien combat hits and damages "
                        "hostile alien NPC enemies, and checks the selected "
                        "planet before colonization."
                    ),
                    "client_behavior": CLIENT_GOOD,
                    "observable_result": RESULT_GOOD,
                    "interaction": "request_response",
                    "input_mode": "custom",
                    "world_entities": [],
                }]}
            return {"server_behavior": (
                "The server persists a newly established planet colony "
                "settlement with player ownership on successful colonization."
            )}
    model = Model()
    result = RobloxDynamicArchitect(model).design(PROMPT, _research(), [])
    assert model.calls == 2
    assert any("newly established planet colony" in m.description
               for m in result["modules"])


def test_semantic_repair_bad_shape_retries_same_small_patch(monkeypatch):
    """Malformed repair outputs preserve the valid draft and patch budget."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append((prompt, options))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "AlienColony",
                    "server_behavior": (
                        "The server validates alien NPC attacks and applies "
                        "damage to hostile enemies, and checks colony "
                        "prerequisites without changing planet ownership."
                    ),
                    "client_behavior": CLIENT_GOOD,
                    "observable_result": RESULT_GOOD,
                    "interaction": "request_response",
                    "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert options["json_schema"] == _SCOPED_SEMANTIC_REPAIR_SCHEMA
            if len(self.calls) == 2:
                return {"unrelated": "Wrong key"}
            return {"replacement": (
                "The server saves the newly established owned planet "
                "colony settlement after validated colonization."
            )}
    model = Model()
    result = RobloxDynamicArchitect(model).design(PROMPT, _research(), [])
    assert len(model.calls) == 3
    assert [a["passed"] for a in _research()["ledger"].get(
        "architecture_attempts", [])] == []
    assert any("newly established owned planet" in m.description
               for m in result["modules"])

def test_compact_replan_truncation_retries_compact_not_original(monkeypatch):
    """A truncated scoped replan must not restart the large first-call prompt."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Ship can launch into space"
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-launch", "statement": source}],
        "facets": [{"id": "intent-launch", "requirements": ["req-launch"],
                    "source_span": source,
                    "search_query": "Roblox launch and enter space"}],
    }, "evidence": []}
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "UpgradeShip",
                    "server_behavior": (
                        "The server charges credits to upgrade ship modules "
                        "and records the expanded module inventory."
                    ),
                    "client_behavior": (
                        "The UI shows ship upgrades and purchases and "
                        "confirms completed modifications."
                    ),
                    "observable_result": (
                        "The player sees purchased module upgrades and "
                        "the changed ship configuration."
                    ),
                    "interaction": "request_response",
                    "world_entities": [],
                }]}
            assert "missing_obligations" in prompt
            assert kwargs["max_tokens"] <= 1024
            if len(self.calls) == 2:
                raise ValueError(
                    "Model JSON completion truncated (finish_reason=length)"
                )
            return {"systems": [{
                "name": "SpaceLaunch",
                "server_behavior": (
                    "The server verifies ship readiness, then launches "
                    "the spacecraft into space and records its departure."
                ),
                "client_behavior": (
                    "The client shows a launch button and updates "
                    "the space flight HUD after confirmed departure."
                ),
                "observable_result": (
                    "The spacecraft launches into space and the player "
                    "sees the orbital flight location."
                ),
                "interaction": "request_response",
                "world_entities": [],
            }]}
    model = Model()
    result = RobloxDynamicArchitect(model).design(source, research, [])
    assert len(model.calls) == 3
    assert all("missing_obligations" in request
               for request, _ in model.calls[1:])
    assert "space" in result["acceptance"]["req-launch"].lower()

def test_official_doc_handoff_excludes_unrelated_space_tutorials(monkeypatch):
    """Only source-relevant evidence should steer the small design model."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Ship can launch into space"
    facet = "intent-space"
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-space", "statement": source}],
        "facets": [{"id": facet, "requirements": ["req-space"],
                    "source_span": source,
                    "search_query": "Roblox launch a ship and travel into space"}],
    }, "evidence": [
        {"facet": facet, "provider": "official_docs",
         "grounding": "fetched_official_document",
         "url": "https://create.roblox.com/docs/tutorials/grouping-the-parts.md",
         "excerpt": "Group the parts together into one vehicle model."},
        {"facet": facet, "provider": "official_docs",
         "grounding": "fetched_official_document",
         "url": "https://create.roblox.com/docs/tutorials/space-launch.md",
         "excerpt": "Ship launch travel into space requires a ready spacecraft."},
    ]}
    class Model:
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            assert "Group the parts" not in prompt
            assert "space-launch.md" in prompt
            return {"systems": [{
                "name": "SpaceLaunch",
                "server_behavior": (
                    "The server validates that the ship can launch and "
                    "records the ship entering the playable space region."
                ),
                "client_behavior": (
                    "The client displays the launch action and shows "
                    "the confirmed travel into space."
                ),
                "observable_result": (
                    "The ship launches into space and arrives in orbit."
                ),
                "interaction": "request_response",
                "world_entities": [],
            }]}
    model = Model()
    result = RobloxDynamicArchitect(model).design(source, research, [])
    assert model.calls == 1
    assert result["modules"]

def test_generic_replan_for_missing_settlement_action(monkeypatch):
    """The recovery decision must not depend on a launch-specific error code."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Colonize a planet after exploration"
    audit = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-settlement", "statement": source}],
        "facets": [{"id": "intent-settlement",
                    "requirements": ["req-settlement"],
                    "source_span": source,
                    "search_query": "Roblox establish and own a planet colony"}],
    }, "evidence": []}
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "CreatureHunter",
                    "server_behavior": (
                        "The server validates the selected enemy and applies "
                        "damage to a hostile NPC monster on the planet."
                    ),
                    "client_behavior": (
                        "The client offers creature combat controls and "
                        "shows damage caused to the monster."
                    ),
                    "observable_result": (
                        "The monster loses hit points and can be defeated "
                        "for an ordinary combat reward."
                    ),
                    "interaction": "request_response",
                    "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert len(self.calls) == 2
            assert "missing_obligations" in prompt
            assert kwargs["max_tokens"] <= 1024
            return {"systems": [{
                "name": "ColonyEstablishment",
                "server_behavior": (
                    "The server validates settlement requirements and "
                    "records a newly established planet colony owned by "
                    "the player in persistent world state."
                ),
                "client_behavior": (
                    "The client shows the settlement request and confirms "
                    "the newly owned planet territory."
                ),
                "observable_result": (
                    "The planet becomes colonized and the player sees the "
                    "new colony ownership state."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": [],
            }]}
    model = Model()
    result = RobloxDynamicArchitect(model).design(source, audit, [])
    assert len(model.calls) == 2
    assert all("damages" not in m.description
               for m in result["modules"])
    assert any("newly established planet colony" in m.description
               for m in result["modules"])


def test_generic_semantic_replan_must_allow_multiple_independent_actions(
        monkeypatch):
    """Source obligations, not the old 'exactly one' recovery prompt, set size."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Fight alien enemies and colonize planets"
    audit = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-both", "statement": source}],
        "facets": [{"id": "intent-both", "requirements": ["req-both"],
                    "source_span": source,
                    "search_query": "Roblox fight alien enemies and colonize planets"}],
    }, "evidence": []}
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "DecorationCreator",
                    "server_behavior": (
                        "The server validates cosmetic color selection and "
                        "saves the purchased decoration in inventory."
                    ),
                    "client_behavior": (
                        "The client offers decoration buttons and "
                        "displays the purchased decorative object."
                    ),
                    "observable_result": (
                        "The player receives a decorative inventory skin."
                    ),
                    "interaction": "request_response",
                    "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert len(self.calls) == 2
            assert "one system per independently triggered" in prompt
            return {"systems": [{
                "name": "AlienCombat",
                "server_behavior": (
                    "The server validates weapon range and attacks a hostile "
                    "alien NPC enemy, applies damage to its health, "
                    "and records defeat."
                ),
                "client_behavior": (
                    "The player aims and attacks a hostile alien enemy; "
                    "the target's remaining health is displayed."
                ),
                "observable_result": (
                    "The hostile alien enemy loses health and can be "
                    "defeated by the player's weapon."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": [],
            }, {
                "name": "PlanetColonization",
                "server_behavior": (
                    "The server validates settlement supplies, establishes "
                    "a new planet colony and records the settlement ownership."
                ),
                "client_behavior": (
                    "The player requests colonization and receives the "
                    "newly established settlement ownership status."
                ),
                "observable_result": (
                    "The planet becomes colonized and the player can see "
                    "its new colony state."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": [],
            }]}
    model = Model()
    result = RobloxDynamicArchitect(model).design(source, audit, [])
    assert len(model.calls) == 2
    assert len(result["modules"]) >= 4
    assert all("Decoration" not in m.name for m in result["modules"])

def test_general_source_fidelity_review_repairs_unseen_gardening_mechanic(
        monkeypatch):
    """Unknown game domains must not be accepted merely because regexes do not know them."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_SOURCE_FIDELITY_AUDIT", "1")
    source = "Plant seeds and water the growing garden"
    audit = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-garden", "statement": source}],
        "facets": [{"id": "intent-garden", "requirements": ["req-garden"],
                    "source_span": source,
                    "search_query": "Roblox plant seeds and water garden to grow plants"}],
    }, "evidence": []}
    bad = {"systems": [{
        "name": "GardenDecorationShop",
        "server_behavior": (
            "The server charges currency for decoration skins and stores "
            "the purchased decorations in the player's inventory."
        ),
        "client_behavior": (
            "The client opens a cosmetics catalog and shows purchased items."
        ),
        "observable_result": (
            "The player receives a purchased decoration for the garden."
        ),
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }]}
    good = {"systems": [{
        "name": "SeedPlanting",
        "server_behavior": (
            "The server validates the selected plot, plants the seed "
            "in the garden soil and saves its growth state."
        ),
        "client_behavior": (
            "The player selects a seed and a target plot and requests "
            "planting from the server."
        ),
        "observable_result": (
            "The player sees the seed planted in the soil plot."
        ),
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }, {
        "name": "GardenWatering",
        "server_behavior": (
            "The server validates water availability, waters the garden "
            "plant and increases its saved growth progress."
        ),
        "client_behavior": (
            "The player chooses a planted plot and requests watering."
        ),
        "observable_result": (
            "The planted seed visibly grows after being watered."
        ),
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }]}
    class Model:
        supports_source_fidelity_audit = True

        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append((prompt, options))
            if len(self.calls) == 1:
                return deepcopy(bad)
            if len(self.calls) == 2:
                assert options["max_tokens"] <= 360
                assert "source_requirement" in prompt
                return {"covered": False, "server_quote": "",
                        "outcome_quote": "",
                        "missing": "Plant and water seeds, not buy garden decorations"}
            if len(self.calls) == 3:
                assert "missing_obligations" in prompt
                return deepcopy(good)
            assert len(self.calls) == 4
            assert options["max_tokens"] <= 360
            return {"covered": True,
                    "server_quote": "plants the seed in the garden soil",
                    "outcome_quote": "The planted seed visibly grows",
                    "missing": ""}
    model = Model()
    result = RobloxDynamicArchitect(model).design(source, audit, [])
    assert len(model.calls) == 4
    assert any("plants the seed" in m.description for m in result["modules"])
    assert any("waters the garden" in m.description for m in result["modules"])
    assert not any("decoration skins" in m.description for m in result["modules"])


def test_source_fidelity_rejects_unsupported_model_self_certification():
    from roblox_mod_ai.dynamic_architect import _ground_source_fidelity_review
    server = "The server updates a catalog of cosmetic items and prices."
    visible = "The player sees a purchased cosmetic item on screen."
    assert "Unsupported server_quote" in _ground_source_fidelity_review(
        {"covered": True,
         "server_quote": "server plants and waters a garden plot",
         "outcome_quote": "purchased cosmetic item",
         "missing": ""},
        server, visible)
    assert "Unimplemented source action" in _ground_source_fidelity_review(
        {"covered": False, "missing": "growing plants",
         "server_quote": "", "outcome_quote": ""},
        server, visible)
