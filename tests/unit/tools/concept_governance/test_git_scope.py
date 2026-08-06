"""Pre-merge scoping against a real git repository (AG3-234 F3).

Every test runs against a repository created by ``git init`` in ``tmp_path``.
The defect these tests pin down is not reachable with a fake: it lives in
the difference between what ``git diff`` can report and what is actually in
the working tree, and only git knows that difference.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from concept_governance.chunks import load_chunks
from concept_governance.git_scope import GitScopeError, changed_concept_docs
from tests.unit.tools.concept_governance.helpers import write_doc

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.requires_git


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, encoding="utf-8"
    )
    return completed.stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.email=w2@example.invalid",
        "-c",
        "user.name=W2 Test",
        "commit",
        "-q",
        "-m",
        message,
    )


def _seed(tmp_path: Path) -> tuple[Path, str]:
    """Create a repository with one committed concept document."""
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "DK-01", "[{scope: lock.lifecycle}]")
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "base")
    return concept, _git(tmp_path, "rev-parse", "HEAD").strip()


def test_untracked_concept_document_enters_the_pre_merge_scope(tmp_path: Path) -> None:
    """F3: a freshly written document is a change before anyone stages it."""
    concept, base = _seed(tmp_path)
    write_doc(concept, "fresh.md", "DK-02", "[{scope: lock.fresh}]")

    assert changed_concept_docs(tmp_path, concept, base) == frozenset({"domain-design/fresh.md"})


def test_new_unstaged_document_is_scoped_exactly_as_after_staging(tmp_path: Path) -> None:
    """AC 1, direction 'new but unstaged'."""
    concept, base = _seed(tmp_path)
    write_doc(concept, "fresh.md", "DK-02", "[{scope: lock.fresh}]")
    unstaged = changed_concept_docs(tmp_path, concept, base)
    _git(tmp_path, "add", "concept/domain-design/fresh.md")
    staged = changed_concept_docs(tmp_path, concept, base)

    assert unstaged == staged
    assert "domain-design/fresh.md" in unstaged


def test_deleted_unstaged_document_is_scoped_exactly_as_after_staging(tmp_path: Path) -> None:
    """AC 1, direction 'deleted but unstaged'."""
    concept, base = _seed(tmp_path)
    write_doc(concept, "doomed.md", "DK-02", "[{scope: lock.doomed}]")
    _commit(tmp_path, "add doomed")

    (concept / "domain-design" / "doomed.md").unlink()
    unstaged = changed_concept_docs(tmp_path, concept, base)
    _git(tmp_path, "add", "-A")
    staged = changed_concept_docs(tmp_path, concept, base)

    assert unstaged == staged
    assert "domain-design/doomed.md" in unstaged


def test_ignored_markdown_stays_out_of_the_pre_merge_scope(tmp_path: Path) -> None:
    """AC 5: ``--exclude-standard`` still keeps generated Markdown out."""
    concept, base = _seed(tmp_path)
    (tmp_path / ".gitignore").write_text("concept/domain-design/generated.md\n", encoding="utf-8")
    _commit(tmp_path, "ignore generated output")
    write_doc(concept, "generated.md", "DK-99", "[{scope: lock.generated}]")

    assert changed_concept_docs(tmp_path, concept, base) == frozenset()


def test_untracked_document_reaches_the_chunk_loader(tmp_path: Path) -> None:
    """F3, end of chain: the corrected selection survives into ``load_chunks``.

    ``load_chunks`` was never the defect -- it reads the working tree either
    way. What was broken is what it got handed, so the proof belongs here.
    """
    concept, base = _seed(tmp_path)
    write_doc(concept, "fresh.md", "DK-02", "[{scope: lock.fresh}]")

    included = changed_concept_docs(tmp_path, concept, base)
    chunks = load_chunks(concept, included)

    assert [chunk.rel_path for chunk in chunks] == ["domain-design/fresh.md"]


def test_unresolvable_base_fails_closed(tmp_path: Path) -> None:
    """AC 5: an unusable range is an error, never an empty scope."""
    concept, _base = _seed(tmp_path)

    with pytest.raises(GitScopeError):
        changed_concept_docs(tmp_path, concept, "no-such-revision")


def test_concept_root_outside_repo_root_fails_closed(tmp_path: Path) -> None:
    """AC 5: the pre-existing containment guard is untouched."""
    _concept, base = _seed(tmp_path)

    with pytest.raises(GitScopeError):
        changed_concept_docs(tmp_path, tmp_path.parent / "elsewhere", base)
