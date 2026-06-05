---
concept_id: DK-00
title: Fachkonzept-Übersicht
module: meta
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: domain-overview
defers_to: []
supersedes: []
superseded_by:
tags: [domain-overview, navigation, agentkit, architecture]
formal_scope: prose-only
---

# AgentKit — Fachkonzept-Übersicht

**Status:** Konsolidiert aus agentkit-domain-concept.md + agentkit-overview.md
**Datum:** 2026-04-02

## Kernauftrag

AK3 gewährleistet ein hochqualitatives E2E-Ergebnis in der autonomen,
agentischen AI-Software-Entwicklung und ermöglicht so eine stärkere
Skalierbarkeit agentischer Entwicklungsprozesse. Seine Aufgabe erfüllt
AK3, indem es autonome AI-Agents mit Methoden, Prozessen und Werkzeugen
unterstützt, Aktivitäten überwacht und dabei Fehlverhalten aktiv
unterbindet, eigenständig Qualitätssicherung betreibt. AK3 konzentriert
sich auf die Phase der Implementierung und verbindet das mit Lösungen
für vor- und nachgelagerte Phasen, um einen holistischen Gesamtansatz
zu ermöglichen.

Dieser Kernauftrag ist die normative Grundlage. Alle Architekturentscheidungen,
Komponentenschnitte und Werkzeugwahl müssen sich an ihm messen lassen. Story,
Phase, Pipeline, Stage, Worker, Worktree und Verify-Layer sind die *Methoden*,
mit denen AK3 diesen Kernauftrag operationalisiert — nicht der Auftrag selbst.
Bei Konflikten zwischen Operationalisierung und Kernauftrag gilt der Kernauftrag.

## Teilkonzepte

| Nr. | Dokument | Domäne |
|-----|----------|--------|
| 01 | [01-rollen-und-llm-einsatz.md](01-rollen-und-llm-einsatz.md) | Spezialisierte Rollen und LLM-Einsatz |
| 02 | [02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md) | Deterministische Pipeline-Orchestrierung |
| 03 | [03-governance-und-guards.md](03-governance-und-guards.md) | Fail-Closed Governance |
| 04 | [04-qualitaetssicherung.md](04-qualitaetssicherung.md) | Mehrstufige Qualitätssicherung |
| 05 | [05-telemetrie-und-metriken.md](05-telemetrie-und-metriken.md) | Telemetrie, Metriken und KPIs |
| 06 | [06-are-integration.md](06-are-integration.md) | Agent Requirements Engine |
| 07 | [07-failure-corpus.md](07-failure-corpus.md) | Failure Corpus als Lernschleife |
| 08 | [08-installation-und-bootstrap.md](08-installation-und-bootstrap.md) | Projektregistrierung und Bootstrap |
| 09 | [09-tools-und-skills.md](09-tools-und-skills.md) | Tool-Governance (CCAG) |
| 10 | [10-story-lifecycle-und-erstellung.md](10-story-lifecycle-und-erstellung.md) | Story-Lifecycle und Story-Erstellung |
| 11 | [11-review-qualitaetsverbesserung.md](11-review-qualitaetsverbesserung.md) | Review-Qualitätsverbesserung |
| 12 | [12-skills-und-skill-system.md](12-skills-und-skill-system.md) | Spezialisierte Skills und Skill-System |
| 13 | [13-kpis-und-optimierung.md](13-kpis-und-optimierung.md) | KPIs und nachgelagerte Optimierung |
| 14 | [14-project-management.md](14-project-management.md) | Project-Management (Project-Entitaet, ID-Praefix-Schema, Konfiguration) |
| 15 | [15-task-management.md](15-task-management.md) | Task-Management (Tasks, Lifecycle, Verlinkung zu Stories/Tasks) |

---

## 1. Zweck

AgentKit ist ein Orchestrierungs- und Governance-Framework für KI-gestützte
Softwareentwicklung im Enterprise-Kontext. Es ermöglicht 1-2 Entwicklern,
eine Flotte autonomer KI-Agenten zu steuern, die 98% der Konzeptions-,
Implementierungs- und Absicherungsarbeit an geschäftskritischen Systemen
(250k+ LOC) leisten. Absicherung bedeutet dabei insbesondere die
Qualitätssicherung und Governance-Durchsetzung nach erfolgter
Implementierung, eine Kernaufgabe, die ebenfalls autonom durch Agenten
erfolgt, nicht durch den Menschen.

