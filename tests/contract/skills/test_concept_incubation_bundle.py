"""Contract tests for the FK-78 concept-incubation skill bundle."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.skills.bundle_store import shipped_skill_bundles_root

if TYPE_CHECKING:
    from pathlib import Path


def _bundle_root() -> Path:
    return shipped_skill_bundles_root() / "concept-incubation-core" / "4.0.0"


def test_manifest_declares_core_profile_and_skill_name() -> None:
    manifest = json.loads((_bundle_root() / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bundle_id"] == "concept-incubation-core"
    assert manifest["bundle_version"] == "4.0.0"
    assert manifest["profile"] == "CORE"
    assert manifest["skill_name"] == "concept-incubation"
    assert manifest["variants"] == {"CORE": "concept-incubation"}


def test_bundle_ships_single_source_references_and_templates() -> None:
    root = _bundle_root()
    for relative in [
        "SKILL.md",
        "references/process-core.md",
        "references/claude-code.md",
        "references/codex.md",
        "references/participant-briefing.md",
        "templates/RUN.json",
        "templates/LEASE.json",
        "templates/ROUND.json",
        "templates/promotion-manifest.json",
        "templates/projection-manifest.json",
        "templates/concept-governance.json",
        "templates/scope-lock.json",
        "templates/projection-receipt.json",
        "templates/briefing.md",
        "templates/INDEX.md",
        "templates/tsv-headers.md",
        "templates/gitignore-fragment.txt",
    ]:
        assert (root / relative).is_file(), f"missing bundle asset: {relative}"


def test_skill_md_carries_role_gate_and_harness_self_detection() -> None:
    skill_md = (_bundle_root() / "SKILL.md").read_text(encoding="utf-8")

    for marker in [
        # Role gate (FK-78 §78.15): first action clarifies the role.
        "Rolle und Harness klaeren",
        "Council-Orchestrator",
        "Gremiums-Worker",
        # Harness self-detection resolves to the harness-specific reference.
        "references/claude-code.md",
        "references/codex.md",
        "references/process-core.md",
        "references/participant-briefing.md",
        # Staffing is always a user decision, never a silent default.
        "Niemals still eine Default-Besetzung",
        # Loss-free promotion chain markers.
        "claims-inventory",
        "disposition-ledger",
        "Round-Seal",
        "Reverse-Trace",
        "blocked_projection",
        # Toolchain gates.
        "check.py",
        "semantic_gate.py",
    ]:
        assert marker in skill_md, f"SKILL.md lost required marker: {marker}"


def test_skill_templates_are_schema_versioned_json() -> None:
    root = _bundle_root() / "templates"
    for name in [
        "RUN.json",
        "LEASE.json",
        "ROUND.json",
        "promotion-manifest.json",
        "projection-manifest.json",
        "concept-governance.json",
        "scope-lock.json",
        "projection-receipt.json",
    ]:
        payload = json.loads((root / name).read_text(encoding="utf-8"))
        assert payload["schema_version"] == "1.0.0", name


def test_scope_lock_template_matches_toolchain_catalog() -> None:
    """The published lock template must carry exactly the toolchain lock catalog."""
    payload = json.loads((_bundle_root() / "templates" / "scope-lock.json").read_text(encoding="utf-8"))
    assert set(payload) == {
        "schema_version",
        "scope_id",
        "locked_by_run",
        "fencing_token",
        "backend",
        "acquired_at",
        "ttl_seconds",
    }
    assert payload["backend"] == "filesystem"
    assert payload["fencing_token"] == 1


def test_run_template_matches_fk78_state_and_digest_contract() -> None:
    payload = json.loads(
        (_bundle_root() / "templates" / "RUN.json").read_text(encoding="utf-8")
    )
    assert payload["state"] == "FRAMING"
    assert payload["state_revision"] == 1
    digests = payload["register_digests"]
    assert set(digests) == {
        "corpus_baseline",
        "source_intake_input_head",
        "source_intake_final_head",
        "source_register_input",
        "source_units_input",
        "claims_inventory_input",
        "derived_claims",
        "disposition_ledger",
        "source_register_final",
        "source_units_final",
        "atom_register",
    }
    assert all(value is None for value in digests.values())
    assert payload["blocked"] is None
    assert payload["recheck"] is None
