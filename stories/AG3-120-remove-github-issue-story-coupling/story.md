# AG3-120: GitHub-Issue-Story-Kopplung restlos entfernen (`issue_nr`-Spine, Variante B)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `setup-preflight` / `story-lifecycle` / `github-integration` (cross-cutting). Die Story entfernt eine AK2-Altlast: AK3 hat eine **eigene** User-Story-Verwaltung (`StoryContext.story_id`, branch-sicher ueber `story/{story_id}`), GitHub ist ausschliesslich Code-Backend. Heute speist das Setup den Story-Kontext jedoch aus einem GitHub-Issue (`get_issue` → `issue.number` → `StoryContext.issue_nr`), persistiert `issue_nr` als Story-Attribut, injiziert es in Worker-Prompts und traegt ein totes `_close_github_issue` durch die Closure. Diese Kopplung widerspricht FK-12 §12.1.1 und FK-91 §91.2 Regel 9 und wird **vollstaendig** entfernt (Mark & Ask Runde 2: Variante B = Vollentfernung, nicht nur Entkopplung).

**Quell-Konzepte (autoritativ):**
- `FK-12 §12.1.1` — Abgrenzung zur Story-Autoritaet: „GitHub Issues/Projects als Story-Verwaltung waren ein verworfenes AK2-Experiment und werden in AK3 nicht mehr verwendet" (`12_github_integration_repo_operationen.md:56-71`).
- `FK-91 §91.2 Regel 9` — Stories werden ausschliesslich ueber die Control-Plane-API angelegt/mutiert; externe Referenzen sind „niemals Wahrheitsquelle fuer Story-Identitaet, -Status oder -Story-Attribute" (`91_api_event_katalog.md:171-176`).
- `FK-22 §22.4` — Story-Context-Berechnung als Setup-Owner des `StoryContext`; der Kontext wird nicht mehr aus einem Issue gespeist (`22_setup_preflight_worktree_guard_activation.md`).
- `domain-design/10` + `technical-design/02_domaenenmodell_zustaende_artefakte.md` — Story-Identitaet = `story_id` (Konzeptseite bereits geradegezogen, Commits `36a55ee` + `6c1b6ac`).
- `FK-17` (`17_fachliches_datenmodell_ownership.md`) — fachliches Datenmodell/Ownership: Story-Stammdaten-Owner ist der AK3-Story-BC; `issue_nr` ist kein ownership-getragenes Story-Attribut.
- `FK-18 §18.9a` (`18_relationales_abbildungsmodell_postgres.md`) — relationale Postgres-Abbildung der `story_contexts`-Tabelle + `schema_version`-Migrationsmechanik fuer den `issue_nr`-Spalten-Drop.
- `FK-91 §91.1/§91.1a` + `FK-45 §45.1/§45.4` — Service-API-/CLI-Adapterverhalten: `run-story`/Phase-Start identifizieren die Story ueber `story_id`/Control-Plane-Vertrag, nicht ueber `--issue-nr`.
- `formal.setup-preflight.commands` + `formal.story-closure.commands` — formale Command-Contracts fuer Setup-/Closure-Pfad; sind auf einen Ablauf ohne Issue-Eingabe zu pruefen/mitzuziehen.

---

## 1. Kontext / Ist-Zustand (belegt)

> Re-verifiziert gegen den aktuellen Code (`src/agentkit/backend/...`). Mehrere Zeilen aus der Abweichungskarte (WP-H) sind gewandert; unten der **aktuelle** Stand.

