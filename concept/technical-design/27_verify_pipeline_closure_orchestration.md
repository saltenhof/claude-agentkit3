---
concept_id: FK-27
title: Verify-Pipeline und Closure-Orchestration
module: verify-closure
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: verify-closure
  - scope: qa-cycle
  - scope: adversarial-orchestration
  - scope: policy-evaluation
  - scope: closure-sequence
defers_to:
  - target: FK-26
    scope: handover-paket
    reason: Verify konsumiert Handover-Paket und Worker-Manifest aus FK-26
  - target: FK-20
    scope: feedback-loop
    reason: Feedback-Loop-Mechanismus in FK-20.5 definiert
  - target: FK-23
    scope: impact-violation
    reason: Impact-Violation-Check und Modus-abhaengige Reaktion in Kap. 23.8
  - target: FK-33
    scope: deterministic-checks
    reason: Deterministische Structural Checks in Kap. 33
  - target: FK-34
    scope: llm-evaluations
    reason: StructuredEvaluator und LLM-Bewertungen in Kap. 34
  - target: FK-11
    scope: structured-evaluator
    reason: StructuredEvaluator-Architektur in Kap. 11
supersedes: []
superseded_by:
tags: [verify, closure, qa-cycle, adversarial-testing, policy-evaluation]
---

# 27 — Verify-Pipeline und Closure-Orchestration

## 27.1 Zweck

Die Verify-Phase ist die maschinelle Qualitätssicherung. Sie prüft
die Implementierung in vier aufeinander aufbauenden Schichten.

Dateisystem-Zugriff nach Layer:
- **Schicht 1 (Skripte)**: Lese-Zugriff — Artefakt-Existenzprüfung, Build-Ergebnisse, JSON-Validierung (FK-05-128 bis FK-05-130).
- **Schicht 2 Pre-Step (ContextSufficiencyBuilder)**: Lese-Zugriff — lädt Kontext-Artefakte aus dem Story-Verzeichnis (§27.5a).
- **Schicht 2 LLM-Bewertungen**: Kein direkter Dateisystem-Zugriff — die LLM-Evaluatoren erhalten gebundelte Kontext-Daten vom ContextSufficiencyBuilder; kein eigenes Dateisystem-Lesen.
- **Schicht 3 (Adversarial Agent)**: Lese-Zugriff auf alles + Schreib-Zugriff auf Sandbox-Pfad (`_temp/adversarial/{story_id}/`).

Die Closure-Phase schließt die Story ab: Integrity-Gate, Merge,
Issue-Close, Metriken, Postflight. Ihre Schritte sind sequentielle
Seiteneffekte über verschiedene Systeme und werden über persistierte
Substates abgesichert (Kap. 10.5.3).

## 27.2 Atomarer QA-Zyklus

### 27.2.1 Identitätsfelder

Jede Verify-Remediation-Iteration bildet einen atomaren QA-Zyklus
mit drei Identitätsfeldern:

| Feld | Typ | Semantik |
|------|-----|----------|
| `qa_cycle_id` | 12-Zeichen UUID-Fragment | Eindeutig pro Zyklus, wird bei jedem `advance_qa_cycle()` neu generiert |
| `qa_cycle_round` | Monotoner Zähler (ab 1) | Inkrementiert bei jedem neuen Zyklus |
| `evidence_epoch` | ISO-8601 Timestamp | Zeitpunkt der letzten Code-/Artefakt-Mutation |
| `evidence_fingerprint` | SHA256-Hash (Hex-String) | SHA256 der relevanten Artefakte — inhaltliche Integritätsprüfung (Entscheidung 2026-04-08, Element 19); separates Feld, `evidence_epoch` bleibt Timestamp |

> **[Entscheidung 2026-04-08]** Element 19 — Evidence-Fingerprint wird verbessert: SHA256-Hash statt Dateigroessen. Eingeführt wird ein separates Feld `evidence_fingerprint` (SHA256-Hash der relevanten Artefakte) für die Inhaltsprüfung; `evidence_epoch` bleibt ein ISO-8601-Timestamp (Zeitpunkt der letzten Mutation) und ändert seinen Typ nicht.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 19.

Die QA-Zyklus-Felder werden im Story-State persistiert und in
alle QA-Artefakte geschrieben (Traceability).

### 27.2.2 State Machine

```
idle → awaiting_qa → awaiting_policy → pass
                  ↓
           awaiting_remediation → (nächster Zyklus)
                  ↓
              escalated  (direkter Pfad: impact.violation oder max_rounds)
```

- `idle`: Kein aktiver QA-Zyklus
- `awaiting_qa`: Verify-Schichten laufen (Schicht 1–3)
- `awaiting_policy`: Policy-Evaluation (Schicht 4) ausstehend
- `pass`: Policy-Evaluation bestanden → Verify COMPLETED (kein Umweg über `awaiting_remediation`)
- `awaiting_remediation`: Verify gescheitert, Worker-Remediation erwartet
- `escalated`: Direkter Übergang aus `awaiting_qa` bei `impact.violation` (vor Policy-Evaluation); oder aus `awaiting_remediation` bei `max_rounds_exceeded`

### 27.2.3 Artefakt-Invalidierung

**Zweck:** Verhindert, dass veraltete Artefakte aus einer früheren
Verify-Runde nach einer Remediation in späteren Runden konsumiert
werden.

Wenn ein neuer Zyklus beginnt (`advance_qa_cycle()`), werden alle
zyklusgebundenen Artefaktdateien gelöscht oder nach `stale/`
verschoben (11 Dateien): [Korrektur 2026-04-09: 11→10 — `qa_review.json` war kein eigenständiges Artefakt, sondern identisch mit `llm-review.json`; `semantic.json`→`semantic-review.json` (§27.5.5)] [Ergänzung 2026-04-09: 10→11 — doc-fidelity.json als drittes Layer-2-Artefakt ergänzt (§27.5.5).]

| Artefakt | Datei |
|----------|-------|
| Semantic Review | `semantic-review.json` |
| Guardrail Check | `guardrail.json` | <!-- [Hinweis 2026-04-09] Kein aktiver Producer in §27.5 definiert — in früherer Layer-2-Architektur war ein separater Guardrail-Evaluator vorgesehen. Artefakt verbleibt in der Invalidierungs-Liste für den Fall, dass es aus einem früheren Zyklus noch existiert. -->
| Policy Decision | `decision.json` |
| LLM Review (QA-Bewertung) | `llm-review.json` | <!-- [Korrektur 2026-04-09] Separaten `qa_review.json`-Eintrag entfernt — QA-Bewertung (Rolle `qa_review`) wird in `llm-review.json` geschrieben (§27.5.5). -->
| Umsetzungstreue | `doc-fidelity.json` |
| Feedback | `feedback.json` |
| Adversarial | `adversarial.json` |
| E2E Verify | `e2e_verify.json` | <!-- [Hinweis 2026-04-09] Kein aktiver Producer in §27.5 definiert — reserviert für eine zukünftige End-to-End-Integritätsprüfung. Artefakt verbleibt in der Invalidierungs-Liste für den Fall, dass es aus einem früheren Zyklus noch existiert. -->
| Structural | `structural.json` |
| Context | `context.json` | <!-- [Hinweis 2026-04-09] context.json ist keine Löschung — es wird vor Schicht 2 vom Phase Runner neu aufgebaut (rebuild pre-step), um dem Context Sufficiency Builder (§27.5a.6) ein aktuelles Artefakt zu liefern. Ohne diesen Rebuild wäre der Remediation-Re-Entry-Pfad nicht implementierbar. Der Eintrag in der Invalidierungs-Liste bedeutet: altes context.json wird nach stale/ verschoben, dann neu erzeugt. -->
| Context Sufficiency | `context_sufficiency.json` |

### 27.2.4 Runtime-Staleness-Check

`artifact_matches_current_cycle()` prüft bei jedem Artefakt-Zugriff,
ob das eingebettete `qa_cycle_id` mit dem aktuellen Zyklus
übereinstimmt. Bei Mismatch: **fail-closed** — das Artefakt wird
abgelehnt, als wäre es nicht vorhanden.

### 27.2.5 FK-Referenz

Domänenkonzept 5.2 "Atomarer QA-Zyklus".

## 27.3 Verify-Phase: Gesamtablauf

```mermaid
flowchart TD
    START(["agentkit run-phase verify<br/>--story ODIN-042"]) --> S1

    subgraph SCHICHT_1 ["Schicht 1: Deterministische Checks (Skripte, kein LLM)"]
        S1["Artefakt-Prüfung:<br/>Protocol, Manifest,<br/>deklarierte Dateien"]
        S1 -->|PASS| S1P{Parallel}
        S1 -->|FAIL| FB
        S1P --> STRUCT["Structural Checks"]
        S1P --> RECUR["Recurring Guards<br/>(Telemetrie-basiert)"]
        S1P --> ARE_G["ARE-Gate<br/>(wenn aktiviert)"]
        S1P --> IMPACT["Impact-Violation-<br/>Check"]
        STRUCT --> S1G{Gate}
        RECUR --> S1G
        ARE_G --> S1G
        IMPACT -->|PASS| S1G
        IMPACT -->|FAIL| ESC_IV(["ESCALATED:<br/>Impact-Violation"])
    end

    S1G -->|"Ein BLOCKING-FAIL"| FB["Feedback:<br/>Mängelliste"]
    S1G -->|"Kein BLOCKING-FAIL"| S2

    subgraph SCHICHT_2 ["Schicht 2: LLM-Bewertungen (Skript, kein Dateisystem)"]
        S2{Parallel}
        S2 --> QA["QA-Bewertung<br/>(12 Checks, LLM A)<br/>StructuredEvaluator"]
        S2 --> SEM["Semantic Review<br/>(LLM B)<br/>StructuredEvaluator"]
        S2 --> UMSTR["Umsetzungstreue<br/>(Dokumententreue Ebene 3)<br/>StructuredEvaluator"]
        QA --> S2G{Gate}
        SEM --> S2G
        UMSTR --> S2G
    end

    S2G -->|"Ein FAIL"| FB
    S2G -->|"Kein FAIL"| S3

    subgraph SCHICHT_3 ["Schicht 3: Adversarial Testing (Agent, mit Dateisystem)"]
        S3["Adversarial Agent<br/>spawnen"]
        S3 --> S3_OWN["Agent entwickelt<br/>eigenständig Edge Cases"]
        S3_OWN --> S3_TEST1["Tests schreiben +<br/>ausführen (Sandbox)"]
        S3_TEST1 --> S3_SPAR["Sparring mit LLM C:<br/>Was habe ich übersehen?"]
        S3_SPAR --> S3_TEST2["Sparring-Ideen als<br/>weitere Tests umsetzen"]
        S3_TEST2 --> S3_RESULT{"Befunde?"}
    end

    S3_RESULT -->|"Fehler gefunden"| FB
    S3_RESULT -->|"Keine Befunde"| S4

    subgraph SCHICHT_4 ["Schicht 4: Policy-Evaluation (Skript)"]
        S4["Ergebnisse aller<br/>Schichten aggregieren"]
        S4 --> S4_EVAL["Stage-Registry<br/>auswerten:<br/>Blocking-Stages PASS?"]
    end

    S4_EVAL -->|FAIL| FB
    S4_EVAL -->|PASS| DONE(["Verify COMPLETED"])

    FB --> WORKER["→ Zurück zu Implementation<br/>(Feedback-Loop, Kap. 20.5)"]
```

[Hinweis: Für concept/research-Stories: `integrity_passed` und `merge_done` werden direkt auf `true` gesetzt (kein Worktree, kein Branch-Merge). Finding-Resolution-Gate und Integrity-Gate entfallen vollständig. Der Closure-Ablauf geht direkt von `issue_closed` weiter (§27.10a.1).]

