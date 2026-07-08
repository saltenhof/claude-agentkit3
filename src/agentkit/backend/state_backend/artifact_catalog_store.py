"""Artifact-catalog persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.persistence_json_codec import (
    JsonRecord,
    _cast_json_record,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.state_backend.scope import RuntimeStateScope


def load_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    """Load an artifact payload by local story directory and artifact kind."""
    return _cast_json_record(
        _backend_module().load_artifact_record_payload(story_dir, artifact_kind),
    )


def load_artifact_record_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> JsonRecord | None:
    """Load an artifact payload by explicit runtime scope."""
    return _cast_json_record(
        _backend_module().load_artifact_record_payload_for_scope(scope, artifact_kind),
    )


def read_artifact_record(
    story_dir: Path,
    artifact_kind: str,
) -> JsonRecord | None:
    """Compatibility alias for ``load_artifact_record``."""
    return load_artifact_record(story_dir, artifact_kind)


def purge_run_bound_artifact_envelopes(
    story_dir: Path,
    story_id: str,
    run_id: str,
) -> int:
    """Delete run-bound artifact envelope rows for ``(story_id, run_id)``."""
    return int(
        _backend_module().purge_run_bound_artifact_envelopes_row(
            story_dir,
            story_id,
            run_id,
        )
    )


__all__ = [
    "load_artifact_record",
    "load_artifact_record_for_scope",
    "read_artifact_record",
    "purge_run_bound_artifact_envelopes",
]
