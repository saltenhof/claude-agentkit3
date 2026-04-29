---
concept_id: FK-38
title: Verify-Feedback und Dokumententreue-Schleife
module: verify-feedback
domain: verify-system
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: feedback-mechanism
  - scope: fidelity-impl
  - scope: fidelity-feedback
  - scope: remediation-loop
defers_to:
  - target: FK-27
    scope: layer-2-artifacts
    reason: Quelle der LLM-Review-Findings; gemeinsamer QA-Zyklus (FK-27 §27.5)
  - target: FK-29
    scope: closure-substates
    reason: Rückkopplungstreue Ebene 4 läuft im Closure-Ablauf nach Merge
  - target: FK-37
    scope: context-bundle
    reason: doc_fidelity-Kontextfelder werden vom Context Sufficiency Builder geladen
  - target: FK-32
    scope: doc-fidelity
    reason: Dokumententreue-Mechanik und Conformance-Service liegen bei FK-32
  - target: FK-34
    scope: structured-evaluator
    reason: Layer-2-Bewertung erfolgt über StructuredEvaluator (Remediation-Modus)
  - target: FK-26
    scope: remediation-worker
    reason: Konsumiert feedback.json als Remediation-Input
  - target: FK-20
    scope: feedback-loop
    reason: Engine-Feedback-Loop, Phase-Transition und max-Runden-Eskalation liegen in FK-20 §20.5
  - target: FK-39
    scope: feedback-rounds-counter
    reason: PhaseMemory.verify.feedback_rounds Carry-Forward-Logik in FK-39 §39.5
supersedes: []
superseded_by:
tags: [verify, feedback-loop, doc-fidelity, fidelity-impl, fidelity-feedback, remediation]
prose_anchor_policy: strict
formal_refs:
  - formal.verify.commands
  - formal.verify.events
  - formal.verify.invariants
---

# 38 — Verify-Feedback und Dokumententreue-Schleife

<!-- PROSE-FORMAL: formal.verify.commands, formal.verify.events, formal.verify.invariants -->

## 38.1 Feedback-Mechanismus

### 38.1.1 Mängelliste erzeugen

Bei Verify-FAIL wird aus den Ergebnissen aller Schichten eine
strukturierte Mängelliste erzeugt:

```python
def build_feedback(story_id: str) -> list[Finding]:
    findings = []

    # Schicht 1: Structural Failures
    # Fail-safe: structural.json kann fehlen wenn Verify in der Artefakt-Prüfung
    # gescheitert ist (bevor structural.json erzeugt wurde).
    structural = load_artifact(story_id, "structural")
    for check in (structural.checks if structural else []):
        if check.status == "FAIL":
            findings.append(Finding(
                source="structural",
                check_id=check.id,
                status="FAIL",
                detail=check.detail,
            ))

    # Schicht 2: LLM-Review Failures (inkl. Umsetzungstreue)
for artifact_id in ("qa_review", "semantic_review", "doc_fidelity"):
        review = load_artifact(story_id, artifact_id)
        if review:
            for check in review.checks:
                if check.status == "FAIL":
                    findings.append(Finding(
                        source=artifact_id,
                        check_id=check.check_id,
                        status="FAIL",
                        reason=check.reason,
                        description=check.description,
                    ))

    # Schicht 3: Adversarial Findings
    adversarial = load_artifact(story_id, "adversarial")
    if adversarial:
        for finding in adversarial.findings:
            findings.append(Finding(source="adversarial", **finding))

    return findings
```

### 38.1.2 Feedback-Datei

`_temp/qa/{story_id}/feedback.json`:

```json
{
  "story_id": "ODIN-042",
  "run_id": "...",
  "feedback_round": 1,
  "findings": [
    {
      "source": "structural",
      "check_id": "build.test_execution",
      "status": "FAIL",
      "detail": "3 Tests failed"
    },
    {
"source": "qa_review",
      "check_id": "error_handling",
      "status": "FAIL",
      "reason": "Timeout wird verschluckt",
      "description": "BrokerClient.send() fängt TimeoutException..."
    }
  ]
}
```

