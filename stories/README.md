# AK3 Story-Backlog — Agent-Briefing

Dieses Verzeichnis enthaelt den **operativen Implementierungs-Backlog**
von AgentKit 3. Jede Unterordnerin der Form `AG3-NNN-kurzname/` ist
eine vollstaendig spezifizierte Story-Einheit, die ein Agent
eigenstaendig umsetzen kann.

Zusaetzlich liegen hier Konzept-/Analyse-Dokumente (siehe §10), die
**keine** Story-Pakete sind und nicht abzuarbeiten sind.

## 1. Auftrag fuer den Agenten

> **Du bekommst einen Pull-basierten Auftrag: zieh die naechste
> ausfuehrbare Story aus dem Backlog, implementiere sie vollstaendig
> bis zur Definition of Done, schliesse sie ab, entblocke abhaengige
> Stories — und nimm dann die naechste. Arbeite sequenziell, nicht
> parallel.**

Bevor du irgendetwas tust:

1. Lies `T:/codebase/claude-agentkit3/CLAUDE.md`. Die dort
   formulierten Projekt- und Code-Regeln sind verbindlich.
2. Lies dieses README vollstaendig.
3. Lies `concept/domain-design/00-uebersicht.md` und
   `concept/technical-design/01_systemkontext_und_architekturprinzipien.md`,
   damit du die Architektur verstehst, in die du implementierst.
4. Wenn du AK3 noch nie gesehen hast: lies zusaetzlich
   `concept/_meta/bc-cut-decisions.md` (Bounded-Context-Schnitt) und
   `PROJECT_STRUCTURE.md`.

Erst danach faengst du mit Story-Arbeit an.

## 2. Anatomie einer Story

Jeder `AG3-NNN-kurzname/`-Ordner enthaelt zwei Dateien:

### 2.1 `status.yaml` — autoritativer Status

```yaml
story_id: AG3-018
title: "..."
type: implementation        # implementation | concept | research
status: ready               # ready | blocked | in_progress | completed
phase: setup                # interner Phasen-Anker (meist setup)
created: "2026-05-06"
size: L                     # S | M | L
depends_on: []              # Liste von Story-IDs (autoritativ)
unblocks: ["AG3-019"]       # Liste von Story-IDs (Dokumentation, nicht autoritativ)
```

**Autoritativ ist `depends_on`**. Eine Story darf gestartet werden,
wenn alle in `depends_on` genannten Stories `status: completed` haben.
Das `unblocks`-Feld ist nur Dokumentation der Reverse-Beziehung und
kann lueckenhaft sein — bei Konflikt gilt `depends_on`.

### 2.2 `story.md` — Briefing fuer die Implementation

Jede Story hat dieselbe feste Struktur:

- **Header**: Typ, Groesse, Abhaengigkeiten, Quell-Konzept
- **Kontext**: warum gibt es die Story, welches Problem loest sie
- **Scope** (In Scope / Out of Scope): was ist Teil der Story, was nicht
- **Betroffene Dateien**: Tabelle der Dateien mit Aenderungsart
- **Akzeptanzkriterien**: nummerierte Liste pruefbarer Kriterien
- **Definition of Done**: was muss vor Statuswechsel erfuellt sein
- **Konzept-Referenzen**: FK-/DK-/formal-Anker
- **Guardrail-Referenzen**: welche Projektregeln besonders gelten

Du arbeitest **strikt im Scope**. Was unter "Out of Scope" steht,
ist tabu — auch wenn es naheliegend waere. Wenn eine Story zu eng
geschnitten ist und du beim Implementieren ein Problem siehst, das
nicht abgedeckt ist: **stoppe und melde**, splitte nicht eigenmaechtig.

## 3. Status-Werte und Lebenszyklus

| Status | Bedeutung | Naechster Uebergang |
|--------|-----------|---------------------|
| `ready` | Alle `depends_on` sind `completed`. Story darf gezogen werden. | -> `in_progress` beim Start |
| `blocked` | Mindestens eine Dependency ist nicht `completed`. **Nicht starten.** | wird `ready`, wenn alle Deps `completed` sind |
| `in_progress` | Aktuell in Bearbeitung. **Nur eine Story darf gleichzeitig in_progress sein.** | -> `completed` bei Erfolg, -> `ready` bei Abbruch |
| `completed` | Alle Akzeptanzkriterien erfuellt, alle Definition-of-Done-Punkte abgehakt, gemerged auf `main`. | terminal |

