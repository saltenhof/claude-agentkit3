"""Deterministic Zone-2 runtime for Layer-3 Adversarial Testing (FK-48 §48.1).

AG3-079: the real Schicht-3 runtime behind the AG3-044 spawn mechanism. The
adversarial agent itself is a Harness-Sub-Agent (the only allowed mock boundary,
FK-48 §48.1.1); everything in this sub-package is deterministic Zone-2 pipeline
logic — NO LLM, NO agent — that orchestrates the FK-48 §48.1.3 phases, reads the
sandbox result, forces the mandatory sparring call over the AG3-065 transport,
promotes/quarantines the sandbox tests, materialises ``adversarial.json`` via the
``ArtifactManager`` and feeds unmet mandatory targets back to Layer 2.

Module map:

* :mod:`models` — typed sandbox-result + ``adversarial.json`` schema (3.1).
* :mod:`sparring` — mandatory sparring over the AG3-065 transport (AC3).
* :mod:`promotion` — deterministic test promotion / quarantine (AC4).
* :mod:`artifact` — ``adversarial.json`` materialisation via ArtifactManager (AC5).
* :mod:`feedback` — Layer-3 -> Layer-2 mandatory-target feedback (AC8).
* :mod:`runner` — the deterministic orchestrator the challenger drives (AC1/2/6).
"""

from __future__ import annotations

from agentkit.backend.verify_system.adversarial_orchestrator.runtime.models import (
    ADVERSARIAL_RESULT_SCHEMA_VERSION,
    ADVERSARIAL_SANDBOX_RESULT_FILENAME,
    AdversarialResultArtifact,
    AdversarialTelemetryCounts,
    MandatoryTargetResult,
    PromotionSummary,
    SandboxResult,
    SandboxTest,
    SparringProof,
)

__all__ = [
    "ADVERSARIAL_RESULT_SCHEMA_VERSION",
    "ADVERSARIAL_SANDBOX_RESULT_FILENAME",
    "AdversarialResultArtifact",
    "AdversarialTelemetryCounts",
    "MandatoryTargetResult",
    "PromotionSummary",
    "SandboxResult",
    "SandboxTest",
    "SparringProof",
]
