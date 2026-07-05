# AG3-144 — Reconnect-Rekonsiliierung + No-Lease-no-Write-Vollständigkeit (synchrones Sollbild)

- **Typ:** implementation
- **Größe:** S/M
- **depends_on:** [AG3-138, AG3-140, AG3-142] — alle gelandet.
  - **AG3-142** — der aktive `RunOwnershipRecord` + `_enforce_ownership_fence_row`
    (Lease-Fence in derselben Transaktion, `SELECT … FOR UPDATE`) ist der EINE
    Fence-Mechanismus, den diese Story auf alle mutierenden Story-Projektions-Writes
    ausdehnt.
  - **AG3-138/AG3-140** — der op_id-Reconcile-Weg (`GET operations/{op_id}` liefert das
    gespeicherte Terminal-Ergebnis) + der Client-op_id-Vertrag tragen die
    Reconnect-Rekonsiliierung.
- **Herkunft:** NEUSCHNITT nach PO-Architekturentscheidung 2026-07-05 (bindend):
  synchrones Ausführungsmodell; der aktive Ownership-Lease ist der ALLEINIGE Fence.
  Ersetzt den ursprünglichen L-Schnitt (async 202-Job-Muster + drei Ergebnisarten +
  `stale_observation`), der mit der synchronen Entscheidung ENTFALLEN ist
  (Konzept-Commits 7fc7a834 + a964629a; FK-91 §91.1a Regel 14/15 neu, FK-44 §44.3a).
  Die geparkte Fence-Hälfte (Branch `ag3-144-fence-half-wip`) wird VERWORFEN.

## Kontext / Problem

Das synchrone Sollbild (FK-91 §91.1a Regel 14 neu): lange Umsetzungsarbeit läuft
synchron im Request. Zwei Konsequenzen sind abzusichern:

1. **Reconnect (Regel 17).** Bricht die Leitung ab, verliert der Client weder
   Ownership noch Arbeit — er rekonsiliiert den Ausgang über `GET operations/{op_id}`
   (bzw. den Story-Run-Status). Dieser Weg existiert bereits (AG3-138/140: Terminal-
   Ergebnisse sind über `GET operations/{op_id}` abrufbar). Zu tun: den Ende-zu-Ende-
   Pfad an der Phasengrenze VERIFIZIEREN und etwaige Lücken schließen.

2. **No-Lease-no-Write (Regel 15 neu).** Wer den aktiven Ownership-Lease nicht (mehr)
   hält, kann für die Story NICHTS Mutierbares durchsetzen; ein verspätetes Ex-Owner-
   Ergebnis wird deterministisch abgewiesen (Regel 18), nicht als Historie abgelegt.
   Der Regime-Fence (AG3-142, `_enforce_ownership_fence_row`) deckt die Regime-Pfade
   (start/complete/fail/closure/resume). Die mutierenden **Projektions-Writes**
   (`artifact_envelopes`, `qa_stage_results`, `qa_findings` inkl. Batch-Delete+Rebuild,
   `decision_records`, `closure_report`) rufen den Fence heute NICHT direkt (am Code
   verifiziert 2026-07-05: `_enforce_ownership_fence_row` an den Regime-Commits, nicht
   an `persist_layer_artifact_rows`/`persist_verify_decision_row`/
   `persist_closure_report_row`/`_pg_write`). Zu tun: SICHERSTELLEN, dass jeder dieser
   Writes transaktional vom Lease gedeckt ist.

## Scope

### In Scope

1. **Reconnect-Verifikation (+ Lückenschluss).** Integrationstest an der echten
   Phasengrenze: eine (synchrone) mutierende Operation verliert die Verbindung; der
   Client rekonsiliiert über `GET operations/{op_id}` und erhält das committete
   Terminal-Ergebnis; ein noch laufender Lauf ist als in-flight beobachtbar; kein
   Server-Minting (client-op_id, AG3-140); op_id-Idempotenz (kein Doppel-Effekt). Ist
   der Pfad bereits vollständig (erwartet), genügt der pinnende Test; besteht eine
   echte Lücke (z. B. Terminal-Ergebnis nicht abrufbar), wird sie minimal geschlossen.

