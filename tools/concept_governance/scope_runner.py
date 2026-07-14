"""W3 orchestration from local discovery through shared baseline policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.errors import MultiLlmHubError
from concept_governance.baseline import BaselineError, load_baseline
from concept_governance.baseline_policy import apply_scope_baseline
from concept_governance.chunks import load_chunks
from concept_governance.scope_execution import ScopeSweepError, collect_scope_findings
from concept_governance.scope_port import BatchScopeConsistencyEvaluator
from concept_governance.scope_run_findings import (
    incomplete_finding,
    make_scope_result,
    partition_finding,
    run_finding,
)
from concept_governance.scope_sets import ScopeSetError, build_scope_sets, partition_scope_sets
from concept_governance.vocabulary import load_scope_vocabulary

if TYPE_CHECKING:
    from pathlib import Path

    from concept_governance.scope_models import ScopeConsistencyRunResult
    from concept_governance.scope_port import ScopeConsistencyEvaluator


def run_scope_consistency(
    concept_root: Path,
    baseline_path: Path,
    evaluator: ScopeConsistencyEvaluator,
    scope_filters: tuple[str, ...] = (),
    *,
    limit: int | None = None,
    partition_max_chars: int = 48_000,
    partition_max_chunks: int = 20,
) -> ScopeConsistencyRunResult:
    """Run W3 fail closed without reading an index or writing the baseline."""
    baseline_doc = _relative_baseline_doc(concept_root, baseline_path)
    try:
        baseline = load_baseline(baseline_path)
    except BaselineError as exc:
        finding = run_finding("INVALID_BASELINE", str(exc), evaluator.model, baseline_doc)
        return make_scope_result((finding,), 0, 0, 0)
    try:
        vocabulary = load_scope_vocabulary(concept_root)
        chunks = load_chunks(concept_root)
        requested = frozenset(scope_filters) if scope_filters else None
        scope_sets = build_scope_sets(chunks, vocabulary, requested)
        if limit is not None:
            if limit < 1:
                raise ScopeSetError("limit must be positive")
            scope_sets = scope_sets[:limit]
        empty = tuple(item.scope for item in scope_sets if not item.assertions)
        if not scope_sets or empty:
            detail = "no scope sets selected" if not scope_sets else f"empty scope sets: {list(empty)}"
            incomplete = run_finding(
                "INCOMPLETE_SWEEP", detail, evaluator.model, concept_root.as_posix()
            )
            return make_scope_result((incomplete,), len(scope_sets), 0, 0)
        partitions = partition_scope_sets(
            scope_sets, max_chars=partition_max_chars, max_chunks=partition_max_chunks
        )
    except (OSError, ValueError) as exc:
        finding = run_finding("DISCOVERY_FAILURE", str(exc), evaluator.model, concept_root.as_posix())
        return make_scope_result((finding,), 0, 0, 0)
    try:
        if isinstance(evaluator, BatchScopeConsistencyEvaluator):
            with evaluator:
                raw_findings = collect_scope_findings(partitions, evaluator)
        else:
            raw_findings = collect_scope_findings(partitions, evaluator)
    except ScopeSweepError as exc:
        failed = partition_finding(exc.code, str(exc), exc.model, exc.partition)
        incomplete = incomplete_finding(exc.completed, len(partitions), exc.partition, exc.model)
        return make_scope_result((failed, incomplete), len(scope_sets), len(partitions), exc.completed)
    except (LlmClientError, MultiLlmHubError, TimeoutError) as exc:
        failed = run_finding("HUB_UNREACHABLE", str(exc), evaluator.model, concept_root.as_posix())
        incomplete = run_finding(
            "INCOMPLETE_SWEEP",
            f"completed=0 expected={len(partitions)}",
            evaluator.model,
            concept_root.as_posix(),
        )
        return make_scope_result((failed, incomplete), len(scope_sets), len(partitions), 0)
    selected_scopes = frozenset(item.scope for item in scope_sets)
    findings = apply_scope_baseline(raw_findings, baseline, baseline_doc, selected_scopes)
    return make_scope_result(findings, len(scope_sets), len(partitions), len(partitions))


def _relative_baseline_doc(concept_root: Path, baseline_path: Path) -> str:
    try:
        return baseline_path.resolve().relative_to(concept_root.resolve().parent).as_posix()
    except ValueError:
        return baseline_path.name
