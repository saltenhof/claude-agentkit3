"""Unit tests for ConflictFreezeOverlay dual persistence + overlay (FK-55 §55.8/§55.10.5/§55.10.6, AK6)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.principal_capabilities import (
    CapabilityDecision,
    CapabilityVerdict,
    ConflictFreezeOverlay,
    OperationClass,
    Principal,
)
from agentkit.backend.governance.principal_capabilities.errors import FreezePersistenceError
from agentkit.backend.governance.principal_capabilities.freeze import FREEZE_EXPORT_RELPATH
from agentkit.backend.state_backend.store.freeze_repository import (
    FreezeRepository,
    LocalFreezeJsonExport,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY = "AG3-001"


def _overlay(tmp_path: Path) -> ConflictFreezeOverlay:
    # Production wiring: BOTH the backend store AND the local export (FK-55
    # §55.10.5 dual materialization).
    return ConflictFreezeOverlay(
        FreezeRepository(tmp_path),
        local_export=LocalFreezeJsonExport(tmp_path),
    )


def test_freeze_writes_both_backend_and_local_export(tmp_path: Path) -> None:
    # AK6: dual persistence — backend record (truth) + local freeze.json.
    overlay = _overlay(tmp_path)
    overlay.freeze(_STORY, reason="normative_conflict", freeze_version=1)

    # Backend truth.
    record = FreezeRepository(tmp_path).read_freeze(_STORY)
    assert record is not None
    assert record.freeze_reason == "normative_conflict"
    assert record.freeze_version == 1

    # Local export with matching freeze_version (FK-31 §31.2.7).
    export = tmp_path / FREEZE_EXPORT_RELPATH
    assert export.exists()
    payload = json.loads(export.read_text(encoding="utf-8"))
    assert payload["story_id"] == _STORY
    assert payload["freeze_version"] == 1


def test_is_frozen_requires_both_materializations(tmp_path: Path) -> None:
    # ERROR 6 / FK-55 §55.10.5: BOTH the backend record AND the local export are
    # consulted. When both agree there is no freeze → not frozen.
    overlay = _overlay(tmp_path)
    assert overlay.is_frozen(_STORY) is False
    overlay.freeze(_STORY, reason="hard_stop", freeze_version=2)
    assert overlay.is_frozen(_STORY) is True


def test_is_frozen_fail_closed_when_local_export_missing(tmp_path: Path) -> None:
    # ERROR 6 / FK-55 §55.10.5: a backend freeze WITHOUT the matching local
    # export is a stale/incomplete context → fail-closed (treated as frozen).
    repo = FreezeRepository(tmp_path)
    repo.set_freeze(
        _STORY, frozen_at="t", freeze_reason="hard_stop", freeze_version=1
    )
    # No local export written → disagreement → fail-closed frozen.
    overlay = _overlay(tmp_path)
    assert overlay.is_frozen(_STORY) is True


def test_is_frozen_fail_closed_when_backend_missing_but_export_present(
    tmp_path: Path,
) -> None:
    # ERROR 6: a local export WITHOUT a backend record is also a disagreement →
    # fail-closed frozen.
    LocalFreezeJsonExport(tmp_path).write(
        _STORY, frozen_at="t", freeze_reason="hard_stop", freeze_version=1
    )
    overlay = _overlay(tmp_path)
    assert overlay.is_frozen(_STORY) is True


def test_is_frozen_corrupt_local_export_raises(tmp_path: Path) -> None:
    # ERROR 6 / FAIL-CLOSED: a corrupt local export is a fault, not a soft pass.
    repo = FreezeRepository(tmp_path)
    repo.set_freeze(
        _STORY, frozen_at="t", freeze_reason="hard_stop", freeze_version=1
    )
    export = tmp_path / FREEZE_EXPORT_RELPATH
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_text("{ this is not json", encoding="utf-8")
    overlay = _overlay(tmp_path)
    with pytest.raises(FreezePersistenceError):
        overlay.is_frozen(_STORY)


def test_release_clears_both_paths(tmp_path: Path) -> None:
    overlay = _overlay(tmp_path)
    overlay.freeze(_STORY, reason="hard_stop", freeze_version=1)
    overlay.release(_STORY)
    assert overlay.is_frozen(_STORY) is False
    assert FreezeRepository(tmp_path).read_freeze(_STORY) is None
    assert not (tmp_path / FREEZE_EXPORT_RELPATH).exists()


def test_export_only_overlay_uses_local_freeze(tmp_path: Path) -> None:
    # AK6: with no backend store the local export is the sole record path
    # (degraded single-side wiring; the present side is authoritative).
    overlay = ConflictFreezeOverlay(
        store=None, local_export=LocalFreezeJsonExport(tmp_path)
    )
    overlay.freeze(_STORY, reason="hard_stop", freeze_version=1)
    assert overlay.is_frozen(_STORY) is True


def test_apply_overrides_allow_for_orchestrator_mutation(tmp_path: Path) -> None:
    # AK6 + FK-55 §55.10.6: freeze turns an ALLOW into DENY for orchestrator
    # mutations.
    overlay = _overlay(tmp_path)
    overlay.freeze(_STORY, reason="normative_conflict", freeze_version=1)
    base = CapabilityVerdict.allow("base allow")
    result = overlay.apply(base, Principal.ORCHESTRATOR, _STORY, OperationClass.WRITE)
    assert result.decision is CapabilityDecision.DENY


def test_apply_overrides_allow_for_worker_write(tmp_path: Path) -> None:
    # FK-55 §55.8.1: frozen worker may not create new productive progress.
    overlay = _overlay(tmp_path)
    overlay.freeze(_STORY, reason="hard_stop", freeze_version=1)
    base = CapabilityVerdict.allow("base allow")
    result = overlay.apply(base, Principal.WORKER, _STORY, OperationClass.WRITE)
    assert result.decision is CapabilityDecision.DENY


def test_apply_allows_official_principal_during_freeze(tmp_path: Path) -> None:
    # FK-55 §55.8.1: human_cli / pipeline_deterministic / admin_service continue.
    overlay = _overlay(tmp_path)
    overlay.freeze(_STORY, reason="hard_stop", freeze_version=1)
    base = CapabilityVerdict.allow("base allow")
    for principal in (
        Principal.HUMAN_CLI,
        Principal.PIPELINE_DETERMINISTIC,
        Principal.ADMIN_SERVICE,
    ):
        result = overlay.apply(base, principal, _STORY, OperationClass.WRITE)
        assert result.decision is CapabilityDecision.ALLOW


def test_apply_does_not_elevate_base_deny(tmp_path: Path) -> None:
    # FK-55 invariant: a freeze never turns DENY into ALLOW.
    overlay = _overlay(tmp_path)
    base = CapabilityVerdict.deny("matrix deny")
    result = overlay.apply(base, Principal.WORKER, _STORY, OperationClass.WRITE)
    assert result.decision is CapabilityDecision.DENY


def test_apply_leaves_read_unaffected(tmp_path: Path) -> None:
    # Freeze blocks mutations only; reads are not new productive progress.
    overlay = _overlay(tmp_path)
    overlay.freeze(_STORY, reason="hard_stop", freeze_version=1)
    base = CapabilityVerdict.allow("read allow")
    result = overlay.apply(base, Principal.WORKER, _STORY, OperationClass.READ)
    assert result.decision is CapabilityDecision.ALLOW
