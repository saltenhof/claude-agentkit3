"""Unit tests for the W4 decision-record gate against a real git repository."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from concept_toolchain.config import load_governance_config
from concept_toolchain.decision_gate import run_decision_gate
from tests.unit.concept_toolchain.conftest import concept_doc, write_doc, write_governance_config

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult

pytestmark = pytest.mark.requires_git

RECORD_TEXT = "---\ntitle: Decision\n---\n\n# Decision\n\nRationale.\n"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return completed.stdout


def init_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "toolchain-test@example.com")
    git(tmp_path, "config", "user.name", "Toolchain Test")
    git(tmp_path, "config", "core.autocrlf", "false")
    write_governance_config(tmp_path)
    write_doc(tmp_path, "concept/domain-design/01-sample.md", concept_doc("DK-01"))
    write_doc(tmp_path, "concept/technical-design/10_sample.md", concept_doc("FK-10"))
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base corpus")
    return tmp_path


def run(repo: Path, base: str, trailers: list[str] | None = None) -> CheckResult:
    return run_decision_gate(repo, load_governance_config(repo), base, trailers or [])


def append_normative_sentence(repo: Path) -> None:
    path = repo / "concept/technical-design/10_sample.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nDas System MUSS dieses Verhalten erzwingen.\n", encoding="utf-8")


def test_clean_tree_passes(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    result = run(repo, "HEAD")
    assert result.findings == []
    assert result.complete is True


def test_normative_change_without_record_fails(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    result = run(repo, "HEAD")
    assert any(finding.check_id == "decision-gate.missing-record" for finding in result.findings)


def test_record_in_same_diff_satisfies_gate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    write_doc(repo, "concept/_meta/decisions/2026-07-19-sample-decision.md", RECORD_TEXT)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "normative change with record")
    result = run(repo, "HEAD~1")
    assert result.findings == []


def test_malformed_record_name_is_error(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    write_doc(repo, "concept/_meta/decisions/Bad_Name.md", RECORD_TEXT)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "normative change with malformed record")
    result = run(repo, "HEAD~1")
    ids = {finding.check_id for finding in result.findings}
    assert "decision-gate.record-name" in ids
    assert "decision-gate.missing-record" in ids


def test_trailer_option_references_existing_record(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write_doc(repo, "concept/_meta/decisions/2026-07-19-sample-decision.md", RECORD_TEXT)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add record")
    append_normative_sentence(repo)
    result = run(repo, "HEAD", trailers=["2026-07-19-sample-decision"])
    assert result.findings == []


def test_dead_trailer_reference_is_error(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    result = run(repo, "HEAD", trailers=["2026-07-19-nonexistent"])
    ids = {finding.check_id for finding in result.findings}
    assert "decision-gate.dead-reference" in ids
    assert "decision-gate.missing-record" in ids


def test_commit_trailer_satisfies_gate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    write_doc(repo, "concept/_meta/decisions/2026-07-19-sample-decision.md", RECORD_TEXT)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add record")
    append_normative_sentence(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change\n\nConcept-Decision: 2026-07-19-sample-decision")
    result = run(repo, "HEAD~1")
    assert result.findings == []


def test_format_only_trailer_exempts_non_normative_diff(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    path = repo / "concept/technical-design/10_sample.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Body text.", "Body  text."), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "whitespace\n\nConcept-Format-Only: double space typo fix")
    result = run(repo, "HEAD~1")
    assert result.findings == []


def test_format_only_never_covers_normative_modal(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "sneaky\n\nConcept-Format-Only: pretend format fix")
    result = run(repo, "HEAD~1")
    assert any(finding.check_id == "decision-gate.missing-record" for finding in result.findings)


def test_empty_format_only_reason_is_error(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    path = repo / "concept/technical-design/10_sample.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Body text.", "Body  text."), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "whitespace\n\nConcept-Format-Only:")
    result = run(repo, "HEAD~1")
    assert any(finding.check_id == "decision-gate.format-only" for finding in result.findings)


def test_ambiguous_change_without_format_only_requires_record(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    path = repo / "concept/technical-design/10_sample.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nA new descriptive sentence.\n", encoding="utf-8")
    result = run(repo, "HEAD")
    assert any(finding.check_id == "decision-gate.missing-record" for finding in result.findings)


def test_unresolvable_base_is_incomplete(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    result = run(repo, "no-such-revision")
    assert result.complete is False
    assert result.incomplete_reason is not None


def write_normative_doc(repo: Path, relative: str, concept_id: str) -> None:
    """Write a brand-new normative concept document without staging it."""
    write_doc(repo, relative, concept_doc(concept_id, body="Das System MUSS dieses Verhalten erzwingen.\n"))


def test_untracked_concept_document_is_seen_and_does_not_short_circuit(tmp_path: Path) -> None:
    """AC 2: a never-staged normative document is the change class this gate exists for."""
    repo = init_repo(tmp_path)
    write_normative_doc(repo, "concept/technical-design/11_brand_new.md", "FK-11")

    result = run(repo, "HEAD")

    assert result.summary != "no concept documents changed"
    assert any(finding.check_id == "decision-gate.missing-record" for finding in result.findings)
    assert any(finding.path == "concept/technical-design/11_brand_new.md" for finding in result.findings)


def test_new_unstaged_document_is_scoped_exactly_as_after_staging(tmp_path: Path) -> None:
    """AC 1, direction 'new but unstaged'."""
    repo = init_repo(tmp_path)
    write_normative_doc(repo, "concept/technical-design/11_brand_new.md", "FK-11")
    unstaged = run(repo, "HEAD")
    git(repo, "add", "concept/technical-design/11_brand_new.md")
    staged = run(repo, "HEAD")

    assert unstaged.summary == staged.summary
    assert [finding.check_id for finding in unstaged.findings] == [finding.check_id for finding in staged.findings]
    assert unstaged.summary == "1 changed concept document(s) evaluated"


def test_deleted_unstaged_document_is_scoped_exactly_as_after_staging(tmp_path: Path) -> None:
    """AC 1, direction 'deleted but unstaged'."""
    repo = init_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD").strip()

    (repo / "concept/technical-design/10_sample.md").unlink()
    unstaged = run(repo, base)
    git(repo, "add", "-A")
    staged = run(repo, base)

    assert unstaged.summary == staged.summary
    assert unstaged.summary == "1 changed concept document(s) evaluated"


def test_ignored_markdown_is_not_a_concept_change(tmp_path: Path) -> None:
    """AC 5: ``--exclude-standard`` keeps generated Markdown out of the change set."""
    repo = init_repo(tmp_path)
    (repo / ".gitignore").write_text("concept/technical-design/99_generated.md\n", encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ignore generated output")
    write_normative_doc(repo, "concept/technical-design/99_generated.md", "FK-99")

    result = run(repo, "HEAD")

    assert result.summary == "no concept documents changed"
    assert result.findings == []


def test_uncommitted_record_does_not_satisfy_a_commit_trailer(tmp_path: Path) -> None:
    """AC 3: a commit's own justification must exist in the commit graph.

    Before the fix this run was entirely green: ``is_file()`` accepted a
    record that no commit contains, and the untracked record was invisible
    to the diff, so nothing else objected either. Now the unverifiable claim
    is an ERROR. The record still counts as an in-flight addition -- it is a
    real working-tree change -- so ``missing-record`` is deliberately absent;
    what closed is the trailer's free pass, not the change set.
    """
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    git(repo, "add", "concept/technical-design/10_sample.md")
    git(repo, "commit", "-q", "-m", "change\n\nConcept-Decision: 2026-08-06-uncommitted")
    write_doc(repo, "concept/_meta/decisions/2026-08-06-uncommitted.md", RECORD_TEXT)

    result = run(repo, "HEAD~1")

    dead = [finding for finding in result.findings if finding.check_id == "decision-gate.dead-reference"]
    assert len(dead) == 1
    assert "does not resolve to a record committed at HEAD" in dead[0].message
    assert result.findings != []


def test_commit_trailer_for_an_absent_record_is_not_green(tmp_path: Path) -> None:
    """AC 3, the pure case: nothing on disk, nothing in history, nothing green."""
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change\n\nConcept-Decision: 2026-08-06-never-written")

    result = run(repo, "HEAD~1")

    ids = {finding.check_id for finding in result.findings}
    assert ids == {"decision-gate.dead-reference", "decision-gate.missing-record"}


def test_committed_record_still_satisfies_a_commit_trailer(tmp_path: Path) -> None:
    """The legitimate case stays green: the record is in the commit graph."""
    repo = init_repo(tmp_path)
    write_doc(repo, "concept/_meta/decisions/2026-08-06-committed.md", RECORD_TEXT)
    append_normative_sentence(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change\n\nConcept-Decision: 2026-08-06-committed")

    assert run(repo, "HEAD~1").findings == []


def test_cli_trailer_accepts_a_never_staged_record(tmp_path: Path) -> None:
    """A ``--trailer`` names work in preparation, so the working tree may vouch."""
    repo = init_repo(tmp_path)
    append_normative_sentence(repo)
    write_doc(repo, "concept/_meta/decisions/2026-08-06-in-flight.md", RECORD_TEXT)

    assert run(repo, "HEAD", trailers=["2026-08-06-in-flight"]).findings == []


def test_cli_trailer_rejects_an_ignored_record(tmp_path: Path) -> None:
    """AC 5: an ignored file is not versionable content and vouches for nothing."""
    repo = init_repo(tmp_path)
    (repo / ".gitignore").write_text("concept/_meta/decisions/\n", encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ignore local decision scratch")
    append_normative_sentence(repo)
    write_doc(repo, "concept/_meta/decisions/2026-08-06-local-only.md", RECORD_TEXT)

    result = run(repo, "HEAD", trailers=["2026-08-06-local-only"])

    dead = [finding for finding in result.findings if finding.check_id == "decision-gate.dead-reference"]
    assert len(dead) == 1
    assert "does not name versionable repository content" in dead[0].message


def test_cli_trailer_rejects_a_deleted_but_still_indexed_record(tmp_path: Path) -> None:
    """AC 5: known to git is not enough; the record must be there now."""
    repo = init_repo(tmp_path)
    write_doc(repo, "concept/_meta/decisions/2026-08-06-vanished.md", RECORD_TEXT)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add record")
    append_normative_sentence(repo)
    (repo / "concept/_meta/decisions/2026-08-06-vanished.md").unlink()

    result = run(repo, "HEAD", trailers=["2026-08-06-vanished"])

    dead = [finding for finding in result.findings if finding.check_id == "decision-gate.dead-reference"]
    assert len(dead) == 1
    assert "is known to git but absent from the working tree" in dead[0].message
