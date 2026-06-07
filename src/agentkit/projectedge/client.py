"""Local Project Edge Client for control-plane calls and bundle publish."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
)
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    import ssl
    from collections.abc import Mapping

_LOCK_EXPORT_FILE = "lock.json"
_QA_LOCK_EXPORT_FILE = "qa-lock.json"


class ControlPlaneTransport(Protocol):
    """Send one control-plane request and return the decoded JSON object."""

    def send(
        self,
        *,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
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
    ) -> dict[str, object]:
        body = (
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            url=f"{self._base_url}{path}",
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request,
                context=self._ssl_context,
            ) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            return self._handle_http_error(exc)
        data = json.loads(response_body.decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("control-plane response must be a JSON object")
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
