"""Unit-Tests fuer FailureCorpus-Top-Komponente (AG3-028 §2.1.2, AK#2/#3).

``record_incident`` wird gegen einen ECHTEN ProjectionAccessor (SQLite) verprobt
(kein Mock fuer Kernlogik). Die vier nicht-implementierten Top-Methoden werden
auf ihren NotImplementedError-Vertrag gepinnt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_failure_corpus
from agentkit.backend.core_types import FailureCategory
from agentkit.backend.failure_corpus import (
    FailureCorpus,
    IncidentCandidate,
    IncidentRole,
    IncidentSeverity,
)
from agentkit.backend.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.backend.failure_corpus.top import (
    CheckApprovalDecision,
    PatternDecision,
)
from agentkit.backend.failure_corpus.types import CheckId, PatternId
from agentkit.backend.state_backend.store.projection_repositories import (
    build_projection_repositories,
)
from agentkit.backend.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "proj-a"


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FailureCorpus]:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    yield build_failure_corpus(accessor)
    reset_backend_cache_for_tests()


def _candidate(
    symptom: str = "scope exceeded",
    *,
    severity: IncidentSeverity = IncidentSeverity.HIGH,
) -> IncidentCandidate:
    return IncidentCandidate(
        project_key=_PROJECT,
        story_id="AG3-001",
        run_id="run-1",
        category=FailureCategory.SCOPE_DRIFT,
        severity=severity,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom=symptom,
        evidence=["detail x"],
        merge_blocked=True,
    )


class TestRecordIncident:
    def test_happy_path_returns_incident_id_and_persists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        reset_backend_cache_for_tests()
        try:
            acc = ProjectionAccessor(build_projection_repositories(tmp_path))
            fc = build_failure_corpus(acc)

            incident_id = fc.record_incident(_candidate())
            assert incident_id == "FC-2026-0001"

            rows = acc.read_projection(
                ProjectionKind.FC_INCIDENTS,
                ProjectionFilter(
                    project_key=_PROJECT, story_id="AG3-001", run_id="run-1"
                ),
            )
            assert len(rows) == 1
            assert rows[0].incident_id == incident_id
        finally:
            reset_backend_cache_for_tests()

    def test_low_severity_admitted_when_merge_blocked(
        self, corpus: FailureCorpus
    ) -> None:
        # DK-07 §7.3.6 reines ODER: LOW + merge_blocked wird aufgenommen
        # (der alte AND-Floor verwarf das faelschlich).
        incident_id = corpus.record_incident(
            _candidate(severity=IncidentSeverity.LOW)
        )
        assert str(incident_id).startswith("FC-")

    def test_reject_not_significant_when_no_criterion(
        self, corpus: FailureCorpus
    ) -> None:
        # LOW + nichts: nicht merge-blocked, kein Rework, und nicht novel (es gibt
        # bereits einen Incident derselben category) -> NOT_SIGNIFICANT (reines
        # ODER, DK-07 §7.3.6). Zuerst einen gleichartigen Incident aufnehmen.
        corpus.record_incident(_candidate(severity=IncidentSeverity.LOW))
        no_trigger = IncidentCandidate(
            project_key=_PROJECT,
            story_id="AG3-001",
            run_id="run-1",
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.LOW,
            phase="implementation",
            role=IncidentRole.WORKER,
            model="claude-opus",
            symptom="something else entirely",
            evidence=["detail x"],
            merge_blocked=False,
            rework_minutes=0,
        )
        with pytest.raises(IncidentRejectedError) as exc:
            corpus.record_incident(no_trigger)
        assert IncidentRejectReason.NOT_SIGNIFICANT in exc.value.reason_codes


class TestUnwiredSubsFailClosed:
    """AG3-078: when project_key is omitted from build_failure_corpus, subs are None.

    The top surface fails-closed with RuntimeError (FAIL-CLOSED guard), not
    NotImplementedError, since these methods are implemented in AG3-078 but
    require project_key to be wired.
    """

    def test_suggest_patterns_without_project_key(self, corpus: FailureCorpus) -> None:
        with pytest.raises(RuntimeError, match="PatternPromotion"):
            corpus.suggest_patterns()

    def test_confirm_pattern_without_project_key(self, corpus: FailureCorpus) -> None:
        with pytest.raises(RuntimeError, match="PatternPromotion"):
            corpus.confirm_pattern(PatternId("P-1"), PatternDecision.ACCEPTED)

    def test_derive_check_without_project_key(self, corpus: FailureCorpus) -> None:
        with pytest.raises(RuntimeError, match="CheckFactory"):
            corpus.derive_check(PatternId("P-1"))

    def test_approve_check_without_project_key(self, corpus: FailureCorpus) -> None:
        with pytest.raises(RuntimeError, match="CheckFactory"):
            corpus.approve_check(CheckId("C-1"), CheckApprovalDecision.APPROVED)

    def test_report_effectiveness_without_project_key(self, corpus: FailureCorpus) -> None:
        with pytest.raises(RuntimeError, match="CheckEffectivenessTracker"):
            corpus.report_effectiveness()


class TestBuildFailureCorpusWiring:
    """AG3-078 ERROR A/2/3: production wiring tests for the LLM sharpener + story creation.

    Verifies that:
    - build_failure_corpus with project_key but no llm_client BUILDS (ERROR A regression
      fix): the LLM sharpener is built lazily, so the non-derive_check subs/commands work.
      The factory is wired WITHOUT a sharpener and derive_check stays fail-closed.
    - build_failure_corpus with project_key and a real LlmClient wires sharpener + story_creation.
    """

    def test_builds_without_llm_client_and_derive_check_stays_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR A: llm_client=None must NOT crash the build (regression fix).

        The previous fail-closed-at-construction wiring broke every non-derive_check
        CLI command (the composition root unconditionally built LlmInvariantSharpener(None),
        which raised). The corrected build constructs the sharpener LAZILY: with no
        llm_client the CheckFactory has no sharpener wired, the other five top methods
        build, and derive_check itself remains FAIL-CLOSED (raises if it tries to sharpen
        without a sharpener).
        """
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.core_types import FailureCategory, PatternStatus
        from agentkit.backend.failure_corpus.pattern import (
            FailurePatternRecord,
            PatternRiskLevel,
            PromotionRule,
        )
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )

        reset_backend_cache_for_tests()
        try:
            acc = ProjectionAccessor(build_projection_repositories(tmp_path))
            # Build must SUCCEED without an llm_client.
            corpus = build_failure_corpus(
                acc, project_key="proj-wire-fail", store_dir=tmp_path, llm_client=None
            )
            factory = corpus._check_factory  # noqa: SLF001
            assert factory is not None
            assert factory._sharpener is None  # noqa: SLF001
            # The non-derive_check path works: suggest_patterns runs (empty corpus).
            assert corpus.suggest_patterns() == []
            # derive_check stays FAIL-CLOSED: seed an ACCEPTED pattern, then derive.
            StateBackendFcPatternRepository(tmp_path).save(
                FailurePatternRecord(
                    pattern_id="FP-0001",
                    project_key="proj-wire-fail",
                    status=PatternStatus.ACCEPTED,
                    category=FailureCategory.SCOPE_DRIFT,
                    promotion_rule=PromotionRule.HIGH_SEVERITY,
                    invariant="scope must not be exceeded",
                    risk_level=PatternRiskLevel.HIGH,
                    confirmed_by="human",
                    incident_refs=[],
                    incident_count=0,
                )
            )
            with pytest.raises(RuntimeError, match="InvariantSharpenerPort is None"):
                corpus.derive_check(PatternId("FP-0001"))
        finally:
            reset_backend_cache_for_tests()

    def test_wires_sharpener_and_story_creation_with_real_llm_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ERROR 2/3 production path: wired corpus has CheckFactory with both ports set.

        Uses a minimal LlmClient stub (only seam allowed at LLM boundary per CLAUDE.md).
        Verifies the composition root wires invariant_sharpener + story_creation
        into the CheckFactory — the PRODUCTION path that was missing before AG3-078.
        """

        class _StubLlmClient:
            """Minimal LlmClient test double (LLM boundary seam only)."""

            def complete(self, *, role: str, prompt: str) -> str:
                return f"Stub invariant for role={role}"

        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        reset_backend_cache_for_tests()
        try:
            acc = ProjectionAccessor(build_projection_repositories(tmp_path))
            corpus = build_failure_corpus(
                acc,
                project_key="proj-wire-ok",
                store_dir=tmp_path,
                llm_client=_StubLlmClient(),  # type: ignore[arg-type]
            )
            # Composition root succeeded — both ports must be wired in CheckFactory.
            # Access via the internal _check_factory attribute (production path verification).
            factory = corpus._check_factory  # noqa: SLF001
            assert factory is not None, "CheckFactory must be wired when project_key is given"
            assert factory._sharpener is not None, (  # noqa: SLF001
                "invariant_sharpener must be wired (AG3-078 ERROR 2)"
            )
            assert factory._story_creation is not None, (  # noqa: SLF001
                "story_creation must be wired (AG3-078 ERROR 3)"
            )
        finally:
            reset_backend_cache_for_tests()
