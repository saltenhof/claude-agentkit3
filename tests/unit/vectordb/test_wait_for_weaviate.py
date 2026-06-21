"""Unit tests for the wait_for_weaviate readiness shim (AG3-068 / FK-21 §21.11.4).

The adapter factory is the injected boundary (mocks exception). The exit-code
mapping (0 ready / 1 not) and the polling loop run for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from agentkit.backend.vectordb.wait_for_weaviate import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    _resolve_host_port,
    main,
    wait_for_weaviate,
)
from agentkit.integration_clients.vectordb import VectorDbUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
    """CONSUMES the AG3-070-owned vectordb stanza for host/port."""
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
            "vectordb": {"host": "weaviate.internal", "port": 9999},
        },
    }
    (config_dir / "project.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    assert _resolve_host_port(str(tmp_path)) == ("weaviate.internal", 9999)


def test_resolve_host_port_falls_back_when_config_missing(tmp_path: Path) -> None:
    assert _resolve_host_port(str(tmp_path)) == (DEFAULT_HOST, DEFAULT_PORT)
