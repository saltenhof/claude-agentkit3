---
concept_id: FK-00
title: Technisches Feinkonzept
module: meta
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: technical-overview
  - scope: frontmatter-contract
defers_to: []
supersedes: []
superseded_by:
tags: [feinkonzept, index, dokumentenstruktur, architekturrahmen]
formal_scope: prose-only
---

# AgentKit — Technisches Feinkonzept

## Dokumentenübersicht

Dieses Feinkonzept detailliert das fachliche Domänenkonzept
(`agentkit-domain-concept.md`) so weit technisch aus, dass ein
Entwickler sofort Code schreiben kann. Es ist in thematische
Kapitel-Dokumente und Referenzanhänge gegliedert.

Grundlage für die Priorisierung und Vollständigkeitsprüfung ist die
Fachkonzept-Checkliste (`fachkonzept-checkliste.md`) mit 568 atomaren
Anforderungen.

---

## 1. Grundlagen und Architekturrahmen

| Dokument | Inhalt |
|----------|--------|
| `01_systemkontext_und_architekturprinzipien.md` | Zielbild, Systemgrenzen, Architekturprinzipien, Fail-Closed, Trust Boundaries |
| `02_domaenenmodell_zustaende_artefakte.md` | Kanonische Begriffe, Zustandsmodelle, Identifikatoren, Artefaktklassen |
| `03_konfigurationsmodell_schemas_versionierung.md` | Config-Hierarchie, Dateiformate, Defaults, Validierung |
| `04_betrieb_monitoring_audit_runbooks.md` | Monitoring, Audit-Logs, Runbooks, SLOs |
| `05_integration_stabilization_contract.md` | Integrationsstabilisierung fuer breite E2E-/Systemstories, Manifest, Budget, Stability-Gate, kontrollierte Cross-Scope-Arbeit |
| `06_truth_boundary_and_concept_code_contract_checker.md` | Harte Wahrheitsgrenze DB vs. Exportdatei und Concept-to-Code-Contract-Checker |
| `07_komponentenarchitektur_und_architekturkonformanz.md` | Normativer Komponentenschnitt, Blutgruppen, Importgrenzen und deterministische Architektur-Konformanz |

## 2. Plattform, Infrastruktur und externe Anbindungen

| Dokument | Inhalt |
|----------|--------|
| `10_runtime_deployment_speicher.md` | Laufzeitkomponenten, Verzeichnisstruktur, Persistenz, Locking |
| `11_llm_provider_browser_pools_prompt_execution.md` | Pool-Abstraktion, Modellzuordnung, Request/Response, Retry, JSON-Enforcement |
| `12_github_integration_repo_operationen.md` | GitHub API, Project Board, Branching, Worktree, Merge, Fehlerbehandlung |
| `13_retrieval_vektordb_wissenszugriff.md` | Weaviate, Chunking, Embedding, Similarity, zweistufiger Abgleich |
| `15_security_secrets_identity_zugriffsmodell.md` | Secrets, Rollenidentitäten, Berechtigungsmodell, Audit |
| `17_fachliches_datenmodell_ownership.md` | Fachliche Entitäten, Aggregat-Grenzen, Owner-Komponenten, Persistenzmodell-Tags |
| `18_relationales_abbildungsmodell_postgres.md` | Tabellenfamilien, Pflicht- und optionale Spalten, Single-Writer, Reset-Closure |
| `68_telemetrie_eventing_workflow_metriken.md` | Event-Modell, JSONL-Schema, Metriken, Experiment-Tags |
| `69_qa_telemetrie_aggregation_dashboard.md` | QA-Telemetrie, Read-Models, Verdichtung, Dashboard-Vorbereitung |

## 3. Orchestrierung und Pipeline

