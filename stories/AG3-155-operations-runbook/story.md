# AG3-155 — Betriebs-Runbook (FK-04): Takeover-Ablauf, `admin_abort`, Startup-Rekonsiliierung, Migrationsreihenfolge ST-01→ST-02→ST-03

- **Typ:** concept (Doku-Story — keine Code-Änderungen)
- **Größe:** S
- **depends_on:** [AG3-139, AG3-149, AG3-151, AG3-154]
  - **AG3-139** — das Runbook beschreibt den Betrieb **ohne** automatisches
    Verwaisungs-Handling (kein TTL, kein Lease, keine PID-Heuristik;
    einzige Endwege: Startup-Rekonsiliierung + `admin_abort`). Solange die
    Claim-TTL im Code lebt, wäre jedes dieser Runbooks operativ falsch;
    zusätzlich dokumentiert genau diese Story die kritische
    Migrationsreihenfolge, deren Abschluss AG3-139 ist (GAP §4:
    „ST-13 ← konzeptionell nach ST-02/03/07").
  - **AG3-149** — der dokumentierte Takeover-/Entzugs-Ablauf (Wirkung auf
    den Ex-Owner, Disown-Baustein, Ping-Pong-Schranke, Reconcile-Antwort)
    wird erst durch AG3-149 final hergestellt; ein Runbook, das vorher
    geschrieben würde, beschriebe einen Zwischenzustand. Das Runbook darf
    erst danach als „fertig" gelten (Plan-Vorgabe zur Kante).
  - **AG3-151** — die dokumentierten Reconcile-Zustände und
    Quarantäne-Prozeduren (`takeover_reconcile_required`,
    `contested_local_writes`, `remote_branch_diverged_after_takeover`,
    `local_stale_or_dirty_takeover_target`) entstehen erst dort; das
    Runbook kann sie erst nach deren Landung final beschreiben.
  - **AG3-154** — die `recover-story`-/CLI-Bedienpfade (Takeover-/Abort-/
    Recover-Kommandos im Operator- und Edge-Tool-Pfad), auf die die
    Lösungsschritte verweisen, entstehen erst dort; das Runbook kann erst
    nach deren Landung fertig beschrieben werden.
- **Quell-Konzept:** FK-04 §4.5 (Runbook-Kapitel; Bestand §4.5.1–§4.5.9);
  FK-56 §56.13/§56.13a–h (Takeover-Protokoll, Freigabe, Vollzug, Disown);
  FK-91 §91.1a Regel 16/17 + Endpoint-Zeile `…/operations/{op_id}/admin-abort`,
  §91.1 (Operator-CLI); FK-10 §10.5.4 (Startup-Rekonsiliierung,
  Ein-Writer-Betriebsannahme), §10.6.1/§10.6.2 (Absturz-Szenarien,
  Recovery-Protokoll — bereits TTL-/PID-frei); FK-20 §20.7.3/§20.7.4
  (`recover-story`); FK-30 §30.6.3 (Edge-Zustände als Betriebs-Befunde)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-13; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-04 ist das Betriebs-Dokument (`concept/technical-design/
04_betrieb_monitoring_audit_runbooks.md`, `authority_over: operations`,
`cross_cutting: true`). Sein Runbook-Kapitel §4.5 führt heute neun Runbooks
(§4.5.1 LLM-Hub … §4.5.9 Permission-Block) — **keines** für die neuen
Ownership-Betriebsfälle (am Dokument verifiziert 2026-07-02: Grep
`takeover|admin.abort|rekonsil|migration` in FK-04: null Treffer). Konkret
fehlen (IMPL-024, Enabler h):

- **Takeover:** Wie führt ein Operator/Reviewer eine Übernahme durch
  (request → Challenge lesen → menschlicher Confirm → Reconcile durch die
  neue Session), was bedeutet der Verlustkorridor, was passiert mit dem
  Ex-Owner, was tun bei `contested_local_writes` /
  `remote_branch_diverged_after_takeover` /
  `local_stale_or_dirty_takeover_target`?
- **`admin_abort`:** Wann ist der administrative Abbruch einer hängenden
  In-Flight-Operation der richtige (und einzige) manuelle Endweg, was
  bedeutet der auditierte Reconcile-/Repair-Zustand nach Teil-Writes, was
  bedeutet der `operation_epoch`-Fence für einen noch physisch laufenden
  Alt-Executor?
- **Startup-Rekonsiliierung:** Was passiert beim Server-Boot
  (Verwaisten-Finalisierung nur eigener Instanz-Inkarnationen, fail-closed
  Start bei Reconcile-Fehler), was sieht der Operator, wann greift er ein?
- **Migrationsreihenfolge (IMPL-006):** die harte Ordnung
  **ST-01 → ST-02 → ST-03** (AG3-137 Schema+Backfill → AG3-138
  Startup-Rekonsiliierung/admin_abort → AG3-139 TTL-Entfall): zwischen
  ST-02 und ST-03 darf **kein Deployment-Zustand ohne
  Verwaisungs-Handling** existieren — heute ist diese Reihenfolge nur in
  Story-Briefings dokumentiert, nicht als Betriebs-/Deployment-Regel in
  FK-04.
- **Bestands-Inkonsistenz (verifiziert):** das Runbook §4.5.2 „Stale Lock"
  enthält noch den Schritt „Lock-Record prüfen: **Prozess noch aktiv?** /
  Wenn Prozess tot: `agentkit cleanup`" — eine PID-/Liveness-Heuristik,
  die dem bereits umgestellten FK-10 §10.6.1/§10.6.2 widerspricht (Locks
  enden nie automatisch; Stale-Anzeige ist reine Information; Inaktivität
  ist keine Diagnose; der Mensch entscheidet über offizielle
  Recovery-Pfade). Diese Leiche würde in einem Ownership-Runbook-Kapitel
  direkt daneben stehen.

Die zugrundeliegenden **Normen existieren vollständig** (FK-56/91/10/20/30
— Verankerungs-Commits); was fehlt, ist ausschließlich die operative
Runbook-Sicht: Symptom → Ursache → Lösungsschritte über die offiziellen
Pfade. FK-04 hat `prose_anchor_policy: strict` und eine
`formal_refs`-Frontmatter-Liste — neue Abschnitte müssen sich in die
Anker-/Gate-Mechanik einfügen.

## Scope

### In Scope

1. **Runbook „Ownership-Takeover"** (neuer Abschnitt unter FK-04 §4.5,
   Form analog Bestand: Symptom/Ursache/Lösung): der operative Ablauf
   `request → Challenge (inkl. SHA/Push-Frische + Verlustkorridor-
   Pflichttext) → menschliche Freigabe/Confirm → takeover_reconcile der
   neuen Session`; der agenteninitiierte Fall (`pending_human_approval` →
   Freigabe im globalen Overlay bzw. CLI); Wirkung auf den Ex-Owner
   (`ownership_transferred`, Reads erlaubt); Betriebs-Befunde und ihre
   Auflösung: `takeover_reconcile_required` (normal, Reconcile ausführen),
   `contested_local_writes` (menschlich/administrativ auflösen),
   `remote_branch_diverged_after_takeover` (administrativ),
   `local_stale_or_dirty_takeover_target` (Quarantäne). Als Verweis-Prosa
   auf FK-56/30/91 — **keine Norm-Duplikation** (Single-Assertion): das
   Runbook nennt Schritte und verweist, es definiert nichts neu.
