"""Project-bound VectorDB endpoint preflight (AG3-176 AC1, FK-13 §13.8).

The installer **does not** install or start a database. It only validates that
the configured Weaviate endpoint is reachable, ready, and version-compatible
— fail-closed, with **no localhost / default fallback** on the project path.

Named reasons (ARCH-55) are stable for tests and installer ``CheckpointResult``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.config.models import ProjectConfig, VectorDbConfig

#: Stable machine-readable preflight reasons (AG3-176 AC1).
REASON_VECTORDB_BLOCK_MISSING: Final = "vectordb_block_missing"
REASON_VECTORDB_BLOCK_MALFORMED: Final = "vectordb_block_malformed"
REASON_VECTORDB_HOST_INVALID: Final = "vectordb_host_invalid"
REASON_VECTORDB_PORT_INVALID: Final = "vectordb_port_invalid"
REASON_VECTORDB_GRPC_PORT_INVALID: Final = "vectordb_grpc_port_invalid"
REASON_VECTORDB_NOT_WEAVIATE: Final = "vectordb_not_weaviate"
REASON_VECTORDB_NOT_READY: Final = "vectordb_not_ready"
REASON_VECTORDB_VERSION_INCOMPATIBLE: Final = "vectordb_version_incompatible"
REASON_VECTORDB_UNREACHABLE: Final = "vectordb_unreachable"

#: Minimum supported Weaviate major version (FK-13 / FK-21 preflight).
MIN_WEAVIATE_MAJOR: Final[int] = 1

_SEMVER_HEAD = re.compile(r"^(\d+)")


class EndpointPreflightError(Exception):
    """Named fail-closed preflight failure (no partial installer effect)."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class EndpointSpec:
    """Validated Weaviate endpoint from project config (no defaults)."""

    host: str
    http_port: int
    grpc_port: int


@dataclass(frozen=True)
class PreflightResult:
    """Successful preflight outcome."""

    endpoint: EndpointSpec
    weaviate_version: str
    ready: bool = True


def resolve_endpoint_from_vectordb_config(vectordb: object | None) -> EndpointSpec:
    """Resolve host/ports from a typed or raw VectorDB config — fail-closed.

    Args:
        vectordb: ``VectorDbConfig`` instance or a raw mapping, or ``None``.

    Raises:
        EndpointPreflightError: Named reason for missing/malformed/invalid fields.
    """
    if vectordb is None:
        raise EndpointPreflightError(
            REASON_VECTORDB_BLOCK_MISSING,
            "pipeline.vectordb is required for project-bound VectorDB preflight "
            "(no default endpoint; installer does not start a database, AG3-176 AC1).",
        )

    host, http_port, grpc_port = _extract_fields(vectordb)

    if not isinstance(host, str) or not host.strip():
        raise EndpointPreflightError(
            REASON_VECTORDB_HOST_INVALID,
            f"vectordb.host must be a non-empty string; got {host!r}.",
        )
    host_s = host.strip()
    if host_s.lower() in {"", "0.0.0.0"} or any(c.isspace() for c in host_s):
        raise EndpointPreflightError(
            REASON_VECTORDB_HOST_INVALID,
            f"vectordb.host is invalid: {host_s!r}.",
        )

    if not _is_positive_port(http_port):
        raise EndpointPreflightError(
            REASON_VECTORDB_PORT_INVALID,
            f"vectordb.port must be a positive int 1..65535; got {http_port!r}.",
        )
    if not _is_positive_port(grpc_port):
        raise EndpointPreflightError(
            REASON_VECTORDB_GRPC_PORT_INVALID,
            f"vectordb.grpc_port must be a positive int 1..65535; got {grpc_port!r}.",
        )

    assert isinstance(http_port, int) and isinstance(grpc_port, int)
    return EndpointSpec(host=host_s, http_port=http_port, grpc_port=grpc_port)