Der Mensch agiert dabei nicht als klassischer Entwickler, sondern als
Stratege, Impulsgeber und punktueller Controller. AgentKit liefert die
Infrastruktur, die dieses Betriebsmodell tragfähig macht: deterministische
Prozesse, maschinelle Qualitätssicherung und lückenlose Nachvollziehbarkeit
in einem Maßstab, in dem menschliches Review nicht mehr skaliert.

AgentKit nimmt eine AK3-Story entgegen und führt sie durch eine definierte
Pipeline: von der Kontexterhebung über die Code-Implementierung,
automatisierte Qualitätssicherung bis hin zum Merge und Story-Abschluss.

Der Kern-Gedanke: **Kreative Arbeit (Code schreiben, Reviews) machen
LLM-Agenten. Alles andere — Ablaufsteuerung, Qualitäts-Gates, Merge,
Status-Updates — läuft deterministisch, ohne LLM, ohne Halluzinationsrisiko.**

AgentKit ist kein Agent selbst, sondern die Maschine, die Agenten orchestriert.

## 2. Für wen?

Entwicklungsteams, die LLM-basierte Agent-Harnesses (Claude Code oder
Codex; siehe FK-76) für KI-gestützte Feature-
Implementierung und Bugfixing einsetzen und dabei nachvollziehbare,
auditierbare Qualitätsstandards brauchen. Typischer Einsatz: Projekte mit
regulatorischen Anforderungen oder hohen Qualitätsansprüchen, bei denen
"KI hat Code geschrieben" allein nicht reicht.

## 3. Kernproblem

Autonome KI-Agenten sind produktiv, aber unzuverlässig. Das beobachtete
Fehlverhalten ist dabei kein Ausnahmefall, sondern ein systematisches Muster:

- **Abkürzungen:** Agenten überspringen Schritte, wenn der Weg des geringsten
  Widerstands schneller zum Ziel führt. Statt E2E-Tests durchzuführen,
  behaupten sie, es getan zu haben.

- **PASS by Absence:** Wenn ein Check crasht und keinen Fehler meldet,
  wertet die Pipeline "0 Fehler" als Erfolg. Der gefährlichste Zustand ist
  nicht ein Fehlschlag, sondern ein stiller Nicht-Lauf.

- **Evidence-Fabrication:** Agenten erzeugen plausibel aussehende Artefakte
  (Screenshots, Logs, Protokolle), die keinen realen Prüfvorgang belegen.

- **Kontextverschmutzung:** Zu viel oder irrelevanter Kontext degradiert
  die Leistung. Zu wenig Kontext führt zu Halluzinationen und Scope Drift.

- **Destruktive Aktionen:** Ohne Leitplanken löschen Agenten Tests statt
  Bugs zu fixen, force-pushen auf Main oder überschreiben QA-Artefakte.

- **Scope-Drift aus Hilfsbereitschaft:** Agenten weichen aus guter Absicht
  von ihrer Kernaufgabe ab. Ein Orchestrator, der Stories nur über
  Sub-Agents umsetzen lassen soll, beginnt selbst zu implementieren,
  wenn seine Agents scheitern, verschmutzt dabei seinen eigenen Kontext
  und vergisst seine Steuerungsaufgabe. Agenten setzen Guards außer Kraft,
  um ein Umsetzungsziel zu erreichen, das sie als wichtiger einstufen als
  die Prozesseinhaltung. Das Einzelverhalten wirkt rational, das
  Gesamtergebnis ist destruktiv.

In einem Entwicklungsprozess, in dem der Mensch nur punktuell eingreift,
wird jedes dieser Muster zu einem unkontrollierten Qualitätsrisiko im
Bauvorgang von Systemen, die Trades ausführen oder regulatorische
Berichte erzeugen.

## 4. Säulen im Überblick

AgentKit adressiert diese Herausforderungen über neun Säulen:

**4.1 Spezialisierte Rollen und LLM-Einsatz** (→ [01-rollen-und-llm-einsatz.md](01-rollen-und-llm-einsatz.md)).
Systemische Qualität entsteht aus dem Zusammenspiel spezialisierter Rollen
mit orthogonalen Zielen. Nicht jede Rolle ist ein Agent mit Dateisystem-Zugriff.
LLMs werden auch als Bewertungsfunktion über deterministische Skripte
aufgerufen. Die Rollentrennung wird durch unterschiedliche Aufträge,
unterschiedliche LLMs und unterschiedliche Zugriffsrechte durchgesetzt.

