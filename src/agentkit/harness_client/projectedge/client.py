"""Local Project Edge Client for control-plane calls and bundle publish."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.control_plane.models import (
    ApiErrorResponse,
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    CreatedStorySummary,
    CreateStoryInputs,
    CreateStoryRequest,
    EdgeBundle,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.backend.exceptions import ControlPlaneApiError
from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    import ssl
    from collections.abc import Mapping

    # The reconciler is sourced through the ``story_creation`` create-flow surface
    # (which owns the reconcile entry point) rather than the client touching the
    # ``story_context_manager`` ``CreateStoryInput`` directly, so the ProjectEdge
    # boundary stays within its permitted import set (architecture-conformance
    # AC010). The reconciler derives that input INTERNALLY from ``CreateStoryInputs``
    # via :meth:`reconcile_only_from_inputs`.
    from agentkit.backend.story_creation.create_flow import StoryCreationReconciler

_LOCK_EXPORT_FILE = "lock.json"
_QA_LOCK_EXPORT_FILE = "qa-lock.json"


#: The wire header that carries the stable correlation id (FK-91 §91.1a Regel #7).
#: The control plane reads it on the request (adopting the client's id instead of
#: minting its own ``req-<uuid>``) and echoes it on every response.
_CORRELATION_HEADER = "X-Correlation-Id"


@dataclass(frozen=True)
class CreateStoryResult:
    """Typed result of an agent-facing create (summary + §21.4.2 counters).

    Carries the backend-allocated story summary plus the FK-21 §21.4.2 abgleich
    counters (``total_hits`` / ``above_threshold`` / ``sent_to_llm`` /
    ``llm_conflicts`` / ``threshold_used`` / ``search_mode``) of the reconciliation
    the client ran INSIDE the boundary. Surfacing the full counter set here lets
    the create surface (tool output / telemetry) carry it without re-running the
    reconciliation (Codex R2 residual #3 / AG3-115). The persisted-story
    projection of these counters is owned by the ``story_context_manager`` Story
    model (a foreign owner), so AG3-114's surface carries them on the wire body
    (inside ``reconciliation``) and in this result, not as new Story columns.

    Attributes:
        summary: The backend-allocated created-story summary (the server truth).
        reconciliation_counters: The FK-21 §21.4.2 abgleich-protocol counters of
            the in-boundary reconciliation, as their canonical wire-key dict.
    """

    summary: CreatedStorySummary
    reconciliation_counters: dict[str, object]


class ControlPlaneTransport(Protocol):
    """Send one control-plane request and return the decoded JSON object."""

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        ...


class HttpsJsonTransport:
    """Minimal HTTPS JSON transport for the local edge client."""

    def __init__(
        self,
        *,
        base_url: str,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ssl_context = ssl_context

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        body = (
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            if payload is not None
            else None
        )
        request_headers = {"Content-Type": "application/json"}
        if headers is not None:
            # FK-91 §91.1a Regel #7: pass through the caller's correlation header
            # so the control plane adopts the SAME id it audits (no divergent
            # ``req-<uuid>``). Content-Type stays authoritative.
            for key, value in headers.items():
                if key.lower() != "content-type":
                    request_headers[key] = value
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            method=method,
            data=body,
            headers=request_headers,
        )
        try:
            with urllib.request.urlopen(
                request,
                context=self._ssl_context,
            ) as response:
                response_body = response.read()
                response_correlation = response.headers.get(_CORRELATION_HEADER)
        except urllib.error.HTTPError as exc:
            return self._handle_http_error(exc)
        data = json.loads(response_body.decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("control-plane response must be a JSON object")
        # Surface the SERVER's correlation id (Regel #7) from the response header
        # when the body does not already carry one, so the official client reports
        # the id the control plane actually audited (never a locally invented id).
        if response_correlation and not data.get("correlation_id"):
            data["correlation_id"] = response_correlation
        return data

    @staticmethod
    def _handle_http_error(exc: urllib.error.HTTPError) -> dict[str, object]:
        """Map an ``HTTPError`` to a structured rejection or re-raise.

        AG3-054 (FK-20 §20.8.2): the control plane returns HTTP 409 Conflict for a
        fail-closed REJECTED mutation (pre-start-guard denial / invalid first-call
        / illegal transition; see ``http.py``). That 409 body is a structured
        :class:`ControlPlaneMutationResult` with ``status == "rejected"`` -- it is
        a legitimate, expected outcome, NOT a transport failure. We parse it and
        RETURN the structured object so the official client surfaces the rejection
        (and the ``edge_bundle is None`` publish-skip applies on the real path).
        Every OTHER HTTP error (and any 409 whose body is not a rejected mutation
        result) still raises ``RuntimeError`` -- no silent fallback.

        Args:
            exc: The raised ``HTTPError``.

        Returns:
            The decoded rejected mutation result body (a JSON object).

        Raises:
            RuntimeError: For any non-409 error, or a 409 whose body is not a
                rejected control-plane mutation result.
        """
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == HTTPStatus.CONFLICT:
            rejected = _parse_rejected_conflict_body(detail)
            if rejected is not None:
                return rejected
        # FK-91 §91.1a Regel #8: an error body that conforms to the stable error
        # contract (error_code/error/correlation_id) is surfaced as a typed
        # ControlPlaneApiError so the official client carries the structured
        # rejection (e.g. fail-closed reconciliation_evidence_missing on
        # POST /v1/stories). A non-conforming body still raises RuntimeError.
        api_error = _parse_api_error_body(detail, http_status=exc.code)
        if api_error is not None:
            raise api_error
        raise RuntimeError(
            f"control-plane request failed with HTTP {exc.code}: {detail}",
        )


def _parse_rejected_conflict_body(detail: str) -> dict[str, object] | None:
    """Validate a 409 body as a conforming rejected mutation result (W8).

    A 409 is the expected transport for a fail-closed REJECTED mutation, whose
    body is a structured :class:`ControlPlaneMutationResult` with
    ``status == "rejected"`` and ``edge_bundle is None``. The body is partly
    attacker-influenced (the rejection_reason echoes request-derived text), so it
    is STRICTLY validated against the model before being trusted: it must parse,
    ``model_validate`` to a ``ControlPlaneMutationResult``, carry
    ``status == "rejected"`` AND ``edge_bundle is None``. A malformed / non-
    conforming 409 returns ``None`` so the caller RAISES (no bogus result is ever
    returned as if it were a legitimate rejection).

    Args:
        detail: The raw decoded 409 response body.

    Returns:
        The validated rejected-result body (a JSON object), or ``None`` when the
        body is not a conforming rejected mutation result.
    """
    from pydantic import ValidationError

    try:
        body = json.loads(detail)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    try:
        parsed = ControlPlaneMutationResult.model_validate(body)
    except ValidationError:
        return None
    if parsed.status != "rejected" or parsed.edge_bundle is not None:
        return None
    return body


def _parse_api_error_body(
    detail: str, *, http_status: int
) -> ControlPlaneApiError | None:
    """Parse an HTTP error body as a stable §91.1a error contract (Regel #8).

    The error body must parse, ``model_validate`` to an :class:`ApiErrorResponse`
    (i.e. carry ``error_code``, ``error`` and ``correlation_id``), to be trusted
    as a structured rejection. A malformed / non-conforming body returns ``None``
    so the caller raises a plain ``RuntimeError`` (no silent fallback to weaker
    error data).

    Args:
        detail: The raw decoded error response body.
        http_status: The HTTP status code of the error response.

    Returns:
        A typed :class:`ControlPlaneApiError`, or ``None`` when the body is not a
        conforming stable-contract error.
    """
    from pydantic import ValidationError

    try:
        body = json.loads(detail)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    try:
        parsed = ApiErrorResponse.model_validate(body)
    except ValidationError:
        return None
    structured_detail = (
        parsed.detail if isinstance(parsed.detail, dict) else None
    )
    return ControlPlaneApiError(
        parsed.error,
        error_code=parsed.error_code,
        correlation_id=parsed.correlation_id,
        http_status=http_status,
        detail=structured_detail,
    )


class LocalEdgePublisher:
    """Atomically publish the locally readable governance bundle."""

    def __init__(self, *, project_root: Path) -> None:
        self._project_root = project_root

    def publish(self, bundle: EdgeBundle) -> None:
        bundle_root = self._project_root / bundle.current.bundle_dir
        bundle_root.mkdir(parents=True, exist_ok=True)
        _write_json(bundle_root / "session.json", _session_payload(bundle))
        if bundle.lock is not None:
            _write_json(
                bundle_root / _LOCK_EXPORT_FILE,
                bundle.lock.model_dump(mode="json"),
            )
        if bundle.qa_lock is not None:
            _write_json(
                bundle_root / _QA_LOCK_EXPORT_FILE,
                bundle.qa_lock.model_dump(mode="json"),
            )
        _write_json(
            self._project_root / "_temp" / "governance" / "current.json",
            bundle.current.model_dump(mode="json"),
        )

        if (
            bundle.session is not None
            and bundle.session.operating_mode == "story_execution"
            and bundle.lock is not None
        ):
            for root in bundle.session.worktree_roots:
                _write_json(
                    Path(root) / ".agent-guard" / _LOCK_EXPORT_FILE,
                    bundle.lock.model_dump(mode="json"),
                )
        for root in bundle.tombstone_worktree_roots:
            lock_path = Path(root) / ".agent-guard" / _LOCK_EXPORT_FILE
            if lock_path.exists():
                lock_path.unlink()


class ProjectEdgeClient:
    """Official local mutation path: control-plane call plus local publish."""

    def __init__(
        self,
        *,
        transport: ControlPlaneTransport,
        publisher: LocalEdgePublisher,
    ) -> None:
        self._transport = transport
        self._publisher = publisher

    def start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._post_and_publish(
            path=f"/v1/story-runs/{run_id}/phases/{phase}/start",
            payload=request.model_dump(mode="json"),
        )

    def complete_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._post_and_publish(
            path=f"/v1/story-runs/{run_id}/phases/{phase}/complete",
            payload=request.model_dump(mode="json"),
        )

    def fail_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._post_and_publish(
            path=f"/v1/story-runs/{run_id}/phases/{phase}/fail",
            payload=request.model_dump(mode="json"),
        )

    def complete_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
    ) -> ControlPlaneMutationResult:
        return self._post_and_publish(
            path=f"/v1/story-runs/{run_id}/closure/complete",
            payload=request.model_dump(mode="json"),
        )

    def sync(self, request: ProjectEdgeSyncRequest) -> ControlPlaneMutationResult:
        return self._post_and_publish(
            path="/v1/project-edge/sync",
            payload=request.model_dump(mode="json"),
        )

    def create_story(
        self,
        inputs: CreateStoryInputs,
        *,
        reconciler: StoryCreationReconciler,
        story_body: str,
        op_id: str,
        correlation_id: str = "",
        story_was_adapted: bool = False,
        story_display_id: str = "",
    ) -> CreateStoryResult:
        """Create a story via the agent-facing boundary.

        This is the §91.1a Regel #3 agent path: agents create stories ONLY
        through the official client against the Control Plane (never ``gh issue
        create`` / free ``curl``). The Control Plane is the single, canonical
        story truth — the story id is backend-allocated, never client-assigned
        (Regel #9). The request targets the actually exposed, tenant-scoped create
        route ``POST /v1/projects/{project_key}/stories`` (§91.1a Regel #1 / FK-72
        §72.8.1: ``project_key`` is a mandatory path segment for every project-
        scoped mutation, so the create passes through ``TenantScopeMiddleware``).
        The ``project_key`` is taken from the single ``CreateStoryInputs`` master
        data, so it can never diverge from the story the route persists.

        The reconciliation runs INSIDE this boundary: the client drives the REAL
        fail-closed :meth:`StoryCreationReconciler.reconcile_only` (FK-21 §21.4
        stage 1 search + the wired stage-2 conflict adjudicator) here and builds
        the wire body — including the typed ``reconciliation`` evidence and the
        authoritative ``participating_repos`` — from the resulting outcome. The
        reconciler input is derived INTERNALLY from the SAME ``CreateStoryInputs``
        that is persisted (one master-data object that is BOTH reconciled and
        sent): there is no split-input seam where a caller could reconcile object
        A and persist object B (FK-21 §21.4 "proof the reconciliation actually
        ran", FIX-THE-MODEL / Codex R2 finding #1+#2). The surface accepts only
        the story master data plus the real reconciler, so the only evidence that
        can reach the boundary is evidence the real reconciliation just produced.

        The route then re-enforces the evidence fail-closed: a missing /
        inconsistent block is rejected BEFORE any persistence and surfaces here as
        a :class:`~agentkit.backend.exceptions.ControlPlaneApiError` with
        ``error_code == "reconciliation_evidence_missing"`` (no dummy evidence, no
        bypass). ``op_id`` is the idempotency key (Regel #5): repeating the same
        ``op_id`` returns the same story without a second mutation.
        ``correlation_id`` is sent as the ``X-Correlation-Id`` request header so
        the control plane ADOPTS and audits it (Regel #7); the id the server echoes
        back is surfaced on the returned summary.

        Args:
            inputs: The typed story master data (no reconciliation evidence). It is
                the SINGLE master record — both the reconciler input and the
                persisted body are derived from it (no split-input seam).
            reconciler: The REAL reconcile runtime (fail-closed Weaviate gate +
                wired conflict adjudicator). The client drives its
                ``reconcile_only`` here so the evidence is produced inside the
                boundary, never handed in.
            story_body: The full story markdown body (the reconciliation query and
                the repo-affinity strong-evidence source).
            op_id: The idempotency key (Regel #5).
            correlation_id: Stable correlation id to propagate (Regel #7); sent as
                ``X-Correlation-Id`` so the server adopts it, and echoed back on
                the returned summary.
            story_was_adapted: Whether a detected stage-2 conflict was resolved by
                ADAPTING (not discarding) the story (FK-21 §21.4.1).
            story_display_id: Optional display-ID for the search query scope /
                telemetry.

        Returns:
            A :class:`CreateStoryResult` carrying the created story summary
            (backend-allocated ``story_id``, status, the audited correlation id)
            plus the FK-21 §21.4.2 reconciliation counters of the in-boundary run.

        Raises:
            ControlPlaneApiError: When the boundary rejects the create with the
                stable error contract (validation / forbidden / idempotency
                mismatch / reconciliation evidence missing). FAIL-CLOSED: no
                story is created in that case.
            RuntimeError: For a transport failure / non-contract error response.
            VectorDbError: When the in-boundary reconciliation fails closed (e.g. a
                Weaviate outage) -- no story is created.
            ConflictAdjudicationUnavailableError: When stage-2 conflict
                adjudication has no create-time owner -- fail-closed.
            CreateTimeConflictAdjudicationError: When the create-time LLM conflict
                assessment could not run -- fail-closed.
        """
        # Run the fail-closed reconciliation INSIDE the boundary so the evidence is
        # produced here from the SINGLE master-data object, never accepted from the
        # caller. ``reconcile_only_from_inputs`` derives the reconciler's
        # ``CreateStoryInput`` INTERNALLY from the SAME ``CreateStoryInputs`` that
        # is persisted, so the reconciled record and the persisted record are one
        # and the same (no split-input seam; Codex R2 finding #2). The
        # ``CreateStoryInput`` construction stays inside the ``story_creation``
        # owner — the ProjectEdge boundary never imports ``story_context_manager``
        # (architecture-conformance AC010).
        outcome = reconciler.reconcile_only_from_inputs(
            inputs,
            story_body=story_body,
            story_was_adapted=story_was_adapted,
            story_display_id=story_display_id,
        )
        request = CreateStoryRequest.from_evidence(
            inputs,
            outcome.evidence,
            op_id=op_id,
            participating_repos=outcome.participating_repos,
        )
        headers = (
            {_CORRELATION_HEADER: correlation_id} if correlation_id else None
        )
        # Target the actually exposed tenant-scoped route (§91.1a Regel #1 /
        # FK-72 §72.8.1). ``project_key`` is URL-encoded so a key with reserved
        # characters cannot break out of the path segment.
        project_segment = urllib.parse.quote(inputs.project_key, safe="")
        data = self._transport.send(
            method="POST",
            path=f"/v1/projects/{project_segment}/stories",
            payload=request.to_wire_body(),
            headers=headers,
        )
        summary = CreatedStorySummary.model_validate(data)
        if correlation_id and not summary.correlation_id:
            summary = summary.model_copy(update={"correlation_id": correlation_id})
        # Surface the full FK-21 §21.4.2 counter set from the in-boundary
        # reconciliation (Codex R2 residual #3): the create surface carries them
        # without re-running the reconciliation.
        from agentkit.backend.story_creation.vectordb_reconciliation import AbgleichProtocol

        counters = AbgleichProtocol.from_result(outcome.reconciliation).to_wire()
        return CreateStoryResult(summary=summary, reconciliation_counters=counters)

    def reconcile_operation(self, op_id: str) -> ControlPlaneMutationResult:
        data = self._transport.send(
            method="GET",
            path=f"/v1/project-edge/operations/{op_id}",
        )
        result = ControlPlaneMutationResult.model_validate(data)
        if result.edge_bundle is not None:
            self._publisher.publish(result.edge_bundle)
        return result

    def _post_and_publish(
        self,
        *,
        path: str,
        payload: Mapping[str, object],
    ) -> ControlPlaneMutationResult:
        data = self._transport.send(method="POST", path=path, payload=payload)
        result = ControlPlaneMutationResult.model_validate(data)
        # AG3-054 (FK-20 §20.8.2): a fail-closed REJECTED start carries no edge
        # bundle (it materialized no run state). There is nothing to publish
        # locally -- publishing must be skipped so the local edge is not activated
        # for a run the control plane denied.
        if result.edge_bundle is not None:
            self._publisher.publish(result.edge_bundle)
        return result


def _write_json(path: Path, payload: dict[str, object]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, default=str))


def _session_payload(bundle: EdgeBundle) -> dict[str, object]:
    if bundle.session is None:
        return {
            "operating_mode": bundle.current.operating_mode,
            "project_key": bundle.current.project_key,
            "export_version": bundle.current.export_version,
        }
    return bundle.session.model_dump(mode="json")
