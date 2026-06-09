# AG3-075 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` only. No production code, tests, or
concept files touched; `status.yaml` left unchanged (no field is genuinely
wrong — see §status.yaml below). Every code anchor below was re-verified
against the real tree at remediation time and corrected to `file:line`.
Strictly within the AG3-075 cut (FK-36 §36.4-§36.9).

## Must-Fix ERRORs

### MF1 — `project_key`-Quelle fuer `epoch_writer`/Manifest/Store verbindlich spezifizieren (review §1 ERROR, §Must-Fix 1)
**Finding:** Story fordert Store-Schluessel `(project_key, story_id)` + atomare
Updates, aber `.agentkit-story.json` trug nur `story_id`/`run_id`/`created_at`
(FK-36 §36.9.4 `:507` nennt ebenfalls nur `story_id`/`worktree_id`/`created_at`).
Damit war nicht definiert, wie `epoch_writer` `project_key` deterministisch
ermittelt (cwd-Heuristik waere ein Ratespiel).
**Resolution (in-story):** `project_key` ist **bereits** Pflichtfeld am Modell
(`StoryContext.project_key`, `story_context_manager/models.py:312`, non-empty-Validator
`:326-331`) und liegt am Worktree-Setup vor (`governance/setup_preflight_gate/worktree.py:38-45`,
`setup_worktrees(story_id, context: StoryContext, ...)`). Kein neues Feld, kein
Schattenfeld (FIX-THE-MODEL). Daraus:
- In-Scope 10: Marker `.agentkit-story.json` traegt jetzt explizit `project_key`
  (Quelle `StoryContext.project_key`); deterministische Store-Schluessel-Quelle
  fuer `epoch_writer` (Walk-up-Discriminator, DD-04).
- In-Scope 3: Spawn-Spec traegt `project_key` als explizites Feld; jeder
  Konsument liest `(project_key, story_id)` aus der Spawn-Spec statt aus cwd.
- In-Scope 5: `manifest_writer` liest `project_key` aus der Spawn-Spec, schreibt
  es ins Manifest, Store-Lookup ueber `(project_key, story_id)`.
- AC4/AC5/AC7/AC10 entsprechend praezisiert.
Konzept-Erweiterung (FK-36 §36.5.2 und §36.9.4 nennen `project_key` heute nicht)
→ als doc-only-Nachzug gemeldet (§2.2 / §6), NICHT im Code-Cut geaendert.

### MF2 — Falsche/stale Ist-Zustand-Anker, bes. `bootstrap/composition_root.py:132` (review §3 ERROR + WARNING, §Must-Fix 2)
**Finding:** `src/agentkit/composition_root.py:132` existiert nicht (real:
`src/agentkit/bootstrap/composition_root.py:132`); Session-Range `193-207` war
stale (realer `materialize_prompt`-Aufruf `:207-214`, Rueckgabe `:215`).
**Resolution (in-story):** Alle drei Vorkommen korrigiert (§1 Ist-Zustand, §1
Anknuepfungspunkte, §6 Hinweise):
- `composition_root.py:132` → `bootstrap/composition_root.py:132` (verifiziert:
  Zeile 132 = `register_prompt_runtime_producers(registry)`).
- `session.py:193-207` → `implementation/worker_session/session.py:207-215`
  (Aufruf `:207-214`, Rueckgabe `:215`); Methode `compose_worker_prompt`
  `:169-215`.
- Registrierungs-Symbol praezisiert: `register_prompt_runtime_producers` (statt
  vager `prompt_runtime/register.py`-Nennung).

### MF3 — Fail-open/fail-closed als testbarer Exit-/Output-Vertrag (review §2 ERROR, §Must-Fix 3)
**Finding:** AC11 sagte nur „abgewiesen"; Story mischte „fail-open bei Drift"
mit „fail-closed gilt fuer Drift-Hash-Erkennung" ohne Exit-/Output-Vertrag pro
Fall (Exit-Code, stderr, ob gelesen/geschrieben wird, ob Agent weiterlaeuft).
**Resolution (in-story):** Pro Hook ein expliziter, testbarer Vertrag:
- In-Scope 5 (`manifest_writer`): je Fall exit 0, **kein** Manifest-Schreiben,
  stderr-Warning bei unparsebarem `spawn_key`/fehlender Spawn-Spec/Hash-Mismatch;
  Path-Traversal fail-closed vor Pfadbildung.
- In-Scope 6 (`recovery_injector`): 7 benannte Faelle (a-g), alle exit 0, mit
  exakter `additionalContext`-Semantik, First-Tool-Guard, DD-09-Tool-Policy
  (kein exit 2), Drift → kein Inject.
- In-Scope 7 (`epoch_writer`): exit 0 je Fall, Update nur bei vollstaendigem
  Marker, sonst stderr-Warning + kein Update.
