---
concept_id: FK-90
title: Schema-Katalog
module: schema-catalog
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: schema-catalog
defers_to:
  - FK-18
  - FK-59
supersedes: []
superseded_by:
tags: [schema, json-schema, katalog, referenz]
prose_anchor_policy: strict
formal_refs:
  - formal.state-storage.entities
  - formal.state-storage.invariants
  - formal.principal-capabilities.entities
  - formal.principal-capabilities.invariants
  - formal.integration-stabilization.entities
  - formal.story-exit.entities
  - formal.story-contracts.entities
  - formal.story-contracts.invariants
---

# 90 — Schema-Katalog

<!-- PROSE-FORMAL: formal.state-storage.entities, formal.state-storage.invariants, formal.principal-capabilities.entities, formal.principal-capabilities.invariants, formal.integration-stabilization.entities, formal.story-exit.entities, formal.story-contracts.entities, formal.story-contracts.invariants -->

## 90.1 Übersicht

**Schema-Owner in v3: Pydantic-Modelle + Contract-Tests.**

Die v3-Linie ersetzt den dateibasierten JSON-Schema-Katalog durch
typisierte Pydantic-v2-Modelle in `src/agentkit/` als einzige
normative Schema-Quelle. Es gibt **keinen** FK-90-Stage-Artefakt-Schema-Katalog
(`{stage_id}.schema.json`-Dateien) im Repository. Die einzige
`*.schema.json`-Datei im Repo ist ein unverwandtes Harness-Test-Fixture
(`tests/fixtures/harness_post_tool/codex_post_tool_use.command.input.schema.json`);
sie gehoert nicht zum FK-90-Schema-Katalog und ist kein Stage-Artefakt-Schema.
Dieser Zustand ist gewollt und entspricht dem
Architekturziel "typisierte Modelle statt JSON-Wildwuchs" (CLAUDE.md
SINGLE SOURCE OF TRUTH, FK-02 §2.1 Artefakt-Definition).

**Stabilitaetsanker:** Contract-Tests in `tests/contract/` fixieren die
Schema-Stabilitaet verbindlich:

- `tests/contract/artifacts/test_envelope_schema.py` — Envelope-Modell
- `tests/contract/implementation/test_handover_schema.py` — Handover-Artefakt
- `tests/contract/implementation/test_worker_manifest.py` — Worker-Manifest

Neue Artefaktklassen werden als Pydantic-v2-Modell unter
`src/agentkit/artifacts/` angelegt und durch einen Contract-Test in
`tests/contract/` abgesichert. Eine parallele `.schema.json`-Datei wird
nicht erzeugt.

**Owning-Chapter-Referenz:** Die folgende Tabelle listet die Artefaktklassen
mit dem Pydantic-Modell-Modul als Schema-Owner und dem Owning-Chapter
als fachliche Referenz.

