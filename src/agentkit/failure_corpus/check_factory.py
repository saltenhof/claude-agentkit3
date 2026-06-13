"""CheckFactory sub of the failure-corpus BC (FK-41 §41.6, AG3-078).

6-step Check-derivation flow:
  Step 1: LLM invariant sharpening via LlmEvaluator (mockable boundary).
  Step 2: Deterministic CheckType mapping via CATEGORY_TO_CHECK_TYPE matrix.
  Step 3: Create fc_check_proposals DRAFT via repository.
  Step 4: Human approval (three-valued: APPROVED / REJECTED / REVISE).
  Step 5: create_check_implementation_story (APPROVED path).
  Step 6: Effectiveness tracking (separate job, not here).

Sources:
- FK-41 §41.6 -- six steps
- FK-41 §41.6.2 -- invariant sharpening (LLM, F-41-070 reference example)
- FK-41 §41.6.3 -- deterministic check-type mapping
- FK-41 §41.6.5 -- three-valued approval
- FK-41 §41.6.6 -- create_check_implementation_story (transport-agnostic)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.core_types import CheckStatus, PatternStatus
from agentkit.failure_corpus.check_proposal import CheckProposalRecord
from agentkit.failure_corpus.errors import FailureCorpusError
from agentkit.failure_corpus.pattern_promotion import (
    CATEGORY_TO_CHECK_TYPE,
    CHECK_TYPE_FALSE_POSITIVE_RISK,
)
from agentkit.failure_corpus.top import CheckApprovalDecision
from agentkit.failure_corpus.types import CheckId, PatternId

if TYPE_CHECKING:
    from agentkit.state_backend.store.fc_check_proposal_repository import FcCheckProposalRepository
    from agentkit.state_backend.store.fc_pattern_repository import FcPatternRepository

# ---------------------------------------------------------------------------
# F-41-070 Reference Example (FK-41 §41.6.2 — permanent fixture/gate artifact)
# ---------------------------------------------------------------------------

#: F-41-070 reference example for invariant sharpening (FK-41 §41.6.2).
#: This example MUST remain as a durable fixture and is checked by a concept gate.
#:
#: Input (vague candidate): "Agent skips E2E tests during implementation"
#: Output (sharpened invariant): "E2E evidence MUST include test-runner exit-code and
#:     timestamp; story closure without this evidence is rejected by the integrity gate."
F41_070_REFERENCE_EXAMPLE: dict[str, str] = {
    "input_candidate": (
        "Agent skips E2E tests during implementation"
    ),
    "sharpened_invariant": (
        "E2E evidence MUST include test-runner exit-code and timestamp; "
        "story closure without this evidence is rejected by the integrity gate."
    ),
    "category": "test_omission",
    "source": "FK-41 §41.6.2 F-41-070 reference example (AG3-078 durable fixture)",
}


# ---------------------------------------------------------------------------
# LlmEvaluator boundary (step 1 / step 3 mock seam)
# ---------------------------------------------------------------------------


@runtime_checkable
class InvariantSharpenerPort(Protocol):
    """Narrow LLM boundary for invariant sharpening (FK-41 §41.6.2, step 1).

    The only mockable boundary in CheckFactory tests (MOCKS only at LLM boundary).
    Real impl delegates to verify-system.LlmEvaluator via prompt-runtime.materialize_prompt.
    """

    def sharpen_invariant(self, candidate_invariant: str, category: str) -> str:
        """Return a sharpened, deterministic invariant statement for the given candidate.

        Args:
            candidate_invariant: Raw invariant candidate text.
            category: FailureCategory wire value (e.g. ``"test_omission"``).

        Returns:
            Sharpened invariant string. Must not be empty.
        """
        ...


# ---------------------------------------------------------------------------
# Story creation surface (step 5)
# ---------------------------------------------------------------------------


@runtime_checkable
class StoryCreationPort(Protocol):
    """Transport-agnostic story-creation port (FK-41 §41.6.6, step 5).

    The ``create_check_implementation_story`` surface. Concrete wiring:
    the AK3 story-creation/governance surface (no direct GitHub/CLI coupling).
    """

    def create_check_implementation_story(
        self,
        check_id: str,
        pattern_ref: str,
        invariant: str,
        check_type: str,
    ) -> str:
        """Create an implementation story for the given check proposal.

        Args:
            check_id: The check proposal identity (CHK-NNNN).
            pattern_ref: The parent pattern identity (FP-NNNN).
            invariant: The sharpened invariant statement.
            check_type: The check-type wire value.

        Returns:
            The created story ID.
        """
        ...


# ---------------------------------------------------------------------------
# Check-ID counter (project-scoped, sequential)
# ---------------------------------------------------------------------------


def _next_check_id(repo: FcCheckProposalRepository) -> str:
    """Allocate the next CHK-NNNN ID against the GLOBAL keyspace (gap-tolerant).

    ``check_id`` is a GLOBAL identifier: ``fc_check_proposals`` is keyed by
    ``check_id`` alone (PK ``(check_id)``) in both the SQLite and the Postgres
    store, and the upsert conflicts only on ``check_id``. The check lifecycle is
    story/project-INDEPENDENT (FK-41 §41.3.3), so allocation MUST span ALL
    proposals — a per-project ``MAX+1`` would let a second project re-allocate
    ``CHK-0001`` and silently overwrite the first project's globally-keyed row.

    Uses a single ``max_check_seq`` query (global ``MAX(suffix)``) — no
    fixed-range scanning. Gaps in the sequence are tolerated; next id = global
    max numeric suffix + 1.

    Args:
        repo: Check proposal repository.

    Returns:
        Next available CHK-NNNN string (zero-padded to 4 digits minimum).
    """
    return f"CHK-{repo.max_check_seq() + 1:04d}"


class CheckFactory:
    """CheckFactory sub of the failure-corpus BC (FK-41 §41.6, AG3-078).

    Args:
        pattern_repo: Repository adapter for ``fc_patterns``.
        check_repo: Repository adapter for ``fc_check_proposals``.
        project_key: Project key (mandatory; all FC reads/writes are project-bound).
        invariant_sharpener: LLM boundary for step 1 (injectable mock in tests).
        story_creation: Transport-agnostic story-creation surface for step 5.
    """

    def __init__(
        self,
        pattern_repo: FcPatternRepository,
        check_repo: FcCheckProposalRepository,
        project_key: str,
        invariant_sharpener: InvariantSharpenerPort | None = None,
        story_creation: StoryCreationPort | None = None,
    ) -> None:
        self._pattern_repo = pattern_repo
        self._check_repo = check_repo
        self._project_key = project_key
        self._sharpener = invariant_sharpener
        self._story_creation = story_creation

    def derive_check(self, pattern_id: PatternId) -> CheckProposalRecord:
        """Derive a check proposal from an ACCEPTED pattern (FK-41 §41.6, steps 1-3).

        Step 1: LLM invariant sharpening.
        Step 2: Deterministic CheckType from category.
        Step 3: Create fc_check_proposals DRAFT.

        Args:
            pattern_id: Pattern identity (FP-NNNN); MUST have status ACCEPTED.

        Returns:
            The created ``CheckProposalRecord`` (status DRAFT).

        Raises:
            FailureCorpusError: If pattern not found or not ACCEPTED (FAIL-CLOSED).
            RuntimeError: If invariant_sharpener is not wired.
        """
        # Load and validate pattern
        pattern = self._pattern_repo.load(str(pattern_id))
        if pattern is None:
            raise FailureCorpusError(
                f"derive_check: pattern {pattern_id!r} not found "
                "(FAIL-CLOSED: no check from unknown pattern)"
            )
        if pattern.status is not PatternStatus.ACCEPTED:
            raise FailureCorpusError(
                f"derive_check: pattern {pattern_id!r} has status "
                f"{pattern.status!r}, expected 'accepted' "
                "(FAIL-CLOSED: check derivation only from ACCEPTED patterns)"
            )

        # Step 1: LLM invariant sharpening
        if self._sharpener is None:
            raise RuntimeError(
                "derive_check step 1 requires invariant_sharpener to be wired "
                "(FAIL-CLOSED: InvariantSharpenerPort is None)"
            )
        sharpened = self._sharpener.sharpen_invariant(
            pattern.invariant,
            pattern.category.value,
        )

        # Step 2: Deterministic check-type mapping
        check_type = CATEGORY_TO_CHECK_TYPE[pattern.category]
        fp_risk = CHECK_TYPE_FALSE_POSITIVE_RISK[check_type]

        # Step 3: Create DRAFT proposal
        check_id = _next_check_id(self._check_repo)
        now = datetime.now(UTC)
        proposal = CheckProposalRecord(
            check_id=check_id,
            project_key=self._project_key,
            status=CheckStatus.DRAFT,
            pattern_ref=str(pattern_id),
            invariant=sharpened,
            check_type=check_type,
            pipeline_stage="structural",
            pipeline_layer=1,
            owner="failure-corpus",
            false_positive_risk=fp_risk,
            positive_fixtures=[],
            negative_fixtures=[],
            created_at=now,
        )
        self._check_repo.save(proposal)
        return proposal

    def approve_check(
        self,
        check_id: CheckId,
        decision: CheckApprovalDecision,
        *,
        rejected_reason: str | None = None,
    ) -> CheckId:
        """Human approval of a check proposal (FK-41 §41.6.5, step 4, AG3-078).

        Three-valued decision:
        - APPROVED: step 5 create_check_implementation_story + set ACTIVE.
        - REJECTED: set REJECTED, no story.
        - REVISE: old proposal -> REJECTED (superseded_by_revision),
          new DRAFT created (new check_id, same pattern_ref). No story.

        Args:
            check_id: Check identity (CHK-NNNN).
            decision: Human decision (APPROVED / REJECTED / REVISE).
            rejected_reason: Optional rejection reason text.

        Returns:
            The resulting check_id (new CHK-NNNN for REVISE, same for others).

        Raises:
            FailureCorpusError: If check_id not found, or its status is not
                DRAFT (FAIL-CLOSED: approval only acts on a DRAFT proposal).
            RuntimeError: If story_creation is not wired on the APPROVED path.
        """
        proposal = self._check_repo.load(str(check_id))
        if proposal is None:
            raise FailureCorpusError(
                f"approve_check: check {check_id!r} not found (FAIL-CLOSED)"
            )
        # FAIL-CLOSED: human approval (FK-41 §41.6.5, step 4) acts ONLY on a
        # DRAFT proposal. Re-approving an already-ACTIVE/REJECTED/RETIRED/APPROVED
        # proposal would create a second implementation story and overwrite the
        # persisted lifecycle state — both forbidden (forward-only transitions,
        # FK-41 §41.3.3). Reject anything that is not DRAFT.
        if proposal.status is not CheckStatus.DRAFT:
            raise FailureCorpusError(
                f"approve_check: check {check_id!r} has status "
                f"{proposal.status.value!r}, expected {CheckStatus.DRAFT.value!r} "
                "(FAIL-CLOSED: approval only acts on a DRAFT proposal)"
            )

        now = datetime.now(UTC)

        if decision is CheckApprovalDecision.APPROVED:
            # Step 5: create implementation story (transport-agnostic, FK-41 §41.6.6).
            # FAIL-CLOSED: story_creation MUST be wired for APPROVED — never silently skip
            # (ERROR 3 fix, AG3-078: an APPROVED check must create the story BEFORE ACTIVE).
            if self._story_creation is None:
                raise RuntimeError(
                    "approve_check APPROVED requires story_creation to be wired "
                    "(FAIL-CLOSED: StoryCreationPort is None, FK-41 §41.6.6). "
                    "Wire a StoryCreationPort in the composition root."
                )
            self._story_creation.create_check_implementation_story(
                check_id=str(check_id),
                pattern_ref=proposal.pattern_ref,
                invariant=proposal.invariant,
                check_type=proposal.check_type.value,
            )
            # Set ACTIVE (forward transition from DRAFT -> APPROVED -> ACTIVE
            # compressed here; approved_by must be 'human')
            updated = CheckProposalRecord(
                **{
                    **proposal.model_dump(),
                    "status": CheckStatus.ACTIVE,
                    "approved_at": now,
                    "approved_by": "human",
                    "rejected_reason": None,
                }
            )
            self._check_repo.save(updated)
            return CheckId(str(check_id))

        elif decision is CheckApprovalDecision.REJECTED:
            updated = CheckProposalRecord(
                **{
                    **proposal.model_dump(),
                    "status": CheckStatus.REJECTED,
                    "rejected_reason": rejected_reason or "rejected",
                }
            )
            self._check_repo.save(updated)
            return CheckId(str(check_id))

        else:  # REVISE
            # Old proposal -> REJECTED with reason "superseded_by_revision"
            superseded = CheckProposalRecord(
                **{
                    **proposal.model_dump(),
                    "status": CheckStatus.REJECTED,
                    "rejected_reason": "superseded_by_revision",
                }
            )
            self._check_repo.save(superseded)

            # New DRAFT revision (new check_id, same pattern_ref)
            new_check_id = _next_check_id(self._check_repo)
            revision = CheckProposalRecord(
                check_id=new_check_id,
                project_key=self._project_key,
                status=CheckStatus.DRAFT,
                pattern_ref=proposal.pattern_ref,
                invariant=proposal.invariant,
                check_type=proposal.check_type,
                pipeline_stage=proposal.pipeline_stage,
                pipeline_layer=proposal.pipeline_layer,
                owner=proposal.owner,
                false_positive_risk=proposal.false_positive_risk,
                positive_fixtures=list(proposal.positive_fixtures),
                negative_fixtures=list(proposal.negative_fixtures),
                created_at=now,
            )
            self._check_repo.save(revision)
            return CheckId(new_check_id)


__all__ = [
    "CheckFactory",
    "F41_070_REFERENCE_EXAMPLE",
    "InvariantSharpenerPort",
    "StoryCreationPort",
]
