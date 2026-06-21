"""Flow constants for the story-flow read-model (AG3-091).

All phase-ordering, substep-sequence, loop-group, and closure-progress
constants live here so that ``read_models.py`` stays within the 100-LOC
module-level limit (PY_MODULE_TOP_LEVEL_MAX_LOC_100).

These are pure data constants — no behaviour, no imports beyond builtins.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase ordering
# ---------------------------------------------------------------------------

PHASE_ORDER: tuple[str, ...] = ("setup", "exploration", "implementation", "closure")

# ---------------------------------------------------------------------------
# Story-status sentinels
# ---------------------------------------------------------------------------

# Story statuses that indicate no pipeline progress has started.
NO_PROGRESS_STATUSES: frozenset[str] = frozenset(
    {"Backlog", "Approved", "Cancelled", "Resetting", "Reset Failed"}
)

# Terminal-done status (wire value).
DONE_STATUS = "Done"

# ---------------------------------------------------------------------------
# Phase-status -> flow-state mapping
# ---------------------------------------------------------------------------

PHASE_STATUS_TO_FLOW: dict[str, str] = {
    "pending": "pending",
    "in_progress": "active",
    "paused": "paused",
    "completed": "done",
    "failed": "failed",
    "escalated": "escalated",
}

# ---------------------------------------------------------------------------
# Substep sequences
# ---------------------------------------------------------------------------

# Canonical substep sequences per phase (ported from storyFixtures.ts
# PHASE_SUBSTEP_SEQUENCE and PHASE_SUBSTEP_SEQUENCE_FAST, FK-24 §24.3.3).
SUBSTEP_SEQUENCE_STANDARD: dict[str, tuple[str, ...]] = {
    "setup": (
        "preflight", "story_context", "are_bundle", "type_switch",
        "worktree", "guard_activation", "mode_resolution",
    ),
    "exploration": (
        "worker_spawn", "draft", "structural_validation", "doc_fidelity_l2",
        "design_review", "aggregation", "feindesign", "freeze",
    ),
    "implementation": (
        "worker_start", "incremental", "inline_reviews", "final_build",
        "handover", "qa_layer1_structural", "qa_layer2_llm",
        "qa_layer3_adversarial", "qa_layer4_policy", "qa_feedback",
    ),
    "closure": (
        "finding_resolution", "integrity_gate", "branch_push", "merge",
        "main_push", "teardown", "story_close", "metrics",
        "doc_fidelity_l4", "postflight", "vectordb_sync", "guards_off",
    ),
}

# Fast-mode: OUT-substeps are absent (FK-24 §24.3.3, AG3-018 §Mode-Profil).
SUBSTEP_SEQUENCE_FAST: dict[str, tuple[str, ...]] = {
    "setup": ("preflight", "story_context", "type_switch", "worktree"),
    # Exploration is entirely OUT in fast-mode; phase renders as skipped.
    "exploration": (),
    "implementation": (
        "worker_start", "incremental", "final_build",
        "handover", "qa_layer1_structural",
    ),
    "closure": (
        "integrity_gate", "branch_push", "merge", "main_push",
        "teardown", "story_close", "metrics", "postflight",
        "vectordb_sync", "guards_off",
    ),
}

# ---------------------------------------------------------------------------
# Substep metadata
# ---------------------------------------------------------------------------

# Optional substep flags (ported from storyFixtures.ts SUBSTEP_META).
OPTIONAL_SUBSTEPS: frozenset[str] = frozenset(
    {"feindesign", "inline_reviews", "qa_feedback", "finding_resolution", "vectordb_sync"}
)

# Loop group membership (ported from storyFixtures.ts SUBSTEP_META).
LOOP_GROUPS: dict[str, str] = {
    "draft": "design_iteration",
    "structural_validation": "design_iteration",
    "doc_fidelity_l2": "design_iteration",
    "design_review": "design_iteration",
    "incremental": "remediation",
    "inline_reviews": "remediation",
    "final_build": "remediation",
    "handover": "remediation",
    "qa_layer1_structural": "remediation",
    "qa_layer2_llm": "remediation",
    "qa_layer3_adversarial": "remediation",
    "qa_layer4_policy": "remediation",
    "qa_feedback": "remediation",
}

# ---------------------------------------------------------------------------
# Closure-progress mapping
# ---------------------------------------------------------------------------

# Mapping from ClosureProgress boolean field name to the canonical substep id.
CLOSURE_PROGRESS_TO_SUBSTEP: tuple[tuple[str, str], ...] = (
    ("integrity_passed", "integrity_gate"),
    ("story_branch_pushed", "branch_push"),
    ("merge_done", "merge"),
    ("story_closed", "story_close"),
    ("metrics_written", "metrics"),
    ("postflight_done", "postflight"),
)
