"""Layer-2 Review Input model (FK-27 §27.4-§27.6).

Defines the four canonical text-based inputs that Layer-2 LLM-Evaluators
operate on, per FK-27 §27.4 (QaReview), §27.5 (SemanticReview), §27.6
(DocFidelity).

The four fields mirror the four Worker-produced artefacts that arrive at the
QA-subflow:
- ``story_spec``: The story specification text (story.md or excerpt).
- ``diff_summary``: Human-readable summary of the diffs the Worker produced.
- ``concept_excerpt``: Relevant concept-doc excerpt (from depends_on refs).
- ``handover``: Worker handover text (list of produced artefacts + rationale).

When ``review_input`` is ``None`` on a Layer-2 reviewer call, the reviewer
raises ``Layer2InputMissingError`` (fail-closed). Until Workers produce
handover artefacts (THEME-009), the ``ImplementationPhaseHandler`` passes a
``Layer2ReviewInput`` with empty strings -- Layer-2 reviewers then emit a
MAJOR finding with code ``"layer2_input.missing"`` rather than silently PASS.

Visibility rule (AC001): imports exclusively from
``verify_system.llm_evaluator.*`` and ``verify_system.system``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Layer2ReviewInput(BaseModel):
    """The four FK-27 §27.4-§27.6 text inputs for Layer-2 reviewers.

    FK-27 §27.4 (QaReview), §27.5 (SemanticReview), §27.6 (DocFidelity).

    Attributes:
        story_spec: Story specification text (story.md content or excerpt).
            Empty string when not yet available (THEME-009).
        diff_summary: Summary of Worker-produced diffs (file paths + change
            kind). Empty string when not yet available.
        concept_excerpt: Relevant concept-doc excerpt tied to
            ``depends_on`` refs. Empty string when not yet available.
        handover: Worker handover text (artefact list + rationale).
            Empty string when not yet available (THEME-009).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_spec: str = ""
    diff_summary: str = ""
    concept_excerpt: str = ""
    handover: str = ""


class Layer2InputMissingError(Exception):
    """Raised by Layer-2 reviewers when review_input is None (fail-closed).

    FK-27 §27.4-§27.6: Layer-2 reviewers require an explicit
    ``Layer2ReviewInput`` instance. Passing ``None`` is a programming error
    (the caller must provide a default input, even with empty fields).
    """