`status.yaml` hat optional ein Feld `completed_at: "<ISO-Timestamp>"`
beim Wechsel auf `completed` (siehe AG3-002 bis AG3-006 als Vorbild).

## 4. Verbindliches Vorgehen pro Story

### 4.1 Story auswaehlen

1. Liste alle Stories mit `status: ready` (siehe §6 Tabelle, oder
   selber `cat stories/AG3-*/status.yaml`).
2. Triff eine Auswahl unter den `ready`-Stories nach folgender
   Heuristik (in dieser Reihenfolge):
   - **Story, die andere entblockt** (`unblocks` nicht leer)
     hat Vorrang vor isolierten Stories.
   - Bei Gleichstand: kleinere Groesse zuerst (`S` vor `M` vor `L`).
   - Bei weiterem Gleichstand: niedrigere Story-ID zuerst.
3. Wenn eine Story `unblocks`-Eintrag X hat, X aber `depends_on`
   Y enthaelt mit Y nicht `completed`: das ist ein Backlog-Drift.
   Halte dich an `depends_on` als autoritativ und melde den Drift
   am Ende des Story-Berichts.

### 4.2 Story starten

1. Setze `status.yaml` auf `status: in_progress`.
2. Lies die Story-Datei `story.md` vollstaendig.
3. Lies die in den **Konzept-Referenzen** genannten FK-/DK-/formal-
   Anker. Diese Konzepte sind die Quelle der Wahrheit fuer
   Architektur-Entscheidungen — nicht das Story-Briefing selbst.
4. Wenn ein Konzept und das Story-Briefing kollidieren: **stoppe
   und melde**. Implementiere keine Abweichung selbstaendig.

### 4.3 Story implementieren

Halte dich an die Code-, Test- und Architektur-Regeln aus
`CLAUDE.md`. Wichtigste:

- Produktionscode nur unter `src/agentkit/`.
- Tests parallel mitschreiben (Pflichtregeln in CLAUDE.md §Tests).
- Keine Mocks/Stubs ausser im engen Ausnahmefall.
- Pflichtbefehle nach Codeaenderungen:
  - `.venv\Scripts\python -m pip install -e ".[dev]"`
  - `.venv\Scripts\python -m pytest`
  - `.venv\Scripts\python -m mypy src`
  - `.venv\Scripts\python -m ruff check src tests`
- mypy strict, ruff clean, Tests gruen, Coverage haelt 85%-Schwelle.
- **Niemals** Python-Pakete global installieren; AK2 und AK3 teilen
  den Package-Namen `agentkit`. Globale Installs zerstoeren AK2.

### 4.4 Story abschliessen

Eine Story darf nur dann auf `completed` gesetzt werden, wenn:

1. Alle nummerierten **Akzeptanzkriterien** der `story.md` erfuellt
   sind.
2. Die Definition-of-Done-Punkte abgehakt sind.
3. Validatoren gruen sind (testsuite, mypy, ruff, ggf. concept-
   validators wenn Konzepte angefasst wurden).
4. Die Aenderungen committed und auf `main` gemerged sind. Pro Story
   typischerweise **ein** thematischer Commit, bei umfangreichen
   Stories mehrere kleinere; jeder Commit gehoert zu dieser Story.

Reihenfolge beim Abschluss:

1. Setze `status.yaml` der Story auf `status: completed`, fuege
   `completed_at` mit aktuellem ISO-Timestamp hinzu.
2. Pruefe alle Stories mit dieser Story in `depends_on`. Wenn alle
   ihre Dependencies jetzt `completed` sind, setze sie von `blocked`
   auf `ready`.
3. Committe die `status.yaml`-Aenderungen als eigenen Folgecommit
   (`Story AG3-XXX: status -> completed; entblockt AG3-YYY`).
4. Push auf `origin/main` (siehe §4.5).

### 4.5 Push-Disziplin

Nach jedem abgeschlossenen Story-Block (Implementation + Status-
Update) auf `origin/main` pushen. Niemals Force-Push, niemals
`--no-verify`. Commit-Nachrichten nutzen das Format aus den
bisherigen Commits (`git log` einsehen).

## 5. Was du nicht ohne Rueckfrage tust

Halte an, melde und warte auf Entscheidung, wenn:

- Eine Story einen Konzept- oder Architekturkonflikt zeigt
  (Konzept widerspricht Story-Briefing oder anderem Konzept).
- Eine Story zu klein/zu gross geschnitten ist (Scope-Drift waehrend
  der Implementation).
- Ein Akzeptanzkriterium technisch nicht erfuellbar ist.
- Tests rot sind und du den Root-Cause nicht klar isolieren kannst
  (siehe Anti-Loop in CLAUDE.md: nach 2 Fehlversuchen Methode wechseln).