def resolve_endpoint_from_project_config(config: ProjectConfig) -> EndpointSpec:
    """Resolve endpoint from loaded :class:`ProjectConfig` (project-bound path)."""
    pipeline = getattr(config, "pipeline", None)
    vectordb = getattr(pipeline, "vectordb", None) if pipeline is not None else None
    return resolve_endpoint_from_vectordb_config(vectordb)


def run_endpoint_preflight(
    endpoint: EndpointSpec,
    *,
    timeout_seconds: float = 10.0,
    ready_probe: Callable[[str, int], bool] | None = None,
    meta_fetcher: Callable[[str, int, float], dict[str, object]] | None = None,
) -> PreflightResult:
    """Probe the configured endpoint: Weaviate meta + ready (fail-closed).

    Does **not** start containers or compose. External ports only.

    Args:
        endpoint: Validated host/ports.
        timeout_seconds: HTTP timeout for meta/ready probes.
        ready_probe: Optional inject for tests (returns ready bool).
        meta_fetcher: Optional inject for tests (returns meta JSON object).

    Raises:
        EndpointPreflightError: Named hard failure (not Weaviate / not ready /
            version / unreachable).
    """
    fetch = meta_fetcher or _fetch_weaviate_meta
    try:
        meta = fetch(endpoint.host, endpoint.http_port, timeout_seconds)
    except EndpointPreflightError:
        raise
    except Exception as exc:  # noqa: BLE001 -- map transport to named reason
        raise EndpointPreflightError(
            REASON_VECTORDB_UNREACHABLE,
            f"Weaviate meta endpoint unreachable at {endpoint.host}:"
            f"{endpoint.http_port}: {exc}",
        ) from exc

    version = _require_weaviate_meta(meta, endpoint)
    _assert_version_compatible(version)

    if ready_probe is not None:
        ready = bool(ready_probe(endpoint.host, endpoint.http_port))
    else:
        ready = _default_ready_probe(endpoint.host, endpoint.http_port, timeout_seconds)

    if not ready:
        raise EndpointPreflightError(
            REASON_VECTORDB_NOT_READY,
            f"Weaviate at {endpoint.host}:{endpoint.http_port} is not ready "
            f"(fail-closed, FK-13 §13.8).",
        )
    return PreflightResult(endpoint=endpoint, weaviate_version=version, ready=True)


def preflight_project_config(
    config: ProjectConfig,
    *,
    timeout_seconds: float = 10.0,
    ready_probe: Callable[[str, int], bool] | None = None,
    meta_fetcher: Callable[[str, int, float], dict[str, object]] | None = None,
) -> PreflightResult:
    """Full project-bound preflight: resolve endpoint then probe."""
    endpoint = resolve_endpoint_from_project_config(config)
    return run_endpoint_preflight(
        endpoint,
        timeout_seconds=timeout_seconds,
        ready_probe=ready_probe,
        meta_fetcher=meta_fetcher,
    )


def _extract_fields(vectordb: object) -> tuple[object, object, object]:
    if isinstance(vectordb, dict):
        # Malformed when not a proper mapping of expected shape later.
        host = vectordb.get("host")
        http_port = vectordb.get("port", vectordb.get("http_port"))
        grpc_port = vectordb.get("grpc_port")
        return host, http_port, grpc_port
    # Typed VectorDbConfig (or duck-type).
    host = getattr(vectordb, "host", None)
    http_port = getattr(vectordb, "port", None)
    if http_port is None:
        http_port = getattr(vectordb, "http_port", None)
    grpc_port = getattr(vectordb, "grpc_port", None)
    # Detect completely wrong type as malformed.
    if not hasattr(vectordb, "host") and not isinstance(vectordb, dict):
        raise EndpointPreflightError(
            REASON_VECTORDB_BLOCK_MALFORMED,
            f"pipeline.vectordb must be a mapping/object; got {type(vectordb).__name__}.",
        )
    return host, http_port, grpc_port


