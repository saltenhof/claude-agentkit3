"""Deterministic Layer-3 adversarial runtime orchestrator (FK-48 §48.1, AG3-079).

The deterministic Zone-2 orchestrator the :class:`AdversarialChallenger` drives
after the Harness-Sub-Agent has run. It is NOT an agent — it reads the sub-agent's
sandbox evidence and turns it into a real Layer-3 verdict, telemetry and the
``adversarial.json`` artefact:

1. emit ``adversarial_start`` (exactly 1, FK-48 §48.1.8),
2. read + validate the sandbox ``result.json`` (no evidence -> FAIL),
3. force the mandatory sparring call over the AG3-065 transport (AC3) and emit
   ``llm_call role=adversarial_sparring`` + ``adversarial_sparring`` (pool),
4. emit ``adversarial_test_created`` (>= 0, per created test) and
   ``adversarial_test_executed`` (>= 1, FK-48 §48.1.8),
5. promote / quarantine the sandbox tests deterministically (AC4),
6. materialise ``adversarial.json`` via the ArtifactManager (AC5),
7. emit ``adversarial_end`` (exactly 1),
8. return the DERIVED :class:`LayerResult` (no PASS without real evidence).

NO PASS without real evidence: a run with zero executed tests, a failed sparring
call, or a proven finding is a Layer-3 FAIL (FK-48 §48.1.8 / story §2.1.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.artifact import (
    build_result_artifact,
    materialize_adversarial_artifact,
    read_sandbox_result,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.feedback import (
    mandatory_target_resolution_feedback,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
    AdversarialTelemetryCounts,
    SparringProof,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.promotion import (
    promote_sandbox_tests,
)
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.sparring import (
    ADVERSARIAL_SPARRING_ROLE,
    AdversarialSparringError,
    run_mandatory_sparring,
)
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactManager
    from agentkit.backend.telemetry.emitters import EventEmitter
    from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
        AdversarialResultArtifact,
    )
    from agentkit.backend.verify_system.adversarial_orchestrator.runtime.promotion import (
        PromotionDecision,
    )
    from agentkit.backend.verify_system.llm_evaluator.llm_client import (
        LlmClient,
        RolePoolResolver,
    )
    from agentkit.backend.verify_system.remediation.finding_resolution import (
        FindingKey,
        FindingResolutionStatus,
    )

#: Layer name of the adversarial layer (matches ``AdversarialChallenger.name``).
_LAYER_NAME: str = "adversarial"

#: Default sparring prompt (FK-48 §48.1.3 phase 3 "what did I miss?").
_DEFAULT_SPARRING_PROMPT: str = (
    "I have written and executed adversarial edge-case tests against the "
    "implementation. Which edge cases, boundary values, error paths, race "
    "conditions or misuse scenarios have I likely missed? List concrete, "
    "testable negative cases."
)


@dataclass(frozen=True)
class AdversarialRuntimeResult:
    """The deterministic Layer-3 runtime outcome (FK-48 §48.1).

    Attributes:
        layer_result: The DERIVED :class:`LayerResult` (the layer verdict).
        artifact: The materialised ``adversarial.json`` payload (schema 3.1).
        promotion_decisions: Per-test promotion decisions (FK-48 §48.1.5).
        resolution_feedback: Layer-3 -> Layer-2 mandatory-target feedback map
            (``{(layer, check) -> PARTIALLY_RESOLVED}`` for unfulfilled targets,
            FK-48 §48.2.5).
    """

    layer_result: LayerResult
    artifact: AdversarialResultArtifact
    promotion_decisions: tuple[PromotionDecision, ...]
    resolution_feedback: dict[FindingKey, FindingResolutionStatus]


def run_adversarial_runtime(
    *,
    artifact_manager: ArtifactManager,
    emitter: EventEmitter,
    sparring_client: LlmClient,
    sandbox_dir: Path,
    tests_root: Path,
    story_id: str,
    run_id: str,
    attempt: int,
    resolver: RolePoolResolver | None = None,
    sparring_prompt: str = _DEFAULT_SPARRING_PROMPT,
    phase: str | None = None,
) -> AdversarialRuntimeResult:
    """Run the deterministic Layer-3 adversarial runtime (FK-48 §48.1).

    Args:
        artifact_manager: Producer-bound ArtifactManager (the only authorised
            ``_temp/qa/`` write path; sub-agents cannot write it).
        emitter: Telemetry emitter for the five adversarial events.
        sparring_client: The AG3-065 verify-LLM-transport (consumed, not rebuilt).
        sandbox_dir: The protected sandbox dir
            (``_temp/adversarial/{story_id}/{epoch}/``) the sub-agent wrote to.
        tests_root: The project ``tests/`` root (promotion target).
        story_id: Story display id.
        run_id: Run-correlation id.
        attempt: QA-subflow attempt counter (>= 1).
        resolver: Optional role->pool resolver (records the concrete pool label).
        sparring_prompt: The sparring prompt (FK-48 §48.1.3 phase 3).
        phase: Optional pipeline phase name stamped on the events.

    Returns:
        An :class:`AdversarialRuntimeResult`.

    Raises:
        AdversarialResultReadError: When the sandbox result is absent/invalid
            (fail-closed, FK-48 §48.1.7).
    """
    # FK-48 §48.1.8: count the emitted lifecycle events so the materialised
    # ``adversarial.json`` carries the EXACT counts the integrity gate (Dim 6)
    # verifies against (exactly-1 start/end, >= 1 sparring/test_executed). The
    # counter wraps the real emitter — it counts what is ACTUALLY emitted, no
    # second telemetry truth. ``_LifecycleEmitter`` additionally guarantees
    # ``adversarial_end`` is emitted exactly once (happy path AND error/finally
    # path) so the recorded count is the REAL emission, never a +1 prediction.
    counter = _LifecycleEmitter(emitter)
    _emit(counter, EventType.ADVERSARIAL_START, story_id, run_id, phase)
    try:
        sandbox_result = read_sandbox_result(sandbox_dir)

        # FK-48 §48.1.8: ``adversarial_test_created`` (>= 0) per created test,
        # ``adversarial_test_executed`` (>= 1, mandatory). Emit BEFORE deriving
        # the verdict so the telemetry reflects what the sub-agent produced.
        for _test in sandbox_result.tests:
            _emit(counter, EventType.ADVERSARIAL_TEST_CREATED, story_id, run_id, phase)
        for _ in range(sandbox_result.tests_executed):
            _emit(counter, EventType.ADVERSARIAL_TEST_EXECUTED, story_id, run_id, phase)

        # AC3: mandatory sparring over the AG3-065 transport (fail-closed). A
        # failed sparring call makes Layer 3 FAIL (no PASS without sparring).
        sparring_failed: str | None = None
        try:
            sparring = run_mandatory_sparring(
                sparring_client=sparring_client,
                emitter=counter,
                story_id=story_id,
                run_id=run_id,
                prompt=sparring_prompt,
                resolver=resolver,
                phase=phase,
            )
        except AdversarialSparringError as exc:
            sparring_failed = str(exc)
            sparring = SparringProof(
                pool=ADVERSARIAL_SPARRING_ROLE,
                adversarial_sparring_events=0,
                llm_call_sparring_events=0,
            )

        # AC4: deterministic promotion / quarantine over the SANDBOX tests.
        decisions, promotion = promote_sandbox_tests(
            tests=sandbox_result.tests,
            sandbox_dir=sandbox_dir,
            tests_root=tests_root,
        )

        # FK-48 §48.1.8: emit ``adversarial_end`` NOW — BEFORE capturing the
        # counts and building the artefact — so the persisted telemetry mirrors
        # the REAL post-emission counter, never a predicted +1. The emission is
        # idempotent: the ``finally`` re-call below is a no-op on the happy path
        # and the sole emitter on an error/early-return path (exactly-1 always).
        _emit_end_once(counter, story_id, run_id, phase)

        # The emitted-event counts mirrored into the artefact — every count is
        # what the ``_LifecycleEmitter`` ACTUALLY observed (incl. the end event
        # just emitted), so Dim 6 verifies real emission, not a self-attested 1.
        telemetry = AdversarialTelemetryCounts(
            adversarial_start=counter.count(EventType.ADVERSARIAL_START),
            adversarial_end=counter.count(EventType.ADVERSARIAL_END),
            adversarial_sparring=counter.count(EventType.ADVERSARIAL_SPARRING),
            adversarial_test_created=counter.count(EventType.ADVERSARIAL_TEST_CREATED),
            adversarial_test_executed=counter.count(
                EventType.ADVERSARIAL_TEST_EXECUTED
            ),
        )

        # AC5: materialise ``adversarial.json`` (schema 3.1) via the ArtifactManager.
        artifact = build_result_artifact(
            sandbox_result=sandbox_result,
            run_id=run_id,
            sparring=sparring,
            promotion=promotion,
            telemetry=telemetry,
        )
        materialize_adversarial_artifact(
            artifact_manager=artifact_manager,
            artifact=artifact,
            attempt=attempt,
        )

        # AC8: Layer-3 -> Layer-2 mandatory-target feedback.
        resolution_feedback = mandatory_target_resolution_feedback(artifact)

        layer_result = _derive_layer_result(
            artifact=artifact,
            sparring_failure=sparring_failed,
        )
        return AdversarialRuntimeResult(
            layer_result=layer_result,
            artifact=artifact,
            promotion_decisions=decisions,
            resolution_feedback=resolution_feedback,
        )
    finally:
        # Exactly-1 ``adversarial_end`` guarantee: a no-op when the happy path
        # already emitted it, the SOLE emission on any error/early-return path.
        _emit_end_once(counter, story_id, run_id, phase)


def _derive_layer_result(
    *,
    artifact: AdversarialResultArtifact,
    sparring_failure: str | None,
) -> LayerResult:
    """Derive the Layer-3 verdict from real evidence (FK-48 §48.1.8 / §48.1.1).

    NO PASS without real evidence: PASS only when >= 1 test executed, no executed
    test failed, the mandatory sparring ran, and every mandatory target is
    fulfilled. Otherwise a BLOCKING finding is produced and the layer FAILs.
    """
    findings: list[Finding] = []
    if artifact.tests_executed < 1:
        findings.append(
            Finding(
                layer=_LAYER_NAME,
                check="no_test_executed",
                severity=Severity.BLOCKING,
                message=(
                    "Layer 3 (Adversarial) executed no test — the mandatory "
                    ">= 1 executed-test duty was violated (FK-48 §48.1.8)."
                ),
                trust_class=TrustClass.SYSTEM,
                suggestion="The adversarial agent must execute at least one test.",
            )
        )
    if sparring_failure is not None:
        findings.append(
            Finding(
                layer=_LAYER_NAME,
                check="sparring_missing",
                severity=Severity.BLOCKING,
                message=(
                    "Layer 3 (Adversarial) mandatory sparring did not run: "
                    f"{sparring_failure}"
                ),
                trust_class=TrustClass.SYSTEM,
                suggestion="The adversarial agent must complete one sparring call.",
            )
        )
    if artifact.tests_failed > 0:
        findings.append(
            Finding(
                layer=_LAYER_NAME,
                check="proven_finding",
                severity=Severity.BLOCKING,
                message=(
                    f"Layer 3 (Adversarial) proved {artifact.tests_failed} "
                    "failing test(s) — quarantined as proven findings (FK-48 §48.1.5)."
                ),
                trust_class=TrustClass.VERIFIED_LLM,
                suggestion="Fix the implementation so the quarantined test(s) pass.",
            )
        )
    for target in artifact.mandatory_target_results:
        status = target.status.upper()
        if status == "TESTED" or (status == "UNRESOLVABLE" and target.reason):
            continue
        findings.append(
            Finding(
                layer=_LAYER_NAME,
                check=target.target_id,
                severity=Severity.BLOCKING,
                message=(
                    "Mandatory adversarial target not fulfilled: "
                    f"{target.target_id} (status={status or 'MISSING'})."
                ),
                trust_class=TrustClass.VERIFIED_LLM,
                suggestion=(
                    "Cover this mandatory adversarial target or mark it "
                    "UNRESOLVABLE with evidence."
                ),
            )
        )
    passed = not findings
    return LayerResult(
        layer=_LAYER_NAME,
        passed=passed,
        findings=tuple(findings),
        metadata={
            "adversarial_status": artifact.status,
            "tests_executed": artifact.tests_executed,
            "tests_failed": artifact.tests_failed,
            "sparring_pool": artifact.sparring.pool,
        },
    )


class _LifecycleEmitter:
    """Counting pass-through emitter with exactly-1 end-emission (FK-48 §48.1.8).

    Wraps the real :class:`EventEmitter`, forwards every event unchanged AND
    tallies them by :class:`EventType`. The tally is mirrored into
    ``adversarial.json`` so the integrity gate (Dim 6) verifies the FULL §48.1.8
    expectation table against the SAME counts that were actually emitted — no
    second telemetry-read port, no second telemetry truth. Conforms to the
    :class:`EventEmitter` protocol so :func:`run_mandatory_sparring` and
    :func:`_emit` accept it transparently.

    It additionally owns the exactly-1 ``adversarial_end`` invariant: callers
    route the end event through :func:`_emit_end_once`, which delegates to
    :meth:`emit_end_once`. The first call emits; every later call is a no-op. So
    the happy path can emit ``adversarial_end`` BEFORE capturing telemetry (the
    recorded count is the REAL post-emission tally, not a +1 prediction) while
    the ``finally`` re-call still guarantees emission on any error/early-return
    path — exactly once, never 0, never 2.
    """

    def __init__(self, inner: EventEmitter) -> None:
        self._inner = inner
        self._counts: dict[EventType, int] = {}
        self._end_emitted = False

    def emit(self, event: Event) -> None:
        """Forward the event to the wrapped emitter and tally its type.

        The tally is incremented ONLY after the inner emitter accepted the event
        — a forwarding failure must NOT inflate the recorded count, so a
        suppressed/failing ``adversarial_end`` truthfully records ``< 1`` and
        Dim 6 fails closed (no silent self-attested 1).
        """
        self._inner.emit(event)
        self._counts[event.event_type] = self._counts.get(event.event_type, 0) + 1

    def query(
        self, _story_id: str, _event_type: EventType | None = None
    ) -> list[Event]:
        """Delegate queries to the wrapped emitter (protocol completeness)."""
        return self._inner.query(_story_id, _event_type)

    def count(self, event_type: EventType) -> int:
        """Return how many events of ``event_type`` were emitted so far."""
        return self._counts.get(event_type, 0)

    def emit_end_once(self, event: Event) -> None:
        """Emit ``adversarial_end`` exactly once; later calls are no-ops.

        The recorded :meth:`count` for ``ADVERSARIAL_END`` therefore reflects the
        single REAL emission — there is no path that double-counts or predicts it.
        """
        if self._end_emitted:
            return
        self._end_emitted = True
        self.emit(event)


def _emit_end_once(
    emitter: _LifecycleEmitter,
    story_id: str,
    run_id: str,
    phase: str | None,
) -> None:
    """Emit the ``adversarial_end`` lifecycle event exactly once (idempotent)."""
    emitter.emit_end_once(
        Event(
            story_id=story_id,
            event_type=EventType.ADVERSARIAL_END,
            source_component="adversarial_runtime",
            phase=phase,
            payload={"story_id": story_id},
            run_id=run_id,
        )
    )


def _emit(
    emitter: EventEmitter,
    event_type: EventType,
    story_id: str,
    run_id: str,
    phase: str | None,
) -> None:
    """Emit one adversarial lifecycle event (no mandatory payload fields)."""
    emitter.emit(
        Event(
            story_id=story_id,
            event_type=event_type,
            source_component="adversarial_runtime",
            phase=phase,
            payload={"story_id": story_id},
            run_id=run_id,
        )
    )


__all__ = [
    "AdversarialRuntimeResult",
    "run_adversarial_runtime",
]
