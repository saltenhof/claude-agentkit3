"""Weaviate readiness entrypoint (FK-21 §21.11.4, canonical FK module path).

CLI-invokable as::

    python -m agentkit.backend.vectordb.wait_for_weaviate --timeout 10

Exit 0 -> Weaviate is ready (VectorDB search available).
Exit 1 -> Weaviate is NOT reachable within the timeout (fail-closed). The
          VectorDB is mandatory infrastructure (FK-13 §13.2 / §13.8); the
          consuming story-creation flow MUST abort, never continue without it.

This is a thin app-layer shim: the "ready / not ready" decision lives here, not
in ``integrations/``. It consumes :class:`WeaviateStoryAdapter` and a factory
seam so the success and failure paths stay testable with a double at the adapter
boundary (mocks exception).
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import TYPE_CHECKING, Final

from agentkit.backend.vectordb.endpoints import split_http_endpoint
from agentkit.integration_clients.vectordb import (
    VectorDbUnavailableError,
    WeaviateStoryAdapter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: Default readiness timeout in seconds (FK-21 §21.11.4: ``--timeout 10``).
DEFAULT_TIMEOUT_SECONDS: Final[int] = 10

#: Default Weaviate host for the PROJECT-LESS diagnostic CLI path.
DEFAULT_HOST: Final[str] = "localhost"

#: Default Weaviate port for the PROJECT-LESS diagnostic CLI path.
DEFAULT_PORT: Final[int] = 8080

#: Seconds between readiness probes while waiting.
_POLL_INTERVAL_SECONDS: Final[float] = 0.5


def _default_adapter_factory(host: str, port: int) -> WeaviateStoryAdapter:
    """Build a real Weaviate adapter (fail-closed when the dep/server is absent)."""
    return WeaviateStoryAdapter.connect(host=host, port=port)


def wait_for_weaviate(
    *,
    host: str,
    port: int,
    timeout_seconds: float,
    adapter_factory: Callable[[str, int], WeaviateStoryAdapter] = _default_adapter_factory,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll Weaviate readiness until ready or the timeout elapses.

    Args:
        host: Weaviate hostname.
        port: Weaviate HTTP port.
        timeout_seconds: Maximum time to wait for readiness.
        adapter_factory: Builds a connected adapter; injected for testing.
        sleep: Sleep function; injected for testing.
        monotonic: Monotonic clock; injected for testing.

    Returns:
        ``True`` once Weaviate reports ready, ``False`` if the timeout elapses
        without a ready answer (fail-closed -- the caller exits 1).
    """
    deadline = monotonic() + max(0.0, timeout_seconds)
    while True:
        adapter: WeaviateStoryAdapter | None = None
        try:
            adapter = adapter_factory(host, port)
            if adapter.is_ready():
                return True
        except VectorDbUnavailableError:
            # Not reachable yet (dependency/connection/probe fault). Keep
            # polling until the deadline; this is the expected transient path.
            pass
        finally:
            if adapter is not None:
                adapter.close()
        if monotonic() >= deadline:
            return False
        sleep(_POLL_INTERVAL_SECONDS)


def _resolve_host_port(project_root: str | None) -> tuple[str, int]:
    """Resolve Weaviate ``(host, port)`` from the consumed ``vectordb`` config.

    The ``vectordb`` config stanza is owned exclusively by AG3-070; this shim
    only CONSUMES it. Host and port are derived from ``weaviate_http_endpoint``
    through the single public splitter (``vectordb.endpoints``, PO decision D-2).

    **AG3-176 resolved the fallback seam AG3-175 left open**: the default only
    applies to the explicitly project-LESS diagnostic probe. With a project
    root, a missing endpoint is a fail-closed error — there is no defaulting
    branch left on the project-bound path. Productive project paths do not use
    this function at all; they use :func:`resolve_adapter_endpoints`, which
    additionally requires the gRPC endpoint and both TLS flags.

    Args:
        project_root: Project root carrying ``.agentkit/config/project.yaml``,
            or ``None`` for the project-less diagnostic probe.

    Returns:
        The resolved ``(host, port)`` pair.

    Raises:
        VectorDbUnavailableError: When a project root is given but its config
            declares no HTTP endpoint.
    """
    if project_root is None:
        return DEFAULT_HOST, DEFAULT_PORT
    from pathlib import Path

    from agentkit.backend.config.loader import load_project_config

    config = load_project_config(Path(project_root))
    vectordb = config.pipeline.vectordb
    if vectordb is None or vectordb.weaviate_http_endpoint is None:
        raise VectorDbUnavailableError("Project configuration has no explicit Weaviate HTTP endpoint")
    host, port, _secure = split_http_endpoint(vectordb.weaviate_http_endpoint)
    return host, port


