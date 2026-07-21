"""Projection-manifest check tests (FK-78 section 78.12, activation hardening)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_toolchain import runmodel
from concept_toolchain.config import load_governance_config
from concept_toolchain.projection_check import run_projection_check
from concept_toolchain.receipts import compute_target_digest
from tests.unit.concept_toolchain import runfixtures
from tests.unit.concept_toolchain.conftest import concept_doc, write_doc
from tests.unit.concept_toolchain.runfixtures import (
    RunFixture,
    build_promotion_run,
    refresh_normative_coverage,
    sha_file,
    write_json,
)

if TYPE_CHECKING:
    from pathlib import Path

    from concept_toolchain.findings import CheckResult

MANIFEST_REL = "concept/_meta/projection-manifest.json"
DECISION_REL = "concept/_meta/decisions/2026-07-19-sample.md"
SOURCE_REL = "concept/domain-design/05-sample-scope.md"


def section_digest(project_root: Path, rel_path: str, anchor: str) -> str:
    result = compute_target_digest(project_root, f"{rel_path}#{anchor}", "markdown-section", None)
    assert result.digest is not None, result
    return result.digest


pytestmark = pytest.mark.requires_git


@pytest.fixture
def fixture(green_corpus: Path) -> RunFixture:
    return build_promotion_run(green_corpus, use_git=True)


def write_decision(project_root: Path, *, decision_status: str | None = "accepted") -> None:
    status_line = f"decision_status: {decision_status}\n" if decision_status is not None else ""
    write_doc(
        project_root,
        DECISION_REL,
        f"---\ndecision_id: 2026-07-19-sample\n{status_line}---\n\n# Decision\n\nAccepted sample scope.\n",
    )


def write_assertion_source(project_root: Path) -> None:
    write_doc(project_root, SOURCE_REL, concept_doc("DK-05", title="Sample scope owner", scopes=("sample-scope",)))


def bound_entry(fixture: RunFixture) -> dict[str, object]:
    """A green, fully bound manifest entry for the fixture's promoted scope."""
    project_root = fixture.project_root
    write_decision(project_root)
    write_assertion_source(project_root)
    return {
        "scope_id": fixture.scope_id,
        "lifecycle": "current",
        "lifecycle_source": {
            "decision_id": "2026-07-19-sample",
            "path": DECISION_REL,
            "digest": sha_file(project_root / DECISION_REL),
            "status": "accepted",
        },
        "assertion_source": {"path": SOURCE_REL, "digest": sha_file(project_root / SOURCE_REL)},
        "assertion_status": "active",
        "required_projections": [
            {
                "kind": "prose",
                "target": f"{fixture.target_rel}#promoted-addition",
                "target_mode": "markdown-section",
                "target_digest": section_digest(project_root, fixture.target_rel, "promoted-addition"),
                "receipt_ref": fixture.receipt_path.relative_to(project_root).as_posix(),
                "equivalence_status": "equivalent",
            }
        ],
        "blockers": [],
        "last_run_id": fixture.run_id,
        "last_promotion_manifest": {
            "path": fixture.manifest_path.relative_to(project_root).as_posix(),
            "digest": sha_file(fixture.manifest_path),
        },
    }


def write_manifest(project_root: Path, entries: list[dict[str, object]], fixture: RunFixture | None = None) -> None:
    (project_root / MANIFEST_REL).write_text(
        json.dumps({"schema_version": "1.0.0", "entries": entries}, indent=2), encoding="utf-8"
    )
    if fixture is not None:
        refresh_normative_coverage(fixture)


def run_check(project_root: Path) -> CheckResult:
    config = load_governance_config(project_root)
    return run_projection_check(project_root, config)


def finding_messages(result: CheckResult) -> str:
    return " | ".join(f"{finding.locator}: {finding.message}" for finding in result.findings)


def test_missing_manifest_is_incomplete(green_corpus: Path) -> None:
    (green_corpus / MANIFEST_REL).unlink()
    result = run_check(green_corpus)
    assert result.complete is False


def test_green_bound_entry_activates(fixture: RunFixture) -> None:
    write_manifest(fixture.project_root, [bound_entry(fixture)], fixture)
    result = run_check(fixture.project_root)
    assert result.findings == [], finding_messages(result)


