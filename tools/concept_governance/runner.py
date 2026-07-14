"""W2 orchestration from working-tree chunks through deterministic policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.baseline import BaselineError, load_baseline
from concept_governance.baseline_policy import apply_baseline
from concept_governance.chunks import load_chunks
from concept_governance.execution import EvaluationRunError, collect_findings
from concept_governance.models import PROMPT_VERSION, AuthorityFinding, AuthorityRunResult
from concept_governance.vocabulary import load_scope_vocabulary

if TYPE_CHECKING:
    from pathlib import Path

    from concept_ingester.discovery import ConceptChunk

    from concept_governance.port import AuthorityProseEvaluator


def run_authority_check(
    concept_root: Path,
    baseline_path: Path,
    evaluator: AuthorityProseEvaluator,
    included_docs: frozenset[str] | None = None,
    *,
    parallelism: int = 1,
) -> AuthorityRunResult:
    """Run W2 fail-closed without ever writing the baseline."""
    baseline_doc = _relative_baseline_doc(concept_root, baseline_path)
    try:
        baseline = load_baseline(baseline_path)
    except BaselineError as exc:
        return _failed("INVALID_BASELINE", str(exc), evaluator.model, baseline_doc)
    try:
        vocabulary = load_scope_vocabulary(concept_root)
        chunks = load_chunks(concept_root, included_docs)
    except (OSError, ValueError) as exc:
        return _failed("DISCOVERY_FAILURE", str(exc), evaluator.model, concept_root.as_posix())
    try:
        raw_findings = collect_findings(chunks, evaluator, vocabulary, parallelism)
    except EvaluationRunError as exc:
        return _chunk_failure(exc.code, str(exc), exc.model, exc.chunk)
    findings = apply_baseline(raw_findings, baseline, baseline_doc, included_docs)
    return AuthorityRunResult(findings=findings)


def _failed(code: str, message: str, model: str, doc: str) -> AuthorityRunResult:
    finding = AuthorityFinding(
        code=code,
        doc=doc,
        anchor="(run)",
        assertion=message,
        scope="",
        prompt_version=PROMPT_VERSION,
        model=model,
        message=message,
    )
    return AuthorityRunResult(findings=(finding,))


def _chunk_failure(code: str, message: str, model: str, chunk: ConceptChunk) -> AuthorityRunResult:
    result = _failed(code, message, model, chunk.rel_path)
    return AuthorityRunResult(findings=(result.findings[0].model_copy(update={"anchor": chunk.section_anchor}),))


def _relative_baseline_doc(concept_root: Path, baseline_path: Path) -> str:
    try:
        return baseline_path.resolve().relative_to(concept_root.resolve().parent).as_posix()
    except ValueError:
        return baseline_path.name