| Dokument | Inhalt |
|----------|--------|
| `20_workflow_engine_state_machine.md` | State Machine, Phasen, Feedback-Loop, Eskalation, Recovery, Scheduling |
| `21_story_creation_pipeline.md` | Story-Erstellung, VektorDB-Abgleich, Feldbelegung, fachliche Labels, Repo-Affinität, Freigabe |
| `22_setup_preflight_worktree_guard_activation.md` | Preflight-Gates, Multi-Repo-Worktrees (Participating Repos), Context, Guard-Aktivierung (4 Guards) |
| `23_modusermittlung_exploration_change_frame.md` | 6-Kriterien-Routing, Entwurfsartefakt, Freeze, Dokumententreue |
| `24_story_type_mode_terminalitaet.md` | Kanonische Story Types, Mode-vs-Typ-Vertrag, Exploration als Vorzustand, terminale Abschlussregeln |
| `25_mandatsgrenzen_feindesign_autonomie.md` | Mandatsprinzip, 4 Eskalationsklassen, Feindesign-Subprozess (Multi-LLM), Scope-Explosion-Erkennung, Tragweiten-Vergleich |
| `26_implementation_runtime_worker_loop.md` | Inkrement-Loop, Drift, Reviews, Handover-Paket |
| `27_verify_pipeline_closure_orchestration.md` | Atomarer QA-Zyklus, 4-Schichten-Verify (Layer 1 Deterministisch, Layer 2 LLM, Layer 3 Adversarial, Layer 4 Policy), Artefakt-Invalidierung |
| `28_evidence_assembly_review_vorbereitung.md` | Evidence Assembly, Import-Resolver, Autoritätsklassen, Request-DSL, Preflight-Turn, BundleManifest |
| `29_closure_sequence.md` | Closure-Phase mit Substates, Finding-Resolution-Gate, Postflight-Gates, Execution Report, Guard-Deaktivierung |
| `70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md` | Planungsdomäne für Abhängigkeiten, Readiness, Scheduling-Policy, kritischen Pfad und Ausführungswellen |

## 4. Governance, Guarding und technische Qualitätssicherung

| Dokument | Inhalt |
|----------|--------|
| `30_hook_adapter_guard_enforcement.md` | Claude-Code-Hooks, Registrierung, Event-Normalisierung |
| `31_branch_guard_orchestrator_guard_artefaktschutz.md` | Regelsätze, Pfadklassifikation, opake Fehlercodes, Prompt-Integrity-Guard |
| `32_dokumententreue_conformance_service.md` | 4 Prüfebenen, Referenzdokumente, JSON-Schema, Trigger |
| `33_deterministische_checks_stage_registry_policy_engine.md` | Stage-Registry, Check-Typen, Trust-Klassen, Aggregation |
| `34_llm_bewertungen_adversarial_testing_runtime.md` | LLM-Evaluator, 12 QA-Checks, Adversarial-Sandbox, Sparring |
| `35_integrity_gate_governance_beobachtung_eskalation.md` | 8 Dimensionen, Anomalie-Sensorik, Incident-Kandidaten, Maßnahmen |
| `36_compaction_resilience_prompt_persistence.md` | Compaction-Schutz, Resume-Kapsel, Prompt-Persistenz für Sub-Agenten |
| `37_verify_context_und_qa_bundle.md` | VerifyContext (POST_IMPLEMENTATION/POST_REMEDIATION), Context Sufficiency Builder, Section-aware Bundle-Packing, Vertragsprofil integration_stabilization, HARD-BLOCKER für fehlende LLM-Reviews |
| `38_verify_feedback_und_doctreue_schleife.md` | Feedback-Mechanismus, Mängelliste, Remediation-Loop / Max-Rounds-Eskalation, Mandatory-Target-Rückkopplung, Umsetzungstreue (Ebene 3), Rückkopplungstreue (Ebene 4) |
| `39_phase_state_persistenz.md` | Vierschichtiges State-Modell, PhaseEnvelope, PhaseStateCore, PhasePayload (discriminated union), PhaseMemory (carry-forward), AttemptRecord (Outcome + FailureCause), PauseReason-Enum, Lese-/Schreibprotokoll |
| `71_artefakt_envelope_und_stage_registry.md` | Artefaktklassen + Ownership, Envelope-Schema mit LLM-Status-Mapping, Lock-Record-Mechanismus für QA-Artefaktschutz, typisierte Stage-Registry |

## 5. Querschnittskomponenten und Lernschleifen

