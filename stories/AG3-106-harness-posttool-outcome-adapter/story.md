# AG3-106: Harness-PostToolUse-Outcome-Adapter (Claude Code + Codex → `HookEvent.post_tool_outcome`)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `harness-integration` (Code aktuell physisch unter `src/agentkit/governance/harness_adapters/`; die kosmetische Paket-Migration nach `agentkit.harness_integration` ist **NICHT** Teil dieser Story — siehe §2.2). Liefert an den Abnehmer `implementation-phase` (Worker-Health, AG3-080).
**Quell-Konzepte (autoritativ):**
- `FK-76 §76.2` — harness-**spezifische** Adapter gehoeren zu harness-integration; Adapter treffen **keine Policy** (Exit-Code/stderr/Timeout NICHT als allow/deny/warn umdeuten).
- `FK-76 §76.3/§76.4` — Adapter-Architektur + Adapter-Vertrag (Eingangs-Mapping harness-nativ → generisch); Paketname-Migration kosmetisch/Folge-Story.
- `FK-76 §76.9` — Importrichtung: `harness_integration` importiert neutrale Contracts aus `governance`; **kein** harter Import von `implementation`-Internas.
- `FK-30 §30.3` — Hook-Registrierung/Matcher (PreToolUse/PostToolUse), Settings-Writer.
- `FK-49 / FK-93` — Worker-Health (Abnehmer); nur Konsument, nicht Gegenstand.

