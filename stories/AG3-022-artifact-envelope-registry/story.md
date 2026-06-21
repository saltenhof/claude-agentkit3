# AG3-022: Artefakt-BC Foundation — ArtifactEnvelope, ArtifactReference, ProducerRegistry

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Core-Enums: `ArtifactClass`, `EnvelopeStatus`)
**Quell-Konzepte (autoritativ, mit `rel_path` ab Repo-Root):**
- `FK-71 §71.1.1` — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (acht Artefaktklassen, Z. 84-99)
- `FK-71 §71.2` — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (Envelope-Pflichtfelder, Producer-Registry, `schema_version="3.0"`, LLM-Status-Mapping, Z. 109-181)
- `concept/_meta/bc-cut-decisions.md §BC 8 artifacts` — Z. 715-770 (Paket `agentkit.backend.artifacts`, Top-Surface, Sub-Komponenten)
- `FK-71 Glossar` — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (Eintrag `ArtifactReference`)

---

## 1. Kontext

THEME-003 aus `stories/_priorisierungsempfehlung.md`, Teil 1. Das Paket `agentkit.backend.artifacts` existiert noch nicht (`artifacts.A1`). Ohne dieses BC-Modul bauen alle Schreibstellen (Worker-Handover, QA-Layer, Closure, Prompt-Audit, ARE-Bundle) rohe dicts ohne Envelope-Pflichtfelder; IntegrityGate kann nur Existenz pruefen, keine Pflichtfeld-Validierung (`artifacts.B4`); Producer-Registry-Validierung fehlt (`artifacts.A5`).

Diese Story legt das **Foundation-Layer**: typisierte Pydantic-Modelle und Producer-Registry. **Ohne Persistenz-Wechsel und ohne Migration der bestehenden QA-Persistenz**. Die Migration der existierenden `verify_system/artifacts.py`-Persistenz auf `ArtifactManager` ist Inhalt von AG3-023.

Spezifische Befunde:
- `artifacts.A1`: Paket `agentkit.backend.artifacts` fehlt
- `artifacts.A3`: `ArtifactEnvelope`-Pydantic-Modell fehlt
- `artifacts.A4`: `EnvelopeValidator` fehlt
- `artifacts.A5`: `ProducerRegistry` mit LLM-Status-Mapping fehlt
- `artifacts.A6`: `Producer`, `ProducerType`, `ProducerId` fehlen
- `artifacts.A7`: `ArtifactReference` fehlt
- `artifacts.B1`: Nur 2 von 8 Artefaktklassen (Heuristik in `state_backend/postgres_store.py`)
- `artifacts.C3`: `SCHEMA_VERSION="3.3.0"` verwechselbar mit Envelope-`schema_version="3.0"`

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Neues Paket `src/agentkit/artifacts/`

Modul-Struktur:

- `__init__.py` — Top-Surface-Re-Export: `ArtifactEnvelope`, `ArtifactClass` (re-export aus core_types), `EnvelopeStatus` (re-export aus core_types), `ArtifactReference`, `Producer`, `ProducerType`, `ProducerId`, `EnvelopeValidator`, `ProducerRegistry`
- `envelope.py` — `ArtifactEnvelope`-Pydantic-v2-Modell und `EnvelopeValidator`
- `producer.py` — `Producer`, `ProducerType`, `ProducerId`
- `producer_registry.py` — `ProducerRegistry` mit LLM-Status-Mapping
- `reference.py` — `ArtifactReference`

#### 2.1.2 `ArtifactEnvelope` (FK-71 §71.2)

Pydantic-v2-Modell, `frozen=True`, `extra="forbid"`. Pflichtfelder:

- `schema_version: Literal["3.0"]` — fester Wert, kein Drift mit `state_backend.config.SCHEMA_VERSION`
- `story_id: str` — Story-Display-ID
- `run_id: str` — Run-Korrelation
- `stage: str` — Stage-ID (typisiert spaeter ueber StageRegistry; hier String mit Mindestpattern)
- `attempt: int` — Versuchszaehler (>=1)
- `producer: Producer` — typisierter Producer (siehe 2.1.3)
- `started_at: datetime` — UTC-Timestamp
- `finished_at: datetime` — UTC-Timestamp; >= `started_at`
- `status: EnvelopeStatus` — aus `core_types`, vier Werte (`PASS`, `FAIL`, `WARN`, `ERROR`)
- `artifact_class: ArtifactClass` — aus `core_types`, acht Werte
- `payload: dict[str, Any] | None` — optionale Nutzdaten (Pydantic-konforme Serialisierung)

Validatoren:
- `finished_at >= started_at`
- `attempt >= 1`
- `story_id` matched dem Pattern `^[A-Z][A-Z0-9]+-\d+$` (z.B. `AK3-042`)

#### 2.1.3 `Producer`, `ProducerType`, `ProducerId` (bc-cut-decisions.md §BC 8)

- `ProducerType` als StrEnum mit den drei Konzept-Typen: `WORKER`, `LLM_REVIEWER`, `DETERMINISTIC`
- `ProducerId` als NewType (`NewType("ProducerId", str)`)
- `Producer` als Pydantic-Modell:
  - `type: ProducerType`
  - `name: str` — kanonischer Produzent-Name (z.B. `qa-semantic-reviewer`, `worker-implementation`)
  - `id: ProducerId` — eindeutige Instanz-ID
  - `version: str | None` — optional (Tool-Version, Bundle-Version etc.)

#### 2.1.4 `ArtifactReference` (FK-71 Glossar)

Pydantic-v2-Modell, `frozen=True`:
- `artifact_class: ArtifactClass`
- `story_id: str`
- `run_id: str`
- `record_key: str` — kanonischer Pfad oder Record-Identifier

#### 2.1.5 `ProducerRegistry` (FK-71 §71.2, bc-cut-decisions.md §BC 8)

Registriert pro Export-Artefakt-Klasse die erlaubten Producer-Namen plus LLM-Status-Mapping.

API:

```python
class ProducerRegistry:
    def register(self, artifact_class: ArtifactClass, producer_name: str, producer_type: ProducerType) -> None: ...
    def validate(self, envelope: ArtifactEnvelope) -> None: ...  # fail-closed bei unbekanntem Producer
    def map_llm_status_to_envelope_status(self, llm_status: str) -> EnvelopeStatus: ...
    def known_producers(self, artifact_class: ArtifactClass) -> set[str]: ...
```

LLM-Status-Mapping (FK-71 §71.2, `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` Z. 145-161):

| LLM-Check-Status (eingehend) | Envelope-`EnvelopeStatus` (gemappt) | Quelle |
|---|---|---|
| `"PASS"`              | `EnvelopeStatus.PASS`  | FK-71 §71.2 Z. 156 |
| `"PASS_WITH_CONCERNS"`| `EnvelopeStatus.WARN`  | FK-71 §71.2 Z. 157 (Wire-String `PASS_WITH_CONCERNS` ist **nur** LLM-Status, kein Envelope-Status) |
| `"FAIL"`              | `EnvelopeStatus.FAIL`  | FK-71 §71.2 Z. 158 |
| `"ERROR"`             | `EnvelopeStatus.ERROR` | FK-71 §71.2 Z. 160 (Infrastruktur-Fehler) |
| `"TIMEOUT"`           | `EnvelopeStatus.ERROR` | Erweiterung um Timeout — gilt als Infrastruktur-Fehler analog `ERROR` |
| beliebiger anderer String | `LlmStatusMappingError` (fail-closed) | Konzeptkonform: kein unbekannter Status passiert |

