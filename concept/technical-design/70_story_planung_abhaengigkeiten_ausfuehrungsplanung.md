---
concept_id: FK-70
title: Story-Planung, Abhaengigkeitsgraph und Ausfuehrungsplanung
module: execution-planning
domain: execution-planning
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
  - target: FK-21
    scope: story-creation
    reason: Story-Erstellung liefert die ersten Planungsmetadaten fuer neue Stories
  - target: FK-07
    scope: component-architecture
    reason: Komponentenschnitt und Top-Surface-Verankerung der Planungsdomaene werden dort normiert
  - target: FK-91
    scope: api-catalog
    reason: Offizielle Control-Plane-Endpunkte und Events fuer Planung werden dort katalogisiert
  - target: FK-63
    scope: dashboard
    reason: Pflichtsichten im Story-Cockpit konsumieren Planungsdaten ueber die Auswertungsschicht
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
glossary:
  exported_terms:
    - id: blocking-condition
      definition: >
        Ein typisierter, erstklassiger Grund, warum eine Story nicht in den
        Status FLIGHT uebergehen darf. Klassen umfassen blocked_internal_dependency,
        blocked_external, blocked_human, blocked_capacity, blocked_conflict und
        blocked_contract. Freitext allein genuegt nicht; Blocker muessen als
        auswertbare Objekte modelliert sein.
    - id: dependency-edge
      definition: >
        Eine explizite Voraussetzungs- oder Einschraenkungsbeziehung zwischen zwei
        Stories oder zwischen einer Story und einem Gate. Unterscheidet mindestens
        hard_story_dependency, soft_story_dependency, serial_execution_constraint,
        mutex_constraint, shared_contract_dependency, shared_file_conflict,
        external_dependency und human_gate_dependency.
    - id: execution-feasibility
      definition: >
        Die objektive Bewertung, ob eine Story unter reiner Betrachtung von
        Abhaengigkeiten, Konflikten, Gates und Invarianten gleichzeitig ausfuehrbar
        waere. Strikt getrennt von ExecutionSchedulingPolicy; darf nie zu einem
        einzigen booleschen Feld kollabieren.
    - id: execution-plan
      definition: >
        Der von AK3 kanonisch abgeleitete und validierte Planungszustand fuer einen
        project_key, bestehend aus critical_path, recommended_batch,
        max_allowed_batch und zugehoerigen ExecutionWaves. Wird nie als
        ungepruefte Agentanantwort behandelt, sondern stets durch den
        ExecutionPlanningService erzeugt und revisionsgebunden persistiert.
    - id: execution-wave
      definition: >
        Eine explizite Gruppe gleichzeitig freigegebener Stories innerhalb eines
        ExecutionPlan. Besitzt einen eigenen Lifecycle (planned, active, completed,
        collapsed) und ist project-scoped. Teilweises Scheitern markiert die Wave
        als collapsed oder loest einen auditierten Re-Plan aus.
    - id: parallelization-policy
      definition: >
        Die Menge der operativen Regeln, die bestimmen, ob und wie stark der
        Orchestrator Stories parallel starten darf. Wirkt nach ExecutionFeasibility
        und ExecutionSchedulingPolicy: hohe theoretische Parallelisierbarkeit
        begruendet keine Pflicht zur maximalen Parallelisierung.
    - id: planned-story
      definition: >
        Eine Story im Backlog oder in Ausfuehrung, fuer die AK3 neben dem
        Story-Inhalt auch Planungsmetadaten kennt (u. a. story_type, story_size,
        participating_repos, planning_status).
    - id: planning-proposal
      definition: >
        Strukturierter, versionierter Uebergabevertrag von einem Agenten an den
        ExecutionPlanningService. Enthaelt vorgeschlagene DependencyEdges,
        BlockingConditions, Gates, Evidenzreferenzen und Provenienz. AK3 validiert
        und normalisiert den Vorschlag; der kanonische ExecutionPlan ist stets eine
        eigene AK3-Ableitung, kein blindes Passthrough.
    - id: readiness-assessment
      definition: >
        Die regelbasierte Auswertung, ob eine Story den Status READY erreicht.
        READY ist kein manuell gesetztes Label, sondern das Ergebnis der Pruefung
        aller hard_story_dependency-Vorgaenger auf DONE, aller offenen Gates und
        aller aktiven Konflikte. Optionale Human-Reviews zaehlen nicht als Blocker.
    - id: scheduling-policy
      definition: >
        Die operative Entscheidungsebene nach ExecutionFeasibility: Darf der
        Orchestrator eine READY Story jetzt tatsaechlich starten, bezogen auf
        Kapazitaets- und Risikobudgets (repo_parallel_cap, merge_risk_cap,
        api_rate_limit_cap, llm_pool_cap u. a.)? Rangfolge: harte
        Graph-Constraints schlagen Budget-Caps, Budget-Caps schlagen
        projektspezifische Rulebook-Hints.
  internal_terms:
    - id: parallelism-budget
      reason: >
        Interne Konfigurationsstruktur mit den konkreten Cap-Werten
        (repo_parallel_cap, merge_risk_cap usw.) fuer einen project_key oder
        tenant. Nicht Teil des oeffentlichen Vertrags; der oeffentliche Begriff
        ist scheduling-policy.
    - id: planning-status
      reason: >
        Das interne Zustandsfeld einer PlannedStory (UNSTARTED, READY, FLIGHT,
        DONE, BLOCKED_*). Implementierungsdetail des State-Machine-Laufs;
        nach aussen relevant als Ergebnis von ReadinessAssessment und
        SchedulingPolicy, nicht als eigenstaendiger exportierter Begriff.
