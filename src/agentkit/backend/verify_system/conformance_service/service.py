"""Shared ConformanceService implementation for all fidelity levels (FK-32)."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.backend.telemetry.emitters import EventEmitter, NullEmitter
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.verify_system.conformance_service.models import (
    ConformanceVerdict,
    FidelityContext,
    FidelityFailureAction,
    FidelityLevel,
    FidelityResult,
    ReferenceDocument,
)
from agentkit.backend.verify_system.llm_evaluator.bundle import ReviewBundle
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    LlmVerdict,
    ReviewerRole,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.verify_system.protocols import Finding

FILE_UPLOAD_THRESHOLD_BYTES: int = 50 * 1024
HARD_LIMIT_BYTES: int = 500 * 1024
_MANIFEST_RELATIVE_PATH = Path("_guardrails") / "manifest-index.json"
_SOURCE_COMPONENT = "conformance_service"
_DOC_FIDELITY_ROLE = "doc_fidelity"


class ConformanceManifestError(ValueError):
    """Raised when the curated manifest index is missing or invalid."""


class ConformanceTier2NotSupportedError(RuntimeError):
    """Raised by an adapter that has no file-capable transport boundary.

    The conformance Tier-2 path writes temporary files and passes them as
    ``merge_paths`` to the evaluator port.  The
    :class:`StructuredEvaluatorConformanceAdapter` routes through the
    file-free Layer-2 ``LlmClient`` (FK-34 / FK-11 §11.5.1) which is
    deliberately file-free; the file-capable MCP transport is owned by
    AG3-065 which is not yet built.  Rather than silently discarding the
    paths and sending pointer text, the adapter raises this error so the
    :class:`ConformanceService` can fail-closed (FAIL without LLM call)
    and surface the deferral explicitly.
    """


@dataclass(frozen=True)
class ConformanceEvaluation:
    """Result returned by the injected fidelity evaluator port."""

    verdict: ConformanceVerdict
    reason: str
    description: str
    findings: tuple[Finding, ...] = ()
    evaluator_result: object | None = None


class ConformanceEvaluationPort(Protocol):
    """Evaluator seam used by ConformanceService for all four levels."""

    def evaluate(
        self,
        *,
        level: FidelityLevel,
        context: FidelityContext,
        subject: str,
        references: str,
        expected_check_id: str,
        merge_paths: Sequence[Path],
    ) -> ConformanceEvaluation:
        """Evaluate one fidelity level."""
        ...

    def supports_file_upload(self) -> bool:
        """Return whether this adapter can deliver ``merge_paths`` to the LLM.

        Adapters backed by a file-free transport (e.g. the Layer-2
        ``LlmClient`` until AG3-065 provides the file-capable MCP boundary)
        MUST return ``False``.  The :class:`ConformanceService` uses this to
        fail-closed on Tier-2 payloads rather than silently degrading to
        pointer text.
        """
        ...


class _ManifestDocument(BaseModel):
    """One curated manifest-index entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    scope: str
    modules: tuple[str, ...] = Field(min_length=1)
    story_types: tuple[str, ...] = Field(min_length=1)
    tags: tuple[str, ...] = ()


