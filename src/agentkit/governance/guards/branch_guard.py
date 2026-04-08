"""Branch guard -- prevents dangerous git operations.

Blocks force-push, hard-reset, direct pushes to main/master, and
force-deletion of branches.  Always active -- does not require
story execution context.
"""

from __future__ import annotations

from agentkit.governance.protocols import GuardVerdict, ViolationType


class BranchGuard:
    """Blocks dangerous git operations on protected branches.

    Evaluates ``bash_command`` operations for patterns known to be
    destructive (force-push, hard-reset, force-delete) and for direct
    pushes targeting protected branch names.

    This guard is stateless and always active -- it does not depend on
    story execution context.
    """

    DANGEROUS_PATTERNS: tuple[str, ...] = (
        "push --force",
        "push -f ",
        "reset --hard",
        "branch -D",
        "branch --delete --force",
    )
    """Command substrings that indicate a dangerous git operation."""

    PROTECTED_BRANCHES: tuple[str, ...] = ("main", "master", "develop")
    """Branch names that must not receive direct pushes."""

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "branch_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block dangerous git operations.

        Only inspects ``bash_command`` operations; all others are allowed
        unconditionally.

        Args:
            operation: The operation type being attempted.
            context: Must contain ``"command"`` for ``bash_command`` ops.

        Returns:
            ``ALLOW`` for safe operations, ``BLOCK`` for dangerous ones.
        """
        if operation != "bash_command":
            return GuardVerdict.ALLOW(self.name)

        command = str(context.get("command", ""))

        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in command:
                return GuardVerdict.BLOCK(
                    self.name,
                    ViolationType.BRANCH_VIOLATION,
                    f"Dangerous git operation detected: {pattern!r}",
                    detail={"command": command, "pattern": pattern},
                )

        # Check for direct push to protected branches
        if "push" in command:
            for branch in self.PROTECTED_BRANCHES:
                # Match patterns like "push origin main", "push origin/main",
                # or trailing branch name at end of command.
                if (
                    f"push origin {branch}" in command
                    or f"push origin/{branch}" in command
                    or command.rstrip().endswith(f" {branch}")
                ):
                    return GuardVerdict.BLOCK(
                        self.name,
                        ViolationType.BRANCH_VIOLATION,
                        f"Direct push to protected branch {branch!r} is forbidden",
                        detail={"command": command, "branch": branch},
                    )

        return GuardVerdict.ALLOW(self.name)
