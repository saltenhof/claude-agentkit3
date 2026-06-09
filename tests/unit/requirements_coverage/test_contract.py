"""Unit tests for requirements_coverage contract data models (AG3-030)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.requirements_coverage.contract import (
    AreContext,
    AreDockpointStatus,
    AreEvidence,
    AreRequirement,
    AreRequirementType,
    ContextLoadResult,
    CoverageVerdict,
    EvidenceCoverage,
    EvidenceProducer,
    EvidenceSubmitResult,
    EvidenceType,
    LinkResult,
)

# ---------------------------------------------------------------------------
# StrEnum values
# ---------------------------------------------------------------------------

class TestAreDockpointStatus:
    def test_values(self) -> None:
        assert AreDockpointStatus.SKIPPED == "SKIPPED"
        assert AreDockpointStatus.PASS == "PASS"
        assert AreDockpointStatus.FAIL == "FAIL"
        assert AreDockpointStatus.ERROR == "ERROR"

    def test_all_four_members(self) -> None:
        assert len(AreDockpointStatus) == 4


class TestAreRequirementType:
    def test_values(self) -> None:
        assert AreRequirementType.REGULATORY == "regulatory"
        assert AreRequirementType.BUSINESS_RULE == "business_rule"
        assert AreRequirementType.REPORT_MAPPING == "report_mapping"
        assert AreRequirementType.SYSTEM == "system"
        assert AreRequirementType.QUALITY == "quality"

    def test_all_five_members(self) -> None:
        assert len(AreRequirementType) == 5


class TestEvidenceType:
    def test_values(self) -> None:
        assert EvidenceType.TEST_REPORT == "test_report"
        assert EvidenceType.COMMIT_REF == "commit_ref"
        assert EvidenceType.ARTIFACT_REF == "artifact_ref"
        assert EvidenceType.MANUAL_NOTE == "manual_note"

    def test_all_four_members(self) -> None:
        assert len(EvidenceType) == 4


class TestEvidenceProducer:
    def test_values(self) -> None:
        assert EvidenceProducer.WORKER == "WORKER"
        assert EvidenceProducer.QA == "QA"

    def test_two_members(self) -> None:
        assert len(EvidenceProducer) == 2


class TestEvidenceCoverage:
    def test_values(self) -> None:
        assert EvidenceCoverage.FULL == "FULL"
        assert EvidenceCoverage.PARTIAL == "PARTIAL"

    def test_two_members(self) -> None:
        assert len(EvidenceCoverage) == 2


# ---------------------------------------------------------------------------
# AreRequirement
# ---------------------------------------------------------------------------

class TestAreRequirement:
    def _make(self, **overrides: object) -> AreRequirement:
        defaults: dict[str, object] = {
            "requirement_id": "REQ-1",
            "requirement_type": AreRequirementType.REGULATORY,
            "summary": "All data must be encrypted",
            "description": None,
            "must_cover": True,
            "acceptance_criteria": ["Encryption key rotation documented"],
            "recurring": False,
        }
        defaults.update(overrides)
        return AreRequirement(**defaults)  # type: ignore[arg-type]

    def test_all_required_fields(self) -> None:
        req = self._make()
        assert req.requirement_id == "REQ-1"
        assert req.requirement_type == AreRequirementType.REGULATORY
        assert req.summary == "All data must be encrypted"
        assert req.description is None
        assert req.must_cover is True
        assert req.acceptance_criteria == ["Encryption key rotation documented"]
        assert req.recurring is False

    def test_frozen_rejects_mutation(self) -> None:
        req = self._make()
        with pytest.raises(ValidationError):
            req.summary = "changed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AreRequirement(
                requirement_id="REQ-1",
                requirement_type=AreRequirementType.SYSTEM,
                summary="x",
                description=None,
                must_cover=False,
                acceptance_criteria=[],
                recurring=False,
                unknown_field="oops",  # type: ignore[call-arg]
            )

    def test_optional_description_with_value(self) -> None:
        req = self._make(description="Longer explanation")
        assert req.description == "Longer explanation"


# ---------------------------------------------------------------------------
# AreContext
# ---------------------------------------------------------------------------

class TestAreContext:
    def test_basic(self) -> None:
        now = datetime.now(UTC)
        ctx = AreContext(requirements=[], loaded_at=now)
        assert ctx.requirements == []
        assert ctx.loaded_at == now

    def test_frozen(self) -> None:
        now = datetime.now(UTC)
        ctx = AreContext(requirements=[], loaded_at=now)
        with pytest.raises(ValidationError):
            ctx.requirements = []  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AreContext(requirements=[], loaded_at=datetime.now(UTC), extra="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AreEvidence
# ---------------------------------------------------------------------------

class TestAreEvidence:
    def test_basic(self) -> None:
        ev = AreEvidence(
            requirement_id="REQ-42",
            evidence_type=EvidenceType.TEST_REPORT,
            evidence_ref="tests/test_x.py::test_y",
            produced_by=EvidenceProducer.WORKER,
        )
        assert ev.requirement_id == "REQ-42"
        assert ev.evidence_type == EvidenceType.TEST_REPORT
        assert ev.produced_by == EvidenceProducer.WORKER
        assert ev.coverage is EvidenceCoverage.FULL

    def test_frozen(self) -> None:
        ev = AreEvidence(
            requirement_id="REQ-1",
            evidence_type=EvidenceType.COMMIT_REF,
            evidence_ref="abc123",
            produced_by=EvidenceProducer.QA,
        )
        with pytest.raises(ValidationError):
            ev.evidence_ref = "xyz"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AreEvidence(
                requirement_id="REQ-1",
                evidence_type=EvidenceType.MANUAL_NOTE,
                evidence_ref="note",
                produced_by=EvidenceProducer.WORKER,
                unknown="x",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class TestLinkResult:
    def test_skipped_with_reason(self) -> None:
        r = LinkResult(status=AreDockpointStatus.SKIPPED, reason="feature_disabled")
        assert r.status == AreDockpointStatus.SKIPPED
        assert r.reason == "feature_disabled"

    def test_reason_optional(self) -> None:
        r = LinkResult(status=AreDockpointStatus.PASS)
        assert r.reason is None

    def test_frozen(self) -> None:
        r = LinkResult(status=AreDockpointStatus.SKIPPED)
        with pytest.raises(ValidationError):
            r.status = AreDockpointStatus.PASS  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LinkResult(status=AreDockpointStatus.PASS, nope="x")  # type: ignore[call-arg]


class TestContextLoadResult:
    def test_skipped(self) -> None:
        r = ContextLoadResult(status=AreDockpointStatus.SKIPPED, are_bundle_ref=None)
        assert r.are_bundle_ref is None

    def test_frozen(self) -> None:
        r = ContextLoadResult(status=AreDockpointStatus.SKIPPED, are_bundle_ref=None)
        with pytest.raises(ValidationError):
            r.status = AreDockpointStatus.PASS  # type: ignore[misc]


class TestEvidenceSubmitResult:
    def test_skipped(self) -> None:
        r = EvidenceSubmitResult(status=AreDockpointStatus.SKIPPED)
        assert r.status == AreDockpointStatus.SKIPPED

    def test_frozen(self) -> None:
        r = EvidenceSubmitResult(status=AreDockpointStatus.PASS)
        with pytest.raises(ValidationError):
            r.status = AreDockpointStatus.FAIL  # type: ignore[misc]


class TestCoverageVerdict:
    def test_skipped(self) -> None:
        r = CoverageVerdict(status=AreDockpointStatus.SKIPPED, verdict=None)
        assert r.verdict is None

    def test_pass_verdict(self) -> None:
        r = CoverageVerdict(status=AreDockpointStatus.PASS, verdict="PASS")
        assert r.verdict == "PASS"
        assert r.uncovered_requirements == ()
        assert r.reason is None

    def test_fail_with_uncovered_and_reason(self) -> None:
        requirement = AreRequirement(
            requirement_id="REQ-1",
            requirement_type=AreRequirementType.SYSTEM,
            summary="Missing",
            description=None,
            must_cover=True,
            acceptance_criteria=[],
            recurring=False,
        )
        r = CoverageVerdict(
            status=AreDockpointStatus.FAIL,
            verdict="FAIL",
            uncovered_requirements=(requirement,),
            reason="missing_evidence",
        )
        assert r.uncovered_requirements == (requirement,)
        assert r.reason == "missing_evidence"

    def test_frozen(self) -> None:
        r = CoverageVerdict(status=AreDockpointStatus.SKIPPED, verdict=None)
        with pytest.raises(ValidationError):
            r.verdict = "PASS"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CoverageVerdict(status=AreDockpointStatus.PASS, verdict="PASS", extra="x")  # type: ignore[call-arg]