---

# 70 — Story-Planung, Abhaengigkeitsgraph und Ausfuehrungsplanung

<!-- PROSE-FORMAL: formal.execution-planning.entities, formal.execution-planning.state-machine, formal.execution-planning.commands, formal.execution-planning.events, formal.execution-planning.invariants, formal.execution-planning.scenarios -->

## 70.1 Zweck

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

## 70.2 Kernentscheidung

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

## 70.3 Abgrenzung

### 70.3.1 Gegen `PipelineEngine`

`PipelineEngine` fuehrt eine einzelne Story oder einen einzelnen
Story-Run korrekt aus.

`ExecutionPlanningService` entscheidet, welche Stories ueberhaupt in
den Status `READY` kommen, in welcher Reihenfolge sie gestartet werden
duerfen und wie starke Parallelisierung aktuell fachlich und operativ
zulaessig ist.

### 70.3.2 Gegen `DashboardApplication`

`DashboardApplication` praesentiert Planungs- und Laufzeitdaten.

Die Planung selbst ist keine Praesentationslogik. Graph, Blocker, Wave
und Ready-Queue sind nur Sichten auf die Planungsdomäne.

### 70.3.3 Gegen externe Story-/Board-Adapter

Story-Identitaet, -Status und -Attribute liegen ausschliesslich im
AK3-Story-Backend. Optionale externe Spiegelungen duerfen
Planungsinformation read-only abbilden, aber die Ableitung von
`READY`, `BLOCKED`, `execution wave`, `critical path` oder
`recommended batch` ist eine AK3-eigene Fachentscheidung.

## 70.4 Fachliche Begriffe

### 70.4.1 Planbare Story

Eine `PlannedStory` ist eine Story im Backlog oder in Ausfuehrung, fuer
die AK3 neben Story-Inhalt auch Planungsmetadaten kennt.

Mindestens relevant sind:

- `project_key`
- `story_id`
- `story_type`
- `story_size`
- `participating_repos`
- `human_touchpoints`
- `external_prerequisites`
- `planning_status`

### 70.4.2 Abhaengigkeitskante

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

### 70.4.3 Blocker

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

