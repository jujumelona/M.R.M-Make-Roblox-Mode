"""Regression: changing ANY host adapter invalidates resumable Luau.

Saved proposal.code and old checkpoint bytes cannot override host templates.
Model-owned modules retain resumability only under the exact source signature.
"""
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.generation_provenance import (
    generation_source_digests, host_source_must_regenerate,
)


def test_fingerprint_includes_new_and_modified_adapter(tmp_path: Path):
    root = tmp_path / "roblox_mod_ai"
    root.mkdir()
    (root / "code_generator.py").write_text("def generate(): pass\n")
    before = generation_source_digests(root)
    assert "code_generator.py" in before
    (root / "host_future_feature.py").write_text("RULE = 'first'\n")
    after_added = generation_source_digests(root)
    assert "host_future_feature.py" not in before
    assert "host_future_feature.py" in after_added
    (root / "host_future_feature.py").write_text("RULE = 'changed'\n")
    after_changed = generation_source_digests(root)
    assert after_changed != after_added
    # File creation order does not alter deterministic checkpoint signatures.
    assert list(after_changed) == sorted(after_changed)


def test_host_owned_regenerates_even_with_loaded_proposal_code():
    module = SimpleNamespace(module_id="dyn_model", name="AnyModule",
                             file_path="src/server/AnyModule.luau",
                             code="return { success = true }")
    for strategy in (
        "host_verified_template",
        "host_declarative_mode_unlock",
        "host_declarative_ship_sections",
        "host_declarative_general_upgrades",
        "host_ship_purchase_facade",
        "host_zero_argument_ui",
        "host_declarative_options",
    ):
        assert host_source_must_regenerate(module, strategy)
    for strategy in ("bounded_server_action", "bounded_client_ui",
                     "whole_file_model_legacy", "bounded_passive_start"):
        assert not host_source_must_regenerate(module, strategy)
    module.module_id = "mod_dynamic_server_bootstrap"
    assert host_source_must_regenerate(module, "builtin_source")
    module.module_id = "mod_player_data"
    module.file_path = "src/server/PlayerDataManager.luau"
    assert host_source_must_regenerate(module, "builtin_source")


def test_generate_all_replaces_stale_market_and_builder_luau():
    from roblox_mod_ai.code_generator import LuauCodeGenerator
    from test_host_ship_purchase_facade import _plan, DataOnly

    plan = _plan()
    stale = "--!strict\nlocal Stale = {}\nreturn Stale\n"
    for module in plan.modules:
        module.code = stale
    model = DataOnly()
    generator = LuauCodeGenerator(model)
    generator.generate_all_modules(plan)
    assert len(model.calls) == 1
    assert all(module.code != stale for module in plan.modules)
    assert 'builder.handleAction(player, services, "create"' in plan.modules[0].code
    assert 'coins.Value -= netCharge' in plan.modules[2].code
    assert 'remote:InvokeServer("buy", part.id)' in plan.modules[1].code



def test_imported_unsourced_dynamic_code_is_not_checkpoint_trusted(tmp_path: Path):
    import hashlib
    from roblox_mod_ai.generation_provenance import trusted_checkpoint_source

    path = tmp_path / "src" / "server" / "Action.luau"
    path.parent.mkdir(parents=True)
    source = "--!strict\nlocal Service = {}\nreturn Service\n"
    path.write_text(source, encoding="utf-8")
    current = "current-sources-and-plan"
    entry = {
        "input_sha256": current,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    assert trusted_checkpoint_source(path, entry, current) == source
    assert trusted_checkpoint_source(path, entry, current, source) == source
    assert trusted_checkpoint_source(path, entry, "changed-host-policy") is None
    assert trusted_checkpoint_source(path, entry, current,
                                     "return { forged = true }") is None
    path.write_text("return { tampered = true }", encoding="utf-8")
    assert trusted_checkpoint_source(path, entry, current) is None
