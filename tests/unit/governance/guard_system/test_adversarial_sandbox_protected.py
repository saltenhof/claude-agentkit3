"""Unit tests: adversarial sandbox is a Protected-Path (AG3-044 / AG3-023)."""

from __future__ import annotations

from agentkit.governance.guard_system.protected_paths import (
    PROTECTED_ADVERSARIAL_SANDBOX_PREFIX,
    is_adversarial_sandbox_path,
)


def test_sandbox_prefix_is_temp_adversarial() -> None:
    """The protected prefix is ``_temp/adversarial/`` (FK-48 §48.1)."""
    assert PROTECTED_ADVERSARIAL_SANDBOX_PREFIX == "_temp/adversarial/"


def test_sandbox_paths_are_protected() -> None:
    """Paths under the sandbox prefix are recognised as protected."""
    assert is_adversarial_sandbox_path("_temp/adversarial/AG3-044/1")
    assert is_adversarial_sandbox_path("_temp/adversarial/AG3-044/1/test_x.py")
    # Windows-style separators normalise to the same protected verdict.
    assert is_adversarial_sandbox_path("_temp\\adversarial\\AG3-044\\1")
    # Leading ./ is tolerated.
    assert is_adversarial_sandbox_path("./_temp/adversarial/AG3-044/1")


def test_non_sandbox_paths_are_not_protected() -> None:
    """Unrelated paths are NOT classified as the protected sandbox (fail-closed)."""
    assert not is_adversarial_sandbox_path("_temp/qa/AG3-044/handover.json")
    assert not is_adversarial_sandbox_path("src/agentkit/x.py")
    assert not is_adversarial_sandbox_path("_temp/adversarialish/x")
