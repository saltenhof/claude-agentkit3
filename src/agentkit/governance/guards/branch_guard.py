"""Branch guard -- prevents dangerous git operations and git internals writes."""

from __future__ import annotations

import os
import shlex

from agentkit.governance.protocols import GuardVerdict, ViolationType


class BranchGuard:
    """Blocks dangerous git operations and story-execution branch escapes."""

    DANGEROUS_PATTERNS: tuple[str, ...] = (
        "push --force",
        "push -f ",
        "push --force-with-lease",
        "reset --hard",
        "branch -D",
        "branch --delete --force",
    )
    STORY_PROTECTED_BRANCHES: tuple[str, ...] = ("main", "master")
    _OFFICIAL_ALLOW_PREFIXES: tuple[str, ...] = (
        "agentkit run-phase closure",
        "agentkit reset-story",
        "agentkit split-story",
    )
    _GIT_INTERNAL_SEGMENTS: tuple[str, ...] = (
        ".git",
        ".git/refs",
        ".git/index",
        ".git/worktrees",
    )
    _GIT_MUTATION_COMMANDS: tuple[str, ...] = (
        "rm ",
        "del ",
        "remove-item",
        "move-item",
        "set-content",
        "out-file",
        "copy-item",
        "new-item",
    )

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "branch_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block dangerous git operations and git-internal mutations."""
        if operation in ("file_write", "file_edit"):
            return self._evaluate_file_mutation(context)
        if operation != "bash_command":
            return GuardVerdict.allow(self.name)

        command = str(context.get("command", ""))
        operating_mode = str(context.get("operating_mode", "ai_augmented"))
        active_story_id = str(context.get("active_story_id", ""))

        if self._is_official_allow_path(command):
            return GuardVerdict.allow(self.name)

        if self._mutates_git_internals_via_bash(command):
            return GuardVerdict.block(
                self.name,
                ViolationType.BRANCH_VIOLATION,
                "Bash mutation of git internals is forbidden",
                detail={"command": command},
            )

        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in command:
                return GuardVerdict.block(
                    self.name,
                    ViolationType.BRANCH_VIOLATION,
                    f"Dangerous git operation detected: {pattern!r}",
                    detail={"command": command, "pattern": pattern},
                )

        if operating_mode != "story_execution":
            return GuardVerdict.allow(self.name)

        disallowed_branch = self._story_execution_branch_violation(
            command,
            active_story_id,
        )
        if disallowed_branch is not None:
            return GuardVerdict.block(
                self.name,
                ViolationType.BRANCH_VIOLATION,
                f"Story execution may not target branch {disallowed_branch!r}",
                detail={"command": command, "branch": disallowed_branch},
            )

        return GuardVerdict.allow(self.name)

    def _evaluate_file_mutation(
        self,
        context: dict[str, object],
    ) -> GuardVerdict:
        file_path = os.path.normpath(str(context.get("file_path", "")))
        if not file_path:
            return GuardVerdict.allow(self.name)

        normalized = file_path.replace("\\", "/")
        for segment in self._GIT_INTERNAL_SEGMENTS:
            if f"/{segment}/" in f"/{normalized}/" or normalized.endswith(segment):
                return GuardVerdict.block(
                    self.name,
                    ViolationType.BRANCH_VIOLATION,
                    "Mutation of git internals is forbidden",
                    detail={"file_path": file_path},
                )
        return GuardVerdict.allow(self.name)

    def _is_official_allow_path(self, command: str) -> bool:
        stripped = command.strip()
        return any(
            stripped.startswith(prefix) for prefix in self._OFFICIAL_ALLOW_PREFIXES
        )

    def _story_execution_branch_violation(
        self,
        command: str,
        active_story_id: str,
    ) -> str | None:
        target_branch = self._target_branch(command)
        if target_branch is None:
            return None
        allowed_branch = f"story/{active_story_id}" if active_story_id else ""
        if target_branch in self.STORY_PROTECTED_BRANCHES:
            return target_branch
        if allowed_branch and target_branch != allowed_branch:
            return target_branch
        return None

    def _target_branch(self, command: str) -> str | None:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        if len(tokens) < 3 or tokens[0] != "git":
            return None
        if tokens[1] in {"checkout", "switch"}:
            if "--" in tokens:
                return None
            target = tokens[-1]
            return self._normalize_branch_token(target)
        if tokens[1] == "push":
            if tokens[-1].startswith("-"):
                return None
            target = tokens[-1]
            return self._normalize_branch_token(target)
        if tokens[1] == "rebase":
            return self._normalize_branch_token(tokens[-1])
        return None

    def _normalize_branch_token(self, token: str) -> str:
        if token.startswith("origin/"):
            return token.removeprefix("origin/")
        if ":" in token:
            return token.split(":", maxsplit=1)[-1]
        return token

    def _mutates_git_internals_via_bash(self, command: str) -> bool:
        normalized = command.lower().replace("\\", "/")
        if ".git/" not in normalized and ".git " not in normalized:
            return False
        return any(marker in normalized for marker in self._GIT_MUTATION_COMMANDS)
