"""Filesystem path constants and driver-level path helpers for the state backend.

Blood group: T (infrastructure_driver)
Owner:       state-backend BC

Migration AG3-023: PROTECTED_QA_ARTIFACTS, LAYER_ARTIFACT_FILES and
VERIFY_DECISION_FILE were moved to
``agentkit.governance.guard_system.protected_paths``
(FK-31 §31.3 + bc-cut-decisions.md §BC 4, refactor list item 24).
No re-export shim here (zero-debt rule).
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
GUARDRAIL_FILE = "guardrail.json"

# ---------------------------------------------------------------------------
# Driver-level path helpers
# ---------------------------------------------------------------------------


def state_backend_dir(story_dir: Path) -> Path:
    """Return the internal state-backend directory for a story."""

    return story_dir / STATE_DB_DIR


def state_db_path(story_dir: Path) -> Path:
    """Return the legacy unversioned SQLite file for a story."""

    return state_backend_dir(story_dir) / STATE_DB_FILE
