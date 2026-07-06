"""CommitHook: emit ``increment_commit`` on observed worker HEAD movement.

FK-68 §68.2.2 (Worker-Lifecycle) / §68.3.1: a harness hook observes a Bash
tool call that created a commit in the worktree and emits an ``increment_commit``
event.

Mandatory payload fields (AG3-036 AC3): ``commit_sha``, ``repo_name``,
``story_id``, ``worker_id``, ``files_changed``. The DriftCheckHook (§2.1.7) is a
separate hook also triggered by the increment commit; this hook only emits the
commit event.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
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

_COMMIT_CREATING_GIT_COMMANDS = frozenset(
    {"am", "cherry-pick", "commit", "merge", "pull", "rebase", "revert"}
)
_GIT_OPTIONS_WITH_VALUE = frozenset(
    {
        "-C",
        "-c",
        "--config-env",
        "--exec-path",
        "--git-dir",
        "--namespace",
        "--work-tree",
    }
)
_GIT_OPTIONS_WITH_VALUE_PREFIXES = tuple(
    f"{option}=" for option in _GIT_OPTIONS_WITH_VALUE if option.startswith("--")
)


@dataclass(frozen=True)
class _HeadSnapshot:
    repo_root: Path
    repo_name: str
    head_sha: str


class CommitHook(EmittingHook):
    """Emits ``increment_commit`` when a worker command advances repository HEAD."""

    name = "commit_hook"

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise with the canonical event emitter.

        Args:
            emitter: Telemetry emitter for persistence (FK-68 §68.3.4).
        """
        super().__init__(emitter)
        self._pre_tool_heads: dict[tuple[str, str, str], _HeadSnapshot] = {}

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``increment_commit`` when a Bash tool call advanced repository HEAD.

        Trigger (FK-68 §68.2.2): a Bash tool call with explicit commit facts in
        its payload, or a PRE/POST HEAD delta observed for the repository. This
        is intentionally independent of the command text so git aliases,
        wrappers and non-``git commit`` commit paths still invalidate barriers.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying the ``increment_commit`` event, or a
            skipped result when no commit fact is observed.
        """
        if not _is_bash_tool(context):
            return HookResult.skipped()
        if context.trigger is HookTrigger.PRE_TOOL_USE:
            snapshot = _head_snapshot_from_context(context)
            if snapshot is not None:
                self._pre_tool_heads[_snapshot_key(context, snapshot.repo_root)] = snapshot
            return HookResult.skipped()
        if context.trigger is not HookTrigger.POST_TOOL_USE:
            return HookResult.skipped()
        commit_sha, repo_name = self._commit_fact(context)
        if not commit_sha:
            return HookResult.skipped()

        payload: dict[str, object] = {
            "commit_sha": commit_sha,
            "repo_name": repo_name,
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

    def _commit_fact(self, context: HookContext) -> tuple[str, str]:
        direct = _payload_commit_fact(context)
        if direct is not None:
            return direct
        current = _head_snapshot_from_context(context)
        if current is None:
            return "", ""
        before = self._pre_tool_heads.pop(_snapshot_key(context, current.repo_root), None)
        if before is None or before.head_sha == current.head_sha:
            return "", ""
        return current.head_sha, current.repo_name


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


__all__ = ["CommitHook", "command_may_create_commit", "context_has_commit_fact"]


def _is_bash_tool(context: HookContext) -> bool:
    return context.tool == "Bash"


def context_has_commit_fact(context: HookContext) -> bool:
    """Return whether the harness supplied a productive commit fact."""

    return _payload_commit_fact(context) is not None


def command_may_create_commit(command: str) -> bool:
    """Return whether a Bash command is a direct git commit-producing command.

    This helper is for PRE hooks that must decide before HEAD can change. The
    post-commit invalidation path does not depend on it.
    """

    try:
        parts = tuple(
            _clean_command_part(part)
            for part in shlex.split(command, posix=False)
        )
    except ValueError:
        return False
    if not parts or Path(parts[0]).name != "git":
        return False
    idx = 1
    while idx < len(parts):
        part = parts[idx]
        if part in _GIT_OPTIONS_WITH_VALUE:
            idx += 2
            continue
        if any(part.startswith(prefix) for prefix in _GIT_OPTIONS_WITH_VALUE_PREFIXES):
            idx += 1
            continue
        if part.startswith("-"):
            idx += 1
            continue
        return part in _COMMIT_CREATING_GIT_COMMANDS
    return False


def _payload_commit_fact(context: HookContext) -> tuple[str, str] | None:
    after = _first_payload_str(
        context,
        "head_after",
        "after_head_sha",
        "current_head_sha",
        "commit_sha",
    )
    if not after:
        return None
    before = _first_payload_str(context, "head_before", "before_head_sha", "previous_head_sha")
    if before and before == after:
        return None
    repo = _first_payload_str(context, "repo_name", "repo_id") or ""
    return after, repo


def _first_payload_str(context: HookContext, *keys: str) -> str:
    for key in keys:
        value = context.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _head_snapshot_from_context(context: HookContext) -> _HeadSnapshot | None:
    repo_hint = _repo_hint_from_context(context)
    if repo_hint is None:
        return None
    repo_root = _git_output(repo_hint, "rev-parse", "--show-toplevel")
    if not repo_root:
        return None
    root = Path(repo_root)
    head = _git_output(root, "rev-parse", "HEAD")
    if not head:
        return None
    repo_name = _first_payload_str(context, "repo_name", "repo_id") or root.name
    return _HeadSnapshot(repo_root=root, repo_name=repo_name, head_sha=head)


def _repo_hint_from_context(context: HookContext) -> Path | None:
    git_c = _git_dash_c_path(context.command)
    if git_c is not None:
        return git_c
    cwd = _first_payload_str(context, "cwd", "current_working_directory", "working_dir")
    return Path(cwd) if cwd else Path.cwd()


def _git_dash_c_path(command: str) -> Path | None:
    try:
        parts = tuple(_clean_command_part(part) for part in shlex.split(command, posix=False))
    except ValueError:
        return None
    if not parts or Path(parts[0]).name != "git":
        return None
    for idx, part in enumerate(parts):
        if part == "-C" and idx + 1 < len(parts):
            return Path(parts[idx + 1].strip('"'))
    return None


def _clean_command_part(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _git_output(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _snapshot_key(context: HookContext, repo_root: Path) -> tuple[str, str, str]:
    return (context.project_key, context.run_id, str(repo_root.resolve()))
