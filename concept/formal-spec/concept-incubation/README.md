---
title: Concept Incubation Formal Spec
status: active
doc_kind: context
---

# Concept Incubation

Dieser Kontext formalisiert den Concept-Incubator (BC concept-incubation):
den administrativen Lauf-Lifecycle, die Gremien-Mechanik (Runden,
Round-Seal), die verlustfreie Promotionskette (Source-Units → Claims →
Dispositionen → Atome → Receipts) und die Locking-/Schreibdisziplin
(Lease, CAS, Scope-Locks).

Der Inkubator ist KEINE Pipeline-Phase und kein Story-Traeger: er
operiert corpus-weit und vor-storylich auf der normativen Konzeptwelt.
Statussemantik der korpusweiten Achsen (`assertion_status`,
`equivalence_status`) liegt bei `concept/_meta/assertion-authority.md`;
dieser Kontext formalisiert die lauf-lokale Achse (`run_status`) und die
Closure-Invarianten.

## Scope

- Zustaende und Uebergaenge eines IncubationRun inkl. BLOCKED/RECHECK/
  PROMOTION_FAILED/ABORTED und Wiederaufnahme
- Offizielle Commands des Council-Orchestrators
- Events der Lauf-Chronik
- Invarianten fuer Rollen-/Schreibgrenzen, Freezes, Closures, Receipts,
  Locks und Datenklassen
- Deklarierte Szenario-Traces (Happy Path, Ausfall, Drift, Gate-Rot,
  Abbruch, Takeover)

## Out of Scope

- Story-Pipeline, Phasen und Verify-Capability
- Skill-Bundle-Mechanik (formal.skills-and-bundles)
- Guard-Enforcement-Mechanik (governance-and-guards)
- Die Statussemantik-PROSA des Assertion-Vertrags (die maschinenpruefbare
  Ableitung selbst ist hier als Invarianten projection_lifecycle_first
  und projection_status_derivation formalisiert)

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Kernentitaeten des Laufs und der Promotionskette |
| `state-machine.md` | run_status-Lifecycle |
| `commands.md` | Offizielle Lauf-Commands |
| `events.md` | Lauf-Events |
| `invariants.md` | Harte Regeln (Rollen, Freezes, Closures, Locks) |
| `scenarios.md` | Deklarierte Traces |

## Prosa-Quellen

- [FK-78](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md)
- [DK-16](/T:/codebase/claude-agentkit3/concept/domain-design/16-konzeption-und-konzeptinkubation.md)