**Wichtige Abgrenzung** (Codex-Befund §"Konzept-Spannungen" Pkt. 1):
- `PASS_WITH_CONCERNS` ist **ausschliesslich** LLM-Check-Wire-String. Er wird hier zu `EnvelopeStatus.WARN` gemappt — keine Wiedereinfuehrung des historischen `PASS_WITH_WARNINGS` ins `PolicyVerdict`-Enum oder in die Policy-Engine (siehe AG3-021 §2.1.1.2 Begriffskasten).

`validate(envelope)` wirft `ProducerNotRegisteredError` (eine neue typisierte Exception unter `agentkit.backend.artifacts.errors`) fail-closed.

##### 2.1.5.1 Producer-Registry-Init-Strategie (Codex-Befund 2)

Die Registry hat in AG3-022 eine **klar definierte Init-Mechanik** — keine impliziten Dummy-Seeds, keine Test-Stubs, kein "ein BC registriert spaeter schon":

- **Konstruktor `ProducerRegistry()`** erzeugt eine Instanz mit:
  - **Klassen-Seed**: alle acht `ArtifactClass`-Werte sind als Keys in der internen Map vorhanden, jeweils mit `producers: dict[str, ProducerType] = {}` (leerem Producer-Set).
  - **LLM-Status-Mapping**: das Mapping aus FK-71 §71.2 ist als Klassen-Konstante in `producer_registry.py` hart kodiert (siehe unten 2.1.5.2). Es ist Teil des Registry-Objekts und nicht dynamisch aenderbar.
- **Keine Produktions-Producer in AG3-022**: AG3-022 registriert **keine** konkreten Producer (`verify-system.layer-1-structural` etc.). Diese Registrierung passiert in **AG3-023** §2.1.6 (`register_verify_producers(registry)` Init-Hook im verify-system-Paket).
- **Zwischenzustand zwischen AG3-022 und AG3-023**: Im Zeitraum nach AG3-022 (verfuegbare Registry, aber noch ohne Producer-Seeds) und vor AG3-023 (Producer-Seeds des verify-system) gilt: jede `ProducerRegistry.validate(envelope)` mit beliebigem Producer-Namen wirft `ProducerNotRegisteredError`. Das ist gewollt fail-closed — Code, der einen `ArtifactManager.write` versucht, wird ohne registrierte Producer scheitern. AG3-022 ist Foundation-Story; AG3-023 zieht die echten Konsumenten an.
- **Tests**:
  - Unit-Tests von `ProducerRegistry` in AG3-022 nutzen **reale Registry-Instanzen** mit Ad-hoc-`register(...)`-Aufrufen pro Test (kein globaler Test-Producer-Seed). Beispiel: ein Test fuer `ArtifactClass.QA` ruft im Setup `registry.register(ArtifactClass.QA, "test-fixture-producer", ProducerType.DETERMINISTIC)` auf, verifiziert dann `validate(envelope)` mit diesem Producer-Namen.
  - **Keine MagicMock**-Producer; reale `Producer`-Instanzen mit echten Pflichtfeldern.
- **Composition-Root-Frage**: ob die Registry-Instanz im Produktionscode ein Singleton ist oder pro App-Bootstrap erzeugt wird, ist **AG3-023-Scope** (siehe AG3-023 §2.1.6 und §8 Hinweise zum Composition-Root). AG3-022 macht keinerlei Aussagen ueber Lifecycle der Registry-Instanz; es liefert nur die Klasse.

#### 2.1.6 `EnvelopeValidator` (FK-71 §71.2)

Eigene Klasse (entkoppelt von ArtifactEnvelope-Pydantic-Validierung, weil sie zusaetzliche Cross-Field-Checks gegen externe Wahrheiten erlaubt):

```python
class EnvelopeValidator:
    def __init__(self, registry: ProducerRegistry) -> None: ...
    def validate(self, envelope: ArtifactEnvelope) -> None: ...
```

##### 2.1.6.1 `ArtifactClass × EnvelopeStatus`-Matrix

