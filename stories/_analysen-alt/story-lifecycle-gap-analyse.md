# story-lifecycle — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `story-lifecycle` |
| Display-Name | `Story-Lifecycle` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-10, FK-21, FK-24, FK-53, FK-54, FK-56, FK-58, FK-59, formal.story-creation.*, formal.story-workflow.*, formal.story-reset.*, formal.story-split.*, formal.story-exit.*, formal.operating-modes.*, formal.story-contracts.*` |
| Codebase-Hauptpfade | `src/agentkit/story_context_manager/, src/agentkit/story/` |

## 1. Executive Summary

Der BC story-lifecycle zeigt eine ausgepraegt ungleiche Abdeckung: Die persistenten Vertragsachsen (`story_type`, `implementation_contract`, `execution_route`/`StoryContext`) und das Story-Status-Zustandsmodell sind solide typisiert und teilweise durch Contract-Tests abgesichert. Die grossen administrativen Unterpfade — Story-Erstellungs-Pipeline (FK-21), StoryResetService (FK-53), StorySplitService (FK-54) und Story-Exit (FK-58) — sind konzeptionell vollstaendig formal spezifiziert, aber im Produktionscode nahezu vollstaendig nicht implementiert: weder CLI-Befehle (`agentkit export-story-md`, `agentkit reset-story`, `agentkit split-story`, `agentkit exit-story`) noch deren Serviceklassen existieren. Der Betriebsmodus-Mechanismus (FK-56) ist partiell in der Control-Plane vorhanden, aber die Modell-Diskrepanz zwischen der internen `StorySize`-Kodierung (`small/medium/large/epic`) und der konzeptionellen (FK-21/DK-10: `XS/S/M/L/XL`) ist ein konkreter Drift-Befund.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 9 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **Story-Erstellungs-Pipeline als deterministischer Ablauf mit VektorDB-Abgleich, Zieltreue-Pruefung, Skill `create-userstory`, `story.md`-Export und menschlicher Freigabe** — `FK-21 §21.1–21.13`
- **Story-Feldschema: sechs Modus-Ermittlungsfelder (`story_type`, `concept_paths`/`concept_quality`, `change_impact`, `new_structures`, Reifegrad, externe Integrationen) plus Projektfelder (`size`, `module`, `epic`)** — `DK-10 §10.3`
- **Fuenf Story-Status (`Backlog`, `Approved`, `In Progress`, `Done`, `Cancelled`); interne Zwischenzustaende aendern den sichtbaren Status nicht** — `DK-10 §10.1`
- **Vier kanonische Story-Types (`implementation`, `bugfix`, `concept`, `research`); `refactoring` ist explizit verboten; ungueltige Werte erzeugen fail-closed** — `FK-24 §24.2`
- **`execution_route` als abgeleitete Laufzeitachse (`execution`/`exploration`); darf Lieferpflicht von `story_type` nie abschwaechen** — `FK-24 §24.3`, `FK-59 §59.5`
- **Terminality-Vertrag: `implementation`/`bugfix` erfordern Implementierungsevidence; Exploration allein ist nicht terminal** — `FK-24 §24.6–24.8`
- **`implementation_contract` als zweite persistente Vertragsachse (`standard`/`integration_stabilization`), nur bei `story_type=implementation` zulaessig** — `FK-24 §24.3a`, `FK-59 §59.4`
- **`operating_mode` als abgeleitete Laufzeitachse (`ai_augmented`/`story_execution`), deterministisch aus Run-Bindung/Lock/Worktree-Konsistenz; kein stiller Fallback bei `binding_invalid`** — `FK-56 §56.2–56.9`
- **`StoryResetService` als menschlich ausgeloeste, 8-stufige administrative Recovery-Operation mit exklusivem Fence, Purge-Domaenen und Resume-faehigem Checkpoint-Flow** — `FK-53 §53.3–53.10`
- **`StorySplitService` als menschlich ausgeloeste administrative Operation auf Basis eines freigegebenen Split-Plans, Ausgangs-Story geht auf `Cancelled`, Nachfolger werden neu erstellt** — `FK-54 §54.4–54.12`
- **Story-Exit als leichtgewichtiger administrativer Uebergang von `story_execution` zu `ai_augmented`, nur ueber offizielle CLI-Route, erzeugt Mindest-Artefakt-Set** — `FK-58 §58.3–58.10`
- **Konsolidierte Vertragsachsen-Matrix; harte Ungueltigkeit-Regeln (z.B. `exit_class` nur unter `Cancelled`, `Cancelled` nie durch normale Closure)** — `FK-59 §59.7–59.11`
- **Story-Groessen-Definition: fuenf Stufen `XS/S/M/L/XL` mit definierten Datei-/Modul-Kriterien und Review-Punkten** — `DK-10 §10.4`
- **Mutual Exclusion zwischen Fast-Mode und Standard-Mode; projektweiter `mode_lock`** — `FK-24 §24.3.3`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/story_context_manager/types.py:StoryType` — vier kanonische Enum-Werte; deckt FK-24 §24.2 ab
- `src/agentkit/story_context_manager/types.py:ImplementationContract` — zwei gueltiger Werte; deckt FK-59 §59.4.2 ab
- `src/agentkit/story_context_manager/types.py:StoryMode` — `execution`/`exploration`/`not_applicable`; deckt execution_route ab
- `src/agentkit/story_context_manager/types.py:PROFILES` — StoryTypeProfile pro Story-Type mit erlaubten Modi, Phasen, Merge-/QA-Flags
- `src/agentkit/story_context_manager/models.py:StoryContext` — pipeline-runtime Modell; validiert `implementation_contract` und `execution_route` gegenueber Profil; frozen/immutable
- `src/agentkit/story_context_manager/models.py:PhaseState` — validiert, dass `verify` keine Top-Level-Phase ist
- `src/agentkit/story_context_manager/models.py:PhaseStatus` — deckt `PAUSED`, `ESCALATED`, `FAILED`, `BLOCKED`, `COMPLETED`
- `src/agentkit/story_context_manager/story_model.py:Story` — Stammdaten-Modell mit Wire-Enums (`WireStoryType`, `WireStorySize`, `StoryStatus`, `ChangeImpact`, `ConceptQuality`)
- `src/agentkit/story_context_manager/story_model.py:StoryStatus` — fuenf Zustande mit Wire-Encoding
- `src/agentkit/story_context_manager/sizing.py:StorySize` — SMALL/MEDIUM/LARGE/EPIC (nicht XS/S/M/L/XL)
- `src/agentkit/story_context_manager/lifecycle.py:create_story` — rudimentaerer Erstellungspfad ohne VektorDB-Abgleich, Zieltreue, Skill-Koordination
- `src/agentkit/story_context_manager/service.py:_check_transition` — Status-Transitions-Guard fuer FK-53 (blockiert `IN_PROGRESS -> CANCELLED`)
- `src/agentkit/story_context_manager/routing_rules.py` — `get_phases_for_story`, `should_run_exploration` basierend auf `execution_route`
- `src/agentkit/control_plane/runtime.py:_resolve_operating_mode` — Basis-Ableitung von `ai_augmented`/`story_execution`/`binding_invalid` aus Binding und Lock-Status
- `src/agentkit/control_plane/models.py` — `operating_mode` als Literal-Feld in EdgeBundle-Views
- `tests/contract/story_context/test_story_contracts.py` — Contract-Tests fuer `implementation_contract`-Kombinationen und `execution_route`-Alias
- `tests/unit/story_context_manager/test_lifecycle_transitions.py` — Vollstaendige Transition-Matrix fuer StoryStatus inkl. Terminal-Enforcement und `IN_PROGRESS -> CANCELLED`-Meldung (FK-53)