### 70.4.4 Feasibility vs. Scheduling

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

## 70.5 Planungszustand

### 70.5.1 Planungsstatus einer Story

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

### 70.5.2 Wichtige Folgerung

`READY` ist kein manuell gesetztes Board-Label, sondern das Ergebnis
einer regelbasierten Auswertung ueber Abhaengigkeiten, Gates und
Policies.

**Konsistenz mit BC 3 (StoryIdentity / story-lifecycle):** BC 3
fuehrt den Basis-`StoryStatus` als primaere Zustandsachse der Story
(z.B. Backlog, Approved, InFlight, Done). Der `PlanningStatus` in
diesem BC ist eine abgeleitete, planungsspezifische Zustandsebene,
die `ExecutionPlanning` eigenstaendig fuehrt. `PlanningStatus`
und `StoryStatus` sind orthogonale Achsen; `PlanningStatus=READY`
ist eine Ableitung aus Abhaengigkeitsgraph und Policies, kein Spiegel
des GitHub-Board-Status. FK-21 und FK-24 beschreiben die Erstellungs-
und Vertragsebene; `PlanningStatus` wird davon erst nach Freigabe
(StoryStatus=Approved) abgeleitet.

### 70.5.3 Human- und External-Gates

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

### 70.5.4 Zwei Arten menschlicher Mitwirkung

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

## 70.6 Planungsregeln

### 70.6.1 Readiness

Eine Story ist nur `READY`, wenn mindestens gilt:

1. alle `hard_story_dependency`-Vorgaenger sind `DONE`
2. keine aktive `mutex_constraint` verletzt wird
3. keine `serial_execution_constraint` einen offenen Vorgaenger hat
4. kein offener `ExternalGate` oder `HumanGate` fuer diese Story besteht
5. kein expliziter Konfliktzustand an einer geschuetzten
   Vertrags- oder Konfliktflaeche vorliegt

Eine offene optionale Human-Review zaehlt hierbei ausdruecklich nicht
als Blocker.

### 70.6.2 Scheduling

Auch wenn eine Story `READY` ist, darf sie dennoch durch Scheduling
Policy zurueckgestellt werden.

Mindestens diese Budget- und Policy-Dimensionen sind zu
beruecksichtigen:

- `repo_parallel_cap`
- `merge_risk_cap`
- `api_rate_limit_cap`
- `llm_pool_cap`
- `ci_capacity_cap`

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

### 70.6.2a Re-Plan-Trigger

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

### 70.6.3 Trade-off-Regel

Hohe theoretische Parallelisierbarkeit begruendet keine Pflicht zur
maximalen Parallelisierung.

AK3 darf die effektive Parallelisierung bewusst unterhalb des
machbaren Niveaus halten, wenn die Grenzkosten in Form von
Merge-Konflikten, Review-Stau, CI-Latenz oder Human-Overhead den
Nutzen uebersteigen.

Der Orchestrator darf daraus nie implizit ableiten, dass maximale
theoretische Parallelitaet auch operativ gewollt ist.

### 70.6.4 Kritischer Pfad und Wellen

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

## 70.7 Story-Erstellung als Planning-Einstieg

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

## 70.7a Planning-Metadata-Vertrag

Bevor AK3 einen belastbaren Ausfuehrungsplan ableiten kann, braucht
es einen expliziten Planungsmetadaten-Vertrag pro Story.

Dieser Vertrag ist nicht identisch mit der Story-Beschreibung. Er
enthaelt mindestens:

- **Strukturmetadaten**: `participating_repos` (gleichberechtigte
  Liste, keine fachliche Sonderrolle eines Repos),
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

## 70.7b Agent-zu-AK3-Handover-Vertrag

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

## 70.7c Braucht AK3 dafuer eine DSL?

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

## 70.7d Projektspezifische Regelwerke

Projektspezifische Artefakte wie ein `orchestrator-rulebook.dsl`
koennen als Analyse- und Importquelle fuer den `ExecutionPlanningService`
dienen.