FK-71 §71.2 (Z. 132-158) definiert kanonisch die vier `EnvelopeStatus`-Werte (`PASS`, `FAIL`, `WARN`, `ERROR`), schreibt aber **keine class-spezifischen Verbote** vor. Die Matrix in dieser Story haelt deshalb folgende Regeln fest — alle ergeben sich entweder aus FK-71 selbst oder aus dem fachlichen Sinn der jeweiligen Klasse:

| `ArtifactClass`              | erlaubte `EnvelopeStatus`             | Begruendung |
|---|---|---|
| `WORKER`                     | `PASS`, `FAIL`, `WARN`, `ERROR`         | Worker-Handover kann grundsaetzlich jeden Status melden (Worker-Manifest-Status COMPLETED / COMPLETED_WITH_ISSUES / BLOCKED projeziert sich darauf). |
| `QA`                         | `PASS`, `FAIL`, `WARN`, `ERROR`         | QA-Layer kann jeden der vier Status erzeugen (`PASS_WITH_CONCERNS` -> `WARN` Mapping, FK-71 §71.2 Z. 154-158). |
| `PIPELINE`                   | `PASS`, `FAIL`, `WARN`, `ERROR`         | Pipeline-Artefakte (`phase_state_projection` etc.) — alle vier Status moeglich. |
| `TELEMETRY`                  | `PASS`, `ERROR`                          | Telemetrie-Events haben binaere Aufnahme-Semantik; `FAIL`/`WARN` sind fachlich nicht definiert (Aufzeichnung gelang oder gelang nicht). |
| `GOVERNANCE`                 | `PASS`, `FAIL`, `WARN`, `ERROR`         | Governance-Artefakte (`integrity-violations.log`, `integrity-gate.json`) — alle vier Status moeglich, da Findings unterschiedlich verdichtet werden. |
| `ENTWURF`                    | `PASS`, `FAIL`, `ERROR`                  | Entwurfsartefakt ist binaer akzeptiert/abgelehnt durch Exploration-Gate; `WARN` ist nicht definiert. |
| `HANDOVER`                   | `PASS`, `FAIL`, `WARN`, `ERROR`         | Worker-Handover-Artefakt; analog `WORKER`. |
| `ADVERSARIAL_TEST_SANDBOX`   | `PASS`, `FAIL`, `WARN`, `ERROR`         | Adversarial-Tests koennen `PASS` (keine Befunde), `FAIL` (Befunde), `WARN` (grenzwertige Befunde) oder `ERROR` (Sandbox-Fehler) liefern. |

Der `EnvelopeValidator` enforced diese Matrix als Schritt 4 (s.u.). Falls eine Klasse einen Status sehen will, der hier nicht erlaubt ist, ist das ein Konzeptbruch und wird mit `EnvelopeFieldError` abgewiesen.

##### 2.1.6.2 Pruefschritte

`EnvelopeValidator.validate(envelope)` durchlaeuft genau diese Schritte in dieser Reihenfolge — bei erstem Fehler fail-closed:

1. **Pydantic-Schema** (durch Pydantic-v2 schon erzwungen — Validator delegiert hier nur; ungueltige Envelopes erreichen den Validator gar nicht erst).
2. **Producer ist im Registry registriert** fuer `envelope.artifact_class` (`ProducerRegistry.validate(envelope)` -> `ProducerNotRegisteredError`).
3. **`attempt`-Plausibilitaet**: `attempt >= 1` (durch Pydantic Field-Validator ohnehin gegeben; redundant fail-closed) -> `EnvelopeFieldError`.
4. **`status`-vs-`artifact_class`-Konsistenz** anhand der Matrix 2.1.6.1 -> `EnvelopeFieldError`.
5. **`finished_at >= started_at`** (durch Pydantic Model-Validator gegeben; hier redundant fail-closed) -> `EnvelopeFieldError`.

