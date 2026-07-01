# AG3-135 — Phasen-Mutationen gegen Lease-Ablauf absichern (Fencing / Dispatch-Idempotenz)

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [] (härtet bereits gelandeten Code auf `main`)
- **Quell-Konzept:** FK-91 §91.1a (Phase-Mutation-Idempotenz/`op_id`), AG3-054
  (geleaster owner-scoped Claim), FK-10 §10.1.0 (kanonischer Zustand,
  fail-closed)
- **Herkunft:** Codex-Review AG3-130 Runde 3, Fund 1
  (`var/ag3-124-challenge/results/ag3-130-review3-codex.md`), vom Orchestrator
  am Code verifiziert.

## Kontext / Problem (verifiziert)

Phasen-Mutationen (`start_phase`, `resume_phase`, ebenso complete/fail/closure)
laufen über einen geleasten, owner-scoped Claim (AG3-054,
`src/agentkit/backend/control_plane/runtime.py`). Ablauf: **Claim gewinnen →
side-effecting Dispatch (`PipelineEngine`) → Ownership-CAS-Finalize**. Ein Claim,
der älter als die Lease-TTL ist, gilt als **abgestürzter Owner** und wird per
atomarem CAS von einem zweiten Aufrufer übernommen.

- `_CLAIM_LEASE_TTL = timedelta(minutes=5)` (`runtime.py:83`)
- „A `claimed` placeholder older than this is treated as a CRASHED owner and is
  reclaimable via an atomic CAS takeover" (`runtime.py:68-69`)

**Die Lücke — „ein Lease ist kein Fence":** Die TTL-Übernahme setzt voraus, dass
ein Owner jenseits 5 Minuten *abgestürzt* ist. Ist der Owner aber nur **langsam
und noch am Leben** (z. B. der Dispatch/`on_resume`/`on_setup` hängt >5 Min an
einem Drittsystem), passiert Folgendes:

1. **Doppel-Dispatch:** Owner B übernimmt den abgelaufenen Claim (gleiche
   `op_id`) und dispatcht denselben Vorgang ein zweites Mal, während A noch
   dispatcht → der side-effecting Engine-Schritt (z. B. `on_resume`,
   Start-Materialisierung) läuft zweimal.
2. **Zerrissener Zustand:** A hat den Engine-/Phasen-State bereits geschrieben,
   verliert aber danach die Finalize-CAS gegen B → A endet mit einer
   In-Flight-Rejection statt einem dauerhaften Op-Record. Ergebnis:
   PhaseState/AttemptRecord sind geschrieben, aber die Control-Plane-Idempotenz-/
   Audit-Spur (`op_id`) fehlt.

**Wahrscheinlichkeit/Severity:** niedrige Eintrittswahrscheinlichkeit (braucht
einen >5-Min-Hang **und** einen nebenläufigen Retry mit derselben `op_id`), aber
ein **echter Korrektheits-/Audit-Integritäts-Defekt**, wenn er eintritt. Da AK3
autonome, langlaufende Agent-Dispatches orchestriert, ist ein >5-Min-Dispatch
nicht exotisch. Fail-closed und ZERO DEBT verlangen, die Lücke zu schließen statt
sie als „passiert selten" zu akzeptieren.

**Kein AG3-130-Defekt:** der Mechanismus ist älter (AG3-054); AG3-130 hat den
Resume-Pfad nur auf denselben Claim wie `start_phase` gehoben (vorher lief Resume
ganz ohne Claim — AG3-130 war also eine Verbesserung). Die Härtung gehört
querschnittlich in den Claim-Mechanismus, nicht in eine einzelne Phase.

## Scope

### In Scope
1. **Fencing / Dispatch-Idempotenz:** Der side-effecting Dispatch darf nicht
   doppelt wirken, wenn ein abgelaufener Claim übernommen wird, während der
   Erst-Owner noch dispatcht. Umzusetzen über eine der folgenden (in Setup zu
   entscheidenden) Linien, konzepttreu:
   - Ein monoton steigendes **Fencing-Token** (Lease-Generation), das der
     Engine-/Store-Schreibpfad prüft, sodass ein Schreibversuch einer
     **älteren** Lease-Generation fail-closed abgewiesen wird (der langsame A
     kann nach B-Übernahme nichts mehr wirksam schreiben/finalizen — was
     Punkt 2 bereits teilweise über die Ownership-CAS tut, hier aber auf den
     **Dispatch-Effekt** ausgedehnt), und/oder
   - **Dispatch-Level-Idempotenz**: der Engine-Schritt selbst ist gegen
     Doppelausführung derselben `op_id`/Lease-Generation abgesichert (kein
     zweites `on_resume`/Start-Side-Effect).
