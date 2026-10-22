"""Original Luau execution text must exclude all long-bracket comments/literals."""
from roblox_mod_ai.dynamic_wiring import _without_comments, _mask_strings
from roblox_mod_ai.gameplay_source_evidence import (
    has_gameplay_mutation, state_key_used_by_executable_code,
)


def test_long_comment_never_pretends_to_fire_remote_or_write_state():
    source = (
        "--[=[\n"
        'remote:FireServer()\nworkspace:SetAttribute("Owner", true)\n'
        "]=]\nlocal value = 2\n"
    )
    cleaned = _mask_strings(_without_comments(source))
    assert "FireServer" not in cleaned
    assert "SetAttribute" not in cleaned
    assert "local value = 2" in cleaned
    assert not has_gameplay_mutation(source)


def test_luau_long_string_is_not_executable_source():
    source = (
        'local prose = [==[\n'
        'workspace:SetAttribute("ColonyOwned", true)\n'
        'remote:FireServer()\n'
        '-- this is literal text, not a line comment\n'
        ']==]\n'
        'print(prose)\n'
    )
    without = _without_comments(source)
    assert "this is literal text" in without
    executable = _mask_strings(without)
    assert "FireServer" not in executable
    assert "SetAttribute" not in executable
    assert "print(prose)" in executable
    assert not has_gameplay_mutation(source)
    assert not state_key_used_by_executable_code(source, "ColonyOwned")


def test_real_code_after_long_comment_is_not_hidden():
    source = (
        "--[=[ fake:FireServer() ]=]\n"
        'player:SetAttribute("ColonyOwned", true)\n'
    )
    assert has_gameplay_mutation(source)
    assert state_key_used_by_executable_code(source, "ColonyOwned")


def test_ordinary_quoted_urls_and_simple_comments_keep_existing_behavior():
    source = 'local url = "https://example.com/a--b"\n-- Remote:FireServer()\n'
    cleaned = _without_comments(source)
    assert "https://example.com/a--b" in cleaned
    assert "Remote:FireServer()" not in cleaned
