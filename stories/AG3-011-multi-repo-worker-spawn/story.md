# AG3-011: Worker-Spawn mit Worktree-Map

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** AG3-010 (Worktrees muessen pro Repo angelegt sein)
**Quell-Konzept:** FK-22 §22.6.4, FK-26 §26.2.1, §26.2.2

---

## Kontext

FK-22 §22.6.4 + FK-26 §26.2.1: bei Multi-Repo-Stories spawnt der
Orchestrator **einen Worker** mit einer **Worktree-Map** als
Spawn-Vertrag (Repo-Name -> Worktree-Pfad). Der erste Eintrag in
`participating_repos` ist der deterministische Spawn-CWD ohne
fachliche Sonderrolle. Schreiben in nicht-teilnehmende Repos ist
verboten.

FK-26 §26.2.2 fuegt eine Kontext-Tabellen-Zeile "Worktree-Map (bei
Multi-Repo)" — diese muss vom Worker-Prompt-Composer befuellt werden.

## Scope

### In Scope

- Worker-Kontext-Komposition (`prompting/workers` oder analog):
  - Bei Multi-Repo (|`participating_repos`| >= 2): Worktree-Map
    (Repo-Name -> Pfad) als Kontext-Item; in den Prompt eingebettet
    als Tabelle
  - Bei Single-Repo: ein einzelner Worktree-Pfad als Kontext-Item
  - Schreibgrenze-Hinweis im Prompt: "Schreiben in nicht-teilnehmende
    Repos ist verboten"
- Worker-Spawn-CWD = `participating_repos[0]`-Worktree-Pfad (kein
  Sonderbegriff "primary")
- Tests:
  - Single-Repo-Worker: ein Worktree-Pfad
  - Multi-Repo-Worker: Worktree-Map mit N Eintraegen
  - Spawn-CWD entspricht participating_repos[0]
  - Prompt enthaelt Schreibgrenze-Hinweis

### Out of Scope

- Branch-Guard fuer Schreibgrenze (FK-31; Folge-Story falls nicht
  vorhanden)
- Worker-Health-Aware Multi-Repo-Heuristik (FK-49 — bereits im Konzept
  klargestellt; Code-Folge separat)
- LLM-Sub-Agent-Mechanik (Harness-Adapter; FK-30 §30.11)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/.../prompting/workers/...` | Modifiziert | Worker-Kontext-Tabelle Multi-Repo |
| `src/agentkit/resources/internal/prompts/worker-implementation.md` | Modifiziert | Multi-Repo-Block analog AK2 worker-implementation.md |
| `tests/unit/prompting/test_worker_context.py` | Neu/Erweitert | Multi-Repo-Worktree-Map-Test |

## Akzeptanzkriterien

1. Worker-Kontext bei Multi-Repo enthaelt Worktree-Map (Repo-Name -> Pfad).
2. Spawn-CWD ist der Worktree zum ersten Eintrag in
   `participating_repos`.
3. Prompt-Inhalt nennt explizit die Schreibgrenze (kein Schreiben in
   nicht-teilnehmende Repos).
4. Single-Repo-Fall: Worker bekommt einen Worktree-Pfad, keine Map.
5. Tests gruen, Lints clean.

## Definition of Done

- Tests gruen
- Worker-Prompt rendert sauber bei 1, 2, 3 Repos
- Konzept-Referenz im Prompt-Template-Comment

## Konzept-Referenzen

- FK-22 §22.6.4 — Worker-Modell bei Multi-Repo (Worktree-Map, Spawn-CWD)
- FK-26 §26.2.1 — Startprotokoll mit Worktree-Map
- FK-26 §26.2.2 — Worker-Kontext-Tabelle
- AK2-Vorlage: `userstory/prompts/worker-implementation.md` Z. 94-109

## Guardrail-Referenzen

- ZERO DEBT: kein Sonderpfad fuer "primary repo" in der Worker-Logik
- FAIL CLOSED: Worker, der in nicht-teilnehmende Repos schreibt, muss
  vom Branch-Guard blockiert werden (separat)
