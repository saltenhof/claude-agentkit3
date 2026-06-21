# AG3-021: Typisierte Kern-Enums (Severity, QaContext, PauseReason, ArtifactClass u.a.)

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** keine
**Quell-Konzepte (autoritativ, in dieser Reihenfolge — `rel_path` ab Repo-Root):**
- `FK-27 §27.4.2` — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` (Severity BLOCKING/MAJOR/MINOR und Wire-Casing der Severity-Strings)
- `FK-27 §27.7.2` — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` (Policy-Entscheidung PASS/FAIL — kein PASS_WITH_WARNINGS)
- `FK-23 §23.5.0` — `concept/technical-design/23_modusermittlung_exploration_change_frame.md` (`ExplorationGateStatus`-StrEnum PENDING/APPROVED/REJECTED)
- `FK-39 §39.2.2` — `concept/technical-design/39_phase_state_persistenz.md` (`PauseReason` mit drei Werten)
- `FK-39 §39.4.2/39.4.3` — `concept/technical-design/39_phase_state_persistenz.md` (`AttemptOutcome`, `FailureCause` als StrEnum)
- `FK-71 §71.1.1/71.2` — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (`ArtifactClass`-Enum, `EnvelopeStatus`)
- `FK-24 §24.3.2/24.5/24.6` — `concept/technical-design/24_story_type_mode_terminalitaet.md` (`StoryMode`-Werte, `execution_route`, Terminalitaet)
- `DK-10 §10.4` — `concept/domain-design/10-story-lifecycle-und-erstellung.md` (Story-Groessen XS/S/M/L/XL, 5 Stufen)
- `FK-29 §29.1.5` — `concept/technical-design/29_closure_sequence.md` (`MergePolicy` ff_only/no_ff)
- `FK-70 §70.4.2` — `concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md` (`StoryDependencyKind` mit 8 Werten)
- `FK-41 §41.4.1` — `concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md` (`FailureCategory` 12 Werte)
- `concept/_meta/bc-cut-decisions.md §QaContext-Werte` — Zeilen 84-95 (`QaContext` mit vier Werten)
- `concept/_meta/bc-cut-decisions.md §BC 6 implementation-phase` — Zeilen 415-456 (`BlockingCategory` mit vier Werten, `SpawnReason`)
- `concept/_meta/bc-cut-decisions.md §BC 8 artifacts` — Closure-Top-Datenmodell mit `ClosureVerdict` (StrEnum: COMPLETED, ESCALATED) und `MergePolicy` (Zeile 558-560)
- `concept/_meta/bc-cut-decisions.md §BC 13 failure-corpus` — Zeilen 1177-1218 (`FailureCategory`, `PromotionStatus`)

---

## 1. Kontext

THEME-002 aus `stories/_priorisierungsempfehlung.md`. Zehn BCs warten auf identische Kern-Typdefinitionen. Solange diese Enums fehlen oder als freie Strings/abweichende Kategorien existieren, arbeiten Stage-Registry, Policy-Engine, Telemetrie-Projektionen, Gates und Audit-Trails gegen ein labiles Fundament.

Spezifische Drift-Punkte aus den GAP-Analysen:

- `verify-system.C1`: Severity-Schema CRITICAL/HIGH/MEDIUM/LOW/INFO statt BLOCKING/MAJOR/MINOR
- `verify-system.C2`: `PASS_WITH_WARNINGS` konzeptlos
- `exploration-and-design.A6/B2`: `ExplorationGateStatus`-StrEnum fehlt; `gate_status: str | None` ungetypt
- `exploration-and-design.C2`: `VerifyContext` hat nur 2 von 4 Werten und falsche Namen
- `pipeline-framework.C2`: `PauseReason` als freier String
- `pipeline-framework.B2/C4`: `AttemptOutcome` und `FailureCause` als StrEnum fehlen; `AttemptRecord` ohne `failure_cause`
- `story-lifecycle.C1`: `StorySize` (small/medium/large/epic) vs. konzeptuell XS/S/M/L/XL; `WireStorySize` zusaetzlich XXL
- `story-lifecycle.C2`: `StoryMode.NOT_APPLICABLE` nicht im Konzept normiert
- `story-closure.A9`: `ClosureVerdict`, `MergePolicy` fehlen
- `implementation-phase.A4`: `BlockingCategory`-StrEnum fehlt
- `implementation-phase.C2`: `SpawnReason` wird als String-Literal verglichen
- `execution-planning.C1`: `StoryDependencyKind`-Vokabular weicht ab (3 statt 8 Werte)
- `artifacts.B3`: `EnvelopeStatus`-Werte uneinheitlich
- `failure-corpus.A2`: `FailureCategory` (12 Werte), `PromotionStatus` fehlen

Diese Story ist ZUERST zu erledigen (Welle 2 nach THEME-001 ist bereits abgeschlossen), weil **alle** nachfolgenden THEMEN diese Enums importieren.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Neues Modul `src/agentkit/core_types/`

Owner-Modul fuer alle Kern-Enums. Begruendung: kein BC ist Owner aller dieser Enums; sie sind cross-cutting Foundation-Typen. Alle Enums sind `StrEnum` (Python 3.11+ stdlib). Python-Member-Namen sind UPPER_SNAKE_CASE; **Wire-Wert pro Member ist der String aus der untenstehenden Tabelle** und ist normativ — der Contract-Test (siehe 2.1.9) pinnt jeden Wert.

##### 2.1.1.1 Sub-Module und Enum-Wertelisten

**`severity.py` — `Severity`** (Quelle: `FK-27 §27.4.2`, `concept/technical-design/27_verify_pipeline_closure_orchestration.md`)

| Python-Member | Wire-Wert | Quelle |
|---|---|---|
| `BLOCKING` | `"BLOCKING"` | FK-27 §27.4.2 Tabelle (Spalte Severity, Upper-Case) |
| `MAJOR`    | `"MAJOR"`    | FK-27 §27.4.2 Tabelle |
| `MINOR`    | `"MINOR"`    | FK-27 §27.4.2 Tabelle |

**`qa_context.py` — `QaContext`** (Quelle: `concept/_meta/bc-cut-decisions.md` Z. 84-95)

| Python-Member | Wire-Wert |
|---|---|
| `IMPLEMENTATION_INITIAL`     | `"IMPLEMENTATION_INITIAL"` |
| `IMPLEMENTATION_REMEDIATION` | `"IMPLEMENTATION_REMEDIATION"` |
| `EXPLORATION_INITIAL`        | `"EXPLORATION_INITIAL"` |
| `EXPLORATION_REMEDIATION`    | `"EXPLORATION_REMEDIATION"` |

