"""Execution context and run-state for the installer checkpoint engine.

The :class:`CheckpointContext` is the immutable per-run view handed to every
checkpoint handler: the install configuration, the typed
:class:`~agentkit.installer.checkpoint_engine.execution_mode.ExecutionMode`, the
project root and the resolved feature flags. Handler-to-handler data (e.g. the
``project.yaml`` mapping that CP 5 produces and CP 7/CP 10c consume) flows
through the mutable :class:`CheckpointRunState` rather than via hidden globals
(FIX-THE-MODEL: one explicit owner for shared run data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode
    from agentkit.installer.registration import RuntimeProfile
    from agentkit.installer.runner import InstallConfig


class ScopeInteractionMode:
    """ARE-scope interaction mode for CP 10c (FK-50 §50.3 CP 10c).

    String constants (not an enum to avoid an extra StrEnum for a binary
    runtime choice that never crosses a wire). ``AGENTIC`` is the default for an
    orchestrated install (returns ``PENDING_SELECTION`` metadata); ``INTERACTIVE``
    is the numbered-selection operator flow.
    """

    AGENTIC = "agentic"
    INTERACTIVE = "interactive"


@dataclass
class CheckpointRunState:
    """Mutable run-scoped state shared between checkpoint handlers.

    Owns the data a checkpoint produces for a LATER checkpoint to consume,
    keeping the data flow explicit and typed instead of recomputed or stashed
    in module globals.

    Attributes:
        created_files: Project-relative paths created/updated so far (mutating
            runs only). Reported on the final :class:`InstallResult`.
        project_yaml: The ``project.yaml`` mapping produced by CP 5 and consumed
            by CP 7 (digest) and CP 10c (ARE-scope map). ``None`` until CP 5.
        resolved_profile: The :class:`RuntimeProfile` resolved by CP 6 and
            consumed by CP 7. ``None`` until CP 6.
        skills: The resolved agent-skills top-surface (CP 8 preflight), shared
            with the binding step. Typed as ``object`` to keep the engine layer
            free of an agent-skills import; CP 8 narrows it.
        resolved_skill_bundles: ``(skill_name, bundle_root)`` pairs resolved in
            the CP 8 preflight, bound by CP 8.
    """

    created_files: list[str] = field(default_factory=list)
    project_yaml: dict[str, object] | None = None
    resolved_profile: RuntimeProfile | None = None
    skills: object | None = None
    resolved_skill_bundles: list[tuple[str, object]] = field(default_factory=list)
    #: CP 10c ARE-scope mappings resolved DURING this run (FK-50 §50.3 CP 10c).
    #: The orchestrating agent's ``resolve_pending_scope_mapping()`` (a producer
    #: OUT of scope, story §2.2) records the just-written ``module -> scope``
    #: entries here. CP 10c uses this to distinguish "this run resolved/wrote the
    #: mapping" (-> ``UPDATED``) from "already complete, nothing changed"
    #: (-> ``SKIPPED``/``PASS``) so an idempotent re-run never re-claims an
    #: UPDATED (story AC8). Empty -> nothing was resolved in this run.
    resolved_scope_mappings: dict[str, str] = field(default_factory=dict)
    #: Content digests of the harness settings files captured at CP 8 entry
    #: (BEFORE the static-resource deploy may overwrite them with the bundled
    #: template). CP 9 (``Governance.register_hooks``) uses this baseline so an
    #: idempotent re-run reports a settings file as changed only when the
    #: GOVERNANCE result actually differs from the previous governance result
    #: (mirrors the legacy ``before``-digest ordering).
    hook_settings_baseline: dict[object, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckpointContext:
    """Immutable per-run context handed to every checkpoint handler.

    Attributes:
        config: The install configuration (coordinates, injected collaborators,
            feature toggles).
        mode: The typed :class:`ExecutionMode` (register / dry_run / verify).
        project_root: Absolute target-project root.
        vectordb_enabled: Resolved ``features.vectordb`` flag.
        are_enabled: Resolved ``features.are`` flag.
        sonarqube_enabled: Resolved ``sonarqube.available`` flag (CP 10d
            applicability axis).
        scope_interaction_mode: CP 10c interaction mode
            (:class:`ScopeInteractionMode`). Defaults to ``AGENTIC``.
        run_state: The mutable :class:`CheckpointRunState` for cross-checkpoint
            data flow.
    """

    config: InstallConfig
    mode: ExecutionMode
    project_root: Path
    vectordb_enabled: bool
    are_enabled: bool
    sonarqube_enabled: bool
    scope_interaction_mode: str = ScopeInteractionMode.AGENTIC
    run_state: CheckpointRunState = field(default_factory=CheckpointRunState)


__all__ = [
    "CheckpointContext",
    "CheckpointRunState",
    "ScopeInteractionMode",
]