[Hinweis: Das Flowchart zeigt den **logischen** Ablauf. Schicht 3 (Adversarial) ist kein synchroner Inline-Schritt — der Phase Runner setzt `agents_to_spawn` und der Orchestrator spawnt den Adversarial-Agenten extern (§27.6.1). Der Gesamtfluss (S2G → Schicht 3 → S4) beschreibt die fachliche Reihenfolge, nicht den mechanischen Ablauf.]

## 27.3a Verify-Kontext: QA-Tiefe über `verify_context` (FK-27-250)

> **[Entscheidung 2026-04-09]** `verify_context` wird als typisiertes `VerifyContext`-Feld auf `VerifyPayload` (diskriminierte Union, §20.3) geführt statt als freier String auf dem flachen PhaseState. `VerifyContext` ist ein StrEnum: `POST_IMPLEMENTATION | POST_REMEDIATION`. Steuert die QA-Tiefe normativ. Verweis auf Designwizard R1+R2 vom 2026-04-09.

### 27.3a.0 VerifyPayload — durable Contract Fields

`VerifyPayload` ist die phasenspezifische Payload für den Verify-Eintritt (diskriminierte Union, §20.3):

```python
class VerifyContext(StrEnum):
    POST_IMPLEMENTATION = "post_implementation"
    POST_REMEDIATION = "post_remediation"

class VerifyPayload(BaseModel):
    phase_type: Literal["verify"]
    verify_context: VerifyContext | None = None
```

`verify_context` hat Transition-Relevanz: Der Phase Runner wertet es aus, um die QA-Tiefe zu bestimmen. Es wird beim Verify-Eintritt vom Phase Runner gesetzt, basierend auf der letzten abgeschlossenen Phase. **`None` ist fail-closed**: wenn `verify_context` beim Verify-Eintritt `None` ist, eskaliert der Phase Runner sofort (ESCALATED) — kein Verify-Lauf ohne bekannten Kontext.

| Letzter abgeschlossener Schritt | `verify_context` |
|---------------------------------|-----------------|
| Implementation-Phase abgeschlossen | `post_implementation` |
| Remediation abgeschlossen (Verify-Failure-Loop) | `post_remediation` |

[Korrektur 2026-04-09: "Exploration-Phase abgeschlossen" als Trigger entfernt — Verify wird nie direkt nach Exploration aufgerufen (§27.3a.1, §27.10.1).]

**Nicht in VerifyPayload:** `feedback_rounds` — dieser Zähler lebt in `PhaseMemory.verify.feedback_rounds` (§20.3.7, carry-forward über Phasenwechsel).

### 27.3a.1 Problem: `mode` ist kein hinreichender Diskriminator

Das Feld `mode` wird in der Setup-Phase gesetzt und bleibt über den
gesamten Story-Lifecycle konstant. Verify läuft ausschließlich nach
der Implementation-Phase (volle 4-Schichten-QA) oder nach einer
Remediation-Runde (erneut volle 4-Schichten-QA). Wenn die Pipeline
nur `mode` auswertet, werden Layer 2–4 für ALLE Verify-Durchläufe
übersprungen — ein kritischer Governance-Fehler.
[Korrektur 2026-04-09: post_exploration entfernt — Dokumententreue-Prüfung
nach Exploration ist Teil der Exploration-Phase selbst (§23.5), nicht via Verify.]

**Empirischer Anlass (BB2-057):** Eine Implementation-Story im
Exploration Mode wurde nach der Implementation ohne ein einziges
LLM-Review durchgewunken. Ursache: Der Phase Runner verwendete
`mode == "exploration"` als Trigger für den Structural-Only-Pfad —
unabhängig davon, welche Phase gerade verifiziert wurde. Der
Orchestrator handelte korrekt nach Phase-State-Vertrag: COMPLETED +
leere `agents_to_spawn` → Closure. Der Bug lag zu 100% im
deterministischen Code (Phase Runner), nicht im nicht-deterministischen
Orchestrator.

### 27.3a.2 Lösung: `verify_context`-Feld im Phase-State

Ein dediziertes Feld `verify_context` im Phase-State identifiziert,
in welchem Kontext der aktuelle Verify-Durchlauf stattfindet. Der
Phase Runner setzt `verify_context` basierend auf dem Auslöser:

[Entscheidung 2026-04-09: VerifyContext ist jetzt ein StrEnum mit genau zwei Werten.
`post_exploration` entfällt — Dokumententreue nach Exploration läuft in der
Exploration-Phase selbst (§23.5). `STRUCTURAL_ONLY_PASS` entfällt ebenfalls.]

| `verify_context` | Auslöser | QA-Tiefe | Begründung |
|------------------|----------|----------|------------|
| `VerifyContext.POST_IMPLEMENTATION` | Verify nach abgeschlossener Implementation-Phase | Volle 4-Schichten-QA (Structural, Semantisch, Adversarial, Policy). | Primärer QA-Durchlauf — unabhängig davon, ob `mode = "exploration"` oder `mode = "execution"`. |
| `VerifyContext.POST_REMEDIATION` | Verify nach einer Remediation-Runde | Volle 4-Schichten-QA (Structural, Semantisch, Adversarial, Policy). | Erneuter vollständiger QA-Durchlauf nach Worker-Remediation — identische Prüftiefe wie nach Implementation. |

### 27.3a.3 Entscheidungsregel

[Entscheidung 2026-04-09: Code-Beispiel auf VerifyContext StrEnum umgestellt.
`post_exploration`-Zweig und `STRUCTURAL_ONLY_PASS` entfernt.]

[Korrektur 2026-04-09: PAUSED/agents_to_spawn/RUN_SEMANTIC entfernt —
Layer 2 laeuft vollstaendig intern im Phase Runner (ThreadPoolExecutor),
kein Orchestrator-Roundtrip, kein PAUSED-Zustand in Verify.]

```python
# Im Phase Runner — Verify-Einstieg:
# [Entscheidung 2026-04-09] VerifyContext ist ein StrEnum, kein String-Literal.
# [Korrektur 2026-04-09] Layer 2 laeuft intern im Phase Runner (ThreadPoolExecutor),
# kein Orchestrator-Roundtrip. Layer 3 (Adversarial) spawnt externen Agenten (§27.3a.4).

if state.verify_context is None:
    # fail-closed (§27.3a.0): kein Verify-Lauf ohne bekannten Kontext
    return PhaseResult(status="ESCALATED", reason="Missing verify_context — Phase Runner Defekt")

if state.verify_context in (
    VerifyContext.POST_IMPLEMENTATION,
    VerifyContext.POST_REMEDIATION,
):
    # Volle 4-Schichten-QA, UNABHAENGIG von state.mode

    # Schicht 1: Deterministische Checks (Layer-1-Orchestrierung, §27.4)
    # run_structural_checks() orchestriert alle 4 parallelen Layer-1-Zweige:
    #   (1) Artefakt-Prüfung (§27.4.1)
    #   (2) Structural Checks (§27.4.2)
    #   (3) Recurring Guards (§27.4.3)
    #   (4) ARE-Gate (§27.4.4, optional)
    # Impact-Violation (§27.4.2) führt zu sofortigem ESCALATED (kein Feedback-Loop).
    # Stoppt NUR bei BLOCKING-FAIL. MAJOR/MINOR Findings laufen durch zu Schicht 2.
    result = run_structural_checks(state)
    if result.has_blocking_failure():  # NUR BLOCKING-FAIL stoppt (§27.4.5)
        return _handle_verify_failure(state, result)

    # Schicht 2: LLM-Bewertungen — intern via ThreadPoolExecutor
    # Phase Runner ruft externe LLMs direkt auf (kein Orchestrator,
    # kein PAUSED, kein agents_to_spawn). Ergebnisse als JSON persistiert.
    layer2_results = _run_layer2_parallel(context)  # ThreadPoolExecutor
    # -> llm-review.json, semantic-review.json, doc-fidelity.json (§27.5.5)
    # Stoppt bei FAIL. PASS_WITH_CONCERNS blockiert NICHT (§27.5.4).
    if layer2_results.has_failure():  # NUR FAIL stoppt, nicht PASS_WITH_CONCERNS
        return _handle_verify_failure(state, layer2_results)

    # Schicht 3: Adversarial Testing (Agent-Spawn via Orchestrator, §27.6.1)
    # Steuerungsvertrag (qa_cycle_status, kanonischer Feldname, §27.2.2/§27.8.3):
    #   Phase Runner setzt agents_to_spawn + speichert State (qa_cycle_status = awaiting_qa).
    #   Orchestrator spawnt Adversarial Agent; dieser schreibt adversarial.json.
    #   Phase Runner wird re-entered wenn adversarial.json vorliegt → qa_cycle_status = awaiting_policy.
    # Schicht 4: Policy-Evaluation (deterministisch, §27.7.1):
    #   → PASS: qa_cycle_status = pass
    #   → FAIL (remediable): qa_cycle_status = awaiting_remediation (Feedback-Loop, §27.2.2)
    #   → FAIL (impact.violation oder max_rounds_exceeded): qa_cycle_status = escalated
```

**Invariante:** Beide `VerifyContext`-Werte (`POST_IMPLEMENTATION`,
`POST_REMEDIATION`) lösen IMMER die volle 4-Schichten-QA aus,
unabhängig von `mode`. Es gibt keinen Structural-only-Verify-Pfad.

### 27.3a.4 Invariante: Verify läuft immer mit voller 4-Schichten-Pipeline

[Entscheidung 2026-04-09: `STRUCTURAL_ONLY_PASS` existiert nicht mehr.
Die gesamte alte Invariante (STRUCTURAL_ONLY_PASS nach Implementation verboten)
entfällt, da es keinen Structural-only-Verify-Pfad mehr gibt.]

[Korrektur 2026-04-09: Falsche Invariante entfernt — Verify verwendet
keinen PAUSED-Zustand, kein agents_to_spawn und kein RUN_SEMANTIC fuer
Layer 2. Layer 2 laeuft intern im Phase Runner.]

Verify wird ausschließlich für Implementation- und Bugfix-Stories
aufgerufen (Concept- und Research-Stories durchlaufen keine
Verify-Phase). In jedem Fall — ob `POST_IMPLEMENTATION` oder
`POST_REMEDIATION` — läuft die volle 4-Schichten-Pipeline:

1. Schicht 1: Deterministische Checks (Structural, Recurring Guards, ARE, Impact)
2. Schicht 2: LLM-Bewertungen (QA, Semantic, Umsetzungstreue) — intern, kein Orchestrator-Roundtrip
3. Schicht 3: Adversarial Testing — extern, via `agents_to_spawn` (§27.6.1)
4. Schicht 4: Policy-Evaluation

[Korrektur 2026-04-09: "Verify ist atomar" bezieht sich nur auf Layer 2 — Layer 3 (Adversarial) spawnt weiterhin einen externen Agenten via Orchestrator (§27.6.1), da Dateisystem-Zugriff und Subprocess-Ausführung erforderlich sind.]

Layer 2 (LLM-Bewertungen) läuft vollständig intern im Phase Runner
via `ThreadPoolExecutor` — kein Orchestrator-Roundtrip, kein
PAUSED-Zustand. Layer 3 (Adversarial) hingegen spawnt einen externen
Agenten über `agents_to_spawn` (§27.6.1), da dieser Dateisystem-Zugriff
und Subprocess-Ausführung benötigt — beides liegt außerhalb der
Fähigkeiten eines einfachen LLM-Aufrufs. Verify ist damit für Layer 2
nicht-unterbrechend, für Layer 3 jedoch Orchestrator-vermittelt.

Die LLM-Ergebnisse (Layer 2) werden als parsebares JSON persistiert
(`llm-review.json`, `semantic-review.json`, `doc-fidelity.json`). Es gibt keinen
PAUSED-Zwischenstatus, kein `agents_to_spawn` fuer Layer 2 und kein
`RUN_SEMANTIC`-Ergebnis fuer Layer 2. Der PauseReason-Enum hat nur
drei Werte (AWAITING_DESIGN_REVIEW, AWAITING_DESIGN_CHALLENGE,
GOVERNANCE_INCIDENT) — keiner davon gilt fuer Layer 2.