Erwartetes Fehlermodell: `EnvelopeValidationError` (Basisfehler), Sub-Klassen `ProducerNotRegisteredError`, `EnvelopeFieldError`, `LlmStatusMappingError`. Alle in `agentkit.backend.artifacts.errors`. Keine Telemetry-Special-Regel mit Epsilon-Differenz — das war in der ersten Story-Skizze; FK-71 §71.2 verlangt nur `finished_at >= started_at` ohne Epsilon (Z. 144).

Hinweis fuer den Worker: Falls die Matrix in 2.1.6.1 sich beim Bauen als zu restriktiv erweist (z.B. `TELEMETRY` benoetigt doch `WARN`), ist das ein Konzeptkonflikt und muss vor Implementierung gemeldet werden — nicht stillschweigend gelockert. Die Matrix folgt aus FK-71 §71.2 plus der fachlichen Klassen-Beschreibung in §71.1.1.

#### 2.1.7 Schema-Versions-Konstanten-Trennung (artifacts.C3)

- `agentkit.backend.artifacts.envelope.ENVELOPE_SCHEMA_VERSION: Final[str] = "3.0"` — Wire-Schema des Envelope
- `agentkit.backend.state_backend.config.SCHEMA_VERSION` bleibt als Storage-Schema-Version unveraendert ("3.3.0" o.ae.) — die Datei wird **nicht angefasst**, aber ein Modul-Docstring erklaert die Unterscheidung
- Contract-Test: ENVELOPE_SCHEMA_VERSION ist "3.0"; jede Envelope-Instanz hat `schema_version="3.0"`

#### 2.1.8 Tests

- Unit-Tests fuer `ArtifactEnvelope` (Pflichtfelder, Validatoren, Pydantic-Serde)
- Unit-Tests fuer `Producer`, `ProducerType`, `ProducerId`
- Unit-Tests fuer `ArtifactReference`
- Unit-Tests fuer `ProducerRegistry` (register, validate, mapping)
- Unit-Tests fuer `EnvelopeValidator` (alle Negativpfade fail-closed)
- Contract-Test in `tests/contract/artifacts/test_envelope_schema.py`:
  - `ENVELOPE_SCHEMA_VERSION == "3.0"`
  - Alle acht `ArtifactClass`-Werte sind registry-bekannt (Default-Seed)
  - LLM-Status-Mapping ist exakt das aus FK-71 §71.2

### 2.2 Out of Scope

