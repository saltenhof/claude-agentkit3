# artifacts — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `artifacts` |
| Display-Name | `Artefakte (Envelope, Producer-Registry, Klassen)` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `FK-71`, `bc-cut-decisions.md §BC 8` |
| Codebase-Hauptpfade | `src/agentkit/state_backend/`, `src/agentkit/verify_system/artifacts.py`, `src/agentkit/verify_system/policy_engine/projections.py` |

## 1. Executive Summary

Das Modul `agentkit.artifacts` existiert als eigenstaendiges Paket nicht. Die im Konzept definierten Klassen `ArtifactManager`, `ArtifactEnvelope`, `ArtifactClass`, `ArtifactReference`, `EnvelopeValidator`, `ProducerRegistry` und verwandte Typen sind vollstaendig unimplementiert. Artefakt-relevante Logik ist stattdessen ueber `state_backend/` (Schema-Tabellen, rudimentaere artifact_class-Heuristik), `verify_system/artifacts.py` (QA-Artefakt-Persistenz) und `verify_system/policy_engine/projections.py` (Envelope-Serialisierung) verstreut — ohne Eigentuemer, ohne typisiertes Envelope-Modell, ohne Producer-Registry-Validierung. Die Implementierung entspricht konzeptionell dem v2-Muster (implizite Datenfluesse, unklare Ownership), das v3 explizit vermeiden soll.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 7 |
| B — Teilweise umgesetzt | 4 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **Paket `agentkit.artifacts` als Top-Modul** mit ca. 9 Klassen: `ArtifactManager`, `ArtifactClass`, `ArtifactReference`, `ArtifactEnvelope`, `EnvelopeStatus`, `Producer`, `ProducerType`, `ProducerId`, `EnvelopeValidator` — `bc-cut-decisions.md §BC 8`
- **`ArtifactManager` mit typisierter Top-Surface** (`write`, `read`, `exists` gegen State-Backend-Driver) als zentrale Schreib-/Lese-Koordination fuer alle Artefaktklassen — `bc-cut-decisions.md §BC 8`
- **`ArtifactEnvelope` als typisiertes Pydantic-Modell** mit Pflichtfeldern `schema_version="3.0"`, `story_id`, `run_id`, `stage`, `attempt`, `producer.type`, `producer.name`, `started_at`, `finished_at`, `status` — `FK-71 §71.2`
- **`EnvelopeValidator` im Top** fuer Pflichtfeld-Pruefung (nicht producer-spezifisch) — `bc-cut-decisions.md §BC 8`
- **Typisierte Artefaktklassen** (`ArtifactClass`-Enum): Worker-Artefakt, QA-Artefakt, Pipeline-Artefakt, Telemetrie, Governance-Artefakt, Entwurfsartefakt, Handover-Artefakt, Adversarial-Test-Sandbox — `FK-71 §71.1.1`
- **Typisierte `ArtifactReference`** mit Feldern `artifact_class`, `story_id`, `run_id` und kanonalem Pfad/Record-ID — `FK-71 Glossar`
- **`ProducerRegistry` als Sub** (`agentkit.artifacts.producer_registry`) mit Mapping Export-Artefakt -> erlaubter Producer-Name, Producer-Validierung, LLM-Check-Status -> Envelope-Status-Mapping (`PASS_WITH_CONCERNS` -> `WARN`) — `FK-71 §71.2`, `bc-cut-decisions.md §BC 8`
- **Integrity-Gate validiert Envelope-Pflichtfelder bei Closure** gegen Producer- und Provenienzfelder der kanonischen Records — `FK-71 §71.2`
- **`schema_version="3.0"` als Pflichtfeld im Envelope** — `FK-71 §71.2`
- **Typisierte Producer-Modelle** (`Producer`, `ProducerType`, `ProducerId`) — `bc-cut-decisions.md §BC 8`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/state_backend/postgres_schema.sql` — Tabelle `artifact_records` mit Feldern `artifact_class`, `artifact_kind`, `producer`, `producer_component`, `producer_trust`; untypisiert, kein Pydantic-Modell
- `src/agentkit/state_backend/postgres_store.py:_artifact_class_for` — Heuristik: `closure_report` -> `"closure"`, alles andere -> `"qa"`; nur 2 Klassen statt der 8 konzeptdefinierten
- `src/agentkit/state_backend/postgres_store.py:_upsert_artifact_record` — schreibt Artefakt-Records direkt ohne ArtifactManager, ohne Envelope-Validierung
- `src/agentkit/verify_system/artifacts.py` — QA-Artefakt-Persistenz (write/load) fuer Layer-Results und VerifyDecision; kein ArtifactEnvelope, kein ArtifactReference
- `src/agentkit/verify_system/policy_engine/projections.py:build_verify_decision_artifact` — serialisiert VerifyDecision in ein dict ohne `schema_version`, ohne `story_id`, ohne `run_id`, ohne `stage`, ohne `attempt`, ohne `started_at`, ohne `finished_at`
- `src/agentkit/verify_system/policy_engine/projections.py:serialize_layer_result` — serialisiert LayerResult in ein dict ohne Envelope-Felder
- `src/agentkit/governance/integrity_gate/__init__.py:IntegrityGate` — prueft Existenz von Artefakt-Records (structural, verify_decision), aber keine Envelope-Pflichtfeld-Validierung gegen FK-71 §71.2
- `src/agentkit/state_backend/paths.py` — definiert `PROTECTED_QA_ARTIFACTS`, `LAYER_ARTIFACT_FILES`, `VERIFY_DECISION_FILE` als Konstanten (gehoert konzeptionell zu governance-and-guards, nicht zu artifacts)
- `src/agentkit/governance/guards/artifact_guard.py` — Lock-basierter Schreibschutz fuer QA-Artefakte (BC governance-and-guards)
- `tests/unit/verify_system/test_artifacts.py` — Tests fuer QA-Artefakt-Serialisierung/Persistenz (verortet in verify_system, nicht in artifacts-BC)

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Paket `agentkit.artifacts` (Top-Modul) | `bc-cut-decisions.md §BC 8` | Kein Verzeichnis `src/agentkit/artifacts/` vorhanden; kein `__init__.py` |
| A2 | `ArtifactManager` (write/read/exists) | `bc-cut-decisions.md §BC 8` | Schreib-/Lese-Koordination gegen State-Backend-Driver vollstaendig fehlend; Logik verstreut in `postgres_store.py` und `verify_system/artifacts.py` |
| A3 | `ArtifactEnvelope` als typisiertes Pydantic-Modell | `FK-71 §71.2` | Kein Modell; Envelope-Felder werden als rohe dicts produziert ohne `schema_version`, `story_id`, `run_id`, `stage`, `attempt`, `started_at`, `finished_at` |
| A4 | `EnvelopeValidator` fuer Pflichtfeld-Pruefung | `bc-cut-decisions.md §BC 8` | Nicht vorhanden; `IntegrityGate` prueft nur Existenz, keine Feldinhalte gemaess FK-71 §71.2 |
| A5 | `ProducerRegistry` als Sub mit Producer-Validierung und LLM-Status-Mapping | `FK-71 §71.2`, `bc-cut-decisions.md §BC 8` | Kein Sub `agentkit.artifacts.producer_registry`; kein Producer-Mapping; kein `PASS_WITH_CONCERNS` -> `WARN`-Mapping |
| A6 | Typisierte Klassen `Producer`, `ProducerType`, `ProducerId` | `bc-cut-decisions.md §BC 8` | Nicht vorhanden; Producer wird als freier String `producer_component` im SQL gespeichert |
| A7 | Typisierte `ArtifactReference` | `FK-71 Glossar` | Nicht vorhanden; Artefakte werden ueber `artifact_kind`-Strings und Dateinamen referenziert, kein typisierter Verweis |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Artefaktklassen-Unterscheidung | `src/agentkit/state_backend/postgres_store.py:_artifact_class_for` | `FK-71 §71.1.1` | Nur 2 Klassen implementiert (`closure`, `qa`); fehlend: `worker`, `pipeline`, `telemetry`, `governance`, `entwurf`, `handover`, `adversarial_test_sandbox`; keine `ArtifactClass`-Enum |
| B2 | QA-Artefakt-Persistenz (write/load) | `src/agentkit/verify_system/artifacts.py` | `FK-71 §71.2` | Persistenz existiert fuer QA-Layer-Results und VerifyDecision; kein Envelope-Schema (kein `schema_version`, `story_id`, `run_id`, `stage`, `attempt`, Zeitstempel); falsche BC-Zuordnung (liegt in `verify_system`, nicht in `artifacts`) |
| B3 | Serialisierung von QA-Artefakt-Payloads | `src/agentkit/verify_system/policy_engine/projections.py:build_verify_decision_artifact` | `FK-71 §71.2` | Payload enthaelt `status`, `passed`, `layers`, aber keine Envelope-Pflichtfelder (`schema_version`, `story_id`, `run_id`, `stage`, `attempt`, `started_at`, `finished_at`); `EnvelopeStatus`-Werte (`PASS`, `PASS_WITH_WARNINGS`) passen nicht exakt zum Konzept-Status-Set (`PASS`, `FAIL`, `WARN`, `ERROR`) |
| B4 | Integrity-Gate prueft Artefakt-Praesenz | `src/agentkit/governance/integrity_gate/__init__.py:IntegrityGate` | `FK-71 §71.2` | Prueft Existenz von structural artifact und verify_decision Record; prueft aber keine Envelope-Pflichtfelder (`schema_version`, `producer.type`, `producer.name`, Stage-ID-Gueltigkeit) |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug, Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | BC-Ownership der QA-Artefakt-Persistenz liegt in `verify_system` | `src/agentkit/verify_system/artifacts.py` | `bc-cut-decisions.md §BC 8` | `verify_system/artifacts.py` ist als Owner der QA-Artefakt-Persistenz positioniert; gemaess BC-Schnitt gehoert Schreib-/Lese-Koordination in `agentkit.artifacts.ArtifactManager`. Das ist eine Konzept-Verletzung der BC-Grenze: verify-system konsumiert artifacts, produziert aber nicht die Artefakt-Infrastruktur selbst |
| C2 | `PROTECTED_QA_ARTIFACTS` und `LAYER_ARTIFACT_FILES` in `state_backend/paths.py` | `src/agentkit/state_backend/paths.py` | `FK-71 §71.1.2`, `bc-cut-decisions.md §BC 8 Konzept-Refactor-Liste Pkt. 3` | Die Liste der geschuetzten Artefakt-Dateinamen liegt in `state_backend`, obwohl das Konzept diese als Hook-Konfiguration in `governance-and-guards` (FK-31) fordert; `state_backend` ist ein T-Adapter und darf keine fachliche Schutz-Liste halten |
| C3 | `schema_version` in `state_backend/config.py` ist `"3.3.0"` (SemVer) statt `"3.0"` | `src/agentkit/state_backend/config.py:SCHEMA_VERSION` | `FK-71 §71.2` | `SCHEMA_VERSION = "3.3.0"` ist das interne Storage-Schema-Versionsformat fuer PostgreSQL-Schemas. Das Envelope-Pflichtfeld `schema_version` laut FK-71 §71.2 muss `"3.0"` sein. Beide Konstanten existieren nicht getrennt und klar benannt; Verwechslungspotenzial bei kuenftiger Envelope-Implementierung |

## 5. Ableitungen / Empfehlungen

1. **`src/agentkit/artifacts/` anlegen und `ArtifactEnvelope` + `ArtifactClass` als Pydantic-Modelle implementieren.** Dies ist der Blocke fuer alle anderen Punkte; ohne die Typbasis koennen `ArtifactManager`, `EnvelopeValidator` und `ProducerRegistry` nicht sinnvoll gebaut werden. Risiko: Weitere Integration zwischen BCs laeuft ohne valides Envelope-Modell und bleibt als rohes dict-Flickwerk.
2. **`ArtifactManager.write/read/exists` gegen State-Backend-Driver implementieren und `verify_system/artifacts.py` auf `ArtifactManager` umstellen.** Solange die BC-Grenze verletzt ist, bleibt verify-system de-facto Owner der Artefakt-Persistenz — genau das Ownership-Problem, das v3 loesen soll. Mittleres Risiko, weil verify-system-Tests existieren und migriert werden muessen.
3. **`ProducerRegistry` als Sub mit LLM-Status-Mapping (`PASS_WITH_CONCERNS` -> `WARN`) implementieren.** Ohne Registry-Validierung kann kein ungueltige Producer zur Laufzeit erkannt werden. Das `PASS_WITH_CONCERNS`-Mapping aus FK-71 §71.2 ist konzeptionell spezifiziert, aber nirgends im Code praesent.
4. **`EnvelopeValidator` implementieren und `IntegrityGate` auf Pflichtfeld-Pruefung erweitern.** Aktuell prueft das Integrity-Gate nur Praesenz, nicht Korrektheit. Ein korrumpiertes oder unvollstaendiges Envelope wird bei Closure nicht erkannt.
5. **`PROTECTED_QA_ARTIFACTS` / `LAYER_ARTIFACT_FILES` aus `state_backend/paths.py` nach `governance-and-guards` verschieben** (FK-31-Scope). Dies ist ein kleinerer Refactor, vermeidet aber das Konzept-Drift-Problem (C2) und macht `state_backend` zum reinen T-Adapter.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/technical-design/71_artefakt_envelope_und_stage_registry.md`
  - `concept/technical-design/_meta/domain-registry.yaml`
  - `concept/formal-spec/state-storage/README.md`
  - `concept/formal-spec/state-storage/entities.md`
  - `concept/formal-spec/state-storage/invariants.md`
  - `src/agentkit/state_backend/config.py`
  - `src/agentkit/state_backend/paths.py`
  - `src/agentkit/verify_system/artifacts.py`
  - `src/agentkit/verify_system/policy_engine/projections.py`
  - `src/agentkit/governance/integrity_gate/__init__.py`
  - `src/agentkit/guard_system/integrity_gate.py`
  - `src/agentkit/phase_state_store/models.py`
  - `tests/unit/verify_system/test_artifacts.py`
  - `tests/unit/governance/test_artifact_guard.py`
- **Punktuell gelesen:**
  - `concept/_meta/bc-cut-decisions.md §BC 8` (Zeilen 684–783): BC-Komponentenschnitt, Top-Surface, Klassen-Skizzen
  - `src/agentkit/state_backend/postgres_schema.sql` (artifact_records-Tabelle)
  - `src/agentkit/state_backend/postgres_store.py` (_artifact_class_for, _upsert_artifact_record)
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/artifacts/**/*.py`: kein Ergebnis — bestaetigt Nichtexistenz des Pakets
  - Pattern `ArtifactEnvelope|ProducerRegistry|artifact_envelope|producer_registry`: kein Treffer in `src/`
  - Pattern `ArtifactClass|artifact_class`: nur in SQL-Schema und postgres_store.py als String-Feld
  - Pattern `schema_version|envelope`: trifft `config.py` (Storage-Schema-Version), `projections.py` (Kommentar-Kontext)
  - Glob `src/agentkit/**/artifact*.py`: liefert `artifact_guard.py` (governance) und `verify_system/artifacts.py`
