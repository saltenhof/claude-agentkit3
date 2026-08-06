"""Authenticated HTTPS client for writer-owned failure-corpus mutations."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING

from agentkit.backend.failure_corpus.http_models import (
    FailureCorpusCheckReviewRequest,
    FailureCorpusCheckReviewResponse,
    FailureCorpusEffectivenessRequest,
    FailureCorpusEffectivenessResponse,
    FailureCorpusIncidentMutationRequest,
    FailureCorpusIncidentMutationResponse,
    FailureCorpusPatternReviewRequest,
    FailureCorpusPatternReviewResponse,
)

if TYPE_CHECKING:
    from agentkit.harness_client.projectedge.client import ControlPlaneTransport


class FailureCorpusWriterClient:
    """Send all mutating failure-corpus commands to the active writer."""

    def __init__(self, transport: ControlPlaneTransport) -> None:
        self._transport = transport

    def add_incident(
        self,
        project_key: str,
        request: FailureCorpusIncidentMutationRequest,
    ) -> FailureCorpusIncidentMutationResponse:
        """Record an incident through the project-scoped writer route."""

        data = self._post(project_key, "/incidents", request.model_dump(mode="json"))
        return FailureCorpusIncidentMutationResponse.model_validate(data)

    def review_pattern(
        self,
        project_key: str,
        pattern_id: str,
        request: FailureCorpusPatternReviewRequest,
    ) -> FailureCorpusPatternReviewResponse:
        """Commit a human pattern decision through the active writer."""

        pattern_segment = urllib.parse.quote(pattern_id, safe="")
        data = self._post(
            project_key,
            f"/patterns/{pattern_segment}/review",
            request.model_dump(mode="json"),
        )
        return FailureCorpusPatternReviewResponse.model_validate(data)

    def review_check(
        self,
        project_key: str,
        check_id: str,
        request: FailureCorpusCheckReviewRequest,
    ) -> FailureCorpusCheckReviewResponse:
        """Commit a human check decision through the active writer."""

        check_segment = urllib.parse.quote(check_id, safe="")
        data = self._post(
            project_key,
            f"/checks/{check_segment}/review",
            request.model_dump(mode="json"),
        )
        return FailureCorpusCheckReviewResponse.model_validate(data)

    def report_effectiveness(
        self,
        project_key: str,
        request: FailureCorpusEffectivenessRequest,
    ) -> FailureCorpusEffectivenessResponse:
        """Run the mutating effectiveness job inside the active writer."""

        data = self._post(
            project_key,
            "/effectiveness-report",
            request.model_dump(mode="json"),
        )
        return FailureCorpusEffectivenessResponse.model_validate(data)

    def _post(
        self,
        project_key: str,
        suffix: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        project_segment = urllib.parse.quote(project_key, safe="")
        data = self._transport.send(
            method="POST",
            path=f"/v1/projects/{project_segment}/failure-corpus{suffix}",
            payload=payload,
        )
        data.pop("correlation_id", None)
        return data


__all__ = ["FailureCorpusWriterClient"]
