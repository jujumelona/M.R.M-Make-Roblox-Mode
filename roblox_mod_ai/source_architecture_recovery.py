"""Verify a source-owned architecture after a nonessential classifier fails.

A small-model English classification is not an implementation contract. The
architect instead sees the exact original source requirement, and recovery is
permitted ONLY when the validated dynamic design provides authoritative server
owners and observable acceptance for every formerly unclassified chunk.
"""
from __future__ import annotations

from typing import Any

from .semantic_preservation import source_intent_conflicts, source_outcome_conflicts


class SourceArchitectureRecoveryError(ValueError):
    """Source-owned gameplay is still missing from the authored architecture."""


def certify_unclassified_chunks(
    ledger: dict[str, Any], dynamic_design: dict[str, Any],
    modules: list[Any],
) -> list[str]:
    """Return recovered chunk IDs, or fail closed with requirement evidence.

    This certifies a *source-level architecture*, never generated Luau or
    Roblox Studio behavior. Do not use model-authored search queries as proof.
    """
    missing = set(ledger.get("classification_unverified") or [])
    if not missing:
        return []
    atoms = {
        row.get("chunk_id"): row
        for row in ledger.get("atomic_intents", [])
        if isinstance(row, dict) and row.get("chunk_id") in missing
    }
    if set(atoms) != missing:
        raise SourceArchitectureRecoveryError(
            "Missing classifier chunks have no exact source-owned requirement"
        )

    module_facets = dynamic_design.get("module_facets") or {}
    module_requirements = dynamic_design.get("module_requirements") or {}
    acceptance = dynamic_design.get("acceptance") or {}
    facet_acceptance = dynamic_design.get("acceptance_facets") or {}
    if not all(isinstance(x, dict) for x in (
        module_facets, module_requirements, acceptance, facet_acceptance
    )):
        raise SourceArchitectureRecoveryError(
            "Architecture has incomplete ownership/acceptance contracts"
        )

    certified: list[str] = []
    for chunk_id in sorted(missing):
        atom = atoms[chunk_id]
        facet = atom.get("facet_id")
        requirement = atom.get("requirement_id")
        source = atom.get("source_span")
        if not all(isinstance(v, str) and v for v in (
            facet, requirement, source
        )):
            raise SourceArchitectureRecoveryError(
                chunk_id + ": missing immutable source identifiers"
            )
        owners = [
            m for m in modules
            if facet in module_facets.get(m.module_id, [])
            and requirement in module_requirements.get(m.module_id, [])
            and getattr(getattr(m, "kind", None), "value", None)
                in ("server_module", "server_script")
        ]
        if not owners:
            raise SourceArchitectureRecoveryError(
                chunk_id + ": no server module directly owns source requirement"
            )
        implementation = "\n".join(str(m.description or "") for m in owners)
        outcome = acceptance.get(requirement)
        facet_outcome = facet_acceptance.get(facet)
        if not isinstance(outcome, str) or not outcome.strip():
            raise SourceArchitectureRecoveryError(
                chunk_id + ": missing requirement-specific acceptance"
            )
        if not isinstance(facet_outcome, str) or not facet_outcome.strip():
            raise SourceArchitectureRecoveryError(
                chunk_id + ": missing feature-level acceptance"
            )
        errors = (
            source_intent_conflicts(source, implementation)
            + source_outcome_conflicts(source, outcome)
            + source_outcome_conflicts(source, facet_outcome)
        )
        if errors:
            raise SourceArchitectureRecoveryError(
                chunk_id + ": " + "; ".join(dict.fromkeys(errors))
            )
        certified.append(chunk_id)
    return certified