## 4. GAP-Analyse

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Deterministischer `story.md`-Export (CLI: `agentkit export-story-md`) und Weaviate-Indizierung | `FK-21 §21.11` | Kein Python-Modul `agentkit.backend.story_creation.story_md_export`, kein CLI-Befehl, keine Weaviate-Indizierungslogik vorhanden |
| A2 | VektorDB-Abgleich als Pflichtschritt der Story-Erstellung (Similarity-Suche + LLM-Konfliktbewertung) | `FK-21 §21.4` | Kein `story_search`-Aufruf, kein Schwellenwert-Filter (0.7), keine StructuredEvaluator-Integration im Erstellungspfad |
| A3 | Zieltreue-Pruefung (Dokumententreue Ebene 1) als Pflichtschritt vor Feldbelegung | `FK-21 §21.5` | Kein StructuredEvaluator-Aufruf fuer `doc-fidelity-goal`-Template im Erstellungspfad |
| A4 | Story-Erstellungs-Guard (PreToolUse-Hook, blockiert direkte Story-Backend-Mutationen ohne Skill) | `FK-21 §21.13` | Kein Hook-Mechanismus fuer direktes Story-Backend-Bypass-Blocking implementiert |
| A5 | `StoryResetService` mit 8-stufigem Purge-Flow, CLI `agentkit reset-story`, Idempotenz- und Checkpoint-Mechanismus | `FK-53 §53.3–53.10, formal.story-reset.*` | Keine Serviceklasse, kein CLI-Einstiegspunkt, keine Purge-Domaenen-Implementierung |
| A6 | `StorySplitService` mit Split-Plan-Verarbeitung, Dependency-Rebinding, Nachfolger-Erstellung, CLI `agentkit split-story` | `FK-54 §54.6–54.11, formal.story-split.*, formal.dependency-rebinding.*` | Keine Serviceklasse, kein CLI-Einstiegspunkt, kein Dependency-Rebinding |
| A7 | Story-Exit-Flow (CLI `agentkit exit-story`), Exit-Gate, Mindest-Artefakte (`viability_dossier.md`, `story_exit_record.json`, `exit_manifest_snapshot.json`) | `FK-58 §58.5–58.10, formal.story-exit.*` | Keine Implementierung des Exit-Flows; formal.story-exit.state-machine formal spezifiziert, aber code-seitig nicht vorhanden |
| A8 | Projektweiter `mode_lock` fuer Fast-/Standard-Mode-Mutual-Exclusion; atomar bei Setup-Preflight geprueft, bei Closure/Cancellation freigegeben | `FK-24 §24.3.3` | Kein `mode_lock`-Zustandsobjekt in Control Plane oder State-Backend implementiert |
| A9 | Batch-Repair-Befehl `agentkit repair-story-md` fuer Stories mit fehlender oder fehlerhafter `story.md` | `FK-21 §21.11.6` | Nicht implementiert |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Story-Erstellungs-Pipeline (`create_story`-Funktion) | `src/agentkit/story_context_manager/lifecycle.py:create_story` | `FK-21 §21.2, formal.story-creation.state-machine` | Nur Persistenz-Schritt; kein VektorDB-Abgleich, keine Zieltreue-Pruefung, kein Skill-Koordinationspfad, kein `story.md`-Export nach Anlage, kein VektorDB-Conflict-Flag, keine Preflight-Weaviate-Readiness-Pruefung |
| B2 | `operating_mode`-Ableitung | `src/agentkit/control_plane/runtime.py:_resolve_operating_mode` | `FK-56 §56.9, formal.operating-modes.state-machine` | Basis-Logik (ai_augmented/story_execution/binding_invalid) vorhanden; fehlt: Worktree-Match-Pruefung gemaess FK-56 §56.9 Schritt 3, bounded Re-Sync-Logik (§56.9a), keine dedizierte `resolve_operating_mode(event)`-Funktion mit vollstaendigem Bundle-Check |
| B3 | Terminality-Enforcement fuer `implementation`/`bugfix` | `src/agentkit/story_context_manager/models.py:PhaseState` | `FK-24 §24.6–24.8` | Modell-Felder `implementation_required`, `closure_allowed`, `exploration_completed`, `execution_pending` nicht im StoryContext/PhaseState vorhanden; Verify-Precondition-Check (FK-24 §24.7) und Closure-Block bei Exploration-only nicht implementiert |
| B4 | Story-Groessen-Schema | `src/agentkit/story_context_manager/sizing.py:StorySize` | `DK-10 §10.4, FK-21 §21.6.1` | Interne Pipeline-Groesse (`small/medium/large/epic`) vs. Wire-Groesse (`XS/S/M/L/XL` in `story_model.py:WireStorySize`) sind zwei getrennte Enums; konzeptionell gibt es nur eine Groessen-Skala (XS/S/M/L/XL); keine Review-Punkt-Zuordnung oder Timeout-Budget-Anbindung |
| B5 | `StoryContext`-Modus-Felder fuer Erstellungs-Klassifikation | `src/agentkit/story_context_manager/story_model.py:Story` | `DK-10 §10.3.1, FK-21 §21.6.2` | `change_impact` und `concept_quality` als Wire-Enums vorhanden; fehlen: `new_structures` (Boolean), Reifegrad-Feld (`goal_only`/`solution_approach`/`architecture_concept`), externe Integrationen (Boolean); 6-Kriterien-Entscheidungslogik fuer Modus-Ermittlung nicht implementiert |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Interne `StorySize`-Kodierung weicht von konzeptioneller Groessen-Skala ab | `src/agentkit/story_context_manager/sizing.py:StorySize` | `DK-10 §10.4, FK-21 §21.6.1` | Konzept definiert XS/S/M/L/XL; Code verwendet `small/medium/large/epic`. `epic` ist kein gueltiger Konzept-Wert. `WireStorySize` in `story_model.py` fuegt zudem `XXL` hinzu, das im Konzept nicht existiert. Zwei parallele Size-Enums ohne Single-Source-of-Truth verstossen gegen SINGLE SOURCE OF TRUTH und erzeugen Konvertierungs-Risiko |
| C2 | `StoryMode.NOT_APPLICABLE` ist kein normierter Konzept-Wert fuer `execution_route` | `src/agentkit/story_context_manager/types.py:StoryMode` | `FK-24 §24.3.2, FK-59 §59.5.2` | FK-24/FK-59 definieren `execution_route` als `execution`/`exploration`/`None` (fuer nicht-implementierende Stories). Der Code fuehrt `NOT_APPLICABLE` als dritten enum-Wert ein, der im Konzept nicht als kanonischer Wire-Wert normiert ist. FK-59 §59.5.2 spricht von "`execution_route=execution` nur als kompatibler Wire-Wert ohne implementierungsartige Exploration-Semantik"; ein eigenstaendiger `NOT_APPLICABLE`-Wert ist konzeptuell nicht vorgesehen |
| C3 | Bugfix erlaubt nur `EXECUTION` als `execution_route`, Konzept erlaubt auch `EXPLORATION` als Vorlauf | `src/agentkit/story_context_manager/types.py:PROFILES` | `FK-24 §24.5.1, DK-10 §10.3.1` | Das Profil fuer `bugfix` hat `allowed_modes=(StoryMode.EXECUTION,)`, aber FK-24 §24.5.1 erlaubt Exploration als vorbereitenden Schritt fuer `bugfix`. FK-21 §21.3.3 und §21.6.2 bestaetigen, dass Bugfix mit `Concept Quality=Low` Exploration ausloesen kann. Das Profil blockiert diesen legitimen Pfad |

