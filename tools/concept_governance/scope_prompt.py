"""Pinned prompt rendering for the W3 closed-set evaluator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from concept_governance.scope_models import SCOPE_PROMPT_VERSION, ScopePartition
from concept_governance.source_spans import build_source_span_map

SCOPE_PROMPT_PATH = Path(__file__).parent / "prompts" / "scope_consistency_v2.md"
SCOPE_PROMPT_TEMPLATE_SHA256 = "3a0abe6c30a3e3a4e3612e54a1a5723f01fc1467f946a5b1937ec40e42febce0"


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
        "sources": [
            {
                "doc": item.doc,
                "anchor": item.anchor,
                **build_source_span_map(item.chunk_id, item.text).prompt_value,
            }
            for item in partition.assertions
        ],
    }
    rendered = f"{template.rstrip()}\n\n## Evaluation input\n{json.dumps(context, ensure_ascii=False)}"
    return rendered, hashlib.sha256(rendered.encode("utf-8")).hexdigest()
