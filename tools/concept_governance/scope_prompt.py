"""Pinned prompt rendering for the W3 closed-set evaluator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from concept_governance.scope_models import SCOPE_PROMPT_VERSION, ScopePartition

SCOPE_PROMPT_PATH = Path(__file__).parent / "prompts" / "scope_consistency_v1.md"
SCOPE_PROMPT_TEMPLATE_SHA256 = "2f842e9a250f9b863614f453235aa2310b94b447d66a49481fc046c74c7eb387"


class ScopePromptVersionError(ValueError):
    """Raised when the W3 prompt asset drifts without a version bump."""


def render_scope_prompt(partition: ScopePartition) -> tuple[str, str]:
    """Render one complete partition and return text plus rendered hash."""
    template = SCOPE_PROMPT_PATH.read_text(encoding="utf-8")
    actual = hashlib.sha256(template.encode("utf-8")).hexdigest()
    if actual != SCOPE_PROMPT_TEMPLATE_SHA256:
        raise ScopePromptVersionError(
            f"prompt asset hash {actual} does not match {SCOPE_PROMPT_VERSION} "
            f"pin {SCOPE_PROMPT_TEMPLATE_SHA256}"
        )
    context = {
        "scope": partition.scope,
        "partition": {"index": partition.index, "count": partition.count},
        "assertions": [item.model_dump() for item in partition.assertions],
    }
    rendered = f"{template.rstrip()}\n\n## Evaluation input\n{json.dumps(context, ensure_ascii=False)}"
    return rendered, hashlib.sha256(rendered.encode("utf-8")).hexdigest()