### 27.3a.5 Fehlende LLM-Reviews sind ein HARD BLOCKER

Fehlende LLM-Reviews bei Implementation- und Bugfix-Stories sind ein
HARD BLOCKER, kein Warning. Zwei unabhängige Gates stellen dies sicher:

- **Gate 1 (`guard.llm_reviews`):** Wurden Reviews überhaupt
  angefordert? 0 `review_request` Events bei Implementation/Bugfix →
  sofortiger FAIL in Layer 1 (Recurring Guards, §27.4.3).
- **Gate 2 (`guard.multi_llm`):** Liegen für ALLE mandatory Reviewer
  (qa_review, semantic_review, doc_fidelity) Telemetrie-Evidenzen vor? Gate 2 ist
  UNABHÄNGIG von Gate 1 — auch wenn Reviews angefordert wurden
  (Gate 1 bestanden), müssen die Ergebnisse vorliegen. Fängt den
  Fall: "Reviews gestartet, aber nie abgeschlossen oder ohne Ergebnis
  beendet".

Beide Gates sind als BLOCKING klassifiziert (nicht WARNING/MAJOR) und
dürfen NICHT zu einem einzigen Gate zusammengefasst werden (siehe
§27.4.3).

[Korrektur 2026-04-09: guard.llm_reviews und guard.multi_llm sind Schicht-1-Checks (§27.4.3), kein Layer-4-Gate. Ein BLOCKING-FAIL in Schicht 1 stoppt die Pipeline, Layer 4 wird nicht erreicht.]

**Provenienz:** REF-036, Domänenkonzept 4.4a.

## 27.4 Schicht 1: Deterministische Checks

### 27.4.1 Artefakt-Prüfung

Erste Prüfung, vor allem anderen. Stellt sicher, dass die
Grundvoraussetzungen für die weiteren Prüfungen erfüllt sind.

| Check-ID | Was | FAIL wenn | Severity |
|----------|-----|----------|----------|
| `artifact.protocol` | `protocol.md` existiert, > 50 Bytes | Datei fehlt oder leer | BLOCKING |
| `artifact.worker_manifest` | `worker-manifest.json` ist valides JSON | Datei fehlt oder ungültiges JSON | BLOCKING |
| `artifact.manifest_claims` | Deklarierte Dateien in Manifest existieren auf Disk | Eine deklarierte Datei fehlt | BLOCKING |
| `artifact.handover` | `handover.json` existiert und Schema-valide | Datei fehlt oder Schema-Verletzung | BLOCKING |

### 27.4.2 Structural Checks

Laufen sequenziell nach erfolgreichem Artefakt-Check (§27.4.1 PASS),
dann parallel zueinander (gemeinsam mit Recurring Guards §27.4.3, ARE-Gate §27.4.4
und Impact-Check — alle vier parallel nach Artefakt-Prüfungs-PASS):

| Check-ID | Kategorie | Was | Severity |
|----------|-----------|-----|----------|
| `branch.story` | Branch | Auf korrektem Branch `story/{story_id}` | BLOCKING |
| `branch.commit_trailers` | Branch | Story-ID in Commit-Message | BLOCKING |
| `completion.commit` | Completion | Mindestens 1 Commit seit Base-Ref | BLOCKING |
| `completion.push` | Completion | Branch auf Remote gepusht | BLOCKING |
| `security.secrets` | Security | Keine `.env`, `.pem`, `.key` etc. im Diff | BLOCKING |
| `build.compile` | Build | Build kompiliert erfolgreich | BLOCKING |
| `build.test_execution` | Build | Tests grün | BLOCKING |
| `test.count` | Test | Mindestens 1 Testdatei im Changeset | MAJOR |
| `test.coverage` | Test | Coverage-Report existiert, Schwellenwert erreicht | MAJOR |
| `hygiene.todo_fixme` | Hygiene | Keine TODO/FIXME in geänderten Dateien | MINOR |
| `hygiene.disabled_tests` | Hygiene | Keine `@Disabled`/`@Ignore`/`@pytest.mark.skip` | MINOR |
| `hygiene.commented_code` | Hygiene | Keine großen auskommentierten Code-Blöcke | MINOR |
| `impact.violation` | Impact | Tatsächlicher Impact ≤ deklarierter Impact (Kap. 23.8). **Reaktion:** Impact-Violation → ESCALATED (Eskalation an Mensch, kein Rücksprung zur Exploration-Phase). [Korrektur 2026-04-09: Modus-abhängige Reaktion entfällt — Impact-Violation führt immer zu ESCALATED, analog FK-20 und FK-23.] | BLOCKING |

### 27.4.3 Recurring Guards (Telemetrie-basiert)

Prüfen den Prozess, nicht die fachliche Lösung. Laufen parallel
zu den Structural Checks:

| Check-ID | Was | Quelle | Severity |
|----------|-----|--------|----------|
| `guard.llm_reviews` | Pflicht-Reviews durchgeführt (mindestens 1 `review_request`-Event; kein größenabhängiger exakter Zähler — konsistent mit §27.11.2 Minimum-Schwellen-Vertrag) | Telemetrie: `review_request` Events zählen | **BLOCKING** |
| `guard.review_compliance` | Reviews über freigegebene Templates | Telemetrie: `review_compliant` Events | MAJOR |
| `guard.no_violations` | Keine Guard-Verletzungen während der Bearbeitung | Telemetrie: keine `integrity_violation` Events | BLOCKING |
| `guard.multi_llm` | Alle konfigurierten Pflicht-Reviewer mit Ergebnis abgeschlossen | Telemetrie: `llm_call_complete` Events mit passenden `pool`/`role` Werten. **`llm_call_complete` darf erst nach erfolgreichem Schreiben des Review-Artefakts (§27.5.5) emittiert werden** — nicht bei bloßer API-Antwort. Fängt "Review gestartet, nie abgeschlossen" (§27.3a.5). | **BLOCKING** |

**Zwei-Stufen-Prüfung für LLM-Reviews (REF-036):**

`guard.llm_reviews` und `guard.multi_llm` bilden eine
Zwei-Stufen-Prüfung, die als separate BLOCKING Guards implementiert
sein MUSS:

1. **Gate 1 (`guard.llm_reviews`):** Wurden Reviews überhaupt
   angefordert? 0 `review_request` Events bei einer
   Implementation/Bugfix-Story → sofortiger FAIL.
2. **Gate 2 (`guard.multi_llm`):** Liegen für ALLE mandatory
   Reviewer (`qa_review`, `semantic_review`, `doc_fidelity`) Telemetrie-Evidenzen
   vor? Gate 2 ist unabhängig von Gate 1 — auch wenn Reviews
   angefordert wurden, müssen die Ergebnisse vorliegen.

Beide Gates dürfen NICHT zu einem einzigen Gate zusammengefasst
werden. Empirischer Anlass: BB2-057 — beide Guards erkannten die
fehlenden Reviews korrekt, waren aber nur als WARNING klassifiziert
und konnten den Closure-Pfad nicht blockieren.

### 27.4.4 ARE-Gate (optional)

Nur bei `features.are: true`. Deterministisches Skript fragt ARE
über MCP ab:

| Check-ID | Was | FAIL wenn |
|----------|-----|----------|
| `are.coverage` | Alle `must_cover`-Anforderungen haben Evidence | Eine Pflichtanforderung ohne Evidence |

### 27.4.5 Gate-Entscheidung Schicht 1

- Ein BLOCKING-FAIL → Story geht zurück an Worker (Feedback). **Ausnahme:** `impact.violation` (BLOCKING) führt direkt zu ESCALATED — kein Feedback-Loop, kein Worker-Rückgabe (§27.4.2).
- Nachfolgende Schichten werden nicht gestartet (FK-05-151)
- MAJOR/MINOR Failures werden gesammelt und fließen in die
  Policy-Evaluation (Schicht 4)

### 27.4.6 Ergebnis-Artefakt

`_temp/qa/{story_id}/structural.json` (Envelope-Format, Producer:
`qa-structural-check`).

## 27.5 Schicht 2: LLM-Bewertungen

### 27.5.1 Parallele Ausführung

Drei LLM-Bewertungen laufen parallel über `ThreadPoolExecutor`
(Kap. 11.7). Alle nutzen den StructuredEvaluator (Kap. 11.4).
[Korrektur 2026-04-09: "Zwei" → "Drei" — Schicht 2 umfasst drei parallele LLM-Bewertungen: QA-Bewertung, Semantic Review, Umsetzungstreue (§27.9.1).]

### 27.5.2 QA-Bewertung (12 Checks)

**Rolle:** `qa_review` (konfiguriertes LLM, z.B. ChatGPT)

**Prompt-Template:** `prompts/qa-semantic.md`

**Kontext-Bundles:** `story_spec`, `diff_summary`, `concept_excerpt`,
`handover`

**12 Checks (FK-05-168 bis FK-05-179):**

| Check-ID | Prüfgegenstand |
|----------|---------------|
| `ac_fulfilled` | Akzeptanzkriterien erfüllt? |
| `impl_fidelity` | Gebaut = konzipiert? |
| `scope_compliance` | Kein undokumentierter Scope Creep? |
| `impact_violation` | Tatsächlicher ≤ deklarierter Impact? |
| `arch_conformity` | Pattern, Schichten, Boundaries eingehalten? |
| `proportionality` | Nicht over-/under-engineered? |
| `error_handling` | Fehlerfälle sauber behandelt? |
| `authz_logic` | Mandantentrennung verletzbar? |
| `silent_data_loss` | Datenverlust ohne Fehler möglich? |
| `backward_compat` | Consumer brechen? |
| `observability` | Logging + Fehler-Sichtbarkeit? |
| `doc_impact` | Bestehende Doku veraltet? |

**Antwort-Schema:** Pro Check: `status` (PASS/PASS_WITH_CONCERNS/FAIL),
`reason` (Einzeiler), `description` (max 300 Zeichen).

### 27.5.3 Semantic Review

**Rolle:** `semantic_review` (anderes LLM, z.B. Gemini)

**Prompt-Template:** `prompts/qa-semantic-review.md`

**Kontext-Bundles:** `story_spec`, `diff_summary`, `evidence_manifest`,
plus aggregierte Befunde aus Schicht 1

**1 Check:** Systemische Angemessenheit — Passt die Lösung in den
Systemkontext? Ist der Change im Verhältnis zum Problem angemessen?
Gibt es systemische Risiken, die die Einzelchecks nicht sehen?
(FK-05-180/181)

### 27.5.4 Aggregation

- Ein einzelnes FAIL in irgendeinem Check → blockiert (FK-05-164)
- PASS_WITH_CONCERNS blockiert nicht → fließt als Warnung in
  Policy-Evaluation + wird an Adversarial Agent als Ansatzpunkt
  weitergegeben (FK-05-165/166)

### 27.5.5 Ergebnis-Artefakte

- `_temp/qa/{story_id}/llm-review.json` (Producer: `qa-llm-review`)
- `_temp/qa/{story_id}/semantic-review.json` (Producer: `qa-semantic-review`)
- `_temp/qa/{story_id}/doc-fidelity.json` (Producer: `qa-doc-fidelity`)

[Ergänzung 2026-04-09: doc-fidelity.json als drittes Layer-2-Artefakt ergänzt — Umsetzungstreue (§27.9.1) schreibt Ergebnis in doc-fidelity.json (Rolle: doc_fidelity).]

> **[Entscheidung 2026-04-08]** Element 27 — Context Sufficiency Builder ist Pflicht-Gate VOR dem Review: stellt sicher dass genuegend Informationen vorhanden sind. Wenn nicht → Informationen zusammentragen, NICHT Review ueberspringen. Reviews finden IMMER statt.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 27.

