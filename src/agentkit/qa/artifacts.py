"""Canonical QA artifact names, serializers, and persistence helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import Finding, LayerResult

LAYER_ARTIFACT_FILES: dict[str, str] = {
    "structural": "structural.json",
    "semantic": "semantic-review.json",
    "adversarial": "adversarial.json",
}
VERIFY_DECISION_FILE = "verify-decision.json"
LEGACY_VERIFY_DECISION_FILE = "decision.json"
GUARDRAIL_FILE = "guardrail.json"

PROTECTED_QA_ARTIFACTS: tuple[str, ...] = (
    *LAYER_ARTIFACT_FILES.values(),
    GUARDRAIL_FILE,
    VERIFY_DECISION_FILE,
    LEGACY_VERIFY_DECISION_FILE,
)


def serialize_finding(finding: Finding) -> dict[str, object]:
    """Serialize a finding into the canonical JSON envelope."""

    return {
        "layer": finding.layer,
        "check": finding.check,
        "severity": finding.severity.value,
        "message": finding.message,
        "trust_class": finding.trust_class.value,
        "file_path": finding.file_path,
        "line_number": finding.line_number,
        "suggestion": finding.suggestion,
    }


def serialize_layer_result(
    layer_result: LayerResult,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Serialize one QA layer result into the canonical artifact shape."""

    return {
        "layer": layer_result.layer,
        "passed": layer_result.passed,
        "attempt_nr": attempt_nr,
        "findings": [
            serialize_finding(finding)
            for finding in layer_result.findings
        ],
        "metadata": layer_result.metadata,
    }


def build_verify_decision_artifact(
    decision: VerifyDecision,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Build the canonical verify-decision artifact payload."""

    return {
        "passed": decision.passed,
        "status": decision.status,
        "layers": [
            {
                "layer": layer_result.layer,
                "passed": layer_result.passed,
                "findings_count": len(layer_result.findings),
                "metadata": layer_result.metadata,
            }
            for layer_result in decision.layer_results
        ],
        "blocking_findings": [
            {
                "layer": finding.layer,
                "check": finding.check,
                "severity": finding.severity.value,
                "message": finding.message,
            }
            for finding in decision.blocking_findings
        ],
        "all_findings_count": len(decision.all_findings),
        "summary": decision.summary,
        "attempt_nr": attempt_nr,
    }


def build_legacy_verify_decision_artifact(
    decision: VerifyDecision,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Build the legacy decision.json compatibility payload."""

    return {
        "decision": decision.status,
        "passed": decision.passed,
        "summary": decision.summary,
        "attempt_nr": attempt_nr,
    }


def write_layer_artifacts(
    story_dir: Path,
    *,
    layer_results: tuple[LayerResult, ...],
    attempt_nr: int,
) -> tuple[str, ...]:
    """Write all known QA layer artifacts and return produced filenames."""

    artifact_names: list[str] = []
    for layer_result in layer_results:
        artifact_name = LAYER_ARTIFACT_FILES.get(layer_result.layer)
        if artifact_name is None:
            continue
        atomic_write_text(
            story_dir / artifact_name,
            json.dumps(
                serialize_layer_result(layer_result, attempt_nr=attempt_nr),
                indent=2,
                default=str,
            ),
        )
        artifact_names.append(artifact_name)
    return tuple(artifact_names)


def write_verify_decision_artifacts(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
) -> tuple[str, str]:
    """Write canonical and legacy verify decision artifacts."""

    atomic_write_text(
        story_dir / VERIFY_DECISION_FILE,
        json.dumps(
            build_verify_decision_artifact(decision, attempt_nr=attempt_nr),
            indent=2,
            default=str,
        ),
    )
    atomic_write_text(
        story_dir / LEGACY_VERIFY_DECISION_FILE,
        json.dumps(
            build_legacy_verify_decision_artifact(decision, attempt_nr=attempt_nr),
            indent=2,
            default=str,
        ),
    )
    return VERIFY_DECISION_FILE, LEGACY_VERIFY_DECISION_FILE


def load_json_object(path: Path) -> dict[str, object] | None:
    """Load a JSON object, returning None on absence or invalid content."""

    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_verify_decision_artifact(
    story_dir: Path,
) -> tuple[str, dict[str, object]] | None:
    """Load the canonical verify decision or legacy fallback."""

    canonical = story_dir / VERIFY_DECISION_FILE
    canonical_data = load_json_object(canonical)
    if canonical_data is not None:
        return VERIFY_DECISION_FILE, canonical_data

    legacy = story_dir / LEGACY_VERIFY_DECISION_FILE
    legacy_data = load_json_object(legacy)
    if legacy_data is not None:
        return LEGACY_VERIFY_DECISION_FILE, legacy_data

    return None


def verify_decision_passed(data: dict[str, object]) -> bool:
    """Evaluate PASS/PASS_WITH_WARNINGS semantics for decision envelopes."""

    status = data.get("status")
    if isinstance(status, str):
        return bool(data.get("passed")) and status in ("PASS", "PASS_WITH_WARNINGS")

    decision = data.get("decision")
    return isinstance(decision, str) and decision in ("PASS", "PASS_WITH_WARNINGS")


__all__ = [
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "LEGACY_VERIFY_DECISION_FILE",
    "PROTECTED_QA_ARTIFACTS",
    "VERIFY_DECISION_FILE",
    "build_legacy_verify_decision_artifact",
    "build_verify_decision_artifact",
    "load_json_object",
    "load_verify_decision_artifact",
    "serialize_finding",
    "serialize_layer_result",
    "verify_decision_passed",
    "write_layer_artifacts",
    "write_verify_decision_artifacts",
]
