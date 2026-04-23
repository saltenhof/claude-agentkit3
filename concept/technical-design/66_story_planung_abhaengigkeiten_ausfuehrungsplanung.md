---
concept_id: FK-66
title: Story-Planung, Abhaengigkeitsgraph und Ausfuehrungsplanung
module: execution-planning
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: execution-planning
  - scope: dependency-graph
  - scope: scheduling-policy
  - scope: backlog-readiness
  - scope: parallelization-policy
defers_to:
  - target: FK-12
    scope: github-integration
    reason: GitHub bleibt aktueller Adapterpfad fuer Story- und Board-Metadaten
  - target: FK-21
    scope: story-creation
    reason: Story-Erstellung liefert die ersten Planungsmetadaten fuer neue Stories
  - target: FK-65
    scope: component-architecture
    reason: Komponentenschnitt und Ports der Planungsdomäne werden dort verankert
  - target: FK-91
    scope: api-catalog
    reason: Offizielle Control-Plane-Endpunkte und Events fuer Planung werden dort katalogisiert
supersedes: []
superseded_by:
tags: [planning, dependencies, scheduling, readiness, parallelization, orchestration]
prose_anchor_policy: strict
formal_refs:
  - formal.execution-planning.entities
  - formal.execution-planning.state-machine
  - formal.execution-planning.commands
  - formal.execution-planning.events
  - formal.execution-planning.invariants
  - formal.execution-planning.scenarios
---

# 66 — Story-Planung, Abhaengigkeitsgraph und Ausfuehrungsplanung

<!-- PROSE-FORMAL: formal.execution-planning.entities, formal.execution-planning.state-machine, formal.execution-planning.commands, formal.execution-planning.events, formal.execution-planning.invariants, formal.execution-planning.scenarios -->

## 66.1 Zweck

AgentKit beantwortet nicht nur die Frage, wie eine freigegebene Story
korrekt umgesetzt wird, sondern auch, welche Story wann warum als
naechstes umgesetzt werden darf und soll.

Diese Planungsdomäne ist eine eigene fachliche Kernkomponente. Sie ist
weder bloss ein Dashboard-Feature noch freie Orchestrator-Heuristik.

Normativ gilt:

1. Der Orchestrator darf nicht frei in einen Backlog greifen.
2. Jede Startentscheidung fuer eine Story muss gegen einen offiziellen
   Planungszustand getroffen werden.
3. Ein Abhaengigkeitsgraph allein reicht nicht aus; AK3 benoetigt
   zusaetzlich Readiness-, Blocking- und Scheduling-Logik.
4. Theoretisch moegliche Parallelisierung und operativ zulaessige
   Parallelisierung sind strikt getrennte Ebenen.

## 66.2 Kernentscheidung

AK3 fuehrt eine eigene fachliche Komponente `ExecutionPlanningService`
ein.

Sie beantwortet vier getrennte Fragen:

1. Welche Stories, Gates und Praemissen existieren im aktuellen
   Backlog-Kontext?
2. Welche Stories sind objektiv ausfuehrbar, weil ihre harten
   Abhaengigkeiten und Konfliktregeln das erlauben?
3. Welche Stories sind trotz theoretischer Machbarkeit momentan
   operativ nicht zulaessig, weil Kapazitaets- oder Risiko-Policies
   dagegen sprechen?
4. Welche naechste Welle, welcher kritische Pfad und welcher
   empfohlene Batch daraus fuer den Orchestrator folgen?

## 66.3 Abgrenzung

### 66.3.1 Gegen `PipelineEngine`

`PipelineEngine` fuehrt eine einzelne Story oder einen einzelnen
Story-Run korrekt aus.

`ExecutionPlanningService` entscheidet, welche Stories ueberhaupt in
den Status `READY` kommen, in welcher Reihenfolge sie gestartet werden
duerfen und wie starke Parallelisierung aktuell fachlich und operativ
zulaessig ist.

### 66.3.2 Gegen `DashboardApplication`

`DashboardApplication` praesentiert Planungs- und Laufzeitdaten.

Die Planung selbst ist keine Praesentationslogik. Graph, Blocker, Wave
und Ready-Queue sind nur Sichten auf die Planungsdomäne.

### 66.3.3 Gegen GitHub Projects

GitHub ist aktuell der externe Story- und Board-Adapter. Die
fachlich bevorzugte Planungswahrheit liegt jedoch in AK3.

