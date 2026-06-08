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
from agentkit.verify_system.adversarial_orchestrator.spawn import AdversarialSpawner
from agentkit.verify_system.contract import VerifyContextBundle
from agentkit.verify_system.protocols import Finding, Severity, TrustClass

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


def _finding(severity: Severity, check: str = "assertion_weakness") -> Finding:
    return Finding(
        layer="qa_review",
        check=check,
        severity=severity,
        message=f"{check} finding",
        trust_class=TrustClass.VERIFIED_LLM,
        suggestion="cover the negative case",
    )


def _spawner(tmp_path: Path) -> AdversarialSpawner:
    return AdversarialSpawner(build_artifact_manager(tmp_path))


def _ctx(story_dir: Path) -> VerifyContextBundle:
    return VerifyContextBundle(
        run_id="run-1",
        story_dir=story_dir,
        attempt=1,
    )


def test_derive_targets_one_per_blocking_finding(tmp_path: Path) -> None:
    """>= 1 AdversarialTarget per BLOCKING finding, each with a test anchor."""
    spawner = _spawner(tmp_path)
    targets = spawner.derive_targets(
        [
            _finding(Severity.BLOCKING, "neg_case_a"),
            _finding(Severity.MAJOR, "minor_b"),
            _finding(Severity.BLOCKING, "neg_case_c"),
        ]
    )
    assert len(targets) == 2
    assert all(t.mandatory for t in targets)
    assert all(t.test_anchor.endswith(".py") for t in targets)
    assert {t.finding_id for t in targets} == {
        "qa_review.neg_case_a",
        "qa_review.neg_case_c",
    }


def test_derive_targets_empty_without_blocking(tmp_path: Path) -> None:
    """No BLOCKING findings -> no mandatory targets (explorative-only Layer 3)."""
    spawner = _spawner(tmp_path)
    assert spawner.derive_targets([_finding(Severity.MAJOR)]) == []


def test_request_spawn_creates_protected_sandbox(tmp_path: Path) -> None:
    """request_spawn materialises the protected sandbox + spawn orders."""
    story_dir = tmp_path / "AG3-044"
    story_dir.mkdir()
    spawner = _spawner(tmp_path)
    targets = spawner.derive_targets([_finding(Severity.BLOCKING, "neg_case")])
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
    targets = spawner.derive_targets([_finding(Severity.BLOCKING)])
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
    targets = spawner.derive_targets([_finding(Severity.BLOCKING)])
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
