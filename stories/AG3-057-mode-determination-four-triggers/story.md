# AG3-057: Deterministische Modus-Ermittlung (4-Trigger-Modell) — `execution_route` real ableiten

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `pipeline-framework` / Setup-Preflight-Governance (BC1) — die deterministische Phase-1-Entscheidung, welche Route eine Story nimmt (EXECUTION vs. EXPLORATION).
**Quell-Konzepte (autoritativ):**
- `FK-22 §22.8.1` — `determine_mode(context, *, project_root)`, die vier unabhaengigen Trigger
- `FK-22 §22.8.2` — Entscheidungsregel-Tabelle (inkl. „Unbekannter Feldwert -> Exploration + WARNING")
- `FK-22 §22.8.2b` — abgeschaffte Kriterien (REF-032): kein `Requires Exploration`, kein `External Integrations`, kein Maturity-Kriterium
- `FK-23 §23.1` — Geltungsbereich der Modus-Ermittlung: **implementierende** Story-Typen `implementation` UND `bugfix` (beide koennen explorativ laufen)
- `FK-23 §23.2.1` — Zusammenfassung der Entscheidungsregel: `>=1 Trigger ODER Pflichtfeld fehlt ODER VektorDB-Konflikt -> Exploration`; sonst Execution; **Default: Exploration (fail-closed)**
- `FK-24 §24.3.2` — `execution_route` ∈ `{execution, exploration, None}`; **`None` fuer nicht-implementierende Storys** (concept/research)

---

## 1. Kontext / Ist-Zustand (belegt)

Die deterministische Modus-Entscheidung — der **Kern-Determinismus** des Setup→Exploration/Implementation-Uebergangs — ist nicht implementiert. Statt aus den vier Triggern abzuleiten, setzt der Code den **Story-Typ-Default**:

- `src/agentkit/governance/setup_preflight_gate/context_builder.py:155` — `mode = profile.default_mode`
- `context_builder.py:168` — `execution_route=mode` (analog `:227`, `:250` in den internal/standalone-Pfaden) — alle drei Build-Pfade verdrahten den Profil-Default, nicht das Trigger-Ergebnis.
- `src/agentkit/story_context_manager/routing_rules.py:29` (`get_phases_for_story`) / `:38-42` (`should_run_exploration`) liest `execution_route` korrekt — der **Entscheider fehlt**, nicht der Standard-Konsument.

Die Trigger-Inputfelder existieren **nicht** im `StoryContext`-Modell (`story_context_manager/models.py:310-323`; nur `execution_route` vorhanden, Zeile `:316`; Allowed-Mode-Validator `:393-400`): `new_structures`, `vectordb_conflict_resolved`, `concept_paths` fehlen komplett.

**Bestehende autoritative Feld-Owner (NICHT duplizieren — FIX THE MODEL):**
- `Story.change_impact: ChangeImpact` existiert bereits (`story_context_manager/story_model.py:194`; Enum `:97-106`). Der für Trigger 2 relevante, architektur-relevante Wert ist `ChangeImpact.ARCHITECTURE_IMPACT = "Architecture Impact"` (`story_model.py:106`) — er existiert im realen Enum und deckt sich exakt mit dem FK-22-§22.8.1-Referenztext (`change_impact == "Architecture Impact"`), DK-02 §Issue-Schema und FK-25 §25.7.1 (kanonische Impact-Stufe 4). Es gibt **keinen** String-Drift; Trigger 2 bindet typisiert an `ChangeImpact.ARCHITECTURE_IMPACT`.
- `Story.concept_quality: ConceptQuality` existiert bereits (`story_model.py:195`; Enum `:109-114`, `ConceptQuality.LOW = "Low"`).
- `StorySpecification.concept_refs: list[str] | None` existiert bereits (`story_model.py:143`; DB-Spalte `concept_refs_json` in `state_backend/store/story_repository.py:424`). Es gibt **kein** Feld `concept_paths` — `concept_refs` ist der vorhandene Owner.

**Bugfix-Exploration ist real nicht lauffaehig (Gegenbeleg zur frueheren AC7-Behauptung):**
- `src/agentkit/process/language/definitions.py:107-124` (`_build_bugfix_workflow`) definiert nur `setup -> implementation -> closure`; **keine** `exploration`-Phase, **keine** `setup -> exploration`-Transition.
- `routing_rules.get_phases_for_story` (`:23-33`) **entfernt** `exploration` nur, fuegt sie nie hinzu. Fehlt sie im Profil/Workflow, kann sie auch bei `execution_route=EXPLORATION` nie laufen.
- `build_pipeline_handler_registry` (`bootstrap/composition_root.py:1614-1615`) registriert Handler ausschliesslich entlang `resolve_workflow(story_type).phase_names`; fuer Bugfix wird damit nie ein Exploration-Handler registriert.
- Drei Tests zementieren diesen Ist-Zustand: `tests/unit/process/language/test_definitions.py:77-83`, `tests/integration/pipeline_engine/test_pipeline_runner.py:447-449`, `tests/unit/bootstrap/test_pipeline_handler_registry.py:89-98`.

Folge: FK-23 §23.1 (Bugfix kann explorativ laufen) ist heute fuer Bugfix nicht erfuellt. AG3-057 muss die Bugfix-Exploration **real** durch die Maschinerie tragen, nicht nur den Entscheider liefern.

## 2. Scope

### 2.1 In Scope
1. **Typisierte Trigger-Inputs am `StoryContext`** (ARCH-55: englische Bezeichner/Enum-Werte; CLAUDE.md „typisiert statt String-/Flag-Kaskaden"). Es werden **nur die noch fehlenden** Felder neu eingefuehrt; die schon vorhandenen autoritativen Felder werden **wiederverwendet**, nicht gedoppelt:
   - **Neu am `StoryContext`:**
     - `new_structures: bool = False` (fail-closed-Default: Abwesenheit zaehlt als „keine neuen Strukturen"; siehe Regel — der Default loest **keinen** Trigger aus, blendet aber auch keinen echten Wert weg)
     - `vectordb_conflict_resolved: bool = False` — der am `StoryContext` konsumierte Run-Wert traegt **exakt** den autoritativen Produzenten-Feldnamen aus AG3-068 (`vectordb_conflict_resolved` am Story-Record, FK-21 §21.12). Damit gibt es **eine** Vertrags-Wahrheit ueber Producer (AG3-068) und Consumer (AG3-057) hinweg — kein zweiter Feldname, kein unbenanntes Mapping, kein Schattenfeld. **Mapping-Hinweis (FK-22 ↔ Code):** Der FK-22-§22.8.1-Pseudocode nennt das Feld verkuerzt `context.vectordb_conflict`; das ist derselbe boolesche Sachverhalt („Konflikt erkannt UND geklaert -> Exploration erzwingen", FK-21 §21.12). Der reale, persistierte Feldname ist `vectordb_conflict_resolved`; daran bindet die Story. Hier wird das Flag nur **konsumiert** (fail-closed-Default `False`/absent); Produzent/Persistenz-Owner bleibt AG3-068 (siehe Out-of-Scope). Die FK-22-Pseudocode-Kurzschreibweise ist als doc-only-Nachzug an FK-22 anzugleichen (siehe Cross-Story-Voraussetzungen).
     - `concept_paths: tuple[str, ...] = ()` — am `StoryContext` als die **Laufzeit-Projektion** der autoritativen `StorySpecification.concept_refs`. `concept_refs` bleibt der Persistenz-Owner; `concept_paths` ist der von dort befuellte, fuer den Sandbox-Guard typisierte Run-Wert. Keine zweite Persistenz-Wahrheit (siehe In-Scope 5).
   - **Wiederverwendet (kein neues Feld):**
     - `change_impact: ChangeImpact | None` — aus `Story.change_impact` projiziert; `| None` nur fuer den Run-Kontext (Feld evtl. (noch) nicht aufloesbar), nicht als neue Persistenzwahrheit.
     - `concept_quality: ConceptQuality | None` — aus `Story.concept_quality` projiziert; `| None` analog.
   Unbekannter/nicht aufloesbarer Wert von `change_impact`/`concept_quality` ist **kein** stiller Default, sondern fail-closed-Signal (siehe Regel, AK4).
2. **`determine_mode(context: StoryContext, *, project_root: Path | None = None) -> StoryMode | None`** als eigenes typisiertes Modul (z. B. `setup_preflight_gate/mode_determination.py`), reine Entscheidungsfunktion (Logging erlaubt, keine I/O-Seiteneffekte ausser Concept-Pfad-Existenzpruefung), exakt nach FK-22 §22.8.1/§22.8.2:
   - Vorbedingung: `story_type not in {implementation, bugfix}` -> **`None`** (concept/research haben keine `execution_route`; FK-24 §24.3.2). Es findet **keine** Trigger-Auswertung statt.
   - **VektorDB-Konflikt-Vorrang** (vor Trigger-Auswertung): `vectordb_conflict_resolved` -> EXPLORATION.
   - Trigger 1: `not _has_valid_concept_paths(concept_paths, project_root=...)` -> EXPLORATION + WARNING.
   - Trigger 2: `change_impact == ChangeImpact.ARCHITECTURE_IMPACT` -> EXPLORATION + INFO. (Typisierte Bindung an den realen Enum-Wert `ChangeImpact.ARCHITECTURE_IMPACT = "Architecture Impact"`, `story_model.py:106` — deckungsgleich mit FK-22 §22.8.1 / DK-02 / FK-25 §25.7.1; kein String-Vergleich, kein String-Drift.)
   - Trigger 3: `new_structures` -> EXPLORATION + INFO.
   - Trigger 4: `concept_quality == ConceptQuality.LOW` -> EXPLORATION + INFO.
   - Unbekannter/nicht aufloesbarer Wert (`change_impact`/`concept_quality` ist `None`) -> EXPLORATION + WARNING (fail-closed).
   - Kein Trigger -> EXECUTION. Default/Unsicherheit -> EXPLORATION (fail-closed).
3. **`_has_valid_concept_paths`** mit Sandbox-Guard: mind. ein nicht-leerer Pfad, Dokument existiert/abrufbar, Pfad liegt **innerhalb** `project_root`. Fehlt `project_root` (`None`): CWD-Fallback + WARNING (FK-22 §22.8.1 Bug-Fix-Hinweis). Leerer String / ungueltiger / nicht existierender Pfad zaehlt als „kein gueltiges Konzept".
4. **Verdrahtung — alle drei Build-Pfade**: `build_story_context` (`context_builder.py:163-177`), `build_internal_story_context` (`:245-258`) und der Standalone-Fallback (`:222-231`) setzen `execution_route = determine_mode(...)` statt `profile.default_mode`. Fuer concept/research liefert `determine_mode` `None` — konsistent mit dem Profil (`allowed_modes=(None,)`). Allowed-Modes-Validator (`models.py:393-400`) bleibt erfuellt (impl/bugfix lassen `EXECUTION`/`EXPLORATION` zu; concept/research lassen `None` zu).
5. **Bugfix-Exploration real durch die Maschinerie** (FK-23 §23.1; behebt den AC7-Gegenbeleg). Ein Bugfix mit `execution_route=EXPLORATION` muss tatsaechlich `setup -> exploration -> implementation -> closure` laufen:
   - `_build_bugfix_workflow` (`definitions.py:107-124`) um die `exploration`-Phase + `setup -> exploration` / `exploration -> implementation`-Transitionen (Gate `exploration_gate_approved`) **so erweitern wie der Implementation-Workflow** (`definitions.py:88-104`).
   - `StoryTypeProfile` fuer BUGFIX (`story_context_manager/types.py:57-74`): `phases` um `"exploration"` ergaenzen (allowed_modes erlauben EXPLORATION bereits). `routing_rules.get_phases_for_story` entfernt `exploration` dann fuer EXECUTION-Bugfixes wieder — der Mechanismus ist identisch zum Implementation-Pfad, kein Sonderpfad.
   - `build_pipeline_handler_registry` registriert den Exploration-Handler dann automatisch ueber `resolve_workflow(BUGFIX).phase_names` (keine Sonderlogik noetig).
   - **Test-Updates (zwingend, sonst rot):** `tests/unit/process/language/test_definitions.py:77-83`, `tests/integration/pipeline_engine/test_pipeline_runner.py:447-449`, `tests/unit/bootstrap/test_pipeline_handler_registry.py:89-98` muessen vom „Bugfix hat nie exploration" auf das neue Verhalten umgestellt werden (EXECUTION-Bugfix: keine exploration; EXPLORATION-Bugfix: exploration laeuft).
6. **Single Source of Truth (FIX-1-Muster wie `_resolve_authoritative_mode`, `context_builder.py:70-109`)**: die Trigger-Inputs werden aus der **autoritativen** Quelle befuellt (StoryService-/State-Backend-Record: `Story.change_impact`/`Story.concept_quality`, `StorySpecification.concept_refs`), GitHub nur Legacy/Standalone-Fallback. `new_structures`/`vectordb_conflict_resolved` haben heute (noch) **keine** von dieser Story selbst zu liefernde Persistenzspalte:
   - `new_structures`: **Modell/Schema erweitern** (FIX-THE-MODEL) — Feld an `Story` (Owner story_context_manager) + DB-Spalte; fail-closed-Default `False` bei Abwesenheit. Schema-Version ziehen falls noetig.
   - `vectordb_conflict_resolved`: **nicht** hier persistieren — Produzent/Persistenz-Owner ist AG3-068 (`vectordb_conflict_resolved` am Story-Record, FK-21 §21.12; siehe Out-of-Scope). AG3-057 liest den autoritativen Wert unter **demselben** Feldnamen in den `StoryContext` und konsumiert ihn fail-closed (`False`/absent, solange AG3-068 nicht gemerged ist). Kein Rename, keine zweite Spalte, kein unbenanntes Mapping.
   Keine zweite Wahrheit, kein Schattenfeld.
7. **Negativpfade an der Phasengrenze** + vollstaendige Trigger-Matrix als Tests, inkl. fehlender Pflichtfelder (siehe AK4) und Bugfix-Exploration-Routing (siehe AK7b).

### 2.2 Out of Scope (mit Owner)
- **Echte VektorDB-Konflikt-Erkennung + Persistenz des `vectordb_conflict_resolved`-Flags** (Produzent) — **AG3-068** (Welle 2; setzt das Flag am autoritativen Story-Record laut FK-21 §21.12 / AG3-068 §2.1.5). `_STORY_INDEX.md:152` Dedup-Notiz: „Der `vectordb_conflict`-Konsument bleibt bei AG3-057, der Produzent ist AG3-068" — die Index-Notiz nutzt den FK-22-Kurznamen; der autoritative, persistierte Feldname des Produzenten ist `vectordb_conflict_resolved`, an den AG3-057 als Konsument bindet. Hier wird das Flag nur **konsumiert** (fail-closed-Default `False`/absent).
- ARE-Bundle-Load (FK-22 §22.4b) — separater Befund, Owner **AG3-077** (`load_are_bundle()`-Setup-Schritt).
- `required_acceptance_criteria`/`advisory_context`-Durchreichung im Spawn-Vertrag (FK-23 §23.6.1) — angrenzend; nur mitnehmen, wenn trivial und ohne Scope-Explosion, sonst als Folge-Einheit melden.

## 3. Akzeptanzkriterien
1. `determine_mode` existiert als typisierte Funktion mit Rueckgabe `StoryMode | None` und implementiert §22.8.1 **exakt** (Reihenfolge: Story-Typ-Weiche → VektorDB-Vorrang → Trigger 1–4 → Execution).
2. Jeder der vier Trigger loest **unabhaengig** Exploration aus (vier einzelne Tests, alle anderen Trigger neutral).
3. VektorDB-Konflikt erzwingt Exploration **vor** der Trigger-Auswertung (Test: Konflikt + sonst alle neutral -> Exploration).
4. **Fehlende/unbekannte Pflichtfelder vollstaendig fail-closed (Tests je Feld):**
   - `change_impact is None` (nicht aufloesbar) -> Exploration + WARNING.
   - `concept_quality is None` (nicht aufloesbar) -> Exploration + WARNING.
   - `concept_paths == ()` / leerer String -> Trigger 1 greift -> Exploration + WARNING.
   - `new_structures` fehlt am Record -> fail-closed-Default `False` (kein stiller Trigger, aber auch kein weggeblendeter echter Wert) — Test belegt, dass die Abwesenheit deterministisch `False` ist und nicht zu unkontrolliertem Verhalten fuehrt.
   - Default-Pfad (alle Trigger neutral, kein Konflikt) -> Execution; reine Unsicherheit -> Exploration.
5. `_has_valid_concept_paths` Sandbox-Guard: Pfad ausserhalb `project_root` / nicht existent / leer -> ungueltig (Trigger 1 greift); `project_root=None` -> CWD-Fallback + WARNING (Tests).
6. Concept-/Research-Story -> `determine_mode` liefert **`None`** (keine Trigger-Auswertung; FK-24 §24.3.2); der Build-Pfad setzt `execution_route=None`, konsistent mit `allowed_modes=(None,)` (Test).
7. `execution_route` wird in **allen drei** Build-Pfaden (`build_story_context`, `build_internal_story_context`, Standalone-Fallback) aus `determine_mode` gesetzt; Allowed-Modes-Validator bleibt konsistent.
7b. **Bugfix-Exploration laeuft real (FK-23 §23.1):** Ein Bugfix mit `execution_route=EXPLORATION` durchlaeuft `setup -> exploration -> implementation -> closure` (Workflow-Definition, Profil-`phases`, Handler-Registry, `routing_rules` angepasst); ein Bugfix mit `execution_route=EXECUTION` durchlaeuft weiterhin `setup -> implementation -> closure`. Die drei bestehenden „Bugfix hat nie exploration"-Tests (`test_definitions.py:77-83`, `test_pipeline_runner.py:447-449`, `test_pipeline_handler_registry.py:89-98`) sind auf das neue Verhalten umgestellt (gueltiger UND ungueltiger Pfad verprobt).
8. Trigger-Inputs stammen aus der autoritativen Quelle (`Story.change_impact`/`Story.concept_quality`, `StorySpecification.concept_refs` -> `concept_paths`-Projektion; kein zweites Wahrheitsmodell). Fehlt die Persistenzspalte fuer `new_structures`, ist das `Story`-Modell/Schema sauber erweitert (kein Schattenfeld); `vectordb_conflict_resolved` wird NUR unter dem autoritativen Produzenten-Feldnamen konsumiert (Produzent/Persistenz-Owner AG3-068, FK-21 §21.12 — kein zweiter Feldname).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 (inkl. 7b) erfuellt; giftige Codex-Review PASS; committed auf `main`; (Jenkins/Sonar laufen danach in der CI).

## 5. Guardrail-Referenzen
- **FAIL CLOSED:** Unsicherheit/Unbekanntes/fehlendes Pflichtfeld -> Exploration, nie stilles Execution. Concept/Research -> `None` (kein erzwungenes Execution).
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** Trigger-Inputs an die autoritative Story-Wahrheit; vorhandene Felder (`change_impact`/`concept_quality`/`concept_refs`) wiederverwenden, kein Schattenfeld, keine zweite Steuerwahrheit. `new_structures` ist ein neuer, sauber persistierter Owner; `vectordb_conflict_resolved` wird nur konsumiert — unter **demselben** Feldnamen wie der AG3-068-Produzent, kein abweichender Consumer-Name.
- **TYPISIERT STATT STRINGS:** Enums statt String-Literal-Vergleiche; Bindung an `ChangeImpact`/`ConceptQuality`-Enums, nicht an FK-Stringliterale; Story-Typ-Routing/Trigger typisiert.
- **ARCH-55:** alle neuen Felder/Enum-Werte/Identifier englisch.
- **ZERO DEBT:** kein Stub-als-Done; die Entscheidung ist real verdrahtet und vom Konsumenten (`routing_rules`, Workflow, Handler-Registry) **fuer impl UND bugfix** sichtbar.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- FK-22 §22.8.1 enthaelt die **Referenzimplementierung** (Python) — als Vorlage nutzen, aber typisiert (Enums, `StoryMode | None`-Rueckgabe statt String) und ARCH-55-konform. Der FK-22-Referenztext vergleicht gegen die Stringliterale `"Architecture Impact"` (Trigger 2) und `"Low"` (Trigger 4). **Beide Werte existieren im realen Enum:** `ChangeImpact.ARCHITECTURE_IMPACT = "Architecture Impact"` (`story_model.py:106`) und `ConceptQuality.LOW = "Low"` (`story_model.py:114`). Binde Trigger 2 typisiert an `ChangeImpact.ARCHITECTURE_IMPACT`, Trigger 4 an `ConceptQuality.LOW` — Enum-Vergleich statt String-Literal (TYPISIERT STATT STRINGS). Kein Konzept-Drift, kein doc-only-Nachzug noetig.
- Wo die autoritativen Story-Felder herkommen (StoryService-Record FK-21, `Story.change_impact`/`concept_quality`, `StorySpecification.concept_refs`): am FIX-1-Muster (`_resolve_authoritative_mode`, `context_builder.py:70-109`) orientieren. Wenn die `new_structures`-Persistenz eine Story-Creation-/Backend-Erweiterung erzwingt, die ueber dieses Paket hinaus eskaliert: **melden**, nicht still ausweiten. Mindestziel: Felder am Modell, Entscheider verdrahtet, fail-closed bei Abwesenheit.
- Bugfix-Exploration (In-Scope 5) am Implementation-Workflow (`definitions.py:88-104`) spiegeln; **kein** Sonderpfad in `routing_rules`. Die drei „Bugfix hat nie exploration"-Tests gehoeren zur AG3-057-Lieferung (gleicher Cut: das 4-Trigger-Modell macht Bugfix-Exploration erst real), nicht zu einer anderen Story.
- VektorDB-Flag: Der `StoryContext`-Run-Wert heisst **`vectordb_conflict_resolved`** — exakt der autoritative Produzenten-Feldname von AG3-068 (FK-21 §21.12). Hier **nur konsumieren** (fail-closed `False`/absent), nicht persistieren, nicht umbenennen. Der FK-22-§22.8.1-Pseudocode nutzt die Kurzschreibweise `context.vectordb_conflict`; binde an den realen Feldnamen `vectordb_conflict_resolved` und melde die FK-22-Pseudocode-Kurzschreibweise als doc-only-Nachzug an die FK-22-zustaendige Einheit — **nicht** im AG3-057-Code-Cut korrigieren.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** — das uebernimmt der Orchestrator nach Review/Verifikation.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle (genaue Ausgaben), Test-Namen der Trigger-Matrix + der Bugfix-Routing-Tests.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
