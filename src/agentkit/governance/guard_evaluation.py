"""Harness-neutral guard evaluation for project-local governance hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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

Operation = Literal[
    "bash_command",
    "file_write",
    "file_edit",
    "file_read",
    "unknown_tool",
]
PrincipalKind = Literal["main", "subagent"]


class HookEvent(BaseModel):
    """Harness-neutral event consumed by the guard evaluation core."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Operation
    operation_args: dict[str, object] = {}
    freshness_class: FreshnessClass
    cwd: str = ""
    session_id: str | None = None
    principal_kind: PrincipalKind = "main"

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, value: object) -> object:
        if isinstance(value, dict) and "cwd" not in value:
            updated = dict(value)
            updated["cwd"] = str(Path.cwd())
            return updated
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


def evaluate_pre_tool_use(event: HookEvent, *, project_root: Path) -> GuardVerdict:
    """Evaluate one harness-neutral pre-tool event against mode-aware guards."""
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
        and freshness_class == "mutation"
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
        return GuardVerdict.allow("guard_evaluation")
    for verdict in verdicts:
        if not verdict.allowed:
            return verdict
    return GuardVerdict.allow("guard_evaluation")


def _normalize_event(
    event: HookEvent,
) -> tuple[str, dict[str, object], FreshnessClass]:
    return event.operation, dict(event.operation_args), event.freshness_class


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
        "principal_kind": event.principal_kind,
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
]
