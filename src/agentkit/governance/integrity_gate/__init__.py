"""Integrity gate -- canonical pre-closure process-integrity checks.

FK-35 §35.2: the gate validates **process integrity** before merge — that all
mandatory artifacts exist and all relevant dimensions hold.  It does not judge
implementation quality (that is the QA-subflow inside the Implementation phase,
FK-35 §35.2.2).

AG3-034 raises the gate to the nine-dimension schema (story.md §2.1.3) with a
mandatory-artifact pre-stage (FK-35 §35.2.3) and fixes the Concept/Research
drift via the single-source ``required_phases_for`` / ``dimensions_for``
(governance-and-guards.C4, story.md §2.1.4).  Each dimension verifies the exact
FK-35 §35.2.4 condition against the canonical QA ``ArtifactEnvelope`` (producer /
status / depth / threshold), not mere existence (AG3-034 Remediation E-A).

DI: ``IntegrityGate`` receives an ``IntegrityGateStatePort`` (Fix E9, AG3-031);
the composition root
(``agentkit.bootstrap.composition_root.build_integrity_gate``) is the canonical
wiring point.  Envelope field validation (FK-71 §71.2) for every mandatory QA
artifact (structural + decision) runs through the injected ``envelope_validator``
(AG3-034 AK7 / E-F).  Dimension 9 verifies the commit-bound Sonar attestation
through the injected ``sonar_port`` (AG3-052 capability) and fails closed for an
APPLICABLE run whose attestation/port is missing (FK-35 §35.2.4a / E-C).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.exceptions import CorruptStateError
from agentkit.governance.integrity_gate.dimensions import (
    IntegrityDimension,
    dimensions_for,
    evaluate_dimension,
    evaluate_mandatory_artifact,
    mandatory_dimensions_for,
    required_phases_for,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.artifacts.validator import EnvelopeValidator
    from agentkit.governance.integrity_gate.dim9_sonar import (
        Dim9Resolution,
        FreshAttestation,
        SonarDimensionPort,
    )
    from agentkit.governance.repository import IntegrityGateStatePort
    from agentkit.state_backend.scope import RuntimeStateScope
    from agentkit.story_context_manager.types import StoryType


class IntegrityGateStatus(StrEnum):
    """Aggregated integrity outcome (story.md §2.1.3)."""

    PASS = "PASS"
    FAIL = "FAIL"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True)
class DimensionResult:
    """Result of one integrity dimension (story.md §2.1.3)."""

    dimension: IntegrityDimension
    passed: bool
    failure_reason: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class IntegrityGateContext:
    """Story directory + type context passed to the dimension checkers."""

    story_dir: Path
    story_type: StoryType


@dataclass(frozen=True)
class IntegrityGateResult:
    """Aggregated integrity outcome (story.md §2.1.3).

    Attributes:
        overall: ``PASS`` / ``FAIL`` / ``ESCALATED``.
        dimension_results: Per-dimension results keyed by the canonical FK-35
            §35.2.4 :class:`IntegrityDimension` (only the dimensions actually
            evaluated; concept/research omit Dim 5/6 — AK8).
        missing_artifacts: ``MISSING_*`` reasons of any absent mandatory
            artifact (FK-35 §35.2.3).
        blocked_dimensions: Dimensions 3-9 that were not evaluated because the
            mandatory pre-stage aborted (AK6).
        failure_reason: The first hard failure reason (``MISSING_*`` /
            ``ENVELOPE_VIOLATION`` / dimension id / ``SONAR_NOT_GREEN``), else
            ``None``.
    """

    overall: IntegrityGateStatus
    dimension_results: dict[IntegrityDimension, DimensionResult]
    missing_artifacts: list[str] = field(default_factory=list)
    blocked_dimensions: list[IntegrityDimension] = field(default_factory=list)
    failure_reason: str | None = None

    @property
    def passed(self) -> bool:
        """Boolean alias for ``overall == PASS``."""
        return self.overall is IntegrityGateStatus.PASS

    @property
    def failed_dimensions(self) -> tuple[DimensionResult, ...]:
        """The failing dimension results, in evaluation order."""
        return tuple(r for r in self.dimension_results.values() if not r.passed)


class IntegrityGate:
    """Run the nine integrity dimensions before closure (FK-35 §35.2 / §35.2.4).

    Args:
        state_port: Read-only state access port (must be provided; use
            ``build_integrity_gate()``).
        envelope_validator: Optional envelope field validator (FK-71 §71.2).
            When provided, the mandatory structural AND decision dimensions
            additionally validate their canonical QA envelopes and fail with
            ``ENVELOPE_VIOLATION`` on a violation (AK7 / E-F).
        sonar_port: Optional ``sonarqube_gate`` capability seam for Dimension 9
            (FK-35 §35.2.4a, AG3-052).  For an APPLICABLE impl/bugfix run the
            port resolves the commit-bound verification inputs; a missing port
            or attestation on an APPLICABLE run is a fail-closed
            ``SONAR_NOT_GREEN`` (ESCALATED) — NEVER a silent skip (E-C).  A
            genuinely not-applicable resolution (``available == false`` / fast /
            concept-research) omits Dim 9.  ``build_integrity_gate`` wires the
            productive Closure port; an absent port for an APPLICABLE run still
            fails closed via :meth:`_resolve_dim9_inputs`.
    """

    def __init__(
        self,
        state_port: IntegrityGateStatePort,
        *,
        envelope_validator: EnvelopeValidator | None = None,
        sonar_port: SonarDimensionPort | None = None,
    ) -> None:
        self._state_port: IntegrityGateStatePort = state_port
        self._envelope_validator = envelope_validator
        self._sonar_port = sonar_port
        #: Per-``evaluate`` Dim-9 resolution resolved once via the capability port
        #: (``None`` == code story with no port wired -> fail-closed, E-C).
        self._dim9_resolution: Dim9Resolution | None = None

    def evaluate(
        self,
        story_dir: Path,
        story_type: StoryType,
        *,
        fresh_attestation: FreshAttestation | None = None,
    ) -> IntegrityGateResult:
        """Evaluate all integrity dimensions for the given story (FK-35 §35.2).

        Phase 1 (mandatory pre-stage, FK-35 §35.2.3): Dim 1-2-4 must all exist.
        A missing one aborts with that ``MISSING_*`` failure reason; the
        post-mandatory dimensions are reported as ``blocked_dimensions`` (AK6).
        Phase 2: the remaining dimensions (Dim 5/6 only for implementation/
        bugfix, AK8; Dim 9 only when APPLICABLE, E-C).

        Args:
            story_dir: Story base directory.
            story_type: Type of the story being evaluated.
            fresh_attestation: The fresh, commit-bound attestation the Closure
                pre-merge scan (AG3-056) produced (FK-29 §29.1a.3 d). When
                supplied, Dim 9 VERIFIES exactly this attestation (green +
                commit-binding + config/version drift) and NEVER re-reads the
                worktree (FK-35 §35.2.4a — "verifiziert die FRISCHE Attestation",
                no stale local read). ``None`` keeps the legacy capability-port
                resolution path (e.g. the non-Closure / unit-test gate).

        Returns:
            An :class:`IntegrityGateResult`.
        """
        gate_ctx = IntegrityGateContext(story_dir=story_dir, story_type=story_type)
        runtime_scope = self._resolve_scope(story_dir)
        results: dict[IntegrityDimension, DimensionResult] = {}

        sonar_applicable = self._resolve_sonar_applicable(
            gate_ctx, story_type, fresh_attestation=fresh_attestation
        )

        mandatory_failure = self._run_mandatory(gate_ctx, runtime_scope, results)
        if mandatory_failure is not None:
            return self._aborted_result(
                gate_ctx, results, mandatory_failure, sonar_applicable
            )

        escalated = False
        for dim in dimensions_for(story_type, sonar_applicable=sonar_applicable):
            if dim is IntegrityDimension.SONARQUBE_GREEN:
                result = self._verify_dim9(gate_ctx, fresh_attestation)
                results[dim] = result
                escalated = escalated or not result.passed
                continue
            results[dim] = evaluate_dimension(
                dim,
                gate_ctx,
                state_port=self._state_port,
                runtime_scope=runtime_scope,
            )
        return self._final_result(results, escalated=escalated)

    def _run_mandatory(
        self,
        gate_ctx: IntegrityGateContext,
        runtime_scope: RuntimeStateScope | None,
        results: dict[IntegrityDimension, DimensionResult],
    ) -> DimensionResult | None:
        """Evaluate the mandatory pre-stage; return the first failure, else ``None``."""
        for dim in mandatory_dimensions_for(gate_ctx.story_type):
            result = evaluate_mandatory_artifact(
                dim,
                gate_ctx,
                state_port=self._state_port,
                runtime_scope=runtime_scope,
                envelope_validator=self._envelope_validator,
            )
            results[dim] = result
            if not result.passed:
                return result
        return None

    def _resolve_scope(self, story_dir: Path) -> RuntimeStateScope | None:
        try:
            return self._state_port.resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return None

    def _resolve_sonar_applicable(
        self,
        gate_ctx: IntegrityGateContext,
        story_type: StoryType,
        *,
        fresh_attestation: FreshAttestation | None = None,
    ) -> bool:
        """Whether Dim 9 is APPLICABLE (FK-33 §33.6.5 / FK-35 §35.2.4a, E-C).

        Concept/research never evaluate Dim 9.  For impl/bugfix the resolution
        comes from the capability port; a missing port on a code story is
        treated as APPLICABLE-but-unresolvable -> fail-closed, NOT a skip (the
        port is the only thing that can prove a deliberate skip via
        ``available == false`` / fast).  Returns ``True`` when Dim 9 must be
        evaluated (and may fail closed), ``False`` when it is skipped.

        Closure pre-merge path (FK-29 §29.1a.3 / §35.2.4a): when the barrier
        supplies a ``fresh_attestation``, Dim 9 is APPLICABLE and verified
        against THAT supplied attestation directly — the capability port is NOT
        consulted (no stale worktree re-read).
        """
        from agentkit.story_context_manager.types import StoryType as _StoryType

        if story_type not in (_StoryType.IMPLEMENTATION, _StoryType.BUGFIX):
            return False
        if fresh_attestation is not None:
            # A fresh pre-merge attestation was produced: Dim 9 is APPLICABLE and
            # verifies exactly it (no port resolution, no worktree re-read).
            self._dim9_resolution = None
            return True
        if self._sonar_port is None:
            # Code story but no capability wired: cannot prove a deliberate
            # skip -> APPLICABLE, and Dim 9 fails closed (E-C).
            self._dim9_resolution = None
            return True
        resolution = self._sonar_port.resolve_dim9_outcome(gate_ctx)
        self._dim9_resolution = resolution
        return self._is_applicable(resolution)

    @staticmethod
    def _is_applicable(resolution: Dim9Resolution) -> bool:
        """Whether the resolved capability outcome is APPLICABLE (FK-33 §33.6.5)."""
        from agentkit.verify_system.sonarqube_gate import SonarApplicability

        return resolution.applicability is SonarApplicability.APPLICABLE

    def _verify_dim9(
        self,
        gate_ctx: IntegrityGateContext,
        fresh_attestation: FreshAttestation | None = None,
    ) -> DimensionResult:
        """Verify Dim 9 over the resolved inputs (FK-35 §35.2.4a, E-C).

        Reached only for an APPLICABLE Dim 9.  Closure pre-merge path: when a
        ``fresh_attestation`` was supplied, Dim 9 verifies exactly THAT fresh
        attestation (green + commit-binding + config/version drift), never
        re-reading the worktree (FK-29 §29.1a.3 / §35.2.4a).  Otherwise (legacy
        path) it maps the capability-port resolution; a code story without a
        wired ``sonar_port`` is APPLICABLE-but-unresolvable -> fail-closed
        ``SONAR_NOT_GREEN`` (never a silent skip).
        """
        del gate_ctx
        from agentkit.governance.integrity_gate.dim9_sonar import (
            SONAR_NOT_GREEN,
            verify_fresh_attestation,
            verify_sonarqube_green,
        )

        if fresh_attestation is not None:
            return verify_fresh_attestation(fresh_attestation)

        resolution = self._dim9_resolution
        if resolution is None:
            return DimensionResult(
                dimension=IntegrityDimension.SONARQUBE_GREEN,
                passed=False,
                failure_reason=SONAR_NOT_GREEN,
                detail=(
                    "sonarqube_gate APPLICABLE but no capability port wired "
                    "(configured-but-unreachable -> fail-closed, FK-35 §35.2.4a)"
                ),
            )
        return verify_sonarqube_green(resolution)

    def _aborted_result(
        self,
        gate_ctx: IntegrityGateContext,
        results: dict[IntegrityDimension, DimensionResult],
        failure: DimensionResult,
        sonar_applicable: bool,
    ) -> IntegrityGateResult:
        """Build the result for a mandatory-pre-stage abort (later dims blocked)."""
        blocked = list(
            dimensions_for(gate_ctx.story_type, sonar_applicable=sonar_applicable)
        )
        missing = [
            r.failure_reason or r.dimension.value
            for r in results.values()
            if not r.passed
        ]
        return IntegrityGateResult(
            overall=IntegrityGateStatus.FAIL,
            dimension_results=dict(results),
            missing_artifacts=missing,
            blocked_dimensions=blocked,
            failure_reason=failure.failure_reason or failure.dimension.value,
        )

    def _final_result(
        self,
        results: dict[IntegrityDimension, DimensionResult],
        *,
        escalated: bool = False,
    ) -> IntegrityGateResult:
        """Build the result after all evaluated dimensions ran.

        A failing Dim 9 (``SONAR_NOT_GREEN``) escalates the gate
        (``ESCALATED``, FK-35 §35.2.4a / §35.2.9); any other failure is a plain
        ``FAIL``.
        """
        first_failure = next(
            (r for r in results.values() if not r.passed),
            None,
        )
        if first_failure is None:
            overall = IntegrityGateStatus.PASS
        elif escalated:
            overall = IntegrityGateStatus.ESCALATED
        else:
            overall = IntegrityGateStatus.FAIL
        return IntegrityGateResult(
            overall=overall,
            dimension_results=dict(results),
            missing_artifacts=[],
            blocked_dimensions=[],
            failure_reason=(
                None
                if first_failure is None
                else (first_failure.failure_reason or first_failure.dimension.value)
            ),
        )


__all__ = [
    "DimensionResult",
    "IntegrityDimension",
    "IntegrityGate",
    "IntegrityGateContext",
    "IntegrityGateResult",
    "IntegrityGateStatus",
    "required_phases_for",
]
