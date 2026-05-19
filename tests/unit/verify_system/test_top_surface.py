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
    VerifyContextBundle,
    VerifySystem,
    VerifyTargetUnknownError,
)
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import Finding, LayerResult, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

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

    def evaluate(self, ctx: object, story_dir: Path) -> LayerResult:
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
    layer_3: _RecordingLayer | AdversarialChallenger | None = None,
    manager: _RecordingArtifactManager | None = None,
    max_major_findings: int = 0,
) -> tuple[VerifySystem, _RecordingArtifactManager]:
    recording_manager = manager or _RecordingArtifactManager()
    vs = VerifySystem(
        layer_1=layer_1 or _RecordingLayer("structural"),
        layer_2=layer_2 or _RecordingLayer("semantic"),
        layer_3=layer_3 or _RecordingLayer("adversarial"),
        policy_engine=PolicyEngine(max_major_findings=max_major_findings),
        artifact_manager=recording_manager,
    )
    return vs, recording_manager


# ---------------------------------------------------------------------------
# Tests: happy path -- Implementation (all 4 layers)
# ---------------------------------------------------------------------------


class TestRunQaSubflowImplementationHappyPath:
    """Happy path: IMPLEMENTATION_INITIAL -> all 4 layers called in order."""

    def test_returns_pass_when_all_layers_pass(self, tmp_path: Path) -> None:
        vs, _ = _make_system()
        verdict = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert verdict is PolicyVerdict.PASS

    def test_all_three_data_layers_called_in_order(self, tmp_path: Path) -> None:
        """Layer execution order: structural -> semantic -> adversarial."""
        call_log: list[str] = []

        class _OrderedLayer(_RecordingLayer):
            def evaluate(self, ctx: object, story_dir: Path) -> LayerResult:
                call_log.append(self._name)
                return super().evaluate(ctx, story_dir)

        l1 = _OrderedLayer("structural")
        l2 = _OrderedLayer("semantic")
        l3 = _OrderedLayer("adversarial")
        vs, _ = _make_system(layer_1=l1, layer_2=l2, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert call_log == ["structural", "semantic", "adversarial"]

    def test_each_data_layer_called_exactly_once(self, tmp_path: Path) -> None:
        l1 = _RecordingLayer("structural")
        l2 = _RecordingLayer("semantic")
        l3 = _RecordingLayer("adversarial")
        vs, _ = _make_system(layer_1=l1, layer_2=l2, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert len(l1.calls) == 1
        assert len(l2.calls) == 1
        assert len(l3.calls) == 1

    def test_artifact_manager_receives_six_writes(self, tmp_path: Path) -> None:
        """AG3-026 §AK7: Layer 1 (1) + Layer 2 (3) + Layer 3 (1) + Policy (1) = 6."""
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert len(manager.written_envelopes) == 6  # noqa: PLR2004

    def test_artifact_stages_match_fk27(self, tmp_path: Path) -> None:
        """AG3-026 §AK7: stages decken alle sechs FK-27 §27.7-Artefakte ab."""
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

        verdict = vs.run_qa_subflow(
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
        assert verdict is PolicyVerdict.PASS

    def test_implementation_remediation_also_writes_six(
        self, tmp_path: Path
    ) -> None:
        vs, manager = _make_system()

        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
            target=_make_target(),
        )

        assert len(manager.written_envelopes) == 6  # noqa: PLR2004


# ---------------------------------------------------------------------------
# Tests: happy path -- Exploration (2 layers: LLM + Policy)
# ---------------------------------------------------------------------------


class TestRunQaSubflowExplorationHappyPath:
    """Happy path: EXPLORATION_INITIAL -> Layer 2 (LLM) + Policy only."""

    def test_returns_pass_when_layers_pass(self, tmp_path: Path) -> None:
        vs, _ = _make_system()
        verdict = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.EXPLORATION_INITIAL,
            target=_make_target(ArtifactClass.ENTWURF),
        )
        assert verdict is PolicyVerdict.PASS

    def test_only_llm_layer_called_not_structural_not_adversarial(
        self, tmp_path: Path
    ) -> None:
        l1 = _RecordingLayer("structural")
        l2 = _RecordingLayer("semantic")
        l3 = _RecordingLayer("adversarial")
        vs, _ = _make_system(layer_1=l1, layer_2=l2, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.EXPLORATION_INITIAL,
            target=_make_target(ArtifactClass.ENTWURF),
        )

        assert len(l1.calls) == 0, "Structural layer must NOT run for Exploration"
        assert len(l2.calls) == 1, "LLM-Evaluator layer must run for Exploration"
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
        verdict = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert verdict is PolicyVerdict.FAIL

    def test_llm_layer_exception_returns_fail(self, tmp_path: Path) -> None:
        """LLM layer raising ValueError -> PolicyVerdict.FAIL."""
        exploding_l2 = _RecordingLayer(
            "semantic",
            raise_exc=ValueError("LLM unavailable"),
        )
        vs, _ = _make_system(layer_2=exploding_l2)
        verdict = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        assert verdict is PolicyVerdict.FAIL

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
        """Even if structural layer fails, LLM and adversarial still run."""
        call_log: list[str] = []

        class _LoggingLayer(_RecordingLayer):
            def evaluate(self, ctx: object, story_dir: Path) -> LayerResult:
                call_log.append(self._name)
                return super().evaluate(ctx, story_dir)

        exploding_l1 = _RecordingLayer(
            "structural",
            raise_exc=RuntimeError("disk full"),
        )
        l2 = _LoggingLayer("semantic")
        l3 = _LoggingLayer("adversarial")
        vs, _ = _make_system(layer_1=exploding_l1, layer_2=l2, layer_3=l3)
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        # LLM and adversarial layers still execute after structural failure.
        assert "semantic" in call_log
        assert "adversarial" in call_log

    def test_return_type_is_exactly_policy_verdict(self, tmp_path: Path) -> None:
        """run_qa_subflow always returns a PolicyVerdict instance (AK2, AK11)."""
        vs, _ = _make_system()
        result = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert isinstance(result, PolicyVerdict)

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
        verdict = vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )
        assert verdict is PolicyVerdict.FAIL


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

        from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
        from agentkit.pipeline_engine.phase_envelope.runtime import (
            PhaseOrigin,
            RuntimeMetadata,
        )
        from agentkit.story_context_manager.models import (
            ImplementationPayload,
            PhaseName,
            PhaseState,
            PhaseStatus,
        )

        qa_cycle_id = "a1b2c3d4e5f6"
        epoch = datetime(2026, 5, 19, 14, 0, 0, tzinfo=UTC)
        fingerprint = "f" * 64
        impl_payload = ImplementationPayload(
            qa_cycle_id=qa_cycle_id,
            qa_cycle_round=2,
            evidence_epoch=epoch,
            evidence_fingerprint=fingerprint,
        )
        state = PhaseState(
            story_id="TEST-001",
            phase=PhaseName.IMPLEMENTATION,
            status=PhaseStatus.IN_PROGRESS,
            payload=impl_payload,
        )
        runtime = RuntimeMetadata(
            origin=PhaseOrigin.NEW,
            loaded_at=None,
            process_id=1,
            worker_id=None,
        )
        envelope = PhaseEnvelope(state=state, runtime=runtime)
        bundle = VerifyContextBundle(
            run_id="run-test-001",
            story_dir=tmp_path,
            phase_envelope=envelope,
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

    def test_payload_omits_qa_cycle_fields_when_envelope_missing(
        self, tmp_path: Path
    ) -> None:
        """Ohne ``phase_envelope`` werden keine Cycle-Felder eingebettet."""
        vs, manager = _make_system()
        vs.run_qa_subflow(
            ctx=_make_bundle(tmp_path),
            story_id="TEST-001",
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_make_target(),
        )

        for env in manager.written_envelopes:
            assert env.payload is not None
            assert "qa_cycle_id" not in env.payload
            assert "qa_cycle_round" not in env.payload
            assert "evidence_epoch" not in env.payload
            assert "evidence_fingerprint" not in env.payload


class TestCreateDefaultFailClosed:
    """AG3-026 §2.1.4 + Re-Review-Befund 3: fail-closed bei manager=None."""

    def test_create_default_without_manager_raises(self) -> None:
        from agentkit.verify_system.errors import VerifySystemError

        with pytest.raises(VerifySystemError, match="ArtifactManager"):
            VerifySystem.create_default(artifact_manager=None)  # type: ignore[arg-type]