**`policy_verdict.py` — `PolicyVerdict`** (Quelle: `FK-27 §27.7.2`, kein PASS_WITH_WARNINGS)

| Python-Member | Wire-Wert |
|---|---|
| `PASS` | `"PASS"` |
| `FAIL` | `"FAIL"` |

**`exploration.py` — `ExplorationGateStatus`** (Quelle: `FK-23 §23.5.0`, `concept/technical-design/23_modusermittlung_exploration_change_frame.md` Z. 365-368)

| Python-Member | Wire-Wert |
|---|---|
| `PENDING`  | `"pending"`  |
| `APPROVED` | `"approved"` |
| `REJECTED` | `"rejected"` |

Wire-Werte lowercase — konzeptlich festgenagelt in FK-23 §23.5.0 Code-Beispiel `PENDING = "pending"`.

**`pause_reason.py` — `PauseReason`** (Quelle: `FK-39 §39.2.2`, `concept/technical-design/39_phase_state_persistenz.md` Glossary-Eintrag Z. 62-69)

| Python-Member | Wire-Wert |
|---|---|
| `AWAITING_DESIGN_REVIEW`    | `"AWAITING_DESIGN_REVIEW"` |
| `AWAITING_DESIGN_CHALLENGE` | `"AWAITING_DESIGN_CHALLENGE"` |
| `GOVERNANCE_INCIDENT`       | `"GOVERNANCE_INCIDENT"` |

**`attempt.py` — `AttemptOutcome`** (Quelle: `FK-39 §39.4.2`, `concept/technical-design/39_phase_state_persistenz.md` Z. 391-402)

| Python-Member | Wire-Wert |
|---|---|
| `COMPLETED` | `"COMPLETED"` |
| `FAILED`    | `"FAILED"` |
| `ESCALATED` | `"ESCALATED"` |
| `SKIPPED`   | `"SKIPPED"` |
| `YIELDED`   | `"YIELDED"` |
| `BLOCKED`   | `"BLOCKED"` |

**`attempt.py` — `FailureCause`** (Quelle: `FK-39 §39.4.3`, `concept/technical-design/39_phase_state_persistenz.md` Z. 404-422). Konzept-Tabelle definiert **16 Werte** (Story-Header in v2 nannte 15 — Quelle ist FK-39, hier verbindlich gefuehrt):

| Python-Member | Wire-Wert |
|---|---|
| `GUARD_REJECTED`              | `"GUARD_REJECTED"` |
| `STRUCTURAL_CHECK_FAIL`       | `"STRUCTURAL_CHECK_FAIL"` |
| `SEMANTIC_REVIEW_FAIL`        | `"SEMANTIC_REVIEW_FAIL"` |
| `ADVERSARIAL_FINDING`         | `"ADVERSARIAL_FINDING"` |
| `POLICY_FAIL`                 | `"POLICY_FAIL"` |
| `WORKER_BLOCKED`              | `"WORKER_BLOCKED"` |
| `INTEGRITY_FAIL`              | `"INTEGRITY_FAIL"` |
| `MERGE_FAIL`                  | `"MERGE_FAIL"` |
| `PREFLIGHT_FAIL`              | `"PREFLIGHT_FAIL"` |
| `MAX_ROUNDS_EXCEEDED`         | `"MAX_ROUNDS_EXCEEDED"` |
| `TIMEOUT`                     | `"TIMEOUT"` |
| `GUARD_FAILED`                | `"GUARD_FAILED"` |
| `HANDLER_EXCEPTION`           | `"HANDLER_EXCEPTION"` |
| `PRECONDITION_FAILED`         | `"PRECONDITION_FAILED"` |
| `HANDLER_REPORTED_FAILED`     | `"HANDLER_REPORTED_FAILED"` |
| `HANDLER_REPORTED_ESCALATED`  | `"HANDLER_REPORTED_ESCALATED"` |

**`artifact.py` — `ArtifactClass`** (Quelle: `FK-71 §71.1.1`, `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` Z. 90-99 — acht Artefaktklassen)

| Python-Member | Wire-Wert |
|---|---|
| `WORKER`                   | `"worker"` |
| `QA`                       | `"qa"` |
| `PIPELINE`                 | `"pipeline"` |
| `TELEMETRY`                | `"telemetry"` |
| `GOVERNANCE`               | `"governance"` |
| `ENTWURF`                  | `"entwurf"` |
| `HANDOVER`                 | `"handover"` |
| `ADVERSARIAL_TEST_SANDBOX` | `"adversarial_test_sandbox"` |

Wire-Werte lowercase; konsistent mit dem Postgres-`CHECK`-Constraint, der in AG3-023 §2.1.4 lower-case Wire-Strings auflistet.

**`artifact.py` — `EnvelopeStatus`** (Quelle: `FK-71 §71.2`, Z. 145)

| Python-Member | Wire-Wert |
|---|---|
| `PASS`  | `"PASS"` |
| `FAIL`  | `"FAIL"` |
| `WARN`  | `"WARN"` |
| `ERROR` | `"ERROR"` |

**`story.py` — `StorySize`** (Quelle: `DK-10 §10.4`, `concept/technical-design/24_story_type_mode_terminalitaet.md` Querverweis FK-59)

| Python-Member | Wire-Wert |
|---|---|
| `XS` | `"XS"` |
| `S`  | `"S"`  |
| `M`  | `"M"`  |
| `L`  | `"L"`  |
| `XL` | `"XL"` |

Kein `XXL`, kein `epic`, kein `small/medium/large`.

**`story.py` — `StoryMode`** (Quelle: `FK-24 §24.3.2`, `concept/technical-design/24_story_type_mode_terminalitaet.md` Z. 157-175 und AG3-018 Fast-Modus)

| Python-Member | Wire-Wert |
|---|---|
| `EXECUTION`   | `"execution"` |
| `EXPLORATION` | `"exploration"` |
| `FAST`        | `"fast"` |

Kein `NOT_APPLICABLE`. Fuer nicht-implementierende Storys ist `execution_route` Optional (`None`), nicht ein eigener Enum-Wert.

**`story.py` — `execution_route`-Typdarstellung** — kein eigener Enum; ist ein Alias auf `StoryMode | None`. Begruendung: FK-24 §24.3.2 hebt hervor, dass der historisch `mode` genannte Wert fachlich `execution_route` heisst und drei mogliche Auspraegungen kennt: `execution`, `exploration`, `None`. `mode` darf NICHT mit `operating_mode` (FK-56) verwechselt werden.

**`closure.py` — `ClosureVerdict`** (Quelle: `concept/_meta/bc-cut-decisions.md` §BC 8/Closure-Top Z. 558-560)

