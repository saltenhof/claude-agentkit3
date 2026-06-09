# AG3-070: Config-Modell-Vollausbau + Schema-Katalog + schema_version

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `project-config` / Konfigurationsmodell & Versionierung (BC). Das `project.yaml`-Modell des Zielprojekts (`.agentkit/config/project.yaml`): Pflicht-`config_version`, fail-closed Loader, Feature-Matrix, Multi-LLM-Rollen, fehlende Config-Stanzas und die Schema-Katalog-Strategie (Pydantic-Owner + `schema_version`).
**Quell-Konzepte (autoritativ):**
- `FK-03 §3.1` — Config-Ebenen: `FeaturesConfig` (multi_repo/vectordb/multi_llm/telemetry/db/e2e_assertions) + Stanzas `orchestrator_guard`/`policy`/`vectordb`/`telemetry`/`governance`; das `sonarqube`-Feld `accept_frequency_fc_threshold: float (0..1, Default 0.25)` (`concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md:184`, `:205`, `:458`).
- `FK-03 §3.2.1` — `config_version`-Pflichtfeld + fail-closed Loader (`config_version != "3.0" → ValueError`); `validate_config` (Multi-LLM-Validierung: `multi_llm requires llm_roles`, Pflichtrollen-Set; `e2e_assertions requires db`).
- `FK-03 §3.3.4` — die **zwei unabhaengigen Versionierungsbereiche**: Pipeline-Config (`project.yaml` → `config_version`, SemVer, Installer-Migration) **und** QA-Artefakte (JSON-Envelopes → `schema_version`, nur Major). Diese Story besitzt **ausschliesslich** den Config-Bereich (`config_version`); der Artefakt-`schema_version`-Bereich hat bereits eigene Owner im Code (siehe §1) und liegt ausserhalb des `project-config`-Cuts.
- `FK-03 §3.3.1/§3.3.3` — Schema-Katalog + `schema_version`-Feld in Artefakten (FK markiert JSON-Schema-Dateien; Code-Realitaet ist Pydantic+Contract-Tests — der Artefakt-Bereich ist nicht der AG3-070-Cut, siehe §1/§2.2).
- `FK-90 §90.1/§90.2` — Schema-Katalog (`{stage_id}.schema.json`); im Code bewusst durch Pydantic+Contract-Tests ersetzt → FK-90-Prosa-Nachzug ist **doc-only AG3-103**, nicht hier.
- `FK-01 §1.3 P5` — Multi-LLM als Pflicht-Config (`multi_llm: true` Default, `llm_roles`-Map).

---

## 1. Kontext / Ist-Zustand (belegt)

Das implementierte Config-Modell weicht strukturell stark von FK-03 ab (groesste A1-Divergenz):

