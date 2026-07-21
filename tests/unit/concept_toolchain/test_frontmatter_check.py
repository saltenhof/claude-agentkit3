"""Unit tests for the generic frontmatter/authority contract check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_toolchain.config import load_governance_config
from concept_toolchain.frontmatter_check import run_frontmatter_check
from tests.unit.concept_toolchain.conftest import concept_doc, write_doc, write_governance_config

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult


def run(project_root: Path) -> CheckResult:
    return run_frontmatter_check(project_root, load_governance_config(project_root))


def check_ids(result: CheckResult) -> set[str]:
    return {finding.check_id for finding in result.findings}


def test_green_corpus_has_no_findings(green_corpus: Path) -> None:
    result = run(green_corpus)
    assert result.findings == []
    assert result.complete is True


def test_missing_required_field(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/domain-design/01-a.md", concept_doc("DK-01", drop_fields=("tags",)))
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    result = run(tmp_path)
    assert "frontmatter.required-field" in check_ids(result)
    assert any("'tags'" in finding.message for finding in result.findings)


def test_concept_id_grammar_violation(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/domain-design/01-a.md", concept_doc("DKX-1"))
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    result = run(tmp_path)
    assert "frontmatter.concept-id" in check_ids(result)


def test_duplicate_concept_id(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/domain-design/01-a.md", concept_doc("DK-01", scopes=("scope-a",)))
    write_doc(tmp_path, "concept/domain-design/02-b.md", concept_doc("DK-01", scopes=("scope-b",)))
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    result = run(tmp_path)
    assert any(finding.check_id == "frontmatter.concept-id" and "also used" in finding.message for finding in result.findings)


def test_classification_requires_exactly_one_variant(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    both = concept_doc("DK-01", classification="formal_refs:\n  - formal.sample.state-machine\nformal_scope: prose-only")
    neither = concept_doc("DK-02", classification="other_field: x")
    write_doc(tmp_path, "concept/domain-design/01-a.md", both)
    write_doc(tmp_path, "concept/domain-design/02-b.md", neither)
    (tmp_path / "concept" / "technical-design").mkdir(parents=True)
    result = run(tmp_path)
    messages = [finding.message for finding in result.findings if finding.check_id == "frontmatter.classification"]
    assert any("mixes" in message for message in messages)
    assert any("must declare" in message for message in messages)


def test_detail_requires_parent(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/technical-design/11_detail.md", concept_doc("FK-11", doc_kind="detail"))
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert "frontmatter.detail-parent" in check_ids(result)


def test_defers_to_dead_target(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    dead = concept_doc("FK-10", defers="defers_to:\n  - target: FK-99\n    scope: nowhere\n    reason: dead")
    write_doc(tmp_path, "concept/technical-design/10_a.md", dead)
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert any(finding.check_id == "frontmatter.defers-to" and "FK-99" in finding.message for finding in result.findings)


def test_full_supersession_requires_reciprocity(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    superseder = concept_doc("FK-11", supersedes="supersedes:\n  - FK-10")
    superseded = concept_doc("FK-10")  # missing superseded_by: FK-11
    write_doc(tmp_path, "concept/technical-design/11_new.md", superseder)
    write_doc(tmp_path, "concept/technical-design/10_old.md", superseded)
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert any(
        finding.check_id == "frontmatter.supersession" and "not reciprocated" in finding.message
        for finding in result.findings
    )


def test_full_supersession_pair_shares_scope_without_finding(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    superseder = concept_doc("FK-11", scopes=("shared-scope",), supersedes="supersedes:\n  - FK-10")
    superseded = concept_doc("FK-10", scopes=("shared-scope",), superseded_by="FK-11")
    write_doc(tmp_path, "concept/technical-design/11_new.md", superseder)
    write_doc(tmp_path, "concept/technical-design/10_old.md", superseded)
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert result.findings == []


def test_parent_cycle_is_detected(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/technical-design/10_a.md", concept_doc("FK-10", parent="FK-11"))
    write_doc(tmp_path, "concept/technical-design/11_b.md", concept_doc("FK-11", parent="FK-10"))
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert any(
        finding.check_id == "frontmatter.authority-cycle" and finding.locator == "parent_concept_id"
        for finding in result.findings
    )


def test_scope_deferral_cycle_is_detected(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    first = concept_doc("FK-10", defers="defers_to:\n  - target: FK-11\n    scope: shared\n    reason: forward")
    second = concept_doc("FK-11", defers="defers_to:\n  - target: FK-10\n    scope: shared\n    reason: backward")
    write_doc(tmp_path, "concept/technical-design/10_a.md", first)
    write_doc(tmp_path, "concept/technical-design/11_b.md", second)
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert any(
        finding.check_id == "frontmatter.authority-cycle" and finding.locator == "scope:shared"
        for finding in result.findings
    )


def test_scope_deferral_cycle_requires_same_scope(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    first = concept_doc("FK-10", defers="defers_to:\n  - target: FK-11\n    scope: one\n    reason: forward")
    second = concept_doc("FK-11", defers="defers_to:\n  - target: FK-10\n    scope: two\n    reason: backward")
    write_doc(tmp_path, "concept/technical-design/10_a.md", first)
    write_doc(tmp_path, "concept/technical-design/11_b.md", second)
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert not any(finding.check_id == "frontmatter.authority-cycle" for finding in result.findings)


def test_shared_authority_scope_without_supersession(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/technical-design/10_a.md", concept_doc("FK-10", scopes=("shared-scope",)))
    write_doc(tmp_path, "concept/technical-design/11_b.md", concept_doc("FK-11", scopes=("shared-scope",)))
    (tmp_path / "concept" / "domain-design").mkdir(parents=True)
    result = run(tmp_path)
    assert any(
        finding.check_id == "frontmatter.authority-scope" and finding.locator == "scope:shared-scope"
        for finding in result.findings
    )


def test_missing_roots_are_incomplete(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    result = run(tmp_path)
    assert result.complete is False
    assert result.incomplete_reason is not None
    assert "domain-design" in result.incomplete_reason
