---
concept_id: FK-27
title: "Verify-Pipeline: Schichten und QA-Zyklus"
module: verify-layered-checks
domain: verify-system
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: verify-pipeline
  - scope: qa-cycle
  - scope: layered-checks
  - scope: adversarial-orchestration
  - scope: policy-evaluation
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
  - target: FK-35
    scope: integrity-gate
    reason: Integrity-Gate-Definition, 8 Dimensionen und Eskalation in FK-35 §35.2 normiert
  - target: FK-37
    scope: verify-context
    reason: VerifyContext, Context-Bundle-Vorbereitung und Section-aware Packing in FK-37
  - target: FK-29
    scope: closure-sequence
    reason: Closure-Phase, Finding-Resolution-Gate, Postflight, Execution Report und Guard-Deaktivierung in FK-29
  - target: FK-38
    scope: feedback-und-doctreue
    reason: Feedback-Mechanismus, Umsetzungstreue (Ebene 3) und Rückkopplungstreue (Ebene 4) in FK-38
  - target: FK-44
    scope: prompt-bundles
    reason: LLM-Evaluator-Prompts werden aus dem gebundenen Prompt-Bundle materialisiert (FK-44)
  - target: FK-67
    scope: artefakt-envelope
    reason: QA-Artefakte (qa_review.json, semantic_review.json, decision.json, structural.json) folgen dem Envelope-Schema und der Producer-Registry (FK-67)
supersedes: []
superseded_by:
tags: [verify, qa-cycle, adversarial-testing, policy-evaluation, layered-checks]
prose_anchor_policy: strict
formal_refs:
  - formal.deterministic-checks.entities
  - formal.deterministic-checks.state-machine
  - formal.deterministic-checks.commands
  - formal.deterministic-checks.events
  - formal.deterministic-checks.invariants
  - formal.deterministic-checks.scenarios
  - formal.implementation.entities
  - formal.implementation.invariants
  - formal.verify.entities
  - formal.verify.state-machine
  - formal.verify.commands
  - formal.verify.events
  - formal.verify.invariants
  - formal.verify.scenarios
---

# 27 — Verify-Pipeline: Schichten und QA-Zyklus

<!-- PROSE-FORMAL: formal.deterministic-checks.entities, formal.deterministic-checks.state-machine, formal.deterministic-checks.commands, formal.deterministic-checks.events, formal.deterministic-checks.invariants, formal.deterministic-checks.scenarios, formal.implementation.entities, formal.implementation.invariants, formal.verify.entities, formal.verify.state-machine, formal.verify.commands, formal.verify.events, formal.verify.invariants, formal.verify.scenarios -->

## 27.1 Zweck

Die Verify-Phase ist die maschinelle Qualitätssicherung. Sie prüft
die Implementierung in vier aufeinander aufbauenden Schichten.

Fuer `implementation_contract=integration_stabilization` bleibt die
Verify-Phase voll aktiv, erhaelt aber zusaetzlich ein dediziertes
`stability_gate` ueber Manifest, Integrationszielmatrix und
Stabilisierungsbudget.

Dateisystem-Zugriff nach Layer:
- **Schicht 1 (Skripte)**: Lese-Zugriff — Artefakt-Existenzprüfung, Build-Ergebnisse, JSON-Validierung (FK-05-128 bis FK-05-130).
- **Schicht 2 Pre-Step (ContextSufficiencyBuilder)**: Lese-Zugriff — lädt Kontext-Artefakte aus dem Story-Verzeichnis (FK-37 §37.2).
- **Schicht 2 LLM-Bewertungen**: Kein direkter Dateisystem-Zugriff — die LLM-Evaluatoren erhalten gebundelte Kontext-Daten vom ContextSufficiencyBuilder; kein eigenes Dateisystem-Lesen.
- **Schicht 3 (Adversarial Agent)**: Lese-Zugriff auf alles + Schreib-Zugriff auf Sandbox-Pfad (`_temp/adversarial/{story_id}/`).

Closure ist nicht mehr Teil dieses Dokuments. Closure-Sequenz, Integrity-Gate-Aufruf,
Merge, Issue-Close, Postflight, Execution Report und Guard-Deaktivierung sind
in FK-29 normiert. Verify-Context-Steuerung, Context-Bundle-Vorbereitung und
Section-aware Packing liegen in FK-37. Feedback-Mechanik, Umsetzungstreue und
Rückkopplungstreue liegen in FK-38.

**Abgrenzung:** Ein vollstaendiger Story-Reset ist kein Schritt der
Verify- oder Closure-Phase. Wenn Verify oder Closure in einen harten,
nicht ueber den offiziellen Workflow reparierbaren Fehler laufen,
eskaliert die Pipeline. Erst danach kann der Mensch ueber die CLI
einen `StoryResetService` ausloesen.

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
verschoben (11 Dateien).