| Artefaktklasse | Pydantic-Modul (Schema-Owner) | Owning Chapter | Beschreibung |
|----------------|-------------------------------|---------------|-------------|
| Envelope | `artifacts.envelope` | 02 | Gemeinsame Metadaten aller QA-Artefakte |
| Context | `story_context_manager.models` | 22 | Story-Context (autoritativer Snapshot) |
| Structural | `verify_system.structural.checker` | 33 | Deterministische Check-Ergebnisse (kein eigenstaendiges models.py; Owner ist StructuralChecker in checker.py) |
| QA-Review | `verify_system.llm_evaluator.reviewer` | 34 | LLM-Bewertung (12 Checks); Reviewer-Klasse: QaReviewReviewer |
| Semantic-Review | `verify_system.llm_evaluator.reviewer` | 34 | Systemische Angemessenheit; Reviewer-Klasse: SemanticReviewer |
| Doc-Fidelity | `verify_system.conformance_service.models` | 32 | Umsetzungstreue; FidelityResult + VerifyDecision |
| Adversarial | `verify_system.adversarial_orchestrator.runtime.models` | 34 | Adversarial-Testing-Ergebnisse; AdversarialResultArtifact |
| Policy | `verify_system.policy_engine.engine` | 33 | Policy-Entscheidung; VerifyDecision + PolicyEngine |
| Closure | `pipeline_engine.phase_executor.models` | 25 | Closure-Ergebnis mit Metriken; ClosureProgress + ClosurePayload |
| Phase-State | `pipeline_engine.phase_executor.models` | 20 | Pipeline-Zustand; PhaseState |
| Worker-Manifest | `implementation.manifest.manifest` | 24 | Technische Worker-Deklaration; WorkerManifest |
| Handover | `implementation.handover.packager` | 24 | Fachliche Uebergabe an Verify; HandoverData |
| Entwurfsartefakt | `exploration.change_frame` | 23 | Change-Frame (Exploration); ChangeFrame |
| Bugfix-Reproducer | `verify_system.structural.checks.bugfix_checks` | 24 | Bugfix-Reproducer (kein eigenstaendiges Artefaktmodell; Owner ist bugfix_checks) |
| Guardrail | `verify_system.structural.checker` | 33 | Guardrail-Pruefung; Owner ist StructuralChecker in checker.py |
| ARE-Evidence | `requirements_coverage.models` | 40 | ARE-Evidence-Einreichung |
| Story-Reset-Record | `story_reset.models` | 53 | Auditierbarer Reset-Vorgang |
| Story-Split-Plan | `story_split.models` | 54 | Menschlich freigegebener Plan fuer Nachfolger, Rebinding und Cancel-Pfad |
| Story-Split-Record | `story_split.models` | 54 | Auditierbarer Split-Vorgang |
| Capability-Freeze-Record | `governance.ccag.rules` | 55 | Storybezogener Freeze bei HARD-STOP-/Normkonflikten; CcagRule |
| Conflict-Resolution-Record | `governance.ccag.rules` | 55 | Auditierbare menschliche oder offizielle Konfliktaufloesung; CcagRule |
| Permission-Request-Record | `governance.ccag.requests` | 55 | Auditierbarer Einzelfall fuer unbekannte Freigaben mit TTL und Resolution; PermissionRequest |
| Permission-Lease-Record | `governance.ccag.leases` | 55 | Befristete, story-/run-scoped Freigabe ausserhalb einer Dauerregel; PermissionLease |
| Integration-Scope-Manifest | governance.ccag (Story-Typ-Enum; kein eigenstaendiges Artefaktmodell in HEAD) | 57 | Freigegebener Integrationsraum fuer systemische E2E-/Stabilisierungsstories |
| Manifest-Approval-Record | governance.ccag (kein eigenstaendiges Artefaktmodell in HEAD) | 57 | Attestierte menschliche oder administrative Freigabe eines Integrations-Manifests |
| Stabilization-Budget | governance.ccag (kein eigenstaendiges Artefaktmodell in HEAD) | 57 | Harte Schleifen-, Surface- und Regressionsgrenzen fuer Integrationsstabilisierung |
| Story-Exit-Record | `story_exit.models` | 58 | Audit-Record fuer administrativen Story-Exit in Human-Takeover |
| Exit-Manifest-Snapshot | `story_exit.models` | 58 | Letzter gebundener Story-/Manifest-/Budget-Stand beim Exit |
| ARE-Gate-Result | `requirements_coverage.models` | 40 | ARE-Gate-Pruefergebnis |
| Concept-Feedback | verify_system.stage_registry (Stage-ID; kein eigenstaendiges Artefaktmodell in HEAD) | 24 | Konzept-Feedback-Loop-Ergebnis |
| Incident | `failure_corpus.incident` | 41 | Failure-Corpus-Incident; Incident (BaseModel) |
| Pattern | `failure_corpus.pattern` | 41 | Failure-Corpus-Pattern; FailurePatternRecord |
| Check-Proposal | `failure_corpus.top` | 41 | Failure-Corpus-Check-Proposal; CheckProposal |
| Story-Search-Result | `integrations.vectordb.weaviate_adapter` | 13 | VektorDB-Suchergebnisse; StorySearchHit |
| Feedback | `verify_system.remediation.feedback` | 25 | Maengelliste fuer Remediation; RemediationFeedback |
| Governance-Adjudication | `governance.governance_observer.models` | 35 | Incident-Klassifikation; GovernanceAdjudicationVerdict |

Der relationale PostgreSQL-State gehoert bewusst nicht in diesen
Artefaktkatalog. Fuer den kanonischen Speicherschnitt sind FK-18
und `formal.state-storage.*` massgeblich.

Konsolidierte Vertragsregel gemaess FK-59:

- `story_type` und `implementation_contract` sind kanonische
  Story-Vertragsfelder
- `operating_mode` ist **kein** kanonisches Story-Hauptfeld
- `exit_class` ist **kein** freies Story-Hauptfeld, sondern nur in
  offiziellen Exit-/Split-/Reset-Records zulaessig

## 90.2 Namenskonvention

**Pydantic-Modell als Schema-Owner:** In v3 ist das Pydantic-v2-Modell
die einzig normative Schema-Quelle. Artefaktdateien im Dateisystem
(z. B. als optionaler JSON-Export) erhalten den Namen des Stage-Kontexts
(z. B. `structural.json`, `qa_review.json`), aber es gibt keine
korrespondierenden `.schema.json`-Dateien. Das Muster
`{stage_id}.schema.json` ist **nicht** Teil der v3-Namenskonvention und
darf nicht eingefuehrt werden.

**Autoritaetsquelle:** Code/v3-Linie ist autoritativ (AG3-103
Nachzug-Entscheidung). FK-90 spiegelt die implementierte Realitaet.
Contract-Tests in `tests/contract/` sind der maschinell pruefbare
Stabilitaetsanker dieser Konvention.
