---
concept_id: FK-37
title: Verify-Context und QA-Bundle-Vorbereitung
module: verify-context
domain: verify-system
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: verify-context
  - scope: context-bundle
  - scope: context-sufficiency
  - scope: bundle-packing
defers_to:
  - target: FK-27
    scope: verify-pipeline
    reason: QA-Schichten und QA-Zyklus sind in FK-27 definiert; FK-37 liefert nur die Bundle-Vorbereitung VOR Layer 2
  - target: FK-20
    scope: workflow-engine
    reason: Workflow-Engine-Mechanik und Phasenmodell liegen in FK-20
  - target: FK-39
    scope: verify-payload
    reason: VerifyPayload und PhaseMemory.verify.feedback_rounds sind in FK-39 normiert
  - target: FK-26
    scope: handover-paket
    reason: Bundle-Felder werden u.a. aus dem Worker-Handover geladen
  - target: FK-28
    scope: evidence-assembly
    reason: Evidence-Manifest und Section-aware Packing-Modul liegen bei FK-28
  - target: FK-34
    scope: parallel-eval-runner
    reason: ParallelEvalRunner und StructuredEvaluator sind FK-34
  - target: FK-21
    scope: external-sources
    reason: Externe Quellen-Auflösung in FK-21 §21.3.3
  - target: FK-23
    scope: integration-stabilization
    reason: Vertragsprofil integration_stabilization wird in FK-23 fachlich beschrieben
supersedes: []
superseded_by:
tags: [verify, verify-context, context-bundle, context-sufficiency, bundle-packing, integration-stabilization]
prose_anchor_policy: strict
formal_refs:
  - formal.verify.state-machine
  - formal.verify.invariants
  - formal.integration-stabilization.state-machine
  - formal.integration-stabilization.commands
  - formal.integration-stabilization.events
  - formal.integration-stabilization.invariants
  - formal.integration-stabilization.scenarios
---

# 37 — Verify-Context und QA-Bundle-Vorbereitung

<!-- PROSE-FORMAL: formal.verify.state-machine, formal.verify.invariants, formal.integration-stabilization.state-machine, formal.integration-stabilization.commands, formal.integration-stabilization.events, formal.integration-stabilization.invariants, formal.integration-stabilization.scenarios -->

## 37.1 Verify-Kontext: QA-Tiefe über `verify_context` (FK-27-250)

> **[Entscheidung 2026-04-09]** `verify_context` wird als typisiertes `VerifyContext`-Feld auf `VerifyPayload` (diskriminierte Union, FK-39 §39.2.3) geführt statt als freier String auf dem flachen PhaseState. `VerifyContext` ist ein StrEnum: `POST_IMPLEMENTATION | POST_REMEDIATION`. Steuert die QA-Tiefe normativ. Verweis auf Designwizard R1+R2 vom 2026-04-09.

### 37.1.0 VerifyPayload — durable Contract Fields

`VerifyPayload` ist die phasenspezifische Payload für den Verify-Eintritt (diskriminierte Union, FK-39 §39.2.3):

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

[Korrektur 2026-04-09: "Exploration-Phase abgeschlossen" als Trigger entfernt — Verify wird nie direkt nach Exploration aufgerufen (§37.1.1, FK-29 §29.1.1).]

**Nicht in VerifyPayload:** `feedback_rounds` — dieser Zähler lebt in `PhaseMemory.verify.feedback_rounds` (FK-39 §39.5, carry-forward über Phasenwechsel).

### 37.1.1 Problem: `mode` ist kein hinreichender Diskriminator

Das Feld `mode` wird in der Setup-Phase gesetzt und bleibt über den
gesamten Story-Lifecycle konstant. Verify läuft ausschließlich nach
der Implementation-Phase (volle 4-Schichten-QA) oder nach einer
Remediation-Runde (erneut volle 4-Schichten-QA). Wenn die Pipeline
nur `mode` auswertet, werden Layer 2–4 für ALLE Verify-Durchläufe
übersprungen — ein kritischer Governance-Fehler.
[Korrektur 2026-04-09: post_exploration entfernt — Dokumententreue-Prüfung
nach Exploration ist Teil der Exploration-Phase selbst (FK-23 §23.5), nicht via Verify.]

**Empirischer Anlass (BB2-057):** Eine Implementation-Story im
Exploration Mode wurde nach der Implementation ohne ein einziges
LLM-Review durchgewunken. Ursache: Der Phase Runner verwendete
`mode == "exploration"` als Trigger für den Structural-Only-Pfad —
unabhängig davon, welche Phase gerade verifiziert wurde. Der
Orchestrator handelte korrekt nach Phase-State-Vertrag: COMPLETED +
leere `agents_to_spawn` → Closure. Der Bug lag zu 100% im
deterministischen Code (Phase Runner), nicht im nicht-deterministischen
Orchestrator.

