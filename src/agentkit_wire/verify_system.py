"""Verify-system vocabulary of the ``/v1`` boundary (FK-27 / FK-28 / FK-34).

Two operations of the capability bounded context ``verify-system`` cross the
edge/core boundary, and both carry the same shape of traffic: the developer
machine holds raw observations it is the only one able to make, the core holds
the judgement it is the only one allowed to make.

* **Story-conflict assessment** (FK-21 §21.4.1 Schritt 3). The edge runs the
  stage-1 similarity search and ships the surviving candidates; the core runs
  the LLM conflict assessment and answers with a binary verdict. The verdict
  vocabulary is binary ON PURPOSE: FK-21 §21.4.1 Schritt 3 specifies ``PASS``
  (no conflict) or ``FAIL`` (duplicate / overlap), and the ambiguous
  ``PASS_WITH_CONCERNS`` of the shared Layer-2 aggregation is collapsed to
  ``FAIL`` by the core before it ever reaches the wire. Carrying the ternary
  enum here would put a third value on the boundary that no producer may emit
  and that the single consumer treats as "no conflict" -- a fail-open surface.

* **Verify-evidence assembly** (FK-28 §28.7.1). The human operator recovery CLI
  ships the edge-exported evidence checkpoint; the core assembles the review
  bundle and answers with the manifest. The manifest travels as the canonical
  JSON document its owner (``verify_system.evidence.BundleManifest``) produced.
  The edge never interprets it -- the recovery CLI writes it to disk and prints
  it -- so a second typed copy of the manifest model here would be a second
  truth for a document with a living owner, not a contract.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConflictVerdict(StrEnum):
    """Binary outcome of the create-time conflict assessment (FK-21 §21.4.1)."""

    PASS = "PASS"
    FAIL = "FAIL"


class ConflictCandidate(BaseModel):
    """One above-threshold similarity candidate handed to the assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    title: str = ""
    snippet: str = ""


class StoryConflictAssessmentRequest(BaseModel):
    """Wire request of the create-time conflict assessment.

    ``story_id`` is the DRAFT display-id: at assessment time the story does not
    exist yet, so it is the search scope, never a persisted identity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    story_description: str = Field(min_length=1)
    candidates: tuple[ConflictCandidate, ...] = Field(min_length=1)


class StoryConflictAssessmentResponse(BaseModel):
    """Binary verdict of the create-time conflict assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: ConflictVerdict


class EvidenceRepository(BaseModel):
    """Logical repository of the evidence checkpoint -- never a physical path.

    ``repo_path`` is deliberately absent: a developer-machine worktree path has
    no meaning on the core host, and the assembler never opens it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    git_base_branch: str = Field(default="main", min_length=1)
    role: str = Field(default="app", min_length=1)
    affected: bool = True
    changed_files: tuple[str, ...] = ()


class EvidenceFile(BaseModel):
    """One content-bound file observation made on the developer machine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    content: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerifyEvidenceAssemblyRequest(BaseModel):
    """Wire request of the operator-recovery evidence assembly (FK-28 §28.7.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str = Field(min_length=1)
    repositories: tuple[EvidenceRepository, ...] = Field(min_length=1)
    collected_files: tuple[EvidenceFile, ...] = ()


class VerifyEvidenceAssemblyResponse(BaseModel):
    """Assembled review bundle of one evidence checkpoint.

    ``bundle_manifest_json`` is the canonical manifest document as its owner
    serialized it. It is opaque on the wire by design (see the module
    docstring); ``manifest_hash`` and ``merge_paths`` are lifted out because
    they are the two values the recovery CLI reports without reading the
    document.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    merge_paths: tuple[str, ...]
    bundle_manifest_json: str = Field(min_length=1)


__all__ = [
    "ConflictCandidate",
    "ConflictVerdict",
    "EvidenceFile",
    "EvidenceRepository",
    "StoryConflictAssessmentRequest",
    "StoryConflictAssessmentResponse",
    "VerifyEvidenceAssemblyRequest",
    "VerifyEvidenceAssemblyResponse",
]