- **H1 — Adapter (komplettes Issue-CRUD):** `src/agentkit/integration_clients/github/issues.py` exportiert `IssueData` (`:17`), `get_issue` (`:58`), `create_issue` (`:88`), `close_issue` (`:130`), `reopen_issue` (`:148`), `add_labels` (`:166`), `remove_labels` (`:186`), `add_comment` (`:208`). `integration_clients/github/__init__.py:20-43` re-exportiert alle Issue-Funktionen im `__all__`.
- **H2 — Setup (Spine-Wurzel):** `backend/governance/setup_preflight_gate/context_builder.py:18` importiert `get_issue`; `:215` liest das Issue live; `:223` `story_number ... or issue.number`; `:254`/`:276` `issue_nr=issue.number`. `backend/governance/setup_preflight_gate/phase.py:104` traegt das Pflichtfeld `issue_nr: int`, `:303` `issue_nr=cfg.issue_nr`.
- **H2 — Fail-closed-Gate:** `backend/bootstrap/composition_root.py:2609` erzwingt fuer codeproduzierende Stories `ctx.issue_nr > 0` (sonst fail-closed E5, `:2612`); `:2618` baut `SetupConfig(... issue_nr=ctx.issue_nr ...)`; Docstrings `:2414`/`:2509`/`:2553`/`:2570` zementieren `issue_nr` als Pflicht-Eingabe.
- **H3 — Core-Modell + Persistenz:** `backend/story_context_manager/models.py:49` `issue_nr: int | None`; `backend/story/models.py:72`; `backend/story/service.py:80` (`issue_nr=context.issue_nr`); Schema `backend/state_backend/postgres_schema.sql:15` (`issue_nr INTEGER`); `backend/state_backend/sqlite_store.py:123` (DDL) + Insert/Upsert `:1531`/`:1542`/`:1555`/`:1612`/`:1623`/`:1636`; `backend/state_backend/postgres_store.py:882`/`:893`/`:906`/`:964`/`:975`/`:988`; `backend/state_backend/store/mappers.py` (`issue_nr`-Mapping).
- **H4 — Closure (totes Beiwerk):** `backend/closure/phase.py:194` `ClosureConfig.issue_nr: int | None`; Aufrufer `:420` (`_close_github_issue(cfg)`); Funktion `_close_github_issue` `:1141`, ruft `gh_close_issue(cfg.owner, cfg.repo, cfg.issue_nr)` `:1155`, baut `issue_ref` `:1157`/`:1163`. Wird im Hauptpfad nie sinnvoll befuellt (no-op).
- **H5 — Prompt-Injektion:** `backend/prompt_runtime/composer.py:137` (`"issue_nr": str(ctx.issue_nr) if ... else "N/A"`); Platzhalter `#{issue_nr}` in den Templates `bundles/internal/prompts/worker-{exploration,implementation,bugfix,concept,research}.md` (z. B. `worker-implementation.md:7` `- **Issue:** #{issue_nr}`) und `qa-adversarial-review.md`.
- **H6 — CLI:** `backend/cli/main.py:170` `--issue-nr` (`type=int, required=True`, Hilfetext „GitHub issue number"); `:1002` `print(... issue #{args.issue_nr})`; Docstring `:996`.
- **Selbst-Beleg der halben Migration:** Story-**Erzeugung** ist bereits AK3-Control-Plane (kein `gh issue create`); nur das Setup-**Lesen** des Issues und die `issue_nr`-Persistenz blieben haengen.
- **Spine:** Setup liest Issue (H2) → `StoryContext.issue_nr` (H3) → Persistenz/Projektion → Prompt (H5) → Closure-Close (H4, tot). Eingangstor: CLI `--issue-nr` (H6).

## 2. Scope

### 2.1 In Scope

1. **H2 — Setup von der Issue-Quelle loesen:** `get_issue`-Import und -Aufruf in `context_builder.py` entfernen; `StoryContext` wird ausschliesslich aus `story_id` und den vom AK3-Story-Service gelieferten Attributen gebildet (FK-22 §22.4). Das `issue.number`-Fallback fuer `story_number` faellt weg; `story_number` wird, falls weiter benoetigt, deterministisch aus `story_id` abgeleitet (bestehende `_story_number_from_id`-Logik) ohne Issue-Quelle.
2. **H2 — Fail-closed-Gate umstellen:** Das `issue_nr > 0`-Pflichtgate in `composition_root.py:2609-2618` wird entfernt bzw. auf die **vorhandene** AK3-Identitaet (`story_id` und ggf. `owner`/`repo` fuer Git-Mechanik) umgestellt. Die Fail-closed-Strenge bleibt erhalten (codeproduzierende Stories brauchen weiter eine aufloesbare Identitaet) — nur die **Quelle** wechselt von `issue_nr` auf `story_id`. Kein Aufweichen des Gates.
3. **H3 — `issue_nr` aus Domaenenmodell + Persistenz restlos entfernen:** Feld streichen in `story_context_manager/models.py:49`, `story/models.py:72`, Setup-`SetupConfig`/`phase.py:104`, `closure/phase.py:194`; Schreibpfade in `story/service.py:80`. Persistenz: Spalte `issue_nr` aus `postgres_schema.sql:15` und `sqlite_store.py:123` entfernen, alle Insert/Upsert/Read-Stellen in `postgres_store.py` (`:882`-`:988`), `sqlite_store.py` (`:1531`-`:1636`) und `mappers.py` bereinigen. Die Schema-/`schema_version`-Konsequenz wird mitgezogen (FK-03/FK-18; Contract-/Golden-Tests aktualisieren — CLAUDE.md „State und Artefakte").
4. **H4 — Closure-`_close_github_issue` entfernen:** Funktion (`closure/phase.py:1141`), Aufruf (`:420`), `ClosureConfig.issue_nr` (`:194`) und die `gh_close_issue`-Nutzung streichen. Closure schliesst Stories ueber den AK3-Story-Service, nicht ueber GitHub-Issue-Mechanik (FK-91 §91.2 Regel 9).
5. **H5 — Prompt-Platzhalter entfernen:** `issue_nr`-Variable aus `prompt_runtime/composer.py:137` und den Platzhalter `#{issue_nr}` aus allen sechs Prompt-Templates (`worker-*.md`, `qa-adversarial-review.md`) streichen. Wo der Worker einen Story-Bezug braucht, tritt `story_id` an die Stelle.
6. **H1 — Issue-CRUD-Adapter zurueckbauen:** `integration_clients/github/issues.py` und die Issue-Exports in `github/__init__.py:20-43` werden entfernt, **sofern** nach H2-H6 kein produktiver Aufrufer mehr existiert (vorab per Repo-weitem Aufruf-Sweep belegen). Der `gh`/`git`-Client fuer Code-/Branch-Mechanik (`run_gh`, `resolve_token_for_owner`) bleibt unangetastet (FK-12 §12.1 Carve-out).
7. **H6 — CLI `--issue-nr` entfernen:** Argument (`cli/main.py:170`) und die `issue #{...}`-Ausgabe (`:1002`) streichen; der `run-story`-Adapter identifiziert die Story ueber `story_id`/Control-Plane-Vertrag.
8. **CLAUDE.md-Alt-Zeile angleichen (klein, in-scope):** Die Zeile „GitHub-Felder sind Eingabe fuer Setup, aber nicht die operative Wahrheit ..." im Repo-`CLAUDE.md` (Abschnitt SINGLE SOURCE OF TRUTH) wird auf den neuen Stand gezogen (GitHub = Code-Backend, keine Issue-Eingabe). Reine Textangleichung, keine Regelaufweichung.
9. **H7 — Deployte Skill-Bundles bereinigen (sonst Rest-Drift):** Die ausgelieferten Agent-Instruktionen tragen noch GitHub-Issue-Kopplung: `bundles/skill_bundles/execute-userstory-core/4.0.0/SKILL.md:133` (`context.issue_nr → <ISSUE-NR>`) und `:449` (`--issue-nr <ISSUE-NR>`), `bundles/skill_bundles/lookup-userstory-core/4.0.0/SKILL.md:82` (`issue_nr` im Feldkatalog). Diese werden auf `story_id`/Control-Plane-Story-Vertraege umgestellt; deployte Skills referenzieren danach **kein** `issue_nr`/`--issue-nr` mehr. (Die `create-userstory-core/SKILL.md:20/1041`-Zeilen „there is NO `gh issue create`" sind korrekt und bleiben.) Golden-/Skill-Manifest-Tests fuer die Bundles werden mitgezogen.

### 2.2 Out of Scope (mit Owner)

- **Konzept-Seite (HK1-HK4):** bereits erledigt (Commits `36a55ee` + `6c1b6ac`); kein `concept/`-Diff in dieser Story. Grep nach `Issue-Nummer|gh issue|issue_nr` in `concept/` ist leer.
- **`gh`/`git`-Code-Mechanik** (Branch/Worktree/Merge, `run_gh`) — bleibt (FK-12 §12.1 Carve-out); Owner `github-integration`.
- **B8 GitHub-API-Metadaten-Vermittlung** (Kern-vermittelt vs. Carve-out) — eigenes Thema der Zentralisierung (WP-B/B8), nicht Teil dieser Altlast-Entfernung.
- **Daten-Migration bestehender Postgres-Bestaende** (`issue_nr`-Spalten-Drop in produktiven DBs) — folgt der `schema_version`-Migrationsmechanik (FK-18 §18.9a); diese Story liefert das Schema ohne `issue_nr` + die Migration, keine Ops-Ausfuehrung.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/integration_clients/github/issues.py` | Entfernen (Issue-CRUD-Adapter, nach Aufruf-Sweep) |
| `src/agentkit/integration_clients/github/__init__.py` | Aendern (Issue-Exports `:20-43` raus) |
| `src/agentkit/backend/governance/setup_preflight_gate/context_builder.py` | Aendern (`get_issue`-Import/-Aufruf raus, Kontext aus `story_id`) |
| `src/agentkit/backend/governance/setup_preflight_gate/phase.py` | Aendern (`issue_nr`-Pflichtfeld + Durchreichung raus) |
| `src/agentkit/backend/bootstrap/composition_root.py` | Aendern (Fail-closed-Gate `:2609-2618` auf `story_id`) |
| `src/agentkit/backend/story_context_manager/models.py` | Aendern (`issue_nr`-Feld `:49` raus) |
| `src/agentkit/backend/story/models.py`, `story/service.py` | Aendern (`issue_nr`-Projektion raus) |
| `src/agentkit/backend/closure/phase.py` | Aendern (`_close_github_issue`, `ClosureConfig.issue_nr` raus) |
| `src/agentkit/backend/state_backend/postgres_schema.sql`, `sqlite_store.py`, `postgres_store.py`, `store/mappers.py` | Aendern (Spalte + Insert/Upsert/Read raus) + `schema_version`-Migration |
| `src/agentkit/backend/prompt_runtime/composer.py` | Aendern (`issue_nr`-Variable raus) |
| `src/agentkit/bundles/internal/prompts/worker-{exploration,implementation,bugfix,concept,research}.md`, `qa-adversarial-review.md` | Aendern (`#{issue_nr}`-Platzhalter raus) |
| `src/agentkit/bundles/skill_bundles/execute-userstory-core/4.0.0/SKILL.md`, `lookup-userstory-core/4.0.0/SKILL.md` | Aendern (`issue_nr`/`--issue-nr` → `story_id`) |
| `src/agentkit/backend/cli/main.py` | Aendern (`--issue-nr` `:170` + Ausgabe `:1002` raus) |
| `CLAUDE.md` | Aendern (eine Alt-Zeile, §2.1.8) |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**`, `tests/golden/**` | Aendern/Ergaenzen (siehe AC 2-6, 8, 11; Golden/Schema/Skill-Manifest-Updates) |

## 3. Akzeptanzkriterien

1. Kein Produktionspfad liest oder schreibt `issue_nr` mehr: Repo-weiter Sweep (`issue_nr`, `--issue-nr`, `get_issue`, `_close_github_issue`, `gh_close_issue`, `#{issue_nr}`) in `src/agentkit/` (inkl. `bundles/internal/prompts` **und** `bundles/skill_bundles`) liefert ausschliesslich entfernte/leere Treffer (ausser neutralen Migrationsnotizen). `StoryContext` traegt kein `issue_nr`-Feld mehr.
2. Setup baut den `StoryContext` ohne `get_issue`: ein **echter Integrationstest** (realer `StoryService` + reales State-Backend, **kein** Fake-/In-Memory-Repo) belegt, dass eine codeproduzierende Story ohne jegliche Issue-Eingabe vollstaendig durch Setup laeuft und der Kontext aus `story_id` + Story-Service-Attributen entsteht; der Test beweist zugleich, dass `setup_preflight_gate` kein `get_issue` mehr importiert/aufruft.
3. Das fruehere `issue_nr>0`-Fail-closed-Gate ist auf `story_id` umgestellt: fehlt eine aufloesbare AK3-Story-Identitaet, scheitert Setup weiterhin fail-closed (**Negativpfad-Test an der Phasengrenze**, testing-guardrails §1/§3); eine fehlende `issue_nr` ist **kein** Fehlergrund mehr.
4. Persistenz ohne `issue_nr`: `postgres_schema.sql` und das SQLite-DDL enthalten keine `issue_nr`-Spalte; **reale Persistenztests gegen echtes SQLite UND echtes Postgres** (kein Fake-Repo) beweisen Schema-Anlage, Insert/Upsert/Read und dass Snapshots/Read-Modelle kein `issue_nr` enthalten; Contract-/Golden-Tests fuer Schema/Snapshot sind mitgezogen und gruen; `schema_version` ist erhoeht (FK-18 §18.9a).
5. Closure schliesst Stories ohne GitHub-Issue-Aufruf: `_close_github_issue`/`ClosureConfig.issue_nr` existieren nicht mehr; ein **Closure-Integrationstest gegen den realen AK3-Story-Service-Pfad** (nicht `NoOpStoryService`/Recording-Stub) belegt den Abschluss ohne `gh_close_issue`.
6. Worker-Prompts, QA-Adversarial-Prompt **und** die deployten Skill-Bundles (`execute-userstory-core`, `lookup-userstory-core`) enthalten keinen `#{issue_nr}`/`issue_nr`/`--issue-nr`-Bezug mehr; der Composer rendert keine `issue_nr`-Variable; Prompt-Contract-/Golden- und Skill-Manifest-Tests sind auf die neue Form gezogen.
7. Der Issue-CRUD-Adapter (`integration_clients/github/issues.py`) und seine Exports sind entfernt (oder, falls ein nicht-Issue-Aufrufer wider Erwarten bleibt, explizit begruendet); der `run_gh`/`git`-Code-Backend-Pfad bleibt funktionsfaehig (Regressionstest gruen).
8. **CLI-/API-Adapter-Vertrag:** `run-story`/Phase-Start akzeptieren ausschliesslich `story_id` und exponieren `--issue-nr` nicht mehr; ein CLI-/Contract-Test belegt, dass die Option entfernt ist und die Story ueber `story_id` adressiert wird (FK-91 §91.1a, FK-45 §45.4).
9. **ARCH-55:** alle verbliebenen Bezeichner, Wire-/DB-/Schema-Keys und Kommentare englisch; keine `noqa`/`type: ignore` ohne Begruendung.
10. **Testpyramide / keine Stub-Absicherung (testing-guardrails):** Die ACs 2/4/5 werden **nicht** durch Fake-/In-Memory-Repos oder manuell zusammengebauten Pipeline-State erfuellt (testing-guardrails §2). Boundaries, die Prozess-/REST-/DB-Grenzen kreuzen (Setup, Persistenz, Closure, CLI/API-Adapter), haben echte Integrations-/Contract-Tests; Unit-Tests decken die reine Umbaulogik ab.
11. **Quality-Gates gruen** (aus Repo-Root, GAC-konform):
    - `.venv\Scripts\python -m pip install -e ".[dev]"`, `.venv\Scripts\python -m pytest` (unit/integration/contract), Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`);
    - `.venv\Scripts\python -m mypy src` (strict, inkl. `--platform linux`), `.venv\Scripts\python -m ruff check src tests`;
    - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`;
    - **Remote-Gates** (`scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube-Gate gruen mit Zero-Violation-Policy** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code) — kein Merge bei roten Remote-Gates.

## 4. Definition of Done

- AK 1–11 erfuellt; Issue-Spine H1-H7 restlos entfernt (Variante B, inkl. deployter Skill-Bundles), kein paralleler Alt-/Neu-Zustand.
- Schema-/Contract-/Golden-/Skill-Manifest-Tests fuer den `issue_nr`-Wegfall sind mitgezogen; `schema_version`-Konsequenz dokumentiert.
- Pflichtbefehle + Konzept-Gates gruen; **Jenkins-Build gruen, SonarQube Zero-Violation gruen** (AC 11); QA-Subflow/Code-Review PASS; Status erst nach belegtem Diff + gruenen Befehlen auf `completed`.

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Die Story-Identitaet hat genau **einen** Owner (`story_id` im AK3-Story-Backend). Kein zweiter operativer Story-Schluessel (`issue_nr`) wird parallel weitergetragen — die Wurzel (Setup-Issue-Lesen) wird entfernt, nicht das Symptom kaschiert.
- **SINGLE SOURCE OF TRUTH:** GitHub ist Code-Backend, nicht Story-Traeger (FK-12 §12.1.1, FK-91 §91.2 Regel 9). Externe Referenzen sind nie Wahrheitsquelle.
- **FAIL CLOSED:** Das Identitaets-Gate bleibt fail-closed, wechselt nur die Quelle von `issue_nr` auf `story_id`; keine Aufweichung.
- **ZERO DEBT / NO ERROR BYPASSING:** Vollentfernung statt Entkopplung; keine toten `_close_github_issue`-Reste, keine verwaisten Schema-Spalten, keine Issue-Reste in deployten Skills, keine „spaeter sauber machen"-Verschiebung.
- **Testing-Guardrails (`guardrails/testing-guardrails.md`):** Negativpfade an den Phasengrenzen (Setup/Closure), **kein manuelles State-Setup als Ersatz fuer Pipeline-Flow** (§2), Precondition-Enforcement nachgewiesen — Tests gegen echte Komponenten, nicht gegen Stubs der zu pruefenden Sache.
- **ARCH-55:** englische Identifier/Keys verbindlich.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Reihenfolge bottom-up entlang des Spines: zuerst die Wurzel (H2 Setup + Gate) trockenlegen, dann Modell/Persistenz (H3), dann Closure (H4), Prompt (H5), Adapter (H1) und CLI (H6). Vor dem Adapter-Loeschen (H1) den Repo-weiten Aufruf-Sweep fahren — nichts entfernen, das noch einen Code-Backend-Aufrufer hat.
- `run_gh`/`git`-Mechanik und `resolve_token_for_owner` NICHT anfassen (FK-12 §12.1 Carve-out).
- Persistenz-Aenderung zieht `schema_version` + Contract-/Golden-Tests mit (CLAUDE.md „State und Artefakte"). Keine Schema-Aenderung ohne mitgezogene Tests.
- `concept/`-Dateien NICHT anfassen (Konzept ist bereits geradegezogen). Einzige Doc-Aenderung: die eine Alt-Zeile in `CLAUDE.md` (§2.1.8).
- Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Sweep-Ausgabe (leer), Testnamen (Setup-ohne-Issue, Fail-closed-Negativpfad, Closure, Prompt-Contract), gruene Pflichtbefehle.

## 7. Vorbedingungen

- Keine offenen Abhaengigkeiten (`depends_on: []`). Die Konzeptseite ist erledigt; der AK3-Story-Service (`story_id`-Identitaet) ist bereits produktiv.
- `unblocks`: keine.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed).
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