**4.2 Deterministische Pipeline-Orchestrierung** (→ [02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md)).
Der Story-Lifecycle folgt einer festen Phasenfolge. Kein Agent entscheidet
ueber den Ablauf, der Ablauf entscheidet, wann welcher Agent arbeiten darf.
Story-Typ bestimmt die Prozessschwere. Ein deterministischer Kriterienkatalog
entscheidet zwischen Execution Mode und Exploration Mode. Der
Phasenuebergangsgraph wird zur Laufzeit erzwungen — ungueltige Uebergaenge
werden fail-closed blockiert. Der QA-Subflow innerhalb der Implementation-Phase
unterscheidet ueber `verify_context` zwischen Post-Implementation und
Post-Remediation (beide mit voller 4-Schichten-QA).

**4.3 Fail-Closed Governance** (→ [03-governance-und-guards.md](03-governance-und-guards.md)).
Jede Unklarheit ist ein Fehler. Guards verhindern destruktive Operationen,
Schreibschutz sichert QA-Artefakte, ein Prompt-Integrity-Guard kontrolliert
jeden Agent-Spawn auf Governance-Konformität und Template-Treue, ein
Integrity-Gate validiert vor Closure, dass der Prozess durchlaufen wurde.
Eine gestufte Dokumententreue-Prüfung erkennt Konflikte mit bestehenden
Architektur- und Strategiedokumenten. Eine eingebettete Governance-Beobachtung
erkennt Anomalien im laufenden Betrieb über Hook-Heuristiken und
Phasen-Schwellen, verdichtet sie zu Incident-Kandidaten und speist den
Failure Corpus. Ein Worker-Health-Monitor erkennt Stagnation und
Endlosschleifen über ein gewichtetes Scoring-Modell und interveniert
gestuft (Warnung → Selbstdiagnose → Hard Stop). Workers können über
den BLOCKED-Status unlösbare Constraint-Konflikte sauber eskalieren.

**4.4 Mehrstufige Qualitaetssicherung** (→ [04-qualitaetssicherung.md](04-qualitaetssicherung.md)).
Vier Schichten im QA-Subflow innerhalb der Implementation-Phase:
deterministische Checks, parallele LLM-Bewertungen (via Skript),
Adversarial Testing Agent (baut aktiv neue Tests) und Policy-Evaluation.
`verify-system` ist Capability-BC, kein Phase-Owner — die Capability wird
sowohl von Exploration (Exit-Gate) als auch von Implementation
(QA-Subflow) aufgerufen. Jede Subflow-interne Remediation-Iteration
bildet einen atomaren QA-Zyklus mit eigener Identitaet und
Evidenz-Epoche. Artefakte aus vorherigen Zyklen werden invalidiert,
damit keine veraltete Evidenz in die naechste Bewertung einfliesst. Die
Remediation-Schleife ist auf eine konfigurierbare Maximalzahl begrenzt,
danach wird an den Menschen eskaliert.

**4.5 Telemetrie, Metriken und KPIs** (→ [05-telemetrie-und-metriken.md](05-telemetrie-und-metriken.md)).
Protokollierung dort, wo Agents autonom handeln. Die Telemetrie ist
Pruefgegenstand des Integrity-Gates. Workflow-Metriken mit Experiment-Tags
ermoeglichen den quantitativen Vergleich ueber Stories hinweg. KPIs
leiten aus Events und Metriken nachgelagerte Kennzahlen ab, die
Trend-Analyse, LLM-Auswahl und Prozess-Optimierung informieren.

**4.6 Anforderungsvollständigkeit durch Agent Requirements Engine** (→ [06-are-integration.md](06-are-integration.md)).
Optionale externe Säule. Typisierte Anforderungsobjekte mit automatischer
Injektion wiederkehrender Pflichten. Erzwingt Vollständigkeit, nicht
Qualität. Die Zuordnung von Anforderungen zu Stories erfolgt über eine
Scope-Zuordnung: Repositories und Story-Module werden bei der
Installation auf ARE-Scopes abgebildet. Bei der Story-Erstellung leiten
die betroffenen Repos automatisch die passenden Scopes ab.

**4.7 Failure Corpus als Lernschleife** (→ [07-failure-corpus.md](07-failure-corpus.md)).
Beobachtetes Fehlverhalten wird als Artefakt festgehalten. Wiederkehrende
Muster werden in deterministische Checks überführt. Brücke zwischen
nicht-deterministischer LLM-Welt und deterministischer QA-Pipeline.

