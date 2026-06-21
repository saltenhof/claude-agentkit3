"""Core-type enums (foundation module).

Single source of truth for all cross-cutting StrEnum types that are
needed by multiple bounded contexts at once. This module may import
from NO other module (no circular import); ``agentkit.backend.core_types`` is the
``domain_core_foundation`` boundary (bloodgroup A: a leaf foundation that
carries AK3 DOMAIN core types -- ArtifactClass/QaContext/StoryStatus/
OperatingMode/... -- so NOT fachneutral Null-Software; ``importable_by: any``,
modeled in ``concept/formal-spec/architecture-conformance/entities.md``).

Story anchor: AG3-021 (typed core enums). Value lists and wire strings
are normative in AG3-021 §2.1.1.1; every member is pinned by the
contract test in `tests/contract/core_types/`.
"""

from __future__ import annotations

from agentkit.backend.core_types.artifact import ArtifactClass, EnvelopeStatus
from agentkit.backend.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.backend.core_types.closure import ClosureVerdict, MergePolicy
from agentkit.backend.core_types.dependency import StoryDependencyKind
from agentkit.backend.core_types.exploration import ExplorationGateStatus
from agentkit.backend.core_types.failure_corpus import (
    CheckStatus,
    CheckType,
    FailureCategory,
    IncidentStatus,
    PatternStatus,
)
from agentkit.backend.core_types.operating_mode import OperatingMode
from agentkit.backend.core_types.override import OverrideType
from agentkit.backend.core_types.pause_reason import PauseReason
from agentkit.backend.core_types.policy_verdict import PolicyVerdict
from agentkit.backend.core_types.qa_artifact_names import (
    ALL_QA_ARTIFACT_FILES,
    GUARDRAIL_FILE,
    HANDOVER_FILE,
    LAYER_ARTIFACT_FILES,
    PROTOCOL_FILE,
    QA_LAYER2_FILES,
    VERIFY_DECISION_FILE,
    VERIFY_DECISION_STAGE,
    WORKER_MANIFEST_FILE,
)
from agentkit.backend.core_types.qa_context import QaContext
from agentkit.backend.core_types.severity import Severity
from agentkit.backend.core_types.story import StoryMode, StorySize
from agentkit.backend.core_types.worker import (
    BlockingCategory,
    SpawnKind,
    SpawnReason,
    SpawnRequest,
)

__all__ = [
    "ALL_QA_ARTIFACT_FILES",
    "ArtifactClass",
    "AttemptOutcome",
    "BlockingCategory",
    "CheckStatus",
    "CheckType",
    "ClosureVerdict",
    "EnvelopeStatus",
    "ExplorationGateStatus",
    "FailureCategory",
    "FailureCause",
    "GUARDRAIL_FILE",
    "HANDOVER_FILE",
    "IncidentStatus",
    "LAYER_ARTIFACT_FILES",
    "MergePolicy",
    "OperatingMode",
    "OverrideType",
    "PatternStatus",
    "PauseReason",
    "PolicyVerdict",
    "PROTOCOL_FILE",
    "QA_LAYER2_FILES",
    "VERIFY_DECISION_FILE",
    "VERIFY_DECISION_STAGE",
    "WORKER_MANIFEST_FILE",
    "QaContext",
    "Severity",
    "SpawnKind",
    "SpawnReason",
    "SpawnRequest",
    "StoryDependencyKind",
    "StoryMode",
    "StorySize",
]
