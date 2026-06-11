"""The installer ``CheckpointEngine`` (FK-50 §50.3.1).

Deterministically walks the installer :class:`FlowDefinition` (a
``level=COMPONENT, owner="Installer"`` instance of the existing process-DSL —
NOT a new flow engine) and executes each ``step`` node's handler, routing
``branch`` nodes via typed feature predicates over the per-run context.

Control flow (order + optional branches) lives in the flow contract; per-handler
idempotency/mutation lives in the handlers (FK-50 §50.3.1). The engine itself is
mode-agnostic: ``register``/``dry_run``/``verify`` differ only in what the
handlers do, which they read from ``context.mode``.

The engine is GENERIC over its run-context type (``ContextT``): the installer
flow instantiates it with :class:`CheckpointContext`, the FK-51 upgrade flow
(AG3-089) instantiates the SAME engine with its own upgrade context. This is a
type-level reuse of the ONE walker (no second installer / second walker, story
§6): both contexts only have to expose the typed ``mode`` the engine reads to
honour the register-aborts / read-only-collects contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from agentkit.exceptions import InstallationError
from agentkit.installer.registration import CheckpointStatus
from agentkit.process.language.model import NodeKind

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from agentkit.installer.checkpoint_engine.execution_mode import ExecutionMode
    from agentkit.installer.registration import CheckpointResult
    from agentkit.process.language.model import FlowDefinition


class EngineContext(Protocol):
    """Minimal contract the :class:`CheckpointEngine` requires of a run context.

    The engine only reads the typed :class:`ExecutionMode` off the context (to
    honour the register-aborts-on-FAILED vs read-only-collects contract, FK-50
    §50.2/§50.4). Concrete contexts (installer / upgrade) carry whatever ELSE
    their handlers need on top of this.
    """

    @property
    def mode(self) -> ExecutionMode:
        """The typed execution mode of this run."""


class CheckpointHandler[ContextT: EngineContext](Protocol):
    """Execution contract for a ``step`` checkpoint node.

    A handler receives the immutable run context and returns exactly one
    :class:`CheckpointResult`. It must be idempotent and must perform NO
    mutation when ``context.mode.mutations_allowed`` is ``False`` (FK-50 §50.2).
    """

    def __call__(self, context: ContextT) -> CheckpointResult:
        """Run the checkpoint and return its result."""


#: A branch predicate selects whether the branch's guarded successor runs.
#: It is a pure function of the (immutable) context — no side effects.
BranchPredicate = "Callable[[EngineContext], bool]"


class CheckpointEngine[ContextT: EngineContext]:
    """Deterministic walker over a ``level=COMPONENT`` checkpoint flow.

    Generic over the run-context type so the installer flow and the FK-51
    upgrade flow (AG3-089) reuse the SAME walker (story §6 — no second
    installer).

    Args:
        flow: The :class:`FlowDefinition`
            (``level=COMPONENT``; installer or upgrade owner).
        handlers: Registry mapping every ``step`` node id to its
            :class:`CheckpointHandler`.
        branch_predicates: Registry mapping every ``branch`` node id to a pure
            predicate over the context (``True`` -> take the branch's guarded
            successor edge; ``False`` -> skip the guarded sub-checkpoint).
    """

    def __init__(
        self,
        flow: FlowDefinition,
        handlers: Mapping[str, CheckpointHandler[ContextT]],
        branch_predicates: Mapping[str, Callable[[ContextT], bool]],
    ) -> None:
        self._flow = flow
        self._handlers = handlers
        self._branch_predicates = branch_predicates
        self._validate_registry()

    @property
    def flow(self) -> FlowDefinition:
        """The installer flow definition this engine executes."""
        return self._flow

    def _validate_registry(self) -> None:
        """Fail closed when a node has no handler / branch predicate.

        ZERO DEBT: every ``step`` node MUST have a handler and every ``branch``
        node MUST have a predicate, otherwise the flow could silently skip a
        checkpoint. A missing entry is a wiring error, not a runtime SKIP.
        """
        for node in self._flow.nodes:
            if node.kind is NodeKind.STEP and node.node_id not in self._handlers:
                raise InstallationError(
                    f"Installer flow step node {node.node_id!r} has no registered "
                    "handler (FK-50 §50.3.1; ZERO DEBT — every checkpoint is a "
                    "real handler).",
                    detail={"cause": "MissingCheckpointHandler", "node": node.node_id},
                )
            if (
                node.kind is NodeKind.BRANCH
                and node.node_id not in self._branch_predicates
            ):
                raise InstallationError(
                    f"Installer flow branch node {node.node_id!r} has no registered "
                    "predicate (FK-50 §50.3.1).",
                    detail={"cause": "MissingBranchPredicate", "node": node.node_id},
                )

    def run(self, context: ContextT) -> tuple[CheckpointResult, ...]:
        """Execute the flow in ``context.mode`` and collect results.

        Walks the flow from its first node, following the single ordered edge
        out of each node. A ``branch`` node evaluates its predicate: when
        ``False`` the guarded successor (the optional sub-checkpoint) is skipped
        and traversal jumps to that successor's own successor (rejoining the
        spine); when ``True`` traversal proceeds into the guarded successor.

        ``register`` aborts on the FIRST ``FAILED`` checkpoint (FK-50 §50.4 —
        a FAILED checkpoint aborts the install; prior results are preserved).
        ``dry_run`` and ``verify`` are read-only and collect every checkpoint's
        result without aborting (a plan/verification must surface ALL findings).

        Args:
            context: The immutable per-run context.

        Returns:
            The ordered tuple of :class:`CheckpointResult` for the nodes that
            ran (branch-skipped sub-checkpoints contribute no result).
        """
        results: list[CheckpointResult] = []
        current = self._flow.nodes[0].node_id if self._flow.nodes else None
        visited_guard = 0
        max_steps = len(self._flow.nodes) * 4 + 8  # deterministic loop bound

        while current is not None:
            visited_guard += 1
            if visited_guard > max_steps:  # pragma: no cover - defensive
                raise InstallationError(
                    "Installer flow traversal exceeded its deterministic step "
                    "bound; the flow graph is not a finite spine.",
                    detail={"cause": "FlowTraversalRunaway", "node": current},
                )
            node = self._flow.get_node(current)
            if node is None:  # pragma: no cover - registry validated at build
                raise InstallationError(
                    f"Installer flow references unknown node {current!r}.",
                    detail={"cause": "UnknownFlowNode", "node": current},
                )

            if node.kind is NodeKind.BRANCH:
                current = self._route_branch(current, context)
                continue

            result = self._handlers[current](context)
            results.append(result)
            if (
                context.mode.mutations_allowed
                and result.status is CheckpointStatus.FAILED
            ):
                # FK-50 §50.4: a FAILED checkpoint aborts the register run.
                break
            current = self._next_spine_node(current)

        return tuple(results)

    def _route_branch(self, branch_id: str, context: ContextT) -> str | None:
        """Resolve the next node out of a ``branch`` node.

        The branch has exactly two outgoing edges by priority: the higher
        priority edge is the guarded sub-checkpoint (taken when the predicate is
        ``True``); the lower-priority edge is the skip edge that rejoins the
        spine (taken when ``False``).
        """
        edges = self._flow.get_edges_from(branch_id)
        if len(edges) != 2:
            raise InstallationError(
                f"Installer branch node {branch_id!r} must have exactly two "
                f"outgoing edges (guarded + skip); found {len(edges)}.",
                detail={"cause": "MalformedBranch", "node": branch_id},
            )
        take_guarded = self._branch_predicates[branch_id](context)
        # ``get_edges_from`` returns edges sorted by DESCENDING priority, so
        # edges[0] is the guarded edge and edges[1] is the skip edge.
        return edges[0].target if take_guarded else edges[1].target

    def _next_spine_node(self, node_id: str) -> str | None:
        """Return the single ordered successor of a ``step`` node (or ``None``)."""
        edges = self._flow.get_edges_from(node_id)
        if not edges:
            return None
        if len(edges) > 1:
            raise InstallationError(
                f"Installer step node {node_id!r} has {len(edges)} outgoing "
                "edges; a step is a single-successor spine node (branches own "
                "the fan-out).",
                detail={"cause": "MalformedStepFanout", "node": node_id},
            )
        return edges[0].target


__all__ = [
    "BranchPredicate",
    "CheckpointEngine",
    "CheckpointHandler",
    "EngineContext",
]