**4.8 Projektregistrierung und Bootstrap** (→ [08-installation-und-bootstrap.md](08-installation-und-bootstrap.md)).
AgentKit wird systemweit betrieben und registriert Projekte über
idempotente Checkpoints. Im Projekt liegen nur Konfiguration und
harness-spezifische Skill-Bindungen (Claude Code, Codex — siehe
FK-76); der kanonische Inhalt liegt
systemweit bzw. im zentralen State-Backend.

**4.9 Umsetzungsautomatisierung und Werkzeuge** (→ [09-tools-und-skills.md](09-tools-und-skills.md)).
Parameterbasierte Tool-Governance (CCAG) mit sessionübergreifender
Persistenz und LLM-gestützter Regelgenerierung senkt Permission-Reibung.
Spezialisierte Skills standardisieren komplexe Aufgaben und heben die
Ergebnisqualität.

Jede Säule wird in den Teilkonzepten 01 bis 09 im Detail beschrieben.

## 5. Die 4-Phasen-Pipeline mit QA-Subflow innerhalb Implementation

Jede Story durchlaeuft bis zu vier Phasen in fester Reihenfolge.
Jede Phase produziert Artefakte und endet mit einem klaren Status
(COMPLETED, FAILED, ESCALATED). Der QA-Subflow laeuft als Exit-Gate
innerhalb der Implementation-Phase (analog zum Exit-Gate der
Exploration-Phase) und ruft die Capability `VerifySystem` (BC
verify-system).

```
Setup  -->  Exploration  -->  Implementation (inkl. QA-Subflow)  -->  Closure
  |          (optional;          |                                       |
  |          Exit-Gate ruft      |  4-Layer QA-Subflow als               |
  |          VerifySystem)       |  Exit-Gate (ruft VerifySystem)        |
  v                              v                                       v
Kontext          Design-       Worker schreibt Code/Docs;            Merge,
erheben,         Artefakt      QA-Subflow prueft Ergebnis,           Issue
Prompt           erstellen     Subflow-interner Remediation-Loop     schliessen
bauen
```

> **[Entscheidung 2026-05-01]** Eine eigenstaendige Top-Phase `verify`
> existiert nicht mehr. Output-QA ist interner Subflow innerhalb der
> Implementation-Phase. Siehe `concept/_meta/bc-cut-decisions.md`
> "Verify als Capability (Variante Y)".

### Phase 1: Setup (deterministisch)

Liest die AK3-Story aus dem AK3-Story-Backend, erhebt Kontext (Story-Typ, Größe, Scope),
erstellt einen Git-Worktree für Code-Stories, komponiert den Worker-Prompt
aus Templates und persistiert den autoritativen `StoryContext` im
State-Backend. Ein `context.json` kann daraus nur optional exportiert
werden. Kein LLM beteiligt.

### Phase 2: Exploration (optional, agentengesteuert)

Nur für Implementation-Stories im Explorationsmodus. Ein Explorations-Agent
erstellt ein Design-Artefakt, das vor der eigentlichen Implementierung
geprüft und eingefroren wird. Concept- und Research-Stories überspringen
diese Phase.

### Phase 3: Implementation (agentengesteuert)

Ein Claude-Sub-Agent (Worker) wird gestartet und bekommt: den komponierten
Prompt, Zugriff auf das Dateisystem, MCP-Server (VectorDB, ARE) und
optional LLM-Pools (ChatGPT, Gemini) für Multi-Perspektiven-Reviews.

Je nach Story-Typ arbeitet ein anderer Worker-Typ:

| Story-Typ      | Worker                | Was passiert                                   |
|----------------|-----------------------|------------------------------------------------|
| Implementation | Implementation-Worker | Feature-Code, Tests, Doku                      |
| Bugfix         | Bugfix-Worker         | Reproducer-Test schreiben, dann Fix, dann Test  |
| Concept        | Concept-Worker        | Design-Dokumente, Architektur-Entscheidungen    |
| Research       | Research-Worker       | Recherche-Ergebnisse, Analyse-Dokumente         |

Der Worker liefert am Ende: geänderte Dateien, ein Protokoll (`protocol.md`),
ein Manifest (`worker-manifest.json`) und eine Übergabe an QA (`handover.json`).

