---
concept_id: META-DEC-2026-07-09-TAKEOVER-CHALLENGE-RECONCILE
title: Concept-Decision-Record — Takeover-Challenge-Persistenz und Reconcile-Obligation am Transfer-Record
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, ownership-transfer, session-ownership, challenge, reconcile, admission-blocker, state-storage, bc-cut, AG3-148]
formal_scope: prose-only
---

# Concept-Decision-Record — Takeover-Challenge-Persistenz und Reconcile-Obligation

Datum: 2026-07-09. Record gemaess META-CONCEPT-CONSISTENCY P3.
Anlass: AG3-148 (Ownership-Transfer-Kern). Eine finale Drei-Reviewer-Runde
(Codex + GLM + Fable) sowie ein Fable-Design-Sparring (Component-Architecture-
Skill) haben zwei architektonische Luecken plus mehrere fail-open/Contract-
Befunde aufgedeckt, die der erste Wurf abgekuerzt hatte. Dieser Record friert
das gehaertete Zielbild ein; er ist der verbindliche Implementierungs-Kontrakt
fuer die AG3-148-Remediation.

## 1. Ausgangsbefund (verifiziert am Code, main@fc1717e8)

- **GAP 1 — Challenge nicht persistiert.** Confirm vertraute der Client-
  echoed `expires_at`; `challenge_id` war die ratbare Konvention
  `takeover-{op_id}`, serverseitig nie validiert. Server-TTL nicht
  durchsetzbar, Challenge-Identitaet client-attestiert. Verstoss gegen
  FK-56 §56.13a (server-autoritative, versionierte Entscheidungsgrundlage)
  und die AG3-148-K5-Klausel (Postgres-only Challenge-Persistenz).
- **GAP 2 — Reconcile-Blocker fail-open.** `takeover_reconcile_required`
  wurde in das geteilte Freitext-Feld `stories.blocker` geschrieben (ohne
  rowcount-Check; von Story-Upserts `blocker=EXCLUDED.blocker` ueberschreibbar;
  durch unattestierten Story-PATCH loeschbar). Verstoss gegen AC16 / FK-30
  §30.6.3 / FK-56 §56.13f.
- **F1** approved-Ausgang wird nicht am Request-Op terminalisiert (Deny schon
  — asymmetrisch); Agent sieht ewig `pending_human_approval` (AC3, §56.13b).
- **F2** `takeover_approval_changed` wird mit `phase="ownership"` emittiert und
  vom SSE-Router auf Topic `phases` statt `governance` geleitet (Dead-Code-
  Zweig; formal.frontend-contracts verlangt `governance`).
- **F5** Challenge-Inhalt `open_operation_ids`/`takeover_history_refs` hart
  leer (§56.13a/d, AC1 verletzt).
- **W6/W7** Confirm bindet Approval nicht an project/story/run/challenge;
  lazy-expiry-Write ungeguarded.

## 2. Entscheidung (Zielbild, verbindlich)

### 2.1 Challenge-Persistenz (GAP 1) — REQUIRED in 148
Neue Postgres-Record-Familie **`takeover_challenges`**, Eigentuemer-BC
**story-lifecycle** (Modul `state_backend/story_lifecycle_store`, gleiches
Zuhause wie `takeover_approvals` und `takeover_transfer_records`; FK-72 §72.14
`owner_bc: story-lifecycle`). Single Writer: Control-Plane-Runtime (K5,
Postgres-only). Felder (Minimum): opaque server-minted `challenge_id`,
`request_op_id`, project/story/run, requesting_session/principal, reason,
`owner_session_id`, `ownership_epoch`, `binding_version`, `phase_status`,
`issued_at`, `expires_at`, per-Repo Anzeige-/Audit-Block
(`repo_id`, candidate `takeover_base_sha`, `last_push_at`, `push_lag_hint`,
`base_quality`), `open_operation_ids`, `takeover_history_refs`, Status/Audit.

- **Confirm-CAS-Basis ist ausschliesslich** `owner_session_id` +
  `ownership_epoch` + `binding_version` + Server-TTL (aus der gespeicherten
  Zeile, NICHT aus dem Client-Echo) + Challenge-Existenz/-Gueltigkeit. Der
  per-Repo-SHA der Challenge ist Anzeige/Audit; **keine** Echo-SHA-Gleichheit
  im CAS.
- **Der gepushte Head wird zur Confirm-Zeit materialisiert** (live aus dem
  verifizierten AG3-147-PushBarrierVerdict), §56.13c; die bestehende Live-
  Rederivation muss ueberleben.