def _is_positive_port(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 1 <= value <= 65535


def _fetch_weaviate_meta(host: str, port: int, timeout: float) -> dict[str, object]:
    url = f"http://{host}:{port}/v1/meta"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 -- operator endpoint
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise EndpointPreflightError(
            REASON_VECTORDB_NOT_WEAVIATE,
            f"HTTP {exc.code} from {url}; not a ready Weaviate meta endpoint.",
        ) from exc
    except urllib.error.URLError as exc:
        raise EndpointPreflightError(
            REASON_VECTORDB_UNREACHABLE,
            f"cannot reach {url}: {exc.reason}",
        ) from exc
    except TimeoutError as exc:
        raise EndpointPreflightError(
            REASON_VECTORDB_UNREACHABLE,
            f"timeout reaching {url}",
        ) from exc

    if "json" not in content_type.lower() and content_type:
        # Still try JSON body; many servers omit precise content-type.
        pass
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EndpointPreflightError(
            REASON_VECTORDB_NOT_WEAVIATE,
            f"response from {url} is not JSON Weaviate meta: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise EndpointPreflightError(
            REASON_VECTORDB_NOT_WEAVIATE,
            f"response from {url} is not a JSON object (not Weaviate meta).",
        )
    return data


def _require_weaviate_meta(meta: dict[str, object], endpoint: EndpointSpec) -> str:
    version = meta.get("version")
    # Weaviate meta always carries version; hostname optional.
    if not isinstance(version, str) or not version.strip():
        raise EndpointPreflightError(
            REASON_VECTORDB_NOT_WEAVIATE,
            f"reachable service at {endpoint.host}:{endpoint.http_port} did not "
            "return Weaviate meta.version (not Weaviate or incompatible).",
        )
    return version.strip()


def _assert_version_compatible(version: str) -> None:
    match = _SEMVER_HEAD.match(version.lstrip("vV"))
    if match is None:
        raise EndpointPreflightError(
            REASON_VECTORDB_VERSION_INCOMPATIBLE,
            f"cannot parse Weaviate version {version!r} (fail-closed).",
        )
    major = int(match.group(1))
    if major < MIN_WEAVIATE_MAJOR:
        raise EndpointPreflightError(
            REASON_VECTORDB_VERSION_INCOMPATIBLE,
            f"Weaviate version {version!r} is below minimum major "
            f"{MIN_WEAVIATE_MAJOR} (fail-closed).",
        )


def _default_ready_probe(host: str, port: int, timeout: float) -> bool:
    from agentkit.backend.vectordb.wait_for_weaviate import wait_for_weaviate

    return wait_for_weaviate(host=host, port=port, timeout_seconds=timeout)


def endpoint_from_typed(vectordb: VectorDbConfig) -> EndpointSpec:
    """Convenience for typed config (tests / callers with validated model)."""
    return resolve_endpoint_from_vectordb_config(vectordb)


__all__ = [
    "MIN_WEAVIATE_MAJOR",
    "EndpointPreflightError",
    "EndpointSpec",
    "PreflightResult",
    "REASON_VECTORDB_BLOCK_MALFORMED",
    "REASON_VECTORDB_BLOCK_MISSING",
    "REASON_VECTORDB_GRPC_PORT_INVALID",
    "REASON_VECTORDB_HOST_INVALID",
    "REASON_VECTORDB_NOT_READY",
    "REASON_VECTORDB_NOT_WEAVIATE",
    "REASON_VECTORDB_PORT_INVALID",
    "REASON_VECTORDB_UNREACHABLE",
    "REASON_VECTORDB_VERSION_INCOMPATIBLE",
    "endpoint_from_typed",
    "preflight_project_config",
    "resolve_endpoint_from_project_config",
    "resolve_endpoint_from_vectordb_config",
    "run_endpoint_preflight",
]
