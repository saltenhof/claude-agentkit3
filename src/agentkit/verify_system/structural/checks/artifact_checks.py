"""Artifact checks (FK-27 §27.4.1 Artefakt-Pruefung).

These are the precondition artifact checks of Layer 1: the worker's
file-based deliverables must exist and be well-formed before the structural
checks run (FK-27 §27.4.1). They are deterministic Trust-A (``SYSTEM``)
checks over ``story_dir`` files.

Severities are sourced from the stage registry (FK-27 §27.4.1: all four
BLOCKING); the registry passes the resolved ``Severity`` into each check so
there is one severity truth (no second classification here).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.core_types.qa_artifact_names import (
    HANDOVER_FILE,
    PROTOCOL_FILE,
    WORKER_MANIFEST_FILE,
)
from agentkit.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.core_types import Severity
    from agentkit.story_context_manager.models import StoryContext

__all__ = [
    "check_artifact_handover",
    "check_artifact_manifest_claims",
    "check_artifact_protocol",
    "check_artifact_worker_manifest",
]

#: FK-27 §27.4.1 worker artifact filenames (story-dir relative).
_PROTOCOL_FILE = PROTOCOL_FILE
_WORKER_MANIFEST_FILE = WORKER_MANIFEST_FILE
_HANDOVER_FILE = HANDOVER_FILE
_ARTIFACT_HANDOVER_CHECK = "artifact.handover"
#: FK-27 §27.4.1: ``protocol.md`` must be larger than 50 bytes.
_PROTOCOL_MIN_BYTES = 50
#: FK-26 §26.7.3 handover mandatory fields (the FULL handover contract, NOT a
#: placeholder). ``handover.json`` is the structured worker->QA handover; the
#: QA-subflow (FK-26 §26.7.4) relies on every one of these being present:
#: Layer 1 reads ``increments``/``existing_tests``, Layer 2 reads
#: ``changes_summary``/``assumptions``/``drift_log``/``acceptance_criteria_status``,
#: Layer 3 reads ``risks_for_qa``/``existing_tests``. ``assumptions`` and
#: ``drift_log`` may be empty lists but the KEY must be present (FK-26 §26.7.3).
#: The envelope identity fields (``story_id`` etc.) live in the artefact
#: envelope, not the handover payload, so they are not re-required here.
_HANDOVER_REQUIRED_KEYS: tuple[str, ...] = (
    "changes_summary",
    "increments",
    "assumptions",
    "existing_tests",
    "risks_for_qa",
    "drift_log",
    "acceptance_criteria_status",
)


def _finding(check: str, severity: Severity, message: str, file_path: Path) -> Finding:
    """Build a Trust-A artifact finding with the registry-resolved severity."""
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
        file_path=str(file_path),
    )


def check_artifact_protocol(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """FK-27 §27.4.1 ``artifact.protocol``: ``protocol.md`` exists and > 50 bytes.

    Args:
        ctx: Story context (unused; kept for the uniform check signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.1: BLOCKING).

    Returns:
        ``None`` on PASS; a Trust-A finding when the file is missing or too small.
    """
    del ctx
    path = story_dir / _PROTOCOL_FILE
    if not path.is_file():
        return _finding(
            "artifact.protocol", severity,
            f"{_PROTOCOL_FILE} is missing (FK-27 §27.4.1)", path,
        )
    if path.stat().st_size <= _PROTOCOL_MIN_BYTES:
        return _finding(
            "artifact.protocol", severity,
            f"{_PROTOCOL_FILE} is empty or <= {_PROTOCOL_MIN_BYTES} bytes "
            "(FK-27 §27.4.1)",
            path,
        )
    return None


def check_artifact_worker_manifest(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """FK-27 §27.4.1 ``artifact.worker_manifest``: valid JSON manifest.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.1: BLOCKING).

    Returns:
        ``None`` on PASS; a finding when missing or not valid JSON.
    """
    del ctx
    path = story_dir / _WORKER_MANIFEST_FILE
    if not path.is_file():
        return _finding(
            "artifact.worker_manifest", severity,
            f"{_WORKER_MANIFEST_FILE} is missing (FK-27 §27.4.1)", path,
        )
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return _finding(
            "artifact.worker_manifest", severity,
            f"{_WORKER_MANIFEST_FILE} is not valid JSON: {exc} (FK-27 §27.4.1)",
            path,
        )
    return None


def check_artifact_manifest_claims(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """FK-27 §27.4.1 ``artifact.manifest_claims``: declared files exist on disk.

    Reads the ``files`` (or ``produced_files``) array from the worker manifest
    and verifies each declared path exists relative to ``story_dir``.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.1 / FK-33 §33.3.2:
            BLOCKING).

    Returns:
        ``None`` on PASS; a finding when the manifest is unreadable or a
        declared file is missing on disk.
    """
    del ctx
    path = story_dir / _WORKER_MANIFEST_FILE
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return _finding(
            "artifact.manifest_claims", severity,
            f"{_WORKER_MANIFEST_FILE} unreadable for claim check: {exc} "
            "(FK-27 §27.4.1)",
            path,
        )
    declared = _declared_files(manifest)
    for rel in declared:
        if not (story_dir / rel).exists():
            return _finding(
                "artifact.manifest_claims", severity,
                f"Declared file '{rel}' does not exist on disk (FK-27 §27.4.1)",
                story_dir / rel,
            )
    return None


def _declared_files(manifest: object) -> list[str]:
    """Extract declared file paths from a worker manifest mapping (fail-soft)."""
    if not isinstance(manifest, dict):
        return []
    raw = manifest.get("files")
    if raw is None:
        raw = manifest.get("produced_files")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, str)]


def check_artifact_handover(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
) -> Finding | None:
    """FK-27 §27.4.1 ``artifact.handover``: ``handover.json`` exists, schema-valid.

    Schema validity is checked against the FULL FK-26 §26.7.3 handover contract
    (``changes_summary``, ``increments``, ``assumptions``, ``existing_tests``,
    ``risks_for_qa``, ``drift_log``, ``acceptance_criteria_status``) -- NOT a
    reduced placeholder. A missing field is a BLOCKING schema violation
    (FK-27 §27.4.1: "Schema-Verletzung" -> FAIL).

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.1: BLOCKING).

    Returns:
        ``None`` on PASS; a finding when missing, not JSON, or schema-invalid.
    """
    del ctx
    path = story_dir / _HANDOVER_FILE
    if not path.is_file():
        return _finding(
            _ARTIFACT_HANDOVER_CHECK, severity,
            f"{_HANDOVER_FILE} is missing (FK-27 §27.4.1)", path,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return _finding(
            _ARTIFACT_HANDOVER_CHECK, severity,
            f"{_HANDOVER_FILE} is not valid JSON: {exc} (FK-27 §27.4.1)", path,
        )
    if not isinstance(payload, dict):
        return _finding(
            _ARTIFACT_HANDOVER_CHECK, severity,
            f"{_HANDOVER_FILE} must be a JSON object (FK-26 §26.7.2)", path,
        )
    missing = [key for key in _HANDOVER_REQUIRED_KEYS if key not in payload]
    if missing:
        return _finding(
            _ARTIFACT_HANDOVER_CHECK, severity,
            f"{_HANDOVER_FILE} missing required handover fields {missing} "
            "(FK-26 §26.7.3)",
            path,
        )
    return None
