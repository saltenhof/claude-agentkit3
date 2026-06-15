"""Unit tests for the real stability_gate producer (AG3-069 ERROR C, AC5/AC12).

The producer is the REAL Layer-4 stability_gate artefact producer. It evaluates
reached integration_targets, undeclared_surface and budget, produces a Layer-4
LayerResult the PolicyEngine aggregates, persists the gate verdict the closure
precondition reads, and emits the stability_gate_passed event on PASS.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.core_types import Severity
from agentkit.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.integration_stabilization.stability_gate_producer import (
    IS_STABILITY_GATE_FILE,
    IS_TARGETS_FILE,
    produce_stability_gate_layer_result,
)
from agentkit.integration_stabilization.state import (
    save_integration_manifest,
    save_manifest_approval,
)
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path

_STORY = "IS-69"
_RUN = "run-is69"


def _caps() -> StabilizationBudgetCaps:
    return StabilizationBudgetCaps(
        max_loops=3,
        max_new_surfaces=2,
        max_contract_changes=1,
        max_regressions_per_cycle=1,
    )


def _manifest(targets: tuple[str, ...] = ("e2e_login",)) -> IntegrationScopeManifest:
    return IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id=_STORY,
        implementation_contract="integration_stabilization",
        target_seams=("src/api/",),
        allowed_repos_paths=("wt/",),
        integration_targets=targets,
        allowed_contract_changes=(),
        stabilization_budget=_caps(),
    )


def _approval(m: IntegrationScopeManifest) -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=m.project_key,
        story_id=m.story_id,
        run_id=_RUN,
        manifest_version=m.version,
        manifest_hash=m.content_hash,
    )


def _setup(tmp_path: Path, *, targets: tuple[str, ...] = ("e2e_login",)) -> Path:
    story_dir = tmp_path / _STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    m = _manifest(targets)
    save_integration_manifest(story_dir, m)
    save_manifest_approval(story_dir, _approval(m))
    return story_dir


class TestStabilityGateProducer:
    def test_blocks_without_manifest(self, tmp_path: Path) -> None:
        story_dir = tmp_path / _STORY
        story_dir.mkdir(parents=True, exist_ok=True)
        result = produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=(),
            story_id=_STORY,
            project_key="PROJ",
        )
        assert result.passed is False
        assert any(f.severity is Severity.BLOCKING for f in result.findings)
        # The Layer-4 result marks the IS Layer-4 stages produced.
        assert "stability_gate" in result.metadata["stage_ids"]

    def test_passes_when_targets_reached_and_surfaces_declared(
        self, tmp_path: Path
    ) -> None:
        story_dir = _setup(tmp_path)
        (story_dir / IS_TARGETS_FILE).write_text(
            json.dumps({"achieved_targets": ["e2e_login"]}), encoding="utf-8"
        )
        result = produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=("src/api/handler.py",),
            story_id=_STORY,
            project_key="PROJ",
        )
        assert result.passed is True
        assert result.findings == ()

    def test_fails_on_undeclared_surface(self, tmp_path: Path) -> None:
        story_dir = _setup(tmp_path)
        (story_dir / IS_TARGETS_FILE).write_text(
            json.dumps({"achieved_targets": ["e2e_login"]}), encoding="utf-8"
        )
        result = produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=("src/unrelated/hack.py",),
            story_id=_STORY,
            project_key="PROJ",
        )
        assert result.passed is False

    def test_fails_on_unmet_targets(self, tmp_path: Path) -> None:
        story_dir = _setup(tmp_path, targets=("e2e_login", "e2e_checkout"))
        (story_dir / IS_TARGETS_FILE).write_text(
            json.dumps({"achieved_targets": ["e2e_login"]}), encoding="utf-8"
        )
        result = produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=("src/api/handler.py",),
            story_id=_STORY,
            project_key="PROJ",
        )
        assert result.passed is False

    def test_persists_gate_verdict_for_closure(self, tmp_path: Path) -> None:
        story_dir = _setup(tmp_path)
        (story_dir / IS_TARGETS_FILE).write_text(
            json.dumps({"achieved_targets": ["e2e_login"]}), encoding="utf-8"
        )
        produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=("src/api/handler.py",),
            story_id=_STORY,
            project_key="PROJ",
        )
        gate_file = story_dir / IS_STABILITY_GATE_FILE
        assert gate_file.exists()
        data = json.loads(gate_file.read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["achieved_targets"] == ["e2e_login"]

    def test_emits_stability_gate_passed_event_on_pass(self, tmp_path: Path) -> None:
        story_dir = _setup(tmp_path)
        (story_dir / IS_TARGETS_FILE).write_text(
            json.dumps({"achieved_targets": ["e2e_login"]}), encoding="utf-8"
        )
        emitter = MemoryEmitter()
        produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=("src/api/handler.py",),
            emitter=emitter,
            story_id=_STORY,
            project_key="PROJ",
        )
        events = emitter.query(_STORY, EventType.STABILITY_GATE_PASSED)
        assert len(events) == 1
        assert events[0].run_id == _RUN

    def test_no_event_on_fail(self, tmp_path: Path) -> None:
        story_dir = _setup(tmp_path)
        emitter = MemoryEmitter()
        produce_stability_gate_layer_result(
            story_dir=story_dir,
            run_id=_RUN,
            touched_paths=("src/api/handler.py",),
            emitter=emitter,
            story_id=_STORY,
            project_key="PROJ",
        )
        assert emitter.query(_STORY, EventType.STABILITY_GATE_PASSED) == []
