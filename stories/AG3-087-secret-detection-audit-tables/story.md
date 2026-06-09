# AG3-087: Secret-Detection-Vollausbau + Audit-Tabellen + Servicepfad/Freeze-Nachweis

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** mehrteilig (ein lieferbarer governance-and-guards-Slice):
- `guard_system` — `GuardDecision`-Entitaet (FK-17 §17.3.11 Owner), Secret-Detection-Patterns + Content-Scan, Servicepfad-Verdict, Freeze-Nachweis, Sub-Agent-Rueckkanal-Filter.
- `story_context_manager` — `StoryCustomFieldDefinition`/`StoryCustomFieldValue` (FK-17 §17.3.4/5 Owner; FK-18 §18.3.1 Catalog-Family-Owner).
- `state_backend` — **nur Persistenzadapter** (postgres_schema.sql + sqlite_store.py); kein fachlicher Owner der Entitaeten.

**Quell-Konzepte (autoritativ):**
- `FK-15 §15.5.2` — **zweistufige** Secret-Detection: Stufe 1 Pre-Commit-Hook, Stufe 2 Structural-Check `security.secrets`; Pattern-Tabelle „beide Stufen identisch" (Datei-/Name-Patterns + Diff-Content-Scan `AKIA`/`ghp_`/`sk-`)
- `FK-15 §15.4` / `§15.5.1` — immer-aktive „Keine Secrets im Commit"-Regel; Basisschutz
- `FK-17 §17.3.11` — `GuardDecision` (kanonische append-only Audit-Entitaet, Owner `guard_system`)
- `FK-17 §17.3.4` / `§17.3.5` — `StoryCustomFieldDefinition` / `StoryCustomFieldValue` (Owner `story_context_manager`), vollstaendiger Feldsatz
- `FK-18 §18.3.1` / `§18.3.3` — Table-Families Catalog (`story_custom_field_definitions`/`_values`) und Governance (`guard_decisions`); `§18.4` Entitaet↔Tabelle-Mapping; `§18.6e.1`/`§18.6e.3` Pflichtspalten + optionale Spalten je Tabelle
- `FK-55 §55.6` — Verdict-Tripel `ALLOW`/`BLOCK`/`ALLOW_VIA_OFFICIAL_SERVICE_PATH`
- `FK-55 §55.3a` — zulaessige Attestierungsquellen eines Principals (4 Quellen)
- `FK-55 §55.9` — offizielle Servicepfade (Service-API + Operator-CLI) + Principal-Tabelle; „freier Bash nie = offizieller Servicepfad"
- `FK-55 §55.10.3 Step 8` — Auswertungsreihenfolge: offiziellen Servicepfad nur pruefen, wenn nicht bereits blocked; `§55.10.4` Referenz-Pseudocode `is_official_service_path(event, principal)`
- `FK-55 §55.10.7` — offizielle Servicepfade sind nicht per Bash spooffaehig (nur attestierte Aufrufe)
- `FK-55 §55.10.8` — Integrity-Freeze-Nachweis: Aktivierungszeit, geblockter Principal, offizieller Aufloesungspfad; kein Nachweis -> nicht closure-faehig
- `FK-55 §55.10.10` — Sub-Agent-Rueckkanal-Filter (nur schema-gebundene Steuerungsausgaben: `status`/`error_class`/`next_step`/`artifact_refs`/kurze strukturierte Begruendung)

---

## 1. Kontext / Ist-Zustand (belegt)

