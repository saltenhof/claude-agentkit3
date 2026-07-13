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
    if not _echoes_match(payload, result):
        return False
    repo_ids = {repo.repo_id for repo in payload.repositories}
    if result.stage is VerifyEvidenceStage.BASE_COLLECTION:
        return all(file.repo_id in repo_ids for file in result.files)
    return _dynamic_result_matches(payload, result, repo_ids)


def _echoes_match(
    payload: CollectVerifyEvidenceCommandPayload,
    result: VerifyEvidenceReport,
) -> bool:
    return (
        result.stage is payload.stage
        and result.batch_id == payload.batch_id
        and result.generation == payload.generation
        and result.candidate_digest == payload.candidate_digest
        and result.request_digest == payload.request_digest
    )


def _dynamic_result_matches(
    payload: CollectVerifyEvidenceCommandPayload,
    result: VerifyEvidenceReport,
    repo_ids: set[str],
) -> bool:
    expected = {request.request_index for request in payload.requests}
    observed = [item.request_index for item in result.observations]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        return False
    requests = {item.request_index: item for item in payload.requests}
    for observation in result.observations:
        request = requests[observation.request_index]
        if any(candidate.repo_id not in repo_ids for candidate in observation.candidates):
            return False
        if not _observation_matches_request(request.request_type, observation):
            return False
    return True


def _observation_matches_request(request_type: str, observation: object) -> bool:
    from agentkit.backend.core_types.verify_evidence import VerifyEvidenceObservation

    if not isinstance(observation, VerifyEvidenceObservation):
        return False
    if request_type != "NEED_TEST_EVIDENCE":
        return observation.content is None
    if observation.candidates:
        return False
    return observation.status.value != "COLLECTED" or bool(observation.content)


__all__ = ["verify_evidence_result_matches_command"]
