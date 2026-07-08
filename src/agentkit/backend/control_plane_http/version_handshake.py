"""Version handshake middleware and compat window (FK-91 §91.1a Rule 11).

The ``/v1`` boundary between the developer machine (levels 2/3) and the central
core (level 1) is an explicitly **negotiated** wire boundary, not a static
prefix.  FK-91 §91.1a Rule 11 and FK-10 §10.2.7/§10.2.8 require a version
handshake: every Dev->Control-Plane request carries the agent-runtime package
version (``X-AK3-Client``) and the bound skill bundle (``X-AK3-Skill-Bundle``).
The core validates the runtime against a supported ``[min, max]`` window,
announces ``recommended``/``blocked`` and **fails closed with HTTP 426 Upgrade
Required** for incompatible requests.

The supported window is a central, versioned source of the core (the
:func:`default_compat_window` / :func:`default_bundle_window` constants), never
project-local state (FK-10 §10.2.7: manifest authority stays central).  The
reaction matrix mirrors FK-10 §10.2.8:

* **ERROR / fail-closed (HTTP 426):** agent-runtime below ``min``, above ``max``
  or in ``blocked``; unsupported / missing wire version; missing handshake at a
  Dev-agent->Core mutation / governance endpoint.
* **WARNING (request runs):** agent-runtime inside the window but below
  ``recommended``; a stale-but-allowed skill bundle -> a structured advisory
  response header, no block (FK-10 §10.2.8: "skills never hard-block").
* **PASS:** agent-runtime ``>= recommended`` with a current bundle.

**Route classification (FK-91 §91.1a Rule 11).** The handshake carries the
*agent-runtime* version, so it applies **only** to the Dev-agent->Core surface
(telemetry ingest, project-edge sync/operations, story-run phase / closure
mutations, governance commands).  Frontend / browser writes (``+Story`` create,
story approve/reject/cancel, field edits, planning, limits) reach the **same**
process through the BFF (FK-72 §72.8: one server process) and carry **no**
``X-AK3-*`` header; gating them would 426 the production UI (e.g.
``POST /v1/auth/login``).  The exempt set therefore covers auth, ``/healthz``,
``GET /v1/compat`` (otherwise a too-old client could never learn it is too old
-- hen-and-egg) and all frontend read / write routes.

**Governance is method-aware (FK-10 §10.2.7 / FK-72 §72.11).** Rule 11's
"governance endpoints" are the Dev-agent->Core governance *commands*
(mutations), not the browser read surface: the Frontend Inspector READS
governance status (Guard-/Hook-Status, FK-72 §72.11) browser->Core through the
same control-plane process carrying no agent header.  A governance **GET read**
is therefore EXEMPT (gating it would 426 the Inspector, the auth-login bug
class), while governance **mutations** remain handshake-REQUIRED.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from http import HTTPStatus
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.control_plane.models import ApiErrorResponse
from agentkit.backend.control_plane_http.header_lookup import lookup_header_ci

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from agentkit.backend.control_plane_http.app import HttpResponse

# ---------------------------------------------------------------------------
# Wire header names (ARCH-55: English identifiers / wire keys)
# ---------------------------------------------------------------------------

#: Request header carrying the dev agent-runtime package version (FK-91 Rule 11).
CLIENT_VERSION_HEADER = "X-AK3-Client"
#: Request header carrying the bound skill-bundle version (FK-91 Rule 11).
SKILL_BUNDLE_HEADER = "X-AK3-Skill-Bundle"
#: Response header announcing the recommended agent-runtime version.
COMPAT_RECOMMENDED_HEADER = "X-AK3-Compat-Recommended"
#: Response header announcing the comma-separated blocked agent-runtime versions.
COMPAT_BLOCKED_HEADER = "X-AK3-Compat-Blocked"
#: Response header carrying the structured upgrade WARNING (request still ran).
COMPAT_WARNING_HEADER = "X-AK3-Compat-Warning"

_CORRELATION_HEADER = "X-Correlation-Id"
_UPGRADE_REQUIRED_ERROR_CODE = "upgrade_required"

# ---------------------------------------------------------------------------
# Dev-agent->Core route classification (FK-91 §91.1a Rule 11, FK-72 §72.8)
# ---------------------------------------------------------------------------

#: Strips an optional ``/vN`` wire prefix and yields the logical (wire-agnostic)
#: path tail, so a route is classified by its *identity* and the wire version is
#: validated separately (a wrong / missing wire prefix on a required endpoint
#: must fail closed, not fall through to 404).
_WIRE_PREFIX_STRIP = re.compile(r"^/v\d+(?P<rest>/.*)?$")

#: Extracts the wire-version number ``N`` from a ``/vN`` / ``/vN/...`` path.
_WIRE_VERSION_PATTERN = re.compile(r"^/v(?P<wire>\d+)(?:/|$)")

#: HTTP methods that mutate state. Read methods (GET/HEAD/OPTIONS) are never a
#: mutation; everything else is treated as a write for handshake classification.
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: The wire-agnostic logical-path patterns of the Dev-agent->Core surface that
#: mandates the handshake for **every** method (typed allowlist, not a string-flag
#: cascade).  These are agent-runtime carriers regardless of verb, so they stay
#: required for all methods.  Everything not matched here (and not a governance
#: mutation below) is exempt (auth, health, compat, frontend read/write).
_REQUIRED_LOGICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Telemetry ingest (harness / agent-runtime -> core).
    re.compile(r"^/telemetry/events$"),
    # Project-edge sync + operation reconcile (official Project Edge Client).
    re.compile(r"^/project-edge/sync$"),
    re.compile(r"^/project-edge/operations/[^/]+$"),
    # Story-run phase + closure mutations (bare and project-scoped forms).
    # AG3-130: ``resume`` is a phase mutation of the same story-runs family and is
    # therefore handshake-required like start/complete/fail (FK-91 §91.1a Rule 11).
    re.compile(r"^/story-runs/[^/]+/phases/[^/]+/(?:start|complete|fail|resume)$"),
    re.compile(r"^/story-runs/[^/]+/closure/complete$"),
    re.compile(
        r"^/projects/[^/]+/story-runs/[^/]+/phases/[^/]+/(?:start|complete|fail|resume)$",
    ),
    re.compile(r"^/projects/[^/]+/story-runs/[^/]+/closure/complete$"),
)

#: Governance is method-aware (FK-10 §10.2.7 / FK-72 §72.11). The handshake
#: carries the *agent-runtime* version, so Rule 11's "governance endpoints" mean
#: the Dev-agent->Core governance *commands* (mutations), NOT the browser read
#: surface: the Frontend Inspector READS governance status (Guard-/Hook-Status,
#: FK-72 §72.11) browser->Core through the SAME control-plane process (FK-72
#: §72.8: one server) carrying NO ``X-AK3-*`` header.  Gating that GET read would
#: 426 the production UI (the auth-login bug class).  Therefore: governance
#: **reads** (GET/HEAD/OPTIONS) are EXEMPT; governance **mutations**
#: (POST/PUT/PATCH/DELETE), if any exist over ``/v1``, remain handshake-REQUIRED.
_MUTATION_ONLY_LOGICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/projects/[^/]+/governance(?:/.*)?$"),
    # AG3-129 (FK-91 §91.1a Rule 11 / Rule 12): the Dev-agent->Core governance
    # hook-mediation mutations (guard-counter record/housekeeping, worker-health
    # write) are bare (non-project-scoped, like ``/telemetry/events``). Their
    # WRITE verbs are handshake-required; the worker-health GET read stays exempt
    # (governance reads are method-aware, FK-72 §72.11).
    re.compile(r"^/governance/.*$"),
)


def _logical_path(route_path: str) -> str:
    """Return ``route_path`` with an optional leading ``/vN`` prefix removed."""
    match = _WIRE_PREFIX_STRIP.match(route_path)
    if match is None:
        return route_path
    return match.group("rest") or "/"


@dataclass(frozen=True)
class HandshakeRouteClassifier:
    """Typed classifier of the Dev-agent->Core handshake surface (Rule 11).

    A route requires the handshake iff its wire-agnostic logical path matches one
    of the always-required Dev-agent->Core patterns (any method) OR a
    mutation-only pattern under a mutating HTTP method.  The classification is
    deliberately wire-agnostic so that an unsupported / missing wire prefix on an
    otherwise-required endpoint is still recognised as required and fails closed
    (the wire version itself is validated by the middleware).

    Governance is method-aware: its GET reads are the FK-72 §72.11 browser read
    surface (no agent header) and stay EXEMPT, while its mutations remain
    handshake-REQUIRED (FK-91 §91.1a Rule 11 governance commands).

    Args:
        required_patterns: The compiled logical-path allowlist required for every
            method. Injectable for tests; defaults to the central Dev-agent->Core
            surface.
        mutation_only_patterns: The compiled logical-path allowlist required only
            under a mutating HTTP method (governance commands). Injectable for
            tests; defaults to the governance subtree.
    """

    required_patterns: tuple[re.Pattern[str], ...] = _REQUIRED_LOGICAL_PATTERNS
    mutation_only_patterns: tuple[re.Pattern[str], ...] = _MUTATION_ONLY_LOGICAL_PATTERNS

    def requires_handshake(self, route_path: str, method: str) -> bool:
        """Return whether ``route_path`` is handshake-required for ``method``.

        Args:
            route_path: The URL path (already split from any query string).
            method: The HTTP method; governance is gated only on mutations
                (FK-72 §72.11: the GET governance read is the browser surface).
        """
        logical = _logical_path(route_path)
        if any(pattern.match(logical) for pattern in self.required_patterns):
            return True
        if method.upper() in _MUTATION_METHODS:
            return any(
                pattern.match(logical) for pattern in self.mutation_only_patterns
            )
        return False


# ---------------------------------------------------------------------------
# Central compatibility-window constants (SINGLE SOURCE OF TRUTH, core-owned)
# ---------------------------------------------------------------------------

#: Lowest still-supported agent-runtime version (below -> fail-closed 426).
_RUNTIME_MIN = "0.1.0"
#: Highest announced agent-runtime version of the current window.
_RUNTIME_MAX = "0.1.0"
#: Recommended agent-runtime version (below, but in window -> WARNING).
_RUNTIME_RECOMMENDED = "0.1.0"
#: Statically supported wire version (the ``/v1`` prefix). A bump produces
#: ``/v2`` (FK-10 §10.2.7: no in-place break), never an in-place change.
_WIRE_SUPPORTED = "1"
#: Skill-bundle window (FK-10 §10.2.7 axis). Bundles never hard-block on version
#: (FK-10 §10.2.8: "Skills brechen never hard-block except on integrity breach"); the window
#: only drives the stale-but-allowed WARNING. Sourced from the SAME core-owned
#: SSOT module as the compat window. Integrity (hash/signature) is out of scope
#: (FK-43/FK-44).
_BUNDLE_MIN = "0.1.0"
_BUNDLE_MAX = "0.1.0"
_BUNDLE_RECOMMENDED = "0.1.0"


class VersionAxisWindow(BaseModel):
    """Supported ``[min, max]`` window plus announce values for one version axis.

    Attributes:
        min: Lowest still-supported version (below it -> fail-closed).
        max: Highest announced version of the current window.
        recommended: Recommended version (in window but below it -> WARNING).
        blocked: Explicitly blocked versions (any match -> fail-closed).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    min: str = Field(min_length=1)
    max: str = Field(min_length=1)
    recommended: str = Field(min_length=1)
    blocked: tuple[str, ...] = ()