- **Secret-Detection einstufig statt zweistufig (UNVOLLSTAENDIG, FK-15 §15.5.2):** FK-15 verlangt **zwei** Stufen mit **identischen** Patterns — Stufe 1 Pre-Commit-Hook, Stufe 2 Structural-Check `security.secrets`. Real:
  - **Stufe 1 fehlt vollstaendig:** Der echte Pre-Commit-Hook ist `.githooks/pre-commit:19-31` und macht **nur** Concept-Validation (pfadbasiertes Dispatching); **kein** Secret-Scan. (Hinweis: FK-15 §15.5.2:198 nennt den Hook-Pfad `tools/hooks/pre-commit` — der reale Pfad ist `.githooks/pre-commit`; Doc-Drift, siehe §2.2.)
  - **Stufe 2 verkuerzt:** `src/agentkit/bootstrap/composition_root.py:773` `_SECRET_EXTENSIONS = (".env", ".pem", ".key", ".pfx", ".p12")`; `secret_files` wird (`:805-806`) **nur** per Datei-Endung gebildet. Es fehlen Name-Patterns (`credentials.json`/`serviceaccount.json`, `*_SECRET*`/`*_TOKEN*`/`*_PASSWORD*`, `*.keystore`/`*.jks`) und der **Content-Scan** auf `AKIA`/`ghp_`/`sk-`. Der konsumierende Check `_check_security_secrets` (`src/agentkit/verify_system/structural/checker.py:459`) entscheidet nur ueber `evidence.secret_files` und erbt die verkuerzte Liste. Es gibt **keine** `security.secrets_content`-Stage (Grep `security.secrets_content` -> 0 Treffer).
- **`guard_decisions`-Tabelle FEHLT:** keine Tabelle in `state_backend/postgres_schema.sql` noch `sqlite_store.py`; Grep `guard_decisions|GuardDecision` -> 0 Treffer. (`guard_invocation_counters` ist ein KPI-Fakt, **nicht** die Audit-Entitaet.) (Gap FK-17 §17.3.11 / FK-18 §18.3.3).
- **`story_custom_field_*`-Tabellen FEHLEN:** Grep `story_custom_field|StoryCustomField` -> 0 Treffer; keine `story_custom_field_definitions`/`_values` (Gap FK-17 §17.3.4/5 / FK-18 §18.3.1).
- **`ALLOW_VIA_OFFICIAL_SERVICE_PATH` UNVOLLSTAENDIG:** `src/agentkit/governance/principal_capabilities/matrix.py:26` markiert das Verdict als „later" (out of scope AG3-032); `enforcement.py:49-52` haelt den Servicepfad-Schritt (Code-internes „Step 6" == FK-55 §55.10.3 step 8) als „deliberately rudimentary (AG3-032 out of scope)" fest; **kein** `is_official_service_path`-Validator (Grep -> 0 Treffer). Gefaehrliche Service-Zellen sind aktuell fail-closed verdrahtet (sicher, aber das positive Servicepfad-Verdict fehlt) (Gap FK-55 §55.6/§55.9/§55.10.3). Der Attestierungs-Pfad existiert bereits strukturell: `principals.py:51-67` (`_ATTEST_FLAG`, `_PRIVILEGED`) attestiert `pipeline_deterministic`/`admin_service`/`human_cli` nach FK-55 §55.3a.
- **Freeze-Nachweis FEHLT:** Freeze-Mechanik existiert (`principal_capabilities/freeze.py`), aber Grep `freeze|conflict_freeze` in `governance/integrity_gate/` -> 0 Treffer; keine Freeze-Proof-Dimension (Gap §55.10.8).
- **Sub-Agent-Rueckkanal-Filter FEHLT:** Grep `back_channel|artifact_refs|next_step|error_class|return_channel` in `governance/` -> 0 Treffer (Gap §55.10.10).

## 2. Scope

### 2.1 In Scope

