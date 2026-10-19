"""RMM runs only executable validation and never claims unrun engine tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.roblox_toolchain import RobloxToolchainManager
from roblox_mod_ai.verification_selector import make_verification_report, SCHEMA


def _report(**kwargs):
    defaults = dict(
        source_only=False, addon_mode=False, tool_results={},
        analysis_passed=True, acceptance={"passed": True},
        artifact_ready=True,
    )
    defaults.update(kwargs)
    return make_verification_report(**defaults)


def test_colab_style_environment_never_reports_unexecuted_studio_success():
    report = _report(tool_results={
        "stylua": {"executed": True, "success": True},
        "selene": {"executed": True, "success": True},
        "luau_analyze": {"executed": False, "message": "luau-analyze missing"},
        "lune_economy_applicable": True,
        "lune_economy": {"executed": False, "status": "not_run",
                         "reason": "Lune is not installed"},
        "rojo": {"executed": True, "success": True},
        "compiled_structure": {"passed": True},
        "local_studio_kit": {"executed": False, "passed": True},
    })
    assert report["schema"] == SCHEMA
    assert report["checks"]["stylua"]["status"] == "passed"
    assert report["checks"]["lune_economy"]["status"] == "not_run"
    assert report["checks"]["studio_structure"]["status"] == "not_run"
    assert report["checks"]["studio_multiplayer"]["status"] == "not_run"
    assert report["checks"]["datastore_rejoin"]["status"] == "not_run"
    assert report["checks"]["compiled_structure"]["status"] == "passed"
    assert report["gameplay_verified"] is False
    assert report["studio_executed"] is False


def test_source_only_or_addon_never_pretends_to_have_compiled_place():
    for flags in ({"source_only": True, "addon_mode": False},
                  {"source_only": False, "addon_mode": True}):
        report = _report(**flags)
        assert report["checks"]["rojo_build"]["status"] == "not_applicable"
        assert report["checks"]["compiled_structure"]["status"] == "not_applicable"
        assert report["checks"]["studio_multiplayer"]["status"] == "not_run"


def test_executable_optional_unit_failure_is_reported_not_silently_ignored():
    report = _report(tool_results={
        "lune_economy_applicable": True,
        "lune_economy": {"executed": True, "success": False, "status": "failed",
                         "error": "EconomyRules test failed"},
    }, artifact_ready=False)
    assert report["checks"]["lune_economy"]["status"] == "failed"
    assert report["checks"]["artifact"]["status"] == "failed"
    assert report["gameplay_verified"] is False


def test_lune_case_is_generated_only_if_this_project_has_economy_rules(tmp_path):
    assert RobloxToolchainManager.stage_lune_economy_test(tmp_path) is None
    src = tmp_path / "src" / "shared" / "EconomyRules.luau"
    src.parent.mkdir(parents=True)
    src.write_text("return {canAfford = function() return true end}\n", encoding="utf-8")
    path = RobloxToolchainManager.stage_lune_economy_test(tmp_path)
    assert path is not None and path.is_file()
    content = path.read_text(encoding="utf-8")
    assert 'require("../src/shared/EconomyRules")' in content
    assert "RMM_LUNE_ECONOMY_PASS" in content


def test_lune_is_selected_only_with_binary_and_test_file(tmp_path, monkeypatch):
    # This test never needs an installed Lune. Simulate binary discovery and
    # a real process result, verifying the precise subprocess command.
    from roblox_mod_ai import roblox_toolchain
    case = tmp_path / "tests" / "economy_contract.luau"
    case.parent.mkdir()
    case.write_text('print("RMM_LUNE_ECONOMY_PASS")\n', encoding="utf-8")
    manager = RobloxToolchainManager()
    real_which = roblox_toolchain.shutil.which
    monkeypatch.setattr(roblox_toolchain.shutil, "which",
                        lambda name: "/mock/lune" if name == "lune" else real_which(name))
    observed = []
    def fake_run(argv, **kwargs):
        observed.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="RMM_LUNE_ECONOMY_PASS\n", stderr="")
    monkeypatch.setattr(roblox_toolchain.subprocess, "run", fake_run)
    passed = manager.run_lune_economy_test(tmp_path)
    assert passed["executed"] and passed["success"] and passed["status"] == "passed"
    assert observed[0][0] == ["/mock/lune", "run", str(case)]
    monkeypatch.setattr(roblox_toolchain.shutil, "which",
                        lambda name: None if name == "lune" else real_which(name))
    skipped = manager.run_lune_economy_test(tmp_path)
    assert skipped["executed"] is False and skipped["status"] == "not_run"
