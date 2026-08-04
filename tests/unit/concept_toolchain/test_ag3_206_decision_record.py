"""AG3-206 concept ownership and known-contradiction contracts."""

from __future__ import annotations

from pathlib import Path

_FK22 = Path("concept/technical-design/22_setup_preflight_worktree_guard_activation.md")
_FK50 = Path("concept/technical-design/50_installer_checkpoint_engine_bootstrap.md")
_RECORD = Path(
    "concept/_meta/decisions/"
    "2026-08-04-abhaengigkeitsvollstaendigkeit-und-hook-fehlersichtbarkeit.md"
)


def test_dependency_preflight_is_owned_by_fk50_not_story_setup() -> None:
    """B4: installation completeness belongs to CP 1, not setup/start."""
    fk22 = _FK22.read_text(encoding="utf-8")
    fk50 = _FK50.read_text(encoding="utf-8")

    assert "### 22.3.0 Laufzeit-Abhaengigkeiten" not in fk22
    assert 'ENVIRONMENT{"Deklarierte Runtime-' not in fk22
    assert "stdlib-only Installer-Eingangsgrenze" in fk50
    assert "`Requires-Dist`" in fk50
    assert "kein weiterer Checkpoint" in fk50


def test_decision_record_names_fk30_harness_reality_contradiction_and_owner() -> None:
    """B5: the known false consistency claim cannot silently return."""
    record = _RECORD.read_text(encoding="utf-8")
    normalized_record = " ".join(record.split())

    assert "Glossareintrag `hook-enforcement`" in record
    assert "aktuell Zeilen 71–76" in record
    assert "§30.2.4" in record
    assert "aktuell Zeilen 217–225" in record
    assert "164 `hook_non_blocking_error`" in record
    assert "FK-76 §76.1–76.2" in record
    assert "aktuell Zeilen 96–124" in record
    assert (
        "der Widerspruch bleibt deshalb ausdruecklich offen und ist kein PASS"
        in normalized_record
    )
    assert "FK-76-Owner" in record
    assert "FK-30-Owner" in record
