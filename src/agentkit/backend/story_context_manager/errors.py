"""Domain errors for story_context_manager."""

from __future__ import annotations

from agentkit.backend.exceptions import StoryError


class StoryProjectNotFoundError(StoryError):
    """Raised when a story is created for an unknown project."""


class StoryProjectArchivedError(StoryError):
    """Raised when a story is created for an archived project."""


class StoryIdentityConflictError(StoryError):
    """Raised when story identity uniqueness is violated."""


class StoryValidationError(StoryError):
    """Raised when story field values fail validation.

    ``error_code`` maps to ``validation_failed`` (HTTP 400).
    """


class StoryNotFoundError(StoryError):
    """Raised when the requested story does not exist.

    ``error_code`` maps to ``story_not_found`` (HTTP 404).
    """


class InvalidStatusTransitionError(StoryError):
    """Raised when a status transition is not permitted.

    ``error_code`` maps to ``invalid_transition`` (HTTP 422).
    """


class IdempotencyMismatchError(StoryError):
    """Raised when op_id is reused with a different body hash.

    ``error_code`` maps to ``idempotency_mismatch`` (HTTP 409).
    """


class OperationInFlightError(StoryError):
    """Raised when an op_id is claimed by a concurrent caller mid-mutation.

    FK-91 §91.1a Rule 5 in-flight protection (AG3-140): the unified idempotency
    guard writes a ``claimed`` placeholder before the mutation and only replaces
    it with the stored result on ``finalize``. A parallel request carrying the
    same ``op_id`` therefore sees a live claim and is rejected fail-closed instead
    of re-executing the mutation. A retry after the winner finalizes reads the
    committed result as a normal replay.

    ``error_code`` maps to ``operation_in_flight`` (HTTP 409).
    """


class ForbiddenFieldError(StoryError):
    """Raised when a forbidden field appears in a mutation.

    ``error_code`` maps to ``forbidden_field`` (HTTP 422).
    """


class ForbiddenError(StoryError):
    """Raised when a project is archived or the auth scope is insufficient.

    ``error_code`` maps to ``forbidden`` (HTTP 403).
    """


class StoryConcurrencyConflictError(StoryError):
    """Raised on optimistic-locking conflict.

    ``error_code`` maps to ``conflict`` (HTTP 409).
    """


class ReconciliationEvidenceMissingError(StoryError):
    """Raised when an agent-facing create omits the VectorDB reconciliation proof.

    The agent-facing ``POST /v1/stories`` path must carry the typed
    reconciliation evidence (FK-21 §21.4 / §21.12) — proof that the fail-closed
    Weaviate reconciliation ran and that repo-affinity fed
    ``participating_repos``. Without that evidence (and without a direct-create
    grant for Zone-2/admin callers, FK-21 §21.13.2) the create is blocked
    fail-closed; a story can never be persisted while silently bypassing the
    reconciliation.

    ``error_code`` maps to ``reconciliation_evidence_missing`` (HTTP 422).
    """