- **Challenge-Invalidierung wird beim Confirm ABGELEITET** aus dem epoch/
  binding-CAS-Mismatch (`challenge_invalidated`) — sie ist KEIN Status, den
  exit/reset/split/closure/freeze schreiben (sonst 5-Flow-Kopplung in den
  Challenge-Store). Nur Takeover-Pfade schreiben Terminal-Status
  (confirmed/denied/expired/invalidated).
- `challenge_id` ist opaque server-minted; der String-Parser
  `takeover-{op_id}` entfaellt (persistierte `request_op_id` ersetzt ihn).

### 2.2 Challenge vs. Approval — getrennt, EINE Komponente
`takeover_challenges` (server-autoritative Entscheidungsgrundlage fuer
Menschen- UND Agent-Pfad) und `takeover_approvals` (Agent-Permission-Wrapper,
FK-42/FK-90-Familie) bleiben getrennte Record-Familien mit
`approval.challenge_ref → challenge.challenge_id`, aber innerhalb der EINEN
Komponente OwnershipTransferProtocol (CCP/CRP: die Challenge aendert mit der
Ownership-CAS-Semantik, die Approval mit der Permission-/Overlay-Semantik).

### 2.3 TTL-Semantik (Red-Flag 5) — Confirm re-issued frische Challenge
Bestaetigt ein Mensch eine noch gueltige Agent-Approval, deren Challenge-TTL
(15 min) bereits abgelaufen ist (Approval-TTL 2 h), so **re-issued der Confirm
eine frische Challenge**: er schnappt die Entscheidungsgrundlage neu
(aktueller owner_session_id/ownership_epoch/binding_version, per-Repo base_sha,
neue TTL) und fuehrt den CAS auf dieser frischen Basis aus. Der Mensch
entscheidet auf aktuellen Daten; kein Sackgassen-Dead-End. (Konzept war
unterspezifiziert; hiermit entschieden.)

### 2.4 Reconcile-Obligation (GAP 2) — REQUIRED in 148, Modellierung am Transfer-Record
**Kein** drittes Freitext-/Blocker-Table und **nicht** `stories.blocker`.
Stattdessen die Reconcile-Pflicht am bestehenden **Takeover-Transfer-Record**
modellieren: additive Felder `reconciled_at` / `reconcile_ref` (symmetrisch zu
`challenge_ref`/`confirm_ref`). **Admission-Regel:** eine Story ist nur
mutations-admissibel, wenn **kein** Transfer-Row der **aktuellen
`ownership_epoch`** unreconciled ist; sonst fail-closed `409` +
maschinenlesbarer Grund `takeover_reconcile_required`.

- Atomicity gratis (Transfer-Rows werden ohnehin im Confirm-Unit-of-Work
  geschrieben); Fehler beim Schreiben → Rollback des gesamten Transfers.
- Audit am Uebergabeobjekt; per-Repo natuerlich (passt zu
  `takeover-reconcile-worktree`, FK-30 §30.6.3); kein Create/Clear-Drift
  zweier Records fuer EINE Wahrheit (FIX THE MODEL).
- Vor AG3-151 loest ausschliesslich der auditierte `admin_transition` die
  Obligation (aktualisiert dieselben Rows). AG3-151 baut den vollen Reconcile-
  Contract darauf auf.
- Admission-Check sitzt am bestehenden Control-Plane-Runtime-Admission-/Fence-
  Locus (Rule-15-Analog: Re-Read zur Commit-Zeit) via Read-Port; Writer =
  Confirm-Unit-of-Work; Clearer = Reconcile-/Admin-Pfad. Reader und Writer sind
  Ports derselben Komponentenfamilie → kein Required-Interface-Zyklus.

### 2.5 Weitere Festlegungen
- **F1:** Original-Request-Op im Confirm/Deny/Expiry-Unit-of-Work
  terminalisieren (`request_op_id` persistiert). Expiry bleibt **lazy**
  (materialisiert beim naechsten Touch; kein Background-Reaper; FK-91 §91.1a
  Rule 16).
- **F2:** `takeover_approval_changed` erreicht Topic `governance` — governance-
  Event-Typen VOR dem phase-Zweig pruefen (oder diese Events mit `phase=None`
  emittieren).
- **F5:** Challenge-Inhalt aus zwei schmalen Owner-BC-Read-Ports
  (`control_plane_operations` live sync-ops; `takeover_transfer_records`/
  challenge-history) — nie aus Telemetrie-Projektionen.
- **W6:** Confirm validiert `approval.project_key/story_id/run_id` und
  `approval.challenge_ref` (wie Deny). **W7:** lazy-expiry-Update mit
  `AND status='pending'`-Guard.

