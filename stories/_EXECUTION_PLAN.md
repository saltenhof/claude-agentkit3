# AG3-057..105 — Execution-Plan (Abhaengigkeits-Reihenfolge + Vorgehen)

**Stand 2026-06-08:** 49/49 Stories APPROVED (dedizierte Codex-Review je Story).
Zwei globale Akzeptanzkriterien gelten fuer alle Stories (`stories/_GLOBAL_ACCEPTANCE.md`):
**GAC-1** Architektur-Checker 0 Errors (Baseline aktuell GRUEN), **GAC-2**
`guardrails/architecture-guardrails.md`. KPI-Routen-Root entschieden: Singular `/kpi/*`.

## Abhaengigkeits-Wellen (topologische Level)

Alle `depends_on` auf `AG3-001..056` zeigen auf **completed** Stories der Vorwelle;
nur In-Wave-Kanten (057-105) bestimmen die Reihenfolge.

| Welle | Stories |
|---|---|
| **0** (sofort startbar) | AG3-057, 059, 060, 061, 064, 066, 070, 073, 075, 077, 080, 087, 090, 095, 096, 098, 102 |
| **1** | AG3-058, 062, 063, 065, 067, 068, 074, 078, 081, 088, 092, 104 |
| **2** | AG3-069, 072, 079, 083, 085, 086, 089, 097, 099, 101 |
| **3** | AG3-082, 100, 103 |
| **4** | AG3-071, 091 |
| **5** | AG3-076, 084, 093 |
| **6** | AG3-094, 105 |

Innerhalb einer Welle sind Stories parallelisierbar (disjunkte Cuts). Eine Story
startet erst, wenn alle In-Wave-Vorgaenger `completed` sind.

Hinweis Metadaten-Drift (nicht-blockierend): AG3-082 `depends_on` listet AG3-083,
AG3-083 `unblocks` AG3-082 — Richtung konsistent (082 nach 083). 083 selbst haengt nur
an 081. Bei Implementierung der Welle 3 verifizieren.

## Reihenfolge-Politik
- **Doc-only-Stories** (101-104) sind reine `concept/`-Prosa-Nachzuege und koennen
  jederzeit ab Erreichen ihrer Deps eingeschoben werden (kein `src/`-Risiko).
- **Hoher Unblock-Wert zuerst** innerhalb einer Welle: AG3-070 (Config, unblockt 5),
  AG3-061 (Evidence-Core, unblockt 3), AG3-090 (BFF, unblockt 3), AG3-098 (Planning-Model, unblockt 3).

## Erste Story in Umsetzung: **AG3-057**
Begruendung: Welle 0, alle Deps `completed`, fachliches Fundament der Pipeline
(deterministische 4-Trigger-Modusermittlung, FK-22/23) und die als Qualitaets-Bar
gesetzte Template-Story. Geringes Cross-Story-Risiko.

## Vorgehen je Story (Worker-Loop)
1. **Worker setzt um** (eigener Agent), strikt im Story-Cut; Produktionscode nur in
   `src/agentkit/`, volle Type-Hints, Pydantic v2, ARCH-55 Englisch.
2. **Lokale Gate-Batterie gruen** (Beleg pflicht):
   `pytest` (unit/integration/contract), `mypy src`, `ruff check src tests`,
   **GAC-1** `check_architecture_conformance.py` (0 Errors), Konzept-Gates
   (`check_concept_frontmatter.py`, `compile_formal_specs.py`), Coverage >= 85%.
3. **GAC-2** Guardrail-Konformitaet; Konflikt = hart stoppen + melden.
4. **Hostile Verify** (Codex-Review des Diffs gegen Story-AC + GAC-1/2), analog der Spec-Review.
5. **Commit/Push NUR auf expliziten User-Befehl** (CLAUDE.md/Harness-Regel; ausstehende
   Drift `.mcp.json`/`composition_root.py` NICHT mitcommitten).

## Reconciliation-Backlog (vor/waehrend der jeweiligen Welle)
Offene Cross-Story-/No-Owner-Punkte aus `var/concept-gap-analysis/_CROSS_STORY_PREREQS.md`
brauchen z.T. neue Cut-Items **AG3-106+**, bevor abhaengige Stories implementiert werden:
- **Runtime-Execution-Purge-Port** (FK-53) — Voraussetzung fuer **AG3-071** (Welle 4).
- **execution_input snapshot/next Reason-Entity, Planning-Projektions-Schreibpfad** — in 099/100-Scope geklaert; bei Welle 2/3 verifizieren.
- **No-Owner-Gaps** (FK-35-Escalation, FK-30 `*_send`, Task-BFF-Adapter, story_metrics-`check_ref`, ProjectionFilter, Login-Pause, baseline-hash, WorktreeManager, harness_integration) — als AG3-106+ anzulegen, terminiert je nach konsumierender Welle. **Keiner blockiert Welle 0.**
- Index-Korrekturen (C-Punkte) — beim Plan-Vollzug nachziehen.

