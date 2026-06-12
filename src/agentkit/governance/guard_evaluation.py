"""Harness-neutral guard evaluation for project-local governance hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
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
    read_change_frame_freeze_state,
)
from agentkit.story_context_manager.operating_mode_resolver import (
    resolve_operating_mode,
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
    # AG3-032 (FK-55 §55.3a): harness-context fields the PrincipalResolver reads
    # to attest the technical principal. NEVER prompt content. Default None; the
    # resolver then falls back to the context default principal. Deliberately a
    # minimal extension — no full HookEvent overhaul (AG3-032 §2.2).
    parent_session_id: str | None = None
    cli_args: list[str] | None = None
    principal_kind: PrincipalKind = "main"
    # Harness-neutral PostToolUse outcome payload. Harness-specific adapters own
    # filling it; the worker-health engine validates it against PostToolOutcome.
    post_tool_outcome: dict[str, object] | None = None

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

    @field_validator("session_id", "parent_session_id", mode="before")
    @classmethod
    def _coerce_session_id(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None

    @field_validator("cli_args", mode="before")
    @classmethod
    def _coerce_cli_args(cls, value: object) -> list[str] | None:
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(value)
        return None


def evaluate_pre_tool_use(event: HookEvent, *, project_root: Path) -> GuardVerdict:
    """Evaluate one harness-neutral pre-tool event against mode-aware guards."""
    operation, context, freshness_class = _normalize_event(event)
    resolver = ProjectEdgeResolver(project_root=project_root)
    resolved = resolver.resolve(
        session_id=event.session_id,
        cwd=event.cwd,
        freshness_class=freshness_class,
    )
    context.update(_guard_context(event, resolved, project_root=project_root))

    operating_mode = resolve_operating_mode(resolved)
    if operating_mode == "binding_invalid" and freshness_class == "mutation":
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
    *,
    project_root: Path,
) -> dict[str, object]:
    story_id = ""
    context_project_key = ""
    context_run_id = ""
    principal_type = ""
    qa_lock_active = False
    qa_lock_known = False
    if resolved.bundle is not None and resolved.bundle.session is not None:
        story_id = resolved.bundle.session.story_id
        context_project_key = resolved.bundle.session.project_key
        context_run_id = resolved.bundle.session.run_id
        principal_type = resolved.bundle.session.principal_type
        qa_lock_known = resolved.bundle.qa_lock is not None
        qa_lock_active = (
            resolved.bundle.qa_lock is not None
            and resolved.bundle.qa_lock.status == "ACTIVE"
        )
    context: dict[str, object] = {
        "operating_mode": resolve_operating_mode(resolved),
        "principal_kind": event.principal_kind,
        "active_story_id": story_id,
        "project_key": context_project_key if story_id else "",
        "run_id": context_run_id if story_id else "",
        "principal_type": principal_type,
        "qa_artifact_lock_known": qa_lock_known,
        "qa_artifact_lock_active": qa_lock_active,
    }
    context.update(
        _change_frame_freeze_signals(story_id, project_root=project_root)
    )
    return context


def _change_frame_freeze_signals(
    story_id: str,
    *,
    project_root: Path,
) -> dict[str, object]:
    """Resolve the persisted change-frame freeze signals (FK-23 §23.4.3, AG3-047).

    The ``ArtifactGuard`` keys the exploration change-frame protection on two
    guard-context signals (``change_frame_frozen`` / ``change_frame_freeze_known``).
    The productive guard-context builder feeds them from the PERSISTED
    ``_temp/qa/{story_id}/change_frame.json`` freeze state via the ``projectedge``
    R-boundary read (this A-core owns the path policy, the boundary owns the FS
    read). Fail-closed semantics (AG3-047):

    * no file yet OR an explicitly NOT-frozen file -> ``freeze_known=True`` +
      ``frozen=False`` (the legitimate pre-freeze editable draft is allowed,
      FK-25 §25.4.2);
    * a frozen file -> ``freeze_known=True`` + ``frozen=True`` (the write is
      blocked);
    * an UNREADABLE file (error, not absence) -> ``freeze_known`` is LEFT UNSET
      so the guard blocks fail-closed (the unknown freeze state is never read as
      "not frozen", ARCH-48 default deny).

    Args:
        story_id: The active story display id (empty outside story execution).
        project_root: The project root resolving ``_temp/qa/{story_id}/``.

    Returns:
        The freeze guard-context signals (possibly empty when no story scope or
        when the state is unreadable).
    """
    if not story_id:
        return {}
    change_frame_path = qa_story_dir(project_root, story_id) / CHANGE_FRAME_FILE
    state = read_change_frame_freeze_state(change_frame_path)
    if state == "unreadable":
        # Unknown freeze state -> leave freeze_known unset -> guard blocks.
        return {}
    return {
        "change_frame_freeze_known": True,
        "change_frame_frozen": state == "frozen",
    }


def _guards_for_state(
    resolved: ResolvedEdgeState,
    *,
    project_root: Path,
) -> list[GovernanceGuard]:
    guards: list[GovernanceGuard] = [BranchGuard()]
    if (
        resolve_operating_mode(resolved) == "story_execution"
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
