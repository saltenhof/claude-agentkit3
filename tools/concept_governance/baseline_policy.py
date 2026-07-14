"""Keyed suppression and stale-entry surfacing for W2 findings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.models import AuthorityFinding
from concept_governance.scope_models import ScopeConsistencyFinding

if TYPE_CHECKING:
    from concept_governance.baseline import BaselineDocument, BaselineEntry

W3_CODES = frozenset({"SCOPE_CONTRADICTION"})


def apply_baseline(
    findings: tuple[AuthorityFinding, ...],
    baseline: BaselineDocument,
    baseline_doc: str,
    included_docs: frozenset[str] | None = None,
) -> tuple[AuthorityFinding, ...]:
    """List baselined findings as reports and emit stale entries as errors."""
    entries = tuple(
        entry
        for entry in baseline.entries
        if entry.code not in W3_CODES and (included_docs is None or entry.doc in included_docs)
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


def apply_scope_baseline(
    findings: tuple[ScopeConsistencyFinding, ...],
    baseline: BaselineDocument,
    baseline_doc: str,
    included_scopes: frozenset[str],
) -> tuple[ScopeConsistencyFinding, ...]:
    """Apply only W3 entries and surface stale selected-scope keys."""
    entries = tuple(
        entry
        for entry in baseline.entries
        if entry.code in W3_CODES and entry.scope in included_scopes
    )
    by_key = {entry.key: entry for entry in entries}
    active = {finding.key for finding in findings}
    output = [
        finding.model_copy(
            update={
                "severity": "REPORT",
                "baselined": True,
                "formalization_check": by_key[finding.key].formalization_check,
            }
        )
        if finding.key in by_key
        else finding
        for finding in findings
    ]
    output.extend(_scope_stale(entry, baseline_doc) for entry in entries if entry.key not in active)
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


def _scope_stale(entry: BaselineEntry, baseline_doc: str) -> ScopeConsistencyFinding:
    return ScopeConsistencyFinding(
        code="STALE_BASELINE",
        doc=baseline_doc,
        anchor=entry.anchor,
        assertion=entry.assertion,
        related_loci=entry.related_loci,
        scope=entry.scope,
        prompt_version=entry.prompt_version,
        model=entry.model,
        message=f"baseline entry for {entry.code} in {entry.doc} no longer matches an active finding",
        formalization_check=entry.formalization_check,
    )