## 27.5a Context Sufficiency Builder (Pre-Step Schicht 2)

### 27.5a.1 Zweck (FK-27-200)

Zusätzlich zur bestehenden Schicht 2 (§27.5) wird ab Version 3.0
ein deterministischer Pre-Step eingeführt, der VOR dem Start des
`ParallelEvalRunner` die Vollständigkeit des Kontext-Bundles prüft
und ergänzt. Ziel: Schicht-2-Evaluatoren erhalten ein geprüftes,
angereichertes Bundle statt eines möglicherweise lückenhaften
Kontexts.

**Architektonische Einordnung:** [Korrektur 2026-04-09: "Layer-2-Caller" als eigenständige Komponente entfernt — Layer 2 läuft vollständig intern im Phase Runner via `_run_layer2_parallel()`.]

- **ContextSufficiencyBuilder** (innerhalb Phase Runner): Orchestrierung + Dateisystem — prüft
  und ergänzt das Bundle BEVOR der Runner startet
- **ParallelEvalRunner** (innerhalb Phase Runner): Reiner Executor — führt LLM-Evaluierungen
  parallel aus

Der Builder wird aus der `_run_layer2_parallel()`-Funktion des Phase
Runners aufgerufen, bevor der `ParallelEvalRunner` gestartet wird.
Er läuft im selben Prozess — kein Orchestrator-Roundtrip, keine
separate Caller-Komponente. Er wird NICHT innerhalb des
ParallelEvalRunner aufgerufen (Runner ist reiner Executor,
Builder benötigt Dateisystem-Zugriff).

### 27.5a.2 Prüfungen

Der Context Sufficiency Builder prüft alle 6 `ContextBundle`-Felder:

| Feld | Prüfung | Bewertung |
|------|---------|-----------|
| `story_spec` | Vorhanden? Leer? | `present` / `missing` |
| `diff_summary` | Vorhanden? Trunkiert (>32.000 Zeichen)? | `present` / `missing` / `truncated` |
| `concept_excerpt` | Vorhanden? Nur Summary statt Primärquelle? | `present` / `missing` / `summary_only` |
| `handover` | Vorhanden? Substantielle `risks_for_qa`? | `present` / `missing` |
| `arch_references` | Vorhanden? Architektur-Docs geladen? | `present` / `missing` |
| `evidence_manifest` | Vorhanden? Evidence-Assembly-Ergebnis? | `present` / `missing` |

**Loader-Vollständigkeit als Invariante (REF-035):** Für jedes der
6 Felder MUSS ein kanonischer Bezugsweg existieren: entweder eine
dedizierte Loader-Methode im Builder ODER eine dokumentierte
caller-seitige Einspeisung. Felder ohne definierten Bezugsweg werden
als `missing` klassifiziert, obwohl die Daten auf Disk vorhanden sind —
ein Implementierungsfehler, kein fehlender Input.

Kanonische Loader-Methoden und Quellen:

| Feld | Loader-Methode | Quelle |
|------|---------------|--------|
| `story_spec` | `_load_story_spec()` | `{story_dir}/story.md` |
| `handover` | `_load_handover()` | `{story_dir}/handover.json` |
| `diff_summary` | Caller-seitig aus `context.json` übergeben; kein eigener Loader im Builder | `context.json` (Setup-Phase) |
| `concept_excerpt` | `_load_concept_excerpt()` | `concept_paths` aus `context.json` → Dateien unter `_concept/` |
| `arch_references` | `_load_arch_references()` | `concept_paths` aus `context.json` (inkl. `external_sources`) |
| `evidence_manifest` | Caller-seitig aus `context.json` übergeben; kein eigener Loader im Builder | `context.json` (Evidence-Assembly) |

### 27.5a.3 Sufficiency-Klassifikation

| Stufe | Bedingung | Konsequenz |
|-------|-----------|------------|
| `sufficient` | Alle Pflichtfelder vorhanden und substantiell | Layer 2 startet regulär |
| `reviewable_with_gaps` | Felder vorhanden, aber Lücken (z.B. Trunkierung, nur Summary) | Layer 2 startet, Lücken als Warnung in `context_sufficiency.json` |
| `partially_reviewable` | Wesentliche Felder fehlen oder leer | **Warning**, Layer 2 läuft trotzdem (fail-open für Sufficiency) |

**Klassifikationsregel (REF-035):** Trunkierung allein (z.B.
`diff_summary` von 84.979 auf 32.000 Zeichen gekürzt) ergibt
`reviewable_with_gaps`, NICHT `partially_reviewable`. Nur fehlende
Pflichtfelder (z.B. `story_spec` oder `diff_summary` nicht ladbar)
rechtfertigen `partially_reviewable`. Diese Unterscheidung ist
wesentlich: Trunkierung reduziert die Review-Qualität, verhindert
aber kein Review. Fehlende Pflichtfelder machen ein vollständiges
Review unmöglich.

**Scope von `partially_reviewable`:** `story_spec` und `diff_summary`
haben keine dedizierten Structural Checks in §27.4.1 (der prüft nur
Worker-Artefakte: protocol.md, worker-manifest, manifest-claims,
handover.json). Fehlt `story_spec` oder `diff_summary`, führt das
zur Einstufung `partially_reviewable` und einer Warning — Layer 2
läuft trotzdem weiter (fail-open für Sufficiency). Reviews dürfen
nicht wegen fehlender Kontexte übersprungen werden.

### 27.5a.4 Enrichment

Wo möglich ergänzt der Builder fehlende Felder:
- `story_spec`: `story.md` aus `story_dir` laden (REF-035).
- `handover`: `handover.json` aus `story_dir` laden (REF-035).
- `concept_excerpt`: Konzeptdokumente über `concept_paths` aus
  `context.json` auflösen und aus dem `_concept/`-Verzeichnis des
  Zielprojekts laden (Primärquellen statt nur Summary).
- `arch_references`: Architektur-Dokumente aus `context.json`
  nachladen.
- `external_sources`: Referenzen aus `context.json` an den Reviewer
  weiterreichen. Nicht-erreichbare externe Quellen werden als
  unresolved evidence gap dokumentiert — kein PASS auf Claims, die
  diese Quelle benötigen (FK 21.3.3). [Hinweis: `external_sources`
  ist kein eigenständiges ContextBundle-Feld — externe Referenzen
  werden durch den Builder in `arch_references` eingebettet und
  fließen über dieses Bundle-Feld zum Reviewer.]

**Path-Resolution-Fallback für Concept-Excerpts (REF-035):**
Concept-Pfade in `context.json` können nackte Dateinamen enthalten
(z.B. `02-komponentenstruktur.md` statt
`_concept/technical-design/02-komponentenstruktur.md`). Der Builder
MUSS einen Fallback implementieren: Wenn der direkte Pfad
(`{repo_root}/{dateiname}`) nicht existiert, wird in den
`_concept/`-Unterverzeichnissen (`domain-design/`, `technical-design/`)
gesucht. Nur wenn auch der Fallback fehlschlägt, wird das Feld
als `missing` klassifiziert.

**Kanonische Feldnamen aus `story_sections.py` (REF-035):**
Der Builder MUSS die kanonischen Feldnamen aus `story_sections.py`
(Single Source of Truth) verwenden — keine eigenen Schlüsselsuchen.
Konkret: Die Setup-Phase speichert Architektur-Referenzen unter
`concept_paths`. Der Builder muss diesen Key konsumieren, nicht
alternative Keys wie `arch_references`, `architecture_docs` oder
`concept_files`. Was das Template vorgibt, muss die Pipeline
verwenden.

### 27.5a.5 Ergebnis-Artefakt

`_temp/qa/{story_id}/context_sufficiency.json`
(Producer: `qa-context-sufficiency`):

```json
{
  "schema_version": "1.0",
  "story_id": "ODIN-042",
  "stage": "context_sufficiency",
  "bundles": {
    "story_spec": { "status": "present", "chars": 4200, "truncated": false },
    "diff_summary": { "status": "truncated", "chars": 32000, "truncated": true, "truncated_from": 48000 },
    "concept_excerpt": { "status": "summary_only", "chars": 1200, "truncated": false, "note": "Nur Summary, Primärquelle nicht verfügbar" },
    "handover": { "status": "present", "chars": 3100, "truncated": false },
    "arch_references": { "status": "present", "chars": 2800, "truncated": false },
    "evidence_manifest": { "status": "present", "chars": 1500, "truncated": false }
  },
  "sufficiency": "reviewable_with_gaps",
  "gaps": ["concept_excerpt: nur Summary", "diff_summary: trunkiert von 48000 auf 32000 Zeichen"]
}
```

### 27.5a.6 Ablauf in _run_layer2_parallel()

```python
# In _run_layer2_parallel() des Phase Runners:

from agentkit.qa.context_sufficiency import ContextSufficiencyBuilder, SufficiencyLevel
from agentkit.core.packing import pack_markdown, pack_code

# 0. context.json rebuild (Remediation-Re-Entry-Pflicht, §27.2.3):
#    Falls context.json nach advance_qa_cycle() nach stale/ verschoben wurde,
#    wird es hier neu aufgebaut (Caller-Verantwortung vor _run_layer2_parallel()).
#    context_json = rebuild_context(story_id)  # Phase-Runner-eigene Funktion
context_json = load_or_rebuild_context(story_id)  # fail-closed wenn nicht ladbar

# 1. ContextBundle aus context_json + Caller-Inputs aufbauen
#    (bundle wird vom Caller vor _run_layer2_parallel() konstruiert)
bundle: ContextBundle  # übergeben als Parameter — Felder aus context_json + story_dir

# 2. Sufficiency prüfen + enrichen
sufficiency_builder = ContextSufficiencyBuilder(
    story_id=ctx.story_id,
    story_dir=ctx.story_dir,
    output_dir=ctx.output_dir,
    context_json=context_json,
)
sufficiency_result = sufficiency_builder.build(bundle)
enriched_bundle = sufficiency_result.enriched_bundle

# 3. Warning bei Gaps
if sufficiency_result.sufficiency != SufficiencyLevel.SUFFICIENT:
    warnings.append(
        f"Context sufficiency: {sufficiency_result.sufficiency.value}, "
        f"gaps: {sufficiency_result.gaps}"
    )

# 4. Per-Feld Packing (§27.5b)
context_dict = _pack_and_convert(enriched_bundle)

# 5. ParallelEvalRunner starten
runner.run(context=context_dict, ...)
```

> **[Entscheidung 2026-04-08]** Element 28 — Section-aware Bundle-Packing ist Pflicht. FK-34-121 normativ. In v2 bereits implementiert.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 28.

## 27.5b Konvertierungs-Verantwortung und Section-aware Packing

### 27.5b.1 Design-Entscheidung D7: Domänen-Abstraktion vs. Transport-Schicht (FK-27-210)

[Korrektur 2026-04-09: "Layer-2-Caller" als eigenständige Komponente entfernt — die Konvertierung (ContextBundle → dict[str, str]) findet innerhalb von `_run_layer2_parallel()` statt, nicht in einer separaten Caller-Komponente.]

**ContextBundle ist die Domänen-Abstraktion (Track B).
`dict[str, str]` ist die Transport-Schicht (Runner/Evaluator).**

Die Konvertierung findet exakt einmal statt, in `_run_layer2_parallel()`
des Phase Runners. Weder der Sufficiency Builder noch der Runner/Evaluator
werden mit der jeweils anderen Abstraktion belastet.

| Komponente | Kennt ContextBundle? | Kennt dict[str, str]? | Rolle |
|-----------|---------------------|----------------------|-------|
| ContextSufficiencyBuilder | Ja (Input + Output) | Nein | Prüft + ergänzt Bundle-Felder |
| ParallelEvalRunner | Nein | Ja (Signatur `context: dict[str, str]`) | Reiner Executor für Placeholder-Rendering |

