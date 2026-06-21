# AG3-005: Schema-Versionierung mit Side-by-Side-Datenbanken

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** Keine
**Quell-Konzept:** FK-18 §18.9a

---

## Kontext

AK3 verzichtet bewusst auf ein Migrations-Framework. Stattdessen
fuehrt jede Schema-Version eine **eigene Datenbank** — beim
Versions-Wechsel wird automatisch eine **neue, leere DB daneben**
angelegt; die alte bleibt unangetastet.

Konzeptionell festgelegt (FK-18 §18.9a):

- **Schema-Version als Konstante** im Code (SemVer)
- **DB-Bezeichnung enthaelt die Version**: Postgres-Schema
  `ak3_v3_0_0`, SQLite-Datei `agentkit_3_0_0.sqlite`
- **Bootstrap-Verhalten**: bei AK3-Start prueft der Driver, ob fuer
  die aktuelle `SCHEMA_VERSION` eine DB existiert; falls nicht, wird
  sie leer angelegt; die alte DB bleibt
- **Pre-1.0**: Schema-Wechsel = destructive reset (kein Bestand)
- **Migration zwischen Versionen** ist separate, vom Strategen
  gestartete Aktion (nicht Auto-Boot-Verhalten) — heute nicht
  spezifiziert

## Scope

### In Scope

- Neue Konstante `agentkit.backend.state_backend.config.SCHEMA_VERSION`
  (z. B. `"3.0.0"`)
- Postgres-Driver:
  - Schema-Name aus Versions-Konstante ableiten
    (`f"ak3_v{version.replace('.', '_')}"`)
  - Bootstrap: `CREATE SCHEMA IF NOT EXISTS {versioned_schema}`,
    danach DDL aus `postgres_schema.sql` im versionierten Schema
    anwenden
  - `search_path` der Verbindung auf das versionierte Schema setzen
- SQLite-Driver:
  - Datei-Name aus Versions-Konstante ableiten
    (`agentkit_{version.replace('.', '_')}.sqlite`)
  - Bootstrap: Datei anlegen, falls nicht vorhanden, danach DDL
    anwenden
- Konfiguration: bestehende DB-Konfigurations-Schluessel
  unveraendert lassen (`base_url`/`db_dir`/etc.); der Versions-Praefix
  ist intern aus `SCHEMA_VERSION` abgeleitet, nicht extern konfiguriert
- Tests:
  - Schema-Anlage funktioniert idempotent (zweiter Bootstrap-Lauf
    ist No-Op)
  - Bei Aenderung der `SCHEMA_VERSION` wird eine neue, leere DB
    angelegt; alte bleibt
  - SQLite-Datei-Pfade enthalten Version
  - Postgres-Schema-Namen enthalten Version
- Dokumentation im Modul-Docstring und in FK-18 §18.9a (kleine
  Verweise auf konkrete Konstanten und Datei-Pfade)

### Out of Scope

- `agentkit migrate --from=... --to=...`-Befehl (kommt erst, wenn
  reale Migrations-Anforderung entsteht)
- Auto-Detection alter DB-Versionen mit Hinweis-Anzeige
- Schema-Diff-Tools
- Rollback-Pfade (Rollback = Wechsel zur alten Version, die ihre
  eigene DB hat)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|--------------|--------------|
| `src/agentkit/state_backend/config.py` | Modifiziert | Neue Konstante `SCHEMA_VERSION` |
| `src/agentkit/state_backend/postgres_store.py` | Modifiziert | Versionierter Schema-Name, Bootstrap-Verhalten |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | Versionierter Datei-Name, Bootstrap-Verhalten |
| `src/agentkit/state_backend/postgres_schema.sql` | Pruefen | DDL muss schema-relativ sein, nicht hardcoded auf `public.` |
| `tests/unit/state_backend/test_schema_versioning.py` | Neu | Versions-abgeleiteter DB-Name, Bootstrap-Idempotenz, Side-by-Side-Verhalten |
| `tests/integration/state_backend/test_schema_versioning_e2e.py` | Neu | End-to-End: zwei Versionen parallel, beide funktionsfaehig |

## Akzeptanzkriterien

1. **`SCHEMA_VERSION`-Konstante existiert** in `agentkit.backend.state_backend.config` und wird als SemVer-String gepflegt.
2. **Postgres-Schema-Name enthaelt die Version**: `ak3_v3_0_0` (oder analog). DDL-Anwendung erfolgt im versionierten Schema.
3. **SQLite-Datei-Name enthaelt die Version**: `agentkit_3_0_0.sqlite` (oder analog).
4. **Bootstrap legt automatisch eine neue, leere DB an**, wenn die Version geaendert wurde. Alte DB bleibt erreichbar.
5. **Bootstrap ist idempotent**: zweiter Lauf bei gleicher Version ist No-Op.
6. **Tests gruen**, ruff, mypy strict, alle drei concept-lints, architecture-conformance-Audit clean.
7. **Keine bestehenden Tests brechen**: alle vorhandenen Repository- und Driver-Tests laufen weiter.

## Definition of Done

- Build kompiliert
- Unit + Integration-Tests gruen
- Lints clean
- Smoke-Test: AK3 mit `SCHEMA_VERSION = "3.0.0"` startet, dann
  manuell auf `"3.1.0"` aendern, neuer Start legt neue DB an, alte
  bleibt im DB-Server vorhanden

## Konzept-Referenzen

- FK-18 (`concept/technical-design/18_relationales_abbildungsmodell_postgres.md`) §18.9a — Schema-Versionierung
- FK-50 (`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md`) — Bootstrap-Verhalten

## Guardrail-Referenzen

- ZERO DEBT: keine "spaeter migrieren wir mal"-Faelle
- FAIL CLOSED: bei DB-Schema-Mismatch klar fehlschlagen, nicht
  raten
- SINGLE SOURCE OF TRUTH: jede Version hat ihre eigene DB; keine
  zweite Wahrheit
