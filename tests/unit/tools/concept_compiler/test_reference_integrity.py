"""Tests for the deterministic concept-reference-integrity gate."""

from __future__ import annotations

from pathlib import Path

from concept_compiler.compiler import compile_formal_specs
from concept_compiler.loader import try_load_frontmatter
from concept_compiler.reference_integrity import (
    ReferenceIntegrityResult,
    audit_reference_integrity,
    render_reference_integrity,
)

FIXTURES = Path("tests/fixtures/concept_compiler")
EMPTY_BASELINE = FIXTURES / "empty-baseline.yaml"
COMPILED = compile_formal_specs(FIXTURES / "compile_ok")


def _audit(scenario: str, baseline: Path = EMPTY_BASELINE) -> ReferenceIntegrityResult:
    root = FIXTURES.resolve()
    return audit_reference_integrity(root, root / scenario / "concept", COMPILED, baseline.resolve())


def test_dead_document_reference_is_error() -> None:
    result = _audit("dead_doc_ref")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_DOCUMENT"]
    assert result.findings[0].reference == "FK-99"


def test_section_anchor_resolves_against_target_heading() -> None:
    result = _audit("dead_section")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_SECTION"]
    assert result.findings[0].reference == "FK-71 §67.3"


def test_unknown_formal_item_uses_compiled_declared_ids() -> None:
    result = _audit("unknown_formal_id")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_FORMAL_ID"]
    assert result.findings[0].reference == "formal.example.invariant.missing"


def test_dead_repo_path_is_error() -> None:
    result = _audit("dead_path")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_REPO_PATH"]


def test_dead_path_under_dynamically_discovered_top_level_is_error() -> None:
    result = _audit("unrecognized_dead_path")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_REPO_PATH"]
    assert result.findings[0].reference == "compile_ok/missing.yml"


def test_ellipsis_dead_path_is_error_on_every_platform() -> None:
    result = _audit("platform_ellipsis_dead_path")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_REPO_PATH"]
    assert result.findings[0].reference == "compile_ok/..."


def test_same_scope_cycle_is_error_with_both_reasons() -> None:
    result = _audit("per_scope_cycle")

    scope_finding = next(item for item in result.findings if item.code == "SCOPE_DEFERS_TO_CYCLE")
    assert scope_finding.reference == "shared-scope"
    assert "A delegates the shared scope to B" in scope_finding.message
    assert "B delegates the shared scope to A" in scope_finding.message


def test_reasonless_mapping_edge_is_kept_and_same_scope_cycle_is_error() -> None:
    result = _audit("reasonless_mapping_cycle")

    scope_finding = next(item for item in result.findings if item.code == "SCOPE_DEFERS_TO_CYCLE")
    assert scope_finding.reference == "shared-scope"
    assert "FK-01->FK-02: reason missing or non-string" in scope_finding.message
    assert not any(item.code == "INVALID_DEFERS_TO_EDGE" for item in result.findings)


def test_mapping_missing_target_or_scope_is_malformed_error() -> None:
    result = _audit("malformed_mapping")

    assert [finding.code for finding in result.findings] == [
        "INVALID_DEFERS_TO_EDGE",
        "INVALID_DEFERS_TO_EDGE",
    ]


def test_scalar_defers_to_entry_is_valid_and_document_level_only() -> None:
    fixture = FIXTURES / "scalar_defers_cycle"
    result = _audit("scalar_defers_cycle", fixture / "baseline.yaml")

    assert result.ok
    assert [report.code for report in result.reports] == ["DOCUMENT_DEFERS_TO_CYCLE"]
    assert not any(item.code in {"INVALID_DEFERS_TO_EDGE", "SCOPE_DEFERS_TO_CYCLE"} for item in result.findings)


def test_justified_document_cycle_is_report_only() -> None:
    fixture = FIXTURES / "doc_level_cycle"
    result = _audit("doc_level_cycle", fixture / "baseline.yaml")

    assert result.ok
    assert [report.code for report in result.reports] == ["DOCUMENT_DEFERS_TO_CYCLE"]


def test_unjustified_document_cycle_is_fail_closed() -> None:
    fixture = FIXTURES / "doc_level_cycle_unjustified"
    result = _audit("doc_level_cycle_unjustified", fixture / "baseline.yaml")

    assert {finding.code for finding in result.findings} == {
        "UNBASELINED_DOCUMENT_CYCLE",
        "UNJUSTIFIED_BASELINE",
    }


def test_marked_negative_example_is_ignored_but_same_unmarked_fails() -> None:
    result = _audit("marked_vs_unmarked")

    assert len(result.findings) == 1
    assert result.findings[0].path.endswith("unmarked.md")
    assert result.findings[0].code == "UNRESOLVED_SECTION"


def test_dangling_ignore_line_at_eof_is_error() -> None:
    result = _audit("dangling_ignore_line")

    assert [finding.code for finding in result.findings] == ["INVALID_IGNORE_DIRECTIVE"]
    assert "no following physical line" in result.findings[0].message


def test_unclosed_ignore_begin_at_eof_is_error() -> None:
    result = _audit("dangling_ignore_begin")

    assert [finding.code for finding in result.findings] == ["INVALID_IGNORE_DIRECTIVE"]
    assert "no matching end" in result.findings[0].message


def test_production_governance_negative_examples_are_marked() -> None:
    repo_root = Path.cwd().resolve()
    result = audit_reference_integrity(
        repo_root,
        repo_root / "concept",
        compile_formal_specs(repo_root / "concept/formal-spec"),
        repo_root / "concept/_meta/reference-integrity-baseline.yaml",
    )

    governance = "concept/_meta/konzept-konsistenz-governance.md"
    assert not any(finding.path == governance and "§67.x" in finding.reference for finding in result.findings)
    assert any(report.reference == "reports/AG3-148-model-fix-design.md" for report in result.reports)


def test_production_scalar_defers_to_entries_are_not_invalid() -> None:
    repo_root = Path.cwd().resolve()
    scalar_count = 0
    for path in (repo_root / "concept").rglob("*.md"):
        frontmatter = try_load_frontmatter(path)
        if frontmatter is None:
            continue
        raw_edges = frontmatter.get("defers_to", [])
        if isinstance(raw_edges, list):
            scalar_count += sum(isinstance(edge, str) for edge in raw_edges)
    result = audit_reference_integrity(
        repo_root,
        repo_root / "concept",
        compile_formal_specs(repo_root / "concept/formal-spec"),
        repo_root / "concept/_meta/reference-integrity-baseline.yaml",
    )

    assert scalar_count == 47
    assert not any(finding.code == "INVALID_DEFERS_TO_EDGE" for finding in result.findings)


def test_rendering_is_byte_identical_across_runs() -> None:
    first = render_reference_integrity(_audit("determinism")).encode()
    second = render_reference_integrity(_audit("determinism")).encode()

    assert first == second


def test_cli_returns_nonzero_for_unresolved_reference() -> None:
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/check_concept_reference_integrity.py",
            "--repo-root",
            str(FIXTURES),
            "--concept-root",
            "dead_doc_ref/concept",
            "--formal-root",
            "compile_ok",
            "--baseline",
            "empty-baseline.yaml",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "UNRESOLVED_DOCUMENT" in completed.stdout
