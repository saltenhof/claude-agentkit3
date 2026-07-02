# AG3-143 — Execution-Contract-Digest + Spec-Freeze: Digest beim Setup, Wirkungsklassen, Freeze tragender Spec-Felder, Digest als Fence-Prädikat

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [AG3-137] — das Spec-Freeze-Gate braucht ein
  deterministisches Prädikat „aktives Execution-Regime" = existierender
  aktiver `RunOwnershipRecord` (Tabelle + Read-Repository aus AG3-137), und
  die run-scoped Digest-Persistenz baut auf der dort gelegten additiven
  Postgres-only-Schema-/Fassaden-Mechanik auf (GAP §4: ST-01 → ST-12).
- **Quell-Konzept:** FK-44 Frontmatter (`authority_over` scope
  `execution-contract-digest`), §44.3a + Glossar `execution-contract-digest`,
  §44.3 (`run-prompt-pin` als Komponente); FK-59 §59.9a (Spec-Freeze) +
  §59.9 (administrative Felder); FK-91 §91.1a Regel 15 (Digest im
  Fence-Prädikat-Katalog), Regel 13 (Story-Serialisierung administrativer
  Feldpflege); FK-56 §56.13 (administrativer Eingriff läuft gegen den Owner)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-12; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-44 §44.3a verallgemeinert das Run-Pinning: Ein aktiver Run arbeitet gegen
einen eingefrorenen **fachlichen Execution-Contract**, dessen Digest beim
Setup gebildet wird. FK-59 §59.9a zieht daraus die Mutations-Konsequenz für
die Story-Spec. Im Code existiert davon nichts (am Code verifiziert
2026-07-02):

- Grep `execution_contract` über `src/agentkit/`: **null Treffer**. Es gibt
  keinen Digest, keine Persistenz, kein Prädikat, keine Wirkungsklassen.
- Der **run-prompt-pin trägt als Komponente und als Muster**:
  `prompt_runtime/pins.py` (`initialize_prompt_run_pin` :104,
  `ensure_prompt_run_pin` :182) mit der C2-Invariante
  `binding_changes_affect_only_future_runs` (Moduldocstring :8-14) — genau
  die „gepinnt-für-neue-Runs"-Semantik, die §44.3a auf den gesamten
  Contract verallgemeinert.
- **Spec-Felder sind während eines aktiven Runs still mutierbar:**
  `update_story_fields` (`story_context_manager/service.py:441`) prüft kein
  Execution-Regime; verboten sind nur `status`/`created_at`/`completed_at`
  (`FORBIDDEN_PATCH_FIELDS`, `story_context_manager/wire_adapter.py:256-274`).
  Scope, Akzeptanzkriterien und Story-Text eines laufenden Runs können per
  PATCH geändert werden — exakt der „stille Mid-run-Drift", den FK-44
  §44.3a/FK-59 §59.9a verbieten (SOLL-098-Lücke).
- Der Setup-Start läuft über den Control-Plane-Dispatch
  (`control_plane/dispatch.py:246` → Engine) und das atomare
  Start-Finalize (`control_plane/runtime.py:684-755`) — der Andockpunkt,
  an dem der Digest verbindlich mit dem committeten Setup entsteht.

Ohne diese Story bleibt der Fence-Prädikat-Katalog aus FK-91 Regel 15
unvollständig: AG3-144 (ST-09) kann das Digest-Prädikat nur verwenden, wenn
es hier definiert und persistiert wird (Bauplan-Kante ST-12 → ST-09,
Review-Runde 1 E2).

## Scope

### In Scope

1. **Digest-Bildung beim Setup** (SOLL-095): Deterministischer
   `execution_contract_digest` aus (a) Story-Spec-Version + fachlich
   tragenden Spec-Feldern (Scope, Akzeptanzkriterien, Story-Text), (b) der
   einschlägigen Projekt-, QA- und Gate-Konfiguration, (c) den Skill-,
   Prompt- und Capability-Versionen. Der `run-prompt-pin` (§44.3) ist
   **Komponente** des Digests; seine Semantik bleibt unangetastet.
   Implementierungs-Owner ist der prompt-runtime BC (FK-44 `authority_over`
   scope `execution-contract-digest` — Umsetzungsanteil von SOLL-094):
   neues Modul `prompt_runtime/execution_contract.py` mit kanonischer
   Serialisierung + SHA-256.