GitHub darf Planungsinformation spiegeln oder beherbergen, aber die
Ableitung von `READY`, `BLOCKED`, `execution wave`, `critical path`
oder `recommended batch` ist eine AK3-eigene Fachentscheidung.

## 66.4 Fachliche Begriffe

### 66.4.1 Planbare Story

Eine `PlannedStory` ist eine Story im Backlog oder in Ausfuehrung, fuer
die AK3 neben Story-Inhalt auch Planungsmetadaten kennt.

Mindestens relevant sind:

- `project_key`
- `story_id`
- `story_type`
- `story_size`
- `primary_repo`
- `participating_repos`
- `human_touchpoints`
- `external_prerequisites`
- `planning_status`

### 66.4.2 Abhaengigkeitskante

Eine `DependencyEdge` beschreibt eine explizite Voraussetzung oder
Einschraenkung zwischen zwei Stories oder zwischen Story und Gate.

Mindestens zu unterscheiden sind:

- `hard_story_dependency`
- `soft_story_dependency`
- `serial_execution_constraint`
- `mutex_constraint`
- `shared_contract_dependency`
- `shared_file_conflict`
- `external_dependency`
- `human_gate_dependency`

`soft_story_dependency` ist **kein** harter Topologie-Blocker. Sie
beeinflusst Priorisierung oder Scheduling, darf aber eine Story nicht
eigenstaendig von `READY` auf nicht-ausfuehrbar setzen.

### 66.4.3 Blocker

Ein `BlockingCondition` ist ein expliziter, typisierter Grund, warum
eine Story nicht in `FLIGHT` uebergehen darf.

Mindestens relevante Blockerklassen sind:

- `blocked_internal_dependency`
- `blocked_external`
- `blocked_human`
- `blocked_capacity`
- `blocked_conflict`
- `blocked_contract`

Freitext allein ist nicht ausreichend. Blocker muessen als
erstklassige Objekte modelliert und auswertbar sein.

Nicht jede menschliche Mitwirkung ist ein Blocker. AK3 trennt deshalb
sauber zwischen:

- **optionaler Human-Review oder Human-Mitarbeit** zur
  Qualitaetsverbesserung
- **blockierendem Human-Gate**, wenn Rechte, Mandat, Fachwissen oder
  externe Entscheidungshoheit fehlen

### 66.4.4 Feasibility vs. Scheduling

AK3 trennt zwei Ebenen:

**ExecutionFeasibility**

Die objektive Frage, ob eine Story unter reiner Betrachtung von
Abhaengigkeiten, Konflikten, Gates und Invarianten gleichzeitig
ausfuehrbar waere.

**ExecutionSchedulingPolicy**

Die operative Frage, ob der Orchestrator diese Story jetzt auch
tatsaechlich starten soll oder darf, bezogen auf Kapazitaet, Risiko,
Rate-Limits und Merge-Folgekosten.

Diese Ebenen duerfen nie zu einem einzigen booleschen Feld
zusammenfallen.

**Normative Kurzform:** AK3 unterscheidet strikt zwischen
`can_parallelize` und `may_parallelize_now`.

## 66.5 Planungszustand

### 66.5.1 Planungsstatus einer Story

Fuer die Planung gilt mindestens dieses Zustandsmodell:

| Status | Bedeutung |
|--------|-----------|
| `UNSTARTED` | Story ist bekannt, aber noch nicht bereit zur Ausfuehrung |
| `READY` | Story ist fachlich ausfuehrbar und darf grundsaetzlich gestartet werden |
| `FLIGHT` | Story wird aktuell aktiv bearbeitet |
| `DONE` | Story ist erfolgreich abgeschlossen |
| `BLOCKED_EXTERNAL` | Externe Voraussetzung fehlt |
| `BLOCKED_HUMAN` | Menschliche Mitwirkung oder Freigabe fehlt |
| `BLOCKED_CAPACITY` | Story waere theoretisch moeglich, ist aber aktuell aus Kapazitaets- oder Risiko-Gruenden nicht schedulbar |
| `BLOCKED_CONFLICT` | Bekannte Konflikt- oder Mutex-Regel verhindert den Start |

### 66.5.2 Wichtige Folgerung

`READY` ist kein manuell gesetztes Board-Label, sondern das Ergebnis
einer regelbasierten Auswertung ueber Abhaengigkeiten, Gates und
Policies.