| Python-Member | Wire-Wert |
|---|---|
| `COMPLETED` | `"COMPLETED"` |
| `ESCALATED` | `"ESCALATED"` |

**`closure.py` — `MergePolicy`** (Quelle: `FK-29 §29.1.5`, `concept/technical-design/29_closure_sequence.md` Z. 351-358)

| Python-Member | Wire-Wert |
|---|---|
| `FF_ONLY` | `"ff_only"` |
| `NO_FF`   | `"no_ff"` |

**`dependency.py` — `StoryDependencyKind`** (Quelle: `FK-70 §70.4.2`, `concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md` Z. 211-220)

| Python-Member | Wire-Wert |
|---|---|
| `HARD_STORY_DEPENDENCY`       | `"hard_story_dependency"` |
| `SOFT_STORY_DEPENDENCY`       | `"soft_story_dependency"` |
| `SERIAL_EXECUTION_CONSTRAINT` | `"serial_execution_constraint"` |
| `MUTEX_CONSTRAINT`            | `"mutex_constraint"` |
| `SHARED_CONTRACT_DEPENDENCY`  | `"shared_contract_dependency"` |
| `SHARED_FILE_CONFLICT`        | `"shared_file_conflict"` |
| `EXTERNAL_DEPENDENCY`         | `"external_dependency"` |
| `HUMAN_GATE_DEPENDENCY`       | `"human_gate_dependency"` |

**`failure_corpus.py` — `FailureCategory`** (Quelle: `FK-41 §41.4.1`, `concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md` Z. 281-294, abgeglichen mit `concept/_meta/bc-cut-decisions.md §BC 13`, Z. 1214-1218 — 12 Werte)

| Python-Member | Wire-Wert |
|---|---|
| `SCOPE_DRIFT`            | `"scope_drift"` |
| `ARCHITECTURE_VIOLATION` | `"architecture_violation"` |
| `EVIDENCE_FABRICATION`   | `"evidence_fabrication"` |
| `HALLUCINATION`          | `"hallucination"` |
| `TEST_OMISSION`          | `"test_omission"` |
| `ASSERTION_WEAKNESS`     | `"assertion_weakness"` |
| `UNSAFE_REFACTOR`        | `"unsafe_refactor"` |
| `POLICY_VIOLATION`       | `"policy_violation"` |
| `TOOL_MISUSE`            | `"tool_misuse"` |
| `STATE_DESYNC`           | `"state_desync"` |
| `REQUIREMENTS_MISS`      | `"requirements_miss"` |
| `REVIEW_EVASION`         | `"review_evasion"` |

Hinweis: frueher in dieser Story zirkulierende Wertelisten wie `INSTRUCTION_NEGLECT`, `BAR_RAISING_FAILURE`, `TEST_FRAMEWORK_GAP` etc. sind **nicht** Teil von FK-41 §41.4.1 und entfallen. Wert `OTHER` ist nicht im Konzept; falls Bedarf nach Fallback-Klassifikation entsteht, wird das in einer Folge-Story am Konzept verankert.

**`failure_corpus.py` — `PromotionStatus`** (Quelle: `FK-41` Glossar `exported_terms.promotion-status.values`, Z. 70-76 in 41_failure_corpus_pattern_promotion_check_factory.md — 7 Werte; `concept/_meta/bc-cut-decisions.md §BC 13` Z. 1217-1218 nennt nur, dass PromotionStatus "alle 3 Ebenen abdeckt", ohne Wertelisten — verbindlich gilt FK-41 Glossar)

| Python-Member | Wire-Wert |
|---|---|
| `MONITORING` | `"monitoring"` |
| `DRAFT`      | `"draft"` |
| `APPROVED`   | `"approved"` |
| `ACTIVE`     | `"active"` |
| `TUNED`      | `"tuned"` |
| `RETIRED`    | `"retired"` |
| `REJECTED`   | `"rejected"` |

Hinweis: frueher in dieser Story zirkulierende Werteliste `OBSERVED/PROPOSED/CONFIRMED/IMPLEMENTED/RETIRED` ist **nicht** Teil von FK-41 und entfaellt; die obigen sieben Werte sind die Wahrheit aus FK-41 Glossar.

**`worker.py` — `BlockingCategory`** (Quelle: `FK-26 §26.8.2` Glossar Z. 42-53 in `concept/technical-design/26_implementation_runtime_worker_loop.md`, mehrfach gespiegelt in bc-cut-decisions §BC 6)

| Python-Member | Wire-Wert |
|---|---|
| `POLICY_CONFLICT` | `"POLICY_CONFLICT"` |
| `ENVIRONMENTAL`   | `"ENVIRONMENTAL"` |
| `FIXABLE_LOCAL`   | `"FIXABLE_LOCAL"` |
| `FIXABLE_CODE`    | `"FIXABLE_CODE"` |

**`worker.py` — `SpawnReason`** (Quelle: `concept/_meta/bc-cut-decisions.md §BC 6` Z. 441-450 und FK-26 §26.2, Worker-Variants implementation/bugfix/remediation; SpawnReason klassifiziert WANN gespawnt wird)

| Python-Member | Wire-Wert | Anmerkung |
|---|---|---|
| `INITIAL`      | `"initial"`      | Erstaufruf einer Story-Phase |
| `PAUSED_RETRY` | `"paused_retry"` | Re-Spawn nach PAUSED-Zustand (Wert `paused_reason` faellt weg) |
| `REMEDIATION`  | `"remediation"`  | Re-Spawn nach QA-FAIL fuer Remediation-Runde |

Hinweis: Die obigen drei Werte folgen aus FK-26-Worker-Variants und bc-cut-decisions §BC 6 (Spawn-Protokoll). FK-Konzept nennt die exakte Werteliste nicht in einem geschlossenen Glossar — diese drei Werte folgen aus FK-26 §26.2 und bc-cut-decisions §BC 6 Klassenskizze; sollte ein vierter Wert (z.B. `MANUAL`) konzeptuell verankert werden, ist das Folge-Story.

##### 2.1.1.2 PASS_WITH_WARNINGS vs. PASS_WITH_CONCERNS — Begriffskasten

