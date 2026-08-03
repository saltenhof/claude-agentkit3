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
        # Strict UTF-8: this reads AK3's OWN repositories, and the values it
        # returns -- SHA, branch, tree hash -- travel on into URLs and JSON. A
        # value that is not decodable is a protocol violation and fails closed
        # here; carried through losslessly it would raise in `urlencode`,
        # arriving without a cause.
        try:
            result = subprocess.run(
                ["git", "-C", str(repo.command_cwd), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except UnicodeDecodeError as exc:
            return GitCommandResult(1, "", f"git output is not UTF-8: {exc}")
        return GitCommandResult(result.returncode, result.stdout, result.stderr)
