"""Unit tests for the FK-32 ConformanceService (AG3-063)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.verify_system.conformance_service import (
    ConformanceEvaluation,
    ConformanceService,
    ConformanceTier2NotSupportedError,
    ConformanceVerdict,
    FidelityContext,
    FidelityFailureAction,
    FidelityLevel,
    StructuredEvaluatorConformanceAdapter,
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

    def supports_file_upload(self) -> bool:
        """Return True so tests that probe Tier-2 can pass merge_paths through."""
        return True

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


# ---------------------------------------------------------------------------
# AG3-063 Remediation: ERROR 1 — Tier-2 file boundary
# ---------------------------------------------------------------------------


def test_tier2_fails_closed_when_adapter_has_no_file_transport(tmp_path: Path) -> None:
    """ERROR 1 fix: Tier-2 path fails closed when adapter has no file-capable transport.

    StructuredEvaluatorConformanceAdapter.supports_file_upload() returns False.
    ConformanceService must NOT silently discard merge_paths but FAIL CLOSED,
    emitting level.evaluated + assessment.completed (status=FAIL) but NO
    llm_call event (no LLM was invoked).
    """
    _write_manifest(tmp_path, content="r" * 128)

    class _FakeEval:
        """Fake underlying evaluator that would be called if the adapter forwarded."""

        def __init__(self) -> None:
            self.called = False

        def evaluate(self, **_: object) -> ConformanceEvaluation:  # type: ignore[override]
            self.called = True
            return ConformanceEvaluation(
                verdict=ConformanceVerdict.PASS, reason="ok", description="ok"
            )

    fake = _FakeEval()
    adapter = StructuredEvaluatorConformanceAdapter(fake)
    assert adapter.supports_file_upload() is False

    emitter = MemoryEmitter()
    service = ConformanceService(
        adapter,
        emitter=emitter,
        file_upload_threshold=10,  # tiny threshold to force Tier-2
        hard_limit=10_000,
    )

    result = service.check_fidelity(
        FidelityLevel.IMPL,
        _context(tmp_path, subject="s" * 64),
    )

    assert result.conformance_verdict is ConformanceVerdict.FAIL
    assert "AG3-065" in result.reason
    assert fake.called is False  # LLM was never called
    assert emitter.query("AG3-063", EventType.LLM_CALL) == []  # no llm_call event
    evaluated = emitter.query("AG3-063", EventType.CONFORMANCE_LEVEL_EVALUATED)
    completed = emitter.query("AG3-063", EventType.CONFORMANCE_ASSESSMENT_COMPLETED)
    assert evaluated[-1].payload["status"] == "FAIL"
    assert completed[-1].payload["status"] == "FAIL"


def test_structured_evaluator_adapter_raises_on_nonempty_merge_paths(
    tmp_path: Path,
) -> None:
    """ERROR 1 adapter-level test: StructuredEvaluatorConformanceAdapter raises
    ConformanceTier2NotSupportedError when merge_paths is non-empty (not silently
    dropped). The Layer-2 LlmClient is file-free; file upload deferred to AG3-065.
    """

    class _FakeEval:
        """Stub evaluator that records whether it was called."""

        def __init__(self) -> None:
            self.called = False

        def evaluate(self, **_: object) -> ConformanceEvaluation:  # type: ignore[override]
            self.called = True
            return ConformanceEvaluation(
                verdict=ConformanceVerdict.PASS, reason="ok", description="ok"
            )

    fake = _FakeEval()
    adapter = StructuredEvaluatorConformanceAdapter(fake)

    dummy_path = tmp_path / "dummy.txt"
    dummy_path.write_text("x", encoding="utf-8")

    with pytest.raises(ConformanceTier2NotSupportedError, match="AG3-065"):
        adapter.evaluate(
            level=FidelityLevel.IMPL,
            context=_context(tmp_path),
            subject="subject",
            references="refs",
            expected_check_id="impl_fidelity",
            merge_paths=(dummy_path,),
        )

    assert fake.called is False


# ---------------------------------------------------------------------------
# AG3-063 Remediation: ERROR 2 — Level-specific prompt rendering
# ---------------------------------------------------------------------------


def test_adapter_uses_level_specific_template_for_each_fidelity_level(
    tmp_path: Path,
) -> None:
    """ERROR 2 fix: StructuredEvaluatorConformanceAdapter passes a level-specific
    template_override to the underlying evaluator for each FidelityLevel so that a
    real LLM receives instructions matching the expected check_id (not impl_fidelity
    for all levels).
    """
    from agentkit.verify_system.conformance_service.service import (
        _CONFORMANCE_TEMPLATE_FOR_LEVEL,
    )

    @dataclass
    class _CapturingEval:
        """Records the template_override passed per evaluate() call."""

        calls: list[dict[str, object]] = field(default_factory=list)

        def evaluate(  # type: ignore[override]
            self,
            *,
            role: object,
            bundle: object,
            previous_findings: object,
            qa_cycle_round: int,
            expected_check_ids: object,
            template_override: str | None = None,
        ) -> object:
            from agentkit.verify_system.llm_evaluator.structured_evaluator import (
                LlmVerdict,
                ReviewerRole,
                StructuredEvaluatorResult,
            )

            self.calls.append({"template_override": template_override, "expected_check_ids": expected_check_ids})
            return StructuredEvaluatorResult(
                role=ReviewerRole.DOC_FIDELITY,
                verdict=LlmVerdict.PASS,
                findings=(),
                finding_resolutions={},
                raw_response_hash="a" * 64,
                template_sha256="b" * 64,
            )

    capturing = _CapturingEval()
    adapter = StructuredEvaluatorConformanceAdapter(capturing)

    ctx = _context(tmp_path)
    for level in FidelityLevel:
        capturing.calls.clear()
        adapter.evaluate(
            level=level,
            context=ctx,
            subject="subject",
            references="refs",
            expected_check_id=f"{level.value}_fidelity",
            merge_paths=(),
        )
        assert len(capturing.calls) == 1
        call = capturing.calls[0]
        expected_template = _CONFORMANCE_TEMPLATE_FOR_LEVEL[level]
        assert call["template_override"] == expected_template, (
            f"Level {level.value}: expected template {expected_template!r}, "
            f"got {call['template_override']!r}"
        )
        expected_check_id = frozenset({f"{level.value}_fidelity"})
        assert call["expected_check_ids"] == expected_check_id, (
            f"Level {level.value}: expected check_ids {expected_check_id}, "
            f"got {call['expected_check_ids']!r}"
        )


# ---------------------------------------------------------------------------
# AG3-063 Remediation: NIT (ERROR 2 strengthening) — real prompt materialization
# ---------------------------------------------------------------------------


def test_adapter_rendered_prompt_instructs_level_appropriate_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NIT (ERROR 2 strengthening): the rendered prompt for each FidelityLevel
    instructs the LLM with the level-appropriate check_id, not a generic one.

    Materializes the ACTUAL rendered prompt (via the real PromptRuntime + a
    project-bound bundle) for each level (goal/design/feedback/impl) and asserts:
    - goal template asks for ``goal_fidelity``
    - design template asks for ``design_fidelity``
    - feedback template asks for ``feedback_fidelity``
    - impl template (qa-doc-fidelity) asks for ``impl_fidelity``

    Proves that a real LLM would be asked the right question per level, not just
    that the override string is plumbed to the evaluator parameter.
    """
    import json
    from hashlib import sha256 as _sha256

    from agentkit.artifacts import ArtifactManager, EnvelopeValidator, ProducerRegistry
    from agentkit.installer.paths import PROMPT_BUNDLE_STORE_ENV, prompt_bundle_store_dir
    from agentkit.prompt_runtime.register import register_prompt_runtime_producers
    from agentkit.prompt_runtime.resources import (
        PROJECT_LOCK_RELPATH,
        load_prompt_template,
    )
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryMode, StoryType
    from agentkit.verify_system.conformance_service.service import (
        _CONFORMANCE_TEMPLATE_FOR_LEVEL,
    )
    from agentkit.verify_system.llm_evaluator.bundle import build_review_bundle
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
    from agentkit.verify_system.llm_evaluator.prompt_materializer import (
        PromptRuntimeMaterializer,
    )
    from agentkit.verify_system.llm_evaluator.structured_evaluator import ReviewerRole
    from agentkit.verify_system.protocols import RunScope

    # Collect the real template text for all four conformance levels.
    template_names = list(_CONFORMANCE_TEMPLATE_FOR_LEVEL.values())
    templates: dict[str, str] = {name: load_prompt_template(name) for name in template_names}

    # Write a project-bound prompt bundle for these four templates.
    bundle_dir = prompt_bundle_store_dir(
        "conformance-bound", "1", store_root=tmp_path / "prompt-bundles"
    )
    (bundle_dir / "internal" / "prompts").mkdir(parents=True)
    for name, content in templates.items():
        (bundle_dir / "internal" / "prompts" / f"{name}.md").write_text(
            content, encoding="utf-8"
        )
    entries = {
        name: {
            "relpath": f"internal/prompts/{name}.md",
            "sha256": _sha256(content.encode("utf-8")).hexdigest(),
        }
        for name, content in templates.items()
    }
    manifest_text = json.dumps(
        {"bundle_id": "conformance-bound", "bundle_version": "1", "templates": entries}
    )
    (bundle_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = tmp_path / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "conformance-bound",
                "bundle_version": "1",
                "binding_root": "prompts",
                "manifest_file": "manifest.json",
                "manifest_sha256": _sha256(manifest_text.encode("utf-8")).hexdigest(),
                "templates": entries,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

    from agentkit.state_backend.store import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    from agentkit.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    registry = ProducerRegistry()
    register_prompt_runtime_producers(registry)
    manager = ArtifactManager(
        repository=StateBackendArtifactRepository(store_dir=tmp_path),
        validator=EnvelopeValidator(registry),
    )

    ctx = StoryContext(
        project_key="test",
        story_id="AG3-063",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )

    class _FixedScope:
        def load(self, story_dir: object) -> None:
            return None

        def resolve_run_scope(self, story_dir: object) -> RunScope:
            return RunScope(run_id="run-1", story_id="AG3-063", attempt=1)

    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=tmp_path,
        artifact_manager=manager,
        story_context_port=_FixedScope(),
    )
    bundle = build_review_bundle(
        Layer2ReviewInput(story_spec="b"), story_id="AG3-063", qa_cycle_round=1
    )
    resolved_ctx, story_id = materializer.context_for(bundle)

    # Map each FidelityLevel to its expected check_id keyword in the rendered prompt.
    level_to_check_id = {
        FidelityLevel.GOAL: "goal_fidelity",
        FidelityLevel.DESIGN: "design_fidelity",
        FidelityLevel.IMPL: "impl_fidelity",
        FidelityLevel.FEEDBACK: "feedback_fidelity",
    }

    for level, expected_check_id in level_to_check_id.items():
        template_name = _CONFORMANCE_TEMPLATE_FOR_LEVEL[level]
        rendered, _sha = materializer.render(
            ReviewerRole.DOC_FIDELITY, resolved_ctx, story_id,
            template_override=template_name,
        )
        assert expected_check_id in rendered, (
            f"Level {level.value!r}: rendered prompt from template "
            f"{template_name!r} does not contain check_id {expected_check_id!r} — "
            f"a real LLM would NOT be asked the right question."
        )
        # Confirm none of the OTHER level check_ids leak in (no cross-contamination).
        # The impl level shares the qa-doc-fidelity template so skip its cross-check.
        if level is not FidelityLevel.IMPL:
            for _other_level, other_check_id in level_to_check_id.items():
                if other_check_id != expected_check_id:
                    assert other_check_id not in rendered, (
                        f"Level {level.value!r}: rendered prompt unexpectedly contains "
                        f"{other_check_id!r} from another level — cross-contamination."
                    )


