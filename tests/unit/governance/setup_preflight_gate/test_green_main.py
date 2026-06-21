"""Unit tests for the setup green-main precondition (FK-22 §22.4c, AG3-034 T3).

Exercises the applicability matrix (FK-33 §33.6.5) against a stubbed AG3-052
capability port (no live Sonar — only the capability boundary is stubbed):
APPLICABLE-green -> GREEN (proceed); APPLICABLE red/stale/unreachable ->
fail-closed with a blame-free cleanup proposal; available:false -> SKIPPED;
fast -> SKIPPED; concept/research -> SKIPPED.  Asserts the absent-vs-broken
distinction (available:false SKIP vs available:true+unreachable RED).
"""

from __future__ import annotations

import pytest

from agentkit.backend.governance.setup_preflight_gate.green_main import (
    MainAttestationView,
    MainGreenStatus,
    check_main_green_precondition,
)
from agentkit.backend.story_context_manager.story_model import WireStoryMode
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.sonarqube_gate import SonarAttestation

_HEAD = "main-head-1"


def _attestation(*, status: str = "OK", revision: str = _HEAD) -> SonarAttestation:
    return SonarAttestation(
        commit_sha=_HEAD,
        tree_hash="tree-1",
        analysis_id="an-1",
        ce_task_id="ce-1",
        quality_gate_status=status,
        quality_gate_hash="qg",
        quality_profile_hash="qp",
        analysis_scope_hash="sc",
        new_code_definition="ref",
        exception_ledger_hash="led",
        last_analyzed_revision=revision,
        sonarqube_version="26.4",
        branch_plugin_version="1.0",
        scanner_version="5.0",
        status="bound",
    )


def _view(
    *, status: str = "OK", revision: str = _HEAD, open_issues: int = 0
) -> MainAttestationView:
    return MainAttestationView(
        attestation=_attestation(status=status, revision=revision),
        overall_open_issue_count=open_issues,
    )


class _Port:
    def __init__(self, view: object | None, head: str = _HEAD) -> None:
        self._view = view
        self._head = head

    def main_head_revision(self) -> str:
        return self._head

    def read_main_attestation(self) -> object | None:
        return self._view


def _check(**kwargs: object):  # type: ignore[no-untyped-def]
    base: dict[str, object] = {
        "available": True,
        "mode": None,
        "story_type": StoryType.IMPLEMENTATION,
        "port": _Port(_view()),
    }
    base.update(kwargs)
    return check_main_green_precondition(**base)  # type: ignore[arg-type]


def test_applicable_green_proceeds() -> None:
    result = _check()
    assert result.status is MainGreenStatus.GREEN
    assert not result.blocks_setup


def test_applicable_red_qg_fails_closed_with_cleanup() -> None:
    result = _check(port=_Port(_view(status="ERROR")))
    assert result.status is MainGreenStatus.RED
    assert result.blocks_setup
    assert result.cleanup_proposal is not None
    assert "blame_free" in result.cleanup_proposal


def test_applicable_overall_open_issues_fails_closed() -> None:
    # AG3-052 green = QG OK AND overall-zero: QG OK but open issues > 0 -> RED.
    result = _check(port=_Port(_view(open_issues=3)))
    assert result.status is MainGreenStatus.RED
    assert result.blocks_setup


def test_applicable_stale_fails_closed() -> None:
    result = _check(port=_Port(_view(revision="old-rev")))
    assert result.status is MainGreenStatus.STALE
    assert result.blocks_setup
    assert result.analyzed_revision == "old-rev"
    assert result.cleanup_proposal is not None


def test_applicable_unreachable_fails_closed_no_attestation() -> None:
    # available:true but attestation None (configured-but-unreachable) -> RED.
    result = _check(port=_Port(None))
    assert result.status is MainGreenStatus.RED
    assert result.blocks_setup


def test_applicable_but_port_unwired_fails_closed() -> None:
    # APPLICABLE with no capability port == configured-but-unreachable -> RED.
    result = _check(port=None)
    assert result.status is MainGreenStatus.RED
    assert result.blocks_setup


def test_unavailable_skips_not_fail_closed() -> None:
    # available:false (deliberate absence) -> SKIP, never fail-closed.
    result = _check(available=False, port=None)
    assert result.status is MainGreenStatus.SKIPPED
    assert not result.blocks_setup


def test_fast_mode_skips() -> None:
    result = _check(mode=WireStoryMode.FAST, port=None)
    assert result.status is MainGreenStatus.SKIPPED
    assert not result.blocks_setup


@pytest.mark.parametrize("story_type", [StoryType.CONCEPT, StoryType.RESEARCH])
def test_noncode_story_skips(story_type: StoryType) -> None:
    result = _check(story_type=story_type, port=None)
    assert result.status is MainGreenStatus.SKIPPED
    assert not result.blocks_setup


def test_absent_vs_unreachable_distinction() -> None:
    # absent (available:false) SKIPs; unreachable (available:true) fail-closed.
    absent = _check(available=False, port=None)
    unreachable = _check(available=True, port=None)
    assert absent.status is MainGreenStatus.SKIPPED
    assert unreachable.status is MainGreenStatus.RED
