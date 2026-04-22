"""Project-local hook runtime for mode-aware guard evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from agentkit.governance.guards.artifact_guard import ArtifactGuard
from agentkit.governance.guards.branch_guard import BranchGuard
from agentkit.governance.guards.scope_guard import ScopeGuard
from agentkit.governance.protocols import (
    GovernanceGuard,
    GuardVerdict,
    ViolationType,
)
from agentkit.governance.runner import GuardRunner
from agentkit.installer.paths import qa_story_dir
from agentkit.projectedge.runtime import (
    FreshnessClass,
    ProjectEdgeResolver,
    ResolvedEdgeState,
)

_MUTATING_TOOLS = frozenset({"Bash", "Edit", "Write"})
_READ_ONLY_TOOLS = frozenset({"Glob", "Grep", "Read"})


class HookEvent(BaseModel):
    """Minimal normalized hook event consumed by the guard runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    tool_input: dict[str, object] = {}
    cwd: str = ""
    session_id: str | None = None
    is_subagent: bool = False

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, value: object) -> object:
        if isinstance(value, dict) and "cwd" not in value:
            updated = dict(value)
            updated["cwd"] = str(Path.cwd())
            return updated
        return value

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        if not value:
            raise ValueError("tool_name must be a non-empty string")
        return value

    @field_validator("cwd", mode="before")
    @classmethod
    def _default_cwd(cls, value: object) -> str:
        if isinstance(value, str) and value:
            return value
        return str(Path.cwd())

    @field_validator("session_id", mode="before")
    @classmethod
    def _coerce_session_id(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None


def main(argv: list[str] | None = None) -> int:
    """Read one hook event from stdin, evaluate, and exit with hook code."""
    del argv
    raw = sys.stdin.read()
    event = _parse_hook_event(raw)
    decision = evaluate_pre_tool_use(event, project_root=Path.cwd())
    if not decision.allowed:
        payload = {
            "decision": "block",
            "guard": decision.guard_name,
            "message": decision.message,
            "detail": decision.detail,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    return 0


def evaluate_pre_tool_use(event: HookEvent, *, project_root: Path) -> GuardVerdict:
    """Evaluate one normalized hook event against mode-aware guards."""
    operation, context, freshness_class = _normalize_event(event)
    resolver = ProjectEdgeResolver(project_root=project_root)
    resolved = resolver.resolve(
        session_id=event.session_id,
        cwd=event.cwd,
        freshness_class=freshness_class,
    )
    context.update(_guard_context(event, resolved))

    if (
        resolved.operating_mode == "binding_invalid"
        and event.tool_name in _MUTATING_TOOLS
    ):
        return GuardVerdict.block(
            "operating_mode_guard",
            ViolationType.POLICY_VIOLATION,
            "Mutating operation blocked because the local story binding is invalid",
            detail={"reason": resolved.block_reason},
        )

    runner = GuardRunner(guards=_guards_for_state(resolved, project_root=project_root))
    allowed, verdicts = runner.is_allowed(operation, context)
    if allowed:
        return GuardVerdict.allow("hook_runtime")
    for verdict in verdicts:
        if not verdict.allowed:
            return verdict
    return GuardVerdict.allow("hook_runtime")


def _parse_hook_event(raw: str) -> HookEvent:
    try:
        return HookEvent.model_validate_json(raw)
    except ValidationError as exc:
        message = str(exc)
        if "tool_input" in message and "object" in message:
            raise RuntimeError("tool_input must be a JSON object") from exc
        if "Input should be an object" in message:
            raise RuntimeError("Hook payload must be a JSON object") from exc
        raise RuntimeError(str(exc)) from exc


def _normalize_event(
    event: HookEvent,
) -> tuple[str, dict[str, object], FreshnessClass]:
    if event.tool_name == "Bash":
        return (
            "bash_command",
            {"command": str(event.tool_input.get("command", ""))},
            "mutation",
        )
    if event.tool_name == "Write":
        return (
            "file_write",
            {"file_path": str(event.tool_input.get("file_path", ""))},
            "mutation",
        )
    if event.tool_name == "Edit":
        return (
            "file_edit",
            {"file_path": str(event.tool_input.get("file_path", ""))},
            "mutation",
        )
    if event.tool_name in _READ_ONLY_TOOLS:
        return (
            "file_read",
            {"file_path": str(event.tool_input.get("file_path", ""))},
            "baseline_read",
        )
    return ("unknown_tool", {}, "guarded_read")


def _guard_context(
    event: HookEvent,
    resolved: ResolvedEdgeState,
) -> dict[str, object]:
    story_id = ""
    principal_type = ""
    qa_lock_active = False
    qa_lock_known = False
    if resolved.bundle is not None and resolved.bundle.session is not None:
        story_id = resolved.bundle.session.story_id
        principal_type = resolved.bundle.session.principal_type
        qa_lock_known = resolved.bundle.qa_lock is not None
        qa_lock_active = (
            resolved.bundle.qa_lock is not None
            and resolved.bundle.qa_lock.status == "ACTIVE"
        )
    return {
        "operating_mode": resolved.operating_mode,
        "is_subagent": event.is_subagent,
        "active_story_id": story_id,
        "principal_type": principal_type,
        "qa_artifact_lock_known": qa_lock_known,
        "qa_artifact_lock_active": qa_lock_active,
    }


def _guards_for_state(
    resolved: ResolvedEdgeState,
    *,
    project_root: Path,
) -> list[GovernanceGuard]:
    guards: list[GovernanceGuard] = [BranchGuard()]
    if (
        resolved.operating_mode == "story_execution"
        and resolved.bundle is not None
        and resolved.bundle.session is not None
    ):
        allowed_paths = list(resolved.bundle.session.worktree_roots)
        allowed_paths.append(
            str(qa_story_dir(project_root, resolved.bundle.session.story_id)),
        )
        guards.append(
            ScopeGuard(allowed_paths=allowed_paths),
        )
        guards.append(ArtifactGuard())
    return guards


__all__ = [
    "HookEvent",
    "evaluate_pre_tool_use",
    "main",
]
