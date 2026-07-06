# Story-Schnitt aus den THEMEN 002-010

> Generiert am 2026-05-16 fuer den orchestrierenden Top-Agent.
> Quelle: `stories/_priorisierungsempfehlung.md`, kombiniert mit den
> elf `<bc-id>-gap-analyse.md`-Markdowns im Stories-Root.

## 1. Zusammenfassung

THEME-001 (Modul-Prefix-Konsolidierung) ist bereits in den vorherigen
fuenf Commits abgearbeitet (Frontend-Contracts, Repos, KPI-Phasen,
Search, Status-Regeln, FK-72/FK-91-Erweiterung, Race-Invarianten).

Aus den verbliebenen Themen 002-010 wurden **27 neue Stories**
geschnitten (AG3-021 bis AG3-047). Naechste freie ID nach diesem Schnitt: AG3-048.

| THEMA | Story-IDs | Anzahl | Begruendung |
|---|---|---:|---|
| THEME-002: Typisierte Kern-Enums | AG3-021 | 1 | Eine zusammenhaengende Type-Kollektion, alles in einem `core_types`-Modul; Splitt wuerde nur kuenstlich Aufwand multiplizieren. |
| THEME-003: Artefakt-BC | AG3-022, AG3-023 | 2 | Datenmodelle/Registry zuerst (M), dann Manager + Persistenz-Migration (L). Trennung erlaubt isolierte Pruefbarkeit; Migration braucht alle vier Layer-Producer von verify-system und kann nicht parallel zum Foundation-Modell laufen. |
| THEME-004: PhaseEnvelope + AttemptRecord | AG3-024, AG3-025 | 2 | PhaseEnvelope/RuntimeMetadata/PauseReason zuerst (M), dann AttemptRecord + Write-Ordering + QA-Zyklus-Felder (M). Beide bauen aufeinander auf; isoliert pruefbar (Envelope ist getrennt vom Attempt-Schema). |
| THEME-005: Top-Surfaces der Capability-BCs | AG3-026 (VerifySystem), AG3-027 (Skills), AG3-028 (FailureCorpus), AG3-029 (KpiAnalytics), AG3-030 (RequirementsCoverage), AG3-031 (Governance-Top) | 6 | Eine Story pro BC. Jeder BC ist eine klare Komponenten-Grenze und wird unabhaengig pruefbar (eigene Tests, eigene Top-Methoden). PromptRuntime ist AG3-015 (bereits ready). Splitt verhindert God-Tasks. |
| THEME-006: Principal/Guards/Preflight/Integrity | AG3-032 (Principal-Capability-Modell), AG3-033 (Self-Protection + Story-Creation-Guard), AG3-034 (Preflight + IntegrityGate) | 3 | Drei klare Komponentengrenzen: (1) FK-55-Datenmodell + Capability-Matrix (L) — Voraussetzung fuer alle Guards; (2) zwei dedizierte Guard-Module (M); (3) Setup-Preflight + IntegrityGate-Dimensionen (L). 3xS wuerde kuenstlich trennen, was zusammen pruefbar ist; 1xXL waere God-Task. |
| THEME-007: Telemetrie | AG3-035 (ProjectionAccessor + Reset-Purge), AG3-036 (Harness-Hooks + Audit-Bundle), AG3-037 (TelemetryContract + EventTypes + Risk-Window) | 3 | ProjectionAccessor zuerst (M, Voraussetzung fuer Reset-Purge und Hook-Persistenz), dann sieben Harness-Hooks + Audit-Bundle (L), dann Contract + neue EventTypes + NormalizedEvent (M). Sub-Aufgaben sind eigenstaendig pruefbar; Sub-Aufgaben-Trennung ist konzeptuell entlang Konsumenten gezogen (DB-Owner vs. Emitter vs. Pruefmodul). |
| THEME-008: Persistenz-Topologie | AG3-038 (analytics-Schema + Fact-Tabellen), AG3-039 (project_registry), AG3-040 (Postgres-Store-Komplettierung + fc_*-Tabellen + Wire-Adapter) | 3 | Drei orthogonale Persistenzbereiche, jeder mit eigenem Schema-Bump. AG3-038 ist L (5 Tabellen + sync_state + Migrations); AG3-039 ist M (1 Tabelle, fokussiert); AG3-040 ist M (Wire-Adapter-Fixes + zwei fc_*-Tabellen). |
| THEME-009: QA-Zyklus-Kernlogik | AG3-041 (QA-Cycle-Mechanik), AG3-042 (Layer 1), AG3-043 (Layer 2), AG3-044 (Worker-Loop + Manifest + Adversarial-Spawn) | 4 | Vier Komponenten mit klaren Grenzen: Zyklus-Lifecycle (L) -> Layer 1 Vollausbau (L) -> Layer 2 LLM-Aufrufe (L) -> Worker-Loop + Manifest + Adversarial-Spawn (L). Jede einzeln ist L; 3-4x L statt 1xXXL ist die richtige Granularitaet, weil Layer 1, Layer 2 und Worker-Loop fachlich getrennt sind und unterschiedliche Test-Strategien brauchen. |
| THEME-010: Exploration-Phase | AG3-045 (Handler + Drafting), AG3-046 (Review-Exit-Gate), AG3-047 (Mandate + Freeze + Events) | 3 | Drei klare Sub-Phasen: Drafting (M), Review (L), Mandate-Classification + Freeze (M). AG3-045 enthaelt einen explizit dokumentierten Provisorium-Pfad (`gate_status=APPROVED` direkt), den AG3-046 ersetzt — das ist sauber via `depends_on` verkettet und in den Stories beschriftet. |

