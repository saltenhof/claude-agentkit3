"""Regression guards for the public authentication error contract."""

from __future__ import annotations

from agentkit.backend.auth import errors


def test_removed_http_bootstrap_origin_error_has_no_contract_residue() -> None:
    """The removed HTTP bootstrap route must not retain a dead error type."""
    assert not hasattr(errors, "BootstrapOriginError")

