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
| AG3-122 | Install-Dreifaltigkeit: `serve`/`update`/`detach`/`decommission` + `install`-Rückbau | F | L | completed | 121 |
| AG3-123 | Phase-Dispatch von lokalem `project_root` entkoppeln (Kern-Worktree-Bindung) | D | L | completed | — |
| AG3-124 | ⊘ superseded (FK-72 §72.8.2 erden, Commit 95d5ac1): `pipeline_engine/http` redundant zurückgebaut | D | L | superseded | 123 |
| AG3-125 | ⊘ superseded (FK-72 §72.8.2 erden, Commit 95d5ac1): `verify_system`+`closure`+`governance` http redundant zurückgebaut | D | L | superseded | 123 |
| AG3-126 | `story`-BC Read-Port (echte Kapselung statt `state_backend.store`-Re-Export) | I | L | completed | — |
| AG3-127 | `telemetry`+`project_management` Read-Ports; BFF entkoppeln | I | M | completed | 126 |
| AG3-128 | Konformanz-Suite: Repository-Vertrags-Invariante erzwingen (FK-07 §7.6) | I | M | completed | 126,127 |
| AG3-136 | Projekt-Katalog-Read-Surface erzwingen (`load_projects` off-port) + decommission-Reroute | I | S | completed | — |
| AG3-129 | Hook→Backend REST (neu geerdet: control-plane-Routen in `control_plane_http`, kein `governance/http`) | A | L | completed | — |
| AG3-130 | Operator-CLI `run-phase`/`resume` über REST (neu geerdet: kanonische `story-runs`-Route) | A | M | completed | 123 |
| AG3-131 | CCAG Requests/Leases + Mode-Lock-Holder zentral (Postgres+REST) | E | L | ready | 129 |
| AG3-132 | Backend-Validierung der Drittsystem-Erreichbarkeit (Installer prüft nicht mehr direkt, I2) — neu geschnitten + Codex-reviewed | B | L | ready | — |
| AG3-133 | LLM-Hub-Evals in den Kern (C1/C3) + Layer-2 produktiv (neu geerdet: C5 in-process, Eval-Route `control_plane_http`) | C | L | ready | 129 |
| AG3-134 | Skill-Bundle `execute-userstory-core` auf REST/BC-reconciled Orchestrierung migrieren (Bundle spricht noch Vor-REST-Dialekt: `run-phase --story`-only, `run-phase verify`, file-State) + resume-Signatur-Korpus angleichen | A | L | ready | 130 |
| AG3-135 | ⊘ superseded (wird NICHT implementiert): Lease-Fencing-Prämisse fachlich falsch — Auto-Ablauf/Auto-Takeover darf es nicht geben. Ersetzt durch Session-Ownership-Strang (§6.7) | A | M | superseded | — |

**Sofort startbar (`ready`):** AG3-131, AG3-132, AG3-133, AG3-134. (AG3-127, AG3-128, AG3-129, AG3-130, AG3-136 ✅ completed. **AG3-135 ⊘ superseded** → Session-Ownership-Strang §6.7. WP-I-Strang [126→127→128] abgeschlossen; AG3-136 [`load_projects` off-port] als Review-Folge nachgezogen.) (AG3-120, AG3-121, AG3-122, AG3-123, AG3-126, **AG3-130** ✅ completed. AG3-124, AG3-125 ⊘ superseded (FK-72-§72.8.2-Erdung, Commit 95d5ac1). Downstream gegen die rekonziliierte Architektur neu geerdet: **AG3-129** ready; **AG3-133** blocked auf 129; **AG3-132** neu geschnitten + Codex-reviewed → ready.) **AG3-134** (neu) erfasst den bei der AG3-130-Landung verifizierten, vorbestehenden Bundle-/Spec-Drift gegen den REST-Kontrakt (W1+W2); kein AG3-130-Defekt, eigener Scope.
**Sequenz-Treiber:** WP-D (123→124/125) ist Fundament für die dev-seitigen
Umstellungen A/B/C/E; WP-I-Read-Ports (126→127→128) laufen unabhängig parallel;
H/G/F sind voneinander unabhängig.

