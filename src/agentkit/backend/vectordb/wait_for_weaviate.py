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
    only CONSUMES it. When no project config is resolvable (e.g. a bare
    readiness probe outside a project), the documented localhost defaults apply.

    **AG3-175 (PO decision D-2) changed only the FIELD SOURCE**: ``vectordb.host``
    / ``vectordb.port`` are removed, so host and port are derived from
    ``weaviate_http_endpoint`` through the single public splitter
    (``vectordb.endpoints``). The FALLBACK POLICY is deliberately unchanged.

    **Seam for AG3-176:** that story's Scope 1 owns EXCLUDING the
    localhost/default fallback for the project-bound install path while KEEPING
    documented defaults for the project-less diagnostic CLI path -- it names this
    function explicitly. All four fallback branches below are therefore left
    exactly as they were; AG3-175 must not pre-empt that decision.

    Args:
        project_root: Optional project root carrying
            ``.agentkit/config/project.yaml``.

    Returns:
        The resolved ``(host, port)`` pair.
    """
    if project_root is None:
        return DEFAULT_HOST, DEFAULT_PORT
    from pathlib import Path

    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.exceptions import AgentKitError

    try:
        config = load_project_config(Path(project_root))
    except (AgentKitError, OSError):
        # No resolvable project config (missing / invalid project.yaml) => fall
        # back to the documented localhost defaults. The readiness probe itself
        # still fails closed if Weaviate is genuinely unreachable.
        return DEFAULT_HOST, DEFAULT_PORT
    vectordb = config.pipeline.vectordb
    if vectordb is None or not vectordb.weaviate_http_endpoint:
        return DEFAULT_HOST, DEFAULT_PORT
    try:
        host, port, _secure = split_http_endpoint(vectordb.weaviate_http_endpoint)
    except VectorDbUnavailableError:
        # A malformed endpoint keeps the documented default for THIS path only;
        # the config model already rejects malformed endpoints at load time, so
        # this branch is defence in depth for a hand-edited file. Tightening it is
        # AG3-176's call, not this story's (see the seam note above).
        return DEFAULT_HOST, DEFAULT_PORT
    return host, port


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

    host, port = _resolve_host_port(args.project_root)
    if args.host is not None:
        host = args.host
    if args.port is not None:
        port = args.port

    ready = wait_for_weaviate(host=host, port=port, timeout_seconds=float(args.timeout))
    if ready:
        print(f"Weaviate ready at {host}:{port}")
        return 0
    print(
        f"Weaviate NOT reachable at {host}:{port} within {args.timeout}s "
        "(fail-closed; the VectorDB is mandatory, FK-13 §13.2).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