Die Konvertierung geschieht in `_run_layer2_parallel()` (Phase Runner) —
dies ist die einzige Stelle, die beide Abstraktionen kennt.

### 27.5b.2 Konvertierung in _run_layer2_parallel()

`BUNDLE_TOKEN_LIMIT`: Maximale Zeichenanzahl pro Bundle-Feld nach dem Packing.
Default: 32.000 Zeichen (konfigurierbar in `pipeline.yaml` unter `layer2.bundle_token_limit`).
Referenz: §27.5a.2 `diff_summary` Trunkierungsbeispiel (84.979 → 32.000).

`_run_layer2_parallel()` (Phase Runner) ist die einzige Stelle, die beide Abstraktionen
kennt. Es führt zwei Schritte aus:

1. **Per-Feld Packing**: Jedes Feld wird mit dem passenden Packer
   komprimiert
2. **Konvertierung**: `enriched_bundle._asdict()` → `dict[str, str]`
   (None-Felder filtern)

```python
# In _run_layer2_parallel() (Phase Runner):

from agentkit.core.packing import pack_markdown, pack_code

def _pack_and_convert(bundle: ContextBundle) -> dict[str, str]:
    """Packt jedes Bundle-Feld semantisch und konvertiert zu dict."""
    packed: dict[str, str] = {}

    # Markdown-Felder: Section-aware Packing
    for field_name in ("story_spec", "concept_excerpt", "arch_references"):
        value = getattr(bundle, field_name)
        if value:
            result = pack_markdown(value, limit=BUNDLE_TOKEN_LIMIT, priority_headings=_priorities_for(field_name))
            packed[field_name] = result.content

    # Code-Feld: Symbol-aware Packing (nur diff_summary — enthält Git-Diff)
    diff_value = getattr(bundle, "diff_summary")
    if diff_value:
        result = pack_code(diff_value, changed_symbols=_extract_symbols(diff_value), limit=BUNDLE_TOKEN_LIMIT)
        packed["diff_summary"] = result.content

    # JSON-Feld: Durchreichen (evidence_manifest ist strukturiertes JSON, kein Code-Diff)
    evidence = getattr(bundle, "evidence_manifest")
    if evidence:
        packed["evidence_manifest"] = evidence  # kein pack_code — keine Symbol-Extraktion auf JSON

    # Handover: Durchreichen (JSON, kein Packing nötig)
    if bundle.handover:
        packed["handover"] = bundle.handover

    return packed
```

`ParallelEvalRunner.run(context=context_dict)` — die
Runner-Signatur bleibt unverändert.

### 27.5b.3 Section-aware Packing (Kap. 28, Modul `agentkit/core/packing.py`)

Das neue Modul `agentkit/core/packing.py` stellt zwei Packer bereit:

**`pack_markdown(content, limit, priority_headings)`**
- Segmentiert an Markdown-Überschriften (`##`, `###`, `####`)
- Priorisiert: `priority_headings` matchen → höhere Priorität
- Packt ganze Abschnitte (nie mitten im Satz)
- Ersetzt weggelassene Abschnitte durch Platzhalter:
  `[Section "..." omitted — N chars]`
- Eingesetzt für: `story_spec`, `concept_excerpt`, `arch_references`

**`pack_code(content, changed_symbols, limit)`**
- Geänderte Funktionen/Klassen vollständig behalten
- Unveränderte Nachbarn nur mit Signatur (ohne Body)
- Kommentare und Leerzeilen am Ende kürzen
- Eingesetzt für: `diff_summary`, `evidence_manifest`

**Dispatcher `truncate_bundle()` in `evaluator.py`:**

Die bestehende `truncate_bundle()`-Funktion in `evaluator.py` wird
zum Dispatcher erweitert: delegiert an `pack_markdown()` wenn
`priority_headings` gesetzt, sonst bisheriger beginning+end-Fallback.
Die Signatur bleibt abwärtskompatibel.

[Hinweis: `_pack_and_convert()` (§27.5b.2) ruft die Packer direkt auf —
nicht über den Dispatcher. Der Dispatcher ist für externe Aufrufer in
`evaluator.py` vorgesehen. Dies ist kein Widerspruch: `_pack_and_convert()`
ist der kanonische Packing-Pfad für Layer 2; der Dispatcher deckt Legacy-
und Fallback-Pfade in der Evaluator-Schicht ab.]

```python
# evaluator.py — truncate_bundle() wird zum Dispatcher
def truncate_bundle(
    content: str,
    limit: int = BUNDLE_TOKEN_LIMIT,
    priority_headings: list[str] | None = None,
) -> str:
    """Dispatcher: pack_markdown wenn priority_headings gesetzt,
    sonst bisheriger beginning+end-Fallback."""
    if len(content) <= limit:
        return content
    if priority_headings is not None:
        result = pack_markdown(content, limit, priority_headings)
        return result.content
    # Bisheriger Fallback für unbekannte/unstrukturierte Inhalte
    half = limit // 2
    return content[:half] + TRUNCATION_MARKER + content[-half:]
```

### 27.5b.4 Evaluator-rollenspezifische Prioritäten

Die Priorisierung der Markdown-Sektionen ist **feldspezifisch** (nicht
rollenspezifisch): `_pack_and_convert()` erzeugt ein einziges gepacktes
Dict, das alle drei Evaluatoren gemeinsam nutzen. Die Konstanten unten
sind Feldprioritäten, die in `_priorities_for(field_name)` nachgeschlagen
werden — nicht pro Evaluator-Rolle unterschiedlich.

[Hinweis: Alle Evaluatoren (QA, Semantic, Umsetzungstreue) erhalten
dieselbe gepackte Fassung pro Feld. Role-spezifisches Packing ist nicht
implementiert — alle Evaluatoren teilen ein gemeinsames context_dict.
Role-spezifisches Packing wäre ein FK-34-Thema.]

```python
# In _run_layer2_parallel() (Phase Runner), feldspezifisch, NICHT pro Evaluator-Rolle:
# Ein gepacktes Dict für ALLE Evaluatoren — keine rollenspezifischen Varianten.
# story_spec wird mit QA_PRIORITY_HEADINGS gepackt; ALLE Evaluatoren (QA, Semantic,
# Umsetzungstreue) erhalten dieselbe gepackte Fassung. semantic_review erhält
# story_spec mit den QA-Prioritäten — kein ungefiltert-Sonderweg.

QA_PRIORITY_HEADINGS = ["Acceptance Criteria", "Akzeptanzkriterien", "Requirements"]
DOC_FIDELITY_PRIORITY_HEADINGS = ["Design", "Architecture", "Architektur"]
ARCH_PRIORITY_HEADINGS = ["Architecture", "Architektur", "Components", "Komponenten", "Interfaces"]
# story_spec     → QA_PRIORITY_HEADINGS      (geteilt von allen Evaluatoren)
# concept_excerpt → DOC_FIDELITY_PRIORITY_HEADINGS
# arch_references → ARCH_PRIORITY_HEADINGS
```

> **[Entscheidung 2026-04-08]** Element 26 — Quorum / Tiebreaker ist Pflicht. Dritter Reviewer bei Divergenz.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 26.
> [Scope-Begrenzung FK-27 (2026-04-09): FK-27 beschreibt drei feste parallele Evaluatoren (QA, Semantic, Umsetzungstreue) ohne Tiebreaker-Mechanismus. Die Quorum/Divergenz-Logik (Divergenzbedingung, Tiebreak-Reviewer, Aggregationsregel) ist normativ nach FK-34 ausgelagert und implementierbar erst wenn FK-34 diese Verträge definiert. Bis dahin gilt: alle drei Evaluatoren müssen PASS liefern, FAIL in einem Evaluator → gesamte Schicht 2 FAIL (kein Tiebreaker).]

## 27.6 Schicht 3: Adversarial Testing

### 27.6.1 Agent-Spawn

Der Phase Runner setzt `agents_to_spawn` im Phase-State:

```json
{
  "type": "adversarial",
  "prompt_file": "prompts/adversarial-testing.md",
  "model": "opus",
  "sandbox_path": "_temp/adversarial/ODIN-042/",
  "inputs": {
    "handover": "stories/ODIN-042/handover.json",
    "layer2_concerns": [
      "_temp/qa/ODIN-042/llm-review.json",
      "_temp/qa/ODIN-042/semantic-review.json",
      "_temp/qa/ODIN-042/doc-fidelity.json"
    ]
  }
}
```

Der Orchestrator spawnt den Adversarial Agent als Claude-Code-
Sub-Agent. Der Agent hat:
- Dateisystem-Zugriff (Read auf alles, Write nur in Sandbox)
- Zugriff auf Handover-Paket (`inputs.handover`, `risks_for_qa` als Ansatzpunkte)
- Zugriff auf Concerns aus Schicht 2 (`inputs.layer2_concerns`, PASS_WITH_CONCERNS als Ansatzpunkte)
- Pflicht, Sparring-LLM zu holen
- Write-Scoping über CCAG-Regel (Kap. 02.7, 15.4.2)

### 27.6.2 Ablauf (FK-05-197 bis FK-05-207)

1. Agent **prüft die vorhandene Test-Suite** — Abdeckung,
   Aussagekraft, Edge-Case-Behandlung bewerten (FK-05-197)
2. Agent entscheidet: Reichen die bestehenden Tests? Wenn ja:
   bestehende Tests ausführen, nicht pauschal neue schreiben
   (FK-05-198/199)
3. Agent **entwickelt eigenständig Edge Cases** für Lücken
4. Agent schreibt ergänzende Tests in Sandbox, führt sie aus
5. Agent holt Sparring-LLM: "Was habe ich übersehen?"
6. Agent setzt Sparring-Ideen in weitere Tests um
7. Agent muss **mindestens einen Test ausführen** (bestehend
   oder neu) als Nachweis (FK-05-200/201)
8. Ergebnis: Mängelliste oder "keine Befunde"

### 27.6.3 Test-Suite-Wachstum und Konsolidierungsverbot

Es findet keine automatische Konsolidierung der Test-Suite statt
(FK-27-051). Wenn die Test-Suite im Laufe der Zeit zu groß wird,
ist menschliche Intervention erforderlich. Agents dürfen
vorhandene Tests weder eigenständig löschen noch zusammenführen —
auch nicht wenn sie inhaltlich redundant erscheinen. Jede
Verkleinerung der Test-Suite ist eine bewusste menschliche
Entscheidung, die außerhalb des automatisierten Pipeline-Ablaufs
getroffen wird.

### 27.6.4 Test-Promotion

Tests, die der Adversarial Agent in der Sandbox erzeugt hat,
werden **nicht unkonditioniert** ins Repo übernommen. Ein
Pipeline-Skript prüft nach dem Adversarial-Run:

1. Sind die Tests schema-valide (korrekte Test-Struktur)?
2. Sind sie ausführbar (kein Syntax-Error)?
3. Sind sie dedupliziert (kein Duplikat bestehender Tests)?
4. Wenn ja: Promotion ins Repo (kopieren aus Sandbox in `test/`)
5. Wenn nein: Verbleiben in der Sandbox (ephemer)

Promotete Tests werden Teil der regulären Test-Suite und unterliegen
ab dann normaler Code-Ownership (FK-05-204/205).

**Fehlschlagende Tests → Quarantäne für Remediation:**

Wenn der Adversarial Agent einen validen, fehlschlagenden Test
erzeugt hat (= Befund), wird dieser nicht verworfen, sondern in
ein Quarantäne-Verzeichnis im Worktree kopiert:
`tests/adversarial_quarantine/`. Der Remediation-Worker erhält
den expliziten Auftrag, diesen Test grün zu machen — analog zum
Red-Green-Workflow bei Bugfixes. Damit hat der Remediation-Worker
den fehlschlagenden Test als konkreten Ausgangspunkt statt nur
einer textuellen Mängelbeschreibung.

