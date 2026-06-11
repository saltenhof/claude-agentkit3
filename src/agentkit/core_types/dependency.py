"""StoryDependencyKind — story dependency edges.

Source of truth: FK-70 §70.4.2 — concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
(lines 211-220, eight values).

Fully replaces the v2 vocabulary ``blocks/derives_from/branches_off``
(three values).
"""

from __future__ import annotations

from enum import StrEnum


class StoryDependencyKind(StrEnum):
    """Story dependency edge per FK-70 §70.4.2.

    `soft_story_dependency` is NOT a hard topology blocker; it influences
    prioritization/scheduling but may never move a story from `READY` to
    non-executable.

    Attributes:
        HARD_STORY_DEPENDENCY: Hard precondition; story stays blocked
            until the predecessor is `completed`.
        SOFT_STORY_DEPENDENCY: Soft hint for scheduling.
        SERIAL_EXECUTION_CONSTRAINT: Enforces sequential execution.
        MUTEX_CONSTRAINT: Mutex between two stories.
        SHARED_CONTRACT_DEPENDENCY: Shared contract (schema/API).
        SHARED_FILE_CONFLICT: Touch the same files.
        EXTERNAL_DEPENDENCY: External dependency (lib, tool, service).
        HUMAN_GATE_DEPENDENCY: Waits for a human decision.
    """

    HARD_STORY_DEPENDENCY = "hard_story_dependency"
    SOFT_STORY_DEPENDENCY = "soft_story_dependency"
    SERIAL_EXECUTION_CONSTRAINT = "serial_execution_constraint"
    MUTEX_CONSTRAINT = "mutex_constraint"
    SHARED_CONTRACT_DEPENDENCY = "shared_contract_dependency"
    SHARED_FILE_CONFLICT = "shared_file_conflict"
    EXTERNAL_DEPENDENCY = "external_dependency"
    HUMAN_GATE_DEPENDENCY = "human_gate_dependency"
