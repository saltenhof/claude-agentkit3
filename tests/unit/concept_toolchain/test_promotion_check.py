"""Promotion-closure tests (FK-78 section 78.11 rules 1-7) with real git baselines."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel
from concept_toolchain.config import load_governance_config
from concept_toolchain.promotion_check import run_promotion_check
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.runfixtures import ATOM_ID, RunFixture, build_promotion_run, refresh_target_bindings

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult

pytestmark = pytest.mark.requires_git


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=True)


def run_check(fixture: RunFixture) -> CheckResult:
    config = load_governance_config(fixture.project_root)
    return run_promotion_check(fixture.project_root, config, fixture.run_dir)


def finding_messages(result: CheckResult) -> str:
    return " | ".join(f"{finding.path}:{finding.locator}: {finding.message}" for finding in result.findings)


def rewrite_receipt(fixture: RunFixture, **overrides: object) -> None:
    payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    payload.update(overrides)
    runfixtures.write_json(fixture.receipt_path, payload)


def test_green_promotion_passes_completely(fixture: RunFixture) -> None:
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)
    assert result.complete is True, result.incomplete_reason


def test_non_git_baseline_marks_reverse_trace_incomplete(green_corpus: Path) -> None:
    fixture = build_promotion_run(green_corpus, use_git=False)
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)
    assert result.complete is False
    assert result.incomplete_reason is not None
    assert "INCOMPLETE_CHECK_SET" in result.incomplete_reason
    assert "reverse-trace" in result.incomplete_reason


def test_covered_atom_without_receipt_file_is_error(fixture: RunFixture) -> None:
    fixture.receipt_path.unlink()
    result = run_check(fixture)
    assert "does not exist or failed validation" in finding_messages(result)


def test_receipt_with_same_principal_is_error(fixture: RunFixture) -> None:
    rewrite_receipt(fixture, reviewer_principal_id="p.writer")
    result = run_check(fixture)
    assert "reviewer principal must differ from the writer principal" in finding_messages(result)


def test_receipt_with_same_session_is_error(fixture: RunFixture) -> None:
    rewrite_receipt(fixture, reviewer_session_ref="sess-writer")
    result = run_check(fixture)
    assert "reviewer session must differ from the writer session" in finding_messages(result)


def test_disagreeing_receipt_without_blocker_is_error(fixture: RunFixture) -> None:
    rewrite_receipt(fixture, verdict="disagrees")
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "disagreeing receipt requires a scope blocker" in combined
    assert "verdict 'disagrees'" in combined


def test_receipt_source_digest_mismatch_is_error(fixture: RunFixture) -> None:
    rewrite_receipt(fixture, source_digest="0" * 64)
    result = run_check(fixture)
    assert "source_digest does not match the atom statement" in finding_messages(result)


def test_target_after_digest_mismatch_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    targets = manifest["targets"]
    assert isinstance(targets, list) and isinstance(targets[0], dict)
    targets[0]["after_sha256"] = "0" * 64
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "after_sha256 does not match the working tree" in finding_messages(result)


def test_target_before_digest_mismatch_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    targets = manifest["targets"]
    assert isinstance(targets, list) and isinstance(targets[0], dict)
    targets[0]["before_sha256"] = "0" * 64
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "before_sha256 does not match the corpus baseline" in finding_messages(result)


def test_uncovered_diff_hunk_is_error(fixture: RunFixture) -> None:
    target = fixture.project_root / fixture.target_rel
    target.write_text(
        target.read_text(encoding="utf-8") + "\n## Sneaky Section\n\nSmuggled normative content must pass.\n",
        encoding="utf-8",
        newline="\n",
    )
    refresh_target_bindings(fixture)
    result = run_check(fixture)
    assert "diff hunk is not covered by any receipt or atom target anchor" in finding_messages(result)


def test_whitespace_only_hunk_needs_no_coverage(fixture: RunFixture) -> None:
    target = fixture.project_root / fixture.target_rel
    target.write_text(target.read_text(encoding="utf-8") + "\n\n", encoding="utf-8", newline="\n")
    refresh_target_bindings(fixture)
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_missing_scope_lock_file_is_error(fixture: RunFixture) -> None:
    fixture.lock_path.unlink()
    result = run_check(fixture)
    assert "scope lock file" in finding_messages(result)


def test_lock_fencing_token_mismatch_is_error(fixture: RunFixture) -> None:
    payload = json.loads(fixture.lock_path.read_text(encoding="utf-8"))
    payload["fencing_token"] = 8
    runfixtures.write_json(fixture.lock_path, payload)
    result = run_check(fixture)
    assert "does not match the manifest entry" in finding_messages(result)


def test_lock_held_by_other_run_is_error(fixture: RunFixture) -> None:
    payload = json.loads(fixture.lock_path.read_text(encoding="utf-8"))
    payload["locked_by_run"] = "2026-07-19-other-ffffffff"
    runfixtures.write_json(fixture.lock_path, payload)
    result = run_check(fixture)
    assert "lock is held by" in finding_messages(result)


def test_promoted_with_deferred_backlog_atom_is_error(fixture: RunFixture) -> None:
    register = fixture.atom_register_path
    deferral = "owner=po;trigger=next-run;anchor=concept/technical-design/10_sample.md#promoted-addition"
    row = (
        f"ATM-{fixture.uuid8}-0002\tDeferred content.\tREQUIREMENT\t\taccepted\t{fixture.scope_id}"
        f"\t\tDEFERRED_BACKLOG\t{deferral}\t{runfixtures.CLAIM_ID}\t"
    )
    register.write_text(register.read_text(encoding="utf-8") + row + "\n", encoding="utf-8", newline="\n")
    fixture.repin_registers()
    result = run_check(fixture)
    assert "disposition DEFERRED_BACKLOG" in finding_messages(result)


def test_promoted_with_open_finding_is_error(fixture: RunFixture) -> None:
    findings_path = fixture.run_dir / "findings.tsv"
    row = f"FND-{fixture.uuid8}-0001\tP1\topen\t\t{ATOM_ID}\t{fixture.target_rel}\tL1\tUnresolved gap\t"
    findings_path.write_text(findings_path.read_text(encoding="utf-8") + row + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "open finding(s)" in finding_messages(result)


def test_deferred_scope_without_blocker_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    scopes = manifest["scopes"]
    assert isinstance(scopes, list) and isinstance(scopes[0], dict)
    scopes[0]["promotion_disposition"] = "deferred"
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "deferred scope requires at least one blocker" in finding_messages(result)


def test_rejected_scope_must_document_alternative(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    scopes = manifest["scopes"]
    assert isinstance(scopes, list) and isinstance(scopes[0], dict)
    scopes[0]["promotion_disposition"] = "rejected"
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "rejected scope must document the discarded alternative" in finding_messages(result)


def test_unresolved_required_concept_id_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    required = manifest["required_concept_ids"]
    assert isinstance(required, list)
    required.append("FK-99")
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "concept id does not resolve in the corpus: 'FK-99'" in finding_messages(result)


def test_coverage_reviewer_must_not_be_author(fixture: RunFixture) -> None:
    coverage = fixture.run_dir / "baseline" / "source-coverage.tsv"
    lines = coverage.read_text(encoding="utf-8").rstrip("\n").split("\n")
    for index, line in enumerate(lines[1:], start=1):
        fields = line.split("\t")
        if fields[0] == runfixtures.SRC_PROPOSAL:
            fields[4] = "p.worker"
            lines[index] = "\t".join(fields)
    coverage.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "reviewer must not be the source author" in finding_messages(result)


def test_missing_normative_coverage_row_is_error(fixture: RunFixture) -> None:
    coverage = fixture.run_dir / "baseline" / "normative-coverage.tsv"
    coverage.write_text(coverage.read_text(encoding="utf-8").split("\n")[0] + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "normative coverage row missing for" in finding_messages(result)


def test_semantic_gate_not_run_blocks_promoted_scope(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    gates = manifest["semantic_gates"]
    assert isinstance(gates, list) and isinstance(gates[0], dict)
    gates[0]["status"] = "not_run"
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "is 'not_run' for a promoted scope" in finding_messages(result)


def test_empty_semantic_gates_set_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    manifest["semantic_gates"] = []
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "exactly one 'authority-prose' entry is required, found 0" in combined
    assert "exactly one 'scope-consistency' entry is required, found 0" in combined


def test_unresolved_registry_edge_string_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append("concept/technical-design/10_sample.md#no-such-anchor")
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "anchor does not resolve" in finding_messages(result)


def test_resolvable_registry_edge_forms_pass(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append(f"{fixture.target_rel}#promoted-addition")
    edges.append({"from": "DK-01", "to": "scope-dk-01", "kind": "owns"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_unresolved_test_oracle_locator_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    oracles = manifest["required_test_oracles"]
    assert isinstance(oracles, list)
    oracles.append({"oracle_id": "oracle-1", "kind": "pytest", "locator": "tests/does_not_exist.py"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "oracle 'oracle-1': reference path does not exist" in finding_messages(result)


def test_expired_scope_lock_is_error(fixture: RunFixture) -> None:
    payload = json.loads(fixture.lock_path.read_text(encoding="utf-8"))
    payload["acquired_at"] = "2020-01-01T00:00:00Z"
    runfixtures.write_json(fixture.lock_path, payload)
    result = run_check(fixture)
    assert "scope lock TTL has expired" in finding_messages(result)


def test_lock_blob_backend_mismatch_is_error(fixture: RunFixture) -> None:
    payload = json.loads(fixture.lock_path.read_text(encoding="utf-8"))
    payload["backend"] = "git-remote"
    runfixtures.write_json(fixture.lock_path, payload)
    result = run_check(fixture)
    assert "lock backend 'git-remote' does not match configured 'filesystem'" in finding_messages(result)


def _switch_to_git_remote(fixture: RunFixture) -> None:
    config_rel = "concept/_meta/concept-governance.json"
    config_path = fixture.project_root / config_rel
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["lock_backend"] = "git-remote"
    payload["lock_remote"] = "origin"
    runfixtures.write_json(config_path, payload)
    manifest = fixture.read_manifest()
    locks = manifest["scope_locks"]
    assert isinstance(locks, list) and isinstance(locks[0], dict)
    locks[0]["backend"] = "git-remote"
    fixture.write_manifest(manifest)
    coverage = fixture.run_dir / "baseline" / "normative-coverage.tsv"
    lines = coverage.read_text(encoding="utf-8").rstrip("\n").split("\n")
    row = "\t".join(
        [
            config_rel,
            fixture.baseline_digests[config_rel],
            runfixtures.sha_file(config_path),
            "modified",
            "PASS",
            f"{fixture.run_rel}/synthesis/synthesis-r1.md",
            "rev.bob",
            "",
        ]
    )
    coverage.write_text("\n".join([lines[0], row, *lines[1:]]) + "\n", encoding="utf-8", newline="\n")


def test_git_remote_without_evidence_is_incomplete(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    result = run_check(fixture)
    assert result.complete is False
    assert result.incomplete_reason is not None
    assert "git-remote lock verification requires the orchestrator-side CAS evidence" in result.incomplete_reason


LOCK_ACQUIRED_AT = runfixtures.now_utc()


def cas_evidence_ref(fixture: RunFixture, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "scope_id": fixture.scope_id,
        "ref": runmodel.scope_lock_ref(fixture.scope_id),
        "expected_ref": runmodel.scope_lock_ref(fixture.scope_id),
        "old_oid": "0" * 40,
        "new_oid": "b" * 40,
        "observed_oid": "b" * 40,
        "lock_blob_digest": runmodel.canonical_lock_blob_digest(
            fixture.scope_id, fixture.run_id, 7, "git-remote", 3600, LOCK_ACQUIRED_AT
        ),
        "fencing_token": 7,
        "ttl_seconds": 3600,
        "acquired_at": LOCK_ACQUIRED_AT,
        "attested_by_principal": "orch.alice",
        "attested_by_session": "sess-orch",
        "verified_at": runfixtures.now_utc(),
    }
    entry.update(overrides)
    return entry


def write_evidence(fixture: RunFixture, ref: dict[str, object]) -> None:
    runfixtures.write_json(
        fixture.run_dir / "promotion" / "lock-evidence.json",
        {"schema_version": "1.0.0", "backend": "git-remote", "remote": "origin", "refs": [ref]},
    )


def test_git_remote_with_cas_evidence_completes(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    write_evidence(fixture, cas_evidence_ref(fixture))
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)
    assert result.complete is True, result.incomplete_reason


def test_cas_evidence_with_wrong_ref_is_error(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    write_evidence(fixture, cas_evidence_ref(fixture, expected_ref="refs/concept-locks/deadbeef"))
    result = run_check(fixture)
    assert "expected_ref must be" in finding_messages(result)


def test_cas_evidence_with_wrong_lock_blob_digest_is_error(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    write_evidence(fixture, cas_evidence_ref(fixture, lock_blob_digest="4" * 64))
    result = run_check(fixture)
    assert "lock_blob_digest does not match the canonical lock blob" in finding_messages(result)


def test_cas_evidence_with_wrong_fencing_token_is_error(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    write_evidence(fixture, cas_evidence_ref(fixture, fencing_token=3))
    result = run_check(fixture)
    assert "does not match the manifest entry" in finding_messages(result)


def test_cas_evidence_with_mismatched_observed_oid_is_error(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    write_evidence(fixture, cas_evidence_ref(fixture, observed_oid="c" * 40))
    result = run_check(fixture)
    assert "does not equal the attested new_oid" in finding_messages(result)


def test_stale_cas_evidence_is_error(fixture: RunFixture) -> None:
    _switch_to_git_remote(fixture)
    write_evidence(fixture, cas_evidence_ref(fixture, verified_at="2020-01-01T00:00:00Z"))
    result = run_check(fixture)
    assert "CAS attestation is stale" in finding_messages(result)


def test_source_coverage_digest_mismatch_is_error(fixture: RunFixture) -> None:
    coverage = fixture.run_dir / "baseline" / "source-coverage.tsv"
    lines = coverage.read_text(encoding="utf-8").rstrip("\n").split("\n")
    fields = lines[1].split("\t")
    fields[1] = "3" * 64
    lines[1] = "\t".join(fields)
    coverage.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "coverage digest does not match the current source" in finding_messages(result)


def test_missing_review_artifact_is_error(fixture: RunFixture) -> None:
    coverage = fixture.run_dir / "baseline" / "source-coverage.tsv"
    lines = coverage.read_text(encoding="utf-8").rstrip("\n").split("\n")
    fields = lines[1].split("\t")
    fields[3] = "concept-incubator/does-not-exist.md"
    lines[1] = "\t".join(fields)
    coverage.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "review artifact does not exist" in finding_messages(result)


def test_structured_registry_edge_resolves_the_concrete_relation(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append({"from": "FK-10", "to": "scope-fk-10", "kind": "owns"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_owns_edge_without_matching_authority_scope_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append({"from": "FK-10", "to": "scope-dk-01", "kind": "owns"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "FK-10 does not declare authority_over scope 'scope-dk-01'" in finding_messages(result)


def test_defers_to_edge_without_frontmatter_edge_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append({"from": "FK-10", "to": "DK-01", "kind": "defers_to"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "FK-10 does not declare a defers_to edge to 'DK-01'" in finding_messages(result)


def test_structured_registry_edge_with_unknown_node_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append({"from": "FK-10", "to": "FK-404", "kind": "defers_to"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "to node 'FK-404' does not resolve" in finding_messages(result)


def test_structured_registry_edge_with_unknown_kind_is_error(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    edges = manifest["required_registry_edges"]
    assert isinstance(edges, list)
    edges.append({"from": "FK-10", "to": "scope-fk-10", "kind": "vibes"})
    fixture.write_manifest(manifest)
    result = run_check(fixture)
    assert "kind 'vibes' is not one of" in finding_messages(result)





def test_promotion_covers_all_four_target_modes(fixture: RunFixture) -> None:
    """One atom + receipt per target mode must pass the promotion closure."""
    runfixtures.add_mode_atoms(fixture)
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)
    assert result.complete is True, result.incomplete_reason


def test_receipt_mode_mismatch_against_target_is_error(fixture: RunFixture) -> None:
    """A whole-file receipt cannot attest a markdown-section atom target."""
    payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    payload["target_mode"] = "whole-file"
    payload["target"] = {"path": fixture.target_rel, "anchor": ""}
    runfixtures.write_json(fixture.receipt_path, payload)
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "covers undeclared target" in combined or "target_section_digest does not match" in combined


def test_selector_receipt_digest_drift_is_error(fixture: RunFixture) -> None:
    runfixtures.add_mode_atoms(fixture)
    receipt_path = fixture.run_dir / "promotion" / "receipts" / f"RCP-{fixture.uuid8}-0004.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["target_section_digest"] = "9" * 64
    runfixtures.write_json(receipt_path, payload)
    result = run_check(fixture)
    assert "target_section_digest does not match the current target" in finding_messages(result)