### 27.6.5 Ergebnis-Artefakt

`_temp/qa/{story_id}/adversarial.json` (Producer: `qa-adversarial`)

```json
{
  "schema_version": "3.0",
  "story_id": "ODIN-042",
  "run_id": "...",
  "stage": "qa_adversarial",
  "producer": { "type": "agent", "name": "qa-adversarial" },
  "status": "PASS",
  "tests_created": 3,
  "tests_executed": 5,
  "tests_passed": 5,
  "tests_failed": 0,
  "findings": [],
  "sparring_pool": "grok",
  "sparring_edge_cases_received": 7,
  "sparring_edge_cases_implemented": 3,
  "mandatory_target_results": [
    {
      "target_id": "target-uuid-1",
      "status": "TESTED"
    }
  ]
}
```

### 27.6.6 Telemetrie

| Event | Erwartungswert |
|-------|---------------|
| `adversarial_start` | Genau 1 |
| `adversarial_sparring` | >= 1 (Pflicht) |
| `adversarial_test_created` | >= 0 (neue Tests nur wenn bestehende unzureichend) |
| `adversarial_test_executed` | >= 1 (Pflicht: mindestens 1 Test ausführen) |
| `adversarial_end` | Genau 1 |

## 27.7 Schicht 4: Policy-Evaluation

### 27.7.1 Aggregation

Die Policy-Engine (Kap. 02.9) aggregiert die Ergebnisse aller
vorherigen Schichten:

```python
def evaluate_policy(story_id: str, story_type: str, config: PipelineConfig) -> PolicyResult:
    """story_type: "implementation" | "bugfix" | "concept" | "research" (steuert aktive Stages)."""
    registry = load_stage_registry()
    results = []

    for stage in registry.stages_for(story_type):
        # StageResult.severity: Literal["BLOCKING", "MAJOR", "MINOR"]
        # BLOCKING → severity="BLOCKING" (zählt in blocking_failures bei FAIL)
        # MAJOR    → severity="MAJOR"    (zählt in major_failures bei FAIL)
        # MINOR    → severity="MINOR"    (zählt NICHT in major/blocking_failures)
        artifact = load_artifact(story_id, stage.id)
        if artifact is None:
            # Fehlendes Artefakt = FAIL (fail-closed)
            results.append(StageResult(stage.id, "FAIL", stage.severity, "Artifact missing"))
            continue

        results.append(StageResult(
            stage_id=stage.id,
            status=artifact.status,
            severity=stage.severity,  # "BLOCKING" | "MAJOR" | "MINOR"
            detail=artifact.summary,
        ))

    blocking_failures = sum(1 for r in results if r.severity == "BLOCKING" and r.status == "FAIL")
    major_failures = sum(1 for r in results if r.severity == "MAJOR" and r.status == "FAIL")
    minor_failures = sum(1 for r in results if r.severity == "MINOR" and r.status == "FAIL")
    major_threshold = config.policy.get("major_threshold", 3)

    # §27.7.2: Entscheidungsregel
    if blocking_failures > 0 or major_failures > major_threshold:
        status = "FAIL"
    else:
        status = "PASS"

    # Finding-Resolution (§27.10a) ist ein separates Closure-Gate — kein Teil der Policy-Evaluation.
    return PolicyResult(
        status=status,
        stages=results,
        blocking_failures=blocking_failures,
        major_failures=major_failures,
        minor_failures=minor_failures,  # Quelle für Execution Report §27.13.2
        major_threshold=major_threshold,
    )
```

### 27.7.2 Entscheidung

| Bedingung | Ergebnis |
|-----------|---------|
| Kein blocking FAIL UND `major_failures <= policy.major_threshold` | PASS → weiter zu Closure |
| Mindestens 1 blocking FAIL | FAIL → Feedback an Worker |
| `major_failures > policy.major_threshold` (Default: 3) | FAIL (auch ohne blocking FAIL) |

### 27.7.3 Ergebnis-Artefakt

`_temp/qa/{story_id}/decision.json` (Producer: `qa-policy-engine`)

## 27.8 Feedback-Mechanismus

### 27.8.1 Mängelliste erzeugen

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
    for artifact_id in ("llm-review", "semantic-review", "doc-fidelity"):
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

### 27.8.2 Feedback-Datei

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
      "source": "llm-review",
      "check_id": "error_handling",
      "status": "FAIL",
      "reason": "Timeout wird verschluckt",
      "description": "BrokerClient.send() fängt TimeoutException..."
    }
  ]
}
```

Der Remediation-Worker (Kap. 26.2.3) erhält diese Datei als Input.

### 27.8.3 Remediation-Loop und Max-Rounds-Eskalation

> **[Entscheidung 2026-04-09]** `feedback_rounds` wird nicht mehr im Verify-Handler inkrementiert. In v3 verwaltet die Engine `phase_memory.verify.feedback_rounds` als Carry-Forward-Akkumulator: Inkrementierung erfolgt beim Phasenwechsel verify→implementation (Remediation-Pfad), VOR Erzeugung des neuen Implementation-States. Der Verify-Handler selbst liest `verify_context: VerifyContext` aus dem VerifyPayload, schreibt aber keine Zähler. Siehe FK-20 §20.3.7.

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
  invalidiert alle zyklusgebundenen Artefakte (siehe Kap. 27.2).
  Danach laufen alle vier Verify-Schichten vollständig von vorne.

### 27.8.4 Mandatory-Target-Rueckkopplung im Remediation-Loop (FK-27-220)

Wenn ein mandatory adversarial target (Kap. 34, abgeleitet aus
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
  als `partially_resolved` bewertet (Kap. 04, §4.6.3)

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

**Provenienz:** Kap. 04, §4.6.3 (Mandatory Adversarial Targets).
Empirischer Beleg BB2-012: Der Wrong-Phase-Fall war im P3-Review
konkret benannt, wurde aber vom Adversarial Agent nicht eigenstaendig
gefunden.

## 27.9 Dokumententreue Ebene 3: Umsetzungstreue

### 27.9.1 Integration in Verify

Die Umsetzungstreue (FK-06-058) läuft als Teil der Schicht 2, über
den StructuredEvaluator:

Adapter-Vertrag (Bundle → doc_fidelity context):

| doc_fidelity context-Feld | Quelle im Bundle / Artefakt |
|--------------------------|----------------------------|
| `diff` | `bundle.diff_summary` (aus `context_dict["diff_summary"]`) |
| `entwurfsartefakt_or_concept` | `bundle.concept_excerpt` (aus `context_dict["concept_excerpt"]`) |
| `handover` | `bundle.handover` (aus `context_dict["handover"]`) |
| `drift_log` | `handover.drift_log` — aus `handover.json` geladen (§27.5a.2 `_load_handover()`) |

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

**Bei FAIL:** Story geht in den Feedback-Loop (via S2G → FAIL → §27.8).
[Korrektur 2026-04-09: Impact-Violation wird ausschließlich durch den
deterministischen Layer-1-Check `impact.violation` (§27.4.2) erkannt und
direkt zu ESCALATED eskaliert. Ein Layer-2-Doc-Fidelity-Befund führt
immer in den Feedback-Loop — es gibt keinen LLM-basierten Pfad zu ESCALATED.]

## 27.10 Closure-Phase

### 27.10.0 ClosurePayload — durable Contract Fields

> **[Entscheidung 2026-04-09]** `ClosurePayload` führt `ClosureProgress` als typisiertes Objekt mit granularen Booleans. Granularität ist notwendig, weil "nach Merge vor Issue-Close" als Recovery-Zustand eindeutig identifizierbar sein muss. Ein grobes `current_substate`-Enum würde diese Eindeutigkeit nicht liefern. Verweis auf Designwizard R1+R2 vom 2026-04-09.

`ClosurePayload` ist die phasenspezifische Payload für die Closure-Phase (diskriminierte Union, §20.3):

```python
class ClosureProgress(BaseModel):
    integrity_passed: bool = False
    merge_done: bool = False
    issue_closed: bool = False
    metrics_written: bool = False
    postflight_done: bool = False

class ClosurePayload(BaseModel):
    phase_type: Literal["closure"]
    progress: ClosureProgress = Field(default_factory=ClosureProgress)
```

`ClosureProgress` hat Recovery-Relevanz: Jedes Boolean entspricht einem abgeschlossenen Closure-Substate. Bei Crash und Wiederaufnahme (§27.10.3) überspringt der Phase Runner alle Schritte, deren Boolean bereits `true` ist.

**Granularität:** Die Einzelbooleans sind notwendig, weil Closure-Substates nicht zurückgerollt werden können (Merge ist irreversibel, Issue-Close ist ein GitHub-Seiteneffekt). Ein einziges `current_substate`-Enum würde den Zustand "nach Merge, vor Issue-Close" nicht eindeutig von "vor Merge" unterscheiden.

### 27.10.1 Voraussetzung

Closure wird nur aufgerufen wenn Verify PASS. **Ausnahme: Concept- und Research-Stories** durchlaufen keine Verify-Phase — für diese Story-Typen wird Closure direkt nach der Implementation-Phase aufgerufen. `integrity_passed` und `merge_done` werden für Concept/Research direkt auf `true` gesetzt (kein Worktree, kein Branch-Merge, §20.8.2).

**REF-034:** Für Exploration-Mode-Stories gilt: Verify läuft erst NACH der vollständigen Exploration-Phase (einschließlich Design-Review-Gate). Das Design-Review-Gate (`ExplorationGateStatus.APPROVED`) wird durch den Phase-Runner-Guard am Übergang `exploration → implementation` erzwungen (FK-20 §20.4.2a). Wenn Verify erreicht wird, ist `APPROVED` durch die State-Machine-Invariante garantiert — kein erneuter Payload-Zugriff aus der Verify-Phase nötig. [Korrektur 2026-04-09: Direkte Referenz auf `ExplorationPayload.gate_status` aus der Verify-Phase entfernt — ExplorationPayload ist nicht der aktive Payload in der Verify-Phase (aktiv: VerifyPayload). Die Garantie stammt aus dem Transition-Guard, nicht aus einem Laufzeit-Check in Verify.]

**REF-036 / §27.3a:** Die QA-Tiefe wird über `verify_context` gesteuert,
nicht über `mode`. Nach der Implementation-Phase gilt
`verify_context = VerifyContext.POST_IMPLEMENTATION`, nach einer
Remediation-Runde `verify_context = VerifyContext.POST_REMEDIATION` —
beide lösen die volle 4-Schichten-Verify aus, unabhängig davon ob
die Story im Exploration- oder Execution-Modus gestartet wurde.
[Korrektur 2026-04-09: `STRUCTURAL_ONLY_PASS` und `post_exploration`
entfernt — Verify läuft immer mit voller Pipeline (§27.3a.4).]

> **[Entscheidung 2026-04-08]** Element 17 — Alle 11 Eskalations-Trigger werden beibehalten. FK-20 §20.6.1 und FK-35 §35.4.2 normativ. Kein Trigger ist redundant.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 17.

### 27.10.2 Ablauf mit Substates

```mermaid
flowchart TD
    START(["agentkit run-phase closure<br/>--story ODIN-042"]) --> STYPE{Story-Typ?}

    STYPE -->|"impl / bugfix"| FR
    STYPE -->|"concept / research<br/>(kein Verify, kein Merge)"| CR_SUB1["Substate:<br/>integrity_passed = true<br/>merge_done = true<br/>(direkt gesetzt, §27.10.1)"]
    CR_SUB1 --> CLOSE_CR["Issue schließen<br/>(gh issue close)"]
    CLOSE_CR --> SUB3

    FR["Finding-Resolution-Gate<br/>(§27.10a)"]
    FR -->|"FAIL: Ungelöste Findings"| ESC_FR(["ESCALATED:<br/>Offene Findings."])
    FR -->|PASS| INTEGRITY

    INTEGRITY["Integrity-Gate<br/>(Pflicht-Artefakt-Vorstufe +<br/>7 Dimensionen +<br/>Telemetrie-Nachweise)"]
    INTEGRITY -->|FAIL| ESC_I(["ESCALATED:<br/>Opake Meldung.<br/>Details in Audit-Log."])
    INTEGRITY -->|PASS| SUB1["Substate:<br/>integrity_passed = true"]

    SUB1 --> MERGE["Branch mergen<br/>(git merge --ff-only)"]
    MERGE -->|Merge-Konflikt| ESC_M(["ESCALATED:<br/>Merge-Konflikt.<br/>Mensch muss intervenieren."])
    MERGE -->|Erfolg| SUB2["Substate:<br/>merge_done = true"]

    SUB2 --> TEARDOWN["Worktree aufräumen<br/>Branch löschen"]
    TEARDOWN --> CLOSE["Issue schließen<br/>(gh issue close)"]
    CLOSE --> SUB3["Substate:<br/>issue_closed = true"]

    SUB3 --> STATUS["Projektstatus: Done<br/>+ QA Rounds, Completed At"]
    STATUS --> SUB4["Substate:<br/>metrics_written = true"]

    SUB4 --> DOCTREUE4["Dokumententreue Ebene 4:<br/>Rückkopplungstreue<br/>(StructuredEvaluator)"]
    DOCTREUE4 -->|"FAIL (non-blocking)"| WARN_DT(["Warnung an Mensch<br/>(§27.14.1)"])
    DOCTREUE4 -->|"PASS"| POSTFLIGHT["Postflight-Gates"]
    WARN_DT --> POSTFLIGHT
    POSTFLIGHT -->|"FAIL (non-blocking)"| WARN_PF(["Warnung an Mensch<br/>(§27.12.2)"])
    POSTFLIGHT -->|"PASS"| SUB5["Substate:<br/>postflight_done = true"]
    WARN_PF --> SUB5

    SUB5 --> VDBSYNC["VektorDB-Sync<br/>(async, Fire-and-Forget)"]
    VDBSYNC --> GUARDS_OFF["Guards deaktivieren:<br/>Sperrdateien entfernen"]
    GUARDS_OFF --> DONE(["Story abgeschlossen"])
