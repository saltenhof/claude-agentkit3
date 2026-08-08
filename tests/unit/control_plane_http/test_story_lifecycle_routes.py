"""Negative paths of the three story-lifecycle ``/v1`` routes (AG3-240).

Split, reset and exit are the operations the operator triggers on the developer
machine and the core executes. Since AG3-240 the edge holds no second copy of
their rules, which makes these routes the SINGLE validator -- so the rejections
have to be proven here, not assumed.

Three axes per route, per AC 6:

* **missing or insufficient authorisation** -- anything that is not an
  authenticated strategist session is ``403``;
* **unknown identity** -- a plan that does not belong to the addressed story, an
  exit whose ``run_id`` is not the actively bound run;
* **fail-closed when the core cannot execute** -- a composition that cannot
  reach its dependencies answers ``503`` and never a partial success.

The routes expose ``*_service_builder`` seams; the tests drive the real route
objects through them (no HTTP client and no database needed to prove the
rejections, which all happen before any service call).
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest

from agentkit.backend.control_plane_http.story_admin_routes import StoryAdminRoutes
from agentkit.backend.control_plane_http.story_split_routes import StorySplitRoutes

if TYPE_CHECKING:
    from agentkit.backend.control_plane_http.responses import HttpResponse

_CORRELATION = "corr-ag3-240"


class _Auth:
    """Minimal stand-in for the middleware's ``AuthResult``.

    The route consults exactly two attributes. Building a real ``AuthResult``
    would drag the credential store and its file layout into a rejection test
    that never reaches authentication code.
    """

    def __init__(self, *, is_human_bff_session: bool, session_id: str | None) -> None:
        self.is_human_bff_session = is_human_bff_session
        self.session_id = session_id


def _strategist() -> Any:
    return _Auth(is_human_bff_session=True, session_id="sess-1")


def _plan_text(*, project_key: str = "ak3", story_id: str = "AK3-001") -> str:
    return json.dumps(
        {
            "project_key": project_key,
            "source_story_id": story_id,
            "reason": "scope_explosion",
            "successors": [
                {"story_id": "AK3-107", "title": "Slice A", "scope_slice": "A"},
            ],
            "dependency_rebinding": [],
        }
    )


def _body(response: HttpResponse) -> dict[str, Any]:
    payload = json.loads(response.body)
    assert isinstance(payload, dict)
    return payload


def _never_built(**_kwargs: object) -> object:
    raise AssertionError("a rejected request must never build a service")


class _NeverInvokedExitService:
    """A built-but-unused exit service.

    The route resolves the reason code while assembling the request, i.e. AFTER
    the service exists. Proving that the invalid reason never reaches the saga
    therefore needs a service that exists and refuses to run.
    """

    def exit_story(self, _request: object) -> object:
        raise AssertionError("an invalid reason must never reach the exit saga")


class _UnreachableCore:
    """A composition whose dependencies are not reachable."""

    def __call__(self, **_kwargs: object) -> object:
        raise RuntimeError("state backend is not reachable")


# --------------------------------------------------------------------------
# split
# --------------------------------------------------------------------------


class TestSplitRouteRejections:
    """``POST /v1/projects/{key}/stories/{id}/split``."""

    @pytest.mark.parametrize(
        "auth",
        [None, _Auth(is_human_bff_session=False, session_id="sess-1")],
        ids=["unauthenticated", "non_strategist_session"],
    )
    def test_without_a_strategist_session_the_split_is_forbidden(self, auth: Any) -> None:
        response = StorySplitRoutes(service_builder=_never_built).handle_post(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "plan_text": _plan_text(),
                "reason": "scope explosion",
                "run_id": "run-1",
                "project_root": "/srv/p",
            },
            correlation_id=_CORRELATION,
            auth_result=auth,
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _body(response)["error_code"] == "story_split_forbidden"

    def test_a_defective_plan_document_is_rejected_by_the_single_validator(self) -> None:
        """The edge forwards the document verbatim; this is where it is judged."""
        response = StorySplitRoutes(service_builder=_never_built).handle_post(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "plan_text": "not json {",
                "reason": "scope explosion",
                "run_id": "run-1",
                "project_root": "/srv/p",
            },
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _body(response)["error_code"] == "invalid_story_split_request"

    def test_a_plan_for_a_different_story_is_rejected(self) -> None:
        """Unknown identity: the plan does not address the routed story."""
        response = StorySplitRoutes(service_builder=_never_built).handle_post(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "plan_text": _plan_text(story_id="AK3-999"),
                "reason": "scope explosion",
                "run_id": "run-1",
                "project_root": "/srv/p",
            },
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _body(response)["error_code"] == "story_split_scope_mismatch"

    def test_an_unreachable_core_fails_closed(self) -> None:
        response = StorySplitRoutes(service_builder=_UnreachableCore()).handle_post(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "plan_text": _plan_text(),
                "reason": "scope explosion",
                "run_id": "run-1",
                "project_root": "/srv/p",
            },
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert _body(response)["error_code"] == "story_split_unavailable"


# --------------------------------------------------------------------------
# reset
# --------------------------------------------------------------------------


class _NoOwnershipRepository:
    """Writer state in which no run owns the addressed story.

    `handle_reset` never consults the repository -- reset is not bound to an
    active run. It is injected only so constructing the routes does not reach
    for a live state backend.
    """

    def load_active_ownership(self, _project_key: str, _story_id: str) -> None:
        return None


class _UnknownStoryResetService:
    """A reset service that does not know the addressed story."""

    def request_reset(self, _request: object) -> object:
        from agentkit.backend.story_reset.service import StoryResetError

        raise StoryResetError("unknown story AK3-does-not-exist")

    def execute_reset(self, _reset_id: str) -> object:
        raise AssertionError("a rejected reset must never execute")


class TestResetRouteRejections:
    """``POST /v1/projects/{key}/stories/{id}/reset``."""

    @pytest.mark.parametrize(
        "auth",
        [
            None,
            _Auth(is_human_bff_session=False, session_id="sess-1"),
            _Auth(is_human_bff_session=True, session_id="   "),
        ],
        ids=["unauthenticated", "non_strategist_session", "blank_session_id"],
    )
    def test_without_a_strategist_session_the_reset_is_forbidden(self, auth: Any) -> None:
        routes = StoryAdminRoutes(
            reset_service_builder=_never_built,
            repository=_NoOwnershipRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_reset(
            project_key="ak3",
            story_id="AK3-001",
            payload={"op_id": "op-1", "reason": "irreparable", "project_root": "/srv/p"},
            correlation_id=_CORRELATION,
            auth_result=auth,
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _body(response)["error_code"] == "story_admin_forbidden"

    def test_a_malformed_reset_payload_is_rejected(self) -> None:
        routes = StoryAdminRoutes(
            reset_service_builder=_never_built,
            repository=_NoOwnershipRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_reset(
            project_key="ak3",
            story_id="AK3-001",
            payload={"reason": "irreparable"},
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _body(response)["error_code"] == "invalid_story_reset_request"

    def test_an_unknown_story_identity_is_rejected(self) -> None:
        """Unknown identity: the addressed story does not exist for the writer.

        Reset is not bound to a run, so the identity it can fail on is the story
        itself; the rejection surfaces from the service as a 409, not from an
        ownership lookup.
        """
        routes = StoryAdminRoutes(
            reset_service_builder=lambda **_kwargs: _UnknownStoryResetService(),
            repository=_NoOwnershipRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_reset(
            project_key="ak3",
            story_id="AK3-does-not-exist",
            payload={"op_id": "op-1", "reason": "irreparable", "project_root": "/srv/p"},
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.CONFLICT
        assert _body(response)["error_code"] == "story_reset_rejected"

    def test_an_unreachable_core_fails_closed(self) -> None:
        routes = StoryAdminRoutes(
            reset_service_builder=_UnreachableCore(),
            repository=_NoOwnershipRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_reset(
            project_key="ak3",
            story_id="AK3-001",
            payload={"op_id": "op-1", "reason": "irreparable", "project_root": "/srv/p"},
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert _body(response)["error_code"] == "story_reset_unavailable"


# --------------------------------------------------------------------------
# exit
# --------------------------------------------------------------------------


class _BoundOwnership:
    """Writer state whose active run is ``run-1``."""

    run_id = "run-1"
    owner_session_id = "sess-owner"


class _BoundRepository:
    def load_active_ownership(self, _project_key: str, _story_id: str) -> _BoundOwnership:
        return _BoundOwnership()


class TestExitRouteRejections:
    """``POST /v1/projects/{key}/stories/{id}/exit``."""

    @pytest.mark.parametrize(
        "auth",
        [
            None,
            _Auth(is_human_bff_session=False, session_id="sess-1"),
            _Auth(is_human_bff_session=True, session_id=None),
        ],
        ids=["unauthenticated", "non_strategist_session", "session_without_id"],
    )
    def test_without_a_strategist_session_the_exit_is_forbidden(self, auth: Any) -> None:
        routes = StoryAdminRoutes(
            exit_service_builder=_never_built,
            repository=_BoundRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_exit(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "op_id": "op-1",
                "run_id": "run-1",
                "reason": "solution_viability_requires_human_design",
            },
            correlation_id=_CORRELATION,
            auth_result=auth,
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _body(response)["error_code"] == "story_admin_forbidden"

    def test_an_unknown_run_identity_is_rejected(self) -> None:
        """Unknown identity: the requested run is not the actively bound one."""
        routes = StoryAdminRoutes(
            exit_service_builder=_never_built,
            repository=_BoundRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_exit(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "op_id": "op-1",
                "run_id": "run-does-not-exist",
                "reason": "solution_viability_requires_human_design",
            },
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.CONFLICT
        assert _body(response)["error_code"] == "story_exit_rejected"

    def test_an_unknown_reason_code_is_rejected_here_and_only_here(self) -> None:
        """AG3-240: the FK-58 reason vocabulary has exactly one adjudicator."""
        routes = StoryAdminRoutes(
            exit_service_builder=lambda **_kwargs: _NeverInvokedExitService(),
            repository=_BoundRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_exit(
            project_key="ak3",
            story_id="AK3-001",
            payload={"op_id": "op-1", "run_id": "run-1", "reason": "no_such_reason_code"},
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _body(response)["error_code"] == "invalid_story_exit_reason"

    def test_an_unreachable_core_fails_closed(self) -> None:
        routes = StoryAdminRoutes(
            exit_service_builder=_UnreachableCore(),
            repository=_BoundRepository(),  # type: ignore[arg-type]
        )

        response = routes.handle_exit(
            project_key="ak3",
            story_id="AK3-001",
            payload={
                "op_id": "op-1",
                "run_id": "run-1",
                "reason": "solution_viability_requires_human_design",
            },
            correlation_id=_CORRELATION,
            auth_result=_strategist(),
        )

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert _body(response)["error_code"] == "story_exit_unavailable"
