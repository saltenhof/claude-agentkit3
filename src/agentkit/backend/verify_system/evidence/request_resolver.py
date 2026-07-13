"""Backend-pure consolidation for reviewer preflight request observations."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.core_types.verify_evidence import (
    VerifyEvidenceFile,
    VerifyEvidenceObservation,
    VerifyEvidenceObservationStatus,
)
from agentkit.backend.verify_system.evidence.request_types import (
    RequestResult,
    RequestResultStatus,
    RequestType,
    ReviewerRequest,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 30
MAX_REQUESTS = 8


def parse_preflight_response(raw_response: str) -> list[ReviewerRequest]:
    """Parse reviewer JSON into at most eight typed requests."""
    try:
        data = json.loads(raw_response)
        raw_requests = data["requests"]
        if not isinstance(raw_requests, list):
            raise ValueError("requests must be a list")
        if len(raw_requests) > MAX_REQUESTS:
            logger.warning(
                "Preflight response contained %s requests; processing first %s.",
                len(raw_requests),
                MAX_REQUESTS,
            )
        return [ReviewerRequest.model_validate(item) for item in raw_requests[:MAX_REQUESTS]]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Preflight response could not be parsed: %s", exc)
        return []


class RequestResolver:
    """Apply backend-owned D3 and local concept resolution to edge observations."""

    def __init__(self, *, story_dir: Path) -> None:
        """Create a resolver whose only filesystem authority is backend-local docs."""
        self._story_dir = story_dir

    def resolve_all(
        self,
        requests: Sequence[ReviewerRequest],
        observations: Sequence[VerifyEvidenceObservation] = (),
    ) -> list[RequestResult]:
        """Resolve capped requests without ever reading a target worktree."""
        if len(requests) > MAX_REQUESTS:
            logger.warning(
                "Preflight resolver received %s requests; processing first %s.",
                len(requests),
                MAX_REQUESTS,
            )
        by_index = {item.request_index: item for item in observations}
        return [
            self._resolve_single(request, by_index.get(index))
            for index, request in enumerate(requests[:MAX_REQUESTS])
        ]

    def _resolve_single(
        self,
        request: ReviewerRequest,
        observation: VerifyEvidenceObservation | None,
    ) -> RequestResult:
        if request.type is RequestType.NEED_CONCEPT_SOURCE:
            return self._resolve_concept_source(request)
        if observation is None:
            return _unresolved(
                request,
                "Edge evidence was not reported.",
                finding_code="EDGE_EVIDENCE_UNAVAILABLE",
            )
        if observation.status is VerifyEvidenceObservationStatus.TIMEOUT:
            return RequestResult(
                request=request,
                status=RequestResultStatus.TIMEOUT,
                content=observation.content or "Edge evidence collection timed out.",
                finding_code=observation.finding_code or "EDGE_EVIDENCE_TIMEOUT",
                duration_ms=observation.duration_ms,
            )
        if observation.status is VerifyEvidenceObservationStatus.REJECTED:
            return RequestResult(
                request=request,
                status=RequestResultStatus.ERROR,
                content=observation.content or "Edge rejected the evidence request.",
                finding_code=observation.finding_code or "EDGE_REQUEST_REJECTED",
                duration_ms=observation.duration_ms,
            )
        if request.type is RequestType.NEED_TEST_EVIDENCE:
            if observation.status is VerifyEvidenceObservationStatus.COLLECTED:
                return RequestResult(
                    request=request,
                    status=RequestResultStatus.RESOLVED,
                    content=observation.content,
                    duration_ms=observation.duration_ms,
                )
            return _unresolved(
                request,
                observation.content or "Test evidence was not collected.",
                finding_code=observation.finding_code or "TEST_EVIDENCE_UNRESOLVED",
                duration_ms=observation.duration_ms,
            )
        return _d3_result(
            request,
            observation.candidates,
            duration_ms=observation.duration_ms,
            finding_code=observation.finding_code,
        )

    def _resolve_concept_source(self, request: ReviewerRequest) -> RequestResult:
        """Resolve headings only from backend-local ``concept``/``stories`` docs."""
        start = time.monotonic()
        pattern = re.compile(
            rf"^#+\s+.*{re.escape(request.target)}.*$", re.MULTILINE
        )
        project_root = _project_root_for_story_dir(self._story_dir)
        roots = (project_root / "concept", project_root / "stories", self._story_dir)
        candidates: list[VerifyEvidenceFile] = []
        for root in roots:
            if not root.exists():
                continue
            for file_path in root.rglob("*.md"):
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if pattern.search(content):
                    relative = file_path.relative_to(project_root).as_posix()
                    candidates.append(
                        VerifyEvidenceFile.from_content(
                            repo_id="_context", path=relative, content=content
                        )
                    )
        return _d3_result(
            request,
            candidates,
            duration_ms=_elapsed_ms(start),
        )


def timeout_results(requests: Sequence[ReviewerRequest]) -> tuple[RequestResult, ...]:
    """Return named timeout outcomes for every worktree-dependent request."""
    return tuple(
        RequestResolver(story_dir=Path("."))._resolve_single(
            request,
            None
            if request.type is RequestType.NEED_CONCEPT_SOURCE
            else VerifyEvidenceObservation(
                request_index=index,
                status=VerifyEvidenceObservationStatus.TIMEOUT,
                finding_code="EDGE_EVIDENCE_TIMEOUT",
            ),
        )
        for index, request in enumerate(requests[:MAX_REQUESTS])
    )


def _d3_result(
    request: ReviewerRequest,
    candidates: Sequence[VerifyEvidenceFile],
    *,
    duration_ms: int,
    finding_code: str | None = None,
) -> RequestResult:
    unique = _unique_candidates(candidates)
    paths = tuple(f"{item.repo_id}:{item.path}" for item in unique)
    if len(unique) == 1:
        candidate = unique[0]
        return RequestResult(
            request=request,
            status=RequestResultStatus.RESOLVED,
            content=candidate.content,
            file_path=candidate.path,
            candidate_paths=paths,
            duration_ms=duration_ms,
        )
    content = (
        "No deterministic match found."
        if not unique
        else "Ambiguous candidates:\n" + "\n".join(paths)
    )
    return RequestResult(
        request=request,
        status=RequestResultStatus.UNRESOLVED,
        content=content,
        candidate_paths=paths,
        finding_code=finding_code or "D3_NO_UNIQUE_MATCH",
        duration_ms=duration_ms,
    )


def _unresolved(
    request: ReviewerRequest,
    content: str,
    *,
    finding_code: str,
    duration_ms: int = 0,
) -> RequestResult:
    return RequestResult(
        request=request,
        status=RequestResultStatus.UNRESOLVED,
        content=content,
        finding_code=finding_code,
        duration_ms=duration_ms,
    )


def _unique_candidates(
    candidates: Sequence[VerifyEvidenceFile],
) -> list[VerifyEvidenceFile]:
    by_key = {(candidate.repo_id, candidate.path): candidate for candidate in candidates}
    return [by_key[key] for key in sorted(by_key)]


def _project_root_for_story_dir(story_dir: Path) -> Path:
    resolved = story_dir.resolve()
    if resolved.parent.name == "stories":
        return resolved.parent.parent
    return resolved.parent


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


__all__ = [
    "MAX_REQUESTS",
    "REQUEST_TIMEOUT_S",
    "RequestResolver",
    "parse_preflight_response",
    "timeout_results",
]
