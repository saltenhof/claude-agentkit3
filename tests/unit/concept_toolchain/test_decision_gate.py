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
