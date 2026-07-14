"""LLM client view over the shared W2 Hub batch session."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName
    from concept_governance.hub_batch import HubBatchSession


class HubBatchLlmClient:
    """Target one backend through a shared corpus batch session."""

    def __init__(self, session: HubBatchSession, model: HubBackendName) -> None:
        """Bind the shared session to one backend."""
        self._session = session
        self._model = model

    def complete(self, *, role: str, prompt: str) -> str:
        """Send the prompt on the shared session for the W2 role."""
        if role != "concept_authority_prose":
            raise ValueError(f"unsupported governance role: {role}")
        return self._session.send(self._model, prompt)
