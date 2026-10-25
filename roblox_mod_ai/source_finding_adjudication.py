"""Separate model speculation from authoritative codegen/static verification.

A verbatim source-line quote proves only that text exists. It does *not*
establish the truth of an AI claim about a whole-file implementation. For
first-party host-owned sources, never promote such a claim to an automatic
whole-source repair or a blocking generator bug. Keep it visible as unresolved
for the host generator's deterministic contracts and subsequent engine checks.
Failures to determine provenance remain blocking (fail closed).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .generation_provenance import host_source_must_regenerate
from .generation_scope import generation_scope


def adjudicate_source_findings(proposal: Any, report: dict[str, Any]) -> dict[str, Any]:
    """Return a new review report, retaining every model claim and source cite.

    This does not assert that a host template is correct. The claims become
    'unverified', not 'resolved' or 'passed'. A model-authored source with a
    blocking finding still enters the bounded AI repair loop.
    """
    result = deepcopy(report)
    result["unverified_host_claims"] = []
    result["adjudication"] = "model_claims_not_code_evidence"
    if not result.get("fully_covered") or result.get("status") == "failed":
        return result

    try:
        scope = generation_scope(proposal)
        rows = scope["modules"]
        strategies = {
            row["module_id"]: row["strategy"]
            for row in rows
        }
        paths = {module.file_path: module for module in proposal.modules}
        # Do not trust partial or stale ownership tables to downgrade findings.
        if (len(rows) != len(proposal.modules)
                or any(module.module_id not in strategies
                       for module in proposal.modules)):
            raise ValueError("Incomplete generation ownership map")
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        result["adjudication"] = (
            "generation_provenance_unavailable; AI claims remain blocking: "
            + str(exc)[:250])
        return result

    updated = []
    for finding in result.get("findings", []):
        if not isinstance(finding, dict):
            updated.append(finding)
            continue
        row = dict(finding)
        module = paths.get(row.get("file"))
        if module is None:
            # Unknown source has no trusted provenance.
            updated.append(row)
            continue
        if (row.get("severity") == "blocking" and
                host_source_must_regenerate(
                    module, strategies[module.module_id])):
            row["claimed_severity"] = "blocking"
            row["severity"] = "advisory"
            row["adjudication"] = "unverified_host_model_claim"
            row["evidence"] = "source_quote_matches_but_claim_unproven"
            result["unverified_host_claims"].append({
                "file": row.get("file"), "line": row.get("line"),
                "quote": row.get("quote"), "issue": row.get("issue"),
                "why_not_autofixed": "Host-generated template needs independent "
                                     "generator/static or engine evidence",
            })
        updated.append(row)

    result["findings"] = updated
    blocking = any(isinstance(f, dict) and f.get("severity") == "blocking"
                   for f in updated)
    unverified = bool(result["unverified_host_claims"])
    if blocking:
        result["status"] = "issues_found"
        result["reason"] = (
            "Model-authored source has blocking quoted findings requiring "
            "verified repair; host template claims remain separately unverified")
    elif unverified:
        result["status"] = "reviewed_unverified_host_claims"
        result["reason"] = (
            f"Full AI review completed, but {len(result['unverified_host_claims'])} "
            "host-generated defects were alleged without independent proof. "
            "Not a passed source review or Roblox Studio gameplay verification; "
            "claims retained for generator-level inspection.")
    return result
