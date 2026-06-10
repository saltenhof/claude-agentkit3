"""Implementation evidence terminality gate (FK-24 §24.6 / §24.14)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.core_types.qa_artifact_names import (
    CHANGE_FRAME_DRAFT_FILE,
    CHANGE_FRAME_FILE,
    HANDOVER_FILE,
    PROTOCOL_FILE,
    WORKER_MANIFEST_FILE,
)
from agentkit.story_context_manager.types import StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.verify_system.structural.system_evidence import ChangeEvidence


@dataclass(frozen=True)
class ImplementationEvidenceVerdict:
    """Outcome of the implementation-evidence terminality gate (FK-24 §24.6)."""

    passed: bool
    blocking_reason: str | None = None


def evaluate_implementation_evidence_gate(
    *,
    story_type: StoryType,
    story_dir: Path,
    change_evidence: ChangeEvidence,
) -> ImplementationEvidenceVerdict:
    """Evaluate whether an impl/bugfix story has real implementation evidence."""
    if story_type not in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
        return ImplementationEvidenceVerdict(passed=True)

    artifact_error = _required_implementation_artifact_error(story_dir)
    if artifact_error is not None:
        return ImplementationEvidenceVerdict(
            passed=False,
            blocking_reason=artifact_error,
        )

    if not change_evidence.available:
        return ImplementationEvidenceVerdict(
            passed=False,
            blocking_reason=(
                "Implementation-Evidence-Gate: independent System change "
                "evidence is unavailable; cannot confirm real implementation "
                "changes (FK-24 §24.6 / FK-33 §33.5)."
            ),
        )
    implementation_changes = tuple(
        changed
        for changed in change_evidence.changed_files
        if _counts_as_implementation_change(changed)
    )
    if not implementation_changes:
        return ImplementationEvidenceVerdict(
            passed=False,
            blocking_reason=(
                "Implementation-Evidence-Gate: no real implementation file "
                "change is confirmed by System git diff evidence; exploration "
                "artifacts and worker-manifest claims do not count "
                "(FK-24 §24.6)."
            ),
        )
    return ImplementationEvidenceVerdict(passed=True)


def _required_implementation_artifact_error(story_dir: Path) -> str | None:
    """Return a blocker for missing or malformed worker delivery artifacts."""
    handover = story_dir / HANDOVER_FILE
    if not handover.is_file():
        return (
            f"Implementation-Evidence-Gate: primary delivery artifact "
            f"{HANDOVER_FILE} is missing (FK-24 §24.6)."
        )
    protocol = story_dir / PROTOCOL_FILE
    if not protocol.is_file():
        return (
            f"Implementation-Evidence-Gate: required artifact {PROTOCOL_FILE} "
            "is missing (FK-24 §24.6)."
        )
    manifest = story_dir / WORKER_MANIFEST_FILE
    if not manifest.is_file():
        return (
            f"Implementation-Evidence-Gate: required artifact "
            f"{WORKER_MANIFEST_FILE} is missing (FK-24 §24.6)."
        )
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return (
            f"Implementation-Evidence-Gate: {WORKER_MANIFEST_FILE} is not "
            f"valid JSON: {exc} (FK-24 §24.6)."
        )
    try:
        from agentkit.implementation.manifest import WorkerManifest

        WorkerManifest.model_validate(raw)
    except ValueError as exc:
        return (
            f"Implementation-Evidence-Gate: {WORKER_MANIFEST_FILE} is not a "
            f"valid WorkerManifest: {exc} (FK-24 §24.6)."
        )
    return None


_EXPLORATION_ONLY_FILENAMES: frozenset[str] = frozenset(
    {
        CHANGE_FRAME_FILE,
        CHANGE_FRAME_DRAFT_FILE,
        "exploration-summary.md",
        "entwurfsartefakt.json",
        HANDOVER_FILE,
        PROTOCOL_FILE,
        WORKER_MANIFEST_FILE,
    }
)


def _counts_as_implementation_change(changed_path: str) -> bool:
    """Whether a changed path is eligible implementation evidence."""
    normalized = changed_path.replace("\\", "/")
    name = normalized.rsplit("/", maxsplit=1)[-1]
    if name in _EXPLORATION_ONLY_FILENAMES:
        return False
    return not (
        normalized.startswith("_temp/qa/")
        and name in {
            CHANGE_FRAME_FILE,
            CHANGE_FRAME_DRAFT_FILE,
        }
    )


__all__ = [
    "ImplementationEvidenceVerdict",
    "evaluate_implementation_evidence_gate",
]
