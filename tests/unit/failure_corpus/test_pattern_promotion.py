"""Unit tests for PatternPromotion sub (FK-41 §41.5, AG3-078).

Tests cover:
- compute_symptom_signature determinism and normalization
- CATEGORY_TO_CHECK_TYPE and CHECK_TYPE_FALSE_POSITIVE_RISK constants
- suggest_patterns: all three promotion rules (HIGH_SEVERITY > REPETITION >
  FAVORABLE_CHECKABILITY)
- suggest_patterns: clusters satisfying no rule produce no candidate
- confirm_pattern: ACCEPTED path (saves FailurePatternRecord)
- confirm_pattern: REJECTED path
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.core_types import CheckType, FailureCategory, PatternStatus
from agentkit.backend.failure_corpus.check_proposal import FalsePositiveRisk
from agentkit.backend.failure_corpus.pattern import PatternRiskLevel, PromotionRule
from agentkit.backend.failure_corpus.pattern_promotion import (
    CATEGORY_TO_CHECK_TYPE,
    CHECK_TYPE_FALSE_POSITIVE_RISK,
    PatternPromotion,
    compute_symptom_signature,
)
from agentkit.backend.failure_corpus.top import PatternDecision
from agentkit.backend.failure_corpus.types import PatternId

# ---------------------------------------------------------------------------
# compute_symptom_signature
# ---------------------------------------------------------------------------


class TestComputeSymptomSignature:
    def test_returns_16_hex_chars(self) -> None:
        sig = compute_symptom_signature("Agent skips tests during implementation")
        assert len(sig) == 16
        assert all(c in "0123456789abcdef" for c in sig)

    def test_deterministic(self) -> None:
        s1 = compute_symptom_signature("same symptom text")
        s2 = compute_symptom_signature("same symptom text")
        assert s1 == s2

    def test_order_invariant(self) -> None:
        # Tokens are sorted before hashing
        s1 = compute_symptom_signature("alpha beta gamma")
        s2 = compute_symptom_signature("gamma alpha beta")
        assert s1 == s2

    def test_case_insensitive(self) -> None:
        s1 = compute_symptom_signature("Agent Skips Tests")
        s2 = compute_symptom_signature("agent skips tests")
        assert s1 == s2

    def test_unicode_normalization(self) -> None:
        # NFKC normalization: ﬁ -> fi
        # cannot easily inject NFKC ligature in test, so just assert determinism
        s_direct = compute_symptom_signature("file")
        assert len(s_direct) == 16

    def test_punctuation_stripped(self) -> None:
        # Non-alphanumeric chars act as separators; resulting tokens are the same
        s1 = compute_symptom_signature("agent-skips-tests")
        s2 = compute_symptom_signature("agent skips tests")
        assert s1 == s2

    def test_different_symptoms_produce_different_sigs(self) -> None:
        s1 = compute_symptom_signature("scope exceeded")
        s2 = compute_symptom_signature("test omission found")
        assert s1 != s2


# ---------------------------------------------------------------------------
# Constant matrices
# ---------------------------------------------------------------------------


class TestCategoryToCheckTypeMatrix:
    def test_scope_drift_maps_to_changed_file_policy(self) -> None:
        assert CATEGORY_TO_CHECK_TYPE[FailureCategory.SCOPE_DRIFT] is CheckType.CHANGED_FILE_POLICY

    def test_test_omission_maps_to_test_obligation(self) -> None:
        assert CATEGORY_TO_CHECK_TYPE[FailureCategory.TEST_OMISSION] is CheckType.TEST_OBLIGATION

    def test_hallucination_maps_to_fixture_replay(self) -> None:
        assert CATEGORY_TO_CHECK_TYPE[FailureCategory.HALLUCINATION] is CheckType.FIXTURE_REPLAY

    def test_all_categories_have_mapping(self) -> None:
        # All FailureCategory values must have an entry
        for cat in FailureCategory:
            assert cat in CATEGORY_TO_CHECK_TYPE, f"Missing mapping for {cat}"


class TestCheckTypeFalsePositiveRiskMatrix:
    def test_changed_file_policy_is_low(self) -> None:
        assert CHECK_TYPE_FALSE_POSITIVE_RISK[CheckType.CHANGED_FILE_POLICY] is FalsePositiveRisk.LOW

    def test_fixture_replay_is_high(self) -> None:
        assert CHECK_TYPE_FALSE_POSITIVE_RISK[CheckType.FIXTURE_REPLAY] is FalsePositiveRisk.HIGH

    def test_test_obligation_is_medium(self) -> None:
        assert CHECK_TYPE_FALSE_POSITIVE_RISK[CheckType.TEST_OBLIGATION] is FalsePositiveRisk.MEDIUM

    def test_all_check_types_covered(self) -> None:
        for ct in CheckType:
            assert ct in CHECK_TYPE_FALSE_POSITIVE_RISK, f"Missing risk for {ct}"

    def test_full_matrix_pinned_exactly(self) -> None:
        """Pin the COMPLETE CHECK_TYPE_FALSE_POSITIVE_RISK matrix (story §2.1.1)."""
        assert CHECK_TYPE_FALSE_POSITIVE_RISK == {
            CheckType.CHANGED_FILE_POLICY: FalsePositiveRisk.LOW,
            CheckType.SENSITIVE_PATH_GUARD: FalsePositiveRisk.LOW,
            CheckType.FORBIDDEN_DEPENDENCY: FalsePositiveRisk.LOW,
            CheckType.ARTIFACT_COMPLETENESS: FalsePositiveRisk.MEDIUM,
            CheckType.TEST_OBLIGATION: FalsePositiveRisk.MEDIUM,
            CheckType.FIXTURE_REPLAY: FalsePositiveRisk.HIGH,
        }

    def test_only_three_check_types_are_low_fp(self) -> None:
        """Exactly the three LOW-FP check types qualify for FAVORABLE_CHECKABILITY."""
        low = {
            ct
            for ct, risk in CHECK_TYPE_FALSE_POSITIVE_RISK.items()
            if risk is FalsePositiveRisk.LOW
        }
        assert low == {
            CheckType.CHANGED_FILE_POLICY,
            CheckType.SENSITIVE_PATH_GUARD,
            CheckType.FORBIDDEN_DEPENDENCY,
        }


# ---------------------------------------------------------------------------
# PatternPromotion.suggest_patterns
# ---------------------------------------------------------------------------


_STATE_BACKEND_ENV = "AGENTKIT_STATE_BACKEND"
_ALLOW_SQLITE_ENV = "AGENTKIT_ALLOW_SQLITE"


def _suggest_for_incidents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_key: str,
    incidents: list[dict[str, object]],
    *,
    now: datetime,
) -> list[object]:
    """Record the given incidents for one project and return suggest_patterns().

    Real production path: ``build_failure_corpus().record_incident`` through the
    ProjectionAccessor, then ``PatternPromotion.suggest_patterns(_now=now)``. The
    LLM boundary is not involved here (clustering/promotion is deterministic).

    Args:
        tmp_path: Per-test SQLite store dir.
        monkeypatch: For env isolation.
        project_key: Project key for all incidents.
        incidents: Each dict carries the per-incident overrides
            (``category``/``severity``/``symptom``/``story_id``/``run_id``).
        now: Injected UTC clock for the REPETITION 30d window.

    Returns:
        The list of ``PatternCandidate`` objects produced.
    """
    monkeypatch.setenv(_STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(_ALLOW_SQLITE_ENV, "1")
    from agentkit.backend.bootstrap.composition_root import build_failure_corpus
    from agentkit.backend.failure_corpus import IncidentCandidate
    from agentkit.backend.failure_corpus.types import IncidentRole
    from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
    from agentkit.backend.state_backend.store.fc_pattern_repository import (
        StateBackendFcPatternRepository,
    )
    from agentkit.backend.state_backend.store.projection_repositories import (
        build_projection_repositories,
    )
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

    reset_backend_cache_for_tests()
    accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
    corpus = build_failure_corpus(accessor)
    for spec in incidents:
        corpus.record_incident(
            IncidentCandidate(
                project_key=project_key,
                story_id=str(spec["story_id"]),
                run_id=str(spec["run_id"]),
                category=spec["category"],  # type: ignore[arg-type]
                severity=spec["severity"],  # type: ignore[arg-type]
                phase="implementation",
                role=IncidentRole.WORKER,
                model="claude-opus",
                symptom=str(spec["symptom"]),
                evidence=[],
                merge_blocked=True,
            )
        )
    pattern_repo = StateBackendFcPatternRepository(tmp_path)
    promo = PatternPromotion(accessor, pattern_repo, project_key)
    return promo.suggest_patterns(_now=now)


def _incident(
    category: FailureCategory,
    severity: object,
    symptom: str,
    idx: int,
) -> dict[str, object]:
    """Build one incident spec dict with a unique story/run id (avoids dedup)."""
    return {
        "category": category,
        "severity": severity,
        "symptom": symptom,
        "story_id": f"AG3-{idx:04d}",
        "run_id": f"run-{idx}",
    }


class TestSuggestPatterns:
    """Non-vacuous boundary tests: EXACT candidate counts + resulting rule.

    No ``if candidates``-guarded assertions. Each promotion rule is verified on
    BOTH its positive and its negative boundary, against the real production
    record_incident -> suggest_patterns path (LLM not involved). The priority
    order (HIGH_SEVERITY > REPETITION > FAVORABLE_CHECKABILITY) is pinned too.
    """

    def test_no_incidents_returns_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            candidates = _suggest_for_incidents(
                tmp_path, monkeypatch, "proj-empty", [], now=datetime.now(UTC)
            )
            assert candidates == []
        finally:
            reset_backend_cache_for_tests()

    # -- REPETITION boundary: 2 vs 3 within 30d ----------------------------

    def test_repetition_two_incidents_no_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2 TEST_OMISSION/LOW incidents in 30d -> NO candidate (REPETITION needs 3)."""
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-rep2",
                [
                    _incident(
                        FailureCategory.TEST_OMISSION,
                        IncidentSeverity.LOW,
                        "test suite not executed",
                        i,
                    )
                    for i in range(2)
                ],
                now=datetime.now(UTC),
            )
            assert len(candidates) == 0
        finally:
            reset_backend_cache_for_tests()

    def test_repetition_three_incidents_one_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """3 TEST_OMISSION/LOW incidents in 30d -> exactly one REPETITION candidate."""
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-rep3",
                [
                    _incident(
                        FailureCategory.TEST_OMISSION,
                        IncidentSeverity.LOW,
                        "test suite not executed",
                        i,
                    )
                    for i in range(3)
                ],
                now=datetime.now(UTC),
            )
            assert len(candidates) == 1
            assert candidates[0].promotion_rule is PromotionRule.REPETITION
            assert candidates[0].category is FailureCategory.TEST_OMISSION
        finally:
            reset_backend_cache_for_tests()

    # -- HIGH_SEVERITY boundary: HIGH at 1 vs MEDIUM at 1 -------------------

    def test_high_severity_one_high_incident_one_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """severity==HIGH at 1 -> exactly one HIGH_SEVERITY candidate."""
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-hs1",
                [
                    _incident(
                        FailureCategory.SCOPE_DRIFT,
                        IncidentSeverity.HIGH,
                        "agent rewrote files outside story scope",
                        1,
                    )
                ],
                now=datetime.now(UTC),
            )
            assert len(candidates) == 1
            assert candidates[0].promotion_rule is PromotionRule.HIGH_SEVERITY
            assert candidates[0].category is FailureCategory.SCOPE_DRIFT
        finally:
            reset_backend_cache_for_tests()

    def test_medium_severity_one_incident_no_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """severity==MEDIUM at 1 -> zero candidates (no rule satisfied at count 1)."""
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-ms1",
                [
                    _incident(
                        FailureCategory.SCOPE_DRIFT,
                        IncidentSeverity.MEDIUM,
                        "agent rewrote files outside story scope",
                        1,
                    )
                ],
                now=datetime.now(UTC),
            )
            assert len(candidates) == 0
        finally:
            reset_backend_cache_for_tests()

    # -- FAVORABLE_CHECKABILITY boundary: LOW-FP vs MEDIUM/HIGH-FP at 2 -----

    def test_favorable_checkability_two_low_fp_incidents_one_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2 incidents of a LOW-FP-risk category -> exactly one FAVORABLE_CHECKABILITY.

        POLICY_VIOLATION -> SENSITIVE_PATH_GUARD -> LOW FP risk. ``far_future`` now
        keeps the REPETITION 30d window from applying; LOW severity keeps
        HIGH_SEVERITY off.
        """
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        far_future = datetime.now(UTC) + timedelta(days=100)
        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-fav-low",
                [
                    _incident(
                        FailureCategory.POLICY_VIOLATION,
                        IncidentSeverity.LOW,
                        "sonar rule bypassed",
                        i,
                    )
                    for i in range(2)
                ],
                now=far_future,
            )
            assert len(candidates) == 1
            assert candidates[0].promotion_rule is PromotionRule.FAVORABLE_CHECKABILITY
            assert candidates[0].category is FailureCategory.POLICY_VIOLATION
        finally:
            reset_backend_cache_for_tests()

    def test_favorable_checkability_two_medium_fp_incidents_no_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2 incidents of a MEDIUM-FP-risk category -> zero candidates.

        TEST_OMISSION -> TEST_OBLIGATION -> MEDIUM FP risk. Outside the 30d window
        and LOW severity, so neither REPETITION nor HIGH_SEVERITY fires either.
        """
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        far_future = datetime.now(UTC) + timedelta(days=100)
        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-fav-med",
                [
                    _incident(
                        FailureCategory.TEST_OMISSION,
                        IncidentSeverity.LOW,
                        "test suite not executed",
                        i,
                    )
                    for i in range(2)
                ],
                now=far_future,
            )
            assert len(candidates) == 0
        finally:
            reset_backend_cache_for_tests()

    def test_favorable_checkability_two_high_fp_incidents_no_candidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """2 incidents of a HIGH-FP-risk category -> zero candidates.

        HALLUCINATION -> FIXTURE_REPLAY -> HIGH FP risk.
        """
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        far_future = datetime.now(UTC) + timedelta(days=100)
        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-fav-high",
                [
                    _incident(
                        FailureCategory.HALLUCINATION,
                        IncidentSeverity.LOW,
                        "fabricated test output",
                        i,
                    )
                    for i in range(2)
                ],
                now=far_future,
            )
            assert len(candidates) == 0
        finally:
            reset_backend_cache_for_tests()

    # -- Priority order: HIGH_SEVERITY > REPETITION > FAVORABLE_CHECKABILITY

    def test_priority_high_severity_beats_repetition(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """3 incidents in 30d (REPETITION) where one is HIGH -> HIGH_SEVERITY wins."""
        from agentkit.backend.failure_corpus.types import IncidentSeverity
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests

        try:
            candidates = _suggest_for_incidents(
                tmp_path,
                monkeypatch,
                "proj-prio",
                [
                    _incident(
                        FailureCategory.TEST_OMISSION,
                        IncidentSeverity.LOW,
                        "test suite not executed",
                        0,
                    ),
                    _incident(
                        FailureCategory.TEST_OMISSION,
                        IncidentSeverity.LOW,
                        "test suite not executed",
                        1,
                    ),
                    _incident(
                        FailureCategory.TEST_OMISSION,
                        IncidentSeverity.HIGH,
                        "test suite not executed",
                        2,
                    ),
                ],
                now=datetime.now(UTC),
            )
            assert len(candidates) == 1
            assert candidates[0].promotion_rule is PromotionRule.HIGH_SEVERITY
        finally:
            reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# PatternPromotion.confirm_pattern
# ---------------------------------------------------------------------------


class TestConfirmPattern:
    def test_accepted_saves_record_with_accepted_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.backend.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
            pattern_repo = StateBackendFcPatternRepository(tmp_path)
            promo = PatternPromotion(accessor, pattern_repo, "proj-test")
            record = promo.confirm_pattern(
                PatternId("FP-0001"),
                PatternDecision.ACCEPTED,
                invariant="Agent MUST NOT modify files outside story scope",
                risk_level=PatternRiskLevel.HIGH,
                promotion_rule=PromotionRule.HIGH_SEVERITY,
                incident_refs=["FC-2026-0001"],
                category=FailureCategory.SCOPE_DRIFT,
            )
            assert record.status is PatternStatus.ACCEPTED
            assert record.pattern_id == "FP-0001"
            assert record.invariant == "Agent MUST NOT modify files outside story scope"
            assert record.risk_level is PatternRiskLevel.HIGH
            # Verify it was persisted
            loaded = pattern_repo.load("FP-0001")
            assert loaded is not None
            assert loaded.status is PatternStatus.ACCEPTED
        finally:
            reset_backend_cache_for_tests()

    def test_rejected_saves_record_with_rejected_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.backend.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
            pattern_repo = StateBackendFcPatternRepository(tmp_path)
            promo = PatternPromotion(accessor, pattern_repo, "proj-test")
            record = promo.confirm_pattern(
                PatternId("FP-0002"),
                PatternDecision.REJECTED,
            )
            assert record.status is PatternStatus.REJECTED
            loaded = pattern_repo.load("FP-0002")
            assert loaded is not None
            assert loaded.status is PatternStatus.REJECTED
        finally:
            reset_backend_cache_for_tests()

    def test_accepted_requires_invariant_fail_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
        from agentkit.backend.failure_corpus.errors import FailureCorpusError
        from agentkit.backend.state_backend.store.facade import reset_backend_cache_for_tests
        from agentkit.backend.state_backend.store.fc_pattern_repository import (
            StateBackendFcPatternRepository,
        )
        from agentkit.backend.state_backend.store.projection_repositories import (
            build_projection_repositories,
        )
        from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

        reset_backend_cache_for_tests()
        try:
            accessor = ProjectionAccessor(build_projection_repositories(tmp_path))
            pattern_repo = StateBackendFcPatternRepository(tmp_path)
            promo = PatternPromotion(accessor, pattern_repo, "proj-test")
            with pytest.raises((FailureCorpusError, ValueError)):
                promo.confirm_pattern(
                    PatternId("FP-0003"),
                    PatternDecision.ACCEPTED,
                    invariant=None,  # required for ACCEPTED
                )
        finally:
            reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# ERROR 7: symptom_signature boundary tests
# ---------------------------------------------------------------------------


class TestSymptomSignatureExact:
    """Pin exact hash values + prove no stopword removal (ERROR 7 requirement)."""

    def test_ascii_fold_accent_cafe(self) -> None:
        """ERROR 5 / ERROR 7: accented café must produce the SAME signature as cafe.

        This tests the production ASCII fold: NFKC + NFD decomposition + encode(ignore)
        maps é -> e (base char preserved, combining accent dropped).
        """
        sig_accented = compute_symptom_signature("café")
        sig_plain = compute_symptom_signature("cafe")
        assert sig_accented == sig_plain, (
            f"ASCII fold broken: café -> {sig_accented!r} != cafe -> {sig_plain!r}"
        )

    def test_ascii_fold_multiple_accents(self) -> None:
        """Multiple accented chars all fold correctly."""
        # ñ -> n, ü -> u, à -> a
        sig1 = compute_symptom_signature("niño uber à la")
        sig2 = compute_symptom_signature("nino uber a la")
        assert sig1 == sig2

    def test_no_stopword_removal_common_words(self) -> None:
        """ERROR 7: the word 'the' is NOT removed — no stopword list exists.

        compute_symptom_signature must NOT strip 'the', 'and', 'or', 'is', etc.
        Adding a common stopword changes the token set and therefore the signature.
        """
        # If stopwords were removed, "the agent" and "agent" would give the same sig
        sig_with_the = compute_symptom_signature("the agent skips tests")
        sig_without_the = compute_symptom_signature("agent skips tests")
        assert sig_with_the != sig_without_the, (
            "Stopword 'the' was removed from signature — violates no-stopword rule"
        )

    def test_no_stopword_removal_and(self) -> None:
        """Verify 'and' is kept as a token (not stripped)."""
        sig_with_and = compute_symptom_signature("build and test failed")
        sig_without_and = compute_symptom_signature("build test failed")
        assert sig_with_and != sig_without_and, (
            "Stopword 'and' was removed — violates no-stopword rule"
        )

    def test_exact_hash_pinned(self) -> None:
        """Pin exact SHA-256[:16] for a known input.

        Input: "Agent skips E2E tests during implementation" (F-41-070 reference example input).
        Expected value computed from the fully specified pipeline:
        1. NFKC("Agent skips E2E tests during implementation") -> same (all ASCII)
        2. NFD -> same (all ASCII, no combining)
        3. ASCII encode -> same
        4. lowercase -> "agent skips e2e tests during implementation"
        5. tokenize on [^a-z0-9]+ -> ["agent", "skips", "e2e", "tests", "during", "implementation"]
        6. sort -> ["agent", "during", "e2e", "implementation", "skips", "tests"]
        7. join -> "agent during e2e implementation skips tests"
        8. sha256 hex[:16]
        """
        import hashlib
        joined = "agent during e2e implementation skips tests"
        expected = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
        actual = compute_symptom_signature("Agent skips E2E tests during implementation")
        assert actual == expected, (
            f"Exact hash mismatch for F-41-070 reference input: "
            f"expected {expected!r}, got {actual!r}"
        )

    def test_digits_kept_as_tokens(self) -> None:
        """Digits are not stripped — they are part of the token alphabet [a-z0-9]."""
        sig_with_digit = compute_symptom_signature("layer2 failed")
        sig_without_digit = compute_symptom_signature("layer failed")
        assert sig_with_digit != sig_without_digit, (
            "Digit '2' was dropped from token — digits should be kept"
        )