> **Wichtige terminologische Trennung** (Codex-Befund §"Konzept-Spannungen" Pkt. 1):
>
> - **`PASS_WITH_WARNINGS`** ist ein **alter Wert** des Policy-Verdicts aus v2 und ist **entfernt**. `PolicyVerdict` kennt ab AG3-021 ausschliesslich `PASS` und `FAIL` (`FK-27 §27.7.2`). Jede Wiedereinfuehrung im `PolicyVerdict`-Enum oder in der `PolicyEngine.decide()`-Rueckgabe ist ein Konzeptbruch.
> - **`PASS_WITH_CONCERNS`** ist ein **LLM-Check-Status**, den einzelne LLM-Bewertungen (QA-Review, Semantic Review, Doc-Fidelity) zurueckliefern (`FK-71 §71.2`, Z. 150-158). Beim Aggregieren in einen Envelope wird dieser Status auf `EnvelopeStatus.WARN` gemappt — das Mapping lebt in **AG3-022** (`ProducerRegistry.map_llm_status_to_envelope_status`).
>
> Trennregel: `PASS_WITH_CONCERNS -> WARN` ist ein Mapping **am Envelope-Rand** und darf **nicht** als Verdict ins `PolicyVerdict`-Enum oder in die `PolicyEngine` zurueckfliessen. AG3-022 importiert `EnvelopeStatus` aus diesem Modul; AG3-021 traegt keine LLM-Status-Mapping-Logik.

Alle Enums sind `StrEnum` (Python 3.11+ stdlib) und unveraendert; die *Wire-Werte* (Strings) entsprechen exakt den Konzept-Quellen oben.

#### 2.1.2 Migration bestehender Code-Stellen — Severity (FK-27 §27.4.2, verify-system.C1)

`src/agentkit/verify_system/protocols.py:Severity` wird ersetzt:

- alter Wertebereich `CRITICAL/HIGH/MEDIUM/LOW/INFO` entfaellt
- neuer Wertebereich `BLOCKING/MAJOR/MINOR` (Import aus `agentkit.backend.core_types`)
- alle Stellen, die alte Werte vergleichen, werden migriert
- Mapping: keine 1:1-Konversion noetig — alte Tests wandern auf neuen Wertebereich; alte Produktivdaten existieren nicht (greenfield)

`PolicyEngine.decide` wird so umgebaut, dass es nur `PolicyVerdict.PASS` oder `PolicyVerdict.FAIL` zurueckgeben kann (kein `PASS_WITH_WARNINGS`).

#### 2.1.3 Migration — QaContext (verify-system, exploration-and-design.C2)

`src/agentkit/story_context_manager/models.py:VerifyContext` wird umbenannt und auf vier Werte gehoben:

- alt: `POST_IMPLEMENTATION`, `POST_REMEDIATION` (nur zwei Werte)
- neu: `QaContext` mit `IMPLEMENTATION_INITIAL`, `IMPLEMENTATION_REMEDIATION`, `EXPLORATION_INITIAL`, `EXPLORATION_REMEDIATION` (aus `agentkit.backend.core_types`)
- alle Importer im Repo werden umgestellt
- Wenn das Modell `VerifyContext` an Aufrufstellen exportiert wurde, bleibt ein Deprecation-Alias **nicht** zurueck (greenfield, Zero Debt)

#### 2.1.4 Migration — PauseReason (pipeline-framework.C2)

`src/agentkit/pipeline/engine.py:_handle_paused_result` setzt `paused_reason=result.yield_status` (freier String). Migration:

- `result.yield_status` wird zu `PauseReason | None` typisiert (oder das Yield-Result-Modell erhaelt ein neues typisiertes `pause_reason: PauseReason`-Feld)
- Validierung: Engine akzeptiert nur die drei normierten Werte; alles andere fail-closed (Engine ruft `InvalidPauseReasonError` aus AG3-024 §2.1.5)

**Helper `PauseReason.from_yield_status(s: str) -> PauseReason`** (verbindliche Werteliste in dieser Story; wird in AG3-024 konsumiert):

| Alter Yield-Status-String (case-insensitive) | Ziel `PauseReason` |
|---|---|
| `"awaiting_design_review"`, `"design_review_pending"`, `"design_review"` | `AWAITING_DESIGN_REVIEW` |
| `"awaiting_design_challenge"`, `"design_challenge"`, `"design_challenge_pending"` | `AWAITING_DESIGN_CHALLENGE` |
| `"governance_incident"`, `"governance_pause"`, `"governance_intervention"` | `GOVERNANCE_INCIDENT` |
| jeder andere String oder leerer String | `ValueError` (fail-closed; kein Default) |

Begruendung: die im Repo aktuell vorgefundenen freien Yield-Strings stammen aus v2 und sind nicht normiert. Die obigen drei Synonym-Gruppen sind die in Code und Konzeptdokumenten beobachteten Werte; sie werden auf die drei normierten `PauseReason`-Werte abgebildet. Jede weitere Variante wird durch den Contract-Test in 2.1.9 erfasst und ist hart abzuweisen.

Alternative: Wenn der Worker-/Engine-Code im Migrationsfenster keine freien Strings mehr produziert (Greenfield bestaetigt durch grep nach `yield_status =` in `src/`), darf `from_yield_status` **aus dem Scope genommen werden** — in diesem Fall:
- Die obige Mapping-Tabelle entfaellt mit klarer Notiz in der Story-Schliessung.
- `pipeline.engine._handle_paused_result` akzeptiert nur `PauseReason`-Instanzen direkt.
- Keine String-Konversionsschicht.

Der Worker waehlt eine der beiden Varianten **am Anfang der Implementation** und dokumentiert die Entscheidung im Commit-Message. Default-Empfehlung: `from_yield_status` einbauen, weil noch Bestandscode `yield_status: str` traegt.

#### 2.1.5 Migration — StoryMode und StorySize (story-lifecycle.C1, C2)

`src/agentkit/story_context_manager/types.py:StoryMode` und `sizing.py:StorySize`:

- `StoryMode.NOT_APPLICABLE` wird entfernt; `execution_route` darf `None` sein (Pydantic-Optional), aber nicht den eigenen Enum-Wert tragen. Alle Stellen, die `NOT_APPLICABLE` vergleichen, werden umgestellt auf `mode is None`.
- `StorySize`-Werte `small/medium/large/epic` werden auf `XS/S/M/L/XL` migriert. Repository-Persistenz: greenfield, keine Bestandsdaten zu migrieren — Schema-Spalten-Migration nur Datentyp-Update.
- `WireStorySize.XXL` wird entfernt; `XXL` ist kein Konzept-Wert.
- `StoryMode.FAST` wird im Enum aufgenommen (AG3-018 verlangt Fast-Modus, ist bereits konzeptionell vorgesehen).

#### 2.1.6 Migration — StoryDependencyKind (execution-planning.C1)

`src/agentkit/execution_planning/entities.py:StoryDependencyKind` (3 Werte) wird durch den 8-Werte-Enum aus 2.1.1 ersetzt:

- altes Vokabular `blocks/derives_from/branches_off` entfaellt
- Tests werden auf die neuen Werte umgestellt
- Repository-Persistenz: greenfield
- `compute_readiness` wird in diesem Migrationsschritt **nicht** umgebaut (hard vs. soft-Logik) — das ist eine separate Story der THEME-009/Execution-Planning-Welle; nur die Typumstellung ist Pflicht hier.

#### 2.1.7 Migration — SpawnReason (implementation-phase.C2)

`src/agentkit/workers/types.py:SpawnReason` existiert bereits korrekt. Aber:

- `src/agentkit/prompt_composer/selectors.py:select_template_name` vergleicht `spawn_reason == "remediation"` als String. Signatur wird umgestellt: Parameter wird `SpawnReason` (Import aus `agentkit.backend.core_types`), Vergleiche werden typisiert.
- Bestehende `SpawnReason`-Definition in `workers/types.py` wird zugunsten von `agentkit.backend.core_types.SpawnReason` aufgegeben (Re-Export erlaubt, aber kanonische Definition wandert ins Core-Modul).

#### 2.1.8 Migration — EnvelopeStatus (artifacts.B3)

Die in `verify_system/policy_engine/projections.py` verwendeten Status-Werte (`PASS`, `PASS_WITH_WARNINGS`) werden auf `EnvelopeStatus` aus `agentkit.backend.core_types` umgestellt:

- Wertebereich `PASS`, `FAIL`, `WARN`, `ERROR`
- `PASS_WITH_WARNINGS` faellt weg (passt zu 2.1.2-Policy-Engine-Migration)

#### 2.1.9 Tests

##### 2.1.9.1 Unit-Tests pro Sub-Modul

Pro Enum jeweils unter `tests/unit/core_types/test_<modul>.py`:

- Jeder Wert ist konstruierbar (`Severity("BLOCKING")` etc.).
- Iteration ist deterministisch und liefert exakt die in 2.1.1.1 dokumentierten Werte in derselben Reihenfolge.
- `StrEnum`-Invariante: `Enum.<MEMBER>.value == "<wire>"` und `isinstance(Enum.<MEMBER>, str)`.
- Unbekannter Wert wirft `ValueError` (`Severity("CRITICAL")` schlaegt fehl, `PauseReason("foo")` schlaegt fehl etc.).
- `from_yield_status` (falls implementiert): Vollstaendige Mapping-Tabelle aus 2.1.4 wird zeilenweise getestet inkl. der `ValueError`-Pfade.

##### 2.1.9.2 Contract-Test-Pflichtliste

`tests/contract/core_types/test_enum_wire_values.py` enthaelt **eine** parametrisierte Test-Funktion pro Enum mit folgender Pflichtliste — jeder Eintrag ist ein Tupel `(Enum, set_of_members, dict_of_wire_values)`. Drift in einem dieser Werte schlaegt sofort fehl:

| Test-Funktion | Enum | Anzahl Werte | Quelle |
|---|---|---|---|
| `test_severity_wire_values`            | `Severity`            | 3  | FK-27 §27.4.2 |
| `test_qa_context_wire_values`          | `QaContext`           | 4  | bc-cut Z. 84-95 |
| `test_policy_verdict_wire_values`      | `PolicyVerdict`       | 2  | FK-27 §27.7.2 |
| `test_exploration_gate_wire_values`    | `ExplorationGateStatus`| 3 | FK-23 §23.5.0 |
| `test_pause_reason_wire_values`        | `PauseReason`         | 3  | FK-39 §39.2.2 |
| `test_attempt_outcome_wire_values`     | `AttemptOutcome`      | 6  | FK-39 §39.4.2 |
| `test_failure_cause_wire_values`       | `FailureCause`        | 16 | FK-39 §39.4.3 |
| `test_artifact_class_wire_values`      | `ArtifactClass`       | 8  | FK-71 §71.1.1 |
| `test_envelope_status_wire_values`     | `EnvelopeStatus`      | 4  | FK-71 §71.2 |
| `test_story_size_wire_values`          | `StorySize`           | 5  | DK-10 §10.4 |
| `test_story_mode_wire_values`          | `StoryMode`           | 3  | FK-24 §24.3.2 + AG3-018 |
| `test_closure_verdict_wire_values`     | `ClosureVerdict`      | 2  | bc-cut §BC 8 Closure |
| `test_merge_policy_wire_values`        | `MergePolicy`         | 2  | FK-29 §29.1.5 |
| `test_story_dependency_kind_wire_values`| `StoryDependencyKind`| 8  | FK-70 §70.4.2 |
| `test_failure_category_wire_values`    | `FailureCategory`     | 12 | FK-41 §41.4.1 |
| `test_promotion_status_wire_values`    | `PromotionStatus`     | 7  | FK-41 Glossar |
| `test_blocking_category_wire_values`   | `BlockingCategory`    | 4  | FK-26 §26.8.2 Glossar |
| `test_spawn_reason_wire_values`        | `SpawnReason`         | 3  | bc-cut §BC 6 + FK-26 §26.2 |

Implementierungshinweis: die Wire-Werte werden im Test als Konstante in einem Modul-Dict gepinnt; Vergleich erfolgt via `set({m.value for m in Enum}) == expected_set` UND `{m.name: m.value for m in Enum} == expected_map`. Damit ist sowohl die Werteliste als auch die Member-Namen-Konvention festgenagelt.

##### 2.1.9.3 Migrationsfolge-Tests

- Existierende Tests in `tests/unit/verify_system/`, `tests/unit/pipeline/`, `tests/unit/story_context_manager/`, `tests/unit/execution_planning/`, `tests/unit/prompting/` werden auf neue Enum-Werte umgestellt.
- Neuer Test in `tests/unit/pipeline/test_engine_pause_reason_typing.py`: `_handle_paused_result` weist freie Strings ausserhalb der Wertemenge fail-closed ab (AG3-024-Pfad — bleibt aber AG3-021-Scope: Foundation-Enum + Engine-Typisierung).

### 2.2 Out of Scope

