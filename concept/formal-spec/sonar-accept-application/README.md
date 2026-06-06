---
title: Sonar Accept Application Formal Spec
status: active
doc_kind: context
---

# Sonar Accept Application

Dieser Kontext formalisiert den synchronen, worker-initiierten
Accept-Self-Assessment-Schritt fuer die bewusste Einzelfall-Akzeptanz einer
SonarQube-Regel (World 2 des Zwei-Welten-Modells). Konzeptionell gehoert der
Kontext zur Capability `VerifySystem`; die Prosa-SSOT des Verfahrens ist
FK-27 §27.6b.

## Scope

Im Scope sind:

- der Antrags-Lebenszyklus `requested → pending → accepted | rejected`
- Kommandos `apply` / `approve` / `reject`
- die Einstimmigkeitsregel (Worker + zwei unterschiedliche Modelle, ein
  gemeinsamer zielorientierter Prompt)
- dass ausschliesslich AK3 `Accepted` setzt (Worker ohne Admin-Rechte)
- sofortiges Feedback an den Worker bei mindestens einem `no`
- das leichte Failure-Corpus-Frequenz-Signal

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die Gate-Semantik „Accepted zaehlt gruen", der Reconciler-Vertrag und das
  Ledger-Schema (Owner: FK-33 §33.6.4, `formal.deterministic-checks.*`)
- der Default-Schwellwert des Frequenz-Signals (Owner: FK-03)
- der Haupt-QA-Pass (Reviewer/Adversarial) des verify-system

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Antrag, LLM-Votum, Ledger-Eintrag (referenziert) |
| `commands.md` | `apply` / `approve` / `reject` |
| `events.md` | `application-requested` / `accepted` / `rejected` |
| `state-machine.md` | `requested → pending → accepted \| rejected` |
| `invariants.md` | Einstimmigkeit, zwei Modelle, nur AK3 setzt Accepted, sofortiges Feedback |
| `scenarios.md` | beide yes → accepted; mindestens ein no → rejected |

## Prosa-Quellen

- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
- [FK-41](/T:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md)
