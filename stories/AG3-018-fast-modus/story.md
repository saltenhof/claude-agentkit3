# AG3-018: Fast-Modus konzeptionell und im Code aufnehmen

**Typ:** Concept + Implementation
**Groesse:** L
**Abhaengigkeiten:** keine harte (impliziter Sequenzwunsch nach abgeschlossener CLI-Drift-Korrektur, weil Fast-Modus die Service-API referenziert)
**Quell-Konzept:** FK-22 §22.8 (Modus-Ermittlung), FK-24 (Story-Type-Mode-Terminalitaet), FK-27 (QA-Subflow), FK-29 (Closure), FK-30/31/35 (Guards/Integrity), FK-91 §91.1a (Service-API)

---

## Kontext

AK3 kennt heute zwei Story-Modi: `execution` und `exploration`. Der User-Workflow im Alltag enthaelt aber Stories, die der User eng begleitet und sofort selbst reviewt — fuer diese sind voller QA-Subflow plus Repo-Schutz-Guards uebertrieben. Aktuell entgleitet das in Freestyle-Agent-Aufrufen ausserhalb der Story-Disziplin: keine Story-ID, kein Branch, kein Tracking, keine Telemetrie.

Der Fast-Modus loest das: die Story bleibt eine vollwertige AK3-Story (Story-ID, Branch, Closure-Workflow, Telemetrie-Eintrag), aber Schutz- und Pruef-Schichten sind gezielt reduziert, weil ein Mensch die Story aktiv begleitet.

## Zwei Besonderheiten gegenueber Standard-Modus

1. **QS-Schleifen abgespeckt**: QA-Subflow Schichten 2-4 (LLM-Bewertung, Adversarial, Policy) entfallen vollstaendig. Schicht 1 (Strukturell) reduziert sich auf einen **harten Pflicht-Floor "Tests gruen"** (nicht abschaltbar). Begruendung: User reviewed das Inhaltliche selbst.

2. **Repo-Schutz-Guards entfallen**: 4 Guards werden nicht aktiviert; Lock-Records werden nicht angelegt; Scope-Overlap-Check entfaellt. Andere Agents koennen parallel auf demselben Repo committen. Konfliktbehandlung beim Merge erfolgt via Pre-Merge-Rebase auf main; bei Konflikt Eskalation an User.

   **Was bleibt aktiv (Baseline-Guards, alle Modi):** destructive git protections, secrets protection, CCAG, self-protection. Siehe `formal-spec/operating-modes/invariants.md` `baseline_guards_apply_in_all_modes`.

## Aktivierung

- Story-Attribut `mode=fast`, gesetzt beim Anlegen oder Starten der Story ueber die AK3-Service-Schnittstelle.
- **Kein** CLI-Flag (CLI ist Operator-Recovery-Spezialfall, nicht Standardweg, vgl. parallele CLI-Drift-Korrektur).
- **Kein** Projekt-Feature-Flag. Fast ist Standard-Modus, in jedem AK3-Projekt verfuegbar gleichrangig zu execution/exploration.
- Verfuegbar nur fuer Story-Typen `implementation` und `bugfix`. `concept`/`research` -> Fail-Closed.

## Mutual Exclusion zwischen Fast und Standard (FK-24 §24.3.3)

Fast und Standard (`execution` / `exploration`) sind **fachlich
ausschliesslich** auf Projekt-Ebene. Solange in einem Projekt
mindestens eine Story im Standard-Modus aktiv ist (Status
`In Progress`), darf keine Fast-Story starten — und umgekehrt.

Begruendung:

- Eine parallel aktive Standard-Story haelt ihre Story-scoped
  Repo-Schutz-Guards aktiv. Genau diese deaktiviert Fast — die
  Fast-Story wuerde reproduzierbar gegen die noch aktiven Guards
  der Standard-Story laufen.