# ---------------------------------------------------------------------------
# AG3-063 Remediation: ERROR 4 — ConformanceConfig wiring
# ---------------------------------------------------------------------------


def test_configured_threshold_changes_tier_boundary(tmp_path: Path) -> None:
    """ERROR 4 fix: a configured file_upload_threshold takes effect on check_fidelity.

    The service uses the injected threshold, not just the default 50KB constant.
    With threshold=5 and subject of 10 bytes, Tier-2 is triggered.  Because the
    recording evaluator supports_file_upload() (returns True by default for
    _RecordingEvaluator), it actually receives merge_paths — proving the threshold
    was applied.
    """
    _write_manifest(tmp_path, content="r" * 10)

    class _FileCapableEvaluator:
        """Recording evaluator that claims file upload support."""

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.paths_seen: tuple[Path, ...] = ()

        def supports_file_upload(self) -> bool:
            return True

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
            self.paths_seen = tuple(merge_paths)
            self.calls.append({"level": level, "merge_paths": tuple(merge_paths)})
            return ConformanceEvaluation(
                verdict=ConformanceVerdict.PASS,
                reason="ok",
                description="ok",
            )

    evaluator = _FileCapableEvaluator()
    # Construct the service with a small custom threshold (simulating
    # project_config.pipeline.conformance.file_upload_threshold = 5)
    service = ConformanceService(
        evaluator,
        emitter=MemoryEmitter(),
        file_upload_threshold=5,
        hard_limit=500_000,
    )

    result = service.check_fidelity(
        FidelityLevel.IMPL,
        _context(tmp_path, subject="s" * 20),  # 20 bytes > threshold 5
    )

    assert result.conformance_verdict is ConformanceVerdict.PASS
    assert len(evaluator.paths_seen) == 2  # tier-2 files were created and passed
    assert evaluator.calls[0]["level"] is FidelityLevel.IMPL


