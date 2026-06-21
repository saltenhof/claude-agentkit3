"""Mandate-classification sub-package of the exploration BC (FK-25).

This package implements the deterministic / signal-bearing parts of the
exploration mandate classification (FK-25 §25.3-25.7) plus the Klasse-2
fine-design subprocess skeleton (FK-25 §25.5):

* :class:`MandateClassification` -- the top classifier (FK-25 §25.4.1 check
  order Klasse 1 -> 3 -> 4 -> 2, first hit wins);
* :class:`ScopeExplosionDetector` -- the quantitative scope-explosion signal
  (FK-25 §25.6, >= 2 HIGH indicators => Klasse 3);
* :class:`ImpactExceedanceChecker` -- the ordinal impact comparison
  (FK-25 §25.7, actual > declared => Klasse 4);
* :class:`FineDesignSubprocess` -- the Klasse-2 fine-design skeleton
  (FK-25 §25.5; single-LLM-per-round, multi-LLM is a follow-up story).

``agentkit.backend.exploration`` is a bloodgroup-A domain core (ARCH-22 / ARCH-31): no
direct filesystem I/O, no ``state_backend.store`` imports. All side-effecting
collaborators (telemetry emitter, fine-design evaluator, clock) are injected.
"""

from __future__ import annotations

from agentkit.backend.exploration.mandate.classification import (
    MandateClass,
    MandateClassification,
    MandateClassificationResult,
)
from agentkit.backend.exploration.mandate.fine_design import (
    FineDesignDecision,
    FineDesignEvaluator,
    FineDesignEvaluatorUnavailableError,
    FineDesignResult,
    FineDesignRoundOutcome,
    FineDesignSubprocess,
)
from agentkit.backend.exploration.mandate.impact_checker import (
    IMPACT_ORDER,
    ImpactExceedanceChecker,
    ImpactExceedanceResult,
    impact_rank,
)
from agentkit.backend.exploration.mandate.scope_detector import (
    ScopeExplosionDetector,
    ScopeExplosionResult,
    ScopeIndicator,
    ScopeIndicatorWeight,
)

__all__ = [
    "IMPACT_ORDER",
    "FineDesignDecision",
    "FineDesignEvaluator",
    "FineDesignEvaluatorUnavailableError",
    "FineDesignResult",
    "FineDesignRoundOutcome",
    "FineDesignSubprocess",
    "ImpactExceedanceChecker",
    "ImpactExceedanceResult",
    "MandateClass",
    "MandateClassification",
    "MandateClassificationResult",
    "ScopeExplosionDetector",
    "ScopeExplosionResult",
    "ScopeIndicator",
    "ScopeIndicatorWeight",
    "impact_rank",
]
