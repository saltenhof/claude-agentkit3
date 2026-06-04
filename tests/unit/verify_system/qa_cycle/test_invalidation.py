"""Unit tests for cycle-bound artefact invalidation (FK-27 §27.2.3).

Proves AG3-041 AC2 (artefacts moved to ``stale/{old_epoch}/``) and the
``artifact_invalidated`` telemetry emission, plus the "missing file -> skip
without error" rule. Operates on a real ``tmp_path`` filesystem (no mock FS).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.verify_system.qa_cycle.invalidation import (
    CYCLE_BOUND_QA_ARTIFACTS,
    RecordingArtifactInvalidationSink,
    invalidate_cycle_artifacts,
    qa_artifact_dir,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "AG3-041"


def _write_all_artifacts(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for name in CYCLE_BOUND_QA_ARTIFACTS:
        (base / name).write_text("{}", encoding="utf-8")


class TestInvalidateAllArtifacts:
    def test_all_present_artifacts_move_to_stale(self, tmp_path: Path) -> None:
        base = qa_artifact_dir(tmp_path, _STORY_ID)
        _write_all_artifacts(base)

        events = invalidate_cycle_artifacts(
            story_dir=tmp_path,
            story_id=_STORY_ID,
            old_epoch=1,
            sink=RecordingArtifactInvalidationSink.empty(),
        )

        assert len(events) == len(CYCLE_BOUND_QA_ARTIFACTS)
        stale = base / "stale" / "1"
        for name in CYCLE_BOUND_QA_ARTIFACTS:
            assert not (base / name).exists(), f"{name} should be moved away"
            assert (stale / name).is_file(), f"{name} should be in stale/1"

    def test_telemetry_emitted_per_moved_file(self, tmp_path: Path) -> None:
        base = qa_artifact_dir(tmp_path, _STORY_ID)
        _write_all_artifacts(base)
        sink = RecordingArtifactInvalidationSink.empty()

        invalidate_cycle_artifacts(
            story_dir=tmp_path, story_id=_STORY_ID, old_epoch=2, sink=sink
        )

        assert len(sink.events) == len(CYCLE_BOUND_QA_ARTIFACTS)
        emitted_names = {e.filename for e in sink.events}
        assert emitted_names == set(CYCLE_BOUND_QA_ARTIFACTS)
        for event in sink.events:
            assert event.story_id == _STORY_ID
            assert event.old_epoch == 2  # noqa: PLR2004
            assert event.stale_path.parent.name == "2"


class TestInvalidateSkipsMissing:
    def test_missing_file_skipped_without_error(self, tmp_path: Path) -> None:
        base = qa_artifact_dir(tmp_path, _STORY_ID)
        base.mkdir(parents=True, exist_ok=True)
        # Only two of the cycle-bound artefacts exist.
        (base / "structural.json").write_text("{}", encoding="utf-8")
        (base / "decision.json").write_text("{}", encoding="utf-8")

        events = invalidate_cycle_artifacts(
            story_dir=tmp_path,
            story_id=_STORY_ID,
            old_epoch=1,
            sink=RecordingArtifactInvalidationSink.empty(),
        )

        assert {e.filename for e in events} == {"structural.json", "decision.json"}

    def test_no_artifacts_returns_empty(self, tmp_path: Path) -> None:
        events = invalidate_cycle_artifacts(
            story_dir=tmp_path,
            story_id=_STORY_ID,
            old_epoch=1,
            sink=RecordingArtifactInvalidationSink.empty(),
        )
        assert events == ()