2. **Run-scoped Persistenz** (additiv, Postgres-only, K5): Der Digest wird
   atomar mit dem committeten Setup-Start persistiert und ist kanonisch
   abfragbar (Fence-Auswertung + Audit). Fail-closed: Es gibt keinen Run im
   Execution-Regime ohne persistierten Digest; nach dem Setup-Commit ist die
   Digest-Persistenz read-only (kein stiller Update-Pfad).
3. **Drei Wirkungsklassen** (SOLL-096): Typisiertes Klassifikationsmodell
   für Contract-Änderungen während eines aktiven Runs — `run_neutral`,
   `pinned_for_new_runs` (Default: laufender Run behält seinen Digest, neue
   Runs bilden neu), `deliberate_administrative_intervention` (nur als
   expliziter, auditierter Vorgang gegen den Run-Owner bzw. als
   Run-Invalidierung; die Kommando-Oberfläche dafür liegt in
   AG3-148/AG3-154). Nie stiller Mid-run-Drift.
4. **Spec-Freeze** (SOLL-098): `update_story_fields` prüft vor dem Write,
   ob die Story ein aktives Execution-Regime hat (aktiver
   `RunOwnershipRecord` aus AG3-137 als deterministisches Prädikat). PATCH
   auf fachlich tragende Felder bei aktivem Regime → deterministische
   Ablehnung (`409` + typisierter `error_code`, kein Write, kein
   Erfolg-vortäuschender Idempotenz-Record). Die Feldklassifikation
   (tragend vs. administrativ) ist ein typisiertes Modell, keine
   String-/Flag-Kaskade; nicht klassifizierte Spec-Felder gelten
   fail-closed als tragend.
5. **Administrative Metadaten bleiben frei** (SOLL-099): Labels,
   Anzeigename und vergleichbare Nicht-Achsen-Felder (§59.9) bleiben
   mutierbar und unterliegen nur der normalen Story-Serialisierung
   (FK-91 Regel 13); außerhalb eines aktiven Execution-Regimes gilt kein
   Freeze (Anlage, Approval, Feldpflege unverändert).
6. **Digest als Fence-Prädikat — DEFINITION** (SOLL-097): Eine
   deterministische, sperrenfreie Prüf-Fläche
   („persistierter Digest des Runs vs. aktuell gebildete
   Contract-Grundlage") mit der normierten Semantik: Abweichung ⇒ Prädikat
   false ⇒ betroffene Job-Ergebnisse sind als `stale_observation` zu
   behandeln. Die **VERWENDUNG** dieses Prädikats im Job-Abschluss-/
   Upsert-Fencing liegt in **AG3-144**.

### Out of Scope (mit Owner)

- **Verwendung des Digest-Prädikats** in Job-Abschluss-Fences,
  `stale_observation`-Store und materialisierter Fence-Sicht: **AG3-144**
  (Kante ST-12 → ST-09).
- **Ownership-Fencing der Regime-Pfade** (Owner-/Epoch-Prädikate):
  **AG3-142**.
- **Schema-/Repository-Fundament** (`run_ownership_records` u. a.):
  **AG3-137**.
- **Kommando-Oberfläche administrativer Eingriffe** (Transfer-Endpoints,
  Admin-/CLI-Kommandos, Run-Invalidierung als Bedienpfad): **AG3-148** /
  **AG3-154**.
- **Betriebs-Runbook** (Umgang mit Digest-Abweichungen im Betrieb):
  **AG3-155**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/prompt_runtime/execution_contract.py` | neu | Digest-Assembler (kanonische Serialisierung + SHA-256), Wirkungsklassen-Modell, Prädikat-Definition (BC-Owner per FK-44 `authority_over`) |
| `src/agentkit/backend/state_backend/postgres_schema.sql` | ändern | Additive run-scoped Digest-Persistenz (Postgres-only, Präzedenz: idempotenter Bootstrap + `_schema_alter_statements()`) |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`, `mappers.py`) | ändern | Row-Funktionen + Fassaden-API: Digest-Save (nur Setup-Commit) / Load (sperrenfrei) |
| `src/agentkit/backend/control_plane/runtime.py` / `control_plane/dispatch.py` | ändern | Digest-Bildung als Bestandteil des committeten Setup-Starts (Andockpunkt Finalize-/Materialisierungsplan `_finalize_start_phase` :684-755; Dispatch :246) |
| `src/agentkit/backend/story_context_manager/service.py` | ändern | Spec-Freeze-Gate in `update_story_fields` (:441): Regime-Prüfung vor Idempotenz-Record und Write |
| `src/agentkit/backend/story_context_manager/wire_adapter.py` | ändern | Typisierte Feldklassifikation tragend/administrativ (Nachbarschaft `FORBIDDEN_PATCH_FIELDS` :256-274) |
| `src/agentkit/backend/story_context_manager/errors.py` | ändern | Typisierter Freeze-Fehler (409, maschinenlesbarer `error_code`) |
| `tests/unit/prompt_runtime/**`, `tests/unit/story_context_manager/**` | neu/ändern | Digest-Determinismus, Wirkungsklassen, Feldklassifikation, Freeze-Gate über Ports/Fakes |
| `tests/integration/**` | neu | Postgres: Setup persistiert Digest atomar; Freeze-Negativpfade am echten Regime-Zustand; „gepinnt-für-neue-Runs"-Szenario |
| `tests/contract/**` | neu/ändern | Contract-Pin des Digest-Formats (Komponentenliste + Kanonikalisierung) und der Freeze-Fehlerform |

