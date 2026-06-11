"""Story routes for the control-plane dispatcher (story_context_manager BC).

Handles all FK-91 §91.1a story endpoints:
  GET  /v1/stories                    -> list_stories
  POST /v1/stories                    -> create_story
  GET  /v1/stories/{id}               -> get_story (with spec)
  PATCH /v1/stories/{id}              -> update_story_fields
  POST /v1/stories/{id}/approve       -> approve_story
  POST /v1/stories/{id}/reject        -> reject_story
  POST /v1/stories/{id}/cancel        -> cancel_story
  GET  /v1/stories/{id}/fields        -> get_story_fields
  PUT  /v1/stories/{id}/fields/{key}  -> set_story_field
  GET  /v1/projects/{key}/stories/search?q=... -> search_stories

Error contract (FK-91 §91.1a Rule 7+8):
  Every response carries X-Correlation-Id header.
  Error body: {error_code, error, correlation_id, [detail]}.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from agentkit.story_context_manager.errors import (
    ForbiddenError,
    ForbiddenFieldError,
    IdempotencyMismatchError,
    InvalidStatusTransitionError,
    ReconciliationEvidenceMissingError,
    StoryNotFoundError,
    StoryProjectNotFoundError,
    StoryValidationError,
)
from agentkit.story_context_manager.story_model import CreateStoryInput
from agentkit.story_context_manager.wire_adapter import (
    story_spec_to_wire,
    story_to_wire_summary,
)

if TYPE_CHECKING:
    from agentkit.story_context_manager.service import StoryService

_CORRELATION_HEADER = "X-Correlation-Id"

# Path patterns
_STORY_COLLECTION = re.compile(r"^/v1/stories$")
_STORY_DETAIL = re.compile(r"^/v1/stories/(?P<story_id>[^/]+)$")
_STORY_APPROVE = re.compile(r"^/v1/stories/(?P<story_id>[^/]+)/approve$")
_STORY_REJECT = re.compile(r"^/v1/stories/(?P<story_id>[^/]+)/reject$")
_STORY_CANCEL = re.compile(r"^/v1/stories/(?P<story_id>[^/]+)/cancel$")
_STORY_FIELDS = re.compile(r"^/v1/stories/(?P<story_id>[^/]+)/fields$")
_STORY_FIELD_KEY = re.compile(
    r"^/v1/stories/(?P<story_id>[^/]+)/fields/(?P<field_key>[^/]+)$"
)
_STORY_SEARCH = re.compile(
    r"^/v1/projects/(?P<project_key>[^/]+)/stories/search$"
)


@dataclass(frozen=True)
class StoryRouteResponse:
    """Serializable response produced by the story-context HTTP adapter."""

    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class StoryContextRoutes:
    """Route handler for all story-context service endpoints.

    Dispatches HTTP requests to the authoritative ``StoryService``
    (story_context_manager BC). Does NOT use the old ``story.service.StoryService``
    (read-model adapter) — that path is superseded by this service.

    Args:
        story_service: Injected StoryService. If None, constructed with defaults.
    """

    def __init__(
        self,
        *,
        story_service: StoryService | None = None,
    ) -> None:
        if story_service is None:
            import agentkit.story_context_manager.service as _svc_mod

            story_service = _svc_mod.StoryService()
        self._svc: StoryService = story_service

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------

    def handle_get(
        self,
        route_path: str,
        correlation_id: str,
        query: dict[str, list[str]] | None = None,
    ) -> StoryRouteResponse | None:
        """Handle GET story routes or return None."""
        query = query or {}

        # GET /v1/stories?project_key=...
        if _STORY_COLLECTION.match(route_path):
            project_key = _single_query(query, "project_key")
            if project_key is None:
                return _error_response(
                    HTTPStatus.BAD_REQUEST,
                    error_code="missing_project_key",
                    message="Missing required query parameter: project_key",
                    correlation_id=correlation_id,
                )
            stories = self._svc.list_stories(project_key)
            return _json_response(
                HTTPStatus.OK,
                {
                    "project_key": project_key,
                    "stories": [story_to_wire_summary(s) for s in stories],
                },
                correlation_id=correlation_id,
            )

        # GET /v1/stories/{id}
        detail_match = _STORY_DETAIL.match(route_path)
        if detail_match is not None:
            story_id = detail_match.group("story_id")
            result = self._svc.get_story_detail(story_id)
            if result is None:
                return _error_response(
                    HTTPStatus.NOT_FOUND,
                    error_code="story_not_found",
                    message=f"Story {story_id!r} not found",
                    correlation_id=correlation_id,
                )
            story, spec = result
            wire: dict[str, object] = {
                "summary": story_to_wire_summary(story),
                "spec": story_spec_to_wire(spec) if spec is not None else None,
                "evidence": None,
                "telemetry": None,
                "gates": [],
                "phases": [],
                "events": [],
            }
            return _json_response(HTTPStatus.OK, wire, correlation_id=correlation_id)

        # GET /v1/stories/{id}/fields
        fields_match = _STORY_FIELDS.match(route_path)
        if fields_match is not None:
            story_id = fields_match.group("story_id")
            try:
                fields = self._svc.get_story_fields(story_id)
            except StoryNotFoundError as exc:
                return _service_error_response(exc, correlation_id)
            return _json_response(
                HTTPStatus.OK, {"fields": fields}, correlation_id=correlation_id
            )

        # GET /v1/projects/{key}/stories/search?q=...
        search_match = _STORY_SEARCH.match(route_path)
        if search_match is not None:
            project_key = search_match.group("project_key")
            q = _single_query(query, "q")
            if q is None:
                return _error_response(
                    HTTPStatus.BAD_REQUEST,
                    error_code="missing_query",
                    message="Missing required query parameter: q",
                    correlation_id=correlation_id,
                )
            stories = self._svc.search_stories(project_key, q)
            return _json_response(
                HTTPStatus.OK,
                {
                    "project_key": project_key,
                    "stories": [story_to_wire_summary(s) for s in stories],
                },
                correlation_id=correlation_id,
            )

        return None

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------

    def handle_post(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        """Handle POST story routes or return None."""

        # POST /v1/stories
        if _STORY_COLLECTION.match(route_path):
            return self._handle_create_story(payload, correlation_id)

        # POST /v1/stories/{id}/approve
        approve_match = _STORY_APPROVE.match(route_path)
        if approve_match is not None:
            return self._handle_approve(
                approve_match.group("story_id"), payload, correlation_id
            )

        # POST /v1/stories/{id}/reject
        reject_match = _STORY_REJECT.match(route_path)
        if reject_match is not None:
            return self._handle_reject(
                reject_match.group("story_id"), payload, correlation_id
            )

        # POST /v1/stories/{id}/cancel
        cancel_match = _STORY_CANCEL.match(route_path)
        if cancel_match is not None:
            return self._handle_cancel(
                cancel_match.group("story_id"), payload, correlation_id
            )

        return None

    # ------------------------------------------------------------------
    # PATCH
    # ------------------------------------------------------------------

    def handle_patch(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        """Handle PATCH story routes or return None."""

        detail_match = _STORY_DETAIL.match(route_path)
        if detail_match is None:
            return None

        story_id = detail_match.group("story_id")
        return self._handle_update_fields(story_id, payload, correlation_id)

    # ------------------------------------------------------------------
    # PUT
    # ------------------------------------------------------------------

    def handle_put(
        self,
        route_path: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse | None:
        """Handle PUT story field routes or return None."""

        field_match = _STORY_FIELD_KEY.match(route_path)
        if field_match is None:
            return None

        story_id = field_match.group("story_id")
        field_key = field_match.group("field_key")
        return self._handle_set_field(story_id, field_key, payload, correlation_id)

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    def _handle_create_story(
        self, payload: object, correlation_id: str
    ) -> StoryRouteResponse:
        body = _require_dict(payload, correlation_id)
        if isinstance(body, StoryRouteResponse):
            return body

        op_id = _require_str(body, "op_id", correlation_id)
        if isinstance(op_id, StoryRouteResponse):
            return op_id

        # FK-21 §21.4 / §21.12 / §21.13 (AG3-068 FIX-1): the agent-facing create
        # path is NON-BYPASSABLE. It MUST carry the typed reconciliation evidence
        # (proof the fail-closed Weaviate reconciliation ran + repo-affinity fed
        # participating_repos). Without it, the create is blocked fail-closed BEFORE
        # any persistence — a story can never be created here while silently
        # skipping the Weaviate check / affinity feed. There is no in-body escape
        # hatch: the Zone-2/admin exemption (FK-21 §21.13.2) calls the StoryService
        # in-process, not this route.
        enforced_or_error = _enforce_reconciliation(body, correlation_id)
        if isinstance(enforced_or_error, StoryRouteResponse):
            return enforced_or_error

        request_or_error = _parse_create_story_input(
            enforced_or_error, correlation_id
        )
        if isinstance(request_or_error, StoryRouteResponse):
            return request_or_error

        try:
            story = self._svc.create_story(
                request_or_error,
                op_id=op_id,
                correlation_id=correlation_id,
            )
        except (StoryValidationError, StoryProjectNotFoundError) as exc:
            return _service_error_response(exc, correlation_id)
        except ForbiddenError as exc:
            return _service_error_response(exc, correlation_id)
        except IdempotencyMismatchError as exc:
            return _service_error_response(exc, correlation_id)
        except Exception as exc:  # noqa: BLE001 — last-resort 500 wrapper
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="internal_error",
                message=str(exc),
                correlation_id=correlation_id,
            )

        return _json_response(
            HTTPStatus.CREATED,
            story_to_wire_summary(story),
            correlation_id=correlation_id,
        )

    def _handle_update_fields(
        self, story_id: str, payload: object, correlation_id: str
    ) -> StoryRouteResponse:
        body = _require_dict(payload, correlation_id)
        if isinstance(body, StoryRouteResponse):
            return body

        op_id = _require_str(body, "op_id", correlation_id)
        if isinstance(op_id, StoryRouteResponse):
            return op_id

        # Pass everything except op_id as updates
        updates = {k: v for k, v in body.items() if k != "op_id"}

        try:
            story = self._svc.update_story_fields(
                story_id,
                updates=updates,
                op_id=op_id,
                correlation_id=correlation_id,
            )
        except ForbiddenFieldError as exc:
            return _service_error_response(exc, correlation_id)
        except StoryNotFoundError as exc:
            return _service_error_response(exc, correlation_id)
        except StoryValidationError as exc:
            return _service_error_response(exc, correlation_id)
        except ForbiddenError as exc:
            return _service_error_response(exc, correlation_id)
        except IdempotencyMismatchError as exc:
            return _service_error_response(exc, correlation_id)
        except Exception as exc:
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="internal_error",
                message=str(exc),
                correlation_id=correlation_id,
            )

        return _json_response(
            HTTPStatus.OK, story_to_wire_summary(story), correlation_id=correlation_id
        )

    def _handle_approve(
        self, story_id: str, payload: object, correlation_id: str
    ) -> StoryRouteResponse:
        body = _require_dict(payload, correlation_id)
        if isinstance(body, StoryRouteResponse):
            return body
        op_id = _require_str(body, "op_id", correlation_id)
        if isinstance(op_id, StoryRouteResponse):
            return op_id

        try:
            story = self._svc.approve_story(
                story_id, op_id=op_id, correlation_id=correlation_id
            )
        except (StoryNotFoundError, InvalidStatusTransitionError, ForbiddenError,
                IdempotencyMismatchError) as exc:
            return _service_error_response(exc, correlation_id)
        except Exception as exc:
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="internal_error",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK, story_to_wire_summary(story), correlation_id=correlation_id
        )

    def _handle_reject(
        self, story_id: str, payload: object, correlation_id: str
    ) -> StoryRouteResponse:
        body = _require_dict(payload, correlation_id)
        if isinstance(body, StoryRouteResponse):
            return body
        op_id = _require_str(body, "op_id", correlation_id)
        if isinstance(op_id, StoryRouteResponse):
            return op_id

        try:
            story = self._svc.reject_story(
                story_id, op_id=op_id, correlation_id=correlation_id
            )
        except (StoryNotFoundError, InvalidStatusTransitionError, ForbiddenError,
                IdempotencyMismatchError) as exc:
            return _service_error_response(exc, correlation_id)
        except Exception as exc:
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="internal_error",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK, story_to_wire_summary(story), correlation_id=correlation_id
        )

    def _handle_cancel(
        self, story_id: str, payload: object, correlation_id: str
    ) -> StoryRouteResponse:
        body = _require_dict(payload, correlation_id)
        if isinstance(body, StoryRouteResponse):
            return body
        op_id = _require_str(body, "op_id", correlation_id)
        if isinstance(op_id, StoryRouteResponse):
            return op_id
        reason = body.get("reason")

        try:
            story = self._svc.cancel_story(
                story_id,
                reason=str(reason) if reason is not None else None,
                op_id=op_id,
                correlation_id=correlation_id,
            )
        except (StoryNotFoundError, InvalidStatusTransitionError, ForbiddenError,
                IdempotencyMismatchError) as exc:
            return _service_error_response(exc, correlation_id)
        except Exception as exc:
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="internal_error",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK, story_to_wire_summary(story), correlation_id=correlation_id
        )

    def _handle_set_field(
        self,
        story_id: str,
        field_key: str,
        payload: object,
        correlation_id: str,
    ) -> StoryRouteResponse:
        body = _require_dict(payload, correlation_id)
        if isinstance(body, StoryRouteResponse):
            return body
        op_id = _require_str(body, "op_id", correlation_id)
        if isinstance(op_id, StoryRouteResponse):
            return op_id

        value = body.get("value")

        try:
            story = self._svc.set_story_field(
                story_id,
                field_key,
                value,
                op_id=op_id,
                correlation_id=correlation_id,
            )
        except ForbiddenFieldError as exc:
            return _service_error_response(exc, correlation_id)
        except StoryNotFoundError as exc:
            return _service_error_response(exc, correlation_id)
        except StoryValidationError as exc:
            return _service_error_response(exc, correlation_id)
        except IdempotencyMismatchError as exc:
            return _service_error_response(exc, correlation_id)
        except Exception as exc:
            return _error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code="internal_error",
                message=str(exc),
                correlation_id=correlation_id,
            )
        return _json_response(
            HTTPStatus.OK, story_to_wire_summary(story), correlation_id=correlation_id
        )


# ---------------------------------------------------------------------------
# Error-code mapping
# ---------------------------------------------------------------------------

_ERROR_CODE_MAP: dict[type[Exception], tuple[HTTPStatus, str]] = {
    StoryValidationError: (HTTPStatus.BAD_REQUEST, "validation_failed"),
    StoryNotFoundError: (HTTPStatus.NOT_FOUND, "story_not_found"),
    StoryProjectNotFoundError: (HTTPStatus.BAD_REQUEST, "validation_failed"),
    ForbiddenError: (HTTPStatus.FORBIDDEN, "forbidden"),
    ForbiddenFieldError: (HTTPStatus.UNPROCESSABLE_ENTITY, "forbidden_field"),
    InvalidStatusTransitionError: (HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_transition"),
    IdempotencyMismatchError: (HTTPStatus.CONFLICT, "idempotency_mismatch"),
    ReconciliationEvidenceMissingError: (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "reconciliation_evidence_missing",
    ),
}


def _service_error_response(exc: Exception, correlation_id: str) -> StoryRouteResponse:
    """Map a service exception to the correct HTTP error response."""
    http_status, error_code = _ERROR_CODE_MAP.get(
        type(exc), (HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")
    )
    from agentkit.exceptions import AgentKitError

    detail: object | None = None
    if isinstance(exc, AgentKitError) and exc.detail:
        detail = exc.detail

    return _error_response(
        http_status,
        error_code=error_code,
        message=str(exc),
        correlation_id=correlation_id,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# HTTP response helpers
# ---------------------------------------------------------------------------


def _json_response(
    status: HTTPStatus,
    payload: dict[str, object],
    *,
    correlation_id: str,
) -> StoryRouteResponse:
    return StoryRouteResponse(
        status_code=int(status),
        body=json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
        headers=((_CORRELATION_HEADER, correlation_id),),
    )


def _error_response(
    status: HTTPStatus,
    *,
    error_code: str,
    message: str,
    correlation_id: str,
    detail: object | None = None,
) -> StoryRouteResponse:
    payload: dict[str, object] = {
        "error_code": error_code,
        "error": message,
        "correlation_id": correlation_id,
    }
    if detail is not None:
        payload["detail"] = detail
    return _json_response(status, payload, correlation_id=correlation_id)


def _require_dict(
    payload: object, correlation_id: str
) -> dict[str, object] | StoryRouteResponse:
    if not isinstance(payload, dict):
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="validation_failed",
            message="Request body must be a JSON object",
            correlation_id=correlation_id,
        )
    return cast("dict[str, object]", payload)


# Transport-level keys that are NOT part of ``CreateStoryInput`` content.
# ``reconciliation`` is the AG3-068 (FK-21 §21.4/§21.13) fail-closed precondition
# channel, consumed by ``_enforce_reconciliation`` and stripped before the body
# is validated as story content.
_NON_CONTENT_KEYS: frozenset[str] = frozenset({"op_id", "reconciliation"})


def _enforce_reconciliation(
    body: dict[str, object], correlation_id: str
) -> dict[str, object] | StoryRouteResponse:
    """Fail-closed reconciliation gate for the agent-facing create path.

    The body MUST carry a typed ``reconciliation`` evidence block
    (FK-21 §21.4/§21.12). The grounded ``vectordb_conflict_resolved`` flag and
    the repo-affinity ``participating_repos`` (``repos``) are PROJECTED from the
    evidence into the body, so the persisted story cannot diverge from the
    reconciliation outcome (FIX-THE-MODEL).

    There is deliberately NO in-body bypass on this route. FK-21 §21.13.2 routes
    the Zone-2/admin exemption to a DIFFERENT entry: those callers (Zone-2
    pipeline scripts, Kap. 41; the official admin StorySplit/StoryReset service,
    Kap. 54) invoke the authoritative ``StoryService`` / ``StoryCreationReconciler``
    IN-PROCESS ("may call the AK3 story service directly to create stories"),
    not this agent-facing HTTP boundary. A body-settable grant string would be a
    second, spoofable copy of an authorization decision the ``StoryCreationGuard``
    (FK-31 §31.5 / FK-21 §21.13) already owns at the harness PreToolUse boundary
    via a resolved ``Principal`` — exactly the kind of "second operative truth"
    AK3 forbids (FIX-THE-MODEL). So the HTTP route is non-bypassable: evidence or
    fail-closed, no escape hatch.

    Args:
        body: The raw request body.
        correlation_id: Correlation id for the error response.

    Returns:
        The evidence-projected body to validate as story content, or a
        fail-closed error response when the evidence is absent / inconsistent.
    """
    raw_evidence = body.get("reconciliation")
    if raw_evidence is None:
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="reconciliation_evidence_missing",
            message=(
                "POST /v1/stories requires VectorDB reconciliation evidence "
                "(FK-21 §21.4/§21.12): a Weaviate outage or a missing reconciliation "
                "blocks story creation fail-closed. Provide a 'reconciliation' block. "
                "Zone-2/admin direct creation (FK-21 §21.13.2) does not use this "
                "agent-facing route; it calls the StoryService in-process."
            ),
            correlation_id=correlation_id,
        )
    if not isinstance(raw_evidence, dict):
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="reconciliation_evidence_missing",
            message="'reconciliation' must be a JSON object",
            correlation_id=correlation_id,
        )

    from pydantic import ValidationError

    from agentkit.story_creation.reconciliation_evidence import ReconciliationEvidence

    try:
        evidence = ReconciliationEvidence.model_validate(raw_evidence)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        return _error_response(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="reconciliation_evidence_missing",
            message=(
                f"reconciliation evidence is invalid: "
                f"{location}: {first.get('msg', 'invalid value')}".rstrip(": ")
            ),
            correlation_id=correlation_id,
        )

    # Project the GROUNDED flag + affinity into the body (SSOT): the persisted
    # story follows the reconciliation outcome, not an unchecked caller value.
    projected: dict[str, object] = dict(body)
    projected["vectordb_conflict_resolved"] = evidence.vectordb_conflict_resolved
    if evidence.participating_repos:
        projected["repos"] = list(evidence.participating_repos)
    return projected


def _parse_create_story_input(
    body: dict[str, object], correlation_id: str
) -> CreateStoryInput | StoryRouteResponse:
    """Parse the create-story request body into a typed ``CreateStoryInput``.

    Builds a payload dict (without the transport-level / reconciliation keys)
    and lets Pydantic do the enum coercion, optionality and constraint checks
    in one step.  All Pydantic ``ValidationError``s are mapped to a HTTP 400.
    """
    from pydantic import ValidationError

    payload = {k: v for k, v in body.items() if k not in _NON_CONTENT_KEYS}
    try:
        return CreateStoryInput.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="validation_failed",
            message=f"{location}: {first.get('msg', 'invalid value')}".lstrip(": "),
            correlation_id=correlation_id,
        )


def _require_str(
    body: dict[str, object], field: str, correlation_id: str
) -> str | StoryRouteResponse:
    value = body.get(field)
    if not isinstance(value, str) or not value:
        return _error_response(
            HTTPStatus.BAD_REQUEST,
            error_code="validation_failed",
            message=f"Missing required field: {field!r}",
            correlation_id=correlation_id,
        )
    return value


def _single_query(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None
