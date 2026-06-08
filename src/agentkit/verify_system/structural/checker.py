"""Structural QA layer -- deterministic Layer-1 checks without LLM.

Drives the FK-27 §27.4 Layer-1 stage catalogue via the typed
:class:`StageRegistry` (FK-33 §33.2): ``StructuralChecker.evaluate`` iterates
``StageRegistry.layer1_stages_for(story_type, are_enabled=...)`` and dispatches
each stage to its check function, sourcing the severity from the
:class:`StageDefinition` (single severity truth, no second classification).
The mandatory canonical-state meta pre-checks (``check_context_exists`` etc.)
run first as a precondition for the stage checks (FK-27 §27.4).

Implements the ``QALayer`` protocol; no business logic beyond aggregation
(ARCH-12). A BLOCKING finding makes ``LayerResult.passed`` False (FK-27
§27.4.2). When an ``escalated`` stage (``impact.violation``, FK-27 §27.4.5)
FAILs, the layer stamps ``metadata["escalated"] = True`` so the orchestrator
routes directly to ESCALATED.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.story_context_manager.types import get_profile
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
)
from agentkit.verify_system.stage_registry.registry import StageRegistry
from agentkit.verify_system.structural.checks import (
    ABSENT_BUILD_TEST_PORT,
    ABSENT_CHANGE_EVIDENCE_PORT,
    BuildTestEvidencePort,
    ChangeEvidencePort,
    check_are_gate,
    check_artifact_handover,
    check_artifact_manifest_claims,
    check_artifact_protocol,
    check_artifact_worker_manifest,
    check_branch_commit_trailers,
    check_branch_story,
    check_build_compile,
    check_build_test_execution,
    check_completion_commit,
    check_completion_push,
    check_context_exists,
    check_context_valid,
    check_guard_llm_reviews,
    check_guard_multi_llm,
    check_guard_no_violations,
    check_guard_review_compliance,
    check_hygiene_commented_code,
    check_hygiene_disabled_tests,
    check_hygiene_todo_fixme,
    check_impact_violation,
    check_no_corrupt_state,
    check_phase_snapshots,
    check_test_count,
    check_test_coverage,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.requirements_coverage.contract import CoverageVerdict
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
    from agentkit.verify_system.protocols import TelemetryEventQueryPort
    from agentkit.verify_system.stage_registry.stages import StageDefinition
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence

__all__ = ["FULL_STAGE_REGISTRY", "AreGateProvider", "StructuralChecker"]

_SECURITY_SECRETS_CHECK = "security.secrets"


@runtime_checkable
class AreGateProvider(Protocol):
    """Resolve the ARE activation + coverage verdict for a story run.

    Mirrors the ``RequirementsCoverage`` top-surface (AG3-030): ``is_enabled``
    gates the ARE stage (FK-27 §27.4.4), ``coverage_verdict`` carries the
    dock-point-4 ``check_gate`` result.
    """

    @property
    def is_enabled(self) -> bool:
        """Return ``True`` when ``features.are`` is active."""
        ...

    def coverage_verdict(
        self, story_id: str, project_key: str
    ) -> CoverageVerdict | None:
        """Return the ARE coverage verdict (``None`` when unavailable)."""
        ...


class _AbsentAreGateProvider:
    """Default ARE provider: ARE disabled (the ARE stage is not planned)."""

    @property
    def is_enabled(self) -> bool:
        """ARE is disabled by default."""
        return False

    def coverage_verdict(
        self, story_id: str, project_key: str
    ) -> CoverageVerdict | None:
        """Return ``None`` -- no ARE verdict when ARE is disabled."""
        del story_id, project_key
        return None


class _NullTelemetryPort:
    """Default telemetry port: every event count is ``0`` (fail-closed)."""

    def count_events(
        self,
        story_dir: Path,
        *,
        story_id: str,
        event_type: str,
        role: str | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Return ``0`` -- no telemetry wired (BLOCKING guards fail closed)."""
        del story_dir, story_id, event_type, role, project_key, run_id
        return 0

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        """Return ``False`` -- no telemetry wired => no resolvable run scope.

        FIX-B (FK-33 §33.3.2): with no telemetry wired the run scope is unknown,
        so ``guard.no_violations`` must fail closed (never free-pass).
        """
        del story_dir
        return False


_ABSENT_ARE_PROVIDER: AreGateProvider = _AbsentAreGateProvider()
_NULL_TELEMETRY_PORT: TelemetryEventQueryPort = _NullTelemetryPort()

