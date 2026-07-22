"""Weaviate readiness entrypoint (FK-21 §21.11.4, canonical FK module path).

CLI-invokable as::

    python -m agentkit.backend.vectordb.wait_for_weaviate --timeout 10

Exit 0 -> Weaviate is ready (VectorDB search available).
Exit 1 -> Weaviate is NOT reachable within the timeout (fail-closed). The
          VectorDB is mandatory infrastructure (FK-13 §13.2 / §13.8); the
          consuming story-creation flow MUST abort, never continue without it.

Project-bound resolution (``--project-root``) is **fail-closed without
localhost defaults** (AG3-176 AC1). Only the explicitly project-less diagnose
CLI path may use documented localhost defaults.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import TYPE_CHECKING, Final

from agentkit.integration_clients.vectordb import (
    VectorDbUnavailableError,
    WeaviateStoryAdapter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: Default readiness timeout in seconds (FK-21 §21.11.4: ``--timeout 10``).
DEFAULT_TIMEOUT_SECONDS: Final[int] = 10

#: Documented defaults for the **project-less diagnose CLI path only**.
DEFAULT_HOST: Final[str] = "localhost"
DEFAULT_PORT: Final[int] = 8080

#: Seconds between readiness probes while waiting.
_POLL_INTERVAL_SECONDS: Final[float] = 0.5


class ProjectEndpointResolutionError(Exception):
    """Raised when project-bound host/port cannot be resolved fail-closed."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


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
    """Resolve Weaviate ``(host, port)`` for CLI use.

    * ``project_root is None`` — project-less diagnose path: documented
      localhost defaults apply.
    * ``project_root`` set — project-bound path: load config fail-closed;
      **no** localhost/default fallback when config is missing, invalid, or
      incomplete (AG3-176 AC1).

    Args:
        project_root: Optional project root carrying
            ``.agentkit/config/project.yaml``.

    Returns:
        The resolved ``(host, port)`` pair.

    Raises:
        ProjectEndpointResolutionError: On the project-bound path when the
            endpoint cannot be resolved without inventing defaults.
    """
    if project_root is None:
        return DEFAULT_HOST, DEFAULT_PORT

    from pathlib import Path

    from agentkit.backend.config.loader import load_project_config
    from agentkit.backend.exceptions import AgentKitError
    from agentkit.backend.vectordb.endpoint_preflight import (
        EndpointPreflightError,
        resolve_endpoint_from_project_config,
    )

    try:
        config = load_project_config(Path(project_root))
    except (AgentKitError, OSError) as exc:
        raise ProjectEndpointResolutionError(
            "configuration_invalid",
            f"cannot load project config for VectorDB endpoint at "
            f"{project_root!r}: {exc} (no localhost default on project path, "
            "AG3-176 AC1)",
        ) from exc

    try:
        endpoint = resolve_endpoint_from_project_config(config)
    except EndpointPreflightError as exc:
        raise ProjectEndpointResolutionError(exc.reason, exc.detail) from exc
    return endpoint.host, endpoint.http_port


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

    try:
        host, port = _resolve_host_port(args.project_root)
    except ProjectEndpointResolutionError as exc:
        print(
            f"Weaviate endpoint resolution failed ({exc.reason}): {exc.detail}",
            file=sys.stderr,
        )
        return 1
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