Welle 0 ist frei von diesen Abhaengigkeiten → Implementierung kann sofort starten.

## Fortschritt
- **AG3-057 — IMPLEMENTIERT & VERIFIZIERT (2026-06-08), pending Commit.** Worker (Sonnet) + 3 hostile Verify-Runden (Codex). Befunde aus Runde 1+2 (concept_refs->concept_paths-Projektion, Trigger-3-Persistenz inkl. idempotentem Cached-Replay, Postgres-Schema+ALTER, Real-Build-Path-Tests, caplog-Asserts) alle behoben; Runde 3 = APPROVE, GAC-1 0 Violations, mypy/ruff clean, Coverage ~88%, unit 4185 passed. Geaenderte Dateien: governance/setup_preflight_gate/{mode_determination.py,context_builder.py}, story_context_manager/{story_model.py,models.py,types.py,service.py}, process/language/definitions.py, state_backend/{postgres_schema.sql,postgres_store.py,store/story_repository.py} + Tests. NICHT committet (wartet auf PO-Go). AK2/.mcp.json/stories/concept unberuehrt.

## Wave-0 Implementierungs-Loop (autonom, PO-Go 2026-06-08)
**Modus:** sequenziell, Branch+Commit+Push+PR pro Story (wie AG3-057). Pro Story: Sonnet-Worker -> hostile Codex-Verify -> ggf. Remediation -> bei APPROVE Commit (nur Story-Pfade, NIE .mcp.json) + Push -> naechste Story. GAC-1/GAC-2 verbindlich. Kein -A; gezielt nach Pfad stagen.
**Reihenfolge (Unblock-Wert):** AG3-070 (config, +5) -> AG3-061 (evidence-core, +3) -> AG3-090 (BFF, +3) -> AG3-098 (planning-model, +3) -> 059, 060, 064, 066, 073, 075, 077, 080, 087, 095, 096 -> 102 (doc-only, concept/-Prosa-Worker).
**Status:** AG3-057 DONE (b96bcb5). AG3-070 DONE (95bb761). AG3-061 DONE (9e84b32; Codex-impl 45931b7 + hostile Opus-Verify APPROVE + Sonnet test-gap-remediation: evidence-Paket 97,6%, assembler.py 97%, 41 passed). AG3-090 DONE (branch ag3-090-bff-topology, 3 Commits d626f94/d0da074/3352411 gepusht). Hostile Opus-Verify fand 2 HIGH-Defekte (Legacy-Story-Fläche fail-open; control_plane_http unmodelliert→AC011); beide behoben. entities.md-Edit (control_plane_http module_prefix) per Codex abgesegnet + re-reviewt (APPROVED); bc_route_response nach control_plane_records relocated. Opus-Full-Re-Verify APPROVE, Codex-Re-Review APPROVED, alle lokalen Gates grün.

## OFFEN — Merge-Bottleneck (PO-Entscheidung dringlicher)
4 fertige/validierte Story-Branches liegen NICHT auf main: ag3-057, ag3-070, ag3-061, ag3-090. main=7f8d4fe. Folgen: (a) Remote-Gates (Sonar/Jenkins, Single-Project) validieren nur main → die Story-Code-Stände sind real noch nicht CI-geprüft (DoD AC9); (b) jede neue Story wird von main geschnitten und sieht die anderen nicht → späte Integration (v2-Antipattern-Risiko). Empfehlung: validierte Branches in Reihenfolge nach main mergen (rebase auf 7f8d4fe, je Merge Remote-Gate-Check), bevor weitere Wave-0-Stories starten. Wartet auf PO-Go.

## EFFIZIENZ-GUARDRAIL (PO 2026-06-08) — gescopte Tests, kein Voll-Suite-Lauf im Worker
- Worker/Remediation-Agenten fuehren NUR die Tests aus, die die von der Story beruehrten Komponenten/Bereiche abdecken (gezielte Pfade/Knoten, z.B. `tests/unit/<bc>` + `tests/contract/<bc>`), NICHT pauschal die ganze Suite.
- Verboten im Worker-Loop: voller `pytest tests/unit tests/integration tests/contract`, globaler `--cov`-Lauf ueber alles, wiederholte Voll-Suite-Laeufe. Das ist CI-Sache (Jenkins/Sonar auf Push).
- Erlaubt/schnell im Worker: gescoptes pytest, `mypy src`, `ruff check` (gescopt mgl.), GAC-1 `check_architecture_conformance.py`, Konzept-Gates.
- Zeitbudget: kein Worker > ~30 Min; keine langen Wartezeiten auf irrelevante Tests. Volle Regression + globale Coverage laufen auf dem CI-Push, nicht lokal im Worker.