def test_unknown_manifest_field_is_fail_closed(fixture: RunFixture) -> None:
    entry = bound_entry(fixture) | {"surprise": True}
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "unknown field 'surprise'" in finding_messages(result)


def test_stale_assertion_source_is_reported(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    source = entry["assertion_source"]
    assert isinstance(source, dict)
    source["digest"] = "0" * 64
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "stale-source" in finding_messages(result)


def test_missing_receipt_derives_unreviewed_mismatch(fixture: RunFixture) -> None:
    fixture.receipt_path.unlink()
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "derived status mismatch: recorded 'equivalent', derived 'unreviewed'" in combined
    assert "recorded 'active', derived 'blocked_projection'" in combined


def test_missing_target_derives_blocked_missing_target(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0]["target"] = "concept/technical-design/99_missing.md"
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "derived 'blocked_missing_target'" in finding_messages(result)


def test_target_digest_drift_derives_stale(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0]["target_digest"] = "0" * 64
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "derived 'stale'" in finding_messages(result)


def test_null_target_digest_blocks_activation(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0]["target_digest"] = None
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "recorded 'active', derived 'blocked_projection'" in finding_messages(result)


def test_receipt_with_same_principal_does_not_activate(fixture: RunFixture) -> None:
    payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    payload["reviewer_principal_id"] = payload["writer_principal_id"]
    write_json(fixture.receipt_path, payload)
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "reviewer principal must differ from the writer principal" in combined
    assert "derived 'unreviewed'" in combined


def test_receipt_outside_run_receipts_dir_is_rejected(fixture: RunFixture) -> None:
    foreign_rel = "concept-incubator/foreign-receipt.json"
    (fixture.project_root / foreign_rel).write_text(fixture.receipt_path.read_text(encoding="utf-8"), encoding="utf-8")
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0]["receipt_ref"] = foreign_rel
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "is not registered under the run's receipts_dir" in finding_messages(result)