### 66.5.3 Human- und External-Gates

AK3 fuehrt `HumanGate` und `ExternalGate` als erstklassige
Planungsobjekte.

Beispiele:

- UAT oder manuelle fachliche Abnahme
- Entscheidung ueber konkurrierende Konzeptvorgaben
- externe API-, CI-, Infrastruktur- oder Zuliefer-Situation
- Bereitstellung von Testdaten, Credentials oder Hardware

Solche Voraussetzungen duerfen nicht nur als Kommentar in einer Story
stehen. Sie muessen den Readiness- und Scheduling-Zustand direkt
beeinflussen.

### 66.5.4 Zwei Arten menschlicher Mitwirkung

AK3 unterscheidet normativ zwei Kategorien:

**1. Optionale Human-Review**

Ein Agent oder das System kann einen Menschen hinzuziehen, um
Ergebnisqualitaet zu verbessern, Plausibilitaet zu validieren oder
einen Plan zu schärfen.

Beispiele:

- "Bitte reviewe diese Abhaengigkeiten"
- "Bitte validiere diesen Wellenplan"
- "Bitte schaue, ob die Reihenfolge fachlich sinnvoll ist"

Diese Kategorie ist **nicht blockierend**. Sie darf `READY`,
`recommended_batch` oder `ExecutionPlan` informativ anreichern, aber
nicht allein verhindern, dass AK3 mit einem gueltigen Plan arbeitet.

**2. Blockierendes Human-Gate**

Ein Human-Gate liegt nur dann vor, wenn ein Agent die Blockade selbst
nicht aufloesen kann, weil mindestens eines davon fehlt:

- Rechte
- Mandat
- erforderliches Fachwissen
- offizielle externe Entscheidung oder Freigabe

Nur diese Kategorie darf den Status `BLOCKED_HUMAN` erzeugen und
damit Ausfuehrung oder Weiterplanung fail-closed stoppen.

## 66.6 Planungsregeln

### 66.6.1 Readiness

Eine Story ist nur `READY`, wenn mindestens gilt:

1. alle `hard_story_dependency`-Vorgaenger sind `DONE`
2. keine aktive `mutex_constraint` verletzt wird
3. keine `serial_execution_constraint` einen offenen Vorgaenger hat
4. kein offener `ExternalGate` oder `HumanGate` fuer diese Story besteht
5. kein expliziter Konfliktzustand an einer geschuetzten
   Vertrags- oder Konfliktflaeche vorliegt

Eine offene optionale Human-Review zaehlt hierbei ausdruecklich nicht
als Blocker.

### 66.6.2 Scheduling

Auch wenn eine Story `READY` ist, darf sie dennoch durch Scheduling
Policy zurueckgestellt werden.

Mindestens diese Budget- und Policy-Dimensionen sind zu
beruecksichtigen:

- `repo_parallel_cap`
- `merge_risk_cap`
- `api_rate_limit_cap`
- `llm_pool_cap`
- `ci_capacity_cap`
- `human_gate_cap`
- `global_orchestrator_cap`

**Normative Auswertungsreihenfolge:**

1. harte Graph- und Gate-Regeln bestimmen die reine
   `ExecutionFeasibility`
2. systemische und projektweite Kapazitaets- und Risikobudgets
   begrenzen daraus den `max_allowed_batch`
3. projektspezifische Rulebooks oder Scheduling-Hints duerfen daraus
   den `recommended_batch` weiter verengen, aber keine harte
   Feasibility-Verletzung heilen oder uebersteuern

Damit gilt strikt:

- harte Abhaengigkeiten und Konflikte schlagen immer
- zentrale Budgets schlagen projektspezifische Scheduling-Hints
- projektlokale Rulebooks duerfen nur weiter einschränken, nicht
  freigeben was zuvor verboten war

### 66.6.2a Re-Plan-Trigger

Readiness und Scheduling werden nicht nur manuell, sondern
ereignisgetrieben neu bewertet.

Mindestens folgende Aenderungen loesen einen bounded Re-Plan aus:

- Story wurde `DONE`
- Blocker oder Gate wurde gesetzt oder aufgehoben
- Kapazitaetsbudget wurde frei oder erschopft
- Rulebook oder Scheduling-Policy wurde geaendert
- Konflikt- oder Vertragsflaeche wurde neu bewertet