Der Remediation-Worker (FK-26 §26.2.3) erhält diese Datei als Input.

### 38.1.3 Remediation-Loop und Max-Rounds-Eskalation

> **[Entscheidung 2026-04-09]** `feedback_rounds` wird nicht mehr im Verify-Handler inkrementiert. In v3 verwaltet die Engine `phase_memory.verify.feedback_rounds` als Carry-Forward-Akkumulator: Inkrementierung erfolgt beim Phasenwechsel verify→implementation (Remediation-Pfad), VOR Erzeugung des neuen Implementation-States. Der Verify-Handler selbst liest `verify_context: VerifyContext` aus dem VerifyPayload, schreibt aber keine Zähler. Siehe FK-39 §39.5.

Der Verify-Remediation-Zyklus ist auf eine konfigurierbare Anzahl
von Runden begrenzt:

- `max_feedback_rounds` in der Pipeline-Config (Default: 3)
- `feedback_rounds` liegt in `PhaseMemory.verify.feedback_rounds`
  (carry-forward über Phase-Transitionen) und wird ausschließlich
  von der **Engine (Phase Runner)** inkrementiert — beim
  Phase-Übergang `verify → implementation` (Remediation), NACH dem
  Guard-Check und VOR der Transition. [Entscheidung 2026-04-09]
- Bei jedem Verify-FAIL mit verbleibenden Runden:
  `_handle_verify_failure` inkrementiert `feedback_rounds` NICHT
  selbst — er liefert nur das FAILED-Ergebnis zurück, setzt
  `qa_cycle_status = "awaiting_remediation"` und assembliert den
  Remediation-Worker-Spawn-Contract mit der `feedback.json`-Mängelliste.
  Die eigentliche Inkrementierung erfolgt durch die Engine beim
  Phase-Übergang. [Entscheidung 2026-04-09]
- Wenn `feedback_rounds >= max_feedback_rounds` (nach Inkrementierung
  durch die Engine): Status wird `ESCALATED`,
  `qa_cycle_status` wird `"escalated"`. Die Story ist permanent
  blockiert bis ein Mensch interveniert.
- Menschliche Intervention: `agentkit reset-escalation` CLI-Kommando
  setzt `feedback_rounds` zurück und erlaubt erneute Bearbeitung.
- Wenn Verify nach Remediation erneut betreten wird (Status
  `awaiting_remediation`): `advance_qa_cycle()` feuert und
  invalidiert alle zyklusgebundenen Artefakte (siehe FK-27 §27.2).
  Danach laufen alle vier Verify-Schichten vollständig von vorne.

### 38.1.4 Mandatory-Target-Rueckkopplung im Remediation-Loop (FK-27-220)

Wenn ein mandatory adversarial target (FK-34, abgeleitet aus
Layer-2-Findings vom Typ `assertion_weakness`) nicht erfuellt wird,
fliesst das deterministisch in die naechste Remediation-Runde:

- Das nicht erfuellte Target wird dem Remediation-Worker als
  zusaetzlicher Maengelpunkt in der `feedback.json` uebergeben
- Die Rueckkopplung nutzt den bestehenden Loop (max 3 Runden),
  keinen neuen Mechanismus
- Ein mandatory target gilt als nicht erfuellt, wenn der
  Adversarial Agent weder einen deckenden Test geschrieben noch
  explizit `UNRESOLVABLE: Grund` gemeldet hat
- Das zugehoerige Layer-2-Finding wird in diesem Fall mindestens
  als `partially_resolved` bewertet (DK-04 §4.6.3)

**Ablauf:**

```python
def build_feedback(story_id: str) -> list[Finding]:
    findings = []
    # ... bestehende Finding-Sammlung aus Schicht 1-3 ...

    # Mandatory-Target-Rueckkopplung (ab Runde 2)
    adversarial = load_artifact(story_id, "adversarial")
    if adversarial:
        for target in adversarial.get("mandatory_target_results", []):
            if target["status"] not in ("TESTED", "UNRESOLVABLE"):
                findings.append(Finding(
                    source="adversarial_mandatory_target",
                    check_id=target["target_id"],
                    status="FAIL",
                    detail=(
                        f"Mandatory adversarial target nicht erfuellt: "
                        f"{target['target_id']}"
                    ),
                ))

    return findings
```

