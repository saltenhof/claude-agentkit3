"""Semantic-status accounting tests (FK-78 section 78.14)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import semantic_gate
from concept_toolchain.config import load_governance_config
from concept_toolchain.semantic_status import run_semantic_status
from tests.unit.concept_toolchain.runfixtures import WRITER_ARGS, RunFixture, build_promotion_run
from tests.unit.concept_toolchain.test_semantic_gate import find_pack, make_receipt

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=False)


def run_check(fixture: RunFixture) -> CheckResult:
    config = load_governance_config(fixture.project_root)
    return run_semantic_status(fixture.project_root, config, fixture.run_dir)


def finding_messages(result: CheckResult) -> str:
    return " | ".join(f"{finding.locator}: {finding.message}" for finding in result.findings)


def prepare_both_gates(fixture: RunFixture) -> None:
    for gate in ("w2", "w3"):
        arguments = ["--project-root", str(fixture.project_root), "prepare", fixture.run_rel, *WRITER_ARGS, "--gate", gate]
        assert semantic_gate.main(arguments) == 0


def import_receipt(fixture: RunFixture, gate_key: str, *, status: str = "passed") -> None:
    receipt_path = make_receipt(fixture, gate_key, status=status)
    arguments = ["--project-root", str(fixture.project_root), "import", fixture.run_rel, *WRITER_ARGS, str(receipt_path)]
    assert semantic_gate.main(arguments) == 0


def test_unprepared_gates_contradict_passed_manifest(fixture: RunFixture) -> None:
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "recorded status 'passed' does not match computed 'not_run'" in combined


def test_missing_receipt_blocks_scope(fixture: RunFixture) -> None:
    prepare_both_gates(fixture)
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "no valid receipt for gate 'authority-prose'; blocking scope 'sample-scope'" in combined
    assert "recorded status 'passed' does not match computed 'blocked'" in combined
    assert "recorded blocking_scope_ids [-] do not match computed [sample-scope]" in combined


def test_full_green_settlement(fixture: RunFixture) -> None:
    prepare_both_gates(fixture)
    import_receipt(fixture, "w2")
    import_receipt(fixture, "w3")
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_failed_receipt_blocks_scope(fixture: RunFixture) -> None:
    prepare_both_gates(fixture)
    import_receipt(fixture, "w2", status="failed")
    import_receipt(fixture, "w3")
    result = run_check(fixture)
    assert "receipt status 'failed' blocks scope 'sample-scope'" in finding_messages(result)


def test_tampered_pack_request_digest_is_error(fixture: RunFixture) -> None:
    prepare_both_gates(fixture)
    pack_path = find_pack(fixture, "w2")
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    payload["request_digest"] = "0" * 64
    pack_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = run_check(fixture)
    assert "does not match the canonical digest" in finding_messages(result)


def test_stale_chunks_block_scope(fixture: RunFixture) -> None:
    prepare_both_gates(fixture)
    import_receipt(fixture, "w2")
    import_receipt(fixture, "w3")
    target = fixture.project_root / fixture.target_rel
    target.write_text(target.read_text(encoding="utf-8") + "\nDrifted after review.\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "request pack is stale" in finding_messages(result)


def test_receipt_without_pack_is_error(fixture: RunFixture) -> None:
    prepare_both_gates(fixture)
    import_receipt(fixture, "w2")
    import_receipt(fixture, "w3")
    receipts_dir = fixture.run_dir / "semantic" / "receipts"
    stray = json.loads(next(iter(sorted(receipts_dir.glob("*.json")))).read_text(encoding="utf-8"))
    stray["request_digest"] = "2" * 64
    (receipts_dir / "stray.json").write_text(json.dumps(stray, indent=2), encoding="utf-8")
    result = run_check(fixture)
    assert "receipt does not match any request pack" in finding_messages(result)


def test_missing_run_dir_is_incomplete(green_corpus: Path) -> None:
    config = load_governance_config(green_corpus)
    result = run_semantic_status(green_corpus, config, green_corpus / "concept-incubator" / "runs" / "missing")
    assert result.complete is False
