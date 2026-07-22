"""CP 10a — first indexing checkpoint (AG3-176 AC3 / R14)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.installer.bootstrap_checkpoints.cp10_common import (
    feature_present_result,
)
from agentkit.backend.installer.checkpoint_engine import node_ids as nid
from agentkit.backend.installer.checkpoint_engine.result_builder import make_result
from agentkit.backend.installer.registration import CheckpointStatus

if TYPE_CHECKING:
    from agentkit.backend.installer.checkpoint_engine.context import CheckpointContext
    from agentkit.backend.installer.registration import CheckpointResult


def cp10a_concept_context_properties(context: CheckpointContext) -> CheckpointResult:
    """CP 10a — schema ensure + first indexing with typed receipts (AG3-176 AC3).

    Depends on CP 10 (MCP server registered). Runs
    ``story_sync(full_reindex=true)`` and ``concept_sync(full_reindex=true)``
    against the target corpus via the AG3-174 engine only. Publishes typed
    receipts for both; ``empty_corpus=true`` is success with zero counts.
    Transport/parse/partial failures are FAILED without success/freshness.
    """
    start = time.monotonic()
    if not context.mode.mutations_allowed:
        detail = (
            "Would ensure StoryContext schema and run story_sync + concept_sync "
            "full_reindex with typed receipts (no mutation in this mode)."
        )
        return feature_present_result(
            nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            context,
            detail=detail,
            start=start,
        )

    from agentkit.backend.vectordb.first_index import FirstIndexError, FirstIndexResult

    try:
        result_obj = _execute_first_index(context)
    except Exception as exc:  # noqa: BLE001 -- CP boundary: named FAILED
        if isinstance(exc, FirstIndexError):
            return make_result(
                nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
                status=CheckpointStatus.FAILED,
                detail=exc.detail,
                reason=exc.reason,
                start=start,
            )
        return make_result(
            nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            status=CheckpointStatus.FAILED,
            detail=f"first indexing failed: {exc}",
            reason="first_index_failed",
            start=start,
        )

    if not isinstance(result_obj, FirstIndexResult):
        return make_result(
            nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
            status=CheckpointStatus.FAILED,
            detail="first indexing returned unexpected result type",
            reason="first_index_failed",
            start=start,
        )
    result = result_obj
    detail = (
        f"First indexing complete: story "
        f"(discovered={result.story_receipt.discovered}, "
        f"upserted={result.story_receipt.upserted}, "
        f"empty_corpus={result.story_receipt.empty_corpus}); concept "
        f"(discovered={result.concept_receipt.discovered}, "
        f"upserted={result.concept_receipt.upserted}, "
        f"empty_corpus={result.concept_receipt.empty_corpus})."
    )
    return make_result(
        nid.CP_10A_CONCEPT_CONTEXT_PROPERTIES,
        status=CheckpointStatus.CREATED,
        detail=detail,
        start=start,
    )


def _execute_first_index(context: CheckpointContext) -> object:
    """Build binding + adapter and run first index (injectable via module attr)."""
    from agentkit.backend.vectordb.first_index import run_first_index
    from agentkit.backend.vectordb.project_binding import bind_project
    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter

    binding = bind_project(context.project_root)
    host = getattr(context.config, "weaviate_host", None)
    http_port = getattr(context.config, "weaviate_http_port", None)
    grpc_port = getattr(context.config, "weaviate_grpc_port", None)
    if not host or not http_port or not grpc_port:
        vdb = binding.config.pipeline.vectordb
        if vdb is None:
            from agentkit.backend.vectordb.first_index import FirstIndexError

            raise FirstIndexError(
                "vectordb_block_missing",
                "no vectordb endpoint for first indexing (fail-closed).",
            )
        host = vdb.host
        http_port = vdb.port
        grpc_port = vdb.grpc_port
    if host is None or http_port is None or grpc_port is None:
        from agentkit.backend.vectordb.first_index import FirstIndexError

        raise FirstIndexError(
            "vectordb_block_missing",
            "incomplete vectordb endpoint for first indexing (fail-closed).",
        )
    adapter = WeaviateStoryAdapter.connect(
        host=str(host), port=int(http_port), grpc_port=int(grpc_port)
    )
    try:
        # WeaviateStoryAdapter satisfies IngestStorePort at runtime.
        return run_first_index(binding, adapter)
    finally:
        adapter.close()



__all__ = ["cp10a_concept_context_properties"]
