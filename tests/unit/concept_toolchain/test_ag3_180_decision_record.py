"""AG3-180 normative decision-record contract."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_ag3_180_decision_record_and_secret_class_contract_are_present() -> None:
    record = (
        _REPO_ROOT
        / "concept"
        / "_meta"
        / "decisions"
        / "2026-08-03-erstzugang-bootstrap.md"
    ).read_text(encoding="utf-8")
    fk15 = (
        _REPO_ROOT
        / "concept"
        / "technical-design"
        / "15_security_secrets_identity_zugriffsmodell.md"
    ).read_text(encoding="utf-8")
    fk91 = (
        _REPO_ROOT
        / "concept"
        / "technical-design"
        / "91_api_event_katalog.md"
    ).read_text(encoding="utf-8")
    normalized_fk15 = " ".join(fk15.split())

    assert "concept_id: META-DEC-2026-08-03-ERSTZUGANG-BOOTSTRAP" in record
    assert "doc_kind: decision-record" in record
    assert "## 4. Impact-Sweep (P3/W4)" in record
    assert "## 5. Betroffenheitsmatrix" in record
    assert "`agentkit.shared`-Namespace und Deployment-Unit-Struktur" in record
    assert "ProjectEdge Credential-/Env-Vertrag" in record
    assert "Auth-Autorisierungsoberflaeche" in record
    assert "### 15.10.3 Strategen-Login (UI-BFF)" in fk15
    assert "eine anonyme HTTP-Bootstrap-Route existiert nicht" in normalized_fk15
    assert "unten benannten dedizierten Credential-Speichern" in normalized_fk15
    assert "Credential-Dateien sind weder allgemeine Konfiguration" in normalized_fk15
    assert "Argon2id-Hash" in fk15
    assert "### 15.10.4 Thin-Client-Token (Project-API)" in fk15
    assert "`agentkit auth store-token`" in fk15
    assert "Backend-Admin und Client-Bediener" in fk15
    assert "ausserhalb von AK3" in fk15
    assert "Strategenpasswort ist weder Eingabe noch Umgebungsvariable noch Datei" in normalized_fk15
    assert "Windows eine geschuetzte DACL" in fk15
    assert "`/v1/auth/password`" in fk91
    assert "gespeicherter Replay nach erneuter Anmeldung" in fk91
    assert "vor Aktivierung der ersten Credential" in fk91
    assert "### 15.8.1 Dienstspezifische Bind-Grenzen" in fk15
    assert "Loopback oder dedizierter Server gemaess FK-10" in normalized_fk15
    assert "Logout-Replay bei bereits fehlender Zielsitzung" in normalized_fk15
    assert "Profile derselben Control-Plane-Anwendung" in normalized_fk15
    assert "prozessuebergreifenden Session-Store" in normalized_fk15
    assert "an die beim Login aktive Passwortgeneration gebunden" in normalized_fk15
    assert "greift nicht auf den Laptop-Dateibaum zu" in normalized_fk15
    assert "FK-72 §72.8 BFF-Topologie" in record
    assert "schema-geschlossen" in normalized_fk15
    assert "`last_rotation_op_id`" in normalized_fk15
    assert "[--op-id {op_id}]` | 15 | Duenner Adapter auf Login und `DELETE" in fk91
    assert "Alle AgentKit-Dienste laufen auf `localhost`" not in fk15
    for auth_command in (
        "agentkit auth bootstrap",
        "agentkit auth login",
        "agentkit auth rotate-password",
        "agentkit auth issue-token",
        "agentkit auth revoke-token",
    ):
        assert auth_command in fk91
    assert "einzige Ausnahme ist `agentkit auth bootstrap`" in " ".join(fk91.split())


def test_ag3_180_does_not_create_a_shared_deployment_unit_or_edge_backend_import() -> None:
    shared = _REPO_ROOT / "src" / "agentkit" / "shared"
    edge_credential_sources = (
        _REPO_ROOT / "src" / "agentkit" / "harness_client" / "projectedge"
    ).glob("*credential*.py")

    assert list(shared.glob("*.py")) == []
    for source in edge_credential_sources:
        assert "agentkit.backend" not in source.read_text(encoding="utf-8")


def test_edge_core_distribution_record_has_w4_evidence_and_real_story_locators() -> None:
    record = (
        _REPO_ROOT
        / "concept"
        / "_meta"
        / "decisions"
        / "2026-08-03-edge-und-kern-sind-zwei-distributionen.md"
    ).read_text(encoding="utf-8")

    assert "## 6. Impact-Sweep (P3/W4)" in record
    assert "## 7. Betroffenheitsmatrix" in record
    assert "**AG3-208**" in record
    assert "**AG3-209**" in record
    assert "**AG3-210**" in record
    assert "AG3-207" not in record