2. **Runbook „Hängende In-Flight-Operation / `admin_abort`"**: Symptom
   (Operation dauerhaft `claimed`, Client weg), Diagnose
   (`GET operations/{op_id}`, Regel 17: Transport-Timeouts bedeuten
   nichts), Lösung ausschließlich über
   `POST …/operations/{op_id}/admin-abort` (Klasse `admin_transition`,
   nur servereigene Claims) bzw. den AG3-138-CLI-Adapter; Verhalten bei
   Teil-Writes (expliziter auditierter Reconcile-/Repair-Zustand — was der
   Operator damit tut); ausdrücklich: **kein** Warten auf Ablauf, denn
   nichts läuft ab.
3. **Runbook „Server-Boot / Startup-Rekonsiliierung"**: was der Boot
   deterministisch tut (Verwaisten-Finalisierung eigener Inkarnationen vor
   Request-Annahme), warum fremde Claims unangetastet bleiben, was ein
   fail-closed verweigerter Start bedeutet und wie der Operator reagiert;
   Ein-Writer-Betriebsannahme als Betriebsregel sichtbar machen.
4. **Deployment-/Migrationsreihenfolge als Betriebsregel**: verbindliche
   Reihenfolge AG3-137 (Schema + Backfill laufender Runs) → AG3-138
   (Startup-Rekonsiliierung + `admin_abort` produktiv) → AG3-139
   (TTL-Entfall), mit der Begründung IMPL-006 (die TTL war bis dahin das
   einzige Verwaisungs-Handling; kein Deployment-Zustand ohne
   Verwaisungs-Handling) und dem Hinweis auf den idempotenten Backfill
   (`ownership_epoch=1`, `status='active'`).
