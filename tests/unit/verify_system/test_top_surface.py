"""Unit tests for VerifySystem.run_qa_subflow() -- AG3-026 Top-Surface.

Tests:
  - happy path Implementation (all 4 layers in order)
  - happy path Exploration (LLM-Evaluator + Policy, 2 layers)
  - fail-closed: unknown target_type -> VerifyTargetUnknownError
  - Layer exception -> PolicyVerdict.FAIL (BLOCKING finding)

Uses Recording-Test-Doubles (no MagicMock) per AG3-026 §Station 4.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import (
    ArtifactEnvelope,
    ArtifactManager,
    ArtifactReference,
)
from agentkit.core_types import ArtifactClass, PolicyVerdict, QaContext, Severity
from agentkit.verify_system import (
    QaSubflowOutcome,
    VerifyContextBundle,
    VerifySystem,
    VerifyTargetUnknownError,
)
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import Finding, LayerResult, TrustClass

if TYPE_CHECKING:
    from agentkit.verify_system.adversarial_orchestrator.challenger import (
        AdversarialChallenger,
    )
    from agentkit.verify_system.llm_evaluator.reviewer import SemanticReviewer
    from agentkit.verify_system.structural.checker import StructuralChecker


# ---------------------------------------------------------------------------
# Recording test doubles
# ---------------------------------------------------------------------------


class _RecordingLayer:
    """A QALayer test double that records evaluate() calls in order.

    Does NOT inherit from any concrete class -- satisfies the QALayer
    protocol structurally. No MagicMock (AG3-026 §Station 4).
    """

    def __init__(
        self,
        name: str,
        result: LayerResult | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._name = name
        self._result = result or LayerResult(
            layer=name,
            passed=True,
            findings=(),
        )
        self._raise_exc = raise_exc
        self.calls: list[tuple[object, Path]] = []

    @property
    def name(self) -> str:
        return self._name

    def evaluate(
        self,
        ctx: object,
        story_dir: Path,
        *,
        review_input: object = None,
    ) -> LayerResult:
        self.calls.append((ctx, story_dir))
        if self._raise_exc is not None:
            raise self._raise_exc  # noqa: RSE102
        return self._result


class _RecordingArtifactManager(ArtifactManager):
    """An ArtifactManager test double that records write() calls.

    Extends ArtifactManager to satisfy the type checker. Bypasses the
    constructor (no real repository/validator needed). Returns a synthetic
    ArtifactReference on each write. Never touches the filesystem.
    """

    def __init__(self) -> None:
        # Bypass the real ArtifactManager.__init__ intentionally.
        self.written_envelopes: list[ArtifactEnvelope] = []

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        self.written_envelopes.append(envelope)
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"recording/{envelope.stage}/{envelope.attempt}",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _git_worktree(tmp_path: Path) -> None:
    """Initialise a real git worktree in ``tmp_path`` (no fail-open).

    AG3-041 E2: the QA-subflow now ALWAYS starts a QA cycle on the first call
    (FK-27 §27.2.2 ``idle -> awaiting_qa``), which computes the deterministic
    ``evidence_fingerprint`` over the story branch's git delta. The productive
    ``story_dir`` is always a git worktree; these unit tests therefore run
    against a REAL repo rather than letting the fingerprint fail closed on a
    non-repo path. A single base commit on ``main`` + a story branch suffices.
    """
    import subprocess

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        )

    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Test")
    (tmp_path / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", ".")
    _git("commit", "-m", "base")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bundle(tmp_path: Path, *, attempt: int = 1) -> VerifyContextBundle:
    return VerifyContextBundle(
        run_id="run-test-001",
        story_dir=tmp_path,
        phase_envelope=None,
        attempt=attempt,
    )


def _make_target(
    artifact_class: ArtifactClass = ArtifactClass.WORKER,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_class=artifact_class,
        story_id="TEST-001",
        run_id="run-test-001",
        record_key="envelopes/worker/TEST-001/1",
    )


def _make_system(
    *,
    layer_1: _RecordingLayer | StructuralChecker | None = None,
    layer_2: _RecordingLayer | SemanticReviewer | None = None,
    layer_2a: _RecordingLayer | None = None,
    layer_2b: _RecordingLayer | None = None,
    layer_2c: _RecordingLayer | None = None,
    layer_3: _RecordingLayer | AdversarialChallenger | None = None,
    manager: _RecordingArtifactManager | None = None,
    max_major_findings: int = 0,
    story_context_port: _SpyStoryContextPort | None = None,
    review_completion_sink: object | None = None,
) -> tuple[VerifySystem, _RecordingArtifactManager]:
    recording_manager = manager or _RecordingArtifactManager()
    # W1: three distinct Layer-2 reviewers.
    # Backward compat: if layer_2 is given, use it for layer_2a (primary reviewer).
    _l2a = layer_2a or layer_2 or _RecordingLayer("qa_review")
    _l2b = layer_2b or _RecordingLayer("semantic_review")
    _l2c = layer_2c or _RecordingLayer("doc_fidelity")
    kwargs: dict[str, object] = {}
    if story_context_port is not None:
        kwargs["story_context_port"] = story_context_port
    if review_completion_sink is not None:
        kwargs["review_completion_sink"] = review_completion_sink
    vs = VerifySystem(
        layer_1=layer_1 or _RecordingLayer("structural"),
        layer_2a=_l2a,
        layer_2b=_l2b,
        layer_2c=_l2c,
        layer_3=layer_3 or _RecordingLayer("adversarial"),
        policy_engine=PolicyEngine(max_major_findings=max_major_findings),
        artifact_manager=recording_manager,
        **kwargs,  # type: ignore[arg-type]
    )
    return vs, recording_manager


# ---------------------------------------------------------------------------
# Tests: happy path -- Implementation (all 4 layers)
# ---------------------------------------------------------------------------


class TestRunQaSubflowImplementationHappyPath:
    """Happy path: IMPLEMENTATION_INITIAL -> all 4 layers called in order."""

    def test_returns_pass_when_all_layers_pass(self, tmp_path: Path) -> None:
        vs, _ = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert isinstance(outcome, QaSubflowOutcome)
        assert outcome.verdict is PolicyVerdict.PASS

    def test_all_five_data_layers_called_in_order(self, tmp_path: Path) -> None:
        """Layer execution order: structural -> qa_review -> semantic_review -> doc_fidelity -> adversarial."""
        call_log: list[str] = []

        class _OrderedLayer(_RecordingLayer):
            def evaluate(
                self,
                ctx: object,
                story_dir: Path,
                *,
                review_input: object = None,
            ) -> LayerResult:
                call_log.append(self._name)
                return super().evaluate(ctx, story_dir, review_input=review_input)

        l1 = _OrderedLayer("structural")
        l2a = _OrderedLayer("qa_review")
        l2b = _OrderedLayer("semantic_review")
        l2c = _OrderedLayer("doc_fidelity")
        l3 = _OrderedLayer("adversarial")
        vs, _ = _make_system(layer_1=l1, layer_2a=l2a, layer_2b=l2b, layer_2c=l2c, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert call_log == [
            "structural", "qa_review", "semantic_review", "doc_fidelity", "adversarial"
        ]

    def test_each_data_layer_called_exactly_once(self, tmp_path: Path) -> None:
        l1 = _RecordingLayer("structural")
        l2a = _RecordingLayer("qa_review")
        l2b = _RecordingLayer("semantic_review")
        l2c = _RecordingLayer("doc_fidelity")
        l3 = _RecordingLayer("adversarial")
        vs, _ = _make_system(layer_1=l1, layer_2a=l2a, layer_2b=l2b, layer_2c=l2c, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert len(l1.calls) == 1
        assert len(l2a.calls) == 1
        assert len(l2b.calls) == 1
        assert len(l2c.calls) == 1
        assert len(l3.calls) == 1

    def test_artifact_manager_receives_seven_writes(self, tmp_path: Path) -> None:
        """Layer 1 (1) + Layer 2 (3) + Layer 3 (1) + sonarqube_gate (1) + Policy (1) = 7.

        AG3-052 / FK-33 §33.8.3: the sonarqube_gate stage is sequenced
        after adversarial and writes its own ``sonarqube_gate.json``
        envelope (here a SKIP, since the default port resolves
        NOT_APPLICABLE — no Sonar wired).
        """
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert len(manager.written_envelopes) == 7  # noqa: PLR2004

    def test_artifact_stages_match_fk27(self, tmp_path: Path) -> None:
        """AG3-026 §AK7 + AG3-052: stages cover the seven QA artefacts."""
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        stages = {e.stage for e in manager.written_envelopes}
        assert stages == {
            "qa-layer-structural",
            "qa-layer-qa-review",
            "qa-layer-semantic-review",
            "qa-layer-doc-fidelity",
            "qa-layer-adversarial",
            "qa-sonarqube-gate",
            "qa-policy-decision",
        }

    def test_layer_2_writes_three_distinct_artifacts(
        self, tmp_path: Path
    ) -> None:
        """AG3-026 §AK7: Layer 2 erzeugt qa_review/semantic_review/doc_fidelity."""
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        layer_2_producers = {
            e.producer.name
            for e in manager.written_envelopes
            if e.stage.startswith("qa-layer-")
            and e.stage not in {"qa-layer-structural", "qa-layer-adversarial"}
        }
        assert layer_2_producers == {
            "verify-system.layer-2-qa-review",
            "verify-system.layer-2-semantic-review",
            "verify-system.layer-2-doc-fidelity",
        }

    def test_policy_uses_decision_filename(self, tmp_path: Path) -> None:
        """AG3-026 §AK7: Policy schreibt unter ``decision.json`` (kein verify- Prefix)."""
        vs, manager = _make_system()

        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # Producer + Stage des Policy-Envelopes pinnen den Filename indirekt.
        policy_envs = [
            e for e in manager.written_envelopes
            if e.stage == "qa-policy-decision"
        ]
        assert len(policy_envs) == 1
        assert policy_envs[0].producer.name == "verify-system.layer-4-policy"
        assert outcome.verdict is PolicyVerdict.PASS

    def test_implementation_remediation_also_writes_seven(
        self, tmp_path: Path
    ) -> None:
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
            target=_make_target(),
        )

        assert len(manager.written_envelopes) == 7  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Tests: happy path -- Exploration (2 layers: LLM + Policy)
# ---------------------------------------------------------------------------


class TestRunQaSubflowExplorationHappyPath:
    """Happy path: EXPLORATION_INITIAL -> Layer 2 (LLM) + Policy only."""

    def test_returns_pass_when_layers_pass(self, tmp_path: Path) -> None:
        vs, _ = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.EXPLORATION_INITIAL,
            target=_make_target(ArtifactClass.ENTWURF),
        )
        assert outcome.verdict is PolicyVerdict.PASS

    def test_only_llm_layers_called_not_structural_not_adversarial(
        self, tmp_path: Path
    ) -> None:
        l1 = _RecordingLayer("structural")
        l2a = _RecordingLayer("qa_review")
        l2b = _RecordingLayer("semantic_review")
        l2c = _RecordingLayer("doc_fidelity")
        l3 = _RecordingLayer("adversarial")
        vs, _ = _make_system(layer_1=l1, layer_2a=l2a, layer_2b=l2b, layer_2c=l2c, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.EXPLORATION_INITIAL,
            target=_make_target(ArtifactClass.ENTWURF),
        )

        assert len(l1.calls) == 0, "Structural layer must NOT run for Exploration"
        assert len(l2a.calls) == 1, "LLM-Evaluator qa_review must run for Exploration"
        assert len(l2b.calls) == 1, "LLM-Evaluator semantic_review must run for Exploration"
        assert len(l2c.calls) == 1, "LLM-Evaluator doc_fidelity must run for Exploration"
        assert len(l3.calls) == 0, "Adversarial layer must NOT run for Exploration"

    def test_artifact_manager_receives_four_writes(self, tmp_path: Path) -> None:
        """AG3-026 §AK7: Layer 2 (3 Artefakte) + Policy (1) = 4 Envelopes."""
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.EXPLORATION_INITIAL,
            target=_make_target(ArtifactClass.ENTWURF),
        )

        assert len(manager.written_envelopes) == 4  # noqa: PLR2004

    def test_exploration_remediation_also_writes_four(
        self, tmp_path: Path
    ) -> None:
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.EXPLORATION_REMEDIATION,
            target=_make_target(ArtifactClass.ENTWURF),
        )

        assert len(manager.written_envelopes) == 4  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Tests: fail-closed -- unknown target_type
# ---------------------------------------------------------------------------


class TestRunQaSubflowFailClosed:
    """Fail-closed behaviour for unresolvable targets."""

    def test_unknown_artifact_class_raises_verify_target_unknown_error(
        self, tmp_path: Path
    ) -> None:
        """artifact_class with no VerifyTargetType mapping -> VerifyTargetUnknownError."""
        vs, _ = _make_system()
        # TELEMETRY is not a valid QA-subflow target.
        bad_target = ArtifactReference(
            artifact_class=ArtifactClass.TELEMETRY,
            story_id="TEST-001",
            run_id="run-001",
            record_key="telemetry/foo/1",
        )

        with pytest.raises(VerifyTargetUnknownError):
            vs.run_qa_subflow(
                ctx=_make_bundle(tmp_path),
                story_id="TEST-001",
                qa_context=QaContext.IMPLEMENTATION_INITIAL,
                target=bad_target,
            )

    def test_governance_artifact_class_raises_verify_target_unknown_error(
        self, tmp_path: Path
    ) -> None:
        vs, _ = _make_system()
        bad_target = ArtifactReference(
            artifact_class=ArtifactClass.GOVERNANCE,
            story_id="TEST-001",
            run_id="run-001",
            record_key="governance/foo/1",
        )

        with pytest.raises(VerifyTargetUnknownError):
            vs.run_qa_subflow(
                ctx=_make_bundle(tmp_path),
                story_id="TEST-001",
                qa_context=QaContext.IMPLEMENTATION_INITIAL,
                target=bad_target,
            )

    def test_pipeline_artifact_class_raises_verify_target_unknown_error(
        self, tmp_path: Path
    ) -> None:
        vs, _ = _make_system()
        bad_target = ArtifactReference(
            artifact_class=ArtifactClass.PIPELINE,
            story_id="TEST-001",
            run_id="run-001",
            record_key="pipeline/foo/1",
        )

        with pytest.raises(VerifyTargetUnknownError):
            vs.run_qa_subflow(
                ctx=_make_bundle(tmp_path),
                story_id="TEST-001",
                qa_context=QaContext.IMPLEMENTATION_INITIAL,
                target=bad_target,
            )


# ---------------------------------------------------------------------------
# Tests: Layer exception -> BLOCKING finding -> PolicyVerdict.FAIL
# ---------------------------------------------------------------------------


class TestRunQaSubflowLayerException:
    """Layer exceptions are wrapped in LayerExecutionError -> FAIL verdict."""

    def test_structural_layer_exception_returns_fail(self, tmp_path: Path) -> None:
        """Structural layer raising RuntimeError -> PolicyVerdict.FAIL."""
        exploding_l1 = _RecordingLayer(
            "structural",
            raise_exc=RuntimeError("disk exploded"),
        )
        vs, _ = _make_system(layer_1=exploding_l1)
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert outcome.verdict is PolicyVerdict.FAIL

    def test_llm_layer_exception_returns_fail(self, tmp_path: Path) -> None:
        """LLM layer raising ValueError -> PolicyVerdict.FAIL."""
        exploding_l2a = _RecordingLayer(
            "qa_review",
            raise_exc=ValueError("LLM unavailable"),
        )
        vs, _ = _make_system(layer_2a=exploding_l2a)
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert outcome.verdict is PolicyVerdict.FAIL

    def test_layer_exception_generates_blocking_finding_in_artifact(
        self, tmp_path: Path
    ) -> None:
        """When a layer raises, the written structural artefact payload contains
        a BLOCKING finding."""
        exploding_l1 = _RecordingLayer(
            "structural",
            raise_exc=RuntimeError("oops"),
        )
        vs, manager = _make_system(layer_1=exploding_l1)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # The structural envelope should exist and reflect FAIL.
        structural_envs = [
            e for e in manager.written_envelopes if e.stage == "qa-layer-structural"
        ]
        assert len(structural_envs) == 1
        from agentkit.core_types import EnvelopeStatus
        assert structural_envs[0].status is EnvelopeStatus.FAIL

    def test_execution_continues_after_one_layer_fails(
        self, tmp_path: Path
    ) -> None:
        """Even if structural layer fails, LLM reviewers and adversarial still run."""
        call_log: list[str] = []

        class _LoggingLayer(_RecordingLayer):
            def evaluate(
                self,
                ctx: object,
                story_dir: Path,
                *,
                review_input: object = None,
            ) -> LayerResult:
                call_log.append(self._name)
                return super().evaluate(ctx, story_dir, review_input=review_input)

        exploding_l1 = _RecordingLayer(
            "structural",
            raise_exc=RuntimeError("disk full"),
        )
        l2a = _LoggingLayer("qa_review")
        l2b = _LoggingLayer("semantic_review")
        l2c = _LoggingLayer("doc_fidelity")
        l3 = _LoggingLayer("adversarial")
        vs, _ = _make_system(
            layer_1=exploding_l1, layer_2a=l2a, layer_2b=l2b, layer_2c=l2c, layer_3=l3
        )
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # All LLM reviewers and adversarial layer still execute after structural failure.
        assert "qa_review" in call_log
        assert "semantic_review" in call_log
        assert "doc_fidelity" in call_log
        assert "adversarial" in call_log

    def test_return_type_is_qa_subflow_outcome(self, tmp_path: Path) -> None:
        """run_qa_subflow returns QaSubflowOutcome (AG3-026 Pass-2 §Befund-A)."""
        vs, _ = _make_system()
        result = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert isinstance(result, QaSubflowOutcome)
        assert isinstance(result.verdict, PolicyVerdict)

    def test_return_type_is_fail_when_finding_is_blocking(
        self, tmp_path: Path
    ) -> None:
        """BLOCKING findings in layer result -> FAIL verdict."""
        blocking_result = LayerResult(
            layer="structural",
            passed=False,
            findings=(
                Finding(
                    layer="structural",
                    check="context_exists",
                    severity=Severity.BLOCKING,
                    message="story dir missing",
                    trust_class=TrustClass.SYSTEM,
                ),
            ),
        )
        l1 = _RecordingLayer("structural", result=blocking_result)
        vs, _ = _make_system(layer_1=l1)
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert outcome.verdict is PolicyVerdict.FAIL


# ---------------------------------------------------------------------------
# Tests: AG3-026 Pass-2 -- QaSubflowOutcome carries VerifyDecision (Befund-A)
# ---------------------------------------------------------------------------


class TestQaSubflowOutcomeCarriesDecision:
    """run_qa_subflow returns QaSubflowOutcome with full VerifyDecision.

    Verifies Befund-A fix: outcome.decision.layer_results contains all
    layer results so FK-69 consumers can call record_layer_artifacts /
    record_verify_decision without a second layer-execution cycle.
    """

    def test_outcome_decision_has_layer_results(self, tmp_path: Path) -> None:
        """outcome.decision.layer_results has 6 entries for IMPLEMENTATION.

        1 structural + 3 layer-2 + 1 adversarial + 1 sonarqube_gate
        (AG3-052 / FK-33 §33.8.3).
        """
        vs, _ = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        from agentkit.verify_system.policy_engine.engine import VerifyDecision

        decision = outcome.decision
        assert isinstance(decision, VerifyDecision)
        assert len(decision.layer_results) == 6  # noqa: PLR2004  # 1+3+1+1

    def test_outcome_carries_artifact_refs(self, tmp_path: Path) -> None:
        """outcome.artifact_refs contains the seven QA artefact filenames."""
        vs, _ = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert set(outcome.artifact_refs) == {
            "structural.json",
            "qa_review.json",
            "semantic_review.json",
            "doc_fidelity.json",
            "adversarial.json",
            "sonarqube_gate.json",
            "decision.json",
        }

    def test_outcome_feedback_none_on_pass(self, tmp_path: Path) -> None:
        """outcome.feedback is None when verdict is PASS."""
        vs, _ = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert outcome.verdict is PolicyVerdict.PASS
        assert outcome.feedback is None

    def test_outcome_feedback_present_on_fail(self, tmp_path: Path) -> None:
        """outcome.feedback is RemediationFeedback when verdict is FAIL."""
        blocking_result = LayerResult(
            layer="structural",
            passed=False,
            findings=(
                Finding(
                    layer="structural",
                    check="context_exists",
                    severity=Severity.BLOCKING,
                    message="story dir missing",
                    trust_class=TrustClass.SYSTEM,
                ),
            ),
        )
        l1 = _RecordingLayer("structural", result=blocking_result)
        vs, _ = _make_system(layer_1=l1)
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert outcome.verdict is PolicyVerdict.FAIL
        assert outcome.feedback is not None
        from agentkit.verify_system.remediation.feedback import RemediationFeedback

        assert isinstance(outcome.feedback, RemediationFeedback)

    def test_outcome_attempt_nr_matches_bundle(self, tmp_path: Path) -> None:
        """outcome.attempt_nr == ctx.attempt."""
        vs, _ = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path, attempt=3),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert outcome.attempt_nr == 3  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Tests: AG3-026 Re-Review -- AK7 (6 Envelopes), AK8 (QA-Cycle), fail-closed
# ---------------------------------------------------------------------------


class TestAk8QaCycleFieldsInPayload:
    """AG3-026 §AK8: qa_cycle_id/qa_cycle_round/evidence_epoch/
    evidence_fingerprint aus ``ctx.phase_envelope`` werden in jede
    Envelope-Payload eingebettet (FK-27 §27.2.1).
    """

    def test_payload_carries_qa_cycle_fields_when_envelope_present(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime

        from agentkit.verify_system.contract import PhaseEnvelopeView

        qa_cycle_id = "a1b2c3d4e5f6"
        epoch = datetime(2026, 5, 19, 14, 0, 0, tzinfo=UTC)
        fingerprint = "f" * 64
        view = PhaseEnvelopeView(
            qa_cycle_id=qa_cycle_id,
            qa_cycle_round=2,
            evidence_epoch=epoch,
            evidence_fingerprint=fingerprint,
        )
        bundle = VerifyContextBundle(
            run_id="run-test-001",
            story_dir=tmp_path,
            phase_envelope=view,
            attempt=1,
        )

        vs, manager = _make_system()
        vs.run_qa_subflow(
            ctx=bundle,
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # Jede Envelope-Payload muss die vier QA-Zyklus-Felder tragen.
        for env in manager.written_envelopes:
            assert env.payload is not None
            assert env.payload["qa_cycle_id"] == qa_cycle_id
            assert env.payload["qa_cycle_round"] == 2  # noqa: PLR2004
            assert env.payload["evidence_epoch"] == epoch.isoformat()
            assert env.payload["evidence_fingerprint"] == fingerprint

    def test_idle_start_embeds_fresh_cycle_fields(
        self, tmp_path: Path
    ) -> None:
        """Ohne ``phase_envelope`` startet der Subflow einen Zyklus (E2).

        FK-27 §27.2.2 (``idle -> awaiting_qa``): der ERSTE QA-Subflow-Aufruf
        startet IMMER einen Zyklus (round 1, epoch 1) und bettet alle vier
        Identitaetsfelder in jede QA-Artefakt-Payload ein — kein Fail-open-
        Idle-Pass-through mehr (AG3-041 E2/E1).
        """
        vs, manager = _make_system()
        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # Outcome surfaces the freshly-started cycle identities (round 1).
        assert outcome.qa_cycle_round == 1
        assert outcome.qa_cycle_id is not None
        assert len(outcome.qa_cycle_id) == 12  # noqa: PLR2004
        assert outcome.evidence_epoch is not None
        assert outcome.evidence_fingerprint is not None
        assert len(outcome.evidence_fingerprint) == 64  # noqa: PLR2004

        for env in manager.written_envelopes:
            assert env.payload is not None
            assert env.payload["qa_cycle_id"] == outcome.qa_cycle_id
            assert env.payload["qa_cycle_round"] == 1
            assert env.payload["evidence_epoch"] == outcome.evidence_epoch.isoformat()
            assert env.payload["evidence_fingerprint"] == outcome.evidence_fingerprint


class TestCreateDefaultFailClosed:
    """AG3-026 §2.1.4 + Re-Review-Befund 3: fail-closed bei manager=None."""

    def test_create_default_without_manager_raises(self) -> None:
        from agentkit.verify_system.errors import VerifySystemError

        with pytest.raises(VerifySystemError, match="ArtifactManager"):
            VerifySystem.create_default(artifact_manager=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AG3-035 (echter Drift-Fix): StoryContext via injizierten Port, kein
# direkter state_backend.store-Import mehr in verify_system.
# ---------------------------------------------------------------------------


class _SpyStoryContextPort:
    """Records load() calls; returns a preconfigured StoryContext (or None).

    Satisfies ``verify_system.protocols.StoryContextQueryPort`` structurally.
    """

    def __init__(self, result: object = None) -> None:
        self._result = result
        self.calls: list[Path] = []

    def load(self, story_dir: Path) -> object:
        self.calls.append(story_dir)
        return self._result


class TestStoryContextPortInjection:
    """AG3-035: run_qa_subflow loest StoryContext via injizierten Port auf."""

    def test_run_qa_subflow_uses_injected_story_context_port(self, tmp_path: Path) -> None:
        spy = _SpyStoryContextPort(result=None)
        vs, _ = _make_system(story_context_port=spy)
        bundle = _make_bundle(tmp_path)

        vs.run_qa_subflow(
            ctx=bundle,
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # Der Port wurde genau einmal mit dem story_dir des Bundles aufgerufen.
        assert spy.calls == [bundle.story_dir]

    def test_create_default_defaults_to_null_story_context_port(self) -> None:
        from agentkit.verify_system.system import _NULL_STORY_CONTEXT_PORT

        vs = VerifySystem.create_default(artifact_manager=_RecordingArtifactManager())

        assert vs.story_context_port is _NULL_STORY_CONTEXT_PORT
        # No-op-Port liefert None -> _execute_layer faellt auf IMPLEMENTATION-Stub.
        assert vs.story_context_port.load(Path(".")) is None


# ---------------------------------------------------------------------------
# FIX-C: run_qa_subflow emits llm_call_complete AFTER each Layer-2 artefact
# write, per reviewer role (FK-27 §27.4.3 / §27.5.5) -> guard.multi_llm count.
# ---------------------------------------------------------------------------


class TestReviewCompletionEmission:
    """FIX-C: ``llm_call_complete`` is emitted after Layer-2 artefact writes."""

    def test_emits_completion_per_reviewer_role(self, tmp_path: Path) -> None:
        """Three Layer-2 writes -> three completion events with the right roles.

        FK-27 §27.4.3 Gate 2 counts ``llm_call_complete`` per mandatory reviewer
        role; the emission must carry the role the guard filters on
        (qa_review / semantic_review / doc_fidelity).
        """
        from agentkit.verify_system.review_completion import (
            RecordingReviewCompletionSink,
        )

        sink = RecordingReviewCompletionSink.empty()
        vs, _ = _make_system(review_completion_sink=sink)

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        roles = sorted(e.role for e in sink.events)
        assert roles == ["doc_fidelity", "qa_review", "semantic_review"]
        assert all(e.story_id == "TEST-001" for e in sink.events)
        # Each emission names the review artefact it followed (FK-27 §27.5.5).
        files = sorted(e.artifact_filename for e in sink.events)
        assert files == ["doc_fidelity.json", "qa_review.json", "semantic_review.json"]

    def test_failed_reviews_emit_no_mandatory_role(self, tmp_path: Path) -> None:
        """Failed Layer-2 reviewers do NOT emit any mandatory reviewer role.

        When the Layer-2 reviewers raise, ``_execute_layer`` writes a synthetic
        BLOCKING result whose layer name is the generic kind (``llm_evaluator``),
        not a mandatory role. The completion emissions therefore cover NONE of
        the mandatory roles (qa_review / semantic_review / doc_fidelity), so the
        run-scoped Gate-2 count stays at 0 per mandatory role and
        ``guard.multi_llm`` fails closed (FK-27 §27.4.3 / FK-37 §37.1.6).
        """
        from agentkit.verify_system.review_completion import (
            RecordingReviewCompletionSink,
        )

        sink = RecordingReviewCompletionSink.empty()
        boom = RuntimeError("reviewer crashed")
        vs, _ = _make_system(
            layer_2a=_RecordingLayer("qa_review", raise_exc=boom),
            layer_2b=_RecordingLayer("semantic_review", raise_exc=boom),
            layer_2c=_RecordingLayer("doc_fidelity", raise_exc=boom),
            review_completion_sink=sink,
        )

        outcome = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert outcome.verdict is PolicyVerdict.FAIL
        emitted_roles = {e.role for e in sink.events}
        mandatory = {"qa_review", "semantic_review", "doc_fidelity"}
        assert emitted_roles.isdisjoint(mandatory)