## Akzeptanzkriterien

1. **Digest deterministisch:** Gleicher Contract-Input ⇒ identischer Digest;
   ein Contract-/Golden-Test pinnt Kanonikalisierung und Komponentenliste
   (Spec-Version + tragende Felder, Projekt-/QA-/Gate-Konfiguration,
   Skill-/Prompt-/Capability-Versionen, `run-prompt-pin`).
2. **Setup-Kopplung fail-closed:** Der committete Setup-Start persistiert
   den Digest atomar; ist eine Digest-Komponente nicht bildbar (z. B.
   fehlende Projekt-/QA-Konfiguration), wird der Setup-Start deterministisch
   abgewiesen — kein Run im Execution-Regime ohne Digest (Negativtest an
   der Setup-Phasengrenze).
3. **Pin-Semantik unangetastet:** Bestehende `run-prompt-pin`-Tests bleiben
   ohne Semantik-Anpassung grün; der Digest konsumiert den Pin als
   Komponente und ersetzt ihn nicht
   (`binding_changes_affect_only_future_runs`).
4. **Wirkungsklasse „gepinnt-für-neue-Runs" (Default):** Eine Konfig-/
   Bundle-/Spec-relevante Änderung nach Run-Start lässt den persistierten
   Digest des laufenden Runs unverändert; ein danach gestarteter neuer Run
   erhält einen abweichenden Digest (Integrationstest über zwei Runs).
5. **Kein stiller administrativer Eingriff:** Es existiert kein Codepfad,
   der den persistierten Digest eines laufenden Runs ohne expliziten,
   auditierten Vorgang ändert — die Digest-Persistenz ist nach Setup-Commit
   read-only (API-Beweis + Negativtest).
6. **Spec-Freeze:** PATCH auf tragende Felder (Scope/Akzeptanzkriterien/
   Story-Text) bei aktivem Execution-Regime → `409` mit typisiertem
   `error_code`, kein Write; administrative Felder bleiben im selben
   Zustand mutierbar; ohne aktives Regime kein Freeze (Positivtests für
   Anlage/Approval/Feldpflege). Die Freeze-Prüfung läuft VOR dem
   Idempotenz-Record — ein abgewiesener PATCH hinterlässt keinen
   Erfolgs-Replay.
7. **Klassifikation fail-closed:** Ein neues/nicht klassifiziertes
   Spec-Feld wird vom Freeze-Gate als fachlich tragend behandelt (kein
   stilles Durchrutschen); die Klassifikation ist ein typisiertes Modell
   (Negativtest mit unbekanntem Feld).
