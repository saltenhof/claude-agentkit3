"""Core-Type-Enums (Foundation-Modul).

Single Source of Truth fuer alle Cross-Cutting-StrEnum-Typen, die von
mehreren Bounded Contexts gleichzeitig benoetigt werden. Dieses Modul
darf von KEINEM anderen Modul importieren (kein zyklischer Import);
es ist ein Bluttyp-0-Foundation-Modul.

Story-Anker: AG3-021 (Typisierte Kern-Enums). Wertelisten und
Wire-Strings sind in AG3-021 §2.1.1.1 normativ; jeder Member wird
durch den Contract-Test in `tests/contract/core_types/` gepinnt.
"""

from __future__ import annotations

from agentkit.core_types.artifact import ArtifactClass, EnvelopeStatus
from agentkit.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.core_types.closure import ClosureVerdict, MergePolicy
from agentkit.core_types.dependency import StoryDependencyKind
from agentkit.core_types.exploration import ExplorationGateStatus
from agentkit.core_types.failure_corpus import FailureCategory, PromotionStatus
from agentkit.core_types.pause_reason import PauseReason
from agentkit.core_types.policy_verdict import PolicyVerdict
from agentkit.core_types.qa_artifact_names import (
    ALL_QA_ARTIFACT_FILES,
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    QA_LAYER2_FILES,
    VERIFY_DECISION_FILE,
    VERIFY_DECISION_STAGE,
)
from agentkit.core_types.qa_context import QaContext
from agentkit.core_types.severity import Severity
from agentkit.core_types.story import StoryMode, StorySize
from agentkit.core_types.worker import BlockingCategory, SpawnReason

__all__ = [
    "ALL_QA_ARTIFACT_FILES",
    "ArtifactClass",
    "AttemptOutcome",
    "BlockingCategory",
    "ClosureVerdict",
    "EnvelopeStatus",
    "ExplorationGateStatus",
    "FailureCategory",
    "FailureCause",
    "GUARDRAIL_FILE",
    "LAYER_ARTIFACT_FILES",
    "MergePolicy",
    "PauseReason",
    "PolicyVerdict",
    "QA_LAYER2_FILES",
    "VERIFY_DECISION_FILE",
    "VERIFY_DECISION_STAGE",
    "PromotionStatus",
    "QaContext",
    "Severity",
    "SpawnReason",
    "StoryDependencyKind",
    "StoryMode",
    "StorySize",
]