## 3. Azyklik / Blutgruppen
Kein Store→Store-Zyklus: die Confirm/Deny-Transaktion bleibt im Muster
Runtime (R) assembliert via Read-Ports → EIN `operation_ledger`-Unit-of-Work
schreibt alle Rows (challenge-terminalisierung, ownership-CAS, bindings, lock,
transfers inkl. reconcile-Feldern, approval, events). A-Core
`control_plane/ownership_transfer.py` bleibt rein (keine Persistenz/HTTP/Clock/
SQL/Events). Das ist exakt das bestehende Muster (commit_takeover_confirm
schreibt heute schon governance-Lock- + story-lifecycle-Rows atomar).

## 4. Alternativen (verworfen)
- GAP-2 als drittes eigenstaendiges `admission_blockers`-Table: verworfen —
  zweite operative Wahrheit fuer „nicht mutations-admissibel" neben
  `governance_freeze_records`, CCP-Verstoss, Create/Clear-Drift.
- GAP-2 auf gehaertetem `stories.blocker`: verworfen — Runtime-Admissions-
  Wahrheit in Story-Stammdaten/Freitext (String-Flag-Kaskade; widerspricht
  FK-17 kleinem stabilem Story-Modell).
- Challenge in Request-Op-Body-Hash kodieren statt eigener Tabelle: verworfen —
  koppelt Security-Semantik an Payload-Form, Challenge-Lebenszyklus bruechig.
- (Nicht gewaehlt, aber zulaessige Variante B fuer GAP 2: Reconcile-Zustand als
  Instanz der §56.13f-Freeze-Familie `governance_freeze_records`,
  `freeze_reason='takeover_reconcile_required'`, geschrieben durch denselben
  Unit-of-Work. Option A (Transfer-Record) bevorzugt wegen Atomicity-gratis und
  Ein-Wahrheit; falls die formale Klaerung Variante B verlangt, ist der Umstieg
  additiv.)

## 5. Betroffenheitsmatrix
| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-56 §56.13a/c/d/f | nicht betroffen | bleibt normative Heimat; Record bestaetigt/operationalisiert |
| FK-30 §30.6.3 | nicht betroffen | Reconcile-Guard-Semantik unveraendert; Obligation am Transfer-Record ist die Persistenz-Auspraegung |
| formal.state-storage.entities (v5) | **geaendert (Migrationsschnitt)** | neue Entitaeten `takeover-challenge`, `takeover-approval` und Reconcile-Felder am `takeover-transfer-record` → Schema-Version-Bump + Contract-Tests im Remediation-Diff |
| FK-72 §72.14 | nicht betroffen | `owner_bc: story-lifecycle` bestaetigt |
| K5 (control-plane Postgres-only) | nicht betroffen | Challenge/Reconcile Postgres-only, bestaetigt |
| TTL-Semantik agent→human | **entschieden + verschaerft (§6.3)** | Confirm re-issued frische Challenge (§2.3), ABER nur bei unveraenderter Eigentumslage — sonst §56.13a-Invalidierung |
| PROJECT_STRUCTURE.md | nicht betroffen | keine neuen Top-Level-Verzeichnisse |

## 6. Nachtrag 2026-07-10 — Confirm-Identitaetsmodell + Reissue-Guard (Finale-Befunde)

Ein zweites Fable-Finale (Component-Architecture) auf dem konvergierten Remediation-
Head (main@bcce5555) hat drei ERROR-Befunde aufgedeckt, die alle dieselbe Wurzel
haben: der **Confirm zieht die Entscheidungsgrundlage aus dem Request-Body statt aus
der gespeicherten Challenge (Server-Wahrheit)** — genau der FIX-THE-MODEL-/§56.13a-
Verstoss, den diese Story tilgen soll. Codex+GLM (beide APPROVE nach Runde 2) haben
diese Schicht uebersehen; am Code verifiziert. Dieser Nachtrag friert die Zielsemantik
ein; er ist verbindlicher Implementierungs-Kontrakt fuer die AG3-148-Remediation R3.