### 37.1.2 Lösung: `verify_context`-Feld im Phase-State

Ein dediziertes Feld `verify_context` im Phase-State identifiziert,
in welchem Kontext der aktuelle Verify-Durchlauf stattfindet. Der
Phase Runner setzt `verify_context` basierend auf dem Auslöser:

[Entscheidung 2026-04-09: VerifyContext ist jetzt ein StrEnum mit genau zwei Werten.
`post_exploration` entfällt — Dokumententreue nach Exploration läuft in der
Exploration-Phase selbst (FK-23 §23.5). `STRUCTURAL_ONLY_PASS` entfällt ebenfalls.]

| `verify_context` | Auslöser | QA-Tiefe | Begründung |
|------------------|----------|----------|------------|
| `VerifyContext.POST_IMPLEMENTATION` | Verify nach abgeschlossener Implementation-Phase | Volle 4-Schichten-QA (Structural, Semantisch, Adversarial, Policy). | Primärer QA-Durchlauf — unabhängig davon, ob `mode = "exploration"` oder `mode = "execution"`. |
| `VerifyContext.POST_REMEDIATION` | Verify nach einer Remediation-Runde | Volle 4-Schichten-QA (Structural, Semantisch, Adversarial, Policy). | Erneuter vollständiger QA-Durchlauf nach Worker-Remediation — identische Prüftiefe wie nach Implementation. |

### 37.1.3 Vertragsprofil `integration_stabilization`

Wenn `story_type=implementation` und
`implementation_contract=integration_stabilization`, gelten zusaetzlich
zu den normalen Verify-Schichten diese Pflichtpruefungen:

- `integration_target_matrix_passed`
- `declared_surfaces_only`
- `stabilization_budget_not_exhausted`
- `stability_gate`

Ein PASS der normalen Verify-Schichten allein reicht in diesem
Vertrag nicht fuer Closure.

**Schichtzuordnung:**

- `declared_surfaces_only` gehoert in die deterministische
  Schicht-1-Pruefung
- `stabilization_budget_not_exhausted` ist primaer ein
  Hook-/Capability-Enforcement und wird in Verify nur noch auditierend
  gegengeprueft
- `integration_target_matrix_passed` und `stability_gate` sind
  zusaetzliche Verify-/Closure-Preconditions

### 37.1.4 Entscheidungsregel

[Entscheidung 2026-04-09: Code-Beispiel auf VerifyContext StrEnum umgestellt.
`post_exploration`-Zweig und `STRUCTURAL_ONLY_PASS` entfernt.]

[Korrektur 2026-04-09: PAUSED/agents_to_spawn/RUN_SEMANTIC entfernt —
Layer 2 laeuft vollstaendig intern im Phase Runner (ThreadPoolExecutor),
kein Orchestrator-Roundtrip, kein PAUSED-Zustand in Verify.]