### QA-Subflow innerhalb Phase 3: Implementation (deterministisch + LLM, 4 Layer)

Vor Phasenabschluss durchlaeuft die Story einen QA-Subflow innerhalb
der Implementation-Phase (analog zum Exit-Gate der Exploration). Der
Subflow ruft die Capability `VerifySystem` (BC verify-system, kein
Phase-Owner). Vier aufeinander aufbauende Pruefschichten:

**Layer 1 — Strukturelle Checks (deterministisch)**
Automatische Prüfungen ohne LLM: Existieren alle Artefakte? Baut der
Code? Laufen die Tests? Sicherheits-Scan? Branch sauber? ARE-Gate bestanden?
Kanonisches Ergebnis: `ArtifactRecord(kind="structural")` im
State-Backend. Ein `structural.json` ist nur ein optionaler Export.

**Layer 2 — Semantisches Review (LLM-Bewertungen via Skript, parallel)**
Zwei LLM-Bewertungen laufen parallel, gesteuert durch deterministische
Python-Skripte über konfigurierte LLM-Pools (nicht als eigenständige
Agents): eine QA-Bewertung (Code-Qualität, Testabdeckung,
Akzeptanzkriterien) und ein Semantic Review (Architektur-Compliance).
Kanonisches Ergebnis: typisierte `ArtifactRecord`-Einträge für
`qa_review`, `semantic_review` und Guardrail-/Conformance-Artefakte.
Dateien wie `semantic_review.json` oder `guardrail.json` sind nur
optionale Materialisierungen.

**Layer 3 — Adversarial Testing (LLM-Agent)**
Ein Agent schreibt gezielt Edge-Case-Tests, führt sie aus und führt
ein Multi-LLM-Sparring (Debatte über Schwachstellen). Nur für
Code-produzierende Stories. Kanonisches Ergebnis:
`ArtifactRecord(kind="adversarial")`; `adversarial.json` ist nur ein
optionaler Export.

**Layer 4 — Policy Engine (deterministisch)**
Aggregiert die Ergebnisse aller Layer unter Berücksichtigung von
Vertrauensklassen: System-Checks (Trust A) dürfen blockieren,
Worker-Aussagen (Trust C) nicht. Entscheidet PASS oder FAIL.
Kanonisches Ergebnis: ein Policy-/Verify-Decision-Record im
State-Backend. `decision.json` oder `verify-decision.json` sind nur
optionale Export- oder Kompatibilitätsartefakte.

**Bei FAIL:** Die Maengel werden in `feedback.json` gesammelt, ein
Remediation-Worker bekommt die Liste, korrigiert den Code, und der
QA-Subflow laeuft erneut — Subflow-intern innerhalb derselben
Implementation-Phase. Maximal 3 Runden, dann Eskalation an einen
Menschen.

### Phase 4: Closure (deterministisch)

Merge nach `main` (fast-forward-only), Worktree aufräumen, AK3-Story
auf Status `Done` setzen, Metriken schreiben, VectorDB aktualisieren
(Story für zukünftige Suchen indexieren), Postflight-Checks.

## 6. Story-Typ-Routing

Nicht jede Story durchläuft alle Phasen gleich:

| Story-Typ      | Worktree? | 4-Layer QA? | Merge? | Typischer Zweck               |
|----------------|-----------|-------------|--------|-------------------------------|
| Implementation | Ja        | Ja          | Ja     | Features, neue Funktionalität |
| Bugfix         | Ja        | Ja          | Ja     | Fehlerbehebungen              |
| Concept        | Nein      | Nein        | Nein   | Design-Dokumente, Architektur |
| Research       | Nein      | Nein        | Nein   | Recherche, Analysen           |

Concept und Research erzeugen keinen Code, brauchen also weder Worktree
noch Merge noch das volle QA-Programm.

## 7. Determinismus-Prinzip

AgentKit trennt strikt zwischen deterministischen und nicht-deterministischen
Schritten:

| Deterministisch (kein LLM)              | Deterministisch mit LLM (Skript)        | Agentengesteuert (LLM)                  |
|-----------------------------------------|-----------------------------------------|-----------------------------------------|
| Setup (Kontext, Prompt, Worktree)       | QA-Subflow Layer 2 (LLM-Bewertungen via Skript) | Implementation Worker-Run     |
| QA-Subflow Layer 1 (strukturelle Checks)|                                         | QA-Subflow Layer 3 (Adversarial Agent)  |
| QA-Subflow Layer 4 (Policy Engine)      |                                         | Exploration (Worker)                    |
| Closure (Merge, Story-Close, Metriken)  |                                         |                                         |

