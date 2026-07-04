# AG3-150 — Freeze-Zustände als Admission-Blocker: `freeze_epoch`/`freeze_reason` auf der conflict_freeze-Familie, Challenge-Invalidierung bei Freeze-Eintritt, Split-Fence → Admin-Freeze

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [AG3-149] — der Schlussstein der 07-Familie (GAP §4:
  ST-07a → ST-07b → ST-07c): die Split-Umstellung setzt den in AG3-149
  vereinheitlichten Disown-Baustein voraus (der Split entwertet fremde
  Bindungen über ihn, FK-54 §54.8.2a) und die Entmündigungs-/
  Capability-Fläche aus AG3-149 (FK-55 §55.8.3 „analog `conflict_freeze`")
  ist das Gegenstück, an dem die Freeze-Familie andockt; die zu
  invalidierenden Challenges und die takeover-admissibility-Prüfung
  betreffen die (transitiv über AG3-149 → AG3-148 vorhandene)
  Transfer-Fläche.
- **Quell-Konzept:** FK-56 §56.13f (Freeze-Zustände als Admission-Blocker
  mit `freeze_epoch`/`freeze_reason`; Challenge-Invalidierung;
  takeover-admissibility); `formal.operating-modes.invariants` →
  `freeze_states_are_admission_blockers_and_invalidate_challenges`;
  FK-54 §54.8.2 (Fence) + §54.8.2a (Split als administrative Saga:
  Admin-Freeze über die Dauer, kurze bounded gefencte Sub-Commits mit
  eigenem Claim-Erwerb in globaler Ordnung, Reentranz über
  `op_id`-Abstammung); FK-55 §55.8 (`conflict_freeze` als Vorbild)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-07c; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-56 §56.13f normiert: alle temporären Sperr-/Sonderzustände —
`conflict_freeze`, der administrative Split-Freeze, Reconcile-/
Repair-Zustände, `contested_local_writes` — sind story-scoped
**Admission-Blocker** mit eigener `freeze_epoch`, `freeze_reason` und
Audit-Spur; der Ownership-Record bleibt dabei `active`, der Freeze
blockiert **zusätzlich**; jeder Freeze-Eintritt invalidiert offene
Takeover-Challenges. Der Ist-Zustand (am Code verifiziert 2026-07-02):

- **`conflict_freeze` existiert als tragfähiges Vorbild — aber ohne
  Epoche und ohne Admission-Wirkung:**
  `governance/principal_capabilities/freeze.py` bietet
  `set_freeze` (:93), `read_freeze` (:104), `clear_freeze` (:108),
  `is_frozen` (:246) mit `freeze_reason`; es gibt eine
  Record-Versionszählung (`_record_freeze_version` :386), aber **keine
  `freeze_epoch`** (Grep `freeze_epoch` über `src/agentkit/`: null
  Treffer). Tabellen: `governance_freeze_records`
  (`state_backend/postgres_schema.sql:820`, `freeze_reason` :823) und
  `conflict_freeze_proofs` (:848) — beide existieren auch im gated
  SQLite-Test-Backend (`sqlite_store.py:826/:854`). Konsumiert wird der
  Freeze nur guard-/gate-seitig: Capability-Enforcement (`enforcement.py:424`)
  und Integrity-Gate-Proof-Prüfung
  (`governance/integrity_gate/dimensions.py:717`,
  `_check_conflict_freeze_proof`). **Kein Regime-Mutationspfad prüft
  Freezes** — die Admission aus AG3-142/149 kennt ausschließlich den
  Ownership-Record.
- **Keine Challenge-Invalidierung bei Freeze-Eintritt:** AG3-148
  invalidiert Challenges bei Eigentumslage-Änderungen (Transfer, Exit,
  Reset, Split, Closure); ein Freeze-Eintritt (z. B. `conflict_freeze`
  während eines offenen Challenge) bleibt ohne Wirkung auf offene
  Challenges, und `confirm-run-ownership-takeover` kennt keine
  takeover-admissibility-Prüfung.
- **Der Split hält eine exklusive Fence über die gesamte Saga-Dauer:**
  `_commit_fence` (`story_split/service.py:251`, Kommentar „exclusive
  fence" :250) committet den Split als Operation mit `op_id=split_id`
  (:958/:1147) und hält diese Exklusivität über den gesamten Ablauf —
  statt des normierten Admin-Freeze mit kurzen, bounded, gefencten
  Sub-Commits (FK-54 §54.8.2a). Die Saga-Ordnung und Reentranz **tragen**:
  deterministisches `split_id` (:227), Resume-Konvergenz (:232-240),
  `op_id`-Abstammung der Successor-Anlagen
  (`{split_id}:successor:{index}:{story_id}` :680),
  `materialize_split_lineage` (:89/:355), Quiesce (:312-315).

Ohne diese Story bleibt „Freeze" ein reines Guard-Signal ohne
Admission-Wirkung, offene Challenges überleben Konflikt-/Split-Zustände,
und der Split blockiert länger und breiter als fachlich nötig.

## Scope

### In Scope

1. **`freeze_epoch`/`freeze_reason` auf der Freeze-Familie** (SOLL-092-Basis,
   SOLL-093): die Freeze-Records werden zur generischen, story-scoped
   **Freeze-Familie** generalisiert — Mitglieder: `conflict_freeze`
   (Bestand), der **Split-Admin-Freeze** (neu, In-Scope 4), der
   **Reconcile-/Repair-Zustand** nach `admin_abort`-Teil-Writes (erzeugt
   von AG3-138, hier als Familienmitglied geführt) und
   `contested_local_writes` (Zustands-**Eintritt** erzeugt AG3-151; das
   Familien-Vokabular und die Blocker-Mechanik entstehen hier). Jeder
   Eintrag trägt `freeze_epoch` (monoton je Story, additiv zur bestehenden
   Versionszählung), `freeze_reason` und Audit-Spur. Freezes enden nie
   automatisch (kein TTL-/Wanduhr-Pfad); Auflösung nur über die explizit
   erlaubten Reconcile-/Repair-/Admin-Kommandos.
2. **Generischer story-scoped Admission-Blocker** (SOLL-092, SOLL-093):
   mutierende Admissions erfordern **beides** — aktiven Ownership-Record
   UND keinen blockierenden Freeze. Der Blocker wird an der
   AG3-142/149-Admissionsfläche durchgesetzt (alle Regime-Mutationspfade:
   start/complete/fail/resume/closure/Executor), transaktional mit dem
   Commit (kein TOCTOU). Der Ownership-Record bleibt während eines Freeze
   `active` — der Freeze blockiert zusätzlich, er entzieht kein Eigentum.
   **Ausnahmen fail-open sind verboten**: nur die explizit als
   auflösend registrierten Reconcile-/Repair-/Admin-Kommandos passieren
   den Blocker.
3. **Challenge-Invalidierung bei Freeze-Eintritt** (SOLL-092, SOLL-093):
   jeder Eintritt in einen Zustand der Freeze-Familie invalidiert offene
   Takeover-Challenges (AG3-148-Fläche); `confirm-run-ownership-takeover`
   scheitert deterministisch, solange die Story nicht takeover-admissible
   ist (aktiver blockierender Freeze ⇒ nicht takeover-admissible). Nach
   der Freeze-Auflösung ist ein **neuer** Request nötig — verfallene
   Challenges leben nicht wieder auf.
4. **Split-Fence → Admin-Freeze** (SOLL-086, SOLL-087): der §54.8.2-Fence
   wird auf einen fachlichen **Admin-Freeze über die gesamte Saga-Dauer**
   umgestellt (Mitglied der Familie: nie auto-ablaufend, auditiert,
   Admission-Blocker). Jeder Saga-Schritt wird eine **kurze, bounded,
   gefencte Mutation** mit eigenem Claim-Erwerb und eigener Freigabe
   (AG3-141: per-Story-Objekt-Claim; Nachfolger-Anlage/Nummernvergabe
   vollständig in einer Transaktion); die Saga als Ganzes hält **keine**
   Serialisierungs-Claims über ihre Laufzeit. Die
   bestehende Reentranz über die `op_id`-Abstammung wird **angedockt,
   nicht neu gebaut** (SOLL-087): Resume konvergiert ohne Doppelvollzug
   (keine doppelte Successor-Anlage, kein doppeltes Rebinding, kein
   zweiter Source-Cancel).

### Out of Scope (mit Owner)

- **Erzeugung des `contested_local_writes`-Eintritts, Guard-Zustände,
  Reconcile-/Quarantäne-Ausführung**: **AG3-151** (konsumiert die hier
  gebaute Familie/Blocker-Mechanik für den read-only Konflikt-Freeze).
  Hinweis: AG3-151 registriert `contested_local_writes` über die hier
  gebaute `freeze_epoch`-Familienfläche (Kante AG3-151 ← AG3-150
  existiert; kein Bestands-`conflict_freeze`-Fallback mehr).
- **Erzeugung des Reconcile-/Repair-Zustands** nach `admin_abort`-
  Teil-Writes: **AG3-138** (die Einordnung als Familienmitglied und die
  Admission-Wirkung entstehen hier).
- **Transfer-Endpoints, Challenge-Bau, Invalidierung bei
  Eigentumslage-Änderung**: **AG3-148**.
- **Disown-Baustein, Record-Status-Pflege, Ping-Pong**: **AG3-149** (der
  Split-Disown-Anteil liegt dort; hier nur Saga-/Freeze-Modellierung).
- **Per-Story-Objekt-Claim-Maschinerie**: **AG3-141**
  (wird hier je Saga-Schritt konsumiert).
- **Frontend-Anzeige der Freeze-/Contested-Zustände**: **AG3-153**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/governance/principal_capabilities/freeze.py` | ändern | Generalisierung zur Freeze-Familie: Familien-Vokabular (`conflict_freeze`, `split_admin_freeze`, `reconcile_repair`, `contested_local_writes`), `freeze_epoch` (monoton je Story), auflösende Kommando-Registrierung |
| `src/agentkit/backend/state_backend/postgres_schema.sql` + `sqlite_store.py` + `postgres_store.py` + `store/facade.py` | ändern | Additive Spalten (`freeze_epoch`, Familien-Kind) auf `governance_freeze_records` — die Bestands-Tabelle ist in beiden Backends definiert (:820/:826), die additiven Spalten folgen dieser vorhandenen Dual-Definition; **neue** Tabellen (falls das Familien-Design eine braucht) sind Postgres-only (K5) |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Admission-Prädikat „aktiver Record ∧ kein blockierender Freeze" an der AG3-142/149-Fence-Fläche (start/complete/fail/resume/closure + Executor-Commit), transaktional; takeover-admissibility am Confirm |
| `src/agentkit/backend/control_plane/ownership_transfer.py` (aus AG3-148) | ändern | Challenge-Invalidierung bei Freeze-Eintritt; Confirm scheitert bei nicht takeover-admissible Story |
| `src/agentkit/backend/story_split/service.py` | ändern | `_commit_fence`-Exklusivhaltung (:250-251) durch Admin-Freeze der Familie ersetzen; Saga-Schritte mit je eigenem Claim-Erwerb/-Freigabe (AG3-141); Reentranz-/Resume-Pfade (:232-240, :680) unverändert andocken |
| `src/agentkit/backend/governance/principal_capabilities/enforcement.py` | ändern | Enforcement konsultiert die Familie statt nur `conflict_freeze` (:424) — Guard-Seite bleibt konsistent zur Admission-Seite |
| `src/agentkit/backend/governance/integrity_gate/dimensions.py` | ändern (minimal) | Proof-Prüfung (:717) gegen das Familien-Vokabular robust halten (Bestandssemantik für `conflict_freeze` unverändert) |
| `tests/unit/**` | neu/ändern | Familien-/Epoch-/Blocker-Entscheidungslogik über Ports/Fakes; Split-Saga-Schritt-Claims |
| `tests/integration/**` | neu | Postgres: Admission-Blockade je Regime-Pfad bei aktivem Freeze; Challenge-Invalidierung bei Freeze-Eintritt; Split-Saga ohne gehaltene Claims (Concurrency-Beweis); Resume-Konvergenz |
| `tests/contract/**` | neu/ändern | Contract-Pins: Freeze-Record-Form (`freeze_epoch`/`freeze_reason`/Kind), Blocker-Fehlerbild, takeover-admissibility-Fehlerbild |

## Akzeptanzkriterien

1. **Freeze-Record-Form:** jeder Eintrag der Freeze-Familie trägt
   `freeze_epoch` (monoton steigend je Story), `freeze_reason`, Familien-Kind
   und Audit-Spur (contract-gepinnt); die Bestands-Semantik von
   `conflict_freeze` (set/read/clear/is_frozen, Proof-Prüfung) bleibt
   unverändert grün.
2. **Admission-Blocker an allen Regime-Pfaden:** bei aktivem blockierendem
   Freeze wird jede Regime-Mutation (start/complete/fail/resume/closure und
   der Executor-Commit) deterministisch abgewiesen, obwohl der
   Ownership-Record `active` ist — je Pfad ein Negativtest an der
   Phasengrenze, ohne State-Write; der Record bleibt nachweislich `active`
   (kein Statuswechsel durch Freeze).
3. **Auflösende Kommandos passieren:** die als auflösend registrierten
   Reconcile-/Repair-/Admin-Kommandos bleiben bei aktivem Freeze zulässig
   (Positivtest); jedes andere Kommando wird geblockt — es gibt keine
   implizite Ausnahmeliste (fail-closed, Code-Beweis: Registrierung statt
   Streuprüfungen).
4. **Challenge-Invalidierung:** ein offener Challenge + Freeze-Eintritt ⇒
   der Confirm scheitert deterministisch fail-closed (je Familien-Kind
   getestet); nach Auflösung des Freeze ist ein neuer Request nötig — der
   alte Challenge bleibt tot (Negativtest: kein Wiederaufleben).
5. **takeover-admissibility:** `confirm-run-ownership-takeover` scheitert,
   solange irgendein blockierender Freeze der Story aktiv ist; das
   Fehlerbild ist strukturiert (Regel-8-Vertrag) und contract-gepinnt.
6. **Kein Auto-Ablauf:** es existiert kein TTL-/Wanduhr-Codepfad für
   Freezes (Code-Beweis + Negativtest mit vorgerückter Uhr: Freeze bleibt
   aktiv).
7. **Split als Saga:** während einer laufenden Split-Saga besteht ein
   auditierter Admin-Freeze (Admission-Blocker auf der Quelle); die
   exklusive committed-op-Fence-Haltung über die Saga-Dauer ist ersetzt
   (Code-Beweis); jeder Saga-Schritt erwirbt seine Claims in globaler
   Ordnung und gibt sie je Schritt frei — zwischen zwei Schritten hält
   die Saga keinen Claim, eine unabhängige Story desselben Projekts
   bleibt währenddessen mutierbar (Concurrency-Integrationstest).
8. **Reentranz angedockt:** ein Resume nach Abbruch mitten in der Saga
   konvergiert ohne Doppelvollzug (keine doppelte Successor-Anlage, kein
   zweites Rebinding, kein zweiter Source-Cancel) — die bestehenden
   Konvergenz-Tests bleiben grün, ergänzt um den Fall „Abbruch zwischen
   zwei Sub-Commits mit aktivem Admin-Freeze".
9. **Fail-closed bei inkonsistentem Freeze-Zustand:** unbekanntes
   Familien-Kind, fehlender `freeze_reason` oder nicht lesbarer
   Freeze-Zustand blockiert die Admission (nie optimistisch passieren
   lassen).
10. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
    Familien-Kinds, Wire-Keys, Fehlercodes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-086, SOLL-087, SOLL-092, SOLL-093.

## Konzept-Referenzen

- FK-56 §56.13f (Freeze-Zustände sind story-scoped Admission-Blocker mit
  `freeze_epoch`/`freeze_reason`/Audit-Spur; Ownership-Record bleibt
  `active`; Mutation erfordert aktiven Record UND keinen Freeze —
  ausgenommen auflösende Reconcile-/Repair-/Admin-Kommandos; jeder
  Freeze-Eintritt invalidiert offene Challenges;
  `confirm-run-ownership-takeover` scheitert solange nicht
  takeover-admissible)
- `formal.operating-modes.invariants` →
  `freeze_states_are_admission_blockers_and_invalidate_challenges`
  (requires-Invariante des Confirm-Commands)
- FK-54 §54.8.2 (Fence-Schritt) + §54.8.2a (Admin-Freeze über die
  Saga-Dauer, nie auto-ablaufend, auditiert, Admission-Blocker gemäß
  FK-56 §56.13f; jeder Saga-Schritt kurz/bounded/gefenct mit eigenem
  Claim-Erwerb in globaler Ordnung; Saga hält keine Claims über die
  Laufzeit; Reentranz über `op_id`-Abstammung)
- FK-55 §55.8 (`conflict_freeze` als Vorbild der Entmündigungs-/
  Freeze-Mechanik; §55.8.1-Wirkung bleibt)
- FK-91 §91.1a Regeln 13/14 (Claim-Erwerb in globaler Ordnung, bounded
  Sub-Commits — Konsum der AG3-141-Fläche)

## Guardrail-Referenzen

- **FAIL-CLOSED:** ein Freeze blockiert zusätzlich zum Ownership-Regime;
  unbekannte/inkonsistente Freeze-Zustände blockieren; Challenges
  überleben keinen Freeze-Eintritt; kein Auto-Ablauf.
- **FIX THE MODEL, NOT THE SYMPTOM:** die Split-Exklusivhaltung wird durch
  das normierte Saga-Modell (Freeze + kurze gefencte Schritte) **ersetzt**;
  die Freeze-Familie generalisiert das vorhandene `conflict_freeze`-Modell
  statt einen parallelen Blocker-Mechanismus daneben zu stellen.
- **SINGLE SOURCE OF TRUTH:** genau eine Freeze-Familie mit einem
  Vokabular; Guard-Seite (Enforcement) und Admission-Seite entscheiden
  gegen dieselben Records.
- **NO ERROR BYPASSING:** es gibt keinen Freeze-Bypass für
  System-Principals; nur registrierte auflösende Kommandos passieren.
- **Testing-Guardrails:** Negativpfade an allen Regime-Phasengrenzen;
  Split-Saga-State über den echten Saga-Pfad erzeugt (Resume-Konvergenz),
  nicht manuell zusammengesetzt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** die additiven Spalten liegen auf der
  Bestands-Tabelle `governance_freeze_records`, die heute in beiden
  Backends definiert ist (`postgres_schema.sql:820`, `sqlite_store.py:826`,
  gated Test-Backend) — die Spalten folgen dieser vorhandenen
  Dual-Definition, damit die bestehenden gated Unit-Tests tragfähig
  bleiben; **neue** Tabellen des Familien-Designs (falls nötig) sind
  Postgres-only, fail-closed über das
  `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`). Die Admission-Prüfung selbst läuft
  auf der Postgres-Control-Plane; Contract-/Integrationstests über die
  Postgres-Fixture, Unit-Tests über Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Freeze-Familien-Modell,
  Admission-Prädikat, takeover-admissibility- und Invalidierungsregeln =
  **A**; Row↔Record-/Fehlerbild-Mapper = **R**; Persistenz-Row-Funktionen
  im `state_backend` = **AT/T** (dort lokalisiert). Der A-Kern bleibt
  AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert: reine Backend-/
  Governance-Mechanik; die Edge-seitige Sichtbarkeit der Zustände —
  `contested_local_writes` im Bundle — liegt in **AG3-151**).
