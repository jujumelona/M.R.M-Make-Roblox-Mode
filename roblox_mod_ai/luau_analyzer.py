"""Luau static analysis, syntax verification, and linter for Roblox scripts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LuauDiagnostic:
    file_path: str
    line_number: int
    rule: str
    severity: str  # "ERROR", "WARNING", "INFO"
    message: str
    suggestion: str = ""


@dataclass
class LuauAnalysisReport:
    passed: bool
    diagnostics: list[LuauDiagnostic] = field(default_factory=list)
    files_analyzed: int = 0
    error_count: int = 0
    warning_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "files_analyzed": self.files_analyzed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "diagnostics": [
                {
                    "file": d.file_path,
                    "line": d.line_number,
                    "rule": d.rule,
                    "severity": d.severity,
                    "message": d.message,
                    "suggestion": d.suggestion,
                }
                for d in self.diagnostics
            ],
        }


from .dynamic_wiring import _mask_strings, _without_comments

class LuauStaticAnalyzer:
    """Performs static checks, type assertions, and linter passes on Luau code."""

    def __init__(self) -> None:
        self.has_luau_analyze = shutil.which("luau-analyze") is not None
        self.has_selene = shutil.which("selene") is not None
        # StyLua is already installed by MRM's Colab bootstrap, but the old
        # analyzer never used it when validating an individual model response.
        self.has_stylua = shutil.which("stylua") is not None

    def analyze_source(self, code: str, file_path: str = "script.luau") -> list[LuauDiagnostic]:
        """Perform comprehensive static analysis on a single Luau source string."""
        diagnostics: list[LuauDiagnostic] = []
        lines = code.splitlines()

        # Rule 1: Type Checking Mode
        if not any(line.strip().startswith("--!") for line in lines[:5]):
            diagnostics.append(
                LuauDiagnostic(
                    file_path=file_path,
                    line_number=1,
                    rule="LUAU_STRICT_TYPING",
                    severity="INFO",
                    message="Missing Luau mode annotation at top of file.",
                    suggestion="Add '--!strict' to enable compile-time type verification.",
                )
            )

        # Real Luau grammar validation MUST precede hand-written lint rules.
        # StyLua parses the original source without changing it (stdin mode).
        # Unlike keyword counting, it reports malformed types, function
        # declarations, expressions, comments and missing block terminators.
        # In Colab, RMM_REQUIRE_REAL_LUAU_PARSER=1 prevents a silent downgrade
        # to the inadequate balance heuristic when the binary is missing.
        stylua_path = shutil.which("stylua")
        real_parser_used = False
        if stylua_path:
            try:
                parsed = subprocess.run(
                    [stylua_path, "--syntax", "luau", "--stdin-filepath",
                     file_path, "-"],
                    input=code, text=True, capture_output=True, timeout=12,
                    check=False,
                )
                real_parser_used = True
                if parsed.returncode != 0:
                    detail = (parsed.stderr or parsed.stdout or
                              "StyLua rejected Luau source")
                    detail = re.sub(r"\x1b\[[0-9;]*m", "", detail).strip()
                    # Actual StyLua diagnostics use "(line:column to
                    # line:column)" rather than the English "line N".
                    # The previous regexp incorrectly treated the column as
                    # the line (e.g. (4:3) became line 3).
                    location = re.search(
                        r"\((\d+):(\d+)(?:\s+to\s+\d+:\d+)?\)",
                        detail)
                    by_label = re.search(r"(?i)\bline\s+(\d+)", detail)
                    line_no = (int(location.group(1)) if location else
                               int(by_label.group(1)) if by_label else 1)
                    diagnostics.append(LuauDiagnostic(
                        file_path=file_path, line_number=line_no,
                        rule="LUAU_PARSER_SYNTAX", severity="ERROR",
                        message=detail[:5000],
                        suggestion="Repair the actual Luau parser diagnostic; "
                                   "do not guess an extra end token.",
                    ))
            except subprocess.TimeoutExpired:
                real_parser_used = True
                diagnostics.append(LuauDiagnostic(
                    file_path=file_path, line_number=1,
                    rule="LUAU_PARSER_TIMEOUT", severity="ERROR",
                    message="StyLua Luau syntax parsing exceeded 12 seconds.",
                ))
            except OSError as exc:
                real_parser_used = True
                diagnostics.append(LuauDiagnostic(
                    file_path=file_path, line_number=1,
                    rule="LUAU_PARSER_UNAVAILABLE", severity="ERROR",
                    message=f"StyLua parser could not start: {exc}",
                ))
        elif os.environ.get("RMM_REQUIRE_REAL_LUAU_PARSER") == "1":
            real_parser_used = True
            diagnostics.append(LuauDiagnostic(
                file_path=file_path, line_number=1,
                rule="LUAU_PARSER_UNAVAILABLE", severity="ERROR",
                message="StyLua is required for actual Luau code verification "
                        "but not installed or not on PATH.",
            ))

        # Fallback keyword checking is retained for lightweight library tests
        # without StyLua. It is NOT used as a contradictory grammar verifier
        # when the actual Luau parser has run.
        # Rule 2: Syntax and Keyword Balance
        block_starts = ["function", "if", "for", "while", "do"]
        open_blocks = 0
        in_multiline_comment = False
        in_multiline_string = False

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Handle multiline comments --[[ ... ]]
            if "--[[" in stripped:
                in_multiline_comment = True
            if "]]" in stripped and in_multiline_comment:
                in_multiline_comment = False
                continue
            if in_multiline_comment:
                continue

            # Strip single line comments
            # Quoted Lua strings may contain words such as "function" or
            # "end". Never treat them as syntax-block tokens.
            code_line = _mask_strings(_without_comments(line))

            # Rule 3: Deprecated legacy globals (wait, spawn, delay)
            if re.search(r"(?<![.\w:])wait\s*\(", code_line):
                diagnostics.append(
                    LuauDiagnostic(
                        file_path=file_path,
                        line_number=idx,
                        rule="DEPRECATED_GLOBAL_WAIT",
                        severity="WARNING",
                        message="Legacy global 'wait()' is throttled and deprecated.",
                        suggestion="Replace with 'task.wait()'.",
                    )
                )
            if re.search(r"(?<![.\w:])spawn\s*\(", code_line):
                diagnostics.append(
                    LuauDiagnostic(
                        file_path=file_path,
                        line_number=idx,
                        rule="DEPRECATED_GLOBAL_SPAWN",
                        severity="WARNING",
                        message="Legacy global 'spawn()' runs with a 2-frame delay.",
                        suggestion="Replace with 'task.spawn()' or 'task.defer()'.",
                    )
                )

            # Rule 4: Proper GetService convention
            game_dot_match = re.search(
                r"\bgame\.(Players|ReplicatedStorage|ServerScriptService|ServerStorage|Workspace|Lighting|SoundService|TweenService|UserInputService|DataStoreService)\b",
                code_line,
            )
            if game_dot_match:
                service = game_dot_match.group(1)
                diagnostics.append(
                    LuauDiagnostic(
                        file_path=file_path,
                        line_number=idx,
                        rule="DIRECT_SERVICE_INDEXING",
                        severity="WARNING",
                        message=f"Accessing 'game.{service}' directly can fail if not replicated yet.",
                        suggestion=f'Use \'game:GetService("{service}")\' instead.',
                    )
                )

            # Rule 5: DataStore operations must use pcall
            if re.search(r":(GetAsync|SetAsync|UpdateAsync)\s*\(", code_line):
                # Check previous lines for pcall (ignoring comments)
                clean_context = [re.sub(r"--.*$", "", l) for l in lines[max(0, idx - 5) : idx]]
                context_window = "\n".join(clean_context)
                if "pcall" not in context_window:
                    diagnostics.append(
                        LuauDiagnostic(
                            file_path=file_path,
                            line_number=idx,
                            rule="DATASTORE_UNSAFE_PCALL",
                            severity="WARNING",
                            message="DataStore HTTP calls can fail and must be wrapped in pcall.",
                            suggestion="Wrap DataStore calls inside 'local success, result = pcall(function() ... end)'.",
                        )
                    )

            # Syntax block counting
            tokens = re.findall(r"\b(function|if|for|while|do|then|end|repeat|until)\b", code_line)
            # "elseif ... then" continues an existing if block, not a new block.
            if re.search(r"\belseif\b.*\bthen\b", code_line) and "then" in tokens:
                tokens.remove("then")
            for token in tokens:
                if token in {"function", "do", "repeat"}:
                    open_blocks += 1
                elif token in {"then"}:
                    # 'if ... then' starts a block
                    open_blocks += 1
                elif token in {"end", "until"}:
                    open_blocks -= 1

        if not real_parser_used and open_blocks != 0:
            diagnostics.append(
                LuauDiagnostic(
                    file_path=file_path,
                    line_number=len(lines),
                    rule="UNBALANCED_BLOCKS",
                    severity="ERROR",
                    message=f"Syntax error: Unbalanced Luau blocks (net balance: {open_blocks}). Missing 'end' or 'then'?",
                    suggestion="Ensure every 'function', 'if ... then', 'for', 'while' has a corresponding 'end'.",
                )
            )

        return diagnostics

    def analyze_files(self, file_map: dict[str, str]) -> LuauAnalysisReport:
        """Analyze all files provided as {relative_path: code_content}."""
        all_diagnostics: list[LuauDiagnostic] = []
        files_analyzed = len(file_map)

        for path, code in file_map.items():
            if path.endswith(".luau") or path.endswith(".lua"):
                diags = self.analyze_source(code, file_path=path)
                all_diagnostics.extend(diags)

        errors = [d for d in all_diagnostics if d.severity == "ERROR"]
        warnings = [d for d in all_diagnostics if d.severity == "WARNING"]

        return LuauAnalysisReport(
            passed=(len(errors) == 0),
            diagnostics=all_diagnostics,
            files_analyzed=files_analyzed,
            error_count=len(errors),
            warning_count=len(warnings),
        )