**Abgrenzung zur FlowDefinition-DSL (FK-20):** Die Rulebook-DSL von
execution-planning ist NICHT identisch mit der `FlowDefinition`-DSL
aus FK-20 (pipeline-framework). FK-20 beschreibt die
Checkpoint-Engine-Schrittfolge und den Phase-Lifecycle der
PipelineEngine. Die Rulebook-DSL hier beschreibt
Scheduling-Hints, Parallelisierungsregeln, Prioritaetsreihenfolgen
und Konfliktindikatoren fuer den ExecutionPlanningService. Beide DSLs
bestehen parallel; keine ersetzt die andere. Verwechslung fuehrt zu
falschen BC-Grenzen.

Dabei gilt fuer Rulebooks in execution-planning:

1. Solche Rulebooks sind zulaessige Input-Artefakte fuer die
   Planungsdomaene.
2. Die kanonische Wahrheit bleibt dennoch das zentrale AK3-
   Planungsmodell mit typisierten Entities, Commands, Events und
   Invarianten.
3. Projekt- oder Agentensyntax darf deshalb nicht die kanonischen
   Grundbegriffe von FK-70 ersetzen, sondern nur auf sie abgebildet
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

## 70.8 Orchestrator-Vertrag

Der Orchestrator ist Konsument der Planungsdomaene, nicht ihr
beliebiger Autor.

**Normative Pflicht (PipelineEngine-Vertrag):** `PipelineEngine` MUSS
`ExecutionPlanning.evaluate_scheduling` vor jedem Story-Start
aufrufen. Sie darf nicht eigenstaendig in den Backlog greifen oder
eine Story starten, ohne das Ergebnis dieser Top-Surface-Auswertung
abzuwarten. Dieser Vertrag ist in FK-20 §20.8.2 normiert;
execution-planning behaelt hier die fachliche Autoritaet ueber die
Scheduling-Logik.

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

Querverweis: FK-20 §20.8.2 (PipelineEngine-Pflicht).

## 70.8a Execution-Input-Top-Surface (lebend, Doppel-Schnittstelle)

Die Execution-Input-Top-Surface beantwortet zu jedem Zeitpunkt die
Frage: **was kann jetzt maximal an den Orchestrator delegiert werden,
ohne dass die Caps oder die Graph-Feasibility verletzt werden?** Sie
ist **lebend** — jeder Story-Status-Wechsel, jeder Cap-Wechsel, jede
neue Story, jede Dependency-Aenderung loest eine bounded
Re-Evaluation aus (§70.6.2a Re-Plan-Trigger). Damit traegt die
Surface den Druck, die Umsetzungspipeline auf hoher Auslastung zu
halten, ohne dabei die zentralen Caps zu verletzen.

Die Top-Surface hat **zwei fachlich gleiche Auspraegungen** auf
derselben Triage-Logik, mit unterschiedlichen Payload-Formaten — eine
fuer das Frontend, eine fuer den autonomen Orchestrator-Skill. Beide
Auspraegungen pumpen aus **einem** deterministischen Selektor; eine
Doppel-Implementierung ist explizit unzulaessig.

### 70.8a.1 UI-Snapshot

Konsument: Frontend (Story-Cockpit / Execution-Input-View, FK-72).
Endpoint: `GET /v1/projects/{project_key}/execution-input/snapshot`.

Liefert in einem Aufruf:

- `running` — bereits delegierte Stories mit Predecessor/Successor-
  Stack-Format
- `eligibleReady` — Triage-gefilterte Ready-Stories mit Predecessor/
  Successor-Stack-Format
- `totalReady` — Anzahl theoretisch ready (vor Triage)
- `globalSlotsLeft` — verbleibende Slots aus dem globalen Cap

