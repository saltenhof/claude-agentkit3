"""Unit tests for the FK-32 ConformanceService (AG3-063)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.verify_system.conformance_service import (
    ConformanceEvaluation,
    ConformanceService,
    ConformanceVerdict,
    FidelityContext,
    FidelityFailureAction,
    FidelityLevel,
    identify_references,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass
class _RecordingEvaluator:
    verdict: ConformanceVerdict = ConformanceVerdict.PASS
    calls: list[dict[str, object]] = field(default_factory=list)
    paths_seen_during_call: tuple[Path, ...] = ()

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
        del context
        self.paths_seen_during_call = tuple(merge_paths)
        for path in merge_paths:
            assert path.is_file()
        self.calls.append(
            {
                "level": level,
                "subject": subject,
                "references": references,
                "expected_check_id": expected_check_id,
                "merge_paths": tuple(merge_paths),
            }
        )
        return ConformanceEvaluation(
            verdict=self.verdict,
            reason=f"{level.value} {self.verdict.value}",
            description=f"{level.value} evaluated",
        )


def _write_manifest(project_root: Path, *, content: str = "reference") -> None:
    guardrails = project_root / "_guardrails"
    docs = project_root / "concepts"
    guardrails.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "architecture.md").write_text(content, encoding="utf-8")
    (guardrails / "manifest-index.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "path": "concepts/architecture.md",
                        "scope": "architecture",
                        "modules": ["verify-system", "*"],
                        "story_types": ["implementation", "bugfix"],
                        "tags": ["document-fidelity", "*"],
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _context(project_root: Path, *, subject: str = "subject") -> FidelityContext:
    return FidelityContext(
        story_id="AG3-063",
        run_id="11111111-1111-4111-8111-111111111111",
        project_root=project_root,
        story_type="implementation",
        module="verify-system",
        subject=subject,
        story_description="Implement conformance",
        tags=("document-fidelity",),
    )


def test_all_four_levels_use_one_check_fidelity_entry(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    evaluator = _RecordingEvaluator()
    emitter = MemoryEmitter()
    service = ConformanceService(evaluator, emitter=emitter)

    results = [
        service.check_fidelity(level, _context(tmp_path))
        for level in FidelityLevel
    ]

    assert [result.level for result in results] == list(FidelityLevel)
    assert all(
        result.conformance_verdict is ConformanceVerdict.PASS for result in results
    )
    assert [call["expected_check_id"] for call in evaluator.calls] == [
        "goal_fidelity",
        "design_fidelity",
        "impl_fidelity",
        "feedback_fidelity",
    ]
    assert "conformance-verdict" in results[0].model_dump(by_alias=True)
    llm_events = emitter.query("AG3-063", EventType.LLM_CALL)
    assert len(llm_events) == 4
    assert all(
        event.source_component == "conformance_service"
        and event.payload["role"] == "doc_fidelity"
        for event in llm_events
    )


def test_level_failures_attach_typed_level_specific_action(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    expected = {
        FidelityLevel.GOAL: FidelityFailureAction.STORY_REVISION_REQUIRED,
        FidelityLevel.DESIGN: FidelityFailureAction.ESCALATED,
        FidelityLevel.IMPL: FidelityFailureAction.IMPLEMENTATION_BLOCKED,
        FidelityLevel.FEEDBACK: FidelityFailureAction.FEEDBACK_WARNING,
    }

    for level, action in expected.items():
        service = ConformanceService(
            _RecordingEvaluator(verdict=ConformanceVerdict.FAIL),
            emitter=MemoryEmitter(),
        )

        result = service.check_fidelity(level, _context(tmp_path))

        assert result.conformance_verdict is ConformanceVerdict.FAIL
        assert result.failure_action is action


def test_manifest_index_matches_module_story_type_and_tags(tmp_path: Path) -> None:
    _write_manifest(tmp_path, content="matched reference")

    references = identify_references(FidelityLevel.GOAL, _context(tmp_path))

    assert [reference.path for reference in references] == ["concepts/architecture.md"]
    assert references[0].content == "matched reference"


def test_missing_manifest_index_fails_closed_without_llm_call(tmp_path: Path) -> None:
    evaluator = _RecordingEvaluator()
    emitter = MemoryEmitter()
    service = ConformanceService(evaluator, emitter=emitter)

    result = service.check_fidelity(FidelityLevel.GOAL, _context(tmp_path))

    assert result.conformance_verdict is ConformanceVerdict.FAIL
    assert result.failure_action is FidelityFailureAction.STORY_REVISION_REQUIRED
    assert evaluator.calls == []
    assert emitter.query("AG3-063", EventType.LLM_CALL) == []


def test_broken_manifest_index_fails_closed_without_llm_call(tmp_path: Path) -> None:
    guardrails = tmp_path / "_guardrails"
    guardrails.mkdir(parents=True)
    (guardrails / "manifest-index.json").write_text("{broken", encoding="utf-8")
    evaluator = _RecordingEvaluator()
    service = ConformanceService(evaluator, emitter=MemoryEmitter())

    result = service.check_fidelity(FidelityLevel.DESIGN, _context(tmp_path))

    assert result.conformance_verdict is ConformanceVerdict.FAIL
    assert result.failure_action is FidelityFailureAction.ESCALATED
    assert evaluator.calls == []


def test_tier2_uses_merge_paths_and_cleans_up(tmp_path: Path) -> None:
    _write_manifest(tmp_path, content="r" * 128)
    evaluator = _RecordingEvaluator()
    service = ConformanceService(
        evaluator,
        emitter=MemoryEmitter(),
        file_upload_threshold=10,
        hard_limit=10_000,
    )

    result = service.check_fidelity(FidelityLevel.IMPL, _context(tmp_path, subject="s" * 64))

    assert result.conformance_verdict is ConformanceVerdict.PASS
    assert len(evaluator.paths_seen_during_call) == 2
    assert all(not path.exists() for path in evaluator.paths_seen_during_call)
    call = evaluator.calls[0]
    assert "uploaded as file" in str(call["subject"])
    assert "uploaded as file" in str(call["references"])


def test_tier3_fails_without_llm_call_or_truncation(tmp_path: Path) -> None:
    _write_manifest(tmp_path, content="r" * 128)
    evaluator = _RecordingEvaluator()
    emitter = MemoryEmitter()
    service = ConformanceService(
        evaluator,
        emitter=emitter,
        file_upload_threshold=10,
        hard_limit=64,
    )

    result = service.check_fidelity(
        FidelityLevel.FEEDBACK,
        _context(tmp_path, subject="s" * 128),
    )

    assert result.conformance_verdict is ConformanceVerdict.FAIL
    assert result.failure_action is FidelityFailureAction.FEEDBACK_WARNING
    assert evaluator.calls == []
    assert emitter.query("AG3-063", EventType.LLM_CALL) == []
    evaluated = emitter.query("AG3-063", EventType.CONFORMANCE_LEVEL_EVALUATED)
    completed = emitter.query("AG3-063", EventType.CONFORMANCE_ASSESSMENT_COMPLETED)
    assert evaluated[-1].payload["status"] == "FAIL"
    assert completed[-1].payload["status"] == "FAIL"
