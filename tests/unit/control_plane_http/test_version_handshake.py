"""Unit tests for the /v1 version handshake (AG3-121, FK-91 §91.1a Regel 11).

Covers, exercised through the REAL ``ControlPlaneApplication.handle_request``
dispatch (no mock of the middleware under test):

  - AC1: ``GET /v1/compat`` returns the full ``min``/``max``/``recommended``/
    ``blocked`` window for agent-runtime + wire with a correlation id, and
    requires NO handshake header.
  - AC2: fail-closed 426 for runtime-below-min, runtime-in-blocked, unsupported
    wire version, and missing handshake at a mutating endpoint — each with the
    stable error contract + window announce, and the mutation does NOT run.
  - AC3: each individually missing header (client / skill-bundle) -> 426; an
    in-window-but-below-recommended runtime runs (WARNING), not blocked.
  - AC4: WARNING carries a structured ``X-AK3-Compat-Warning`` header; PASS runs
    without it (announce headers still present).
"""

from __future__ import annotations

import json
from http import HTTPStatus

import pytest

from agentkit.backend.control_plane.models import TelemetryEventAccepted
from agentkit.backend.control_plane_http.app import ControlPlaneApplication
from agentkit.backend.control_plane_http.version_handshake import (
    CLIENT_VERSION_HEADER,
    COMPAT_BLOCKED_HEADER,
    COMPAT_RECOMMENDED_HEADER,
    COMPAT_WARNING_HEADER,
    SKILL_BUNDLE_HEADER,
    CompatWindow,
    HandshakeRouteClassifier,
    VersionAxisWindow,
    VersionHandshakeMiddleware,
    default_bundle_window,
    default_compat_window,
)

_TELEMETRY_PATH = "/v1/telemetry/events"


class _RecordingTelemetryService:
    """Telemetry service spy: records ingest calls, returns an accepted result."""

    def __init__(self) -> None:
        self.calls = 0

    def ingest_event(self, request: object) -> TelemetryEventAccepted:  # noqa: ARG002
        self.calls += 1
        return TelemetryEventAccepted(event_id="evt-1")


def _test_window() -> CompatWindow:
    """A window with room for below-min / blocked / WARNING / PASS cases."""
    return CompatWindow(
        agent_runtime=VersionAxisWindow(
            min="1.0.0", max="3.0.0", recommended="2.0.0", blocked=("1.5.0",),
        ),
        wire=VersionAxisWindow(min="1", max="1", recommended="1", blocked=()),
    )


def _build_app(
    telemetry: _RecordingTelemetryService | None = None,
) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(window=_test_window()),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )


def _valid_telemetry_body() -> bytes:
    return json.dumps(
        {
            "project_key": "p",
            "story_id": "s",
            "run_id": "r",
            "event_type": "agent_start",
            "occurred_at": "2026-06-29T10:00:00+00:00",
            "source_component": "c",
        },
    ).encode("utf-8")


