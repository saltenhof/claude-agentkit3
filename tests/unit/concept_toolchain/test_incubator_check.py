"""Incubator-check tests against a full generated run (FK-78 78.3-78.9, 78.13)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain.config import load_governance_config
from concept_toolchain.incubator_check import run_incubator_check
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.runfixtures import RunFixture, build_promotion_run

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult


pytestmark = pytest.mark.requires_git


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=True)


def run_check(fixture: RunFixture) -> CheckResult:
    config = load_governance_config(fixture.project_root)
    return run_incubator_check(fixture.project_root, config, fixture.run_dir)


def finding_messages(result: CheckResult) -> str:
    return " | ".join(f"{finding.locator}: {finding.message}" for finding in result.findings)


def edit_tsv_lines(fixture: RunFixture, relative: str, transform: object) -> None:
    path = fixture.run_dir / relative
    lines = path.read_text(encoding="utf-8").split("\n")
    assert callable(transform)
    path.write_text("\n".join(transform(lines)), encoding="utf-8", newline="\n")
    fixture.repin_registers()


def test_green_run_passes(fixture: RunFixture) -> None:
    result = run_check(fixture)
    assert result.complete is True
    assert result.findings == [], finding_messages(result)


def test_missing_run_dir_is_incomplete(green_corpus: Path) -> None:
    config = load_governance_config(green_corpus)
    result = run_incubator_check(green_corpus, config, green_corpus / "concept-incubator" / "runs" / "missing")
    assert result.complete is False
    assert result.incomplete_reason is not None


def test_unknown_run_field_is_error(fixture: RunFixture) -> None:
    payload = fixture.read_run() | {"shadow_state": True}
    fixture.write_run(payload)
    result = run_check(fixture)
    assert "unknown field 'shadow_state'" in finding_messages(result)


def test_state_gate_requires_input_digests(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    digests = payload["register_digests"]
    assert isinstance(digests, dict)
    digests["claims_inventory_input"] = None
    fixture.write_run(payload)
    result = run_check(fixture)
    assert "register_digests.claims_inventory_input" in finding_messages(result)


def test_blocked_must_be_null_outside_blocked_state(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    payload["blocked"] = {"reason": "stuck", "since_state": "DECIDING"}
    fixture.write_run(payload)
    result = run_check(fixture)
    assert "must be null outside state BLOCKED" in finding_messages(result)


def test_pinned_register_digest_mismatch_is_error(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    digests = payload["register_digests"]
    assert isinstance(digests, dict)
    digests["atom_register"] = "0" * 64
    fixture.write_run(payload)
    result = run_check(fixture)
    assert "register_digests.atom_register: pinned digest does not match the canonical re-derivation" in finding_messages(result)


def test_round_seal_digest_mismatch_is_error(fixture: RunFixture) -> None:
    round_path = fixture.run_dir / "rounds" / "r1" / "ROUND.json"
    payload = json.loads(round_path.read_text(encoding="utf-8"))
    payload["seal"]["sealed_proposal_digests"]["worker-one"] = "0" * 64
    payload["participants"][0]["receipt"]["proposal_digest"] = "0" * 64
    runfixtures.write_json(round_path, payload)
    result = run_check(fixture)
    assert "sealed proposal digest does not match the file" in finding_messages(result)


def test_round_beyond_current_round_is_error(fixture: RunFixture) -> None:
    extra = fixture.run_dir / "rounds" / "r2"
    extra.mkdir()
    round_payload = json.loads((fixture.run_dir / "rounds" / "r1" / "ROUND.json").read_text(encoding="utf-8"))
    round_payload["round"] = 2
    round_payload["participants"] = []
    round_payload["sealed"] = False
    round_payload["seal"] = None
    runfixtures.write_json(extra / "ROUND.json", round_payload)
    result = run_check(fixture)
    assert "round beyond RUN.json current_round" in finding_messages(result)


def test_unit_thinning_is_detected(fixture: RunFixture) -> None:
    edit_tsv_lines(
        fixture, "baseline/source-units.tsv", lambda lines: [line for line in lines if "briefing.md#briefing" not in line]
    )
    result = run_check(fixture)
    assert "missing from the register (thinned)" in finding_messages(result)


def test_unit_digest_drift_is_detected(fixture: RunFixture) -> None:
    def tamper(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if "briefing.md#briefing" in line:
                fields = line.split("\t")
                fields[3] = "0" * 64
                line = "\t".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "baseline/source-units.tsv", tamper)
    result = run_check(fixture)
    assert "does not match the re-derived partition" in finding_messages(result)


def test_source_digest_drift_is_detected(fixture: RunFixture) -> None:
    briefing = fixture.run_dir / "briefing.md"
    briefing.write_text(briefing.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "source file digest drifted" in finding_messages(result)


def test_missing_ledger_row_per_claim_is_error(fixture: RunFixture) -> None:
    edit_tsv_lines(fixture, "synthesis/disposition-ledger.tsv", lambda lines: lines[:1] + [""])
    result = run_check(fixture)
    assert "has no disposition-ledger row" in finding_messages(result)


def test_claim_unit_edges_must_match(fixture: RunFixture) -> None:
    def drop_claim(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if "synthesis-r1.md#synthesis" in line:
                fields = line.split("\t")
                fields[4] = ""
                fields[5] = "NO_MATERIAL_CONTENT"
                line = "\t".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "baseline/source-units.tsv", drop_claim)
    result = run_check(fixture)
    assert "does not carry claim" in finding_messages(result)


def test_artifact_provenance_cycle_is_error(fixture: RunFixture) -> None:
    rel = fixture.run_rel

    def introduce_cycle(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if line.startswith(f"{rel}/briefing.md"):
                fields = line.split("\t")
                fields[3] = f"artifact:{rel}/synthesis/synthesis-r1.md"
                line = "\t".join(fields)
            if line.startswith(f"{rel}/synthesis/"):
                fields = line.split("\t")
                fields[3] = f"artifact:{rel}/briefing.md"
                line = "\t".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "artifact-register.tsv", introduce_cycle)
    result = run_check(fixture)
    assert "provenance cycle detected" in finding_messages(result)


def test_sensitive_versioned_without_declassification_is_error(fixture: RunFixture) -> None:
    def sensitive(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if line.startswith(f"{fixture.run_rel}/briefing.md"):
                fields = line.split("\t")
                fields[4] = "sensitive"
                fields[5] = "sensitive"
                line = "\t".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "artifact-register.tsv", sensitive)
    result = run_check(fixture)
    assert "requires vcs_disposition local (commit gate)" in finding_messages(result)


def test_effective_class_must_be_input_maximum(fixture: RunFixture) -> None:
    def downgrade(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            fields = line.split("\t")
            if line.startswith(f"{fixture.run_rel}/briefing.md"):
                fields[4] = "sensitive"
                fields[5] = "sensitive"
                fields[6] = "local"
            if line.startswith(f"{fixture.run_rel}/rounds/"):
                fields[3] = f"artifact:{fixture.run_rel}/briefing.md"
            out.append("\t".join(fields))
        return out

    edit_tsv_lines(fixture, "artifact-register.tsv", downgrade)
    result = run_check(fixture)
    assert "effective_class must be the maximum" in finding_messages(result)


def test_local_overlay_union_keeps_run_green(fixture: RunFixture) -> None:
    register = fixture.run_dir / "artifact-register.tsv"
    lines = register.read_text(encoding="utf-8").rstrip("\n").split("\n")
    header, rows = lines[0], lines[1:]
    moved = [row.replace("\tversioned\t", "\tlocal\t") for row in rows if "/synthesis/" in row]
    kept = [row for row in rows if "/synthesis/" not in row]
    register.write_text("\n".join([header, *kept]) + "\n", encoding="utf-8", newline="\n")
    overlay = fixture.run_dir / "artifact-register.local.tsv"
    overlay.write_text("\n".join([header, *moved]) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)


def test_lease_run_id_mismatch_is_error(fixture: RunFixture) -> None:
    lease_path = fixture.run_dir / "LEASE.json"
    payload = json.loads(lease_path.read_text(encoding="utf-8"))
    payload["run_id"] = "2026-07-19-other-ffffffff"
    runfixtures.write_json(lease_path, payload)
    result = run_check(fixture)
    assert "does not match RUN.json" in finding_messages(result)


def test_foreign_uuid8_in_register_id_is_error(fixture: RunFixture) -> None:
    foreign = fixture.run_dir / "foreign.md"
    foreign.write_text("# Foreign\n\nContent.\n", encoding="utf-8", newline="\n")

    def add_row(lines: list[str]) -> list[str]:
        digest = runfixtures.sha_file(foreign)
        row = f"SRC-ffffffff-0009\tinput\tEVIDENCE\t{fixture.run_rel}/foreign.md\t{digest}\t\t\torch.alice\t"
        return [*lines[:-1], row, ""]

    edit_tsv_lines(fixture, "baseline/source-register.tsv", add_row)
    result = run_check(fixture)
    assert "does not match run_uuid8" in finding_messages(result)


def test_non_git_base_revision_is_incomplete(green_corpus: Path) -> None:
    fixture = build_promotion_run(green_corpus, use_git=False)
    result = run_check(fixture)
    assert result.findings == [], finding_messages(result)
    assert result.complete is False
    assert result.incomplete_reason is not None
    assert "baseline-rederivation" in result.incomplete_reason


def test_thinned_baseline_row_is_detected(fixture: RunFixture) -> None:
    edit_tsv_lines(
        fixture, "baseline/corpus-baseline.tsv", lambda lines: [line for line in lines if "10_sample.md" not in line]
    )
    result = run_check(fixture)
    assert "missing from the baseline register (thinned)" in finding_messages(result)


def test_omitted_sealed_proposal_breaks_input_closure(fixture: RunFixture) -> None:
    edit_tsv_lines(
        fixture, "baseline/source-register.tsv", lambda lines: [line for line in lines if "worker-one.md" not in line]
    )
    result = run_check(fixture)
    assert "sealed proposal is missing from the input source register" in finding_messages(result)


def test_forged_input_digest_is_detected(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    digests = payload["register_digests"]
    assert isinstance(digests, dict)
    digests["source_register_input"] = "1" * 64
    fixture.write_run(payload)
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "register_digests.source_register_input: pinned digest does not match the canonical re-derivation" in combined


def test_atom_with_foreign_claim_ref_is_error(fixture: RunFixture) -> None:
    def foreign(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if line.startswith("ATM-"):
                fields = line.split("	")
                fields[9] = "CLM-ffffffff-0001"
                line = "	".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "promotion/atom-register.tsv", foreign)
    result = run_check(fixture)
    assert "unknown claim 'CLM-ffffffff-0001'" in finding_messages(result)


def test_ledger_atom_ref_to_missing_atom_is_error(fixture: RunFixture) -> None:
    def dangling(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if line.startswith("CLM-"):
                fields = line.split("	")
                fields[4] = f"ATM-{fixture.uuid8}-0009"
                line = "	".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "synthesis/disposition-ledger.tsv", dangling)
    result = run_check(fixture)
    assert f"unknown atom 'ATM-{fixture.uuid8}-0009'" in finding_messages(result)


def test_atom_without_ledger_back_edge_is_error(fixture: RunFixture) -> None:
    register = fixture.atom_register_path
    row = (
        f"ATM-{fixture.uuid8}-0002	Supporting evidence.	EVIDENCE		evidence	{fixture.scope_id}"
        f"		EVIDENCE_ONLY		{runfixtures.CLAIM_ID}	"
    )
    register.write_text(register.read_text(encoding="utf-8") + row + "\n", encoding="utf-8", newline="\n")
    fixture.repin_registers()
    result = run_check(fixture)
    assert "does not list atom" in finding_messages(result)


def test_expired_lease_in_active_state_is_error(fixture: RunFixture) -> None:
    lease_path = fixture.run_dir / "LEASE.json"
    payload = json.loads(lease_path.read_text(encoding="utf-8"))
    payload["acquired_at"] = "2020-01-01T00:00:00Z"
    runfixtures.write_json(lease_path, payload)
    result = run_check(fixture)
    assert "expired writer lease" in finding_messages(result)


def test_missing_lease_in_active_state_is_error(fixture: RunFixture) -> None:
    (fixture.run_dir / "LEASE.json").unlink()
    result = run_check(fixture)
    assert "active run without LEASE.json" in finding_messages(result)


def test_main_register_must_stay_versioned(fixture: RunFixture) -> None:
    def localize(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if line.startswith(f"{fixture.run_rel}/briefing.md"):
                line = line.replace("	versioned	", "	local	")
            out.append(line)
        return out

    edit_tsv_lines(fixture, "artifact-register.tsv", localize)
    result = run_check(fixture)
    assert "main register permits only vcs_disposition versioned" in finding_messages(result)


def test_artifact_digest_mismatch_is_error(fixture: RunFixture) -> None:
    def forge(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if line.startswith(f"{fixture.run_rel}/briefing.md"):
                fields = line.split("	")
                fields[1] = "2" * 64
                line = "	".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "artifact-register.tsv", forge)
    result = run_check(fixture)
    assert "registered artifact digest does not match the file" in finding_messages(result)


def test_omitted_dissent_map_breaks_derived_closure(fixture: RunFixture) -> None:
    edit_tsv_lines(
        fixture, "baseline/source-register.tsv", lambda lines: [line for line in lines if "dissent-map.md" not in line]
    )
    result = run_check(fixture)
    assert "canonical derived source is not registered" in finding_messages(result)


def test_omitted_second_synthesis_round_breaks_derived_closure(fixture: RunFixture) -> None:
    second = fixture.run_dir / "synthesis" / "synthesis-r2.md"
    second.write_text("# Synthesis r2\n\nRefined statement.\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "canonical derived source is not registered" in combined
    assert "synthesis-r2.md" in combined


def test_registered_derived_source_outside_canonical_paths_is_error(fixture: RunFixture) -> None:
    stray = fixture.run_dir / "synthesis" / "notes.md"
    stray.write_text("# Notes\n\nSide note.\n", encoding="utf-8", newline="\n")

    def add_row(lines: list[str]) -> list[str]:
        row = (
            f"SRC-{fixture.uuid8}-0009\tderived\tSYNTHESIS\t{fixture.run_rel}/synthesis/notes.md"
            f"\t{runfixtures.sha_file(stray)}\t\t\torch.alice\t{runfixtures.SRC_SYNTHESIS}"
        )
        return [*lines[:-1], row, ""]

    edit_tsv_lines(fixture, "baseline/source-register.tsv", add_row)
    result = run_check(fixture)
    assert "is not a canonical derived path of the run" in finding_messages(result)


def test_intake_entry_without_register_row_is_error(fixture: RunFixture) -> None:
    extra = fixture.run_dir / "synthesis" / "po-decision-late.md"
    extra.write_text("# PO Decision\n\nLate input.\n", encoding="utf-8", newline="\n")
    runfixtures.append_intake_entry(
        fixture,
        intake_id=f"INT-{fixture.uuid8}-9",
        source_phase="derived",
        role="PO_DECISION",
        path=f"{fixture.run_rel}/synthesis/po-decision-late.md",
        sha256=runfixtures.sha_file(extra),
    )
    result = run_check(fixture)
    assert "intake entry has no source-register row" in finding_messages(result)


def test_intake_chain_tampering_is_detected(fixture: RunFixture) -> None:
    """Pruning intake and register together now breaks the externally pinned head."""
    intake = fixture.run_dir / "baseline" / "source-intake.tsv"
    lines = intake.read_text(encoding="utf-8").rstrip("\n").split("\n")
    intake.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8", newline="\n")
    register = fixture.run_dir / "baseline" / "source-register.tsv"
    kept = [line for line in register.read_text(encoding="utf-8").rstrip("\n").split("\n") if "dissent-map.md" not in line]
    register.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "intake chain head does not match RUN.json" in finding_messages(result)


def test_intake_entry_digest_forgery_is_detected(fixture: RunFixture) -> None:
    intake = fixture.run_dir / "baseline" / "source-intake.tsv"
    lines = intake.read_text(encoding="utf-8").rstrip("\n").split("\n")
    fields = lines[1].split("\t")
    fields[3] = f"{fixture.run_rel}/briefing-forged.md"
    lines[1] = "\t".join(fields)
    intake.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "entry_digest does not match the row content" in finding_messages(result)


def test_canonical_derived_role_mismatch_is_error(fixture: RunFixture) -> None:
    def wrong_role(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            if "dissent-map.md" in line:
                fields = line.split("\t")
                fields[2] = "SYNTHESIS"
                line = "\t".join(fields)
            out.append(line)
        return out

    edit_tsv_lines(fixture, "baseline/source-register.tsv", wrong_role)
    result = run_check(fixture)
    assert "must carry role DISSENT_MAP" in finding_messages(result)


def test_register_row_without_intake_entry_is_error(fixture: RunFixture) -> None:
    intake = fixture.run_dir / "baseline" / "source-intake.tsv"
    lines = intake.read_text(encoding="utf-8").rstrip("\n").split("\n")
    kept = [line for line in lines if "dissent-map.md" not in line]
    intake.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    assert "source-register row has no intake entry" in finding_messages(result)


def test_missing_intake_manifest_is_error(fixture: RunFixture) -> None:
    (fixture.run_dir / "baseline" / "source-intake.tsv").unlink()
    result = run_check(fixture)
    assert "append-only source intake manifest is missing" in finding_messages(result)


def test_intake_digest_drift_breaks_set_equality(fixture: RunFixture) -> None:
    intake = fixture.run_dir / "baseline" / "source-intake.tsv"
    lines = intake.read_text(encoding="utf-8").rstrip("\n").split("\n")
    fields = lines[1].split("\t")
    fields[4] = "5" * 64
    lines[1] = "\t".join(fields)
    intake.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture)
    combined = finding_messages(result)
    assert "intake entry has no source-register row" in combined
    assert "source-register row has no intake entry" in combined


def test_missing_artifact_register_is_error(fixture: RunFixture) -> None:
    (fixture.run_dir / "artifact-register.tsv").unlink()
    result = run_check(fixture)
    assert "artifact-register.tsv is mandatory from FRAMING onwards" in finding_messages(result)


def test_missing_findings_register_in_promoting_is_error(fixture: RunFixture) -> None:
    (fixture.run_dir / "findings.tsv").unlink()
    result = run_check(fixture)
    assert "findings.tsv is mandatory from PROMOTING onwards" in finding_messages(result)


def test_findings_register_optional_before_promoting(fixture: RunFixture) -> None:
    (fixture.run_dir / "findings.tsv").unlink()
    payload = fixture.read_run()
    payload["state"] = "PROPOSING"
    fixture.write_run(payload)
    result = run_check(fixture)
    assert "findings.tsv is mandatory" not in finding_messages(result)


def test_lease_token_above_run_token_is_error(fixture: RunFixture) -> None:
    lease_path = fixture.run_dir / "LEASE.json"
    payload = json.loads(lease_path.read_text(encoding="utf-8"))
    payload["fencing_token"] = 5
    runfixtures.write_json(lease_path, payload)
    result = run_check(fixture)
    assert "does not equal lease fencing_token" in finding_messages(result)
