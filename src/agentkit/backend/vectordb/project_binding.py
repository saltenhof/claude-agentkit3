"""Minimal project binding for the FK-13 retrieval engine (Review 174-P0-4).

A typed, authoritative project identity for the vectordb ingest/MCP paths:

- ``project_root`` is the authoritative root; every write path must be contained
  inside it (no escape via ``..`` / absolute paths / symlinks pointing out).
- ``project_id`` is the multi-tenant discriminator (FK-13 §13.3.1) read from the
  project configuration contract.
- ``cwd`` is the project-local working / containment boundary.
- ``endpoint`` (Weaviate HTTP/gRPC) is a configuration VALUE, never a guessed
  default.

There is NO global identity registry, no registry-CAS, no localhost default.
The binding is constructed explicitly and validated fail-closed; an unbound or
ambiguous binding is an ERROR, not a best-effort guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class ProjectBindingError(ValueError):
    """Raised when a project binding is missing, ambiguous or unsafe."""


@dataclass(frozen=True)
class ProjectBinding:
    """Authoritative project identity for the retrieval engine.

    Attributes:
        project_id: Non-empty multi-tenant discriminator (FK-13 §13.3.1).
        project_root: Authoritative filesystem root; all write paths must be
            contained inside it.
        concepts_dir: Configured concept corpus root (FK-13 §13.9: "konfiguriertes
            concepts_dir ist massgeblich").
        stories_dir: Story corpus root (``stories/*/story.md`` etc.).
        weaviate_http_endpoint: Weaviate HTTP endpoint URL (config value, no default).
        weaviate_grpc_endpoint: Weaviate gRPC endpoint (host:port). Mandatory,
            exactly like the HTTP endpoint: FK-03 §93 lists it as "kein Default
            (Pflicht bei MCP-Registrierung)", and a binding that may silently
            carry an empty gRPC endpoint is the same inherited leniency the
            HTTP endpoint already rejects.
    """

    project_id: str
    project_root: Path
    concepts_dir: Path
    stories_dir: Path
    weaviate_http_endpoint: str
    weaviate_grpc_endpoint: str

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ProjectBindingError(
                "project_id is missing/empty; the binding is authoritative "
                "(no default, fail-closed)."
            )
        if not isinstance(self.project_root, Path):
            raise ProjectBindingError("project_root must be a Path (typed binding).")
        if not isinstance(self.weaviate_http_endpoint, str) or not self.weaviate_http_endpoint.strip():
            raise ProjectBindingError(
                "weaviate_http_endpoint is missing/empty; the endpoint is a "
                "configuration value (no localhost default, fail-closed)."
            )
        # The endpoint must never be a synthesised localhost default.
        ep = self.weaviate_http_endpoint.strip()
        if ep in {"http://localhost:8080", "http://127.0.0.1:8080"}:
            raise ProjectBindingError(
                f"weaviate_http_endpoint {ep!r} is a forbidden localhost default; "
                "the endpoint must come from explicit configuration."
            )
        if not isinstance(self.weaviate_grpc_endpoint, str) or not self.weaviate_grpc_endpoint.strip():
            raise ProjectBindingError(
                "weaviate_grpc_endpoint is missing/empty; both endpoints are "
                "configuration values (FK-03 §93: no default, fail-closed)."
            )

    def resolve_within_root(self, candidate: Path) -> Path:
        """Resolve ``candidate`` and prove it is contained under project_root.

        Raises:
            ProjectBindingError: If the resolved path escapes ``project_root``
                (path traversal / absolute escape).
        """
        root = self.project_root.resolve()
        resolved = candidate if candidate.is_absolute() else (self.project_root / candidate)
        resolved = resolved.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProjectBindingError(
                f"path {candidate} resolves outside project_root {self.project_root} "
                "(containment violation, fail-closed)."
            ) from exc
        return resolved

    def assert_writable_within_root(self, paths: Sequence[Path]) -> None:
        """Assert every path in ``paths`` is contained under project_root."""
        for path in paths:
            self.resolve_within_root(path)


#: Environment key carrying the bound project id (FK-13 §13.4.3 ``PROJECT_ID``).
PROJECT_ID_ENV_KEY = "PROJECT_ID"


def resolve_authoritative_project_id(
    *,
    project_root: str | None,
    supplied: str | None,
    env: Mapping[str, str],
    config_project_id: str | None = None,
) -> str:
    """Resolve the AUTHORITATIVE project id for a local operation (D2, N06).

    The authority is the project configuration's ``project_prefix`` (FK-13
    §13.4.3 registers ``PROJECT_ID`` from exactly that value); when no project
    configuration is resolvable, the ``PROJECT_ID`` environment value is the
    authority. A caller-supplied value (e.g. a CLI ``--project-id``) is NOT a
    source of truth: it is only accepted when it MATCHES the authority.

    Args:
        project_root: Project root carrying ``.agentkit/config/project.yaml``;
            ``None`` falls back to upward discovery from the current directory.
        supplied: The caller-supplied project id (may be ``None``/absent).
        env: The process environment.
        config_project_id: The configuration authority when the CALLER already
            holds it, replacing the on-disk lookup. Added for the installer
            (AG3-175): CP 10 consumes the ``project.yaml`` that CP 5 produced, and
            in ``dry_run``/``verify`` that file is not on disk yet — treating the
            authority as unavailable there would mean pretending not to know a
            value we are about to write. This is NOT a second authority: the
            divergence check against ``PROJECT_ID`` from the environment and the
            precedence rule are unchanged, and there is still exactly one
            implementation of them.

    Returns:
        The authoritative project id.

    Raises:
        ProjectBindingError: When no authority can be derived (fail-closed: no
            empty default), when two authorities diverge, or when ``supplied``
            diverges from the authority (never cross-project).
    """
    config_id = (
        config_project_id.strip()
        if config_project_id is not None
        else _project_id_from_config(project_root)
    )
    env_raw = env.get(PROJECT_ID_ENV_KEY)
    env_id = env_raw.strip() if isinstance(env_raw, str) else ""
    if config_id and env_id and config_id != env_id:
        raise ProjectBindingError(
            f"{PROJECT_ID_ENV_KEY}={env_id!r} diverges from the project "
            f"configuration's project_prefix {config_id!r}; fail-closed (D2)."
        )
    authoritative = config_id or env_id
    if not authoritative:
        raise ProjectBindingError(
            "no authoritative project id: neither the project configuration "
            f"(project_prefix) nor {PROJECT_ID_ENV_KEY} is available. The project "
            "id is never defaulted or taken from a caller argument (D2, fail-closed)."
        )
    if supplied is not None and supplied.strip() and supplied.strip() != authoritative:
        raise ProjectBindingError(
            f"supplied project id {supplied.strip()!r} diverges from the "
            f"authoritative {authoritative!r}; cross-project access is rejected (D2)."
        )
    return authoritative


def _project_id_from_config(project_root: str | None) -> str:
    """Return the project configuration's ``project_prefix``, or ``""`` if ABSENT.

    Absence and invalidity are strictly separated (N22/D2): only a genuinely
    missing project configuration (no discoverable project root, or no
    ``project.yaml``) yields ``""`` so the env binding can be the authority. An
    EXISTING but malformed / schema-invalid / unreadable configuration is a hard
    :class:`ProjectBindingError` -- silently falling back to ``PROJECT_ID`` there
    would let a broken config bind the operation to the wrong project.
    """
    from agentkit.backend.config.defaults import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_FILE
    from agentkit.backend.config.loader import find_project_root, load_project_config
    from agentkit.backend.exceptions import AgentKitError, ConfigError

    if project_root:
        root = Path(project_root)
    else:
        try:
            root = find_project_root()
        except (AgentKitError, OSError):
            return ""  # genuinely no project context
    config_path = root / DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILE
    if not config_path.is_file():
        return ""  # genuine absence: the env binding may be the authority
    try:
        config = load_project_config(root)
    except ConfigError as exc:
        raise ProjectBindingError(
            f"project configuration {config_path} exists but is invalid: {exc}; "
            "fail-closed (D2/N22: an invalid config is never treated as absent)."
        ) from exc
    except (AgentKitError, OSError) as exc:
        raise ProjectBindingError(
            f"project configuration {config_path} could not be read: {exc}; "
            "fail-closed (D2/N22)."
        ) from exc
    prefix = config.project_prefix or config.project_key.upper()
    if not prefix.strip():
        raise ProjectBindingError(
            f"project configuration {config_path} carries no usable project_prefix; "
            "fail-closed (D2)."
        )
    return prefix.strip()


__all__ = [
    "PROJECT_ID_ENV_KEY",
    "ProjectBinding",
    "ProjectBindingError",
    "resolve_authoritative_project_id",
]
