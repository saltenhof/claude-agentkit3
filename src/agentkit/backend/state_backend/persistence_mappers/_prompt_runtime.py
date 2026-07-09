"""Prompt-runtime row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentkit.backend.prompt_runtime.execution_contract import ExecutionContractDigestRecord



def execution_contract_digest_to_row(
    record: ExecutionContractDigestRecord,
) -> dict[str, Any]:
    """Convert an ``ExecutionContractDigestRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "execution_contract_digest": record.execution_contract_digest,
        "digest_format_version": record.digest_format_version,
        "formed_at": record.formed_at.isoformat(),
    }



def execution_contract_digest_row_to_record(
    row: dict[str, Any],
) -> ExecutionContractDigestRecord:
    """Convert a DB row dict to an ``ExecutionContractDigestRecord``."""


    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord as _ExecutionContractDigestRecord,
    )

    return _ExecutionContractDigestRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        execution_contract_digest=str(row["execution_contract_digest"]),
        digest_format_version=int(row["digest_format_version"]),
        formed_at=datetime.fromisoformat(str(row["formed_at"])),
    )