| Dokument | Inhalt |
|----------|--------|
| `40_are_integration_anforderungsvollstaendigkeit.md` | Scope-Zuordnung (Repo→Scope, Modul→Scope), ARE-Andock-Punkte, must_cover, Evidence, ARE-Gate, Fallback |
| `41_failure_corpus_pattern_promotion_check_factory.md` | Incident→Pattern→Check, 12 Kategorien, Wirksamkeit |
| `42_ccag_tool_governance_permission_runtime.md` | Regelmodell, Persistenz, Auswertung, LLM-Generierung |
| `43_skills_system_task_automation.md` | Skill-Format, Registry, Versionierung, Kontext-Übergabe |
| `44_prompt_bundles_materialization_audit.md` | Kanonische Prompt-Bundles, Run-Pinning, Materialisierung, Audit und Drift-Schutz |
| `45_phase_runner_cli.md` | Phase Runner CLI (`agentkit run-phase`), Phasen-Dispatch, Phase-Transition-Enforcement (Graphen + Status + semantische Preconditions), Orchestrator-Reaktionstabelle |
| `46_import_resolver.md` | Sprachspezifische Import-Extraktion (Python, TypeScript, Java) für Stufe 2 der Evidence Assembly, Confidence-Labels, Spring-Heuristiken, Barrel-Auflösung |
| `47_request_dsl_und_preflight_turn.md` | 7 Request-Typen (NEED_FILE, NEED_SCHEMA, ...), RequestResolver, Mehrdeutigkeitsregel, Preflight-Turn-Architektur, `review-preflight.md`-Template |
| `48_adversarial_testing_runtime.md` | Adversarial Agent (Schicht 3 der Verify-Pipeline) mit Sandbox, Sparring-Protokoll, Test-Promotion + Mandatory Adversarial Targets (Motivation, Datenmodell, Gate-Rückkopplung) |
| `49_worker_health_monitor.md` | Worker-Health-Monitor: Scoring-Engine (PostToolUse), Interventions-Gate (PreToolUse), LLM-Assessment-Sidecar, Hook-Commit-Failure-Klassifikation, Persistenz-Artefakte, Konfiguration |

## 6. Installation, Upgrade und Betrieb

| Dokument | Inhalt |
|----------|--------|
| `50_installer_checkpoint_engine_bootstrap.md` | 14 Checkpoints (inkl. ARE-Scope-Validierung), Manifest, Idempotenz, Verifikation |
| `51_upgrade_migration_customization_preservation.md` | Upgrade-Strategie, Anpassungsschutz, Schema-Migration |
| `53_story_reset_service_recovery_flow.md` | Vollstaendiger Story-Reset, Purge-Reihenfolge, Worktree-/Branch-Behandlung, Endzustand |
| `54_story_split_service_scope_explosion.md` | Scope-Explosion, Story-Split, Cancelled-Pfad, Nachfolger-Stories, Dependency-Rebinding |
| `55_principal_capability_model_story_scope_enforcement.md` | Principals, Capability-Profile, storybezogene Pfad- und Operationsklassen, Freeze-Modell, offizielle Servicepfade |
| `56_ai_augmented_mode_and_story_execution_separation.md` | Betriebsmodi, explizite Run-Bindung, freier AI-Augmented-Modus vs. Story-Execution-Regime |
| `58_story_exit_human_takeover_handoff.md` | Leichtgewichtiger offizieller Exit aus Story-Execution in menschlich gefuehrten AI-Augmented-Modus bei grossen Loesungsvorschlagsfaellen |
| `59_story_contract_axes_and_combination_matrix.md` | Konsolidierte Vertragsachsen, gueltige/ungueltige Kombinationen, Trennung von Story-Vertrag, Laufzeitableitung und Ergebnisachsen |

## 7. KPIs und Auswertung

| Dokument | Inhalt |
|----------|--------|
| `60_kpi_katalog_und_architektur.md` | KPI-Inventar, Architektur der Erhebungs- und Aggregationsschicht |
| `61_kpi_erhebung_nach_domaenen.md` | Domänenspezifische Erhebung, Quellen, Pflichtfelder |
| `62_kpi_aggregation.md` | Aggregations-Regeln, Fact-Tabellen, Idempotenz, Reset-Closure |
| `63_auswertung_und_dashboard.md` | Read-only Auswertung, Dashboard-Schnittstellen, Berechtigungsgrenzen |

## 8. Referenzanhänge

| Dokument | Inhalt |
|----------|--------|
| `90_schema_katalog.md` | Alle JSON Schemas mit Felddefinitionen und Beispielen |
| `91_api_event_katalog.md` | Interne/externe APIs, Eventtypen, Fehlercodes |
| `92_verzeichnis_namenskonventionen.md` | Repo-Struktur, Run-Verzeichnisse, Naming-Schemata |
| `93_standardwerte_schwellwerte_timeouts.md` | Defaults, Budgets, Timeouts, Retry-Limits, Cooldowns |

## 9. Frontmatter-Vertrag

Dieses Kapitel ist **normativ** für jedes Dokument unter
`concept/technical-design/`. Es ergänzt FK-00 um den
Frontmatter-Vertrag und nimmt damit `authority_over:
frontmatter-contract`.