Pflicht: liefert das vollstaendige Bild fuer eine menschlich
gesteuerte Sicht. Eine leere Liste ist eine zulaessige Antwort,
keine `404`. Die Sicht zeigt im Empty-State eine Platzhalter-Saeule
(siehe FK-72 Layout-Invarianten der Execution-Input-View) — die
API-Antwort selbst traegt die leeren Listen plus die Counters.

### 70.8a.2 Agent-Pull

Konsument: Orchestrator-Skill, autonom oder operator-getrieben.
Endpoint: `GET /v1/projects/{project_key}/execution-input/next`.

Liefert pro Aufruf **genau eine** naechste Story (oder `null`,
wenn nichts delegierbar ist), plus eine maschinenlesbare Triage-
Begruendung: Repo-Bucket, Critical-Path-Flag, verbleibende Slots
pro relevanten Cap, aktiver Tiebreaker.

Pflicht: idempotent. Wiederholte Aufrufe ohne Backlog-Aenderung
liefern dieselbe Antwort. Der Skill darf den Endpoint deshalb
nach jedem Story-Abschluss aufrufen, ohne lokale Cache-Logik.
Dieser Pfad ermoeglicht autonomen Pipeline-Pull: nach
Closure-Abschluss zieht der Orchestrator selbststaendig die
naechste Story und beginnt sofort den naechsten Setup-Lauf.

### 70.8a.3 Gemeinsame Triage-Logik

Beide Auspraegungen leiten aus demselben deterministischen
Selektor ab:

1. `globalSlotsLeft = min(merge_risk_cap, max_parallel_agent_cap,
   llm_pool_cap, ci_capacity_cap) - running.length`,
   lower-bounded auf 0.
2. Pro Repo: `repoSlotsLeft = repo_parallel_cap - running_in_repo
   - bereits_im_pick_genutzt`.
3. Bucket pro Repo, intern sortiert nach `critical_path`
   absteigend, dann Story-Nummer aufsteigend.
4. Round-Robin ueber Repos (Repo-Liste alphabetisch sortiert
   fuer Determinismus), bis `globalSlotsLeft` aufgebraucht ist
   oder kein Repo mehr Karten/Slots hat.

Der UI-Snapshot liefert das gesamte Pick-Ergebnis. Der Agent-Pull
liefert die erste Karte des Pick-Ergebnisses.

### 70.8a.4 Determinismus und Re-Plan

- Gleiche Eingabe (Stories, Caps, Stati) liefert identische
  Ausgabe.
- Cap-Aenderung wirkt sofort. Reale Implementierung nutzt
  Optimistic-Update + debounced Backend-Sync; aus Vertragssicht
  ist die Cap-Aktualisierung Pflicht-Trigger fuer Re-Plan
  (§70.6.2a).
- Re-Evaluation triggert §70.6.2a (Story DONE, Blocker, Cap-
  Aenderung, Rulebook-Update, Konfliktflaeche).

### 70.8a.5 Trennung gegenueber bestehenden Planning-Endpoints

`/v1/planning/ready-set` und `/v1/planning/execution-plan`
liefern Planungs-**Detail** (alle ready, blocked, Wave, Critical-
Path). Die Execution-Input-Top-Surface liefert die direkt
delegierbare Teilmenge nach Triage gegen die Caps. Sie ist also
keine Doppelung, sondern die eingeschnittene operative Teilsicht.

## 70.9 UI- und API-Folgen

Die Webanwendung braucht spaeter mindestens diese Pflichtsichten auf
die Planungsdomäne:

- Dependency-Graph
- typisierte Blocker-Sicht als Ableitung aus Story-Status,
  Abhaengigkeiten und Blocker-Kontext
- Execution-Plan bzw. Wellenplan
- Critical-Path-Sicht
- Parallelisierung nach Repo oder Scope
- Story-Detail mit Abhaengigkeiten, Gates und Blocker-Kontext

Diese Pflichtsichten definieren noch nicht das konkrete UI-Design.
Sie definieren aber, welche planungsbezogenen Informationen AK3
normativ bereitstellen muss.

