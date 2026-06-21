"""DriftCheckHook: emit ``drift_check`` after increment commits.

FK-68 §68.2.2 (Worker-Lifecycle) / §68.3.1: after an increment commit the worker
runs a drift check against the design artifact and a hook emits a ``drift_check``
event with ``drift_detected: bool`` (AG3-036 AC7).

FAIL-CLOSED (AG3-036 §2.1.7 / briefing): when the design artifact
``_temp/qa/{story_id}/entwurfsartefakt.json`` (FK-23 §23.4.3) is absent, the hook
emits a ``drift_check`` event with ``drift_detected=false`` and
``reason="no_design_artifact"`` -- NEVER a silent pass. The escalation logic
(self-correction / BLOCKED) is out of scope (THEME-009).

The design-artifact path is a data path (string), not a code import: the AC10
import boundary forbids importing ``agentkit.backend.installer.paths`` from a hook, so the
``_temp/qa`` layout is reproduced locally and pinned by a unit test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
)
from agentkit.backend.telemetry.hooks.commit_hook import _GIT_COMMIT_PATTERN

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.telemetry.emitters import EventEmitter

#: Design-artifact file name (FK-23 §23.4.3).
_DESIGN_ARTIFACT_FILENAME = "entwurfsartefakt.json"

#: Reason recorded when the design artifact is absent (fail-closed, never silent).
_REASON_NO_DESIGN_ARTIFACT = "no_design_artifact"


class DriftCheckHook(EmittingHook):
    """Emits ``drift_check`` after increment commits (FK-68 §68.2.2)."""

    name = "drift_check_hook"

    def __init__(self, emitter: EventEmitter, *, project_root: Path) -> None:
        """Initialise with the emitter and the project root.

        Args:
            emitter: Telemetry emitter for persistence (FK-68 §68.3.4).
            project_root: Project root used to locate the design artifact under
                ``_temp/qa/{story_id}/entwurfsartefakt.json``.
        """
        super().__init__(emitter)
        self._project_root = project_root

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``drift_check`` after an increment commit.

        Trigger (FK-68 §68.2.2): a PostToolUse Bash ``git commit`` (the
        increment commit). When the design artifact is absent the event is
        fail-closed (``drift_detected=false``, ``reason="no_design_artifact"``).
        Otherwise the precomputed drift result is read from the payload
        (``drift_detected``); drift computation against the artifact is owned by
        the worker marker command, this hook only emits the resulting fact.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying the ``drift_check`` event, or a
            skipped result when no increment commit is observed.
        """
        if not self._is_increment_commit(context):
            return HookResult.skipped()

        artifact_path = (
            self._project_root
            / "_temp"
            / "qa"
            / context.story_id
            / _DESIGN_ARTIFACT_FILENAME
        )
        payload: dict[str, object] = {
            "story_id": context.story_id,
            "run_id": context.run_id,
        }
        if not artifact_path.exists():
            # FAIL-CLOSED: absent design artifact is reported explicitly, never
            # a silent pass (AG3-036 §2.1.7 / briefing).
            payload["drift_detected"] = False
            payload["reason"] = _REASON_NO_DESIGN_ARTIFACT
            severity = "warning"
        else:
            drift_detected = bool(context.payload.get("drift_detected", False))
            payload["drift_detected"] = drift_detected
            reason = context.payload.get("reason")
            if isinstance(reason, str) and reason:
                payload["reason"] = reason
            severity = "warning" if drift_detected else "info"

        event = Event(
            story_id=context.story_id,
            event_type=EventType.DRIFT_CHECK,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            severity=severity,
            payload=payload,
        )
        return HookResult.emitting((event,))

    @staticmethod
    def _is_increment_commit(context: HookContext) -> bool:
        return (
            context.trigger is HookTrigger.POST_TOOL_USE
            and context.tool == "Bash"
            and bool(_GIT_COMMIT_PATTERN.search(context.command))
        )


__all__ = ["DriftCheckHook"]