### 9.1 Pflichtfelder (alle FK-Dokumente)

```yaml
concept_id:        FK-NN              # Pflicht, Pattern: ^FK-\d{2}$
title:             <string>           # Pflicht
module:            <kebab-case>       # Pflicht, kleinbuchstaben mit Bindestrichen
status:            active | draft     # Pflicht
doc_kind:          core | detail      # Pflicht; "detail" verlangt parent_concept_id
parent_concept_id: FK-NN | <leer>     # Pflichtfeld; bei doc_kind=detail nicht leer
authority_over:                        # Pflicht; Liste mit mindestens einem Eintrag
  - scope: <kebab-case>
defers_to:         [FK-NN, ...]       # Pflichtfeld; Liste (ggf. leer)
supersedes:        [FK-NN, ...]       # Pflichtfeld; Liste (ggf. leer)
superseded_by:     FK-NN | <leer>     # Pflichtfeld; bei Wert reziproker supersedes
tags:              [..., ...]         # Pflicht; mindestens ein Eintrag
```

### 9.2 Klassifikation (mutually exclusive)

Jedes FK-Dokument trägt **genau eine** der folgenden Varianten:

| Variante | Bedingung | Pflichtfelder zusätzlich |
|----------|-----------|--------------------------|
| **A — formale Spec** | Doc verweist auf eine oder mehrere `formal-spec/`-Dateien | `prose_anchor_policy: strict` und `formal_refs: [formal.x.y, ...]` (non-empty) |
| **B — reine Prosa** | Doc hat keine maschinell prüfbare Spec | `formal_scope: prose-only` |

Beides gleichzeitig oder keins von beidem ist **fail-closed verboten**.

### 9.3 Maschinell erzwungene Regeln

Die folgenden Regeln werden durch `scripts/ci/compile_formal_specs.py`
(Funktionen `audit_concept_doc_classification` und
`audit_formal_prose_links`) erzwungen:

1. Frontmatter parsebar.
2. Genau eine der beiden Varianten 9.2.
3. Jeder Eintrag in `formal_refs` referenziert eine kompilierte
   formale Spec (`doc_id` aus dem `formal-spec/`-Korpus).
4. Reziprozität: die referenzierte formale Spec listet das
   FK-Dokument in ihrem `prose_refs`.
5. Bei `prose_anchor_policy: strict` muss jeder `formal_refs`-Eintrag
   im Body als `<!-- PROSE-FORMAL: ... -->` Anker auftauchen.

### 9.4 Schema-Detail-Regeln

Die folgenden Regeln werden vom Frontmatter-Lint
(`scripts/ci/check_concept_frontmatter.py`) deterministisch erzwungen.
Severity ist **immer Error** — Warnings sind unzulaessig, weil sie in
der Praxis untergehen. Ein nicht-fehlerfreier Stand ist
Handlungsauftrag, kein Hintergrundrauschen.

| Regel | Bedeutung |
|-------|-----------|
| `concept_id` Pattern | `^FK-\d{2}$` (technical-design) oder `^DK-\d{2}$` (domain-design) |
| `concept_id` Eindeutigkeit | jede ID darf hoechstens einmal vorkommen (ueber alle Layer) |
| `parent_concept_id` Target | wenn gesetzt: muss existierendes `FK-` oder `DK-` sein |
| `parent_concept_id` Pflicht bei `doc_kind: detail` | Detail-Dokumente brauchen einen Eltern-Eintrag |
| `defers_to` Targets | jeder Eintrag (string oder dict.target) muss existieren |
| `supersedes` Form | string oder `{target, scope, reason}`; Eintrag mit `scope` ist Teil-Supersession |
| `superseded_by` Reciprocity | nur fuer **vollstaendige** Supersession (Eintrag ohne `scope`): das Ziel-Doc muss `superseded_by` zurueckzeigen |
| Authority-Graph | `parent_concept_id` + `defers_to` zusammen muessen zyklenfrei sein |
| Authority-Disjunktheit | kein `authority_over.scope` darf von zwei Konzepten gehalten werden, ausser sie sind durch Voll-Supersession verbunden |
| Authority-Typkompatibilitaet | `defers_to` und `parent_concept_id` duerfen nicht auf einen Index- oder Anhang-Doc zeigen; `supersedes`/`superseded_by` muessen gleiche `doc_kind`-Familie haben |
| Index-Vollstaendigkeit | jede Datei in `concept/technical-design/*.md` muss in §1-§8 dieses Index referenziert sein, und umgekehrt |
| Body-Referenz-Existenz | jede `FK-NN`/`DK-NN`-Erwaehnung im Doc-Body muss zu einem existierenden Konzept passen |
| `formal_refs` ↔ Body-Anker | bei `prose_anchor_policy: strict`: jeder formal_refs-Eintrag im Body als `<!-- PROSE-FORMAL: ... -->` Anker (lokale Pruefung vor `audit_formal_prose_links`) |