```

### 27.10.3 Substates und Recovery

[Entscheidung 2026-04-09: `closure_substates` ersetzt durch
`ClosurePayload.progress` (Typ `ClosureProgress`). Die fünf
Boolean-Felder liegen jetzt unter `payload.progress.*` im Phase-State.]

Die fünf ClosureProgress-Booleans markieren die kritischen Checkpoints mit Crash-Recovery-Relevanz. Weitere Schritte (Finding-Resolution-Gate, VectorDB-Sync, Guards-Off) werden nicht separat im Progress-Feld verfolgt — Finding-Resolution ist eine Vorstufe, VectorDB-Sync und Guards-Off sind idempotente Fire-and-Forget-Operationen. Bei Crash: Recovery setzt beim letzten bestätigten Fortschrittsfeld wieder an (Kap. 10.5.3).

```python
class ClosureProgress(BaseModel):
    integrity_passed: bool = False
    merge_done: bool = False
    issue_closed: bool = False
    metrics_written: bool = False
    postflight_done: bool = False

class ClosurePayload(BaseModel):
    progress: ClosureProgress
```

Im Phase-State (`phase-state.json`):

```json
"payload": {
  "progress": {
    "integrity_passed": true,
    "merge_done": true,
    "issue_closed": false,
    "metrics_written": false,
    "postflight_done": false
  }
}
```

Zugriff: `payload.progress.integrity_passed`,
`payload.progress.merge_done` etc.

Bei erneutem Aufruf von `agentkit run-phase closure`: Merge wird
übersprungen (bereits erledigt, `payload.progress.merge_done == true`),
Issue-Close wird ausgeführt.

Teardown (Worktree aufräumen, Branch löschen) ist idempotent — er wird bei jedem Recovery-Lauf mit `merge_done == true && issue_closed == false` erneut ausgeführt. Ein eigenes `teardown_done`-Feld ist nicht erforderlich, da ein fehlgeschlagener oder bereits erledigter Teardown keinen Datenverlust verursacht.

### 27.10.4 Reihenfolge ist Pflicht (FK-05-226)

Die Reihenfolge stellt sicher, dass ein Issue nie geschlossen wird,
wenn der Merge scheitert:

1. Erst Finding-Resolution-Gate (§27.10a) → sicherstellt: alle Findings vollständig aufgelöst
2. Erst Integrity-Gate → sicherstellt: Prozess wurde durchlaufen
3. Erst mergen → Code ist auf Main
4. Erst Worktree aufräumen → kein staler Worktree
5. Dann Issue schließen → fachlich abgeschlossen
6. Dann Metriken → Nachvollziehbarkeit
7. Dann Rückkopplungstreue → Doku aktuell?
8. Dann Postflight → Konsistenzprüfung
9. Dann VektorDB-Sync → für nachfolgende Stories suchbar
10. Zuletzt Guards deaktivieren → AI-Augmented-Modus wieder frei

## 27.10a Finding-Resolution als Closure-Gate (FK-27-221 bis FK-27-225)

### 27.10a.1 Prinzip

Closure blockiert, wenn mindestens ein Finding aus dem Layer-2-Output
den Resolution-Status `partially_resolved` oder `not_resolved` hat.
Es gibt keinen degradierten Modus — ein offenes Finding ist ein
harter Blocker.

**Ausnahme Concept/Research:** Für Concept- und Research-Stories
entfallen Finding-Resolution-Gate UND Integrity-Gate vollständig (kein
Layer-2-QA, kein Verify, kein Merge). `integrity_passed` und `merge_done`
werden direkt auf `true` gesetzt; der Closure-Ablauf startet effektiv
bei `issue_closed` (§27.10.2 Concept/Research-Pfad im Flowchart).

**Provenienz:** Kap. 04, §4.6. Empirischer Beleg BB2-012: Worker
markierte ein Finding als `ADDRESSED`, obwohl nur ein Teilfall
behoben war. Das System uebernahm die Teilbehebung als
Vollbehebung, weil keine andere Instanz den Finding-Status setzte.

### 27.10a.2 Quelle des Resolution-Status (FK-27-222)

Der Resolution-Status kommt ausschliesslich aus den Layer-2-QA-
Review-Checks (StructuredEvaluator im Remediation-Modus, Kap. 34).
Es gibt keine eigene Quelle und kein separates Artefakt:

- **Kanonisch:** Layer-2-Evaluator bewertet pro Finding:
  `fully_resolved`, `partially_resolved`, `not_resolved`
- **Nicht kanonisch:** Worker-Artefakte (`protocol.md`,
  `handover.json`) — diese haben Trust C und duerfen den Status
  eines Findings nicht autoritativ setzen (Kap. 04, §4.2)

Die Bewertung erfolgt als zusaetzliche Check-IDs in den bestehenden
Layer-2-Artefakten (`llm-review.json`, `semantic-review.json`, `doc-fidelity.json`, §27.5.5). Kein
neues Artefakt. [Korrektur 2026-04-09: `qa_review.json` → kanonische Artefaktnamen aus §27.5.5; Ergaenzung 2026-04-09: `doc-fidelity.json` als drittes Layer-2-Artefakt ergaenzt (§27.5.5).]

### 27.10a.3 Finding-Laden im Remediation-Zyklus (FK-27-223)

Im Remediation-Zyklus (Runde 2+) werden die Findings der Vorrunde
direkt aus den Review-Artefakten geladen, NICHT aus Worker-
Zusammenfassungen:

```python
def load_previous_findings(story_id: str, previous_cycle_id: str) -> list[dict]:
    """Laedt Findings der Vorrunde aus stale/ Review-Artefakten.

    Wichtig: Direkt aus Review-Artefakten, nicht aus Worker-
    Zusammenfassungen (BB2-012: Worker-Zusammenfassungen
    komprimieren offene Subcases weg).
    """
    stale_dir = Path(f"_temp/qa/{story_id}/stale/{previous_cycle_id}")
    findings = []
    for artifact_name in ("llm-review.json", "semantic-review.json", "doc-fidelity.json"):
        artifact_path = stale_dir / artifact_name
        if artifact_path.exists():
            artifact = json.loads(artifact_path.read_text())
            for check in artifact.get("checks", []):
                if check.get("status") == "FAIL":
                    findings.append(check)
    return findings
```

### 27.10a.4 Gate-Pruefung vor Closure (FK-27-224)

[Korrektur 2026-04-09: Die Finding-Resolution-Pruefung laeuft als
**Closure-Gate** (§27.10a.1), nicht als Teil der Policy-Evaluation
(Schicht 4). Policy-Evaluation prueft auf BLOCKING-Failures und
major_threshold — Finding-Resolution ist ein eigenstaendiger
Vorstufen-Check am Beginn der Closure-Phase, konsistent mit dem
Abschnittstitel "Finding-Resolution als Closure-Gate" und §27.7.1.]

Die Finding-Resolution-Pruefung laeuft als Closure-Gate (§27.10a.1)
— vor dem Integrity-Gate, am Beginn der Closure-Phase. Sie prueft
alle drei Layer-2-Artefakte:

```python
# [Korrektur 2026-04-09] Alle drei Layer-2-Artefakte pruefen (§27.5.5),
# konsistent mit §27.10a.3 und §27.8.1.
def check_finding_resolution(story_id: str) -> bool:
    """Prueft ob alle Findings vollstaendig aufgeloest sind.

    Returns False wenn mindestens ein Finding partially_resolved
    oder not_resolved ist.
    """
    for artifact_id in ("llm-review", "semantic-review", "doc-fidelity"):
        review = load_artifact(story_id, artifact_id)
        if review is None:
            return False  # fail-closed

        for check in review.get("checks", []):
            resolution = check.get("resolution")
            # Design-Invariante: Erstlauf (Runde 1, kein Remediation) → keine Checks haben
            # ein resolution-Feld → Gate gibt True zurück → Closure nicht blockiert.
            # Ab Runde 2 (Remediation-Modus, §27.10a.2): Checks haben resolution-Feld →
            # Gate wird aktiv. fail-closed für unbekannte/problematische Werte.
            if resolution is None:
                continue  # kein Remediation-Check, nicht prüfen
            if resolution not in ("fully_resolved", "not_applicable"):
                return False
    return True
