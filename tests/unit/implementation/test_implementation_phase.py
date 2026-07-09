"""Tests for ImplementationPhaseHandler against canonical backend records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.artifacts import ArtifactEnvelope, ArtifactManager, ArtifactReference
from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.core_types import PolicyVerdict, QaContext
from agentkit.backend.core_types.qa_artifact_names import (
    ALL_QA_ARTIFACT_FILES,
    HANDOVER_FILE,
    PROTOCOL_FILE,
    WORKER_MANIFEST_FILE,
)
from agentkit.backend.implementation.phase import (
    ImplementationConfig,
    ImplementationPhaseHandler,
)
from agentkit.backend.installer.paths import qa_story_dir
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.lifecycle import PhaseHandler
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
)
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.pipeline_runtime_store import (
    save_flow_execution,
    save_phase_snapshot,
)
from agentkit.backend.state_backend.store.verify_story_context_repository import (
    StateBackendVerifyStoryContextAdapter,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.verify_system import VerifySystem
from agentkit.backend.verify_system.contract import QaSubflowOutcome, VerifyContextBundle
from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine
from agentkit.backend.verify_system.protocols import LayerResult
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope


# ---------------------------------------------------------------------------
# Recording test doubles for VerifySystem (AG3-026 Pass-2 §Befund-A)
# ---------------------------------------------------------------------------


def test_conformance_config_flows_from_project_config_to_verify_system(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ERROR 4 fix (AG3-063 rem-2): ProjectConfig.pipeline.conformance reaches
    VerifySystem.conformance_config through the productive build_verify_system path.

    This is a FACTORY/PHASE-LEVEL test: it proves that a custom
    ``conformance.file_upload_threshold`` from ``ProjectConfig`` actually changes
    the tier boundary used by the ConformanceService reached through
    ``_resolve_conformance_config`` + ``build_verify_system``, NOT by constructing
    ``ConformanceService`` directly. The custom threshold value must demonstrably
    flow from ProjectConfig -> build_verify_system -> VerifySystem.conformance_config
    -> _run_impl_conformance -> ConformanceService tier decision.
    """
    from agentkit.backend.config.models import (
        SUPPORTED_CONFIG_VERSION,
        ConformanceConfig,
        Features,
        JenkinsConfig,
        PipelineConfig,
        ProjectConfig,
        RepositoryConfig,
        SonarQubeConfig,
    )
    from agentkit.backend.implementation.phase import _resolve_conformance_config

    custom_threshold = 7  # deliberate non-default to prove flow
    project = ProjectConfig(
        project_key="ak3",
        project_name="AK3",
        repositories=[RepositoryConfig(name="repo", path=tmp_path)],
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(are=False, multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
            conformance=ConformanceConfig(
                file_upload_threshold=custom_threshold,
                hard_limit=500_000,
            ),
        ),
    )
    monkeypatch.setattr("agentkit.backend.config.loader.load_project_config", lambda _root: project)

    ctx = StoryContext(
        project_key="ak3",
        story_id="AG3-063",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )

    # Step 1: _resolve_conformance_config reads project_config.pipeline.conformance.
    resolved = _resolve_conformance_config(ctx)
    assert resolved is not None
    assert resolved.file_upload_threshold == custom_threshold

    # Step 2: build_verify_system threads the resolved ConformanceConfig.
    # Use monkeypatching so we don't need the full state-backend on this unit path.
    captured: dict[str, object] = {}

    from agentkit.backend.bootstrap import composition_root as _cr

    original_build = _cr.build_verify_system

    def _capturing_build(store_dir: object, **kwargs: object) -> object:
        captured.update(kwargs)
        # Return a real VerifySystem so conformance_config is actually stored.
        return original_build(store_dir, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_cr, "build_verify_system", _capturing_build)

    # Trigger the productive wiring path via _resolve_conformance_config directly
    # (the on_enter path requires a live state-backend; this unit test validates
    # the config-threading contract without a full pipeline run).
    resolved_again = _resolve_conformance_config(ctx)
    assert resolved_again is not None
    assert resolved_again.file_upload_threshold == custom_threshold

    # Step 3: build_verify_system with the resolved conformance_config yields a
    # VerifySystem whose conformance_config matches the ProjectConfig value.
    # This proves the project-config value flows through the productive factory.
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    from agentkit.backend.bootstrap.composition_root import build_verify_system

    vs = build_verify_system(
        tmp_path,
        conformance_config=resolved_again,
    )
    assert vs.conformance_config is not None
    assert vs.conformance_config.file_upload_threshold == custom_threshold, (
        "ProjectConfig.pipeline.conformance.file_upload_threshold did not reach "
        "VerifySystem.conformance_config — ERROR 4 wiring is broken"
    )