## 2. Reihenfolge-Empfehlung (Topological Order)

Reihenfolge ergibt sich aus `depends_on`. Mehrere Stories ohne harte
Wechselabhaengigkeit koennen sequenziell oder parallel laufen; AK3
fordert sequenzielle Bearbeitung pro Agent.

```
THEME-002 (Foundation):
  AG3-021 (M)  Kern-Enums

THEME-003 (Artefakte) — depends_on: AG3-021:
  AG3-022 (M)  ArtifactEnvelope, Registry, Validator
  AG3-023 (L)  ArtifactManager + Migration QA-Persistenz

THEME-004 (Phase/Attempt) — depends_on: AG3-021:
  AG3-024 (M)  PhaseEnvelope + PauseReason
  AG3-025 (M)  AttemptRecord + Write-Ordering + QA-Cycle-Felder
    (depends_on: AG3-024)

THEME-005 (Top-Surfaces) — depends_on: AG3-021, AG3-022, ggf. AG3-023:
  AG3-026 (M)  VerifySystem.run_qa_subflow
  AG3-027 (M)  Skills.bind_skill + Subs (schlanke Top-Surface; siehe AG3-048)
    — geaendert 2026-05-19: User-Entscheidung Split, war L
  AG3-028 (L)  FailureCorpus.record_incident + IncidentTriage
    — geaendert 2026-05-19: User-Entscheidung Vollumsetzung, war M;
      depends_on jetzt zusaetzlich AG3-035, AG3-040
  AG3-029 (M)  KpiAnalytics + Paket-Migration
  AG3-030 (M)  RequirementsCoverage + AreClient-Skelett
  AG3-031 (M)  Governance.register_hooks/deactivate_locks

THEME-005-Folge (neu 2026-05-19) — depends_on: AG3-027:
  AG3-048 (M)  Skills-Persistenz + Installer-Andockung + Repo-Hygiene
    (Auslagerung aus AG3-027, siehe Split-Entscheidung)

THEME-006 (Trust-Boundary) — depends_on: AG3-021 + ggf. AG3-031:
  AG3-032 (L)  Principal-Capability-Modell + Matrix + Freeze
  AG3-033 (M)  Self-Protection + Story-Creation-Guard
    (depends_on: AG3-021, AG3-031, AG3-032)
  AG3-034 (L)  Preflight + IntegrityGate
    (depends_on: AG3-021, AG3-022, AG3-023, AG3-032)

THEME-007 (Telemetrie) — depends_on: AG3-021, AG3-022, ggf. AG3-023:
  AG3-035 (M)  ProjectionAccessor + Reset-Purge
  AG3-036 (L)  Harness-Hooks + Audit-Bundle
    (depends_on: AG3-035)
  AG3-037 (M)  TelemetryContract + EventTypes + Risk-Window
    (depends_on: AG3-035)

THEME-008 (Persistenz) — depends_on: AG3-021 + ggf. AG3-029, AG3-028:
  AG3-038 (L)  analytics-Schema + 5 Fact-Tabellen + Migrations
    (depends_on: AG3-021, AG3-029)
  AG3-039 (M)  project_registry
    (depends_on: AG3-021)
  AG3-040 (M)  Postgres-Store-Komplettierung + fc_-Tabellen
    (depends_on: AG3-021, AG3-028)

THEME-009 (QA-Kernlogik) — depends_on: AG3-021, AG3-022, AG3-023, AG3-024, AG3-025, AG3-026:
  AG3-041 (L)  QA-Cycle-Mechanik + advance_qa_cycle + Remediation-Loop
  AG3-042 (L)  Layer 1 + Stage-Registry
    (depends_on: AG3-021, AG3-022, AG3-023, AG3-026)
  AG3-043 (L)  Layer 2 LLM-Evaluations
    (depends_on: AG3-015, AG3-021, AG3-022, AG3-026, AG3-041)
  AG3-044 (L)  Worker-Loop + Manifest + Adversarial-Spawn
    (depends_on: AG3-021, AG3-022, AG3-023, AG3-026, AG3-041)

THEME-010 (Exploration) — depends_on: AG3-021, AG3-024, AG3-026, AG3-041 + ggf. AG3-043:
  AG3-045 (M)  ExplorationPhaseHandler + Drafting + Gate-Guard-Fix
  AG3-046 (L)  ExplorationReview dreistufig
    (depends_on: AG3-021, AG3-026, AG3-037, AG3-041, AG3-043, AG3-045)
  AG3-047 (M)  MandateClassification + DesignFreeze + Events
    (depends_on: AG3-021, AG3-022, AG3-037, AG3-045, AG3-046)
```

