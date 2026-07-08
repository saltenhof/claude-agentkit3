"""Prompt-runtime persistence store."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.runtime_scope_resolver import resolve_runtime_scope
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord,
    )
    from agentkit.backend.state_backend.scope import RuntimeStateScope


def insert_execution_contract_digest_global(
    record: ExecutionContractDigestRecord,
) -> None:
    """Strictly insert one Postgres-only execution-contract-digest row."""
    from agentkit.backend.state_backend.store import mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_execution_contract_digest_global_row(
        mappers.execution_contract_digest_to_row(record),
    )


def load_execution_contract_digest_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> ExecutionContractDigestRecord | None:
    """Load the run's persisted execution-contract-digest row."""
    from agentkit.backend.state_backend.store import mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_execution_contract_digest_global_row(
        project_key,
        story_id,
        run_id,
    )
    if row is None:
        return None
    return mappers.execution_contract_digest_row_to_record(row)


def find_prompt_audit_output_hashes(
    story_dir: Path,
    scope: RuntimeStateScope | None,
) -> frozenset[str]:
    """Return all prompt-audit output digests for the resolved run scope."""
    if scope is not None:
        story_id, run_id = scope.story_id, scope.run_id
    else:
        try:
            resolved = resolve_runtime_scope(story_dir)
        except CorruptStateError:
            return frozenset()
        story_id, run_id = resolved.story_id, resolved.run_id
    if not run_id:
        return frozenset()
    rows = _backend_module().load_prompt_audit_payload_rows(
        story_dir,
        story_id,
        run_id,
    )
    hashes: set[str] = set()
    for raw_payload in rows:
        if raw_payload is None:
            continue
        payload = (
            raw_payload if isinstance(raw_payload, dict) else json.loads(str(raw_payload))
        )
        digest = payload.get("output_sha256")
        if isinstance(digest, str) and digest:
            hashes.add(digest)
    return frozenset(hashes)


__all__ = [
    "insert_execution_contract_digest_global",
    "load_execution_contract_digest_global",
    "find_prompt_audit_output_hashes",
]