2. **No-Lease-no-Write-Vollständigkeit.** Für JEDE mutierende Story-Projektions-
   Schreibfläche (`artifact_envelopes`-Upsert, `qa_stage_results`, `qa_findings` inkl.
   Batch, `decision_records`, `closure_report`) nachweisen/sicherstellen: ein Commit
   einer Session, deren Ownership nicht (mehr) dem aktiven Record entspricht, wird
   deterministisch abgewiesen — OHNE State-Write. Wo der Write nicht bereits
   transaktional in einem gefencten Regime-Commit liegt, den AG3-142-Lease-Fence
   (`_enforce_ownership_fence_row`) an seinem Commit ergänzen — in DERSELBEN
   Transaktion, `SELECT … FOR UPDATE` (kein TOCTOU). Die Erhebung des Ist-Zustands
   (transaktional gedeckt vs. eigenständiger Commit) je Schreibfläche ist Teil der
   Story und wird als Beleg dokumentiert.

3. **Abgrenzung (explizit ENTFALLEN, nicht zu bauen):** async `202`-Job-Muster /
   server-seitiger Background-Execution-Driver; Ergebnisart-Registry
   (`append_only_observation`/`projection_upsert`/`steering`); `stale_observation`-
   Store; materialisierte Fence-Sicht; per-Phase-Attempt-Snapshot; die Stale-Prädikate
   `compaction_epoch`/`execution_contract_digest`/Artefakt-Zielversion. Der
   `execution_contract_digest` (AG3-143) bleibt als Run-Pinning-/Audit-Artefakt
   bestehen, wird NICHT als Fence-Prädikat verdrahtet.

### Out of Scope (mit Owner)

- **Disown-/Reset-Verhalten** (Owner-Notification, Tombstone, Reconcile): **AG3-149**.
- **In-Flight-Idempotenz** (`operation_epoch`-CAS): **AG3-138/AG3-140** (eigener,
  unberührter Mechanismus — wird hier nur konsumiert, soweit vorhanden).
