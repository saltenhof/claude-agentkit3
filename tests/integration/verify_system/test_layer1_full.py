"""Integration: full Layer-1 run against a simulated story directory (AG3-042).

Wires the real ``StructuralChecker`` (full FK-27 §27.4 registry + ports) and
the registry-bound ``PolicyEngine`` over a simulated story dir with real
state-backend records and on-disk worker artefacts. Proves the end-to-end
Layer-1 path: a clean story PASSes; a broken BLOCKING stage FAILs and the
policy verdict is FAIL; an impact violation routes to ESCALATED.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import PolicyVerdict
from agentkit.state_backend.store import save_phase_snapshot, save_story_context
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.story_model import ChangeImpact
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.stage_registry import StageRegistry
from agentkit.verify_system.structural.checker import StructuralChecker
from agentkit.verify_system.structural.checks import BuildTestEvidence
from agentkit.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_STORY_ID = "ODIN-042"


def _ctx() -> StoryContext:
    return StoryContext(
        project_key="odin",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
    )


class _Tel:
    def __init__(
        self,
        counts: dict[tuple[str, str | None], int],
        *,
        scope_resolvable: bool = True,
    ) -> None:
        self._counts = counts
        self._scope_resolvable = scope_resolvable

    def count_events(
        self,
        story_dir: Path,
        *,
        story_id: str,
        event_type: str,
        role: str | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> int:
        del story_dir, story_id, project_key, run_id
        return self._counts.get((event_type, role), 0)

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        del story_dir
        return self._scope_resolvable


class _Bt:
    def __init__(self, ev: BuildTestEvidence | None) -> None:
        self._ev = ev

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        del story_dir
        return self._ev


class _Ev:
    def __init__(self, evidence: ChangeEvidence) -> None:
        self._evidence = evidence

    def collect(self, story_dir: Path) -> ChangeEvidence:
        del story_dir
        return self._evidence


def _system_evidence(actual: str) -> _Ev:
    """Clean SYSTEM change-evidence with the given measured actual impact."""
    return _Ev(
        ChangeEvidence(
            available=True,
            current_branch=f"story/{_STORY_ID}",
            commit_messages=(f"feat({_STORY_ID}): add feature",),
            pushed=True,
            secret_files=(),
            changed_files=("feature.py",),
            actual_impact=ChangeImpact(actual),
        )
    )


_GREEN_TEL = _Tel(
    {
        ("review_request", None): 2,
        ("review_compliant", None): 2,
        ("llm_call_complete", "qa_review"): 1,
        ("llm_call_complete", "semantic_review"): 1,
        ("llm_call_complete", "doc_fidelity"): 1,
    }
)
_GREEN_BT = _Bt(
    BuildTestEvidence(
        build_ok=True,
        tests_green=True,
        test_file_count=3,
        coverage_report_present=True,
        coverage_meets_threshold=True,
    )
)


def _simulate_story_dir(tmp_path: Path, *, declared: str) -> Path:
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = _ctx()
    save_story_context(story_dir, ctx)
    for phase in get_profile(ctx.story_type).phases:
        if phase == "implementation":
            break
        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id=_STORY_ID,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    (story_dir / "protocol.md").write_text("protocol body " * 10, encoding="utf-8")
    (story_dir / "feature.py").write_text("value = 42\n", encoding="utf-8")
    # FK-33 §33.5.2: branch/commit/push/actual-impact are SYSTEM evidence, not
    # the manifest. The manifest only carries the worker's DECLARED impact budget.
    (story_dir / "worker-manifest.json").write_text(
        json.dumps(
            {
                "story_id": _STORY_ID,
                "status": "DONE",
                "files": ["feature.py"],
                "declared_change_impact": declared,
            }
        ),
        encoding="utf-8",
    )
    (story_dir / "handover.json").write_text(
        json.dumps(
            {
                "changes_summary": "added feature",
                "increments": [
                    {"description": "f", "commit_sha": "a", "tests_added": []}
                ],
                "assumptions": [],
                "existing_tests": ["tests/test_feature.py::test_x"],
                "risks_for_qa": ["load"],
                "drift_log": [],
                "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
            }
        ),
        encoding="utf-8",
    )
    return story_dir


def _checker(actual_impact: str = "Component") -> StructuralChecker:
    return StructuralChecker(
        registry=StageRegistry(),
        telemetry=_GREEN_TEL,
        build_test_port=_GREEN_BT,
        change_evidence_port=_system_evidence(actual_impact),
    )


def test_clean_story_layer1_pass_and_policy_pass(tmp_path: Path) -> None:
    ctx = _ctx()
    story_dir = _simulate_story_dir(tmp_path, declared="Architecture Impact")
    layer1 = _checker().evaluate(ctx, story_dir)
    assert layer1.passed is True, [f.check + ":" + f.message for f in layer1.findings]

    decision = PolicyEngine().decide(
        [layer1], story_type=ctx.story_type, max_layer_reached=1
    )
    assert decision.verdict is PolicyVerdict.PASS


def test_broken_blocking_stage_drives_policy_fail(tmp_path: Path) -> None:
    ctx = _ctx()
    story_dir = _simulate_story_dir(tmp_path, declared="Architecture Impact")
    (story_dir / "protocol.md").unlink()  # break artifact.protocol (BLOCKING)

    layer1 = _checker().evaluate(ctx, story_dir)
    assert layer1.passed is False

    decision = PolicyEngine().decide(
        [layer1], story_type=ctx.story_type, max_layer_reached=1
    )
    assert decision.verdict is PolicyVerdict.FAIL
    assert any(f.check == "artifact.protocol" for f in decision.blocking_findings)


def test_impact_violation_escalates(tmp_path: Path) -> None:
    ctx = _ctx()
    story_dir = _simulate_story_dir(tmp_path, declared="Local")
    # SYSTEM-measured actual impact exceeds the declared budget -> ESCALATED.
    layer1 = _checker(actual_impact="Architecture Impact").evaluate(ctx, story_dir)
    assert layer1.passed is False
    assert layer1.metadata.get("escalated") is True

    decision = PolicyEngine().decide(
        [layer1], story_type=ctx.story_type, max_layer_reached=1
    )
    assert decision.verdict is PolicyVerdict.FAIL


def test_blocking_check_does_not_gate_on_worker_self_report(tmp_path: Path) -> None:
    """FIX-3 / FK-33 §33.5.2: a worker manifest claiming a clean branch/push

    must NOT make the BLOCKING checks pass when the SYSTEM evidence is
    unavailable. With no change-evidence provider (fail-closed default) the
    branch/commit/push checks FAIL even though the manifest declares them green.
    """
    ctx = _ctx()
    story_dir = _simulate_story_dir(tmp_path, declared="Architecture Impact")
    # Manifest declares everything green (the worker self-report).
    (story_dir / "worker-manifest.json").write_text(
        json.dumps(
            {
                "story_id": _STORY_ID,
                "status": "DONE",
                "files": ["feature.py"],
                "branch": f"story/{_STORY_ID}",
                "commits": [f"feat({_STORY_ID}): x"],
                "pushed": True,
                "declared_change_impact": "Architecture Impact",
                "actual_change_impact": "Local",
            }
        ),
        encoding="utf-8",
    )
    # No change-evidence provider wired -> the absent fail-closed default.
    checker = StructuralChecker(
        registry=StageRegistry(),
        telemetry=_GREEN_TEL,
        build_test_port=_GREEN_BT,
    )
    layer1 = checker.evaluate(ctx, story_dir)
    assert layer1.passed is False
    failed = {f.check for f in layer1.findings if f.severity.value == "BLOCKING"}
    # The BLOCKING branch/commit/push/secrets/impact checks fail closed despite
    # the manifest's green self-report -- they decided on system evidence.
    assert "branch.story" in failed
    assert "completion.push" in failed
    assert "impact.violation" in failed


def test_policy_fail_closed_when_layer1_result_absent(tmp_path: Path) -> None:
    """FK-33 §33.7: layer-1 traversed but no result reaches policy -> FAIL."""
    ctx = _ctx()
    decision = PolicyEngine().decide(
        [], story_type=ctx.story_type, max_layer_reached=1
    )
    assert decision.verdict is PolicyVerdict.FAIL
