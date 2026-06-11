"""StorySize and StoryMode — story master-data enums.

Source of truth:
- StorySize: DK-10 §10.4 — concept/domain-design/10-story-lifecycle-und-erstellung.md
  (5 levels XS/S/M/L/XL; no XXL, no epic).
- StoryMode: FK-24 §24.3.2 — concept/technical-design/24_story_type_mode_terminalitaet.md.

`execution_route` is `StoryMode | None`; non-implementing stories carry
`None`, not a dedicated sentinel enum value. The permitted StoryMode
values are documented in the class itself.

The fast/standard mode (AG3-018) is a SEPARATE axis (FK-24 §24.3.3) and
does NOT belong in ``StoryMode``/``execution_route``. It is carried via
``WireStoryMode`` (story_model) and passed through on the runtime context
as ``StoryContext.mode``.
"""

from __future__ import annotations

from enum import StrEnum


class StorySize(StrEnum):
    """Story size per DK-10 §10.4.

    Wire value is identical to the Python member (upper-case).

    Attributes:
        XS: 1-2 files, 1 module, no new test needed.
        S: 3-10 files, 1 module, few unit tests.
        M: 10-30 files, 1-2 modules, unit and integration tests.
        L: 30-80 files, 2-4 modules, unit/integration/E2E.
        XL: 80+ files, 4+ modules, architecture-affecting.
    """

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class StoryMode(StrEnum):
    """Execution route for a governing story run.

    Exactly two values; `execution_route` is `StoryMode | None` and
    carries `None` for non-implementing stories (FK-24 §24.3.2:
    `execution` / `exploration` / `None`).

    Note: `mode`/`execution_route` must not be confused with
    `operating_mode` from FK-56 — the latter separates `ai_augmented`
    and `story_execution`. Likewise the fast/standard mode (AG3-018,
    FK-24 §24.3.3) is a SEPARATE axis and NOT an ``execution_route`` value;
    it is carried via ``WireStoryMode`` / ``StoryContext.mode``.

    Attributes:
        EXECUTION: Direct execution path without an exploration prelude.
        EXPLORATION: Exploration path as a prelude before implementation.
    """

    EXECUTION = "execution"
    EXPLORATION = "exploration"
