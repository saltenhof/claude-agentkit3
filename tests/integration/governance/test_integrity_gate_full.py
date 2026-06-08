"""Integration test — full IntegrityGate closure check over the 9 dimensions.

DB-backed (SQLite) end-to-end run of ``build_integrity_gate().evaluate`` for a
populated implementation story and for the mandatory-artifact-vorstufe abort
(FK-35 §35.2.3), plus the concept routing (Dim 5/6/7/9 absent, §2.1.4) and the
Dim 9 (SONARQUBE_GREEN) applicability matrix against a stubbed AG3-052
capability boundary (no live Sonar).  All nine dimensions verify the canonical
QA envelopes for real (producer / status / depth / threshold, Remediation E-A);
the helpers therefore write a substantive, FK-35-conformant QA artifact set.

Dim 9 (R2-C/A2): the productive ``build_integrity_gate`` wires a Dim-9 port that
CONSUMES the AG3-052 capability (``build_sonar_gate_port_for_run`` +
``evaluate_sonarqube_gate``).  A project WITHOUT a ``sonarqube`` stanza (or
``available: false``) is a deliberate absence -> Dim 9 NOT_APPLICABLE skip (FK-33
§33.6.5 "absent != broken").  A project with ``sonarqube.available: true`` but no
commit-bound scan artefact in the worktree (the Closure pre-merge scan is OOS)
resolves APPLICABLE and the capability fails closed (``attestation_unreadable``)
-> ESCALATED, never a silent skip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_artifact_manager, build_integrity_gate
from agentkit.core_types import PolicyVerdict
from agentkit.governance.integrity_gate import (
    IntegrityDimension,
    IntegrityGateStatus,
)
from agentkit.governance.integrity_gate.dim9_sonar import SONAR_NOT_GREEN
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    record_layer_artifacts,
    record_verify_decision,
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.artifacts import (
    write_layer_artifacts,
    write_verify_decision_artifacts,
)
from agentkit.verify_system.policy_engine.engine import VerifyDecision
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY = "AG3-700"
_RUN = "run-ig-full-001"
_CODE_PHASES = ("setup", "implementation", "closure")
_NONCODE_PHASES = ("setup", "closure")


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(root: Path) -> Path:
    story_dir = root / "stories" / _STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _write_sonar_project_config(project_root: Path) -> None:
    """Write a project.yaml declaring ``sonarqube.available: true`` (APPLICABLE).

    With Sonar declared present but no scan artefact in the worktree, the
    productive Dim-9 port resolves APPLICABLE and the AG3-052 capability fails
    closed (no commit-bound attestation) — the genuine consumer path.
    """
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        "\n".join(
            (
                "project_key: test-project",
                "project_name: test-project",
                "repositories:",
                "  - name: app",
                "    path: .",
                "    language: python",
                "pipeline:",
                # FK-03 §3.2.1: config_version is mandatory (fail-closed).
                "  config_version: '3.0'",
                "  features:",
                "    multi_llm: false",
                "  sonarqube:",
                "    available: true",
                "    enabled: true",
                "    base_url: http://sonar.invalid:9901",
                "    token_env: SONAR_TOKEN_TEST",
                "    scanner_version: 5.0.1",
                # AG3-056: code-producing project must declare the ci stanza;
                # an explicit opt-out keeps this Dim-9/Sonar test isolated.
                "  ci:",
                "    available: false",
                "    enabled: false",
            )
        ),
        encoding="utf-8",
    )


def _write_sonar_unavailable_project_config(project_root: Path) -> None:
    """Write a project.yaml declaring ``sonarqube.available: false`` (skip).

    A code-producing project MUST carry a ``sonarqube`` stanza (omitting it is an
    E6 hard-fail ConfigError); ``available: false`` is the ONLY legitimate,
    declared Sonar absence for an implementation/bugfix story -> Dim 9
    NOT_APPLICABLE skip (FK-33 §33.6.5 "absent != broken").  A missing/unresolvable
    project_root is NOT a declared absence for a code story (it is a broken
    precondition that fails closed, R4-C/A2).
    """
    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        "\n".join(
            (
                "project_key: test-project",
                "project_name: test-project",
                "repositories:",
                "  - name: app",
                "    path: .",
                "    language: python",
                "pipeline:",
                # FK-03 §3.2.1: config_version is mandatory (fail-closed).
                "  config_version: '3.0'",
                "  features:",
                "    multi_llm: false",
                "  sonarqube:",
                "    available: false",
                "    enabled: false",
                # AG3-056: code-producing project must declare the ci stanza.
                "  ci:",
                "    available: false",
                "    enabled: false",
            )
        ),
        encoding="utf-8",
    )


def _create_context(
    story_dir: Path,
    story_type: StoryType,
    *,
    project_root: Path | None = None,
) -> None:
    mode: StoryMode | None = (
        StoryMode.EXECUTION
        if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
        else None
    )
    save_story_context(
        story_dir,
        StoryContext(
            project_key="test-project",
            story_id=_STORY,
            story_type=story_type,
            execution_route=mode,
            mode=WireStoryMode.STANDARD,
            title="IntegrityGate full",
            project_root=project_root,
            # FK-35 §35.2.4 Dim 8: the context is built at setup, strictly
            # before the QA-subflow decision flow_end (stamped at QA write time,
            # i.e. "now").  A fixed past timestamp keeps the causality holding.
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        ),
    )
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id=_STORY,
            run_id=_RUN,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _create_snapshot(story_dir: Path, phase: str) -> None:
    save_phase_snapshot(
        story_dir,
        PhaseSnapshot(
            story_id=_STORY,
            phase=phase,
            status=PhaseStatus.COMPLETED,
            completed_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
            artifacts=[],
            evidence={},
        ),
    )


def _structural_result() -> LayerResult:
    """A substantive structural result (>=5 checks, >500B serialized payload)."""
    findings = tuple(
        Finding(
            layer="structural",
            check=f"informational_check_{i}",
            severity=Severity.MINOR,
            message=(
                f"informational structural finding number {i} with descriptive "
                "context so the canonical envelope payload exceeds 500 bytes"
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=f"src/agentkit/module_{i}.py",
            line_number=i,
        )
        for i in range(3)
    )
    return LayerResult(
        layer="structural",
        passed=True,
        findings=findings,
        metadata={"total_checks": 6},
    )


def _full_layer_results() -> tuple[LayerResult, ...]:
    """Structural + both Layer-2 reviews + adversarial (all passing, FK-35)."""
    return (
        _structural_result(),
        LayerResult(layer="qa_review", passed=True, findings=()),
        LayerResult(layer="semantic_review", passed=True, findings=()),
        LayerResult(
            layer="adversarial",
            passed=True,
            findings=(),
            metadata={
                "summary": "adversarial sparring run; " + ("edge probe " * 25),
            },
        ),
    )


def _write_full_qa(story_dir: Path) -> None:
    """Write the full FK-35-conformant QA envelope set + decision."""
    layers = _full_layer_results()
    decision = VerifyDecision(
        passed=True,
        verdict=PolicyVerdict.PASS,
        layer_results=layers,
        all_findings=(),
        blocking_findings=(),
        summary="ok",
        max_major_findings=0,
    )
    manager = build_artifact_manager(story_dir)
    write_layer_artifacts(
        manager=manager, story_id=_STORY, run_id=_RUN,
        layer_results=layers, attempt_nr=1,
    )
    write_verify_decision_artifacts(
        manager=manager, story_id=_STORY, run_id=_RUN,
        decision=decision, attempt_nr=1,
    )
    record_layer_artifacts(story_dir, layer_results=layers, attempt_nr=1)
    record_verify_decision(story_dir, decision=decision, attempt_nr=1)


def _create_structural_only(story_dir: Path) -> None:
    """Write only the structural QA artifact (no verify decision)."""
    structural = _structural_result()
    manager = build_artifact_manager(story_dir)
    write_layer_artifacts(
        manager=manager, story_id=_STORY, run_id=_RUN,
        layer_results=(structural,), attempt_nr=1,
    )
    record_layer_artifacts(story_dir, layer_results=(structural,), attempt_nr=1)


def test_implementation_sonar_unavailable_is_deliberate_absence_skip(
    tmp_path: Path,
) -> None:
    # R2-C/A2 + R4-C/A2 (genuine AG3-052 consumer path): an impl story whose
    # project declares ``sonarqube.available: false`` is a DELIBERATE, declared
    # absence -> build_sonar_gate_port_for_run returns None -> Dim 9
    # NOT_APPLICABLE skip (FK-33 §33.6.5 "absent != broken").  This is the ONLY
    # legitimate Dim-9 skip for a code-producing story (an unresolvable
    # project_root would instead fail closed, R4-C/A2).  The eight non-Sonar
    # dimensions pass; Dim 9 is absent from the result, gate PASSES.
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    _write_sonar_unavailable_project_config(project_root)
    story_dir = _story_dir(tmp_path)
    _create_context(
        story_dir, StoryType.IMPLEMENTATION, project_root=project_root
    )
    for phase in _CODE_PHASES:
        _create_snapshot(story_dir, phase)
    _write_full_qa(story_dir)

    result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)

    assert result.overall is IntegrityGateStatus.PASS
    assert IntegrityDimension.SONARQUBE_GREEN not in result.dimension_results
    assert set(result.dimension_results) == {
        IntegrityDimension.NO_QA_ARTIFACTS,
        IntegrityDimension.DECISION_INVALID,
        IntegrityDimension.CONTEXT_INVALID,
        IntegrityDimension.STRUCTURAL_SHALLOW,
        IntegrityDimension.NO_LLM_REVIEW,
        IntegrityDimension.NO_ADVERSARIAL,
        IntegrityDimension.NO_VERIFY,
        IntegrityDimension.TIMESTAMP_INVERSION,
    }


def test_implementation_applicable_without_attestation_escalates(
    tmp_path: Path,
) -> None:
    # R2-C/A2 (genuine AG3-052 consumer path): an impl story whose project
    # declares sonarqube.available: true resolves Dim 9 APPLICABLE; with NO
    # commit-bound scan artefact in the worktree (the Closure pre-merge scan is
    # OOS), build_sonar_gate_port_for_run returns a fail-closed APPLICABLE port
    # whose inputs carry attestation=None, and evaluate_sonarqube_gate yields a
    # failed outcome -> Dim 9 fail-closed SONAR_NOT_GREEN, NEVER a silent skip.
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    _write_sonar_project_config(project_root)
    story_dir = _story_dir(tmp_path)
    _create_context(
        story_dir, StoryType.IMPLEMENTATION, project_root=project_root
    )
    for phase in _CODE_PHASES:
        _create_snapshot(story_dir, phase)
    _write_full_qa(story_dir)

    result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)

    assert result.overall is IntegrityGateStatus.ESCALATED
    assert result.failure_reason == SONAR_NOT_GREEN
    dim9 = result.dimension_results[IntegrityDimension.SONARQUBE_GREEN]
    assert dim9.passed is False
    # Every NON-Sonar dimension passed (the only failure is the absent
    # commit-bound attestation, which is fail-closed not a skip).
    non_sonar = {
        dim: r
        for dim, r in result.dimension_results.items()
        if dim is not IntegrityDimension.SONARQUBE_GREEN
    }
    assert all(r.passed for r in non_sonar.values())


def test_missing_decision_aborts_and_blocks_later_dims(tmp_path: Path) -> None:
    # Sonar is a declared absence (available:false) so Dim 9 is a legitimate skip;
    # the concern here is the MISSING_DECISION mandatory abort, orthogonal to
    # Sonar.  A resolvable project_root is required: an unresolvable one would
    # fail closed for this code story (R4-C/A2), not skip.
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    _write_sonar_unavailable_project_config(project_root)
    story_dir = _story_dir(tmp_path)
    _create_context(
        story_dir, StoryType.IMPLEMENTATION, project_root=project_root
    )
    for phase in _CODE_PHASES:
        _create_snapshot(story_dir, phase)
    # Structural present, but NO verify decision -> mandatory MISSING_DECISION aborts.
    _create_structural_only(story_dir)

    result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)

    assert result.overall is IntegrityGateStatus.FAIL
    assert result.failure_reason == "MISSING_DECISION"
    assert IntegrityDimension.STRUCTURAL_SHALLOW in result.blocked_dimensions
    assert IntegrityDimension.STRUCTURAL_SHALLOW not in result.dimension_results


def test_concept_skips_code_only_dimensions(tmp_path: Path) -> None:
    story_dir = _story_dir(tmp_path)
    _create_context(story_dir, StoryType.CONCEPT)
    for phase in _NONCODE_PHASES:
        _create_snapshot(story_dir, phase)
    # Concept stories carry a structural artefact (mandatory Dim 1) but no
    # code-QA delivery; Dim 3 still verifies its depth.
    _create_structural_only(story_dir)

    result = build_integrity_gate().evaluate(story_dir, StoryType.CONCEPT)

    assert result.overall is IntegrityGateStatus.PASS
    assert IntegrityDimension.NO_LLM_REVIEW not in result.dimension_results
    assert IntegrityDimension.NO_ADVERSARIAL not in result.dimension_results
    assert IntegrityDimension.NO_VERIFY not in result.dimension_results
    assert IntegrityDimension.SONARQUBE_GREEN not in result.dimension_results


# ---------------------------------------------------------------------------
# Dim 9 SONARQUBE_GREEN — applicability matrix against a stubbed capability
# boundary.  The stub returns the canonical AG3-052 ``SonarGateOutcome`` (the
# value evaluate_sonarqube_gate would produce); Dim 9 only MAPS it (no live
# Sonar, no second mechanic).
# ---------------------------------------------------------------------------


def _outcome(applicability: object, *, passed: bool | None, status: str,
             reason: str | None = None):  # type: ignore[no-untyped-def]
    from agentkit.verify_system.sonarqube_gate import SonarGateOutcome

    return SonarGateOutcome(
        applicability=applicability,  # type: ignore[arg-type]
        passed=passed,
        gate_status=status,
        failure_reason=reason,
    )


class _StubSonarPort:
    """Stubbed ``SonarDimensionPort`` returning a canonical AG3-052 resolution."""

    def __init__(self, resolution: object) -> None:
        self._resolution = resolution

    def resolve_dim9_outcome(self, gate_ctx: object) -> object:
        _ = gate_ctx
        return self._resolution


def _gate_with_sonar(resolution: object):  # type: ignore[no-untyped-def]
    from agentkit.governance.integrity_gate import IntegrityGate
    from agentkit.state_backend.store.integrity_gate_repository import (
        StateBackendIntegrityGateStateAdapter,
    )

    return IntegrityGate(
        state_port=StateBackendIntegrityGateStateAdapter(),
        sonar_port=_StubSonarPort(resolution),  # type: ignore[arg-type]
    )


def _evaluate_with_dim9(tmp_path: Path, resolution: object):  # type: ignore[no-untyped-def]
    story_dir = _story_dir(tmp_path)
    _create_context(story_dir, StoryType.IMPLEMENTATION)
    for phase in _CODE_PHASES:
        _create_snapshot(story_dir, phase)
    _write_full_qa(story_dir)
    return _gate_with_sonar(resolution).evaluate(story_dir, StoryType.IMPLEMENTATION)


def test_dim9_applicable_green_passes(tmp_path: Path) -> None:
    from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution
    from agentkit.verify_system.sonarqube_gate import SonarApplicability

    resolution = Dim9Resolution(
        applicability=SonarApplicability.APPLICABLE,
        outcome=_outcome(
            SonarApplicability.APPLICABLE,
            passed=True,
            status="sonarqube_gate_passed",
        ),
    )
    result = _evaluate_with_dim9(tmp_path, resolution)
    assert result.overall is IntegrityGateStatus.PASS
    dim9 = result.dimension_results[IntegrityDimension.SONARQUBE_GREEN]
    assert dim9.passed is True


def test_dim9_applicable_red_escalates(tmp_path: Path) -> None:
    from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution
    from agentkit.verify_system.sonarqube_gate import SonarApplicability

    resolution = Dim9Resolution(
        applicability=SonarApplicability.APPLICABLE,
        outcome=_outcome(
            SonarApplicability.APPLICABLE,
            passed=False,
            status="failed",
            reason="stale_attestation: ...",
        ),
    )
    result = _evaluate_with_dim9(tmp_path, resolution)
    assert result.overall is IntegrityGateStatus.ESCALATED
    assert result.failure_reason == SONAR_NOT_GREEN


def test_dim9_not_applicable_unavailable_is_absent(tmp_path: Path) -> None:
    from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution
    from agentkit.verify_system.sonarqube_gate import SonarApplicability

    # available:false resolves NOT_APPLICABLE_UNAVAILABLE -> Dim 9 omitted, no FAIL.
    resolution = Dim9Resolution(
        applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE, outcome=None
    )
    result = _evaluate_with_dim9(tmp_path, resolution)
    assert IntegrityDimension.SONARQUBE_GREEN not in result.dimension_results
    assert result.overall is IntegrityGateStatus.PASS


def test_dim9_applicable_unreachable_escalates(tmp_path: Path) -> None:
    from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution
    from agentkit.verify_system.sonarqube_gate import SonarApplicability

    # APPLICABLE but the capability produced no outcome (configured-but-
    # unreachable) -> fail-closed SONAR_NOT_GREEN, ESCALATED (absent != broken).
    resolution = Dim9Resolution(
        applicability=SonarApplicability.APPLICABLE, outcome=None
    )
    result = _evaluate_with_dim9(tmp_path, resolution)
    assert result.overall is IntegrityGateStatus.ESCALATED
    assert result.failure_reason == SONAR_NOT_GREEN
    dim9 = result.dimension_results[IntegrityDimension.SONARQUBE_GREEN]
    assert dim9.passed is False
