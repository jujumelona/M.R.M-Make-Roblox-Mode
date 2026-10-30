"""Plan94: semantic acceptance must preserve authored effects, never codegen proof."""
from roblox_mod_ai.semantic_preservation import source_intent_conflicts
from roblox_mod_ai.grounded_atomic_source_effects import preserved_world_inventory_extraction

SOURCE = "자원파밍"
PROMPT = "자원파밍 돈모으기 거래 등으로 우주선을 부위마다 만들어서 만들수있고"
EXTRACTION = (
    "Server performs a server-owned mining/harvesting effect on a real resource "
    "source, granting resources to the player's owned inventory."
)
ASSEMBLY = (
    "Validate the requested component name against a server-owned registry "
    "of ship components and the player's owned spaceship instance. "
    "On success, mutate server-owned ship component state and attach "
    "the component to the player's owned spaceship at a server-chosen "
    "position and orientation. Reject unknown parts."
)


def test_plan94_authored_extraction_is_preserved_not_reamplified():
    value = preserved_world_inventory_extraction(
        {"source_quote": SOURCE, "action": EXTRACTION},
        original_prompt=PROMPT,
    )
    assert value is not None
    assert value["world_entities"] == []  # source semantics, NOT physical proof
    assert EXTRACTION in value["server_behavior"]
    assert source_intent_conflicts(SOURCE, value["server_behavior"]) == []


def test_plan94_genuine_component_installation_is_not_a_missing_build():
    source = "우주선을 부위마다 만들어서 만들수있고"
    assert source_intent_conflicts(source, ASSEMBLY) == []


def test_catalog_without_attachment_still_fails_build():
    source = "우주선을 부위마다 만들어서 만들수있고"
    only_catalog = (
        "The server checks a spaceship component catalog and purchases "
        "a component but does not install or attach anything to the ship."
    )
    assert any("SOURCE_SECTION_BUILD_MISSING" in issue
               for issue in source_intent_conflicts(source, only_catalog))


def test_grant_without_world_harvest_still_fails():
    action = "Server grants resources to the player's inventory for resource-gathering."
    assert preserved_world_inventory_extraction(
        {"source_quote": SOURCE, "action": action}, original_prompt=PROMPT,
    ) is None


def test_unsupported_unowned_physical_source_remains_unverified():
    action = (
        "Server performs a mining/harvesting effect on a real resource source, "
        "granting resources to the player's owned inventory."
    )
    assert preserved_world_inventory_extraction(
        {"source_quote": SOURCE, "action": action}, original_prompt=PROMPT,
    ) is None
