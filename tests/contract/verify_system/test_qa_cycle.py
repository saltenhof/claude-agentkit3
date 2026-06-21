"""Contract: cycle-bound QA-artefact invalidation set pinned to FK-27 §27.2.3.

AG3-041 AC8 / E6. The :data:`CYCLE_BOUND_QA_ARTIFACTS` tuple is the operative
invalidation set. FK-27 §27.2.3 prose says "11 Dateien" but the normative
table enumerates 12 rows; the table is authoritative.

E6 (anti-self-fulfilling): the filenames that have a canonical SINGLE SOURCE OF
TRUTH are pinned AGAINST that SSOT (``core_types.qa_artifact_names`` — the 6
FK-27 §27.7 QA files plus ``GUARDRAIL_FILE``), NOT against a tuple duplicated
inside this test. Only the cycle-only extras that have no other home
(``sonarqube_gate``/``e2e_verify``/``context``/``context_sufficiency``,
FK-27 §27.2.3 / §27.6a.3) are pinned by literal here, each FK-anchored. The
path root mirrors ``installer.paths.QA_DIR`` (one path truth, E4).
"""

from __future__ import annotations

from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.installer.paths import QA_DIR
from agentkit.backend.verify_system.contract import PolicyVerdictResult
from agentkit.backend.verify_system.qa_cycle.invalidation import (
    CYCLE_BOUND_QA_ARTIFACTS,
    QA_ARTIFACT_SUBDIR,
    STALE_SUBDIR,
)


class TestCycleBoundArtifactContract:
    def test_ssot_qa_files_are_all_invalidated(self) -> None:
        """Every canonical QA artefact (SSOT) is in the invalidation set.

        Pins AGAINST ``core_types.qa_artifact_names`` — the single naming
        truth — not a test-local duplicate. A drift in any QA filename in the
        SSOT that is NOT mirrored into the invalidation set breaks this test.
        """
        from agentkit.backend.core_types.qa_artifact_names import (
            ALL_QA_ARTIFACT_FILES,
            GUARDRAIL_FILE,
        )

        cycle_set = set(CYCLE_BOUND_QA_ARTIFACTS)
        for name in (*ALL_QA_ARTIFACT_FILES, GUARDRAIL_FILE):
            assert name in cycle_set, (
                f"{name} is a canonical QA artefact (SSOT) but is missing from "
                "the cycle-bound invalidation set (FK-27 §27.2.3)"
            )

    def test_cycle_only_extras_pinned(self) -> None:
        """The invalidation-only extras (no other SSOT home) are FK-anchored.

        FK-27 §27.2.3 / §27.6a.3: ``sonarqube_gate.json`` (zyklusgebunden),
        ``e2e_verify.json`` (reserviert), ``context.json`` /
        ``context_sufficiency.json`` (rebuild pre-step) are part of the
        invalidation table but have no naming SSOT constant; pinned by literal.
        """
        cycle_set = set(CYCLE_BOUND_QA_ARTIFACTS)
        for name in (
            "feedback.json",
            "sonarqube_gate.json",
            "e2e_verify.json",
            "context.json",
            "context_sufficiency.json",
        ):
            assert name in cycle_set, name

    def test_all_entries_are_json(self) -> None:
        for name in CYCLE_BOUND_QA_ARTIFACTS:
            assert name.endswith(".json"), name

    def test_no_duplicate_entries(self) -> None:
        assert len(CYCLE_BOUND_QA_ARTIFACTS) == len(set(CYCLE_BOUND_QA_ARTIFACTS))

    def test_table_row_count_is_twelve(self) -> None:
        # FK-27 §27.2.3 prose says 11, table lists 12; table is operative.
        assert len(CYCLE_BOUND_QA_ARTIFACTS) == 12  # noqa: PLR2004

    def test_artifact_root_mirrors_installer_ssot(self) -> None:
        # E4: QA_ARTIFACT_SUBDIR must mirror installer.paths.QA_DIR (one path
        # truth); invalidated files move into the stale/ sub-directory.
        assert QA_ARTIFACT_SUBDIR == QA_DIR
        assert QA_ARTIFACT_SUBDIR == "_temp/qa"
        assert STALE_SUBDIR == "stale"


class TestPolicyVerdictResultContract:
    def test_escalated_flag_defaults_false(self) -> None:
        result = PolicyVerdictResult(verdict=PolicyVerdict.PASS)
        assert result.escalated is False
        assert result.closure_blocked is False

    def test_escalated_requires_fail(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="escalated"):
            PolicyVerdictResult(verdict=PolicyVerdict.PASS, escalated=True)

    def test_escalated_fail_allowed(self) -> None:
        result = PolicyVerdictResult(
            verdict=PolicyVerdict.FAIL, escalated=True, closure_blocked=True
        )
        assert result.escalated is True
        assert result.closure_blocked is True