## 3. Splitt-Erlaeuterungen im Detail

### 3.1 THEME-002 als 1 Story

Begruendung: Enums sind eng zusammenhaengende Typen, die als Foundation in **einem** `core_types`-Modul leben. Splitt waere kuenstlich (z.B. "alle Severity-Werte in einer Story, alle Story-Enums in einer anderen"); zudem muessen alle Migrations gleichzeitig passieren, weil sonst Importer halbrunde Zustaende sehen.

### 3.2 THEME-003 als 2 Stories statt 1 L

Eine L-Story haette Foundation + Manager + Migration zusammen. Splitt: Datenmodelle (Envelope, Registry, Validator, Reference) sind isoliert pruefbar (`AG3-022`); ArtifactManager + Persistenz-Migration ist eine separate fachliche Einheit (`AG3-023`). Zudem braucht Migration die vier verify-system-Producer registriert, was die Story zusaetzlich verlaengert. 2xM ist sauberer als 1xL.

### 3.3 THEME-004 als 2 Stories statt 1 L

PhaseEnvelope/RuntimeMetadata (`AG3-024`) ist ein **Datenmodell + Persistenzgrenze**; AttemptRecord-Umbau + Write-Ordering-Bug (`AG3-025`) ist ein **Schema-Umbau + Crash-Safety-Fix**. Beide haben eigene Test-Strategien; Splitt nach Persistenzgrenze. 2xM.

### 3.4 THEME-005 als 6 Stories

Klare Komponentengrenze: pro BC eine Story. Splitt unverhandelbar — sonst God-Task. PromptRuntime ist bereits als AG3-015 angelegt (vorhanden, status `ready`). Sechs BCs * je M-L = sechs Stories.