#: Meta-only registry (no FK-27 §27.4 stages): the default for a bare
#: ``StructuralChecker()`` so it runs only the canonical-state pre-checks
#: (pre-AG3-042 behaviour). The productive composition root injects the full
#: ``StageRegistry()`` instead.
_META_ONLY_REGISTRY: StageRegistry = StageRegistry(stages=())

#: The full canonical FK-27 §27.4 catalogue for productive wiring.
FULL_STAGE_REGISTRY: StageRegistry = StageRegistry()


class StructuralChecker:
    """Layer 1: deterministic structural checks (FK-27 §27.4 / FK-33 §33.3).

    Drives the stage registry's Layer-1 stages plus the mandatory canonical-
    state pre-checks. All checks run regardless of earlier failures
    (fail-closed, collect all findings). Satisfies the
    :class:`~agentkit.verify_system.protocols.QALayer` protocol.

    Args:
        registry: The stage registry that plans the Layer-1 stages
            (FK-33 §33.2). Defaults to a META-ONLY registry (empty stage
            tuple): the bare ``StructuralChecker()`` runs only the mandatory
            canonical-state pre-checks, preserving the pre-AG3-042 behaviour
            for callers that have not wired the productive evidence ports.
            The productive composition root (``build_verify_system``) injects
            the full canonical FK-27 §27.4 catalogue (``StageRegistry()``)
            together with the live telemetry / build-test / ARE ports so the
            complete Layer-1 stage suite runs on the real path. The new
            contract/integration tests pin that full path.
        telemetry: Telemetry event count port for the recurring guards
            (FK-27 §27.4.3). Default is the No-op port (BLOCKING guards fail
            closed). The productive SQLite adapter is wired via the
            composition root.
        build_test_port: Build/test/coverage evidence port (FK-27 §27.4.2).
            Default is the fail-closed absent port.
        are_provider: ARE activation + coverage verdict provider (FK-27
            §27.4.4 / AG3-030). Default is the absent provider (ARE disabled,
            ARE stage not planned).
        change_evidence_port: Independent SYSTEM change-evidence port (FK-33
            §33.5) consumed by the BLOCKING branch / commit / push / secrets /
            impact checks so they decide on real ``git`` evidence, NOT the
            worker manifest (FK-33 §33.5.2: a BLOCKING check may never gate on
            worker self-report). Default is the fail-closed absent port (the
            BLOCKING checks then FAIL until the productive provider is wired).
    """

    def __init__(
        self,
        *,
        registry: StageRegistry | None = None,
        telemetry: TelemetryEventQueryPort | None = None,
        build_test_port: BuildTestEvidencePort | None = None,
        are_provider: AreGateProvider | None = None,
        change_evidence_port: ChangeEvidencePort | None = None,
    ) -> None:
        self._registry = registry if registry is not None else _META_ONLY_REGISTRY
        self._telemetry = telemetry if telemetry is not None else _NULL_TELEMETRY_PORT
        self._build_test_port = (
            build_test_port if build_test_port is not None else ABSENT_BUILD_TEST_PORT
        )
        self._are_provider = (
            are_provider if are_provider is not None else _ABSENT_ARE_PROVIDER
        )
        self._change_evidence_port = (
            change_evidence_port
            if change_evidence_port is not None
            else ABSENT_CHANGE_EVIDENCE_PORT
        )

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"structural"``.
        """
        return "structural"

    @property
    def are_enabled(self) -> bool:
        """Return whether the ARE gate is active (FK-27 §27.4.4).

        Exposes the bound ARE provider's activation so the policy engine's
        fail-closed missing-stage check knows whether to expect the ``are.gate``
        stage (FIX-2). ONE ARE-activation truth (the injected provider), not a
        second flag.
        """
        return self._are_provider.is_enabled

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Run all Layer-1 checks and collect findings (FK-27 §27.4).

        Order: mandatory canonical-state pre-checks, then every applicable
        Layer-1 stage from the registry (each dispatched to its check with the
        registry-resolved severity). All checks run unconditionally -- no early
        returns. The layer passes only when no ``BLOCKING`` finding exists
        (FK-27 §27.4.2); an ``escalated`` stage FAIL stamps
        ``metadata["escalated"] = True`` (FK-27 §27.4.5).

        ``review_input`` is accepted but ignored by Layer 1 (Structural).

        Args:
            ctx: Story context for type-specific evaluation.
            story_dir: Directory containing story artifacts.
            review_input: Ignored by Layer 1 (QALayer protocol compatibility).

        Returns:
            LayerResult with all collected findings.
        """
        del review_input  # Layer 1 does not use review_input.
        findings: list[Finding] = []
        checks_run = 0

        # --- Mandatory canonical-state pre-checks (FK-27 §27.4 precondition) --
        checks_run += self._run_pre_checks(ctx, story_dir, findings)

        # --- Stage-registry-driven Layer-1 stages (FK-27 §27.4.1-§27.4.4) -----
        # FK-33 §33.5: collect the INDEPENDENT system change evidence ONCE (one
        # git read) and share it across the BLOCKING branch/commit/push/secrets/
        # impact + the hygiene checks, so they decide on system evidence rather
        # than the worker manifest.
        evidence = self._change_evidence_port.collect(story_dir)
        dispatch = self._dispatch(evidence)
        escalated = False
        for stage in self._registry.layer1_stages_for(
            ctx.story_type, are_enabled=self._are_provider.is_enabled
        ):
            checks_run += 1
            finding = self._run_stage(stage, dispatch, ctx, story_dir)
            if finding is not None:
                findings.append(finding)
                if stage.escalated and finding.severity == Severity.BLOCKING:
                    escalated = True

        passed = not any(f.severity == Severity.BLOCKING for f in findings)
        metadata: dict[str, object] = {"total_checks": checks_run}
        if escalated:
            # FK-27 §27.4.5: impact.violation routes directly to ESCALATED.
            metadata["escalated"] = True
        return LayerResult(
            layer=self.name,
            passed=passed,
            findings=tuple(findings),
            metadata=metadata,
        )

    def _run_pre_checks(
        self,
        ctx: StoryContext,
        story_dir: Path,
        findings: list[Finding],
    ) -> int:
        """Run the mandatory canonical-state pre-checks; return checks-run count."""
        checks_run = 0

        checks_run += 1
        f = check_context_exists(story_dir)
        if f:
            findings.append(f)

        checks_run += 1
        f = check_context_valid(story_dir)
        if f:
            findings.append(f)

        profile = get_profile(ctx.story_type)
        implementation_index = _phase_index(profile.phases, "implementation")
        required_prior = list(profile.phases[:implementation_index])
        checks_run += len(required_prior)
        findings.extend(check_phase_snapshots(story_dir, required_prior))

        checks_run += 1
        f = check_no_corrupt_state(story_dir)
        if f:
            findings.append(f)

        return checks_run

    def _run_stage(
        self,
        stage: StageDefinition,
        dispatch: dict[str, Callable[[StoryContext, Path, Severity], Finding | None]],
        ctx: StoryContext,
        story_dir: Path,
    ) -> Finding | None:
        """Dispatch one registry stage to its check function (fail-closed).

        Args:
            stage: The Layer-1 stage definition (severity source).
            dispatch: The pre-built stage-id -> bound check dispatch table
                (built once per ``evaluate`` with the collected evidence).
            ctx: Story context.
            story_dir: Story working directory.

        Returns:
            The stage's finding (``None`` = PASS).

        Raises:
            KeyError: If a registry stage has no wired check function -- a
                fail-closed signal that a stage exists but is dead code
                (ZERO DEBT: every registry stage MUST be dispatched).
        """
        handler = dispatch.get(stage.stage_id)
        if handler is None:
            msg = (
                f"No structural check wired for stage {stage.stage_id!r}; "
                "every Layer-1 stage in the registry MUST be dispatched "
                "(ZERO DEBT, no dead stage)."
            )
            raise KeyError(msg)
        return handler(ctx, story_dir, stage.severity)

    def _dispatch(
        self,
        evidence: ChangeEvidence,
    ) -> dict[str, Callable[[StoryContext, Path, Severity], Finding | None]]:
        """Build the stage-id -> bound check dispatch table.

        Every Layer-1 stage id in the registry has exactly one entry here;
        the extra per-check dependencies (telemetry port, build/test port, ARE
        verdict, the collected SYSTEM change evidence) are bound via closures so
        the dispatched callables share the uniform ``(ctx, story_dir, severity)``
        signature.

        Args:
            evidence: The independent system change evidence collected once for
                this ``evaluate`` (FK-33 §33.5), bound into the BLOCKING branch /
                commit / push / secrets / impact + the hygiene checks.
        """
        tel = self._telemetry
        bt = self._build_test_port
        are = self._are_provider
        ev = evidence

        return {
            # §27.4.1 Artefakt-Pruefung
            "artifact.protocol": lambda c, d, s: check_artifact_protocol(
                c, d, severity=s
            ),
            "artifact.worker_manifest": lambda c, d, s: check_artifact_worker_manifest(
                c, d, severity=s
            ),
            "artifact.manifest_claims": lambda c, d, s: check_artifact_manifest_claims(
                c, d, severity=s
            ),
            "artifact.handover": lambda c, d, s: check_artifact_handover(
                c, d, severity=s
            ),
            # §27.4.2 Branch & Completion (decide on SYSTEM git evidence).
            "branch.story": lambda c, d, s: check_branch_story(
                c, d, severity=s, evidence=ev
            ),
            "branch.commit_trailers": lambda c, d, s: check_branch_commit_trailers(
                c, d, severity=s, evidence=ev
            ),
            "completion.commit": lambda c, d, s: check_completion_commit(
                c, d, severity=s, evidence=ev
            ),
            "completion.push": lambda c, d, s: check_completion_push(
                c, d, severity=s, evidence=ev
            ),
            # §27.4.2 Security (decide on the SYSTEM diff secret-scan).
            _SECURITY_SECRETS_CHECK: lambda c, d, s: _check_security_secrets(
                c, d, severity=s, evidence=ev
            ),
            # §27.4.2 Build & Test
            "build.compile": lambda c, d, s: check_build_compile(
                c, d, severity=s, port=bt
            ),
            "build.test_execution": lambda c, d, s: check_build_test_execution(
                c, d, severity=s, port=bt
            ),
            "test.count": lambda c, d, s: check_test_count(c, d, severity=s, port=bt),
            "test.coverage": lambda c, d, s: check_test_coverage(
                c, d, severity=s, port=bt
            ),
            # §27.4.2 Code-Hygiene (scan the SYSTEM diff changed files).
            "hygiene.todo_fixme": lambda c, d, s: check_hygiene_todo_fixme(
                c, d, severity=s, evidence=ev
            ),
            "hygiene.disabled_tests": lambda c, d, s: check_hygiene_disabled_tests(
                c, d, severity=s, evidence=ev
            ),
            "hygiene.commented_code": lambda c, d, s: check_hygiene_commented_code(
                c, d, severity=s, evidence=ev
            ),
            # §27.4.3 Recurring Guards
            "guard.llm_reviews": lambda c, d, s: check_guard_llm_reviews(
                c, d, severity=s, telemetry=tel
            ),
            "guard.review_compliance": lambda c, d, s: check_guard_review_compliance(
                c, d, severity=s, telemetry=tel
            ),
            "guard.no_violations": lambda c, d, s: check_guard_no_violations(
                c, d, severity=s, telemetry=tel
            ),
            "guard.multi_llm": lambda c, d, s: check_guard_multi_llm(
                c, d, severity=s, telemetry=tel
            ),
            # §27.4.4 ARE-Gate
            "are.gate": lambda c, d, s: check_are_gate(
                c, d, severity=s,
                coverage_verdict=are.coverage_verdict(c.story_id, c.project_key),
            ),
            # §27.4.2 Impact (actual impact from SYSTEM evidence).
            "impact.violation": lambda c, d, s: check_impact_violation(
                c, d, severity=s, evidence=ev
            ),
        }