5. **Konsistenz-Angleichung §4.5.2 „Stale Lock"**: den
   PID-/Prozess-Liveness-Schritt entfernen und auf die verankerte Semantik
   heben (Stale-Anzeige = Information; Lösung über die offiziellen
   Recovery-Pfade: `recover-story`/Takeover/`cleanup` als explizit-
   administrative Entscheidung — konsistent mit FK-10 §10.6.1/§10.6.2 und
   FK-20 §20.7). Reine Angleichung an bestehende Normen, keine neue
   Festlegung.
6. **Frontmatter-/Anker-Pflege**: soweit die neuen Abschnitte formale
   Commands/Invarianten referenzieren, werden `formal_refs`/PROSE-FORMAL-
   Marker von FK-04 nachgezogen, sodass die Konzept-Gates grün bleiben
   (`prose_anchor_policy: strict`).

### Out of Scope (mit Owner)

- **Jede Code-, Test- oder Schema-Änderung** — diese Story ist doc-only;
  die Mechanik liefern AG3-137/138/139 (Fundament, Reconcile, TTL-Entfall),
  AG3-148/149/151 (Transfer, Disown, Reconcile-Zustände), AG3-154
  (CLI-Kommandos, `recover-story`).
- **Normative Neudefinitionen** (Protokolle, Zustände, Endpoints): liegen
  in FK-56/91/30/10/20 — das Runbook verweist (Single-Assertion), Konflikte
  würden dort gelöst, nicht in FK-04 überschrieben.
- **FK-91-CLI-Tabellen-Pflege für die neuen Kommandos**: **AG3-154**.
- **Frontend-Bedienungsdokumentation des Overlays**: prototyp-normativ
  (FK-72 §72.13) bzw. **AG3-153**; FK-04 verweist nur auf den
  Freigabe-Schritt.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `concept/technical-design/04_betrieb_monitoring_audit_runbooks.md` | ändern | Neue Runbook-Abschnitte unter §4.5 (Takeover, `admin_abort`, Startup-Rekonsiliierung, Migrations-/Deployment-Reihenfolge); Konsistenz-Angleichung §4.5.2; ggf. Frontmatter `formal_refs` + PROSE-FORMAL-Marker |

Keine weiteren Dateien. Insbesondere: keine Änderungen unter
`src/`, `tests/`, `guardrails/` oder an anderen Konzepten (Verweise
zeigen auf bestehende Anker; fehlt ein Anker, ist das ein zu meldender
Befund, kein Freibrief für Nebenänderungen).

## Akzeptanzkriterien

1. **Vier Betriebsfälle abgedeckt:** unter FK-04 §4.5 existieren die
   Runbooks Takeover, `admin_abort`, Startup-Rekonsiliierung und
   Migrations-/Deployment-Reihenfolge in der Bestands-Form
   (Symptom/Ursache/Lösung bzw. Regel + Begründung); jeder Lösungsschritt
   nennt ausschließlich **offizielle Pfade** (Endpoints/CLI-Kommandos, die
   in FK-91 verankert sind) — kein Schritt empfiehlt Umgehungen,
   Wartezeiten auf Ablauf oder manuelle DB-Eingriffe (fail-closed).
