"""Regression for proposal 39: host Luau must pass Selene's assert ABI.

Template bugs must be fixed at the deterministic source generator, not by
asking a small model to rewrite the generated entire server module.
"""
from pathlib import Path
import re
from types import SimpleNamespace as NS

from roblox_mod_ai.host_level_upgrade import _SERVER as RANK_SERVER
from roblox_mod_ai.host_vehicle_departure import _SERVER as DEPARTURE_SERVER
from roblox_mod_ai.host_space_actions import LUA as SPACE_SERVER, _client, _server
from roblox_mod_ai import dynamic_repair


def unmessaged_assert_lines(source: str) -> list[int]:
    """Find assert(expr) using balanced parens, not a single-line regex.

    This handles multiline calls and nested expressions; Lua strings in the
    templates are simple quoted literals, and escaped quotes are respected.
    """
    bad = []
    for match in re.finditer(r"\bassert\s*\(", source):
        depth = 1
        quote = None
        escaped = False
        commas = 0
        for c in source[match.end():]:
            if quote is not None:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == quote:
                    quote = None
                continue
            if c in ('"', "'"):
                quote = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            elif c == "," and depth == 1:
                commas += 1
        assert depth == 0, "Malformed assert expression"
        if not commas:
            bad.append(source.count("\n", 0, match.start()) + 1)
    return bad


def test_every_host_assert_in_failed_space_protocol_has_message():
    emitted_sources = {
        "rank_server": RANK_SERVER,
        "departure_server": DEPARTURE_SERVER,
        "space_server": SPACE_SERVER,
        "planet_combat": _server("AlienCombat", {
            "arrival": "ArrivalZone", "target": "AlienTarget"
        }, "BuilderServer"),
        "weapon_upgrade": _server("WeaponPerformanceUpgrade", {}, ""),
        "client": _client("SpaceAction", "AlienCombat"),
    }
    for label, source in emitted_sources.items():
        assert "assert(" in source, label
        assert unmessaged_assert_lines(source) == [], label
    # Grounded weapon upgrades do not need orbit/world-action helpers.
    weapon = emitted_sources["weapon_upgrade"]
    assert "local function near(" not in weapon
    assert "local function arrived(" not in weapon
    assert "local function placePlanetActionTarget(" not in weapon


def test_failed_host_linter_does_not_call_model_or_mutate_generated_source(
    monkeypatch, tmp_path: Path,
):
    module = NS(
        module_id="dyn_rank_server",
        file_path="src/server/GenericRankServer.luau",
        code="--!strict\nreturn {}\n",
    )
    proposal = NS(modules=[module])
    monkeypatch.setattr(
        dynamic_repair, "generation_scope",
        lambda _: {"modules": [
            {"module_id": "dyn_rank_server",
             "strategy": "host_declarative_rank_upgrade"}
        ]},
    )

    def forbidden_repair(*args, **kwargs):
        raise AssertionError("Host-owned source must never be model-rewritten")

    monkeypatch.setattr(
        dynamic_repair.RobloxCodeRepairAgent, "repair", forbidden_repair
    )
    location = tmp_path / module.file_path
    location.parent.mkdir(parents=True)
    location.write_text(module.code, encoding="utf-8")
    diag = "src/server/GenericRankServer.luau:12: assert requires 2 parameters"
    result = dynamic_repair.repair_tool_diagnostics(
        proposal, tmp_path, "selene",
        {"executed": True, "success": False, "stdout": diag},
        retry_tool=forbidden_repair,
        format_sources=forbidden_repair,
        router=NS(),
    )
    assert result["passed"] is False
    assert "HOST_GENERATOR_SOURCE_DEFECT" in result["reason"]
    assert result["host_source_defects"][0]["path"] == module.file_path
    assert location.read_text(encoding="utf-8") == module.code
