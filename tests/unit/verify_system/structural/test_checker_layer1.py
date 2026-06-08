"""StructuralChecker full Layer-1 path (FK-27 §27.4 via StageRegistry).

Proves the registry-driven path: a wired ``StructuralChecker`` actually
invokes EVERY Layer-1 stage check, a BLOCKING finding drives
``LayerResult.passed=False``, and an impact violation stamps the ESCALATED
metadata (FK-27 §27.4.5). Uses real state-backend records + ``tmp_path``;
telemetry / build-test / ARE evidence via in-test port doubles.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.pipeline_engine.phase_executor.models import PhaseSnapshot, PhaseStatus
from agentkit.state_backend.store import save_phase_snapshot, save_story_context
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import ChangeImpact
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.verify_system.protocols import Severity
from agentkit.verify_system.stage_registry import StageRegistry
from agentkit.verify_system.structural.checker import (
    FULL_STAGE_REGISTRY,
    StructuralChecker,
)
from agentkit.verify_system.structural.checks import BuildTestEvidence
from agentkit.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "TEST-001"


def _ctx(story_type: StoryType = StoryType.IMPLEMENTATION) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=story_type,
        execution_route=(
            StoryMode.EXPLORATION
            if story_type is StoryType.IMPLEMENTATION
            else StoryMode.EXECUTION
        ),
    )


def _story_dir(root: Path) -> Path:
    d = root / "stories" / _STORY_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seed_state(story_dir: Path, ctx: StoryContext) -> None:
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


_GREEN = BuildTestEvidence(
    build_ok=True,
    tests_green=True,
    test_file_count=2,
    coverage_report_present=True,
    coverage_meets_threshold=True,
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
    """In-test ``ChangeEvidencePort`` double: returns a fixed ``ChangeEvidence``."""

    def __init__(self, evidence: ChangeEvidence) -> None:
        self._evidence = evidence

    def collect(self, story_dir: Path) -> ChangeEvidence:
        del story_dir
        return self._evidence


def _clean_evidence(actual_impact: ChangeImpact = ChangeImpact.LOCAL) -> _Ev:
    """A clean SYSTEM change-evidence double (branch/commit/push OK, no secrets)."""
    return _Ev(
        ChangeEvidence(
            available=True,
            current_branch=f"story/{_STORY_ID}",
            commit_messages=(f"feat: {_STORY_ID} do work",),
            pushed=True,
            secret_files=(),
            changed_files=("made.py",),
            actual_impact=actual_impact,
        )
    )


def _all_green_tel() -> _Tel:
    return _Tel(
        {
            ("review_request", None): 1,
            ("review_compliant", None): 1,
            ("llm_call_complete", "qa_review"): 1,
            ("llm_call_complete", "semantic_review"): 1,
            ("llm_call_complete", "doc_fidelity"): 1,
        }
    )


def _write_clean_worker_artifacts(story_dir: Path) -> None:
    (story_dir / "protocol.md").write_text("p" * 100, encoding="utf-8")
    (story_dir / "made.py").write_text("x = 1\n", encoding="utf-8")
    # FK-33 §33.5.2: branch/commit/push are now SYSTEM evidence (not the
    # manifest). The manifest carries only the worker-DECLARED impact budget
    # (legitimate; the SYSTEM measures the actual impact).
    manifest = {
        "story_id": _STORY_ID,
        "status": "DONE",
        "files": ["made.py"],
        "declared_change_impact": "Architecture Impact",
    }
    (story_dir / "worker-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    # Full FK-26 §26.7.3 handover contract.
    (story_dir / "handover.json").write_text(
        json.dumps(
            {
                "changes_summary": "made it",
                "increments": [
                    {"description": "i", "commit_sha": "a", "tests_added": []}
                ],
                "assumptions": [],
                "existing_tests": ["tests/test_made.py::test_x"],
                "risks_for_qa": ["edge case"],
                "drift_log": [],
                "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
            }
        ),
        encoding="utf-8",
    )


def _full_checker(evidence: _Ev | None = None) -> StructuralChecker:
    return StructuralChecker(
        registry=FULL_STAGE_REGISTRY,
        telemetry=_all_green_tel(),
        build_test_port=_Bt(_GREEN),
        change_evidence_port=evidence or _clean_evidence(),
    )


class TestFullLayer1Path:
    def test_clean_story_passes_all_stages(self, tmp_path: Path) -> None:
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        _seed_state(story_dir, ctx)
        _write_clean_worker_artifacts(story_dir)

        result = _full_checker().evaluate(ctx, story_dir)
        assert result.passed is True, [f.check + ":" + f.message for f in result.findings]
        # Every applicable Layer-1 stage was run (pre-checks + stages).
        assert int(result.metadata["total_checks"]) >= 21

    def test_every_registry_stage_is_dispatched(self, tmp_path: Path) -> None:
        """ZERO DEBT: every Layer-1 registry stage has a wired check (no dead).

        Running the checker against an empty story dir must produce a finding
        for EACH blocking stage id (the dispatch raises KeyError if a stage is
        unwired), proving none is dead code.
        """
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        # No state, no artifacts -> everything fails, but nothing raises.
        result = StructuralChecker(
            registry=FULL_STAGE_REGISTRY,
        ).evaluate(ctx, story_dir)
        checks = {f.check for f in result.findings}
        # A representative stage per FK-27 §27.4 category is present.
        for stage_id in (
            "artifact.protocol",
            "branch.story",
            "build.compile",
            "guard.llm_reviews",
            "guard.multi_llm",
            "impact.violation",
        ):
            assert stage_id in checks, stage_id

    def test_blocking_finding_drives_passed_false(self, tmp_path: Path) -> None:
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        _seed_state(story_dir, ctx)
        _write_clean_worker_artifacts(story_dir)
        # Break exactly one BLOCKING stage: remove protocol.md.
        (story_dir / "protocol.md").unlink()

        result = _full_checker().evaluate(ctx, story_dir)
        assert result.passed is False
        assert any(
            f.check == "artifact.protocol" and f.severity is Severity.BLOCKING
            for f in result.findings
        )

    def test_major_only_finding_keeps_passed_true(self, tmp_path: Path) -> None:
        """A MAJOR-only finding (test.count) does NOT set passed=False.

        passed reflects "no BLOCKING finding" (FK-27 §27.4.2); MAJOR/MINOR
        are collected for the policy aggregation, they do not block the layer.
        """
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        _seed_state(story_dir, ctx)
        _write_clean_worker_artifacts(story_dir)
        checker = StructuralChecker(
            registry=FULL_STAGE_REGISTRY,
            telemetry=_all_green_tel(),
            build_test_port=_Bt(
                BuildTestEvidence(
                    build_ok=True,
                    tests_green=True,
                    test_file_count=0,  # MAJOR test.count finding
                    coverage_report_present=True,
                    coverage_meets_threshold=True,
                )
            ),
            change_evidence_port=_clean_evidence(),
        )
        result = checker.evaluate(ctx, story_dir)
        assert result.passed is True
        assert any(
            f.check == "test.count" and f.severity is Severity.MAJOR
            for f in result.findings
        )

    def test_impact_violation_stamps_escalated_metadata(self, tmp_path: Path) -> None:
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        _seed_state(story_dir, ctx)
        _write_clean_worker_artifacts(story_dir)
        # Declare a small budget in the manifest, but the SYSTEM evidence
        # measures a large actual impact (FK-23 §23.8 violation).
        manifest_path = story_dir / "worker-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["declared_change_impact"] = "Local"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        evidence = _clean_evidence(actual_impact=ChangeImpact.ARCHITECTURE_IMPACT)
        result = _full_checker(evidence).evaluate(ctx, story_dir)
        assert result.passed is False
        assert result.metadata.get("escalated") is True

    def test_are_stage_skipped_when_disabled(self, tmp_path: Path) -> None:
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        _seed_state(story_dir, ctx)
        _write_clean_worker_artifacts(story_dir)
        result = _full_checker().evaluate(ctx, story_dir)
        # ARE disabled by default -> no are.gate finding even on a clean story.
        assert not any(f.check == "are.gate" for f in result.findings)


class TestMetaOnlyDefault:
    def test_bare_checker_runs_meta_only(self, tmp_path: Path) -> None:
        """A bare StructuralChecker() runs only the meta pre-checks (no stages)."""
        ctx = _ctx()
        story_dir = _story_dir(tmp_path)
        _seed_state(story_dir, ctx)
        result = StructuralChecker().evaluate(ctx, story_dir)
        # Meta-only: no FK-27 §27.4 stage findings; clean state -> passes.
        assert result.passed is True
        assert not any("." in f.check for f in result.findings)

    def test_empty_registry_constant_is_empty(self) -> None:
        assert StageRegistry(stages=()).stages_for(StoryType.IMPLEMENTATION) == []
