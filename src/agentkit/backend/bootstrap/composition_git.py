"""Git adapter for non-closure composition paths."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from agentkit.backend.closure.multi_repo_saga import GitCommandResult

if TYPE_CHECKING:
    from agentkit.backend.closure.multi_repo_saga import ClosureRepo


class CompositionSubprocessGitBackend:
    """Supply system Git evidence to implementation/structural composition."""

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        """Run one bounded Git command for a non-closure evidence consumer."""
        result = subprocess.run(
            ["git", "-C", str(repo.command_cwd), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return GitCommandResult(result.returncode, result.stdout, result.stderr)
