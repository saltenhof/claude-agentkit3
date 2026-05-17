"""Tests fuer QA-Zyklus-Identitaets-Felder in ImplementationPayload (AG3-025 §2.1.3).

Verifiziert: qa_cycle_id, qa_cycle_round, evidence_epoch, evidence_fingerprint
plus Validator: bei gesetztem qa_cycle_id muss qa_cycle_round >= 1 sein.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.story_context_manager.models import ImplementationPayload


class TestQaCycleFieldDefaults:
    """AK6: Pflicht-Defaults bei Erstanlage."""

    def test_defaults_all_none_or_zero(self) -> None:
        payload = ImplementationPayload()
        assert payload.qa_cycle_id is None
        assert payload.qa_cycle_round == 0
        assert payload.evidence_epoch == 0
        assert payload.evidence_fingerprint is None

    def test_phase_type_is_implementation(self) -> None:
        payload = ImplementationPayload()
        assert payload.phase_type == "implementation"


class TestQaCycleRoundValidator:
    """AK6: qa_cycle_round >= 1 wenn qa_cycle_id gesetzt."""

    def test_id_set_round_ge_1_valid(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id="uuid-abc",
            qa_cycle_round=1,
        )
        assert payload.qa_cycle_id == "uuid-abc"
        assert payload.qa_cycle_round == 1

    def test_id_set_round_zero_invalid(self) -> None:
        with pytest.raises(ValidationError, match="qa_cycle_round"):
            ImplementationPayload(
                qa_cycle_id="uuid-abc",
                qa_cycle_round=0,
            )

    def test_id_none_round_zero_valid(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=None,
            qa_cycle_round=0,
        )
        assert payload.qa_cycle_id is None
        assert payload.qa_cycle_round == 0

    def test_id_none_round_positive_valid(self) -> None:
        """Without qa_cycle_id, any non-negative qa_cycle_round is valid."""
        payload = ImplementationPayload(
            qa_cycle_id=None,
            qa_cycle_round=3,
        )
        assert payload.qa_cycle_round == 3


class TestEvidenceEpochType:
    """evidence_epoch ist int (nicht str), >= 0."""

    def test_evidence_epoch_is_int(self) -> None:
        payload = ImplementationPayload(evidence_epoch=0)
        assert isinstance(payload.evidence_epoch, int)

    def test_evidence_epoch_positive(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id="uuid-x",
            qa_cycle_round=1,
            evidence_epoch=5,
        )
        assert payload.evidence_epoch == 5

    def test_evidence_epoch_negative_invalid(self) -> None:
        with pytest.raises(ValidationError, match="evidence_epoch"):
            ImplementationPayload(evidence_epoch=-1)

    def test_evidence_epoch_not_string(self) -> None:
        """evidence_epoch muss int sein, nicht str."""
        with pytest.raises(ValidationError):
            ImplementationPayload(evidence_epoch="not-an-int")  # type: ignore[arg-type]


class TestEvidenceFingerprint:
    """evidence_fingerprint ist str | None."""

    def test_fingerprint_defaults_none(self) -> None:
        payload = ImplementationPayload()
        assert payload.evidence_fingerprint is None

    def test_fingerprint_can_be_set(self) -> None:
        sha = "a" * 64
        payload = ImplementationPayload(
            qa_cycle_id="uuid-y",
            qa_cycle_round=1,
            evidence_fingerprint=sha,
        )
        assert payload.evidence_fingerprint == sha


class TestImplementationPayloadFrozen:
    """ImplementationPayload ist frozen=True."""

    def test_frozen(self) -> None:
        from pydantic import ValidationError
        payload = ImplementationPayload()
        with pytest.raises(ValidationError, match="frozen"):
            payload.qa_cycle_id = "changed"  # type: ignore[misc]


class TestQaCycleFull:
    """Vollstaendiger QA-Zyklus-Zustand ist valide."""

    def test_full_qa_cycle_state(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id="uuid-full",
            qa_cycle_round=3,
            evidence_epoch=2,
            evidence_fingerprint="abc123",
        )
        assert payload.qa_cycle_id == "uuid-full"
        assert payload.qa_cycle_round == 3
        assert payload.evidence_epoch == 2
        assert payload.evidence_fingerprint == "abc123"
