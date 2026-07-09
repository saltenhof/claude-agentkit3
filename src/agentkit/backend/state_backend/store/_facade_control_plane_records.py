"""Static compatibility exports for control-plane-adjacent record symbols."""

# ruff: noqa: I001 - grouped static re-exports keep this compat facade under the module-level LOC cap.

from __future__ import annotations

from agentkit.backend.state_backend.governance_runtime_store import (
    load_story_execution_lock_global as load_story_execution_lock_global,
    save_story_execution_lock_global as save_story_execution_lock_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    commission_edge_command_record_global as commission_edge_command_record_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    insert_edge_command_record_global as insert_edge_command_record_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    list_and_ack_open_edge_command_records_global as list_and_ack_open_edge_command_records_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    load_edge_command_record_global as load_edge_command_record_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    supersede_open_edge_command_global as supersede_open_edge_command_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    acquire_object_mutation_claim_global as acquire_object_mutation_claim_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    commit_edge_command_result_global as commit_edge_command_result_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    delete_object_mutation_claim_global as delete_object_mutation_claim_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    insert_object_mutation_claim_global as insert_object_mutation_claim_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    list_orphaned_object_mutation_claims_global as list_orphaned_object_mutation_claims_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    load_object_mutation_claim_global as load_object_mutation_claim_global,
)
from agentkit.backend.state_backend.prompt_runtime_store import (
    insert_execution_contract_digest_global as insert_execution_contract_digest_global,
    load_execution_contract_digest_global as load_execution_contract_digest_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    list_push_barrier_verdicts_global as list_push_barrier_verdicts_global,
    list_push_freshness_records_global as list_push_freshness_records_global,
    list_ref_protection_degradation_findings_global as list_ref_protection_degradation_findings_global,
    load_push_barrier_verdict_global as load_push_barrier_verdict_global,
    load_push_freshness_record_global as load_push_freshness_record_global,
    upsert_push_barrier_verdict_global as upsert_push_barrier_verdict_global,
    upsert_push_freshness_record_global as upsert_push_freshness_record_global,
    upsert_ref_protection_degradation_finding_global as upsert_ref_protection_degradation_finding_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_takeover_transfer_record_global as load_takeover_transfer_record_global,
    save_takeover_transfer_record_global as save_takeover_transfer_record_global,
)

__all__ = [
    "insert_edge_command_record_global",
    "commission_edge_command_record_global",
    "load_edge_command_record_global",
    "list_and_ack_open_edge_command_records_global",
    "commit_edge_command_result_global",
    "supersede_open_edge_command_global",
    "upsert_push_freshness_record_global",
    "load_push_freshness_record_global",
    "list_push_freshness_records_global",
    "upsert_push_barrier_verdict_global",
    "load_push_barrier_verdict_global",
    "list_push_barrier_verdicts_global",
    "upsert_ref_protection_degradation_finding_global",
    "list_ref_protection_degradation_findings_global",
    "insert_execution_contract_digest_global",
    "load_execution_contract_digest_global",
    "insert_object_mutation_claim_global",
    "load_object_mutation_claim_global",
    "acquire_object_mutation_claim_global",
    "delete_object_mutation_claim_global",
    "list_orphaned_object_mutation_claims_global",
    "save_takeover_transfer_record_global",
    "load_takeover_transfer_record_global",
    "save_story_execution_lock_global",
    "load_story_execution_lock_global",
]
