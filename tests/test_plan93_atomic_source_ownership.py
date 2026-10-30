"""Plan 93 source ownership and no fabrication regression."""
from roblox_mod_ai.atomic_action_quotes import eligible_atomic_action_spans, verify_or_bind_actions
from roblox_mod_ai.source_owned_microplanning import (
    _realign_misattributed_source_effects, _coverage_issues, complete_source_owned_actions,
)

SOURCE = "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 부위마다 만들어서 만들수있고"
WEAK = "Server grants resources to the player for resource-gathering."
TRADE = ("Server trades collected resources for money at a server-priced market: "
         "it deducts owned resource inventory and credits earned currency to the same player's balance.")
HARVEST = ("Server performs a server-owned mining/harvesting effect on a real resource "
           "source, granting resources to the player's owned inventory.")
BUILD = ("Server attaches a player-owned ship part to the server-owned ship assembly, "
         "marking the part as built and updating the ship's owned component inventory.")


class NoCalls:
    def complete_json(self, *a, **k):
        raise AssertionError("A verified move must not need another model response")


def rows(pairs):
    ids = {span["quote"]: span["id"] for span in eligible_atomic_action_spans(SOURCE)}
    return [{"source_id": ids[quote], "action": action} for quote, action in pairs]


def sample():
    return rows([("자원파밍", WEAK), ("돈모으기 거래", TRADE),
                 ("부위마다", HARVEST), ("우주선을 부위마다", BUILD)])


def test_reassign_existing_effect_without_adding_any_new_gameplay():
    fixed = _realign_misattributed_source_effects(NoCalls(), SOURCE, sample(), max_actions=6)
    verified = verify_or_bind_actions(NoCalls(), SOURCE, fixed, max_actions=6)
    assert len(verified) == 3
    assert {(x["source_quote"], x["action"]) for x in verified} == {
        ("자원파밍", HARVEST), ("돈모으기 거래", TRADE), ("우주선을 부위마다", BUILD)
    }
    assert _coverage_issues(SOURCE, verified) == []


def test_end_to_end_microplanning_avoids_truncated_wrong_grant_loop():
    accepted = complete_source_owned_actions(NoCalls(), SOURCE, initial_actions=sample())
    assert len(accepted) == 3
    assert accepted[0]["action"] == HARVEST


def test_no_harvest_created_when_missing_from_model_output():
    source_rows = rows([("자원파밍", WEAK), ("돈모으기 거래", TRADE),
                        ("우주선을 부위마다", BUILD)])
    assert _realign_misattributed_source_effects(
        NoCalls(), SOURCE, source_rows, max_actions=6
    ) == source_rows
    bound = verify_or_bind_actions(NoCalls(), SOURCE, source_rows,
                                   require_complete=False, max_actions=6)
    # Either absence of a harvest effect OR absence of a grounded physical
    # origin is a blocking failure. A phrase like "resource-gathering"
    # can reach the stronger SOURCE_UNBOUND diagnostic.
    assert any(x.startswith(("RESOURCE_GATHER_ACTION_MISSING:",
                             "RESOURCE_GATHER_SOURCE_UNBOUND:"))
               for x in _coverage_issues(SOURCE, bound))


def test_do_not_steal_from_another_valid_source_mining_owner():
    source_rows = rows([("자원파밍", WEAK), ("돈모으기 거래", TRADE),
                        ("자원파밍 돈모으기", HARVEST),
                        ("우주선을 부위마다", BUILD)])
    assert _realign_misattributed_source_effects(
        NoCalls(), SOURCE, source_rows, max_actions=6
    ) == source_rows