### 6.7 Session-Ownership & Nebenläufigkeit (neuer normativer Strang, ersetzt AG3-135)

Ausgelöst durch die AG3-135-Analyse: die Nebenläufigkeit von Phasen-/Story-
Mutationen ist **fachlich neu zu fundieren**, bevor Code entsteht. Normative
Regeln (PO-Entscheidung 2026-07-02), noch in den Konzepten zu verankern:

1. **Story-Lifecycle = Eigentum einer Session** (`SessionRunBinding`); der
   gesamte Lifecycle ist an die besitzende Session gekoppelt.
2. **Kein automatischer Ablauf/Entzug.** AgentKit kann client-seitiges Schweigen
   nicht deuten (tot / Langläufer / Pause / wartet auf Benutzereingabe) →
   Ownership läuft NIE automatisch ab; kein Timeout, kein Heartbeat-Entzug.
3. **Übernahme nur explizit & folgenschwer.** Ein anderer Owner (Mensch via UI
   oder Agent via Control-Plane-API — nie ein Automatismus) beantragt die
   Übernahme ausdrücklich; die alte Session wird entmündigt, der handelnde Agent
   wird informiert, dass dies kein Regelbetrieb ist.
4. **Einzige technische Nebenläufigkeits-Garantie:** In-Flight-Idempotenz +
   Serialisierung **pro mutiertem Objekt** (Reads immer frei parallel; Mutationen
   sequenziell pro Objekt, an das Objekt gebunden, nicht an den Aufrufer).

