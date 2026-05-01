# AgentKit 3 — Agent-Onboarding

Stand: 2026-05-01

Dieses Dokument ist die zentrale Erst-Orientierung fuer jeden Agent
oder Sub-Agent, der in AgentKit 3 (AK3) arbeitet. Es ersetzt keine
fachliche Lektuere, sondern stellt die Strukturen bereit, in die diese
Lektuere einsortiert wird.

Lies vorab — und das ist Pflicht, nicht Empfehlung —:

1. `T:/codebase/claude-agentkit3/CLAUDE.md` — Projekt-Guardrails.
2. `T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md` — verbindliche
   Verzeichnis- und Modulgrenzen.
3. `T:/codebase/claude-agentkit3/guardrails/architecture-guardrails.md`
   und `testing-guardrails.md` — die `ARCH-NN`- und `TEST-NN`-Regeln,
   gegen die im Workbook geprueft wird.

Alle Aussagen unten sind mit den autoritativen Konzepten unter
`concept/` konsistent. Bei Konflikt gilt: Konzept schlaegt Onboarding,
Onboarding schlaegt eigenes Erinnerungsvermoegen.

---

## 1. Fachlichkeit von AgentKit 3

### 1.1 Was AK3 ist und wofuer es da ist

AgentKit 3 ist eine **deterministische Orchestrierungs- und
Governance-Maschine** fuer KI-gestuetzte Software-Entwicklung in
Enterprise-Kontexten. Es nimmt ein GitHub-Issue entgegen und treibt es
durch eine geschlossene 5-Phasen-Pipeline bis zum Merge oder zur
sauberen Eskalation.

AK3 ist **kein Agent**. Es ist die Maschine, die Agenten orchestriert,
qualitaetspruefend einrahmt, telemetrisch beobachtet und am Ende den
Story-Schluss deterministisch herbeifuehrt.

Zielgroesse: 1-2 Entwickler steuern eine Flotte autonomer KI-Agenten,
die ~98% der Konzeptions-, Implementierungs- und Absicherungsarbeit an
geschaeftskritischen Systemen (250k+ LOC) leisten. Der Mensch agiert
als Stratege, Impulsgeber und punktueller Controller — nicht als
klassischer Entwickler.

### 1.2 Welches Problem AK3 loest

Beobachtetes systematisches Fehlverhalten autonomer LLM-Agenten:

- **Abkuerzungen.** Agenten ueberspringen Schritte, behaupten, sie
  getan zu haben.
- **PASS by Absence.** Crasht ein Check ohne Fehlermeldung, wertet die
  Pipeline "0 Fehler" als Erfolg. Stiller Nicht-Lauf ist gefaehrlicher
  als sichtbarer Fehlschlag.
- **Evidence-Fabrication.** Plausible Artefakte (Logs, Reports), die
  keinen realen Pruefvorgang belegen.
- **Kontext-Verschmutzung.** Zu viel Kontext degradiert, zu wenig
  halluziniert. Beides ist nicht trivial steuerbar.
- **Destruktive Aktionen.** Tests loeschen statt Bug fixen,
  Force-Push, QA-Artefakte ueberschreiben.
- **Scope-Drift aus Hilfsbereitschaft.** Agent verlaesst seine
  Kernaufgabe rational, das Gesamtergebnis ist destruktiv.

AK3 adressiert diese Muster nicht durch besseres Prompting, sondern
durch deterministische Prozessgrenzen, fail-closed-Guards und eine
mehrschichtige QS, die LLMs nur als **Bewertungsfunktion** einsetzt,
nicht als frei handelnden Akteur.

### 1.3 Kernidee in einer Zeile

**Kreative Arbeit (Code, Reviews) machen LLMs. Alles andere —
Ablaufsteuerung, Qualitaets-Gates, Merge, Status-Updates — laeuft
deterministisch.**

### 1.4 Das v3-Korrektiv gegen v2

AK3 ist die Neuausrichtung nach den Strukturproblemen von v2. Zwei
Fehler werden bewusst nicht wiederholt:

- **Kein operatives JSON-Flickwerk ohne Owner.** Fachliche
  Verantwortung sitzt in Modulen, Domaenen, Artefaktklassen und
  Producer-Registries. Operative Wahrheit entsteht nicht aus losen
  Dateien, sondern aus typisierten, ownership-klaren Modellen.
- **Keine monolithische Workflow-Datei.** Workflows sind entlang
  fachlicher Einheiten geschnitten (Phasen, Komponenten), nicht als
  riesige imperative Steuerdatei.

JSON existiert weiter — aber als typisiertes Artefakt mit Envelope und
Producer-Vertrag, nicht als ungeordnetes Sammelsurium.

### 1.5 Die 5-Phasen-Pipeline

Jede Story durchlaeuft bis zu fuenf Phasen in fester Reihenfolge:

| # | Phase | Typ | Zweck |
|---|---|---|---|
| 1 | Setup | deterministisch | Kontext erheben, Worktree vorbereiten, Guards aktivieren, Worker-Prompt komponieren |
| 2 | Exploration | LLM (optional) | Entwurfsartefakt fuer explorative Implementation-Stories |
| 3 | Implementation | LLM | Worker-Sub-Agent setzt Story um, liefert Handover |
| 4 | Verify | det. + LLM | 4-Schichten-QA: structural + LLM-Bewertungen + adversarial + policy |
| 5 | Closure | deterministisch | Integrity-Gate, Merge/Cleanup, Issue-Close, Telemetrie/KPIs |

**Story-Typen routen unterschiedlich**: `implementation` und `bugfix`
durchlaufen alle 5 Phasen mit Worktree und Merge; `concept` und
`research` ueberspringen Worktree, 4-Layer-QA und Merge.

**Verify ist mehrschichtig**:
- Layer 1 — Structural: deterministische Checks, Build/Test/Artefakte.
- Layer 2 — LLM-Evaluations: drei parallele StructuredEvaluator-Aufrufe
  (QA-Bewertung, Semantic Review, Umsetzungstreue). LLMs werden hier
  als **Bewertungsfunktion** ueber deterministische Skripte
  aufgerufen, nicht als frei handelnde Agents.
- Layer 3 — Adversarial: ein Agent baut gezielt Edge-Case-Tests und
  fuehrt Multi-LLM-Sparring. Nur fuer code-produzierende Stories.
- Layer 4 — Policy Engine: deterministische Aggregation entlang
  Trust-Klassen und Stage-Registry, entscheidet PASS oder FAIL.

### 1.6 Zustandsmodell

v3 trennt:

- **`StoryContext`** — langlebige Story-Semantik (Scope, Bindings,
  Custom-Fields).
- **`PhaseStateCore` / `PhasePayload` / `PhaseMemory` /
  `RuntimeMetadata`** — Laufzeitstatus pro Phase, vier-schichtig.
- **QA-Artefakte mit Envelope + Producer-Registry** — verifizierbare
  Ergebnisse.
- **Telemetrie als `ExecutionEvent`-Stream im State-Backend**, nicht
  als unkontrollierter Datei-Faecher.

Operative Wahrheit liegt im **State-Backend** (Postgres als
Primaerziel, SQLite fuer Tests). Exportdateien wie `phase-state.json`
oder `decision.json` sind nur Materialisierungen einer kanonischen
Projektion — niemals Wahrheitsquelle.

---

## 2. Bounded-Context-Landschaft

AK3 ist in **16 Bounded Contexts** geschnitten. Quelle-of-Truth ist
`concept/technical-design/_meta/bounded-contexts.yaml` (semantisch:
`responsibility`, `owns`, `excluded`, `drift_risks`) plus
`_meta/domain-registry.yaml` (maschinenlesbar:
`bc_id -> contract_docs / member_docs`).

### 2.1 Methodische Praemissen

- BC = Sprachgrenze + Ownership + Public Surface, **nicht**
  Code-Komponente.
- Pipeline ist Framework — kein Inhaltswissen ueber Phasen.
- Verify ist Capability, kein Geschwister von Pipeline.
- BCs sind keine Silos; Querreferenzen sind erlaubt, Internals-Zugriff
  ist verboten.
- Storage-Backends sind Implementierung, **nicht** oeffentlicher
  Vertrag.

### 2.2 Die 16 BCs im Ueberblick

