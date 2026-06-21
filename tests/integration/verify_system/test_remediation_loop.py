"""Integration: QA-subflow remediation loop with QA-cycle advance + escalation.

AG3-041 §2.1.8 / AC6 / E6. Drives ``VerifySystem.run_qa_subflow`` across the
REAL idle -> start_cycle -> persist -> advance path against a REAL git repo
(only the QA layers are recording test doubles — the MOCKS-Ausnahme for the
layer evaluation surface). NO pre-injected QA-cycle identities: the first call
starts the cycle (FK-27 §27.2.2 ``idle -> awaiting_qa``); subsequent rounds feed
the persisted identities back (as the phase handler does), so the subflow
ADVANCES the cycle (``advance_qa_cycle``) and invalidates the prior artefacts.
Proves:

* idle -> start_cycle: first call starts round 1 and surfaces all four
  identities (qa_cycle_id, round, evidence_epoch, fingerprint);
* PASS  -> ``escalated == False`` (CONTINUE_TO_CLOSURE);
* FAIL below the round ceiling -> ``escalated == False`` (CONTINUE_REMEDIATION),
  and ``advance_qa_cycle`` between rounds moves the cycle-bound artefacts to
  ``stale/`` and bumps round/epoch;
* FAIL at/over the round ceiling -> ``escalated == True`` and ``verdict == FAIL``
  (hard, FK-27 §27.2.2 max_rounds_exceeded);
* ``closure_blocked`` via the REAL subflow: a previous-round finding still
  present in a remediation round is NOT_RESOLVED -> closure blocked (FK-34).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.artifacts import ArtifactEnvelope, ArtifactManager, ArtifactReference
from agentkit.backend.core_types import ArtifactClass, PolicyVerdict, QaContext
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system import VerifyContextBundle, VerifySystem
from agentkit.backend.verify_system.contract import PhaseEnvelopeView
from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine
from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.backend.verify_system.qa_cycle.invalidation import (
    RecordingArtifactInvalidationSink,
    qa_artifact_dir,
)
from agentkit.backend.verify_system.qa_cycle.lifecycle import QaCycleLifecycle
from agentkit.backend.verify_system.remediation.loop_counter import RemediationLoopController
from agentkit.backend.verify_system.stage_registry import StageRegistry
from integration.implementation_evidence_support import (
    GitDiffChangeEvidencePort,
    StaticStoryContextPort,
    write_implementation_qa_preconditions,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "AG3-041"
_MAX_ROUNDS = 3
_STRUCTURAL_STAGE_METADATA = {
    "stage_ids": tuple(
        stage.stage_id
        for stage in StageRegistry().layer1_stages_for(
            StoryType.IMPLEMENTATION, are_enabled=False
        )
    )
    + ("sonarqube_gate",)
}


def _story_context_port() -> StaticStoryContextPort:
    return StaticStoryContextPort(
        StoryContext(
            project_key="test-project",
            story_id=_STORY_ID,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        ),
        run_id="run-1",
    )


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "base"], root)
    _git(["update-ref", "refs/remotes/origin/main", "HEAD"], root)
    _git(["checkout", "-b", "story-branch"], root)
    (root / "feature.py").write_text("y = 2\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "feature"], root)
    write_implementation_qa_preconditions(
        root, story_id=_STORY_ID, run_id="run-1", project_root=root
    )


class _ConfigurableLayer:
    """QA layer that passes or fails deterministically per construction."""

    def __init__(self, name: str, *, fail: bool) -> None:
        self._name = name
        self._fail = fail

    @property
    def name(self) -> str:
        return self._name

    def evaluate(
        self, ctx: object, story_dir: Path, *, review_input: object = None
    ) -> LayerResult:  # noqa: ARG002
        if not self._fail:
            return LayerResult(
                layer=self._name,
                passed=True,
                findings=(),
                metadata=(
                    _STRUCTURAL_STAGE_METADATA if self._name == "structural" else {}
                ),
            )
        finding = Finding(
            layer=self._name,
            check="always_fails",
            severity=Severity.BLOCKING,
            message="seeded failure",
            trust_class=TrustClass.SYSTEM,
        )
        return LayerResult(
            layer=self._name,
            passed=False,
            findings=(finding,),
            metadata=(
                _STRUCTURAL_STAGE_METADATA if self._name == "structural" else {}
            ),
        )


class _SeveritySwitchLayer:
    """QA layer emitting the SAME check at a construction-time severity.

    Round 1 emits the check at ``BLOCKING`` (-> policy FAIL); a later round
    emits the same ``(layer, check)`` at a lower severity (``MINOR``) so the
    finding is PARTIALLY_RESOLVED while the policy verdict is PASS (no
    SYSTEM-blocking, no MAJOR). This is the ER1 fixture: PASS verdict +
    PARTIALLY_RESOLVED previous finding.
    """

    def __init__(self, name: str, *, severity: Severity) -> None:
        self._name = name
        self._severity = severity

    @property
    def name(self) -> str:
        return self._name

    def evaluate(
        self, ctx: object, story_dir: Path, *, review_input: object = None
    ) -> LayerResult:  # noqa: ARG002
        finding = Finding(
            layer=self._name,
            check="recurring_defect",
            severity=self._severity,
            message="recurring defect",
            trust_class=TrustClass.SYSTEM,
        )
        # passed mirrors the policy outcome: a non-blocking severity is a
        # warning-level PASS at the layer surface.
        return LayerResult(
            layer=self._name,
            passed=self._severity is not Severity.BLOCKING,
            findings=(finding,),
            metadata=(
                _STRUCTURAL_STAGE_METADATA if self._name == "structural" else {}
            ),
        )


class _RecordingArtifactManager(ArtifactManager):
    def __init__(self) -> None:
        self.written_envelopes: list[ArtifactEnvelope] = []

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        self.written_envelopes.append(envelope)
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"recording/{envelope.stage}/{envelope.attempt}",
        )

    def read_latest(self, **_kwargs: object) -> ArtifactEnvelope:
        # No adversarial artifact is written in these remediation scenarios ->
        # genuinely absent (ArtifactNotFoundError). The mandatory-target feedback
        # read is fail-closed (AG3-067 def-5): only a genuinely-absent artifact
        # means "no targets", so the double signals absence honestly.
        from agentkit.backend.artifacts import ArtifactNotFoundError

        raise ArtifactNotFoundError("no artifact recorded by the test double")


def _build_system(*, fail: bool, sink: RecordingArtifactInvalidationSink) -> VerifySystem:
    manager = _RecordingArtifactManager()
    layer = _ConfigurableLayer("structural", fail=fail)
    return VerifySystem(
        layer_1=layer,
        layer_2a=_ConfigurableLayer("qa_review", fail=False),
        layer_2b=_ConfigurableLayer("semantic_review", fail=False),
        layer_2c=_ConfigurableLayer("doc_fidelity", fail=False),
        layer_3=_ConfigurableLayer("adversarial", fail=False),
        policy_engine=PolicyEngine(max_major_findings=0),
        artifact_manager=manager,
        qa_cycle_lifecycle=QaCycleLifecycle(invalidation_sink=sink),
        remediation_loop_controller=RemediationLoopController(
            max_feedback_rounds=_MAX_ROUNDS
        ),
        story_context_port=_story_context_port(),
        implementation_change_evidence_port=GitDiffChangeEvidencePort(),
    )


def _build_system_with_layer1(
    *, layer1: object, sink: RecordingArtifactInvalidationSink
) -> VerifySystem:
    """Build a system whose structural (layer 1) is a caller-supplied double."""
    manager = _RecordingArtifactManager()
    return VerifySystem(
        layer_1=layer1,
        layer_2a=_ConfigurableLayer("qa_review", fail=False),
        layer_2b=_ConfigurableLayer("semantic_review", fail=False),
        layer_2c=_ConfigurableLayer("doc_fidelity", fail=False),
        layer_3=_ConfigurableLayer("adversarial", fail=False),
        policy_engine=PolicyEngine(max_major_findings=0),
        artifact_manager=manager,
        qa_cycle_lifecycle=QaCycleLifecycle(invalidation_sink=sink),
        remediation_loop_controller=RemediationLoopController(
            max_feedback_rounds=_MAX_ROUNDS
        ),
        story_context_port=_story_context_port(),
        implementation_change_evidence_port=GitDiffChangeEvidencePort(),
    )


def _target() -> ArtifactReference:
    return ArtifactReference(
        artifact_class=ArtifactClass.WORKER,
        story_id=_STORY_ID,
        run_id="run-1",
        record_key=f"envelopes/worker/{_STORY_ID}/1",
    )


def _idle_bundle(story_dir: Path, *, attempt: int) -> VerifyContextBundle:
    """A bundle with NO phase-envelope view (idle): forces start_cycle."""
    return VerifyContextBundle(
        run_id="run-1",
        story_dir=story_dir,
        phase_envelope=None,
        attempt=attempt,
        project_root=story_dir,
    )


def _view_from_outcome(outcome: object) -> PhaseEnvelopeView:
    """Re-build the phase-envelope view from a prior outcome (as the handler does)."""
    return PhaseEnvelopeView(
        qa_cycle_id=outcome.qa_cycle_id,  # type: ignore[attr-defined]
        qa_cycle_round=outcome.qa_cycle_round,  # type: ignore[attr-defined]
        evidence_epoch=outcome.evidence_epoch,  # type: ignore[attr-defined]
        evidence_fingerprint=outcome.evidence_fingerprint,  # type: ignore[attr-defined]
    )


class TestRemediationLoop:
    def test_idle_first_call_starts_cycle(self, tmp_path: Path) -> None:
        """E2/E6: the FIRST call from idle starts a cycle (no pre-injection)."""
        _init_repo(tmp_path)
        system = _build_system(
            fail=False, sink=RecordingArtifactInvalidationSink.empty()
        )
        outcome = system.run_qa_subflow(
            ctx=_idle_bundle(tmp_path, attempt=1),
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_target(),
        )
        assert outcome.qa_cycle_round == 1
        assert outcome.qa_cycle_id is not None
        assert len(outcome.qa_cycle_id) == 12  # noqa: PLR2004
        assert outcome.evidence_epoch is not None
        assert outcome.evidence_fingerprint is not None
        assert len(outcome.evidence_fingerprint) == 64  # noqa: PLR2004

    def test_pass_is_not_escalated(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        system = _build_system(fail=False, sink=RecordingArtifactInvalidationSink.empty())
        outcome = system.run_qa_subflow(
            ctx=_idle_bundle(tmp_path, attempt=1),
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_target(),
        )
        assert outcome.verdict is PolicyVerdict.PASS
        assert outcome.escalated is False

    def test_fail_below_max_not_escalated(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        system = _build_system(fail=True, sink=RecordingArtifactInvalidationSink.empty())
        outcome = system.run_qa_subflow(
            ctx=_idle_bundle(tmp_path, attempt=1),
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_target(),
        )
        assert outcome.verdict is PolicyVerdict.FAIL
        assert outcome.escalated is False

    def test_advance_invalidates_between_rounds(self, tmp_path: Path) -> None:
        """E6: real idle -> start -> advance path; no pre-injected identities."""
        _init_repo(tmp_path)
        sink = RecordingArtifactInvalidationSink.empty()
        system = _build_system(fail=True, sink=sink)

        # Round 1 (idle -> start_cycle): FAIL below the ceiling.
        first = system.run_qa_subflow(
            ctx=_idle_bundle(tmp_path, attempt=1),
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_target(),
        )
        assert first.qa_cycle_round == 1
        assert first.escalated is False

        # Seed a prior cycle artefact so the advance has something to invalidate.
        base = qa_artifact_dir(tmp_path, _STORY_ID, project_root=tmp_path)
        base.mkdir(parents=True, exist_ok=True)
        (base / "structural.json").write_text("{}", encoding="utf-8")

        # Round 2 (remediation): feed the persisted identities back -> the
        # subflow ADVANCES the cycle (advance_qa_cycle), not a fresh start.
        bundle = VerifyContextBundle(
            run_id="run-1",
            story_dir=tmp_path,
            phase_envelope=_view_from_outcome(first),
            attempt=2,
            project_root=tmp_path,
        )
        second = system.run_qa_subflow(
            ctx=bundle,
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
            target=_target(),
        )
        # advance_qa_cycle moved the prior structural.json into stale/1.
        assert any(e.filename == "structural.json" for e in sink.events)
        assert (base / "stale" / "1" / "structural.json").is_file()
        # New cycle round is 2 (advanced from 1) with a fresh id.
        assert second.qa_cycle_round == 2  # noqa: PLR2004
        assert second.qa_cycle_id != first.qa_cycle_id

    def test_fail_at_max_escalates(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        system = _build_system(fail=True, sink=RecordingArtifactInvalidationSink.empty())
        # Active cycle at the ceiling-minus-one round, remediation context: the
        # advance bumps the round to the ceiling and a FAIL there escalates.
        view = PhaseEnvelopeView(
            qa_cycle_id="a1b2c3d4e5f6",
            qa_cycle_round=_MAX_ROUNDS - 1,
            evidence_epoch=datetime(2026, 5, 19, tzinfo=UTC),
            evidence_fingerprint="f" * 64,
        )
        bundle = VerifyContextBundle(
            run_id="run-1",
            story_dir=tmp_path,
            phase_envelope=view,
            attempt=_MAX_ROUNDS,
            project_root=tmp_path,
        )
        outcome = system.run_qa_subflow(
            ctx=bundle,
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
            target=_target(),
        )
        # advance bumps round (MAX-1) -> MAX, FAIL at the ceiling -> ESCALATE.
        assert outcome.qa_cycle_round == _MAX_ROUNDS
        assert outcome.escalated is True
        assert outcome.verdict is PolicyVerdict.FAIL

    def test_closure_blocked_when_previous_finding_unresolved(
        self, tmp_path: Path
    ) -> None:
        """E6: closure_blocked via the REAL subflow + FindingResolutionAssessor.

        A round-1 finding that is still present in the round-2 remediation run
        is NOT_RESOLVED -> the subflow sets ``closure_blocked`` (FK-34 / DK-04
        §4.6). The previous findings are fed in exactly as the phase handler
        carries them forward (``decision.all_findings``).
        """
        _init_repo(tmp_path)
        system = _build_system(fail=True, sink=RecordingArtifactInvalidationSink.empty())

        first = system.run_qa_subflow(
            ctx=_idle_bundle(tmp_path, attempt=1),
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_target(),
        )
        assert first.closure_blocked is False  # no previous findings yet

        bundle = VerifyContextBundle(
            run_id="run-1",
            story_dir=tmp_path,
            phase_envelope=_view_from_outcome(first),
            attempt=2,
            project_root=tmp_path,
        )
        second = system.run_qa_subflow(
            ctx=bundle,
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
            target=_target(),
            previous_findings=first.decision.all_findings,
        )
        # Same seeded failure recurs -> NOT_RESOLVED -> closure blocked.
        assert second.closure_blocked is True
        assert second.feedback is not None
        assert second.feedback.has_open_findings() is True

    def test_closure_blocked_on_pass_with_partially_resolved(
        self, tmp_path: Path
    ) -> None:
        """ER1: a PASS verdict with a PARTIALLY_RESOLVED previous finding still
        blocks closure (FK-34 §34.9.4) — via the REAL subflow, no pre-injection.

        Round 1 emits a BLOCKING ``recurring_defect`` (policy FAIL). Round 2
        emits the SAME ``(layer, check)`` at a *lower* severity (MINOR): the
        policy verdict is PASS (no SYSTEM-blocking, no MAJOR), so ``feedback``
        is ``None`` — yet the previous finding is PARTIALLY_RESOLVED and MUST
        block closure. Regression for the fail-open where ``closure_blocked``
        was derived from ``feedback`` (None on PASS) instead of the
        finding-resolution assessment.
        """
        _init_repo(tmp_path)
        sink = RecordingArtifactInvalidationSink.empty()

        # Round 1 (idle -> start): BLOCKING -> FAIL.
        system_round1 = _build_system_with_layer1(
            layer1=_SeveritySwitchLayer("structural", severity=Severity.BLOCKING),
            sink=sink,
        )
        first = system_round1.run_qa_subflow(
            ctx=_idle_bundle(tmp_path, attempt=1),
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_INITIAL,
            target=_target(),
        )
        assert first.verdict is PolicyVerdict.FAIL

        # Round 2 (remediation): SAME check at MINOR -> policy PASS, but the
        # previous finding is PARTIALLY_RESOLVED (lower severity).
        system_round2 = _build_system_with_layer1(
            layer1=_SeveritySwitchLayer("structural", severity=Severity.MINOR),
            sink=sink,
        )
        bundle = VerifyContextBundle(
            run_id="run-1",
            story_dir=tmp_path,
            phase_envelope=_view_from_outcome(first),
            attempt=2,
            project_root=tmp_path,
        )
        second = system_round2.run_qa_subflow(
            ctx=bundle,
            story_id=_STORY_ID,
            qa_context=QaContext.IMPLEMENTATION_REMEDIATION,
            target=_target(),
            previous_findings=first.decision.all_findings,
        )
        # PASS verdict -> no feedback object built ...
        assert second.verdict is PolicyVerdict.PASS
        assert second.feedback is None
        # ... but the PARTIALLY_RESOLVED previous finding still blocks closure.
        assert second.closure_blocked is True
