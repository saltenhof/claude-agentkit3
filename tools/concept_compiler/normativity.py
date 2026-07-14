"""Shared deterministic normativity markers for concept tooling."""

from __future__ import annotations

import re

NORMATIVE_MODAL_RE = re.compile(
    r"\b(muss(?:t|en)?|darf\s+nur|sind?\s+pflicht|"
    r"single\s+source\s+of\s+truth|verboten|fail[-\s]closed|"
    r"shall|must)\b",
    re.IGNORECASE,
)
