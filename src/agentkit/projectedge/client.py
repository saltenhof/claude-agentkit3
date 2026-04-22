"""Local Project Edge Client for control-plane calls and bundle publish."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"control-plane request failed with HTTP {exc.code}: {detail}",
            ) from exc
        data = json.loads(response_body.decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("control-plane response must be a JSON object")
        return data


class LocalEdgePublisher:
    """Atomically publish the locally readable governance bundle."""

    def __init__(self, *, project_root: Path) -> None:
        self._project_root = project_root

    def publish(self, bundle: EdgeBundle) -> None:
        bundle_root = self._project_root / bundle.current.bundle_dir
        bundle_root.mkdir(parents=True, exist_ok=True)
        _write_json(bundle_root / "session.json", _session_payload(bundle))
        _write_json(bundle_root / "lock.json", bundle.lock.model_dump(mode="json"))
        _write_json(
            self._project_root / "_temp" / "governance" / "current.json",
            bundle.current.model_dump(mode="json"),
        )

        if (
            bundle.session is not None
            and bundle.session.operating_mode == "story_execution"
        ):
            for root in bundle.session.worktree_roots:
                _write_json(
                    Path(root) / ".agent-guard" / "lock.json",
                    bundle.lock.model_dump(mode="json"),
                )
        for root in bundle.tombstone_worktree_roots:
            lock_path = Path(root) / ".agent-guard" / "lock.json"
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
