"""QA layer contracts -- defines what every QA layer must provide.

Central types for the 4-layer QA system. All result types are frozen
dataclasses (ARCH-29). Business results via return types, not
exceptions (ARCH-20).

Severity stammt seit AG3-021 aus ``agentkit.core_types`` und nutzt das
FK-27-normative Vokabular BLOCKING/MAJOR/MINOR (kein
CRITICAL/HIGH/MEDIUM/LOW/INFO mehr).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.core_types import Severity

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput


__all__ = [
    "ASSERTION_WEAKNESS_FINDING_TYPE",
    "Finding",
    "LayerResult",
    "QALayer",
    "RunScope",
    "Severity",
    "StoryContextQueryPort",
    "TelemetryEventQueryPort",
    "TrustClass",
]


@runtime_checkable
class TelemetryEventQueryPort(Protocol):
    """Read-only Port for counting canonical telemetry ``execution_events``.

    FK-27 §27.4.3 Recurring Guards are telemetry-based: they count
    ``review_request`` / ``review_compliant`` / ``integrity_violation`` /
    ``llm_call_complete`` events for a story run. The verify-system BC must NOT import
    ``state_backend.store`` directly (AG3-035 BC-topology); the productive
    SQLite-backed adapter is wired via
    ``bootstrap.composition_root.build_verify_system``. The default No-op
    port returns ``0`` for every event type so the BLOCKING REF-036 guards
    (``guard.llm_reviews`` / ``guard.multi_llm``) FAIL CLOSED when no
    telemetry is wired (NO ERROR BYPASSING).
    """

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
        """Count canonical ``execution_events`` of ``event_type`` for the story.

        FK-33 §33.3.2 scopes the recurring guards to ``(project_key, story_id,
        run_id)`` -- a count must not bleed across projects or prior runs of the
        same story. The caller passes ``project_key`` (from the ``StoryContext``)
        and the adapter resolves/uses ``run_id`` for the active run; ``None`` for
        either means "do not filter on that dimension" (the resolved run scope is
        applied by the productive adapter).

        Args:
            story_dir: Story working directory (event store root).
            story_id: Story display id whose events are counted.
            event_type: The ``execution_events.event_type`` to count
                (FK-27 §27.4.3: ``review_request`` / ``review_compliant`` /
                ``integrity_violation`` / ``llm_call_complete``).
            role: Optional reviewer-role payload filter (FK-27 §27.4.3 Gate 2:
                ``llm_call_complete`` events carry the reviewer ``role`` in their
                payload). When given, only events whose ``payload['role']``
                matches are counted.
            project_key: Owning project key (FK-33 run scope). ``None`` => not
                filtered on project.
            run_id: Active run id (FK-33 run scope). ``None`` => the adapter
                resolves the active run for ``story_dir`` (so a prior run's
                events never count toward the current guard).

        Returns:
            The number of matching events (``0`` when none / unresolvable).
        """
        ...

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        """Whether the active run scope for ``story_dir`` is resolvable.

        FK-33 §33.3.2 run scope (FIX-B, fail-CLOSED): the recurring guards count
        events of the CURRENT run only. A count of ``0`` is ambiguous -- it can
        mean "no such event in this run" OR "the run scope could not be resolved
        so nothing was counted". For the must-have-events guards
        (``guard.llm_reviews`` / ``guard.review_compliance`` /
        ``guard.multi_llm``) both readings fail closed (they require a positive
        count). But ``guard.no_violations`` PASSES on ``0``; it would therefore
        FREE-PASS on an unresolvable scope. This probe lets that guard fail
        closed when the run scope is unknown, so no recurring guard ever passes
        on an unresolvable run scope.

        Args:
            story_dir: Story working directory (event store root).

        Returns:
            ``True`` iff the active run id for ``story_dir`` could be resolved;
            ``False`` when no run scope is known (fail-closed signal).
        """
        ...


@runtime_checkable
class StoryContextQueryPort(Protocol):
    """Read-only Port zum Aufloesen eines ``StoryContext`` fuer die QA-Auswertung.

    AG3-035 (echter Drift-Fix): eliminiert den direkten
    ``agentkit.state_backend.store``-Import innerhalb von ``verify_system``. Der
    konkrete Adapter lebt im state-backend-BC und wird via
    ``bootstrap.composition_root.build_verify_system`` verdrahtet. BC-Topologie:
    ``verify-system`` haengt von diesem Port ab, nicht von ``state_backend.store``.
    """

    def load(self, story_dir: Path) -> StoryContext | None:
        """Lade den persistierten ``StoryContext`` fuer ``story_dir``.

        Args:
            story_dir: Story-Arbeitsverzeichnis.

        Returns:
            Der ``StoryContext`` oder ``None``, wenn keiner persistiert ist.
        """
        ...

    def resolve_run_scope(self, story_dir: Path) -> RunScope | None:
        """Loese die Run-Korrelation (run_id, attempt) fuer ``story_dir`` auf.

        AG3-015 (FK-44 §44.4.2): der Prompt-Audit-Pfad braucht die
        authoritative Run-Korrelation, um ueber ``PromptRuntime`` zu
        materialisieren -- **ohne** direkten ``state_backend.store``-Import in
        ``verify_system``. Der konkrete Adapter lebt im state-backend-BC.

        Args:
            story_dir: Story-Arbeitsverzeichnis.

        Returns:
            Ein ``RunScope`` oder ``None``, wenn keine Run-Korrelation
            aufloesbar ist (dann wird der Prompt-Audit uebersprungen).
        """
        ...


@dataclass(frozen=True)
class RunScope:
    """Resolved run correlation for the prompt-audit path (AG3-015).

    Attributes:
        run_id: Active run identifier.
        story_id: Story identifier the run belongs to.
        attempt: QA-subflow attempt counter (>= 1).
    """

    run_id: str
    story_id: str
    attempt: int


class TrustClass(StrEnum):
    """Trust classification for findings (ARCH-04: Single Source of Truth).

    System checks (A) are more trustworthy than worker assertions (C).

    Attributes:
        SYSTEM: Deterministic system check (build, lint, test).
        VERIFIED_LLM: LLM check with evidence verification.
        WORKER_ASSERTION: Worker self-report (least trusted).
    """

    SYSTEM = "A"
    VERIFIED_LLM = "B"
    WORKER_ASSERTION = "C"


#: Canonical finding-type wire value for a Layer-2 ``assertion_weakness`` finding
#: (FK-48 §48.2.2). A Layer-2 finding tagged with this type names a testable
#: negative case that Layer 3 (Adversarial) MUST address as a mandatory target.
#: ARCH-55: English-only wire string; the single source of truth for the value.
ASSERTION_WEAKNESS_FINDING_TYPE: str = "assertion_weakness"


@dataclass(frozen=True)
class Finding:
    """A single QA finding from any layer.

    Immutable value object. Domain concept, not a string (ARCH-14).

    Args:
        layer: Which layer produced this (e.g. ``"structural"``).
        check: Which specific check (e.g. ``"context_exists"``).
        severity: How severe the finding is.
        message: Human-readable description of the finding.
        trust_class: How trustworthy the source of this finding is.
        file_path: Optional file path related to the finding.
        line_number: Optional line number in the file.
        suggestion: Optional suggestion for remediation.
        finding_type: Optional FK-48 §48.2.2 finding type (additive). When set
            to :data:`ASSERTION_WEAKNESS_FINDING_TYPE`, a Layer-2 FAIL/
            PASS_WITH_CONCERNS finding names a testable negative case that
            becomes a mandatory adversarial target
            (:func:`~agentkit.verify_system.adversarial_orchestrator.spawn.extract_mandatory_targets`).
            ``None`` keeps the legacy (untyped) finding -- a plain BLOCKING
            finding without this type does NOT yield a mandatory target.
        addressed_part: Optional FK-48 §48.2.2 summary of what was already
            fixed for an ``assertion_weakness`` finding. Carried additively onto
            the derived :class:`AdversarialTarget`; empty when unknown.
    """

    layer: str
    check: str
    severity: Severity
    message: str
    trust_class: TrustClass
    file_path: str | None = None
    line_number: int | None = None
    suggestion: str | None = None
    finding_type: str | None = None
    addressed_part: str = ""


@dataclass(frozen=True)
class LayerResult:
    """Result of a single QA layer evaluation.

    Fachliches Ergebnis via Return-Type, nicht Exception (ARCH-20).

    Args:
        layer: Name of the layer that produced this result.
        passed: Whether the layer evaluation passed overall.
        findings: Tuple of findings discovered during evaluation.
        metadata: Additional metadata about the evaluation.
    """

    layer: str
    passed: bool
    findings: tuple[Finding, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        """Return findings that block progression (``Severity.BLOCKING``).

        Returns:
            Tuple of findings with ``Severity.BLOCKING``.
        """
        return tuple(
            f for f in self.findings if f.severity == Severity.BLOCKING
        )

    @property
    def major_findings(self) -> tuple[Finding, ...]:
        """Return findings classified as MAJOR.

        Returns:
            Tuple of findings with ``Severity.MAJOR``.
        """
        return tuple(f for f in self.findings if f.severity == Severity.MAJOR)


@runtime_checkable
class QALayer(Protocol):
    """Contract for a QA layer (ARCH-06).

    Each layer evaluates one aspect of quality. Layers are:

    - Independent: can run without other layers.
    - Pure: no side effects during evaluation (ARCH-31).
    - Return-based: results via LayerResult, not exceptions (ARCH-20).
    """

    @property
    def name(self) -> str:
        """Layer identifier (e.g. ``"structural"``, ``"semantic"``).

        Returns:
            The name string for this layer.
        """
        ...

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Evaluate this layer against a story's artifacts.

        Args:
            ctx: Story context for type/mode-specific evaluation.
            story_dir: Directory containing story artifacts.
            review_input: Optional Layer-2 text inputs (FK-27 §27.4-§27.6).
                Layer-1 (Structural) and Layer-3 (Adversarial) ignore this.
                Layer-2 reviewers require it (fail-closed: raise
                ``Layer2InputMissingError`` when ``None``).

        Returns:
            LayerResult with findings. Never raises for business errors.
        """
        ...
