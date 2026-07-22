"""AG3-176 AC1: endpoint preflight fail-closed, no default fallback."""

from __future__ import annotations

import pytest

from agentkit.backend.vectordb.endpoint_preflight import (
    REASON_VECTORDB_BLOCK_MISSING,
    REASON_VECTORDB_HOST_INVALID,
    REASON_VECTORDB_NOT_READY,
    REASON_VECTORDB_NOT_WEAVIATE,
    REASON_VECTORDB_PORT_INVALID,
    REASON_VECTORDB_VERSION_INCOMPATIBLE,
    EndpointPreflightError,
    EndpointSpec,
    resolve_endpoint_from_vectordb_config,
    run_endpoint_preflight,
)


def test_missing_block_named_error() -> None:
    with pytest.raises(EndpointPreflightError) as ei:
        resolve_endpoint_from_vectordb_config(None)
    assert ei.value.reason == REASON_VECTORDB_BLOCK_MISSING


def test_invalid_host_named_error() -> None:
    with pytest.raises(EndpointPreflightError) as ei:
        resolve_endpoint_from_vectordb_config(
            {"host": "", "port": 8080, "grpc_port": 50051}
        )
    assert ei.value.reason == REASON_VECTORDB_HOST_INVALID


def test_invalid_port_named_error() -> None:
    with pytest.raises(EndpointPreflightError) as ei:
        resolve_endpoint_from_vectordb_config(
            {"host": "weaviate.local", "port": 0, "grpc_port": 50051}
        )
    assert ei.value.reason == REASON_VECTORDB_PORT_INVALID


def test_not_weaviate_service_named_error() -> None:
    endpoint = EndpointSpec(host="svc.local", http_port=9, grpc_port=10)

    def _meta(host: str, port: int, timeout: float) -> dict[str, object]:
        del host, port, timeout
        return {"hostname": "nginx"}  # no version

    with pytest.raises(EndpointPreflightError) as ei:
        run_endpoint_preflight(
            endpoint,
            meta_fetcher=_meta,
            ready_probe=lambda h, p: True,
        )
    assert ei.value.reason == REASON_VECTORDB_NOT_WEAVIATE


def test_not_ready_named_error() -> None:
    endpoint = EndpointSpec(host="weaviate.local", http_port=8080, grpc_port=50051)

    def _meta(host: str, port: int, timeout: float) -> dict[str, object]:
        del host, port, timeout
        return {"version": "1.24.0"}

    with pytest.raises(EndpointPreflightError) as ei:
        run_endpoint_preflight(
            endpoint,
            meta_fetcher=_meta,
            ready_probe=lambda h, p: False,
        )
    assert ei.value.reason == REASON_VECTORDB_NOT_READY


def test_incompatible_version_named_error() -> None:
    endpoint = EndpointSpec(host="weaviate.local", http_port=8080, grpc_port=50051)

    def _meta(host: str, port: int, timeout: float) -> dict[str, object]:
        del host, port, timeout
        return {"version": "0.9.0"}

    with pytest.raises(EndpointPreflightError) as ei:
        run_endpoint_preflight(
            endpoint,
            meta_fetcher=_meta,
            ready_probe=lambda h, p: True,
        )
    assert ei.value.reason == REASON_VECTORDB_VERSION_INCOMPATIBLE


def test_ready_success() -> None:
    endpoint = EndpointSpec(host="weaviate.local", http_port=8080, grpc_port=50051)

    def _meta(host: str, port: int, timeout: float) -> dict[str, object]:
        del host, port, timeout
        return {"version": "1.24.1"}

    result = run_endpoint_preflight(
        endpoint,
        meta_fetcher=_meta,
        ready_probe=lambda h, p: True,
    )
    assert result.ready is True
    assert result.weaviate_version == "1.24.1"