- Fast setzt voraus, dass ein Mensch die Story aktiv begleitet.
  Eine zweite Pipeline parallel verwaessert dieses Versprechen.
- Pre-Merge-Rebase-Konflikte zwischen Fast und Standard sind
  wahrscheinlicher als zwischen zwei Stories desselben Modes.

**Innerhalb** desselben Modes ist Parallelitaet erlaubt
(reglementiert ueber die Execution-Caps, FK-70 §70.6.2). Das
Mutex-Verbot greift nur zwischen verschiedenen Modes.

Diese Story enforced die Regel ueber:

1. **Projektweiten `mode_lock`** in der Control Plane mit Werten
   `null` | `standard` | `fast` plus `holder_count`. Atomar gesetzt
   beim Story-Start, runtergezaehlt bei Story-Abschluss.
2. **Setup-Preflight-Check 10** `no_competing_story_mode_active`
   (FK-22 §22.3.1, formale Invariante
   `formal.setup-preflight.no_competing_story_mode_active`).
3. **Klare Operator-Fehlermeldung** bei Konflikt: "Mode-Konflikt:
   Fast nicht startbar; Standard-Story BB2-XXX laeuft noch. Story
   bleibt in Approved." Die Story bleibt im Backlog ready, sobald
   der aktive Modus alle Stories beendet hat.

## Mode-Profil (kanonische Tabelle, Owner FK-24)

Vollstaendige Tabelle Phase × Substep × Fast-Verhalten als kanonische Quelle in einer neuen FK-24-Sektion. Alle abhaengigen Konzepte verweisen auf diese Sektion — keine Duplikation. Auszeichnung: **IN** unveraendert / **OUT** entfaellt / **MOD** veraendert (Delta hinter dem Doppelpunkt).

| Phase | Substep | Fast-Verhalten |
|-------|---------|----------------|
| Setup | Preflight-Gates (10 Checks) | **MOD**: 4 Mindest-Checks aktiv (story_exists, kein aktiver Run, kein staler Worktree, Mode-Konflikt aus §24.3.3); Status/Deps/Scope-Overlap weg |
| Setup | Story-Context-Berechnung | **IN** |
| Setup | ARE-Bundle laden | **OUT** |
| Setup | Story-Typ-Weiche | **MOD**: nur impl/bugfix erlaubt |
| Setup | Worktree-Erstellung | **IN** |
| Setup | Guard-Aktivierung | **OUT** (Baseline-Guards bleiben) |
| Setup | Modus-Ermittlung | **OUT** (mode aus Story-Attribut, keine 4-Trigger-Auswertung) |
| Exploration | komplette Phase (alle Substeps) | **OUT** |
| Implementation | Worker-Start | **MOD**: Light-Prompt, keine Inkrement-/Review-Pflicht |
| Implementation | Inkrementelles Vorgehen | **MOD**: Disziplin Worker-frei, kein Inkrement-Tracking |
| Implementation | Inline-Reviews | **OUT** (User reviewed direkt) |
| Implementation | Finaler Build + Gesamttest | **MOD**: Build+Tests gruen — **harter Pflicht-Floor**, nicht abschaltbar |
| Implementation | Handover-Paket | **MOD**: nur Worker-Manifest, keine QA-Artefakte |
| QA-Subflow | Schicht 1 Strukturell | **MOD**: degeneriert auf Tests-gruen-Floor |
| QA-Subflow | Schicht 2 LLM-Bewertungen | **OUT** |
| QA-Subflow | Schicht 3 Adversarial | **OUT** |
| QA-Subflow | Schicht 4 Policy-Eval | **OUT** |
| QA-Subflow | Feedback-Loop | **OUT** (User steuert manuell) |
| Closure | Finding-Resolution-Gate | **OUT** (keine Findings produziert) |
| Closure | Integrity-Gate | **MOD**: Sanity-Gate (Tests gruen, Worktree clean, Pre-Merge-Rebase OK) — Pflicht |
| Closure | Story-Branch Push | **IN** |
| Closure | Branch-Merge | **MOD**: Pre-Merge-Rebase auf main statt Lock; bei Konflikt Eskalation an User |
| Closure | Main Push (mit Rollback) | **IN** |
| Closure | Teardown | **IN** |
| Closure | Story-Close | **IN** |
| Closure | Metriken schreiben | **MOD**: Records mit `mode=fast` getaggt; KPI separat aggregierbar |
| Closure | Doctreue Ebene 4 | **OUT** |
| Closure | Postflight-Gates | **MOD**: nur Hard-Failures (Branch-Reste, offene Worktrees) bleiben |
| Closure | VektorDB-Sync | **IN** |
| Closure | Guards deaktivieren | **MOD**: no-op (keine Locks aktiv) |