- **Edge-Command-Result-Fencing**: **AG3-145** (nutzt denselben Lease-Fence auf seiner
  eigenen Schreibfläche).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/state_backend/postgres_store.py` | ändern | Lease-Fence (`_enforce_ownership_fence_row`) an den Projektions-Write-Commits ergänzen, wo nicht schon transaktional gedeckt (`persist_layer_artifact_rows`, `persist_verify_decision_row`, `persist_closure_report_row`, QA-Row-Upserts) |
| `src/agentkit/backend/state_backend/store/artifact_repository.py` | ändern | `artifact_envelopes`-`_pg_write`-Upsert unter den Lease-Fence (in derselben Transaktion) |
| `src/agentkit/backend/state_backend/store/facade.py` (+ Nachbarn) | ändern (falls nötig) | Fence-Kontext (aktiver Record) an die Write-Fassaden durchreichen, soweit für die Lease-Prüfung erforderlich |
| `tests/integration/**` | neu | Reconnect-Rekonsiliierung an der Phasengrenze; No-Lease-no-Write-Negativpfade je Schreibfläche (echte Epoch-Drift über die AG3-137-Schreibfläche); TOCTOU-Concurrency (AG3-142-Standard) |
| `tests/unit/**`, `tests/contract/**` | neu/ändern | Ex-Owner-Abweisungs-Fehlerform (Regel 18); Vollständigkeits-Grep als Test/Review-Artefakt |

## Akzeptanzkriterien

1. **Reconnect:** Integrationstest an der echten Phasengrenze — Verbindungsabbruch
   während einer synchronen Mutation → Rekonsiliierung via `GET operations/{op_id}` →
   committetes Terminal-Ergebnis; op_id-Idempotenz (kein Doppel-Effekt); kein
   Server-Minting.
2. **No-Lease-no-Write je Projektions-Write:** für `artifact_envelopes`,
   `qa_stage_results`, `qa_findings` (inkl. Batch-Delete+Rebuild), `decision_records`,
   `closure_report` je ein Negativtest — ein Write einer Session mit abweichendem/
   verlorenem Lease (präparierte Epoch-Drift über die sanktionierte AG3-137-
   Schreibfläche) schreibt NICHTS (Projektion byte-identisch) und wird mit `409`/`403`
   + `ownership_transferred`-Payload abgewiesen (Regel 18).
3. **Positivpfad:** gültiger Lease ⇒ Write wie spezifiziert (Regression bleibt grün).
4. **TOCTOU-frei:** der Lease-Read erfolgt zum Commit-Zeitpunkt in DERSELBEN
   Transaktion unter `SELECT … FOR UPDATE` (Concurrency-Test analog AG3-142; ein
   Owner-Wechsel zwischen Prüfung und Commit gewinnt nie).
5. **Vollständigkeit:** Grep-/Review-Beleg, dass KEIN mutierender Story-Projektions-
   Write ohne Lease-Deckung verbleibt (Betroffene-Flächen-Liste vollständig
   abgearbeitet); je Fläche dokumentiert, ob sie schon transaktional gedeckt war oder
   der Fence ergänzt wurde.
6. **Kein Ballast:** kein `stale_observation`, keine Ergebnisart-Registry, keine
   Fence-Sicht, kein Snapshot-/compaction-/digest-Prädikat eingeführt (Code-Beweis).
7. Coverage ≥ 85 % gehalten; `mypy` strict (+ `--platform linux`) und `ruff` ohne neue
   Ausnahmen; ARCH-55 (englische Bezeichner/Wire-Keys/Fehlercodes); 4 Konzept-Gates.

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest` unit/integration/contract,
  Coverage ≥ 85, `mypy src` + `--platform linux`, `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`; README-Backlog (§6.8)
  nachgezogen; Branch `ag3-144-fence-half-wip` verworfen.

## Konzept-Referenzen

- FK-91 §91.1a Regel 14 (synchrone Umsetzung; Reconnect-Rekonsiliierung via Regel 17),
  Regel 15 (Ownership-Lease als alleiniger Fence; Ex-Owner-Abweisung ohne State-Write,
  keine Stale-Historie), Regel 17 (Reconnect), Regel 18 (Ex-Owner-Fehlerbild)
- FK-44 §44.3a (`execution_contract_digest` = Run-Pinning-/Audit-Artefakt, kein
  Fence-Prädikat)
- `formal.state-storage.invariants` →
  `stale_results_never_overwrite_current_projections` (neu: Lease-Verlust ⇒ Abweisung
  ohne State-Write)

## Guardrail-Referenzen

- **FAIL-CLOSED:** Ein Write ohne gültigen Lease wirkt nie „trotzdem"; er wird
  abgewiesen, ohne jeden State-Write.
- **FIX THE MODEL:** EIN Fence-Mechanismus (der Ownership-Lease aus AG3-142) für ALLE
  mutierenden Story-Writes — keine zweite Fence-Schicht, keine Stale-Sonderpfade.
- **ZERO DEBT:** Der Scope ist bewusst klein; die entfallene async/Stale-Maschinerie
  wird NICHT halb mitgeschleppt (die geparkte Fence-Hälfte wird verworfen).
- **Testing-Guardrails:** Negativpfade an der Commit-Grenze; Zustand über die echte
  AG3-137-Schreibfläche/echte Vorgängerpfade, nicht zusammenfantasiert.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Der Lease-Fence ist Postgres-only (`_enforce_ownership_fence_row`,
  `SELECT … FOR UPDATE`); der schmale SQLite-Unit-Test-Pfad erhält KEINE Fence-
  Spiegelung (explizit, kein stilles Offenlassen).
- **Blutgruppen-Klassifikation:** die Lease-Fence-Nutzung an den Projektions-Writes +
  Row-/DDL-Mechanik = **AT/T** (state_backend); Reconnect-/Wire-Mapping = **R**. Kein
  neuer A-Kern.
- **Bundle-Assets:** keine betroffen (verifiziert).
