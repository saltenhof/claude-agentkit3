# Review 10 (Codex, job-4f2b0fdc) — Abnahme Haertungsrunde 4

## Findings

1. **P0 – R9-1 weiterhin nicht vollstaendig geschlossen.**
   Write und Takeover verwenden unterschiedliche Intents: `RUN.mutex.write`
   versus `RUN.mutex.takeover`. Dadurch kann Takeover zwischen
   Ownership-Pruefung und `_refresh_heartbeat` laufen; `_refresh_heartbeat`
   liest dann den neuen Mutex, prueft dessen Nonce nicht erneut und
   ueberschreibt ihn mit der alten Nonce. Zudem loescht der alte Writer sein
   Write-Intent im `finally` ohne Intent-Identitaet und koennte ein
   inzwischen neu beanspruchtes Intent entfernen. Der neue Test deckt dieses
   konkrete Interleaving nicht ab.

   **Empfehlung:** ein gemeinsames CAS-/Coordination-Intent fuer saemtliche
   Mutex-Aenderungen und Wirkungen; Intent selbst mit Nonce versehen und nur
   per Nonce-Match freigeben. Testbarriere zwischen `_mutex_still_ours` und
   `_refresh_heartbeat` sowie waehrend eines neu beanspruchten Intents
   ergaenzen.

2. **P1 – R9-3 fast, aber nicht vollstaendig geschlossen.**
   Feldkatalog, Digest und getrennte Fristen stimmen jetzt ueberein. Beide
   Zeitpruefungen akzeptieren jedoch beliebig weit zukuenftige
   `acquired_at`-/`verified_at`-Werte, weil nur "noch nicht abgelaufen"
   geprueft wird.

   **Empfehlung:** `acquired_at <= verified_at <= now + clock_skew` sowie
   `verified_at <= acquired_at + ttl_seconds` erzwingen; Zukunfts-Tests
   ergaenzen.

## Aufloesungsstand

- R9-1: **nicht geschlossen**
- R9-2: **geschlossen** (zweistufiger Intake-Freeze mit Praefixbeweis ist
  tragfaehig)
- R9-3: **teilweise**
- R9-4: **geschlossen** (Consumer-Semantik sauber normiert)
- R9-5: **geschlossen**

Die dokumentierte VCS-Vertrauensgrenze ist akzeptabel.

## Verdict

| target | verdict | Begruendung |
|---|---|---|
| `concept_toolchain/` | `disagrees` | Der verbliebene Mutex-Interleaving-Pfad verletzt weiterhin die zugesicherte Single-Writer-Garantie; Remote-Zeitordnung ist zusaetzlich fail-open. |

Der ehrliche `blocked_projection`-/Exit-2-Stand bleibt richtig. In den
PO-Abschlussbericht gehoeren ausdruecklich: Projection-Audit-Lauf,
VCS-Vertrauensgrenze der Intake-Pins, das minimale `os.replace`-Restfenster,
SSOT-Wrapper-Migration und Compiler-Folgearbeit.

**Gesamturteil: Rework.** Der Remote-Zeitpunkt ist ueberschaubar; der
verbleibende Mutex-Gegenbeweis blockiert die Freigabe.
