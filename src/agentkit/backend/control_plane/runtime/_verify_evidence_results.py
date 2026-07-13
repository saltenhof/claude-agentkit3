"""Correlation checks for verify-evidence edge command reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from agentkit.backend.core_types.verify_evidence import (
    CollectVerifyEvidenceCommandPayload,
    VerifyEvidenceReport,
    VerifyEvidenceStage,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import EdgeCommandRecord


def verify_evidence_result_matches_command(
    command: EdgeCommandRecord,
    result: object,
) -> bool:
    """Return whether a typed report exactly matches its immutable command."""
    if command.command_kind != "collect_verify_evidence":
        return not isinstance(result, VerifyEvidenceReport)
    if not isinstance(result, VerifyEvidenceReport):
        return False
    try:
        payload = CollectVerifyEvidenceCommandPayload.model_validate(command.payload)
    except ValidationError:
        return False
    if (
        result.stage is not payload.stage
        or result.batch_id != payload.batch_id
        or result.generation != payload.generation
        or result.candidate_digest != payload.candidate_digest
        or result.request_digest != payload.request_digest
    ):
        return False
    repo_ids = {repo.repo_id for repo in payload.repositories}
    if result.stage is VerifyEvidenceStage.BASE_COLLECTION:
        return all(file.repo_id in repo_ids for file in result.files)
    expected = {request.request_index for request in payload.requests}
    observed = [item.request_index for item in result.observations]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        return False
    requests = {item.request_index: item for item in payload.requests}
    for observation in result.observations:
        request = requests[observation.request_index]
        if any(candidate.repo_id not in repo_ids for candidate in observation.candidates):
            return False
        if request.request_type == "NEED_TEST_EVIDENCE":
            if observation.candidates:
                return False
            if (
                observation.status.value == "COLLECTED"
                and not observation.content
            ):
                return False
        elif observation.content is not None:
            return False
    return True


__all__ = ["verify_evidence_result_matches_command"]