### 3.5 THEME-006 als 3 Stories statt 1 XL

- AG3-032 (L): Principal-Capability-Modell + Matrix + Freeze. Datenmodell-zentriert; pruefbar via Matrix-Tests.
- AG3-033 (M): zwei dedizierte Guard-Module + Hook-Dispatch-Differenzierung. Hat eigene Pruefbarkeit (Guard-Tests pro Modul).
- AG3-034 (L): Preflight 7 neue Checks + IntegrityGate 8 Dimensionen + Concept/Research-Drift. Logisch zusammen (beide sind Pruef-Pipelines mit Pflicht-Vollstaendigkeit).

3xL/M ist die richtige Granularitaet — die drei Bereiche sind fachlich getrennt aber bauen aufeinander auf.

### 3.6 THEME-007 als 3 Stories

- AG3-035 (M): ProjectionAccessor + Reset-Purge. DB-Owner-Pattern; Voraussetzung fuer alle weiteren.
- AG3-036 (L): sieben Harness-Hooks + Audit-Bundle-Exporter. Klare Sub-Komponenten-Sammlung; sieben Hooks aber alle nach gleichem Muster (`evaluate -> emit`).
- AG3-037 (M): TelemetryContract + neue EventTypes + Risk-Window-NormalizedEvent. Pruefmodul + Datenmodell-Erweiterung.

### 3.7 THEME-008 als 3 Stories

Drei orthogonale Persistenzbereiche:
- AG3-038 (L): analytics-Schema + 5 Fact-Tabellen + Migrations-Strategie. Gross, weil FactStore-Sub + Migrations-Runner + 5 Tabellen.
- AG3-039 (M): project_registry + ProjectRegistration. Fokussiert auf Installer-CP-7.
- AG3-040 (M): Postgres-Store fuer project_management + fc_*-Tabellen + Wire-Adapter. Behebt drei orthogonale Drift-Punkte zusammen, weil sie alle "Postgres-Persistenz fuer existing BC vollstaendig machen" sind.

### 3.8 THEME-009 als 4 Stories statt 1 XXL

Vier Stories sind die richtige Granularitaet, weil jede einzeln L ist:
- AG3-041: QA-Zyklus-Lifecycle (advance_qa_cycle, Remediation-Loop, Finding-Resolution).
- AG3-042: Layer 1 Vollausbau + Stage-Registry.
- AG3-043: Layer 2 echte LLM-Aufrufe.
- AG3-044: Worker-Loop + Manifest + BLOCKED-Exit + Adversarial-Spawn.

Jede hat eigene Test-Strategie (Layer 2 braucht Mock-LLM; Worker-Loop braucht Filesystem-Fixtures). 1xXXL waere unwartbar; mehr als 4 Stories waere kuenstlich.

### 3.9 THEME-010 als 3 Stories statt 1 L

- AG3-045 (M): Handler + Drafting + Bugfix-Profil-Fix + Gate-Guard-Erweiterung. Hat einen **dokumentierten Provisorium-Pfad** fuer Gate-Approval, der von AG3-046 ersetzt wird.
- AG3-046 (L): Review (dreistufiges Exit-Gate) — vollwertig mit Remediation-Loop und Eskalation.
- AG3-047 (M): MandateClassification + DesignFreezeMarker + Telemetrie-Events.

Splitt nach Lifecycle-Pfaden: erst Skelett (Drafting + Provisorium-Gate), dann echtes Gate, dann Mandate-Logik. Jede Sub ist eigenstaendig pruefbar; der Provisorium-Pfad in AG3-045 ist klar dokumentiert.

## 4. Bewusst NICHT in dieser Erst-Welle

Folgende Befunde aus den GAP-Analysen sind in den Stories als
**Out of Scope** ausgewiesen und werden in spaeteren Wellen adressiert.
Die Liste deckt sich grossteils mit `_priorisierungsempfehlung.md §5`,
plus ein paar zusaetzliche Befunde, die innerhalb von Stories als
Folge-Story markiert wurden:

