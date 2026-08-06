"""Tests for the deterministic concept-reference-integrity gate."""

from __future__ import annotations

import subprocess
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


def test_case_variant_tracked_root_dead_path_is_error_while_exact_existing_path_resolves() -> None:
    result = _audit("case_variant_root_path")

    assert [finding.code for finding in result.findings] == ["UNRESOLVED_REPO_PATH"]
    assert result.findings[0].reference == "Compile_ok/missing.yml"


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=gate@example.invalid", "-c", "user.name=Gate", "commit", "-q", "-m", message)


def _seed_repo(tmp_path: Path) -> Path:
    """Create a real git repository with a tracked concept doc and payload tree."""
    repo = tmp_path / "repo"
    (repo / "concept").mkdir(parents=True)
    (repo / "payload").mkdir()
    (repo / "concept" / "baseline.yaml").write_text(
        "version: 1\nunresolved_references: []\ndocument_cycles: []\n", encoding="utf-8"
    )
    (repo / "payload" / "anchor.md").write_text("anchor\n", encoding="utf-8")
    (repo / "concept" / "source.md").write_text("# Source\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "seed")
    return repo


def _name(repo: Path, reference: str) -> None:
    (repo / "concept" / "source.md").write_text(f"# Source\n\nIt names `{reference}`.\n", encoding="utf-8")


def _repo_path_findings(repo: Path, reference: str) -> tuple[tuple[str, str], ...]:
    result = audit_reference_integrity(repo, repo / "concept", COMPILED, repo / "concept" / "baseline.yaml")
    return tuple((item.code, item.message) for item in result.findings if item.reference == reference)


def test_new_unstaged_file_resolves_exactly_as_after_staging(tmp_path: Path) -> None:
    """AC 1, direction 'new but unstaged': the gate follows the working tree."""
    repo = _seed_repo(tmp_path)
    _name(repo, "payload/added.md")
    absent = _repo_path_findings(repo, "payload/added.md")

    (repo / "payload" / "added.md").write_text("added\n", encoding="utf-8")
    unstaged = _repo_path_findings(repo, "payload/added.md")
    _git(repo, "add", "payload/added.md")
    staged = _repo_path_findings(repo, "payload/added.md")

    assert absent == (
        ("UNRESOLVED_REPO_PATH", "repo-relative path is neither tracked by git nor an unignored working-tree file"),
    )
    assert unstaged == ()
    assert unstaged == staged


def test_deleted_unstaged_file_fails_exactly_as_after_staging(tmp_path: Path) -> None:
    """AC 1, direction 'deleted but unstaged': the gate follows the working tree."""
    repo = _seed_repo(tmp_path)
    (repo / "payload" / "doomed.md").write_text("doomed\n", encoding="utf-8")
    _name(repo, "payload/doomed.md")
    _commit(repo, "add doomed")
    present = _repo_path_findings(repo, "payload/doomed.md")

    (repo / "payload" / "doomed.md").unlink()
    unstaged = _repo_path_findings(repo, "payload/doomed.md")
    _git(repo, "add", "-A")
    staged = _repo_path_findings(repo, "payload/doomed.md")

    assert present == ()
    assert unstaged == (
        ("UNRESOLVED_REPO_PATH", "repo-relative path is known to git but absent from the working tree"),
    )
    # Staging the deletion drops the path from git entirely, so the message names
    # the other unmet condition; the verdict the developer sees is identical.
    assert [code for code, _ in staged] == [code for code, _ in unstaged]
    assert staged == (
        ("UNRESOLVED_REPO_PATH", "repo-relative path is neither tracked by git nor an unignored working-tree file"),
    )


def test_unresolved_repo_path_in_a_clean_tree_is_still_an_error(tmp_path: Path) -> None:
    """AC 3: the gate keeps rejecting a genuinely unresolvable repository path."""
    repo = _seed_repo(tmp_path)
    _name(repo, "payload/never_existed.md")
    _commit(repo, "name a dead path")

    # ``diff --quiet`` exits non-zero on any change, so ``check=True`` asserts a
    # fully clean tree: nothing here is an artefact of staging state.
    _git(repo, "diff", "--quiet", "HEAD")
    assert _repo_path_findings(repo, "payload/never_existed.md") == (
        ("UNRESOLVED_REPO_PATH", "repo-relative path is neither tracked by git nor an unignored working-tree file"),
    )


def test_gitignored_working_tree_file_is_not_a_valid_reference(tmp_path: Path) -> None:
    """The ignore filter survives: generated artefacts never resolve as content."""
    repo = _seed_repo(tmp_path)
    (repo / ".gitignore").write_text("payload/generated.md\n", encoding="utf-8")
    _name(repo, "payload/generated.md")
    _commit(repo, "ignore generated payload")
    (repo / "payload" / "generated.md").write_text("generated\n", encoding="utf-8")

    assert (repo / "payload" / "generated.md").exists()
    assert _repo_path_findings(repo, "payload/generated.md") == (
        ("UNRESOLVED_REPO_PATH", "repo-relative path is neither tracked by git nor an unignored working-tree file"),
    )


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


def test_present_null_defers_to_is_invalid_while_absent_and_empty_are_valid() -> None:
    result = _audit("null_absent_empty_defers_to")

    assert [finding.code for finding in result.findings] == ["INVALID_DEFERS_TO_EDGE"]
    assert result.findings[0].path.endswith("null.md")
    assert result.findings[0].reference == "None"


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
        encoding="utf-8",
    )

    assert completed.returncode == 1
    assert "UNRESOLVED_DOCUMENT" in completed.stdout
