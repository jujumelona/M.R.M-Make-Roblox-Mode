"""Contract-based source attestation, independent of game genres and prompts."""
from __future__ import annotations

import pytest

from roblox_mod_ai.compiled_effect_verification import (
    _luau_tokens, verify_compiled_effect_sources,
)
from roblox_mod_ai.host_atomic_effect import render_atomic_server
from test_generic_transaction_effect import _candidate


def _persist_transaction(tmp_path):
    proposal, server, remote = _candidate()
    source = render_atomic_server(server, proposal)
    assert source is not None
    file = tmp_path / server.file_path
    file.parent.mkdir(parents=True)
    file.write_text(source, encoding="utf-8")
    return proposal, server, remote, file


def test_unmodified_host_transaction_attests_each_declared_state_write(tmp_path):
    proposal, server, _, _ = _persist_transaction(tmp_path)
    report = verify_compiled_effect_sources(proposal, tmp_path)
    assert report["passed"], report
    assert len(report["checked"]) == 1
    assert report["checked"][0]["contract_effect_count"] == 2
    assert report["checked"][0]["file"] == server.file_path


@pytest.mark.parametrize("bad_change", [
    "remove_first_write", "remove_second_write", "alter_operation",
    "comment_out_write", "substitute_return", "alter_guard",
])
def test_omitted_or_corrupted_declarative_effect_fails_closed(tmp_path, bad_change):
    proposal, _, _, file = _persist_transaction(tmp_path)
    source = file.read_text(encoding="utf-8")
    if bad_change == "remove_first_write":
        source = source.replace("state.ore=next1", "")
    elif bad_change == "remove_second_write":
        source = source.replace("state.credits=next2", "")
    elif bad_change == "alter_operation":
        source = source.replace("local next2=old2+amount2",
                                "local next2=old2-amount2")
    elif bad_change == "comment_out_write":
        source = source.replace("state.credits=next2", "-- state.credits=next2")
    elif bad_change == "substitute_return":
        source = source.replace("return {success=true,values=",
                                "return {success=false,values=")
    else:
        source = source.replace("if old1<amount1 then",
                                "if old1>amount1 then")
    assert source != file.read_text(encoding="utf-8")
    file.write_text(source, encoding="utf-8")
    report = verify_compiled_effect_sources(proposal, tmp_path)
    assert not report["passed"], report
    assert any("compiled_effect_source_mismatch" in issue
               for issue in report["failures"])


def test_stylua_spacing_and_comments_do_not_break_attestation(tmp_path):
    proposal, _, _, file = _persist_transaction(tmp_path)
    source = file.read_text(encoding="utf-8")
    source = source.replace("state.ore=next1", "state.ore = next1")
    source = source.replace("state.credits=next2",
                            "-- audited state source\n    state.credits = next2")
    file.write_text(source, encoding="utf-8")
    assert verify_compiled_effect_sources(proposal, tmp_path)["passed"]


def test_contract_change_without_regeneration_is_detected(tmp_path):
    proposal, _, remote, _ = _persist_transaction(tmp_path)
    replacement = proposal.game_design["dynamic_design"]["host_executable_actions"][remote]
    replacement["changes"][1]["amount"]["constant"] = 7
    assert not verify_compiled_effect_sources(proposal, tmp_path)["passed"]


def test_unowned_or_unsupported_executable_program_is_not_approved(tmp_path):
    proposal, _, remote, _ = _persist_transaction(tmp_path)
    design = proposal.game_design["dynamic_design"]
    design["host_actions"][remote]["service"] = "NotInModuleRoster"
    assert not verify_compiled_effect_sources(proposal, tmp_path)["passed"]


def test_prompt_rewording_does_not_change_attestation(tmp_path):
    proposal, _, _, _ = _persist_transaction(tmp_path)
    result = verify_compiled_effect_sources(proposal, tmp_path)
    assert result["passed"]
    for prompt in (
        "Build an interactive garden with seed counters",
        "Make a puzzle with three scores",
        "우주 모드의 자원 처리",
        "Completely different world and story",
    ):
        proposal.requested_prompt = prompt
        report = verify_compiled_effect_sources(proposal, tmp_path)
        assert report["passed"], report
        assert report["checked"] == result["checked"]


def test_tokenizer_does_not_confuse_comment_with_code():
    a = "state.score += 5 -- diagnostic\n"
    b = "state.score += 5\n"
    c = "-- state.score += 5\n"
    assert _luau_tokens(a) == _luau_tokens(b)
    assert _luau_tokens(a) != _luau_tokens(c)
    assert _luau_tokens("local ab = 5") != _luau_tokens("local a b = 5")
