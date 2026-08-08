"""The verify-system ``/v1`` vocabulary is a contract, not a convenience (AG3-241).

``agentkit_wire.verify_system`` is what the developer machine and the core agree
on for the two operations of the capability bounded context. These tests pin the
properties a consumer on the other side of the wire is entitled to rely on, and
the two the story deliberately decided:

* the conflict verdict is **binary**. FK-21 §21.4.1 Schritt 3 specifies PASS or
  FAIL, and the ambiguous ``PASS_WITH_CONCERNS`` of the shared Layer-2
  aggregation is collapsed by the core BEFORE it reaches the wire. A third value
  here would be one no producer may emit and that the single consumer reads as
  "no conflict" -- a fail-open surface;
* the evidence checkpoint carries **no physical path**. A developer-machine
  worktree location is meaningless on the core host, and a field that supplied
  one would make core-side artefacts addressable from outside.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agentkit_wire.verify_system import (
    ConflictCandidate,
    ConflictVerdict,
    EvidenceFile,
    EvidenceRepository,
    StoryConflictAssessmentRequest,
    StoryConflictAssessmentResponse,
    VerifyEvidenceAssemblyRequest,
    VerifyEvidenceAssemblyResponse,
)

_MODELS = (
    ConflictCandidate,
    EvidenceFile,
    EvidenceRepository,
    StoryConflictAssessmentRequest,
    StoryConflictAssessmentResponse,
    VerifyEvidenceAssemblyRequest,
    VerifyEvidenceAssemblyResponse,
)
_SHA = "b" * 64


@pytest.mark.contract
@pytest.mark.parametrize("model", _MODELS, ids=lambda m: m.__name__)
class TestEveryModelIsAStrictFrozenContract:
    """A wire type that accepts unknown keys or mutates is not a contract."""

    def test_forbids_unknown_fields(self, model: type[BaseModel]) -> None:
        assert model.model_config.get("extra") == "forbid"

    def test_is_frozen(self, model: type[BaseModel]) -> None:
        assert model.model_config.get("frozen") is True


@pytest.mark.contract
class TestTheVerdictIsBinary:
    """The single decision this boundary carries admits exactly two answers."""

    def test_exactly_pass_and_fail(self) -> None:
        assert [member.value for member in ConflictVerdict] == ["PASS", "FAIL"]

    def test_the_ambiguous_layer2_value_is_not_on_the_wire(self) -> None:
        """``PASS_WITH_CONCERNS`` is collapsed by the core, never transported."""
        with pytest.raises(ValidationError):
            StoryConflictAssessmentResponse(verdict="PASS_WITH_CONCERNS")  # type: ignore[arg-type]

    def test_the_verdict_serializes_as_its_wire_string(self) -> None:
        response = StoryConflictAssessmentResponse(verdict=ConflictVerdict.FAIL)
        assert response.model_dump(mode="json") == {"verdict": "FAIL"}


@pytest.mark.contract
class TestTheAssessmentRequestCarriesSomethingToAssess:
    """An assessment is asked for because stage 1 found candidates."""

    def test_an_empty_candidate_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StoryConflictAssessmentRequest(
                story_id="DRAFT-1", story_description="x", candidates=()
            )

    def test_a_score_outside_the_similarity_range_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConflictCandidate(story_id="AG3-012", score=1.5)

    def test_an_empty_story_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StoryConflictAssessmentRequest(
                story_id="",
                story_description="x",
                candidates=(ConflictCandidate(story_id="AG3-012", score=0.9),),
            )

    def test_a_valid_request_round_trips_through_json(self) -> None:
        request = StoryConflictAssessmentRequest(
            story_id="DRAFT-1",
            story_description="Add retry/backoff.",
            candidates=(ConflictCandidate(story_id="AG3-012", score=0.94),),
        )
        assert (
            StoryConflictAssessmentRequest.model_validate(
                request.model_dump(mode="json")
            )
            == request
        )


@pytest.mark.contract
class TestTheEvidenceCheckpointCarriesNoPhysicalPath:
    """The repository is a handle; its location never crosses the boundary."""

    def test_repository_has_no_repo_path_field(self) -> None:
        assert "repo_path" not in EvidenceRepository.model_fields

    def test_a_supplied_repo_path_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRepository.model_validate(
                {"repo_id": "app", "repo_path": "C:/worktrees/app"}
            )

    def test_a_file_observation_is_content_bound(self) -> None:
        """Content, size and a full sha256 travel together or not at all."""
        with pytest.raises(ValidationError):
            EvidenceFile(
                repo_id="app", path="src/app.py", content="x", size=1, sha256="short"
            )

    def test_a_checkpoint_without_a_repository_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VerifyEvidenceAssemblyRequest(story_id="AG3-241", repositories=())


@pytest.mark.contract
class TestTheAssemblyResponseIsStampedAndOpaque:
    """The manifest travels as its owner serialized it, with its hash lifted out."""

    def test_the_manifest_hash_must_be_a_full_sha256(self) -> None:
        with pytest.raises(ValidationError):
            VerifyEvidenceAssemblyResponse(
                manifest_hash="not-a-hash",
                merge_paths=(),
                bundle_manifest_json="{}",
            )

    def test_an_empty_manifest_document_is_rejected(self) -> None:
        """"No bundle" is an error at the route, never an empty success body."""
        with pytest.raises(ValidationError):
            VerifyEvidenceAssemblyResponse(
                manifest_hash=_SHA, merge_paths=(), bundle_manifest_json=""
            )

    def test_the_manifest_stays_an_opaque_document(self) -> None:
        """No second typed copy of a model that already has a living owner."""
        assert (
            VerifyEvidenceAssemblyResponse.model_fields[
                "bundle_manifest_json"
            ].annotation
            is str
        )
