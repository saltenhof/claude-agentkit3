"""Versioned prompt loading and rendering for W2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from concept_governance.models import PROMPT_VERSION
from concept_governance.source_spans import build_source_span_map

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

PROMPT_PATH = Path(__file__).parent / "prompts" / "authority_prose_v2.md"
PROMPT_TEMPLATE_SHA256 = "816529099433b8eae2da5adfa9bbddcece1e0338537ba6a9af63f5b7c05aae5e"


class PromptVersionError(ValueError):
    """Raised when prompt content drifts without an explicit version update."""


def render_prompt(
    chunk: ConceptChunk,
    vocabulary: tuple[str, ...],
) -> tuple[str, str]:
    """Render the pinned prompt and return text plus rendered SHA-256."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    actual = hashlib.sha256(template.encode("utf-8")).hexdigest()
    if actual != PROMPT_TEMPLATE_SHA256:
        raise PromptVersionError(
            f"prompt asset hash {actual} does not match {PROMPT_VERSION} pin {PROMPT_TEMPLATE_SHA256}"
        )
    source = build_source_span_map(chunk.chunk_id, chunk.content)
    context = {
        "doc": chunk.rel_path,
        "anchor": chunk.section_anchor,
        "heading": chunk.heading,
        "scope_vocabulary": vocabulary,
        "source": source.prompt_value,
    }
    rendered = f"{template.rstrip()}\n\n## Evaluation input\n{json.dumps(context, ensure_ascii=False)}"
    return rendered, hashlib.sha256(rendered.encode("utf-8")).hexdigest()