8. **Prädikat abfragbar:** Die Digest-Prüf-Fläche liefert deterministisch
   und sperrenfrei match/mismatch; eine nachträglich (administrativ)
   geänderte Contract-Grundlage ⇒ Prädikat false. Die Fence-VERWENDUNG
   wird hier nicht gebaut (AG3-144) — getestet wird nur die
   Prädikat-Definition.
9. **Postgres-only fail-closed (K5):** Digest-Persistenz über ein
   Nicht-Postgres-Backend scheitert als expliziter `ConfigError` (Muster
   `_require_postgres_control_plane_backend`,
   `control_plane/runtime.py:2119`); kein SQLite-Spiegel (Negativtest).
10. Coverage ≥ 85 % gehalten; `mypy` strict (+ `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Feldnamen, Wire-Keys,
    Fehlercodes — z. B. `spec_frozen_during_active_run`).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-144); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-094–099.

## Konzept-Referenzen

- FK-44 Frontmatter: `authority_over` scope `execution-contract-digest`
  (SOLL-094; konzeptseitig bereits verankert — diese Story setzt den
  Umsetzungsanteil im prompt-runtime BC um)
- FK-44 §44.3a (Digest-Komponenten, drei Wirkungsklassen, Digest als
  Fencing-Prädikat, `stale_observation`-Semantik bei geänderter Grundlage)
  + Glossar `execution-contract-digest`
- FK-44 §44.3 (`run-prompt-pin`; Komponente des Digests, Semantik
  unangetastet; `formal.prompt-runtime.invariants` →
  `binding_changes_affect_only_future_runs`)
- FK-59 §59.9a (Spec-Freeze: tragende Felder eingefroren; Änderung nur als
  expliziter Vorgang gegen den Owner oder Run-Invalidierung; administrative
  Metadaten frei; außerhalb aktivem Regime kein Freeze) + §59.9
  (Nicht-Achsen-Felder)
- FK-91 §91.1a Regel 15 (`execution_contract_digest` im
  Fence-Prädikat-Katalog — Verwendung in AG3-144), Regel 13
  (Story-Serialisierung der administrativen Feldpflege)
- FK-56 §56.13 (administrativer Eingriff läuft sichtbar gegen den
  Run-Owner — Querverweis für Wirkungsklasse 3)

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Der Freeze ist eine typisierte
  Vertragsklassifikation der Spec-Felder — keine wachsende
  Feld-Blacklist neben `FORBIDDEN_PATCH_FIELDS`.
- **FAIL-CLOSED:** Kein Run ohne Digest; unklassifizierte Felder gelten als
  tragend; nicht bildbare Digest-Komponenten weisen den Setup ab.
- **SINGLE SOURCE OF TRUTH:** Genau ein kanonisch persistierter Digest pro
  Run; keine zweite operative Wahrheit (kein Schattenfeld, keine
  Seiten-Datei) für den Execution-Contract.
- **ZERO DEBT:** Digest, Wirkungsklassen, Freeze und Prädikat-Definition
  sind gemeinsam der vereinbarte Scope — kein „Fence-Definition später".
- **State-/Artefakt-Disziplin (CLAUDE.md):** Format-/Schema-Änderung nur
  mit mitgezogenen Contract-/Golden-Tests (AK 1).

## Querschnitts-Auflagen

- **K5 Postgres-only:** Die Digest-Persistenz ist Postgres-only,
  fail-closed über das `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`); kein SQLite-Spiegel. Teststrategie:
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Digest-Assembler,
  Wirkungsklassen-Modell und Feldklassifikation
  (`execution_contract.py`, wire_adapter-Klassifikation) = **A**;
  Fassaden-/Wire-/Fehler-Mapping = **R**; Row-Funktionen/DDL im
  `state_backend` = **T**. Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert: der Digest ist
  Backend-intern; `bundles/target_project/` konsumiert ihn nicht —
  Skill-/Prompt-Bundle-Versionen gehen nur als Eingabe in die
  Digest-Bildung ein, die Bundles selbst ändern sich nicht).
