"""Target-mode digest engine tests (FK-78 78.12 target modes)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from concept_toolchain.receipts import (
    canonical_json_digest,
    compute_target_digest,
    directory_tree_digest,
    resolve_selector,
)
from concept_toolchain.units import section_index

if TYPE_CHECKING:
    from pathlib import Path

DOC = "# Alpha\n\nAlpha body.\n\n## Beta\n\nBeta body.\n"
REGISTRY_YAML = (
    "domains:\n"
    "  - id: concept-incubation\n"
    "    display_name: Concept Incubation\n"
    "    contract_docs:\n"
    "      - FK-78\n"
    "  - id: other\n"
    "    display_name: Other\n"
)


def write(tmp_path: Path, relative: str, text: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_markdown_section_digest_matches_unit_partition(tmp_path: Path) -> None:
    write(tmp_path, "doc.md", DOC)
    result = compute_target_digest(tmp_path, "doc.md#beta", "markdown-section", None)
    assert result.digest == section_index("doc.md", DOC)["beta"].digest


def test_markdown_section_missing_anchor_is_missing_target(tmp_path: Path) -> None:
    write(tmp_path, "doc.md", DOC)
    result = compute_target_digest(tmp_path, "doc.md#nope", "markdown-section", None)
    assert result.missing is True


def test_markdown_section_without_fragment_is_a_problem(tmp_path: Path) -> None:
    write(tmp_path, "doc.md", DOC)
    result = compute_target_digest(tmp_path, "doc.md", "markdown-section", None)
    assert result.problem is not None


def test_whole_file_digest_is_the_raw_byte_digest(tmp_path: Path) -> None:
    path = write(tmp_path, "registry.yaml", REGISTRY_YAML)
    result = compute_target_digest(tmp_path, "registry.yaml", "whole-file", None)
    assert result.digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_whole_file_missing_target(tmp_path: Path) -> None:
    assert compute_target_digest(tmp_path, "absent.json", "whole-file", None).missing is True


def test_structured_selector_on_yaml_entry(tmp_path: Path) -> None:
    write(tmp_path, "registry.yaml", REGISTRY_YAML)
    result = compute_target_digest(tmp_path, "registry.yaml", "structured-selector", "domains[id=concept-incubation]")
    expected = canonical_json_digest(
        {"id": "concept-incubation", "display_name": "Concept Incubation", "contract_docs": ["FK-78"]}
    )
    assert result.digest == expected


def test_structured_selector_on_json_key(tmp_path: Path) -> None:
    write(tmp_path, "governance.json", json.dumps({"lock_backend": "filesystem", "roots": {"meta": "concept/_meta"}}))
    result = compute_target_digest(tmp_path, "governance.json", "structured-selector", "roots")
    assert result.digest == canonical_json_digest({"meta": "concept/_meta"})


def test_structured_selector_is_stable_against_key_order(tmp_path: Path) -> None:
    write(tmp_path, "a.json", json.dumps({"x": {"b": 2, "a": 1}}))
    write(tmp_path, "b.json", json.dumps({"x": {"a": 1, "b": 2}}))
    first = compute_target_digest(tmp_path, "a.json", "structured-selector", "x")
    second = compute_target_digest(tmp_path, "b.json", "structured-selector", "x")
    assert first.digest == second.digest


def test_structured_selector_chains_steps(tmp_path: Path) -> None:
    write(tmp_path, "registry.yaml", REGISTRY_YAML)
    result = compute_target_digest(
        tmp_path, "registry.yaml", "structured-selector", "domains[id=concept-incubation].contract_docs"
    )
    assert result.digest == canonical_json_digest(["FK-78"])


def test_structured_selector_reports_unmatched_filter(tmp_path: Path) -> None:
    write(tmp_path, "registry.yaml", REGISTRY_YAML)
    result = compute_target_digest(tmp_path, "registry.yaml", "structured-selector", "domains[id=nope]")
    assert result.problem is not None
    assert "matched 0 entries" in result.problem


def test_structured_selector_requires_a_selector(tmp_path: Path) -> None:
    write(tmp_path, "registry.yaml", REGISTRY_YAML)
    assert compute_target_digest(tmp_path, "registry.yaml", "structured-selector", None).problem is not None


def test_malformed_selector_step_is_reported() -> None:
    _, problem = resolve_selector({"a": 1}, "a..b")
    assert problem is not None


def test_directory_tree_digest_covers_content_and_layout(tmp_path: Path) -> None:
    write(tmp_path, "pkg/a.py", "print(1)\n")
    write(tmp_path, "pkg/sub/b.py", "print(2)\n")
    first = compute_target_digest(tmp_path, "pkg", "directory-tree", None)
    assert first.digest == directory_tree_digest(tmp_path / "pkg")
    write(tmp_path, "pkg/sub/b.py", "print(3)\n")
    assert compute_target_digest(tmp_path, "pkg", "directory-tree", None).digest != first.digest
    write(tmp_path, "pkg/c.py", "print(4)\n")
    assert compute_target_digest(tmp_path, "pkg", "directory-tree", None).digest != first.digest


def test_directory_tree_ignores_dotted_and_pycache_entries(tmp_path: Path) -> None:
    write(tmp_path, "pkg/a.py", "print(1)\n")
    baseline = compute_target_digest(tmp_path, "pkg", "directory-tree", None).digest
    write(tmp_path, "pkg/__pycache__/a.cpython.pyc", "cache\n")
    write(tmp_path, "pkg/.hidden", "hidden\n")
    assert compute_target_digest(tmp_path, "pkg", "directory-tree", None).digest == baseline


def test_directory_tree_missing_target(tmp_path: Path) -> None:
    assert compute_target_digest(tmp_path, "absent", "directory-tree", None).missing is True


def test_unknown_mode_is_reported(tmp_path: Path) -> None:
    assert compute_target_digest(tmp_path, "x", "bogus", None).problem is not None
