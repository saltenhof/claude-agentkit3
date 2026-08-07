"""AG3-214 normative single-writer and current boot-flow contract."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_decision_record_has_w4_matrix_and_both_po_decisions() -> None:
    record = _read(
        "concept/_meta/decisions/2026-08-04-ein-writer-ein-vertrag.md",
    )

    assert "concept_id: META-DEC-2026-08-04-EIN-WRITER-EIN-VERTRAG" in record
    assert "## 4. Impact-Sweep (P3/W4)" in record
    assert "## 5. Betroffenheitsmatrix" in record
    assert "Eine Datenbank hat einen Writer-Prozess mit zwei Listenern" in record
    assert "Jeder In-Flight-Claim traegt denselben Absendervertrag" in record
    assert "AG3-137 und AG3-138 tragen keinen Gegengrund" in record
    assert "FK-41 §41.9" in record
    assert "FK-50 CP 7–CP 10d" in record
    assert "FK-53 §53.3/§53.5" in record
    assert "FK-58 §58.5/§58.6" in record
    assert "Pool-Fallback noch Late-Commit" in record


def test_fk10_boot_command_is_single_process_and_tls_complete() -> None:
    fk10 = _read("concept/technical-design/10_runtime_deployment_speicher.md")

    # AG3-208 hat den blossen Scriptnamen `agentkit` zurueckgezogen; `serve`
    # liefert die Kern-Distribution als `agentkit-backend` aus (FK-10 §10.2.11).
    # Die Zusage dieses Tests ist unveraendert: EIN Bootbefehl startet BEIDE
    # Listener, und er ist TLS-vollstaendig.
    assert "agentkit-backend serve --ui-host 127.0.0.1 --ui-port 9701" in fk10
    assert "--project-host 127.0.0.1 --project-port 9702" in fk10
    assert "--certfile var/core-tls/core-cert.pem" in fk10
    assert "--keyfile var/core-tls/core-key.pem" in fk10
    # Die Negativhaelfte muss den HEUTIGEN Scriptnamen tragen. Mit dem alten
    # `agentkit serve --ui-bff` koennte sie nach der Umbenennung nie mehr
    # fehlschlagen -- sie waere gruen, ohne noch etwas zu bewachen.
    assert "agentkit-backend serve --ui-bff" not in fk10
    assert "agentkit-backend serve --project-api" not in fk10


def test_runtime_port_defaults_name_the_shared_writer_process() -> None:
    defaults = _read("src/agentkit/backend/config/defaults.py")

    assert defaults.count("shared ``agentkit serve`` writer process") == 2
    assert "--ui-bff" not in defaults
    assert "--project-api" not in defaults


def test_fk15_and_fk91_pin_real_listener_and_auth_contracts() -> None:
    fk15 = " ".join(
        _read("concept/technical-design/15_security_secrets_identity_zugriffsmodell.md").split(),
    )
    fk91 = _read("concept/technical-design/91_api_event_katalog.md")

    assert "zwei HTTPS-Listener **derselben Control-Plane-Laufzeit" in fk15
    assert "eigenen Auth-Middleware-Kontext" in fk15
    assert "Der UI-BFF akzeptiert keine Project-Tokens" in fk15
    assert "agentkit auth store-token --project-key" in fk91
    assert "agentkit auth issue-token --project-key {project_key} --base-url" in fk91
    assert "agentkit auth revoke-token --project-key {project_key} --token-id" in fk91
    assert fk91.count("[--ca-file {path}]") == 13
    assert "/stories/{story_id}/split` | `POST`" in fk91
    assert "/stories/{story_id}/reset` | `POST`" in fk91
    assert "/stories/{story_id}/exit` | `POST`" in fk91
    assert "agentkit admin-abort {op_id}" in fk91
    assert "der CLI-Prozess mutiert keinen State" in fk91
    assert "noch kein einziges" in fk91


def test_failure_corpus_mutations_are_normative_writer_routes() -> None:
    fk41 = _read(
        "concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md",
    )
    fk91 = _read("concept/technical-design/91_api_event_katalog.md")

    route_suffixes = (
        "/failure-corpus/incidents",
        "/failure-corpus/patterns/{pattern_id}/review",
        "/failure-corpus/checks/{check_id}/review",
        "/failure-corpus/effectiveness-report",
    )
    for suffix in route_suffixes:
        assert suffix in fk41
        assert suffix in fk91
    assert "BackendUnreachable" in fk41
    assert "ohne lokalen Repository- oder In-Process-Fallback" in fk41
    assert "409 idempotency_mismatch" in fk41
    assert "409 operation_in_flight" in fk41
    assert "kein Project-Edge-Materialisierungsbundle" in fk41
    assert fk91.count("[--op-id {op_id}]") >= 4
    assert "Failure-Corpus-Mutationen" in fk91


def test_installer_writer_violation_is_explicitly_resolved() -> None:
    record = _read(
        "concept/_meta/decisions/2026-08-04-ein-writer-ein-vertrag.md",
    )
    fk10 = _read("concept/technical-design/10_runtime_deployment_speicher.md")
    fk91 = _read("concept/technical-design/91_api_event_katalog.md")

    fk50 = _read("concept/technical-design/50_installer_checkpoint_engine_bootstrap.md")
    fk51 = _read(
        "concept/technical-design/51_upgrade_migration_customization_preservation.md",
    )

    for document in (record, fk10, fk91):
        normalized = " ".join(document.split())
        assert "BEHOBENER VERSTOSS — Stand 2026-08-05" in document
        assert "register-project" in document
        assert "upgrade-project" in document
        assert "installer_commands.py" in document
        assert "_cmd_register_project" in document
        assert "installer/runner.py" in document
        assert "installer/upgrade/entry.py" in document
        assert "run_checkpoint_upgrade" in document
        assert "installer/upgrade/engine.py" in document
        assert "up_04_migrate_hooks" in document
        assert "lokaler" in normalized and "Fallback" in normalized
    normalized_record = " ".join(record.split())
    assert "Alternative **(a)" in record
    assert "erwirbt die Lease nicht selbst" in normalized_record
    assert "systemweit umsetzbar" in record
    assert "installation/writer-ready" in fk50
    assert "installation/register-project" in fk50
    assert "installation/skill-bindings" in fk50
    assert "installation/governance-hooks" in fk50
    normalized_fk51 = " ".join(fk51.split())
    assert "UP 04" in fk51
    assert "vor jeder lokalen Upgrade-Wirkung fail-closed" in normalized_fk51


def test_installer_endpoints_and_cli_are_writer_backed() -> None:
    fk91 = _read("concept/technical-design/91_api_event_katalog.md")

    for suffix in (
        "/installation/writer-ready",
        "/installation/register-project",
        "/installation/project-registration",
        "/installation/skill-bindings",
        "/installation/governance-hooks",
    ):
        assert suffix in fk91
    assert "agentkit register-project --project-key" in fk91
    assert "agentkit upgrade-project --project-key" in fk91
    assert "Root-`op_id`" in fk91
    assert "weder lokalen Fallback noch eine vom Installer selbst erworbene Lease" in fk91


def test_installer_writer_routes_delegate_state_to_owner_without_repository_access() -> None:
    cli = _read("src/agentkit/backend/cli/installer_commands.py")
    runner = _read("src/agentkit/backend/installer/runner.py")
    upgrade_entry = _read("src/agentkit/backend/installer/upgrade/entry.py")
    writer_routes = _read(
        "src/agentkit/backend/control_plane_http/installer_writer_routes.py",
    )
    writer_service = _read("src/agentkit/backend/installer/writer_service.py")
    composition = _read("src/agentkit/backend/bootstrap/composition_installer.py")
    http_models = _read("src/agentkit/backend/installer/http_models.py")
    writer_client = _read("src/agentkit/backend/installer/writer_client.py")
    auth_commands = _read("src/agentkit/backend/cli/auth_commands.py")

    forbidden_constructors = (
        "StateBackendProjectRegistrationRepository(",
        "StateBackendProjectRepository(",
        "StateBackendSkillBindingRepository(",
        "StateBackendHookRegistrationRepository(",
        "LockRecordRepository(",
    )
    for source in (cli, runner, upgrade_entry):
        for constructor in forbidden_constructors:
            assert constructor not in source
    for constructor in forbidden_constructors[:-1]:
        assert constructor not in writer_routes
        assert constructor in composition
    assert "self._owner" in writer_routes
    assert "state_backend" not in writer_routes
    assert "SkillBindingRepository" in writer_service
    assert "from agentkit.backend.skills import" in writer_service
    assert "agentkit.backend.skills.binding" not in http_models
    assert "agentkit.backend.skills.binding" not in writer_client
    assert ").assert_ready()" in auth_commands
    assert auth_commands.index(").assert_ready()") < auth_commands.index(
        "credential_lock = exclusive_private_file_lock(credential_path)",
    )
    assert "no local State-Backend fallback is permitted" in runner
    assert "ControlPlaneWriterRequired" in upgrade_entry


def test_server_entry_and_atomic_storyless_recovery_are_normative() -> None:
    fk10 = " ".join(
        _read("concept/technical-design/10_runtime_deployment_speicher.md").split(),
    )
    fk50 = " ".join(
        _read(
            "concept/technical-design/50_installer_checkpoint_engine_bootstrap.md",
        ).split(),
    )
    fk91 = " ".join(
        _read("concept/technical-design/91_api_event_katalog.md").split(),
    )

    assert "injizierte Anwendungen und Startup-Hooks" in fk10
    assert "bindet keinen der beiden" in fk10
    assert "`credentials.lock`" in fk10
    assert "gesamte lokale Projektbaum bytegleich" in fk10
    assert "beiden CP-7-Wirkungen und die erfolgreiche Finalisierung" in fk50
    assert "Same-`op_id`-Retry" in fk91
    assert "String `\"None\"`" in fk91


def test_writer_liveness_and_background_work_are_normative() -> None:
    fk10 = _read("concept/technical-design/10_runtime_deployment_speicher.md")
    fk50 = " ".join(
        _read(
            "concept/technical-design/50_installer_checkpoint_engine_bootstrap.md",
        )
        .replace("-\n", "-")
        .split(),
    )
    fk91 = _read("concept/technical-design/91_api_event_katalog.md")

    assert "Liveness-Monitor prueft die Lease" in fk10
    assert "asynchrone Writer-Arbeit vollstaendig gedraint" in fk10
    assert "Future bleibt bis zur vollstaendigen terminalen Guard-Finalisierung" in fk50
    assert "keine normale Pool-Verbindung als Ersatz" in fk50
    assert "jede Claim-Schreibgrenze weist fehlende" in fk91


def test_reset_and_exit_are_authenticated_writer_routes() -> None:
    fk53 = _read("concept/technical-design/53_story_reset_service_recovery_flow.md")
    fk58 = " ".join(
        _read("concept/technical-design/58_story_exit_human_takeover_handoff.md")
        .replace("-\n", "-")
        .split(),
    )

    assert "/stories/{story_id}/reset" in fk53
    assert "serverseitig authentisierten Session" in fk53
    assert "Claim-Schreibgrenze ein harter Fehler" in fk53
    assert "/stories/{story_id}/exit" in fk58
    assert "autoritativen Ownership-State" in fk58
    assert "Claim-Owner-CAS derselben Epoche" in fk58
