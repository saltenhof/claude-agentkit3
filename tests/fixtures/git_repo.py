"""Shared test helper: provision a real git repo for installer unit tests.

CP 11 (FK-50 §50.3) runs ``git config core.hooksPath tools/hooks/`` against the
target project. Real AgentKit target projects ARE git repositories — you install
into a repo — so the unit tests that drive a full ``register``/``install`` must
provision a real repo at the project root, exactly like production.

Why this exists (CI regression, Jenkins #312): the failing tests previously ran
the install against a bare ``tmp_path`` that was never ``git init``-ed. They only
passed on the Windows dev host because the pytest temproot sits INSIDE the
AgentKit repo, so ``git config`` walked up and (accidentally) wrote to the
AgentKit repo's own config. On a clean Linux CI agent ``tmp_path`` is
``/tmp/pytest-of-jenkins/...`` — not inside any repo — so ``git config`` failed
with ``fatal: not in a git directory`` and CP 11 hard-aborted the install.

This helper makes the test setup faithful to real usage AND robust on a clean CI
agent: it initialises a real repo and hardens the git environment
(``safe.directory``, ``HOME``/``GIT_CONFIG`` writability, deterministic identity)
so ``git config`` works regardless of the agent's ambient git state, uid mismatch
("dubious ownership") or an unset ``HOME``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ensure_git_repo"]


def ensure_git_repo(project_root: Path) -> None:
    """Initialise ``project_root`` as a git work tree CP 11 can configure.

    Idempotent: re-initialising an existing repo is a no-op for git. Hardens the
    repo against CI-only failures (dubious-ownership refusal, unset ``HOME``) by
    marking the path as a ``safe.directory`` in a repo-local config write.

    Args:
        project_root: Directory that the installer treats as the target project
            root. Created if it does not yet exist.

    Raises:
        RuntimeError: If ``git init`` fails (git missing / unwritable path) —
            fail-closed, because the test cannot faithfully exercise CP 11
            without a real repo.
    """
    project_root.mkdir(parents=True, exist_ok=True)
    init = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
        ["git", "init", "--quiet", str(project_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if init.returncode != 0:
        msg = f"test setup: git init failed for {project_root}: {init.stderr.strip()}"
        raise RuntimeError(msg)
    # Repo-local identity + safe.directory: a clean CI agent may run pytest under
    # a uid that differs from the workspace owner ("detected dubious ownership")
    # or with an unset HOME (no global config to fall back to). A repo-local
    # config write resolves both — it never touches the developer's global git.
    for argv in (
        ["config", "--local", "user.email", "ci@agentkit.test"],
        ["config", "--local", "user.name", "AgentKit CI"],
        ["config", "--local", "safe.directory", str(project_root)],
    ):
        subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
            ["git", "-C", str(project_root), *argv],
            capture_output=True,
            text=True,
            check=False,
        )
