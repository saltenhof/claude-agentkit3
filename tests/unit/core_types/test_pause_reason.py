"""Unit-Tests fuer PauseReason und from_yield_status (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.core_types import PauseReason


def test_each_value_constructable() -> None:
    assert (
        PauseReason("AWAITING_DESIGN_REVIEW")
        is PauseReason.AWAITING_DESIGN_REVIEW
    )
    assert (
        PauseReason("AWAITING_DESIGN_CHALLENGE")
        is PauseReason.AWAITING_DESIGN_CHALLENGE
    )
    assert PauseReason("GOVERNANCE_INCIDENT") is PauseReason.GOVERNANCE_INCIDENT


def test_iteration_is_deterministic() -> None:
    assert list(PauseReason) == [
        PauseReason.AWAITING_DESIGN_REVIEW,
        PauseReason.AWAITING_DESIGN_CHALLENGE,
        PauseReason.GOVERNANCE_INCIDENT,
        PauseReason.AWAITING_EDGE_PROVISIONING,
    ]


def test_str_enum_invariants() -> None:
    assert PauseReason.AWAITING_DESIGN_REVIEW.value == "AWAITING_DESIGN_REVIEW"
    assert isinstance(PauseReason.AWAITING_DESIGN_REVIEW, str)


def test_unknown_value_rejected() -> None:
    """PauseReason ist eine geschlossene Werteliste."""
    for raw in ("foo", "PENDING", "BLOCKED", ""):
        with pytest.raises(ValueError):
            PauseReason(raw)


# ---------------------------------------------------------------------------
# from_yield_status — Mapping-Tabelle aus AG3-021 §2.1.4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("awaiting_design_review", PauseReason.AWAITING_DESIGN_REVIEW),
        ("design_review_pending", PauseReason.AWAITING_DESIGN_REVIEW),
        ("design_review", PauseReason.AWAITING_DESIGN_REVIEW),
        ("awaiting_design_challenge", PauseReason.AWAITING_DESIGN_CHALLENGE),
        ("design_challenge", PauseReason.AWAITING_DESIGN_CHALLENGE),
        ("design_challenge_pending", PauseReason.AWAITING_DESIGN_CHALLENGE),
        ("governance_incident", PauseReason.GOVERNANCE_INCIDENT),
        ("governance_pause", PauseReason.GOVERNANCE_INCIDENT),
        ("governance_intervention", PauseReason.GOVERNANCE_INCIDENT),
    ],
)
def test_from_yield_status_synonyms(raw: str, expected: PauseReason) -> None:
    """Synonym-Tabelle aus AG3-021 §2.1.4 wird zeilenweise verifiziert."""
    assert PauseReason.from_yield_status(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AWAITING_DESIGN_REVIEW", PauseReason.AWAITING_DESIGN_REVIEW),
        ("Awaiting_Design_Review", PauseReason.AWAITING_DESIGN_REVIEW),
        ("AWAITING_DESIGN_CHALLENGE", PauseReason.AWAITING_DESIGN_CHALLENGE),
        ("GOVERNANCE_INCIDENT", PauseReason.GOVERNANCE_INCIDENT),
    ],
)
def test_from_yield_status_canonical_wire_value(
    raw: str, expected: PauseReason,
) -> None:
    """Der normierte Wire-Wert wird unabhaengig vom Casing akzeptiert."""
    assert PauseReason.from_yield_status(raw) is expected


def test_from_yield_status_case_insensitive_synonyms() -> None:
    """Synonyme werden case-insensitive gemappt."""
    assert (
        PauseReason.from_yield_status("Awaiting_Design_Challenge")
        is PauseReason.AWAITING_DESIGN_CHALLENGE
    )
    assert (
        PauseReason.from_yield_status("  governance_incident  ")
        is PauseReason.GOVERNANCE_INCIDENT
    )


def test_from_yield_status_empty_string_raises() -> None:
    with pytest.raises(ValueError):
        PauseReason.from_yield_status("")


def test_from_yield_status_whitespace_only_raises() -> None:
    with pytest.raises(ValueError):
        PauseReason.from_yield_status("   ")


def test_from_yield_status_unknown_value_raises() -> None:
    """Jeder andere String wirft ValueError (fail-closed; kein Default)."""
    for raw in ("foo", "approved", "blocked", "DESIGN_OK", "Awaiting"):
        with pytest.raises(ValueError):
            PauseReason.from_yield_status(raw)