def resolve_adapter_endpoints(project_root: str) -> dict[str, object]:
    """Resolve the COMPLETE ``WeaviateStoryAdapter.connect`` keyword set.

    Both endpoints — including both TLS flags — come from configuration through
    the single public splitters. The adapter can *derive* a gRPC host from the
    HTTP host, but that derivation is a convenience for single-host deployments;
    relying on it here would silently ignore a configured split deployment and
    re-introduce exactly the synthesised endpoint PO decision D-2 removed.
    Dropping ``http_secure`` would do the same to a configured HTTPS endpoint.

    The parameter is deliberately NOT optional: this is the project-bound path,
    and it is the caller boundary that keeps the diagnostic localhost defaults
    of :func:`_resolve_host_port` out of productive project paths.

    Args:
        project_root: Project root carrying ``.agentkit/config/project.yaml``.

    Returns:
        The keyword arguments for ``WeaviateStoryAdapter.connect``.

    Raises:
        VectorDbUnavailableError: When the project config declares no HTTP or no
            gRPC endpoint.
    """
    from pathlib import Path

    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.vectordb.endpoints import split_grpc_endpoint

    vectordb = load_project_config(Path(project_root)).pipeline.vectordb
    if vectordb is None or not vectordb.weaviate_http_endpoint:
        raise VectorDbUnavailableError("Project configuration has no explicit Weaviate HTTP endpoint")
    if not vectordb.weaviate_grpc_endpoint:
        raise VectorDbUnavailableError(
            "Project configuration has no explicit Weaviate gRPC endpoint; both "
            "endpoints are mandatory configuration (PO decision D-2)."
        )
    host, port, http_secure = split_http_endpoint(vectordb.weaviate_http_endpoint)
    grpc_host, grpc_port, grpc_secure = split_grpc_endpoint(vectordb.weaviate_grpc_endpoint)
    return {
        "host": host,
        "port": port,
        "http_secure": http_secure,
        "grpc_host": grpc_host,
        "grpc_port": grpc_port,
        "grpc_secure": grpc_secure,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the readiness probe.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` when Weaviate is ready, ``1`` when it is not reachable within the
        timeout (fail-closed).
    """
    parser = argparse.ArgumentParser(
        prog="python -m agentkit.backend.vectordb.wait_for_weaviate",
        description="Wait for the Weaviate story knowledge base to become ready.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Maximum seconds to wait for readiness (default: 10).",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root carrying .agentkit/config/project.yaml for host/port.",
    )
    parser.add_argument("--host", default=None, help="Override Weaviate host.")
    parser.add_argument("--port", type=int, default=None, help="Override Weaviate port.")
    args = parser.parse_args(argv)

    # Project-bound: both endpoints come from configuration and a missing gRPC
    # endpoint fails closed here rather than being synthesised by the adapter.
    # Project-less: the documented diagnostic defaults apply.
    connect_kwargs: dict[str, object]
    if args.project_root is None:
        connect_kwargs = {"host": DEFAULT_HOST, "port": DEFAULT_PORT}
    else:
        try:
            connect_kwargs = resolve_adapter_endpoints(args.project_root)
        except VectorDbUnavailableError as exc:
            # Fail-closed is right; an uncaught traceback at a CLI boundary is not.
            print(f"Weaviate endpoints are not resolvable: {exc}", file=sys.stderr)
            return 1
    host = str(args.host if args.host is not None else connect_kwargs["host"])
    port = int(args.port if args.port is not None else connect_kwargs["port"])  # type: ignore[arg-type]

    def probe_factory(probe_host: str, probe_port: int) -> WeaviateStoryAdapter:
        return WeaviateStoryAdapter.connect(**{**connect_kwargs, "host": probe_host, "port": probe_port})  # type: ignore[arg-type]

    ready = wait_for_weaviate(
        host=host,
        port=port,
        timeout_seconds=float(args.timeout),
        adapter_factory=probe_factory,
    )
    if ready:
        print(f"Weaviate ready at {host}:{port}")
        return 0
    print(
        f"Weaviate NOT reachable at {host}:{port} within {args.timeout}s (fail-closed; the VectorDB is mandatory, FK-13 §13.2).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
