"""Unit tests for the reference-integrity check with baseline support.

``green_corpus`` is a real ``git init`` repository. That is a precondition,
not scenery: the check resolves a backticked repo-relative path against the
set of versionable repository content that only git can name, conjunctively
with a working-tree probe, and it has no filesystem fallback to slip into.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from concept_toolchain.config import load_governance_config
from concept_toolchain.reference_check import run_reference_check
from tests.unit.concept_toolchain.conftest import concept_doc, write_doc, write_governance_config

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult

NOT_KNOWN = "repo-relative path is neither tracked by git nor an unignored working-tree file"
ABSENT = "repo-relative path is known to git but absent from the working tree"


def run(project_root: Path) -> CheckResult:
    return run_reference_check(project_root, load_governance_config(project_root))


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def name_path(project_root: Path, reference: str) -> None:
    """Let one concept document mention ``reference`` as a backticked path."""
    write_doc(
        project_root,
        "concept/domain-design/02-names.md",
        concept_doc("DK-02", body=f"It names `{reference}`.\n"),
    )


def repo_path_messages(project_root: Path, reference: str) -> tuple[str, ...]:
    result = run(project_root)
    return tuple(
        finding.message.removeprefix(f"{reference} - ")
        for finding in result.findings
        if finding.check_id == "UNRESOLVED_REPO_PATH" and finding.message.startswith(f"{reference} - ")
    )


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


def commit(project_root: Path, message: str) -> None:
    git(project_root, "add", "-A")
    git(
        project_root,
        "-c",
        "user.email=toolchain-test@example.com",
        "-c",
        "user.name=Toolchain Test",
        "commit",
        "-q",
        "-m",
        message,
    )


def seed_payload(project_root: Path) -> None:
    """Give the repository a second top-level root to reference into."""
    payload = project_root / "payload"
    payload.mkdir(exist_ok=True)
    (payload / "anchor.md").write_text("anchor\n", encoding="utf-8", newline="\n")


def test_new_unstaged_file_resolves_exactly_as_after_staging(green_corpus: Path) -> None:
    """AC 1, direction 'new but unstaged': the check follows the working tree."""
    seed_payload(green_corpus)
    name_path(green_corpus, "payload/added.md")
    absent = repo_path_messages(green_corpus, "payload/added.md")

    (green_corpus / "payload" / "added.md").write_text("added\n", encoding="utf-8", newline="\n")
    unstaged = repo_path_messages(green_corpus, "payload/added.md")
    git(green_corpus, "add", "payload/added.md")
    staged = repo_path_messages(green_corpus, "payload/added.md")

    assert absent == (NOT_KNOWN,)
    assert unstaged == ()
    assert unstaged == staged


def test_deleted_unstaged_file_fails_exactly_as_after_staging(green_corpus: Path) -> None:
    """AC 1, direction 'deleted but unstaged': the check follows the working tree."""
    seed_payload(green_corpus)
    (green_corpus / "payload" / "doomed.md").write_text("doomed\n", encoding="utf-8", newline="\n")
    name_path(green_corpus, "payload/doomed.md")
    commit(green_corpus, "seed")
    present = repo_path_messages(green_corpus, "payload/doomed.md")

    (green_corpus / "payload" / "doomed.md").unlink()
    unstaged = repo_path_messages(green_corpus, "payload/doomed.md")
    git(green_corpus, "add", "-A")
    staged = repo_path_messages(green_corpus, "payload/doomed.md")

    assert present == ()
    assert unstaged == (ABSENT,)
    # Staging the deletion drops the path from git entirely, so the message
    # names the other unmet condition; the verdict the author sees is the same.
    assert staged == (NOT_KNOWN,)


def test_gitignored_working_tree_file_is_not_a_valid_reference(green_corpus: Path) -> None:
    """AC 5: ``.gitignore`` still keeps generated artefacts unreferenceable."""
    seed_payload(green_corpus)
    (green_corpus / ".gitignore").write_text("payload/generated.md\n", encoding="utf-8", newline="\n")
    (green_corpus / "payload" / "generated.md").write_text("generated\n", encoding="utf-8", newline="\n")
    name_path(green_corpus, "payload/generated.md")

    assert repo_path_messages(green_corpus, "payload/generated.md") == (NOT_KNOWN,)


def test_unresolved_repo_path_in_a_clean_tree_is_still_an_error(green_corpus: Path) -> None:
    """AC 5: a genuinely dead repository path is still rejected."""
    seed_payload(green_corpus)
    name_path(green_corpus, "payload/never_existed.md")
    commit(green_corpus, "name a dead path")
    git(green_corpus, "diff", "--quiet", "HEAD")

    assert repo_path_messages(green_corpus, "payload/never_existed.md") == (NOT_KNOWN,)


def test_case_variant_of_a_present_file_is_still_an_error(green_corpus: Path) -> None:
    """AC 5: membership stays case-sensitive on a case-insensitive filesystem."""
    seed_payload(green_corpus)
    (green_corpus / "payload" / "exact.md").write_text("exact\n", encoding="utf-8", newline="\n")
    name_path(green_corpus, "payload/Exact.md")

    assert repo_path_messages(green_corpus, "payload/Exact.md") == (NOT_KNOWN,)


def test_failing_git_call_is_incomplete_not_a_different_predicate(tmp_path: Path) -> None:
    """AC 4: without git the check declares itself INCOMPLETE and measures nothing.

    ``tmp_path`` is deliberately not a repository, so ``git ls-files`` really
    fails. There is no fallback left that would answer the same question with
    a different predicate under the same wording.
    """
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/domain-design/01-sample.md", concept_doc("DK-01"))

    result = run(tmp_path)

    assert result.complete is False
    assert result.incomplete_reason is not None
    assert "could not be discovered" in result.incomplete_reason
    assert result.findings == []


def test_symlink_with_a_missing_target_is_present_in_the_working_tree(green_corpus: Path) -> None:
    """AG3-234 F5: the presence probe measures the entry, not its target.

    A symlink is repository content in its own right. ``Path.exists`` follows
    it and would report "absent from the working tree" about an entry that is
    demonstrably there, so the message would state a predicate the code never
    evaluated.
    """
    seed_payload(green_corpus)
    link = green_corpus / "payload" / "dangling.md"
    try:
        link.symlink_to("no-such-target.md")
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform-gated
        pytest.skip(f"symlink creation unavailable: {exc}")
    name_path(green_corpus, "payload/dangling.md")

    assert repo_path_messages(green_corpus, "payload/dangling.md") == ()


def test_reference_to_a_missing_symlink_is_still_an_error(green_corpus: Path) -> None:
    """AC 5: measuring the entry does not make a truly absent entry resolve."""
    seed_payload(green_corpus)
    name_path(green_corpus, "payload/no-link-here.md")

    assert repo_path_messages(green_corpus, "payload/no-link-here.md") == (NOT_KNOWN,)
