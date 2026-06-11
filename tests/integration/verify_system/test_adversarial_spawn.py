"""Integration: adversarial-spawn end-to-end (FK-27 §27.6 / FK-48 §48.2).

Layer-2 BLOCKING findings -> AdversarialTargets -> a materialised protected
sandbox -> ``agents_to_spawn`` set on the PhaseState. Uses the REAL
ArtifactManager (sqlite) and the challenger->spawner wiring.
"""

from __future__ import annotations

import dataclasses
import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.artifacts import ArtifactReference
from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.core_types import ArtifactClass, QaContext, SpawnKind, SpawnReason
from agentkit.governance.guard_system.protected_paths import (
    is_adversarial_sandbox_path,
)
from agentkit.implementation.phase import (
    ImplementationConfig,
    ImplementationPhaseHandler,
)
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.engine import PipelineEngine
from agentkit.pipeline_engine.lifecycle import PhaseHandlerRegistry
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import (
    PhaseStatus,
)
from agentkit.process.language.definitions import IMPLEMENTATION_WORKFLOW
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    read_phase_state_record,
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.adversarial_orchestrator.challenger import (
    AdversarialChallenger,
)
from agentkit.verify_system.adversarial_orchestrator.spawn import AdversarialSpawner
from agentkit.verify_system.contract import VerifyContextBundle
from agentkit.verify_system.protocols import (
    ASSERTION_WEAKNESS_FINDING_TYPE,
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)
from agentkit.verify_system.system import VerifySystem
from integration.implementation_evidence_support import (
    bind_implementation_qa_preconditions,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _layer2_findings() -> list[Finding]:
    return [
        Finding(
            layer="qa_review",
            check="assertion_weakness",
            severity=Severity.BLOCKING,
            message="negative case for INV-6 not covered",
            trust_class=TrustClass.VERIFIED_LLM,
            suggestion="add a test for the wrong-phase case",
            # FK-48 §48.2.2: only an ``assertion_weakness``-typed finding becomes
            # a mandatory adversarial target (not pauschal per BLOCKING finding).
            finding_type=ASSERTION_WEAKNESS_FINDING_TYPE,
            addressed_part="fixed the happy-path assertion",
        ),
        Finding(
            layer="semantic_review",
            check="style_nit",
            severity=Severity.MINOR,
            message="cosmetic",
            trust_class=TrustClass.VERIFIED_LLM,
        ),
    ]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_story_worktree(story_dir: Path) -> None:
    """Initialise the real git boundary required by QA-cycle fingerprinting."""
    story_dir.mkdir(parents=True, exist_ok=True)
    if not any(story_dir.iterdir()):
        (story_dir / ".ak3-baseline").write_text("baseline\n", encoding="utf-8")
    _git(["init", "-b", "main"], story_dir)
    _git(["config", "user.email", "t@example.com"], story_dir)
    _git(["config", "user.name", "Test"], story_dir)
    _git(["add", "."], story_dir)
    _git(["commit", "-m", "base"], story_dir)
    _git(["update-ref", "refs/remotes/origin/main", "HEAD"], story_dir)
    _git(["checkout", "-b", "story-branch"], story_dir)


def test_layer2_findings_to_agents_to_spawn(tmp_path: Path) -> None:
    """BLOCKING Layer-2 findings flow through to PhaseState.agents_to_spawn."""
    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    manager = build_artifact_manager(tmp_path)
    spawner = AdversarialSpawner(manager)
    # Challenger uses the spawner to derive mandatory targets (FK-48 §48.2).
    challenger = AdversarialChallenger(spawner=spawner)

    targets = challenger.derive_adversarial_targets(_layer2_findings())
    assert len(targets) == 1  # only the BLOCKING finding becomes a target
    assert targets[0].finding_id == "qa_review.assertion_weakness"

    ctx = VerifyContextBundle(run_id="run-1", story_dir=story_dir, attempt=1)
    request = spawner.request_spawn(ctx, targets)

    # Sandbox materialised under the protected path (AG3-023 / FK-48 §48.1).
    assert request.sandbox_path.is_dir()
    rel = request.sandbox_path.relative_to(story_dir).as_posix()
    assert is_adversarial_sandbox_path(rel)

    # agents_to_spawn is written into the PhaseState (FK-45 §45.3).
    state = make_phase_state(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    updated = request.apply_to_state(state)
    assert len(updated.agents_to_spawn) == 1
    assert updated.agents_to_spawn[0].kind is SpawnKind.ADVERSARIAL
    assert updated.agents_to_spawn[0].target_id == "qa_review.assertion_weakness"


def test_adversarial_sandbox_envelope_is_persisted(tmp_path: Path) -> None:
    """request_spawn persists a typed ADVERSARIAL_TEST_SANDBOX envelope."""
    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    manager = build_artifact_manager(tmp_path)
    spawner = AdversarialSpawner(manager)
    targets = spawner.extract_mandatory_targets(_layer2_findings(), 1)
    ctx = VerifyContextBundle(run_id="run-1", story_dir=story_dir, attempt=1)
    request = spawner.request_spawn(ctx, targets)

    envelope = manager.read_latest(
        story_id="AG3-044",
        run_id="run-1",
        artifact_class=ArtifactClass.ADVERSARIAL_TEST_SANDBOX,
        stage="qa-adversarial",
    )
    assert envelope.payload is not None
    assert envelope.payload["sandbox_path"].startswith("_temp/adversarial/")
    assert request.epoch == "1"

    # FIX-1 (AC0 / FK-48 §48.2.2): each mandatory target carries its
    # addressed_part + normative_ref through the spawn envelope payload (the
    # durable record the adversarial sub-agent reads), not just finding_id.
    payload_targets = envelope.payload["targets"]
    assert payload_targets, "spawn envelope must carry the mandatory targets"
    target0 = payload_targets[0]
    assert target0["finding_id"] == "qa_review.assertion_weakness"
    assert target0["addressed_part"] == "fixed the happy-path assertion"
    assert target0["normative_ref"] == "negative case for INV-6 not covered"
    assert target0["mandatory"] is True

    # FIX-1 (AC0 / FK-48 §48.2.3): the rendered "Mandatory Targets" prompt
    # section is delivered IN the productive spawn payload (not only available
    # via the render function in isolation). This is what reaches the adversarial
    # worker's prompt — with the per-target test mandate + the UNRESOLVABLE path.
    section = envelope.payload["mandatory_targets_prompt_section"]
    assert "## Mandatory Targets" in section
    assert "Target: qa_review.assertion_weakness" in section
    assert "fixed the happy-path assertion" in section
    assert "UNRESOLVABLE" in section


def test_no_blocking_findings_no_spawn(tmp_path: Path) -> None:
    """No BLOCKING Layer-2 findings -> no mandatory targets, no spawn order."""
    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    spawner = AdversarialSpawner(build_artifact_manager(tmp_path))
    findings = [
        Finding(
            layer="qa_review",
            check="nit",
            severity=Severity.MINOR,
            message="cosmetic",
            trust_class=TrustClass.VERIFIED_LLM,
        ),
    ]
    targets = spawner.extract_mandatory_targets(findings, 1)
    assert targets == []


# ---------------------------------------------------------------------------
# FIX-1: adversarial spawn reached on the REAL QA path (not hand-wired).
# ---------------------------------------------------------------------------


class _BlockingQaReviewLayer:
    """Layer-2 ``qa_review`` double producing one BLOCKING finding.

    Drives a BLOCKING Layer-2 finding through the REAL ``run_qa_subflow`` so the
    productive spawner (wired by ``create_default``) is reached end-to-end -- the
    spawner itself is NOT hand-wired here (FK-27 §27.6 / FK-48 §48.2).
    """

    @property
    def name(self) -> str:
        return "qa_review"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        del ctx, story_dir, review_input
        return LayerResult(
            layer="qa_review",
            passed=False,
            findings=(
                Finding(
                    layer="qa_review",
                    check="assertion_weakness",
                    severity=Severity.BLOCKING,
                    message="negative case for INV-6 not covered",
                    trust_class=TrustClass.VERIFIED_LLM,
                    suggestion="add a test for the wrong-phase case",
                    finding_type=ASSERTION_WEAKNESS_FINDING_TYPE,
                    addressed_part="fixed the happy-path assertion",
                ),
            ),
        )


def _impl_target() -> ArtifactReference:
    return ArtifactReference(
        artifact_class=ArtifactClass.WORKER,
        story_id="AG3-044",
        run_id="run-1",
        record_key="envelopes/worker/AG3-044/1",
    )


def test_real_qa_subflow_layer2_blocking_to_agents_to_spawn(tmp_path: Path) -> None:
    """REAL run_qa_subflow: Layer-2 BLOCKING -> adversarial_spawn + sandbox envelope.

    The spawner is the PRODUCTIVE one wired by ``VerifySystem.create_default``
    (not constructed in the test). Layer 2 yields a BLOCKING finding via a
    reviewer double; the subflow derives an AdversarialTarget, materialises the
    protected sandbox + ``ADVERSARIAL_TEST_SANDBOX`` envelope and carries the
    typed spawn order out through ``QaSubflowOutcome.adversarial_spawn``.
    """
    story_dir = tmp_path / "AG3-044"
    _init_story_worktree(story_dir)
    manager = build_artifact_manager(tmp_path)
    system = VerifySystem.create_default(artifact_manager=manager)
    # Replace ONLY the qa_review Layer-2 reviewer with a blocking double; the
    # adversarial spawner stays the real one create_default wired.
    system = dataclasses.replace(system, layer_2a=_BlockingQaReviewLayer())
    system = bind_implementation_qa_preconditions(
        system, story_dir, story_id="AG3-044", run_id="run-1"
    )
    assert system.adversarial_spawner is not None

    ctx = VerifyContextBundle(run_id="run-1", story_dir=story_dir, attempt=1)
    outcome = system.run_qa_subflow(
        ctx,
        "AG3-044",
        QaContext.IMPLEMENTATION_INITIAL,
        _impl_target(),
    )

    # The Layer-2 BLOCKING finding produced exactly one adversarial spawn order.
    assert len(outcome.adversarial_spawn) == 1
    spawn = outcome.adversarial_spawn[0]
    assert spawn.kind is SpawnKind.ADVERSARIAL
    assert spawn.target_id == "qa_review.assertion_weakness"

    # The protected sandbox envelope was written as a side effect (durable).
    envelope = manager.read_latest(
        story_id="AG3-044",
        run_id="run-1",
        artifact_class=ArtifactClass.ADVERSARIAL_TEST_SANDBOX,
        stage="qa-adversarial",
    )
    assert envelope.payload is not None
    assert envelope.payload["sandbox_path"].startswith("_temp/adversarial/")

    # The spawn order writes into PhaseState.agents_to_spawn (FK-45 §45.3).
    state = make_phase_state(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    updated = state.model_copy(update={"agents_to_spawn": list(outcome.adversarial_spawn)})
    assert len(updated.agents_to_spawn) == 1
    assert updated.agents_to_spawn[0].kind is SpawnKind.ADVERSARIAL


class _PassingLayer:
    """A Layer-2 reviewer double producing no findings (clean PASS)."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        del ctx, story_dir, review_input
        return LayerResult(layer=self._name, passed=True)


def test_real_qa_subflow_impl_route_no_blocking_layer2_no_spawn(tmp_path: Path) -> None:
    """REAL run_qa_subflow on the IMPL route: no BLOCKING Layer-2 -> no spawn.

    Layer 3 IS routed (IMPLEMENTATION), but all three Layer-2 reviewers PASS, so
    no mandatory adversarial target is derived -> ``adversarial_spawn`` is empty
    (no spurious spawn on a clean Layer-2).
    """
    story_dir = tmp_path / "AG3-044"
    _init_story_worktree(story_dir)
    manager = build_artifact_manager(tmp_path)
    system = VerifySystem.create_default(artifact_manager=manager)
    system = dataclasses.replace(
        system,
        layer_2a=_PassingLayer("qa_review"),
        layer_2b=_PassingLayer("semantic_review"),
        layer_2c=_PassingLayer("doc_fidelity"),
    )
    system = bind_implementation_qa_preconditions(
        system, story_dir, story_id="AG3-044", run_id="run-1"
    )

    ctx = VerifyContextBundle(run_id="run-1", story_dir=story_dir, attempt=1)
    outcome = system.run_qa_subflow(
        ctx,
        "AG3-044",
        QaContext.IMPLEMENTATION_INITIAL,
        _impl_target(),
    )

    assert outcome.adversarial_spawn == ()


def test_real_qa_subflow_exploration_route_no_spawn(tmp_path: Path) -> None:
    """REAL run_qa_subflow: Exploration route (no Layer 3) -> no adversarial spawn.

    The Exploration QaContext routes only Layer 2 + Layer 4 (no adversarial
    layer), so no adversarial spawn order is derived even if Layer 2 blocks --
    the spawn is scoped to the Layer-3 route (FK-27 §27.3).
    """
    story_dir = tmp_path / "AG3-044"
    _init_story_worktree(story_dir)
    manager = build_artifact_manager(tmp_path)
    system = VerifySystem.create_default(artifact_manager=manager)
    system = bind_implementation_qa_preconditions(
        system, story_dir, story_id="AG3-044", run_id="run-1"
    )

    ctx = VerifyContextBundle(run_id="run-1", story_dir=story_dir, attempt=1)
    outcome = system.run_qa_subflow(
        ctx,
        "AG3-044",
        QaContext.EXPLORATION_INITIAL,
        _impl_target(),
    )

    assert outcome.adversarial_spawn == ()


# ---------------------------------------------------------------------------
# FIX-3: adversarial-order persistence proven through the REAL PipelineEngine.
# ---------------------------------------------------------------------------


def _engine_ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-044",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _bind_engine_story_dir(tmp_path: Path) -> Path:
    """Materialise a story dir with the bound FlowExecution the handler needs."""
    story_dir = tmp_path / "stories" / "AG3-044"
    story_dir.mkdir(parents=True)
    save_story_context(story_dir, _engine_ctx())
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-044",
            run_id="run-1",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )
    _init_story_worktree(story_dir)
    return story_dir


def test_engine_persists_remediation_and_adversarial_spawn(tmp_path: Path) -> None:
    """REAL engine drives REAL handler: BOTH spawn orders + sandbox persisted.

    FIX-3 (FK-27 §27.6 / FK-48 §48.2 / FK-45 §45.3): instead of hand-copying
    ``outcome.adversarial_spawn`` into a PhaseState, this drives the REAL
    :class:`ImplementationPhaseHandler` through :class:`PipelineEngine.run_phase`
    with the PRODUCTIVE ``VerifySystem.create_default`` (only the Layer-2
    ``qa_review`` reviewer is replaced by a BLOCKING double). It asserts the
    PERSISTED ``PhaseState.agents_to_spawn`` carries BOTH the remediation worker
    order AND the adversarial order, and that the ``ADVERSARIAL_TEST_SANDBOX``
    envelope is durably persisted — the orchestrator-trennlinie spawn truth
    proven end-to-end through the engine, not by hand.
    """
    story_dir = _bind_engine_story_dir(tmp_path)
    # The artifact manager is bound to the SAME store as the engine's state so
    # the sandbox envelope and the persisted PhaseState share one backend.
    manager = build_artifact_manager(story_dir)
    system = VerifySystem.create_default(artifact_manager=manager)
    # Replace ONLY the qa_review Layer-2 reviewer with a blocking double; the
    # adversarial spawner stays the real one create_default wired.
    system = dataclasses.replace(system, layer_2a=_BlockingQaReviewLayer())
    system = bind_implementation_qa_preconditions(
        system, story_dir, story_id="AG3-044", run_id="run-1"
    )
    assert system.adversarial_spawner is not None

    config = ImplementationConfig(
        story_dir=story_dir,
        max_feedback_rounds=3,
        verify_system=system,
    )
    registry = PhaseHandlerRegistry()
    registry.register("implementation", ImplementationPhaseHandler(config))
    engine = PipelineEngine(IMPLEMENTATION_WORKFLOW, registry, story_dir)

    state = make_phase_state(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    result = engine.run_phase(_engine_ctx(), envelope)

    # FAIL below the ceiling -> the engine yields for orchestrator re-entry
    # (subflow-internal remediation, no phase transition).
    assert result.status == "yielded"
    assert result.phase == "implementation"
    assert result.next_phase is None

    # The PERSISTED PhaseState carries BOTH spawn orders (FK-45 §45.3).
    persisted = read_phase_state_record(story_dir)
    assert persisted is not None
    assert persisted.status == PhaseStatus.IN_PROGRESS
    spawn = persisted.agents_to_spawn
    assert len(spawn) == 2, spawn
    remediation = [s for s in spawn if s.kind is SpawnKind.WORKER]
    adversarial = [s for s in spawn if s.kind is SpawnKind.ADVERSARIAL]
    assert len(remediation) == 1
    assert remediation[0].spawn_reason is SpawnReason.REMEDIATION
    assert remediation[0].target_id == "AG3-044"
    assert len(adversarial) == 1
    assert adversarial[0].target_id == "qa_review.assertion_weakness"

    # The protected ADVERSARIAL_TEST_SANDBOX envelope is durably persisted.
    sandbox_envelope = manager.read_latest(
        story_id="AG3-044",
        run_id="run-1",
        artifact_class=ArtifactClass.ADVERSARIAL_TEST_SANDBOX,
        stage="qa-adversarial",
    )
    assert sandbox_envelope.payload is not None
    assert sandbox_envelope.payload["sandbox_path"].startswith("_temp/adversarial/")