def _check_security_secrets(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-27 §27.4.2 ``security.secrets``: no secret files in the changeset.

    BLOCKING -> decides on the INDEPENDENT system ``git diff`` (the
    ``ChangeEvidence.secret_files`` computed over the real diff), NOT the worker
    manifest (FK-33 §33.5.2). Kept module-local (single small check; the other
    groups own multi-function modules).

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.2: BLOCKING).
        evidence: Independent system change evidence (the diff secret-scan).

    Returns:
        ``None`` on PASS; a BLOCKING finding when the system diff carries a
        secret-shaped path, or when the evidence is unconfirmable (fail-closed).
    """
    from agentkit.verify_system.protocols import TrustClass

    del ctx
    if not evidence.available:
        return Finding(
            layer="structural",
            check=_SECURITY_SECRETS_CHECK,
            severity=severity,
            message="system git diff unavailable; cannot scan the changeset for "
            "secrets independently -> fail-closed (FK-27 §27.4.2, FK-33 §33.5.2)",
            trust_class=TrustClass.SYSTEM,
        )
    if evidence.secret_files:
        first = evidence.secret_files[0]
        return Finding(
            layer="structural",
            check=_SECURITY_SECRETS_CHECK,
            severity=severity,
            message=f"secret-shaped file in the changeset (git diff): {first!r} "
            "(FK-27 §27.4.2)",
            trust_class=TrustClass.SYSTEM,
            file_path=str(story_dir / first),
        )
    return None


def _phase_index(phases: tuple[str, ...], target: str) -> int:
    """Find the index of a phase in the phase tuple.

    If the target phase is not found, returns the length of the tuple
    (i.e., all phases are considered prior).

    Args:
        phases: Ordered tuple of phase names.
        target: Phase name to locate.

    Returns:
        Index of the target phase, or ``len(phases)`` if not found.
    """
    for i, phase in enumerate(phases):
        if phase == target:
            return i
    return len(phases)