## PUSH-POLICY + Sonar-Cleanup (PO 2026-06-08)
- **Push-on-finish:** jede fertiggestellte Story wird SOFORT committet + gepusht (Branch+PR pro Story). AG3-061 gepusht (45931b7).
- **Sonar-Cleanup-Worker (Codex, chore/sonar-cleanup):** loopt push->Jenkins->Sonar bis Quality Gate OK + violations/critical/hotspots = 0 + Jenkins SUCCESS. Credentials via T:\seu\agentkit3-secrets.cmd.
- **Working-Tree-Exklusivitaet:** nur EIN code-schreibender Worker zugleich (Codex-write/Agent mutieren denselben Live-Tree). Solange der Sonar-Worker laeuft: kein zweiter Code-Writer (AG3-090) starten.
- **Queue (nach Sonar-Cleanup / Tree frei):** (1) AG3-061 hostile Opus-Verify (gegen branch ag3-061-evidence-assembly-core), (2) AG3-090 implementieren. Danach restliche Welle 0.

## SONAR-CLEANUP ABGESCHLOSSEN (2026-06-08)
- **job-ca489037 completed**, 271 Tool-Calls, ~2,5 h. Branch `chore/sonar-cleanup` (6 Commits
  9edcedb..7f8d4fe) zweigte sauber von `origin/main` (ac01da8) ab — reine Sonar-Fixes auf
  bestehenden main-Dateien + 1 neue Datei `verify_system/defaults.py` (VerifySystemDefaultOptions,
  S107-Extraktion). Keine fremde WIP eingesammelt.
- **Unabhaengig verifiziert (Opus, hostile):** Sonar Quality Gate OK, violations/critical/hotspots
  = 0/0/0, Jenkins #232 SUCCESS; lokal ruff sauber, GAC-1 exit 0, mypy strict 504 files clean.
- **Fast-Forward auf `main` gepusht: ac01da8 -> 7f8d4fe.** main ist damit Sonar-grün auf dem Trunk.
- Gefixte Regeln: S1110 (redundante Klammern), S7632 (Suppression-Syntax), S3776 (Complexity),
  S107 (zu viele Params -> Options-Objekt), Modul-/Klassen-LOC, S1192 (Duplicate-Literals),
  S2638 (Override-Signatur), + Postgres-Bootstrap-DDL-Serialisierung + Adversarial-QA-Fixture-Worktrees.

## OFFENER PUNKT — Branch-Integration (Entscheidung noetig)
- `main` steht jetzt auf 7f8d4fe (Sonar-Cleanup). Die DONE/IN-ARBEIT-Story-Branches wurden von
  einem AELTEREN `main` (ac01da8) geschnitten und sind NICHT auf main:
  - `ag3-057-mode-determination` (b96bcb5, DONE)
  - `ag3-070-config-model` (95bb761, DONE)
  - `ag3-061-evidence-assembly-core` (45931b7, Verify laeuft)
- Vor Merge nach main muessen diese auf das neue main (7f8d4fe) rebased/gemerged werden, damit sie
  die Sonar-Fixes tragen und keine alten Violations reintroducen. Reihenfolge + Merge-Politik
  (sammeln vs. sofort nach main) ist eine PO-Entscheidung.

## AG3-061 VERIFY (laeuft, 2026-06-08)
- Hostile Opus-Verify (isolierter Worktree, read-only) gegen `ag3-061-evidence-assembly-core`,
  gegen Story-AC + GAC-1/2. Bei APPROVE -> AG3-090 starten. Bei CHANGES-REQUESTED -> Remediation
  auf dem AG3-061-Branch (Code-Writer, Live-Tree-Exklusivitaet) vor AG3-090.

## POLL-REGEL (PO 2026-06-08)
- Bei JEDEM laufenden Codex-Worker (submit-Job) alle ~10 Min via ScheduleWakeup pollen (status/list), ob fertig — Codex meldet sich NICHT von selbst zuverlaessig. Erst bei "completed" Ergebnis ziehen. Aktiver Job: Sonar-Cleanup job-ca489037.

---

## AKTUELLER STAND — 2026-06-09 (autoritativ, ersetzt aeltere Notizen oben)