```

### 27.10a.5 Artefakt-Invalidierung (FK-27-225)

Die Finding-Resolution ist Teil der bestehenden Layer-2-Artefakte
`llm-review.json`, `semantic-review.json` und `doc-fidelity.json` (§27.5.5) — alle drei
Artefakte sind bereits in der Invalidierungstabelle (§27.2.3)
enthalten. Eine Erweiterung der Tabelle ist daher nicht erforderlich.
[Korrektur 2026-04-09: `qa_review.json` → kanonische Artefaktnamen aus §27.5.5; Ergaenzung 2026-04-09: `doc-fidelity.json` als drittes Layer-2-Artefakt ergaenzt.]

**Querverweis:** Kap. 34 fuer die technische Erweiterung des
StructuredEvaluator um den Remediation-Modus.

## 27.11 Integrity-Gate

### 27.11.0 Pflicht-Artefakt-Pruefung (Vorstufe)

Vor der Dimensionspruefung validiert das Gate die Existenz aller
Pflicht-Artefakte. Fehlende Pflicht-Artefakte sind ein sofortiger
harter Blocker — die Dimensionspruefung wird nicht gestartet.

| Pflicht-Artefakt | FAIL bei Fehlen |
|------------------|----------------|
| `structural.json` | Structural Checks nicht ausgefuehrt |
| `decision.json` | Policy-Evaluation nicht stattgefunden |
| `context.json` | Story-Context nicht aufgebaut |

**Empirischer Beleg (BB2-012):** `decision.json` fehlte, trotzdem
lief Closure durch. Dieser Defekt wird durch die Vorstufe
verhindert. Details: Kap. 35, §35.2.3.

### 27.11.1 Sieben Dimensionen (FK-06-075 bis FK-06-081)

| Dim | Prüfgegenstand | FAIL-Code | Prüfung |
|-----|---------------|-----------|---------|
| 1 | QA-Verzeichnis existiert | `NO_QA_DIR` | `_temp/qa/{story_id}/` vorhanden |
| 2 | Context-Integrität | `CONTEXT_INVALID` | `context.json` vorhanden, `status == PASS`, hat `story_id` |
| 3 | Structural-Check-Tiefe | `STRUCTURAL_SHALLOW` | `structural.json` > 500 Bytes, >= 5 Checks, Producer = `qa-structural-check` |
| 4 | Policy-Decision | `DECISION_INVALID` | `decision.json` > 200 Bytes, hat `major_threshold`, Producer = `qa-policy-engine` |
| 5 | Semantic-Validierung | `NO_SEMANTIC` | Bei impl/bugfix: `llm-review.json` + `semantic-review.json` + `doc-fidelity.json` existieren |
| 6 | Verify-Phase | `NO_VERIFY` | Bei impl/bugfix: Abgeschlossener Verify-Phaseneintrag in `story_dir/phase-history.json` vorhanden (`phase == verify`, `status == COMPLETED`). Bei concept/research: Dimension entfällt (kein Verify). |
| 7 | Timestamp-Kausalität | `TIMESTAMP_INVERSION` | `context.json.finished_at` > `decision.json.finished_at` (Inversion: Context darf nicht nach Policy-Decision abgeschlossen sein) |

[Korrektur 2026-04-09: Dimension 6 prüft nicht das aktive `phase-state.json` (das zeigt während Closure `phase == closure`), sondern den Phasen-Abschluss-Eintrag im Phase-History-Log des Story-Verzeichnisses. Dieser wird vom Phase Runner beim Abschluss jeder Phase geschrieben.]

[Hinweis: Die Dimensionsprüfung wird story-type-abhängig gefiltert — analog zur Stage-Registry in §27.7.1. Der Integrity-Gate-Runner lädt `story_type` aus dem Phase-State und überspringt Dimensionen, die für den jeweiligen Typ nicht gelten (Dimension 5 und 6 für concept/research). Dieser Filter-Mechanismus entspricht dem Stage-Registry-Prinzip: welche Stages/Dimensionen aktiv sind, hängt vom Story-Typ ab.]

> **[Entscheidung 2026-04-08]** Element 12 — Telemetry Contract: Crash-Detection (Start/End-Paarung) essentiell. Event-Count-Vertrag auf Minimum-Schwellen ("mindestens 1 Review", "mindestens 1 Drift-Check"), keine exakten Zaehler pro Story-Groesse.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 12.

### 27.11.2 Telemetrie-Nachweise (FK-06-082 bis FK-06-091)

| Nachweis | Prüfung | FAIL-Code |
|----------|---------|-----------|
| `agent_start` mit Story-ID | Event vorhanden | `NO_AGENT_START` |
| `agent_end` mit Story-ID | Event vorhanden | `NO_AGENT_END` |
| `llm_call_complete` pro Pflicht-Rolle | Für jede konfigurierte Rolle mindestens 1 Abschluss-Event (konsistent mit guard.multi_llm §27.4.3) | `MISSING_LLM_{role}` |
| `review_compliant` | Anzahl `review_compliant` Events >= Anzahl `review_request` Events (jeder Request braucht ein Compliant) | `REVIEW_NOT_COMPLIANT` |
| Kein `integrity_violation` | 0 Events dieses Typs | `HAS_VIOLATIONS` |
| `web_call` <= Limit | Nur bei Research: Count <= `web_call_limit` | `WEB_BUDGET_EXCEEDED` |
| `adversarial_sparring` | Mindestens 1 Event (impl/bugfix Stories; concept/research: entfällt) | `NO_ADVERSARIAL_SPARRING` |
| `adversarial_test_executed` | Mindestens 1 Event (impl/bugfix Stories; concept/research: entfällt) — Nachweis dass tatsächlich getestet wurde | `NO_ADVERSARIAL_TEST_EXECUTION` |
| `preflight_request` (Pflicht) | Mindestens 1 Preflight-Turn pro Story nachgewiesen | `PREFLIGHT_MISSING` |
| `preflight_compliant` | Anzahl `preflight_compliant` Events >= Anzahl `preflight_request` Events | `PREFLIGHT_NOT_COMPLIANT` |

### 27.11.3 Opake Fehlermeldung

Bei FAIL sieht der Agent nur:

```
GOVERNANCE VIOLATION DETECTED.
Immediately stop all work. Do not attempt any further actions,
fixes, retries, or workarounds.
Report to the project owner.
```

Die konkreten FAIL-Codes werden in
`_temp/qa/{story_id}/integrity-violations.log` geschrieben
(JSON, für den Menschen lesbar).

## 27.12 Postflight-Gates

### 27.12.1 Checks (FK-05-227 bis FK-05-231)

Nach erfolgreichem Merge und Issue-Close (für Concept/Research: nach
`merge_done = true` und `issue_closed = true`, §27.10.1):

| Check | Was | FAIL wenn |
|-------|-----|----------|
| `story_dir_exists` | Story-Verzeichnis existiert mit `protocol.md` | Verzeichnis oder Protokoll fehlt |
| `issue_closed` | Issue-State == CLOSED | Issue noch offen |
| `metrics_set` | QA Rounds und Completed At gesetzt | Felder leer |
| `telemetry_complete` | `agent_start` und `agent_end` Events vorhanden | Events fehlen |
| `artifacts_complete` | Bei impl/bugfix: `structural.json`, `decision.json`, `context.json` vorhanden. Bei concept/research: nur `context.json` Pflicht (`structural.json` und `decision.json` entfallen — kein Verify). | Pflicht-Artefakte fehlen |

### 27.12.2 Postflight-FAIL

Postflight-Failure nach erfolgreichem Merge ist ein Sonderfall:
Der Code ist bereits auf Main. Ein Rollback ist nicht vorgesehen.
Stattdessen: Warnung an den Menschen, dass die Konsistenz
unvollständig ist. Der Mensch entscheidet, ob Nacharbeit nötig ist.

## 27.13 Execution Report

### 27.13.1 Zweck

Am Ende jeder Story-Bearbeitung — unabhängig vom Ergebnis (COMPLETED,
ESCALATED, FAILED) — wird ein konsolidierter Markdown-Report erzeugt:
`_temp/qa/{story_id}/execution-report.md`. Konsument ist der Mensch
(Oversight/Audit); bei erfolgreich abgeschlossenen Stories ist keine
aktive Intervention erforderlich.

### 27.13.2 Report-Sektionen

| Sektion | Inhalt |
|---------|--------|
| **Summary Table** | Story-ID, Typ, Modus, Status, Dauer, QA Rounds, Feedback Rounds, durchlaufene Verify-Schichten |
| **Failure Diagnosis** | Fehlgeschlagene Phase, primärer Fehler, Trigger — nur bei FAILED/ESCALATED |
| **Artifact Health** | Verfügbare vs. fehlende/invalide Datenquellen; Ladestatus pro Quelle |
| **Errors and Warnings** | Aggregierte Fehler und Warnungen aus allen Phasen |
| **Structural Check Results** | Ergebnisse der deterministischen Checks (Schicht 1) |
| **Policy Engine Verdict** | Aggregiertes Policy-Ergebnis mit Blocking/Major/Minor Counts |
| **Closure Sub-Step Status** | Status jedes `ClosureProgress`-Feldes (`payload.progress.integrity_passed`, `payload.progress.merge_done`, `payload.progress.issue_closed`, `payload.progress.metrics_written`, `payload.progress.postflight_done`) [Entscheidung 2026-04-09] |
| **Telemetry Event Counts** | Zähler aller relevanten Telemetrie-Events |
| **Integrity Violations Log** | Vollständiger Integrity-Violations-Auszug (falls vorhanden) |

### 27.13.3 Graceful Degradation

Jede Datenquelle ist optional. Wenn ein Artefakt fehlt oder nicht
ladbar ist, wird der Ladestatus in der Sektion "Artifact Health"
als `MISSING` oder `LOAD_ERROR` dokumentiert. Die restlichen Sektionen
werden trotzdem befüllt — der Report wird nie wegen fehlender
Einzeldaten abgebrochen.

### 27.13.4 FK-Referenz

Domänenkonzept 5.2 Closure-Phase "Execution Report".

## 27.14 Dokumententreue Ebene 4: Rückkopplungstreue

### 27.14.1 Prüfung (FK-06-059)

Nach dem Merge (bzw. nach `merge_done = true` für Concept/Research,
§27.10.1), vor Postflight. Prüft ob bestehende Dokumentation
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

**Bei FAIL:** Warnung, keine Blockade. Die Story ist bereits gemergt.
Ein FAIL erzeugt einen Incident-Kandidaten für den Failure Corpus
und eine Empfehlung an den Menschen, welche Dokumente aktualisiert
werden sollten.

## 27.15 Guard-Deaktivierung

Nach erfolgreichem Postflight:

1. Sperrdateien entfernen:
   `_temp/governance/locks/{story_id}/qa-lock.json`
2. Story-Execution-Marker entfernen:
   `_temp/governance/active/{story_id}.active`
3. Ab hier: AI-Augmented-Modus wieder aktiv (Branch-Guard inaktiv,
   Orchestrator-Guard inaktiv, QA-Schutz inaktiv)

---

*FK-Referenzen: FK-05-128 bis FK-05-214 (Verify-Phase komplett),
FK-05-215 bis FK-05-232 (Closure-Phase komplett),
FK-06-057 bis FK-06-063 (Dokumententreue Ebene 3+4),
FK-06-071 bis FK-06-094 (Integrity-Gate komplett),
FK-07-001 bis FK-07-021 (QA-Prinzipien),
FK-27-200 (Context Sufficiency Builder),
FK-27-210 (Layer-2-Konvertierung via `_run_layer2_parallel()`, kein eigenständiger Layer-2-Caller, Korrektur 2026-04-09),
FK-27-220 (Mandatory-Target-Rueckkopplung im Remediation-Loop),
FK-27-221 bis FK-27-225 (Finding-Resolution als Closure-Gate),
FK-27-250 (Verify-Kontext: QA-Tiefe ueber `verify_context`)*

**Querverweise:**
- Kap. 28 — Evidence Assembly: EvidenceAssembler, Import-Resolver, Autoritätsklassen, Request-DSL, BundleManifest, Section-aware Packing (`agentkit/core/packing.py`)
- Kap. 34 — LLM-Evaluierungen: StructuredEvaluator, ParallelEvalRunner, ContextBundle, `truncate_bundle()` Dispatcher, Evaluator-Erweiterung fuer Finding-Resolution im Remediation-Modus
- Kap. 04 §4.6 — Finding-Resolution und Remediation-Haertung (Fachkonzept-Provenienz fuer §27.10a und §27.8.4)
- Kap. 02 §"Verify-Kontext" — Verify-Kontext-Differenzierung POST_IMPLEMENTATION vs. POST_REMEDIATION (Fachkonzept-Provenienz fuer §27.3a) [Korrektur 2026-04-09: post_exploration entfällt]
- Kap. 04 §4.4a — Verify-Kontext-Differenzierung, Guard-Severity (Fachkonzept-Provenienz fuer §27.3a und §27.4.3) [Korrektur 2026-04-09: STRUCTURAL_ONLY_PASS-Invariante entfällt]
- REF-036 — Verify Layer 2 Skip Blocker (empirischer Anlass BB2-057)
- REF-035 — Context Sufficiency Builder Gaps (Loader-Vollstaendigkeit, Path-Resolution, kanonische Feldnamen, Klassifikationslogik)
