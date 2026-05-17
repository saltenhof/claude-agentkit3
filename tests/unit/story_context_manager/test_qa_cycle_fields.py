"""Tests fuer QA-Zyklus-Identitaets-Felder in ImplementationPayload (AG3-025 §2.1.3).

Verifiziert:
- ``qa_cycle_id`` ist UUID4-String (Pattern + version=4 strikt)
- ``evidence_fingerprint`` ist SHA-256-hex (64 lowercase hex chars)
- ``qa_cycle_round`` >= 1 wenn ``qa_cycle_id`` gesetzt
- alle Felder sind frozen
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agentkit.story_context_manager.models import ImplementationPayload

_VALID_UUID4 = str(uuid4())
_VALID_SHA256 = "a" * 64  # 64 lowercase hex chars


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


class TestQaCycleIdUuid4Validation:
    """qa_cycle_id ist UUID4-String (FK-27 §27.2)."""

    def test_valid_uuid4_accepted(self) -> None:
        payload = ImplementationPayload(qa_cycle_id=_VALID_UUID4, qa_cycle_round=1)
        assert payload.qa_cycle_id == _VALID_UUID4

    def test_free_string_rejected(self) -> None:
        """Ein freier String wie "uuid-abc" ist KEIN UUID4 und muss fail-closen."""
        with pytest.raises(ValidationError, match="UUID4"):
            ImplementationPayload(qa_cycle_id="uuid-abc", qa_cycle_round=1)

    def test_uuid_v1_rejected(self) -> None:
        """UUID1 hat version=1; nur UUID4 ist zulaessig."""
        uuid_v1 = "550e8400-e29b-11d4-a716-446655440000"  # version=1
        with pytest.raises(ValidationError, match="version 4"):
            ImplementationPayload(qa_cycle_id=uuid_v1, qa_cycle_round=1)

    def test_malformed_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError, match="UUID4"):
            ImplementationPayload(
                qa_cycle_id="not-a-uuid-at-all",
                qa_cycle_round=1,
            )


class TestQaCycleRoundValidator:
    """AK6: qa_cycle_round >= 1 wenn qa_cycle_id gesetzt."""

    def test_id_set_round_ge_1_valid(self) -> None:
        payload = ImplementationPayload(qa_cycle_id=_VALID_UUID4, qa_cycle_round=1)
        assert payload.qa_cycle_round == 1

    def test_id_set_round_zero_invalid(self) -> None:
        with pytest.raises(ValidationError, match="qa_cycle_round"):
            ImplementationPayload(qa_cycle_id=_VALID_UUID4, qa_cycle_round=0)

    def test_id_none_round_zero_valid(self) -> None:
        payload = ImplementationPayload(qa_cycle_id=None, qa_cycle_round=0)
        assert payload.qa_cycle_id is None
        assert payload.qa_cycle_round == 0

    def test_id_none_round_positive_valid(self) -> None:
        """Without qa_cycle_id, any non-negative qa_cycle_round is valid."""
        payload = ImplementationPayload(qa_cycle_id=None, qa_cycle_round=3)
        assert payload.qa_cycle_round == 3


class TestEvidenceEpochType:
    """evidence_epoch ist int (nicht str), >= 0."""

    def test_evidence_epoch_is_int(self) -> None:
        payload = ImplementationPayload(evidence_epoch=0)
        assert isinstance(payload.evidence_epoch, int)

    def test_evidence_epoch_positive(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_UUID4,
            qa_cycle_round=1,
            evidence_epoch=5,
        )
        assert payload.evidence_epoch == 5

    def test_evidence_epoch_negative_invalid(self) -> None:
        with pytest.raises(ValidationError, match="evidence_epoch"):
            ImplementationPayload(evidence_epoch=-1)

    def test_evidence_epoch_not_string(self) -> None:
        with pytest.raises(ValidationError):
            ImplementationPayload(evidence_epoch="not-an-int")


class TestEvidenceFingerprintSha256Validation:
    """evidence_fingerprint ist SHA-256 hex (FK-27 §27.2)."""

    def test_fingerprint_defaults_none(self) -> None:
        payload = ImplementationPayload()
        assert payload.evidence_fingerprint is None

    def test_valid_sha256_accepted(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_UUID4,
            qa_cycle_round=1,
            evidence_fingerprint=_VALID_SHA256,
        )
        assert payload.evidence_fingerprint == _VALID_SHA256

    def test_short_hex_rejected(self) -> None:
        """SHA-256 ist 64 chars; kuerzere hex-strings sind fail-closed."""
        with pytest.raises(ValidationError, match="SHA-256"):
            ImplementationPayload(
                qa_cycle_id=_VALID_UUID4,
                qa_cycle_round=1,
                evidence_fingerprint="abc123",
            )

    def test_upper_case_hex_rejected(self) -> None:
        """SHA-256 hex muss lowercase sein."""
        with pytest.raises(ValidationError, match="SHA-256"):
            ImplementationPayload(
                qa_cycle_id=_VALID_UUID4,
                qa_cycle_round=1,
                evidence_fingerprint="A" * 64,
            )

    def test_non_hex_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SHA-256"):
            ImplementationPayload(
                qa_cycle_id=_VALID_UUID4,
                qa_cycle_round=1,
                evidence_fingerprint="g" * 64,
            )


class TestImplementationPayloadFrozen:
    """ImplementationPayload ist frozen=True."""

    def test_frozen(self) -> None:
        payload = ImplementationPayload()
        with pytest.raises(ValidationError, match="frozen"):
            payload.qa_cycle_id = _VALID_UUID4  # type: ignore[misc]


class TestQaCycleFull:
    """Vollstaendiger QA-Zyklus-Zustand mit korrekt typisierten Werten."""

    def test_full_qa_cycle_state(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_UUID4,
            qa_cycle_round=3,
            evidence_epoch=2,
            evidence_fingerprint=_VALID_SHA256,
        )
        assert payload.qa_cycle_id == _VALID_UUID4
        assert payload.qa_cycle_round == 3
        assert payload.evidence_epoch == 2
        assert payload.evidence_fingerprint == _VALID_SHA256