| BC | Verantwortung (Kurz) | Contract-Docs |
|---|---|---|
| `pipeline-framework` | Knotenkomposition + Kontrollfluss zwischen Phasen, ohne Phasen-Inhaltswissen | DK-02, FK-20, FK-36, FK-39, FK-45 |
| `exploration-and-design` | Konzeptarbeit fuer Stories ohne belastbaren Loesungsrahmen, Change-Frame, Mandate, Scope-Explosion | FK-23, FK-25 |
| `implementation-phase` | Worker-Loop, Inkrement, Handover, Worker-Health | FK-26 (+ Member: FK-49) |
| `verify-system` | Multi-Layer-QA-Capability mit Stage-Registry, Policy-Engine, Trust-Klassen, deterministischen Checks, LLM-Eval, Adversarial, Conformance, Evidence-Assembly | DK-04, DK-11, FK-27, FK-28, FK-32, FK-33, FK-34, FK-37, FK-38 (+ Member: FK-46, FK-47, FK-48) |
| `story-closure` | Closure-Sequence mit irreversiblen Seiteneffekten: Finding-Resolution, Merge, Cleanup, Postflight, VektorDB-Sync | FK-29 |
| `story-lifecycle` | Story-Identitaet, Status, Custom-Fields, Lebenszyklus, Vertragsachsen, Mode-Routing-Entscheidung | DK-10, FK-21, FK-24, FK-53, FK-54, FK-56, FK-58, FK-59 |
| `execution-planning` | Backlog-Readiness, Abhaengigkeitsgraph, Wellen, Plan-Proposal, Scheduling- und Parallelisierungspolicy | FK-70 |
| `governance-and-guards` | Hooks, Branch-/Artefakt-Schutz, Principal/Capability, CCAG, Mandatsgrenzen-Eskalation, Security/Identity, Rollen, Integrity-Gate, Eskalationsmechanik | DK-03, DK-09, FK-22, FK-30, FK-31, FK-35, FK-42, FK-55 |
| `artifacts` | Artefakt-Referenzen, Envelope, Producer-Registry, Artefakt-Klassen | FK-71 |
| `telemetry-and-events` | ExecutionEvent-Stream, Event-Schemata, Phase-State-Projektionen, QA-Read-Models | DK-05, FK-68, FK-69 |
| `requirements-and-scope-coverage` | must_cover, Evidence, Scope-Mapping, ARE-Dock-Points, Coverage-Verdict (Vollstaendigkeit, **nicht** Qualitaet) | DK-06, FK-40 |
| `prompt-runtime` | Prompt-Bundle-Komposition, Materialisierung, Audit-Hash, Template-Mechanik, Drift-Vermeidung | FK-44 |
| `agent-skills` | Skill-Definition, Skill-Variants, Skill-Profile, Skill-Lifecycle, Skill-Quality | DK-01, DK-12, FK-43 |
| `kpi-and-dashboard` | KPI-Katalog, Erhebung, Aggregation/Rollups, Fact-Tabellen, Dashboard-Sichten | DK-13, FK-60, FK-61, FK-62, FK-63 |
| `failure-corpus` | Fehlmuster-Sammlung, Pattern-Promotion, Check-Factory, Lernschleife in deterministische Guards | DK-07, FK-41 |
| `installation-and-bootstrap` | Projektregistrierung, Installer-Checkpoints, Hook/Wrapper-Bindung, Upgrade/Migration | DK-08, FK-50, FK-51 |

### 2.3 Cross-Cutting (kein BC)

Foundation-/Adapter-/Referenz-Docs sind explizit **kein BC**. Sie
tragen `cross_cutting: true` im Frontmatter und sind aus L17/L18 (BC-
Pflicht und Cross-BC-Refs) ausgenommen.

Aktuell cross-cutting: DK-00, FK-00, 01, 02, 03, 04 (Operations), 05
(Integration-Stab), 06 (Truth-Boundary), 07 (Komponentenarchitektur),
10 (Runtime/Speicher), 11 (LLM-Provider), 12 (GitHub-Adapter), 13
(VektorDB-Adapter), 15 (Security), 17 (Datenmodell), 18 (Postgres-
Mapping), 52 (war Betrieb — siehe FK-04), 90-93 (Referenzkataloge).

### 2.4 Zusammenspiel + Ownership-Disjunktheit

BCs ueberschneiden sich **fachlich** an vielen Beruehrungspunkten —
Ownership ist trotzdem strikt diskunkt. Beispiele:

- **Verify-System** orchestriert die QA-Pipeline; **Pipeline-
  Framework** stellt das Phasenmodell und die Engine. Verify
  *deferiert auf* Pipeline (Scope `feedback-loop`,
  `workflow-engine`) — schreibt aber keine FlowExecutions.
- **Story-Closure** ist nicht Teil von **Verify-System**: Closure
  beginnt **nach** Verify PASS, hat eigene Substates,
  Finding-Resolution-Gate und Postflight. Verify deferiert auf
  Closure (Scope `closure-sequence`).
- **Governance-and-Guards** owns die Eskalations-**Mechanik**.
  **Exploration-and-Design** owns die Mandats- und
  Scope-Explosion-**Erkennung**. Beide arbeiten zusammen, der Schnitt
  ist scharf: Erkennung != Mechanik.
- **Requirements-and-Scope-Coverage** liefert Coverage-Verdict
  (vollstaendig?). Stage-Registry und Policy-Engine sind explizit
  ausgeschlossen — die liegen in `verify-system`. Pro Begriff ein
  Definitions-Owner.
- **Artifacts** owns Envelope-Schema und Producer-Registry; jede
  QA-erzeugende Komponente in `verify-system` und `story-closure`
  deferiert auf das Envelope-Vertrag.
- **Prompt-Runtime** owns Bundle-Komposition und Audit-Hash; jeder
  prompt-konsumierende BC (Implementation, Verify, Exploration,
  Agent-Skills) deferiert.

Die Ownership-Disjunktheit wird **maschinell** gehalten:

- L5 (Authority-Disjunktheit) verbietet, dass zwei Docs dieselbe
  `authority_over.scope` halten.
- L18 (Cross-Domain-Refs) verbietet, dass ein BC auf eine **Internal-
  Surface** eines anderen BC defertiert — nur Contract-Surface ist
  ansprechbar.
- L19 (Glossar-Integritaet) verbietet, dass ein Begriff in zwei BCs
  gleichzeitig exportiert ist.

### 2.5 BC-Owner-Rolle

Pro BC genau ein **BC-Owner** (synonym "Domain-Owner"):
- pflegt seine Contract- und Member-Docs allein,
- ist Autor des `glossary:`-Blocks im Contract-Doc,
- ist Verantwortlicher fuer das Einhalten der `excluded`-Liste seines
  BC,
- meldet Drift in fremden BCs an deren Owner, fasst sie aber nie
  selbst an.

Sub-Agenten fuer Glossar-/Doc-Arbeit bekommen genau **eine** `bc_id`
mit. Siehe `prompts/bc-glossary-briefing.md`.

---

## 3. Dreistufigkeit: Prosa -> Formal -> Code

AK3 zwingt jede Aussage in eine von drei Schichten und prueft alle
drei gegeneinander. Das ist die zentrale Drift-Verteidigung.

### 3.1 Drei Schichten, drei Aufgaben

| Schicht | Ort | Form | Aufgabe |
|---|---|---|---|
| **Prosa-Konzept** | `concept/domain-design/`, `concept/technical-design/` | Markdown mit Frontmatter | Menschenlesbare Vertraege fuer Domain (`DK-NN`) und Technik (`FK-NN`). Authoritativ, normativ, fail-closed gegen Code geprueft. |
| **Formal-Layer** | `concept/formal-spec/<context>/` | Markdown-only mit YAML-Bloecken (`<!-- FORMAL-SPEC:BEGIN/END -->`) | Maschinenpruefbare Spezifikation: `entities`, `state-machine`, `commands`, `events`, `invariants`, `scenarios`. Pro `<context>` ein Folder. |
| **Code** | `src/agentkit/`, `tools/` | Python 3.11+ | Implementation. Liest, validiert oder bricht gegen die formale Schicht. |

### 3.2 Drei Layer im Konzept-Index

Das ist auch die Filterachse, mit der die MCP-Concept-Suche arbeitet:

- `domain` — `DK-NN`, fachliche Sicht (Rollen, Pipeline-Domaene,
  Governance-Idee, KPIs).
- `technical` — `FK-NN`, Feinkonzept (Architektur, State-Modell,
  Pipeline-Engine, Schemas).
- `formal` — `formal.<context>.<x>`, maschinenpruefbare YAML-Specs.

Aktuell: 68 domain-chunks, 671 technical-chunks, 348 formal-chunks (=
1087 Total).

### 3.3 Validierungsmechanismen

Vier Validatoren, alle ERROR-only, alle determistisch, alle in
`scripts/ci/`:

#### 3.3.1 `check_concept_frontmatter.py` — 21 Lints (`L1`-`L21`)

Pflicht fuer jede Konzeptaenderung. Wichtigste Lints:

- **L1** Index `<->` Disk: jede Datei in `00_index.md` referenziert
  und vice versa.
- **L2** `concept_id`-Pattern (`^FK-\d{2}$` oder `^DK-\d{2}$`) und
  Eindeutigkeit ueber Layer hinweg.
