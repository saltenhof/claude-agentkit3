"""Persistence port for the Edge-Command-Queue (FK-91 §91.1b, AG3-145).

The command queue between the control plane and the harness edge is its own
aggregate: its rows live in their own store module, its lifecycle
(commission -> deliver/ack -> result-commit -> supersede) is independent of the
control-plane operation ledger, and none of its eight primitives is shared with
another repository. It therefore carries its own imports instead of loading them
into every consumer of ``control_plane.repository`` (AG3-229).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.harness_edge_command_store import (
    commission_edge_command_record_global,
    insert_edge_command_record_global,
    list_and_ack_open_edge_command_records_global,
    load_edge_command_record_global,
    reconcile_verify_evidence_command_generation_global,
    supersede_open_edge_command_global,
    supersede_verify_evidence_command_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    commit_edge_command_result_global,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.records import EdgeCommandRecord


@dataclass(frozen=True)
class EdgeCommandRepository:
    """Persistence port for the Edge-Command-Queue (FK-91 §91.1b, AG3-145).

    Postgres-only (K5): every method fails closed with ``ConfigError`` off
    Postgres (``_require_control_plane_backend``, mirrors
    :class:`RunOwnershipRepository` / :class:`ObjectMutationClaimRepository`).
    ``insert_command`` is the strict commissioning write (setup provisioning,
    sub-step C); ``commission_command`` is the ATOMICALLY IDEMPOTENT commissioning
    write (``INSERT ... ON CONFLICT DO NOTHING``) used by the teardown path
    (sub-step D) so a concurrent double-detach is one visible command / no error
    (FK-10 §10.5.3); ``list_and_ack_open_commands`` is the GET Ack-read (Rule 13,
    no lock); ``load_command`` is a raw identity lookup (idempotency-replay / test
    support); ``commit_result`` is the atomic op-ledger + Rule-15-fenced
    command-result commit (sub-step A).
    """

    insert_command: Callable[[EdgeCommandRecord], None] = (
        insert_edge_command_record_global
    )
    commission_command: Callable[[EdgeCommandRecord], bool] = (
        commission_edge_command_record_global
    )
    load_command: Callable[[str], EdgeCommandRecord | None] = (
        load_edge_command_record_global
    )
    list_and_ack_open_commands: Callable[..., tuple[EdgeCommandRecord, ...]] = (
        list_and_ack_open_edge_command_records_global
    )
    commit_result: Callable[..., None] = commit_edge_command_result_global
    supersede_command: Callable[..., bool] = supersede_open_edge_command_global
    reconcile_verify_evidence_generation: Callable[..., tuple[bool, bool]] = (
        reconcile_verify_evidence_command_generation_global
    )
    supersede_verify_evidence: Callable[..., bool] = (
        supersede_verify_evidence_command_global
    )
