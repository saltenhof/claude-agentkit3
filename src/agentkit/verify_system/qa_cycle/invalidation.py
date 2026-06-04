"""Cycle-bound QA-artefact invalidation (FK-27 §27.2.3).

When a new atomic QA cycle begins (``advance_qa_cycle()``), every cycle-bound
QA artefact written under ``_temp/qa/{story_id}/`` is moved to
``_temp/qa/{story_id}/stale/{old_epoch}/`` so it can never be consumed by a
later remediation round (FK-27 §27.2.3 "Artefakt-Invalidierung"). A missing
file is skipped without error; each successful move emits an
``artifact_invalidated`` invalidation record through the injected
:class:`ArtifactInvalidationSink`.

Pinned filename set (FK-27 §27.2.3 table). The prose says "11 Dateien" but the
normative table lists **12** rows; the table is operative, so all 12 are
pinned and the count discrepancy is recorded here and surfaced to the caller.
The contract test ``tests/contract/verify_system/test_qa_cycle.py`` pins this
exact tuple against FK-27 §27.2.3.

Quelle:
  - FK-27 §27.2.3 -- Artefakt-Invalidierung (Datei-Tabelle, ``stale/``-Move)
  - FK-27 §27.6a.3 -- ``sonarqube_gate.json`` ist zyklusgebunden
  - AG3-041 §2.1.3 -- Invalidierungslogik + ``artifact_invalidated``-Telemetrie
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.installer.paths import QA_DIR as _QA_DIR

if TYPE_CHECKING:
    from pathlib import Path

#: Story-relative root holding the cycle-bound QA artefacts (FK-27 §27.2.3).
#: SSOT: mirrors ``installer.paths.QA_DIR`` (no second path-string truth).
QA_ARTIFACT_SUBDIR = _QA_DIR

#: Sub-directory under the QA artefact root that receives invalidated files.
STALE_SUBDIR = "stale"

#: Canonical cycle-bound QA-artefact filenames, EXACTLY as listed in the
#: FK-27 §27.2.3 table (operative invalidation set). Order mirrors the table
#: top-to-bottom. NOTE (ZERO DEBT / FAIL-CLOSED): FK-27 §27.2.3 prose says
#: "11 Dateien" but the table enumerates 12 rows -- a concept count/table
#: inconsistency. The table is the operative artefact list, so all 12 entries
#: are pinned here; the discrepancy is reported upward, not silently resolved.
CYCLE_BOUND_QA_ARTIFACTS: tuple[str, ...] = (
    "semantic_review.json",
    "guardrail.json",
    "decision.json",
    "qa_review.json",
    "doc_fidelity.json",
    "feedback.json",
    "adversarial.json",
    "sonarqube_gate.json",
    "e2e_verify.json",
    "structural.json",
    "context.json",
    "context_sufficiency.json",
)


@dataclass(frozen=True)
class ArtifactInvalidationEvent:
    """An immutable fact: one cycle-bound artefact was moved to ``stale/``.

    Attributes:
        story_id: Story whose QA cycle advanced.
        filename: Cycle-bound artefact filename (FK-27 §27.2.3).
        old_epoch: Epoch the artefact belonged to before invalidation.
        source_path: Absolute path the artefact was moved FROM.
        stale_path: Absolute path the artefact was moved TO.
    """

    story_id: str
    filename: str
    old_epoch: int
    source_path: Path
    stale_path: Path


@runtime_checkable
class ArtifactInvalidationSink(Protocol):
    """Port receiving ``artifact_invalidated`` facts (FK-27 §27.2.3).

    The verify-system BC owns this port; the productive telemetry adapter is
    wired at the composition root (Closure/telemetry integration is a follow-up
    story). Keeping the sink behind a Protocol avoids a verify-system import of
    the telemetry BC for the AG3-041 mechanic.
    """

    def artifact_invalidated(self, event: ArtifactInvalidationEvent) -> None:
        """Record that a cycle-bound artefact was invalidated.

        Args:
            event: The invalidation fact (story, filename, epoch, paths).
        """
        ...


@dataclass(frozen=True)
class NullArtifactInvalidationSink:
    """No-op sink: drops invalidation events.

    Default for callers without a wired telemetry adapter (test paths,
    pre-integration). It is a recordable contract surface, not a swallow of QA
    truth -- the file move still happens; only the telemetry emission is inert.
    """

    def artifact_invalidated(self, event: ArtifactInvalidationEvent) -> None:
        """Drop the event (no-op).

        Args:
            event: The invalidation fact (ignored).
        """
        del event  # no-op sink intentionally ignores the event (S1172).


@dataclass(frozen=True)
class RecordingArtifactInvalidationSink:
    """In-memory sink collecting invalidation events for tests/diagnostics."""

    events: list[ArtifactInvalidationEvent]

    @classmethod
    def empty(cls) -> RecordingArtifactInvalidationSink:
        """Construct a sink with a fresh empty event list.

        Returns:
            A new recording sink.
        """
        return cls(events=[])

    def artifact_invalidated(self, event: ArtifactInvalidationEvent) -> None:
        """Append the event to the in-memory list.

        Args:
            event: The invalidation fact to record.
        """
        self.events.append(event)


def qa_artifact_dir(
    story_dir: Path, story_id: str, *, project_root: Path | None = None
) -> Path:
    """Return the cycle-bound QA-artefact directory for a story.

    SINGLE SOURCE OF TRUTH (AG3-041 E4): delegates to the canonical
    :func:`agentkit.installer.paths.resolve_qa_story_dir` so the invalidation
    writes to EXACTLY the directory the QA-subflow + phase handler write to.
    Reconstructing ``{story_dir}/_temp/qa/{story_id}`` locally would diverge
    whenever ``project_root != story_dir``.

    Args:
        story_dir: Story working directory (run root).
        story_id: Story display-ID (path segment, FK-27 §27.2.3).
        project_root: Optional explicit project root; when ``None`` the
            canonical resolver derives it from ``story_dir`` (a ``stories/``
            child) and otherwise treats ``story_dir`` as the run root.

    Returns:
        The canonical QA-artefact directory (``{root}/_temp/qa/{story_id}``).
    """
    from agentkit.installer.paths import resolve_qa_story_dir

    return resolve_qa_story_dir(
        story_dir, story_id=story_id, project_root=project_root
    )


def invalidate_cycle_artifacts(
    *,
    story_dir: Path,
    story_id: str,
    old_epoch: int,
    sink: ArtifactInvalidationSink,
    project_root: Path | None = None,
) -> tuple[ArtifactInvalidationEvent, ...]:
    """Move all cycle-bound QA artefacts to ``stale/{old_epoch}/`` (FK-27 §27.2.3).

    For each filename in :data:`CYCLE_BOUND_QA_ARTIFACTS` present in the
    story's QA artefact directory, the file is atomically moved into
    ``stale/{old_epoch}/`` and an :class:`ArtifactInvalidationEvent` is emitted
    via ``sink``. Missing files are skipped without error (FK-27 §27.2.3).

    Args:
        story_dir: Story working directory (run root).
        story_id: Story display-ID.
        old_epoch: Epoch the about-to-be-invalidated artefacts belong to.
        sink: Telemetry sink receiving one ``artifact_invalidated`` fact per
            moved file.
        project_root: Optional project root forwarded to the canonical QA-dir
            resolver (AG3-041 E4); ``None`` derives the root from ``story_dir``.

    Returns:
        Tuple of the emitted invalidation events (one per moved file). Empty
        when no cycle-bound artefact existed.
    """
    base = qa_artifact_dir(story_dir, story_id, project_root=project_root)
    stale_root = base / STALE_SUBDIR / str(old_epoch)

    emitted: list[ArtifactInvalidationEvent] = []
    for filename in CYCLE_BOUND_QA_ARTIFACTS:
        source = base / filename
        if not source.is_file():
            # FK-27 §27.2.3: missing file -> skip without error.
            continue
        stale_root.mkdir(parents=True, exist_ok=True)
        target = stale_root / filename
        _atomic_rename(source, target)
        event = ArtifactInvalidationEvent(
            story_id=story_id,
            filename=filename,
            old_epoch=old_epoch,
            source_path=source,
            stale_path=target,
        )
        sink.artifact_invalidated(event)
        emitted.append(event)

    return tuple(emitted)


def _atomic_rename(source: Path, target: Path) -> None:
    """Atomically move ``source`` onto ``target`` within the same directory tree.

    ``os.replace`` is atomic on POSIX and Windows for same-volume moves and
    overwrites an existing ``target`` (a leftover stale entry from a re-run).

    Args:
        source: Existing file to move.
        target: Destination path (overwritten if present).
    """
    os.replace(source, target)


__all__ = [
    "CYCLE_BOUND_QA_ARTIFACTS",
    "QA_ARTIFACT_SUBDIR",
    "STALE_SUBDIR",
    "ArtifactInvalidationEvent",
    "ArtifactInvalidationSink",
    "NullArtifactInvalidationSink",
    "RecordingArtifactInvalidationSink",
    "invalidate_cycle_artifacts",
    "qa_artifact_dir",
]