- Logische Aenderung an PolicyEngine-Schwellen (welche Severities aggregieren wie zur Endentscheidung — bleibt unveraendert, nur Wertebereich migriert)
- Stage-Registry-Bindung mit BLOCKING/MAJOR/MINOR (gehoert zu THEME-009/`verify-system.B3`)
- Layer 1 Erweiterung (`verify-system.B1` — separate Story der THEME-009-Welle)
- `AttemptRecord`-Schema-Erweiterung (das gehoert zu THEME-004, AG3-025)
- `PhaseEnvelope`-Einfuehrung (THEME-004, AG3-024)
- Stage-Definition-Modelle (`StageDefinition`, `stages_for(story_type)`) — THEME-009
- `IncidentCandidate`, `IncidentRepository` und alle weiteren Failure-Corpus-Klassen ausser den hier definierten Enums (`FailureCategory`, `PromotionStatus`) — THEME-005 Sub-Story und Folge
- Aktualisierung von Konzept-Dokumenten — die Enums spiegeln das Konzept; keine Konzept-Anpassung
- ExecutionPlanning-Logik (hard vs. soft-Auswertung) — separate Story
- `StoryStatus`-Wire-Werte ("In Progress" etc.) — die sind in AG3-014 bereits implementiert und nicht Teil des Core-Type-Moduls; bleibt im Owner-BC `story_context_manager`

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/core_types/__init__.py` | Neu | Re-Export aller oeffentlichen StrEnum-Typen |
| `src/agentkit/core_types/severity.py` | Neu | `Severity` StrEnum (BLOCKING/MAJOR/MINOR) |
| `src/agentkit/core_types/qa_context.py` | Neu | `QaContext` StrEnum (vier Werte) |
| `src/agentkit/core_types/policy_verdict.py` | Neu | `PolicyVerdict` StrEnum (PASS/FAIL) |
| `src/agentkit/core_types/exploration.py` | Neu | `ExplorationGateStatus` StrEnum |
| `src/agentkit/core_types/pause_reason.py` | Neu | `PauseReason` StrEnum (drei Werte) |
| `src/agentkit/core_types/attempt.py` | Neu | `AttemptOutcome`, `FailureCause` StrEnums |
| `src/agentkit/core_types/artifact.py` | Neu | `ArtifactClass`, `EnvelopeStatus` StrEnums |
| `src/agentkit/core_types/story.py` | Neu | `StorySize`, `StoryMode` StrEnums |
| `src/agentkit/core_types/closure.py` | Neu | `ClosureVerdict`, `MergePolicy` StrEnums |
| `src/agentkit/core_types/dependency.py` | Neu | `StoryDependencyKind` StrEnum (acht Werte) |
| `src/agentkit/core_types/failure_corpus.py` | Neu | `FailureCategory`, `PromotionStatus` StrEnums |
| `src/agentkit/core_types/worker.py` | Neu | `BlockingCategory`, `SpawnReason` StrEnums |
| `src/agentkit/verify_system/protocols.py` | Modifiziert | `Severity` durch Core-Type ersetzen; Migration aller Aufrufstellen |
| `src/agentkit/verify_system/policy_engine/engine.py` | Modifiziert | `PolicyVerdict`/`Severity` aus Core, kein PASS_WITH_WARNINGS |
| `src/agentkit/verify_system/policy_engine/projections.py` | Modifiziert | `EnvelopeStatus` aus Core |
| `src/agentkit/verify_system/policy_engine/trust.py` | Modifiziert | Severity-Mapping auf BLOCKING/MAJOR/MINOR |
| `src/agentkit/story_context_manager/models.py` | Modifiziert | `VerifyContext` -> `QaContext` (Import aus Core, vier Werte); `gate_status: ExplorationGateStatus \| None` |
| `src/agentkit/story_context_manager/types.py` | Modifiziert | `StoryMode.NOT_APPLICABLE` entfernen; `StorySize` durch Core ersetzen; `StoryMode.FAST` ergaenzen |
| `src/agentkit/story_context_manager/sizing.py` | Modifiziert | `StorySize.SMALL/MEDIUM/LARGE/EPIC` durch XS/S/M/L/XL |
| `src/agentkit/story_context_manager/story_model.py` | Modifiziert | `WireStorySize.XXL` entfernen; Konsolidierung mit `StorySize` aus Core |
| `src/agentkit/pipeline/engine.py` | Modifiziert | `paused_reason` typisiert (`PauseReason`); fail-closed bei unbekannten Werten |
| `src/agentkit/execution_planning/entities.py` | Modifiziert | `StoryDependencyKind` durch acht-Wert-Variante aus Core ersetzen |
| `src/agentkit/workers/types.py` | Modifiziert | `SpawnReason` als Re-Export aus Core; kanonische Definition in Core |
| `src/agentkit/prompt_composer/selectors.py` | Modifiziert | Parameter `spawn_reason: SpawnReason` (kein String), typisierte Vergleiche |
| `tests/unit/core_types/test_severity.py` | Neu | Severity-Enum-Tests |
| `tests/unit/core_types/test_qa_context.py` | Neu | QaContext-Enum-Tests |
| `tests/unit/core_types/test_exploration.py` | Neu | ExplorationGateStatus-Tests |
| `tests/unit/core_types/test_pause_reason.py` | Neu | PauseReason-Tests + `from_yield_status` |
| `tests/unit/core_types/test_attempt.py` | Neu | AttemptOutcome/FailureCause-Tests |
| `tests/unit/core_types/test_artifact.py` | Neu | ArtifactClass/EnvelopeStatus-Tests |
| `tests/unit/core_types/test_story.py` | Neu | StorySize/StoryMode-Tests |
| `tests/unit/core_types/test_closure.py` | Neu | ClosureVerdict/MergePolicy-Tests |
| `tests/unit/core_types/test_dependency.py` | Neu | StoryDependencyKind-Tests |
| `tests/unit/core_types/test_failure_corpus.py` | Neu | FailureCategory/PromotionStatus-Tests |
| `tests/unit/core_types/test_worker.py` | Neu | BlockingCategory/SpawnReason-Tests |
| `tests/contract/core_types/test_enum_wire_values.py` | Neu | Wire-Wert-Pflichtliste pro Enum |
| `tests/unit/verify_system/test_policy_engine.py` | Modifiziert | Auf BLOCKING/MAJOR/MINOR und PASS/FAIL umstellen |
| `tests/unit/story_context_manager/...` | Modifiziert | QaContext-Migration, StorySize-Migration |
| `tests/unit/execution_planning/...` | Modifiziert | StoryDependencyKind-Migration |
| `tests/unit/pipeline/...` | Modifiziert | PauseReason-Migration |
| `tests/unit/prompting/test_selectors.py` | Modifiziert | typisierte SpawnReason-Parameter |

## 4. Akzeptanzkriterien

1. **Modul `src/agentkit/core_types/` existiert** mit allen oben aufgefuehrten Sub-Modulen; `from agentkit.backend.core_types import Severity, QaContext, PolicyVerdict, ExplorationGateStatus, PauseReason, AttemptOutcome, FailureCause, ArtifactClass, EnvelopeStatus, StorySize, StoryMode, ClosureVerdict, MergePolicy, StoryDependencyKind, FailureCategory, PromotionStatus, BlockingCategory, SpawnReason` ist erfolgreich.
2. **`Severity` hat genau die Werte `BLOCKING`, `MAJOR`, `MINOR`** (keine `CRITICAL`/`HIGH`/`MEDIUM`/`LOW`/`INFO`). Wire-Werte sind **upper-case** Strings exakt `"BLOCKING"`, `"MAJOR"`, `"MINOR"` (siehe 2.1.1.1, Quelle FK-27 §27.4.2 Tabelle).
3. **`PolicyVerdict` enthaelt nur `PASS` und `FAIL`** — kein `PASS_WITH_WARNINGS`. `PolicyEngine.decide` gibt nur diese beiden Verdicts zurueck. Wire-Werte siehe 2.1.1.1. (Der LLM-Status `PASS_WITH_CONCERNS` ist davon abgegrenzt und gehoert in AG3-022.)
4. **`QaContext` enthaelt exakt vier Werte**: `IMPLEMENTATION_INITIAL`, `IMPLEMENTATION_REMEDIATION`, `EXPLORATION_INITIAL`, `EXPLORATION_REMEDIATION`. Wire-Werte sind upper-case Strings (siehe 2.1.1.1). Code, der frueher `VerifyContext` importierte, importiert jetzt `QaContext` und alle Aufrufstellen verwenden die neuen Werte.
5. **`PauseReason` enthaelt exakt drei Werte**: `AWAITING_DESIGN_REVIEW`, `AWAITING_DESIGN_CHALLENGE`, `GOVERNANCE_INCIDENT` (Wire-Werte siehe 2.1.1.1). `pipeline.engine._handle_paused_result` typisiert `paused_reason` und lehnt unbekannte Werte fail-closed ab. Der Helper `PauseReason.from_yield_status` ist gemaess Mapping-Tabelle in 2.1.4 implementiert ODER ausdruecklich aus dem Scope genommen (Variantenwahl gemaess 2.1.4 letzter Absatz).
6. **`AttemptOutcome` enthaelt sechs Werte** (`COMPLETED`, `FAILED`, `ESCALATED`, `SKIPPED`, `YIELDED`, `BLOCKED`) und **`FailureCause` enthaelt 16 Werte** gemaess Tabelle 2.1.1.1 / FK-39 §39.4.2/39.4.3. (Die `AttemptRecord`-Schema-Anpassung selbst gehoert zu AG3-025; hier reicht die Enum-Verfuegbarkeit.)
7. **`ArtifactClass` enthaelt acht Werte** mit lower-case Wire-Strings (`"worker"`, `"qa"`, `"pipeline"`, `"telemetry"`, `"governance"`, `"entwurf"`, `"handover"`, `"adversarial_test_sandbox"`); `EnvelopeStatus` enthaelt `PASS`, `FAIL`, `WARN`, `ERROR` (upper-case).
8. **`StorySize` enthaelt nur `XS`, `S`, `M`, `L`, `XL`** mit Wire-Werten identisch zum Python-Member-Namen (upper-case). Kein `XXL`, kein `epic`, kein `SMALL/MEDIUM/LARGE`. Bestehender Code wurde durchgaengig migriert.
9. **`StoryMode`-Werte sind `EXECUTION`, `EXPLORATION`, `FAST`** mit **lower-case** Wire-Strings (`"execution"`, `"exploration"`, `"fast"` — konsistent mit FK-24 §24.3.2 Lower-Case-Konvention). Kein `NOT_APPLICABLE`. Aufrufer, die frueher `NOT_APPLICABLE` verwendeten, vergleichen jetzt gegen `None` (Optional-Feld).
10. **`StoryDependencyKind` enthaelt acht Werte** gemaess FK-70 §70.4.2 mit lower-case Wire-Strings (siehe 2.1.1.1). Existing-Code (`execution_planning/entities.py`) verwendet ausschliesslich Core-Enum.
11. **`SpawnReason` ist in `core_types/worker.py`** definiert mit drei lower-case Wire-Werten (`"initial"`, `"paused_retry"`, `"remediation"`); `workers/types.py` re-exportiert; `prompt_composer/selectors.py` akzeptiert `SpawnReason` (kein String-Parameter).
12. **`ClosureVerdict` enthaelt zwei Werte** (`COMPLETED`, `ESCALATED`, upper-case Wire-Strings); **`MergePolicy` enthaelt zwei Werte** (`FF_ONLY`, `NO_FF`) mit Wire-Strings `"ff_only"` / `"no_ff"`. (Aktive Verwendung in `closure/`-Modulen ist Aufgabe spaeter Stories.)
13. **`FailureCategory` enthaelt genau die 12 Werte aus FK-41 §41.4.1** (siehe Tabelle in 2.1.1.1: `SCOPE_DRIFT`, `ARCHITECTURE_VIOLATION`, `EVIDENCE_FABRICATION`, `HALLUCINATION`, `TEST_OMISSION`, `ASSERTION_WEAKNESS`, `UNSAFE_REFACTOR`, `POLICY_VIOLATION`, `TOOL_MISUSE`, `STATE_DESYNC`, `REQUIREMENTS_MISS`, `REVIEW_EVASION`). **`PromotionStatus` enthaelt genau die sieben Werte aus FK-41 Glossar** (`MONITORING`, `DRAFT`, `APPROVED`, `ACTIVE`, `TUNED`, `RETIRED`, `REJECTED`). **`BlockingCategory` enthaelt vier Werte** (siehe 2.1.1.1).
14. **Contract-Test `tests/contract/core_types/test_enum_wire_values.py`** durchlaeuft alle Enums entsprechend der Pflichtliste in 2.1.9.2 (eine Test-Funktion pro Enum, exakter Set-Vergleich von `{(member.name, member.value)}`); jede Drift schlaegt sofort.
15. **`grep` nach veralteten Strings findet keine Treffer** in `src/`:
    - `Severity.CRITICAL`, `Severity.HIGH`, `Severity.MEDIUM` (auf StrEnum-Member), `Severity.LOW`, `Severity.INFO`
    - `PASS_WITH_WARNINGS` (Policy-Verdict; LLM-Status `PASS_WITH_CONCERNS` ist erlaubt — siehe Begriffskasten 2.1.1.2)
    - `VerifyContext.POST_IMPLEMENTATION`, `POST_REMEDIATION`
    - `StoryMode.NOT_APPLICABLE`
    - `StorySize.SMALL`, `StorySize.MEDIUM`, `StorySize.LARGE`, `StorySize.EPIC`, `WireStorySize.XXL`
    - `StoryDependencyKind.BLOCKS`, `DERIVES_FROM`, `BRANCHES_OFF`
    - alte `FailureCategory`-Werte wie `INSTRUCTION_NEGLECT`, `BAR_RAISING_FAILURE`, `TEST_FRAMEWORK_GAP`, `IMPORT_STRUCTURE_DRIFT`, `CONCEPT_VIOLATION`, `DOC_FIDELITY_DRIFT`, `ARE_GATE_FAIL`, `GUARD_BREACH`, `WORKER_RUNAWAY`, `ENVIRONMENTAL_FAILURE`, `OTHER` (falls vorher im Repo) — Werte sind nicht Teil von FK-41 §41.4.1
16. **Pflichtbefehle gruen**: pytest unit + contract; `mypy --strict src tests` clean; `ruff check src tests` clean; Coverage haelt 85% (CLAUDE.md).
17. **Architecture-Conformance-Checks** (`scripts/ci/check_architecture_conformance.py`, `check_concept_code_contracts.py`) bleiben gruen.

## 5. Definition of Done

- Alle Akzeptanzkriterien 1-17 erfuellt.
- `T:/codebase/claude-agentkit3/.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Coverage haelt 85%-Schwelle.
- Aenderungen committed auf `main` (Story-Status-Commit als Folgecommit).
- Architecture-Conformance- und Concept-Code-Contract-Validatoren gruen.