Vorgehen (systematisch, jede Stufe reviewed): (a) Regeln normativ in den
zuständigen BCs/PCs + formal-spec verankern; (b) **Machbarkeits-/Edge-Case-
Review** (Codex für Codebase/DB — insb. „was genau ist das gesperrte Objekt?
Composite-Objekte?"; LLM-Hub für konzeptionelle Lücken); (c) **GAP-Analyse**
Soll↔Ist → fehlende Stories; (d) GAP-Analyse reviewen; (e) neue Stories durch
den regulären akribischen Story-Prozess (mit Reviews); (f) erst dann Umsetzung.
**Kein Teil-Übernehmen der AG3-135-Arbeit** — das Endergebnis wird signifikant
anders.

**Stand 2026-07-02: Schritte (a)+(b) abgeschlossen.** Konzeptentwurf in
`_temp/entwurf-session-ownership-und-nebenlaeufigkeit.md` (3 Review-Runden
Codex+LLM-Hub bis 2× APPROVE; PO-Entscheidungen eingearbeitet: Sperr-Objekt =
Story, Run-Fortführung mit `ownership_epoch`, Branch wird bei Takeover
fortgeführt nie resettet, Agent-Takeover-Request mit menschlicher
Frontend-Freigabe via globalem Overlay). Normative Verankerung in 4
Arbeitspaketen gelandet: FK-56 §56.8a/§56.13 (Run-Ownership-Record,
Ownership-Transfer), formal.operating-modes (+8 Invarianten), FK-17, FK-91
§91.1a Regeln 13–18 + Ownership-Endpoints, FK-10, formal.state-storage/
story-workflow, Disown-Familie (FK-58/53/54/55/20/44/59/30/31), FK-72
(Takeover-UI + globaler Freigabe-Overlay); TTL/PID/Lease-Autofreigabe aus
FK-02/10/15/53/54/71/93 + formal.story-reset/-split entfernt. Finale
Diff-Review (Codex) mit 4 ERRORs → remediert (u. a. neue Entität
`inflight-operation-record`, `defers_to`-Kanten zurückgebaut). Flankierend:
`concept/_meta/konzept-konsistenz-governance.md` (Konsistenz-Prinzipien +
Werkzeuge W1–W4). **Nächster Schritt: (c) GAP-Analyse.**

**Stand 2026-07-02, Nachtrag (K1-Worktree-Topologie verankert):** Die im
Session-Ownership-Strang offen gebliebene Frage K1 ist durch zwei
PO-Entscheidungen vom 2026-07-02 entschieden: **(I) dev-lokale Worktrees** —
das Backend hat nie physischen Worktree-Zugriff (Akteursmodell
Agent/Edge/niemand); **(II) pushed-only** — für AgentKit existiert nur der
gepushte Stand; Übergabeobjekt eines Transfers ist ein SHA
(`takeover_base_sha`), nie ein Dateizustand. Das K1-Delta
(`_temp/entwurf-k1-worktree-topologie.md`, v4; drei Review-Runden
Codex+LLM-Hub, von beiden freigegeben) ist normativ verankert: FK-10
§10.2.4a/§10.2.4b (Topologie, Akteursmodell, Ausführungsort-Grundsatz,
Pushed-only, Sync-Punkte-Hybrid, workspace_locator-Trennung), FK-12
(Ausführungsort Edge, Code-Backend-API nur lesend/verifizierend, §12.1.3
App-Identität + `story/*`-Ref-Schutz), FK-22 (Preflight 7/8 als Edge-Probe
mit differenzierten Befunden), FK-29 §29.1a (Merge-Block via `merge_local`
durch den Edge, Verträge unverändert), FK-56 §56.13c/e (Transfer-Record
statt Snapshot, Worktree-Identitäts-Klassifikation, Quarantäne-Semantik,
Verlustkorridor-Pflichttext), FK-30 §30.6.3 (+`remote_branch_diverged_
after_takeover`, +`local_stale_or_dirty_takeover_target`), FK-31 §31.1.3c
(Salvage-Commit entfällt), FK-91 §91.1b (Edge-Command-Queue) +
Reconcile-Endpoint auf SHA-Semantik, formal.state-storage
(`takeover-transfer-record` ersetzt `takeover-worktree-snapshot`),
formal.operating-modes (Confirm-Signatur), FK-15 §15.5.4/FK-55 §55.9
(App-Identität + Edge-Push-Gate), FK-36/FK-72 (Konsistenz-Anpassungen).
Decision-Record:
`concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`.

**Stand 2026-07-02, Abschluss (c)–(e):** Die GAP-Analyse (Schritt c;
`_temp/gap-analyse-session-ownership.md` v4, Nenner SOLL-001..194 +
IMPL-001..025, Traceability maschinell verifiziert) wurde reviewt
(Schritt d; Codex, 3 Runden bis APPROVE) und in **19 Stories
AG3-137..AG3-155 geschnitten** (Schritt e; Tabelle §6.8). Der Schnitt
durchlief eine doppelte adversariale Review (Codex + ChatGPT, beide
initial REJECT) mit Remediation: 5 zusätzliche Abhängigkeits-Kanten,
minimaler `takeover_reconcile_required`-Blocker bereits im
Confirm-Vollzug (AG3-148), zwei kleine Formal-Nachzüge
(frontend-contracts v3: `repo_push_status` statt K1-widrigem
`worktree_dirty`/`last_commit_sha`; state-storage v5:
`takeover-transfer-record` je Repo) — danach beide APPROVE. Jede Story
trägt eine maschinenlesbare `**Deckt ab:**`-Traceability-Zeile; ein
Prüfskript verifiziert Matrix-Deckung + Graph-Symmetrie.
**Nächster Schritt: (f) Umsetzung via Backlog-Pull (§6.8).**

**Klärungspunkt entschieden (PO-Go 2026-07-02):** Die backend-seitige
Verify-Evidenz-Auflösung (`request_resolver.py` inkl. `shell=True`-
Testausführung, plus die Worktree-Reads des `evidence/assembler.py`)
wird als eigene Story **AG3-156** vom Backend gelöst (Ausführungsort
Edge/Agent, FK-47-/FK-28-Konzept-Nachzug mit P3-Decision-Record im
Story-Scope); siehe §6.8.

### 6.8 Session-Ownership-Umsetzungs-Backlog (AG3-137…AG3-155)

Geschnitten aus der GAP-Analyse §6.7 (Schritt e, 2026-07-02); je Story
Briefing mit SOLL-/IMPL-Rückverweisen, Konzept-Ankern und
Querschnitts-Auflagen (Postgres-only K5, Blutgruppen, Bundle-Assets).
Autoritativ ist je `status.yaml`; Reihenfolge ist `depends_on`-getrieben.

| ID | Titel (Kurzform) | Größe | Status | depends_on |
|----|------------------|-------|--------|------------|
| AG3-137 | Ownership-Schema-Fundament (Records/Claims/Transfer, Backfill) | L | **completed** | — |
| AG3-138 | Instanz-Identität + Startup-Rekonsiliierung + admin_abort | L | **completed** | 137 |
| AG3-139 | TTL-Entfall (Rückbau, NUR nach 138) | S | **completed** | 138 |
| AG3-140 | Einheitlicher Idempotenz-Vertrag (BC-weit, Client-op_id) | L | **completed** | 137 |
| AG3-141 | Objekt-Serialisierung (per-Story-Claims, 409/Retry-After) | L | **completed** | 137, 138 |
| AG3-142 | Ownership-Fencing der Regime-Pfade (`ownership_epoch`) | L | **completed** | 137 |
| AG3-143 | Execution-Contract-Digest + Spec-Freeze | M | **completed** | 137 |
| AG3-144 | Job-Muster + Ergebnisarten + Upsert-Fences | L | **completed** | 141, 142, 143 |
| AG3-145 | Edge-Command-Queue + Worktree-Ops-Umzug | L | **completed** | 137, 141, 142, 146 |
| AG3-146 | Provider-Adapter-Schnitt (ls-remote, gh nur im Adapter) | M | **completed** | — |
| AG3-147 | Sync-Punkte + Push-Gate + Ref-Schutz (pushed-only) | L | **completed** | 145, 146 |
| AG3-148 | Transfer-Kern (Challenge-Confirm-CAS, Approval-Queue) | L | **completed** | 141, 142, 147 |
| AG3-149 | Disown-Baustein + Ex-Owner + Ping-Pong-Schranke | M | **ready** | 148 |
| AG3-150 | Freeze-Admission-Blocker (`freeze_epoch`) | M | blocked | 149 |
| AG3-151 | Takeover-Reconcile + Quarantäne + Edge-Zustände | L | blocked | 145, 148, 149, 150 |
| AG3-152 | merge_local-Umzug (Closure via Edge) | M | **completed** | 145, 147 |
| AG3-153 | Frontend Takeover (globaler governance-Stream, Overlay, Cockpit) | L | **completed** | 144, 148, 151 |
| AG3-154 | CLI/Admin-Kommandos + Edge-Tool (inkl. recover-story) | M | **ready** | 138, 145, 148 |
| AG3-155 | Betriebs-Runbook FK-04 (concept) | S | blocked | 139, 149, 151, 154 |
| AG3-156 | Verify-Evidenz-Ausführungsort: Request-DSL-Resolver + Evidence-Assembler vom Backend-Worktree-Zugriff lösen (Review-Fund, PO-Go 2026-07-02) | L | **completed** | 144, 145 |

**Sofort startbar (`ready`): AG3-149, AG3-154** (Ownership-Strang; AG3-148, AG3-152 und AG3-156 completed). Unabhängige Blätter ausserhalb dieses Strangs: AG3-131/132/133/134/157.**
AG3-156 ✅ **completed** 2026-07-13 — Verify-Evidenz wird als zweistufiger
`collect_verify_evidence`-Edge-Batch über die vorhandene Phase-Yield/Resume-
Grenze erhoben: Basis-Snapshot vor dem einmaligen crash-sicheren Preflight,
danach dynamische Reviewer-Requests. Result-POSTs terminalisieren nur den
CommandRecord; D3 und Bundle-Erweiterung erfolgen beim gefencten Resume.
Backend-Resolver, Assembler und Import-Resolver lesen keine Ziel-Worktrees;
Testkommandos sind typisiert, argumentweise, `shell=False` und hart begrenzt.
P3-Decision-Record, FK-28/33/46/47/91 und der Postgres-Command-Kind-Vertrag
sind nachgezogen; reale Exit-/Reset-Negativpfade verhindern Late-Result-Writes.
(AG3-146 ✅ **completed** 2026-07-05 — Provider-Adapter-Schnitt: neues Backend-BC
`code_backend/` mit schmalem Capability-Port `provider_port.py` (Blutgruppe A,
GitHub-frei/Azure-DevOps-tauglich: keine gh-Argumente/URL-Formen/owner-repo-Slugs im
Port; opake Provider-Koordinaten) + `git_protocol.py` (Blutgruppe T, `git ls-remote`
ohne Worktree für `ref_read`, fail-closed bei nicht auflösbarem Ref/Remote). `gh`
läuft ausschließlich im GitHub-Adapter; `repo_probe`/CP2 gehen über den Port (kein
direkter gh-Subprozess mehr außerhalb des Adapters); fehlendes `gh` = benannter
Capability-Befund, kein Crash. Port-Contract-Suite läuft unverändert gegen den
GitHub-Adapter UND ein Nicht-GitHub-Test-Double (Austauschbarkeit bewiesen). Codex
AC1–AC6 + A-Core-AT-Freiheit APPROVE; einziger REJECT-Grund war ARCH-55-Deutsch in
neuen Docstrings → direkt übersetzt + breiter German-Sweep clean; Jenkins #998 grün,
Sonar-Gate OK / 0 Issues. Entblockt AG3-145. WARNING: das neue BC ist noch nicht in
`concept/formal-spec/architecture-conformance/entities.md` registriert → der
Conformance-Gate erzwingt die A-Core-AT-Freiheit nicht mechanisch fort (manuell + per
AST-Grep-Test belegt); Registrierung ist eine `concept/`-Änderung (PO) — kleiner
Follow-up.
AG3-144 ✅ **completed** 2026-07-05 (status.yaml `completed_at` 10:43:33Z) — Job-Muster
+ Ergebnisarten + Upsert-Fences. Die zuvor hier notierte W2-Arch-Blockade
(phasenübergreifendes Fence-Context-Capture + server-seitiger 202-Execution-Driver)
wurde aufgelöst und die Story abgeschlossen; Abschlussdetails im story-eigenen
`status.yaml`.
(AG3-143 ✅ **completed** 2026-07-04 — Execution-Contract-Digest + Spec-Freeze:
deterministischer `execution_contract_digest` beim Setup-Commit, content-adressiert
über tragende Spec-Felder (FK-59 §59.9a) + `ProjectRegistration.config_version`/
`config_digest` (SSOT) + Skill-/Capability-Versionen + `run-prompt-pin` (FK-44 §44.3);
atomar mit der Start-CAS persistiert, nach Commit read-only (kein UPDATE-Pfad),
fail-closed abgewiesen bei unauflösbarer/malformter Komponente (AC2, u. a.
64-Hex-`config_digest`-Prüfung). Drei Wirkungsklassen (Default `pinned_for_new_runs`).
Spec-Freeze-Gate in `update_story_fields` VOR dem Idempotenz-Record: tragende Felder
bei aktivem Execution-Regime → `409 spec_frozen_during_active_run`, typisierte
Feldklassifikation (unbekannt ⇒ fail-closed tragend), administrative Felder frei; der
Freeze ist bewusst präventiv (heute existiert kein Live-PATCH-Schreibpfad für
StorySpecification-Felder — explizit getestet). Digest-Fence-Prädikat DEFINIERT
(Verwendung in AG3-144). Codex r1 REJECT (skill_versions Total-Order, config-digest
fail-closed, ARCH-55, ehrlicher Freeze-Beweis) → remediated → r2 APPROVE; Sonar-#988-
Cleanup (S1110, Barrel entschlackt, Digest-Assembly aus der Admission-Klasse
extrahiert 922→796 LOC — Sonar/Analyzer unverändert) → Jenkins #990 grün, Sonar-Gate
OK / 0 Issues. Entblockt AG3-144.
AG3-142 ✅ **completed** 2026-07-04 — Ownership-Fencing der Regime-Pfade:
der aktive `RunOwnershipRecord` (AG3-137) ist jetzt die EINZIGE Admissions-
und Fencing-Wahrheit aller mutierenden Regime-Pfade (start/complete/fail/
closure/resume + serverseitiger Executor). Fence = co-transaktionales
`SELECT … FOR UPDATE` auf die aktive Zeile mit `(run_id, owner_session_id,
ownership_epoch)`-Prädikat (kein TOCTOU-Fenster); der Record wird im Setup
atomar mit der Start-CAS gemintet (CAS-Verlierer schreibt keinen Record).
Die committed-op-Heuristik `_run_admission_evidence` wurde durch
`_evaluate_run_admission` abgelöst (positive Heuristik entfernt, Exit-Fence
behalten). Ex-Owner-Fehlerbild `ownership_transferred` → 403 (übrige
Ownership-Ablehnungen 409) + `OwnershipTransferredDetail`-Payload; Reads
bleiben sperrenfrei. Fail-closed: ein genuin neuer `run_id` für eine Story
mit noch aktivem Record wird als RUN_MISMATCH gefenced (das Disown-/Reset-
VERHALTEN liegt in AG3-149). Codex verifizierte die Fence-Substanz und
adjudizierte den Single-Connection-PG-Fence-Test als adäquat für diesen
Scope (echter 2-Connection-Takeover-Race → AG3-148); r1-REJECT betraf nur
zwei ARCH-55-Docstrings (behoben), r2 APPROVE. Jenkins #984 grün, Sonar-Gate
OK / 0 Issues (nach S3358-Ent-Schachtelung des Fence-Reason-Strings).
AG3-141 ✅ **completed** 2026-07-04 — Objekt-Serialisierung, **nur per-Story**:
durabler per-Story-Objekt-Claim vor Dispatch (Claim→Dispatch→Finalize/Abort),
Crash→Reconcile/admin_abort-Freigabe, K4 `409 + Retry-After` (kein
Thread-Blocking), Reads sperrenfrei, kein Wanduhr-Verfall. Das ursprünglich
geschnittene **projektweite Sperrobjekt + Lock-Sets + Queue-Fairness** wurden
nach zwei unabhängigen Analysen (Codex + Fable: kein realer Aufrufer) als
anforderungslos **entfernt** und die Konzepte FK-91 Regel 13 / FK-10 §10.5.4 /
FK-17 §17.5 / FK-54 §54.8.2a + die formale Invariante
`pending_project_claims_...` entschlackt (Codex-Concept-Review r3 APPROVE).
Jenkins #979 grün, Sonar-Gate OK / 0 Issues.
AG3-140 ✅ **completed** 2026-07-04 — Einheitlicher Idempotenz-Vertrag
(BC-weit): serverseitiges op_id-Minten entfernt, alle mutierenden Routen unter
den Vertrag (claim→body-hash→finalize; replay/409-mismatch/in-flight),
guard-counter + control-plane inkl. operation_kind-Diskriminator; 7 Codex-Runden
(finale 2 Befunde = fehlende Regressionstests + Matrix-Ehrlichkeit, direkt
nachgezogen), Jenkins #973 grün, Sonar-Gate OK / 0 Issues.
AG3-137 ✅ **completed** 2026-07-02 — Ownership-Schema-Fundament.
AG3-138 ✅ **completed** 2026-07-03 — Instanz-Identität + Startup-
Rekonsiliierung + admin_abort abgeschlossen (Best-of-Breed auf sonnet-Basis,
Opus-AC10-Mutationssperre eingearbeitet): Codex-Review APPROVE (r3) +
SonarQube 0 Issues overall + volle Gate-Suite grün (8354, 91.87 %);
E1-Posture PO-bestätigt. Entblockte AG3-139 + AG3-141.
AG3-139 ✅ **completed** 2026-07-03 — TTL-Entfall (Rückbau Claim-Lease-TTL
+ CAS-Auto-Takeover): Codex-Substanz-APPROVE (r3 PP1-3) + SonarQube 0;
der rote Jenkins-Build 949 war ein last-induzierter Flake in einem
fremden Test (`test_concurrent_opposite_acquires_cannot_both_pass`,
SQLite-Bootstrap-Race), PO-Abschluss mit Blick auf den anschließenden
Test-/Docker-Infrastruktur-Umbau. Entblockt AG3-155 nur teilweise
(braucht zusätzlich 149/151/154 → bleibt blocked).)

**Sequenzieller Ausführungsplan (gültige topologische Reihenfolge):**
Die IDs wurden topologisch vergeben; aufsteigende Abarbeitung ist
gültig — mit genau **einer** Ausnahme aus der Schnitt-Review:
**AG3-146 vor AG3-145** (Provider-Adapter liefert die
`ls-remote`-Lesefläche der Command-Queue). Verbindliche Sequenz:

> AG3-137 → 138 → 139 → 140 → 141 → 142 → 143 → 144 → **146 → 145**
> → 147 → 148 → 149 → 150 → 151 → 152 → 153 → 154 → 155 → 156
> (→ 157 → 158 → 159 → 160, §6.9 — eigener Strang, jederzeit
> einschiebbar, da ohne Kanten in den Ownership-Strang)

Autoritativ bleibt je Story `status.yaml.depends_on` (§2.1): Vor dem
Start einer Story prüft der Ausführende, dass alle ihre `depends_on`
`completed` sind — die Sequenz oben ist eine gültige Linearisierung
des Graphen, ersetzt aber nicht den Check. Parallelisierung ist
erlaubt, wo Kanten es zulassen (z. B. AG3-140 unabhängig neben
138–144; AG3-157 ff. jederzeit).

### 6.9 Konzept-Konsistenz-Werkzeuge W1–W4 (AG3-157…AG3-160)

Eigener Strang aus `concept/_meta/konzept-konsistenz-governance.md`
(§5 Werkzeug-Spezifikationen, §6 Betriebsmodell, §7 Fahrplan).
Reihenfolge nach §7 als Kanten kodiert (W1→W4→W2→W3; nur W3←W2 ist
technisch, die übrigen sind ausgewiesene Sequenz-Kanten).

| ID | Werkzeug | Größe | Status | depends_on |
|----|----------|-------|--------|------------|
| AG3-157 | W1 `concept-reference-integrity` — deterministisches CI-Pflichtgate (Querverweis-Auflösbarkeit, §-Anker, formal.*-IDs, Pfade; + `defers_to`-Scope-Zyklen-Semantik) | M | **completed** | — |
| AG3-158 | W4 `concept-decision-record-gate` — P3-Durchsetzung (Konzeptdiff ⇒ Decision-Record) | S | **completed** | 157 (Sequenz) |
| AG3-159 | W2 `concept-authority-prose` — LLM-Bewertung + deterministische Policy (unzuständige normative Behauptungen) | L | **completed** | 158 (Sequenz) |
| AG3-160 | W3 `concept-scope-consistency` — LLM-Sweep pro Scope (Widerspruchssuche auf kleinen Mengen) | M | **ready** | 159 (technisch) |

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
