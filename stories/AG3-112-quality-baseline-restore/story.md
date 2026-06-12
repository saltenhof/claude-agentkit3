# AG3-112: Quality-Baseline-Restore (Aufraeumrunde)

**Typ:** Bugfix / Cleanup
**Groesse:** M

PO-Direktive (2026-06-12): Sobald Sonar oder Jenkins rot ist, wird die laufende
Story fertig implementiert und dann eine **Aufraeumrunde** gefahren, die ALLE
technischen Schulden / Fehler / Sonar-Issues beseitigt — unabhaengig davon, aus
welcher Story sie stammen — bis die 100%-Qualitaets-Baseline (lokal + remote
Jenkins/Sonar gruen) wiederhergestellt ist. Danach geht die Story-Umsetzung
weiter.

## Befund (Codex-Diagnose gegen Sonar-Rev `46fcc99` + Jenkins #325, 2026-06-12)

Keiner der Befunde stammt aus den 7 Stories dieser Session (AG3-100/104/101/074/
072/097/109). Es ist akkumulierte AG3-065/AG3-043- (Sonar) + AG3-110- (Jenkins)
Schuld.

### Jenkins #325 — Stage `Postgres Contract + Integration` (3 failed)
- `tests/integration/governance/test_install_manifest_spawn_proof_e2e.py`:
  `test_real_install_writes_manifest_with_token`,
  `test_e2e_install_header_guard_allows_and_blocks`,
  `test_idempotent_reinstall_keeps_token` — alle `git_config_failed`
  (CP11 `git -C <root> config core.hooksPath tools/hooks/`).
- **Root Cause:** der Test legt `tmp_path/proj` an, macht aber **kein `git init`**.
  Produktiv-CP11 braucht ein echtes Git-Repo. Lokal „besteht" der Test nur, weil
  Git zum Eltern-Repo hochlaeuft (nicht-hermetisch, evtl. Repo-Pollution); in CI
  gibt es kein Eltern-Repo ueber `tmp_path` -> FAILED. **Test-Hermetik-Bug, kein
  Produkt-Bug.**

### Sonar — 3 Critical (alle `verify_system/llm_evaluator/structured_evaluator.py`)
- `PY_MODULE_TOP_LEVEL_MAX_LOC_100`: Modul-Top-Level-LOC 119 > 100.
- `python:S3776`: `evaluate` Cognitive Complexity 18 -> <=15.
- `python:S3776`: `_stage3_regex_fallback` Cognitive Complexity 19 -> <=15.

### Sonar — 6 Minor `python:S5713` (`dialogue_runner.py`, `llm_client.py`)
- Subklasse+Elternklasse im selben `try` doppelt gefangen
  (`except HubLoginRequiredError` + `except MultiLlmHubError`; erstere ist
  Subklasse von letzterer). Handhabung ist UNTERSCHIEDLICH (Login vs. generisch),
  daher NICHT einfach loeschen (NO ERROR BYPASSING). Behavior-preserving: ein
  `except MultiLlmHubError` mit `isinstance(exc, HubLoginRequiredError)`-Branch.

### Sonar — 1 Security Hotspot `python:S5852` (DoS / ReDoS)
- `structured_evaluator.py` `re.search(r"```json\s*(.*?)```", text, re.DOTALL)`
  (Stage-2-Fence-Extraktion). Backtracking-Risiko -> nicht-regex String-Index-
  Extraktion (Fence-Start/`find`, Fence-Ende/`find`), Verhalten erhalten.

## Scope
1. Test-Hermetik-Fix: betroffene Install-E2E-Tests initialisieren ihr eigenes
   isoliertes Git-Repo (`git init` am Projekt-Root) vor `install_agentkit`.
2. Sonar-3-Critical: Modul-LOC unter 100 (Top-Level-Helper in Schwester-Modul
   auslagern, `__all__`/Public-API stabil); `evaluate` + `_stage3_regex_fallback`
   Cognitive Complexity <=15 (dekomponieren, Verhalten + 3-Stage-Parse-Contract
   erhalten).
3. Sonar-6-Minor S5713: behavior-preserving isinstance-Branch.
4. Sonar-1-Hotspot S5852: nicht-backtrackende Fence-Extraktion.
5. Fresh-Scan-Schleife: nach Push triggert Jenkins eine frische Analyse gegen
   aktuellen `main`; Codex liest das echte Ergebnis; Restbefunde werden iterativ
   beseitigt, bis Jenkins + Sonar gruen sind.

## Akzeptanzkriterien
- Alle lokalen Pflichtbefehle gruen (pytest scoped + broad, mypy x2, ruff,
  4 Concept-Gates, Coverage >= 85%).
- Verhalten unveraendert (kein geschwaechtes Error-Handling, kein Bypass).
- Remote: Jenkins-Build gruen, Sonar Quality Gate PASS (frische Analyse gegen
  aktuellen `main`), 0 offene Violations + 0 offene Security-Hotspots.

## Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply.
- Verhalten strikt erhalten. Keine Except-Klausel ersatzlos entfernen, die echtes
  Handling traegt. Kein Test-Abschwaechen.
- `.mcp.json` / `mcps/` / AK2 nicht anfassen; `concept/**`/`stories/**` nicht im
  Code-Commit.
