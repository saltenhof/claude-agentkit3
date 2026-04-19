"""Projection/export helpers for story-scoped runtime artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import Finding, LayerResult
    from agentkit.state_backend.records import ExecutionReport

STATE_DB_FILE = "state.sqlite3"
STATE_DB_DIR = ".agentkit"
CONTEXT_EXPORT_FILE = "context.json"
PHASE_STATE_EXPORT_FILE = "phase-state.json"
CLOSURE_REPORT_FILE = "closure.json"
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


def state_backend_dir(story_dir: Path) -> Path:
    """Return the internal state-backend directory for a story."""

    return story_dir / STATE_DB_DIR


def state_db_path(story_dir: Path) -> Path:
    """Return the canonical SQLite file for a story."""

    return state_backend_dir(story_dir) / STATE_DB_FILE


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
    """Write JSON atomically."""

    atomic_write_text(
        path,
        json.dumps(data, indent=2, sort_keys=True, default=str),
    )


def load_json_object(path: Path) -> dict[str, object] | None:
    """Load a JSON object, returning None on absence or invalid content."""

    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def read_projection_json_object(path: Path) -> dict[str, object] | None:
    """Compatibility alias for projection reads outside truth paths."""

    return load_json_object(path)


def _write_projection(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def write_story_context_projection(
    story_dir: Path,
    payload: dict[str, object],
) -> str:
    """Project the canonical story context into the legacy JSON export."""

    _write_projection(story_dir / CONTEXT_EXPORT_FILE, payload)
    return CONTEXT_EXPORT_FILE


def write_phase_state_projection(
    story_dir: Path,
    payload: dict[str, object],
) -> str:
    """Project the canonical current phase state into the legacy JSON export."""

    _write_projection(story_dir / PHASE_STATE_EXPORT_FILE, payload)
    return PHASE_STATE_EXPORT_FILE


def write_phase_snapshot_projection(
    story_dir: Path,
    phase: str,
    payload: dict[str, object],
) -> str:
    """Project a phase snapshot into the legacy per-phase export."""

    filename = f"phase-state-{phase}.json"
    _write_projection(story_dir / filename, payload)
    return filename


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


def write_layer_projection(
    story_dir: Path,
    *,
    layer_result: LayerResult,
    attempt_nr: int,
) -> str | None:
    """Write one QA layer projection."""

    artifact_name = LAYER_ARTIFACT_FILES.get(layer_result.layer)
    if artifact_name is None:
        return None
    payload = serialize_layer_result(layer_result, attempt_nr=attempt_nr)
    _write_projection(story_dir / artifact_name, payload)
    return artifact_name


def write_verify_decision_projection(
    story_dir: Path,
    *,
    decision: VerifyDecision,
    attempt_nr: int,
) -> tuple[str, str]:
    """Write canonical and legacy verify decision projections."""

    canonical_payload = build_verify_decision_artifact(
        decision,
        attempt_nr=attempt_nr,
    )
    legacy_payload = build_legacy_verify_decision_artifact(
        decision,
        attempt_nr=attempt_nr,
    )
    _write_projection(story_dir / VERIFY_DECISION_FILE, canonical_payload)
    _write_projection(story_dir / LEGACY_VERIFY_DECISION_FILE, legacy_payload)
    return VERIFY_DECISION_FILE, LEGACY_VERIFY_DECISION_FILE


def write_execution_report_projection(
    story_dir: Path,
    report: ExecutionReport,
) -> Path:
    """Write the closure execution report projection."""

    path = story_dir / CLOSURE_REPORT_FILE
    _write_projection(path, report.to_dict())
    return path


def verify_decision_passed(data: dict[str, object]) -> bool:
    """Evaluate PASS/PASS_WITH_WARNINGS semantics for decision envelopes."""

    status = data.get("status")
    if isinstance(status, str):
        return bool(data.get("passed")) and status in ("PASS", "PASS_WITH_WARNINGS")

    decision = data.get("decision")
    return isinstance(decision, str) and decision in ("PASS", "PASS_WITH_WARNINGS")


def load_verify_decision_projection(
    story_dir: Path,
) -> tuple[str, dict[str, object]] | None:
    """Load the canonical verify decision or legacy fallback projection."""

    canonical = load_json_object(story_dir / VERIFY_DECISION_FILE)
    if canonical is not None:
        return VERIFY_DECISION_FILE, canonical

    legacy = load_json_object(story_dir / LEGACY_VERIFY_DECISION_FILE)
    if legacy is not None:
        return LEGACY_VERIFY_DECISION_FILE, legacy
    return None


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""

    return datetime.now(tz=UTC).isoformat()
