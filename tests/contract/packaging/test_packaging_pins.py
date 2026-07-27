"""Contract test binding the tokenizer/library packaging pins (FK-13 §13.2, D5)."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _project_table() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        data: dict[str, object] = tomllib.load(handle)
    project = data.get("project")
    assert isinstance(project, dict)
    return project


def test_weaviate_client_is_runtime_dependency_pinned() -> None:
    deps = _project_table().get("dependencies")
    assert isinstance(deps, list)
    assert any(
        isinstance(d, str) and d.startswith("weaviate-client") and ">=4.9" in d and "<5.0" in d
        for d in deps
    ), "weaviate-client must be a real runtime dep pinned >=4.9,<5.0 (FK-13 §13.2)"


def test_mcp_is_runtime_dependency() -> None:
    deps = _project_table().get("dependencies")
    assert isinstance(deps, list)
    assert any(
        isinstance(d, str) and d.startswith("mcp") for d in deps
    ), "mcp must be a real runtime dependency"


def test_tokenizers_pinned_exactly() -> None:
    deps = _project_table().get("dependencies")
    assert isinstance(deps, list)
    assert "tokenizers==0.21.0" in deps, "tokenizers pinned ==0.21.0 (PO decision D5)"


def test_tomlkit_pinned_exactly() -> None:
    """AG3-175 decision D-1 (PO-approved): the TOML writer is pinned exactly.

    ``tomllib`` (stdlib) reads only; the semantic merge into a target project's
    ``.codex/config.toml`` needs a round-trip writer that preserves FOREIGN
    comments and formatting. Same exact-pin discipline as PO decision D5.
    """
    deps = _project_table().get("dependencies")
    assert isinstance(deps, list)
    assert "tomlkit==0.15.1" in deps, "tomlkit pinned ==0.15.1 (AG3-175 decision D-1)"


def test_no_second_toml_writer_is_declared() -> None:
    """SINGLE SOURCE OF TRUTH: exactly one TOML writer in the dependency set."""
    deps = _project_table().get("dependencies")
    assert isinstance(deps, list)
    writers = [d for d in deps if isinstance(d, str) and d.startswith(("tomli-w", "tomli_w", "toml=="))]
    assert writers == [], f"a second TOML writer is declared: {writers}"


def test_weaviate_no_longer_optional_extra() -> None:
    optional = _project_table().get("optional-dependencies")
    assert isinstance(optional, dict)
    assert "weaviate" not in optional, "weaviate extra removed; it is now a base dep"