## 5. Ableitungen / Empfehlungen

1. **Story-Erstellungs-Pipeline (FK-21) priorisiert implementieren**: Die Luecken A1–A4 sind systemkritisch, weil jede Story-Erstellung diesen Pfad durchlaeuft. VektorDB-Abgleich und `story.md`-Export sind Pflichtbestandteile laut Konzept; ihr Fehlen bedeutet, dass kein valider Story-Erstellungspfad existiert. Blocker fuer Weaviate-Indizierung und alle nachgelagerten Story-KB-Abfragen.
2. **Groessen-Diskrepanz (C1) bereinigen**: Zwei parallele Size-Enums (`StorySize` intern vs. `WireStorySize` Wire-Kontrakt) sind eine Single-Source-of-Truth-Verletzung und begruenden Konvertierungsrisiken. `XXL` hat keine konzeptionelle Grundlage; `epic` ist kein DK-10/FK-21-Wert. Sollte vor weiterer Modell-Nutzung normiert werden.
3. **Terminality-Vertrag (FK-24 §24.5–24.8) in PhaseState abbilden**: Die fehlenden Felder `implementation_required`, `closure_allowed` (B3) sind die Grundlage dafuer, dass Verify und Closure Exploration-only-Stories nicht falsch durchlassen. Risiko: ohne diese Guards kann eine `implementation`-Story nach Exploration faelschlich als Done geschlossen werden (der exakte BB2-093-Fehler, den FK-24 normativ schliessen soll).
4. **Bugfix-Exploration zulassen (C3)**: Bugfix-Profil auf `allowed_modes=(StoryMode.EXECUTION, StoryMode.EXPLORATION)` erweiterbar gemaess FK-24 §24.5.1 und FK-21 §21.3.3; Aenderung ist klein aber normativ notwendig.
5. **`StoryMode.NOT_APPLICABLE` normieren oder entfernen (C2)**: Entweder als konzeptionell anerkannten Wert formal dokumentieren oder durch `None` im Konzept-Sinne ersetzen; aktuell widerspricht er FK-59 §59.5.2.
6. **Administrative Services (A5–A7) planen**: `StoryResetService`, `StorySplitService` und Story-Exit sind vollstaendig formal spezifiziert (formal.story-reset.*, formal.story-split.*, formal.story-exit.*) und direkt implementierbar. Ohne sie gibt es keinen offiziellen Recovery-Pfad fuer eskalierte oder falsch geschnittene Stories.
7. **`mode_lock` fuer Fast/Standard-Mutual-Exclusion (A8) in Control Plane erganzen**: Fehlt der projectweite Lock, koennen Fast- und Standard-Mode gleichzeitig aktiv sein, was FK-24 §24.3.3 explizit als Fehler klassifiziert.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/10-story-lifecycle-und-erstellung.md`
  - `concept/technical-design/21_story_creation_pipeline.md`
  - `concept/technical-design/24_story_type_mode_terminalitaet.md`
  - `concept/technical-design/53_story_reset_service_recovery_flow.md`
  - `concept/technical-design/54_story_split_service_scope_explosion.md`
  - `concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md`
  - `concept/technical-design/58_story_exit_human_takeover_handoff.md`
  - `concept/technical-design/59_story_contract_axes_and_combination_matrix.md`
  - `concept/formal-spec/story-creation/entities.md`
  - `concept/formal-spec/story-creation/state-machine.md`
  - `concept/formal-spec/story-creation/invariants.md`
  - `concept/formal-spec/story-workflow/state-machine.md`
  - `concept/formal-spec/story-reset/state-machine.md`
  - `concept/formal-spec/story-split/state-machine.md`
  - `concept/formal-spec/story-exit/state-machine.md`
  - `concept/formal-spec/operating-modes/state-machine.md`
  - `src/agentkit/story_context_manager/types.py`
  - `src/agentkit/story_context_manager/models.py`
  - `src/agentkit/story_context_manager/story_model.py`
  - `src/agentkit/story_context_manager/lifecycle.py`
  - `src/agentkit/story_context_manager/sizing.py`
  - `src/agentkit/story_context_manager/routing_rules.py`
  - `src/agentkit/story/models.py`
  - `src/agentkit/story/service.py`
  - `src/agentkit/control_plane/runtime.py` (Auszug)
  - `tests/contract/story_context/test_story_contracts.py`
  - `tests/unit/story_context_manager/test_lifecycle_transitions.py`
- **Punktuell gelesen:**
  - `concept/technical-design/_meta/domain-registry.yaml` (BC-ID und contract_docs)
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/story*/` und `src/agentkit/story_context_manager/`: Vollscan aller Module
  - Grep `StoryResetService|StorySplitService|story_reset|story_split|story_exit`: Kein Treffer in produktivem Code (nur Branch-Guard)
  - Grep `export.*story.*md|StoryMdExport|vectordb_conflict|similarity_threshold`: Kein Treffer
  - Grep `mode_lock|operating_mode|resolve_operating_mode`: Treffer in `control_plane/runtime.py` und `control_plane/models.py`
  - Grep `find tests -name *.py | grep story`: Vollscan Testverzeichnisse
