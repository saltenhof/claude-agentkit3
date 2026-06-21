"""Unit-Tests fuer ArtifactClass und EnvelopeStatus (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus


class TestArtifactClass:
    def test_each_value_constructable(self) -> None:
        for raw in (
            "worker",
            "qa",
            "pipeline",
            "telemetry",
            "governance",
            "entwurf",
            "handover",
            "adversarial_test_sandbox",
            "prompt_audit",
        ):
            assert ArtifactClass(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert list(ArtifactClass) == [
            ArtifactClass.WORKER,
            ArtifactClass.QA,
            ArtifactClass.PIPELINE,
            ArtifactClass.TELEMETRY,
            ArtifactClass.GOVERNANCE,
            ArtifactClass.ENTWURF,
            ArtifactClass.HANDOVER,
            ArtifactClass.ADVERSARIAL_TEST_SANDBOX,
            ArtifactClass.PROMPT_AUDIT,
        ]

    def test_str_enum_invariants(self) -> None:
        assert ArtifactClass.WORKER.value == "worker"
        assert isinstance(ArtifactClass.WORKER, str)

    def test_upper_case_rejected(self) -> None:
        """Wire-Werte sind lowercase; upper-case ist ungueltig."""
        for raw in ("WORKER", "QA", "ADVERSARIAL_TEST_SANDBOX"):
            with pytest.raises(ValueError):
                ArtifactClass(raw)

    def test_nine_values(self) -> None:
        # AG3-015: prompt_audit added (FK-44 §44.6); 8 -> 9.
        assert len(ArtifactClass) == 9


class TestEnvelopeStatus:
    def test_each_value_constructable(self) -> None:
        for raw in ("PASS", "FAIL", "WARN", "ERROR"):
            assert EnvelopeStatus(raw).value == raw

    def test_iteration_is_deterministic(self) -> None:
        assert list(EnvelopeStatus) == [
            EnvelopeStatus.PASS,
            EnvelopeStatus.FAIL,
            EnvelopeStatus.WARN,
            EnvelopeStatus.ERROR,
        ]

    def test_str_enum_invariants(self) -> None:
        assert EnvelopeStatus.PASS.value == "PASS"
        assert isinstance(EnvelopeStatus.PASS, str)

    def test_pass_with_warnings_rejected(self) -> None:
        """PASS_WITH_WARNINGS faellt mit AG3-021 weg."""
        with pytest.raises(ValueError):
            EnvelopeStatus("PASS_WITH_WARNINGS")

    def test_pass_with_concerns_is_llm_status_not_envelope(self) -> None:
        """PASS_WITH_CONCERNS ist LLM-Check-Status (AG3-022), kein
        EnvelopeStatus — Mapping erfolgt im Envelope-Rand."""
        with pytest.raises(ValueError):
            EnvelopeStatus("PASS_WITH_CONCERNS")
