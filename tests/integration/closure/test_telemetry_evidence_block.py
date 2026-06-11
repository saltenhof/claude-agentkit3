"""Integration test: the Closure Telemetry-Evidence-Block (FK-68 §68.4, AG3-081).

Exercises the productive ``ProductiveTelemetryEvidencePort`` end to end on SQLite:
the port resolves the authoritative review/llm/web budget config, reads the run's
canonical ``execution_events`` via ``StateBackendExecutionEventReader`` and runs
the six FK-68 §68.4 proofs. Each of the SIX negative classes yields a fail-closed
``TelemetryEvidenceVerdict(passed=False)`` so Closure blocks; a complete run
passes (story §2.1.4b / AC3).

Naming discipline (story §1): this is the **Telemetry-Evidence-Block (FK-68
§68.4)**, NOT the IntegrityGate dimension 8.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.closure.runtime_ports import ProductiveTelemetryEvidencePort
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.storage import StateBackendEmitter

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_PROJECT = "demo-project"
_STORY = "AG3-001"
_RUN = "run-teb-001"
_REQUIRED_ROLE = "qa_review"
_POOL = "chatgpt"
_WEB_BUDGET = 5


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _write_project_config(project_root: Path) -> None:
    """Write a minimal project.yaml carrying the authoritative gate config."""
    import yaml

    config_dir = project_root / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "project_key": _PROJECT,
                "project_name": "Tenant A",
                "repositories": [{"name": "repo", "path": str(project_root / "repo")}],
                "story_types": ["concept"],
                "pipeline": {
                    "config_version": "3.0",
                    "features": {"multi_llm": False},
                    "telemetry": {
                        "web_call_limit": _WEB_BUDGET,
                        "web_call_warning": 1,
                    },
                    "review": {"required_roles": [_REQUIRED_ROLE]},
                    "llm_roles": {
                        "qa_review": _POOL,
                        "semantic_review": _POOL,
                        "adversarial_sparring": _POOL,
                        "doc_fidelity": _POOL,
                        "governance_adjudication": _POOL,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _seed_scope(story_dir: Path, project_root: Path) -> None:
    save_story_context(
        story_dir,
        StoryContext(
            project_key=_PROJECT,
            story_id=_STORY,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title="Telemetry-Evidence-Block run",
            project_root=project_root,
        ),
    )
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _complete_run_events() -> list[Event]:
    """A run that satisfies all six FK-68 §68.4 proofs."""
    return [
        Event(story_id=_STORY, event_type=EventType.AGENT_START, run_id=_RUN),
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_REQUEST,
            run_id=_RUN,
            payload={"role": _REQUIRED_ROLE, "pool": _POOL},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_RESPONSE,
            run_id=_RUN,
            payload={"role": _REQUIRED_ROLE, "verdict": "PASS"},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.REVIEW_COMPLIANT,
            run_id=_RUN,
            payload={"pool": _POOL, "template_name": "review-v1"},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.LLM_CALL,
            run_id=_RUN,
            payload={"role": _REQUIRED_ROLE, "pool": _POOL},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.PREFLIGHT_REQUEST,
            run_id=_RUN,
            payload={"pool": _POOL},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.PREFLIGHT_RESPONSE,
            run_id=_RUN,
            payload={"pool": _POOL, "request_count": 1},
        ),
        Event(
            story_id=_STORY,
            event_type=EventType.PREFLIGHT_COMPLIANT,
            run_id=_RUN,
            payload={"pool": _POOL},
        ),
        Event(story_id=_STORY, event_type=EventType.AGENT_END, run_id=_RUN),
    ]


def _setup(tmp_path: Path) -> tuple[Path, ProductiveTelemetryEvidencePort]:
    project_root = tmp_path
    story_dir = project_root / "stories" / _STORY
    story_dir.mkdir(parents=True)
    _write_project_config(project_root)
    _seed_scope(story_dir, project_root)
    port = ProductiveTelemetryEvidencePort(
        project_key=_PROJECT, project_root=project_root
    )
    return story_dir, port


def _emit(story_dir: Path, events: list[Event]) -> None:
    emitter = StateBackendEmitter(story_dir, default_project_key=_PROJECT)
    for event in events:
        emitter.emit(event)


# ---------------------------------------------------------------------------
# Positive: a complete run passes all six proofs (AC3 positive)
# ---------------------------------------------------------------------------


def test_complete_run_passes_telemetry_evidence_block(tmp_path: Path) -> None:
    story_dir, port = _setup(tmp_path)
    _emit(story_dir, _complete_run_events())

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert verdict.passed, verdict.blocking_reason
    assert verdict.failing_rule_ids == ()


# ---------------------------------------------------------------------------
# Negative: each of the SIX FK-68 §68.4 proof classes blocks Closure (AC3)
# ---------------------------------------------------------------------------


def test_agent_pairing_violation_blocks_closure(tmp_path: Path) -> None:
    # (a) agent_start/agent_end pairing broken -> blocks.
    story_dir, port = _setup(tmp_path)
    events = [e for e in _complete_run_events() if e.event_type != EventType.AGENT_END]
    _emit(story_dir, events)

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert not verdict.passed
    assert "FK-68 §68.4.1" in verdict.failing_rule_ids


def test_missing_llm_call_role_blocks_closure(tmp_path: Path) -> None:
    # (b) llm_call for the mandatory role->pool missing -> blocks.
    story_dir, port = _setup(tmp_path)
    events = [e for e in _complete_run_events() if e.event_type != EventType.LLM_CALL]
    _emit(story_dir, events)

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert not verdict.passed
    assert "FK-68 §68.4.3" in verdict.failing_rule_ids


def test_review_compliance_violation_blocks_closure(tmp_path: Path) -> None:
    # (c) review_compliant < review_request -> blocks.
    story_dir, port = _setup(tmp_path)
    events = [
        e for e in _complete_run_events() if e.event_type != EventType.REVIEW_COMPLIANT
    ]
    _emit(story_dir, events)

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert not verdict.passed
    assert "FK-68 §68.4.2" in verdict.failing_rule_ids


def test_integrity_violation_blocks_closure(tmp_path: Path) -> None:
    # (d) an integrity_violation event present -> blocks.
    story_dir, port = _setup(tmp_path)
    events = [
        *_complete_run_events(),
        Event(
            story_id=_STORY,
            event_type=EventType.INTEGRITY_VIOLATION,
            run_id=_RUN,
            payload={"stage": "escape_detection"},
        ),
    ]
    _emit(story_dir, events)

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert not verdict.passed
    assert "FK-68 §68.4.4" in verdict.failing_rule_ids


def test_web_call_over_budget_blocks_closure(tmp_path: Path) -> None:
    # (e) web_call count > configured budget -> blocks.
    story_dir, port = _setup(tmp_path)
    over_budget = [
        Event(story_id=_STORY, event_type=EventType.WEB_CALL, run_id=_RUN)
        for _ in range(_WEB_BUDGET + 1)
    ]
    _emit(story_dir, [*_complete_run_events(), *over_budget])

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert not verdict.passed
    assert "FK-68 §68.4.5" in verdict.failing_rule_ids


def test_preflight_balance_violation_blocks_closure(tmp_path: Path) -> None:
    # (f) preflight stream unbalanced (no preflight at all) -> blocks.
    story_dir, port = _setup(tmp_path)
    events = [
        e
        for e in _complete_run_events()
        if e.event_type
        not in {
            EventType.PREFLIGHT_REQUEST,
            EventType.PREFLIGHT_RESPONSE,
            EventType.PREFLIGHT_COMPLIANT,
        }
    ]
    _emit(story_dir, events)

    verdict = port.evaluate(story_dir, story_id=_STORY, run_id=_RUN)

    assert not verdict.passed
    assert "FK-68 §68.9.2" in verdict.failing_rule_ids
