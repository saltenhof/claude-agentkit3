"""Fail-closed installer preflight for the mandatory Weaviate dependency."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.exceptions import ProjectError
from agentkit.backend.vectordb.endpoints import (
    split_grpc_endpoint,
    split_http_endpoint,
)
from agentkit.backend.vectordb.wait_for_weaviate import wait_for_weaviate
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError
from agentkit.integration_clients.vectordb.weaviate_adapter import (
    WeaviateStoryAdapter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.config.models import ProjectConfig

_MIN_VERSION = (1, 25, 0)
_MAX_VERSION = (2, 0, 0)


@dataclass(frozen=True)
class VectorDbPreflightReceipt:
    """Evidence that both configured endpoints identify a compatible Weaviate."""

    http_endpoint: str
    grpc_endpoint: str
    server_version: str


class VectorDbPreflightPort(Protocol):
    """External-boundary port used by installer tests and production wiring."""

    def check(self, config: ProjectConfig) -> VectorDbPreflightReceipt:
        """Raise on any configuration, identity, readiness, or compatibility fault."""


def _version_tuple(raw: object) -> tuple[int, int, int]:
    if not isinstance(raw, str):
        raise ProjectError(
            "Weaviate metadata has no string version",
            detail={"reason": "not_weaviate"},
        )
    pieces = raw.split(".")
    if len(pieces) < 2 or any(not piece.isdigit() for piece in pieces[:2]):
        raise ProjectError(
            f"Weaviate returned malformed version {raw!r}",
            detail={"reason": "incompatible_version", "version": raw},
        )
    patch = pieces[2].split("-", maxsplit=1)[0] if len(pieces) > 2 else "0"
    if not patch.isdigit():
        raise ProjectError(
            f"Weaviate returned malformed version {raw!r}",
            detail={"reason": "incompatible_version", "version": raw},
        )
    return int(pieces[0]), int(pieces[1]), int(patch)


def _required_endpoints(config: ProjectConfig) -> tuple[str, str]:
    vectordb = config.pipeline.vectordb
    if vectordb is None or vectordb.weaviate_http_endpoint is None or vectordb.weaviate_grpc_endpoint is None:
        raise ProjectError(
            "Mandatory VectorDB endpoints are missing",
            detail={"reason": "configuration_invalid"},
        )
    return vectordb.weaviate_http_endpoint, vectordb.weaviate_grpc_endpoint


class HttpVectorDbPreflight:
    """Production probe: HTTP readiness/identity plus configured gRPC reachability."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        readiness: Callable[[str, int, bool, str, int, bool, float], bool] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._readiness = readiness or _wait_for_explicit_endpoints

    def _get(self, url: str, *, failure_reason: str) -> bytes:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise ProjectError(
                f"Mandatory Weaviate endpoint rejected the readiness request: {url}",
                detail={
                    "reason": failure_reason,
                    "endpoint": url,
                    "status": exc.code,
                },
            ) from exc
        except OSError as exc:
            raise ProjectError(
                f"Mandatory Weaviate endpoint is unreachable: {url}",
                detail={"reason": "unreachable", "endpoint": url, "error": str(exc)},
            ) from exc

    def check(self, config: ProjectConfig) -> VectorDbPreflightReceipt:
        http_endpoint, grpc_endpoint = _required_endpoints(config)
        try:
            http_host, http_port, http_secure = split_http_endpoint(http_endpoint)
            grpc_host, grpc_port, grpc_secure = split_grpc_endpoint(grpc_endpoint)
        except VectorDbUnavailableError as exc:
            raise ProjectError(
                f"Mandatory VectorDB endpoint configuration is invalid: {exc}",
                detail={"reason": "configuration_invalid"},
            ) from exc

        ready = self._readiness(
            http_host,
            http_port,
            http_secure,
            grpc_host,
            grpc_port,
            grpc_secure,
            self._timeout_seconds,
        )

        raw_meta = self._get(
            f"{http_endpoint.rstrip('/')}/v1/meta",
            failure_reason="not_weaviate",
        )
        try:
            metadata = json.loads(raw_meta)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProjectError(
                "Readiness endpoint is not a Weaviate instance",
                detail={"reason": "not_weaviate"},
            ) from exc
        if not isinstance(metadata, dict) or "version" not in metadata:
            raise ProjectError(
                "Readiness endpoint is not a Weaviate instance",
                detail={"reason": "not_weaviate"},
            )
        raw_version = metadata["version"]
        version = _version_tuple(raw_version)
        if version < _MIN_VERSION or version >= _MAX_VERSION:
            raise ProjectError(
                f"Weaviate version {raw_version!r} is incompatible",
                detail={"reason": "incompatible_version", "version": raw_version},
            )
        if not ready:
            raise ProjectError(
                "Weaviate did not report ready within the installer timeout",
                detail={"reason": "not_ready", "endpoint": http_endpoint},
            )
        return VectorDbPreflightReceipt(
            http_endpoint=http_endpoint,
            grpc_endpoint=grpc_endpoint,
            server_version=str(raw_version),
        )


def _wait_for_explicit_endpoints(
    http_host: str,
    http_port: int,
    http_secure: bool,
    grpc_host: str,
    grpc_port: int,
    grpc_secure: bool,
    timeout_seconds: float,
) -> bool:
    """Reuse the canonical readiness loop with both validated endpoint ports."""

    def _adapter(host: str, port: int) -> WeaviateStoryAdapter:
        return WeaviateStoryAdapter.connect(
            host=host,
            port=port,
            http_secure=http_secure,
            grpc_host=grpc_host,
            grpc_port=grpc_port,
            grpc_secure=grpc_secure,
        )

    return wait_for_weaviate(
        host=http_host,
        port=http_port,
        timeout_seconds=timeout_seconds,
        adapter_factory=_adapter,
    )


__all__ = [
    "HttpVectorDbPreflight",
    "VectorDbPreflightPort",
    "VectorDbPreflightReceipt",
]
