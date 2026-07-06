"""CommitHook: emit ``increment_commit`` on worker commit-producing git commands.

FK-68 §68.2.2 (Worker-Lifecycle) / §68.3.1: a harness hook observes a Bash
git command that creates commits in the worktree and emits an
``increment_commit`` event.

Mandatory payload fields (AG3-036 AC3): ``commit_sha``, ``repo_name``,
``story_id``, ``worker_id``, ``files_changed``. The DriftCheckHook (§2.1.7) is a
separate hook also triggered by the increment commit; this hook only emits the
commit event.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
)

if TYPE_CHECKING:
    from agentkit.backend.telemetry.emitters import EventEmitter

#: Recognises git invocations that can create local commits.
_GIT_COMMIT_PRODUCING_PATTERN = re.compile(r"\bgit\s+(?:commit|cherry-pick|revert|merge|rebase)\b")
_GIT_COMMIT_PATTERN = _GIT_COMMIT_PRODUCING_PATTERN


class CommitHook(EmittingHook):
    """Emits ``increment_commit`` on worker commit-producing git commands."""

    name = "commit_hook"

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise with the canonical event emitter.

        Args:
            emitter: Telemetry emitter for persistence (FK-68 §68.3.4).
        """
        super().__init__(emitter)

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``increment_commit`` when a commit-producing Bash git command runs.

        Trigger (FK-68 §68.2.2): a Bash tool call whose command can create
        commits in the worktree.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying the ``increment_commit`` event, or a
            skipped result when the command is not commit-producing.
        """
        if not self._is_git_commit(context):
            return HookResult.skipped()

        payload: dict[str, object] = {
            "commit_sha": str(context.payload.get("commit_sha", "")),
            "repo_name": str(context.payload.get("repo_name", "")),
            "story_id": context.story_id,
            "worker_id": context.worker_id or "",
            "files_changed": _coerce_files_changed(context.payload.get("files_changed")),
        }
        event = Event(
            story_id=context.story_id,
            event_type=EventType.INCREMENT_COMMIT,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            payload=payload,
        )
        return HookResult.emitting((event,))

    @staticmethod
    def _is_git_commit(context: HookContext) -> bool:
        return (
            context.trigger in (HookTrigger.PRE_TOOL_USE, HookTrigger.POST_TOOL_USE)
            and context.tool == "Bash"
            and bool(_GIT_COMMIT_PRODUCING_PATTERN.search(context.command))
        )


def _coerce_files_changed(value: object) -> int:
    """Coerce a payload ``files_changed`` value to a non-negative int.

    Args:
        value: Raw payload value (int, numeric str, or anything else).

    Returns:
        The integer file count, or ``0`` when not derivable.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value >= 0 else 0
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


__all__ = ["CommitHook"]
