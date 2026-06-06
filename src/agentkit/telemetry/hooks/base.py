"""Telemetry-hook base surfaces: ``TelemetryHook`` protocol, context, result.

FK-68 §68.3.1 (Hook-based capture) defines the observing telemetry sources as
an adapter path for control-plane telemetry. Every hook in this package shares
one harness-neutral shape:

- :class:`HookContext` -- the harness-neutral observation a hook reacts to. It
  is a SELF-CONTAINED model, deliberately decoupled from
  :class:`agentkit.governance.guard_evaluation.HookEvent` (the guard-side event)
  so that the telemetry hooks stay within the AC10 import boundary (core_types,
  telemetry, and the verdict types from ``agentkit.governance.protocols`` — the
  canonical home of :class:`GuardVerdict`) and never reach into
  config / story-context / installer BCs. The story-type and required-reviewer
  roles that some hooks need are injected as plain values, not imported enums.
- :class:`HookResult` -- the immutable outcome of :meth:`TelemetryHook.evaluate`.
  It carries the telemetry events to emit and, for the double-role
  :class:`~agentkit.telemetry.hooks.review_guard.ReviewGuard` /
  :class:`~agentkit.telemetry.hooks.budget_event_emitter.BudgetEventEmitter`, an
  optional :class:`~agentkit.governance.protocols.GuardVerdict`.

The hooks are observational by default (FK-68 §68.6.0 "Telemetrie-Hooks sind
rein observational"). Only ReviewGuard and BudgetEventEmitter additionally carry
a guard verdict, because the story (§2.1.5 / §2.1.6) mandates their double role.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from agentkit.governance.protocols import GuardVerdict
from agentkit.telemetry.events import Event

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter


class HookTrigger(StrEnum):
    """Harness-neutral trigger phases a hook reacts to (FK-68 §68.3.1).

    Mirrors the harness hook phases without binding to a concrete harness. The
    Claude Code / Codex adapters map their native phases onto these values.
    """

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_SESSION = "post_session"


class HookContext(BaseModel):
    """Harness-neutral observation passed to a telemetry hook.

    Attributes:
        trigger: The hook trigger phase (pre/post tool use, post session).
        story_id: Active story identifier (FK-68 §68.3.3).
        run_id: Active run identifier (FK-68 §68.3.3).
        project_key: Owning project key used for telemetry correlation.
        principal: Technical principal that performed the observed action
            (e.g. ``"worker"``, ``"orchestrator"``). Never prompt content.
        worker_id: Identifier of the worker agent, when known.
        tool: Name of the observed tool (e.g. ``"Bash"``, ``"WebFetch"``).
        command: Raw command string for ``Bash`` observations (e.g. the
            ``git commit`` line). Empty for non-bash tools.
        story_type: Plain story-type string (``"research"`` / ``"implementation"``
            / ...). Injected as a value to honour the AC10 import boundary; the
            hooks never import :class:`StoryType`. Only meaningful when
            ``story_type_resolved`` is ``True``.
        story_type_resolved: Whether the authoritative story type was RESOLVED
            (store read + record found). ``False`` signals the UNRESOLVED state
            (backend fault OR missing record) — the budget hook fail-closes on it
            (AG3-036 FIX-B) instead of downgrading an empty ``story_type`` to
            "not research". Defaults to ``True`` so observational hooks and the
            many contexts that never carry a story type are unaffected.
        phase: Pipeline phase name, when known.
        outcome: Lifecycle outcome for ``agent_end`` (``"success"`` / ``"failure"``).
        subagent_type: Sub-agent type for agent-lifecycle observations.
        payload: Free-form, already harness-decoded observation detail (e.g.
            ``commit_sha``, ``files_changed``, ``reviewer_role``, verdicts).
            Keys/values are English wire keys (ARCH-55).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger: HookTrigger
    story_id: str
    run_id: str
    project_key: str
    principal: str = "worker"
    worker_id: str | None = None
    tool: str = ""
    command: str = ""
    story_type: str = ""
    story_type_resolved: bool = True
    phase: str | None = None
    outcome: str | None = None
    subagent_type: str | None = None
    payload: dict[str, object] = {}


class HookResult(BaseModel):
    """Immutable outcome of :meth:`TelemetryHook.evaluate` (ARCH-29).

    Attributes:
        triggered: Whether the hook's trigger condition matched the context.
            ``False`` means the hook is a no-op for this context (no events, no
            verdict) -- this is NOT a silent pass for fail-closed hooks, which
            set ``triggered=True`` and emit a fail-closed event instead.
        events: Telemetry events to persist via :meth:`TelemetryHook.emit`.
        verdict: Optional guard verdict for the double-role hooks (ReviewGuard,
            BudgetEventEmitter). ``None`` for purely observational hooks.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    triggered: bool
    events: tuple[Event, ...] = ()
    verdict: GuardVerdict | None = None

    @classmethod
    def skipped(cls) -> HookResult:
        """Return a no-op result (trigger condition did not match)."""
        return cls(triggered=False)

    @classmethod
    def emitting(
        cls,
        events: tuple[Event, ...],
        *,
        verdict: GuardVerdict | None = None,
    ) -> HookResult:
        """Return a triggered result carrying *events* and an optional *verdict*.

        Args:
            events: Telemetry events to emit.
            verdict: Optional guard verdict (double-role hooks only).

        Returns:
            A triggered :class:`HookResult`.
        """
        return cls(triggered=True, events=events, verdict=verdict)


@runtime_checkable
class TelemetryHook(Protocol):
    """Contract every telemetry hook implements (FK-68 §68.3.1, ARCH-06).

    Hooks are deterministic, side-effect-free in :meth:`evaluate` (pure
    decision) and push their side effect (persistence) into :meth:`emit`.
    """

    @property
    def name(self) -> str:
        """Stable hook identifier (matches the FK-68 §68.3.1 module name)."""
        ...

    def evaluate(self, context: HookContext) -> HookResult:
        """Decide whether telemetry events must be emitted for *context*.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` with the events to emit (and an optional
            verdict for double-role hooks).
        """
        ...

    def emit(self, result: HookResult) -> None:
        """Persist the events of *result* via the canonical emitter.

        Args:
            result: The evaluation outcome whose events are persisted.
        """
        ...


class EmittingHook:
    """Base class wiring the shared :meth:`emit` side of every hook.

    Concrete hooks subclass this and implement :meth:`evaluate`. The
    persistence path is the canonical :class:`~agentkit.telemetry.emitters.EventEmitter`
    (FK-68 §68.3.4 -- hooks write through the telemetry service, never directly
    into the DB). ``StateBackendEmitter`` is the production implementation;
    ``MemoryEmitter`` is the first-class in-memory variant for tests.
    """

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise the hook with the canonical event emitter.

        Args:
            emitter: The telemetry emitter used by :meth:`emit`.
        """
        self._emitter = emitter

    def emit(self, result: HookResult) -> None:
        """Persist every event in *result* via the canonical emitter.

        Args:
            result: The evaluation outcome whose events are persisted.
        """
        for event in result.events:
            self._emitter.emit(event)


__all__ = [
    "EmittingHook",
    "HookContext",
    "HookResult",
    "HookTrigger",
    "TelemetryHook",
]
