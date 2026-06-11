"""Producer types for the artifact BC (agentkit.artifacts).

Definitions:
- `ProducerType` — StrEnum with WORKER / LLM_REVIEWER / DETERMINISTIC
- `ProducerId` — NewType for type-safe instance ids
- `Producer` — Pydantic model with required fields

Source: bc-cut-decisions.md §BC 8, FK-71 §71.2.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

from pydantic import BaseModel, ConfigDict


class ProducerType(StrEnum):
    """Producer category of an artifact producer.

    Attributes:
        WORKER: Worker agent (implementation, draft, handover).
        LLM_REVIEWER: LLM-based reviewer (QA semantics, guard review).
        DETERMINISTIC: Deterministic check step (structural, policy).
    """

    WORKER = "WORKER"
    LLM_REVIEWER = "LLM_REVIEWER"
    DETERMINISTIC = "DETERMINISTIC"


#: Type-safe instance id of a producer (e.g. "worker-impl-run-42").
ProducerId = NewType("ProducerId", str)


class Producer(BaseModel):
    """Typed producer of an artifact (bc-cut-decisions.md §BC 8).

    Attributes:
        type: Category of the producer (WORKER / LLM_REVIEWER / DETERMINISTIC).
        name: Canonical name (e.g. ``qa-semantic-reviewer``).
        id: Unique instance id of this producer instance.
        version: Optional tool or bundle version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ProducerType
    name: str
    id: ProducerId
    version: str | None = None
