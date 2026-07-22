"""Three-ring CLI operations (R03/R12/R13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.support.vectordb.project_fixtures import make_fk13_project

from agentkit.backend.concept_catalog.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def test_validate_corpus_exit_codes(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    code = main(["--project-root", str(root), "validate", "--corpus"])
    assert code in (0, 1)


def test_validate_strict(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    code = main(["--project-root", str(root), "validate", "--corpus", "--strict"])
    assert code in (0, 1, 2)


def test_build_and_doctor(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    assert main(["--project-root", str(root), "doctor", "--summary"]) == 0
    assert main(["--project-root", str(root), "build"]) == 0
    assert (root / "concepts" / "INDEX.yaml").is_file()
    assert (root / "concepts" / "concept_graph.json").is_file()


def test_sync_requires_real_weaviate_binding(tmp_path: Path) -> None:
    """R03: no silent memory success — missing Weaviate fails closed."""
    root = make_fk13_project(tmp_path, "P1")
    # project config has host but no live weaviate; connect fails closed.
    code = main(["--project-root", str(root), "sync", "--full-reindex"])
    assert code != 0


def test_lint_soft(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    concept = next((root / "concepts").glob("*.md"))
    assert main(["--project-root", str(root), "lint", str(concept)]) == 0
