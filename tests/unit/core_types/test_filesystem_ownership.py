"""Filesystem-link regressions for destructive path ownership decisions."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentkit.backend.boundary.filesystem import (
    is_filesystem_link,
    matches_resolved_path_owner,
)


def test_link_primitive_recognises_a_simulated_windows_junction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Path.is_symlink() is False`` must not hide a Windows junction."""
    junction = tmp_path / "junction"
    junction.mkdir()
    real_isjunction = os.path.isjunction
    monkeypatch.setattr(
        os.path,
        "isjunction",
        lambda path: Path(path) == junction or real_isjunction(path),
    )

    assert not junction.is_symlink()
    assert is_filesystem_link(junction)


@pytest.mark.parametrize("link_side", ["candidate", "owner"])
def test_owner_match_rejects_junction_ancestor_before_dotdot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_side: str,
) -> None:
    """A junction cannot disappear behind lexical normalisation on either side."""
    project = tmp_path / "project"
    hooks = project / ".agentkit" / "hooks"
    hooks.mkdir(parents=True)
    pivot = project / "pivot"
    alias = pivot / ".." / ".agentkit" / "hooks"
    candidate = alias / "audit.py" if link_side == "candidate" else hooks / "audit.py"
    owner = hooks if link_side == "candidate" else alias
    real_isjunction = os.path.isjunction
    monkeypatch.setattr(
        os.path,
        "isjunction",
        lambda path: Path(path) == pivot or real_isjunction(path),
    )

    assert not matches_resolved_path_owner(
        str(candidate),
        str(owner),
        allow_descendants=True,
    )


@pytest.mark.skipif(
    os.name != "nt" or not os.path.isjunction(Path("C:/Documents and Settings")),
    reason="the real Windows compatibility junction is unavailable",
)
def test_real_windows_junction_never_grants_descendant_ownership() -> None:
    """Pin the destructive reviewer counterexample against a real reparse point."""
    hooks = Path(
        "C:/Documents and Settings/ForeignProject/.agentkit/hooks"
    )
    candidate = hooks / "audit.py"

    assert not matches_resolved_path_owner(
        str(candidate),
        str(hooks),
        allow_descendants=True,
    )
