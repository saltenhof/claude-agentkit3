"""Tests for canonical worker handover artifact filename exports."""

from __future__ import annotations

from agentkit.core_types import HANDOVER_FILE, PROTOCOL_FILE, WORKER_MANIFEST_FILE


def test_worker_handover_artifact_names_are_exported_from_core_types() -> None:
    assert PROTOCOL_FILE == "protocol.md"
    assert WORKER_MANIFEST_FILE == "worker-manifest.json"
    assert HANDOVER_FILE == "handover.json"
