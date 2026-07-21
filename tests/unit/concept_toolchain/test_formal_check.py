"""Unit tests for the formal-spec structural compile."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_toolchain.config import load_governance_config
from concept_toolchain.formal_check import run_formal_check
from tests.unit.concept_toolchain.conftest import (
    concept_doc,
    formal_spec,
    write_doc,
    write_formal_context,
    write_governance_config,
)

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult


def run(project_root: Path) -> CheckResult:
    return run_formal_check(project_root, load_governance_config(project_root))


def test_valid_context_is_green(green_corpus: Path) -> None:
    result = run(green_corpus)
    assert result.findings == []
    assert "1 contexts" in result.summary


def test_missing_terminal_state(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path, terminal=False)
    result = run(tmp_path)
    assert any(
        finding.check_id == "formal.state-machine" and "terminal" in finding.message for finding in result.findings
    )


def test_dangling_guard_reference(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path, guard="sample.invariant.missing")
    result = run(tmp_path)
    assert any(
        finding.check_id == "formal.reference" and "sample.invariant.missing" in finding.message
        for finding in result.findings
    )


def test_scenario_must_end_terminal(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path, scenario_end="sample.status.open")
    result = run(tmp_path)
    assert any(
        finding.check_id == "formal.scenario" and "terminal" in finding.message for finding in result.findings
    )


def test_missing_zone_is_error(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path)
    broken = (tmp_path / "concept/formal-spec/sample/events.md").read_text(encoding="utf-8")
    broken = broken.replace("<!-- FORMAL-SPEC:BEGIN -->", "").replace("<!-- FORMAL-SPEC:END -->", "")
    write_doc(tmp_path, "concept/formal-spec/sample/events.md", broken)
    result = run(tmp_path)
    assert any(finding.check_id == "formal.zone" for finding in result.findings)


def test_object_must_match_frontmatter_id(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path)
    events = (tmp_path / "concept/formal-spec/sample/events.md").read_text(encoding="utf-8")
    events = events.replace("object: formal.sample.event-set", "object: formal.sample.other-set")
    write_doc(tmp_path, "concept/formal-spec/sample/events.md", events)
    result = run(tmp_path)
    assert any(
        finding.check_id == "formal.zone" and "differs from frontmatter id" in finding.message
        for finding in result.findings
    )


def test_prose_reciprocity_missing_listing(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path)
    host = concept_doc("FK-20", title="Formal host", classification="formal_refs:\n  - formal.sample.state-machine")
    write_doc(tmp_path, "concept/technical-design/20_formal_host.md", host)
    result = run(tmp_path)
    reciprocity = [finding for finding in result.findings if finding.check_id == "formal.reciprocity"]
    assert reciprocity, "expected reciprocity findings for unlisted formal ids"
    assert all("does not list" in finding.message for finding in reciprocity)


def test_missing_prose_ref_file(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_doc(
        tmp_path,
        "concept/formal-spec/lonely/invariants.md",
        formal_spec(
            "lonely",
            "invariant-set",
            "invariants:\n  - id: lonely.invariant.x\n    scope: process\n    rule: r\n",
            prose_ref="concept/technical-design/99_missing.md",
        ),
    )
    result = run(tmp_path)
    assert any(
        finding.check_id == "formal.reciprocity" and "does not exist" in finding.message for finding in result.findings
    )


def test_readme_and_meta_are_excluded(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    write_formal_context(tmp_path)
    write_doc(tmp_path, "concept/formal-spec/README.md", "# Formal corpus\n\nNo frontmatter here.\n")
    write_doc(tmp_path, "concept/formal-spec/sample/README.md", "# Sample context\n")
    write_doc(tmp_path, "concept/formal-spec/00_meta/syntax.md", "# Syntax contract with `---` examples\n")
    result = run(tmp_path)
    assert result.findings == []


def test_missing_formal_root_is_incomplete(tmp_path: Path) -> None:
    write_governance_config(tmp_path)
    result = run(tmp_path)
    assert result.complete is False
    assert result.incomplete_reason is not None