class _ManifestIndex(BaseModel):
    """Curated manifest-index root object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[_ManifestDocument, ...] = Field(min_length=1)


#: Level-specific prompt template names for the conformance evaluator (FK-32 §32.3).
#: The ``impl`` level reuses the established Layer-2 doc-fidelity template
#: (``qa-doc-fidelity``); the other three levels have their own level-appropriate
#: templates so a real LLM receives instructions matching the expected check_id.
_CONFORMANCE_TEMPLATE_FOR_LEVEL: dict[FidelityLevel, str] = {
    FidelityLevel.GOAL: "qa-conformance-goal",
    FidelityLevel.DESIGN: "qa-conformance-design",
    FidelityLevel.IMPL: "qa-doc-fidelity",
    FidelityLevel.FEEDBACK: "doc-fidelity-feedback",
}


class StructuredEvaluatorConformanceAdapter:
    """Reuse the existing StructuredEvaluator as the single doc-fidelity reviewer.

    This adapter wraps a ``StructuredEvaluator`` (or duck-typed equivalent such
    as ``ParallelEvalRunner``) and maps all four :class:`FidelityLevel` values
    onto ``ReviewerRole.DOC_FIDELITY`` with a level-specific prompt template
    override so that a real LLM receives the correct check-id instruction per
    level (ERROR 2 fix: goal/design/feedback levels use dedicated templates that
    instruct the matching ``{level}_fidelity`` check_id; impl continues to use
    the established ``qa-doc-fidelity`` template).

    File-upload (Tier-2) is NOT supported by this adapter: the Layer-2
    ``LlmClient`` port is deliberately file-free (FK-34 / FK-11 §11.5.1).
    The file-capable MCP transport is owned by AG3-065.  Callers that would
    require file upload must check :meth:`supports_file_upload` and handle the
    ``False`` case fail-closed — the adapter itself raises
    :class:`ConformanceTier2NotSupportedError` when ``merge_paths`` is non-empty
    (ERROR 1 fix: no silent discard).
    """

    def __init__(self, evaluator: Any) -> None:
        """Initialize the adapter.

        Args:
            evaluator: Existing ``StructuredEvaluator`` or ``ParallelEvalRunner``
                instance. The type is kept structural to avoid a second reviewer
                abstraction.
        """
        self._evaluator = evaluator

    def supports_file_upload(self) -> bool:
        """Return ``False``: this adapter has no file-capable transport boundary.

        The underlying Layer-2 ``LlmClient`` is deliberately file-free
        (FK-34 / FK-11 §11.5.1).  The file-capable MCP transport that would
        enable Tier-2 conformance is deferred to AG3-065.
        """
        return False

    def evaluate(
        self,
        *,
        level: FidelityLevel,
        context: FidelityContext,
        subject: str,
        references: str,
        expected_check_id: str,
        merge_paths: Sequence[Path],
    ) -> ConformanceEvaluation:
        """Evaluate via ``ReviewerRole.DOC_FIDELITY`` with a level-specific template.

        Args:
            level: The fidelity level being assessed.
            context: Fidelity assessment context.
            subject: Subject text (inline, Tier-1 path only).
            references: Reference documents text (inline, Tier-1 path only).
            expected_check_id: The expected check_id for this level
                (e.g. ``goal_fidelity``).
            merge_paths: Temp-file paths for Tier-2 uploads.  This adapter has
                no file-capable transport boundary; a non-empty sequence raises
                :class:`ConformanceTier2NotSupportedError` (fail-closed, no
                silent discard).  File-capable transport is deferred to AG3-065.

        Returns:
            :class:`ConformanceEvaluation` with the LLM verdict.

        Raises:
            ConformanceTier2NotSupportedError: When ``merge_paths`` is non-empty
                (Tier-2 file upload not supported until AG3-065).
        """
        if merge_paths:
            raise ConformanceTier2NotSupportedError(
                f"Tier-2 file upload is not supported by "
                f"StructuredEvaluatorConformanceAdapter: the Layer-2 LlmClient "
                f"is deliberately file-free (FK-34 / FK-11 §11.5.1). "
                f"File-capable transport is deferred to AG3-065. "
                f"merge_paths={[str(p) for p in merge_paths]!r}"
            )
        template_name = _CONFORMANCE_TEMPLATE_FOR_LEVEL[level]
        bundle = _bundle_for_context(context, subject=subject, references=references)
        # ERROR 3 fix: propagate context.run_id so the evaluator can persist the
        # prompt-audit envelope keyed to the current run (FK-11 §11.4.6a).
        # FidelityContext does not carry an attempt counter; default to 1.
        result = self._evaluator.evaluate(
            role=ReviewerRole.DOC_FIDELITY,
            bundle=bundle,
            previous_findings=(
                list(context.previous_findings) if context.previous_findings else None
            ),
            qa_cycle_round=context.qa_cycle_round,
            expected_check_ids=frozenset({expected_check_id}),
            template_override=template_name,
            run_id=context.run_id,
            run_attempt=1,
        )
        return ConformanceEvaluation(
            verdict=_verdict_from_llm(result.verdict),
            reason=_reason_from_result(result),
            description=f"{level.value} fidelity evaluated by doc_fidelity",
            findings=result.findings,
            evaluator_result=result,
        )


class ConformanceService:
    """Single shared fidelity entry point for goal/design/impl/feedback."""

    def __init__(
        self,
        evaluator: ConformanceEvaluationPort,
        *,
        emitter: EventEmitter | None = None,
        file_upload_threshold: int = FILE_UPLOAD_THRESHOLD_BYTES,
        hard_limit: int = HARD_LIMIT_BYTES,
    ) -> None:
        """Initialize the service."""
        if file_upload_threshold <= 0:
            raise ValueError("conformance.file_upload_threshold must be > 0")
        if hard_limit <= file_upload_threshold:
            raise ValueError(
                "conformance.hard_limit must be greater than "
                "conformance.file_upload_threshold"
            )
        self._evaluator = evaluator
        self._emitter = emitter if emitter is not None else NullEmitter()
        self._file_upload_threshold = file_upload_threshold
        self._hard_limit = hard_limit

    def check_fidelity(
        self,
        level: FidelityLevel,
        context: FidelityContext,
    ) -> FidelityResult:
        """Check one fidelity level via the common FK-32 five-step flow."""
        assessment_id = str(uuid4())
        self._emit_assessment_started(assessment_id, level, context)
        try:
            references = identify_references(level, context)
        except ConformanceManifestError as exc:
            result = self._fail_result(
                level,
                reason=str(exc),
                description="Conformance assessment failed closed before LLM call.",
                references_used=(),
            )
            self._emit_level_evaluated(assessment_id, context, result)
            self._emit_assessment_completed(assessment_id, context, result)
            return result

        references_text = _format_references(references)
        references_used = tuple(reference.path for reference in references)
        data_size = len(context.subject.encode("utf-8")) + len(
            references_text.encode("utf-8")
        )
        if data_size >= self._hard_limit:
            result = self._fail_result(
                level,
                reason=(
                    f"Payload ({data_size} bytes) exceeds hard limit "
                    f"({self._hard_limit} bytes)."
                ),
                description="LLM call blocked: payload too large for conformance.",
                references_used=references_used,
            )
            self._emit_level_evaluated(assessment_id, context, result)
            self._emit_assessment_completed(assessment_id, context, result)
            return result

        # Tier-2: payload exceeds inline threshold but is below hard limit.
        # Check whether the evaluator supports file upload before writing temp
        # files. If not, fail-closed immediately without an LLM call (no
        # LLM_CALL event — no LLM was invoked). The file-capable transport is
        # deferred to AG3-065. (ERROR 1 fix.)
        if (
            data_size >= self._file_upload_threshold
            and not self._evaluator.supports_file_upload()
        ):
            result = self._fail_result(
                level,
                reason=(
                    f"Tier-2 file upload required ({data_size} bytes "
                    f">= threshold {self._file_upload_threshold} bytes) but the "
                    "configured evaluator has no file-capable transport boundary. "
                    "File-capable transport is deferred to AG3-065."
                ),
                description=(
                    "Conformance Tier-2 blocked: no file-capable LLM transport "
                    "(AG3-065 not yet built)."
                ),
                references_used=references_used,
            )
            self._emit_level_evaluated(assessment_id, context, result)
            self._emit_assessment_completed(assessment_id, context, result)
            return result

        merge_paths: tuple[Path, ...] = ()
        subject = context.subject
        refs = references_text
        try:
            if data_size >= self._file_upload_threshold:
                merge_paths = _write_upload_files(
                    story_id=context.story_id,
                    subject=context.subject,
                    references=references_text,
                )
                subject = (
                    "[Subject uploaded as file: "
                    f"{len(context.subject.encode('utf-8'))} bytes]"
                )
                refs = (
                    "[References uploaded as file: "
                    f"{len(references_text.encode('utf-8'))} bytes]"
                )

            try:
                evaluation = self._evaluator.evaluate(
                    level=level,
                    context=context,
                    subject=subject,
                    references=refs,
                    expected_check_id=f"{level.value}_fidelity",
                    merge_paths=merge_paths,
                )
            except Exception as exc:  # noqa: BLE001 -- FAIL-CLOSED evaluator seam
                result = self._fail_result(
                    level,
                    reason="Conformance evaluator failed: "
                    f"{type(exc).__name__}: {exc}",
                    description="Conformance assessment failed closed during LLM evaluation.",
                    references_used=references_used,
                )
                self._emit_llm_call(level, context, result)
                self._emit_level_evaluated(assessment_id, context, result)
                self._emit_assessment_completed(assessment_id, context, result)
                return result
        finally:
            for path in merge_paths:
                path.unlink(missing_ok=True)

        result = FidelityResult(
            level=level,
            conformance_verdict=evaluation.verdict,
            reason=evaluation.reason,
            description=evaluation.description,
            references_used=references_used,
            findings=evaluation.findings,
            failure_action=_failure_action(level, evaluation.verdict),
            evaluator_result=evaluation.evaluator_result,
        )
        self._emit_llm_call(level, context, result)
        self._emit_level_evaluated(assessment_id, context, result)
        self._emit_assessment_completed(assessment_id, context, result)
        return result

    def _fail_result(
        self,
        level: FidelityLevel,
        *,
        reason: str,
        description: str,
        references_used: tuple[str, ...],
    ) -> FidelityResult:
        """Build a typed fail-closed result."""
        return FidelityResult(
            level=level,
            conformance_verdict=ConformanceVerdict.FAIL,
            reason=reason,
            description=description,
            references_used=references_used,
            failure_action=_failure_action(level, ConformanceVerdict.FAIL),
        )

    def _emit_assessment_started(
        self, assessment_id: str, level: FidelityLevel, context: FidelityContext
    ) -> None:
        self._emitter.emit(
            Event(
                story_id=context.story_id,
                run_id=context.run_id,
                project_key=None,
                event_type=EventType.CONFORMANCE_ASSESSMENT_STARTED,
                source_component=_SOURCE_COMPONENT,
                payload={
                    "assessment_id": assessment_id,
                    "level": level.value,
                    "story_id": context.story_id,
                    "run_id": context.run_id,
                },
            )
        )

    def _emit_level_evaluated(
        self,
        assessment_id: str,
        context: FidelityContext,
        result: FidelityResult,
    ) -> None:
        self._emitter.emit(
            Event(
                story_id=context.story_id,
                run_id=context.run_id,
                event_type=EventType.CONFORMANCE_LEVEL_EVALUATED,
                source_component=_SOURCE_COMPONENT,
                payload={
                    "assessment_id": assessment_id,
                    "level": result.level.value,
                    "status": result.conformance_verdict.value,
                    "reason": result.reason,
                },
            )
        )

    def _emit_assessment_completed(
        self,
        assessment_id: str,
        context: FidelityContext,
        result: FidelityResult,
    ) -> None:
        self._emitter.emit(
            Event(
                story_id=context.story_id,
                run_id=context.run_id,
                event_type=EventType.CONFORMANCE_ASSESSMENT_COMPLETED,
                source_component=_SOURCE_COMPONENT,
                payload={
                    "assessment_id": assessment_id,
                    "level": result.level.value,
                    "status": result.conformance_verdict.value,
                    "references_used": list(result.references_used),
                },
            )
        )

    def _emit_llm_call(
        self,
        level: FidelityLevel,
        context: FidelityContext,
        result: FidelityResult,
    ) -> None:
        self._emitter.emit(
            Event(
                story_id=context.story_id,
                run_id=context.run_id,
                event_type=EventType.LLM_CALL,
                source_component=_SOURCE_COMPONENT,
                payload={
                    "role": _DOC_FIDELITY_ROLE,
                    "level": level.value,
                    "status": result.conformance_verdict.value,
                    "source_component": _SOURCE_COMPONENT,
                },
            )
        )


def identify_references(
    level: FidelityLevel, context: FidelityContext
) -> tuple[ReferenceDocument, ...]:
    """Read, validate, and resolve curated manifest-index references."""
    del level
    root = context.project_root.resolve()
    manifest_path = root / _MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        raise ConformanceManifestError(
            f"missing curated manifest index: {_MANIFEST_RELATIVE_PATH.as_posix()}"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = _ManifestIndex.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ConformanceManifestError(
            f"broken curated manifest index: {_MANIFEST_RELATIVE_PATH.as_posix()}"
        ) from exc

    matches: list[ReferenceDocument] = []
    for document in manifest.documents:
        if not _matches(document.modules, context.module):
            continue
        if not _matches(document.story_types, context.story_type):
            continue
        if not _tags_match(document.tags, context.tags):
            continue
        path = _resolve_reference_path(root, document.path)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConformanceManifestError(
                f"manifest reference is unreadable: {document.path}"
            ) from exc
        matches.append(
            ReferenceDocument(
                path=document.path,
                scope=document.scope,
                content=content,
            )
        )
    if not matches:
        raise ConformanceManifestError(
            "manifest index produced no references for "
            f"module={context.module!r}, story_type={context.story_type!r}"
        )
    return tuple(sorted(matches, key=lambda reference: reference.path))


def _matches(values: tuple[str, ...], actual: str) -> bool:
    return "*" in values or actual in values


def _tags_match(document_tags: tuple[str, ...], context_tags: tuple[str, ...]) -> bool:
    if not document_tags or "*" in document_tags:
        return True
    if not context_tags:
        return False
    return bool(set(document_tags) & set(context_tags))


def _resolve_reference_path(root: Path, manifest_path: str) -> Path:
    path = (root / manifest_path).resolve()
    if not path.is_relative_to(root):
        raise ConformanceManifestError(
            f"manifest reference escapes project root: {manifest_path}"
        )
    if not path.is_file():
        raise ConformanceManifestError(
            f"manifest reference does not exist: {manifest_path}"
        )
    return path


def _format_references(references: tuple[ReferenceDocument, ...]) -> str:
    return "\n\n".join(
        f"## {reference.path}\nScope: {reference.scope}\n{reference.content}"
        for reference in references
    )


def _write_upload_files(
    *,
    story_id: str,
    subject: str,
    references: str,
) -> tuple[Path, Path]:
    subject_path = _write_temp_file(
        prefix=f"fidelity-subject-{story_id}-",
        content=subject,
    )
    refs_path = _write_temp_file(
        prefix=f"fidelity-refs-{story_id}-",
        content=references,
    )
    return subject_path, refs_path


def _write_temp_file(*, prefix: str, content: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=prefix,
        suffix=".txt",
        delete=False,
    ) as handle:
        handle.write(content)
        return Path(handle.name)


def _bundle_for_context(
    context: FidelityContext, *, subject: str, references: str
) -> ReviewBundle:
    if isinstance(context.review_bundle, ReviewBundle):
        return context.review_bundle.model_copy(
            update={
                "story_brief_excerpt": context.story_description or subject,
                "diff_content": subject,
                "concept_refs": [references],
            }
        )
    return ReviewBundle(
        story_id=context.story_id,
        story_brief_excerpt=context.story_description or subject,
        acceptance_criteria=[],
        diff_summary=f"{context.module} {context.story_type} conformance",
        diff_content=subject,
        concept_refs=[references],
        previous_findings=None,
        qa_cycle_round=1,
    )


def _verdict_from_llm(verdict: LlmVerdict) -> ConformanceVerdict:
    return ConformanceVerdict(verdict.value)


def _reason_from_result(result: object) -> str:
    findings = getattr(result, "findings", ())
    if findings:
        first = findings[0]
        return str(getattr(first, "message", "conformance finding"))
    verdict = getattr(result, "verdict", None)
    value = getattr(verdict, "value", str(verdict))
    return f"doc_fidelity returned {value}"


def _failure_action(
    level: FidelityLevel, verdict: ConformanceVerdict
) -> FidelityFailureAction | None:
    if verdict is not ConformanceVerdict.FAIL:
        return None
    return {
        FidelityLevel.GOAL: FidelityFailureAction.STORY_REVISION_REQUIRED,
        FidelityLevel.DESIGN: FidelityFailureAction.ESCALATED,
        FidelityLevel.IMPL: FidelityFailureAction.IMPLEMENTATION_BLOCKED,
        FidelityLevel.FEEDBACK: FidelityFailureAction.FEEDBACK_WARNING,
    }[level]


__all__ = [
    "ConformanceEvaluation",
    "ConformanceEvaluationPort",
    "ConformanceManifestError",
    "ConformanceService",
    "ConformanceTier2NotSupportedError",
    "FILE_UPLOAD_THRESHOLD_BYTES",
    "HARD_LIMIT_BYTES",
    "StructuredEvaluatorConformanceAdapter",
    "identify_references",
]