Re-Planning darf dabei nicht in ungebremstes Thrashing kippen.
AK3 fuehrt deshalb einen debounced, revisionsbasierten Re-Plan-Pfad
statt freier Polling-Heuristik.

### 66.6.3 Trade-off-Regel

Hohe theoretische Parallelisierbarkeit begruendet keine Pflicht zur
maximalen Parallelisierung.

AK3 darf die effektive Parallelisierung bewusst unterhalb des
machbaren Niveaus halten, wenn die Grenzkosten in Form von
Merge-Konflikten, Review-Stau, CI-Latenz oder Human-Overhead den
Nutzen uebersteigen.

Der Orchestrator darf daraus nie implizit ableiten, dass maximale
theoretische Parallelitaet auch operativ gewollt ist.

### 66.6.4 Kritischer Pfad und Wellen

Der `ExecutionPlanningService` leitet aus dem Graphen mindestens ab:

- `critical_path`
- `ready_set`
- `blocked_set`
- `execution_wave`
- `recommended_batch`
- `max_allowed_batch`

Ein `ExecutionWave` ist eine explizite Welle gleichzeitig
freigegebener Stories, nicht nur ein visuelles Gruppierungsartefakt.

Waves besitzen mindestens einen expliziten Lifecycle:

- `planned`
- `active`
- `completed`
- `collapsed`

Teilweises Scheitern innerhalb einer Wave fuehrt nicht zu stiller
Inkonsistenz. AK3 markiert die betroffene Wave als `collapsed` oder
schneidet sie ueber einen auditierten Re-Plan neu.

## 66.7 Story-Erstellung als Planning-Einstieg

Die Planungsdomäne beginnt nicht erst mit der Orchestrierung.

Bereits bei Story-Erstellung muessen planungsrelevante Informationen
erfasst oder vorbereitet werden:

- explizite Story-Abhaengigkeiten
- betroffene Repos und technischer Scope
- moegliche Human-Touchpoints
- bekannte externe Voraussetzungen
- Endgate- oder Sammelrollen

Diese Felder muessen nicht alle vollstaendig bei der ersten Erzeugung
fertig sein. Aber AK3 muss den Prozess normativ vorsehen, wie aus dem
initialen Story-Funken ueber Analyse und Review ein belastbarer
Planungsgraph aufgebaut wird.

## 66.7a Planning-Metadata-Vertrag

Bevor AK3 einen belastbaren Ausfuehrungsplan ableiten kann, braucht
es einen expliziten Planungsmetadaten-Vertrag pro Story.

Dieser Vertrag ist nicht identisch mit der Story-Beschreibung. Er
enthaelt mindestens:

- **Strukturmetadaten**: `primary_repo`, `participating_repos`,
  relevante Scope-Surfaces, technische Konfliktflaechen
- **Abhaengigkeiten**: harte und weiche Story-Beziehungen,
  Sammel- oder Endgate-Rollen
- **Gate-Metadaten**: externe Voraussetzungen, Human-Gates,
  benoetigte Freigaben, UAT- oder Umgebungsbedingungen
- **Planungshinweise**: moegliche Parallelisierung, Serialisierungs-
  hinweise, Mutex- oder Konfliktindikatoren
- **Provenienz**: wer eine Aussage geliefert hat, auf welcher
  Evidenzbasis und mit welchem Verlaesslichkeitsgrad

Normativ gilt:

1. Planungsmetadaten duerfen aus Story-Erstellung, Agentenanalyse,
   administrativen Pfaden oder externen Systemen stammen.
2. Sie muessen aber in einem einheitlichen kanonischen Vertrag
   landen, bevor AK3 daraus `READY`, Blocker oder Waves ableitet.
3. Aussagen ohne Provenienz oder Evidenz duerfen als Hinweis
   gespeichert werden, aber nicht still zur harten Wahrheit werden.

## 66.7b Agent-zu-AK3-Handover-Vertrag

Agenten duerfen Abhaengigkeiten, Gates, Konfliktflaechen und
Ausfuehrungswellen analysieren. Die offizielle Uebergabe an AK3
erfolgt jedoch nicht als freie Prosa, sondern ueber einen
strukturierten, versionierten `PlanningProposal`.

Ein `PlanningProposal` enthaelt mindestens:

- betrachtete Story-Menge und `project_key`
- vorgeschlagene `DependencyEdge`s
- vorgeschlagene `BlockingCondition`s und Gates
- Konflikt- und Scope-Surfaces
- optional vorgeschlagene Waves oder Batch-Gruppierungen
- Evidenzreferenzen und Provenienz
- `proposal_revision` und `source_revision`

Wesentliche Regel:

- Der Agent uebergibt eine **formale Analyse**
- AK3 erzeugt daraus die **kanonische Planung**

Das heisst:

1. ein Agent darf einen Plan vorschlagen
2. AK3 validiert, normalisiert und persistiert diesen Vorschlag
3. der kanonische `ExecutionPlan` bleibt eine AK3-eigene Ableitung und
   ist nie bloss die ungepruefte Agentenantwort

## 66.7c Braucht AK3 dafuer eine DSL?

**Normative Entscheidung:** Nein, nicht als verpflichtende
Primärschnittstelle.

Fuer den offiziellen Handover von Agenten an AK3 ist ein
strukturierter Proposal-Vertrag in kanonischer Form die bessere
Standardschnittstelle als eine freie DSL.

Gruende:

1. AK3 braucht eine stabile API- und Validierungsgrenze.
2. Die Planung muss tenant-scoped, revisionsgebunden und auditierbar
   persistiert werden.
3. Eine freie DSL ist gut fuer kompakte agentenseitige Modellierung,
   aber schlechter als offizielle Runtime-Grenze.
4. Ein strukturierter Proposal-Vertrag laesst sich einfacher gegen
   JSON-Schema, Formal-Spec und Control-Plane-Endpunkte pruefen.

Eine DSL kann **optional** sinnvoll sein, wenn:

- ein Agent komplexe Abhängigkeits- oder Regelmuster kompakt ausdrücken
  will
- projektspezifische Kurzformen fuer Konflikt- oder
  Parallelisierungsregeln nuetzlich sind
- ein Mensch oder Agent ein kompaktes Rulebook als Arbeitsartefakt
  pflegen will

Dann gilt aber:

- die DSL ist ein **Eingabeformat**
- der Proposal-Vertrag ist die **offizielle Uebergabe**
- der kanonische AK3-Planungszustand ist die **einzige Wahrheit**

## 66.7d Projektspezifische Regelwerke

Projektspezifische Artefakte wie ein `orchestrator-rulebook.dsl`
koennen als Analyse- und Importquelle fuer den `ExecutionPlanningService`
dienen.

Dabei gilt:

1. Solche Rulebooks sind zulaessige Input-Artefakte fuer die
   Planungsdomäne.
2. Die kanonische Wahrheit bleibt dennoch das zentrale AK3-
   Planungsmodell mit typisierten Entities, Commands, Events und
   Invarianten.
3. Projekt- oder Agentensyntax darf deshalb nicht die kanonischen
   Grundbegriffe von FK-66 ersetzen, sondern nur auf sie abgebildet
   werden.
4. Jedes Rulebook wird ueber einen offiziellen Compile-Schritt in das
   kanonische Modell uebersetzt; die Rohsyntax selbst ist nie direkte
   Runtime-Wahrheit.
5. Rulebook-Aenderungen sind versioniert (`rulebook_revision`) und
   triggern einen offiziellen Re-Plan statt stiller Hot-Reloads in
   laufende Orchestrierung hinein.
6. Ein Rulebook darf nur ueber offizielle Admin- oder
   Control-Plane-Pfade aktualisiert werden, nicht durch freie
   Agentenmutation im Projekt.

## 66.8 Orchestrator-Vertrag

Der Orchestrator ist Konsument der Planungsdomäne, nicht ihr
beliebiger Autor.

Er darf nicht direkt entscheiden:

- welche Story als naechste gestartet wird
- wie stark parallelisiert wird
- ob ein externer oder menschlicher Blocker ignoriert wird

Er arbeitet stattdessen gegen offizielle Planungsresultate wie:

- `ready_candidates`
- `blocked_stories`
- `recommended_batch`
- `max_allowed_batch`
- `critical_path`
- `next_wave`
- `why_not_now`

Der Orchestrator meldet relevante Planungsverbrauchsereignisse wieder
zurueck, insbesondere:

- Batch wurde gestartet
- Kapazitaetsbudget wurde belegt oder frei
- Wave ist abgeschlossen oder kollabiert
- Re-Plan wurde wegen Laufzeitkonflikt notwendig