### 6.1 Confirm-Identitaetsmodell (ERROR 1) — REQUIRED
Die neue `SessionRunBinding` MUSS auf die **requesting session der gespeicherten
Challenge/Approval** lauten (`requested_by_session_id` / `requested_by_principal_type`
+ deren edge-reported `worktree_roots`), NICHT auf `request.session_id` /
`request.principal_type` aus dem Confirm-Body (heute `_ownership_transfer.py:498-507`).
Der Confirm-Body (menschliche BFF-Session) legitimiert den Vollzug, bestimmt aber NIE
die Owner-Identitaet. Fuer den agent-initiierten Pfad wird B (der Agent) Owner mit
`principal_type` des Agents — kein Stempeln als `human_bff_session`. Normativ:
`formal.operating-modes.command.confirm-run-ownership-takeover` ("transfer the run
binding to the requesting session … rebinding worktree_roots to the edge reported
roots of the new session"), FK-56 §56.13c/e. Die Tests, die heute Owner=Confirm-Body-
Session pinnen (`test_takeover_confirm_pg.py:664ff`, t5), pinnen das falsche Verhalten
und sind mitzuziehen.

### 6.2 approval_required aus Server-Wahrheit (ERROR 2) — REQUIRED
`approval_required` wird aus `stored_challenge.requested_by_principal_type` abgeleitet
(agent-initiiert ⇒ Approval Pflicht), NICHT aus `request.approval_id is not None`
(heute `:471`). Eine agent-initiierte Challenge ist ohne die zugehoerige APPROVED
Approval **nicht** confirmbar (fail-closed); ein Confirm ohne `approval_id` darf sie
nicht als approval-frei behandeln. Verhindert die persistente Zombie-Approval
(`agent_initiated_takeover_requires_human_frontend_approval`, AC14).

### 6.3 Reissue-Guard (ERROR 3) — Verschaerfung von §2.3
Der §2.3-Reissue (frische Challenge bei abgelaufener Challenge-TTL, gueltige Approval)
gilt AUSSCHLIESSLICH bei **unveraenderter Eigentumslage**: reissue nur, wenn
`active.owner_session_id` UND `active.ownership_epoch` noch der Basis der gespeicherten
Challenge entsprechen. Hat sich die Eigentumslage zwischenzeitlich geaendert (fremder
Transfer/Exit/Reset/Split → neuer Owner/Epoch), wird die offene Challenge INVALIDIERT
(FK-56 §56.13a: "jede zwischenzeitliche Aenderung der Eigentumslage invalidiert offene
Challenges; der Verlierer muss neu anfragen — dann gegen den neuen Owner"); KEIN
Auto-Reissue gegen einen Owner, den kein Mensch je in einer Challenge gesehen hat.
Damit bleibt §2.3s Zweck (kein TTL-Sackgassen-Dead-End) erhalten, ohne §56.13a zu
verletzen. Prioritaet: kanonisches Konzept (§56.13a) vor Decision-Detail.

### 6.4 Request-Principal fail-closed (WARNING 5) — REQUIRED
Die Request-seitige Principal-Klassifikation (Approval-Queue vs. offered) wird aus dem
**attestierten** `auth_kind`/Boundary-Principal abgeleitet, nicht aus einem Client-
String. Principals ausserhalb der FK-55-Kanonwerte werden abgewiesen (kein Fail-open-
Fallback in den human-`offered`-Zweig); das Vokabular ist einheitlich
(`_AGENT_PRINCIPAL_TYPES` an FK-55 ausrichten, kein nicht-kanonisches `"agent"`).

### 6.5 Cross-Project-Fence (WARNING 6) — REQUIRED sofern reproduzierbar
Takeover-Request/-Confirm erzwingen `body.project_key == auth_result.project_key`
(fail-closed 403), sodass ein Projekt-A-Token keine Takeover-Operationen gegen
Projekt B ausfuehren kann (kein Cross-Tenant ueber den `X-Project-Key`-Fallback). Vom
Worker am Code zu reproduzieren; falls nicht ausnutzbar, mit Beweis dokumentieren.

### 6.6 Getrennte Admission-Gruende (WARNING 7)
Repair-Lock (AG3-138) und Reconcile-Obligation sind zwei Zustaende der §56.13f-Familie
mit unterschiedlicher sanktionierter Aufloesung; die Admission gibt distinkte
`error_code`s zurueck (nicht beide als `takeover_reconcile_required`).

### 6.7 Component-/Test-Auflagen (WARNING 4/8/9)
- `TakeoverApprovalRepository` wird ueber den `ControlPlaneRuntimeRepository`-Port
  konsumiert (kein ad-hoc Inline-Import als verstecktes Required-Interface;
  Replaceability/Fake-Barkeit herstellen). Request-Pfad-Atomizitaet bleibt
  dokumentierter AG3-149-Follow-up (§3 bindet Atomizitaet an confirm/deny), aber die
  Lese-Seite bleibt fail-closed und §6.2 eliminiert die Zombie-Approval.
- AC6 (Stale-Confirm je zwischenzeitlichem Uebergang: Exit/Reset/Split/Closure, nicht
  nur Transfer), AC12 (praeparierte Stale-Push-Freshness triggert nichts) und AC13
  (Confirm hinter laufender Mutation) werden mit echten fail-before/pass-after-Tests
  ueber die realen Vorgaengerpfade belegt.
- Pending-Approval-Abfrageflaeche (Story-Scope 10): pruefen, ob 148-AC-pflichtig oder
  AG3-153-UI-Flaeche; im 148-Scope belegen, sonst als 153-Kante dokumentieren.
