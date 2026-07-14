"""CLI integration proof with fixed boundary evaluations and no live services."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from concept_governance.chunks import load_chunks
from concept_governance.git_scope import changed_concept_docs
from concept_governance.models import AuthorityProseResponse
from concept_governance.offline import OfflineEvaluations
from tests.unit.tools.concept_governance.helpers import write_doc, write_empty_baseline

SCRIPT = Path.cwd() / "scripts/ci/check_concept_authority_prose.py"


def test_pre_merge_scope_uses_only_changed_concept_markdown(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_doc(concept, "deleted.md", "DELETED", "[{scope: lock.deleted}]")
    write_doc(concept, "old-name.md", "RENAMED", "[{scope: lock.renamed}]")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "w2@example.invalid")
    _git(tmp_path, "config", "user.name", "W2 Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    owner = concept / "domain-design/owner.md"
    owner.write_text(owner.read_text(encoding="utf-8") + "\nChanged prose.\n", encoding="utf-8")
    _git(tmp_path, "rm", "concept/domain-design/deleted.md")
    _git(tmp_path, "mv", "concept/domain-design/old-name.md", "concept/domain-design/new-name.md")
    (tmp_path / "outside.txt").write_text("ignored", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "change")

    assert changed_concept_docs(tmp_path, concept, base) == frozenset(
        {
            "domain-design/deleted.md",
            "domain-design/new-name.md",
            "domain-design/old-name.md",
            "domain-design/owner.md",
        }
    )


def test_nightly_cli_passes_with_fixed_evaluations_and_no_index(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    offline = tmp_path / "evaluations.json"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    response = AuthorityProseResponse(has_normative_statements=False, assertions=())
    source = OfflineEvaluations(
        model="fixed/v1",
        classifications={chunk.chunk_id: response for chunk in load_chunks(concept)},
    )
    offline.write_text(source.model_dump_json(), encoding="utf-8")

    completed = _run(tmp_path, concept, baseline, offline)

    assert completed.returncode == 0
    assert "concept-authority-prose: PASS" in completed.stdout


def test_offline_missing_classification_fails_named_without_baseline_mutation(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    offline = tmp_path / "evaluations.json"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    before = baseline.read_bytes()
    offline.write_text(OfflineEvaluations(model="fixed/v1", classifications={}).model_dump_json(), encoding="utf-8")

    completed = _run(tmp_path, concept, baseline, offline)

    assert completed.returncode == 1
    assert "EVALUATION_PARSE_FAILURE" in completed.stdout
    assert baseline.read_bytes() == before


def _run(repo_root: Path, concept: Path, baseline: Path, offline: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, str(SCRIPT), "--repo-root", str(repo_root),
            "--concept-root", str(concept), "--baseline", str(baseline),
            "--mode", "nightly", "--offline-evaluations", str(offline),
        ],
        cwd=Path.cwd(), capture_output=True, text=True, check=False,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
    )