| Artefakt | Datei |
|----------|-------|
| Semantic Review | `semantic_review.json` |
| Guardrail Check | `guardrail.json` | <!-- [Hinweis 2026-04-09] Kein aktiver Producer in §27.5 definiert — in früherer Layer-2-Architektur war ein separater Guardrail-Evaluator vorgesehen. Artefakt verbleibt in der Invalidierungs-Liste für den Fall, dass es aus einem früheren Zyklus noch existiert. -->
| Policy Decision | `decision.json` |
| LLM Review (QA-Bewertung) | `qa_review.json` |
| Umsetzungstreue | `doc_fidelity.json` |
| Feedback | `feedback.json` |
| Adversarial | `adversarial.json` |
| E2E Verify | `e2e_verify.json` | <!-- [Hinweis 2026-04-09] Kein aktiver Producer in §27.5 definiert — reserviert für eine zukünftige End-to-End-Integritätsprüfung. Artefakt verbleibt in der Invalidierungs-Liste für den Fall, dass es aus einem früheren Zyklus noch existiert. -->
| Structural | `structural.json` |
| Context | `context.json` | <!-- [Hinweis 2026-04-09] context.json ist keine Löschung — es wird vor Schicht 2 vom Phase Runner neu aufgebaut (rebuild pre-step), um dem Context Sufficiency Builder (FK-37 §37.2.6) ein aktuelles Artefakt zu liefern. Ohne diesen Rebuild wäre der Remediation-Re-Entry-Pfad nicht implementierbar. Der Eintrag in der Invalidierungs-Liste bedeutet: altes context.json wird nach stale/ verschoben, dann neu erzeugt. -->
| Context Sufficiency | `context_sufficiency.json` |

### 27.2.4 Runtime-Staleness-Check

`artifact_matches_current_cycle()` prüft bei jedem Artefakt-Zugriff,
ob das eingebettete `qa_cycle_id` mit dem aktuellen Zyklus
übereinstimmt. Bei Mismatch: **fail-closed** — das Artefakt wird
abgelehnt, als wäre es nicht vorhanden.

### 27.2.5 FK-Referenz

Domänenkonzept 5.2 "Atomarer QA-Zyklus".

## 27.2a Eskalation versus Story-Reset

Verify oder Closure koennen in `ESCALATED` enden, wenn Standardpfade
wie Remediation, offizieller Closure-Retry oder `--no-ff`-Fallback den
Sachverhalt nicht mehr sauber beherrschen.

**Normative Regeln:**

1. `ESCALATED` fuehrt nicht automatisch zu einem Story-Reset.
2. Der Orchestrator darf einen Reset nur empfehlen oder dokumentieren.
3. Die Ausfuehrung eines vollstaendigen Resets erfolgt ausschliesslich
   durch einen menschlichen CLI-Befehl gegen den `StoryResetService`.
4. Vor einem Reset muss die bisherige Umsetzung als korrupt oder
   fachlich unbrauchbar bewertet sein; ein Reset ist kein Routinepfad
   fuer gewoehnliche Verify-Fails.

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

    FB --> WORKER["→ Zurück zu Implementation<br/>(Feedback-Loop, FK-20 §20.5)"]
