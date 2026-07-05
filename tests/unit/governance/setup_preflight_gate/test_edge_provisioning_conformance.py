"""Conformance: no backend worktree-git remains in the setup/preflight flow.

AG3-145 Teilschritt C (AC5/AC6, FK-10 §10.2.4a): after the setup-move there is
exactly ONE provisioning truth -- the edge-reported worktree paths. No backend
code path in the setup flow calls ``create_worktree`` / ``write_story_marker`` /
``setup_worktrees``, and no preflight path calls ``branch_exists`` (the git
show-ref probe was replaced by the edge ``preflight_probe`` + backend decision).
Grep-proof over the actual module sources (the story's required evidence).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SETUP_FLOW_MODULES = (
    "agentkit.backend.governance.setup_preflight_gate.phase",
    "agentkit.backend.governance.setup_preflight_gate.preflight",
    "agentkit.backend.governance.setup_preflight_gate.preflight_checks.no_story_branch",
    "agentkit.backend.governance.setup_preflight_gate.preflight_checks.no_stale_worktree",
)

#: Backend physical-worktree/git symbols that must no longer appear in the setup
#: flow (moved to the edge executor, AG3-145 Teilschritt B). ``create_worktree``
#: is deliberately NOT scanned as a bare string -- it collides with the
#: legitimate ``SetupConfig.create_worktree`` flag; the git PRIMITIVE it names
#: lives in ``agentkit.backend.utils.git``, whose import is asserted-absent below.
_FORBIDDEN_SYMBOLS = (
    "write_story_marker",
    "setup_worktrees",
    "branch_exists",
)


def _source_of(module_name: str) -> str:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, module_name
    return Path(spec.origin).read_text(encoding="utf-8")


@pytest.mark.parametrize("module_name", _SETUP_FLOW_MODULES)
def test_setup_flow_has_no_backend_worktree_git(module_name: str) -> None:
    source = _source_of(module_name)
    hits = [symbol for symbol in _FORBIDDEN_SYMBOLS if symbol in source]
    assert not hits, (
        f"{module_name} still references backend worktree-git symbols {hits}; "
        "provisioning is edge-commissioned in AG3-145 Teilschritt C."
    )
    # The backend git primitives (create_worktree / branch_exists /
    # remove_worktree) live in ``utils.git``; the setup flow must not import them.
    assert "agentkit.backend.utils.git" not in source, (
        f"{module_name} still imports the backend git primitives (utils.git); "
        "the setup flow does no physical worktree git (FK-10 §10.2.4a)."
    )


def test_backend_worktree_module_is_removed() -> None:
    # The backend worktree provisioning module was deleted (single provisioning
    # truth: the edge-reported paths).
    assert (
        importlib.util.find_spec(
            "agentkit.backend.governance.setup_preflight_gate.worktree"
        )
        is None
    )