## Scope

### In Scope — Konzept-Aenderungen (BC-getrennt)

| BC | Konzept | Aenderung |
|----|---------|-----------|
| story-mode (Owner FK-24) | `24_story_type_mode_terminalitaet.md` | **Neue Sektion §24.X "Mode-Profil Fast"** mit kanonischer Tabelle (s.o.). Mode-Enum-Erweiterung um `fast`. Single Source of Truth fuer Fast-Profil. |
| setup-preflight | `22_setup_preflight_worktree_guard_activation.md` | §22.3.1, §22.4b, §22.5, §22.7, §22.8: kurze Verweise "im `mode=fast` greift Profil aus FK-24 §24.X" — keine Duplikation der Tabelle |
| exploration | `23_modusermittlung_exploration_change_frame.md` | Hinweis "Phase entfaellt im `mode=fast`; Routing direkt von Setup zu Implementation" |
| implementation | `26_implementation_runtime_worker_loop.md` | Verweise auf Light-Pfad in §26.2 (Worker-Start), §26.3 (Inkrement), §26.5 (Reviews), §26.7 (Handover) |
| verify-system | `27_verify_pipeline_closure_orchestration.md` | Verweise in §27.4-27.7 ("im `mode=fast` greift Schicht-1-Floor; Schichten 2-4 entfallen") |
| story-closure | `29_closure_sequence.md` | Verweise in §29.1-29.3 (Sanity-Gate, Pre-Merge-Rebase, OUT-Substeps) |
| governance-and-guards | `30_hook_adapter_guard_enforcement.md`, `31_branch_guard_orchestrator_guard_artefaktschutz.md`, `35_integrity_gate_governance_beobachtung_eskalation.md` | Hinweise "im `mode=fast` Story-Scoped-Guards SKIP; Baseline-Guards aktiv (`baseline_guards_apply_in_all_modes`)" |
| api-katalog | `91_api_event_katalog.md` §91.1a | `mode`-Parameter im Phase-Aufruf-Schema dokumentieren (Werte: `execution\|exploration\|fast`) |
| kpi-and-dashboard | `60_kpi_katalog_und_architektur.md` | `mode`-Tag-Dimension fuer Aggregation; Fast-Stories als separater Cluster auswertbar |
| telemetry | `68_telemetrie_eventing_workflow_metriken.md` | Phase- und Workflow-Records bekommen `mode`-Feld (StrEnum) |
| operating-modes (formal) | `formal-spec/operating-modes/invariants.md` | Pruefen: ggf. neue Invariante `story_mode_fast_disables_story_scoped_guards_only` (Baseline bleibt aktiv) |

### In Scope — Code

- `src/agentkit/core/types.py` (oder `core/operating_modes.py`): `Mode`-StrEnum erweitern um `FAST`
- `src/agentkit/pipeline/phases/...`: Phase-Handler routen anhand `mode` auf Profil-Pfad
- `src/agentkit/governance/guard_system/...`: Story-Scoped-Guards skip-when-fast (Baseline-Guards bleiben aktiv)
- Service-API: `mode`-Feld im Phase-Aufruf-Schema akzeptieren und persistieren
- Telemetrie: jeder Phase-Record bekommt `mode`-Tag
- Pre-Merge-Rebase-Logik im Closure-Path (statt Lock im Fast-Modus)