- `Features` (`config/models.py:30-42`) hat **nur** `are: bool`. Es fehlen `multi_repo/vectordb/multi_llm/telemetry/db/e2e_assertions` und die Regel `e2e_assertions requires db` (Gap FK-03 §3.1 ABWEICHEND).
- **Kein** `config_version`-Feld im Config-Modell/Loader: weder `ProjectConfig` noch `PipelineConfig` (`config/models.py:335-381`, `:414-443`) tragen es, und `load_project_config` (`config/loader.py:52-107`) prueft keine Version. Andere operative/telemetrische `config_version`-Records existieren sehr wohl (z. B. Closure-Metrics `closure/post_merge_finalization/records.py:30`, `:55-56`; Installer-Tracking `installer/registration.py`) — das sind aber NICHT das `project.yaml`-Pflichtfeld nach FK-03 §3.2.1 (Gap FK-03 §3.2.1 FEHLT).
- **Kein** `multi_llm`/`llm_roles` als **typisiertes Config-Feld** in `ProjectConfig`/`PipelineConfig` (Grep im `config/`-Paket → kein Pydantic-Feld). `llm_roles` taucht ausserhalb des Config-Modells als operativer Record auf (Closure-Metrics `closure/post_merge_finalization/records.py:31`, `:57-58`; String-Referenzen in `installer/registration.py`). Pflicht-Reviewer-Abdeckung laeuft heute ueber `ReviewConfig.required_roles` (`config/models.py:310-332`) — fachlich verwandt, aber abweichend vom FK-01/FK-03-Schnitt (Gap FK-01 §1.3 P5 / FK-03 §3.2.1 FEHLT).
- **Keine** Stanzas `orchestrator_guard`/`policy.major_threshold`/`policy.stage_overrides`/`vectordb`/`telemetry.web_call_limit`/`governance.risk_threshold` als Pydantic-Felder; `class PolicyConfig`/`class StageConfig` aus §3.1 existieren nicht (Gap FK-03 §3.1 FEHLT).
- **Existierender partieller `sonarqube`-Owner:** `class SonarQubeConfig` und `PipelineConfig.sonarqube` sind bereits da (`config/models.py:122`, `:173-180`, `:380`) und werden ueber `config/__init__.py:22-25` exportiert — aber **ohne** das FK-03-Feld `accept_frequency_fc_threshold` (`03_konfigurationsmodell_…:184`, `:205`, `:458`). Dieser bestehende Owner ist zu **erweitern** (eine Wahrheit), keine zweite parallele `sonarqube`-Stanza (Gap FK-03 §3.1 / §3 ABWEICHEND). `_CROSS_STORY_PREREQS.md:6` (CP1) weist das Feld AG3-070 zu; AG3-078 ist Konsument.
- **Schema-Versionierung State-Backend ist konform** (`state_backend/config.py:140` `SCHEMA_VERSION = "3.20.0"`, `versioned_postgres_schema_name()`/`versioned_sqlite_db_file()` vorhanden) — das ist die DB-Schema-Versionierung, **nicht** das FK-03-Config-`config_version`. Beide nicht vermischen.
- **Artefakt-`schema_version` ist bereits eigener Owner im Code — NICHT der AG3-070-Cut:** der QA-Artefakt-Envelope traegt `schema_version` schon heute typisiert und fail-closed (`ArtifactEnvelope.schema_version: Literal["3.0"]` `artifacts/envelope.py:85`, Konstante `ENVELOPE_SCHEMA_VERSION` `:44`, exportiert `artifacts/__init__.py:23`); der Exploration-Change-Frame ebenso (`exploration/change_frame.py:39`, Validator `:318-321`). FK-03 §3.3.4 nennt explizit **zwei unabhaengige** Versionierungsbereiche; AG3-070 (`project-config`-BC) besitzt nur den **Config-Bereich** (`config_version`). Der Artefakt-/Envelope-`schema_version`-Bereich gehoert den jeweiligen Artefakt-/Exploration-BCs und wird hier weder neu gebaut noch dupliziert (SSOT).
- **Kein** `*.schema.json`-Katalog im Repo (0 Treffer ausser `.git`/`var`); Validierung laeuft ueber Pydantic-Modelle. Das ist eine **bewusste BC-Cut-Supersession** (Master-Tabelle Offene-Schnitt-Fragen Nr. 3): FK-90-JSON-Schema-Prosa wird als doc-only (AG3-103) nachgezogen, hier wird ausschliesslich der **Config-`config_version`-Owner** (`project.yaml`-Modell) gebaut.
- Anknuepfung: Die `vectordb`-Stanza wird von **AG3-068** konsumiert; das `telemetry.web_call_limit`-Feld von **AG3-086** (WebCallBudgetGuard); `governance.risk_threshold/window_size/cooldown_s` von **AG3-085**; `sonarqube.accept_frequency_fc_threshold` von **AG3-078** (Failure-Corpus-Accept-Frequency). Diese Story ist der **Feld-Owner**, die Konsumenten haengen sich an.

## 2. Scope

### 2.1 In Scope
1. **`config_version`-Pflichtfeld** am `project.yaml`-Modell — Owner ist `PipelineConfig` (`config/models.py:335`, FK-03 §3.2.1) — + fail-closed Loader (kein stiller Default). Klare Fehler-Grenze, an die reale Code-Realitaet (`config/loader.py:101-107`) angepasst:
   - der Pydantic-**Validator** auf `PipelineConfig` wirft bei unbekannter/fehlender Version `ValueError`;
   - `load_project_config` faengt diesen Validierungsfehler und gibt ihn fail-closed als `ConfigError` (mit Ursache als `__cause__`/`detail`) weiter — das ist die etablierte Loader-API (`config/exceptions`/`agentkit.exceptions.ConfigError`), nicht ein durchgereichtes nacktes `ValueError`. Keine Loader-API-Aenderung in dieser Story.
   Single Source of Truth: das Config-`config_version` ist getrennt vom DB-`SCHEMA_VERSION` (kein Vermischen).
