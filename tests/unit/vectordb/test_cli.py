"""Three-rings CLI tests (FK-13 §13.9.9, AC12).

Proves the operations exist on the same SSOT, ``validate --staged`` blocks a NEW
cross-file error over the candidate corpus, and ``--strict`` escalates warnings.
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.cli import main as cli_main
from agentkit.backend.vectordb.concept_corpus.candidate import build_candidate_corpus
from agentkit.backend.vectordb.concept_corpus.validator import validate_corpus
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from pathlib import Path

A = dedent(
    """\
    ---
    concept_id: FK-A
    title: A
    module: m
    status: active
    doc_kind: core
    defers_to:
      - target: FK-B
        scope: s
        reason: r
    ---

    # A

    ## One

    text.
    """
)
B = dedent(
    """\
    ---
    concept_id: FK-B
    title: B
    module: m
    status: active
    doc_kind: core
    authority_over:
      - scope: s
    ---

    # B

    ## One

    text.
    """
)


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "a.md").write_text(A, encoding="utf-8")
    (root / "b.md").write_text(B, encoding="utf-8")
    return tmp_path / "concept"


def test_validate_staged_blocks_new_cross_file_error(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    # Working corpus is valid.
    report = validate_corpus(discover_concept_files(root))
    assert not report.has_errors
    # Stage a DELETION of b.md -> FK-A.defers_to FK-B now dangles (E-REF-001).
    dest = tmp_path / "candidate"
    build_candidate_corpus(root, {"technical-design/b.md": ""}, dest=dest)
    candidate_report = validate_corpus(discover_concept_files(dest))
    assert candidate_report.has_errors
    assert any(f.code == "E-REF-001" for f in candidate_report.errors)


def test_validate_staged_blocks_new_duplicate(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    # Stage a NEW file that duplicates FK-A's concept_id -> E-ID-001.
    overlay = {"technical-design/a_dup.md": A}
    dest = tmp_path / "candidate"
    build_candidate_corpus(root, overlay, dest=dest)
    candidate_report = validate_corpus(discover_concept_files(dest))
    assert any(f.code == "E-ID-001" for f in candidate_report.errors)


def test_cli_validate_corpus_exit_zero(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    code = cli_main(["--concepts-dir", str(root), "validate", "--corpus"])
    assert code == 0


def test_cli_validate_strict_escalates(tmp_path: Path) -> None:
    # An orphan concept -> W-ORPHAN-001; --strict -> exit 2.
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "orphan.md").write_text(
        dedent(
            """\
            ---
            concept_id: FK-ORPHAN
            title: O
            module: m
            status: active
            doc_kind: core
            ---

            # O

            ## One

            text.
            """
        ),
        encoding="utf-8",
    )
    loose = cli_main(["--concepts-dir", str(tmp_path / "concept"), "validate", "--corpus"])
    strict = cli_main(
        ["--concepts-dir", str(tmp_path / "concept"), "validate", "--corpus", "--strict"]
    )
    assert loose == 1  # warnings only
    assert strict == 2  # escalated to errors


def test_cli_lint_and_doctor_run(tmp_path: Path, capsys: object) -> None:

    root = _corpus(tmp_path)
    assert cli_main(["--concepts-dir", str(root), "lint"]) == 0
    assert cli_main(["--concepts-dir", str(root), "doctor", "--summary"]) == 0


def test_cli_build_writes_artifacts(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    out = tmp_path / "build"
    code = cli_main(["--concepts-dir", str(root), "build", "--out-dir", str(out)])
    assert code == 0
    assert (out / "INDEX.yaml").is_file()
    assert (out / "concept_graph.json").is_file()
    data = json.loads((out / "concept_graph.json").read_text(encoding="utf-8"))
    assert data["corpus_revision"]


def test_cli_build_blocked_on_errors(tmp_path: Path) -> None:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "broken.md").write_text("no frontmatter", encoding="utf-8")
    code = cli_main(["--concepts-dir", str(tmp_path / "concept"), "build"])
    assert code == 2