- AC6/AC7/AC8/AC11/AC12 in einzelne testbare Faelle zerlegt; Guardrail-Bullet
  „FAIL-CLOSED vs FAIL-OPEN" auf den Vertrag verweisend praezisiert.
Klarstellung: „fail-closed" heisst hier „verarbeite nicht still falsche Daten"
(stderr-Warning, kein Inject/Lesen gedrifteter Dateien) — bleibt exit 0, weil
ein PreToolUse/PostCompact-Hook den Agent nie crashen darf (FK-36 §36.13 DD-11).

### MF4 — Remote-Gate `scripts/ci/check_remote_gates.ps1` in AC/DoD (review §2 ERROR, §Must-Fix 4)
**Finding:** AC13 nannte lokale Tests/Lint/Typisierung/Konzept-Gates, aber nicht
das verpflichtende Remote-Gate fuer Jenkins + Sonar.
**Resolution (in-story):** AC13 um `scripts/ci/check_remote_gates.ps1` ergaenzt
(AGENTS.md:43-45): Jenkins gruen + Sonar-Gate `OK` + strikte Nullmetriken
`violations=0`/`critical_violations=0`/`security_hotspots=0`
(`check_remote_gates.ps1:75-83`). DoD entsprechend ergaenzt (mit Hinweis, dass
das Gate mit der Implementierung verbindlich wird, da die Story zunaechst nur
autorisiert/reviewt wird). §6 „done"-Beleg-Liste ergaenzt.

### MF5 — Zentraler Epoch-Store mit State-Backend-Owner, Schema/Migration, atomarer Repository-API (review §4 ERROR, §Must-Fix 5)
**Finding:** Store war in `pipeline_engine/compaction_resilience` verortet, ohne
Code-Owner/Schema-Anschluss; der bestehende zentrale Persistenzpfad ist
`state_backend`; kein `(project_key, story_id, epoch, updated_at)`-Schema +
Repository/Migration als Owner-Vertrag beschrieben.
**Resolution (in-story):** In-Scope 9 als Owner-Vertrag neu gefasst (FIX-THE-MODEL,
SINGLE SOURCE OF TRUTH):
- Tabelle `compaction_epochs` (`PRIMARY KEY (project_key, story_id)`) in **beiden**
  Schema-Ownern: `state_backend/postgres_schema.sql` (analog `story_contexts`
  `:4`, `flow_executions` `:125`, `execution_events` `:154`) und
  `state_backend/sqlite_store.py` (`:108` als Muster).
- Idempotente, versionierte Migration unter `state_backend/migration/versions/`
  (Muster `v_3_4_analytics.sql`), via `MigrationRunner`.
- Repository `state_backend/store/compaction_epoch_repository.py` (Muster der
  bestehenden `store/*_repository.py`) mit atomarer API: `read_epoch` +
  `increment_epoch` (Postgres `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`,
  SQLite `BEGIN IMMEDIATE`/Single-Statement-UPSERT).
- `compaction_resilience` konsumiert **nur** diese API (DI via Composition-Root,
  Store-Handle ueber `state_backend/config.py:173` `load_state_backend_config`).
- BC-Header + §2.2 + AC9 + §6 entsprechend angeglichen.
Kein Scope-Transfer: der `_STORY_INDEX.md` traegt keine Story, die diesen Store
liefert; AG3-075 ist sein einziger Konsument und alleiniger Lieferant. Es ist
eine korrekte Modul-Schicht-Zuordnung innerhalb des AG3-075-Cuts (das
`state_backend` ist foundational und bereits gebaut — AG3-087 ergaenzt dort
ebenfalls Tabellen ohne eigene Backend-Core-Dependency).

## WARNINGs