| Bereich | Befunde | Begruendung |
|---|---|---|
| Volle Checkpoint-Engine Installer (12 Checkpoints) | `installation-and-bootstrap.A1` (alle ausser CP 7) | Aufwand sehr hoch; CP 7 (project_registry) reicht fuer alle Folge-Stories der Welle. |
| CompactionResilience | `pipeline-framework.A1` | Wichtig, aber eigenstaendige Sub-Komponente; setzt PhaseEnvelope + Telemetrie-Hooks voraus. Folge-Welle. |
| StoryResetService / StorySplitService / Story-Exit | `story-lifecycle.A5-A7` | Administrative Pfade; greifen erst im Operationalbetrieb. |
| Closure Sub-Komponenten (ClosureGates, MergeSequence, PostMergeFinalization) | `story-closure.A1-A8` | Braucht VerifySystem-Top + Finding-Resolution-Gate (in der Erst-Welle hergestellt); Closure-Vollausbau ist Folge-Welle. |
| ExecutionPlanning Vollausbau | `execution-planning.A1-A11` (ausser StoryDependencyKind-Migration in AG3-021) | Orthogonaler BC; blockiert die Welle nicht. |
| GovernanceObserver | `governance-and-guards.A1` | Setzt funktionierende Telemetrie-Hooks und Rolling-Window-Storage voraus. Folge-Welle. |
| WorkerHealthMonitor | `implementation-phase.A5-A8`, `governance-and-guards.A2` | FK-49 Vollausbau ist gross; setzt Worker-Loop + Telemetrie + MCP-Pool stabil voraus. |
| EvidenceAssembler, ImportResolver, Request-DSL, Preflight-Turn, ConformanceService, ContextSufficiencyBuilder, Divergenz-Quorum | `verify-system.A3-A7, A9` | Detail-Ausbau der QA-Schichten 2/3; baut auf THEME-009-Kernlogik auf. |
| Dashboard-Tabs + DesignSystem + 40 KPI-Definitionen | `kpi-and-dashboard.A10, A11` | "Spaetere Iteration" laut FK-63 selbst. |
| RefreshWorker (sync_analytics-Aggregation) | `kpi-and-dashboard.A5` | Setzt analytics-Schema voraus (AG3-038); Folge-Story der THEME-008-Welle. |
| Wire-Format-Anpassungen story_counters/concept_anchors-Befuellung | `project-management.A1-A4, B1, C1` | Skelett in AG3-040; Befuellung Folge-Story. |
| Story-Creation-Pipeline (VektorDB-Abgleich, story.md-Export) | `story-lifecycle.A1-A4, A9` | Setzt Skills, PromptRuntime und Telemetrie-Hooks voraus. |
| CLI-Refactor `register-project`/`verify-project` | `installation-and-bootstrap.A4-A10, B1-B5` | Setzt Top-Surfaces voraus. CLI ist Operator-Recovery, nicht Standardweg. |
| Failure-Corpus PatternPromotion + CheckFactory + Effectiveness | `failure-corpus.A4, A5, A7, A8, A9` | Setzt LlmEvaluator (AG3-043) + GitHub-Adapter voraus. Folge-Welle. |
| ARE-Vollausbau (Andock-Punkte 1-4) | `requirements-and-scope-coverage.A1-A5, A7, A8` | RequirementsCoverage-Top mit no-op ist in AG3-030; Vollausbau ist Folge-Welle (Andock-Punkt 4 / ARE-Gate ist Teil von AG3-042 als BLOCKING-Stage). |
| Multi-LLM-Diskussion im Feindesign | `FK-25 §25.5` Detail | Skelett in AG3-047; volle Multi-LLM-Hub-Integration Folge-Story. |
| LLM-Pool-Reviews-Vollausbau (Sparring-Templates) | `implementation-phase.B4` | Templates teilweise vorhanden; vollstaendige Sparring-Suite Folge-Story. |
| Bugfix Red-Green-Suite | `FK-26 §26.9` | Implementation-Phase ist in AG3-044; Bugfix-Detail-Logik Folge-Story. |
| StorySplitService-Auto-Trigger nach Klasse-3 | `story-lifecycle.A6` | Klasse-3 in AG3-047 eskaliert; Service-Implementation Folge-Welle. |

