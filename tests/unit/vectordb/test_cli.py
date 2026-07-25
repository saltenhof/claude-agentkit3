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

    import pytest

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

    Defers to FK-B for scope s.

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


# --------------------------------------------------------------------------- #
# R07: concept sync composes the productive engine and writes for real
# --------------------------------------------------------------------------- #


def test_r07_sync_writes_via_injected_service(tmp_path: Path) -> None:
    from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient, corpus_store

    from agentkit.backend.vectordb.cli import build_parser
    from agentkit.backend.vectordb.engine import WeaviateRetrievalPort
    from agentkit.backend.vectordb.mcp_server import McpToolService
    from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
    from agentkit.backend.vectordb.sync import SyncService

    root = _corpus(tmp_path)
    env = {
        "PROJECT_ID": "acme",
        "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
        "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
    }
    binding = RuntimeBinding.from_env(env, command="python", args=(), cwd=str(tmp_path))
    client = RecordingWeaviateClient()
    store = corpus_store(client)

    def real_factory(concepts_dir: Path) -> McpToolService:
        return McpToolService(
            binding=binding,
            retrieval=WeaviateRetrievalPort(client=client, store=store, binding=binding),  # type: ignore[arg-type]
            sync=SyncService(store=store),
            concepts_dir=concepts_dir, stories_dir=tmp_path,
        )

    parser = build_parser()
    args = parser.parse_args(["--concepts-dir", str(root), "sync", "--full"])
    args.service_factory = real_factory  # type: ignore[attr-defined]
    code = int(args.func(args))
    assert code == 0
    # Real writes happened (store populated with concept chunks).
    assert len(client.objects) > 0


def test_r07_sync_fails_closed_on_composition_error(tmp_path: Path) -> None:
    from agentkit.backend.vectordb.cli import build_parser

    def bad_factory(_concepts_dir: Path) -> object:
        raise RuntimeError("weaviate down")

    parser = build_parser()
    args = parser.parse_args(["--concepts-dir", str(tmp_path), "sync"])
    args.service_factory = bad_factory  # type: ignore[attr-defined]
    code = int(args.func(args))
    assert code == 3  # INTERNAL_FAILURE (fail-closed)


# --------------------------------------------------------------------------- #
# R08: validate --staged fails CLOSED (exit 3) on a git fault
# --------------------------------------------------------------------------- #


def test_r08_validate_staged_exit_3_on_git_fault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agentkit.backend.vectordb import cli as cli_mod

    root = _corpus(tmp_path)

    def _boom(*_a: object, **_k: object) -> str:
        raise cli_mod.GitOperationError("git exploded")

    monkeypatch.setattr(cli_mod, "_staged_concept_overlays", _boom)
    code = cli_main(["--concepts-dir", str(root), "validate", "--staged"])
    assert code == 3


def test_r08_validate_staged_consumes_deletions(tmp_path: Path) -> None:
    """A staged DELETION is represented as an empty overlay (R08)."""
    from agentkit.backend.vectordb.concept_corpus.candidate import build_candidate_corpus

    root = _corpus(tmp_path)
    dest = tmp_path / "cand"
    build_candidate_corpus(root, {"technical-design/b.md": ""}, dest=dest)
    assert not (dest / "technical-design" / "b.md").exists()
    assert (dest / "technical-design" / "a.md").exists()


# --------------------------------------------------------------------------- #
# N20: the CLI must not default onto AK3's OWN development corpus
# --------------------------------------------------------------------------- #


def test_n20_concepts_dir_has_no_default() -> None:
    """The concept corpus root is project configuration -- no silent default.

    Defaulting to the literal ``concept`` pointed every operation at AK3's own
    development corpus instead of the target project's configured ``concepts_dir``.
    """
    import pytest

    from agentkit.backend.vectordb.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["validate", "--corpus"])
    args = parser.parse_args(["--concepts-dir", "concepts", "validate", "--corpus"])
    assert args.concepts_dir == "concepts"


# --------------------------------------------------------------------------- #
# N27: the EXPLICIT administrative reclaim is an operator flag, never automatic
# --------------------------------------------------------------------------- #


def test_n27_sync_without_reclaim_is_rejected_on_a_held_claim(tmp_path: Path) -> None:
    """A claim left behind by a dead writer blocks the sync until an operator acts."""
    import pytest
    from tests.unit.vectordb.corpus_doubles import RecordingWeaviateClient, corpus_store

    from agentkit.backend.vectordb.cli import build_parser
    from agentkit.backend.vectordb.engine import WeaviateRetrievalPort
    from agentkit.backend.vectordb.mcp_server import McpToolService
    from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
    from agentkit.backend.vectordb.sync import ConcurrentSyncRejectedError, SyncService

    root = _corpus(tmp_path)
    env = {
        "PROJECT_ID": "acme",
        "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
        "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
    }
    binding = RuntimeBinding.from_env(env, command="python", args=(), cwd=str(tmp_path))
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    # A dead writer left a claim on the only concept source.
    dead = store.try_claim_source(
        project_id="acme", source_file="technical-design/a.md", owner_id="dead-writer"
    )
    assert dead is not None

    def factory(concepts_dir: Path) -> McpToolService:
        return McpToolService(
            binding=binding,
            retrieval=WeaviateRetrievalPort(client=client, store=store, binding=binding),  # type: ignore[arg-type]
            sync=SyncService(store=store, owner_id="cli-writer"),
            concepts_dir=concepts_dir, stories_dir=tmp_path,
        )

    parser = build_parser()
    args = parser.parse_args(["--concepts-dir", str(root), "sync"])
    args.service_factory = factory  # type: ignore[attr-defined]
    with pytest.raises(ConcurrentSyncRejectedError, match="administrative reclaim"):
        args.func(args)
    assert client.objects == {}

    # WITH the explicit operator flag the claim is taken over and the sync runs.
    reclaim_args = parser.parse_args(["--concepts-dir", str(root), "sync", "--reclaim"])
    reclaim_args.service_factory = factory  # type: ignore[attr-defined]
    assert int(reclaim_args.func(reclaim_args)) == 0
    assert len(client.objects) > 0
    assert any(
        record.get("reclaimed_from") == "dead-writer" for record in client.claim_history
    )
