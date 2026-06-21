"""Unit tests for the FK-27 §27.4 Layer-1 check functions (PASS + finding).

Each check is tested for both a PASS (returns ``None``) and a specific
finding path. Real components + ``tmp_path`` (no mocks); the telemetry /
build-test / ARE evidence are provided via simple in-test recording doubles
of the published ports (a unit otherwise impossible to isolate).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.core_types import Severity
from agentkit.backend.requirements_coverage.contract import (
    AreDockpointStatus,
    CoverageVerdict,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.protocols import TrustClass
from agentkit.backend.verify_system.structural.checks import (
    BuildTestEvidence,
    ChangeEvidence,
    check_are_gate,
    check_artifact_handover,
    check_artifact_manifest_claims,
    check_artifact_protocol,
    check_artifact_worker_manifest,
    check_branch_commit_trailers,
    check_branch_story,
    check_build_compile,
    check_build_test_execution,
    check_completion_commit,
    check_completion_push,
    check_guard_llm_reviews,
    check_guard_multi_llm,
    check_guard_no_violations,
    check_guard_review_compliance,
    check_hygiene_commented_code,
    check_hygiene_disabled_tests,
    check_hygiene_todo_fixme,
    check_impact_violation,
    check_test_count,
    check_test_coverage,
)

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "TEST-001"


def _ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _write_manifest(story_dir: Path, **extra: object) -> None:
    payload: dict[str, object] = {
        "story_id": _STORY_ID,
        "status": "DONE",
        "files": [],
    }
    payload.update(extra)
    (story_dir / "worker-manifest.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


# --- Telemetry / build-test / ARE recording doubles ------------------------


class _FakeTelemetry:
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


class _FakeBuildTest:
    def __init__(self, evidence: BuildTestEvidence | None) -> None:
        self._evidence = evidence

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        del story_dir
        return self._evidence


_GREEN_EVIDENCE = BuildTestEvidence(
    build_ok=True,
    tests_green=True,
    test_file_count=2,
    coverage_report_present=True,
    coverage_meets_threshold=True,
)


# --- Artifact checks (FK-27 §27.4.1) ---------------------------------------


class TestArtifactProtocol:
    def test_pass(self, tmp_path: Path) -> None:
        (tmp_path / "protocol.md").write_text("x" * 100, encoding="utf-8")
        assert (
            check_artifact_protocol(_ctx(), tmp_path, severity=Severity.BLOCKING)
            is None
        )

    def test_missing(self, tmp_path: Path) -> None:
        f = check_artifact_protocol(_ctx(), tmp_path, severity=Severity.BLOCKING)
        assert f is not None
        assert f.check == "artifact.protocol"
        assert f.severity is Severity.BLOCKING
        assert f.trust_class is TrustClass.SYSTEM

    def test_too_small(self, tmp_path: Path) -> None:
        (tmp_path / "protocol.md").write_text("tiny", encoding="utf-8")
        f = check_artifact_protocol(_ctx(), tmp_path, severity=Severity.BLOCKING)
        assert f is not None


class TestArtifactWorkerManifest:
    def test_pass(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path)
        assert (
            check_artifact_worker_manifest(
                _ctx(), tmp_path, severity=Severity.BLOCKING
            )
            is None
        )

    def test_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "worker-manifest.json").write_text("not json", encoding="utf-8")
        f = check_artifact_worker_manifest(
            _ctx(), tmp_path, severity=Severity.BLOCKING
        )
        assert f is not None
        assert f.check == "artifact.worker_manifest"


class TestArtifactManifestClaims:
    def test_pass(self, tmp_path: Path) -> None:
        (tmp_path / "made.py").write_text("x", encoding="utf-8")
        _write_manifest(tmp_path, files=["made.py"])
        assert (
            check_artifact_manifest_claims(
                _ctx(), tmp_path, severity=Severity.BLOCKING
            )
            is None
        )

    def test_declared_file_missing(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, files=["ghost.py"])
        f = check_artifact_manifest_claims(
            _ctx(), tmp_path, severity=Severity.BLOCKING
        )
        assert f is not None
        assert "ghost.py" in f.message


def _full_handover() -> dict[str, object]:
    """A complete FK-26 §26.7.3 handover payload (all 7 mandatory fields)."""
    return {
        "changes_summary": "implemented X",
        "increments": [{"description": "i1", "commit_sha": "abc", "tests_added": []}],
        "assumptions": [],
        "existing_tests": ["tests/test_x.py::test_y"],
        "risks_for_qa": ["race condition not tested"],
        "drift_log": [],
        "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
    }


class TestArtifactHandover:
    def test_pass(self, tmp_path: Path) -> None:
        (tmp_path / "handover.json").write_text(
            json.dumps(_full_handover()), encoding="utf-8"
        )
        assert (
            check_artifact_handover(_ctx(), tmp_path, severity=Severity.BLOCKING)
            is None
        )

    def test_schema_invalid_missing_field(self, tmp_path: Path) -> None:
        # FK-26 §26.7.3: a reduced placeholder payload (story_id/status only) is
        # NOT a valid handover -- the full contract is required.
        (tmp_path / "handover.json").write_text(
            json.dumps({"story_id": _STORY_ID, "status": "DONE"}), encoding="utf-8"
        )
        f = check_artifact_handover(_ctx(), tmp_path, severity=Severity.BLOCKING)
        assert f is not None
        assert "changes_summary" in f.message
        assert "acceptance_criteria_status" in f.message

    def test_partial_handover_missing_one_field(self, tmp_path: Path) -> None:
        payload = _full_handover()
        del payload["risks_for_qa"]
        (tmp_path / "handover.json").write_text(json.dumps(payload), encoding="utf-8")
        f = check_artifact_handover(_ctx(), tmp_path, severity=Severity.BLOCKING)
        assert f is not None
        assert "risks_for_qa" in f.message


# --- Branch & completion checks (FK-27 §27.4.2 / FK-33 §33.3.2) -------------
# FIX-3 (FK-33 §33.5.2): these BLOCKING checks decide on INDEPENDENT system
# evidence (ChangeEvidence), NOT the worker manifest.


def _evidence(
    *,
    available: bool = True,
    branch: str | None = None,
    commits: tuple[str, ...] = (),
    pushed: bool = False,
    secret_files: tuple[str, ...] = (),
    changed_files: tuple[str, ...] = (),
    actual_impact: ChangeImpact | None = None,
) -> ChangeEvidence:
    return ChangeEvidence(
        available=available,
        current_branch=branch,
        commit_messages=commits,
        pushed=pushed,
        secret_files=secret_files,
        changed_files=changed_files,
        actual_impact=actual_impact,
    )


class TestBranchChecks:
    def test_branch_story_pass(self, tmp_path: Path) -> None:
        ev = _evidence(branch=f"story/{_STORY_ID}")
        assert (
            check_branch_story(
                _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
            )
            is None
        )

    def test_branch_story_wrong(self, tmp_path: Path) -> None:
        ev = _evidence(branch="main")
        f = check_branch_story(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None
        assert f.check == "branch.story"

    def test_branch_unconfirmable_fails_closed(self, tmp_path: Path) -> None:
        ev = _evidence(available=False)
        f = check_branch_story(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None
        assert f.severity is Severity.BLOCKING

    def test_commit_trailers_pass(self, tmp_path: Path) -> None:
        ev = _evidence(commits=(f"feat: {_STORY_ID} do work",))
        assert (
            check_branch_commit_trailers(
                _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
            )
            is None
        )

    def test_commit_trailers_untagged(self, tmp_path: Path) -> None:
        ev = _evidence(commits=("feat: untagged",))
        f = check_branch_commit_trailers(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None

    def test_completion_commit_pass(self, tmp_path: Path) -> None:
        ev = _evidence(commits=("c1",))
        assert (
            check_completion_commit(
                _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
            )
            is None
        )

    def test_completion_commit_none(self, tmp_path: Path) -> None:
        ev = _evidence(commits=())
        f = check_completion_commit(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None

    def test_completion_push_pass(self, tmp_path: Path) -> None:
        ev = _evidence(pushed=True)
        assert (
            check_completion_push(
                _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
            )
            is None
        )

    def test_completion_push_not_pushed(self, tmp_path: Path) -> None:
        ev = _evidence(pushed=False)
        f = check_completion_push(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None


# --- Build & test checks (FK-27 §27.4.2) -----------------------------------


class TestBuildTestChecks:
    def test_build_compile_pass(self, tmp_path: Path) -> None:
        port = _FakeBuildTest(_GREEN_EVIDENCE)
        assert (
            check_build_compile(
                _ctx(), tmp_path, severity=Severity.BLOCKING, port=port
            )
            is None
        )

    def test_build_compile_failclosed_no_port(self, tmp_path: Path) -> None:
        port = _FakeBuildTest(None)
        f = check_build_compile(
            _ctx(), tmp_path, severity=Severity.BLOCKING, port=port
        )
        assert f is not None
        assert f.severity is Severity.BLOCKING

    def test_test_execution_red(self, tmp_path: Path) -> None:
        port = _FakeBuildTest(
            BuildTestEvidence(
                build_ok=True,
                tests_green=False,
                test_file_count=1,
                coverage_report_present=True,
                coverage_meets_threshold=True,
            )
        )
        f = check_build_test_execution(
            _ctx(), tmp_path, severity=Severity.BLOCKING, port=port
        )
        assert f is not None

    def test_test_count_zero_is_major(self, tmp_path: Path) -> None:
        port = _FakeBuildTest(
            BuildTestEvidence(
                build_ok=True,
                tests_green=True,
                test_file_count=0,
                coverage_report_present=True,
                coverage_meets_threshold=True,
            )
        )
        f = check_test_count(_ctx(), tmp_path, severity=Severity.MAJOR, port=port)
        assert f is not None
        assert f.severity is Severity.MAJOR

    def test_coverage_below_threshold_major(self, tmp_path: Path) -> None:
        port = _FakeBuildTest(
            BuildTestEvidence(
                build_ok=True,
                tests_green=True,
                test_file_count=1,
                coverage_report_present=True,
                coverage_meets_threshold=False,
            )
        )
        f = check_test_coverage(_ctx(), tmp_path, severity=Severity.MAJOR, port=port)
        assert f is not None


# --- Hygiene checks (FK-27 §27.4.2, MINOR) ---------------------------------


class TestHygieneChecks:
    def test_todo_fixme_pass(self, tmp_path: Path) -> None:
        (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
        _write_manifest(tmp_path, files=["src.py"])
        assert (
            check_hygiene_todo_fixme(_ctx(), tmp_path, severity=Severity.MINOR)
            is None
        )

    def test_todo_fixme_finding(self, tmp_path: Path) -> None:
        (tmp_path / "src.py").write_text("# TODO: later\nx = 1\n", encoding="utf-8")
        _write_manifest(tmp_path, files=["src.py"])
        f = check_hygiene_todo_fixme(_ctx(), tmp_path, severity=Severity.MINOR)
        assert f is not None
        assert f.severity is Severity.MINOR
        assert f.line_number == 1

    def test_disabled_tests_finding(self, tmp_path: Path) -> None:
        (tmp_path / "t.py").write_text(
            "@pytest.mark.skip\ndef test_x(): ...\n", encoding="utf-8"
        )
        _write_manifest(tmp_path, files=["t.py"])
        f = check_hygiene_disabled_tests(_ctx(), tmp_path, severity=Severity.MINOR)
        assert f is not None

    def test_commented_code_block_finding(self, tmp_path: Path) -> None:
        block = "\n".join(f"# x{i} = func({i})" for i in range(6))
        (tmp_path / "c.py").write_text(block + "\n", encoding="utf-8")
        _write_manifest(tmp_path, files=["c.py"])
        f = check_hygiene_commented_code(_ctx(), tmp_path, severity=Severity.MINOR)
        assert f is not None

    def test_commented_code_block_pass_small(self, tmp_path: Path) -> None:
        (tmp_path / "c.py").write_text("# a single note\nx = 1\n", encoding="utf-8")
        _write_manifest(tmp_path, files=["c.py"])
        assert (
            check_hygiene_commented_code(_ctx(), tmp_path, severity=Severity.MINOR)
            is None
        )


# --- Recurring guards (FK-27 §27.4.3, telemetry) ---------------------------


class TestRecurringGuards:
    def test_llm_reviews_pass(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry({("review_request", None): 1})
        assert (
            check_guard_llm_reviews(
                _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
            )
            is None
        )

    def test_llm_reviews_failclosed_no_event(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry({})
        f = check_guard_llm_reviews(
            _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
        )
        assert f is not None
        assert f.severity is Severity.BLOCKING

    def test_review_compliance_major(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry(
            {("review_request", None): 3, ("review_compliant", None): 1}
        )
        f = check_guard_review_compliance(
            _ctx(), tmp_path, severity=Severity.MAJOR, telemetry=tel
        )
        assert f is not None
        assert f.severity is Severity.MAJOR

    def test_no_violations_pass(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry({})
        assert (
            check_guard_no_violations(
                _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
            )
            is None
        )

    def test_no_violations_finding(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry({("integrity_violation", None): 2})
        f = check_guard_no_violations(
            _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
        )
        assert f is not None

    def test_no_violations_failclosed_on_unresolvable_run_scope(
        self, tmp_path: Path
    ) -> None:
        """FIX-B (FK-33 §33.3.2): unresolvable run scope must NOT free-pass.

        Even with zero integrity_violation events, an unresolvable run scope
        means a violation on this run cannot be ruled out -> fail-closed.
        """
        tel = _FakeTelemetry({}, scope_resolvable=False)
        f = check_guard_no_violations(
            _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
        )
        assert f is not None
        assert f.severity is Severity.BLOCKING
        assert "run scope unresolvable" in f.message

    def test_review_compliance_failclosed_on_unresolvable_run_scope(
        self, tmp_path: Path
    ) -> None:
        """FIX-B (FK-33 §33.3.2): unresolvable run scope must NOT free-pass.

        review_compliant/review_request both count 0 on an unresolvable scope
        (0 < 0 is False); without the scope probe the guard would free-pass on
        stale/unknown telemetry -> fail-closed instead.
        """
        tel = _FakeTelemetry({}, scope_resolvable=False)
        f = check_guard_review_compliance(
            _ctx(), tmp_path, severity=Severity.MAJOR, telemetry=tel
        )
        assert f is not None
        assert f.severity is Severity.MAJOR
        assert "run scope unresolvable" in f.message

    def test_multi_llm_pass_all_roles(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry(
            {
                ("llm_call_complete", "qa_review"): 1,
                ("llm_call_complete", "semantic_review"): 1,
                ("llm_call_complete", "doc_fidelity"): 1,
            }
        )
        assert (
            check_guard_multi_llm(
                _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
            )
            is None
        )

    def test_multi_llm_missing_role_blocking(self, tmp_path: Path) -> None:
        tel = _FakeTelemetry(
            {
                ("llm_call_complete", "qa_review"): 1,
                ("llm_call_complete", "semantic_review"): 1,
            }
        )
        f = check_guard_multi_llm(
            _ctx(), tmp_path, severity=Severity.BLOCKING, telemetry=tel
        )
        assert f is not None
        assert "doc_fidelity" in f.message


# --- ARE-Gate (FK-27 §27.4.4) ----------------------------------------------


class TestAreGate:
    def test_pass(self, tmp_path: Path) -> None:
        verdict = CoverageVerdict(status=AreDockpointStatus.PASS, verdict="PASS")
        assert (
            check_are_gate(
                _ctx(), tmp_path, severity=Severity.BLOCKING,
                coverage_verdict=verdict,
            )
            is None
        )

    def test_none_failclosed(self, tmp_path: Path) -> None:
        f = check_are_gate(
            _ctx(), tmp_path, severity=Severity.BLOCKING, coverage_verdict=None
        )
        assert f is not None
        assert f.severity is Severity.BLOCKING

    def test_fail_verdict(self, tmp_path: Path) -> None:
        verdict = CoverageVerdict(status=AreDockpointStatus.FAIL, verdict="FAIL")
        f = check_are_gate(
            _ctx(), tmp_path, severity=Severity.BLOCKING, coverage_verdict=verdict
        )
        assert f is not None


# --- Impact violation (FK-27 §27.4.2 / FK-23 §23.8) ------------------------


class TestImpactViolation:
    def test_pass_within_declared(self, tmp_path: Path) -> None:
        # Declared budget (manifest) Architecture Impact; SYSTEM actual Local.
        _write_manifest(tmp_path, declared_change_impact="Architecture Impact")
        ev = _evidence(actual_impact=ChangeImpact.LOCAL)
        assert (
            check_impact_violation(
                _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
            )
            is None
        )

    def test_violation_local_declared_architecture_actual(
        self, tmp_path: Path
    ) -> None:
        # Declared budget Local; SYSTEM measures Architecture Impact -> violation.
        _write_manifest(tmp_path, declared_change_impact="Local")
        ev = _evidence(actual_impact=ChangeImpact.ARCHITECTURE_IMPACT)
        f = check_impact_violation(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None
        assert f.check == "impact.violation"
        assert "ESCALATED" in f.message

    def test_missing_declared_budget_failclosed(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path)  # no declared_change_impact
        ev = _evidence(actual_impact=ChangeImpact.LOCAL)
        f = check_impact_violation(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None

    def test_unconfirmable_actual_failclosed(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, declared_change_impact="Architecture Impact")
        ev = _evidence(available=False)
        f = check_impact_violation(
            _ctx(), tmp_path, severity=Severity.BLOCKING, evidence=ev
        )
        assert f is not None
