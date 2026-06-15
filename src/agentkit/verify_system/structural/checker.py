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

from pathlib import Path  # noqa: TC003  -- Path used in runtime path operations
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.story_context_manager.types import get_profile
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
)
from agentkit.verify_system.stage_registry.registry import StageRegistry
from agentkit.verify_system.structural.checks import (
    ABSENT_BUGFIX_EVIDENCE_PORT,
    ABSENT_BUILD_TEST_PORT,
    ABSENT_CHANGE_EVIDENCE_PORT,
    BugfixEvidencePort,
    BuildTestEvidencePort,
    ChangeEvidencePort,
    check_are_gate,
    check_artifact_handover,
    check_artifact_manifest_claims,
    check_artifact_protocol,
    check_artifact_worker_manifest,
    check_branch_commit_trailers,
    check_branch_story,
    check_bugfix_green_evidence,
    check_bugfix_red_evidence,
    check_bugfix_red_green_consistency,
    check_bugfix_reproducer_manifest,
    check_bugfix_suite_evidence,
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

    from agentkit.requirements_coverage.contract import CoverageVerdict
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
    from agentkit.verify_system.protocols import TelemetryEventQueryPort
    from agentkit.verify_system.stage_registry.stages import StageDefinition
    from agentkit.verify_system.structural.system_evidence import ChangeEvidence

__all__ = ["FULL_STAGE_REGISTRY", "AreGateProvider", "StructuralChecker"]

_SECURITY_SECRETS_CHECK = "security.secrets"
_SECURITY_SECRETS_CONTENT_CHECK = "security.secrets_content"

# Integration-stabilization Layer-1 stage ID constants (S1192: each appears 3+x).
# Values MUST remain byte-identical to stage_registry/data.py and
# integration_stabilization/stability_gate_producer.py.
_IS_STAGE_MANIFEST_APPROVAL = "integration.manifest_approval_required"
_IS_STAGE_BINDING_INTEGRITY = "integration.binding_integrity"
_IS_STAGE_DECLARED_SURFACES_ONLY = "integration.declared_surfaces_only"
_IS_STAGE_BUDGET_NOT_EXHAUSTED = "integration.stabilization_budget_not_exhausted"


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
        bugfix_port: BugfixEvidencePort | None = None,
        are_provider: AreGateProvider | None = None,
        change_evidence_port: ChangeEvidencePort | None = None,
    ) -> None:
        self._registry = registry if registry is not None else _META_ONLY_REGISTRY
        self._telemetry = telemetry if telemetry is not None else _NULL_TELEMETRY_PORT
        self._build_test_port = (
            build_test_port if build_test_port is not None else ABSENT_BUILD_TEST_PORT
        )
        self._bugfix_port = (
            bugfix_port if bugfix_port is not None else ABSENT_BUGFIX_EVIDENCE_PORT
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
        pre_check_count, pre_check_ids = self._run_pre_checks(ctx, story_dir, findings)
        checks_run += pre_check_count

        # --- Stage-registry-driven Layer-1 stages (FK-27 §27.4.1-§27.4.4) -----
        # FK-33 §33.5: collect the INDEPENDENT system change evidence ONCE (one
        # git read) and share it across the BLOCKING branch/commit/push/secrets/
        # impact + the hygiene checks, so they decide on system evidence rather
        # than the worker manifest.
        evidence = self._change_evidence_port.collect(story_dir)
        dispatch = self._dispatch(evidence, story_dir=story_dir)
        escalated = False
        stage_ids_run: list[str] = []
        for stage in self._registry.layer1_stages_for(
            ctx.story_type,
            are_enabled=self._are_provider.is_enabled,
            implementation_contract=ctx.implementation_contract,
        ):
            checks_run += 1
            stage_ids_run.append(stage.stage_id)
            finding = self._run_stage(stage, dispatch, ctx, story_dir)
            if finding is not None:
                findings.append(finding)
                if stage.escalated and finding.severity == Severity.BLOCKING:
                    escalated = True

        # AG3-108: populate executed_check_ids so CheckOutcomeEmitter can emit
        # clean rows for PASS checks (not just triggered from findings).
        # Includes both pre-check IDs and stage IDs (full executed set).
        executed_check_ids: list[str] = pre_check_ids + stage_ids_run

        passed = not any(f.severity == Severity.BLOCKING for f in findings)
        metadata: dict[str, object] = {
            "total_checks": checks_run,
            "stage_ids": tuple(stage_ids_run),
            "stage_producers": {
                stage.stage_id: stage.producer
                for stage in self._registry.layer1_stages_for(
                    ctx.story_type,
                    are_enabled=self._are_provider.is_enabled,
                    implementation_contract=ctx.implementation_contract,
                )
            },
            # FK-69 §69.15: full set of executed check identifiers so the
            # CheckOutcomeEmitter can emit clean rows for PASS checks.
            "executed_check_ids": tuple(executed_check_ids),
        }
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
    ) -> tuple[int, list[str]]:
        """Run the mandatory canonical-state pre-checks.

        Returns:
            A 2-tuple ``(checks_run_count, executed_check_ids)``.  The
            ``executed_check_ids`` list contains one entry per check that
            actually ran (AG3-108: needed for CheckOutcomeEmitter clean-row
            emission).
        """
        checks_run = 0
        check_ids_run: list[str] = []

        checks_run += 1
        check_ids_run.append("context_exists")
        f = check_context_exists(story_dir)
        if f:
            findings.append(f)

        checks_run += 1
        check_ids_run.append("context_valid")
        f = check_context_valid(story_dir)
        if f:
            findings.append(f)

        profile = get_profile(ctx.story_type)
        implementation_index = _phase_index(profile.phases, "implementation")
        required_prior = list(profile.phases[:implementation_index])
        checks_run += len(required_prior)
        # One "phase_snapshots" check ID per required phase (matches Finding.check).
        check_ids_run.extend("phase_snapshots" for _ in required_prior)
        findings.extend(check_phase_snapshots(story_dir, required_prior))

        checks_run += 1
        check_ids_run.append("no_corrupt_state")
        f = check_no_corrupt_state(story_dir)
        if f:
            findings.append(f)

        return checks_run, check_ids_run

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
        *,
        story_dir: Path,
    ) -> dict[str, Callable[[StoryContext, Path, Severity], Finding | None]]:
        """Build the stage-id -> bound check dispatch table.

        Every Layer-1 stage id in the registry has exactly one entry here;
        the extra per-check dependencies (telemetry port, build/test port, ARE
        verdict, the collected SYSTEM change evidence) are bound via closures so
        the dispatched callables share the uniform ``(ctx, story_dir, severity)``
        signature.

        AG3-069: integration-stabilization stages (``integration.*``) are also
        dispatched here. They load manifest/approval state from ``story_dir``
        and fail closed when state is absent.

        Args:
            evidence: The independent system change evidence collected once for
                this ``evaluate`` (FK-33 §33.5), bound into the BLOCKING branch /
                commit / push / secrets / impact + the hygiene checks.
            story_dir: The story working directory. Passed to IS-stage handlers
                that load manifest/approval state from the filesystem.
        """
        tel = self._telemetry
        bt = self._build_test_port
        bugfix = self._bugfix_port
        are = self._are_provider
        ev = evidence
        s_dir = story_dir

        return {
            # §27.4.1 Artifact check
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
            _SECURITY_SECRETS_CONTENT_CHECK: lambda c, d, s: (
                _check_security_secrets_content(c, d, severity=s, evidence=ev)
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
            # FK-26 §26.9 Bugfix Red-Green-Suite
            "bugfix.reproducer_manifest": lambda c, d, s: (
                check_bugfix_reproducer_manifest(c, d, severity=s, port=bugfix)
            ),
            "bugfix.red_evidence": lambda c, d, s: check_bugfix_red_evidence(
                c, d, severity=s, port=bugfix
            ),
            "bugfix.green_evidence": lambda c, d, s: check_bugfix_green_evidence(
                c, d, severity=s, port=bugfix
            ),
            "bugfix.suite_evidence": lambda c, d, s: check_bugfix_suite_evidence(
                c, d, severity=s, port=bugfix
            ),
            "bugfix.red_green_consistency": lambda c, d, s: (
                check_bugfix_red_green_consistency(c, d, severity=s, port=bugfix)
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
            # AG3-069 (FK-05 §5.5.4/§5.10/§5.14, FK-37 §37.1.3):
            # integration-stabilization Layer-1 stages. These stages only run
            # for stories with implementation_contract=INTEGRATION_STABILIZATION
            # (filtered by StageRegistry.layer1_stages_for with contract param).
            # All load manifest/approval state from story_dir; absent state is
            # a fail-closed BLOCK (no state = no approved manifest = blocked).
            _IS_STAGE_MANIFEST_APPROVAL: (
                lambda c, d, s: _check_is_manifest_approval_required(
                    c, s_dir, severity=s
                )
            ),
            _IS_STAGE_BINDING_INTEGRITY: (
                lambda c, d, s: _check_is_binding_integrity(c, s_dir, severity=s)
            ),
            _IS_STAGE_DECLARED_SURFACES_ONLY: (
                lambda c, d, s: _check_is_declared_surfaces_only(
                    c, s_dir, severity=s, evidence=ev
                )
            ),
            _IS_STAGE_BUDGET_NOT_EXHAUSTED: (
                lambda c, d, s: _check_is_stabilization_budget_not_exhausted(
                    c, s_dir, severity=s
                )
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


def _check_security_secrets_content(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-15 §15.5.2 ``security.secrets_content``: no secret content in diff."""
    from agentkit.verify_system.protocols import TrustClass

    del ctx
    if not evidence.available:
        return Finding(
            layer="structural",
            check=_SECURITY_SECRETS_CONTENT_CHECK,
            severity=severity,
            message="system git diff unavailable; cannot scan diff content for "
            "secrets independently -> fail-closed (FK-15 §15.5.2)",
            trust_class=TrustClass.SYSTEM,
        )
    if evidence.secret_content_hits:
        first = evidence.secret_content_hits[0]
        path = first.split(":", maxsplit=1)[0]
        return Finding(
            layer="structural",
            check=_SECURITY_SECRETS_CONTENT_CHECK,
            severity=severity,
            message=f"secret-shaped content in the changeset (git diff): {first!r} "
            "(FK-15 §15.5.2)",
            trust_class=TrustClass.SYSTEM,
            file_path=str(story_dir / path),
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


# ---------------------------------------------------------------------------
# AG3-069 (FK-05 §5.5.4/§5.10/§5.14, FK-37 §37.1.3):
# Integration-stabilization Layer-1 structural check functions.
# These are wired into _dispatch() above as the real production checks for
# ``integration.*`` stage ids. They load manifest/approval state from
# story_dir and are fail-closed: absent state = BLOCKING (no approved
# manifest means no productive IS work).
# ---------------------------------------------------------------------------


def _check_is_manifest_approval_required(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """Layer-1 IS check: manifest_approval_required (FK-05 §5.5.4, AC12).

    Fail-closed: if no ManifestApprovalRecord is present in story_dir,
    productive integration work is blocked (enforcement point 1).

    Args:
        ctx: Story context (unused beyond guard).
        story_dir: Story working directory.
        severity: Registry-resolved severity (BLOCKING).

    Returns:
        ``None`` when an approval record is present; a BLOCKING finding
        otherwise.
    """
    del ctx
    from agentkit.integration_stabilization.state import load_manifest_approval
    from agentkit.verify_system.protocols import TrustClass

    approval = load_manifest_approval(story_dir)
    if approval is None:
        return Finding(
            layer="structural",
            check=_IS_STAGE_MANIFEST_APPROVAL,
            severity=severity,
            message=(
                "No ManifestApprovalRecord found in story directory. "
                "Integration-stabilization work is fail-closed blocked without "
                "an approved manifest record (FK-05 §5.5.1/§5.5.4, AC2/AC12)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
    return None


def _check_is_binding_integrity(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """Layer-1 IS check: binding_integrity (FK-05 §5.5.4, AC12).

    Fail-closed: if the approval record does not bind the manifest (hash/
    version/run mismatch), productive work is blocked.

    Args:
        ctx: Story context (provides run_id for binding check).
        story_dir: Story working directory.
        severity: Registry-resolved severity (BLOCKING).

    Returns:
        ``None`` when binding is valid; a BLOCKING finding otherwise.
    """
    from agentkit.integration_stabilization.preconditions import check_binding_integrity
    from agentkit.integration_stabilization.state import (
        load_integration_manifest,
        load_manifest_approval,
    )
    from agentkit.verify_system.protocols import TrustClass

    manifest = load_integration_manifest(story_dir)
    approval = load_manifest_approval(story_dir)
    if manifest is None or approval is None:
        # Absent state is caught by _check_is_manifest_approval_required first;
        # but guard against a missing manifest here too (fail-closed).
        return Finding(
            layer="structural",
            check=_IS_STAGE_BINDING_INTEGRITY,
            severity=severity,
            message=(
                "Missing manifest or approval record; cannot verify binding "
                "integrity (FK-05 §5.5.4, AC12)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
    # Use story_id as a fallback run_id if the context has no run.
    run_id = getattr(ctx, "run_id", None) or ctx.story_id
    result = check_binding_integrity(manifest, approval, current_run_id=run_id)
    if not result.binding_valid:
        return Finding(
            layer="structural",
            check=_IS_STAGE_BINDING_INTEGRITY,
            severity=severity,
            message=(
                f"Manifest-approval binding integrity failed: {result.reason} "
                "(FK-05 §5.5.4, AC12 / invariant: binding_integrity)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
    return None


def _check_is_declared_surfaces_only(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """Layer-1 IS check: declared_surfaces_only (FK-05 §5.10, FK-37 §37.1.3).

    Deterministic structural check (no LLM path). Compares the
    SYSTEM-evidence touched paths against the manifest's declared seams.

    Fail-closed: absent manifest → BLOCKING.

    Args:
        ctx: Story context (unused beyond guard).
        story_dir: Story working directory.
        severity: Registry-resolved severity (BLOCKING).
        evidence: System change evidence carrying the touched paths.

    Returns:
        ``None`` when all touched paths are declared; a BLOCKING finding
        for the first undeclared path otherwise.
    """
    del ctx
    from agentkit.integration_stabilization.declared_surfaces_check import (
        check_declared_surfaces_only,
    )
    from agentkit.integration_stabilization.seam_allowlist_guard import (
        materialize_seam_allowlist,
    )
    from agentkit.integration_stabilization.state import (
        load_integration_manifest,
        read_quarantine_state,
    )
    from agentkit.verify_system.protocols import TrustClass

    manifest = load_integration_manifest(story_dir)
    if manifest is None:
        return Finding(
            layer="structural",
            check=_IS_STAGE_DECLARED_SURFACES_ONLY,
            severity=severity,
            message=(
                "No IntegrationScopeManifest found; cannot verify declared "
                "surfaces (fail-closed, FK-05 §5.10, AC6)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
    seam_allowlist = materialize_seam_allowlist(manifest)
    touched_paths = tuple(evidence.changed_files) if evidence.available else ()
    # AG3-069 (AC10, FK-05 §5.7/§5.13): a touched path matching a quarantined
    # pre-snapshot cross-scope delta is BLOCKING even within a declared seam —
    # reclassification never retroactively legalizes a pre-manifest delta.
    quarantined = read_quarantine_state(story_dir)
    result = check_declared_surfaces_only(
        touched_paths=touched_paths,
        manifest=manifest,
        seam_allowlist=seam_allowlist,
        quarantined_deltas=quarantined,
    )
    if not result.passed and result.findings:
        # Return the first BLOCKING finding; the stage loop collects one per run.
        return Finding(
            layer="structural",
            check=_IS_STAGE_DECLARED_SURFACES_ONLY,
            severity=severity,
            message=result.findings[0].message,
            trust_class=TrustClass.SYSTEM,
        )
    return None


def _check_is_stabilization_budget_not_exhausted(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """Layer-1 IS check: stabilization_budget_not_exhausted (FK-05 §5.9).

    Primary: hook/capability layer (live-blocking). This structural check
    also audits budget exhaustion in the QA-subflow per FK-37 §37.1.3.

    The budget counters are read from the persisted manifest's caps. A
    live budget counter file (``integration_budget.json``) is loaded if
    present; otherwise the caps are used as defaults (loops_used=0).

    Args:
        ctx: Story context (unused beyond guard).
        story_dir: Story working directory.
        severity: Registry-resolved severity (BLOCKING).

    Returns:
        ``None`` when within budget; a BLOCKING finding when any cap is
        exhausted.
    """
    del ctx
    import json as _json

    from agentkit.integration_stabilization.models import (
        StabilizationBudget,
    )
    from agentkit.integration_stabilization.preconditions import (
        check_budget_not_exhausted,
    )
    from agentkit.integration_stabilization.state import load_integration_manifest
    from agentkit.verify_system.protocols import TrustClass

    manifest = load_integration_manifest(story_dir)
    if manifest is None:
        return Finding(
            layer="structural",
            check=_IS_STAGE_BUDGET_NOT_EXHAUSTED,
            severity=severity,
            message=(
                "No IntegrationScopeManifest found; cannot verify budget "
                "(fail-closed, FK-05 §5.9, AC4)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
    # Load live budget counters if a counter file exists; default to zeroed.
    budget_file = story_dir / "integration_budget.json"
    counters: dict[str, int] = {}
    if budget_file.exists():
        try:
            counters = _json.loads(budget_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            counters = {}
    budget = StabilizationBudget(
        caps=manifest.stabilization_budget,
        loops_used=int(counters.get("loops_used", 0)),
        new_surfaces_used=int(counters.get("new_surfaces_used", 0)),
        contract_changes_used=int(counters.get("contract_changes_used", 0)),
        regressions_this_cycle=int(counters.get("regressions_this_cycle", 0)),
    )
    result = check_budget_not_exhausted(budget)
    if not result.within_budget:
        return Finding(
            layer="structural",
            check=_IS_STAGE_BUDGET_NOT_EXHAUSTED,
            severity=severity,
            message=(
                f"Stabilization budget exhausted: {list(result.exhausted_caps)}. "
                "No further productive integration steps are allowed "
                "(FK-05 §5.9, AC4 / invariant: budget_exhaustion_blocks_live_capability)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
    return None