Alles, was deterministisch laufen kann, läuft deterministisch.
LLM-Agenten werden nur dort eingesetzt, wo kreative Arbeit nötig ist.

## 8. Integrationen

### GitHub

GitHub bleibt das Code-Backend für Repositories, Branches, Worktrees,
PRs und Merges. Story-Metadaten und Story-Lifecycle kommen aus dem
AK3-Story-Backend: AgentKit liest die Story-Attribute (Typ, Größe,
Scope) einmalig beim Setup, persistiert sie als `StoryContext` und
setzt am Closure-Ende den Story-Status im AK3-Story-Backend auf `Done`.

### Agent Requirements Engine (ARE) — optional

Anforderungsvollständigkeit. Wenn aktiviert, werden Requirements aus
ARE an die Story gelinkt, der Worker erhält sie als Kontext, reicht
Nachweise (Evidence) ein, und im Verify-Layer prüft ein Gate, ob alle
Pflicht-Requirements abgedeckt sind. Fail-closed: ohne ARE-Bestätigung
kein Merge.

Die Zuordnung von Anforderungen zu Stories erfolgt über eine
Scope-Zuordnung: Repositories und Story-Module werden bei der
Installation auf ARE-Scopes abgebildet. Bei der Story-Erstellung leiten
die betroffenen Repos automatisch die passenden Scopes ab.

### Story Knowledge Base (VectorDB) — optional

Semantische Suche über abgeschlossene Stories. Findet Duplikate vor
der Story-Erstellung und verwandte Vorarbeiten für den Worker-Kontext.
Nach Abschluss wird die Story indexiert.

### LLM-Pools (ChatGPT, Gemini, Grok) — optional

Für Multi-Perspektiven-Reviews und Sparring. Concept-Worker können
parallele Reviews durch andere LLMs anfordern. Der Adversarial-Agent
nutzt Multi-LLM-Debatten zur Schwachstellensuche.

## 9. Artefakte und Nachvollziehbarkeit

Jede Phase hinterlässt Artefakte im zentralen State-Backend; bei
Bedarf können daraus Exportdateien materialisiert werden. Kanonische
Wahrheit sind die Records im Backend, nicht die Dateien:

- `phase_state_projection` — rebuildbares Read-Model des aktuellen
  Laufzeitstatus; `phase-state.json` ist nur Export
- `story_contexts` — kanonischer Story-Context; `context.json` ist nur
  Export
- `artifact_records(kind="structural")` — strukturelle Check-Ergebnisse;
  `structural.json` ist nur Export
- `artifact_records(kind="semantic_review")` — semantische
  Review-Ergebnisse; `semantic_review.json` ist nur Export
- Policy-/Verify-Decision-Record im State-Backend; `decision.json` ist
  nur Export
- `execution-report.md` — Konsolidierter Ausführungsbericht (Zusammenfassung,
  Fehler, Warnungen, Timing, Artifact Health)

Jedes QA-Artefakt trägt kanonisch Producer-/Provenienzfelder im
jeweiligen Record. Exporte übernehmen diese Informationen nur
abbildend; sie sind nie die operative Wahrheitsquelle.

## 10. Konfiguration

Zentrale Konfiguration über `project.yaml` (Pfad: `.agentkit/config/project.yaml`):

- GitHub-Anbindung (Owner, Repo, Project-Nummer)
- Feature-Flags (VectorDB, ARE, Multi-LLM-Pools, Telemetrie)
- QA-Policy (Schwellwerte, Stage-Definitionen)
- Build/Test-Kommandos pro Repository
- ARE-Verbindung (Base-URL, Projekt-Slug)

## 11. Zusammenfassung

AgentKit nimmt eine AK3-Story, lässt einen KI-Agenten die Arbeit
machen, prüft das Ergebnis in vier unabhängigen Qualitätsschichten,
und merged erst, wenn alles besteht — deterministisch gesteuert,
vollständig nachvollziehbar, ohne manuelle Intervention im Normalfall.

Detaildefinitionen (Preflight-/Postflight-Katalog, Feldschema,
Größendefinitionen, Artefakt-Schemata) sind in
[02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md) integriert,
das Telemetrie-Event-Schema in
[05-telemetrie-und-metriken.md](05-telemetrie-und-metriken.md).