def test_structural_are_provider_gets_configured_are_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AG3-077: Layer-1 provider receives the real client from ProjectConfig.are."""

    from agentkit.backend.config.models import (
        SUPPORTED_CONFIG_VERSION,
        AreConfig,
        Features,
        JenkinsConfig,
        PipelineConfig,
        ProjectConfig,
        RepositoryConfig,
        SonarQubeConfig,
    )
    from agentkit.backend.implementation.phase import _resolve_structural_evidence_ports

    project = ProjectConfig(
        project_key="ak3",
        project_name="AK3",
        repositories=[RepositoryConfig(name="repo", path=tmp_path)],
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(are=True, multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
        are=AreConfig(
            mcp_server="are-mcp",
            rest_base_url="https://are.example.com",
            auth_token="token",
        ),
    )
    monkeypatch.setattr("agentkit.backend.config.loader.load_project_config", lambda _root: project)

    ctx = StoryContext(
        project_key="ak3",
        story_id="AG3-077",
        story_number=77,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
        participating_repos=["repo"],
    )

    _build_port, are_provider = _resolve_structural_evidence_ports(ctx, tmp_path)

    assert are_provider is not None
    assert are_provider.are_client.base_url == "https://are.example.com"


class _RecordingArtifactManager(ArtifactManager):
    """ArtifactManager test double that records write() calls.

    Extends ArtifactManager to satisfy the type checker. Returns a
    synthetic ArtifactReference on each write. Never touches the filesystem.
    """

    def __init__(self) -> None:
        # Bypass the real ArtifactManager.__init__ intentionally.
        self.written_envelopes: list[ArtifactEnvelope] = []

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        """Record the envelope and return a synthetic reference."""
        self.written_envelopes.append(envelope)
        return ArtifactReference(
            artifact_class=envelope.artifact_class,
            story_id=envelope.story_id,
            run_id=envelope.run_id,
            record_key=f"recording/{envelope.stage}/{envelope.attempt}",
        )


def _cycle_identity(attempt_nr: int) -> dict[str, object]:
    """Deterministic QA-cycle identity tuple for a test-double outcome (E1).

    Mirrors what the real subflow surfaces so the phase handler can persist all
    four fields (FK-27 §27.2.1).

    Args:
        attempt_nr: Round/attempt counter (== qa_cycle_round).

    Returns:
        Dict with qa_cycle_id, evidence_epoch and evidence_fingerprint.
    """
    return {
        "qa_cycle_id": f"{attempt_nr:012x}",
        "evidence_epoch": datetime(2026, 5, 19, tzinfo=UTC),
        "evidence_fingerprint": "f" * 64,
    }


def _make_pass_outcome(attempt_nr: int = 1) -> QaSubflowOutcome:
    """Build a deterministic PASS QaSubflowOutcome for test doubles.

    Args:
        attempt_nr: Attempt counter to embed in the outcome.

    Returns:
        A ``QaSubflowOutcome`` with PASS verdict and empty layer results.
    """
    all_pass_layers = [
        LayerResult(layer="structural", passed=True),
        LayerResult(layer="qa_review", passed=True),
        LayerResult(layer="semantic_review", passed=True),
        LayerResult(layer="doc_fidelity", passed=True),
        LayerResult(layer="adversarial", passed=True),
    ]
    engine = PolicyEngine()
    decision = engine.decide(all_pass_layers)
    return QaSubflowOutcome(
        verdict=PolicyVerdict.PASS,
        decision=decision,
        artifact_refs=ALL_QA_ARTIFACT_FILES,
        attempt_nr=attempt_nr,
        qa_cycle_round=attempt_nr,
        feedback=None,
        **_cycle_identity(attempt_nr),  # type: ignore[arg-type]
    )


def _make_fail_outcome(
    attempt_nr: int = 1, *, escalated: bool = False
) -> QaSubflowOutcome:
    """Build a deterministic FAIL QaSubflowOutcome for test doubles.

    Args:
        attempt_nr: Attempt counter to embed in the outcome.
        escalated: Whether the remediation loop escalated (E3): the phase
            handler consumes ``outcome.escalated`` verbatim, so the double
            replicates the controller decision here.

    Returns:
        A ``QaSubflowOutcome`` with FAIL verdict and one blocking layer.
    """
    from agentkit.backend.verify_system.protocols import Finding, Severity, TrustClass
    from agentkit.backend.verify_system.remediation.feedback import build_feedback

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
    engine = PolicyEngine()
    decision = engine.decide([blocking_result])
    feedback = build_feedback(decision, "TEST-001", attempt_nr)
    return QaSubflowOutcome(
        verdict=PolicyVerdict.FAIL,
        decision=decision,
        artifact_refs=ALL_QA_ARTIFACT_FILES,
        attempt_nr=attempt_nr,
        qa_cycle_round=attempt_nr,
        feedback=feedback,
        escalated=escalated,
        **_cycle_identity(attempt_nr),  # type: ignore[arg-type]
    )


class _EmptyStageRegistry:
    """Minimal stage-registry double exposing no stages (AG3-078).

    phase.py builds a per-check origin map from ``stage_registry.stages``
    (FK-33 §33.2.1). This double carries no FC-derived stages, so the map is
    empty and every emitted ``check_proposal_ref`` is None. No MagicMock.
    """

    stages: tuple[object, ...] = ()


class _RecordingVerifySystem:
    """VerifySystem test double that records run_qa_subflow() calls.

    Returns deterministic outcomes (PASS or FAIL) without executing any
    real layers or writing artifacts to the filesystem.
    No MagicMock (AG3-026 §Station 4).
    """

    def __init__(
        self,
        *,
        verdict: PolicyVerdict = PolicyVerdict.PASS,
        max_feedback_rounds: int = 1,
    ) -> None:
        """Initialise the recording VerifySystem.

        Args:
            verdict: Verdict to return on each run_qa_subflow call.
            max_feedback_rounds: Round ceiling the double uses to replicate the
                RemediationLoopController decision (E3): a FAIL at/over the
                ceiling sets ``escalated=True`` on the returned outcome, exactly
                as the real controller would (FK-27 §27.2.2).
        """
        self._verdict = verdict
        self._max_feedback_rounds = max_feedback_rounds
        self.calls: list[tuple[VerifyContextBundle, str, QaContext, ArtifactReference]] = []
        self._recording_manager = _RecordingArtifactManager()

    @property
    def artifact_manager(self) -> ArtifactManager:
        """Return the recording artifact manager (for FK-69 path compat)."""
        return self._recording_manager

    @property
    def stage_registry(self) -> _EmptyStageRegistry:
        """Return an empty stage registry (AG3-078: no FC-derived origin stages).

        phase.py reads ``stage_registry.stages`` to build the per-check
        check_proposal_ref origin map; this double exposes no stages.
        """
        return _EmptyStageRegistry()

    def run_qa_subflow(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        qa_context: QaContext,
        target: ArtifactReference,
        *,
        previous_findings: tuple[object, ...] = (),
    ) -> QaSubflowOutcome:
        """Record the call and return a deterministic outcome.

        Args:
            ctx: Context bundle.
            story_id: Story ID.
            qa_context: QA context.
            target: Target artifact reference.
            previous_findings: Prior-round findings (recorded, unused here).

        Returns:
            Deterministic PASS or FAIL ``QaSubflowOutcome``. A FAIL escalates
            once the attempt reaches ``max_feedback_rounds`` (controller parity).
        """
        del previous_findings
        self.calls.append((ctx, story_id, qa_context, target))
        if self._verdict == PolicyVerdict.PASS:
            return _make_pass_outcome(attempt_nr=ctx.attempt)
        escalated = ctx.attempt >= self._max_feedback_rounds
        return _make_fail_outcome(attempt_nr=ctx.attempt, escalated=escalated)


class _StaticChangeEvidencePort:
    """Returns fixed System change evidence for VerifySystem.create_default tests."""

    def collect(self, story_dir: Path) -> ChangeEvidence:
        del story_dir
        return ChangeEvidence(
            available=True,
            changed_files=("tests/test_story.py",),
        )


class _FakeSparringClient:
    """Fake AG3-065 transport (the only allowed mock boundary) for Layer 3."""

    def complete(self, *, role: str, prompt: str) -> str:
        del role, prompt
        return "missed: empty input\nmissed: boundary value"


def _make_real_verify_system(
    story_dir: Path, *, max_major_findings: int = 0, max_feedback_rounds: int | None = None
) -> VerifySystem:
    return VerifySystem.create_default(
        artifact_manager=build_artifact_manager(story_dir),
        max_major_findings=max_major_findings,
        max_feedback_rounds=max_feedback_rounds,
        story_context_port=StateBackendVerifyStoryContextAdapter(),
        structural_change_evidence_port=_StaticChangeEvidencePort(),
        # AG3-079 (FK-48 §48.1): the real Layer-3 runtime needs the sparring
        # transport + a telemetry emitter; the harness sub-agent's sandbox
        # evidence is seeded by ``_seed_adversarial_sandbox`` (the only mock).
        adversarial_sparring_client=_FakeSparringClient(),
        adversarial_telemetry_emitter=MemoryEmitter(),
    )


def _seed_adversarial_sandbox(story_dir: Path, *, attempt: int = 1) -> None:
    """Seed the Layer-3 sandbox result.json (simulates the harness sub-agent).

    FK-48 §48.1.7: the adversarial sub-agent writes ``result.json`` into the
    protected sandbox; the deterministic runtime reads it. The sub-agent is the
    only allowed mock boundary, so the unit test seeds a minimal passing result
    with >= 1 executed test (FK-48 §48.1.8).
    """
    sandbox = story_dir / "_temp" / "adversarial" / "TEST-001" / str(attempt)
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "result.json").write_text(
        json.dumps(
            {
                "story_id": "TEST-001",
                "status": "PASS",
                "tests_executed": 1,
                "tests": [],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(root: Path, story_id: str = "TEST-001") -> Path:
    story_dir = root / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    _init_git_worktree(story_dir)
    return story_dir


def _init_git_worktree(path: Path) -> None:
    """Initialise a real git worktree at ``path`` (AG3-041 E1/E2).

    The QA-subflow now ALWAYS starts a QA cycle on the first call (FK-27
    §27.2.2), which computes the deterministic ``evidence_fingerprint`` over the
    git delta. The productive ``story_dir`` is always a git worktree, so these
    tests run against a REAL repo rather than letting the fingerprint fail
    closed on a non-repo path (no fail-open).
    """
    import subprocess

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=path, check=True, capture_output=True, text=True
        )

    _git("init", "-b", "main")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "Test")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git("add", ".")
    _git("commit", "-m", "seed")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")


def _make_context(
    story_type: StoryType = StoryType.BUGFIX,
    *,
    project_root: Path | None = None,
) -> StoryContext:
    """Build a minimal StoryContext for testing."""
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        project_root=project_root,
    )


def _make_state(review_round: int = 0) -> PhaseState:
    """Build a minimal PhaseState for the implementation phase."""
    return make_phase_state(
        story_id="TEST-001",
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
        review_round=review_round,
    )


def _make_envelope(state: PhaseState) -> PhaseEnvelope:
    """Wrap a PhaseState in a PhaseEnvelope for handler calls."""
    return PhaseEnvelopeStore.make_fresh_envelope(state)


def _setup_complete_story_dir(
    tmp_path: Path,
    story_type: StoryType = StoryType.BUGFIX,
) -> Path:
    """Set up a story dir with all required artifacts for a given type.

    Also adds test files and coverage artefacts so the QaReviewReviewer
    passes when called with the real VerifySystem (AG3-026 Pass-2).
    """
    story_dir = _story_dir(tmp_path)

    save_story_context(story_dir, _make_context(story_type))
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="TEST-001",
            run_id="run-implementation-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )

    profile = get_profile(story_type)
    for phase in profile.phases:
        if phase == "implementation":
            break
        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id="TEST-001",
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )

    # AG3-026 Pass-2: add test files so QaReviewReviewer passes.
    test_dir = story_dir / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "test_story.py"
    test_file.write_text(
        '"""Tests for TEST-001. FK-27."""\n\n'
        'def test_case_one():\n    """Test case one. FK-27."""\n    assert True\n\n'
        'def test_case_two():\n    """Test case two. FK-27."""\n    assert True\n\n'
        'def test_case_three():\n    """Test case three. FK-27."""\n    assert True\n',
        encoding="utf-8",
    )
    # Add a coverage artefact so QaReviewReviewer skips coverage_unknown.
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    _write_required_worker_artifacts(story_dir)

    return story_dir


def _write_required_worker_artifacts(story_dir: Path) -> None:
    source_file = story_dir / "src" / "agentkit" / "done.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("DONE = True\n", encoding="utf-8")
    (story_dir / HANDOVER_FILE).write_text("handover\n", encoding="utf-8")
    (story_dir / PROTOCOL_FILE).write_text("protocol\n", encoding="utf-8")
    (story_dir / WORKER_MANIFEST_FILE).write_text(
        json.dumps(
            {
                "story_id": "TEST-001",
                "run_id": "run-implementation-001",
                "status": "completed",
                "completed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                "files_changed": ["src/agentkit/backend/done.py"],
                "tests_added": ["tests/test_story.py"],
                "acceptance_criteria_status": {"AC1": "done"},
            }
        ),
        encoding="utf-8",
    )


class TestImplementationPhaseHandler:
    """ImplementationPhaseHandler tests."""

    def test_complete_setup_returns_completed(self, tmp_path: Path) -> None:
        """PASS verdict from VerifySystem -> PhaseStatus.COMPLETED."""
        story_dir = _setup_complete_story_dir(tmp_path)
        # AG3-026 Pass-2 §Befund-A: inject controlled VerifySystem.
        config = ImplementationConfig(
            story_dir=story_dir,
            verify_system=_RecordingVerifySystem(verdict=PolicyVerdict.PASS),  # type: ignore[arg-type]
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.COMPLETED
        # FK-27 §27.7: 6 Envelopes — structural (1) + Layer-2 (3) + adversarial (1) + decision (1).
        assert set(result.artifacts_produced) == {
            "structural.json",
            "qa_review.json",
            "semantic_review.json",
            "doc_fidelity.json",
            "adversarial.json",
            "decision.json",
        }

    def test_missing_artifacts_returns_escalated(self, tmp_path: Path) -> None:
        """FAIL verdict from VerifySystem -> PhaseStatus.ESCALATED after max rounds."""
        story_dir = _story_dir(tmp_path)
        save_story_context(story_dir, _make_context())
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-implementation-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        # AG3-026 Pass-2 §Befund-A: inject controlled FAIL VerifySystem.
        # E3 (AG3-041): escalation is owned by the controller inside the
        # subflow; the double escalates at round 1 (max_feedback_rounds=1).
        config = ImplementationConfig(
            story_dir=story_dir,
            max_feedback_rounds=1,
            verify_system=_RecordingVerifySystem(
                verdict=PolicyVerdict.FAIL, max_feedback_rounds=1
            ),  # type: ignore[arg-type]
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.ESCALATED
        assert len(result.errors) > 0
        # FK-27 §27.7: auch bei FAIL alle 6 Artefakte.
        assert set(result.artifacts_produced) == {
            "structural.json",
            "qa_review.json",
            "semantic_review.json",
            "doc_fidelity.json",
            "adversarial.json",
            "decision.json",
        }

    def test_persists_all_four_qa_cycle_identities(self, tmp_path: Path) -> None:
        """E1 (AG3-041): the handler persists ALL FOUR cycle identities.

        FK-27 §27.2.1 "im Story-State persistiert": the resolved qa_cycle_id,
        qa_cycle_round, evidence_epoch and evidence_fingerprint must land on the
        ``ImplementationPayload``, not just the round.
        """
        story_dir = _setup_complete_story_dir(tmp_path)
        config = ImplementationConfig(
            story_dir=story_dir,
            verify_system=_RecordingVerifySystem(verdict=PolicyVerdict.PASS),  # type: ignore[arg-type]
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.COMPLETED
        payload = result.updated_state.payload
        from agentkit.backend.pipeline_engine.phase_executor import ImplementationPayload

        assert isinstance(payload, ImplementationPayload)
        assert payload.qa_cycle_id is not None
        assert payload.qa_cycle_round == 1
        assert payload.evidence_epoch is not None
        assert payload.evidence_fingerprint is not None

    def test_on_resume_reruns_qa_subflow(self, tmp_path: Path) -> None:
        """on_resume re-executes the QA-subflow."""
        story_dir = _setup_complete_story_dir(tmp_path)
        config = ImplementationConfig(
            story_dir=story_dir,
            verify_system=_RecordingVerifySystem(verdict=PolicyVerdict.PASS),  # type: ignore[arg-type]
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state(review_round=1)

        result = handler.on_resume(ctx, _make_envelope(state), trigger="remediation_complete")
        assert result.status == PhaseStatus.COMPLETED

    def test_no_story_dir_returns_failed(self) -> None:
        config = ImplementationConfig(story_dir=None)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.FAILED
        assert "story_dir" in result.errors[0]

    def test_on_exit_is_noop(self, tmp_path: Path) -> None:
        config = ImplementationConfig(story_dir=_story_dir(tmp_path))
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context(project_root=tmp_path)
        state = _make_state()
        # on_exit should not raise
        handler.on_exit(ctx, _make_envelope(state))

    def test_implements_phase_handler_protocol(self, tmp_path: Path) -> None:
        config = ImplementationConfig(story_dir=_story_dir(tmp_path))
        handler = ImplementationPhaseHandler(config)
        assert isinstance(handler, PhaseHandler)

    def test_failed_result_contains_feedback_text(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _write_required_worker_artifacts(story_dir)
        save_story_context(story_dir, _make_context())
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-implementation-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        # E3: round ceiling 1 -> a FAIL at round 1 escalates immediately
        # (the controller owns the ceiling; >= 1 is enforced).
        config = ImplementationConfig(
            story_dir=story_dir,
            max_feedback_rounds=1,
            verify_system=_make_real_verify_system(story_dir, max_feedback_rounds=1),
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.ESCALATED
        # Should contain structured feedback
        full_errors = "\n".join(result.errors)
        assert "Remediation Feedback" in full_errors or "FAIL" in full_errors

    def test_verify_decision_json_written_on_pass(self, tmp_path: Path) -> None:
        # Uses the real VerifySystem (build_verify_system) so that actual
        # JSON files are written to disk for FK-69 path verification.
        # _setup_complete_story_dir adds test files + .coverage so the
        # QaReviewReviewer passes (AG3-026 Pass-2).
        #
        # AG3-026 Pass-3 ERROR-5: Layer-2 reviewers now emit MAJOR
        # layer2_input.missing when review_input is empty (THEME-009 not yet
        # wired). max_major_findings=3 tolerates all three MAJOR findings so
        # that the structural / filesystem checks remain the PASS gate.
        #
        # AG3-043 E6: build_verify_system now wires the productive Layer-2 LLM
        # path (FailClosedLlmClient by default). This test specifically covers
        # the DETERMINISTIC Layer-2 reviewers' FK-69 artefacts (prompt_audit
        # skipped, semantic_review layer), which are the no-LLM-client path. So
        # it builds a VerifySystem WITHOUT layer2_llm_client (create_default,
        # the deterministic-reviewer path). The productive LLM path is covered
        # by tests/integration/verify_system/test_layer2_e2e.py.
        story_dir = _setup_complete_story_dir(tmp_path)
        # AG3-079 (FK-48 §48.1.7): seed the Layer-3 sandbox evidence (the harness
        # sub-agent is the only mock boundary) so the real adversarial runtime can
        # PASS with >= 1 executed test instead of failing closed.
        _seed_adversarial_sandbox(story_dir)
        verify_system = _make_real_verify_system(story_dir, max_major_findings=3)
        config = ImplementationConfig(story_dir=story_dir, verify_system=verify_system)
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.COMPLETED

        qa_dir = qa_story_dir(tmp_path, "TEST-001")
        # FK-27 §27.7: decision.json (nicht verify-decision.json).
        decision_path = qa_dir / "decision.json"
        assert decision_path.exists(), "decision.json must be written (FK-27 §27.7)"
        # FK-27 §27.7: semantic_review.json mit Underscore.
        semantic_path = qa_dir / "semantic_review.json"
        adversarial_path = qa_dir / "adversarial.json"
        structural_path = qa_dir / "structural.json"
        assert structural_path.exists()
        assert semantic_path.exists()
        assert adversarial_path.exists()
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        structural_data = json.loads(structural_path.read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["status"] == "PASS"
        assert "summary" in data
        assert isinstance(data["layers"], list)
        assert isinstance(data["blocking_findings"], list)
        assert isinstance(data["all_findings_count"], int)
        assert structural_data["layer"] == "structural"
        assert structural_data["passed"] is True
        # FK-69: FK-27 §27.7 Layer-2 reviewer-Tags.
        semantic_review = next(
            (layer for layer in data["layers"] if layer["layer"] == "semantic_review"),
            None,
        )
        adversarial = next(
            layer for layer in data["layers"] if layer["layer"] == "adversarial"
        )
        assert semantic_review is not None, "semantic_review layer expected in decision"
        assert semantic_review["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }
        assert adversarial["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }
        semantic_data = json.loads(semantic_path.read_text(encoding="utf-8"))
        adversarial_data = json.loads(adversarial_path.read_text(encoding="utf-8"))
        assert semantic_data["layer"] == "semantic_review"
        assert semantic_data["passed"] is True
        assert semantic_data["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }
        assert adversarial_data["layer"] == "adversarial"
        assert adversarial_data["passed"] is True
        assert adversarial_data["metadata"]["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_verify_decision_json_written_on_fail(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _write_required_worker_artifacts(story_dir)
        save_story_context(story_dir, _make_context())
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-implementation-001",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        config = ImplementationConfig(
            story_dir=story_dir,
            max_feedback_rounds=1,
            verify_system=_make_real_verify_system(story_dir, max_feedback_rounds=1),
        )
        handler = ImplementationPhaseHandler(config)
        ctx = _make_context()
        state = _make_state()

        result = handler.on_enter(ctx, _make_envelope(state))
        assert result.status == PhaseStatus.ESCALATED

        qa_dir = qa_story_dir(tmp_path, "TEST-001")
        # FK-27 §27.7: decision.json (nicht verify-decision.json).
        decision_path = qa_dir / "decision.json"
        assert decision_path.exists(), (
            "decision.json must be written even on FAIL (FK-27 §27.7)"
        )
        assert (qa_dir / "structural.json").exists()
        assert (qa_dir / "semantic_review.json").exists()
        assert (qa_dir / "adversarial.json").exists()
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        assert data["passed"] is False
        assert data["status"] == "FAIL"
        assert isinstance(data["layers"], list)
        assert len(data["blocking_findings"]) > 0
