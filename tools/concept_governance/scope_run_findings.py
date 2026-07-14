"""Named W3 operational findings and run-result construction."""

from __future__ import annotations

from concept_governance.scope_models import (
    SCOPE_PROMPT_VERSION,
    ScopeConsistencyFinding,
    ScopeConsistencyRunResult,
    ScopePartition,
)


def run_finding(code: str, message: str, model: str, doc: str) -> ScopeConsistencyFinding:
    """Build one run-level ERROR finding with explicit pending P4 state."""
    return ScopeConsistencyFinding(
        code=code,
        doc=doc,
        anchor="(run)",
        assertion=message,
        related_loci=(),
        scope="",
        prompt_version=SCOPE_PROMPT_VERSION,
        model=model,
        message=message,
        formalization_check=None,
    )


def partition_finding(
    code: str,
    message: str,
    model: str,
    partition: ScopePartition,
) -> ScopeConsistencyFinding:
    """Bind an operational finding to the failed partition's first locus."""
    first = partition.assertions[0]
    return run_finding(code, message, model, first.doc).model_copy(
        update={"anchor": first.anchor, "scope": partition.scope}
    )


def incomplete_finding(
    completed: int,
    expected: int,
    partition: ScopePartition,
    model: str,
) -> ScopeConsistencyFinding:
    """Build the mandatory named completeness failure."""
    detail = f"completed={completed} expected={expected}"
    return partition_finding("INCOMPLETE_SWEEP", detail, model, partition)


def make_scope_result(
    findings: tuple[ScopeConsistencyFinding, ...],
    sets: int,
    partitions: int,
    completed: int,
) -> ScopeConsistencyRunResult:
    """Build one fully accounted W3 run result."""
    return ScopeConsistencyRunResult(
        findings=findings,
        scope_sets=sets,
        partitions=partitions,
        completed_partitions=completed,
    )