- `ArtifactManager` (`artifacts.A2`) und Persistenz-Routing — separate Story AG3-023
- Migration von `verify_system/artifacts.py` auf neuen Manager — separate Story AG3-023
- Verschieben von `PROTECTED_QA_ARTIFACTS` und `LAYER_ARTIFACT_FILES` aus `state_backend/paths.py` nach `governance-and-guards` (`artifacts.C2`) — separate kleine Story bzw. Teil von AG3-023
- IntegrityGate-Erweiterung fuer Envelope-Pflichtfeld-Pruefung (`artifacts.B4`) — gehoert zu THEME-006 (AG3-034)
- ARE-Bundle-Persistenz via ArtifactManager (`requirements-and-scope-coverage.A3`) — gehoert zu der RequirementsCoverage-Story (AG3-030) bzw. nachfolgender ARE-Integrationsstory
- AuditRecord-Persistenz fuer PromptRuntime via ArtifactManager (`prompt-runtime.A5`) — bleibt offen bis AG3-023 + AG3-015-Folgeschritt
- Producer-Registry-Seeds pro BC (welcher BC registriert welche Producer fuer welche Klasse) — bewusst leer in dieser Story; jeder BC registriert in seinem Init-Hook spaeter
- Stage-Typisierung: `stage: str` bleibt hier String; Stage-Registry-Bindung gehoert zu THEME-009

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/artifacts/__init__.py` | Neu | Top-Surface-Re-Export |
| `src/agentkit/artifacts/envelope.py` | Neu | `ArtifactEnvelope`, `ENVELOPE_SCHEMA_VERSION` |
| `src/agentkit/artifacts/producer.py` | Neu | `Producer`, `ProducerType`, `ProducerId` |
| `src/agentkit/artifacts/producer_registry.py` | Neu | `ProducerRegistry` mit LLM-Status-Mapping |
| `src/agentkit/artifacts/reference.py` | Neu | `ArtifactReference` |
| `src/agentkit/artifacts/validator.py` | Neu | `EnvelopeValidator` |
| `src/agentkit/artifacts/errors.py` | Neu | `EnvelopeValidationError`, `ProducerNotRegisteredError`, `EnvelopeFieldError` |
| `tests/unit/artifacts/test_envelope.py` | Neu | Envelope-Validatoren-Tests |
| `tests/unit/artifacts/test_producer.py` | Neu | Producer-Modell-Tests |
| `tests/unit/artifacts/test_producer_registry.py` | Neu | Registry + LLM-Mapping-Tests |
| `tests/unit/artifacts/test_reference.py` | Neu | Reference-Tests |
| `tests/unit/artifacts/test_validator.py` | Neu | EnvelopeValidator-Negativpfade |
| `tests/contract/artifacts/test_envelope_schema.py` | Neu | Wire-Schema-Pflicht-Tests |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/artifacts/` existiert** und exportiert `ArtifactEnvelope`, `ArtifactClass`, `EnvelopeStatus`, `ArtifactReference`, `Producer`, `ProducerType`, `ProducerId`, `EnvelopeValidator`, `ProducerRegistry` ueber `__init__.py`.
2. **`ArtifactEnvelope` ist Pydantic-v2-Modell** mit `frozen=True`, `extra="forbid"`, Pflichtfeldern wie in 2.1.2 und Validatoren `finished_at >= started_at`, `attempt >= 1`, `story_id` Pattern.
3. **`schema_version`** ist Pflichtfeld mit `Literal["3.0"]`. Versuche, einen anderen Wert zu setzen, schlagen mit Pydantic-Validation-Error fehl.
4. **`Producer` traegt Pflichtfelder** `type: ProducerType`, `name: str`, `id: ProducerId`, optional `version`. `ProducerType` ist StrEnum mit `WORKER`, `LLM_REVIEWER`, `DETERMINISTIC`.
5. **`ArtifactReference` ist frozen** und enthaelt `artifact_class`, `story_id`, `run_id`, `record_key`.
6. **`ProducerRegistry.validate(envelope)` ist fail-closed**: ein Envelope mit unbekanntem Producer-Namen fuer die jeweilige Artefaktklasse wirft `ProducerNotRegisteredError`.
7. **`ProducerRegistry.map_llm_status_to_envelope_status`** liefert exakt die FK-71-§71.2-Mappings:
   - `"PASS"` -> `EnvelopeStatus.PASS`
   - `"PASS_WITH_CONCERNS"` -> `EnvelopeStatus.WARN`
   - `"FAIL"` -> `EnvelopeStatus.FAIL`
   - `"ERROR"` -> `EnvelopeStatus.ERROR`
   - `"TIMEOUT"` -> `EnvelopeStatus.ERROR`
   - unbekannte Strings -> `LlmStatusMappingError` (in `errors.py`).
