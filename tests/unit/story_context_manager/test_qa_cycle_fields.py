"""Tests fuer QA-Zyklus-Identitaets-Felder in ImplementationPayload (FK-27 §27.2.1).

Verifiziert wortgleich zum Konzept FK-27 §27.2.1:
- ``qa_cycle_id`` = 12-Zeichen lowercase hex (UUID-Fragment)
- ``qa_cycle_round`` = monotoner Zaehler ab 1 (wenn qa_cycle_id gesetzt)
- ``evidence_epoch`` = ISO-8601 Timestamp (UTC-aware datetime)
- ``evidence_fingerprint`` = SHA-256 hex (64 lowercase hex chars)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentkit.backend.pipeline_engine.phase_executor import ImplementationPayload

_VALID_QA_CYCLE_ID = "a1b2c3d4e5f6"  # 12 lowercase hex chars
_VALID_SHA256 = "a" * 64  # 64 lowercase hex chars
_VALID_EPOCH = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)


class TestQaCycleFieldDefaults:
    """Pflicht-Defaults bei Erstanlage (Idle-State)."""

    def test_defaults_all_none_or_zero(self) -> None:
        payload = ImplementationPayload()
        assert payload.qa_cycle_id is None
        assert payload.qa_cycle_round == 0
        assert payload.evidence_epoch is None
        assert payload.evidence_fingerprint is None

    def test_phase_type_is_implementation(self) -> None:
        payload = ImplementationPayload()
        assert payload.phase_type == "implementation"


class TestQaCycleIdFragmentValidation:
    """qa_cycle_id ist 12-char lowercase hex UUID-Fragment (FK-27 §27.2.1)."""

    def test_valid_fragment_accepted(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_QA_CYCLE_ID, qa_cycle_round=1,
        )
        assert payload.qa_cycle_id == _VALID_QA_CYCLE_ID

    def test_full_uuid4_rejected(self) -> None:
        """Volle UUID4 (36 chars) ist KEIN 12-char-Fragment."""
        from uuid import uuid4
        full_uuid = str(uuid4())
        with pytest.raises(ValidationError, match="12-char"):
            ImplementationPayload(qa_cycle_id=full_uuid, qa_cycle_round=1)

    def test_short_hex_rejected(self) -> None:
        with pytest.raises(ValidationError, match="12-char"):
            ImplementationPayload(qa_cycle_id="abc123", qa_cycle_round=1)

    def test_upper_case_hex_rejected(self) -> None:
        """Pattern verlangt lowercase."""
        with pytest.raises(ValidationError, match="12-char"):
            ImplementationPayload(qa_cycle_id="A1B2C3D4E5F6", qa_cycle_round=1)

    def test_non_hex_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="12-char"):
            ImplementationPayload(
                qa_cycle_id="zzzzzzzzzzzz",  # 12 chars, but not hex
                qa_cycle_round=1,
            )


class TestQaCycleRoundValidator:
    """qa_cycle_round >= 1 wenn qa_cycle_id gesetzt (FK-27 §27.2.1)."""

    def test_id_set_round_ge_1_valid(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_QA_CYCLE_ID, qa_cycle_round=1,
        )
        assert payload.qa_cycle_round == 1

    def test_id_set_round_zero_invalid(self) -> None:
        with pytest.raises(ValidationError, match="qa_cycle_round"):
            ImplementationPayload(
                qa_cycle_id=_VALID_QA_CYCLE_ID, qa_cycle_round=0,
            )

    def test_id_none_round_zero_valid(self) -> None:
        payload = ImplementationPayload(qa_cycle_id=None, qa_cycle_round=0)
        assert payload.qa_cycle_id is None
        assert payload.qa_cycle_round == 0

    def test_id_none_round_positive_valid(self) -> None:
        """Without qa_cycle_id, any non-negative qa_cycle_round is valid."""
        payload = ImplementationPayload(qa_cycle_id=None, qa_cycle_round=3)
        assert payload.qa_cycle_round == 3


class TestEvidenceEpochTimestamp:
    """evidence_epoch ist ISO-8601 UTC-aware Timestamp (FK-27 §27.2.1)."""

    def test_defaults_to_none(self) -> None:
        payload = ImplementationPayload()
        assert payload.evidence_epoch is None

    def test_valid_utc_datetime_accepted(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_QA_CYCLE_ID,
            qa_cycle_round=1,
            evidence_epoch=_VALID_EPOCH,
        )
        assert payload.evidence_epoch == _VALID_EPOCH

    def test_naive_datetime_rejected(self) -> None:
        """Naive datetime ohne tzinfo ist fail-closed.

        Pydantic v2 akzeptiert int und ISO-Strings ueblicherweise als
        ``datetime``-Coercion, faellt dann aber auf naive datetimes
        zurueck. Unser custom-validator faengt das ab.
        """
        naive = datetime(2026, 5, 18, 12, 0, 0)  # no tz
        with pytest.raises(ValidationError, match="tz-aware"):
            ImplementationPayload(
                qa_cycle_id=_VALID_QA_CYCLE_ID,
                qa_cycle_round=1,
                evidence_epoch=naive,
            )

    def test_int_unix_timestamp_coerced_to_utc(self) -> None:
        """Pydantic coerced int -> UTC-aware datetime (Unix-Timestamp).

        Das ist FK-27-konform: int wird als Unix-Epoch interpretiert und
        traegt damit eine UTC-Zeitzone — der Validator akzeptiert das.
        """
        payload = ImplementationPayload(evidence_epoch=42)
        assert payload.evidence_epoch is not None
        assert payload.evidence_epoch.tzinfo is not None
        assert payload.evidence_epoch.tzinfo.utcoffset(payload.evidence_epoch) == (
            payload.evidence_epoch.tzinfo.utcoffset(payload.evidence_epoch)
        )

    def test_non_utc_tz_aware_datetime_rejected(self) -> None:
        """Pass-4 ERROR-7: tz-aware aber nicht UTC (z.B. +02:00) wird abgelehnt.

        FK-27 §27.2.1 verlangt UTC; ein +02:00-Wert ist nicht offset=0
        und damit fail-closed.
        """
        from datetime import timezone

        plus_two = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        with pytest.raises(ValidationError, match="UTC"):
            ImplementationPayload(
                qa_cycle_id=_VALID_QA_CYCLE_ID,
                qa_cycle_round=1,
                evidence_epoch=plus_two,
            )


class TestEvidenceFingerprintSha256:
    """evidence_fingerprint ist SHA-256 hex (FK-27 §27.2.1)."""

    def test_fingerprint_defaults_none(self) -> None:
        payload = ImplementationPayload()
        assert payload.evidence_fingerprint is None

    def test_valid_sha256_accepted(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_QA_CYCLE_ID,
            qa_cycle_round=1,
            evidence_fingerprint=_VALID_SHA256,
        )
        assert payload.evidence_fingerprint == _VALID_SHA256

    def test_short_hex_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SHA-256"):
            ImplementationPayload(
                qa_cycle_id=_VALID_QA_CYCLE_ID,
                qa_cycle_round=1,
                evidence_fingerprint="abc123",
            )

    def test_upper_case_hex_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SHA-256"):
            ImplementationPayload(
                qa_cycle_id=_VALID_QA_CYCLE_ID,
                qa_cycle_round=1,
                evidence_fingerprint="A" * 64,
            )

    def test_non_hex_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="SHA-256"):
            ImplementationPayload(
                qa_cycle_id=_VALID_QA_CYCLE_ID,
                qa_cycle_round=1,
                evidence_fingerprint="g" * 64,
            )


class TestImplementationPayloadFrozen:
    """ImplementationPayload ist frozen=True."""

    def test_frozen(self) -> None:
        payload = ImplementationPayload()
        with pytest.raises(ValidationError, match="frozen"):
            payload.qa_cycle_id = _VALID_QA_CYCLE_ID  # type: ignore[misc]


class TestQaCycleFull:
    """Vollstaendiger QA-Zyklus-Zustand mit FK-27-konformen Werten."""

    def test_full_qa_cycle_state(self) -> None:
        payload = ImplementationPayload(
            qa_cycle_id=_VALID_QA_CYCLE_ID,
            qa_cycle_round=3,
            evidence_epoch=_VALID_EPOCH,
            evidence_fingerprint=_VALID_SHA256,
        )
        assert payload.qa_cycle_id == _VALID_QA_CYCLE_ID
        assert payload.qa_cycle_round == 3
        assert payload.evidence_epoch == _VALID_EPOCH
        assert payload.evidence_fingerprint == _VALID_SHA256
