# Handover: AgentKit v3 Entwicklung

**Stand:** 2026-04-08
**Kontext:** Greenfield-Rewrite von AgentKit v2 als deterministische Orchestrierungsmaschine

---

## 1. Was steht

### Codebase
- **Repo:** `T:/codebase/claude-agentkit3/` (GitHub: `saltenhof/claude-agentkit3`)
- **v2 Referenz:** `T:/codebase/claude-agentkit/` (GitHub: `saltenhof/claude-agentkit`)
- **Testbed:** `saltenhof/agentkit3-testbed` (privat, GitHub Project #5)
- **venv:** `T:/codebase/claude-agentkit3/.venv/` mit `PYTHONSAFEPATH=1`
- **Paketname:** `agentkit` (pip-Name und Python-Namespace identisch zu v2 — Isolation ueber venv)

### Installationssetup (WICHTIG)
- **v2 Produktion:** `pip install -e T:/codebase/claude-agentkit` (User site-packages) + `pipx install --editable T:/codebase/claude-agentkit` (CLI global)
- **v3 Entwicklung:** `.venv/Scripts/python -m pytest ...` — IMMER ueber die venv
- **Namespace-Kollision vermeiden:** v3 NIE global installieren. Tests immer mit `.venv/Scripts/python`
- **gh CLI:** Token-Routing per Owner automatisch (kein `gh auth switch` noetig). Credentials aus `~/.git-credentials-{owner}`

### Fertige Module (56 Produktionsmodule, 922 Tests, ~34s mit E2E)

| Bereich | Module | Tests |
|---|---|---|
| Foundation | exceptions, config (models/loader/validators/defaults), story (types/models/sizing/routing_rules) | 180 |
| Workflow-DSL | workflow/model, builder, guards, gates, recovery, validators, definitions | 224 |
| Pipeline Engine | engine, lifecycle, state, runner | 70 |
| Setup-Phase | preflight, context_builder, phase handler | 25 |
| Closure-Phase | phase handler, execution_report | 16 |
| GitHub-Integration | client (Token-Routing), issues, projects | 40 |
| Prompting | templates, selectors, composer, sentinels | 68 |
| 4-Layer QA | protocols, structural/checks+checker, evaluators (stub), adversarial (stub), policy_engine/trust+engine, remediation/feedback | 78 |
| Telemetrie | events, emitters (Memory/Null/SQLite), storage, metrics | 60 |
| Governance | protocols, guards (branch/scope/artifact), integrity_gate, runner | 66 |
| Utils | io (atomic_write) | 18 |
| CLI | main (install, run-story stub, doctor) | 6 |
| Contract-Tests | prompt_templates, scaffold_snapshots | 43 |
| E2E | real pipeline (concept+research), github_live | 16 |
| Integration | pipeline_runner, install_fresh, closure handler | 32 |

### Qualitaetszustand
- ruff: sauber
- mypy --strict: sauber
- Alle Codex-Review-Findings (12/12) abgearbeitet
- Guards sind Exit-Validierungen (nach Completion)
- Korrupter State → CorruptStateError (fail-closed)
- Kein Import-Zyklus pipeline↔qa
- E2E ehrlich gelabelt (Integration vs. echte E2E)
- Contract-Suite vorhanden

---

## 2. Was als naechstes ansteht

### Offene Entscheidung: v2-Features bewerten

**BLOCKER vor weiterer Implementierung.** Der User muss entscheiden welche v2-Features in v3 uebernommen werden.

Drei Analyse-Dokumente liegen vor:
1. `stories/analyse-worker-phases-code.md` — Was existiert in v2 (Code-Analyse)
2. `stories/analyse-worker-phases-konzepte.md` — Was ist spezifiziert (Konzept-Analyse)
3. `stories/analyse-v2-ballast-begruendungen.md` — Bewertung der "Ballast"-Einstufungen (29 Elemente)

**Zentrale Erkenntnis:** Nichts in v2 wurde grundlos gebaut. Jedes Feature hat einen evidenten Produktionsgrund. "Ballast" ist die falsche Kategorie — die richtige Frage ist: "Wird das Problem in v3 anders geloest, oder brauchen wir dasselbe Feature?"

Der User muss fuer jedes Element in der Ballast-Analyse entscheiden:
- **Uebernehmen** (Feature wird in v3 gebaut, ggf. mit besserer Architektur)
- **Anders loesen** (das Problem existiert, aber v3 loest es anders — wie?)
- **Nach MVP** (Feature ist real, aber nicht fuer die erste lauffaehige Version noetig)

### Naechste Iterationen (nach User-Entscheidung)

**Iteration 14+15: Implementation-Phase + Exploration-Phase**

Was AgentKit bauen muss (NICHT Worker-Spawning — das macht der Orchestrator):

Implementation-Phase-Handler:
- `on_enter()`: Prompt komponieren, Spawn-Spec bauen (`agents_to_spawn`), PAUSED zurueckgeben
- `on_resume(trigger="worker_completed")`: handover.json lesen, validieren, COMPLETED
- Artefakt-Vertraege: handover.json (Pflichtfelder), worker-manifest.json (Status)

Exploration-Phase-Handler:
- 3-stufiges Exit-Gate (Doc-Compliance, Design-Review, Design-Challenge)
- Design-Artefakt-Schema (entwurfsartefakt.json)
- Yield-Punkte: awaiting_design_review, awaiting_design_challenge (in DSL bereits definiert)
- Max 2 Remediation-Runden im Gate

Remediation-Loop:
- Maengelliste aus Verify-Findings → feedback.json
- Remediation-Prompt (existiert bereits in prompting/templates.py)
- Max-Rounds-Check (default 3, dann Eskalation)

**Weitere Iterationen (Tier 2-4):**

| # | Thema | Abhaengigkeit |
|---|---|---|
| 17 | LLM-Pool Integration (ChatGPT/Gemini/Grok Adapter) | MCP-Server |
| 18 | Semantic QA Layer 2 (echter LLM-Review) | LLM-Pools |
| 19 | Adversarial QA Layer 3 (Edge-Case-Tests) | LLM-Pools |
| 20 | CLI vollstaendig (run-story verdrahtet) | Implementation-Phase |
| 21 | Project Ops (Upgrade, Checkpoint) | Installer |
| 22 | Resources/Templates (CLAUDE.md.j2 etc.) | — |
| 23 | ARE Integration | — |
| 24 | VectorDB Integration | Weaviate |
| 25 | Failure Corpus | Telemetrie |

---

## 3. Arbeitsregeln

### Worker-Management
- **Ein Worker pro Task.** Keine parallelen Worker auf denselben Dateien.
- **Sequentiell:** Worker fertig → Opus-Review → Commit → naechster Worker.
- **Orchestrator fasst keinen Code an.** Nur steuern, pruefen, committen.

### Worker-Prompt-Template
```
Read T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md first — all project rules apply to you.
Du bist der EINZIGE Worker. Kein anderer Agent arbeitet parallel.

[Aufgabe]
[Lies zuerst: relevante Dateien]
[Konkrete Dateien + Design]
[Tests]
[Regeln:]
- from __future__ import annotations überall
- Verwende venv: .venv/Scripts/python -m pytest ...
- Am Ende: ruff + mypy + pytest Gesamtsuite
```

### Opus-Review-Template (nach Worker)
```
Du bist QS-Agent. Prüfe ob [Fixes/Features] korrekt umgesetzt wurden.
[Prüfschritte mit konkreten Befehlen]
Kurzes Verdict: Ja/Nein pro Fix + Gesamturteil.
```

### Commit-Konvention
```
feat/fix: Kurzbeschreibung

Details pro Aenderung.

N tests, ruff clean, mypy clean. Verified by Opus QS agent.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

### Qualitaets-Gates (vor jedem Commit)
```bash
cd T:/codebase/claude-agentkit3
.venv/Scripts/python -m ruff check src/agentkit tests
.venv/Scripts/python -m mypy src/agentkit
.venv/Scripts/python -m pytest -q --tb=short -m "not e2e"
```

### gh-Nutzung
- gh ist auf `stefan-altenhof` aktiv (Default)
- Token-Routing fuer `saltenhof`-Repos funktioniert automatisch via `resolve_token_for_owner()`
- Kein `gh auth switch` noetig
- Testbed: `saltenhof/agentkit3-testbed` (Issues #1-#3 + dynamisch erzeugte)

---

## 4. Architektur-Guardrails

Verbindliche Dokumente:
- `T:/codebase/claude-agentkit3/guardrails/architecture-guardrails.md` (ARCH-01 bis ARCH-54)
- `T:/codebase/claude-agentkit3/guardrails/testing-guardrails.md`
- `T:/codebase/claude-agentkit3/concept/testing-standards.md` (Pipeline-Robustheitstests)
- `T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md` (Verzeichnisstruktur)

Kernprinzipien die in jeder Iteration gelten:
- **ARCH-05:** Keine God-Klassen
- **ARCH-06:** Protocols als Vertraege
- **ARCH-12:** Orchestrierung getrennt von Geschaeftslogik
- **ARCH-20:** Fachliche Fehler via Return-Types, nicht Exceptions
- **ARCH-29:** Immutability als Default
- **ARCH-33:** Jede Komponente einzeln testbar

---

## 5. Bekannte Schwachstellen

1. **Semantic QA (Layer 2) und Adversarial (Layer 3) sind Passthrough-Stubs.** Echte LLM-basierte QA fehlt. Erst mit LLM-Pool-Integration moeglich.

2. **CLI `run-story` ist nur ein Stub.** Druckt eine Meldung, fuehrt keine Pipeline aus. Muss nach Implementation-Phase verdrahtet werden.

3. **Worktree-Erstellung ist ein TODO.** Setup-Phase berechnet den Pfad, fuehrt aber `git worktree add` nicht aus.

4. **E2E-Tests nutzen NoOpHandler fuer Implementation.** Akzeptabel weil LLM-Phase, aber echte Worker-Integration fehlt.

5. **Testlaufzeit mit E2E ~34s** wegen GitHub-API-Aufrufen. Ohne E2E: ~2s.

---

## 6. Wichtige Dateien zum Einlesen

| Datei | Zweck |
|---|---|
| `PROJECT_STRUCTURE.md` | Kanonische Verzeichnisstruktur |
| `guardrails/architecture-guardrails.md` | ARCH-01 bis ARCH-54 |
| `concept/testing-standards.md` | Pipeline-Robustheitstests |
| `stories/AG3-001-workflow-dsl/story.md` | DSL-Akzeptanzkriterien |
| `stories/AG3-001-workflow-dsl/sparring-r1.md` | DSL-Architekturentscheidungen |
| `stories/review-codex-architecture-r1.md` | Codex-Review (12 Findings, alle gefixt) |
| `stories/analyse-worker-phases-code.md` | v2-Code-Analyse fuer #14/#15 |
| `stories/analyse-worker-phases-konzepte.md` | Konzept-Analyse fuer #14/#15 |
| `stories/analyse-v2-ballast-begruendungen.md` | **OFFEN: User-Entscheidung ausstehend** |
