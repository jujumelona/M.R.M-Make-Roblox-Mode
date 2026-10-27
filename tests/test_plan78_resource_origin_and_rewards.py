"""Production failure report regression for source-authoritative resource origins.

The model's 2026-10-27 scoped architecture had four systems, including a
"ResourceGather" that grants a quantity out of nowhere and a "save_money"
that adds a player-requested amount under a daily cap. Normalizing their
pseudo-Parts is necessary but must not certify fake gameplay as complete.
"""
from roblox_mod_ai.semantic_preservation import source_intent_conflicts


ORIGINAL = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)

MODEL_FARM = "Server grants resources to the player for resource-gathering."
MODEL_MONEY = (
    "Validate the request as a server-owned action, then add the requested "
    "amount to the player's authoritative owned balance and persist it. "
    "Reject requests with a non-positive amount, an amount exceeding the "
    "configured daily cap, or any request that fails validation."
)
MODEL_TRADE = (
    "Server trades owned resources at an approved market: deduct owned "
    "resource inventory, then credit exact server-priced money."
)
MODEL_SHIP = (
    "Server assembles ship parts, creates a component attachment and "
    "updates the installed ship section."
)


def test_actual_model_cannot_grant_resources_without_gatherable_world_source():
    result = source_intent_conflicts(
        ORIGINAL, " ".join((MODEL_FARM, MODEL_TRADE, MODEL_SHIP))
    )
    assert any("RESOURCE_GATHER_SOURCE_UNBOUND" in problem for problem in result)


def test_requested_amount_daily_cap_is_not_an_authorized_income_source():
    result = source_intent_conflicts(
        ORIGINAL, " ".join((MODEL_FARM, MODEL_MONEY, MODEL_TRADE, MODEL_SHIP))
    )
    assert any("SOURCE_UNBACKED_EARNING_AMOUNT" in problem for problem in result)


def test_real_world_mining_and_server_priced_trade_are_still_eligible():
    real = (
        "Server mines resource ore nodes in the world after validating "
        "player proximity and node availability, depletes the node, and "
        "credits ore inventory. Server trades owned resources at an approved "
        "market: deducts the owned resource quantity and credits exact "
        "server-priced money. Server assembles owned ship sections and "
        "attaches their parts to the ship hull."
    )
    result = source_intent_conflicts(ORIGINAL, real)
    assert not any(item.startswith((
        "RESOURCE_GATHER_SOURCE_UNBOUND",
        "RESOURCE_GATHER_ACTION_MISSING",
        "SOURCE_UNBACKED_EARNING_AMOUNT",
    )) for item in result)


def test_source_classifier_does_not_require_implementation_from_intent_label():
    result = source_intent_conflicts(
        ORIGINAL, "resource farming, currency earning, trading and ship part build",
        require_implementation=False,
    )
    assert not any(item.startswith((
        "RESOURCE_GATHER_SOURCE_UNBOUND",
        "SOURCE_UNBACKED_EARNING_AMOUNT",
    )) for item in result)
