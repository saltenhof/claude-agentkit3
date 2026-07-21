"""Unit tests for the reference-integrity check with baseline support."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_toolchain.config import load_governance_config
from concept_toolchain.reference_check import run_reference_check
from tests.unit.concept_toolchain.conftest import concept_doc, write_doc

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult


def run(project_root: Path) -> CheckResult:
    return run_reference_check(project_root, load_governance_config(project_root))


def line_of(project_root: Path, relative: str, needle: str) -> int:
    text = (project_root / relative).read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"needle {needle!r} not found in {relative}")


def test_resolving_references_pass(green_corpus: Path) -> None:
    result = run(green_corpus)
    assert result.findings == []


def test_dead_document_mention(green_corpus: Path) -> None:
    write_doc(green_corpus, "concept/domain-design/02-dead.md", concept_doc("DK-02", body="See FK-99 for details.\n"))
    result = run(green_corpus)
    assert any(
        finding.check_id == "UNRESOLVED_DOCUMENT" and "FK-99" in finding.message for finding in result.findings
    )


def test_dead_repo_path(green_corpus: Path) -> None:
    body = "See `concept/technical-design/missing.md` for details.\n"
    write_doc(green_corpus, "concept/domain-design/02-dead.md", concept_doc("DK-02", body=body))
    result = run(green_corpus)
    assert any(
        finding.check_id == "UNRESOLVED_REPO_PATH" and "concept/technical-design/missing.md" in finding.message
        for finding in result.findings
    )


def test_dead_formal_id(green_corpus: Path) -> None:
    body = "Formal anchor formal.sample.state-machine is fine, formal.sample.missing-set is not.\n"
    write_doc(green_corpus, "concept/domain-design/02-formal.md", concept_doc("DK-02", body=body))
    result = run(green_corpus)
    formal_findings = [finding for finding in result.findings if finding.check_id == "UNRESOLVED_FORMAL_ID"]
    assert len(formal_findings) == 1
    assert "formal.sample.missing-set" in formal_findings[0].message


def test_anchor_reference_resolution(green_corpus: Path) -> None:
    target = concept_doc("DK-03", title="Anchor target", body="## Details\n\nContent.\n")
    write_doc(green_corpus, "concept/domain-design/03-target.md", target)
    body = (
        "Good: `concept/domain-design/03-target.md#details`.\n"
        "Bad: `concept/domain-design/03-target.md#missing-anchor`.\n"
    )
    write_doc(green_corpus, "concept/domain-design/02-links.md", concept_doc("DK-02", body=body))
    result = run(green_corpus)
    anchor_findings = [finding for finding in result.findings if finding.check_id == "UNRESOLVED_ANCHOR"]
    assert len(anchor_findings) == 1
    assert "#missing-anchor" in anchor_findings[0].message


def test_baseline_match_becomes_report(green_corpus: Path) -> None:
    body = "See `concept/technical-design/missing.md` for details.\n"
    doc_path = "concept/domain-design/02-dead.md"
    write_doc(green_corpus, doc_path, concept_doc("DK-02", body=body))
    line = line_of(green_corpus, doc_path, "missing.md")
    baseline = (
        "version: 1\n"
        "unresolved_references:\n"
        "  - code: UNRESOLVED_REPO_PATH\n"
        f"    path: {doc_path}\n"
        f"    line: {line}\n"
        "    reference: concept/technical-design/missing.md\n"
        "    reason: >-\n"
        "      Deliberate example path kept for the test corpus.\n"
    )
    write_doc(green_corpus, "concept/_meta/reference-integrity-baseline.yaml", baseline)
    result = run(green_corpus)
    assert result.findings == []
    assert any("UNRESOLVED_REPO_PATH" in report and "[REPORT]" in report for report in result.reports)


def test_stale_baseline_entry_is_error(green_corpus: Path) -> None:
    baseline = (
        "version: 1\n"
        "unresolved_references:\n"
        "  - code: UNRESOLVED_REPO_PATH\n"
        "    path: concept/domain-design/01-sample.md\n"
        "    line: 99\n"
        "    reference: concept/never/was.md\n"
        "    reason: stale entry\n"
    )
    write_doc(green_corpus, "concept/_meta/reference-integrity-baseline.yaml", baseline)
    result = run(green_corpus)
    assert any(finding.check_id == "STALE_BASELINE" for finding in result.findings)


def test_baseline_entry_without_reason_is_error(green_corpus: Path) -> None:
    baseline = (
        "version: 1\n"
        "unresolved_references:\n"
        "  - code: UNRESOLVED_REPO_PATH\n"
        "    path: concept/domain-design/01-sample.md\n"
        "    line: 1\n"
        "    reference: concept/never/was.md\n"
    )
    write_doc(green_corpus, "concept/_meta/reference-integrity-baseline.yaml", baseline)
    result = run(green_corpus)
    assert any(finding.check_id == "UNJUSTIFIED_BASELINE" for finding in result.findings)


def test_document_cycle_requires_baseline(green_corpus: Path) -> None:
    first = concept_doc("DK-08", defers="defers_to:\n  - DK-09")
    second = concept_doc("DK-09", defers="defers_to:\n  - DK-08")
    write_doc(green_corpus, "concept/domain-design/08-a.md", first)
    write_doc(green_corpus, "concept/domain-design/09-b.md", second)
    result = run(green_corpus)
    assert any(
        finding.check_id == "UNBASELINED_DOCUMENT_CYCLE" and "DK-08,DK-09" in finding.message
        for finding in result.findings
    )
    baseline = (
        "version: 1\n"
        "document_cycles:\n"
        "  - documents:\n"
        "      - DK-08\n"
        "      - DK-09\n"
        "    reason: scope-disjoint scalar deferral pair for the test corpus\n"
    )
    write_doc(green_corpus, "concept/_meta/reference-integrity-baseline.yaml", baseline)
    baselined = run(green_corpus)
    assert not any(finding.check_id == "UNBASELINED_DOCUMENT_CYCLE" for finding in baselined.findings)
    assert any("DOCUMENT_DEFERS_TO_CYCLE" in report for report in baselined.reports)


def test_ignore_region_suppresses_findings_and_requires_reason(green_corpus: Path) -> None:
    body = (
        "<!-- REF-INTEGRITY:IGNORE-BEGIN deliberate dead example -->\n"
        "Broken example FK-99.\n"
        "<!-- REF-INTEGRITY:IGNORE-END -->\n"
        "<!-- REF-INTEGRITY:IGNORE-LINE -->\n"
    )
    write_doc(green_corpus, "concept/domain-design/02-ignored.md", concept_doc("DK-02", body=body))
    result = run(green_corpus)
    assert not any(finding.check_id == "UNRESOLVED_DOCUMENT" for finding in result.findings)
    assert any(finding.check_id == "INVALID_IGNORE_DIRECTIVE" for finding in result.findings)
