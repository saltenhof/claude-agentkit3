"""Init-hook: registers the prompt-runtime audit producer.

Called once from the composition root (app bootstrap) before any
pipeline run, mirroring ``verify_system.register.register_verify_producers``
(AG3-023 §2.1.6.1). Keeps registration out of the package ``__init__``.

FK-44 §44.6 (audit persistence via ArtifactManager); Entscheidung 1 of
AG3-015 (producer ``prompt_runtime`` for ``ArtifactClass.PROMPT_AUDIT``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts import ProducerType
from agentkit.core_types import ArtifactClass
from agentkit.prompt_runtime.audit import PROMPT_AUDIT_PRODUCER_NAME

if TYPE_CHECKING:
    from agentkit.artifacts import ProducerRegistry


def register_prompt_runtime_producers(registry: ProducerRegistry) -> None:
    """Register the deterministic prompt-audit producer.

    Idempotent: a re-run with the same registry overwrites the entry with
    identical values (AG3-022 §2.1.5.1 init strategy). Belongs in the
    composition root.

    Args:
        registry: Fresh or pre-populated ``ProducerRegistry`` (mutated).
    """
    registry.register(
        ArtifactClass.PROMPT_AUDIT,
        PROMPT_AUDIT_PRODUCER_NAME,
        ProducerType.DETERMINISTIC,
    )


__all__ = ["register_prompt_runtime_producers"]