### W1 — FK-36 DD-09 vs §36.10/§36.11 Widerspruch markieren (review §1 WARNING)
**Finding:** §36.10 („Agent-Spawn-Deny", `:534`) und §36.11 („Agent-Spawns
werden blockiert", `:547`) tragen den alten Deny-Stand; DD-09 (`:660-663`,
explizit „revidiert") sagt „Inject + Warn (exit 0), kein hartes Deny". Story
folgte DD-09, markierte die widersprechenden FK-Stellen aber nicht konkret.
**Resolution (in-story):** Neuer normativer Hinweis-Block unter den Quell-Konzepten
benennt den Widerspruch mit exakten Zeilen und haelt **DD-09 als gueltige
Prioritaet** fest (juengste, „revidiert"-markierte Entscheidung; Deny ohne
Wiederherstellungspfad waere destruktiv + kollidiert mit within-story False
Positives). §2.2 Doc-only-Liste Punkt 2 + §6 Fallstrick-Bullet ergaenzt.
(Doc-follow-up an FK-36 gemeldet, NICHT befolgt/geaendert.)

### W2 — Session-Line-Range stale/zu knapp (review §3 WARNING)
Identisch mit MF2 (Session-Range). `193-207` → `207-215` (Aufruf `:207-214`,
Rueckgabe `:215`), Methode `:169-215`. Resolved wie oben.

## NIT

### N1 — `_temp`/`var`-Konflikt ueberzeichnet, ARCH-55 falsch begruendet (review §3 NIT)
**Finding:** `.gitignore:52-59` dokumentiert `/_temp/` explizit als ephemeres
Laufzeitverzeichnis (Konzept §92); der ARCH-55-Verweis war falsch und der
Konflikt aufgebauscht.
**Resolution (in-story):** ARCH-55-Begruendung entfernt. §1 Kontext-Konflikt-Check
neu gefasst: `_temp/` ist kanonisch + bereits gitignored (FK-36 §36.9.3 `:493`,
§36.10 `:525`); echte Pfadentscheidung knapp begruendet — **`_temp/` gemaess
FK-36 verwenden**, kein neues Top-Level-Verzeichnis, kein Umweg ueber
`.agentkit/prompts`. In-Scope 11 + §6 Fallstrick angeglichen.

## Korrigierte/verifizierte Code-Anker (alle gegen den realen Tree geprueft)
- `bootstrap/composition_root.py:132` (= `register_prompt_runtime_producers`) —
  korrigiert von falschem `composition_root.py:132`.
- `implementation/worker_session/session.py:169-215` / Aufruf `:207-214` /
  Rueckgabe `:215` — korrigiert von stale `193-207`.
- `story_context_manager/models.py:312` (`StoryContext.project_key`, Validator
  `:326-331`) — neue, belegte `project_key`-Quelle.
- `governance/setup_preflight_gate/worktree.py:38-45` (`setup_worktrees`) —
  Worktree-Setup-Punkt, an dem `StoryContext` vorliegt (Marker-Producer).
- `state_backend/postgres_schema.sql:4/:125/:154` + `state_backend/sqlite_store.py:108`
  — Schema-Owner-Muster fuer `compaction_epochs`.
- `state_backend/migration/versions/v_3_4_analytics.sql` (Muster) +
  `state_backend/config.py:173` (`load_state_backend_config`).
- `scripts/ci/check_remote_gates.ps1:75-83` + `AGENTS.md:43-45` — Remote-Gate.
- `.gitignore:52-59` — `_temp/` als ephemeres, gitignored Laufzeitverzeichnis.
- FK-36 `:493/:507/:525/:534/:547/:660-663` — Drift-/Widerspruch-Belege.

## status.yaml
Unveraendert. `phase: review_pending` bleibt korrekt fuer den laufenden
Review-Zyklus; `status: draft` korrekt (Story wird nur autorisiert/reviewt, kein
Commit). `depends_on: [AG3-024, AG3-015]` bleibt korrekt: das `state_backend`
(neuer `compaction_epochs`-Table-Owner) ist foundational und bereits gebaut —
es ist keine Backlog-Story und damit keine neue Dependency (gleiches Muster wie
AG3-087, das im `state_backend` Tabellen ergaenzt ohne Backend-Core-Dependency).
Kein Feld war genuin falsch; daher nicht angefasst (Auftrag: nur bei genuin
falschem Feld).

## Genuine cross-story Voraussetzungen / Folge-Einheiten
1. **AG3-088 (Welle 6) — Installer/Harness-Hook-Bindung** (FK-50). Bleibt
   Out-of-Scope mit klarem Owner: AG3-075 liefert die `python -m`-Module, der
   Installer verdrahtet die `settings.json`-Hook-Eintraege. War bereits korrekt
   verlagert. Kein Scope-Transfer.
2. **doc-only Konzept-Nachzug an FK-36** (thematisch AG3-104 / FK-36-zustaendige
   doc-only-Einheit) — vier gemeldete Drifts, KEINE davon im AG3-075-Code-Cut zu
   aendern:
   (a) `agentkit.prompting.compose` → `prompt_runtime/composer.py`;
   (b) DD-09 vs. §36.10/§36.11 (alter Deny-Stand);
   (c) `project_key` fehlt in §36.5.2 (Spawn-Spec) und §36.9.4 (Marker);
   (d) `_temp/`-Pfade sind bereits kanonisch/gitignored (kein offener Konflikt).

Hinweis zur Cut-Treue MF5: Der Epoch-Store-Persistenz-Owner `state_backend`
liegt **innerhalb** der korrekten Modulgrenzen (FK-18 / bestehende
`state_backend`-Schema-/Repository-Konvention) und ist kein Auslagern an eine
andere Story — es existiert keine Story, die diesen Store liefert, und AG3-075
ist sein einziger Konsument. Die Hook-/Producer-Logik bleibt in
`pipeline_engine/compaction_resilience`; nur Schema/Migration/Repository des
zentralen Stores leben dort, wo der gesamte zentrale `(project_key, story_id)`-
keyed State lebt.
