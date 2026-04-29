# AgentKit 3
# Deterministische Orchestrierungsmaschine fuer KI-gestuetzte Story-Abarbeitung

## Project Context
Tech: Python 3.11+ (`pytest`, `pytest-cov`, `pytest-asyncio`, `mypy` strict, `ruff`), Pydantic v2, PyYAML, psutil | Optional: `weaviate-client`, `mcp[cli]`

Repository: `T:/codebase/claude-agentkit3` — Python-Paket mit `src/`-Layout, Tests, Konzeptdokumenten und deploybaren Zielprojekt-Assets.

Key references:
- `PROJECT_STRUCTURE.md` — verbindliche Verzeichnisstruktur und Modulgrenzen
- `concept/domain-design/00-uebersicht.md` — fachliche Gesamtuebersicht
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` — Architekturprinzipien und Trust Boundaries
- `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md` — Zustaende, Artefakt-Ownership, Invarianten
- `guardrails/architecture-guardrails.md` — architektonische Leitplanken
- `guardrails/testing-guardrails.md` — Pipeline- und Negativpfad-Testpflichten
- `pyproject.toml` — Paket-Metadaten sowie pytest/mypy/ruff/Coverage-Konfiguration

### Was ist AgentKit 3?

AgentKit 3 ist die Neuausrichtung nach den Strukturproblemen von v2. Das System ist bewusst so gebaut, dass die zwei grossen v2-Fehler nicht wieder auftreten:

- **Kein operatives JSON-Flickwerk ohne Owner**: fachliche Verantwortung ist in Modulen, Domänenmodellen, Artefaktklassen und Producer-Registries klar zugeordnet.
- **Keine monolithische Workflow-Datei**: Workflows und Phasen sind entlang fachlicher Einheiten geschnitten (`pipeline/phases/`, `pipeline/workflow/`) statt als riesige imperative Steuerdatei.

AgentKit 3 ist kein Agent selbst. Es ist die Maschine, die Story-Ausfuehrung, Guardrails, QA, Telemetrie und Closure deterministisch orchestriert und nur dort LLMs einsetzt, wo kreative oder bewertende Arbeit wirklich noetig ist.

#### Die 5-Phasen-Pipeline

Jede Story durchlaeuft einen festen, fachlich definierten Ablauf:

| Phase | Typ | Zweck |
|---|---|---|
| **1 — Setup** | deterministisch | Kontext ableiten, Worktree vorbereiten, Guards aktivieren, Prompt-/Runtime-Kontext vorbereiten |
| **2 — Exploration** | LLM (optional) | Entwurfsartefakt fuer explorative Implementierungsstories |
| **3 — Implementation** | LLM | Worker setzt Story um und liefert Handover-Artefakte |
| **4 — Verify** | deterministisch + LLM | Mehrschichtige QA mit klaren Stage-Definitionen |
| **5 — Closure** | deterministisch | Integrity-Gate, Merge/Cleanup, Abschluss, Telemetrie/KPIs |

#### Verify — Schichten statt Ad-hoc-Pruefungen

- **Layer 1 — Structural**: deterministische Checks, Artefakt- und Build-/Test-Pruefung
- **Layer 2 — LLM-Evaluations**: QA-Review und Semantic/Guardrail-Review als Bewertungsfunktionen, nicht als frei handelnde Agents
- **Layer 3 — Adversarial**: gezielte Edge-Case-Pruefung fuer codeproduzierende Stories
- **Layer 4 — Policy Engine**: deterministische Aggregation entlang Trust-Klassen und Stage-Registry

#### Zustandsmodell in v3

v3 trennt bewusst:

- **StoryContext** fuer langlebige Story-Semantik
- **PhaseStateCore / PhasePayload / RuntimeMetadata** fuer Laufzeitstatus
- **QA-Artefakte mit Envelope + Producer** fuer verifizierbare Ergebnisse
- **Telemetrie zur Laufzeit in SQLite**, nicht als unkontrollierter JSON-Dateifaecher

JSON gibt es weiterhin fuer klar definierte Artefakte und Envelopes. Operative Wahrheit entsteht aber nicht aus einem ungeordneten Sammelsurium loser Dateien, sondern aus typisierten, ownership-klaren Modellen und deterministischen Laufzeitregeln.

## Guardrails

### ZERO DEBT RULE
Every deliverable must be fachlich vollstaendig im vereinbarten Scope. Keine stillen Restluecken, keine TODO-Verschiebungen, keine "spaeter sauber machen"-Strategie.

- Wenn etwas fehlt, blockiert oder ohne zusaetzlichen Kontext nicht sauber loesbar ist: explizit melden.
- Keine Attrappen fuer produktive Kernlogik.
- Keine halbfertigen Architekturuebergaenge, die alte und neue Modelle parallel herumtragen.

### FIX THE MODEL, NOT THE SYMPTOM
Die v2-Erfahrung ist hier lehrreich: Fehler entstehen oft durch unklare Ownership, implizite Datenfluesse und versteckte Zustandskopien. Deshalb gilt:

- Keine zweite operative Wahrheit neben dem definierten State-/Artefaktmodell aufbauen.
- Keine "schnellen" Schattenfelder, Hilfsdateien oder Seitentabellen einfuehren, wenn dafuer bereits ein fachlicher Owner existiert.
- Keine neue Imperativsteuerung in einer Zentraldatei hochziehen, wenn Workflow, Stage oder Phase fachlich bereits modelliert ist.

### SINGLE SOURCE OF TRUTH IST PFLICHT

- Deployte Zielprojekt-Dateien existieren genau einmal unter `src/agentkit/resources/target_project/`.
- Produktionscode liegt nur unter `src/agentkit/`.
- `resources/` enthaelt Dateien, aber keinen Python-Code.
- `var/` ist ephemer und niemals fachliche Wahrheit.
- GitHub-Felder sind Eingabe fuer Setup, aber nicht die operative Wahrheit waehrend eines Runs; danach gilt der autoritative Snapshot/State des Runs.

### FAIL-CLOSED
Unklare oder unvollstaendige Zustaende werden nicht grosszuegig toleriert.

- Fehlende Artefakte, ungueltige Envelopes, unbekannte Stage-IDs oder inkonsistente Producer sind Fehler.
- Fehlende externe Systeme, kaputte Konfiguration oder verletzte Vorbedingungen werden nicht wegerklaert.
- Warnungen sind keine Dekoration. Root Cause analysieren und beheben.

### SEVERITY-SEMANTIK

Drei Stufen, klar abgegrenzt:

- **PASS** — fehlerfrei, kein Handlungsauftrag.
- **WARNING** — Handlungsauftrag mit aufschiebender Wirkung. Etwas muss
  gemacht werden, aber nicht sofort. Ein Warning darf **nicht** ignoriert
  oder weggeklickt werden. Wer einen Warning erzeugt oder erbt, hat die
  Pflicht, ihn aktiv an den Auftraggeber zu spiegeln mit der Frage „wie
  wollen wir hier vorgehen". Stilles Liegenlassen ist Verstoss gegen
  ZERO DEBT.
- **ERROR** — Handlungsauftrag ohne aufschiebende Wirkung. Sofort
  beheben. Keine Bypässe, keine Workarounds.

Nicht jeder Befund braucht einen Warning-Pfad. Wo aufschiebbares Handeln
in der Praxis nicht passiert (Erfahrung: Warnings gehen unter), ist
ERROR die richtige Wahl. Ein Befund, fuer den niemand spaeter Zeit
bekommt, ist im Effekt ein ignorierter Befund.

### NO ERROR BYPASSING

- Bei Test-, Build-, Lint-, Typ- oder Guard-Fehlern wird die Ursache behoben.
- Keine Umgehungspfade, die Validierung, Guards oder Stage-Pruefungen aushebeln.
- Keine heimlichen Fallbacks auf schlechtere Datenqualitaet oder weichere Regeln.

### MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL
Mocks und Stubs sind nur erlaubt, wenn

1. der User sie explizit verlangt oder
2. ein isolierter Unit-Test technisch sonst nicht moeglich ist.

Auch dann nur minimal und begruendet. Standardfall sind echte Komponenten, echte Artefakte, echte Integrationspfade.

### STRUKTURREGELN DES REPOS SIND VERBINDLICH

- Keine neuen Top-Level-Verzeichnisse ohne User-Consent.
- Keine Zielprojekt-Struktur im Repo-Root spiegeln.
- Keine losen Python-Dateien im Root.
- Keine zirkulaeren Abhaengigkeiten.
- Module entlang fachlicher Verantwortungen schneiden, nicht entlang kurzfristiger Implementierungsbequemlichkeit.

### WORKFLOW- UND STATE-DISZIPLIN

- Workflow-Logik gehoert in `pipeline/` und deren fachliche Untereinheiten, nicht in neue God-Services.
- Story-Typ-Routing, Stage-Geltung und Guard-/Gate-Regeln werden typisiert modelliert, nicht in String-/Flag-Kaskaden versteckt.
- Artefakte brauchen klaren Producer und klaren Owner.
- QA-Artefakte sind geschuetzt; Worker duerfen ihre eigenen QA-Ergebnisse nicht manipulieren.

## Work Modes

Zwei exklusive Arbeitsmodi pro Aufgabe:

- **Worker**: selbst umsetzen, optional kleine Sub-Tasks delegieren
- **Orchestrator**: koordinieren, aber nicht nebenbei die Facharbeit selbst miterledigen

Nicht mischen. Rollentrennung ist ein fachliches und technisches Prinzip von AgentKit 3.

### Sub-Agent Rules

- Erste Zeile jedes Sub-Agent-Auftrags: `Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.`
- Sub-Agents bekommen alle relevanten Referenzen, Pfade und Erfolgskriterien.
- Kein "done" ohne Beleg: Diff, Tests, Artefakte, Logs oder andere pruefbare Evidenz.
- Kleine, verifizierbare Aufgaben schneiden. Keine God-Tasks.
- Ergebnisse aktiv pruefen, nicht blind uebernehmen.

## Arbeitsdisziplin

### Feasibility zuerst
Vor Codeaenderungen:

1. relevante Konzepte/Guardrails identifizieren
2. Ist-Zustand lesen
3. Delta zum Zielbild bestimmen
4. Design-Entscheidung treffen
5. erst dann implementieren

Wenn die notwendigen Informationen fehlen oder ein Konzeptkonflikt vorliegt: stoppen und explizit machen.

### Konzepttreue ist Pflicht
Alle Aenderungen muessen mit `concept/` und `PROJECT_STRUCTURE.md` vereinbar sein.

- Konflikt mit Fach- oder Technikkonzept: hart stoppen, Konflikt benennen, keine implizite Abweichung implementieren.
- Bestehenden Code, der dem Zielbild widerspricht, nicht durch neue Workarounds stabilisieren; stattdessen am Zielbild ausrichten.

### Anti-Loop
Nach zwei gescheiterten Versuchen mit derselben Methode:

- Methode wechseln
- Ursache bottom-up isolieren
- Invarianten, Unit-Tests und Phasengrenzen separat pruefen

Ratespiel ist hier kein akzeptabler Modus.

## Python Coding Rules

### Code Quality

- `from __future__ import annotations` in jedem Modul
- vollstaendige Type Hints
- `mypy` strict ohne unerklaerte `type: ignore`
- `ruff` ohne unerklaerte `noqa`
- Pydantic v2 fuer Konfigurationen, Artefaktmodelle und andere strukturierte Daten
- Google-Style-Docstrings fuer oeffentliche Klassen/Funktionen
- `snake_case` fuer Funktionen/Variablen/Module, `PascalCase` fuer Klassen

### Architektur

- Produktionscode nur in `src/agentkit/`
- Fachlogik nicht in `integrations/` oder `utils/`
- `integrations/` bleiben duenne Adapter
- `resources/` bleibt Python-frei
- Orchestrierung und Geschaeftslogik trennen
- Seiteneffekte an die Raender, Kernlogik moeglichst rein
- Immutability und unidirektionaler Datenfluss als Default

### State und Artefakte

- Keine neuen ungetypten Zustandsdateien ohne klares Fachmodell
- Kein manueller Hidden-State ausserhalb der dafuer vorgesehenen Modelle/Artefakte
- Artefakt-Envelopes, Producer-Registry und Stage-Definitionen respektieren
- Telemetrie-/State-Formate nur aendern, wenn die Konzeptbasis und die Contract-/Golden-Tests mitgezogen werden

## Tests

### Pflichtregeln

- Neue Business-Logik braucht Unit-Tests.
- Bugfix braucht reproduzierenden Test.
- Pipeline-Schritte muessen Negativpfade an Phasengrenzen beweisen.
- Tests duerfen produktiven Pipeline-State nicht als Abkuerzung manuell zusammenfantasieren, wenn er im echten Lauf durch Vorgaengerphasen erzeugt wird.
- Gueltige und ungueltige Uebergaenge des Workflow-Graphs muessen verprobt werden.

### Testebenen

- `tests/unit/` fuer reine Logik
- `tests/integration/` fuer szenariobasierte Zielprojekt- und Dateisystemablaeufe
- `tests/contract/` fuer Stabilitaet von Schemas, Snapshots, Prompts und Manifests
- `tests/e2e/` nur opt-in, nie Standard-CI

### Coverage

- Mindestgrenze: 85%
- Eine Aenderung, die die Gesamtabdeckung unter die Schwelle zieht, ist blockierend.

## Operations

### Standard nach Codeaenderungen

- `pip install -e ".[dev]"`
- `pytest`

Wenn oeffentliche Schnittstellen, Kernzustandsmodelle oder breit wirksame Pipeline-Logik geaendert wurden, ist nicht nur ein schmaler Ausschnitt zu pruefen.

### Weitere Qualitaetschecks

- `ruff check src tests`
- `mypy src`

### Temp- und Laufzeitdaten

- Ephemere Dateien nach `var/` oder Test-`tmp_path`
- Keine generierten Dateien in `tests/fixtures/`
- Keine temporären Hilfsartefakte im Repo herumliegen lassen

## Mindset

### Prioritaet
User instruction > konkrete Projektregeln in diesem Dokument > kanonische Konzepte/Strukturvorgaben > allgemeine Heuristiken.

### Zielbild
AgentKit 3 ist explizit der Gegenentwurf zu v2:

- klare fachliche Schnitte statt God-Files
- definierte State-Owner statt JSON-Wildwuchs
- deterministische Orchestrierung statt impliziter Ablaufmagie
- typisierte Artefakte und Stages statt loser String-Konventionen

Jede Aenderung muss dieses Zielbild verstaerken, nicht unterlaufen.

### Was gute Arbeit in diesem Repo bedeutet

- fachliche Verantwortung klarer machen, nicht diffuser
- Determinismus ausbauen, nicht durch agentische Sonderpfade erodieren
- Tests an echten Phasengrenzen fuehren, nicht an kuenstlich gebastelten Ersatz-Zustaenden
- bestehende Guardrails ernst nehmen und bei Konflikten nicht kreativ umgehen

Wenn unklar ist, wo etwas hingehoert, ist das ein Architekturproblem, kein Freibrief fuer ad-hoc Code.
