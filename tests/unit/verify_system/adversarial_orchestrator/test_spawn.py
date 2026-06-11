"""Unit tests for AdversarialSpawner (FK-27 §27.6 / FK-48 §48.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.core_types import SpawnKind, SpawnReason
from agentkit.governance.guard_system.protected_paths import (
    is_adversarial_sandbox_path,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.verify_system.adversarial_orchestrator.spawn import (
    AdversarialSpawner,
    render_mandatory_targets_section,
)
from agentkit.verify_system.contract import VerifyContextBundle
from agentkit.verify_system.protocols import (
    ASSERTION_WEAKNESS_FINDING_TYPE,
    Finding,
    Severity,
    TrustClass,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _finding(
    severity: Severity,
    check: str = "assertion_weakness",
    *,
    finding_type: str | None = ASSERTION_WEAKNESS_FINDING_TYPE,
    addressed_part: str = "",
) -> Finding:
    return Finding(
        layer="qa_review",
        check=check,
        severity=severity,
        message=f"{check} finding",
        trust_class=TrustClass.VERIFIED_LLM,
        suggestion="cover the negative case",
        finding_type=finding_type,
        addressed_part=addressed_part,
    )


def _spawner(tmp_path: Path) -> AdversarialSpawner:
    return AdversarialSpawner(build_artifact_manager(tmp_path))


def _ctx(story_dir: Path) -> VerifyContextBundle:
    return VerifyContextBundle(
        run_id="run-1",
        story_dir=story_dir,
        attempt=1,
    )


def test_extract_targets_per_assertion_weakness_finding(tmp_path: Path) -> None:
    """AC0: one AdversarialTarget per assertion_weakness finding, with addressed_part."""
    spawner = _spawner(tmp_path)
    targets = spawner.extract_mandatory_targets(
        [
            _finding(
                Severity.BLOCKING,
                "neg_case_a",
                addressed_part="fixed happy path A",
            ),
            _finding(Severity.MAJOR, "concern_b", addressed_part="fixed B"),
            _finding(Severity.BLOCKING, "neg_case_c", addressed_part="fixed C"),
        ],
        2,
    )
    assert len(targets) == 3
    assert all(t.mandatory for t in targets)
    assert all(t.test_anchor.endswith(".py") for t in targets)
    assert {t.finding_id for t in targets} == {
        "qa_review.neg_case_a",
        "qa_review.concern_b",
        "qa_review.neg_case_c",
    }
    # FK-48 §48.2.2: each target carries the addressed_part + the round source.
    by_id = {t.finding_id: t for t in targets}
    assert by_id["qa_review.neg_case_a"].addressed_part == "fixed happy path A"
    assert by_id["qa_review.neg_case_a"].source == "qa_review round 2"


def test_extract_targets_skips_blocking_without_assertion_weakness(
    tmp_path: Path,
) -> None:
    """AC0: a plain BLOCKING finding WITHOUT assertion_weakness yields NO target."""
    spawner = _spawner(tmp_path)
    targets = spawner.extract_mandatory_targets(
        [_finding(Severity.BLOCKING, "plain_blocking", finding_type=None)],
        1,
    )
    assert targets == []


def test_extract_targets_empty_without_findings(tmp_path: Path) -> None:
    """No assertion_weakness findings -> no mandatory targets (explorative-only)."""
    spawner = _spawner(tmp_path)
    assert spawner.extract_mandatory_targets([], 1) == []


def test_render_mandatory_targets_section_only_with_targets(tmp_path: Path) -> None:
    """AC0: §48.2.3 'Mandatory Targets' section only when targets exist."""
    spawner = _spawner(tmp_path)
    # No targets -> empty section (FK-48 §48.2.3).
    assert render_mandatory_targets_section([]) == ""
    # With targets -> the section names each target + the UNRESOLVABLE escape.
    targets = spawner.extract_mandatory_targets(
        [_finding(Severity.BLOCKING, "neg_case", addressed_part="fixed happy path")],
        1,
    )
    section = render_mandatory_targets_section(targets)
    assert "## Mandatory Targets" in section
    assert "Target: qa_review.neg_case" in section
    assert "fixed happy path" in section
    assert "UNRESOLVABLE" in section


def test_request_spawn_creates_protected_sandbox(tmp_path: Path) -> None:
    """request_spawn materialises the protected sandbox + spawn orders."""
    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    spawner = _spawner(tmp_path)
    targets = spawner.extract_mandatory_targets([_finding(Severity.BLOCKING, "neg_case")], 1)
    request = spawner.request_spawn(_ctx(story_dir), targets)

    assert request.sandbox_path.is_dir()
    assert request.epoch == "1"
    # Sandbox path is a Protected-Path (AG3-023).
    rel = request.sandbox_path.relative_to(story_dir).as_posix()
    assert is_adversarial_sandbox_path(rel)
    # One typed adversarial spawn order per target.
    assert len(request.agents_to_spawn) == 1
    order = request.agents_to_spawn[0]
    assert order.kind is SpawnKind.ADVERSARIAL
    assert order.spawn_reason is SpawnReason.REMEDIATION
    assert order.target_id == "qa_review.neg_case"
    assert order.sandbox_path is not None
    assert is_adversarial_sandbox_path(order.sandbox_path)


def test_request_spawn_fails_closed_on_unprotected_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sandbox path that is not Protected fails closed (AG3-023)."""
    import agentkit.verify_system.adversarial_orchestrator.spawn as spawn_mod

    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    spawner = _spawner(tmp_path)
    targets = spawner.extract_mandatory_targets([_finding(Severity.BLOCKING)], 1)
    # Force the protected-path check to reject (simulates a registry drift).
    monkeypatch.setattr(spawn_mod, "is_adversarial_sandbox_path", lambda _p: False)
    with pytest.raises(ValueError, match="not a Protected-Path"):
        spawner.request_spawn(_ctx(story_dir), targets)


def test_apply_to_state_sets_agents_to_spawn(tmp_path: Path) -> None:
    """apply_to_state writes the spawn orders into PhaseState.agents_to_spawn."""
    from datetime import UTC, datetime

    from agentkit.pipeline_engine.phase_executor.models import (
        PhaseState,
        PhaseStateMode,
        PhaseStateProducer,
        PhaseStatus,
    )
    from agentkit.story_context_manager.types import StoryType

    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    spawner = _spawner(tmp_path)
    targets = spawner.extract_mandatory_targets([_finding(Severity.BLOCKING)], 1)
    request = spawner.request_spawn(_ctx(story_dir), targets)
    now = datetime.now(tz=UTC)

    state = PhaseState(
        schema_version="4.0",
        story_id="AG3-044",
        run_id="00000000-0000-0000-0000-000000000001",
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
        mode=PhaseStateMode.EXECUTION,
        story_type=StoryType.IMPLEMENTATION,
        attempt=1,
        started_at=now,
        phase_entered_at=now,
        pause_reason=None,
        escalation_reason=None,
        warnings=[],
        producer=PhaseStateProducer(type="system", name="test"),
    )
    updated = request.apply_to_state(state)
    assert len(updated.agents_to_spawn) == 1
    assert updated.agents_to_spawn[0].kind is SpawnKind.ADVERSARIAL
    # Original state is unchanged (immutability).
    assert state.agents_to_spawn == []