class CompatWindow(BaseModel):
    """Full compatibility window announced by ``GET /v1/compat`` (FK-91 §91.1a).

    Carries the complete ``min``/``max``/``recommended``/``blocked`` window for
    the two announced handshake axes: the agent runtime and the wire (``/v1``).
    The skill-bundle axis is a handshake participant (FK-10 §10.2.7) but is not
    part of the read surface (the catalogue pins ``/v1/compat`` to agent-runtime
    + wire); it lives on the middleware as :func:`default_bundle_window`.  The
    ``config_version``/``schema_version`` axes are intentionally absent -- they
    are parse/data contracts, not handshake participants (FK-10 §10.2.7).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_runtime: VersionAxisWindow
    wire: VersionAxisWindow


def default_compat_window() -> CompatWindow:
    """Build the central, core-owned compatibility window (SSOT constants)."""
    return CompatWindow(
        agent_runtime=VersionAxisWindow(
            min=_RUNTIME_MIN,
            max=_RUNTIME_MAX,
            recommended=_RUNTIME_RECOMMENDED,
            blocked=(),
        ),
        wire=VersionAxisWindow(
            min=_WIRE_SUPPORTED,
            max=_WIRE_SUPPORTED,
            recommended=_WIRE_SUPPORTED,
            blocked=(),
        ),
    )


def default_bundle_window() -> VersionAxisWindow:
    """Build the central, core-owned skill-bundle window (same SSOT module).

    The bundle axis only drives the stale-but-allowed WARNING (FK-10 §10.2.8);
    it never hard-blocks on version, so its ``min``/``max`` are advisory.
    """
    return VersionAxisWindow(
        min=_BUNDLE_MIN,
        max=_BUNDLE_MAX,
        recommended=_BUNDLE_RECOMMENDED,
        blocked=(),
    )


class _RuntimeDecision(Enum):
    """Typed reaction class for the agent-runtime axis (FK-10 §10.2.8)."""

    PASS = auto()
    WARNING = auto()
    BLOCK = auto()


@dataclass(frozen=True)
class HandshakeOutcome:
    """Result of evaluating the handshake for one request.

    Attributes:
        block: A ready-to-return 426 response when the handshake fails closed,
            else ``None`` (the request is allowed to proceed).
        advisory_headers: Response headers to attach to the downstream response
            on a PASS/WARNING at a handshake-required endpoint (announce +
            optional WARNING). Empty when nothing is to be announced.
    """

    block: HttpResponse | None = None
    advisory_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class VersionHandshakeMiddleware:
    """Validate the dev->central version handshake fail-closed (FK-91 Rule 11).

    Args:
        window: The supported agent-runtime + wire compatibility window. Defaults
            to the central core-owned :func:`default_compat_window` constants;
            injectable for tests and for the ops-set ``min``-client policy (FK-10
            §10.2.8).
        bundle_window: The supported skill-bundle window (same core-owned SSOT,
            :func:`default_bundle_window`). Drives only the stale-but-allowed
            WARNING; never hard-blocks (FK-10 §10.2.8).
        classifier: The Dev-agent->Core route classifier (Rule 11).
    """

    window: CompatWindow = field(default_factory=default_compat_window)
    bundle_window: VersionAxisWindow = field(default_factory=default_bundle_window)
    classifier: HandshakeRouteClassifier = field(default_factory=HandshakeRouteClassifier)

    def evaluate(
        self,
        *,
        method: str,
        route_path: str,
        request_headers: Mapping[str, str] | None,
        correlation_id: str,
    ) -> HandshakeOutcome:
        """Evaluate the handshake for one request.

        Args:
            method: The HTTP method (governance is gated only on mutations).
            route_path: The URL path (already split from any query string).
            request_headers: The incoming request headers (case-insensitive).
            correlation_id: The stable correlation id for the error contract.

        Returns:
            A :class:`HandshakeOutcome` carrying either a fail-closed 426 block
            or (for a passing request) the advisory response headers.
        """
        # Route + verb classification (Rule 11): the handshake carries the
        # agent-runtime version, so only the Dev-agent->Core surface is gated.
        # Governance is method-aware -- its GET read is the FK-72 §72.11 browser
        # surface and stays exempt. Everything else (auth, health, compat,
        # frontend) is exempt and proceeds without a block or announce.
        if not self.classifier.requires_handshake(route_path, method):
            return HandshakeOutcome()

        # Wire version: the ``/vN`` prefix is the carried wire version. On a
        # required endpoint a missing or unsupported wire prefix fails closed
        # (426), it must NOT fall through to 404.
        wire = _wire_version_from_path(route_path)
        if wire is None or not self._wire_supported(wire):
            label = f"'v{wire}'" if wire is not None else "(absent)"
            return self._block(
                f"Unsupported or missing wire version {label}; supported wire "
                f"window is [{self.window.wire.min}, {self.window.wire.max}]",
                correlation_id,
            )

        # A complete handshake is mandatory; each missing header fails closed
        # individually (FK-91 §91.1a Rule 11).
        client_version = lookup_header_ci(request_headers, CLIENT_VERSION_HEADER)
        if client_version is None or not client_version.strip():
            return self._block(
                f"Missing version handshake: header {CLIENT_VERSION_HEADER!r} is "
                f"required at Dev-agent->Core mutation and governance endpoints",
                correlation_id,
            )
        skill_bundle = lookup_header_ci(request_headers, SKILL_BUNDLE_HEADER)
        if skill_bundle is None or not skill_bundle.strip():
            return self._block(
                f"Missing version handshake: header {SKILL_BUNDLE_HEADER!r} is "
                f"required at Dev-agent->Core mutation and governance endpoints",
                correlation_id,
            )

        decision, runtime_reason = self._classify_runtime(client_version)
        if decision is _RuntimeDecision.BLOCK:
            return self._block(runtime_reason, correlation_id)

        warnings: list[str] = []
        if decision is _RuntimeDecision.WARNING:
            warnings.append(runtime_reason)
        bundle_warning = self._classify_bundle(skill_bundle)
        if bundle_warning is not None:
            warnings.append(bundle_warning)

        advisory = list(self._announce_headers())
        if warnings:
            advisory.append((COMPAT_WARNING_HEADER, "; ".join(warnings)))
        return HandshakeOutcome(advisory_headers=tuple(advisory))

    def guard(
        self,
        *,
        method: str,
        route_path: str,
        request_headers: Mapping[str, str] | None,
        correlation_id: str,
        dispatch: Callable[[], HttpResponse],
    ) -> HttpResponse:
        """Gate one request: fail-closed 426, else dispatch + attach advisories.

        Evaluates the handshake (FK-91 §91.1a Rule 11) after auth/tenant and
        before routing. On a fail-closed outcome the ready 426 block is returned
        without dispatching; otherwise ``dispatch`` runs and any announce/WARNING
        advisory headers are attached onto its response.
        """
        outcome = self.evaluate(
            method=method,
            route_path=route_path,
            request_headers=request_headers,
            correlation_id=correlation_id,
        )
        if outcome.block is not None:
            return outcome.block
        response = dispatch()
        if outcome.advisory_headers:
            response = replace(response, headers=response.headers + outcome.advisory_headers)
        return response

    def _classify_runtime(self, client_version: str) -> tuple[_RuntimeDecision, str]:
        """Classify the agent-runtime version against the window (FK-10 §10.2.8)."""
        runtime = self.window.agent_runtime
        if _is_blocked_version(client_version, runtime.blocked):
            return (
                _RuntimeDecision.BLOCK,
                f"Agent-runtime version {client_version!r} is blocked",
            )
        try:
            parsed = _parse_version(client_version)
        except ValueError:
            return (
                _RuntimeDecision.BLOCK,
                f"Agent-runtime version {client_version!r} is not a parsable version",
            )
        if _compare_versions(parsed, _parse_version(runtime.min)) < 0:
            return (
                _RuntimeDecision.BLOCK,
                f"Agent-runtime version {client_version!r} is below the minimum "
                f"supported version {runtime.min!r}",
            )
        if _compare_versions(parsed, _parse_version(runtime.max)) > 0:
            return (
                _RuntimeDecision.BLOCK,
                f"Agent-runtime version {client_version!r} is above the maximum "
                f"supported version {runtime.max!r}",
            )
        if _compare_versions(parsed, _parse_version(runtime.recommended)) < 0:
            return (
                _RuntimeDecision.WARNING,
                f"Agent-runtime version {client_version!r} is below the recommended "
                f"version {runtime.recommended!r}; update advised",
            )
        return (_RuntimeDecision.PASS, "")

    def _classify_bundle(self, bundle_version: str) -> str | None:
        """Return a stale-but-allowed WARNING message, or ``None`` when current.

        Skill bundles never hard-block on version (FK-10 §10.2.8: "Skills brechen
        never hard-block except on integrity breach"; a centrally-outdated bundle hints, never
        bricks). A stale-but-allowed bundle therefore only yields a WARNING.
        Integrity (hash/signature) is intentionally out of scope (FK-43/FK-44);
        only the bundle *version* participates in the handshake. A non-numeric /
        hash bundle that is not explicitly blocked cannot be proven stale and so
        passes without a warning.
        """
        window = self.bundle_window
        if bundle_version in window.blocked:
            return (
                f"Skill bundle {bundle_version!r} is centrally marked outdated; "
                f"update advised"
            )
        try:
            parsed = _parse_version(bundle_version)
        except ValueError:
            return None
        if _compare_versions(parsed, _parse_version(window.recommended)) < 0:
            return (
                f"Skill bundle {bundle_version!r} is below the recommended bundle "
                f"version {window.recommended!r}; update advised"
            )
        return None

    def _wire_supported(self, wire_version: str) -> bool:
        """Return True when ``wire_version`` lies inside the supported window."""
        wire = self.window.wire
        if wire_version in wire.blocked:
            return False
        try:
            parsed = _parse_version(wire_version)
        except ValueError:
            return False
        return (
            _compare_versions(parsed, _parse_version(wire.min)) >= 0
            and _compare_versions(parsed, _parse_version(wire.max)) <= 0
        )

    def _announce_headers(self) -> tuple[tuple[str, str], ...]:
        """Build the always-on announce headers (recommended/blocked)."""
        runtime = self.window.agent_runtime
        return (
            (COMPAT_RECOMMENDED_HEADER, runtime.recommended),
            (COMPAT_BLOCKED_HEADER, ",".join(runtime.blocked)),
        )

    def _block(self, message: str, correlation_id: str) -> HandshakeOutcome:
        """Build a fail-closed 426 outcome with the stable error contract.

        The 426 body follows the FK-91 §91.1a Rule 8 error contract
        (``error_code``/``error``/``correlation_id``) and announces the full
        compatibility window in ``detail`` plus the recommended/blocked headers.
        """
        from agentkit.backend.control_plane_http.app import HttpResponse

        payload = ApiErrorResponse(
            error_code=_UPGRADE_REQUIRED_ERROR_CODE,
            error=message,
            correlation_id=correlation_id,
            detail={"compat": self.window.model_dump(mode="json")},
        ).model_dump(mode="json", exclude_none=True)
        body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        headers = (
            (_CORRELATION_HEADER, correlation_id),
            *self._announce_headers(),
        )
        return HandshakeOutcome(
            block=HttpResponse(
                status_code=int(HTTPStatus.UPGRADE_REQUIRED),
                body=body,
                headers=headers,
            ),
        )


def _wire_version_from_path(route_path: str) -> str | None:
    """Extract the wire version ``N`` from a ``/vN/...`` path, else None."""
    match = _WIRE_VERSION_PATTERN.match(route_path)
    return match.group("wire") if match is not None else None


def _is_blocked_version(client_version: str, blocked: tuple[str, ...]) -> bool:
    """Return whether ``client_version`` matches a blocked entry (numeric-aware).

    Mirrors the level-2 update driver (``installer.lifecycle.update._is_blocked_version``)
    so the server handshake and ``agentkit update`` share ONE blocked semantics
    (SINGLE SOURCE OF TRUTH, fail-closed): a blocked entry matches when it is
    byte-for-byte equal to ``client_version`` OR when it parses to the same numeric
    version (so a blocked ``"1.2.0"`` also rejects an equivalent ``"1.2"`` and vice
    versa — the fail-open class where a blocked version in a different notation slips
    past is closed on both sides). An unparsable blocked entry (or an unparsable
    client version) never crashes the comparison: it can still match by exact string,
    otherwise it is skipped — an unparsable ``client_version`` that matches nothing
    here is still caught by the parse-block in :meth:`_classify_runtime`, never PASS.

    Args:
        client_version: The agent-runtime version carried on the request (raw).
        blocked: The blocked version strings of the agent-runtime axis.

    Returns:
        Whether ``client_version`` is blocked.
    """
    try:
        parsed_client: tuple[int, ...] | None = _parse_version(client_version)
    except ValueError:
        parsed_client = None
    for entry in blocked:
        if entry == client_version:
            return True
        if parsed_client is None:
            continue
        try:
            parsed_entry = _parse_version(entry)
        except ValueError:
            continue
        if _compare_versions(parsed_client, parsed_entry) == 0:
            return True
    return False


def _parse_version(value: str) -> tuple[int, ...]:
    """Parse a dotted numeric version into a comparable tuple.

    Raises:
        ValueError: When a segment is not a non-negative integer.
    """
    parts = value.strip().split(".")
    return tuple(int(part) for part in parts)


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Compare two version tuples (zero-padded), returning -1/0/+1."""
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)