### Arbeitsmodus (PO-Vorgaben, aktuell gueltig)
- **Umsetzung ausschliesslich mit Codex** (kein Sonnet-Agent).
- **Ausschliesslich auf `main`** — KEINE Branches, KEINE Worktrees. Codex committet direkt auf `main`; Push macht der Orchestrator.
- **Halt-and-wait:** nach jeder implementierten + gepushten Story wird NICHTS Neues automatisch angestossen; der Orchestrator haelt an und wartet auf explizites PO-Go.
- **Verifikation je Story vor Commit:** broad `pytest tests/unit tests/contract` (0 failed) + `pytest --collect-only` (0 Importfehler) + `mypy src` (+`--platform linux`) + `ruff` + GAC-1 + Konzept-Gates. (Reine scoped Tests reichten nicht — AG3-059 hatte Laufzeit-Brueche in fernen Tests durchgelassen.)
- **`.mcp.json`** wird NICHT committet (lokale venv-Pfad-Aenderung, maschinenspezifisch).

### Auf `main` fertig & gepusht
- Basis/Integration: Sonar-Cleanup `7f8d4fe`; AG3-057 `b96bcb5`, AG3-070 `95bb761`, AG3-061 `9e84b32`, AG3-090 (`3352411`) — via Branch-Phase auf main integriert (`81d5e64`).
- Direkt auf `main` (Codex): AG3-098 `e4ab949` · AG3-059 `72b6e74` · AG3-060 `b6879a1` · AG3-064 `a517549` · AG3-066 `044fc09` · AG3-073 `6970332` · AG3-075 `0bfbc58` · AG3-077 `361b2d4` · AG3-080 `cf1c2c6` · AG3-087 `74ca012` · **AG3-095 `7137fbe`**.
- AG3-059-Regression (stale Phase-State-Imports + 23 PhaseState-Testfehler): `ee20ab5` — `main` voll grün.

### Review-Status
- Die direkt-auf-main-Stories wurden auf gruener **automatisierter** Gate-Batterie (broad unit+contract, collect-only, mypy, ruff, GAC-1, Konzept-Gates) committet. **Unabhaengiger hostile Review** lief bisher nur fuer AG3-061 + AG3-090 (Branch-Phase).
- **AG3-095 — implementiert + gepusht (`7137fbe`), aber NOCH NICHT REVIEWT.** Kein hostile/unabhaengiger Review, keine Review-Runde durchlaufen. Offen.

### Wave 0 — Restliste
- **AG3-096** (task-management-bc) — Backlog (wartet auf PO-Go).
- **AG3-102** (doc-only, producer-envelope-naming) — Backlog.
- Danach Wellen 1–6 (siehe Wellen-Tabelle oben).

### Offene Entscheidungspunkte
- Siehe `stories/_OPEN_DECISIONS.md` (D1–D15 No-Owner/Konzept-Entscheidungen, E1–E4 Scope-Erweiterungen, X1–X11 doc-only-Drifts, I1–I4 Index-Korrekturen).

### Neue Cut-Items aus Entscheidungen (AG3-106+)
- **AG3-106** harness-posttool-outcome-adapter (S, BC harness-integration) — aus D2 (PO 2026-06-09). Claude-Code-/Codex-Adapter füllen `HookEvent.post_tool_outcome` beim PostToolUse → Worker-Health sieht echte Tool-/Commit-Fehler. Story angelegt; Implementierung offen (PO-Go).
- **AG3-107** remove-phasestatus-blocked-live (M, pipeline_engine+bootstrap) — aus D1 (PO 2026-06-09). `PhaseStatus.BLOCKED` aus Live-Enum + komplette `"blocked"`-Terminal-Vertragskette; Audit `AttemptOutcome.BLOCKED`/`PRECONDITION_FAILED` bleibt. Story angelegt + Codex-APPROVE; Implementierung offen.
- **AG3-108** story-check-outcome-metrics (M, story-closure+telemetry) — aus D6 (PO 2026-06-09). Per-Check-Outcome-Projektion (FK-69 §69.8) + ProjectionFilter check_ref/since_days + Population aus echten verify/closure-Runs. Story angelegt; Codex-Review läuft; Implementierung offen.
- **AG3-109** runtime-execution-purge-port (M, pipeline/governance/telemetry/artifacts + Port; Konsument AG3-071) — aus D3 (PO 2026-06-09). Koordinierter Per-Owner-Purge der Runtime-Execution-Entitaeten (FK-53 §53.6.2/§53.7.5), idempotent, verify-clean-state. FK-53 §53.7.5 um Per-Owner-Port-Realisierung ergänzt. Story angelegt; Codex-Review + Implementierung offen.