8. **`EnvelopeValidator.validate(envelope)`** durchlaeuft genau die fuenf Pruefschritte aus 2.1.6.2 (Pydantic, Producer-Registry, attempt-Plausibilitaet, status-vs-class-Konsistenz gemaess Matrix 2.1.6.1, `finished_at >= started_at`). Fehler werden mit den spezifischen Sub-Exceptions (`ProducerNotRegisteredError`, `EnvelopeFieldError`, `LlmStatusMappingError`) geworfen — keine generische `EnvelopeValidationError`-Direktwuerfe.
9. **`ENVELOPE_SCHEMA_VERSION`** ist als `Final[str]` in `envelope.py` exportiert; Wert ist `"3.0"`. Modul-Docstring in `envelope.py` erlaeutert die Abgrenzung zu `state_backend.config.SCHEMA_VERSION`.
10. **Architecture-Conformance**: das Paket `agentkit.backend.artifacts` importiert **nicht** aus `agentkit.backend.state_backend`, `agentkit.backend.verify_system`, `agentkit.backend.governance` (kein Persistenz-Cross-Talk). Es importiert nur `agentkit.backend.core_types`.
11. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.
12. **Contract-Test `test_envelope_schema.py`** prueft `ENVELOPE_SCHEMA_VERSION == "3.0"`, alle acht `ArtifactClass`-Werte sind im Registry-Default seeded, das exakte LLM-Status-Mapping aus FK-71 §71.2.

## 5. Definition of Done

- AK 1-12 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/artifacts tests/contract/artifacts -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Coverage haelt 85%-Schwelle.
- Architecture-Conformance- und Concept-Code-Contract-Validatoren gruen.
- Aenderungen committed auf `main` (Story-Status-Commit als Folgecommit).

## 6. Konzept-Referenzen (autoritativ, mit `rel_path`)

- **FK-71 §71.1.1** — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (Z. 84-99) — acht Artefaktklassen
- **FK-71 §71.2** — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (Z. 109-181) — Envelope-Pflichtfelder, Producer-Mapping, LLM-Status-Mapping (Z. 145-161), `schema_version="3.0"`
- **FK-71 Glossar** — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` — Eintrag `ArtifactReference`
- **`concept/_meta/bc-cut-decisions.md §BC 8 artifacts`** — `concept/_meta/bc-cut-decisions.md` (Z. 715-770) — Paket `agentkit.backend.artifacts`, Top-Surface, Klassen-Skizzen
- **AG3-021 §2.1.1.2** — `stories/AG3-021-kern-enums/story.md` — Begriffskasten `PASS_WITH_WARNINGS` (Policy) vs. `PASS_WITH_CONCERNS` (LLM-Status), den AG3-022 anwendet
- **FK-18 §18.9a** — `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` — Schema-Versionierung (Hintergrund fuer `state_backend.config.SCHEMA_VERSION` vs. `ENVELOPE_SCHEMA_VERSION`)

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Artefakt-Owner-Modell endlich an einem Ort; keine zweite operative Wahrheit in `verify_system/artifacts.py` (Migration in AG3-023).
- **ZERO DEBT**: Pflichtfelder vollstaendig, kein TODO fuer fehlende Validierung; LLM-Status-Mapping vollstaendig.
- **FAIL CLOSED**: unbekannte Producer, unbekannte LLM-Status, unvollstaendige Envelopes werden hart abgewiesen.
- **SINGLE SOURCE OF TRUTH**: ENVELOPE_SCHEMA_VERSION lebt im Owner-Modul; Storage-Schema-Version bleibt separat.
- **NO ERROR BYPASSING**: keine Default-Werte, die fehlende Pflichtfelder kaschieren.

## 8. Hinweise fuer den Sub-Agent

- Pydantic v2: `model_config = ConfigDict(frozen=True, extra="forbid")`. Validators als `@field_validator`/`@model_validator`.
- ENVELOPE_SCHEMA_VERSION ist `Final[str]`, nicht in einem StrEnum (es ist eine Versions-Konstante, kein Enum).
- ProducerRegistry: thread-safe muss nicht erzwungen werden (Registry wird zur App-Init befuellt, danach read-only). Aber: Implementierung als `dict[ArtifactClass, set[str]]` ist ausreichend.
- Architecture-Conformance: `agentkit.backend.artifacts` darf nur von `agentkit.backend.core_types` importieren. Pruefen mit `check_architecture_conformance.py`.
- Keine MagicMock-Stubs in den Tests; reale Pydantic-Instanzen, reale Registry-Calls.
- AK2 (`T:/codebase/claude-agentkit/`) NICHT veraendern.