2. **Zerrissenen-Zustand-Fenster schließen:** Sicherstellen, dass ein Vorgang,
   dessen Engine-State geschrieben wurde, nicht ohne dauerhaften Control-Plane-
   Op-Record enden kann (oder der Engine-State bei verlorener Finalize-CAS
   nicht als „committed" gilt). Die Reihenfolge Engine-Write ↔ Op-Record so
   ordnen/koppeln, dass keine Idempotenz-/Audit-Spur verloren geht.
3. **Gilt für alle Phasen-Mutationen:** `start_phase`, `resume_phase`,
   complete/fail, closure — einheitlich über den gemeinsamen Claim-Pfad.
4. **Konzept mitziehen, falls nötig (FIX THE MODEL):** wenn die Lease-/Fencing-
   Semantik präzisiert wird, FK-91 §91.1a bzw. AG3-054-Anker und die formalen
   Command-Contracts entsprechend nachziehen; Konzept-Gates grün.

### Out of Scope
- Latenz-/Performance-Optimierung des Claim-Pfads.
- Änderung der fachlichen Phasen-Semantik.
- Die TTL-Länge als solche „wegtunen" (eine längere TTL verschiebt das Fenster
  nur, schließt es nicht — die Härtung muss strukturell sein).

## Betroffene Dateien (Erwartung, in Setup zu verifizieren)
| Datei | Art |
|---|---|
| `src/agentkit/backend/control_plane/runtime.py` (Claim/Lease/Finalize/Dispatch) | ändern |
| `src/agentkit/backend/state_backend/**` (Claim-/Op-Store, CAS, ggf. Fencing-Spalte) | ändern |
| `concept/technical-design/91_api_event_katalog.md` + `concept/formal-spec/**` | ändern, falls Semantik präzisiert |
| `tests/**` (Nebenläufigkeits-/Lease-Ablauf-Tests) | neu |

## Akzeptanzkriterien
1. Ein **Lease-Ablauf-während-lebendigem-Dispatch**-Szenario ist reproduzierend
   getestet: Owner A dispatcht, Lease läuft ab, Owner B übernimmt mit gleicher
   `op_id` → der side-effecting Schritt wirkt **nicht** doppelt (kein zweites
   `on_resume`/Start-Side-Effect; genau ein terminaler Op-Record).
2. Das **Zerrissen-Zustand**-Szenario ist getestet: kein Fall, in dem Engine-/
   Phasen-State persistiert ist, aber der Control-Plane-Op-Record (`op_id`)
   dauerhaft fehlt.
3. Die Härtung gilt einheitlich für `start_phase` und `resume_phase` (Test je
   Pfad); complete/fail/closure sind über denselben Mechanismus abgedeckt.
4. Keine Aufweichung von fail-closed: ein nicht eindeutig zuordenbarer/verlorener
   Vorgang endet fail-closed, nie mit einem stillen Doppel-Effekt oder „leerem OK".
5. ARCH-55 (englische Bezeichner/Wire-Keys); keine unbegründeten
   `noqa`/`type: ignore`.
6. Quality-Gates grün: `pytest` (unit/integration/contract, `-n0`, Coverage
   ≥85 %), `mypy src` + `--platform linux` (strict), `ruff check src tests`,
   4 Konzept-Gates (`scripts/ci/*`), falls Konzepte angefasst wurden.

## Definition of Done
- AK 1–6 erfüllt; Codex-Review PASS; Konzept-Edits (falls normativ) dem PO
  vor Übernahme vorgelegt; auf `origin/main` gemerged; `status.yaml` →
  `completed`; README-Snapshot nachgezogen.

## Guardrail-Referenzen
- **FAIL-CLOSED / NO ERROR BYPASSING:** kein Doppel-Effekt, kein verlorener
  Op-Record, keine „passiert-selten"-Akzeptanz.
- **FIX THE MODEL, NOT THE SYMPTOM:** strukturelles Fencing/Idempotenz statt
  längerer TTL.
- **SINGLE SOURCE OF TRUTH:** Absicherung im gemeinsamen Claim-Pfad, nicht als
  Sonderkante je Phase.