**Provenienz:** DK-04 §4.6.3 (Mandatory Adversarial Targets).
Empirischer Beleg BB2-012: Der Wrong-Phase-Fall war im P3-Review
konkret benannt, wurde aber vom Adversarial Agent nicht eigenstaendig
gefunden.

## 38.2 Dokumententreue Ebene 3: Umsetzungstreue

### 38.2.1 Integration in Verify

Die Umsetzungstreue (FK-06-058) läuft als Teil der Schicht 2, über
den StructuredEvaluator:

Adapter-Vertrag (Bundle → doc_fidelity context):

| doc_fidelity context-Feld | Quelle im Bundle / Artefakt |
|--------------------------|----------------------------|
| `diff` | `bundle.diff_summary` (aus `context_dict["diff_summary"]`) |
| `entwurfsartefakt_or_concept` | `bundle.concept_excerpt` (aus `context_dict["concept_excerpt"]`) |
| `handover` | `bundle.handover` (aus `context_dict["handover"]`) |
| `drift_log` | `handover.drift_log` — aus `handover.json` geladen (FK-37 §37.2.2 `_load_handover()`) |

```python
evaluator.evaluate(
    role="doc_fidelity",
    prompt_template=Path("prompts/doc-fidelity-impl.md"),
    context={
        "diff": context_dict.get("diff_summary", ""),
        "entwurfsartefakt_or_concept": context_dict.get("concept_excerpt", ""),
        "handover": context_dict.get("handover", ""),
        "drift_log": handover_data.get("drift_log", "") if handover_data else "",
    },
    expected_checks=["impl_fidelity"],
    story_id=story_id,
    run_id=run_id,
)
```

**Frage:** Hat der Worker gebaut, was konzeptionell vorgesehen war?
Gibt es undokumentierten Drift?

**Bei FAIL:** Story geht in den Feedback-Loop (via S2G → FAIL → §38.1).
[Korrektur 2026-04-09: Impact-Violation wird ausschließlich durch den
deterministischen Layer-1-Check `impact.violation` (FK-27 §27.4.2) erkannt und
direkt zu ESCALATED eskaliert. Ein Layer-2-Doc-Fidelity-Befund führt
immer in den Feedback-Loop — es gibt keinen LLM-basierten Pfad zu ESCALATED.]

## 38.3 Dokumententreue Ebene 4: Rückkopplungstreue

### 38.3.1 Prüfung (FK-06-059)

Nach dem Merge (bzw. nach `merge_done = true` für Concept/Research,
FK-29 §29.1.1), vor Postflight. Prüft ob bestehende Dokumentation
aktualisiert werden muss:

```python
evaluator.evaluate(
    role="doc_fidelity",
    prompt_template=Path("prompts/doc-fidelity-feedback.md"),
    context={
        "final_diff": git_diff_main,
        "existing_docs": projektdokumentation_index,
    },
    expected_checks=["feedback_fidelity"],
    story_id=story_id,
    run_id=run_id,
)
```

**Frage:** Müssen bestehende Dokumente aktualisiert werden, damit
künftige Dokumententreue-Prüfungen gegen eine korrekte Wahrheit
laufen? (FK-06-063)

**Prompt-Größenkontrolle:** Der `final_diff` kann bei umfangreichen
Stories mehrere hundert Kilobyte umfassen. Die 3-Tier-Strategie
(FK-32 §32.4b) greift: Inline bei kleinen Diffs, Datei-Upload via
`merge_paths` bei mittleren, Blockade bei übergroßen Payloads.
Kein Trunkieren.

**Bei FAIL:** Warnung, keine Blockade. Die Story ist bereits gemergt.
Ein FAIL erzeugt einen Incident-Kandidaten für den Failure Corpus
und eine Empfehlung an den Menschen, welche Dokumente aktualisiert
werden sollten.