2. **Feature-Matrix `FeaturesConfig`** mit den sechs Flags `multi_repo/vectordb/multi_llm/telemetry/db/e2e_assertions` (`are` bleibt) + Cross-Field-Regel `e2e_assertions requires db` (fail-closed Validierung).
3. **`multi_llm` + `llm_roles`** als typisierte Felder + Validierung (`multi_llm: true` requires `llm_roles`; Pflichtrollen-Set qa_review/semantic_review/adversarial_sparring/doc_fidelity/governance_adjudication). Konsolidierung mit dem bestehenden `ReviewConfig.required_roles`: **eine** Wahrheit — entweder `ReviewConfig` auf `llm_roles` umstellen oder `llm_roles` als Owner mit `ReviewConfig`-Ableitung; keine zwei parallelen Rollenmodelle (FIX-THE-MODEL).
4. **Config-Stanzas** als typisierte Pydantic-Modelle mit FK-03-Defaults: `orchestrator_guard` (blocked_paths/extensions/files), `policy` (`major_threshold`, `stage_overrides`, `required_stages`), `vectordb` (`similarity_threshold=0.7`, `max_llm_candidates=5`, Connection), `telemetry` (`web_call_limit=200`, `web_call_warning=180`), `governance` (`risk_threshold`, `window_size`, `cooldown_s`).
4a. **Bestehenden `SonarQubeConfig`-Owner erweitern** (kein zweiter `sonarqube`-Pfad): das fehlende FK-03-Feld `accept_frequency_fc_threshold: float = 0.25` auf `class SonarQubeConfig` (`config/models.py:122`) ergaenzen, mit `0..1`-Range-Validierung (`< 0` oder `> 1` → `ValueError`). Owner-Pflicht aus `_CROSS_STORY_PREREQS.md:6` (CP1); Konsument ist AG3-078. FK-03/FK-41 §41.10-Prosa ist doc-only **AG3-103**, nicht hier.
5. **Config-`config_version`-Versionierung mit konkret benannter, getesteter Owner-Liste** (eng auf den `project-config`-Cut beschnitten — NICHT die Artefakt-`schema_version`-Familien). FK-03 §3.3.4 trennt zwei unabhaengige Versionierungsbereiche; AG3-070 baut **ausschliesslich den Config-Bereich**. Die hier versionierten Pydantic-Owner sind genau und vollstaendig:
   - **`PipelineConfig`** (`config/models.py:335`) — traegt das `config_version`-Pflichtfeld am `project.yaml`-abgeleiteten Modell (FK-03 §3.2.1 verortet `config_version` auf `PipelineConfig`); fail-closed-Validator `config_version != "3.0" → ValueError`.
   - **`ProjectConfig`** (`config/models.py:414`) — Root-Modell von `project.yaml`; erreicht `PipelineConfig` ueber `ProjectConfig.pipeline` (`:439`). Es traegt **kein** eigenes zweites Versionsfeld (ein Versions-Owner, keine Doppelung).
   Die **Artefakt-/Envelope-`schema_version`-Familien** (Envelope, Change-Frame, etc.) sind **explizit NICHT** in dieser Liste — sie sind bereits eigene Code-Owner (`artifacts/envelope.py:85`, `exploration/change_frame.py:318`) und liegen ausserhalb des Cuts (§2.2). Ein **Contract-Test fixiert genau diese Config-Owner-Liste** (`PipelineConfig` als einziger `config_version`-Owner): ein neuer Config-`config_version`-Owner ohne Listeneintrag macht den Test rot; ein versuchter zweiter Config-Versions-Owner ebenfalls — so kann der Config-Versionierungsraum nicht still divergieren. **FK-90-Prosa-Nachzug ist AG3-103 (doc-only), nicht hier.**