def _headers(response_headers: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {key: value for key, value in response_headers}


# ---------------------------------------------------------------------------
# AC1 — GET /v1/compat
# ---------------------------------------------------------------------------


def test_compat_endpoint_returns_full_window_without_handshake() -> None:
    """AC1: /v1/compat is reachable read-only with the full window + correlation."""
    app = _build_app()

    response = app.handle_request(method="GET", path="/v1/compat", body=b"")

    assert response.status_code == int(HTTPStatus.OK)
    headers = _headers(response.headers)
    assert headers["X-Correlation-Id"]
    payload = json.loads(response.body)
    for axis in ("agent_runtime", "wire"):
        assert set(payload[axis]) == {"min", "max", "recommended", "blocked"}
    assert payload["agent_runtime"] == {
        "min": "1.0.0",
        "max": "3.0.0",
        "recommended": "2.0.0",
        "blocked": ["1.5.0"],
    }
    assert payload["wire"]["min"] == "1"


def test_compat_endpoint_available_on_default_app_window() -> None:
    """AC1: the endpoint works on a default app (window = central default)."""
    app = ControlPlaneApplication()

    response = app.handle_request(method="GET", path="/v1/compat", body=b"")

    assert response.status_code == int(HTTPStatus.OK)
    assert json.loads(response.body) == default_compat_window().model_dump(mode="json")


# ---------------------------------------------------------------------------
# AC2 / AC3 — fail-closed 426 negative paths (mutation must NOT run)
# ---------------------------------------------------------------------------


def test_missing_both_headers_blocks_mutation_with_426() -> None:
    """AC2: missing handshake at a mutating endpoint -> 426, no mutation."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST", path=_TELEMETRY_PATH, body=b"{}", request_headers={},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    payload = json.loads(response.body)
    assert payload["error_code"] == "upgrade_required"
    assert payload["correlation_id"]
    assert payload["detail"]["compat"]["agent_runtime"]["min"] == "1.0.0"
    headers = _headers(response.headers)
    assert headers[COMPAT_RECOMMENDED_HEADER] == "2.0.0"
    assert telemetry.calls == 0


def test_missing_client_header_blocks_with_426() -> None:
    """AC3: missing X-AK3-Client alone -> 426."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=b"{}",
        request_headers={SKILL_BUNDLE_HEADER: "bundle-1"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert CLIENT_VERSION_HEADER in json.loads(response.body)["error"]
    assert telemetry.calls == 0


def test_missing_skill_bundle_header_blocks_with_426() -> None:
    """AC3: missing X-AK3-Skill-Bundle alone -> 426."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=b"{}",
        request_headers={CLIENT_VERSION_HEADER: "2.0.0"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert SKILL_BUNDLE_HEADER in json.loads(response.body)["error"]
    assert telemetry.calls == 0


def test_runtime_below_min_blocks_with_426() -> None:
    """AC2: runtime below ``min`` -> 426, no mutation."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "0.9.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert telemetry.calls == 0


def test_runtime_in_blocked_list_blocks_with_426() -> None:
    """AC2: runtime in ``blocked`` -> 426, no mutation."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "1.5.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert telemetry.calls == 0


def test_runtime_blocked_matches_numeric_equal_notation() -> None:
    """F1 fail-open regression: the server blocks a runtime that is numerically
    equal to a blocked entry in a DIFFERENT notation, matching the level-2 update
    driver (``installer.lifecycle.update._is_blocked_version``).

    A client ``"1.2"`` against blocked ``["1.2.0"]`` was PASS under the prior
    exact-string membership (fail-open: a blocked version in a different notation
    slipped past the server while ``agentkit update`` already reported BLOCKED).
    The numeric-aware blocked semantics is the SSOT, so both sides now reject it.
    """
    telemetry = _RecordingTelemetryService()
    window = CompatWindow(
        agent_runtime=VersionAxisWindow(
            min="1.0.0", max="3.0.0", recommended="1.0.0", blocked=("1.2.0",),
        ),
        wire=VersionAxisWindow(min="1", max="1", recommended="1", blocked=()),
    )
    app = ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(window=window),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "1.2", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert "blocked" in json.loads(response.body)["error"].lower()
    assert telemetry.calls == 0


def test_runtime_unparsable_blocked_entry_does_not_crash() -> None:
    """F1 tolerance: an unparsable blocked entry never crashes the comparison; a
    non-matching runtime still proceeds (mirrors update.py's skip-safely tolerance)."""
    telemetry = _RecordingTelemetryService()
    window = CompatWindow(
        agent_runtime=VersionAxisWindow(
            min="1.0.0", max="3.0.0", recommended="1.0.0", blocked=("garbage", "1.2.0"),
        ),
        wire=VersionAxisWindow(min="1", max="1", recommended="1", blocked=()),
    )
    app = ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(window=window),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "1.3.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.CREATED)
    assert telemetry.calls == 1


def test_unsupported_wire_version_blocks_with_426() -> None:
    """AC2: an unsupported wire version (``/v2``) at a mutation -> 426."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path="/v2/telemetry/events",
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert "wire" in json.loads(response.body)["error"].lower()
    assert telemetry.calls == 0


# ---------------------------------------------------------------------------
# AC4 — WARNING / PASS pass-through with advisory headers
# ---------------------------------------------------------------------------


def test_runtime_below_recommended_runs_with_warning_header() -> None:
    """AC3/AC4: in-window-but-below-recommended runs (WARNING), no block."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "1.0.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.CREATED)
    assert telemetry.calls == 1
    headers = _headers(response.headers)
    assert headers[COMPAT_RECOMMENDED_HEADER] == "2.0.0"
    assert "2.0.0" in headers[COMPAT_WARNING_HEADER]


def test_runtime_at_or_above_recommended_passes_without_warning() -> None:
    """AC4: runtime >= recommended runs without the WARNING header."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.CREATED)
    assert telemetry.calls == 1
    headers = _headers(response.headers)
    assert headers[COMPAT_RECOMMENDED_HEADER] == "2.0.0"
    assert COMPAT_BLOCKED_HEADER in headers
    assert COMPAT_WARNING_HEADER not in headers


def test_read_only_endpoint_is_not_handshake_gated() -> None:
    """A read-only GET without headers is never blocked (hen-and-egg safety)."""
    app = _build_app()

    response = app.handle_request(method="GET", path="/v1/compat", body=b"")

    assert response.status_code == int(HTTPStatus.OK)


def test_handshake_disabled_by_default_does_not_block_mutations() -> None:
    """Without an injected middleware, mutations are not handshake-gated."""
    telemetry = _RecordingTelemetryService()
    app = ControlPlaneApplication(telemetry_service=telemetry)  # type: ignore[arg-type]

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={},
    )

    assert response.status_code == int(HTTPStatus.CREATED)
    assert telemetry.calls == 1


def test_compat_window_axes_are_typed_and_closed() -> None:
    """The compat window is a typed Pydantic model (TYPISIERT STATT STRINGS)."""
    window = default_compat_window()
    assert window.agent_runtime.min
    assert window.wire.min == "1"
    # extra fields are forbidden (stable contract)
    with pytest.raises(ValueError, match="extra"):
        VersionAxisWindow.model_validate(
            {"min": "1", "max": "1", "recommended": "1", "blocked": [], "x": 1},
        )


# ---------------------------------------------------------------------------
# Item 2 — full [min, max] window enforcement (boundary tests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client_version", "expected_status"),
    [
        ("0.9.0", int(HTTPStatus.UPGRADE_REQUIRED)),  # below min -> 426
        ("1.0.0", int(HTTPStatus.CREATED)),  # exactly min -> in window (WARNING runs)
        ("3.0.0", int(HTTPStatus.CREATED)),  # exactly max -> in window
        ("3.0.1", int(HTTPStatus.UPGRADE_REQUIRED)),  # above max -> 426
        ("4.0.0", int(HTTPStatus.UPGRADE_REQUIRED)),  # above max -> 426
    ],
)
def test_runtime_window_boundaries(
    client_version: str, expected_status: int,
) -> None:
    """Item 2: both bounds enforced — below-min/above-max 426, min/max admitted."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: client_version, SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == expected_status
    # The mutation runs only on the admitted (in-window) versions.
    assert telemetry.calls == (1 if expected_status == int(HTTPStatus.CREATED) else 0)


def test_runtime_above_max_blocks_with_explicit_reason() -> None:
    """Item 2: an above-max runtime is rejected with an above-max error message."""
    app = _build_app(_RecordingTelemetryService())

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "9.9.9", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert "above" in json.loads(response.body)["error"].lower()


# ---------------------------------------------------------------------------
# Item 3 — missing wire prefix on a required endpoint -> 426 (not 404)
# ---------------------------------------------------------------------------


def test_required_endpoint_without_wire_prefix_blocks_426_not_404() -> None:
    """Item 3: a required logical endpoint with NO /vN prefix fails closed 426."""
    telemetry = _RecordingTelemetryService()
    app = _build_app(telemetry)

    response = app.handle_request(
        method="POST",
        path="/telemetry/events",  # no /v1 prefix
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "b"},
    )

    assert response.status_code == int(HTTPStatus.UPGRADE_REQUIRED)
    assert "wire" in json.loads(response.body)["error"].lower()
    assert telemetry.calls == 0


# ---------------------------------------------------------------------------
# Item 1 — route classification (Dev-agent->Core required, browser/auth exempt)
# ---------------------------------------------------------------------------


def test_route_classifier_required_set() -> None:
    """Item 1: the typed classifier marks the Dev-agent->Core surface required."""
    classifier = HandshakeRouteClassifier()
    for required in (
        "/v1/telemetry/events",
        "/v1/project-edge/sync",
        "/v1/project-edge/operations/op-1",
        "/v1/story-runs/r1/phases/implementation/start",
        "/v1/story-runs/r1/closure/complete",
        "/v1/projects/p/story-runs/r1/phases/setup/complete",
        "/v1/projects/p/story-runs/r1/closure/complete",
    ):
        # Always-required patterns are gated regardless of method.
        assert classifier.requires_handshake(required, "POST"), required
        assert classifier.requires_handshake(required, "GET"), required


def test_route_classifier_governance_is_method_aware() -> None:
    """Item 1: governance READS are exempt (FK-72 §72.11), mutations stay required."""
    classifier = HandshakeRouteClassifier()
    for governance in ("/v1/projects/p/governance", "/v1/projects/p/governance/hooks"):
        # FK-72 §72.11: the browser Inspector READS governance status without an
        # agent header -> a GET must NOT be handshake-gated (no 426 on the UI read).
        assert not classifier.requires_handshake(governance, "GET"), governance
        assert not classifier.requires_handshake(governance, "HEAD"), governance
        # FK-91 §91.1a Regel 11: a Dev-agent->Core governance COMMAND stays gated.
        for mutation in ("POST", "PUT", "PATCH", "DELETE"):
            assert classifier.requires_handshake(governance, mutation), governance


def test_route_classifier_exempt_set() -> None:
    """Item 1: auth/health/compat and frontend read/write routes are exempt."""
    classifier = HandshakeRouteClassifier()
    for exempt in (
        "/healthz",
        "/v1/compat",
        "/v1/auth/login",
        "/v1/projects/p/stories",  # +Story create (browser)
        "/v1/projects/p/stories/s1/approve",  # status drag&drop (browser)
        "/v1/projects/p/stories/s1",  # sheet inline edit (browser)
        "/v1/projects/p/planning/proposals",  # parallelisation config (browser)
        "/v1/projects/p/execution-input/limits",  # caps PUT (browser)
        "/v1/projects/p/dashboard/board",  # read
        "/v1/projects",  # project list
    ):
        # Exempt regardless of method (browser surface carries no agent header).
        assert not classifier.requires_handshake(exempt, "POST"), exempt
        assert not classifier.requires_handshake(exempt, "GET"), exempt


def test_auth_login_post_without_handshake_is_not_426() -> None:
    """Item 1: POST /v1/auth/login without X-AK3-* is exempt (UI login not broken)."""
    app = _build_app()  # handshake ON, auth OFF

    response = app.handle_request(
        method="POST",
        path="/v1/auth/login",
        body=b'{"username": "x", "password": "y", "project_key": "p"}',
        request_headers={},
    )

    assert response.status_code != int(HTTPStatus.UPGRADE_REQUIRED)


# ---------------------------------------------------------------------------
# Item 6 — stale-but-allowed skill bundle -> WARNING (never hard-block)
# ---------------------------------------------------------------------------


def _build_app_with_bundle_window(
    telemetry: _RecordingTelemetryService,
    bundle_window: VersionAxisWindow,
) -> ControlPlaneApplication:
    return ControlPlaneApplication(
        version_handshake_middleware=VersionHandshakeMiddleware(
            window=_test_window(), bundle_window=bundle_window,
        ),
        telemetry_service=telemetry,  # type: ignore[arg-type]
    )


def test_stale_but_allowed_bundle_runs_with_warning_header() -> None:
    """Item 6 (AC3): a stale-but-allowed bundle runs and carries a WARNING header."""
    telemetry = _RecordingTelemetryService()
    bundle_window = VersionAxisWindow(
        min="1.0.0", max="3.0.0", recommended="2.0.0", blocked=(),
    )
    app = _build_app_with_bundle_window(telemetry, bundle_window)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        # runtime PASS (>= recommended) so ONLY the bundle drives the warning.
        request_headers={CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "1.0.0"},
    )

    assert response.status_code == int(HTTPStatus.CREATED)  # not blocked
    assert telemetry.calls == 1
    warning = _headers(response.headers)[COMPAT_WARNING_HEADER]
    assert "bundle" in warning.lower()


