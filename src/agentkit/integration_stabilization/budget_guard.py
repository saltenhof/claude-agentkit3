"""Stabilization-budget live-block guard for integration-stabilization.

FK-05 §5.9/§5.12/§5.14 — AC4.
Invariant: stabilization_budget_is_hard_cap.

This guard is a PreToolUse guard overlay that blocks worker activity when
any stabilization-budget cap is exhausted. It is docked onto the existing
``governance/guards/`` chain for stories with the integration_stabilization
contract.

The ``StabilizationBudgetGuard`` implements the ``GovernanceGuard`` protocol
(``agentkit.governance.protocols``) so it can be registered in the guard
chain alongside ``SeamAllowlistGuard``, ``ScopeGuard``, etc.

Budget state is read from the persisted ``integration_budget.json`` file
(maintained by the pipeline engine during IS loops). Absent file means no
loops have been run -- all caps start at zero usage (pass-through).

Fail-closed: if the budget file is unreadable (corrupt/permission error),
the guard blocks (unknown budget state = block, FK-05 §5.9).
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003  -- Path used in runtime path operations
from typing import TYPE_CHECKING

from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from agentkit.integration_stabilization.models import (
        IntegrationScopeManifest,
        StabilizationBudget,
    )
    from agentkit.telemetry.emitters import EventEmitter

__all__ = ["StabilizationBudgetGuard"]

#: Filename for the persisted stabilization budget counters.
_BUDGET_COUNTER_FILE: str = "integration_budget.json"


class StabilizationBudgetGuard:
    """PreToolUse guard overlay that live-blocks when budget caps are exhausted.

    Reads the current budget counters from ``integration_budget.json`` under
    the story directory at each evaluation. If any cap is exhausted, all
    mutating operations are blocked (fail-closed on exhausted budget).

    Only inspects mutating operations (``file_write``, ``file_edit``,
    ``bash_command``); read operations are allowed unconditionally.

    Fail-closed: if the budget file is present but unreadable, blocks.

    Args:
        manifest: The approved IntegrationScopeManifest supplying the budget caps.
        story_dir: The story working directory containing
            ``integration_budget.json``.
    """

    def __init__(
        self,
        manifest: IntegrationScopeManifest,
        story_dir: Path,
        *,
        emitter: EventEmitter | None = None,
        story_id: str = "",
        project_key: str = "",
        run_id: str = "",
    ) -> None:
        self._manifest = manifest
        self._story_dir = story_dir
        self._emitter = emitter
        self._story_id = story_id
        self._project_key = project_key
        self._run_id = run_id

    @property
    def name(self) -> str:
        """Short identifier for this guard."""
        return "stabilization_budget_guard"

    def evaluate(self, operation: str, context: dict[str, object]) -> GuardVerdict:
        """Block mutating operations when the stabilization budget is exhausted.

        Reads the current budget from ``integration_budget.json`` at evaluation
        time (live-blocking: reflects the latest loop counter increments). Only
        inspects mutating operations; reads are allowed unconditionally.

        Args:
            operation: The operation type being attempted.
            context: Operation context (unused for budget check).

        Returns:
            ``ALLOW`` when within budget or a non-mutating operation;
            ``BLOCK`` with ``POLICY_VIOLATION`` when any cap is exhausted.
        """
        del context  # Budget check is independent of the specific operation args.

        if operation not in ("file_write", "file_edit", "bash_command"):
            return GuardVerdict.allow(self.name)

        budget = self._load_budget()
        if budget is None:
            # Unreadable budget file: fail-closed block.
            return GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                "Stabilization budget is unreadable; cannot confirm within-budget "
                "status. All mutating operations are blocked (FK-05 §5.9, "
                "invariant: stabilization_budget_is_hard_cap).",
                detail={"budget_file": _BUDGET_COUNTER_FILE, "reason": "unreadable"},
            )

        if budget.any_cap_exhausted:
            exhausted = budget.exhausted_caps()
            self._emit_budget_exhausted(exhausted)
            return GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                f"Stabilization budget exhausted — caps hit: {exhausted}. "
                "All mutating operations are blocked until the replan gate "
                "(FK-05 §5.9, invariant: stabilization_budget_is_hard_cap).",
                detail={
                    "exhausted_caps": exhausted,
                    "loops_used": budget.loops_used,
                    "new_surfaces_used": budget.new_surfaces_used,
                    "contract_changes_used": budget.contract_changes_used,
                    "regressions_this_cycle": budget.regressions_this_cycle,
                },
            )

        return GuardVerdict.allow(self.name)

    def _emit_budget_exhausted(self, exhausted_caps: list[str]) -> None:
        """Emit ``stabilization_budget_exhausted`` at the guard boundary (AC11)."""
        if self._emitter is None or not self._story_id:
            return
        from agentkit.integration_stabilization.events import (
            emit_stabilization_budget_exhausted,
        )

        self._emitter.emit(
            emit_stabilization_budget_exhausted(
                story_id=self._story_id,
                project_key=self._project_key,
                run_id=self._run_id,
                exhausted_caps=exhausted_caps,
            )
        )

    def _load_budget(self) -> StabilizationBudget | None:
        """Load current budget counters from the persisted counter file.

        Returns:
            The current :class:`~agentkit.integration_stabilization.models.StabilizationBudget`
            with manifest caps and persisted counters, or ``None`` if the file
            exists but is unreadable.
        """
        from agentkit.integration_stabilization.models import StabilizationBudget

        budget_path = self._story_dir / _BUDGET_COUNTER_FILE
        if not budget_path.exists():
            # No counter file yet: all counters are zero (fresh run).
            return StabilizationBudget(caps=self._manifest.stabilization_budget)

        try:
            data: dict[str, object] = json.loads(
                budget_path.read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            # Unreadable file: signal fail-closed.
            return None

        def _int(key: str) -> int:
            val = data.get(key, 0)
            return int(val) if isinstance(val, (int, float)) else 0

        return StabilizationBudget(
            caps=self._manifest.stabilization_budget,
            loops_used=_int("loops_used"),
            new_surfaces_used=_int("new_surfaces_used"),
            contract_changes_used=_int("contract_changes_used"),
            regressions_this_cycle=_int("regressions_this_cycle"),
        )