```python
# Im Phase Runner — Verify-Einstieg:
# [Entscheidung 2026-04-09] VerifyContext ist ein StrEnum, kein String-Literal.
# [Korrektur 2026-04-09] Layer 2 laeuft intern im Phase Runner (ThreadPoolExecutor),
# kein Orchestrator-Roundtrip. Layer 3 (Adversarial) spawnt externen Agenten (§37.1.5).

if state.verify_context is None:
    # fail-closed (§37.1.0): kein Verify-Lauf ohne bekannten Kontext
    return PhaseResult(status="ESCALATED", reason="Missing verify_context — Phase Runner Defekt")

if state.verify_context in (
    VerifyContext.POST_IMPLEMENTATION,
    VerifyContext.POST_REMEDIATION,
):
    # Volle 4-Schichten-QA, UNABHAENGIG von state.mode

    # Schicht 1: Deterministische Checks (Layer-1-Orchestrierung, FK-27 §27.4)
    # run_structural_checks() orchestriert alle 4 parallelen Layer-1-Zweige:
    #   (1) Artefakt-Prüfung (FK-27 §27.4.1)
    #   (2) Structural Checks (FK-27 §27.4.2)
    #   (3) Recurring Guards (FK-27 §27.4.3)
    #   (4) ARE-Gate (FK-27 §27.4.4, optional)
    # Impact-Violation (FK-27 §27.4.2) führt zu sofortigem ESCALATED (kein Feedback-Loop).
    # Stoppt NUR bei BLOCKING-FAIL. MAJOR/MINOR Findings laufen durch zu Schicht 2.
    result = run_structural_checks(state)
    if result.has_blocking_failure():  # NUR BLOCKING-FAIL stoppt (FK-27 §27.4.5)
        return _handle_verify_failure(state, result)

    # Schicht 2: LLM-Bewertungen — intern via ThreadPoolExecutor
    # Phase Runner ruft externe LLMs direkt auf (kein Orchestrator,
    # kein PAUSED, kein agents_to_spawn). Ergebnisse als JSON persistiert.
    layer2_results = _run_layer2_parallel(context)  # ThreadPoolExecutor
    # -> qa_review.json, semantic_review.json, doc_fidelity.json (FK-27 §27.5.5)
    # Stoppt bei FAIL. PASS_WITH_CONCERNS blockiert NICHT (FK-27 §27.5.4).
    if layer2_results.has_failure():  # NUR FAIL stoppt, nicht PASS_WITH_CONCERNS
        return _handle_verify_failure(state, layer2_results)

    # Schicht 3: Adversarial Testing (Agent-Spawn via Orchestrator, FK-27 §27.6.1)
    # Steuerungsvertrag (qa_cycle_status, kanonischer Feldname, FK-27 §27.2.2 / FK-38 §38.1.3):
    #   Phase Runner setzt agents_to_spawn + speichert State (qa_cycle_status = awaiting_qa).
    #   Orchestrator spawnt Adversarial Agent; dieser schreibt adversarial.json.
    #   Phase Runner wird re-entered wenn adversarial.json vorliegt → qa_cycle_status = awaiting_policy.
    # Schicht 4: Policy-Evaluation (deterministisch, FK-27 §27.7.1):
    #   → PASS: qa_cycle_status = pass
    #   → FAIL (remediable): qa_cycle_status = awaiting_remediation (Feedback-Loop, FK-27 §27.2.2)
    #   → FAIL (impact.violation oder max_rounds_exceeded): qa_cycle_status = escalated
```

**Invariante:** Beide `VerifyContext`-Werte (`POST_IMPLEMENTATION`,
`POST_REMEDIATION`) lösen IMMER die volle 4-Schichten-QA aus,
unabhängig von `mode`. Es gibt keinen Structural-only-Verify-Pfad.

### 37.1.5 Invariante: Verify läuft immer mit voller 4-Schichten-Pipeline

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
3. Schicht 3: Adversarial Testing — extern, via `agents_to_spawn` (FK-27 §27.6.1)
4. Schicht 4: Policy-Evaluation

[Korrektur 2026-04-09: "Verify ist atomar" bezieht sich nur auf Layer 2 — Layer 3 (Adversarial) spawnt weiterhin einen externen Agenten via Orchestrator (FK-27 §27.6.1), da Dateisystem-Zugriff und Subprocess-Ausführung erforderlich sind.]

Layer 2 (LLM-Bewertungen) läuft vollständig intern im Phase Runner
via `ThreadPoolExecutor` — kein Orchestrator-Roundtrip, kein
PAUSED-Zustand. Layer 3 (Adversarial) hingegen spawnt einen externen
Agenten über `agents_to_spawn` (FK-27 §27.6.1), da dieser Dateisystem-Zugriff
und Subprocess-Ausführung benötigt — beides liegt außerhalb der
Fähigkeiten eines einfachen LLM-Aufrufs. Verify ist damit für Layer 2
nicht-unterbrechend, für Layer 3 jedoch Orchestrator-vermittelt.

Die LLM-Ergebnisse (Layer 2) werden als parsebares JSON persistiert
(`qa_review.json`, `semantic_review.json`, `doc_fidelity.json`). Es gibt keinen
PAUSED-Zwischenstatus, kein `agents_to_spawn` fuer Layer 2 und kein
`RUN_SEMANTIC`-Ergebnis fuer Layer 2. Der PauseReason-Enum hat nur
drei Werte (AWAITING_DESIGN_REVIEW, AWAITING_DESIGN_CHALLENGE,
GOVERNANCE_INCIDENT) — keiner davon gilt fuer Layer 2.

### 37.1.6 Fehlende LLM-Reviews sind ein HARD BLOCKER

Fehlende LLM-Reviews bei Implementation- und Bugfix-Stories sind ein
HARD BLOCKER, kein Warning. Zwei unabhängige Gates stellen dies sicher:

- **Gate 1 (`guard.llm_reviews`):** Wurden Reviews überhaupt
  angefordert? 0 `review_request` Events bei Implementation/Bugfix →
  sofortiger FAIL in Layer 1 (Recurring Guards, FK-27 §27.4.3).