### 9.5 Tag-Korpus

Kanonische Quelle: `concept/technical-design/_meta/tag-corpus.txt`
(eine Tag pro Zeile, alphabetisch sortiert).

**Erweiterung:** ein neuer Tag wird durch eine Zeile in dieser Datei
freigeschaltet. Es gibt keinen Warning-Pfad — entweder der Tag ist
freigegeben oder der Lint blockiert. Tag-Pflege ist eine
Nebenverantwortung von FK-00.

### 9.6 Modul-Registry

Kanonische Quelle: `concept/technical-design/_meta/module-registry.yaml`.

**Bedeutung:** Jedes `module:` im Frontmatter muss in dieser Registry
eingetragen sein. Die Registry ist die Bruecke zwischen Konzept-Welt
und Komponentenarchitektur (FK-07 §65.4 fuehrt den normativen
Top-Level-Schnitt). Pro Eintrag kann optional ein `component_family`
gefuehrt werden, der gegen die FK-07-Familien abgleicht.

### 9.7 Bounded-Context-Felder (optional, scharfgeschaltet via Domain-Registry)

Diese Felder ergaenzen den Stamm aus §9.1, sobald die Domain-Registry
(siehe §9.10) Eintraege fuehrt. Bis dahin sind die Felder zulaessig,
aber nicht maschinell erzwungen.

```yaml
domain:            <kebab-case>          # Pflichtfeld, sobald Domain-Registry aktiv ist
applies_policies:  [policy.x, ...]       # Optional, gegen Policy-Registry §9.9
contract_state:    active | compatible | deprecating | breaking
                                         # Pflicht NUR in Contract-Docs (siehe §9.8)
migration_ack:     <new-contract-id>     # Pflicht im Consumer-Doc, wenn ein referenzierter
                                         # Contract auf contract_state=breaking steht
```

### 9.8 Surface (Vertrag vs. Innenleben)

`surface` ist **abgeleitet, nicht manuell**. Die Lint-Logik bestimmt
den Wert nach folgenden Regeln:

| Bedingung | abgeleitetes `surface` |
|-----------|------------------------|
| Doc steht in `_meta/domain-registry.yaml` als `contract_doc` einer Domaene UND hat mindestens einen `formal_ref` | `contract` |
| sonst | `internal` |

Ein Contract-Doc darf mehrere benannte Vertrags-Sektionen tragen, die
ueber `<!-- CONTRACT-ANCHOR: <slug> -->` im Body markiert werden.
Cross-Domain-Referenzen sollen auf solche Anchors zielen, nicht auf
Doc-IDs allein. Bis Lint L18 scharf ist, gilt diese Regel als Konvention.

### 9.9 Policy-Registry

Kanonische Quelle: `concept/technical-design/_meta/policy-registry.yaml`.

**Bedeutung:** Querschnittskonzepte (Trust Boundaries, Severity-Semantik,
Truth-Boundary-Contract) werden NICHT als Domaene gefuehrt — das waere
eine "Foundation-Sinkhole"-Antipattern. Stattdessen sind sie Policies,
die ein Doc als orthogonalen Constraint via `applies_policies`
referenziert. Authority-Graph (`defers_to`) bleibt damit rein fachlich,
keine Sterntopologie.

### 9.10 Domain-Registry

Kanonische Quelle: `concept/technical-design/_meta/domain-registry.yaml`.

**Bedeutung:** Bounded-Context-Schnitt von AK3. Pro Eintrag:
`id`, `display_name`, `contract_docs: [FK-NN, ...]`,
`member_docs: [FK-NN, ...]`. Solange diese Datei leer ist, laufen die
Bounded-Context-Lints L17-L20 als No-Ops. Sobald Eintraege bestehen,
werden sie scharfgeschaltet — fail-closed wie alle anderen Lints.

### 9.11 Glossar (im Contract-Doc)

