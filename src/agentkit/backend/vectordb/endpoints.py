"""Public seam for splitting the configured Weaviate endpoints (AG3-175, D-2).

``pipeline.vectordb.weaviate_http_endpoint`` / ``weaviate_grpc_endpoint`` are the
ONLY way to say where Weaviate is (PO decision D-2 removed the former
``vectordb.host`` / ``vectordb.port``, which were a second operative truth for the
same fact). Every consumer that needs a host/port pair therefore has to split an
endpoint, and that must happen in exactly ONE place.

The two functions here carry the implementation that ``vectordb.engine`` has used
since AG3-174; ``engine`` re-exports them under its historical private names, so
there is one implementation and no chance of drift between the MCP runtime, the
story-creation adapter and the readiness probe. The accepted forms are the
ratified ones and are pinned by ``config.models.VectorDbConfig``:

- HTTP: ``http(s)://host:port`` -- path, query, fragment and userinfo are not
  part of the contract (the config validator rejects them, because this splitter
  would silently drop them).
- gRPC: ``host:port``, optionally ``grpc://`` or ``grpcs://``; ``grpcs`` selects a
  TLS channel. Any other scheme is rejected by the config validator, because this
  splitter would otherwise fold it into the host.

This module deliberately imports only stdlib plus the shared error type, so a
lightweight consumer (the readiness probe, the story-creation factory) can use it
without pulling in the Weaviate engine.
"""

from __future__ import annotations

import urllib.parse

from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

#: gRPC scheme prefixes the contract accepts; ``grpcs`` selects TLS.
_GRPC_SECURE_PREFIX = "grpcs://"
_GRPC_PLAIN_PREFIX = "grpc://"


def split_http_endpoint(endpoint: str) -> tuple[str, int, bool]:
    """Split ``http(s)://host:port`` into ``(host, port, secure)``.

    Args:
        endpoint: The configured HTTP endpoint.

    Returns:
        ``(host, port, secure)`` where ``secure`` is ``True`` for ``https``.

    Raises:
        VectorDbUnavailableError: If the scheme is not ``http``/``https`` or host
            or port are missing (fail-closed, PO decision D2 -- never a guessed
            default).
    """
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in ("http", "https"):
        raise VectorDbUnavailableError(
            f"WEAVIATE_HTTP_ENDPOINT {endpoint!r} must be http(s)://host:port "
            "(fail-closed, D2)."
        )
    if not parsed.hostname or parsed.port is None:
        raise VectorDbUnavailableError(
            f"WEAVIATE_HTTP_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    return parsed.hostname, parsed.port, parsed.scheme == "https"


def split_grpc_endpoint(endpoint: str) -> tuple[str, int, bool]:
    """Split a gRPC endpoint into ``(host, port, secure)`` fail-closed.

    Accepts ``host:port`` as well as an explicit ``grpc://``/``grpcs://`` scheme;
    ``grpcs`` selects a TLS gRPC channel.

    Args:
        endpoint: The configured gRPC endpoint.

    Returns:
        ``(host, port, secure)``.

    Raises:
        VectorDbUnavailableError: If the value is not ``host:port`` or the port is
            not an integer.
    """
    candidate = endpoint
    secure = False
    if candidate.startswith(_GRPC_SECURE_PREFIX):
        secure = True
        candidate = candidate.removeprefix(_GRPC_SECURE_PREFIX)
    elif candidate.startswith(_GRPC_PLAIN_PREFIX):
        candidate = candidate.removeprefix(_GRPC_PLAIN_PREFIX)
    if ":" not in candidate:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    host, _, port = candidate.rpartition(":")
    if not host:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    try:
        return host, int(port), secure
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} has non-integer port (fail-closed, D2)."
        ) from exc


__all__ = ["split_grpc_endpoint", "split_http_endpoint"]
