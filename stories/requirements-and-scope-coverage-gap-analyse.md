# requirements-and-scope-coverage — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `requirements-and-scope-coverage` |
| Display-Name | `Requirements und Scope-Coverage (ARE)` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-06, FK-40, formal.deterministic-checks.entities, formal.deterministic-checks.invariants, formal.deterministic-checks.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/requirements_coverage/, src/agentkit/integrations/are/` |

## 1. Executive Summary

Der BC `requirements-and-scope-coverage` ist in der Codebase nahezu nicht implementiert. Lediglich das `StoryAreLink`-Datenmodell inklusive Repository-Protokoll und einer SQLite-gestuetzten Implementierung ist vorhanden und durch Unit-Tests belegt. Die konzeptuell zentralen Komponenten — `AreClient` (REST-Adapter), `AreIntegration` (vier Andock-Punkte), `ScopeMapping` (Konfigurationstabellen) sowie die Top-Surface `RequirementsCoverage` mit ihrer no-op-Aktivierungslogik — fehlen vollstaendig. Die vier definierten Andock-Punkte (Link, Context, Evidence, Gate) sind nicht umgesetzt; `integrations/are/` ist leer.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 8 |
| B — Teilweise umgesetzt | 2 |
| C — Drift / Fehler | 1 |

## 2. Konzept-Soll (Kurzfassung)

- **Top-Surface `RequirementsCoverage` als no-op bei `features.are: false`** — `FK-40 §40.2`; alle vier Andock-Punkte liefern SKIPPED, Aufrufer-BCs benoetigen keinen Fallback.
- **`AreClient` REST-Adapter** — `FK-40 §40.4`; REST-Calls an externe ARE-API: `list_requirements`, `get_recurring`, `load_context`, `submit_evidence`, `check_gate`. Kein MCP-Wrapper — MCP ist Boundary-Control fuer Harness-Agents.
- **Andock-Punkt 1 — Anforderungen verlinken** — `FK-40 §40.5.1`; `are_get_recurring` + `are_list_requirements` bei Story-Erstellung; INSERT in `StoryAreLink` mit `kind=recurring` bzw. `addresses`.
- **Andock-Punkt 2 — Anforderungskontext laden** — `FK-40 §40.5.2`; deterministisches Setup-Skript schreibt `are_bundle.json` via `ArtifactManager` (ArtifactClass.QA, Producer `qa-are-context-loader`); Ergebnis als Control-Plane-Signal in Phase-State.
- **Andock-Punkt 3 — Evidence einreichen** — `FK-40 §40.5.3`; Worker/QA-Agent ruft `submit_evidence`; validiert, dass Evidence nur fuer verknuepfte ARE-Items eingereicht wird.
- **Andock-Punkt 4 — ARE-Gate pruefen** — `FK-40 §40.5.4`; deterministisches Gate in QA-Subflow Layer 1; liefert `CoverageVerdict` PASS/FAIL; fail-closed bei ARE-Unerreichbarkeit; Ergebnis-Artefakt `are_gate.json`.
- **`ScopeMapping` Konfigurationstabellen** — `FK-40 §40.3`; Repo→Scope und Modul→Scope; Zwei-Tier-Scope-Ableitung bei Story-Erstellung; Lese-Owner (Schreib-Owner: `installation-and-bootstrap`).
- **`StoryAreLink` Edge-Tabelle** — `FK-40 §40.5b`; Persistenz der Story↔ARE-Verknuepfung; Schema, Lifecycle, Schreibwege, Stale-Behandlung.
- **Telemetrie-Events** — `FK-40 §40.8`; `are_requirements_linked`, `are_evidence_submitted`, `are_gate_result` in `execution_events`; EventTypeId-Werte in FK-68 registriert.
- **Frontend Lese-API** — `FK-40 §40.10`; GET `/coverage/stories/{story_id}/acceptance` und `.../are-evidence`; read-only; Eintrag in FK-91.
- **Fehlerbehandlung fail-closed** — `FK-40 §40.9`; ARE-Gate = FAIL bei Unerreichbarkeit in Verify; Warnung (nicht FAIL) bei Unerreichbarkeit in Story-Erstellung.

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/requirements_coverage/models.py:StoryAreLinkKind` — StrEnum mit den vier gueltigen Kind-Werten (addresses, partial, derives_from, recurring).
- `src/agentkit/requirements_coverage/models.py:StoryAreLink` — Pydantic-v2-Modell fuer den Edge (story_id, are_item_id, kind); frozen=True, extra=forbid.
- `src/agentkit/requirements_coverage/repository.py:StoryAreLinkRepository` — Protocol-Definition fuer Storage-Port (add, update_kind, remove, list_by_story).
- `src/agentkit/requirements_coverage/errors.py:StoryAreLinkError` — Basisklasse fuer BC-Fehler.
- `src/agentkit/requirements_coverage/errors.py:StoryAreLinkConflictError` — Duplikat-Konflikt.
- `src/agentkit/requirements_coverage/errors.py:StoryAreLinkNotFoundError` — nicht gefunden.
- `src/agentkit/requirements_coverage/__init__.py` — oeffentliche BC-Surface exportiert nur StoryAreLink-bezogene Symbole; kein `RequirementsCoverage`-Export.
- `src/agentkit/state_backend/store/story_are_link_repository.py:StateBackendStoryAreLinkRepository` — SQLite-gestuetzte Implementierung des StoryAreLinkRepository-Protokolls ueber das state-backend-Facade.
- `src/agentkit/integrations/are/__init__.py` — leere Datei; kein AreClient implementiert.
- `tests/unit/requirements_coverage/test_story_are_link_repository.py` — fuenf Unit-Tests fuer StoryAreLinkRepository (INSERT, UPDATE, DELETE, Duplikat-Abweisung, Determinismus).

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | `AreClient` REST-Adapter | `FK-40 §40.4` | `src/agentkit/integrations/are/__init__.py` ist leer; kein REST-Client; fuenf Endpunkte (list_requirements, get_recurring, load_context, submit_evidence, check_gate) fehlen vollstaendig. |
| A2 | Andock-Punkt 1 — Anforderungen verlinken | `FK-40 §40.5.1` | Kein `RequirementLinker`; kein Aufruf von `are_get_recurring`/`are_list_requirements`; keine automatische INSERT-Logik in `StoryAreLink` bei Story-Erstellung. |
| A3 | Andock-Punkt 2 — Anforderungskontext laden | `FK-40 §40.5.2` | Kein `ContextLoader`; `are_bundle.json` wird nicht erzeugt; kein Integration mit `ArtifactManager` (ArtifactClass.QA, Producer `qa-are-context-loader`); kein Control-Plane-Signal in Phase-State. |
| A4 | Andock-Punkt 3 — Evidence einreichen | `FK-40 §40.5.3` | Kein `EvidenceSubmitter`; kein `submit_evidence`-Aufruf; keine Validierung, ob Evidence nur fuer verknuepfte ARE-Items gilt; kein `kind`-UPDATE (addresses -> partial). |
| A5 | Andock-Punkt 4 — ARE-Gate pruefen | `FK-40 §40.5.4, formal.deterministic-checks.invariants §are-gate-required-only-when-enabled` | Kein `AreGateChecker`; kein `CoverageVerdict`; kein Ergebnis-Artefakt `are_gate.json`; fail-closed-Verhalten bei ARE-Unerreichbarkeit nicht implementiert. |
| A6 | Top-Surface `RequirementsCoverage` | `FK-40 §40.2` | `__init__.py` exportiert nur StoryAreLink-Symbole; keine `RequirementsCoverage`-Klasse; keine no-op-Logik bei `features.are: false`. |
| A7 | `ScopeMapping` Konfigurationstabellen | `FK-40 §40.3` | Kein Sub fuer Repo→Scope und Modul→Scope; keine Scope-Ableitung bei Story-Erstellung (Zwei-Tier-Prioritaet); kein Lese-Zugriff auf PipelineConfig. |
| A8 | Telemetrie-Events | `FK-40 §40.8` | Keine Emission von `are_requirements_linked`, `are_evidence_submitted`, `are_gate_result`; keine Integration mit BC `telemetry-and-events`. |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | `StoryAreLink` Edge-Tabelle | `src/agentkit/requirements_coverage/models.py:StoryAreLink`, `src/agentkit/state_backend/store/story_are_link_repository.py:StateBackendStoryAreLinkRepository` | `FK-40 §40.5b` | Datenmodell und Repository vorhanden. Fehlend: Stale-`are_item_id`-Behandlung (§40.5b.5) mit explizitem FAIL-Hinweis im Gate; Story-Reset-Verhalten (§40.5b.4, Eintraege ueberleben Reset); Story-Split-Verschiebung (§40.5b.4, deterministisch via Story-Split-Service). |
| B2 | Frontend Lese-API | `src/agentkit/requirements_coverage/__init__.py` | `FK-40 §40.10` | Kein REST-Endpunkt `/coverage/stories/{story_id}/acceptance` und `.../are-evidence` vorhanden; BC-Surface exportiert noch kein zugehoerige Handler-Klasse. Datenpfad (StoryAreLink + ARE-Live-Status) existiert im Modell, aber kein HTTP-Binding. |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | BC-Surface exportiert keine `RequirementsCoverage`-Klasse | `src/agentkit/requirements_coverage/__init__.py` | `FK-40 §40.2, concept/_meta/bc-cut-decisions.md §BC-15` | Laut bc-cut-decisions ist `RequirementsCoverage` die Top-Surface des BC (prefix `agentkit.backend.requirements_coverage`). Die aktuelle `__init__.py` exportiert ausschliesslich `StoryAreLink`-bezogene Symbole. Aufrufer-BCs koennen die vorgesehene Top-Surface nicht importieren; kein Aktivierungs-Check (`features.are`) abrufbar. |