```

[Hinweis: Für concept/research-Stories: `integrity_passed` und `merge_done` werden direkt auf `true` gesetzt (kein Worktree, kein Branch-Merge). Finding-Resolution-Gate und Integrity-Gate entfallen vollständig. Der Closure-Ablauf geht direkt von `issue_closed` weiter (FK-29 §29.2.1).]

[Hinweis: Das Flowchart zeigt den **logischen** Ablauf. Schicht 3 (Adversarial) ist kein synchroner Inline-Schritt — der Phase Runner setzt `agents_to_spawn` und der Orchestrator spawnt den Adversarial-Agenten extern (§27.6.1). Der Gesamtfluss (S2G → Schicht 3 → S4) beschreibt die fachliche Reihenfolge, nicht den mechanischen Ablauf.]

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
| `impact.violation` | Impact | Tatsächlicher Impact ≤ deklarierter Impact (FK-23 §23.8). **Reaktion:** Impact-Violation → ESCALATED (Eskalation an Mensch, kein Rücksprung zur Exploration-Phase). [Korrektur 2026-04-09: Modus-abhängige Reaktion entfällt — Impact-Violation führt immer zu ESCALATED, analog FK-20 und FK-23.] | BLOCKING |

### 27.4.3 Recurring Guards (Telemetrie-basiert)

Prüfen den Prozess, nicht die fachliche Lösung. Laufen parallel
zu den Structural Checks:

| Check-ID | Was | Quelle | Severity |
|----------|-----|--------|----------|
| `guard.llm_reviews` | Pflicht-Reviews durchgeführt (mindestens 1 `review_request`-Event; kein größenabhängiger exakter Zähler — konsistent mit FK-35 §35.2.5 Minimum-Schwellen-Vertrag der Telemetrie-Korrelation) | Telemetrie: `review_request` Events zählen | **BLOCKING** |
| `guard.review_compliance` | Reviews über freigegebene Templates | Telemetrie: `review_compliant` Events | MAJOR |
| `guard.no_violations` | Keine Guard-Verletzungen während der Bearbeitung | Telemetrie: keine `integrity_violation` Events | BLOCKING |
| `guard.multi_llm` | Alle konfigurierten Pflicht-Reviewer mit Ergebnis abgeschlossen | Telemetrie: `llm_call_complete` Events mit passenden `pool`/`role` Werten. **`llm_call_complete` darf erst nach erfolgreichem Schreiben des Review-Artefakts (§27.5.5) emittiert werden** — nicht bei bloßer API-Antwort. Fängt "Review gestartet, nie abgeschlossen" (FK-37 §37.1.6). | **BLOCKING** |

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
[Korrektur 2026-04-09: "Zwei" → "Drei" — Schicht 2 umfasst drei parallele LLM-Bewertungen: QA-Bewertung, Semantic Review, Umsetzungstreue (FK-38 §38.2.1).]

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

- `_temp/qa/{story_id}/qa_review.json` (Producer: `qa-llm-review`)
- `_temp/qa/{story_id}/semantic_review.json` (Producer: `qa-semantic-review`)
- `_temp/qa/{story_id}/doc_fidelity.json` (Producer: `qa-doc-fidelity`)

[Ergänzung 2026-04-09: `doc_fidelity.json` als drittes Layer-2-Artefakt ergänzt — Umsetzungstreue (FK-38 §38.2.1) schreibt Ergebnis in `doc_fidelity.json` (Rolle: `doc_fidelity`).]

> **[Entscheidung 2026-04-08]** Element 27 — Context Sufficiency Builder ist Pflicht-Gate VOR dem Review: stellt sicher dass genuegend Informationen vorhanden sind. Wenn nicht → Informationen zusammentragen, NICHT Review ueberspringen. Reviews finden IMMER statt.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 27.

Detailausgliederungen aus dieser Schicht 2:

- Context-Bundle-Vorbereitung, Sufficiency-Klassifikation und
  Ablauf in `_run_layer2_parallel()`: **FK-37 §37.2**
- Konvertierung `ContextBundle → dict[str, str]` und Section-aware
  Packing: **FK-37 §37.3**
- Verify-Context-Steuerung (`POST_IMPLEMENTATION` /
  `POST_REMEDIATION`) und HARD-BLOCKER-Garantie für fehlende
  LLM-Reviews: **FK-37 §37.1**
- Umsetzungstreue (Dokumententreue Ebene 3) und ihre Eingliederung
  in Schicht 2: **FK-38 §38.2**

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
"_temp/qa/ODIN-042/qa_review.json",
"_temp/qa/ODIN-042/semantic_review.json",
"_temp/qa/ODIN-042/doc_fidelity.json"
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
- Write-Scoping über CCAG-Regel (FK-02 §02.7, FK-15 §15.4.2)

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

Die Policy-Engine (FK-02 §02.9) aggregiert die Ergebnisse aller
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

    # Finding-Resolution (FK-29 §29.2) ist ein separates Closure-Gate — kein Teil der Policy-Evaluation.
    return PolicyResult(
        status=status,
        stages=results,
        blocking_failures=blocking_failures,
        major_failures=major_failures,
        minor_failures=minor_failures,  # Quelle für Execution Report (FK-29 §29.4.2)
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

---

*FK-Referenzen: FK-05-128 bis FK-05-214 (Verify-Phase komplett),
FK-06-057 bis FK-06-058 (Dokumententreue Ebene 3 — Detail in FK-38),
FK-07-001 bis FK-07-021 (QA-Prinzipien),
FK-27-051 (Konsolidierungsverbot Test-Suite)*

**Querverweise:**
- FK-29 — Closure-Sequence: Finding-Resolution-Gate, Integrity-Gate-Aufruf, Merge, Postflight, Execution Report, Guard-Deaktivierung
- FK-37 — Verify-Context und QA-Bundle-Vorbereitung: VerifyContext, ContextSufficiencyBuilder, Section-aware Packing, HARD-BLOCKER-Garantie
- FK-38 — Verify-Feedback und Dokumententreue-Schleife: Feedback-Mechanismus, Mandatory-Target-Rückkopplung, Umsetzungstreue (Ebene 3), Rückkopplungstreue (Ebene 4)
- FK-35 — Integrity-Gate (Definitions-Owner), 8 Dimensionen und Eskalation
- FK-28 — Evidence Assembly: EvidenceAssembler, Import-Resolver, Autoritätsklassen, Request-DSL, BundleManifest, Section-aware Packing-Modul (`agentkit/core/packing.py`)
- FK-34 — LLM-Evaluierungen: StructuredEvaluator, ParallelEvalRunner, ContextBundle, `truncate_bundle()` Dispatcher, Evaluator-Erweiterung fuer Finding-Resolution im Remediation-Modus
- DK-04 §4.4a — Verify-Kontext-Differenzierung, Guard-Severity (Fachkonzept-Provenienz fuer FK-37 §37.1 und §27.4.3) [Korrektur 2026-04-09: STRUCTURAL_ONLY_PASS-Invariante entfällt]
- REF-036 — Verify Layer 2 Skip Blocker (empirischer Anlass BB2-057)
