"""Policy engine -- deterministic aggregation of QA layer results.

Takes LayerResults from all layers, applies trust weighting, and
produces a final PASS/FAIL decision per FK-27 §27.7.2. No LLM, no
side effects (ARCH-12).

Since AG3-021, PolicyVerdict is a StrEnum from ``agentkit.backend.core_types``
with only two values: PASS and FAIL. The LLM check status at the
envelope edge (AG3-022, FK-71) is a separate value list and
explicitly does not belong in this module's context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.story_context_manager.types import ImplementationContract, StoryType
from agentkit.backend.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

#: FK-33 §33.7.3 default MAJOR threshold (``policy.major_threshold``: 3).
DEFAULT_MAJOR_THRESHOLD: int = 3

#: FK-33 §33.7.3 per-story-type MAJOR thresholds. Code-producing story types
#: share the canonical default (3); concept/research stories do not traverse
#: the verify pipeline (FK-33 §33.2.4 / §33.9) but carry the default so a
#: lookup never falls through. This is the single threshold truth that
#: REPLACES the v2 ``max_high_findings`` scalar.
DEFAULT_MAX_MAJOR_FINDINGS_PER_STORY_TYPE: dict[StoryType, int] = {
    StoryType.IMPLEMENTATION: DEFAULT_MAJOR_THRESHOLD,
    StoryType.BUGFIX: DEFAULT_MAJOR_THRESHOLD,
    StoryType.CONCEPT: DEFAULT_MAJOR_THRESHOLD,
    StoryType.RESEARCH: DEFAULT_MAJOR_THRESHOLD,
}

#: Trust classes whose findings are permitted to block (DK-04 §4.2 /
#: FK-33 §33.5). Trust A (``SYSTEM``) and Trust B (``VERIFIED_LLM``) are
#: authoritative enough to block; Trust C (``WORKER_ASSERTION``) is the
#: worker's own self-report and — per the DK-04 §4.2 / FK-33 §33.5.2
#: core rule "class C may never be blocking" (FK-07-008) — must NEVER
#: block: the agent must not be able to pass its own check. This frozenset
#: is the single source of truth for "may a finding of this trust class
#: contribute a blocking decision"; both blocking rules in
#: :func:`_compute_blocking` funnel through :func:`_trust_can_block`.
_BLOCKING_TRUST_CLASSES: frozenset[TrustClass] = frozenset(
    (TrustClass.SYSTEM, TrustClass.VERIFIED_LLM)
)


def _trust_can_block(finding: Finding) -> bool:
    """Return whether a finding's trust class may contribute to a FAIL.

    Single trust-class blocking predicate over :data:`_BLOCKING_TRUST_CLASSES`
    (DK-04 §4.2 / FK-33 §33.5.2): Trust A (``SYSTEM``) and Trust B
    (``VERIFIED_LLM``) may block, Trust C (``WORKER_ASSERTION``) may NEVER
    block. All blocking decisions in :func:`_compute_blocking` funnel through
    here so the trust-class block rule stays a single source of truth (no
    second blocking truth, FIX THE MODEL).

    Args:
        finding: The finding to classify.

    Returns:
        ``True`` iff ``finding.trust_class`` is in
        :data:`_BLOCKING_TRUST_CLASSES`.
    """
    return finding.trust_class in _BLOCKING_TRUST_CLASSES


@dataclass(frozen=True)
class PolicyWarning:
    """Non-blocking policy warning surfaced in the verify decision."""

    stage_id: str
    detail: str
    source_artifact: str


@dataclass(frozen=True)
class VerifyDecision:
    """Final decision from the policy engine.

    Immutable result (ARCH-29). Business result via return type (ARCH-20).

    Args:
        passed: Whether the overall verification passed.
        verdict: Final decision as a ``PolicyVerdict`` enum
            (``PASS`` or ``FAIL``).
        layer_results: Tuple of all layer results that contributed.
        all_findings: Flattened tuple of all findings from all layers.
        blocking_findings: Tuple of findings that caused failure.
        summary: Human-readable summary of the decision.
        max_major_findings: The MAJOR-findings threshold this decision was
            taken under (FK-27 §27.7.2).  Persisted into the decision artefact
            as ``major_threshold`` so the IntegrityGate Dim 4 (DECISION_INVALID,
            FK-35 §35.2.4) can verify the canonical policy record carries it.
    """

    passed: bool
    verdict: PolicyVerdict
    layer_results: tuple[LayerResult, ...]
    all_findings: tuple[Finding, ...]
    blocking_findings: tuple[Finding, ...]
    summary: str
    max_major_findings: int = 0
    warnings: tuple[PolicyWarning, ...] = ()

    @property
    def status(self) -> str:
        """Wire representation of the verdict.

        Returns exclusively ``"PASS"`` or ``"FAIL"`` per
        FK-27 §27.7.2 and ``PolicyVerdict`` (AG3-021); no other
        intermediate values are permitted.
        """
        return self.verdict.value


class PolicyEngine:
    """Layer 4: Deterministic aggregation.

    Applies the following rules in order:

    1. A ``Severity.BLOCKING`` finding whose trust class *may block*
       (Trust A ``SYSTEM`` or Trust B ``VERIFIED_LLM``, see
       :func:`_trust_can_block`) -> FAIL. ``BLOCKING`` is the *unconditional*,
       *threshold-independent* severity (FK-27 §27.4.2): such a finding blocks
       the QA-subflow hard, independent of ``max_major_findings``. This covers
       both the Trust-A structural/Sonar blockers AND a Trust-B Layer-2 FAIL --
       FK-33 §33.8.2 / FK-34 §34.2.5: "every [Layer-2] FAIL blocks
       (FK-05-164)", which is threshold-independent. A Trust-C
       (``WORKER_ASSERTION``) finding NEVER blocks here (DK-04 §4.2 / FK-33
       §33.5.2 core rule "class C may never be blocking", FK-07-008) -- the
       worker must not be able to pass its own check. This is the SINGLE
       blocking truth; there is no second gate.
    2. More than ``max_major_findings`` MAJOR findings (any blocking-eligible
       trust) -> FAIL.
    3. Otherwise -> PASS (warnings/minor findings tolerated).

    Configurable thresholds via constructor.
    """

    def __init__(
        self,
        max_major_findings: int = 0,
        *,
        max_major_findings_per_story_type: Mapping[StoryType, int] | None = None,
        stage_registry: StageRegistry | None = None,
    ) -> None:
        """Initialise the policy engine.

        Args:
            max_major_findings: Backward-compatible scalar MAJOR threshold used
                when :meth:`decide` is called WITHOUT a ``story_type``. Default
                ``0`` (any MAJOR blocks). This is the legacy knob the existing
                ``VerifySystem`` wiring sets; it is NOT a second truth -- it is
                the fallback when the per-story-type model is not consulted.
            max_major_findings_per_story_type: Per-story-type MAJOR threshold
                model (FK-33 §33.7.3) that REPLACES the v2 ``max_high_findings``
                scalar. Consulted by :meth:`decide` when a ``story_type`` is
                passed. Defaults to
                :data:`DEFAULT_MAX_MAJOR_FINDINGS_PER_STORY_TYPE`.
            stage_registry: The stage registry (FK-33 §33.2) bound to the
                engine for the fail-closed missing-artifact check (FK-33 §33.7:
                a missing result for a blocking stage of a TRAVERSED layer is a
                FAIL). Defaults to the canonical registry.
        """
        self._max_major = max_major_findings
        self._max_major_per_type: dict[StoryType, int] = dict(
            max_major_findings_per_story_type
            if max_major_findings_per_story_type is not None
            else DEFAULT_MAX_MAJOR_FINDINGS_PER_STORY_TYPE
        )
        self._registry = (
            stage_registry if stage_registry is not None else StageRegistry()
        )

    def threshold_for(self, story_type: StoryType) -> int:
        """Return the MAJOR threshold for ``story_type`` (FK-33 §33.7.3).

        Args:
            story_type: The story type whose threshold to resolve.

        Returns:
            The per-story-type MAJOR threshold (``DEFAULT_MAJOR_THRESHOLD``
            when the type carries no explicit entry).
        """
        return self._max_major_per_type.get(story_type, DEFAULT_MAJOR_THRESHOLD)

    def decide(
        self,
        layer_results: list[LayerResult],
        *,
        story_type: StoryType | None = None,
        max_layer_reached: int | None = None,
        traversed_layers: frozenset[int] | None = None,
        are_enabled: bool = False,
        context_sufficiency_artifact: Mapping[str, object] | None = None,
        implementation_contract: ImplementationContract | None = None,
    ) -> VerifyDecision:
        """Produce a final decision from all layer results (FK-33 §33.7).

        Args:
            layer_results: List of results from all QA layers actually executed.
            story_type: When given, the MAJOR threshold is resolved per
                story type (FK-33 §33.7.3) and the fail-closed missing-artifact
                check runs over the stage registry; when ``None`` the legacy
                scalar ``max_major_findings`` is used and no missing-artifact
                check runs (backward-compatible path).
            max_layer_reached: The highest QA layer actually traversed
                (1-4). Only stages whose ``layer <= max_layer_reached`` are
                expected to have produced a result; deeper layers were never
                started so their absence is expected (FK-33 §33.7.2). Used for
                the fail-closed check when ``traversed_layers`` is not given;
                ``None`` => derive from the present layer results.
            traversed_layers: The EXACT set of QA layer numbers the route
                planned and executed (FK-33 §33.7.2). The QA route is not always
                contiguous: the Exploration context runs Layer 2 + Layer 4 and
                deliberately SKIPS Layer 1 (FK-27 §27.3 / routing), so a Layer-1
                stage must NOT be reported missing there. When supplied, a stage
                is expected iff ``stage.layer in traversed_layers`` (authoritative
                over the contiguous ``max_layer_reached`` heuristic). ``None`` =>
                fall back to ``max_layer_reached`` (backward-compatible).
            are_enabled: Whether ``features.are`` is active (FK-27 §27.4.4);
                gates whether the ARE stage is expected for the missing-artifact
                check.

        Returns:
            A ``VerifyDecision`` with the aggregated outcome
            (``PolicyVerdict.PASS`` or ``PolicyVerdict.FAIL``).
        """
        results_tuple = tuple(layer_results)
        max_major = (
            self.threshold_for(story_type)
            if story_type is not None
            else self._max_major
        )

        # Flatten all findings
        all_findings: list[Finding] = []
        for lr in layer_results:
            all_findings.extend(lr.findings)

        # FK-33 §33.7 fail-closed: a blocking stage of a TRAVERSED layer that
        # produced no result is a synthetic BLOCKING SYSTEM finding (missing
        # artifact in a completed layer == FAIL). Only when a story_type is
        # supplied (the registry-bound path).
        if story_type is not None:
            all_findings.extend(
                self._missing_stage_findings(
                    results_tuple,
                    story_type=story_type,
                    max_layer_reached=max_layer_reached,
                    traversed_layers=traversed_layers,
                    are_enabled=are_enabled,
                    implementation_contract=implementation_contract,
                )
            )

        all_findings_tuple = tuple(all_findings)
        warnings = _context_sufficiency_warnings(context_sufficiency_artifact)

        # Identify blocking findings
        blocking = _compute_blocking(all_findings, max_major)
        blocking_tuple = tuple(blocking)

        # Determine verdict — only PASS/FAIL per FK-27 §27.7.2.
        if blocking_tuple:
            verdict = PolicyVerdict.FAIL
            passed = False
            summary = _build_fail_summary(blocking_tuple)
        elif all_findings_tuple:
            verdict = PolicyVerdict.PASS
            passed = True
            summary = _build_warnings_summary(all_findings_tuple)
        else:
            verdict = PolicyVerdict.PASS
            passed = True
            summary = "All QA layers passed with no findings."

        return VerifyDecision(
            passed=passed,
            verdict=verdict,
            layer_results=results_tuple,
            all_findings=all_findings_tuple,
            blocking_findings=blocking_tuple,
            summary=summary,
            max_major_findings=max_major,
            warnings=warnings,
        )

    def _missing_stage_findings(
        self,
        layer_results: tuple[LayerResult, ...],
        *,
        story_type: StoryType,
        max_layer_reached: int | None,
        traversed_layers: frozenset[int] | None = None,
        are_enabled: bool,
        implementation_contract: ImplementationContract | None = None,
    ) -> list[Finding]:
        """Synthesise BLOCKING findings for missing traversed-layer stages.

        FK-33 §33.7 fail-closed: for every applicable BLOCKING stage whose
        ``layer <= max_layer_reached``, a corresponding finding-bearing
        ``LayerResult`` MUST be present. A blocking stage of a traversed layer
        with no result is a "missing artifact in a completed layer" -> a
        synthetic BLOCKING SYSTEM finding (NOT a silent PASS).

        The result is matched by layer: a Layer-1 ``LayerResult`` (one
        aggregated structural result) standing in for the Layer-1 stages. When
        layer 1 was traversed but produced no result at all, EVERY blocking
        Layer-1 stage is reported missing (fail-closed). Deeper layers
        (2/3/4) follow the same rule against their own result presence.

        Args:
            layer_results: The results actually produced this round.
            story_type: The story type (drives stage applicability).
            max_layer_reached: Highest traversed layer; ``None`` => derive from
                the present results (the max ``layer`` index 1..4 that has a
                result; defaults to 1 when none resolvable).
            are_enabled: Whether the ARE stage is expected (FK-27 §27.4.4).

        Returns:
            A list of synthetic BLOCKING SYSTEM findings (empty when none).
        """
        reached = (
            max_layer_reached
            if max_layer_reached is not None
            else _derive_max_layer_reached(layer_results)
        )
        produced_stage_ids = _produced_stage_ids(layer_results, self._registry)
        findings: list[Finding] = []
        for stage in self._registry.stages_for(
            story_type, implementation_contract=implementation_contract
        ):
            if stage.stage_id == "policy":
                continue  # policy produces the aggregate decision itself.
            if not _stage_layer_traversed(
                stage.layer, reached=reached, traversed_layers=traversed_layers
            ):
                continue  # Layer never traversed -> absence is expected.
            if not stage.effective_blocking:
                continue  # Only blocking stages drive the fail-closed rule.
            if stage.feature_gated_are and not are_enabled:
                continue  # ARE stage only expected when features.are == true.
            if stage.stage_id not in produced_stage_ids:
                findings.append(
                    Finding(
                        layer="policy",
                        check=stage.stage_id,
                        severity=Severity.BLOCKING,
                        message=(
                            f"missing artifact for blocking stage "
                            f"{stage.stage_id!r} with producer "
                            f"{stage.producer!r} in traversed layer {stage.layer} "
                            "-> fail-closed (FK-33 §33.7)"
                        ),
                        trust_class=TrustClass.SYSTEM,
                    )
                )
        return findings


def _stage_layer_traversed(
    stage_layer: int,
    *,
    reached: int,
    traversed_layers: frozenset[int] | None,
) -> bool:
    """Whether a stage's layer was part of the executed QA route (FK-33 §33.7.2).

    When ``traversed_layers`` is given it is authoritative: a stage's layer is
    "traversed" iff it is in that set. This handles the non-contiguous
    Exploration route (Layer 2 + Layer 4, Layer 1 SKIPPED) where a Layer-1 stage
    must NOT be reported missing. When ``traversed_layers`` is ``None`` the
    contiguous ``max_layer_reached`` heuristic applies (any layer <= reached is
    treated as traversed), preserving the backward-compatible behaviour.

    Args:
        stage_layer: The stage's QA layer number.
        reached: The highest traversed layer (contiguous heuristic).
        traversed_layers: The exact executed-layer set, or ``None``.

    Returns:
        ``True`` iff the stage's layer was traversed by the route.
    """
    if traversed_layers is not None:
        return stage_layer in traversed_layers
    return stage_layer <= reached


def _produced_stage_ids(
    layer_results: tuple[LayerResult, ...],
    registry: StageRegistry,
) -> set[str]:
    """Return produced stage IDs from layer results and registry metadata."""
    produced: set[str] = set()
    for lr in layer_results:
        metadata_stage_ids = lr.metadata.get("stage_ids")
        if isinstance(metadata_stage_ids, (list, tuple, set, frozenset)):
            produced.update(str(stage_id) for stage_id in metadata_stage_ids)
        for stage in registry.stages:
            if lr.layer == stage.stage_id or lr.layer == _legacy_result_name(stage):
                produced.add(stage.stage_id)
    return produced


def _derive_max_layer_reached(layer_results: tuple[LayerResult, ...]) -> int:
    """Derive the highest traversed layer from present results (>=1)."""
    from agentkit.backend.story_context_manager.types import ImplementationContract
    from agentkit.backend.verify_system.stage_registry.registry import (
        is_integration_stabilization_stage,
    )

    registry = StageRegistry()
    produced: set[int] = set()
    for stage_id in _produced_stage_ids(layer_results, registry):
        # An IS stage was only produced when running under the IS contract;
        # look it up with that contract so its layer is counted (MAJOR H: the
        # default lookup hides IS stages — that hiding must not under-count a
        # legitimately produced IS Layer-4 result here).
        contract = (
            ImplementationContract.INTEGRATION_STABILIZATION
            if is_integration_stabilization_stage(stage_id)
            else None
        )
        stage = registry.stage_for_id(stage_id, implementation_contract=contract)
        if stage is not None:
            produced.add(stage.layer)
    return max(produced) if produced else 1


def _legacy_result_name(stage: object) -> str:
    """Return the legacy result name for a registered stage."""
    from agentkit.backend.verify_system.stage_registry.stages import StageDefinition

    if not isinstance(stage, StageDefinition):  # pragma: no cover
        return ""
    if stage.stage_id.endswith("_impl"):
        return stage.stage_id.removesuffix("_impl")
    return stage.stage_id


def _context_sufficiency_warnings(
    artifact: Mapping[str, object] | None,
) -> tuple[PolicyWarning, ...]:
    """Fail-open warning extraction for optional context sufficiency input."""
    if artifact is None:
        return ()
    sufficiency = artifact.get("sufficiency")
    if not isinstance(sufficiency, str):
        return ()
    if sufficiency == "sufficient":
        return ()
    gaps = artifact.get("gaps")
    gap_count = len(gaps) if isinstance(gaps, list) else 0
    return (
        PolicyWarning(
            stage_id="context_sufficiency",
            detail=f"Context sufficiency: {sufficiency}; {gap_count} gaps identified",
            source_artifact="context_sufficiency.json",
        ),
    )


def _compute_blocking(
    findings: list[Finding],
    max_major: int,
) -> list[Finding]:
    """Determine which findings are blocking.

    Only findings whose trust class *may block* (:func:`_trust_can_block` --
    Trust A ``SYSTEM`` / Trust B ``VERIFIED_LLM``) are ever considered. Trust C
    (``WORKER_ASSERTION``) findings are filtered out up front and can NEVER
    contribute a blocking decision, neither via the BLOCKING-severity rule nor
    via the MAJOR-threshold rule (DK-04 §4.2 / FK-33 §33.5.2 core rule "class
    C may never be blocking", FK-07-008). This single trust filter is the one
    place the trust-class rule lives (no second blocking truth, FIX THE MODEL).

    Rules (applied to blocking-eligible findings only):
    - Any ``Severity.BLOCKING`` finding blocks immediately and
      *threshold-independently* (FK-27 §27.4.2): ``BLOCKING`` is the unconditional
      severity. This realises both the Trust-A structural/Sonar block AND the
      FK-33 §33.8.2 / FK-34 §34.2.5 "every Layer-2 FAIL blocks" rule (a
      Layer-2 FAIL maps to a Trust-B ``BLOCKING`` finding, not a
      threshold-gated MAJOR).
    - If total MAJOR findings exceed ``max_major``, all MAJOR findings block.

    Args:
        findings: All findings to evaluate.
        max_major: Maximum number of MAJOR findings allowed before
            they become blocking.

    Returns:
        List of blocking findings.
    """
    eligible = [f for f in findings if _trust_can_block(f)]

    blocking: list[Finding] = []

    # Rule 1: any BLOCKING-severity finding blocks immediately, INDEPENDENT of
    # max_major (FK-27 §27.4.2 BLOCKING = hard) -- but only for trust classes
    # that may block (Trust C already filtered out above).
    severity_blockers = [
        f for f in eligible if f.severity == Severity.BLOCKING
    ]
    blocking.extend(severity_blockers)

    # Rule 2: Too many MAJOR findings (blocking-eligible trust) become blocking.
    all_major = [f for f in eligible if f.severity == Severity.MAJOR]
    if len(all_major) > max_major:
        for f in all_major:
            if f not in blocking:
                blocking.append(f)

    return blocking


def _build_fail_summary(blocking: tuple[Finding, ...]) -> str:
    """Build a human-readable summary for FAIL decisions.

    Args:
        blocking: Tuple of blocking findings.

    Returns:
        Summary string listing blocking finding count and details.
    """
    blocking_count = sum(
        1 for f in blocking if f.severity == Severity.BLOCKING
    )
    major_count = sum(1 for f in blocking if f.severity == Severity.MAJOR)
    parts: list[str] = []
    if blocking_count:
        parts.append(f"{blocking_count} blocking")
    if major_count:
        parts.append(f"{major_count} major")
    detail = ", ".join(parts)
    return f"FAIL: {len(blocking)} blocking finding(s) ({detail})."


def _build_warnings_summary(findings: tuple[Finding, ...]) -> str:
    """Build a human-readable summary for PASS decisions that carry
    non-blocking findings.

    Args:
        findings: Tuple of all (non-blocking) findings.

    Returns:
        Summary string with finding counts by severity.
    """
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
    parts = [f"{count} {sev}" for sev, count in counts.items()]
    detail = ", ".join(parts)
    return f"PASS with warnings: {len(findings)} finding(s) ({detail})."
