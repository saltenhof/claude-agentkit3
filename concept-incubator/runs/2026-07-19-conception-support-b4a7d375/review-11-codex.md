# Review 11 (Codex, job-8fce8e42) — Schlussverdict Toolchain

## Findings

1. **P0 – R10-1 noch nicht vollstaendig geschlossen.**
   Das gemeinsame Intent ist richtig. Seine automatische
   Stale-Bereinigung bleibt jedoch Read-then-Unlink: Zwei Reclaimer
   koennen dieselbe alte Nonce lesen; Reclaimer A loescht und erstellt
   ein neues Intent, danach loescht Reclaimer B dieses neue Intent auf
   Basis seiner zuvor gelesenen Identitaet. A laeuft dann ohne sein
   Intent weiter. Dasselbe TOCTOU besteht in `_release_intent`.

   **Fuer den Abschlussbericht:** automatische Stale-Reclamation ist
   nicht atomar. Robust waere ein OS-advisory Lock oder fail-closed
   manuelle Recovery; alternativ ein nachweislich atomarer
   CAS-Mechanismus.

2. **P1 – normativer Nachlauf.**
   FK-78 beschreibt zunaechst korrekt das einzige `RUN.mutex.intent`,
   enthaelt unmittelbar danach aber noch den entfernten Pfad
   `RUN.mutex.takeover` (§78.4). Redaktioneller Normwiderspruch.

R10-2 ist materiell geschlossen: Zeitordnung, Skew-Grenze,
Lock-Lebendigkeit und Evidenzalterung sind fail-closed umgesetzt.

| target | verdict |
|---|---|
| `concept_toolchain/` | `disagrees` |

Verdict wegen des verbleibenden Stale-Intent-Rennens nicht auf
`equivalent` gedreht.

**Gesamturteil: Rework.** Fuer die PO-Abgabe offen benennen:
Mutex-Stale-Reclamation, veralteter FK-78-Absatz, Bootstrap-Exit-2 und
der erforderliche Projection-Audit-Lauf.

---

## Nachtrag des Council-Orchestrators (2026-07-20)

Finding 2 ist behoben: FK-78 §78.4 nennt keinen `RUN.mutex.takeover`-Pfad
mehr; der Takeover laeuft dort jetzt ausdruecklich unter demselben
Coordination-Intent.

Finding 1 wird als **benannte Grenze** in FK-78 §78.4 normiert
(Read-then-Unlink der Stale-Bereinigung, Beschraenkung auf den Fall
"verwaistes Intent trifft zwei gleichzeitige Aufraeumer", empfohlene
Aufloesung ueber OS-Advisory-Lock oder fail-closed manuelle Recovery).
Es bleibt als Restpunkt im Abschlussbericht und in CLOSURE.md §6
sichtbar — bewusst nicht stillgelegt.