2. **Migrationsreihenfolge explizit und begründet:** die Ordnung
   AG3-137 → AG3-138 → AG3-139 steht als verbindliche Betriebsregel mit
   der IMPL-006-Begründung („kein Deployment-Zustand ohne
   Verwaisungs-Handling") und dem Backfill-Hinweis; eine Umkehrung ist als
   unzulässig benannt.
3. **Keine Norm-Duplikation (Single-Assertion):** die Runbooks definieren
   keine Protokoll-/Zustands-/Endpoint-Semantik neu, sondern verweisen auf
   FK-56/91/30/10/20; Stichproben-Review: kein Satz in FK-04 widerspricht
   den Quell-Normen oder formuliert sie abweichend um (Konsistenz mit
   FK-56/FK-91 ist Abnahmebedingung).
4. **§4.5.2 bereinigt:** das Stale-Lock-Runbook enthält keinen
   PID-/Prozess-Liveness-Schritt mehr und ist konsistent mit FK-10
   §10.6.1/§10.6.2 (Stale-Anzeige = Information; explizit-administrative
   Recovery-Entscheidung; Verweis auf `recover-story`/Takeover als
   offizielle Wege).
5. **Terminologie glossar-treu:** verwendete Begriffe
   (`run-ownership-record`, `ownership-transfer`, `ownership_epoch`,
   `pending_human_approval`, Zustands-Namen) entsprechen exakt dem
   FK-56-Glossar bzw. den formalen IDs (englische Bezeichner, ARCH-55;
   deutsche Prosa zulässig).
6. **Konzept-Gates grün:** `scripts/ci/check_concept_frontmatter.py`,
   `scripts/ci/compile_formal_specs.py`,
   `scripts/ci/check_concept_code_contracts.py`,
   `scripts/ci/check_architecture_conformance.py` laufen fehlerfrei
   (insb. `prose_anchor_policy: strict` + `formal_refs`-Konsistenz von
   FK-04).
7. **Doc-only bewiesen:** der Diff berührt ausschließlich
   `concept/technical-design/04_betrieb_monitoring_audit_runbooks.md`
   (Review-/Diff-Beleg); die bestehende Test-Suite bleibt unverändert grün
   (keine Code-Wirkung).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract unverändert grün — doc-only, Coverage ≥ 85
  unberührt, `mypy src` + `--platform linux`, `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** IMPL-024.

## Konzept-Referenzen

- FK-04 §4.5 (Runbook-Kapitel, Bestandsform §4.5.1–§4.5.9; §4.5.2 als
  Angleichungs-Ziel), Frontmatter (`authority_over: operations`,
  `prose_anchor_policy: strict`, `formal_refs`)
- FK-56 §56.13/§56.13a–c (Takeover-Protokoll, Freigabe, atomarer Vollzug,
  Verlustkorridor), §56.13g (`recover-story`-Einordnung), §56.13h
  (Disown-Baustein — Ex-Owner-Auskunft im Runbook)
- FK-91 §91.1 (Operator-Recovery-CLI als menschlicher Adapterpfad),
  §91.1a Regel 16 (Claims enden nur über Start-Rekonsiliierung/
  `admin_abort`), Regel 17 (Transport-Timeouts fachlich bedeutungslos;
  Reconcile via `GET operations/{op_id}`), Endpoint-Zeile
  `POST /v1/project-edge/operations/{op_id}/admin-abort`
  (Teil-Writes → auditierter Reconcile-/Repair-Zustand)
- FK-10 §10.5.4 (Startup-Rekonsiliierung, Ein-Writer-Betriebsannahme),
  §10.6.1 (Absturz-Szenarien — bereits TTL-/PID-frei), §10.6.2
  (Recovery-Protokoll: Mensch entscheidet explizit)
- FK-20 §20.7.3/§20.7.4 (`agentkit recover-story`, Übernehmen/Verwerfen)
- FK-30 §30.6.3 (die vier Edge-Zustände mit Auflösungspfaden —
  Runbook-Verweisziel)
- `formal.state-storage.invariants` →
  `orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort`
  (die Betriebsregel hinter Runbook 2/3);
  `formal.operating-modes.invariants` →
  `ownership_transfer_requires_explicit_confirmed_request`

## Guardrail-Referenzen

- **SINGLE SOURCE OF TRUTH / Konzepttreue:** FK-04 dokumentiert Betrieb,
  definiert aber keine zweite Normwahrheit — jede fachliche Aussage
  verweist auf den Owner-FK (Single-Assertion-Prinzip der
  Konzept-Governance).
- **FAIL-CLOSED / NO ERROR BYPASSING:** kein Runbook-Schritt lehrt
  Umgehungen (kein „Lock manuell löschen", kein „warten bis abgelaufen" —
  es läuft nichts ab); die Lösungswege sind exakt die offiziellen Pfade.
- **ZERO DEBT:** die verifizierte §4.5.2-Leiche (PID-Liveness) wird im
  selben Zug bereinigt statt neben neuen Runbooks stehen gelassen.
- **SEVERITY-SEMANTIK:** Runbooks unterscheiden Information (Stale-Anzeige)
  von Handlungsaufträgen (Repair-Zustand, contested) — nichts davon wird
  als ignorierbar dargestellt.
- **Strukturregeln:** keine neuen Top-Level-Verzeichnisse, keine
  Code-Änderungen; genau eine Konzeptdatei im Diff.

## Querschnitts-Auflagen

- **K5 Postgres-only:** nicht einschlägig — diese Story ändert kein Schema
  und keinen Code (explizit deklariert; die dokumentierte Mechanik ist die
  Postgres-only-Control-Plane der Vorgänger-Stories).
- **Blutgruppen-Klassifikation:** nicht einschlägig — es entstehen keine
  Code-Module (Doku-Story; explizit deklariert gemäß Plan-§3-Auflage
  „je Story konkretisieren").
- **Bundle-Assets:** Keine betroffen (verifiziert: reine Änderung an
  `concept/technical-design/04_…`; `bundles/target_project/` bleibt
  unberührt).