- **Gate 2 (`guard.multi_llm`):** Liegen für ALLE mandatory Reviewer
  (qa_review, semantic_review, doc_fidelity) Telemetrie-Evidenzen vor? Gate 2 ist
  UNABHÄNGIG von Gate 1 — auch wenn Reviews angefordert wurden
  (Gate 1 bestanden), müssen die Ergebnisse vorliegen. Fängt den
  Fall: "Reviews gestartet, aber nie abgeschlossen oder ohne Ergebnis
  beendet".

Beide Gates sind als BLOCKING klassifiziert (nicht WARNING/MAJOR) und
dürfen NICHT zu einem einzigen Gate zusammengefasst werden (siehe
FK-27 §27.4.3).

[Korrektur 2026-04-09: guard.llm_reviews und guard.multi_llm sind Schicht-1-Checks (FK-27 §27.4.3), kein Layer-4-Gate. Ein BLOCKING-FAIL in Schicht 1 stoppt die Pipeline, Layer 4 wird nicht erreicht.]

**Provenienz:** REF-036, Domänenkonzept 4.4a.

## 37.2 Context Sufficiency Builder (Pre-Step Schicht 2)

### 37.2.1 Zweck (FK-27-200)

Zusätzlich zur bestehenden Schicht 2 (FK-27 §27.5) wird ab Version 3.0
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

### 37.2.2 Prüfungen

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

### 37.2.3 Sufficiency-Klassifikation

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
haben keine dedizierten Structural Checks in FK-27 §27.4.1 (der prüft nur
Worker-Artefakte: protocol.md, worker-manifest, manifest-claims,
handover.json). Fehlt `story_spec` oder `diff_summary`, führt das
zur Einstufung `partially_reviewable` und einer Warning — Layer 2
läuft trotzdem weiter (fail-open für Sufficiency). Reviews dürfen
nicht wegen fehlender Kontexte übersprungen werden.

### 37.2.4 Enrichment

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
  diese Quelle benötigen (FK-21 §21.3.3). [Hinweis: `external_sources`
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

### 37.2.5 Ergebnis-Artefakt

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

### 37.2.6 Ablauf in _run_layer2_parallel()

```python
# In _run_layer2_parallel() des Phase Runners:

from agentkit.qa.context_sufficiency import ContextSufficiencyBuilder, SufficiencyLevel
from agentkit.core.packing import pack_markdown, pack_code

# 0. context.json rebuild (Remediation-Re-Entry-Pflicht, FK-27 §27.2.3):
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

# 4. Per-Feld Packing (§37.3)
context_dict = _pack_and_convert(enriched_bundle)

# 5. ParallelEvalRunner starten
runner.run(context=context_dict, ...)
```

> **[Entscheidung 2026-04-08]** Element 28 — Section-aware Bundle-Packing ist Pflicht. FK-34-121 normativ. In v2 bereits implementiert.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 28.

## 37.3 Konvertierungs-Verantwortung und Section-aware Packing

### 37.3.1 Design-Entscheidung D7: Domänen-Abstraktion vs. Transport-Schicht (FK-27-210)

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

### 37.3.2 Konvertierung in _run_layer2_parallel()

`BUNDLE_TOKEN_LIMIT`: Maximale Zeichenanzahl pro Bundle-Feld nach dem Packing.
Default: 32.000 Zeichen (konfigurierbar in `pipeline.yaml` unter `layer2.bundle_token_limit`).
Referenz: §37.2.2 `diff_summary` Trunkierungsbeispiel (84.979 → 32.000).

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

### 37.3.3 Section-aware Packing (FK-28, Modul `agentkit/core/packing.py`)

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

[Hinweis: `_pack_and_convert()` (§37.3.2) ruft die Packer direkt auf —
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

### 37.3.4 Evaluator-rollenspezifische Prioritäten

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
> [Scope-Begrenzung FK-37 (2026-04-29): FK-37 dokumentiert die drei festen parallelen Evaluatoren (QA, Semantic, Umsetzungstreue) ohne Tiebreaker-Mechanismus. Die Quorum/Divergenz-Logik (Divergenzbedingung, Tiebreak-Reviewer, Aggregationsregel) ist normativ nach FK-34 ausgelagert und implementierbar erst wenn FK-34 diese Verträge definiert. Bis dahin gilt: alle drei Evaluatoren müssen PASS liefern, FAIL in einem Evaluator → gesamte Schicht 2 FAIL (kein Tiebreaker).]