- Eine Aenderung ueber den Story-Scope hinaus zu wirken droht
  (Refactoring-Versuchung).
- Du ueber `git push --force`, `git reset --hard`, Branch-Loeschung
  oder andere destruktive Operationen nachdenkst.

**Nicht** ohne Rueckfrage:

- Stories splitten, neu schneiden oder umpriorisieren.
- Akzeptanzkriterien aufweichen oder reinterpretieren.
- Konzept-Dateien aendern, wenn die Story dies nicht explizit
  beauftragt.
- Eigene Stories anlegen (`stories/AG3-NNN-...` neu erstellen).
- Globale Tool-Installs, venv neu anlegen, `pyproject.toml`-Schnitt
  aendern, ohne dass die Story dies vorgibt.

## 6. Backlog-Snapshot — offene Stories

> **Achtung:** Diese Tabelle ist eine **Momentaufnahme**. Autoritativ
> ist immer `status.yaml` jeder einzelnen Story. Bei Drift gilt die
> einzelne `status.yaml`.

### 6.1 In Bearbeitung / Concept

| ID | Titel | Typ | Status |
|----|-------|-----|--------|
| AG3-001 | Workflow-DSL fuer die 5-Phasen-Pipeline | concept | in_progress |

### 6.2 Ready (sofort startbar)

| ID | Titel | Groesse | Entblockt |
|----|-------|---------|-----------|
| AG3-007 | ClosureProgress-Schema: story_branch_pushed + story_closed | S | AG3-008, AG3-009 |
| AG3-010 | setup_worktrees() pro teilnehmendem Repo (Multi-Repo) | S | AG3-011 |
| AG3-012 | StoryAreLink Edge-Tabelle | S | — |
| AG3-013 | CCAG Permission-Runtime und Gate-Keeper-Hook (AK3) | L | — |
| AG3-014 | AK3 Story-Service Backend (Anlage, Status, Dependencies, Attribute) | L | (siehe Drift §6.5) |
| AG3-015 | Prompt-Runtime: Bundle-Pinning, Materialisierung, Audit | L | AG3-011 |
| AG3-016 | Verify-System: agentkit.qa.* -> agentkit.backend.verify_system.* migrieren | M | — |
| AG3-017 | Harness-Hook-Wrapper-CLI: agentkit-hook-claude / agentkit-hook-codex | M | — |
| AG3-018 | Fast-Modus konzeptionell und im Code aufnehmen | L | — |
| AG3-019 | Phase-/Substep-Visualisierung mit Mode-Label im UI-Prototyp | M | — |

### 6.3 Blocked (warten auf Dependency)

| ID | Titel | Groesse | wartet auf |
|----|-------|---------|------------|
| AG3-008 | MultiRepoClosureState im ClosurePayload modellieren | S | AG3-007 |
| AG3-009 | Multi-Repo-Closure-Saga (5-stufig, Pre-Merge-Check, Rollback) | M | AG3-007, AG3-008 |
| AG3-011 | Worker-Spawn mit Worktree-Map (Multi-Repo) | S | AG3-010 |

### 6.4 Bereits abgeschlossen (Referenz)

AG3-002 Auth-Modul Control-Plane (L), AG3-003 SSE-Streaming (M),
AG3-004 Codex-Harness-Adapter (M), AG3-005 Schema-Versionierung (M),
AG3-006 Multi-Harness Installer (S).

### 6.5 Bekannter Backlog-Drift

`AG3-014.unblocks` enthaelt `AG3-007` und `AG3-010`, aber weder
`AG3-007.depends_on` noch `AG3-010.depends_on` enthalten `AG3-014`.
**Lesart**: `depends_on` ist autoritativ, also sind AG3-007 und
AG3-010 weiter `ready` und brauchen AG3-014 nicht. Wenn du den Drift
beim Abarbeiten antriffst, melde ihn — entweder das `unblocks`-Feld
in AG3-014 ist veraltet oder die `depends_on` in AG3-007/AG3-010
fehlen.

### 6.6 Zentralisierungs-/Architektur-Drift-Remediation (AG3-120…133)

Neuer Batch aus der Soll-/Ist-Abweichungsanalyse „Code vs. Konzept
(Zentralisierung)" (Belege: `var/abweichungskarte-zentralisierung.md`).
Beseitigt die Drifts gegen das zentrale-Kern-Leitbild (FK-10 §10.1.0 I1–I6),
die vertikale Kapselung (FK-07 §7.6) und die GitHub-Issues-Altlast. Autoritativ
ist je `status.yaml`; Reihenfolge ist `depends_on`-getrieben (Foundation zuerst).