## 5. Ableitungen / Empfehlungen

1. **`AreClient` REST-Adapter implementieren** (A1): Blocker fuer alle vier Andock-Punkte. Ohne REST-Client koennen AreIntegration-Subs nicht gebaut werden. Analogie zu `GitHub-REST-Adapter (FK-12)` nutzen; kein MCP-Wrapper fuer AgentKit-Code.
2. **Top-Surface `RequirementsCoverage` mit no-op-Logik anlegen** (A6, C1): Aufrufer-BCs (`pipeline-framework`, `verify-system`, `implementation-phase`) erwarten eine stabile Top-Surface, die bei `features.are: false` selbst SKIPPED zurueckgibt. Ohne diese Klasse koennen Aufrufer-BCs nicht korrekt integrieren.
3. **Andock-Punkt 2 — Kontext laden** (A3): Hat direkte Auswirkung auf Setup-Phase-Korrektheit; fehlendes `are_bundle.json` ist ein Startblocker fuer den Worker (FK-40 §40.5.2). Integration mit `ArtifactManager` und Producer-Registry-Eintrag in BC 8 (`qa-are-context-loader`) erforderlich.
4. **Andock-Punkt 4 — ARE-Gate** (A5): Blocker fuer die formale `formal.deterministic-checks`-Invariante `are-gate-required-only-when-enabled`. Ohne Gate-Implementierung laeuft der QA-Subflow Layer 1 inkonsistent zur formal-spec; Integrity-Gate (FK-35) kann `are_gate_result: PASS` nicht verifizieren.
5. **`ScopeMapping` Sub anlegen** (A7): Wird benoetigt sobald Andock-Punkt 1 und Scope-Ableitung bei Story-Erstellung implementiert werden. Schreib-Owner ist `installation-and-bootstrap`; nur Lese-Zugriff aus diesem BC.
6. **Stale-`are_item_id`-Behandlung** (B1): Fehlt in `StateBackendStoryAreLinkRepository.update_kind`/`remove`; Stale-Eintraege werden nicht erkannt und fuehren zu undefiniertem Gate-Verhalten (FK-40 §40.5b.5).
7. **Telemetrie-Events** (A8): EventTypeId-Werte muessen in FK-68 erganzt werden; Emission kann erst nach AreIntegration-Implementierung erfolgen; frueh abstimmen, um spaetere Nacharbeiten zu vermeiden.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/06-are-integration.md` (DK-06)
  - `concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md` (FK-40)
  - `concept/formal-spec/deterministic-checks/entities.md`
  - `concept/formal-spec/deterministic-checks/invariants.md`
  - `concept/formal-spec/deterministic-checks/scenarios.md`
  - `src/agentkit/requirements_coverage/__init__.py`
  - `src/agentkit/requirements_coverage/models.py`
  - `src/agentkit/requirements_coverage/repository.py`
  - `src/agentkit/requirements_coverage/errors.py`
  - `src/agentkit/integrations/are/__init__.py`
  - `src/agentkit/state_backend/store/story_are_link_repository.py`
  - `tests/unit/requirements_coverage/test_story_are_link_repository.py`
- **Punktuell via Grep:**
  - Pattern `requirements-and-scope-coverage|ARE` in `concept/_meta/bc-cut-decisions.md`: BC-15-Eintrag mit Sub-Struktur, Entscheidungspunkten 65–71.
  - Pattern `requirements-and-scope-coverage` in `concept/technical-design/_meta/domain-registry.yaml`: Display-Name und contract_docs bestaetigt.
- **Code-Scan (Glob/Grep):**
  - `src/agentkit/requirements_coverage/**/*`: vollstaendige Dateiliste des BC-Pakets.
  - `src/agentkit/integrations/**/*`: AreClient-Verzeichnis identifiziert als leeres `__init__.py`.
  - `tests/**/*are*`: nur `test_story_are_link_repository.py` gefunden; keine ARE-Client- oder Andock-Punkt-Tests.
  - `tests/contract/**/*`: keine requirements-coverage-spezifischen Contract-Tests gefunden.
  - Pattern `AreClient|RequirementsCoverage|AreIntegration|ScopeMapping` in `src/`: kein Treffer — bestaetigt vollstaendiges Fehlen dieser Klassen.