## 6. Konzept-Referenzen (autoritativ, mit `rel_path`)

- **FK-27 §27.4.2** — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` — Severity-Kategorien BLOCKING/MAJOR/MINOR (inkl. Wire-Casing der Severity-Strings)
- **FK-27 §27.7.2** — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` — Policy-Verdict PASS/FAIL (kein PASS_WITH_WARNINGS)
- **FK-23 §23.5.0** — `concept/technical-design/23_modusermittlung_exploration_change_frame.md` — `ExplorationGateStatus`-StrEnum (Z. 360-394)
- **FK-39 §39.2.2** — `concept/technical-design/39_phase_state_persistenz.md` — `PauseReason`-StrEnum (Glossar-Eintrag Z. 62-69)
- **FK-39 §39.4.2/39.4.3** — `concept/technical-design/39_phase_state_persistenz.md` — `AttemptOutcome` (Z. 391-402)/`FailureCause` (Z. 404-422)
- **FK-71 §71.1.1/71.2** — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` — `ArtifactClass` (Z. 84-99) / `EnvelopeStatus` (Z. 132-158)
- **FK-24 §24.3.2** — `concept/technical-design/24_story_type_mode_terminalitaet.md` — `StoryMode`, `execution_route` (Z. 157-175)
- **FK-24 §24.5/24.6** — `concept/technical-design/24_story_type_mode_terminalitaet.md` — Terminality (Hintergrund fuer StoryMode-Schnitt, Z. 275-360)
- **DK-10 §10.4** — `concept/domain-design/10-story-lifecycle-und-erstellung.md` — Story-Groessen XS/S/M/L/XL (5 Stufen)
- **FK-29 §29.1.5** — `concept/technical-design/29_closure_sequence.md` — `MergePolicy` (Z. 351-358)
- **`concept/_meta/bc-cut-decisions.md` §BC 8 Closure-Top** — `ClosureVerdict` (StrEnum COMPLETED/ESCALATED, Z. 558-560)
- **FK-70 §70.4.2** — `concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md` — `StoryDependencyKind` mit acht Werten (Z. 211-220)
- **FK-41 §41.4.1** — `concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md` — `FailureCategory` 12 Werte (Z. 281-294)
- **FK-41 Glossar** — `concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md` — `PromotionStatus` (Z. 70-76: MONITORING/DRAFT/APPROVED/ACTIVE/TUNED/RETIRED/REJECTED)
- **`concept/_meta/bc-cut-decisions.md §QaContext-Werte`** — Z. 84-95 — vier Werte
- **`concept/_meta/bc-cut-decisions.md §BC 6 implementation-phase`** — Z. 415-456 — `BlockingCategory`, `SpawnReason`
- **`concept/_meta/bc-cut-decisions.md §BC 13 failure-corpus`** — Z. 1177-1218 — `FailureCategory`, `PromotionStatus` (Querverweis und Klassen-Skizze)
- **FK-26 §26.8.2** — `concept/technical-design/26_implementation_runtime_worker_loop.md` — `BlockingCategory`-Glossar (Z. 42-53) und WorkerManifestStatus

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: ein Owner-Modul fuer Cross-Cutting-Typen; keine zweite Severity-Definition pro BC, keine String-Fallbacks.
- **ZERO DEBT**: keine Deprecation-Shims; alle alten Werte werden in einem Wurf migriert.
- **FAIL CLOSED**: unbekannte PauseReason-/AttemptOutcome-/Severity-Werte werden hart abgewiesen (`ValueError` beim StrEnum-Lookup).
- **SINGLE SOURCE OF TRUTH**: `agentkit.backend.core_types` ist die einzige kanonische Definition jeder hier gelisteten Enum.
- **NO ERROR BYPASSING**: keine `# type: ignore`-Workarounds; kein freier String fuer einen Wert, der jetzt typisiert ist.