Optionale Human-Review darf der Orchestrator anfordern oder sichtbar
machen. Sie ist aber kein implizites Stoppsignal. Ein echter Stopp
entsteht nur ueber ein typisiertes `HumanGate`.

## 66.9 UI- und API-Folgen

Die Webanwendung braucht spaeter mindestens diese Pflichtsichten auf
die Planungsdomäne:

- Dependency-Graph
- Ready Queue
- Blocked View mit typisierten Gruenden
- Execution-Plan bzw. Wellenplan
- Critical-Path-Sicht
- Parallelisierung nach Repo oder Scope
- Story-Detail mit Abhaengigkeiten, Gates und Blocker-Kontext

Diese Pflichtsichten definieren noch nicht das konkrete UI-Design.
Sie definieren aber, welche planungsbezogenen Informationen AK3
normativ bereitstellen muss.

## 66.10 Komponenten- und Datenfolgen

### 66.10.1 Neue Top-Level-Komponente

AK3 fuehrt `ExecutionPlanningService` als eigene A-Komponente.

Typische Provided Contracts:

- `DependencyGraphPort`
- `ReadinessAssessmentPort`
- `ExecutionPlanPort`
- `SchedulingPolicyPort`

### 66.10.2 Persistenz

Die kanonische Planungssicht gehoert in die zentrale AK3-Datenbank.

Mindestens relevante Familien sind:

- geplante Stories und ihre Planungsmetadaten
- Abhaengigkeitskanten
- Blocker und Gates
- Scheduling-Budgets und Policies
- Rulebook-Revisionen und Compile-Ergebnisse
- berechnete Planungs-Snapshots und Wellen

### 66.10.3 Audit

Wichtige Planungsentscheidungen sind auditable Events:

- Abhaengigkeit erfasst oder geaendert
- Story wurde `READY`
- Story wurde blockiert
- Execution Plan erzeugt oder revidiert
- Scheduling-Entscheidung getroffen
- Human- oder External-Gate aufgeloest
- Rulebook kompiliert oder verworfen
- Wave kollabiert oder neu geschnitten

## 66.11 Invarianten

Normativ gelten mindestens diese Regeln:

1. Keine Story darf `FLIGHT` betreten, solange ein harter Vorgaenger
   nicht `DONE` ist.
2. Eine Story in `BLOCKED_EXTERNAL` oder `BLOCKED_HUMAN` darf nicht
   durch Scheduling heuristisch ueberstimmt werden.
3. Feasibility und Scheduling Policy muessen getrennt auswertbar
   bleiben.
4. `ExecutionWave` und `recommended_batch` sind tenant-scoped und
   duerfen nie projektuebergreifend aggregiert werden.
5. Konflikt- und Vertragsflaechen duerfen nach Freigabe oder
   Producer-`DONE` nicht still weiter mutiert werden, ohne dass AK3
   einen Re-Plan oder Re-Validation-Pfad verlangt.
6. E2E- und Sammel-Gates duerfen erst `READY` werden, wenn alle
   vorgesehenen Vorgaenger in ihrem Pflichtumfang abgeschlossen sind.
7. `soft_story_dependency` beeinflusst nie allein die reine
   Feasibility; sie wirkt nur auf Priorisierung oder Scheduling.
8. Jede Planungsrevision ist idempotent und revisionsgebunden; gleiches
   Eingangssignal darf nicht mehrere konkurrierende Wahrheiten
   erzeugen.
9. Erkanntes Zyklen- oder Deadlock-Verhalten quarantainiert den
   betroffenen Teilgraphen und eskaliert fail-closed, statt das
   gesamte Backlog still weiterlaufen zu lassen.
10. Optionale Human-Review verbessert oder validiert Qualitaet, darf
    aber nie still wie ein blockierendes Human-Gate behandelt werden.

## 66.12 Offene Konsequenzen fuer Folgekapitel

Dieses Kapitel zieht die Planungsdomäne normativ ein. Folgekapitel
muessen darauf abgestimmt werden:

- FK-21 fuer planungsrelevante Story-Erzeugungsmetadaten
- FK-12 fuer den aktuellen GitHub-Adapterpfad
- FK-63 fuer spaetere Pflichtsichten im Story-Cockpit
- FK-65 fuer die explizite Komponentenverankerung
- FK-91 fuer Control-Plane-Endpunkte und Planungs-Events
