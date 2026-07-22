"""CLI-facing concept sync using the real Weaviate adapter (R03 / AC010).

Owned by the VectorDB BC so ConceptCatalog does not import Integrations.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from agentkit.backend.vectordb.concept_corpus.sync import (
    ConceptSyncBlockedError,
    concept_sync_bounded_window,
)
from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestError
from agentkit.backend.vectordb.project_binding import ProjectBinding, ProjectBindingError
from agentkit.backend.vectordb.runtime_binding import (
    RuntimeBindingError,
    load_runtime_binding_from_env,
)
from agentkit.backend.vectordb.schema import ensure_story_context_schema
from agentkit.integration_clients.vectordb import VectorDbError, WeaviateStoryAdapter


def run_concept_sync_cli(binding: Any, *, full_reindex: bool) -> int:
    """Execute productive concept sync; return process exit code."""
    if not isinstance(binding, ProjectBinding):
        print("internal error: invalid project binding", file=sys.stderr)
        return 3
    try:
        adapter = _build_real_adapter(binding)
    except (RuntimeBindingError, VectorDbError, ProjectBindingError) as exc:
        print(f"Weaviate binding/connect failed (fail-closed): {exc}", file=sys.stderr)
        return 3
    try:
        ensure_story_context_schema(adapter.raw_client)
    except Exception as exc:  # noqa: BLE001
        print(f"schema ensure failed (fail-closed): {exc}", file=sys.stderr)
        adapter.close()
        return 3
    engine = IngestEngine(
        adapter,
        lock_dir=binding.project_root / ".agentkit" / "vectordb" / "locks",
    )
    try:
        result = concept_sync_bounded_window(
            binding, engine, full_reindex=full_reindex
        )
    except ConceptSyncBlockedError as exc:
        print(json.dumps(exc.validation.as_dict(), indent=2), file=sys.stderr)
        return exc.validation.exit_code
    except (IngestError, VectorDbError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        adapter.close()
    print(
        json.dumps(
            {
                "ingest": result.ingest.as_dict(),
                "receipt": result.receipt.as_dict(),
                "receipt_path": str(result.receipt_path),
            },
            indent=2,
        )
    )
    return 0


def _build_real_adapter(binding: ProjectBinding) -> WeaviateStoryAdapter:
    try:
        rb = load_runtime_binding_from_env(cwd=binding.project_root)
        return WeaviateStoryAdapter.connect(
            host=rb.weaviate_host,
            port=rb.weaviate_http_port,
            grpc_port=rb.weaviate_grpc_port,
        )
    except RuntimeBindingError:
        pass
    vectordb = binding.config.pipeline.vectordb if binding.config.pipeline else None
    if vectordb is None or not vectordb.host or vectordb.port is None:
        raise RuntimeBindingError(
            "Weaviate endpoint not configured: set PROJECT_ID/WEAVIATE_* env "
            "or pipeline.vectordb.host/port in ProjectConfig (fail-closed, R03)."
        )
    return WeaviateStoryAdapter.connect(host=vectordb.host, port=int(vectordb.port))


__all__ = ["run_concept_sync_cli"]
