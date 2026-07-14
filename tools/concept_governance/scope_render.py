"""Stable text and JSON rendering for W3 command results."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concept_governance.scope_models import ScopeConsistencyRunResult


def render_scope_result(result: ScopeConsistencyRunResult) -> str:
    """Render completion accounting, findings, both loci, and P4 state."""
    errors = sum(item.severity == "ERROR" for item in result.findings)
    reports = len(result.findings) - errors
    lines = [
        f"concept-scope-consistency: {'PASS' if result.ok else 'ERROR'} "
        f"(scope_sets={result.scope_sets}, partitions={result.partitions}, "
        f"completed={result.completed_partitions}, errors={errors}, reports={reports})"
    ]
    for item in result.findings:
        related = "; ".join(
            f"{locus.doc}#{locus.anchor} assertion={locus.assertion!r}"
            for locus in item.related_loci
        )
        p4 = "pending" if item.formalization_check is None else (
            f"candidate={item.formalization_check.formalization_candidate} "
            f"reason={item.formalization_check.reason!r}"
        )
        lines.append(
            f"[{item.severity}] {item.code} {item.doc}#{item.anchor} scope={item.scope!r} "
            f"assertion={item.assertion!r} related=[{related}] p4={p4} "
            f"prompt={item.prompt_version} model={item.model}: {item.message}"
        )
    return "\n".join(lines)
