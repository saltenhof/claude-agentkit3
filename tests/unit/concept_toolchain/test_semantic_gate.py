"""Mutating semantic-gate CLI tests (FK-78 78.14): writer gate, units, prepare, import."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel, semantic_gate
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.runfixtures import WRITER_ARGS, RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=False)


def gate_cli(fixture: RunFixture, command: str, *args: str, writer: tuple[str, ...] = WRITER_ARGS) -> int:
    return semantic_gate.main(["--project-root", str(fixture.project_root), command, fixture.run_rel, *writer, *args])


def find_pack(fixture: RunFixture, gate_key: str) -> Path:
    packs = sorted((fixture.run_dir / "semantic" / "requests").glob(f"{gate_key}-*.json"))
    assert len(packs) == 1, packs
    return packs[0]


def make_receipt(fixture: RunFixture, gate_key: str, *, status: str = "passed") -> Path:
    pack = json.loads(find_pack(fixture, gate_key).read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.0.0",
        "gate": pack["gate"],
        "request_digest": pack["request_digest"],
        "model": "review-model",
        "principal_id": "rev.bob",
        "session_ref": "sess-review",
        "status": status,
        "findings": [],
        "chunk_digests": [chunk["digest"] for chunk in pack["chunks"]],
        "completed_at": "2026-07-19T11:00:00Z",
    }
    receipt_path = fixture.project_root / f"receipt-input-{gate_key}.json"
    receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return receipt_path


def test_units_is_deterministic_and_idempotent(fixture: RunFixture) -> None:
    fixture.units_path.unlink()
    assert gate_cli(fixture, "units") == 0
    first = fixture.units_path.read_bytes()
    assert gate_cli(fixture, "units") == 0
    assert fixture.units_path.read_bytes() == first
    rows, issues = runmodel.load_source_units(fixture.units_path, require_disposition=False)
    assert issues == []
    assert len(rows) == 4


def test_units_preserves_existing_claim_refs(fixture: RunFixture) -> None:
    before = fixture.units_path.read_bytes()
    assert gate_cli(fixture, "units") == 0
    assert fixture.units_path.read_bytes() == before


def test_units_refuses_overwrite_on_digest_drift(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    lines = fixture.units_path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    fields = lines[1].split("\t")
    fields[3] = "0" * 64
    lines[1] = "\t".join(fields)
    fixture.units_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    tampered = fixture.units_path.read_bytes()
    assert gate_cli(fixture, "units") == 1
    assert "refusing overwrite" in capsys.readouterr().out
    assert fixture.units_path.read_bytes() == tampered


def test_units_appends_new_source_units_with_next_counter(fixture: RunFixture) -> None:
    extra = fixture.run_dir / "synthesis" / "po-decision-scope.md"
    extra.write_text("# PO Decision\n\nDecision input.\n", encoding="utf-8", newline="\n")
    register = fixture.run_dir / "baseline" / "source-register.tsv"
    source_id = f"SRC-{fixture.uuid8}-0005"
    row = (
        f"{source_id}\tderived\tPO_DECISION\t{fixture.run_rel}/synthesis/po-decision-scope.md"
        f"\t{runfixtures.sha_file(extra)}\t\t\torch.alice\t{runfixtures.SRC_SYNTHESIS}"
    )
    register.write_text(register.read_text(encoding="utf-8") + row + "\n", encoding="utf-8", newline="\n")
    assert gate_cli(fixture, "units") == 0
    rows, _ = runmodel.load_source_units(fixture.units_path, require_disposition=False)
    new_rows = [unit_row for unit_row in rows if unit_row["source_id"] == source_id]
    assert [unit_row["unit_id"] for unit_row in new_rows] == [f"SU-{fixture.uuid8}-0005"]
    assert new_rows[0]["claim_refs"] == "" and new_rows[0]["empty_reason"] == ""


def test_mutations_require_lease(fixture: RunFixture) -> None:
    (fixture.run_dir / "LEASE.json").unlink()
    assert gate_cli(fixture, "units") == 2


def test_released_lease_blocks_mutations(fixture: RunFixture) -> None:
    lease_path = fixture.run_dir / "LEASE.json"
    payload = json.loads(lease_path.read_text(encoding="utf-8"))
    payload["released"] = True
    runfixtures.write_json(lease_path, payload)
    assert gate_cli(fixture, "units") == 2


def test_expired_lease_blocks_mutations(fixture: RunFixture) -> None:
    lease_path = fixture.run_dir / "LEASE.json"
    payload = json.loads(lease_path.read_text(encoding="utf-8"))
    payload["acquired_at"] = "2020-01-01T00:00:00Z"
    runfixtures.write_json(lease_path, payload)
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 2


def test_foreign_principal_blocks_mutations(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    writer = ("--principal", "mallory", "--session", "sess-orch", "--fencing-token", "1")
    assert gate_cli(fixture, "units", writer=writer) == 2
    assert "does not match --principal 'mallory'" in capsys.readouterr().err


def test_foreign_session_blocks_mutations(fixture: RunFixture) -> None:
    writer = ("--principal", "orch.alice", "--session", "sess-other", "--fencing-token", "1")
    assert gate_cli(fixture, "units", writer=writer) == 2


def test_wrong_fencing_token_blocks_mutations(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    writer = ("--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "9")
    assert gate_cli(fixture, "units", writer=writer) == 2
    assert "fencing token mismatch" in capsys.readouterr().err


def write_mutex(fixture: RunFixture, *, heartbeat: str, nonce: str = "foreign-nonce") -> None:
    runfixtures.write_json(
        fixture.run_dir / "RUN.mutex",
        {
            "owner_principal": "other.writer",
            "owner_session": "sess-other",
            "nonce": nonce,
            "acquired_at": heartbeat,
            "heartbeat_at": heartbeat,
            "ttl_seconds": 600,
        },
    )


def test_live_mutation_mutex_blocks_mutations(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    write_mutex(fixture, heartbeat=runfixtures.now_utc())
    assert gate_cli(fixture, "units") == 2
    assert "RUN.mutex is held by 'other.writer'" in capsys.readouterr().err
    assert (fixture.run_dir / "RUN.mutex").is_file()


def test_malformed_mutex_blocks_mutations(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    (fixture.run_dir / "RUN.mutex").write_text("held", encoding="utf-8")
    assert gate_cli(fixture, "units") == 2
    assert "not a valid mutex payload" in capsys.readouterr().err


def test_expired_mutex_takeover_requires_matching_fencing_token(fixture: RunFixture) -> None:
    write_mutex(fixture, heartbeat="2020-01-01T00:00:00Z")
    writer = ("--principal", "orch.alice", "--session", "sess-orch", "--fencing-token", "9")
    assert gate_cli(fixture, "units", writer=writer) == 2
    assert (fixture.run_dir / "RUN.mutex").is_file()


def test_expired_mutex_is_taken_over_with_matching_token(fixture: RunFixture) -> None:
    write_mutex(fixture, heartbeat="2020-01-01T00:00:00Z")
    assert gate_cli(fixture, "units") == 0
    assert not (fixture.run_dir / "RUN.mutex").exists()


def test_release_never_deletes_a_foreign_mutex(fixture: RunFixture) -> None:
    """Compare-before-delete: a mutex replaced mid-run is left alone."""
    nonce = "foreign-nonce"
    semantic_gate._atomic_write_bytes(  # noqa: SLF001 - exercising the release guard directly
        fixture.run_dir / "RUN.mutex",
        json.dumps(
            {
                "owner_principal": "other.writer",
                "owner_session": "sess-other",
                "nonce": nonce,
                "acquired_at": runfixtures.now_utc(),
                "heartbeat_at": runfixtures.now_utc(),
                "ttl_seconds": 600,
            }
        ).encode("utf-8"),
    )
    foreign = semantic_gate._MutexGuard(  # noqa: SLF001 - release guard under test
        fixture.run_dir, "our-different-nonce", "orch.alice", "sess-orch"
    )
    foreign.release()
    assert (fixture.run_dir / "RUN.mutex").is_file()
    owner = semantic_gate._MutexGuard(fixture.run_dir, nonce, "other.writer", "sess-other")  # noqa: SLF001 - under test
    owner.release()
    assert not (fixture.run_dir / "RUN.mutex").exists()
    assert not (fixture.run_dir / semantic_gate.INTENT_NAME).exists()


def test_mutex_is_released_after_mutation(fixture: RunFixture) -> None:
    assert gate_cli(fixture, "units") == 0
    assert not (fixture.run_dir / "RUN.mutex").exists()


def test_missing_writer_arguments_is_usage_error(fixture: RunFixture) -> None:
    with pytest.raises(SystemExit) as excinfo:
        semantic_gate.main(["--project-root", str(fixture.project_root), "units", fixture.run_rel])
    assert excinfo.value.code == 3


def test_prepare_writes_reproducible_request_packs(fixture: RunFixture) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    pack_path = find_pack(fixture, "w2")
    first = pack_path.read_bytes()
    pack, issues = runmodel.load_semantic_request_pack(pack_path)
    assert issues == []
    assert pack is not None
    assert pack.gate == "authority-prose"
    assert pack.chunks[0].path == fixture.target_rel
    assert pack.request_digest[:16] in pack_path.name
    pack_path.unlink()
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    assert find_pack(fixture, "w2").read_bytes() == first


def test_prepare_is_noop_for_unchanged_pack(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w3") == 0
    capsys.readouterr()
    assert gate_cli(fixture, "prepare", "--gate", "w3") == 0
    assert "no-op" in capsys.readouterr().out


def test_prepare_refuses_conflicting_pack_for_same_scope(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    target = fixture.project_root / fixture.target_rel
    target.write_text(target.read_text(encoding="utf-8") + "\n\n", encoding="utf-8", newline="\n")
    runfixtures.refresh_target_bindings(fixture)
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 1
    assert "refusing to overwrite" in capsys.readouterr().out
    assert len(sorted((fixture.run_dir / "semantic" / "requests").glob("w2-*.json"))) == 1


def test_prepare_rejects_unknown_gate(fixture: RunFixture) -> None:
    with pytest.raises(SystemExit) as excinfo:
        gate_cli(fixture, "prepare", "--gate", "w9")
    assert excinfo.value.code == 3


def test_import_registers_receipt_and_is_idempotent(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    receipt_path = make_receipt(fixture, "w2")
    assert gate_cli(fixture, "import", str(receipt_path)) == 0
    stored = sorted((fixture.run_dir / "semantic" / "receipts").glob("*.json"))
    assert len(stored) == 1
    capsys.readouterr()
    assert gate_cli(fixture, "import", str(receipt_path)) == 0
    assert "no-op" in capsys.readouterr().out


def test_import_rejects_conflicting_content_for_same_digest(fixture: RunFixture) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    receipt_path = make_receipt(fixture, "w2")
    assert gate_cli(fixture, "import", str(receipt_path)) == 0
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["model"] = "another-model"
    receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert gate_cli(fixture, "import", str(receipt_path)) == 1


def test_import_rejects_receipt_without_matching_pack(fixture: RunFixture) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    receipt_path = make_receipt(fixture, "w2")
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["request_digest"] = "0" * 64
    receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert gate_cli(fixture, "import", str(receipt_path)) == 1


def test_import_rejects_chunk_digest_mismatch(fixture: RunFixture) -> None:
    assert gate_cli(fixture, "prepare", "--gate", "w2") == 0
    receipt_path = make_receipt(fixture, "w2")
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["chunk_digests"] = ["1" * 64]
    receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert gate_cli(fixture, "import", str(receipt_path)) == 1


def test_json_envelope_output(fixture: RunFixture, capsys: pytest.CaptureFixture[str]) -> None:
    code = semantic_gate.main(
        ["--project-root", str(fixture.project_root), "--json", "units", fixture.run_rel, *WRITER_ARGS]
    )
    assert code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "units"
    assert envelope["check_set"] == ["units"]
    assert envelope["complete"] is True
    assert envelope["findings"] == []
