# AG3-206 — Abschlussbericht

## Was umgesetzt wurde

**AC 1/2 — Preflight gegen die Deklaration, vor jeder Mutation.**
`src/agentkit/backend/installer/dependency_preflight.py` leitet die
Pflicht-Abhaengigkeiten aus `pyproject.toml` ab (keine gepflegte Zweitliste) und
prueft sie stdlib-only, bevor CP 1 laeuft. Ein fehlendes Paket bricht mit
Paketnamen und Beschaffungskommando ab. Der oeffentliche Importpfad
`from agentkit.backend.installer import run_checkpoint_install` stirbt nicht
mehr vor dem Preflight — die Kette `registry → cp10_mcp_registration →
codex_settings → codex_config_toml` ist auf Lazy-Imports umgestellt.

**AC 3 — Die Hook-Fehlerklasse ist auswertbar.**
`hook_error_report.py` + Verb `hook-errors`: gruppiert nach Hook-**`command`**,
dedupliziert nach Fehlertext, optional zeitlich begrenzt (`--since`/`--until`).

**AC 4 — Kein Hook taeuscht Erfolg vor.**
Beide Hook-Adapter (`claude_code.py`, `codex/cli.py`) sterben nicht mehr am
Top-Level-Import; ohne `pydantic` blockieren sie maschinenlesbar mit Exit 2.
Im Repo existiert kein `|| true` ohne Begruendung mehr.

**Konzept.** FK-50 ist Owner der Eingangsgrenze (nicht FK-22 — der urspruengliche
Entwurf hatte den Check beim Story-Setup verortet, dort gehoert er nicht hin).
Decision Record: `concept/_meta/decisions/2026-08-04-abhaengigkeitsvollstaendigkeit-und-hook-fehlersichtbarkeit.md`.

## Realitaetsnachweis (CLAUDE.md, Fremdsystem-Grenze)

**Preflight gegen echte, unvollstaendige Umgebungen.** Zwei Wegwerf-venvs unter
`var/`, jeweils mit genau einer fehlenden deklarierten Abhaengigkeit
(`tomlkit` bzw. `pydantic`). Beide brechen vor der ersten Mutation ab.

**AC 3 gegen das Original-Transcript vom 2026-08-03.** Vom Orchestrator
gefahren, nicht vom Umsetzer — die JSONL liegt unter
`~/.claude/projects/T--codebase-intima/`, ausserhalb des Repository-Mandats:

```
hook-errors --since 2026-08-03T00:00:00Z --until 2026-08-03T23:59:59Z
```

| Transcript | Fehler | Gruppen |
|---|---|---|
| `3aa6a7b8-…` | 176 | `post commit_hook` 26, `post health_monitor` 26, `pre commit_hook` 28, `pre skill_usage_check` 28, `pre_tool_use.py` 68 |
| `0bb1451f-…` | 1676 | 8 Gruppen |
| `5cc5893e-…` | 92 | 1 Gruppe |

Jede Gruppe dedupliziert auf **genau einen** Fehlertext — 301 Ereignisse zu
einer Zeile. `No module named 'tomlkit'` bzw. `No module named
'agentkit.governance'`.

Der Lauf belegt zugleich die `command`-Achse: `post commit_hook` und
`post health_monitor` tragen denselben `hookName` `PostToolUse`. Die
urspruengliche Implementierung gruppierte nach `hookName` und haette drei Hooks
zu einer Zeile verschmolzen — der Bericht haette den Incident falsch dargestellt.

## Maschinelle Pruefung

- Blast-Radius-Teilmenge (`tests/unit/installer`, `.../governance/harness_adapters`,
  `tests/unit/cli`, `tests/contract/installer`, `tests/integration/installer`,
  Record-Test): **1162 passed**.
- 4 Fehler in `test_ag3_176_vectordb_integration.py` sind **Bestand auf `HEAD`**
  (per `git stash` verifiziert) und Windows-gebunden: die Tests starten
  `#!/bin/sh`-, `bash`- und `python3`-Hooks, die es hier nicht gibt. Auf Jenkins
  (Linux) gruen.
- `ruff check src tests` clean, `mypy src` 1039 Dateien ohne Befund.
- Konzept-Gates: Frontmatter, Decision Record, `compile_formal_specs` gruen.
- Volle Suite ausschliesslich auf Jenkins (PO-Anweisung 2026-08-04).

## Offen — braucht PO-Entscheidung, ausserhalb des Story-Mandats

1. **FK-30/FK-76-Widerspruch.** FK-30 Glossar `hook-enforcement` (Z. 71–76) und
   §30.2.4 (Z. 217–225) behaupten, jeder Hook-Crash blockiere und werde dem
   Agenten gezeigt. Der Incident beweist das Gegenteil: 164 Fehler wurden
   non-blocking und unsichtbar persistiert. Im Record mit Ownern und Locatoren
   benannt; FK-30/FK-76 blieben per Mandat unveraendert.
2. **Vier externe Hooks in `C:/Users/Sir Freejack/.claude/settings.json`**
   verschlucken ihre Fehler mit `2>/dev/null || true`. Ausserhalb des
   Repositorys, daher nicht geaendert — als ERROR dokumentiert.

## Review

Implementierung `job-56890fb9` → 5 ERRORs. Remediation + unabhaengiges
Read-only-Review `job-60bbf9f7`: "Im implementierten AG3-206-Scope bestehen nach
der Remediation keine substanziellen Code- oder Konzept-Findings mehr." Der
dort verbliebene ERROR 1 (AC 3 ohne Realnachweis) ist mit dem Lauf oben
geschlossen; ERROR 2 und 3 sind die beiden Punkte oben. Abbruchkriterium
erreicht.