## 8. Hinweise fuer den Sub-Agent

- Reihenfolge: ZUERST Core-Types schreiben + isolierte Unit-Tests, DANN die Migrationen pro Datei. Migration kann in nachfolgenden Commits, aber alles muss in einem PR landen (gleiche Story).
- `StrEnum` aus `enum` (Python 3.11+), nicht `str, Enum`-Mixin. Pflicht: `from __future__ import annotations` pro Modul.
- Wire-Wert pro Enum-Member: **exakt** der String aus Abschnitt 2.1.1.1 (siehe Tabellen pro Enum). Die Werte sind normativ; der Contract-Test in 2.1.9.2 pinnt jeden Wert. Casing-Konvention: in 2.1.1.1 pro Enum ausgezeichnet (upper-case fuer Severity/PolicyVerdict/QaContext/PauseReason/AttemptOutcome/FailureCause/EnvelopeStatus/StorySize/ClosureVerdict/BlockingCategory; lower-case fuer ExplorationGateStatus/StoryMode/ArtifactClass/MergePolicy/StoryDependencyKind/FailureCategory/PromotionStatus/SpawnReason).
- Architecture-Conformance: `agentkit.backend.core_types` ist ein Foundation-Modul; es darf von **keinem** anderen Modul importieren (kein zyklischer Import). Pruefen via `check_architecture_conformance.py`.
- AK2 (`T:/codebase/claude-agentkit/`) NICHT veraendern. Lesen erlaubt zur Orientierung, schreiben verboten.