def test_receipt_for_unclaimed_scope_is_rejected(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["scope_id"] = "sample-scope-b"
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "which this entry does not claim" in finding_messages(result)


def test_missing_decision_status_field_is_error(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    write_decision(fixture.project_root, decision_status=None)
    lifecycle_source = entry["lifecycle_source"]
    assert isinstance(lifecycle_source, dict)
    lifecycle_source["digest"] = sha_file(fixture.project_root / DECISION_REL)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "machine-readable decision_status" in finding_messages(result)


def test_unaccepted_decision_blocks_current_lifecycle(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    write_decision(fixture.project_root, decision_status="proposed")
    lifecycle_source = entry["lifecycle_source"]
    assert isinstance(lifecycle_source, dict)
    lifecycle_source["digest"] = sha_file(fixture.project_root / DECISION_REL)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "does not match the decision record's decision_status 'proposed'" in combined
    assert "current lifecycle requires an accepted decision record" in combined


def test_lifecycle_source_digest_mismatch_is_error(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    lifecycle_source = entry["lifecycle_source"]
    assert isinstance(lifecycle_source, dict)
    lifecycle_source["digest"] = "0" * 64
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "decision record digest does not match" in finding_messages(result)


def test_authority_coverage_flags_missing_and_surplus_scopes(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["covered_scope_ids"] = ["scope-not-owned"]
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "claimed scope 'scope-not-owned' is not derived" in finding_messages(result)
    entry = bound_entry(fixture)
    doc_path = fixture.project_root / SOURCE_REL
    text = doc_path.read_text(encoding="utf-8").replace(
        "authority_over:\n  - scope: sample-scope",
        "authority_over:\n  - scope: sample-scope\n  - scope: extra-scope",
    )
    doc_path.write_text(text, encoding="utf-8", newline="\n")
    entry["assertion_source"] = {"path": SOURCE_REL, "digest": sha_file(doc_path)}
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "authority scope 'extra-scope' of an assertion source is not covered" in finding_messages(result)


def test_covered_scope_ids_must_be_disjoint(fixture: RunFixture) -> None:
    first = bound_entry(fixture) | {"covered_scope_ids": ["shared-scope"]}
    second = bound_entry(fixture) | {"scope_id": "scope-b", "covered_scope_ids": ["shared-scope"]}
    write_manifest(fixture.project_root, [first, second], fixture)
    result = run_check(fixture.project_root)
    assert "must be disjoint" in finding_messages(result)


def test_formal_projection_resolves_by_object_id(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["assertion_status"] = "blocked_projection"
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    formal_path = fixture.project_root / "concept/formal-spec/sample/state-machine.md"
    projections[0].update(
        {
            "kind": "formal",
            "target": "formal.sample.state-machine",
            "target_mode": "whole-file",
            "target_digest": sha_file(formal_path),
            "receipt_ref": None,
            "equivalence_status": "unreviewed",
        }
    )
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert result.findings == [], finding_messages(result)


def test_self_projection_uses_canonical_entry_digest(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["assertion_status"] = "blocked_projection"
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0].update(
        {
            "kind": "support",
            "target": MANIFEST_REL,
            "target_mode": "whole-file",
            "target_digest": None,
            "receipt_ref": None,
            "equivalence_status": "unreviewed",
        }
    )
    projections[0]["target_digest"] = runmodel.canonical_projection_entry_digest(entry, MANIFEST_REL)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert result.findings == [], finding_messages(result)
    projections[0]["target_digest"] = "0" * 64
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "derived 'stale'" in finding_messages(result)


def test_blocker_anchor_must_resolve(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["assertion_status"] = "blocked_projection"
    entry["blockers"] = [{"reason": "pending", "owner": "po", "visible_anchor": f"{fixture.target_rel}#no-such-anchor"}]
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "visible_anchor does not resolve" in finding_messages(result)


def test_missing_last_promotion_manifest_pointer_blocks_activation(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["last_promotion_manifest"] = None
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "requires a last_promotion_manifest pointer" in combined
    assert "derived 'unreviewed'" in combined


def test_stale_last_promotion_manifest_digest_is_error(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    pointer = entry["last_promotion_manifest"]
    assert isinstance(pointer, dict)
    pointer["digest"] = "0" * 64
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "last_promotion_manifest digest does not match" in finding_messages(result)


def test_unpinned_atom_register_blocks_activation(fixture: RunFixture) -> None:
    payload = fixture.read_run()
    digests = payload["register_digests"]
    assert isinstance(digests, dict)
    digests["atom_register"] = "0" * 64
    fixture.write_run(payload)
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "does not match its pinned register_digests digest" in finding_messages(result)


def test_forged_receipt_source_digest_blocks_activation(fixture: RunFixture) -> None:
    payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    payload["source_digest"] = "7" * 64
    write_json(fixture.receipt_path, payload)
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "source_digest does not match the atom statement" in combined
    assert "derived 'unreviewed'" in combined


def test_forged_receipt_target_section_digest_blocks_activation(fixture: RunFixture) -> None:
    payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    payload["target_section_digest"] = "8" * 64
    write_json(fixture.receipt_path, payload)
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "target_section_digest does not match the current target" in finding_messages(result)


def test_unpromoted_scope_blocks_activation(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    scopes = manifest["scopes"]
    assert isinstance(scopes, list) and isinstance(scopes[0], dict)
    scopes[0]["promotion_disposition"] = "deferred"
    scopes[0]["blockers"] = [
        {"reason": "pending", "atom_ids": [], "owner": "po", "visible_anchor": f"{fixture.target_rel}#promoted-addition"}
    ]
    fixture.write_manifest(manifest)
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "not 'promoted'" in finding_messages(result)


def test_whole_file_mode_activates_a_json_target(fixture: RunFixture) -> None:
    """Registries/JSON targets are receiptable via whole-file digests."""
    target_rel = "concept/_meta/concept-governance.json"
    receipt_id = f"RCP-{fixture.uuid8}-0002"
    atom_id = f"ATM-{fixture.uuid8}-0002"
    statement = "The governance configuration must declare the lock backend."
    runfixtures.add_whole_file_atom(
        fixture, atom_id=atom_id, receipt_id=receipt_id, statement=statement, target_rel=target_rel
    )
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0].update(
        {
            "kind": "support",
            "target": target_rel,
            "target_mode": "whole-file",
            "target_digest": sha_file(fixture.project_root / target_rel),
            "receipt_ref": (fixture.run_dir / "promotion" / "receipts" / f"{receipt_id}.json")
            .relative_to(fixture.project_root)
            .as_posix(),
        }
    )
    entry["last_promotion_manifest"] = {
        "path": fixture.manifest_path.relative_to(fixture.project_root).as_posix(),
        "digest": sha_file(fixture.manifest_path),
    }
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert result.findings == [], finding_messages(result)


def test_receipt_mode_mismatch_blocks_activation(fixture: RunFixture) -> None:
    """A receipt claiming whole-file cannot satisfy a markdown-section projection."""
    payload = json.loads(fixture.receipt_path.read_text(encoding="utf-8"))
    payload["target_mode"] = "whole-file"
    payload["target"] = {"path": fixture.target_rel, "anchor": ""}
    write_json(fixture.receipt_path, payload)
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "declares target_mode 'whole-file' but 'markdown-section' is required here" in combined
    assert "derived 'unreviewed'" in combined


def test_directory_tree_mode_requires_non_null_digest(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["assertion_status"] = "blocked_projection"
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0].update(
        {
            "kind": "support",
            "target": "concept/technical-design",
            "target_mode": "directory-tree",
            "target_digest": None,
            "receipt_ref": None,
            "equivalence_status": "unreviewed",
        }
    )
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert result.findings == [], finding_messages(result)
    projections[0]["target_digest"] = "0" * 64
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "derived 'stale'" in finding_messages(result)


def test_selector_mode_is_validated(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    entry["assertion_status"] = "blocked_projection"
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0].update(
        {
            "kind": "support",
            "target": "concept/_meta/concept-governance.json",
            "target_mode": "structured-selector",
            "selector": "concept_roots",
            "target_digest": "0" * 64,
            "receipt_ref": None,
            "equivalence_status": "stale",
        }
    )
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert result.findings == [], finding_messages(result)


def test_selector_without_structured_mode_is_fail_closed(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    projections[0]["selector"] = "roots"
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "only allowed for target_mode 'structured-selector'" in finding_messages(result)


def test_missing_target_mode_is_fail_closed(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    projections = entry["required_projections"]
    assert isinstance(projections, list) and isinstance(projections[0], dict)
    del projections[0]["target_mode"]
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    assert "missing required field 'target_mode'" in finding_messages(result)


def test_broken_coverage_register_blocks_activation(fixture: RunFixture) -> None:
    """A self-consistent manifest cannot activate when the run's coverage is broken."""
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    coverage = fixture.run_dir / "baseline" / "source-coverage.tsv"
    lines = coverage.read_text(encoding="utf-8").rstrip("\n").split("\n")
    coverage.write_text(lines[0] + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "promotion closure for run" in combined
    assert "has no final coverage row" in combined


def test_open_finding_in_promoting_run_blocks_activation(fixture: RunFixture) -> None:
    entry = bound_entry(fixture)
    write_manifest(fixture.project_root, [entry], fixture)
    findings_path = fixture.run_dir / "findings.tsv"
    row = f"FND-{fixture.uuid8}-0001\tP1\topen\t\t\t{fixture.target_rel}\tL1\tUnresolved gap\t"
    findings_path.write_text(findings_path.read_text(encoding="utf-8") + row + "\n", encoding="utf-8", newline="\n")
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "promotion closure for run" in combined
    assert "open finding(s)" in combined


def test_missing_required_support_path_blocks_activation(fixture: RunFixture) -> None:
    manifest = fixture.read_manifest()
    required = manifest["required_support_paths"]
    assert isinstance(required, list)
    required.append("does/not/exist.md")
    fixture.write_manifest(manifest)
    entry = bound_entry(fixture)
    entry["last_promotion_manifest"] = {
        "path": fixture.manifest_path.relative_to(fixture.project_root).as_posix(),
        "digest": sha_file(fixture.manifest_path),
    }
    write_manifest(fixture.project_root, [entry], fixture)
    result = run_check(fixture.project_root)
    combined = finding_messages(result)
    assert "promotion closure for run" in combined
    assert "support path does not exist" in combined