## 5. Auffaelliges

- **AG3-045 enthaelt einen bewusst dokumentierten Provisorium-Pfad** (`gate_status=APPROVED` direkt nach Drafting, mit `# TODO AG3-046`-Kommentar). Das ist die einzige Stelle mit kontrolliertem Half-State, der durch die nachgelagerte Story explizit ersetzt wird. `depends_on`-Kette stellt sicher, dass AG3-046 vor produktiven Stories der THEME-009-Welle gemerged wird.
- **AG3-021 hat eine besonders breite `unblocks`-Liste**: praktisch alle weiteren Stories der Welle. Das ist konzeptkonform — `core_types` ist das Foundation-Modul.
- **AG3-027 (Skills)** hat eine kritische Plattformabhaengigkeit (Symlinks unter Windows) — wenn CI/Dev-Umgebung keine Symlinks erlaubt, ist die Story-AK4 nicht erfuellbar. Der Worker muss das pruefen und ggf. an User melden, bevor er beginnt.
- **AG3-043 (Layer 2 LLM-Evaluations)** ist die einzige Story der Welle, die mocks explizit braucht (echte LLM-Calls sind kosten- und zeitintensiv in CI). Das ist im Story-Briefing dokumentiert und entspricht der Mock-Ausnahme aus CLAUDE.md.
- **AG3-031 (Governance-Top-Surfaces)** unblockt AG3-032 (Principal-Capability-Modell), weil das Capability-Enforcement zur Hook-Dispatch-Phase gehoert. Die `depends_on`-Reihenfolge stellt sicher, dass `register_hooks` vor der vollen Enforcement-Pipeline existiert.
- **THEME-009 sequenzialitaet**: AG3-041 (QA-Cycle-Lifecycle) ist Voraussetzung fuer AG3-043 (Layer 2 nutzt FindingResolutionStatus) **und** AG3-044 (Worker-Loop nutzt evidence_epoch fuer Adversarial-Spawn-Sandbox-Pfad). AG3-042 (Layer 1) ist parallel zu AG3-041 startbar, weil sie nur Stage-Registry und Structural-Checks braucht.
- **AG3-024/AG3-025 (PhaseEnvelope, AttemptRecord)** koennten theoretisch parallel laufen, aber `AG3-025.depends_on` zieht AG3-024 mit, weil das `AttemptRecord`-Write-Ordering den Envelope-Save als zweite Schreib-Stelle braucht — sauberer in sequenzieller Reihenfolge.
- **Cross-THEMA-Abhaengigkeiten dokumentiert**: jede Story trágt `depends_on` mit den expliziten Vorgaenger-IDs (nicht nur "letzte Story des Vorgaenger-THEMAs"). Bei der Bearbeitung kann der Orchestrator pruefen, ob alle expliziten Vorgaenger `completed` sind.

## 6. Statistik

- **27 neue Stories** angelegt.
- **Groessenverteilung**: 11 x L, 16 x M, 0 x S (alle Splits ergaben mindestens M; bewusst kein kuenstliches S).
- **Vorbedingungs-Graph**: keine Zyklen; alle `depends_on`-Eintraege zeigen auf existierende Story-IDs.
- **Story-Status**:
  - `ready`: AG3-021 (keine Dependencies).
  - `blocked`: 26 (alle warten auf direkte oder indirekte Vorgaenger).
- **Naechste freie ID nach diesem Schnitt**: AG3-049 (AG3-048 ist seit 2026-05-19 belegt -- Folge-Story zu AG3-027 nach ChatGPT-Deep-Review + User-Split-Entscheidung; siehe `stories/AG3-048-skills-persistence-installer-cleanup/`).