## 70.10 Komponenten- und Datenfolgen

### 70.10.1 Neue Top-Level-Komponente

AK3 fuehrt `ExecutionPlanningService` als eigene A-Komponente (BC 14,
`execution_planning`-Top).

Die Komponente stellt folgende fachliche Top-Surfaces bereit:

- `DependencyGraph` — Schnittstelle fuer Graphaufbau und
  Abhaengigkeitsabfragen
- `ReadinessAssessment` — Schnittstelle fuer regelbasierte
  Readiness-Auswertung
- `PlanDerivation` — Schnittstelle fuer die Ableitung von
  ExecutionPlan, critical_path und ExecutionWave
- `SchedulingPolicy` — Schnittstelle fuer Kapazitaets- und
  Risikobudget-Auswertung

Vokabular-Regel: Diese Surfaces sind Komponenten-Schnittstellen im
fachlichen Sinne, keine Port/Adapter-Abstraktionen. Das Vokabular
"Port", "Adapter-als-Pattern", "Hexagonal" oder "Onion" wird in
diesem BC nicht verwendet.

### 70.10.2 Persistenz

Die kanonische Planungssicht gehoert in die zentrale AK3-Datenbank.
Der Schreibpfad laeuft ausschliesslich ueber `Telemetry.write_projection`
(BC 9, konsistent mit dem BC-9-Pattern aller anderen fachlichen
Projektions-Schreiber). Schema-Owner der Planungstabellen ist BC 14
(`execution-planning`).

Mindestens relevante Schema-Familien unter execution-planning-Owner:

- `planned_story` — geplante Stories und ihre Planungsmetadaten
- `dependency_edge` — Abhaengigkeitskanten
- `blocking_condition`, `gate` — Blocker und Gates
- `scheduling_budget`, `scheduling_policy` — Kapazitaets- und
  Risikobudgets
- `rulebook_revision`, `rulebook_compile_result` — Rulebook-
  Revisionen und Compile-Ergebnisse
- `execution_plan`, `execution_wave` — berechnete Planungs-Snapshots
  und Wellen

### 70.10.3 Audit

Wichtige Planungsentscheidungen sind auditable Events. Die
zugehoerigen `EventTypeId`-Werte sind in FK-68 (BC 9,
`TelemetryContract`) normiert. Nachstehende EventTypeIds gehoeren
zum execution-planning-BC:

| EventTypeId | Bedeutung |
|-------------|-----------|
| `dependency_recorded` | Story-Abhaengigkeit in den Dependency-Graph eingetragen |
| `story_ready` | Story wechselt auf READY |
| `story_blocked` | Story wechselt auf BLOCKED |
| `plan_revised` | Execution-Plan erzeugt oder revidiert |
| `scheduling_decided` | Scheduling-Entscheidung getroffen |
| `gate_resolved` | Human- oder External-Gate aufgeloest |
| `rulebook_compiled` | Rulebook kompiliert oder verworfen |
| `wave_collapsed` | Wave kollabiert oder neu geschnitten |

Definitive Werte- und Schema-Liste: FK-68 §68.3 (EventTypeId-Enum).
Execution-planning-Sicht: FK-68 §68.2.2 (Execution-Planning-Events, BC 14).

## 70.11 Invarianten

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

## 70.12 Offene Konsequenzen fuer Folgekapitel

Dieses Kapitel zieht die Planungsdomäne normativ ein. Folgekapitel
muessen darauf abgestimmt werden:

- FK-21 fuer planungsrelevante Story-Erzeugungsmetadaten
- FK-12 fuer den aktuellen GitHub-Adapterpfad
- FK-63 fuer spaetere Pflichtsichten im Story-Cockpit
- FK-07 fuer die explizite Komponentenverankerung
- FK-91 fuer Control-Plane-Endpunkte und Planungs-Events