> **Review-Historie:** Erstfassung (S) wurde von Codex (`job-cf40377b`) als CHANGES-REQUESTED zerlegt — Live-PostToolUse-Wiring war unterspezifiziert (Adapter parsen Post-stdin durch Pre-Tool-only-Modelle; keine `PostToolUse→health_monitor`-Registrierung; Claude nutzt fuer fehlgeschlagene Befehle evtl. `PostToolUseFailure`; AC4 falsch; „fail-closed" falsch). Diese Fassung (M) adressiert das.

---

## 1. Kontext / Ist-Zustand (belegt)

- **Das Zielfeld existiert, ist aber immer leer:** `HookEvent.post_tool_outcome: dict[str, object] | None = None` (`src/agentkit/governance/guard_evaluation.py:57`); Kommentar (`:55-56`): „Harness-specific adapters own [populating it]" — die Adapter befuellen es **nicht**.
- **Abnehmer gebaut (AG3-080), faellt OFFEN aus (nicht fail-closed):** `_run_health_monitor_post` gibt bei fehlendem Outcome `GuardVerdict.allow("health_monitor")` zurueck (`src/agentkit/governance/runner.py:676-677`) — d. h. **fail-open**. Liegt etwas an, validiert es `PostToolOutcome.model_validate(event.post_tool_outcome)` (`runner.py:683`) und ruft `apply_post_tool_use(...)` (`src/agentkit/implementation/worker_health/engine.py:38`, gibt `AgentHealthState` zurueck). **Wichtig:** `_run_health_monitor_post` selbst gibt einen `GuardVerdict` zurueck, **nicht** den `AgentHealthState`.
- **Neutraler Vertrag liegt beim Abnehmer:** `PostToolOutcome` (`src/agentkit/implementation/worker_health/models.py:53-61`): `exit_code: int | None`, `stdout: str`, `stderr: str`, `tool_result: dict | list | None`; `extra="forbid"`. Der erste fehlgeschlagene Commit erzeugt `hook_conflict > 0` ueber `is_failed_git_commit` (`operation == "bash_command"` + Command enthaelt `git commit` + non-null nonzero `exit_code`, `scoring.py:231-245`) und `register_commit_failure` (`scoring.py:174-206`); Wiederholung ist nur fuer Eskalation noetig.
- **Adapter existieren, mappen aber nur Pre-Tool:** `src/agentkit/governance/harness_adapters/claude_code.py` und `harness_adapters/codex/{event_mapping.py,cli.py}` parsen die stdin in **Pre-Tool-only-Payload-Modelle** (`ClaudeCodeHookEvent`/`CodexHookEvent`, `extra="forbid"`, z. B. `claude_code.py:35/41/156/161`, `codex/event_mapping.py:79/84`, `codex/cli.py:50/55`) — ein echter Post-Payload mit post-only-Feldern wird damit **vor** der Phase-Behandlung **abgewiesen**. Kein Pfad setzt `post_tool_outcome`.
- **Keine `PostToolUse→health_monitor`-Registrierung gefunden:** `settings_writer.py:52` ist nur ein Docstring-**Beispiel** (`post telemetry`); `:114/:417` materialisieren generisch die uebergebenen Definitionen. FK-30 §30.3.1 listet `PostToolUse`-Hooks `telemetry`/`review_guard` — eine konkrete `health_monitor post`-Registrierung pro Harness ist im Code **nicht** belegt (Runner-Support existiert, Installation nicht).
- **Claude fehlgeschlagene Befehle evtl. `PostToolUseFailure`:** Laut Claude-Code-Hook-Doku trennt Claude `PostToolUse` (mit `tool_response`) von `PostToolUseFailure` (z. B. non-zero Exit). AC4 haengt an einem fehlgeschlagenen `git commit` — der kommt fuer Claude womoeglich als `PostToolUseFailure`, nicht `PostToolUse`. **Vor Implementierung mit echtem Fixture verifizieren.**

Anknuepfungspunkte: `HookEvent` (`guard_evaluation.py:38`), `Governance.run_hook(..., phase="post")`, `HookEventName` (`hook_registration.py:24/33`), Settings-Writer.

## 2. Scope

### 2.1 In Scope
1. **Phase-bewusstes Post-Payload-Parsing:** Einen Parse-/Modell-Pfad fuer den PostToolUse-(und ggf. `PostToolUseFailure`-)Payload je Harness ergaenzen, sodass ein **echter** Post-Payload nicht vom Pre-Tool-only-Modell abgewiesen wird, sondern `Governance.run_hook(..., phase="post")` mit gesetztem `event.post_tool_outcome` erreicht. Pre-Tool-Pfad bleibt unveraendert.
2. **Claude-Code-Outcome-Mapping:** Aus dem nativen Claude-Post-Payload (`tool_response`, Exit-Status; **inkl. `PostToolUseFailure`** falls die Fixture-Pruefung das fuer non-zero Exits bestaetigt) `exit_code/stdout/stderr/tool_result` → `HookEvent.post_tool_outcome` (neutrales dict, nur die vier Vertrags-Keys; `PostToolOutcome.model_validate`-kompatibel, `extra="forbid"`).
3. **Codex-Outcome-Mapping:** Analog aus dem Codex-nativen Post-Payload-Aequivalent (CLI `agentkit-hook-codex`). **Reale Codex-Post-Payload-Form als Fixture/Schema beilegen** (heute nur Pre-Tool-Felder modelliert).
4. **Hook-Registrierung:** `PostToolUse` (und ggf. `PostToolUseFailure`) → `health_monitor` fuer **beide** Harnesses ueber den Settings-Writer real registrieren, damit der Live-Pfad in Produktion feuert (FK-30 §30.3). Mit Registrierungs-Test.
5. **Reines Mapping, keine Policy (FK-76 §76.2):** Exit-Code/stderr/Result werden nicht in allow/deny/warn umgedeutet; nur Rohsignale neutral transportiert.
6. **Importrichtung (FK-76 §76.9):** Adapter fuellt nur die `governance`-`HookEvent`-Struktur (ein dict-Feld, dessen Form der implementation-Konsument validiert). **Kein** Import von `implementation.worker_health` und **kein** Import von `PostToolOutcome` in den Adapter.

### 2.2 Out of Scope (mit Owner)
- **Paket-Migration `governance.harness_adapters` → `agentkit.harness_integration`** — FK-76 §76.3 (kosmetisch, eigene Folge-Story / AG3-104-CP2-Umfeld). Diese Story arbeitet am bestehenden Ort, benennt nichts um.
- **`PostToolOutcome`-Vertrag verschieben** — bleibt beim Abnehmer `implementation/worker_health/models.py` (D2-Entscheidung). Der Adapter fuellt ein dict, keinen „typed" governance-Struct.
- **Guard-Policy / Decision-Semantik** — governance-and-guards / FK-30.
- **Worker-Health-Scoring, LLM-Sidecar, Interventionen** — gebaut (AG3-080); hier nur die Datenzufuhr.
- **Weitere Harnesses** (Qwen, Gemini-CLI) — Folge-Stories.

## 3. Akzeptanzkriterien
1. **Claude-Mapping:** Aus einem realistischen Claude-`PostToolUse`-Sample wird `post_tool_outcome` mit `exit_code/stdout/stderr/tool_result` befuellt; fehlende Felder → `exit_code=None`, leere Strings, `tool_result=None` (Test mit Fixture).
1a. **Claude fehlgeschlagener Befehl:** Mit echtem Fixture verifiziert, ob non-zero Bash als `PostToolUse` **oder** `PostToolUseFailure` kommt; der zutreffende Hook-Event wird gemappt + registriert (Test). Falls ausschliesslich `PostToolUseFailure`: dieser ist in Scope (Mapping + Registrierung), und AC4 nutzt ihn.
2. **Codex-Mapping:** Aus dem Codex-nativen Post-Sample wird `post_tool_outcome` analog befuellt (Test mit beigelegtem Fixture/Schema).
3. **Vertrags-Validierung:** `PostToolOutcome.model_validate(mapped_dict)` wirft fuer beide Adapter keinen `extra="forbid"`-/Typ-Fehler (Test).
4. **Health-Effekt (korrekt formuliert):** Getestet wird `apply_post_tool_use(...)` (bzw. der **persistierte/exportierte** `AgentHealthState` nach Runner-Lauf) — **nicht** der Runner-Return (der liefert `GuardVerdict.allow`). Ein fehlgeschlagenes Commit-Outcome (`operation == "bash_command"`, `operation_args.command` enthaelt `git commit`, non-null nonzero `exit_code`) erzeugt `hook_conflict > 0`; ein Erfolgs-Outcome nicht (Test).
5. **Registrierung:** `PostToolUse` (+ ggf. `PostToolUseFailure`) → `health_monitor` ist fuer Claude **und** Codex im Settings-Writer real registriert (Test ueber die materialisierten Settings).
6. **Phase-bewusstes Parsing:** Ein echter Post-Payload erreicht `run_hook(..., phase="post")` mit gesetztem `post_tool_outcome`, **ohne** vom Pre-Tool-only-Modell abgewiesen zu werden (End-to-end-Adapter/CLI-Test).
7. **Malformed/partial:** fehlender Exit-Code → `None`; non-string stdout/stderr robust behandelt; Zusatzfelder werden verworfen; fehlendes `tool_result` → `None` (Tests).
8. **Keine Policy + Importrichtung:** kein Adapter-Pfad deutet Exit-Code/stderr in allow/deny/warn um; Adapter importiert `PostToolOutcome`/`implementation`-Internas nicht; GAC-1 zeigt keine neue Boundary-Verletzung (Test/Review-Assertion).
9. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/governance`, `tests/unit/implementation/worker_health`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+ `--platform linux`); `ruff check src tests`; GAC-1 (Exit 0); Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; Codex-Review PASS; Implementierung/Commit auf `main` erst nach explizitem PO-Go (Halt-and-wait).

## 5. Guardrail-Referenzen
- **SINGLE SOURCE OF TRUTH:** `PostToolOutcome` bleibt der eine Owner beim Abnehmer; Adapter erzeugt nur das dict.
- **FAIL-CLOSED-Klarstellung:** der Health-Monitor faellt heute bewusst **offen** (allow) bei fehlendem Outcome; diese Story aendert das nicht, sondern liefert die Daten — kein neuer Bypass; unvollstaendige Payloads → `None`/leer, nie geraten.
- **ADAPTER TRIFFT KEINE POLICY (FK-76 §76.2)** + **IMPORTRICHTUNG (FK-76 §76.9).**
- **ARCH-55:** Identifier/Keys englisch (Prosa darf deutsch sein).
- **ZERO DEBT:** beide Harnesses + Registrierung + Parsing zusammen; echte Fixtures, kein Platzhalter.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Zuerst** mit echten Fixtures klaeren: (a) Claude `PostToolUse` vs `PostToolUseFailure` bei non-zero Bash; (b) reale Codex-Post-Payload-Form. Bei Unklarheit melden, nicht erfinden.
- dict-Form **exakt** = `PostToolOutcome` (`exit_code/stdout/stderr/tool_result`, `extra="forbid"`), keine Zusatz-Keys.
- `PostToolOutcome` NICHT in den Adapter importieren; Validierung bleibt in `governance/runner.py`.
- Pre-Tool-Mapping-Pfad nicht brechen; nur Post-Outcome-Zweig + Registrierung ergaenzen.
- AK2 NICHT veraendern; `.mcp.json` NICHT anfassen; `concept/**`/`stories/**` nicht im Code-Commit; Paket-Rename OUT OF SCOPE.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (Claude/Codex-Mapping, Failure-Variante, Vertrags-Validierung, Registrierung, phase-aware Parsing, `hook_conflict>0`, malformed).

---

## Globale Akzeptanzkriterien (verbindlich)
Zusaetzlich gelten die globalen Akzeptanzkriterien aus `stories/_GLOBAL_ACCEPTANCE.md`:
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten; Konflikt = hart stoppen und melden.
