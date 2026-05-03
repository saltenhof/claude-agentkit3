"""Filesystem path constants and driver-level path helpers for the state backend.

Blood group: T (infrastructure_driver)
Owner:       state-backend BC
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem filename constants
# ---------------------------------------------------------------------------

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
GUARDRAIL_FILE = "guardrail.json"
PROTECTED_QA_ARTIFACTS: tuple[str, ...] = (
    *LAYER_ARTIFACT_FILES.values(),
    GUARDRAIL_FILE,
    VERIFY_DECISION_FILE,
)

# ---------------------------------------------------------------------------
# Driver-level path helpers
# ---------------------------------------------------------------------------


def state_backend_dir(story_dir: Path) -> Path:
    """Return the internal state-backend directory for a story."""

    return story_dir / STATE_DB_DIR


def state_db_path(story_dir: Path) -> Path:
    """Return the canonical SQLite file for a story."""

    return state_backend_dir(story_dir) / STATE_DB_FILE