6. **Migrations-Andockpunkt**: das `config_version`-Feld ist so geschnitten, dass die Installer-/Upgrade-Migration (AG3-089) bei Major-Sprung greifen kann (`.bak`-Strategie). Hier nur das Feld + Loader-Vorbedingung, nicht die Migrationslogik.
7. **Negativpfade**: unbekannte `config_version` blockiert (am Config-Owner `PipelineConfig`); `multi_llm: true` ohne `llm_roles` blockiert; fehlende Pflichtrolle blockiert; `e2e_assertions: true` ohne `db: true` blockiert; `sonarqube.accept_frequency_fc_threshold` ausserhalb `0..1` blockiert (Range-Negativtest) + Default-`0.25`-Test. (Artefakt-`schema_version`-Negativpfade gehoeren zum Artefakt-BC, nicht hier — siehe §2.2.)

### 2.2 Out of Scope (mit Owner)
- **Artefakt-/Envelope-`schema_version`-Versionierung** (zweiter Versionierungsbereich aus FK-03 §3.3.4) — **bereits eigener Code-Owner**, nicht der `project-config`-Cut: QA-Artefakt-Envelope `ArtifactEnvelope.schema_version` (`artifacts/envelope.py:85`, Konstante `:44`); Exploration-Change-Frame `schema_version` (`exploration/change_frame.py:318`). AG3-070 baut, dupliziert oder versioniert diese **nicht**.
- **FK-90-JSON-Schema-Datei-Prosa angleichen** (Konzepttext auf Pydantic+Contract-Test-Realitaet umschreiben) — **AG3-103** (doc-only). Hier kein Konzept-Diff.
- **Konsum** der Stanzas: `vectordb` → **AG3-068**; `telemetry.web_call_limit` → **AG3-086**; `governance.*` → **AG3-085**. Diese Story liefert nur die Feld-Owner.
- **Installer-/Upgrade-Migration** (`migrate_config`/`migrate_3_to_4`, `.bak`, CustomizationFootprint) — **AG3-088/AG3-089** (depends_on AG3-070).
- **Schema-Katalog als echte JSON-Schema-Generierung** — bewusst NICHT gewaehlt (Offene-Schnitt-Frage Nr. 3); falls der PO das umentscheidet, ist es ein eigener Schnitt.

## 3. Akzeptanzkriterien
1. `config_version` ist Pflichtfeld am `project.yaml`-Modell. Fehler-Grenze sauber getrennt (an realer Loader-API ausgerichtet): (a) der Pydantic-Validator wirft bei unbekannter/fehlender Version `ValueError` (Modell-Negativtest); (b) `load_project_config` liefert fail-closed `ConfigError` mit der `ValueError`-Ursache (Loader-Negativtest, kein nacktes `ValueError` aus dem Loader). Getrennt vom DB-`SCHEMA_VERSION` (Test/Assertion belegt die Trennung).
2. `FeaturesConfig` traegt alle sechs Flags + `are`; `e2e_assertions requires db` wird fail-closed validiert (Negativtest).
3. `multi_llm: true` erzwingt `llm_roles` mit dem vollstaendigen Pflichtrollen-Set; fehlende Rolle blockiert (Negativtest). Es existiert genau **ein** Rollenmodell (kein paralleles `required_roles` + `llm_roles`).
4. Die fuenf Stanzas (`orchestrator_guard`/`policy`/`vectordb`/`telemetry`/`governance`) sind typisierte Pydantic-Modelle mit den FK-03-Defaults (Tests pro Default-Wert).
4a. Der bestehende `SonarQubeConfig`-Owner (`config/models.py:122`) traegt `accept_frequency_fc_threshold: float = 0.25` mit `0..1`-Validierung; Default-Wert-Test **und** Range-Negativtest (`< 0`/`> 1` blockiert). Kein zweiter `sonarqube`-Pfad.
5. **Config-`config_version`-Versionierung mit konkret benannter Owner-Liste** (eng auf den Config-Cut beschnitten, NICHT die Artefakt-`schema_version`-Familien — FK-03 §3.3.4 trennt beide Bereiche). Der einzige `config_version`-Owner ist `PipelineConfig` (`config/models.py:335`, am `project.yaml`-Modell, FK-03 §3.2.1); `ProjectConfig` (`config/models.py:414`) erreicht ihn ueber `ProjectConfig.pipeline` (`:439`) und traegt kein zweites Versionsfeld. Eine unbekannte `config_version` blockiert fail-closed beim Laden (Negativtest). Ein Contract-Test fixiert genau diese Config-Owner-Liste (neuer Config-`config_version`-Owner ohne Listeneintrag → Test rot; ein zweiter Config-Versions-Owner → Test rot), sodass der Config-Versionierungsraum nicht still divergiert. Die Artefakt-/Envelope-`schema_version`-Familien sind explizit nicht Teil dieser Liste (eigene Owner, §2.2).
6. Der Config-`config_version`-Owner (`PipelineConfig`) ist benannt und dokumentiert; kein zweiter Config-Validierungspfad.
7. Das `config_version`-Feld ist als Migrations-Andockpunkt geschnitten (Test/Assertion, dass der Loader die Version exponiert).
8. Alle neuen Felder/Keys/Enum-Werte englisch (ARCH-55).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage ≥ 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt.

