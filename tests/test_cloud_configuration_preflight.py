"""Colab auto verification may not block offline game creation by default.

These tests execute only the configuration cell, with mock credentials.
No Roblox account, model download, external request, or upload is involved.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


NOTEBOOK = Path(__file__).resolve().parents[1] / "R.M.M_Make_Roblox_Mode_Colab.ipynb"


def config_source() -> str:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "".join(next(cell for cell in notebook["cells"]
                        if cell["id"] == "configuration")["source"])


def reset_environment(monkeypatch):
    for key in ("ROBLOX_OPEN_CLOUD_API_KEY", "ROBLOX_TEST_UNIVERSE_ID",
                "ROBLOX_TEST_PLACE_ID", "RMM_ALLOW_TEST_PLACE_PUBLISH"):
        monkeypatch.delenv(key, raising=False)


def execute_policy(source: str, policy: str) -> dict:
    updated = source.replace(
        'ENGINE_VERIFICATION_POLICY = "Auto" #@param',
        f'ENGINE_VERIFICATION_POLICY = "{policy}" #@param',
    )
    scope = {}
    exec(compile(updated, "colab/config", "exec"), scope)
    return scope


def test_default_auto_continues_offline_build_without_cloud_setup(monkeypatch, capsys):
    reset_environment(monkeypatch)
    scope = execute_policy(config_source(), "Auto")
    assert scope["ENGINE_VERIFICATION_POLICY"] == "Auto"
    assert scope["CLOUD_ENGINE_READY"] is False
    assert scope["ENGINE_VERIFY_BEFORE_FINAL"] is False
    out = capsys.readouterr().out
    assert "built_unverified" in out
    assert "ZIP 생성은 계속합니다" in out
    assert "ROBLOX_TEST_PLACE_ID" in out


def test_explicit_off_mode_also_runs_without_secrets(monkeypatch):
    reset_environment(monkeypatch)
    scope = execute_policy(config_source(), "Off")
    assert scope["ENGINE_VERIFY_BEFORE_FINAL"] is False


def test_required_mode_blocks_unsafe_unverified_final(monkeypatch):
    reset_environment(monkeypatch)
    with pytest.raises(RuntimeError, match="Required 모드") as error:
        execute_policy(config_source(), "Required")
    assert "ROBLOX_OPEN_CLOUD_API_KEY" in str(error.value)
    assert "ROBLOX_TEST_PLACE_ID" in str(error.value)


def test_valid_test_only_settings_select_real_cloud_engine(monkeypatch):
    reset_environment(monkeypatch)
    monkeypatch.setenv("ROBLOX_OPEN_CLOUD_API_KEY", "FAKE-LOCAL-UNIT-TEST-ONLY")
    code = (config_source()
            .replace('CLOUD_TEST_UNIVERSE_ID = "" #@param',
                     'CLOUD_TEST_UNIVERSE_ID = "123" #@param')
            .replace('CLOUD_TEST_PLACE_ID = "" #@param',
                     'CLOUD_TEST_PLACE_ID = "456" #@param')
            .replace('CLOUD_ENABLE_TEST_PUBLISH = False #@param',
                     'CLOUD_ENABLE_TEST_PUBLISH = True #@param'))
    auto = execute_policy(code, "Auto")
    required = execute_policy(code, "Required")
    assert auto["CLOUD_ENGINE_READY"] is True
    assert auto["ENGINE_VERIFY_BEFORE_FINAL"] is True
    assert required["ENGINE_VERIFY_BEFORE_FINAL"] is True
    assert execute_policy(code, "Off")["ENGINE_VERIFY_BEFORE_FINAL"] is False


def test_partial_cloud_configuration_falls_back_to_offline_without_upload(monkeypatch):
    reset_environment(monkeypatch)
    code = config_source().replace('CLOUD_TEST_UNIVERSE_ID = "" #@param',
                                   'CLOUD_TEST_UNIVERSE_ID = "123" #@param')
    scope = execute_policy(code, "Auto")
    assert scope["CLOUD_ENGINE_READY"] is False
    assert scope["ENGINE_VERIFY_BEFORE_FINAL"] is False
    assert "ROBLOX_TEST_PLACE_ID" in scope["CLOUD_MISSING_REQUIREMENTS"]


def test_plan_only_mode_does_not_require_cloud_permission(monkeypatch):
    reset_environment(monkeypatch)
    code = config_source().replace('RUN_MODE = "Full" #@param',
                                   'RUN_MODE = "Plan" #@param')
    scope = execute_policy(code, "Required")
    assert scope["RUN_MODE"] == "Plan"
    assert scope["ENGINE_VERIFY_BEFORE_FINAL"] is True