1. **Zweistufige Secret-Detection mit GEMEINSAMER Pattern-Quelle** (FK-15 §15.5.2 — beide Stufen identisch):
   - **Eine einzige typisierte Pattern-Quelle** (Datei-/Name-Patterns + Content-Pattern `AKIA`/`ghp_`/`sk-`) als Owner-Modul im `guard_system`-BC; **kein zweites Pattern-Set**. Sowohl Stufe 1 (Hook) als auch Stufe 2 (Structural) konsumieren genau diese Quelle.
   - **Stufe 1 — Pre-Commit-Hook:** der reale Hook `.githooks/pre-commit` bekommt einen **global aktiven** Secret-Scan (unabhaengig vom pfadbasierten Concept-Dispatching, FK-15 §15.5.2 „global aktiv"), der die gemeinsame Pattern-Quelle gegen den Staging-Diff (Datei-Namen/-Endungen **und** Content) prueft und den Commit fail-closed ablehnt. Die Pattern-Logik liegt in `src/agentkit/` (Python, ARCH-55), der Hook ruft sie auf — keine Pattern-Duplikation im Shell-Skript.
   - **Stufe 2 — Structural-Check:** datei-/namensbasierter `security.secrets` (bestehend, Patterns vervollstaendigt) **plus** neue, separate BLOCKING-Stage/Check `security.secrets_content` fuer den Diff-Content-Scan (getrennte Evidence-Quellen, kein Kollidieren).
2. **Secret-Datei-/Name-Patterns vervollstaendigen** (FK-15 §15.5.2 Pattern-Tabelle): `_SECRET_EXTENSIONS` + Name-Patterns um `credentials.json`/`serviceaccount.json`, `*_SECRET*`/`*_TOKEN*`/`*_PASSWORD*`, `*.keystore`/`*.jks` erweitern. Evidence-Bildung (`composition_root`) und konsumierender `security.secrets`-Check ziehen aus der gemeinsamen Quelle (Punkt 1) — eine Quelle, kein zweites Pattern-Set.
3. **`guard_decisions`-Tabelle + `GuardDecision`-Entitaet** (Owner `guard_system`; FK-17 §17.3.11 / FK-18 §18.3.3/§18.6e.3): kanonische append-only Entitaet mit den FK-18 §18.6e.3-Pflichtspalten `project_key`, `story_id`, `run_id`, `flow_id`, `guard_decision_id` (Identitaet), `guard_key`, `outcome`, `decided_at` (UTC) plus den optionalen Spalten `node_id`, `reason`, `evidence_ref` (FK-17 §17.3.11). Persistenz in **beiden** Stores (postgres_schema.sql + sqlite_store.py) ueber den bestehenden State-Backend-Pfad; Guards schreiben ihre Entscheidung dorthin (kein Parallel-Audit, keine zweite Audit-Wahrheit).
4. **`story_custom_field_definitions` / `story_custom_field_values`** (Owner `story_context_manager`; FK-17 §17.3.4/5 / FK-18 §18.3.1/§18.6e.1) — **vollstaendiger** Feldsatz:
   - `StoryCustomFieldDefinition`: `project_key`, `field_key`, `display_name`, `field_type`, `provider`, `provider_field_ref`, `is_required`, `is_writable_by_agentkit`, `allowed_values`.
   - `StoryCustomFieldValue`: `project_key`, `story_id`, `field_key`, `value`, `value_status`, `source`, `last_synced_at`, `last_written_by`, `provider_sync_status`, `conflict_detected`, `last_sync_attempt_at`.
   - Single-Writer-Schranke: AgentKit schreibt nur, wenn `is_writable_by_agentkit = true` **und** kein `conflict_detected`/fremder Owner. Persistenz in beiden Stores.
5. **`ALLOW_VIA_OFFICIAL_SERVICE_PATH` + `is_official_service_path`** (FK-55 §55.6/§55.9/§55.10.3 Step 8/§55.10.4/§55.10.7; Attestierung nach §55.3a): drittes Permission-Verdict real durchsetzbar; `is_official_service_path(event, principal)`-Validator, der **ausschliesslich** ueber die FK-55 §55.3a-Attestierungsquellen entscheidet (siehe AC5) — **nicht** aus Tool-Args/Command-String ableitbar (FK-55 §55.10.7). Einbindung an der korrekten Stelle der Auswertungsreihenfolge (FK-55 §55.10.3 Step 8: nur wenn die harte Matrix + Freeze nicht bereits `BLOCK` liefern). Die heute fail-closed verdrahteten Service-Zellen erhalten dann ihr positives Verdict fuer die §55.9-Servicepfade.
6. **Integrity-Freeze-Nachweis als kanonischer Proof-Record** (FK-55 §55.10.8): am Integrity-Gate eine fail-closed Dimension, die fuer einen gesetzten `conflict_freeze` einen **persistenten** Nachweis-Record (Owner `guard_system`) mit den drei §55.10.8-Pflichtinhalten verlangt — `activated_at` (Aktivierungszeit), `blocked_principal` (geblockter Principal), `resolution_service_path` (offizieller Aufloesungspfad). Erzeugung des Proof-Records beim Freeze/bei der Aufloesung; Persistenz im State-Backend. Fehlt der Nachweis -> Run **nicht** closure-faehig.
7. **Sub-Agent-Rueckkanal-Filter** (FK-55 §55.10.10): schema-gebundener Filter mit **explizitem, getyptem Allow-Schema** fuer Sub-Agent-/Servicepfad-Ausgaben an den Orchestrator. Erlaubte Felder + Typen + Grenzen: `status` (Enum), `error_class` (Enum/kurzer String), `next_step` (kurzer String), `artifact_refs` (Liste von Referenz-IDs/-Pfaden, keine Inhalte), `reason` (kurze **strukturierte** Begruendung, laengen-/strukturbegrenzt). Default-deny aller anderen Felder; verworfen werden rohe Diffs, `context.json`-/`are_bundle.json`-Zitate, vollstaendige Inhaltsartefakte, freie Prompt-/Bundle-Listen.
8. **Tests:** Content-Scan triggert auf `AKIA`/`ghp_`/`sk-` (Positiv + Negativ) auf **beiden** Stufen; neue Datei-/Name-Patterns greifen (Test pro Patterngruppe) auf **beiden** Stufen; gemeinsame Pattern-Quelle nachgewiesen (kein zweites Set); `guard_decisions`-INSERT/Read-Roundtrip (beide Stores); Custom-Field-Definition+Value-Roundtrip mit allen Feldern (beide Stores) + Single-Writer-Schranke (Schreiben blockt bei `conflict_detected`/fremdem Owner); Servicepfad-Verdict nur bei attestiertem Pfad (Positiv je §55.9-Pfad + Bash-Spoofing-Negativtest); Freeze-Proof-Erzeugung+Persistenz (positiver Roundtrip) **und** Freeze ohne Nachweis -> Closure blockiert; Rueckkanal-Filter laesst nur erlaubte Felder durch und verwirft Inhalts-Felder.

### 2.2 Out of Scope (mit Owner)
- **FK-15 §15.5.2 Hook-Pfad-Doc-Drift** (`tools/hooks/pre-commit` in der FK-Prosa vs. realem `.githooks/pre-commit`): reiner Konzept-Nachzug, **AG3-102** (doc-only, Namens-/Konventions-Angleichung). Diese Story implementiert gegen den **realen** Pfad `.githooks/pre-commit`; sie benennt nicht um und aendert keine FK-Prosa.
- **`.agent-guard/scope.json` / `permission_state.json`-Writer** (FK-55 §55.10.4/4a, ABWEICHEND — bewusst ueber FK-56-Edge-Bundles geloest) — Konzept-Nachzug **AG3-104** (doc-only); nicht hier neu materialisieren.
- **Bugfix-spezifische Structural-Checks** (FK-33 §33.3.2 `bugfix.*`) — anderer Befund, **AG3-064** (Stage-Registry-Vollausbau).
- **KpiProjection-Entitaet** (FK-17 §17.3.14, ABWEICHEND) — KPI-Schema-Owner ist **AG3-083**; hier nicht beruehrt.
- **Tabellen-Umbenennungen** `node_execution_ledgers`/`attempts`/`artifact_envelopes` (FK-18 ABWEICHEND) — Namens-Drift, Konzept-Nachzug **AG3-102** (doc-only); diese Story benennt **nicht** um, sie ergaenzt nur die fehlenden Tabellen.
- **Branch-Guard als Secret-Owner** (FK-15 §15.4.3 ABWEICHEND): Owner-Abweichung; Secret-Detection bleibt Hook + Structural-Check + Content-Scan. FK-Prosa-Nachzug ggf. doc-only (**AG3-102**) — hier nur melden, nicht den Branch-Guard umbauen.
- **Permission-Lease-/Request-Modell, CCAG, Permission-Timeouts** (FK-55 §55.9a/§55.10.9a) — angrenzend, eigener Befund (Welle 5 / **AG3-086** Hook-/Guard-Vollausbau); hier nicht beruehrt. Diese Story ergaenzt nur das dritte Verdict + Validator an der bestehenden Auswertungsreihenfolge.

## 3. Akzeptanzkriterien
1. **Zweistufige Secret-Detection mit identischen Patterns:** sowohl der Pre-Commit-Hook (`.githooks/pre-commit`, Stufe 1) als auch der Structural-Subflow (Stufe 2) blocken bei denselben Datei-/Name-Patterns und beim Content-Scan, weil beide aus **einer** gemeinsamen Pattern-Quelle lesen. Test belegt: gleiches Secret -> beide Stufen blocken; harmloser Inhalt -> beide clean; ein Test belegt, dass es nur **eine** Pattern-Quelle gibt (kein zweites Set).
2. **`security.secrets_content`** existiert als eigene BLOCKING-Stage/Check (getrennt von `security.secrets`) und blockt bei `AKIA`/`ghp_`/`sk-` im Diff-Inhalt (Positivtest), ist clean bei harmlosem Inhalt (Negativtest).
3. Die Secret-Datei-/Name-Patterns enthalten `credentials.json`/`serviceaccount.json`, `*_SECRET*`/`*_TOKEN*`/`*_PASSWORD*`, `*.keystore`/`*.jks`; `security.secrets` greift darauf (Test pro neue Patterngruppe).
4. `guard_decisions`-Tabelle existiert in postgres_schema.sql **und** sqlite_store.py mit allen FK-18 §18.6e.3-Pflichtspalten (`guard_decision_id`/`guard_key`/`outcome`/`decided_at` UTC + Scope-Felder) und den optionalen FK-17 §17.3.11-Spalten (`node_id`/`reason`/`evidence_ref`); append-only; ein Guard-Decision-INSERT/Read-Roundtrip ist getestet (beide Stores).
5. `story_custom_field_definitions`/`_values` existieren in beiden Stores mit dem **vollstaendigen** FK-17-Feldsatz (Definition: `display_name`/`field_type`/`provider`/`provider_field_ref`/`is_required`/`is_writable_by_agentkit`/`allowed_values`; Value: `value`/`value_status`/`source`/`last_synced_at`/`last_written_by`/`provider_sync_status`/`conflict_detected`/`last_sync_attempt_at`). Roundtrip-Test fuer Definition **und** Value; Single-Writer-Schranke blockt Schreiben bei `is_writable_by_agentkit=false`/`conflict_detected`/fremdem Owner (Test).
6. `is_official_service_path` validiert ausschliesslich ueber die FK-55 §55.3a-Attestierungsquellen (1 Hook-Kontext/Prozesskontext, 2 aktiver Lock-/Run-Kontext im State-Backend, 3 lokaler Export der Story-/Freeze-Bindung, 4 expliziter Service-Attest fuer `pipeline_deterministic`/`admin_service`/`human_cli`). Positivtests je §55.9-Servicepfad (mind. `agentkit run-phase closure` als `pipeline_deterministic` und `agentkit reset-story` als `admin_service`/`human_cli`) erhalten `ALLOW_VIA_OFFICIAL_SERVICE_PATH`; ein gespoofter freier Bash-Aufruf desselben Kommandos erhaelt das Verdict **nicht** (Negativtest, FK-55 §55.10.7). Die Pruefung sitzt in der FK-55 §55.10.3-Reihenfolge an Step 8 (nur wenn Matrix + Freeze nicht bereits `BLOCK`).
7. Integrity-Gate erzeugt/liest fuer einen gesetzten `conflict_freeze` einen kanonischen Proof-Record mit `activated_at`/`blocked_principal`/`resolution_service_path` (positiver Erzeugungs-/Persistenz-Roundtrip-Test) und blockiert Closure, wenn dieser Nachweis fehlt (Negativtest: Freeze ohne Nachweis -> nicht closure-faehig).
8. Der Sub-Agent-Rueckkanal-Filter laesst nur die getypten Felder `status`/`error_class`/`next_step`/`artifact_refs`/`reason` (kurze, strukturierte Begruendung mit Laengen-/Strukturgrenze) durch; rohe Diffs, `context.json`-/`are_bundle.json`-Inhalte, vollstaendige Inhaltsartefakte und freie Prompt-/Bundle-Listen werden verworfen (Test).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FAIL-CLOSED:** Secret-Treffer blocken auf beiden Stufen, fehlender Freeze-Nachweis blockt Closure, Servicepfad nur bei Attestierung, Rueckkanal default-deny der Inhalts-Felder.
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** kanonische `guard_decisions`/`story_custom_field_*`-Entitaeten mit den richtigen FK-17-Ownern (`guard_system` bzw. `story_context_manager`) statt Schattenfelder; **eine** Secret-Pattern-Quelle fuer Hook + Structural, kein zweites Set; ein kanonischer Freeze-Proof-Record statt Ad-hoc-Flag; keine zweite Audit-Wahrheit neben dem State-Backend (`state_backend` ist nur Persistenzadapter).
- **TYPISIERT STATT STRINGS:** Verdict-/Outcome-Enums, Custom-Field-Sync-Status (`value_status`/`provider_sync_status`) typisiert; Secret-Pattern als typisierte Liste; Rueckkanal-Allow-Schema getypt.
- **ARCH-55:** Tabellen-/Spalten-/Verdict-/Enum-Namen, Wire-/Schema-Keys englisch.
- **ZERO DEBT:** keine halbfertige Audit-Familie; beide Stores ziehen gemeinsam, Content-Scan ist real (kein Datei-Namen-Surrogat), beide Detection-Stufen sind real verdrahtet.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Die gemeinsame Pattern-Quelle ist der zentrale FIX-THE-MODEL-Punkt: **ein** typisiertes Owner-Modul im `guard_system`-BC, das Hook (Stufe 1) **und** Structural-Check/Content-Scan (Stufe 2) speist. Die Pattern-Logik liegt in `src/agentkit/` (Python, ARCH-55); das Shell-Hook-Skript `.githooks/pre-commit` ruft sie nur auf und dupliziert keine Patterns.
- Realer Hook-Pfad ist `.githooks/pre-commit` (nicht der in FK-15 §15.5.2 genannte `tools/hooks/pre-commit` — Doc-Drift, Owner AG3-102). Der Secret-Scan muss global aktiv sein, unabhaengig vom pfadbasierten Concept-Dispatching.
- Schema-Aenderungen IMMER in **beiden** Stores (`postgres_schema.sql` + `sqlite_store.py`) und gegen die Contract-/Golden-Tests; `SCHEMA_VERSION` ziehen, falls noetig (`state_backend/config.py`). Spalten-Sollstand: FK-18 §18.6e.1 (Custom Fields) / §18.6e.3 (guard_decisions).
- Content-Scan klar vom Datei-basierten Check trennen (`security.secrets` vs. `security.secrets_content`) — sonst kollidieren Evidence-Quellen.
- `is_official_service_path` darf **nicht** aus Tool-Args/Command-String ableitbar/spoofbar sein — nur aus den vier §55.3a-Attestierungsquellen. Vorhandenes Attestierungsmuster: `principals.py:51-67` (`_ATTEST_FLAG`/`_PRIVILEGED`). Einbindung an FK-55 §55.10.3 Step 8 (Code-intern: enforcement.py „Step 6"), nur wenn Matrix + Freeze nicht bereits `BLOCK`.
- Freeze-Nachweis dockt am Integrity-Gate an (`governance/integrity_gate/_dimension_specs.py`/`dimensions.py`) — als zusaetzliche fail-closed Dimension mit kanonischem, persistiertem Proof-Record (drei §55.10.8-Pflichtinhalte).
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (zweistufiger Secret-Scan + gemeinsame Quelle, Content-Scan, Store-Roundtrips Definition+Value, Servicepfad je §55.9-Pfad + Spoofing-Negativtest, Freeze-Proof-Roundtrip + Freeze-ohne-Nachweis-Block, Rueckkanal-Filter).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
