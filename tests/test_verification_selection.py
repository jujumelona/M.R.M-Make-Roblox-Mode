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
        "offline_test_count": 2,
        "lune_offline": {"executed": False, "status": "not_run",
                          "reason": "Lune is not installed"},
        "luau_compile": {"executed": False, "status": "not_run",
                         "reason": "luau-compile missing"},
        "rojo": {"executed": True, "success": True},
        "compiled_structure": {"passed": True},
        "local_studio_kit": {"executed": False, "passed": True},
    })
    assert report["schema"] == SCHEMA
    assert report["checks"]["stylua"]["status"] == "passed"
    assert report["checks"]["lune_offline"]["status"] == "not_run"
    assert report["checks"]["wally_dependencies"]["status"] == "not_run"
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
        "offline_test_count": 1,
        "lune_offline": {"executed": True, "success": False, "status": "failed",
                         "error": "Pure Luau test failed"},
    }, artifact_ready=False)
    assert report["checks"]["lune_offline"]["status"] == "failed"
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
    assert 'require("../../src/shared/EconomyRules")' in content
    assert "RMM_LUNE_ECONOMY_PASS" in content


def test_lune_is_selected_only_with_binary_and_test_file(tmp_path, monkeypatch):
    # This test never needs an installed Lune. Simulate binary discovery and
    # a real process result, verifying the precise subprocess command.
    from roblox_mod_ai import roblox_toolchain
    case = tmp_path / "tests" / "offline" / "economy_contract.luau"
    case.parent.mkdir(parents=True)
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


def test_builtin_game_does_not_try_network_dependency_install():
    report = _report(tool_results={
        "wally": {"executed": False, "status": "not_applicable",
                  "reason": "Built-in UI/storage requires no external Wally packages"},
    })
    assert report["checks"]["wally_dependencies"]["status"] == "not_applicable"
    assert report["checks"]["studio_multiplayer"]["status"] == "not_run"


def test_required_fusion_or_profilestore_wally_failure_is_not_suppressed():
    report = _report(tool_results={
        "wally": {"executed": True, "success": False, "error": "network failed"},
    }, artifact_ready=False)
    assert report["checks"]["wally_dependencies"]["status"] == "failed"
    assert report["checks"]["artifact"]["status"] == "failed"


def test_generic_lune_discovers_unrelated_genre_tests_without_prompt_flags(tmp_path, monkeypatch):
    from roblox_mod_ai import roblox_toolchain
    test_root = tmp_path / "tests"
    (test_root / "offline" / "physics").mkdir(parents=True)
    paths = [test_root / "offline" / "physics" / "gravity.luau",
             test_root / "pathfinding.offline.luau"]
    for path in paths:
        path.write_text('assert(1 + 1 == 2)\\n', encoding="utf-8")
    # Jest specs require the Roblox engine and must NOT be executed in Lune.
    (test_root / "abilities.spec.luau").write_text("game:GetService('Players')", encoding="utf-8")
    (test_root / "offline" / "physics" / "fake.lua").write_text("", encoding="utf-8")
    found = RobloxToolchainManager.discover_offline_tests(tmp_path)
    assert {p.relative_to(tmp_path).as_posix() for p in found} == {
        "tests/offline/physics/gravity.luau", "tests/pathfinding.offline.luau"
    }
    monkeypatch.setattr(roblox_toolchain.shutil, "which",
                        lambda name: "/test/lune" if name == "lune" else None)
    called = []
    def fake_run(cmd, **kw):
        called.append(cmd[-1])
        return SimpleNamespace(returncode=0, stdout="all passed", stderr="")
    monkeypatch.setattr(roblox_toolchain.subprocess, "run", fake_run)
    result = RobloxToolchainManager().run_lune_offline_suite(tmp_path)
    assert result["executed"] and result["success"]
    assert result["test_count"] == result["passed_count"] == 2
    assert set(called) == {str(p) for p in paths}


def test_generic_lune_exec_failure_is_never_relabelled_success(tmp_path, monkeypatch):
    from roblox_mod_ai import roblox_toolchain
    path = tmp_path / "tests" / "offline" / "unknown_gameplay.luau"
    path.parent.mkdir(parents=True)
    path.write_text("assert(false)\\n", encoding="utf-8")
    monkeypatch.setattr(roblox_toolchain.shutil, "which",
                        lambda name: "/mock/lune" if name == "lune" else None)
    monkeypatch.setattr(roblox_toolchain.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="assertion failed"))
    result = RobloxToolchainManager().run_lune_offline_suite(tmp_path)
    assert result["executed"] and not result["success"]
    assert result["tests"][0]["status"] == "failed"


def test_official_luau_parser_optional_and_fails_closed_on_real_error(tmp_path, monkeypatch):
    from roblox_mod_ai import roblox_toolchain
    src = tmp_path / "src" / "server" / "SomeCustomMechanic.server.luau"
    src.parent.mkdir(parents=True)
    src.write_text("--!strict\\nlocal n = 1\\n", encoding="utf-8")
    monkeypatch.setattr(roblox_toolchain.shutil, "which",
                        lambda name: "/mock/luau-compile" if name == "luau-compile" else None)
    calls = []
    def fail_parse(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr="parse error")
    monkeypatch.setattr(roblox_toolchain.subprocess, "run", fail_parse)
    result = RobloxToolchainManager().run_luau_compile(tmp_path)
    assert result["executed"] and not result["success"]
    assert calls[0][:2] == ["/mock/luau-compile", "--only-parse"]
    assert str(src) in calls[0]
    monkeypatch.setattr(roblox_toolchain.shutil, "which", lambda name: None)
    missing = RobloxToolchainManager().run_luau_compile(tmp_path)
    assert missing["status"] == "not_run" and not missing["executed"]


def test_without_offline_tests_lune_is_not_applicable_regardless_of_game_type(tmp_path):
    result = RobloxToolchainManager().run_lune_offline_suite(tmp_path)
    assert result["status"] == "not_applicable"
    report = _report(tool_results={"offline_test_count": 0})
    assert report["checks"]["lune_offline"]["status"] == "not_applicable"