## 5. Guardrail-Referenzen
- **FAIL CLOSED:** unbekannte `config_version`/`schema_version`, fehlende Pflichtrolle, `accept_frequency_fc_threshold` ausserhalb `0..1` und verletzte Cross-Field-Regeln blockieren — kein stiller Default. Loader-Grenze sauber: Validator `ValueError` → `load_project_config` `ConfigError` (kein durchgereichtes nacktes `ValueError`).
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** ein Rollenmodell (kein paralleles `required_roles`/`llm_roles`); Config-`config_version` getrennt von DB-`SCHEMA_VERSION`; Pydantic-Owner statt zweitem Schema-Pfad.
- **TYPISIERT STATT STRINGS:** alle Stanzas + Feature-Flags + Rollen als typisierte Pydantic-Modelle/Enums.
- **ARCH-55:** alle neuen Felder/Keys englisch; FK-90-Prosa-Nachzug ist die doc-only-Story, kein deutscher Code.
- **ZERO DEBT:** Schema-Katalog-Strategie ist real geschnitten (Pydantic-Owner + `schema_version` + Contract-Tests), kein „spaeter JSON-Schema".

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Kritisch:** Config-`config_version` (FK-03) NICHT mit dem bestehenden DB-`SCHEMA_VERSION` (`state_backend/config.py:140`) verwechseln/vermischen — getrennte Owner.
- Das bestehende `ReviewConfig.required_roles` (`config/models.py:310-332`) ist die heutige Rollenwahrheit — auf `llm_roles` konsolidieren, nicht parallel fuehren. Wenn die Konsolidierung breit in den Verify-Pfad ausstrahlt: melden, nicht still ausweiten.
- Diese Story ist **Feld-Owner** der Stanzas; AG3-068/078/085/086 sind Konsumenten — keine Konsum-Logik hier.
- **`sonarqube.accept_frequency_fc_threshold`** (Owner-Pflicht CP1, `_CROSS_STORY_PREREQS.md:6`): den **bestehenden** `SonarQubeConfig`-Owner (`config/models.py:122`, exportiert via `config/__init__.py:22-25`) erweitern — NICHT eine zweite `sonarqube`-Stanza anlegen. Konsument ist AG3-078.
- **Loader-Fehler-Grenze:** der reale Loader kapselt Validierungsfehler als `ConfigError` (`config/loader.py:101-107`). Validator wirft `ValueError`; `load_project_config` reicht ihn fail-closed als `ConfigError` weiter. Keine Loader-API-Aenderung in dieser Story.
- FK-90 ist bewusst Pydantic-statt-JSON-Schema (Offene-Schnitt-Frage Nr. 3); die FK-Prosa zieht AG3-103 (doc-only) nach — hier keinen Konzepttext aendern.
- **Versionierungs-Cut (FK-03 §3.3.4):** nur den **Config**-Bereich (`config_version` auf `PipelineConfig`) bauen. Den **Artefakt**-`schema_version`-Bereich NICHT anfassen — der hat bereits eigene Owner (`ArtifactEnvelope` `artifacts/envelope.py:85`; `ChangeFrame` `exploration/change_frame.py:318`). Kein zweiter Versions-Validierungspfad, keine Duplikation.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen der Loader-/Validierungs-Negativpfade.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
