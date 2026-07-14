"""Keyed suppression and stale-entry surfacing for W2 findings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.models import AuthorityFinding

if TYPE_CHECKING:
    from concept_governance.baseline import BaselineDocument, BaselineEntry


def apply_baseline(
    findings: tuple[AuthorityFinding, ...],
    baseline: BaselineDocument,
    baseline_doc: str,
    included_docs: frozenset[str] | None = None,
) -> tuple[AuthorityFinding, ...]:
    """List baselined findings as reports and emit stale entries as errors."""
    entries = tuple(
        entry for entry in baseline.entries if included_docs is None or entry.doc in included_docs
    )
    by_key = {entry.key: entry for entry in entries}
    active = {finding.key for finding in findings}
    output = [
        finding.model_copy(update={"severity": "REPORT", "baselined": True})
        if finding.key in by_key
        else finding
        for finding in findings
    ]
    output.extend(_stale(entry, baseline_doc) for entry in entries if entry.key not in active)
    return tuple(sorted(output, key=lambda item: item.key))


def _stale(entry: BaselineEntry, baseline_doc: str) -> AuthorityFinding:
    return AuthorityFinding(
        code="STALE_BASELINE",
        doc=baseline_doc,
        anchor=entry.anchor,
        assertion=entry.assertion,
        scope=entry.scope,
        prompt_version=entry.prompt_version,
        model=entry.model,
        message=f"baseline entry for {entry.code} in {entry.doc} no longer matches an active finding",
    )