### In Scope — Tests

- Smoke: impl-Story mit `mode=fast` durchlaeuft Setup -> Implementation -> Closure ohne Exploration, ohne QA-Schichten 2-4, ohne Story-Scoped-Guards
- Tests-gruen-Floor: Worker liefert rote Tests -> Closure-Sanity-Gate FAIL
- Negativpfad: `mode=fast` mit `concept`/`research`-Story -> Fail-Closed
- Pre-Merge-Rebase: parallele Commits anderer Stories werden korrekt rebased; bei Konflikt -> Eskalation
- Telemetrie: Fast-Records in Logs/Metrics korrekt mit `mode=fast` getaggt

### Out of Scope

- CLI-Drift-Korrektur (laeuft parallel im Sonnet-Worker — siehe Working-Worktree)
- Story-Inspector-UI fuer Mode-Anzeige (Folge-Story AG3-019)
- Performance-Optimierungen ueber den Profil-Skip hinaus
- AKreduce: Fast-Modus fuer concept/research (bewusst ausgeschlossen)

## Akzeptanzkriterien

1. FK-24 §24.X enthaelt das vollstaendige Mode-Profil Fast als kanonische Tabelle. Andere Konzepte verweisen, statt zu duplizieren (Single Source of Truth).
2. `mode=fast` ist als 3. Wert im `Mode`-StrEnum verankert; Service-API akzeptiert den Wert; Persistenz im Phase-State.
3. Eine Implementation-Story mit `mode=fast` durchlaeuft Setup -> Implementation -> Closure ohne Exploration, ohne QA-Schichten 2-4, ohne Story-Scoped-Guards, mit Tests-gruen-Pflicht-Floor.
4. Pre-Merge-Rebase auf main statt Lock; Konflikt eskaliert an User.
5. Baseline-Guards (destructive git, secrets, CCAG, self-protection) bleiben im Fast-Modus aktiv.
6. Telemetrie-Records sind mit `mode=fast` getaggt; KPIs aggregieren Fast separat.
7. Negativpfad: `mode=fast` mit `concept`/`research`-Story -> Fail-Closed.
8. Concept-Validatoren gruen, mypy strict, ruff clean, Tests gruen, Coverage haelt 85%-Schwelle.

## Definition of Done

- Konzept-Aenderungen committed (FK-24 als Owner + 9 verweisende BCs)
- Code-Aenderungen mit Tests committed
- Validatoren gruen
- Smoke-Lauf einer echten Fast-Story durchgefuehrt; Telemetrie verifiziert

## Konzept-Referenzen

- FK-24 — Owner-BC fuer Mode-Profil
- FK-22 §22.8 — Modus-Ermittlung
- FK-27 — QA-Subflow Schichten
- FK-29 — Closure-Sequenz
- FK-30, FK-31, FK-35 — Guards und Integrity
- FK-91 §91.1a — Service-API
- FK-60, FK-68 — KPI und Telemetrie
- formal-spec/operating-modes/invariants.md — Baseline-Guard-Garantie

## Guardrail-Referenzen

- **ZERO DEBT**: Mode-Profil genau einmal definiert (FK-24 §24.X), keine Duplikation in abhaengigen Konzepten
- **FAIL CLOSED**: ungueltige Mode-Story-Typ-Kombinationen (z.B. fast + concept) werden hart abgewiesen
- **SINGLE SOURCE OF TRUTH**: `Mode` als StrEnum in `core/types.py`, Profil als FK-24-Sektion, Aufruf-Parameter via FK-91 §91.1a
- **NO ERROR BYPASSING**: Tests-gruen-Floor im Fast-Modus ist nicht abschaltbar