| ID | Titel | WP | Größe | Status | depends_on |
|----|-------|----|-------|--------|------------|
| AG3-120 | GitHub-Issue-Story-Kopplung entfernen (`issue_nr`-Spine + `issues.py`) | H | L | completed | — |
| AG3-121 | `/v1`-Versions-Handshake: `GET /v1/compat` + Client-Header + 426 | G | M | completed | — |
| AG3-122 | Install-Dreifaltigkeit: `serve`/`update`/`detach`/`decommission` + `install`-Rückbau | F | L | ready | 121 |
| AG3-123 | Phase-Dispatch von lokalem `project_root` entkoppeln (Kern-Worktree-Bindung) | D | L | completed | — |
| AG3-124 | Capability-REST: `pipeline_engine` (503-Stub → Server-Ausführung) | D | L | ready | 123 |
| AG3-125 | Capability-REST: `verify_system`+`closure`+`governance` | D | L | ready | 123 |
| AG3-126 | `story`-BC Read-Port (echte Kapselung statt `state_backend.store`-Re-Export) | I | L | in_progress | — |
| AG3-127 | `telemetry`+`project_management` Read-Ports; BFF entkoppeln | I | M | blocked | 126 |
| AG3-128 | Konformanz-Suite: Repository-Vertrags-Invariante erzwingen (FK-07 §7.6) | I | M | blocked | 126,127 |
| AG3-129 | Hook→Backend: Guard-Counter/Worker-Health/Telemetrie über REST statt Direkt-DB | A | L | blocked | 124,125 |
| AG3-130 | Operator-CLI `run-phase` über REST statt in-process Runtime | A | M | blocked | 123,124 |
| AG3-131 | CCAG Requests/Leases + Mode-Lock-Holder zentral (Postgres+REST) | E | L | blocked | 129 |
| AG3-132 | Drittsystem-Vermittlung Sonar/Jenkins/ARE über Backend | B | L | blocked | 125 |
| AG3-133 | LLM-Hub-Evals in den Kern (C1/C3) + Layer-2 produktiv anbinden | C | L | blocked | 125,129 |

**Sofort startbar (`ready`):** AG3-122, AG3-124, AG3-125. (AG3-120, AG3-121, AG3-123 ✅ completed; AG3-126 in Arbeit.)
**Sequenz-Treiber:** WP-D (123→124/125) ist Fundament für die dev-seitigen
Umstellungen A/B/C/E; WP-I-Read-Ports (126→127→128) laufen unabhängig parallel;
H/G/F sind voneinander unabhängig.

## 7. Konzept- und Guardrail-Bezug

- **Konzepte** unter `concept/` sind die Quelle der Wahrheit fuer
  Architektur, Datenmodell, Pipeline-Phasen, Bounded Contexts und
  formale Spezifikation. Story-Briefings paraphrasieren — bei
  Konflikt gewinnt das Konzept.
- **Guardrails** unter `guardrails/` (Architektur, Tests) sind
  technische Regeln. Diese werden nicht durch Stories aufgeweicht.
- **CLAUDE.md** im Repo-Root ist die normative Verhaltens- und Code-
  Ordnung fuer alle Agenten. Bei Konflikt zwischen Story-Briefing
  und CLAUDE.md gewinnt CLAUDE.md.

## 8. Sonstige Dokumente in `stories/`

Die folgenden Dateien sind **keine** Story-Pakete und werden vom
Agent nicht abgearbeitet. Sie liefern Hintergrund:

- `analyse-worker-phases-konzepte.md`,
  `analyse-worker-phases-code.md` — Analyse-Notizen aus
  Konzept-/Code-Reviews
- `analyse-v2-ballast-begruendungen.md`,
  `entscheidung-v2-ballast-bewertung.md` — v2-Architektur-Bewertung
  (Quelle fuer einige Entscheidungs-Anchor in den Konzepten)
- `handover-orchestrator.md` — Uebergabe-Notizen
- `review-codex-architecture-r1.md` — Codex-Architecture-Review

## 9. Zusammenfassung in einem Satz

Lies CLAUDE.md, ziehe die naechste `ready`-Story nach Heuristik in
§4.1, halte dich strikt an Scope und Akzeptanzkriterien der Story,
schliesse mit gruenen Validatoren und committetem Code ab, entblocke
abhaengige Stories — und nimm dann die naechste.