- **L3** `parent_concept_id` und `defers_to`-Targets muessen
  existieren.
- **L4** `supersedes` `<->` `superseded_by` Reciprocity (nur fuer
  vollstaendige Supersession).
- **L5** `authority_over.scope` darf nicht von zwei Docs gehalten
  werden (ausser via Voll-Supersession verbunden).
- **L7** Inline `FK-/DK-`-Refs im Body muessen aufloesen.
- **L8** Tag-Korpus: jeder Tag muss in `_meta/tag-corpus.txt` stehen.
- **L9** Authority-Graph (`parent_concept_id` + `defers_to`) ist
  zyklenfrei.
- **L10** `superseded_by`-Ring-Guard.
- **L11** `module` muss in `_meta/module-registry.yaml` stehen.
- **L14** Stem-Felder (alle Pflichtfelder) vorhanden.
- **L15** `formal_refs` `<->` Body-`<!-- PROSE-FORMAL: ... -->`-
  Anchors.
- **L16** Authority-Typkompatibilitaet (kein `defers_to` auf Index/
  Anhang).
- **L17** BC-Pflicht: jedes Doc traegt `domain` oder
  `cross_cutting: true` (mutually exclusive).
- **L18** Cross-Domain-Refs: ein BC darf nur auf **Contract-Surface**
  eines fremden BC deferieren, nie auf Internal.
- **L19** Glossar-Integritaet: Glossar nur in Contract-Docs;
  `see_also.term` muss als exportierter Begriff im Ziel-BC
  existieren; `internal_terms.reason` Pflicht.
- **L20** Implicit-Leakage: ein Doc darf keine BC-Vokabeln eines
  fremden BC ohne `defers_to` verwenden.
- **L21** Top-Heading-Konsistenz: erste H1 muss `# {N} -- {title}`
  mit Em-Dash sein, `{N}` matcht den Dateinamen-Praefix.

Aufruf: `python scripts/ci/check_concept_frontmatter.py`. Erfolgsbild:
`OK: 79 docs, all lints passed. Bounded-context layer: active.`

#### 3.3.2 `compile_formal_specs.py` — Formal-Compiler

Kompiliert `concept/formal-spec/**/*.md`, validiert IDs,
Cross-References, Scenarios, Drift gegen Prosa. Aktuell: **170
documents, 1230 ids, 1623 references, 104 scenarios, 409 prose links**.

Aufruf: `python scripts/ci/compile_formal_specs.py`.

#### 3.3.3 `check_concept_code_contracts.py` — Truth-Boundary-Checker

Liest `formal.truth-boundary-checker.invariants` und scannt
`src/agentkit/` per AST gegen JSON-als-Wahrheit-Regressionen. Codes:

- **TB001** `json.load`/`json.loads` in geschuetzten Modulen.
- **TB002** Import von verbotenen Export-Modulen
  (`agentkit.pipeline.state`, `agentkit.qa.artifacts`).
- **TB003** Import oder Aufruf verbotener Loader-Symbole
  (`load_phase_state`, `load_story_context`, ...).