# ---------------------------------------------------------------------------
# AG3-063 Remediation: ERROR 3 — No DOC_FIDELITY bypass in layer2_integration
# ---------------------------------------------------------------------------


def test_layer2_integration_no_doc_fidelity_bypass_when_result_is_none() -> None:
    """ERROR 3 fix: when doc_fidelity_result is None, _run_impl_fidelity returns
    a BLOCKING LayerResult rather than calling runner.evaluate(DOC_FIDELITY)
    directly (which would bypass ConformanceService.check_fidelity).
    """
    from agentkit.verify_system.llm_evaluator.bundle import ReviewBundle
    from agentkit.verify_system.llm_evaluator.layer2_integration import (
        _run_impl_fidelity,
    )
    from agentkit.verify_system.protocols import Severity

    class _NeverCalledRunner:
        """Runner that must never be called for DOC_FIDELITY in this test."""

        def evaluate(self, *args: object, **kwargs: object) -> object:
            raise AssertionError(
                "runner.evaluate() was called — DOC_FIDELITY bypass still exists"
            )

    bundle = ReviewBundle(
        story_id="TEST-003",
        story_brief_excerpt="brief",
        acceptance_criteria=[],
        diff_summary="diff",
        diff_content="content",
        concept_refs=[],
        previous_findings=None,
        qa_cycle_round=1,
    )

    result = _run_impl_fidelity(
        _NeverCalledRunner(),  # type: ignore[arg-type]
        bundle=bundle,
        qa_cycle_round=1,
        previous_findings=(),
        doc_fidelity_result=None,
    )

    # Must be BLOCKING (fail-closed) and must NOT have called the runner
    assert result.passed is False
    blocking = [f for f in result.findings if f.severity is Severity.BLOCKING]
    assert blocking, "Expected at least one BLOCKING finding"
    assert any("check_fidelity" in f.message for f in blocking)
