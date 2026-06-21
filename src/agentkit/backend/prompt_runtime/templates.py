"""Prompt templates loaded from internal resource files."""

from __future__ import annotations

from agentkit.backend.prompt_runtime.resources import load_prompt_template


def _build_templates() -> dict[str, str]:
    names = (
        "worker-implementation",
        "worker-bugfix",
        "worker-concept",
        "worker-research",
        "worker-exploration",
        "worker-remediation",
        "qa-review",
        "qa-semantic-review",
        "qa-doc-fidelity",
        "qa-adversarial-review",
        "qa-conformance-goal",
        "qa-conformance-design",
        "qa-conformance-feedback",
        "doc-fidelity-feedback",
        # ARCH-55 note: the internal LLM prompt bodies (this whole template set,
        # including ``vectordb-conflict``) are German by an established repo-wide
        # convention -- every sibling prompt (qa-review, qa-semantic-review, ...)
        # is German Fachprosa. ``vectordb-conflict`` follows that convention
        # rather than introducing a lone English prompt; its operational wire
        # tokens (``check_id``, status values ``PASS|PASS_WITH_CONCERNS|FAIL``,
        # the role id ``story_creation_review``) are English.
        "vectordb-conflict",
    )
    return {name: load_prompt_template(name) for name in names}


TEMPLATES = _build_templates()

__all__ = ["TEMPLATES"]
