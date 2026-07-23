"""Unit tests for project + runtime binding (Review 174-P0-4, D2/D4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.backend.vectordb.project_binding import (
    ProjectBinding,
    ProjectBindingError,
)
from agentkit.backend.vectordb.runtime_binding import (
    RuntimeBinding,
    RuntimeBindingError,
)

# --------------------------------------------------------------------------- #
# ProjectBinding
# --------------------------------------------------------------------------- #


def _binding(tmp_path: Path, **overrides: object) -> ProjectBinding:
    base: dict[str, object] = {
        "project_id": "acme",
        "project_root": tmp_path,
        "concepts_dir": tmp_path / "concept",
        "stories_dir": tmp_path / "stories",
        "weaviate_http_endpoint": "http://weaviate.acme.local:8080",
    }
    base.update(overrides)
    return ProjectBinding(**base)  # type: ignore[arg-type]


def test_project_binding_requires_project_id(tmp_path: Path) -> None:
    with pytest.raises(ProjectBindingError, match="project_id"):
        _binding(tmp_path, project_id="   ")


def test_project_binding_requires_explicit_endpoint(tmp_path: Path) -> None:
    with pytest.raises(ProjectBindingError, match="endpoint"):
        _binding(tmp_path, weaviate_http_endpoint="")


def test_project_binding_rejects_localhost_default(tmp_path: Path) -> None:
    with pytest.raises(ProjectBindingError, match="localhost default"):
        _binding(tmp_path, weaviate_http_endpoint="http://localhost:8080")


def test_resolve_within_root_accepts_inner(tmp_path: Path) -> None:
    b = _binding(tmp_path)
    resolved = b.resolve_within_root(Path("concept/13_retrieval.md"))
    assert tmp_path.resolve() in resolved.parents


def test_resolve_within_root_rejects_traversal(tmp_path: Path) -> None:
    b = _binding(tmp_path)
    with pytest.raises(ProjectBindingError, match="outside project_root"):
        b.resolve_within_root(Path("../../etc/passwd"))


def test_resolve_within_root_rejects_absolute_escape(tmp_path: Path) -> None:
    b = _binding(tmp_path)
    with pytest.raises(ProjectBindingError, match="outside project_root"):
        b.resolve_within_root(Path("C:/Windows/System32/drivers/etc/hosts"))


def test_assert_writable_within_root_batch(tmp_path: Path) -> None:
    b = _binding(tmp_path)
    b.assert_writable_within_root([tmp_path / "stories" / "x", tmp_path / "concept" / "y"])
    with pytest.raises(ProjectBindingError):
        b.assert_writable_within_root([tmp_path / ".." / "escape"])


# --------------------------------------------------------------------------- #
# RuntimeBinding
# --------------------------------------------------------------------------- #


_GOOD_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}


def test_runtime_binding_from_env_ok() -> None:
    rb = RuntimeBinding.from_env(
        _GOOD_ENV, command="python", args=("-m", "agentkit.backend.vectordb.mcp_server"), cwd="/srv"
    )
    assert rb.project_id == "acme"
    assert rb.weaviate_http_endpoint == "http://weaviate.acme.local:8080"
    spec = rb.spec
    assert spec.command == "python"
    assert spec.cwd == "/srv"
    assert spec.env_dict()["PROJECT_ID"] == "acme"


@pytest.mark.parametrize("missing_key", ["PROJECT_ID", "WEAVIATE_HTTP_ENDPOINT"])
def test_runtime_binding_missing_required_key_fails_closed(missing_key: str) -> None:
    env = {k: v for k, v in _GOOD_ENV.items() if k != missing_key}
    with pytest.raises(RuntimeBindingError, match="missing"):
        RuntimeBinding.from_env(env, command="python", args=(), cwd="/srv")


def test_runtime_binding_empty_value_fails_closed() -> None:
    env = {**_GOOD_ENV, "PROJECT_ID": "  "}
    with pytest.raises(RuntimeBindingError, match="empty"):
        RuntimeBinding.from_env(env, command="python", args=(), cwd="/srv")


def test_runtime_binding_wrong_typed_value_fails_closed() -> None:
    env = {**_GOOD_ENV, "WEAVIATE_GRPC_ENDPOINT": 50051}  # type: ignore[dict-item]
    with pytest.raises(RuntimeBindingError, match="string"):
        RuntimeBinding.from_env(env, command="python", args=(), cwd="/srv")


def test_runtime_binding_rejects_localhost_default() -> None:
    env = {**_GOOD_ENV, "WEAVIATE_HTTP_ENDPOINT": "http://127.0.0.1:8080"}
    with pytest.raises(RuntimeBindingError, match="localhost default"):
        RuntimeBinding.from_env(env, command="python", args=(), cwd="/srv")


def test_runtime_binding_rejects_empty_cwd() -> None:
    with pytest.raises(RuntimeBindingError, match="cwd"):
        RuntimeBinding.from_env(_GOOD_ENV, command="python", args=(), cwd="   ")


def test_resolve_project_id_omitted_returns_bound() -> None:
    rb = RuntimeBinding.from_env(_GOOD_ENV, command="python", args=(), cwd="/srv")
    assert rb.resolve_project_id(None) == "acme"
    assert rb.resolve_project_id("") == "acme"


def test_resolve_project_id_matching_returns_bound() -> None:
    rb = RuntimeBinding.from_env(_GOOD_ENV, command="python", args=(), cwd="/srv")
    assert rb.resolve_project_id("acme") == "acme"


def test_resolve_project_id_divergent_rejected() -> None:
    rb = RuntimeBinding.from_env(_GOOD_ENV, command="python", args=(), cwd="/srv")
    with pytest.raises(RuntimeBindingError, match="diverges"):
        rb.resolve_project_id("other-project")
