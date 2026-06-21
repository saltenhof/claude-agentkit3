"""Contract: the central Postgres schema resolver (AG3-051 §2.1.2, AK3).

The resolver is the single source of truth for the Postgres schema name. In
production it returns the versioned ``ak3_v<slug>`` unchanged; a test override is
honored ONLY fail-closed (gate active AND name in the reserved ``ak3test_``
namespace). Any other combination raises ``RuntimeError``.
"""

from __future__ import annotations

import pytest

from agentkit.backend.state_backend.config import (
    SCHEMA_OVERRIDE_ALLOWED_ENV,
    SCHEMA_OVERRIDE_ENV,
    resolve_schema_name,
    versioned_postgres_schema_name,
)


@pytest.mark.contract
def test_no_override_returns_versioned_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an override the resolver returns ``ak3_v<slug>`` unchanged."""
    monkeypatch.delenv(SCHEMA_OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(SCHEMA_OVERRIDE_ALLOWED_ENV, raising=False)

    resolved = resolve_schema_name()

    assert resolved == versioned_postgres_schema_name()
    assert resolved.startswith("ak3_v")


@pytest.mark.contract
def test_override_without_gate_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override set but the gate inactive is fail-closed (RuntimeError)."""
    monkeypatch.setenv(SCHEMA_OVERRIDE_ENV, "ak3test_demo")
    monkeypatch.delenv(SCHEMA_OVERRIDE_ALLOWED_ENV, raising=False)

    with pytest.raises(RuntimeError, match=SCHEMA_OVERRIDE_ALLOWED_ENV):
        resolve_schema_name()


@pytest.mark.contract
def test_override_with_gate_but_bad_pattern_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate active but the name outside ``^ak3test_[a-z0-9_]+$`` is fail-closed."""
    monkeypatch.setenv(SCHEMA_OVERRIDE_ENV, "ak3_v3_14_0")
    monkeypatch.setenv(SCHEMA_OVERRIDE_ALLOWED_ENV, "1")

    with pytest.raises(RuntimeError, match="ak3test_"):
        resolve_schema_name()


@pytest.mark.contract
def test_valid_override_with_gate_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reserved-namespace override under an active gate is returned verbatim."""
    monkeypatch.setenv(SCHEMA_OVERRIDE_ENV, "ak3test_run_abc_gw0")
    monkeypatch.setenv(SCHEMA_OVERRIDE_ALLOWED_ENV, "1")

    assert resolve_schema_name() == "ak3test_run_abc_gw0"


@pytest.mark.contract
def test_uppercase_override_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reserved namespace is lowercase-only; uppercase is fail-closed."""
    monkeypatch.setenv(SCHEMA_OVERRIDE_ENV, "ak3test_BadCase")
    monkeypatch.setenv(SCHEMA_OVERRIDE_ALLOWED_ENV, "1")

    with pytest.raises(RuntimeError, match="ak3test_"):
        resolve_schema_name()
