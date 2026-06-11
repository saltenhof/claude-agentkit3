"""ArtifactClass and EnvelopeStatus — artifact classification.

Source of truth:
- ArtifactClass: FK-71 §71.1.1, lines 90-99 (eight artifact classes, lower-case)
  plus ``prompt_audit`` (AG3-015, FK-44 §44.6 — prompt-audit records).
- EnvelopeStatus: FK-71 §71.2, line 145 (PASS/FAIL/WARN/ERROR, upper-case).

Wire values for ArtifactClass are lowercase and consistent with the
Postgres CHECK constraint from AG3-023 §2.1.4 (extended with
``prompt_audit`` in AG3-015).
"""

from __future__ import annotations

from enum import StrEnum


class ArtifactClass(StrEnum):
    """Producer class of an artifact per FK-71 §71.1.1.

    Attributes:
        WORKER: Worker-agent output (worker-manifest, protocol, code).
        QA: QA-subflow output (structural, policy, semantic_review).
        PIPELINE: Pipeline-runner output (story_contexts, flow_executions).
        TELEMETRY: Telemetry events / export bundle.
        GOVERNANCE: Guard / integrity-gate output.
        ENTWURF: Worker draft artifact (exploration phase). Wire value
            ``"entwurf"`` is a frozen contract string (FK-71 §71.1.1).
        HANDOVER: Worker handover (implementation phase).
        ADVERSARIAL_TEST_SANDBOX: Adversarial-test sandbox directory.
        PROMPT_AUDIT: Prompt-runtime audit record (FK-44 §44.6, AG3-015).
    """

    WORKER = "worker"
    QA = "qa"
    PIPELINE = "pipeline"
    TELEMETRY = "telemetry"
    GOVERNANCE = "governance"
    ENTWURF = "entwurf"
    HANDOVER = "handover"
    ADVERSARIAL_TEST_SANDBOX = "adversarial_test_sandbox"
    PROMPT_AUDIT = "prompt_audit"


class EnvelopeStatus(StrEnum):
    """Artifact-envelope status per FK-71 §71.2.

    The LLM check status ``PASS_WITH_CONCERNS`` is mapped to ``WARN``
    during aggregation — this mapping lives in AG3-022, not here.

    Attributes:
        PASS: Check passed.
        FAIL: Check not passed — blocks the story.
        WARN: Aggregate of a ``PASS_WITH_CONCERNS`` LLM status.
        ERROR: Infrastructure error (no LLM result).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    ERROR = "ERROR"