Glossare leben **im jeweiligen Contract-Doc** der Domaene als
Frontmatter-Block oder dedizierte `## Glossar`-Sektion mit folgender
Form:

```yaml
glossary:
  exported_terms:
    - id: <Term>
      definition: <string>
      values: [optional, fuer Enums]
      see_also:
        - term: <Other-Term>
          domain: <other-domain-id>      # explizit, fuer deterministische FK-Aufloesung
  internal_terms:
    - id: <implementation-detail>
      reason: <warum nicht exportiert>
```

**Ownership:** Der Domain-Owner pflegt den Glossar-Block ihres
Contract-Docs allein. Niemand ausserhalb darf darin schreiben.
Dezentral, in-Doc, mit referenzieller Integritaet ueber den Lint.

**Aggregierte Sicht:** Lint generiert beim Lauf zwei Read-only-
Artefakte als "ein Blick"-Ansicht:

- `concept/technical-design/_meta/glossary-overview.md` — alphabetisch
  alle exportierten Terms, mit Domain-Tag und Cross-Refs als Hyperlinks.
- `concept/technical-design/_meta/glossary-reverse-index.md` —
  pro Term: wer referenziert ihn (Reverse-Lookup).

Beide Artefakte sind regeneriert; **niemals manuell editieren**.

### 9.12 Lints L17-L20 (Bounded-Context-Layer)

Diese Lints sind aktiv, sobald die Domain-Registry Eintraege fuehrt
(siehe §9.10). Sie ergaenzen §9.4:

| Lint | Bedeutung |
|------|-----------|
| L17 | `domain` Pflicht (oder `cross_cutting: true`, siehe §9.13); Wert muss in Domain-Registry sein. `applies_policies` Eintraege muessen in Policy-Registry sein. `cross_cutting: true` und `domain` schliessen sich gegenseitig aus |
| L18 | Cross-Domain-Referenzen (Body oder `defers_to`) duerfen nur auf `surface: contract`-Docs zeigen. Cross-cutting Docs (§9.13) sind sowohl als Source als auch als Target von dieser Regel ausgenommen |
| L19 | Glossar-FK-Integritaet: jeder `see_also.term` + `domain` ist ueber alle Glossare deterministisch aufloesbar; kein Term darf gleichzeitig `exported` und `internal` sein |
| L20 | Implicit-Leakage: kein `internal_term` aus Domaene X mit normativem Modalverb (`muss`, `ist`, `darf nur`, `Single Source of Truth`) in Doc anderer Domaene |

### 9.13 Cross-Cutting-Marker (`cross_cutting: true`)

Die User-BC-Vorgabe (`bounded-contexts.yaml §foundation_principles`)
modelliert Foundation, Adapter und querschnittliche Referenzkataloge
explizit **nicht** als Bounded Context. Solche Docs haben keine
Sprachgrenze und keinen Owner-BC, sondern sind universell lesbare
Grundlage fuer alle BCs.

Damit L17 ihre fail-closed-Pflicht zur Domain-Zuordnung trotzdem
einhalten kann, fuehrt das Frontmatter den Marker `cross_cutting: true`:

```yaml
cross_cutting: true   # statt `domain: <id>`
```

**Semantik:**

- `cross_cutting: true` befreit den Doc von der `domain`-Pflicht (L17).
- Der Doc wird in keiner Domain-Registry-Liste gefuehrt.
- Andere Docs duerfen ohne Einschraenkung auf cross-cutting-Docs
  zeigen (L18 ist exempt).
- Cross-cutting-Docs sind selbst von L18 als Source ausgenommen —
  sie duerfen frei in alle Domaenen referenzieren.
- L19/L20 (Glossar-Integritaet, Implicit-Leakage) gelten nicht fuer
  cross-cutting-Docs, weil sie keinen Domain-Owner haben.

**Wann cross-cutting?** Foundation- und Adapter-Konzepte (z.B.
Architekturprinzipien, GitHub-/VektorDB-Adapter, Runtime-Rahmen),
Operations-/Runbook-Referenzen, Vertragsachsen-Kataloge,
querschnittliche Referenzanhaenge (Schema-, API-Event-,
Naming-Konventionen-, Defaults-Kataloge) und der Index selbst.

**Wann nicht cross-cutting?** Sobald ein Doc fachliches BC-Vokabular
definiert, BC-spezifische Invarianten beschreibt oder Eigentum einer
Domain ist. Im Zweifel: Domaene zuordnen, nicht cross-cutting.
