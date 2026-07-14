"""Versioned prompt loading and rendering for W2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from concept_governance.models import PROMPT_VERSION

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

PROMPT_PATH = Path(__file__).parent / "prompts" / "authority_prose_v1.md"
PROMPT_TEMPLATE_SHA256 = "84d613e4b1cb89682617f2c3c7b630ce0bc82809fda5a28b54237c7948676063"
RETRY_MARKER = "<!-- RETRY_CORRECTION -->"


class PromptVersionError(ValueError):
    """Raised when prompt content drifts without an explicit version update."""


def render_prompt(
    chunk: ConceptChunk,
    vocabulary: tuple[str, ...],
    *,
    retry: bool = False,
) -> tuple[str, str]:
    """Render the pinned prompt and return text plus rendered SHA-256."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    actual = hashlib.sha256(template.encode("utf-8")).hexdigest()
    if actual != PROMPT_TEMPLATE_SHA256:
        raise PromptVersionError(
            f"prompt asset hash {actual} does not match {PROMPT_VERSION} pin {PROMPT_TEMPLATE_SHA256}"
        )
    base, marker, correction = template.partition(RETRY_MARKER)
    if not marker:
        raise PromptVersionError(f"prompt asset lacks {RETRY_MARKER}")
    body = f"{base.rstrip()}\n\n{correction.strip()}" if retry else base.rstrip()
    context = {
        "doc": chunk.rel_path,
        "anchor": chunk.section_anchor,
        "heading": chunk.heading,
        "scope_vocabulary": vocabulary,
        "content": chunk.content,
    }
    rendered = f"{body}\n\n## Evaluation input\n{json.dumps(context, ensure_ascii=False)}"
    return rendered, hashlib.sha256(rendered.encode("utf-8")).hexdigest()
