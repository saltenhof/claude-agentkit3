"""Unit tests for the wait_for_weaviate readiness shim (AG3-068 / FK-21 §21.11.4).

The adapter factory is the injected boundary (mocks exception). The exit-code
mapping (0 ready / 1 not) and the polling loop run for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from agentkit.backend.vectordb.wait_for_weaviate import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    _resolve_host_port,
    main,
    resolve_adapter_endpoints,
    wait_for_weaviate,
)
from agentkit.integration_clients.vectordb import VectorDbUnavailableError

if TYPE_CHECKING:
    from pathlib import Path



class _ReadyAdapter:
    def is_ready(self) -> bool:
        return True

    def close(self) -> None:
        return None


class _NotReadyAdapter:
    def is_ready(self) -> bool:
        return False

    def close(self) -> None:
        return None


class _UnavailableAdapter:
    def is_ready(self) -> bool:
        raise VectorDbUnavailableError("not reachable")

    def close(self) -> None:
        return None


def test_wait_returns_true_when_ready() -> None:
    ready = wait_for_weaviate(
        host="localhost",
        port=8080,
        timeout_seconds=10,
        adapter_factory=lambda h, p: _ReadyAdapter(),  # type: ignore[arg-type, return-value]
    )
    assert ready is True


def test_wait_returns_false_on_timeout_not_ready() -> None:
    """NEGATIVE: a node that never reports ready times out to False (exit 1)."""
    clock = {"t": 0.0}

    def _monotonic() -> float:
        return clock["t"]

    def _sleep(seconds: float) -> None:
        clock["t"] += seconds

    ready = wait_for_weaviate(
        host="localhost",
        port=8080,
        timeout_seconds=2.0,
        adapter_factory=lambda h, p: _NotReadyAdapter(),  # type: ignore[arg-type, return-value]
        sleep=_sleep,
        monotonic=_monotonic,
    )
    assert ready is False


def test_wait_returns_false_when_unreachable() -> None:
    """NEGATIVE: an unreachable Weaviate (adapter raises) times out to False."""
    clock = {"t": 0.0}

    def _monotonic() -> float:
        return clock["t"]

    def _sleep(seconds: float) -> None:
        clock["t"] += seconds

    ready = wait_for_weaviate(
        host="localhost",
        port=8080,
        timeout_seconds=1.0,
        adapter_factory=lambda h, p: _UnavailableAdapter(),  # type: ignore[arg-type, return-value]
        sleep=_sleep,
        monotonic=_monotonic,
    )
    assert ready is False


def test_main_exit_zero_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    import agentkit.backend.vectordb.wait_for_weaviate as mod

    monkeypatch.setattr(mod, "wait_for_weaviate", lambda **_: True)
    assert main(["--timeout", "1", "--host", "localhost", "--port", "8080"]) == 0


def test_main_exit_one_when_not_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """NEGATIVE: exit 1 when Weaviate is not reachable within the timeout."""
    import agentkit.backend.vectordb.wait_for_weaviate as mod

    monkeypatch.setattr(mod, "wait_for_weaviate", lambda **_: False)
    assert main(["--timeout", "1", "--host", "localhost", "--port", "8080"]) == 1


def test_resolve_host_port_defaults_without_project_root() -> None:
    assert _resolve_host_port(None) == (DEFAULT_HOST, DEFAULT_PORT)


def test_resolve_host_port_consumes_vectordb_config(tmp_path: Path) -> None:
    """CONSUMES the AG3-070-owned vectordb stanza for host/port.

    PO decision D-2 removed ``vectordb.host``/``port``; host and port are now
    derived from ``weaviate_http_endpoint`` through the shared public splitter.
    Only the FIELD SOURCE changed here -- the fallback policy is AG3-176's.
    """
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True)
    data = {
        "project_key": "ak3",
        "project_name": "AK3",
        "repositories": [{"name": "backend", "path": "/tmp/backend"}],
        "story_types": ["concept"],
        "pipeline": {
            "config_version": "3.0",
            "features": {"multi_llm": False, "vectordb": True},
            "vectordb": {
                "weaviate_http_endpoint": "http://weaviate.internal:9999",
                "weaviate_grpc_endpoint": "weaviate.internal:50051",
            },
        },
    }
    (config_dir / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    assert _resolve_host_port(str(tmp_path)) == ("weaviate.internal", 9999)


def test_resolve_host_port_fails_when_project_config_missing(tmp_path: Path) -> None:
    from agentkit.backend.exceptions import ConfigError

    with pytest.raises(ConfigError):
        _resolve_host_port(str(tmp_path))


def test_resolve_host_port_fails_when_project_endpoint_absent(tmp_path: Path) -> None:
    """A project-bound probe never falls back to diagnostic localhost defaults."""
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True)
    data = {
        "project_key": "ak3",
        "project_name": "AK3",
        "repositories": [{"name": "backend", "path": "/tmp/backend"}],
        "story_types": ["concept"],
        "pipeline": {
            "config_version": "3.0",
            "features": {"multi_llm": False, "vectordb": True},
            "vectordb": {"similarity_threshold": 0.7},
        },
    }
    (config_dir / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(VectorDbUnavailableError):
        _resolve_host_port(str(tmp_path))


def _write_project_config(tmp_path: Path, vectordb: dict[str, object]) -> None:
    """Write a minimal project config carrying the given vectordb stanza."""
    config_dir = tmp_path / ".agentkit" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "project_key": "ak3",
        "project_name": "AK3",
        "repositories": [{"name": "backend", "path": "/tmp/backend"}],
        "story_types": ["concept"],
        "pipeline": {
            "config_version": "3.0",
            "features": {"multi_llm": False, "vectordb": True},
            "vectordb": vectordb,
        },
    }
    (config_dir / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_resolve_adapter_endpoints_carries_https_and_both_tls_flags(tmp_path: Path) -> None:
    """A configured HTTPS/grpcs deployment must survive the resolution intact.

    Dropping ``http_secure`` would silently downgrade a configured TLS endpoint
    to plaintext — the same class of quiet repair as a synthesised endpoint.
    """
    _write_project_config(
        tmp_path,
        {
            "weaviate_http_endpoint": "https://weaviate.acme.local:8443",
            "weaviate_grpc_endpoint": "grpcs://grpc.acme.local:50052",
        },
    )
    assert resolve_adapter_endpoints(str(tmp_path)) == {
        "host": "weaviate.acme.local",
        "port": 8443,
        "http_secure": True,
        "grpc_host": "grpc.acme.local",
        "grpc_port": 50052,
        "grpc_secure": True,
    }


def test_resolve_adapter_endpoints_keeps_a_split_deployment_split(tmp_path: Path) -> None:
    """The gRPC host must come from config, never be derived from the HTTP host."""
    _write_project_config(
        tmp_path,
        {
            "weaviate_http_endpoint": "http://http.acme.local:8080",
            "weaviate_grpc_endpoint": "grpc.acme.local:50051",
        },
    )
    resolved = resolve_adapter_endpoints(str(tmp_path))
    assert resolved["grpc_host"] == "grpc.acme.local" != resolved["host"]


def test_main_with_project_root_exits_one_when_grpc_endpoint_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both endpoints are mandatory on the project-bound path (PO decision D-2).

    This is the path the productive ``create-userstory-core`` 4.1.0 bundle uses,
    so a missing gRPC endpoint must fail closed here — and as a controlled exit
    code, not an uncaught traceback at a CLI boundary.
    """
    _write_project_config(tmp_path, {"weaviate_http_endpoint": "http://weaviate.acme.local:8080"})
    assert main(["--timeout", "1", "--project-root", str(tmp_path)]) == 1
    assert "gRPC endpoint" in capsys.readouterr().err
