"""Strict Colab engine credential preflight must run before GPU/model setup.

Tests execute only the notebook configuration cell with temporary environment
variables. No Roblox account, model download or API key is used.
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


def test_default_full_mode_fails_early_without_cloud_setup(monkeypatch):
    reset_environment(monkeypatch)
    with pytest.raises(RuntimeError, match="Roblox 엔진 검증 환경") as exc:
        exec(compile(config_source(), "colab/config", "exec"), {})
    message = str(exc.value)
    for field in ("ROBLOX_OPEN_CLOUD_API_KEY", "ROBLOX_TEST_UNIVERSE_ID",
                  "ROBLOX_TEST_PLACE_ID", "CLOUD_ENABLE_TEST_PUBLISH"):
        assert field in message
    assert "Secrets" in message and "ENGINE_VERIFY_BEFORE_FINAL=False" in message


def test_explicit_unverified_dev_build_does_not_need_secrets(monkeypatch):
    reset_environment(monkeypatch)
    code = config_source().replace(
        "ENGINE_VERIFY_BEFORE_FINAL = True #@param",
        "ENGINE_VERIFY_BEFORE_FINAL = False #@param",
    )
    assert code != config_source()
    scope = {}
    exec(compile(code, "colab/config", "exec"), scope)
    assert scope["ENGINE_VERIFY_BEFORE_FINAL"] is False


def test_valid_test_only_settings_allow_verified_build_to_begin(monkeypatch):
    reset_environment(monkeypatch)
    monkeypatch.setenv("ROBLOX_OPEN_CLOUD_API_KEY", "FAKE-LOCAL-UNIT-TEST-ONLY")
    code = (config_source()
            .replace('CLOUD_TEST_UNIVERSE_ID = "" #@param',
                     'CLOUD_TEST_UNIVERSE_ID = "123" #@param')
            .replace('CLOUD_TEST_PLACE_ID = "" #@param',
                     'CLOUD_TEST_PLACE_ID = "456" #@param')
            .replace('CLOUD_ENABLE_TEST_PUBLISH = False #@param',
                     'CLOUD_ENABLE_TEST_PUBLISH = True #@param'))
    scope = {}
    exec(compile(code, "colab/config", "exec"), scope)
    assert scope["ENGINE_VERIFY_BEFORE_FINAL"] is True
    assert scope["CLOUD_ENABLE_TEST_PUBLISH"] is True


def test_plan_only_mode_requires_no_publish_permission(monkeypatch):
    reset_environment(monkeypatch)
    code = config_source().replace('RUN_MODE = "Full" #@param',
                                    'RUN_MODE = "Plan" #@param')
    scope = {}
    exec(compile(code, "colab/config", "exec"), scope)
    assert scope["RUN_MODE"] == "Plan"