- **TB004**/**TB005** Lesen oder Erwaehnen geschuetzter Story-Export-
  Dateinamen (`context.json`, `decision.json`, `phase-state.json` ...)
  in geschuetzten Modulen.

Geschuetzte Module: `agentkit.governance`, `agentkit.pipeline`,
`agentkit.qa.structural`. Ausnahmen: `agentkit.cli`,
`agentkit.migrations`, `agentkit.utils.io`, `tests`.

#### 3.3.4 `check_architecture_conformance.py` — AC-Lint

Liest `formal.architecture-conformance.{entities, invariants}` und
prueft `src/`-Importgraph. Codes:

- **AC001** `dependency_rules` — verbotene Import-Richtung (z.B.
  `story` darf nicht auf `governance.hookruntime` importieren).
- **AC002** `acyclic_group_sets` — Komponentengruppen muessen
  zyklenfrei sein. Aktiv: `application_surface`, `runtime_core`,
  `governance_core`.
- **AC003** `mutation_surface_rules` — bestimmte Writer-Symbole
  (`save_flow_execution`, `save_phase_state`, `append_execution_event`
  etc.) duerfen nur aus erlaubten Modulen importiert werden.
- **AC004** `read_surface_rules` — bestimmte Reader-Symbole nur aus
  expliziten Repositories.

Aktuell deklariert: 18 `component_groups` (Story, Dashboard,
Control-Plane, ProjectEdge, HookRuntime, StateBackend-Drivers,
StoryContextManager, PipelineEngine, GuardSystem, GovernanceObserver,
ConformanceService, StageRegistry, FailureCorpus, PromptComposer,
LlmEvaluator, TelemetryService, PhaseStateStore, Installer).

Bloodgroups (`A` = Fachkomponente, `R` = Adapter, `T` = Treiber) sind
deklariert; ein Bloodgroup-Enforcement-Lint (A darf T nicht direkt
importieren) ist offen — siehe Workbook GAP-10.

### 3.4 Reciprocity Prosa `<->` Formal

Jedes FK/DK-Doc, das auf eine formale Spec verweist
(`formal_refs: [formal.x.y, ...]`), muss:

- pro `formal_refs`-Eintrag genau einen Body-Anker
  `<!-- PROSE-FORMAL: formal.x.y -->` tragen (L15).
- in der formalen Spec-Datei `prose_refs:` als Pfad zurueck-
  referenziert sein.

Bei `prose_anchor_policy: strict` (Default fuer alle modernen Docs)
ist L15 fail-closed.

### 3.5 BC-Projektion auf alle drei Layer

Seit dem BC-Refactor sind alle drei Layer per `domain` und
`cross_cutting` gefiltert durchsuchbar:

- **Domain/Technical** projizieren via `_meta/domain-registry.yaml`.
- **Formal** projiziert via Folder: alle Specs in
  `formal-spec/<folder>/` erben die BC ihrer prose-refs (Mehrheits-
  abstimmung; Tied/All-Foundation -> `cross_cutting`). Beispiel:
  `formal.deterministic-checks.*` -> `verify-system`.

Aktuell: 197/207 Formal-Docs eindeutig einem BC zugeordnet, 11
cross-cutting (architecture-conformance, truth-boundary-checker), 7
unassigned (`00_meta/`-Docs ohne `prose_refs`).

### 3.6 Pre-Commit-Hook

`.githooks/pre-commit` ist aktiviert per `git config core.hookspath
.githooks` und laeuft automatisch bei jedem `git commit`, der
`concept/*` oder Validator-Skripte aendert. Es ruft
`check_concept_frontmatter.py` und `compile_formal_specs.py`. Bei
Fehler bricht der Commit.

---

## 4. Zentrale technische Design-Entscheidungen

### 4.1 Zentraler Betrieb statt verteiltem Pipeline-Knoten

AK3 wird als **zentrale, mandantenfaehige Instanz** betrieben, nicht
als fest installierter Pipeline-Knoten pro Projekt. Eine AK3-Instanz
betreibt mehrere Projekte parallel; alle Flows sind **tenant-scoped
ueber `project_key`**.

Konsequenz: State-Backend, Telemetrie, Control-Plane-API,
Edge-Bundles und Guard-Schnitt sind alle durchgaengig
project_key-gefiltert. Eine zentrale Postgres-Instanz wird **nie**
ungefiltert ueber alle Projekte ausgewertet; jede Session arbeitet
gegen genau einen `project_key`.

### 4.2 REST-API mit Thin Client im Projekt

Die normative Grenze zwischen zentraler AK3-Instanz und Projekt ist
die **HTTPS-Control-Plane unter `/v1/...`**. Alle mutierenden
Runtime-Operationen laufen ueber sie.

Aktuelle Endpunkte (in `src/agentkit/control_plane/http.py`):

- `POST /v1/story-runs/{run_id}/phases/{phase}/{start|complete|fail}`
- `POST /v1/story-runs/{run_id}/closure/complete`
- `POST /v1/project-edge/sync`
- `GET  /v1/project-edge/operations/{op_id}`
- `POST /v1/telemetry/events`
- `GET  /v1/stories`, `GET /v1/stories/{story_id}`
- `GET  /v1/dashboard/board`, `GET /v1/dashboard/story-metrics`

Im Projekt liegt nur ein **`ProjectEdgeClient`** plus
`LocalEdgePublisher` plus `ProjectEdgeResolver` als duenne Edge-
Schicht. Hooks lesen einen lokal materialisierten **Edge-Bundle-
Stand** (`current.json`) statt pro Tool-Call gegen DB oder API zu
roundtrippen. Bounded Re-Sync laeuft ueber `sync.lock`,
`op_id`-basierte Reconciliation sichert Idempotenz.

Querschnittsvertraege fuer alle externen APIs: `op_id`-Idempotenz,
`correlation_id`-Propagation, standardisierter Fehlervertrag,
`/v1`-Versionierung. Inkompatible Aenderungen erzeugen `/v2`, keine
stille Mutation.

### 4.3 Symlinks fuer Skill-Bindung

Skills (`create-userstory-core/`, `execute-userstory-core/`,
`semantic-review/`, ...) liegen **systemweit** in versionierten
AgentKit-Bundles (z.B. `C:\ProgramData\AgentKit\bundles\<version>\`).

Im Projekt unter `.claude/skills/` liegen **nur Symlinks** auf die
ausgewaehlten Bundle-Verzeichnisse. Das Projekt enthaelt damit einen
Claude-Code-kompatiblen Bindungspunkt, **nicht** die Skill-Quelle.

Konsequenz fuer Closure: Zielprojekte sind nicht "AgentKit-Versions-
geprueft"; ein Versions-Upgrade aktualisiert systemweit das Bundle und
re-verlinkt im Projekt — ohne Inhalt zu kopieren.

Platzhalter-Substitution (`{{gh_owner}}`, `{{gh_repo}}`,
`{{project_prefix}}`) erfolgt zur Bind-Zeit, nicht zur Skill-Laufzeit.

### 4.4 Multi-Repo-Stories als First-Class

`StoryContext` traegt `participating_repos` plus `primary_repo`. Der
Evidence-Assembler operiert auf einem `RepoContext`-Set, nicht auf
einer einzelnen `repo_root`. Worktrees werden pro Repo angelegt.

### 4.5 Operating-Modes — strikte Trennung

Zwei Betriebsmodi, niemals gemischt:

- `ai_augmented` — freier Modus ohne Pipeline-Pflichten. Mensch
  arbeitet, AK3 unterstuetzt punktuell.
- `story_execution` — gebundener Story-Workflow mit Guards, QA-Gates
  und Capability-Freeze.

`binding_invalid` ist **kein dritter Modus**, sondern ein blockierender
Fehlerzustand bei gebrochener Story-Bindung. Stilles Zurueckfallen auf
`ai_augmented` bei kaputtem Lock ist fail-closed verboten.

### 4.6 React-Frontend mit xyflow

Das eigentliche Story-Cockpit (Zielbild) ist eine **eigenstaendige
professionelle React-Web-Anwendung**, nicht das aktuelle Single-Page-
Dashboard mit Chart.js.

- Stack: React, modulare Komponentenbibliothek, **xyflow** fuer den
  Live-Story-Graph.
- Pflichtsichten der spaeteren Control-Plane:
  `Dependency-Graph` (xyflow), `Ready Queue`, typisierte Blocker,
  `critical path`, `execution waves` aus FK-70.
- Story-Detailseiten vereinen Status, Protokolle, Telemetrie,
  QA-Artefakte und Closure-Metriken auf einer Seite.
- Tenant-scoped pro `project_key`; liest **nur** ueber die
  offiziellen `/v1/`-Endpunkte.

GitHub Projects ist hoechstens noch ein externer Adapter oder
Synchronisationsziel, **nicht** die fachlich bevorzugte UI.

Status heute: API-Schicht ist halb gebaut (Story- und
Dashboard-Endpoints da), die React-App selbst noch nicht im Repo.
Code unter `src/agentkit/dashboard/` ist die Vorstufe (Python +
Chart.js Single-Page).

### 4.7 Worker-Prompts mit Compaction-Resilience

Sub-Agent-Spawns sind durch den **Compaction-Resilience-Mechanismus**
(FK-36) abgesichert:

- `resume-capsule` (max 8000 Zeichen) wird zur Compose-Time parallel
  zum `prompt_file` erzeugt.
- `spawn-spec--{spawn_key}.json` traegt alle Metadaten fuer die
  `SubagentStart`-Hook-Bindung.
- Ein PreToolUse-Hook injiziert die Capsule per `additionalContext`,
  wenn Compaction stattfand.
- Determinitisch (kein LLM), fail-open, raeumt eigenen Zustand auf.

### 4.8 QA-Artefaktschutz via Lock-Record

Bei Story-Start setzt das Setup-Skript einen zentralen
`qa_artifact_write_lock`-Record im State-Backend. Solange er aktiv
ist, blockiert ein CCAG-Hook **Sub-Agent**-Schreibzugriffe auf
QA-Pfade. Hauptagent und Pipeline-Skripte bleiben zugriffsberechtigt.

PID-Pruefung primaer (`os.kill(pid, 0)`), TTL als Fallback. Cleanup
bei Closure.

### 4.9 Truth-Boundary

QA-Export-Dateien (`structural.json`, `decision.json`,
`phase-state.json`, `closure.json`, ...) sind **niemals**
operative Wahrheit. Sie sind Materialisierung einer kanonischen
Projektion aus dem State-Backend. Geschuetzte Runtime-Module
(`agentkit.governance`, `.pipeline`, `.qa.structural`) duerfen sie
**nicht lesen** (TB001-TB005, fail-closed im AC-Lint).

### 4.10 Stage-Registry und Trust-Klassen

Verify-Stages sind in einem **typisierten Stage-Registry** verankert
(FK-33, BC `verify-system`). Jede Stage hat:

- `producer` (welcher Code/Agent darf das Artefakt schreiben),
- `trust_class` (A = System-Check darf blockieren; C = Worker-Aussage
  darf nicht blockieren),
- `blocking` (pruefblockierend oder rein advisory).

Die Policy-Engine (Layer 4) aggregiert deterministisch entlang dieser
Klassen.

### 4.11 Bounded-Context-Refactor und Renumbering

Konzepte sind in 16 BCs geschnitten; FK-Docs sind in Bloecke
nummeriert (Foundation in 00-09, BC-Inhalte 20-63, BC-Bloecke 68-71,
Referenzkataloge 90-93). Acht Docs wurden 2026-04-29 umgehaengt
(z.B. FK-65 -> FK-07, FK-67 -> FK-71). Externe Referenzen ziehen
mit (Lints fail-closed bei Ist-Soll-Drift).

---

## 5. Externe Systeme

AK3 integriert vier externe Systeme als **duenne Adapter**. Jeder
liegt unter `src/agentkit/integrations/<name>/`. Geschaeftslogik
gehoert nicht in den Adapter, sondern in die fachliche Komponente,
die ihn nutzt.

### 5.1 GitHub

Rolle: **Tracker- und Repo-Integration**. Issues sind
Story-Eingaenge, Project-Boards spiegeln (heute noch) den Story-
Lifecycle, Branches und PRs sind das Merge-Target.

Adapter: `src/agentkit/integrations/github/`. Verantwortlich fuer:
- Issue-Lesen und -Schliessen,
- Project-Field-Lese-/Schreibzugriffe,
- Branch-/Worktree-Operationen,
- Merge-Policy (fast-forward-only Default, Fallback `--no-ff`),
- Label-Management.

Konzept: FK-12 (cross-cutting Adapter-Doc) und DK-10
(`story-lifecycle`).

**Zielzustand**: GitHub ist nach Setup **kein Primaerwahrheitstraeger
mehr**. Die operative Wahrheit waehrend des Runs liegt im AK3-State-
Backend; GitHub spiegelt nur. Heute ist GitHub fachlich noch zu nah
an der Story-Verwaltung — das ist offener Gap (M2 im Fahrplan).

Auth: lokale `gh`-CLI bzw. PAT in der Projekt-Konfiguration.

### 5.2 ARE (Agent Requirements Engine)

Rolle: **externer Anforderungs-Engine** fuer regulatorisch
anspruchsvolle Projekte. Verwaltet typisierte must_cover-Anforderungen
und liefert Coverage-Verdicts.

Adapter: `src/agentkit/integrations/are/`. Konzept: DK-06, FK-40.

Funktionsweise:
- Bei Installation: Repos und GitHub-Project-Module werden auf
  **ARE-Scopes** gemappt.
- Bei Story-Erstellung: betroffene Repos leiten automatisch passende
  Scopes ab; Anforderungen werden als `must_cover`-Pflichten in den
  Story-Kontext injiziert.
- In Verify Layer 1: ARE-Gate prueft Evidence vs. must_cover.

ARE erzwingt **Vollstaendigkeit**, nicht Qualitaet. Stage-Registry und
Policy-Engine bleiben in `verify-system`.

Auth: ARE-API-Token in der Projekt-Konfiguration.

### 5.3 Multi-LLM-Hub

Rolle: **Browser-Pool-Abstraktion** fuer LLM-Aufrufe. AK3 nutzt
mehrere LLM-Anbieter (Claude/Anthropic, ChatGPT/OpenAI, Gemini/
Google) ueber Browser-Sessions, nicht ueber API-Keys mit
Token-Verbrauch.

Pattern: Pool-Adapter haelt N Browser-Sessions pro Anbieter, Skripte
acquire/release Sessions ueber MCP. Konzept: FK-11.

Tooling: Multi-LLM-Hub als separater MCP-Server (siehe `.mcp.json`
des Zielprojekts; im Onboarding-Repo selbst nicht aktiviert, aber
verfuegbar als `mcp__multi-llm-hub__llm_*`-Tools).

Wichtige Calls aus Sicht der Pipeline:
- `llm_acquire` — Session anfordern.
- `llm_send` — Prompt schicken.
- `llm_resume` — bei Session-Reuse.
- `llm_release` — Session zurueckgeben.
- `llm_pool_status` / `llm_health` — Beobachtbarkeit.

Eingesetzt in:
- Verify Layer 2 (3 parallele StructuredEvaluator-Aufrufe).
- Conformance-Service (4 Doc-Fidelity-Ebenen).
- Adversarial-Sparring (Multi-LLM-Debatte).
- Exploration (Drift-/Konzept-Prufung).

Adapter: `src/agentkit/integrations/llm_pools/`. Auth: keine — die
Browser-Sessions tragen ihre Auth selbst.

### 5.4 Weaviate (VektorDB)

Rolle: **semantischer Retrieval-Layer** fuer Konzept-Korpus,
Story-Knowledge-Base und Glossar.

Adapter: `src/agentkit/integrations/vectordb/`. Konzept: FK-13.

Drei Verwendungen:

1. **Konzept-Korpus** (`Ak3ConceptChunk`-Collection): 1087 Chunks
   ueber alle drei Konzept-Layer (`domain`, `technical`, `formal`)
   mit BC-Projektion, Reference-Graph-Filtern und Migration-Tracking.
   Tooling: `tools/concept_ingester/` (Discovery, Ingester, Schema)
   und `tools/concept_mcp/` (FastMCP-Server). Hybrid-Suche (BM25 +
   Multilingual-Embeddings) ueber MCP-Tool `concept_search`.
2. **Glossar** (`Ak3GlossaryTerm`-Collection): pro BC exportierte und
   interne Begriffe. Quelle: `glossary:`-Block in der Frontmatter
   eines Contract-Docs. Tooling identisch. Suche via
   `concept_glossary_search`.
3. **Story-Knowledge-Base** (Zielprojekt-bezogen): semantischer
   Abgleich neuer Stories gegen historisches Story-Wissen, plus
   VektorDB-Sync nach erfolgreichem Closure (FK-29).

Default-Setup: lokale Weaviate-Instanz auf `127.0.0.1:9903` (HTTP) und
`50051` (gRPC); Embedding-Modell `text2vec-transformers`,
multilingual, masked_mean-Pooling.

### 5.5 PostgreSQL als State-Backend

Nicht "extern" im engen Sinn (es ist Infrastruktur-Pflicht), aber zur
Vollstaendigkeit:

- Primaerziel fuer State-Backend, Telemetrie, Analytics-Schema.
- SQLite ist Fallback fuer Tests und einfache lokale Setups
  (`AGENTKIT_STATE_BACKEND=sqlite`, `AGENTKIT_ALLOW_SQLITE=1`).
- Kein A-Code importiert `agentkit.state_backend.store` als
  generische Fassade — Komponenten haben eigene Repository-Vertraege
  (FK-07 §7.x; siehe Workbook A4).

Local-Dev-DSN typisch:
`postgresql://agentkit:agentkit@host.docker.internal:55432/<db>`
(Postgres laeuft als Docker-Container).

---

## 6. Projektstruktur

Quelle-of-Truth: `T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md`.
Lies das Dokument einmal vollstaendig, bevor du Datei-Operationen
machst. Hier nur die Schnellsicht.

### 6.1 Architekturprinzip: dreifache Entkopplung

| Form | Beschreibung |
|---|---|
| Development-Codebase (dieses Repo) | Python-Paket mit src-Layout, Tests, CI |
| Installiert im Zielprojekt | AK3 deployt `.agentkit/`, Prompts, Skills, Hooks, Config dorthin |
| Test-Sandboxes | `tests/integration/target_project_sim/` — simulierte Zielprojekte |

### 6.2 Root-Layout (verbindlich)

```text
T:/codebase/claude-agentkit3/
  src/agentkit/         # einziger Ort fuer Produktionscode
  tests/                # 4 Ebenen: unit, integration, contract, e2e
  stories/              # Story-Artefakte zur Laufzeit
  concept/              # autoritative Fachkonzepte (Markdown only)
    domain-design/      # DK-NN Prosa
    technical-design/   # FK-NN Prosa + _meta/-Registries
    formal-spec/        # formal.<context>.<x> Markdown mit YAML-Bloecken
  guardrails/           # ARCH-NN, TEST-NN — architektonische Leitplanken
  prompts/              # Statische Agent-Briefings (dieses Doc, BC-Glossar-Briefing)
  scripts/              # CI/Dev/Release/Python Helfer
    ci/                 # check_concept_frontmatter.py, compile_formal_specs.py,
                        # check_concept_code_contracts.py,
                        # check_architecture_conformance.py
  tools/                # Architektur-/Build-Tooling (kein Produktivcode)
    concept_compiler/   # Formal-Spec-Compiler/Linter/Scenario-Runner
    concept_ingester/   # Discovery, Ingester, Schema fuer Weaviate
    concept_mcp/        # FastMCP-Server fuer Concept-Suche
    diagram_export/     # Diagramm-Export-Helper
  docs/                 # Publizierte Entwicklerdoku (ADRs, Guides)
  examples/             # Demo-Zielprojekte
  var/                  # GITIGNORED — temp, logs, sandboxes
  Jenkinsfile           # CI-Pipeline-Definition (siehe §7.5)
  CLAUDE.md             # Projekt-Guardrails (Pflichtlektuere)
  PROJECT_STRUCTURE.md  # Diese Struktur, normativ
  pyproject.toml        # Paket, pytest/mypy/ruff/Coverage
```

### 6.3 Verboten auf Root-Ebene

- Kein `.agentkit/` im Root (Zielprojekt-Struktur darf nicht im
  Repo-Root gespiegelt werden).
- Keine losen Python-Dateien im Root.
- Keine neuen Top-Level-Verzeichnisse ohne expliziten User-Consent.

### 6.4 src/agentkit — Strukturprinzip

Namespaces folgen dem **fachlichen Komponentenmodell**, nicht
technischen Querschnitten. Ein Top-Level-Namespace = genau eine
Fachkomponente.

Sollzustand (Auszug):

```text
src/agentkit/
  cli/                       # Entrypoints, Command-Routing
  config/                    # Pydantic v2 Models, Loader
  pipeline_engine/
    setup_phase/
    exploration_phase/
    implementation_phase/
    verify_phase/
    closure_phase/
  story_context_manager/
  guard_system/
  artifact_manager/
  worktree_manager/
  prompt_composer/
  llm_evaluator/
  conformance_service/
  stage_registry/
  governance_observer/
  failure_corpus/
  ccag_permission_runtime/
  kpi_analytics_engine/
  telemetry_service/
  phase_state_store/
  installer/
  control_plane/             # HTTPS-API
  story/                     # Read-Models fuer /v1/stories
  dashboard/                 # Vorstufen-UI (Chart.js)
  projectedge/               # ProjectEdgeClient + LocalEdgePublisher
  process/                   # Querschnittliche Prozesssprache
  integrations/              # Adapter: github, are, llm_pools, vectordb, mcp
  resources/                 # Templates, Prompts, Schemas — KEIN Python
    target_project/          # Was ins Zielprojekt deployt wird
      .agentkit/
      .claude/
      templates/
    internal/                # Interne Prompts/Schemas (nicht deployt)
  shared/                    # Kleine fachneutrale Hilfen
  state_backend/             # Postgres/SQLite-Treiber (T-Code)
```

Der **heutige Baum** ist ein Migrationszustand: einige Zielnamespaces
existieren noch nicht (z.B. `conformance_service/`, `stage_registry/`,
`governance_observer/`, `kpi_analytics_engine/`). Heutige
Sammelcontainer wie `qa/`, `governance/`, `pipeline/` werden
schrittweise in fachliche Komponenten ueberfuehrt — siehe Workbook
A4-A10 und Deletability-Tabelle in
`var/ak3-komponentenarchitektur-workbook/02-gap-workbook.md`.

### 6.5 tests — vier Ebenen

| Ebene | Verzeichnis | Schnelligkeit | CI |
|---|---|---|---|
| Unit | `tests/unit/` (spiegelt `src/agentkit/`) | Sekunden | jeder PR |
| Integration | `tests/integration/` szenariobasiert | Minuten | jeder PR |
| Contract | `tests/contract/` Schemas, Prompt-Sentinels, Manifests | Sekunden | jeder PR |
| E2E | `tests/e2e/` Live-Systeme | Min-Stunden | manuell/nightly, opt-in |

Coverage-Mindestgrenze: **85%**. Eine Aenderung, die unter die
Schwelle zieht, ist blockierend.

E2E ist **immer opt-in**, Marker `@pytest.mark.e2e`. Nie in
Standard-CI. Brauchen echte Credentials.

Golden Files unter `tests/golden/` sind versioniert; Update braucht
bewussten Review. Fixtures unter `tests/fixtures/` sind statisch —
generierte Dateien gehoeren in `var/` oder `tmp_path`.

### 6.6 resources — Single Source of Truth fuer Deploy

```text
resources/
  target_project/    # Genau eine Kopie. Aenderung -> Golden-Files updaten.
    .agentkit/
    .claude/
    templates/
  internal/          # Interne Prompts/Schemas, NICHT deployt
```

Keine Kopien in `tests/fixtures/`. Tests lesen aus `resources/` oder
vergleichen gegen `tests/golden/`.

### 6.7 var — ephemer und gitignored

```text
var/
  tmp/               # Temp-Files, Merge-Files, Zwischenergebnisse
  logs/              # Lokale Laufzeit-Logs
  sandboxes/         # Test-Sandboxes, simulierte Zielprojekte
```

Alles in `var/` ist wegwerfbar. Kein Agent darf `var/` als Source of
Truth verwenden. Lokale Arbeitsdokumente (`gap-analyse-*.md`,
`umsetzungsfahrplan-*.md`, Workbook) liegen ebenfalls in `var/` und
sind nicht eingecheckt.

### 6.8 concept — Konzept-Korpus

```text
concept/
  domain-design/         # DK-NN Markdown
  technical-design/      # FK-NN Markdown + _meta/
    _meta/
      bounded-contexts.yaml   # semantische BC-Quelle (responsibility, owns, excluded, drift_risks)
      domain-registry.yaml    # bc_id -> contract_docs / member_docs
      module-registry.yaml    # erlaubte module-Werte fuer L11
      policy-registry.yaml    # erlaubte applies_policies-Werte
      tag-corpus.txt          # erlaubte Tags fuer L8
  formal-spec/           # formal.<context>.<x> mit YAML-Bloecken
```

Aenderungen an `concept/*` sind nur mit explizitem User-Consent
zulaessig (CLAUDE.md). Pre-Commit-Hook prueft fail-closed.

### 6.9 Schnellnavigation fuer Agents

| Ziel | Wo |
|---|---|
| **Neuen Produktionscode schreiben** | `src/agentkit/<passendes-modul>/`. Neuer Namespace nur mit fachlicher Begruendung. |
| **Neuen Test schreiben** | `tests/<unit|integration|contract|e2e>/...` — richtige Ebene waehlen. |
| **Deploy-Asset aendern** | `src/agentkit/resources/target_project/` aendern, dann `tests/golden/` aktualisieren. |
| **Temporaere Dateien erzeugen** | `var/` oder `tmp_path` (in Tests). NIE in `src/` oder `tests/fixtures/`. |
| **Adapter hinzufuegen** | `src/agentkit/integrations/<name>/` als duenner Adapter, Geschaeftslogik im fachlichen Modul. |
| **Konzept aendern** | `concept/<layer>/...` — nur mit User-Consent. Pre-Commit prueft. |
| **Glossar pflegen** | `glossary:`-Block im Frontmatter des Contract-Docs deines BC. Brief: `prompts/bc-glossary-briefing.md`. |
| **Architektur-/Test-Guardrails konsultieren** | `guardrails/architecture-guardrails.md`, `guardrails/testing-guardrails.md`. |
| **CI-Validatoren** | `scripts/ci/`. |
| **Concept-Tooling** | `tools/concept_compiler/`, `tools/concept_ingester/`, `tools/concept_mcp/`. |

---

## 7. Best Practices und Tooling

### 7.1 Concept-Suche statt grep

Fuer **jede** Frage zur Konzeptlage: nutze die MCP-Concept-Tools statt
`grep` oder Datei-Walk auf `concept/*.md`. Der Index ist hybrid (BM25
+ multilingual Embeddings), BC-projiziert, layer-filterbar und gibt
dir mit jedem Treffer die volle Frontmatter-Sicht.

**Tools (MCP-Server `agentkit3-concepts`):**

| Tool | Zweck |
|---|---|
| `concept_search(query, layer?, domain?, surface?, cross_cutting?, where?, limit, hybrid_alpha, include_content)` | Hybrid-Volltextsuche ueber alle Chunks. Standardeintrag. |
| `concept_glossary_search(query, domain?, term_kind?, limit, hybrid_alpha)` | Suche nur in der Glossar-Collection. Liefert Term + Definition + Source-Doc. |
| `concept_get(doc_id?, rel_path?, chunk_id?, limit)` | Volldokument oder Einzelchunk holen. Read-only, keine Suche. |
| `concept_filter_help()` | Liste aller filterbaren Properties + Beispiele fuer das `where`-DSL. |
| `concept_status()` | Diagnose: lokale vs. remote Counts, BC-Verteilung, Glossar-Status. |
| `concept_ingest(strategy)` | Tooling, nicht Suche. `delta` (idempotent) oder `full` (drop+rebuild). |

**Empfohlener Default**:

```
concept_search(query="<frage>", limit=8)
```

Erst eingrenzen, wenn Top-Treffer aus falschem Layer/BC kommen:
- `layer="technical"` — nur Feinkonzepte.
- `domain="verify-system"` plus `surface="contract"` — Contract-Sicht
  des BC.
- `cross_cutting=true` — nur Foundation/Adapter-Docs.
- `where={"op": "contains_any", "property": "applies_policies",
  "value": ["P-INTEGRITY-V1"]}` — beliebige strukturelle
  Einschraenkung.

Fuer einen vollstaendigen Doc-Inhalt: `concept_get(doc_id="FK-27")`.

Fuer Begriffsdefinitionen:
`concept_glossary_search(query="Stage-Registry")`.

`concept_ingest` nur, wenn `concept/`-Dateien bearbeitet wurden und
die Suche frische Ergebnisse liefern soll.

### 7.2 Linter-Disziplin

Vor jeder Konzept-Aenderung **und** vor jedem Commit:

```bash
PYTHONPATH=. python scripts/ci/check_concept_frontmatter.py
PYTHONPATH=. python scripts/ci/compile_formal_specs.py
PYTHONPATH=. python scripts/ci/check_concept_code_contracts.py
PYTHONPATH=. python scripts/ci/check_architecture_conformance.py
```

Erfolgsbild aller vier:
- `[concept-frontmatter] OK: 79 docs, all lints passed.`
- `[formal-spec] OK: ... documents, ... ids, ... references, ...
  scenarios, ... prose links`
- `[concept-code-contracts] OK: no truth-boundary contract violations`
- `[architecture-conformance] OK: no architecture contract violations`

Der Pre-Commit-Hook deckt automatisch die ersten beiden ab, wenn
`concept/*` oder ein Validator-Skript veraendert wurde.

**Bei rotem Lint**: niemals umgehen, niemals `# noqa` oder
`# type: ignore` ohne Begruendung setzen. Ursache fixen, Lint
re-laufen, dann erst weiter.

### 7.3 Code-Qualitaet — Ruff + Mypy

Tools laufen aus `pyproject.toml`:

```bash
ruff check src tests
mypy src --strict
```

`ruff` und `mypy --strict` sind Pflicht. Keine unerklaerten `noqa`-
oder `type: ignore`-Marker. Jede Ausnahme begruenden.

### 7.4 var/-Disziplin

**Ausnahmslos**:
- Alle temporaeren Dateien gehoeren nach `var/` oder in
  `tmp_path`-Fixtures.
- Nichts in `var/` ist Source of Truth.
- Nichts in `var/` darf eingecheckt werden (gitignored).
- Lokale Hilfsskripte, die einmal laufen sollen, gehoeren nach
  `var/` (nicht nach `scripts/`).

`var/` enthaelt aktuell unter anderem das (nicht eingecheckte)
Komponenten-Workbook, lokale Logs, Test-Sandboxes und Ad-hoc-
Auswertungen.

### 7.5 Build-Infrastruktur — Jenkins + Sonar

AK3 hat eine vollstaendige CI-Pipeline. Beide Tools laufen in
**rechnerlokalen Docker-Containern**.

**Jenkins**:
- URL: `http://127.0.0.1:9900`
- Credentials: `admin` / `admin`
- Pipeline-Definition: `Jenkinsfile` im Repo-Root.
- Trigger: Cron `H * * * *` (stundenbasiert) plus manueller Trigger.

Stages (in Reihenfolge):

1. **Prepare** — Sources mit `tar` extrahieren (Excludes fuer Caches,
   Coverage, .git, .venv).
2. **Setup** — `python -m venv .venv`, `pip install -e ".[dev]"`,
   Output-Verzeichnisse anlegen.
3. **Ruff** — `ruff check src tests`.
4. **Mypy** — `mypy src --strict --no-error-summary`.
5. **Unit Tests + Coverage** — `pytest tests/unit` mit
   SQLite-Backend, JUnit-XML, Coverage-XML.
6. **Postgres Contract + Integration** — Postgres-DB anlegen,
   `pytest tests/contract tests/integration tests/e2e -m "not
   requires_gh"`, DB cleanup.
7. **Concept Frontmatter Lint** — `check_concept_frontmatter.py`.
8. **Formal Spec Compile** — `compile_formal_specs.py`.
9. **Concept Contract Checks** — `check_concept_code_contracts.py`
   und `check_architecture_conformance.py`.
10. **LOC Analysis** — `scripts/python/py_loc_to_sonar.py`.
11. **SonarQube** — `sonar-scanner` mit `brainbox-sonar`-Konfig.
12. **Quality Gate** — `scripts/python/wait_for_sonar_quality_gate.py`
    pollt das Sonar-Quality-Gate (heute non-blocking; existing-debt-
    Modus).

**SonarQube**:
- URL: `http://192.168.0.20:9901`
- Credentials: `admin` / `meinSonarCube2026!`
- Project-Key: `claude-agentkit3`.

**Erwartung**: **Zero Violations**. Jeder Lint-/Test-/Sonar-Befund ist
ein Handlungsauftrag, keine Dekoration. Severity-Modell aus CLAUDE.md:

- PASS — fehlerfrei, kein Handlungsauftrag.
- WARNING — aufschiebbarer Handlungsauftrag. **Pflicht zur Spiegelung
  an den Auftraggeber** mit der Frage "wie wollen wir hier vorgehen".
  Stilles Liegenlassen ist ZERO-DEBT-Verstoss.
- ERROR — sofort beheben. Keine Bypaesse, keine Workarounds.

**Wenn Jenkins oder Sonar nicht erreichbar sind**: Docker-Desktop
pruefen (Container hochfahren, ggf. neustarten). Hinter den URLs
stehen lokale Container — Erreichbarkeit ist Infrastruktur-Frage,
nicht App-Frage.

### 7.6 LSP-Disziplin

Wenn dir ein LSP zur Verfuegung steht (z.B. `pylsp`, `ruff-lsp`,
`mypy-lsp` ueber Editor- oder Tool-Anbindung), nutze ihn nicht nur
zum Navigieren, sondern halte den LSP-Befundstand **aktiv frei von
Warnings und Errors**.

Praktisch heisst das:
- Vor dem Speichern: LSP-Diagnostics fuer die Datei pruefen.
- Vor dem Commit: keine roten oder gelben LSP-Indikatoren in den
  geaenderten Dateien.
- LSP-Findings sind aequivalent zu Linter-Findings — sie werden nicht
  weggeklickt.

### 7.7 Glossar-Pflege pro BC

Eigenes Briefing: `prompts/bc-glossary-briefing.md`. Quintessenz:

- Glossar lebt im **Frontmatter eines Contract-Docs**, nie in
  separater YAML, nie in Member-/Cross-Cutting-Docs.
- Pro Begriff genau ein Definitions-Owner.
- `exported_terms` fuer Begriffe, die andere BCs sehen sollen;
  `internal_terms` mit `reason` fuer BC-private Begriffe.
- `see_also` zeigt nur auf existierende exportierte Begriffe anderer
  BCs (deterministisch, L19 prueft).
- Nach Aenderung: `python -m tools.concept_ingester.cli delta`,
  `concept_status` zur Verifikation.
- Sub-Agent fuer Glossar-Pflege bekommt **genau eine** `bc_id` und
  arbeitet ausschliesslich an deren Contract-Docs.

### 7.8 Sub-Agent-Auftraege

Aus CLAUDE.md, hart:

- Erste Zeile jedes Sub-Agent-Auftrags: **`Read
  T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules
  apply to you.`**
- Sub-Agents bekommen alle relevanten Referenzen, Pfade und
  Erfolgskriterien explizit. Keine "such dir das raus"-Auftraege.
- Kleine, verifizierbare Aufgaben. Keine God-Tasks.
- Kein "done" ohne Beleg: Diff, Tests, Artefakte, Logs oder andere
  pruefbare Evidenz.
- Ergebnisse werden aktiv geprueft, nicht blind uebernommen.

### 7.9 Worker- vs. Orchestrator-Modus

Zwei exklusive Modi pro Aufgabe:
- **Worker**: setzt selbst um, optional kleine Sub-Tasks delegieren.
- **Orchestrator**: koordiniert, **aber nicht nebenbei selbst die
  Facharbeit miterledigen**.

Nicht mischen. Wenn als Orchestrator gestartet, nicht heimlich zum
Worker werden, weil Sub-Agents scheitern — das ist genau der
Scope-Drift, den AK3 verhindert (DK-00 §3, "Scope-Drift aus
Hilfsbereitschaft").

### 7.10 Mocks und Stubs

Mocks/Stubs nur erlaubt, wenn:
1. der User sie explizit verlangt, oder
2. ein isolierter Unit-Test technisch sonst nicht moeglich ist.

Auch dann minimal und begruendet. Standardfall sind echte Komponenten,
echte Artefakte, echte Integrationspfade.

### 7.11 Anti-Loop und Feasibility-zuerst

Vor jeder Codeaenderung:
1. relevante Konzepte/Guardrails identifizieren,
2. Ist-Zustand lesen,
3. Delta zum Zielbild bestimmen,
4. Design-Entscheidung treffen,
5. erst dann implementieren.

Nach **zwei** gescheiterten Versuchen mit derselben Methode:
- Methode wechseln,
- Ursache bottom-up isolieren,
- Invarianten, Unit-Tests und Phasengrenzen separat pruefen.

Ratespiel ist kein akzeptabler Modus.

---

## 8. Was haeufig schiefgeht — typische Fehler

### 8.1 Konzept-Drift

- Doc geaendert, Lints nicht laufen lassen. Folge: Pre-Commit-Hook
  blockt, oder schlimmer: ueberlebt unbemerkt im Index.
- `defers_to`-Edge eingefuegt, ohne dass das Ziel existiert (L3-Bruch).
- Glossar-Eintrag im Member-Doc statt Contract-Doc (L19-Bruch).
- BC-Begriff aus fremdem BC ohne `defers_to` benutzt (L20-Bruch).

### 8.2 Truth-Boundary-Verletzung

- `json.load("phase-state.json")` in einem geschuetzten Modul
  (TB001 + TB004 + TB005). Korrekte Loesung: ueber das State-Backend-
  Repository lesen, nicht ueber den Export.

### 8.3 Architektur-Drift

- A-Code importiert direkt `agentkit.state_backend.store` als
  generische Fassade. Korrekte Loesung: komponentenspezifischer
  Repository-Vertrag (siehe Workbook A4).
- Story-/Dashboard-Code importiert Hook-Runtime oder
  Control-Plane-HTTP. Korrekte Loesung: ueber Ports gehen, AC001
  blockt sonst.

### 8.4 Operativ

- `var/`-Inhalte committen wollen — kann nicht passieren (gitignored),
  aber Sub-Agents versuchen es. Symptom: leere Diffs.
- Hilfsskripte unter `scripts/` parken statt unter `var/`. `scripts/`
  ist fuer dauerhafte CI-/Dev-Helfer, nicht Einmal-Auswertungen.
- Lints bei rotem Stand auf `# noqa` umgehen — fail-closed verboten.
- Tests gegen `var/`- oder `tests/fixtures/`-Generate schreiben statt
  gegen `tests/golden/`. Generate gehoeren nicht in Fixtures.

### 8.5 Sub-Agent-Disziplin

- Sub-Agent ohne CLAUDE.md-Verweis spawnen — fail-closed verboten.
- Sub-Agent mit unspezifischem Auftrag ("kuemmer dich um die
  Glossare") — das fuehrt zu BC-Grenzueberschreitungen. Pro Spawn
  immer **eine** `bc_id` mitgeben.
- Sub-Agent-Ergebnisse blind uebernehmen ohne Diff-Pruefung.

---

## 9. Quick-Reference — Befehle, Pfade, Signatur

### 9.1 Wichtigste Befehle

```bash
# Konzept-Validierung (alle vier)
PYTHONPATH=. python scripts/ci/check_concept_frontmatter.py
PYTHONPATH=. python scripts/ci/compile_formal_specs.py
PYTHONPATH=. python scripts/ci/check_concept_code_contracts.py
PYTHONPATH=. python scripts/ci/check_architecture_conformance.py

# Concept-Index Tooling
python -m tools.concept_ingester.cli status     # Diagnose
python -m tools.concept_ingester.cli delta      # idempotenter Sync
python -m tools.concept_ingester.cli ensure-schema
python -m tools.concept_ingester.cli full       # nur mit Auftraggeber-Bestaetigung
python -m tools.concept_ingester.cli drop --yes # destruktiv

# Code-Qualitaet
ruff check src tests
mypy src --strict
pytest tests/unit -q
pytest tests/contract tests/integration -q
pytest -m e2e   # opt-in

# Pre-Commit aktivieren (einmalig pro Clone)
git config core.hookspath .githooks
```

### 9.2 Wichtigste MCP-Tools (Server `agentkit3-concepts`)

| Tool | Wozu |
|---|---|
| `concept_search` | Standardsuche ueber alle Chunks |
| `concept_glossary_search` | Begriffsdefinitionen |
| `concept_get` | Volldokument oder Einzelchunk |
| `concept_filter_help` | DSL-Referenz fuer `where` |
| `concept_status` | Index-Diagnose |
| `concept_ingest` | Re-Indexierung |

### 9.3 Wichtigste Pfade

| Inhalt | Pfad |
|---|---|
| Projekt-Guardrails | `CLAUDE.md` |
| Verbindliche Struktur | `PROJECT_STRUCTURE.md` |
| Architektur-Guardrails | `guardrails/architecture-guardrails.md` |
| Test-Guardrails | `guardrails/testing-guardrails.md` |
| Domain-Konzepte | `concept/domain-design/` |
| Technische Konzepte | `concept/technical-design/` |
| Formale Specs | `concept/formal-spec/` |
| BC-Quelle | `concept/technical-design/_meta/bounded-contexts.yaml` |
| BC-Registry | `concept/technical-design/_meta/domain-registry.yaml` |
| Tag-Korpus | `concept/technical-design/_meta/tag-corpus.txt` |
| Modul-Registry | `concept/technical-design/_meta/module-registry.yaml` |
| Policy-Registry | `concept/technical-design/_meta/policy-registry.yaml` |
| Validatoren | `scripts/ci/` |
| Concept-Tooling | `tools/concept_compiler/`, `tools/concept_ingester/`, `tools/concept_mcp/` |
| Glossar-Briefing | `prompts/bc-glossary-briefing.md` |
| Onboarding (dieses Doc) | `prompts/agent-onboarding.md` |
| Pre-Commit-Hook | `.githooks/pre-commit` |
| Jenkinsfile | `Jenkinsfile` (Root) |
| Lokale Arbeitsdokumente | `var/...` (gitignored) |

### 9.4 Externe Endpunkte

| System | URL | Credentials |
|---|---|---|
| Jenkins | `http://127.0.0.1:9900` | `admin` / `admin` |
| SonarQube | `http://192.168.0.20:9901` | `admin` / `meinSonarCube2026!` |
| Weaviate (lokal) | `127.0.0.1:9903` (HTTP) / `50051` (gRPC) | — |
| Postgres (lokal, Docker) | `host.docker.internal:55432` | `agentkit` / `agentkit` |

Alle Services laufen in lokalen Docker-Containern. Nicht erreichbar?
**Docker Desktop pruefen, Container hochfahren.** Erreichbarkeit ist
Infrastruktur-Frage, nicht App-Frage.

### 9.5 Ein-Zeiler — Antworten auf typische Fragen

| Frage | Antwort |
|---|---|
| "Wo steht etwas zu X?" | `concept_search(query="X", limit=8)` |
| "Welcher BC besitzt Y?" | `concept_search(query="Y") -> domain` lesen, oder `bounded-contexts.yaml` `owns:` durchsehen |
| "Was bedeutet Begriff Z?" | `concept_glossary_search(query="Z")` |
| "Volltext FK-27" | `concept_get(doc_id="FK-27")` |
| "Welche Lints existieren?" | Doc-Header `scripts/ci/check_concept_frontmatter.py` |
| "Was ist tenant-scoped?" | `project_key` ist Pflicht-Filter; siehe FK-63 §63.3.1 |
| "Wie hole ich einen Story-Run-Status?" | `GET /v1/stories/{story_id}` |
| "Wo legt der Worker Handover ab?" | `_temp/qa/{story_id}/handover.json` (siehe FK-26) |
| "Wie haengt Verify mit Closure zusammen?" | Closure laeuft erst nach Verify PASS; FK-27 §27.5 + FK-29 §29.1 |
| "Welche Phasen gibt es?" | `setup`, `exploration` (optional), `implementation`, `verify`, `closure` (FK-20) |

---

## 10. Mindset

### 10.1 Reihenfolge der Autoritaet

User instruction > konkrete Projektregeln in CLAUDE.md > kanonische
Konzepte/Strukturvorgaben (`concept/`, `PROJECT_STRUCTURE.md`,
`guardrails/`) > allgemeine Heuristiken.

Bei Konflikt: nach oben fragen, nicht nach unten ausweichen.

### 10.2 Zielbild

AK3 ist Gegenentwurf zu v2:
- klare fachliche Schnitte statt God-Files,
- definierte State-Owner statt JSON-Wildwuchs,
- deterministische Orchestrierung statt impliziter Ablaufmagie,
- typisierte Artefakte und Stages statt loser String-Konventionen.

Jede Aenderung muss dieses Zielbild **verstaerken**, nicht
unterlaufen.

### 10.3 Was gute Arbeit hier bedeutet

- Fachliche Verantwortung klarer machen, nicht diffuser.
- Determinismus ausbauen, nicht durch agentische Sonderpfade
  erodieren.
- Tests an echten Phasengrenzen fuehren, nicht an kuenstlich
  gebastelten Ersatz-Zustaenden.
- Bestehende Guardrails ernst nehmen und bei Konflikten nicht kreativ
  umgehen.

Wenn unklar ist, wo etwas hingehoert, ist das ein
**Architekturproblem**, kein Freibrief fuer ad-hoc-Code.

### 10.4 Zero-Debt-Pflicht

Aus CLAUDE.md, woertlich:

> Every deliverable must be fachlich vollstaendig im vereinbarten
> Scope. Keine stillen Restluecken, keine TODO-Verschiebungen, keine
> "spaeter sauber machen"-Strategie.

Konkret:
- Wenn etwas fehlt, blockiert oder ohne zusaetzlichen Kontext nicht
  sauber loesbar ist: **explizit melden**, nicht stillschweigend
  vereinfachen.
- Keine Attrappen fuer produktive Kernlogik.
- Keine halbfertigen Architekturuebergaenge, die alte und neue
  Modelle parallel herumtragen.

---

## 11. Naechste Schritte fuer einen frisch gespawnten Agent

1. **CLAUDE.md vollstaendig lesen** (Pflicht).
2. **PROJECT_STRUCTURE.md vollstaendig lesen** (Pflicht).
3. Den eigenen Auftrag mit den Guardrails (`guardrails/`) abgleichen.
4. Bei BC-bezogener Arbeit: in `concept/technical-design/_meta/
   bounded-contexts.yaml` und `domain-registry.yaml` die eigene `bc_id`
   suchen. `responsibility`, `owns` und `excluded` lesen.
5. Bei Konzept-Suche: `concept_search` als Default-Werkzeug.
6. Bei Glossar-Pflege: `prompts/bc-glossary-briefing.md`.
7. Bei Code-Aenderung: erst Lints und Tests **vorab** laufen lassen,
   um den Ist-Zustand sauber zu kennen, dann implementieren.
8. Im Zweifel: Auftraggeber fragen. Spekulative Eigeninterpretation
   ist gegen Zero-Debt.

---

## 12. Stand-Hinweis

Dieses Dokument spiegelt den AK3-Stand 2026-05-01:
- 16 Bounded Contexts in `_meta/bounded-contexts.yaml`.
- FK-Renumbering 2026-04-29 (Foundation 00-09, BC-Bloecke 60-71).
- 21 Lints (`L1`-`L21`) im Frontmatter-Validator.
- 18 deklarierte `component_groups` im AC-Lint mit drei
  `acyclic_group_set`-Checks.
- `concept_glossary_search` mit erstem indizierten BC
  (`pipeline-framework`, 20 Begriffe) — die uebrigen 15 BCs sind
  noch leer und warten auf ihre BC-Owner.
- React-/xyflow-Story-Cockpit ist im Konzept (FK-63 §63.3.4)
  verankert, im Code noch nicht gebaut.

Aktualisiere dieses Dokument bewusst, wenn sich die Architekturlinie
oder die Validator-Suite aendern. Der Lauftext darf nicht stiller
treiben.
