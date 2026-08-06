"""Filesystem-link regressions for destructive path ownership decisions."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentkit.backend.boundary.filesystem import (
    AK3_OWNER_POLICIES,
    is_filesystem_link,
    matches_resolved_interpreter_owner,
    matches_resolved_path_owner,
)
from agentkit.backend.core_types.mcp_server_registration import (
    AK3_INTERPRETER_COMMAND,
    AK3_WRAPPER_COMMAND,
    Ak3ServerShape,
)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (AK3_INTERPRETER_COMMAND, matches_resolved_interpreter_owner),
        (AK3_WRAPPER_COMMAND, matches_resolved_path_owner),
        # Fail-closed default: a sentinel this method has never been taught
        # about gets the STRICTER policy, not the wider one and not an error
        # that would push the choice back onto the caller.
        ("<some-future-absolute-command>", matches_resolved_path_owner),
        ("/usr/bin/literal-command", matches_resolved_path_owner),
    ],
)
def test_owner_matcher_selects_the_policy_from_the_command_sentinel(
    command: str,
    expected: object,
) -> None:
    """The single decision point maps sentinel -> link policy, strict by default."""
    shape = Ak3ServerShape(command=command, args=(), env_keys=frozenset())

    assert shape.owner_matcher(AK3_OWNER_POLICIES) is expected


def test_owner_policies_expose_exactly_the_two_boundary_link_policies() -> None:
    """The wiring exists once and binds the boundary's own implementations."""
    assert AK3_OWNER_POLICIES.link_free is matches_resolved_path_owner
    assert AK3_OWNER_POLICIES.posix_venv_interpreter is (
        matches_resolved_interpreter_owner
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
