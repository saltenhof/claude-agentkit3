"""Fail-closed artifact loader tests (FK-78 sections 78.3/78.4/78.6-78.14)."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from concept_toolchain import runmodel

if TYPE_CHECKING:
    from pathlib import Path

SHA = hashlib.sha256(b"x").hexdigest()
RUN_ID = "2026-07-19-mini-ab12cd34"


def valid_run_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "title": "Mini run",
        "profile": "LIGHT_INCUBATION",
        "state": "FRAMING",
        "state_revision": 1,
        "lease_fencing_token": 1,
        "current_round": 0,
        "base_revision": {"kind": "git", "value": "abc123"},
        "data_class": "internal",
        "actor": {
            "role": "council-orchestrator",
            "harness": "claude-code",
            "model": "m",
            "principal_id": "orch.alice",
            "session_ref": "sess-1",
        },
        "participants": [],
        "register_digests": dict.fromkeys(runmodel.REGISTER_DIGEST_KEYS),
        "blocked": None,
        "recheck": None,
        "last_completed_action": "run-created",
        "next_action": "freeze-baseline",
        "updated_at": "2026-07-19T10:00:00Z",
    }


def write_payload(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def messages(issues: list[runmodel.Issue]) -> str:
    return " | ".join(f"{issue.locator}: {issue.message}" for issue in issues)


def test_valid_run_state_loads(tmp_path: Path) -> None:
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", valid_run_payload()))
    assert issues == []
    assert run is not None
    assert run.run_uuid8 == "ab12cd34"


def test_unknown_run_field_is_fail_closed(tmp_path: Path) -> None:
    payload = valid_run_payload() | {"surprise": 1}
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", payload))
    assert run is None
    assert "unknown field 'surprise'" in messages(issues)


def test_missing_run_field_is_fail_closed(tmp_path: Path) -> None:
    payload = valid_run_payload()
    del payload["profile"]
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", payload))
    assert run is None
    assert "missing required field 'profile'" in messages(issues)


def test_invalid_state_enum_rejected(tmp_path: Path) -> None:
    payload = valid_run_payload() | {"state": "DANCING"}
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", payload))
    assert run is None
    assert "run.state" in messages(issues)


def test_run_id_grammar_enforced(tmp_path: Path) -> None:
    payload = valid_run_payload() | {"run_id": "Not-A-Run-Id"}
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", payload))
    assert run is None
    assert "run.run_id" in messages(issues)


def test_timestamp_must_be_utc_z(tmp_path: Path) -> None:
    payload = valid_run_payload() | {"updated_at": "2026-07-19T10:00:00+02:00"}
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", payload))
    assert run is None
    assert "run.updated_at" in messages(issues)


def test_register_digest_must_be_sha256_or_null(tmp_path: Path) -> None:
    digests = dict.fromkeys(runmodel.REGISTER_DIGEST_KEYS)
    digests["corpus_baseline"] = "not-a-digest"
    payload = valid_run_payload() | {"register_digests": digests}
    run, issues = runmodel.load_run_state(write_payload(tmp_path / "RUN.json", payload))
    assert run is None
    assert "register_digests.corpus_baseline" in messages(issues)


def test_valid_lease_loads(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "owner": {"principal_id": "orch.alice", "harness": "claude-code", "session_ref": "sess-1"},
        "fencing_token": 1,
        "acquired_at": "2026-07-19T10:00:00Z",
        "ttl_seconds": 3600,
        "released": False,
    }
    lease, issues = runmodel.load_lease(write_payload(tmp_path / "LEASE.json", payload))
    assert issues == []
    assert lease is not None and lease.released is False


def test_round_outcome_reason_required_unless_received(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "round": 1,
        "participants": [
            {
                "participant_id": "worker-one",
                "dispatch": {"sent_at": "2026-07-19T10:00:00Z", "prompt_digest": SHA, "input_digests": []},
                "receipt": None,
                "outcome": "timeout",
                "outcome_reason": "",
            }
        ],
        "sealed": False,
        "seal": None,
    }
    state, issues = runmodel.load_round_state(write_payload(tmp_path / "ROUND.json", payload))
    assert state is None
    assert "outcome_reason" in messages(issues)


def test_round_sealed_requires_seal_and_received_requires_receipt(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "round": 1,
        "participants": [
            {
                "participant_id": "worker-one",
                "dispatch": {"sent_at": "2026-07-19T10:00:00Z", "prompt_digest": SHA, "input_digests": []},
                "receipt": None,
                "outcome": "received",
                "outcome_reason": "",
            }
        ],
        "sealed": True,
        "seal": None,
    }
    state, issues = runmodel.load_round_state(write_payload(tmp_path / "ROUND.json", payload))
    assert state is None
    text = messages(issues)
    assert "round.seal" in text
    assert "receipt" in text


def write_tsv_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="")
    return path


UNITS_HEADER = "unit_id\tsource_id\tunit_locator\tunit_digest\tclaim_refs\tempty_reason"
UNIT_ROW = f"SU-ab12cd34-0001\tSRC-ab12cd34-0001\tdoc.md#alpha\t{SHA}"


def test_tsv_header_contract_is_exact(tmp_path: Path) -> None:
    rows, issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", "unit_id\tWRONG\n"))
    assert rows == ()
    assert "header must be exactly" in messages(issues)


def test_tsv_rows_must_be_strictly_sorted(tmp_path: Path) -> None:
    text = (
        f"{UNITS_HEADER}\n"
        f"SU-ab12cd34-0002\tSRC-ab12cd34-0001\tdoc.md#beta\t{SHA}\t\tNO_MATERIAL_CONTENT\n"
        f"SU-ab12cd34-0001\tSRC-ab12cd34-0001\tdoc.md#alpha\t{SHA}\t\tNO_MATERIAL_CONTENT\n"
    )
    _, issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", text))
    assert "strictly sorted" in messages(issues)


def test_tsv_wrong_column_count_rejected(tmp_path: Path) -> None:
    _, issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", f"{UNITS_HEADER}\nSU-ab12cd34-0001\tonly\n"))
    assert "tab-separated fields" in messages(issues)


def test_tsv_carriage_return_rejected(tmp_path: Path) -> None:
    text = f"{UNITS_HEADER}\n{UNIT_ROW}\t\tNO_MATERIAL_CONTENT\r\n"
    _, issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", text))
    assert "carriage return" in messages(issues)


def test_unit_row_requires_claims_or_reason_in_checker_mode(tmp_path: Path) -> None:
    text = f"{UNITS_HEADER}\n{UNIT_ROW}\t\t\n"
    _, strict_issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", text))
    assert "claim_refs or an empty_reason" in messages(strict_issues)
    _, lenient_issues = runmodel.load_source_units(tmp_path / "u.tsv", require_disposition=False)
    assert lenient_issues == []


def test_unit_row_rejects_claims_and_reason_together(tmp_path: Path) -> None:
    text = f"{UNITS_HEADER}\n{UNIT_ROW}\tCLM-ab12cd34-0001\tNO_MATERIAL_CONTENT\n"
    _, issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", text))
    assert "must be empty when claim_refs is set" in messages(issues)


def test_unit_empty_reason_grammar(tmp_path: Path) -> None:
    text = f"{UNITS_HEADER}\n{UNIT_ROW}\t\tDUPLICATE_OF:garbage\n"
    _, issues = runmodel.load_source_units(write_tsv_text(tmp_path / "u.tsv", text))
    assert "DUPLICATE_OF must reference a unit id" in messages(issues)


def test_ledger_rejected_requires_reason(tmp_path: Path) -> None:
    header = "claim_id\tsynthesis_disposition\tdisposition_reason\tresidual_edge\tatom_refs\tfinding_refs"
    text = f"{header}\nCLM-ab12cd34-0001\tREJECTED_WITH_REASON\t\tESCALATED_TO_PO\t\t\n"
    _, issues = runmodel.load_disposition_ledger(write_tsv_text(tmp_path / "l.tsv", text))
    assert "disposition_reason" in messages(issues)


def test_atom_covered_requires_receipts_and_targets(tmp_path: Path) -> None:
    header = (
        "atom_id\tstatement\tatom_type\tqualifiers\tnormative_status\texpected_authority"
        "\ttarget_refs\tdisposition\tdeferral\tclaim_refs\treceipt_refs"
    )
    text = f"{header}\nATM-ab12cd34-0001\tS\tREQUIREMENT\t\taccepted\tscope-a\t\tCOVERED_EXACT\t\tCLM-ab12cd34-0001\t\n"
    _, issues = runmodel.load_atom_register(write_tsv_text(tmp_path / "a.tsv", text))
    combined = messages(issues)
    assert "receipt_refs" in combined
    assert "target_refs" in combined


def test_atom_covered_split_needs_two_targets(tmp_path: Path) -> None:
    header = (
        "atom_id\tstatement\tatom_type\tqualifiers\tnormative_status\texpected_authority"
        "\ttarget_refs\tdisposition\tdeferral\tclaim_refs\treceipt_refs"
    )
    row = "ATM-ab12cd34-0001\tS\tREQUIREMENT\t\taccepted\tscope-a\ta.md#x\tCOVERED_SPLIT\t\tCLM-ab12cd34-0001\tRCP-ab12cd34-0001"
    _, issues = runmodel.load_atom_register(write_tsv_text(tmp_path / "a.tsv", f"{header}\n{row}\n"))
    assert "at least two target refs" in messages(issues)


def test_source_coverage_na_requires_reason(tmp_path: Path) -> None:
    header = "source_id\tsha256\treview_status\treview_artifact\treviewer_principal_id\tfinding_refs"
    text = f"{header}\nSRC-ab12cd34-0001\t{SHA}\tN_A\tN_A:\trev.bob\t\n"
    _, issues = runmodel.load_source_coverage(write_tsv_text(tmp_path / "c.tsv", text))
    assert "non-empty reason" in messages(issues)


def test_coverage_gaps_require_finding_refs(tmp_path: Path) -> None:
    header = "source_id\tsha256\treview_status\treview_artifact\treviewer_principal_id\tfinding_refs"
    text = f"{header}\nSRC-ab12cd34-0001\t{SHA}\tPASS_WITH_GAPS\treview.md\trev.bob\t\n"
    _, issues = runmodel.load_source_coverage(write_tsv_text(tmp_path / "c.tsv", text))
    assert "finding_refs" in messages(issues)


def test_findings_resolution_required_when_resolved(tmp_path: Path) -> None:
    header = "finding_id\tseverity\tstatus\tclaim_refs\tatom_refs\tpath\tlocator\tstatement\tresolution"
    text = f"{header}\nFND-ab12cd34-0001\tP1\tresolved\t\t\tdoc.md\tL1\tProblem\t\n"
    _, issues = runmodel.load_findings_register(write_tsv_text(tmp_path / "f.tsv", text))
    assert "resolution" in messages(issues)


def test_canonical_request_digest_ignores_request_digest_field() -> None:
    payload: dict[str, object] = {"schema_version": "1.0.0", "gate": "authority-prose", "chunks": []}
    digest = runmodel.canonical_request_digest(payload)
    assert digest == runmodel.canonical_request_digest(payload | {"request_digest": SHA})
    assert digest != runmodel.canonical_request_digest(payload | {"gate": "scope-consistency"})


def test_canonical_projection_entry_digest_strips_derived_fields() -> None:
    entry: dict[str, object] = {
        "scope_id": "scope-a",
        "assertion_status": "active",
        "required_projections": [
            {
                "kind": "support",
                "target": "concept/_meta/projection-manifest.json",
                "target_digest": SHA,
                "equivalence_status": "unreviewed",
            },
            {"kind": "prose", "target": "doc.md", "target_digest": SHA, "equivalence_status": "equivalent"},
        ],
    }
    digest = runmodel.canonical_projection_entry_digest(entry, "concept/_meta/projection-manifest.json")
    mutated = json.loads(json.dumps(entry))
    mutated["assertion_status"] = "blocked_projection"
    mutated["required_projections"][0]["equivalence_status"] = "stale"
    mutated["required_projections"][0]["target_digest"] = hashlib.sha256(b"other").hexdigest()
    assert digest == runmodel.canonical_projection_entry_digest(mutated, "concept/_meta/projection-manifest.json")
    mutated["required_projections"][1]["target_digest"] = hashlib.sha256(b"other").hexdigest()
    assert digest != runmodel.canonical_projection_entry_digest(mutated, "concept/_meta/projection-manifest.json")


def test_scope_lock_filename_normalization() -> None:
    name = runmodel.scope_lock_filename("Sample_Scope.two")
    hash8 = hashlib.sha256(b"Sample_Scope.two").hexdigest()[:8]
    assert name == f"sample-scope-two.{hash8}.lock.json"


def test_semantic_pack_request_digest_is_verified(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "gate": "authority-prose",
        "scope_id": "scope-a",
        "base_revision": {"kind": "git", "value": "abc"},
        "template_id": "w2",
        "template_digest": SHA,
        "chunks": [{"path": "doc.md", "locator": "doc.md#L1-L2", "digest": SHA}],
    }
    payload["request_digest"] = runmodel.canonical_request_digest(payload)
    pack, issues = runmodel.load_semantic_request_pack(write_payload(tmp_path / "p.json", payload))
    assert issues == []
    assert pack is not None
    payload["request_digest"] = SHA
    pack, issues = runmodel.load_semantic_request_pack(write_payload(tmp_path / "p.json", payload))
    assert pack is None
    assert "canonical digest" in messages(issues)


def test_projection_manifest_accepts_optional_covered_scope_ids(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0.0",
        "entries": [
            {
                "scope_id": "scope-a",
                "covered_scope_ids": ["scope-b"],
                "lifecycle": "current",
                "lifecycle_source": {
                    "decision_id": "d",
                    "path": "concept/_meta/decisions/d.md",
                    "digest": SHA,
                    "status": "accepted",
                },
                "assertion_source": {"path": "doc.md", "digest": SHA},
                "assertion_status": "blocked_projection",
                "required_projections": [],
                "blockers": [],
                "last_run_id": None,
                "last_promotion_manifest": None,
            }
        ],
    }
    manifest, issues = runmodel.load_projection_manifest(write_payload(tmp_path / "m.json", payload))
    assert issues == []
    assert manifest is not None
    assert manifest.entries[0].covered_scope_ids == ("scope-b",)


def test_canonical_tsv_subset_digest_equals_file_digest_at_freeze(tmp_path: Path) -> None:
    header = "id\tvalue"
    rows = ["a\t1", "b\t2"]
    path = tmp_path / "r.tsv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8", newline="")
    assert runmodel.canonical_tsv_subset_digest(header, rows) == runmodel.file_sha256(path)
    assert runmodel.canonical_tsv_subset_digest(header, list(reversed(rows))) == runmodel.file_sha256(path)


def test_derive_register_digests_partitions_input_and_derived(tmp_path: Path) -> None:
    run_dir = tmp_path
    (run_dir / "baseline").mkdir()
    (run_dir / "synthesis").mkdir()
    register_header = runmodel.SOURCE_REGISTER_HEADER
    input_row = f"SRC-ab12cd34-0001\tinput\tBRIEFING\tx/briefing.md\t{SHA}\t\t\torch.alice\t"
    derived_row = f"SRC-ab12cd34-0002\tderived\tSYNTHESIS\tx/s.md\t{SHA}\t\t\torch.alice\tSRC-ab12cd34-0001"
    register = run_dir / "baseline" / "source-register.tsv"
    register.write_text("\n".join([register_header, input_row, derived_row]) + "\n", encoding="utf-8", newline="")
    units_header = runmodel.SOURCE_UNITS_HEADER
    unit_input = f"SU-ab12cd34-0001\tSRC-ab12cd34-0001\tx/briefing.md#a\t{SHA}\t\tNO_MATERIAL_CONTENT"
    unit_derived = f"SU-ab12cd34-0002\tSRC-ab12cd34-0002\tx/s.md#a\t{SHA}\tCLM-ab12cd34-0001\t"
    (run_dir / "baseline" / "source-units.tsv").write_text(
        "\n".join([units_header, unit_input, unit_derived]) + "\n", encoding="utf-8", newline=""
    )
    claims_header = runmodel.CLAIMS_INVENTORY_HEADER
    claim_derived = "CLM-ab12cd34-0001\tSRC-ab12cd34-0002\tSU-ab12cd34-0002\tx/s.md#a\tStatement\t\t"
    (run_dir / "synthesis" / "claims-inventory.tsv").write_text(
        "\n".join([claims_header, claim_derived]) + "\n", encoding="utf-8", newline=""
    )
    derived, issues = runmodel.derive_register_digests(run_dir)
    assert issues == []
    assert derived["source_register_input"] == runmodel.canonical_tsv_subset_digest(register_header, [input_row])
    assert derived["source_register_final"] == runmodel.file_sha256(register)
    assert derived["source_units_input"] == runmodel.canonical_tsv_subset_digest(units_header, [unit_input])
    assert derived["claims_inventory_input"] == runmodel.canonical_tsv_subset_digest(claims_header, [])
    assert derived["derived_claims"] == runmodel.canonical_tsv_subset_digest(claims_header, [claim_derived])
    assert derived["corpus_baseline"] is None


def test_registry_edges_accept_string_and_object_forms(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "base_revision": {"kind": "git", "value": "abc"},
        "scopes": [],
        "required_decision_ids": [],
        "required_concept_ids": [],
        "required_formal_ids": [],
        "required_registry_edges": ["a.yaml#anchor", {"from": "DK-01", "to": "FK-10", "kind": "defers_to"}],
        "required_support_paths": [],
        "required_test_oracles": [],
        "targets": [],
        "receipts_dir": "promotion/receipts",
        "scope_locks": [],
        "semantic_gates": [],
    }
    manifest, issues = runmodel.load_promotion_manifest(write_payload(tmp_path / "m.json", payload))
    assert issues == []
    assert manifest is not None
    assert manifest.required_registry_edges[0] == "a.yaml#anchor"
    assert isinstance(manifest.required_registry_edges[1], runmodel.RegistryEdge)
    payload["required_registry_edges"] = ["no-anchor"]
    manifest, issues = runmodel.load_promotion_manifest(write_payload(tmp_path / "m.json", payload))
    assert manifest is None
    assert "string form must be <path>#<anchor>" in messages(issues)


def test_lock_evidence_loader_is_fail_closed(tmp_path: Path) -> None:
    ref_entry: dict[str, object] = {
        "scope_id": "sample-scope",
        "ref": "refs/concept-locks/abcd1234",
        "expected_ref": "refs/concept-locks/abcd1234",
        "old_oid": "0" * 40,
        "new_oid": "b" * 40,
        "observed_oid": "b" * 40,
        "lock_blob_digest": SHA,
        "fencing_token": 7,
        "ttl_seconds": 3600,
        "acquired_at": "2026-07-19T09:00:00Z",
        "attested_by_principal": "orch.alice",
        "attested_by_session": "sess-orch",
        "verified_at": "2026-07-19T10:00:00Z",
    }
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "backend": "git-remote",
        "remote": "origin",
        "refs": [ref_entry],
    }
    evidence, issues = runmodel.load_lock_evidence(write_payload(tmp_path / "e.json", payload))
    assert issues == []
    assert evidence is not None and evidence.refs[0].scope_id == "sample-scope"
    ref_entry["ref"] = "not-a-ref"
    evidence, issues = runmodel.load_lock_evidence(write_payload(tmp_path / "e.json", payload))
    assert evidence is None
    assert "fully qualified ref name" in messages(issues)


def test_timestamp_expired() -> None:
    assert runmodel.timestamp_expired("2020-01-01T00:00:00Z", 60) is True
    assert runmodel.timestamp_expired("2999-01-01T00:00:00Z", 60) is False
