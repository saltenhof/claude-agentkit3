"""Contract tests for formal.conformance.events (AG3-063)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.verify_system.conformance_service import (
    ConformanceEvaluation,
    ConformanceService,
    ConformanceVerdict,
    FidelityContext,
    FidelityLevel,
)


class _PassingEvaluator:
    def evaluate(self, **kwargs: object) -> ConformanceEvaluation:
        del kwargs
        return ConformanceEvaluation(
            verdict=ConformanceVerdict.PASS,
            reason="pass",
            description="pass",
        )


def _write_manifest(project_root: Path) -> None:
    guardrails = project_root / "_guardrails"
    docs = project_root / "concepts"
    guardrails.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    (guardrails / "manifest-index.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "path": "concepts/architecture.md",
                        "scope": "architecture",
                        "modules": ["verify-system"],
                        "story_types": ["implementation"],
                        "tags": ["document-fidelity"],
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _context(project_root: Path) -> FidelityContext:
    return FidelityContext(
        story_id="AG3-063",
        run_id="11111111-1111-4111-8111-111111111111",
        project_root=project_root,
        story_type="implementation",
        module="verify-system",
        subject="subject",
        story_description="story",
        tags=("document-fidelity",),
    )


def _formal_required_payloads() -> dict[str, tuple[str, ...]]:
    spec_path = Path("concept/formal-spec/conformance/events.md")
    text = spec_path.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    assert match is not None
    parsed = yaml.safe_load(match.group(1))
    assert isinstance(parsed, dict)
    events = parsed["events"]
    assert isinstance(events, list)
    required: dict[str, tuple[str, ...]] = {}
    for event in events:
        assert isinstance(event, dict)
        payload = event["payload"]
        assert isinstance(payload, dict)
        fields = payload["required"]
        assert isinstance(fields, list)
        required[str(event["id"])] = tuple(str(field) for field in fields)
    return required


def test_conformance_service_events_match_formal_payload_contract(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path)
    emitter = MemoryEmitter()
    service = ConformanceService(_PassingEvaluator(), emitter=emitter)

    service.check_fidelity(FidelityLevel.GOAL, _context(tmp_path))

    by_type: dict[EventType, dict[str, Any]] = {
        event.event_type: event.payload
        for event in emitter.query("AG3-063")
        if event.event_type
        in {
            EventType.CONFORMANCE_ASSESSMENT_STARTED,
            EventType.CONFORMANCE_LEVEL_EVALUATED,
            EventType.CONFORMANCE_ASSESSMENT_COMPLETED,
        }
    }
    formal = _formal_required_payloads()
    expected_projection = {
        EventType.CONFORMANCE_ASSESSMENT_STARTED: "conformance.event.assessment.started",
        EventType.CONFORMANCE_LEVEL_EVALUATED: "conformance.event.level.evaluated",
        EventType.CONFORMANCE_ASSESSMENT_COMPLETED: (
            "conformance.event.assessment.completed"
        ),
    }

    assert set(by_type) == set(expected_projection)
    for event_type, formal_id in expected_projection.items():
        assert tuple(by_type[event_type]) == formal[formal_id]