def test_blocked_bundle_warns_but_does_not_block() -> None:
    """Item 6: a centrally-outdated bundle hints (WARNING) but never bricks (FK-10 §10.2.8)."""
    telemetry = _RecordingTelemetryService()
    bundle_window = VersionAxisWindow(
        min="1.0.0", max="3.0.0", recommended="2.0.0", blocked=("1.0.0",),
    )
    app = _build_app_with_bundle_window(telemetry, bundle_window)

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "1.0.0"},
    )

    assert response.status_code == int(HTTPStatus.CREATED)
    assert telemetry.calls == 1
    assert COMPAT_WARNING_HEADER in _headers(response.headers)


def test_current_bundle_passes_without_warning() -> None:
    """Item 6: a current (>= recommended) bundle passes with no bundle warning."""
    telemetry = _RecordingTelemetryService()
    app = _build_app_with_bundle_window(
        telemetry,
        VersionAxisWindow(min="1.0.0", max="3.0.0", recommended="2.0.0", blocked=()),
    )

    response = app.handle_request(
        method="POST",
        path=_TELEMETRY_PATH,
        body=_valid_telemetry_body(),
        request_headers={CLIENT_VERSION_HEADER: "2.0.0", SKILL_BUNDLE_HEADER: "2.0.0"},
    )

    assert response.status_code == int(HTTPStatus.CREATED)
    assert COMPAT_WARNING_HEADER not in _headers(response.headers)


def test_default_bundle_window_is_central_ssot() -> None:
    """Item 6: the bundle window comes from the same core-owned SSOT module."""
    bundle = default_bundle_window()
    assert bundle.min and bundle.recommended
    # The middleware sources it from the central default by construction.
    assert VersionHandshakeMiddleware().bundle_window == default_bundle_window()
