"""SQLite roundtrip tests for FreezeRepository (AG3-032, FK-55 §55.8).

Unit path is SQLite-only (tests/unit/conftest.py forces sqlite + drops the
Postgres DSN). Verifies governance_freeze_records set/read/clear + upsert.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.state_backend.store.freeze_repository import (
    FreezeRecord,
    FreezeRepository,
    LocalFreezeJsonExport,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY = "AG3-001"


def test_set_then_read_roundtrip(tmp_path: Path) -> None:
    repo = FreezeRepository(tmp_path)
    repo.set_freeze(
        _STORY, frozen_at="2026-06-02T00:00:00+00:00",
        freeze_reason="normative_conflict", freeze_version=1,
    )
    record = repo.read_freeze(_STORY)
    assert record == FreezeRecord(
        story_id=_STORY,
        frozen_at="2026-06-02T00:00:00+00:00",
        freeze_reason="normative_conflict",
        freeze_version=1,
    )


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert FreezeRepository(tmp_path).read_freeze("missing") is None


def test_set_is_upsert_on_story_id(tmp_path: Path) -> None:
    repo = FreezeRepository(tmp_path)
    repo.set_freeze(
        _STORY, frozen_at="t1", freeze_reason="r1", freeze_version=1
    )
    repo.set_freeze(
        _STORY, frozen_at="t2", freeze_reason="r2", freeze_version=2
    )
    record = repo.read_freeze(_STORY)
    assert record is not None
    assert record.freeze_version == 2
    assert record.freeze_reason == "r2"


def test_clear_removes_record(tmp_path: Path) -> None:
    repo = FreezeRepository(tmp_path)
    repo.set_freeze(_STORY, frozen_at="t", freeze_reason="r", freeze_version=1)
    assert repo.clear_freeze(_STORY) == 1
    assert repo.read_freeze(_STORY) is None
    assert repo.clear_freeze(_STORY) == 0


def test_local_freeze_export_write_read_remove(tmp_path: Path) -> None:
    # AG3-032 ERROR 8: the local freeze.json export boundary (state_backend side,
    # so principal_capabilities never imports utils.io — AK10). FK-55 §55.10.5.
    export = LocalFreezeJsonExport(tmp_path)
    assert export.read() is None
    export.write(
        _STORY, frozen_at="t", freeze_reason="normative_conflict", freeze_version=3
    )
    payload = export.read()
    assert payload is not None
    assert payload["story_id"] == _STORY
    assert payload["freeze_version"] == 3
    export.remove()
    assert export.read() is None
    # remove() on an absent export is a no-op (idempotent).
    export.remove()
