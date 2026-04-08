# V2-Ballast-Bewertung: Detaillierte Begruendungen

**Datum:** 2026-04-07
**Analyst:** Architektur-Analyst (Claude Opus 4.6)
**Quellen:** analyse-worker-phases-code.md (Code-Analyse), analyse-worker-phases-konzepte.md (Konzept-Analyse)

---

## Vorbemerkung zur Methodik

Die beiden Analyse-Dokumente identifizieren Elemente in drei Kategorien:
1. **"Wahrscheinlich Ballast / v2-Artefakte"** (Code-Analyse, Abschnitt 5)
2. **"Vereinfachungspotential in v3"** (Code-Analyse, Abschnitt 5)
3. **"Optional / Nice-to-have (aber spezifiziert)"** (Konzept-Analyse, Zusammenfassung)

Jedes Element wird nachfolgend einzeln bewertet. Die Bewertung ist bewusst nicht voreingenommen Richtung "weglassen" -- wenn die Ballast-Einstufung duenn begruendet ist, wird das benannt.

---

## Kategorie 1: "Wahrscheinlich Ballast / v2-Artefakte" (aus Code-Analyse)

---

### Element 1: Dynamischer Import von compose-prompt.py

#### Was ist es?
`agentkit/orchestration/prompt_composer.py` laedt das externe Skript `userstory/tools/orchestration/compose-prompt.py` zur Laufzeit ueber `importlib.util.spec_from_file_location()`. Das externe Skript fuehrt die eigentliche Prompt-Komposition durch (Template laden, Mustache-Platzhalter aufloesen, Runtime-Conditionals, Guardrail-Konfiguration einbetten). Die Bridge-Funktion `compose_worker_prompt()` in prompt_composer.py delegiert an dieses dynamisch importierte Modul.

#### Warum als Ballast eingestuft?
Die Code-Analyse stuft dies als "Fragile Python-Importmechanik, besser als regulaeres Modul" ein. Der dynamische Import hat mehrere Schwaechen: kein statisches Type-Checking moeglich, Pfad-Abhaengigkeit zur Laufzeit, keine IDE-Navigation, und duplizierter `SpawnReason`-Typ in beiden Dateien (muss manuell synchron gehalten werden).

#### Gegenposition
Die Trennung hatte in v2 vermutlich einen pragmatischen Grund: `compose-prompt.py` lag in `userstory/tools/` und wurde auch als Standalone-Script genutzt (CLI-Zugang ohne agentkit-Import). Wenn v3 dieses Script ausschliesslich ueber die Python-API nutzt, entfaellt der Grund fuer den dynamischen Import. Wenn jedoch ein Standalone-CLI-Zugang gebraucht wird (z.B. fuer Debugging oder manuelle Prompt-Erstellung), muss eine Alternative bereitgestellt werden.

#### Empfehlung
**Begruendet weglassen.** Die Prompt-Kompositionslogik sollte in v3 als regulaeres Python-Modul innerhalb des `agentkit`-Packages leben. Die Funktionalitaet bleibt vollstaendig erhalten, nur der Lademechanismus aendert sich. Ein CLI-Wrapper kann bei Bedarf als duenner Entrypoint daruebergelegt werden.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "Dynamischer Import von compose-prompt.py"

---

### Element 2: SpawnReason als separater Literal-Typ

#### Was ist es?
`SpawnReason = Literal["initial", "paused_retry", "remediation"]` ist in `agentkit/orchestration/prompt_composer.py` definiert und wird von `phase_runner.py` importiert. Er wird in `compose_worker_prompt()` und `_compose_agent_spawn()` verwendet, um den Spawn-Kontext zu unterscheiden (erster Start, Retry nach Pause, oder Remediation). Zusaetzlich existiert eine Kopie in `userstory/tools/orchestration/compose-prompt.py`.

#### Warum als Ballast eingestuft?
Die Code-Analyse argumentiert: "Kann in v3 direkt ins Spawn-Dict." Die Einstufung besagt, dass der Literal-Typ als eigenstaendige exportierte Abstraktion ueberfluessig ist, da der Wert sowieso nur im Spawn-Dict landet.

#### Gegenposition
Ein typisierter Literal-Typ ist kein Ballast -- er ist ein typsicherer Vertrag. Ohne ihn koennen beliebige Strings als spawn_reason uebergeben werden, was genau die Art von Bug ist, die mypy strict verhindern soll. Die "Vereinfachung" waere ein Typsicherheits-Rueckschritt. Das Problem in v2 war die Duplikation (zwei Dateien mit demselben Literal), nicht der Typ selbst.

#### Empfehlung
**Begruendet uebernehmen, aber konsolidieren.** Der Literal-Typ gehoert in ein zentrales Modul (z.B. `agentkit/core/types.py` oder direkt in die Spawn-Spec-Definition). Die Duplikation in compose-prompt.py entfaellt automatisch, wenn Element 1 (dynamischer Import) eliminiert wird.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "SpawnReason als separater Literal-Typ"

---

### Element 3: NON_DETERMINISTIC_PHASE / NON_DETERMINISTIC_PHASE_RATIONALE Konstanten

#### Was ist es?
Zwei Konstanten in `agentkit/orchestration/worker.py`:
- `NON_DETERMINISTIC_PHASE: Final[str] = "implementation"` -- Benennt die einzige Phase, die LLM-Arbeit enthaelt
- `NON_DETERMINISTIC_PHASE_RATIONALE: Final[str] = (...)` -- Erklaerungstext warum

Eine Hilfsfunktion `is_non_deterministic_phase(phase)` vergleicht gegen die Konstante.

#### Warum als Ballast eingestuft?
Die Code-Analyse stuft sie als "Reine Doku-Konstanten, kein Laufzeiteffekt" ein. Die Rationale-Konstante wird tatsaechlich nie in einer Laufzeitentscheidung verwendet; `is_non_deterministic_phase()` wird im Code nur als semantische Klarstellung genutzt, nicht als Gate.

#### Gegenposition
Die Begruendung ist stichhaltig fuer die `RATIONALE`-Konstante: sie ist reiner Dokumentationstext in Code-Form. Die `NON_DETERMINISTIC_PHASE`-Konstante selbst hat allerdings eine Funktion -- sie wird in `is_non_deterministic_phase()` verwendet, und Tests pruefen sie. Wenn kuenftig Entscheidungen davon abhaengen ob eine Phase deterministisch ist (z.B. fuer Logging, fuer Timeout-Verhalten, fuer Retry-Strategie), waere diese Konstante der richtige Ankerpunkt. In v2 wird sie aber nicht so genutzt.

#### Empfehlung
**Begruendet weglassen als eigene Konstante.** Das Determinismus-Prinzip ist besser im Phase-Transition-Graph oder in der Phase-Konfiguration selbst kodiert (z.B. als Property `requires_llm: bool` pro Phase). Eine freistehende String-Konstante ist fragil -- wenn eine zweite nicht-deterministische Phase hinzukommt (z.B. Exploration), bricht das Modell.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "NON_DETERMINISTIC_PHASE/RATIONALE Konstanten"

---

### Element 4: IncrementStep / INCREMENT_CYCLE Enums

#### Was ist es?
`IncrementStep(StrEnum)` definiert die vier Schritte pro Increment: `IMPLEMENT`, `LOCAL_VERIFY`, `DRIFT_CHECK`, `COMMIT`. `INCREMENT_CYCLE` ist ein Tupel der vier Schritte in fester Reihenfolge. Jeder Schritt hat eine zugehoerige Beschreibung in einer Dict-Konstante. Implementiert in `agentkit/orchestration/increment.py`.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Prompt-Dokumentation, nicht Runtime-enforced." Das bedeutet: der 4-Schritt-Zyklus wird dem Worker per Prompt vorgegeben, aber AgentKit erzwingt zur Laufzeit nicht, dass der Worker die Schritte in dieser Reihenfolge durchlaeuft. Es gibt keinen Runtime-Hook der prüft "Step 1 vor Step 2".

#### Gegenposition
Die Konzept-Analyse (FK-24 SS24.3.2) stuft den 4-Schritt-Zyklus als **essentiell** ein. Der Zyklus ist eine Pflichtanforderung. Dass die Enforcement nur per Prompt und nicht per Runtime-Hook erfolgt, ist eine Designentscheidung -- nicht gleichbedeutend mit "nicht benoetigt". Die Enum-Werte werden zudem in der Prompt-Komposition und in Telemetrie-Events referenziert. Sie als "Ballast" zu bezeichnen verwischt die Grenze zwischen "nicht runtime-enforced" und "nicht benoetigt".

Die Frage ist: Braucht v3 diese Abstraktion als Enum, oder reichen die Werte als Strings im Template? Wenn die Increment-Schritte in v3 per Hook tatsaechlich enforced werden (was konzeptionell vorgesehen ist -- `increment_commit`-Hook existiert bereits), waeren die Enums der richtige Anker.

#### Empfehlung
**Begruendet uebernehmen, aber schlanker.** Die vier Schritte als benannte Konstanten (Enum oder Literal) beibehalten. Die ausfuehrlichen Beschreibungs-Dicts koennen in Docstrings oder Prompt-Templates wandern statt als Runtime-Datenstruktur zu existieren. Wenn v3 Increment-Tracking einfuehrt (was in FK-24 spezifiziert ist), sind typisierte Step-Identifier unverzichtbar.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "IncrementStep/INCREMENT_CYCLE Enums"

---

### Element 5: ReviewTemplate / REVIEW_TEMPLATE_REGISTRY

#### Was ist es?
`ReviewTemplate(StrEnum)` definiert 7 Review-Template-Typen (consolidated, bugfix, spec-compliance, implementation, test-sparring, synthesis, mediation-round). `REVIEW_TEMPLATE_REGISTRY` mappt jeden Typ auf Metadaten (Dateiname, Beschreibung, Story-Typ-Zuordnung). Implementiert in `agentkit/orchestration/review.py`. Wird in `build_template_sentinel()` fuer die Template-Sentinel-Erzeugung verwendet.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Template-Metadaten, nicht programmatisch genutzt." Die Registry-Eintraege enthalten Beschreibungen und Zuordnungen, die nur fuer die Sentinel-Erzeugung und fuer Tests relevant sind, aber nicht in der eigentlichen Review-Logik ausgewertet werden.

#### Gegenposition
Die Konzept-Analyse (FK-24 SS24.5.3, SS24.5.4) stuft Template-Sentinels und Review-Templates als **essentiell** ein. Die Registry wird programmatisch genutzt -- `build_template_sentinel()` verwendet die Template-Namen, und der Review-Guard-Hook validiert gegen die bekannten Templates. 7 Templates sind in FK-24 spezifiziert und getestet. Ohne Registry muessten die Template-Namen als Magic Strings im Code verstreut werden.

Die Einstufung als "Ballast" ist hier duenn begruendet. Die Metadaten-Felder (Beschreibungen) sind tatsaechlich nicht laufzeitrelevant, aber die Template-Enumeration und die Sentinel-Logik sind aktive Code-Pfade.

#### Empfehlung
**Begruendet uebernehmen.** Die Template-Enum beibehalten. Die beschreibenden Metadaten in der Registry koennen auf das Minimum reduziert werden (z.B. nur `filename` und `applies_to` behalten, `description` entfernen). Die Sentinel-Logik ist essentiell fuer den Review-Guard-Mechanismus.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "ReviewTemplate/REVIEW_TEMPLATE_REGISTRY"

---

### Element 6: FinalBuildStep Dataclasses

#### Was ist es?
`FinalBuildStep` ist eine Dataclass in `agentkit/orchestration/final_build.py` mit Feldern wie `name`, `description`, `gate` (ob Fehlschlag die Pipeline stoppt), `command_hint`. `FINAL_BUILD_SEQUENCE` ist ein Tupel von drei `FinalBuildStep`-Instanzen: `full_build`, `full_test_suite`, `remote_push`.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Reine Policy-Doku, kein Laufzeiteffekt." Die Dataclasses beschreiben, was passieren soll, aber der eigentliche Build/Test/Push wird vom Worker selbst ausgefuehrt (per Prompt-Instruktion), nicht von AgentKit programmatisch.

#### Gegenposition
FK-24 SS24.6 spezifiziert den finalen Build als Pflichtanforderung. Die drei Schritte muessen in der richtigen Reihenfolge ausgefuehrt werden. Die Frage ist nur, ob AgentKit diese Schritte als Datenstruktur kodiert oder ob sie rein im Prompt stehen. Wenn v3 den Final Build als deterministischen Schritt implementiert (was architektonisch sinnvoll waere -- Build/Test/Push sind deterministische Operationen), dann waeren die Dataclasses der Ausgangspunkt fuer die Implementierung.

Wenn v3 aber -- wie v2 -- den Final Build an den Worker delegiert, dann sind die Dataclasses tatsaechlich nur Doku.

#### Empfehlung
**Erst nach MVP, dann aber als echte Implementierung.** Die Doku-Dataclasses weglassen, aber die Anforderung (3 Schritte vor Handover) im Prompt beibehalten. Wenn v3 deterministische Final-Build-Kontrolle einfuehrt, dann als echte Funktionalitaet, nicht als Doku-Artefakt.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "FinalBuildStep Dataclasses"

---

### Element 7: CrashScenario / CRASH_SCENARIO_CATALOG

#### Was ist es?
`CrashScenario` ist eine Dataclass in `agentkit/orchestration/recovery_scenarios.py` mit Feldern wie `scenario_id`, `trigger`, `detection`, `recovery_action`, `state_expectation`. `CRASH_SCENARIO_CATALOG` ist ein Dict von 4 Szenarien (F-20-035 bis F-20-038): Agent-Crash in Implementation, Phase-Runner-Crash in Verify, Closure-Crash nach Merge, Eskalation-Recovery.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Doku-Katalog, nicht programmatisch genutzt." Die Szenarien werden in `get_crash_scenario()` per ID abgerufen, aber diese Funktion wird in der produktiven Pipeline nicht aufgerufen -- sie dient nur als Referenz und fuer Tests.

#### Gegenposition
Die Konzept-Analyse (FK-20 SS20.7.1) spezifiziert Recovery als essentiell. Die 4 Szenarien sind reale Fehlerfaelle die behandelt werden muessen. Allerdings: in v2 werden die Szenarien nur beschrieben, nicht automatisch erkannt und behandelt. Die echte Recovery-Logik liegt in `abort_recovery.py` und im Phase Runner selbst (z.B. Closure-Substates). Der Katalog ist davon entkoppelt.

Das Risiko beim Weglassen: kein Wissensverlust, weil die Information in den Konzeptdokumenten steht. Es gibt keine Funktionalitaet die bricht.

#### Empfehlung
**Begruendet weglassen als eigenstaendiger Katalog.** Die Recovery-Logik (die tatsaechlich Crash-Handling macht) muss in v3 existieren. Der Doku-Katalog als frozen Dataclass ist redundant zu den Konzeptdokumenten. Wenn v3 automatische Crash-Erkennung implementiert, sollten die Szenarien als Entscheidungsregeln kodiert werden, nicht als passive Beschreibungen.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "CrashScenario/CRASH_SCENARIO_CATALOG"

---

### Element 8: NoSchedulerPolicy / ParallelStoriesPolicy / MergeConflictPolicy

#### Was ist es?
Drei frozen Dataclasses in `agentkit/orchestration/scheduling.py`:
- `NoSchedulerPolicy` -- dokumentiert, dass AgentKit keinen eigenen Scheduler hat (der Orchestrator-Agent steuert die Reihenfolge)
- `ParallelStoriesPolicy` -- dokumentiert, dass parallele Stories auf getrennten Worktrees erlaubt sind (max parallel = 3)
- `MergeConflictPolicy` -- dokumentiert die Merge-Conflict-Behandlung (loser mergt zuerst, Gewinner muss Conflict loesen)

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Reine Policy-Doku-Konstanten." Die drei Klassen haben keine Methoden und werden nirgendwo in Entscheidungslogik ausgewertet. Sie sind typisierte Dokumentation.

#### Gegenposition
Die beschriebenen Policies sind konzeptionell relevant (DK-02 beschreibt das Merge-Verhalten, die parallele Story-Ausfuehrung ist ein reales Szenario). Aber sie als frozen Dataclasses im Code zu haben, hat keinen Vorteil gegenueber Dokumentation in Konzeptdokumenten oder als Kommentar in der relevanten Logik. In v2 gibt es keine Stelle, die `NO_SCHEDULER_POLICY.rationale` liest und darauf reagiert.

#### Empfehlung
**Begruendet weglassen.** Die Policies gehoeren in die Konzeptdokumentation oder als Docstring/Kommentar an die Stelle, wo sie relevant werden (z.B. Worktree-Erstellung, Merge-Logik). Als eigenstaendige Datenstrukturen ohne Verhalten sind sie Code-Ballast.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "NoSchedulerPolicy/ParallelStoriesPolicy/MergeConflictPolicy"

---

### Element 9: WorkerContextItem / WORKER_CONTEXT_SPEC

#### Was ist es?
`WorkerContextItem` ist eine Dataclass in `agentkit/orchestration/worker.py` mit Feldern: `name`, `source`, `required`, `story_type_filter`, `description`. `WORKER_CONTEXT_SPEC` ist ein Tupel von 7 Items (story_description, acceptance_criteria, concept_artifact, guardrails, defect_list, story_type_and_size, are_must_cover). `context_items_for_story_type()` filtert nach Story-Typ.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Doku-Dataclass, context_items_for_story_type nur fuer Doku." Die Filterfunktion wird nicht in der Prompt-Komposition aufgerufen -- die Prompt-Komposition hat ihre eigene Logik, welche Kontextelemente eingebettet werden.

#### Gegenposition
Die Worker Context Spec ist in FK-24 SS24.2.2 als Pflichtanforderung spezifiziert. Sie definiert den Vertrag: welcher Kontext dem Worker uebergeben werden muss. In v2 ist dieser Vertrag nur als Doku-Artefakt implementiert, nicht als Runtime-Validierung. Aber: wenn v3 eine Prompt-Validierung einfuehrt (pruefen ob alle required Context Items im Prompt enthalten sind), waere genau diese Spec die Grundlage.

Das Risiko beim Weglassen: der Vertrag existiert dann nur noch in den Konzeptdokumenten. Ein Worker koennte ohne story_description gestartet werden, und nichts wuerde das erkennen.

#### Empfehlung
**Begruendet uebernehmen, aber als echte Validierung.** Die Context Spec sollte in v3 nicht nur existieren, sondern in `compose_worker_prompt()` aktiv validieren, dass alle required Items vorhanden sind. Als reine Doku-Dataclass waere sie tatsaechlich Ballast -- als Validierungsgrundlage ist sie wertvoll.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "WorkerContextItem/WORKER_CONTEXT_SPEC"

---

### Element 10: ReviewFlowModel / ReviewFlowStep

#### Was ist es?
`ReviewFlowStep` ist eine Dataclass in `agentkit/orchestration/review.py` die einen einzelnen Schritt im Review-Flow beschreibt (name, actor, description, hook). `REVIEW_FLOW_MODEL` ist ein Tupel von 5 Schritten die den Review-Ablauf dokumentieren: Worker erreicht Review-Punkt, Worker sendet an LLM Pool, LLM antwortet, Review Guard schreibt Event, Worker integriert Feedback.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Doku, nicht Runtime." Der 5-Schritt-Flow wird nicht programmatisch ausgefuehrt -- er beschreibt was der Worker (ein LLM-Agent) selbstaendig tut. AgentKit orchestriert den Flow nicht Schritt fuer Schritt.

#### Gegenposition
Der Review-Flow ist in FK-24 SS24.5 als essentiell spezifiziert. Aber die Spezifikation beschreibt ein Verhaltensmuster, das per Prompt vorgegeben wird -- nicht eine Zustandsmaschine die AgentKit steuert. Die Dataclasses fuegen keinen Wert hinzu, der ueber einen Kommentar oder Docstring hinausgeht.

#### Empfehlung
**Begruendet weglassen.** Der Review-Flow gehoert in den Prompt-Template und in die Konzeptdokumentation. Als frozen Dataclass im Code hat er keinen programmatischen Nutzen. Die relevante Runtime-Logik (Review-Frequenz, Template-Sentinel, Review-Guard-Hook) ist in anderen Strukturen kodiert.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "ReviewFlowModel/ReviewFlowStep"

---

### Element 11: WorkerArtifactDescriptor / WORKER_ARTIFACT_REGISTRY

#### Was ist es?
`WorkerArtifactDescriptor` ist eine Dataclass in `agentkit/orchestration/artifacts.py` mit Feldern: `kind` (Enum), `filename`, `format`, `checked_by`, `min_size`. `WORKER_ARTIFACT_REGISTRY` ist ein Tupel von 3 Descriptors (protocol.md, handover.json, worker-manifest.json). `get_artifact_descriptor()` loest ein Kind auf den Descriptor auf.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Registry nur fuer get_artifact_descriptor, besser als einfaches Dict." Die Kritik richtet sich nicht gegen die Funktionalitaet, sondern gegen die Abstraktion: eine Dataclass-Registry fuer 3 Eintraege ist Over-Engineering im Vergleich zu einem einfachen Dict oder direkten Konstanten.

#### Gegenposition
Die Manifest-Validierung (`validate_manifest_dict()`) nutzt die Registry-Informationen. Die Structural Checks in Verify Layer 1 pruefen Dateiexistenz und Mindestgroesse -- diese Werte kommen aus den Descriptors. Das ist kein reiner Doku-Code. Es gibt tatsaechlich Runtime-Pfade die von der Registry abhaengen.

Die Einstufung als "Ballast" ist hier **nicht korrekt**. Die Registry wird programmatisch genutzt. Der Vorschlag "besser als einfaches Dict" ist eine Vereinfachung der Datenstruktur, kein Entfernen von Funktionalitaet.

#### Empfehlung
**Begruendet uebernehmen, Datenstruktur vereinfachen.** Die Artefakt-Informationen (Dateiname, Mindestgroesse, Format, wer prueft) muessen in v3 existieren -- sie treiben die Structural Checks. Ob als Dataclass-Registry oder als Dict/Config ist eine Implementierungsfrage. Die Information selbst ist nicht optional.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "WorkerArtifactDescriptor/WORKER_ARTIFACT_REGISTRY"

---

### Element 12: Telemetry Contract (build_telemetry_contract / evaluate_telemetry_contract)

#### Was ist es?
In `agentkit/orchestration/telemetry_contract.py`: `build_telemetry_contract()` erzeugt einen erwarteten Event-Count basierend auf Story-Groesse und Increment-Anzahl. `evaluate_telemetry_contract()` vergleicht beobachtete Event-Counts gegen den Vertrag und meldet Abweichungen. `detect_worker_crash()` erkennt fehlende `agent_end`-Events.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Nur fuer Integrity Gate relevant; kann vereinfacht werden." Die Einstufung ist nicht "weglassen" sondern "vereinfachen" -- der Telemetrie-Vertrag ist eine relativ komplexe Abstraktion fuer eine begrenzte Pruefung.

#### Gegenposition
FK-24 SS24.10 spezifiziert die Telemetrie-Events als essentiell. Die Crash-Detection (`agent_start` ohne `agent_end`) ist eine wichtige Sicherheitsfunktion. Der Event-Count-Vertrag pro Story-Groesse ermoeglicht die Erkennung von incomplete Runs (fehlende Reviews, fehlende Drift-Checks).

In v2 wird der Telemetrie-Vertrag in Tests und im Integrity Gate tatsaechlich genutzt. `evaluate_telemetry_contract()` ist kein toter Code -- es gibt Integration-Tests die ihn aufrufen.

Das Risiko beim Weglassen: ohne Telemetrie-Vertrag kann ein Worker 0 Reviews durchfuehren und trotzdem als "completed" markiert werden, wenn die Manifest-Pruefung das nicht abfaengt.

#### Empfehlung
**Begruendet uebernehmen, aber vereinfacht.** Die Crash-Detection (agent_start/agent_end) ist essentiell. Der granulare Event-Count-Vertrag pro Story-Groesse kann vereinfacht werden (z.B. nur "mindestens 1 Review", "mindestens 1 Drift-Check" statt exakter Zaehler). Die 480 LOC in v2 koennen vermutlich auf 100-150 LOC reduziert werden.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "Telemetry Contract"

---

### Element 13: _recovered_from_context / _loaded_from_file / _guard_failure Flags

#### Was ist es?
Drei private Boolean-Flags auf der `PhaseState`-Dataclass in `agentkit/orchestration/phase_runner.py`:
- `_loaded_from_file`: True wenn der State aus phase-state.json geladen wurde (vs. frisch erzeugt)
- `_recovered_from_context`: True wenn der State aus dem Aufrufkontext rekonstruiert wurde (Context-Recovery bei fehlender Datei)
- `_guard_failure`: True wenn ein REF-040-Guard-Check fehlgeschlagen hat, um zu verhindern dass der fehlerhafte State die Hauptdatei ueberschreibt

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Interne Workarounds fuer state-recovery Bugs." Die Implikation: diese Flags existieren nur, weil der State-Management-Code in v2 Luecken hat, die mit Flags geflickt werden.

#### Gegenposition
Die Einstufung als "Workaround" verkennt den Zweck der Flags:

1. `_guard_failure` ist **kein Workaround** -- es ist ein Sicherheitsmechanismus. Wenn ein Guard fehlschlaegt (ungueltiger Phasenuebergang), darf der fehlerhafte State NICHT nach phase-state.json geschrieben werden. Ohne dieses Flag wuerde ein Guard-Failure den bestehenden State korrumpieren. Es gibt dedizierte Tests dafuer (`test_guard_failure_state_protection.py`).

2. `_loaded_from_file` wird in der Transition-Validierung verwendet: ein frisch erzeugter State (erster Setup-Aufruf) hat andere Regeln als ein geladener State.

3. `_recovered_from_context` ist am ehesten ein Workaround -- es behandelt den Fall dass phase-state.json fehlt aber genug Kontext vorhanden ist.

Die Einstufung als Ballast ist fuer `_guard_failure` **falsch**. Dieses Flag verhindert aktiv Datenverlust.

#### Empfehlung
**`_guard_failure`: Begruendet uebernehmen** (essentielle Sicherheitsfunktion, muss in v3 existieren, egal wie sie implementiert wird).
**`_loaded_from_file`: Begruendet uebernehmen** (noetig fuer korrekte Transition-Validierung).
**`_recovered_from_context`: Erst nach MVP evaluieren.** Wenn v3 robustes State-Management hat, sollte dieser Recovery-Pfad nicht noetig sein. Aber: ein explizites Recovery-Konzept muss trotzdem existieren (FK-20 SS20.7.1).

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "_recovered_from_context/_loaded_from_file/_guard_failure Flags"

---

### Element 14: Exploration-Summary Markdown Generation

#### Was ist es?
`_write_exploration_summary()` in `agentkit/orchestration/phase_runner.py` erzeugt eine menschenlesbare Markdown-Datei (`exploration-summary.md`) nach Abschluss der Exploration-Phase. Enthaelt: Zusammenfassung des Design-Reviews, Gate-Entscheidung, Concerns, Trigger.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Menschenlesbar, aber kein Pipeline-Effekt." Das Markdown wird generiert, aber von keiner nachfolgenden Phase gelesen oder ausgewertet.

#### Gegenposition
Das Exploration-Summary ist in FK-23 SS23.3.1 als Artefakt spezifiziert und in `agentkit/core/implementation_contract.py` als erwartete Datei aufgefuehrt (`"exploration-summary.md"`). Es dient der Traceability: ein Mensch (oder ein Review-Agent) kann nachvollziehen, warum die Exploration bestanden hat.

Ohne das Summary ist die Exploration eine Blackbox: es gibt `entwurfsartefakt.json` und `design-review.json`, aber keine aggregierte menschenlesbare Zusammenfassung.

#### Empfehlung
**Erst nach MVP.** Fuer den MVP ist die Exploration-Entscheidung in `phase-state.json` und den Review-Artefakten nachvollziehbar. Ein menschenlesbares Summary ist wertvolles Traceability-Feature, aber kein Pipeline-Blocker. Kann nach dem MVP mit geringem Aufwand ergaenzt werden.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "Exploration-Summary Markdown Generation"

---

### Element 15: Multi-Repo Worktree Logic

#### Was ist es?
Der Spawn-Vertrag in v2 enthaelt neben `worktree_path` (einzelner Pfad) auch `worktree_paths` (Dict: repo-id -> Pfad) und `primary_repo_id`. Dies ermoeglicht Stories die sich ueber mehrere Repositories erstrecken. In `agentkit/cli.py` wird `primary_repo_id` aus `context.json` gelesen und in die Evidence-Assembly-Logik weitergegeben.

#### Warum als Ballast eingestuft?
Die Code-Analyse sagt: "Nur wenn v3 Multi-Repo unterstuetzen soll." Das ist eine korrekte Beobachtung -- Multi-Repo-Support ist eine Erweiterung die nur relevant ist, wenn AgentKit Projekte mit mehreren Repos orchestrieren soll.

#### Gegenposition
Das AgentKit-Repository selbst ist ein Single-Repo (`saltenhof/claude-agentkit`, per CLAUDE.md: "Single-Repo, kein Monorepo"). Multi-Repo ist in den Konzeptdokumenten als optionales Feature erwaehnt (FK-26 beschreibt den EvidenceAssembler mit Multi-Repo-Support), aber nicht als Kernfunktionalitaet.

#### Empfehlung
**Begruendet weglassen fuer MVP.** Alle Datenstrukturen koennen auf `worktree_path: str` vereinfacht werden. Die Erweiterung auf Multi-Repo kann spaeter ohne Breaking Change erfolgen (worktree_path -> worktree_paths Migration). Wichtig: die Vereinfachung muss durchgaengig sein (CLI, Spawn-Spec, Evidence Assembly).

#### Quellverweis
Code-Analyse, Abschnitt 5 "Wahrscheinlich Ballast / v2-Artefakte", Zeile "Multi-Repo Worktree Logic"

---

## Kategorie 2: "Vereinfachungspotential in v3" (aus Code-Analyse)

---

### Element 16: PhaseState Dataclass mit 40+ Feldern

#### Was ist es?
`PhaseState` in `agentkit/orchestration/phase_runner.py` ist eine Dataclass mit ueber 40 Feldern: Kern-Steuerungsfelder (phase, status, mode, story_type), QA-Zyklusfelder (qa_cycle_round, qa_cycle_id, qa_cycle_status, current_evidence_epoch), Exploration-Felder (exploration_gate_status, exploration_review_round), Closure-Substates, Spawn-Info, Recovery-Flags, ARE-Bundle, Suggested-Reaction, etc.

#### Warum als Vereinfachungspotential eingestuft?
Die Code-Analyse schlaegt vor: "Pydantic-Modell mit klarer Trennung Core/Extension." Die 40+ Felder sind schwer zu ueberblicken und vermischen Kernlogik mit Erweiterungen. In v2 ist PhaseState eine flache Dataclass ohne Gruppierung.

#### Gegenposition
Die Felder selbst sind fast alle essentiell (die Konzept-Analyse stuft die meisten als "Ja" ein). Das Problem ist nicht die Anzahl der Felder, sondern die fehlende Strukturierung. Ein Pydantic-Modell mit Untermodellen (z.B. `QACycleState`, `ExplorationState`, `ClosureState`) wuerde die gleichen Felder enthalten, aber besser organisiert.

ACHTUNG: Eine "Vereinfachung" die Felder weglässt, statt sie zu gruppieren, riskiert fehlende Zustandsinformation. Jedes Feld das entfernt wird, muss gegen die Konzeptanforderungen geprueft werden.

#### Empfehlung
**Begruendet uebernehmen als Pydantic-Modell mit Untergruppen.** Kein Feld weglassen ohne explizite Pruefung gegen FK-20/FK-24/FK-25. Die Vereinfachung liegt in der Struktur, nicht im Umfang.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Vereinfachungspotential in v3", Zeile "Dataclass PhaseState mit 40+ Feldern"

---

### Element 17: 11 Eskalations-Trigger reduzieren auf ~7

#### Was ist es?
`agentkit/orchestration/escalation.py` definiert 11 `EscalationTrigger`-Eintraege. Die Code-Analyse schlaegt vor, auf die "tatsaechlich ausgeloesten (~7)" zu reduzieren.

#### Warum als Vereinfachungspotential eingestuft?
Vermutlich wurden in v2 nicht alle 11 Trigger tatsaechlich in der Produktiv-Pipeline ausgeloest. Einige Trigger wie `GOVERNANCE_CRITICAL_INCIDENT` oder `GOVERNANCE_HARD_VIOLATION` sind fuer Szenarien definiert die moeglicherweise nie aufgetreten sind.

#### Gegenposition
Die Trigger sind in FK-20 und FK-25 spezifiziert. Dass ein Trigger "nie ausgeloest wurde" bedeutet nicht, dass er unnoetig ist -- es bedeutet dass der entsprechende Fehlerfall nie aufgetreten ist. Ein Eskalations-Trigger der erst bei einem realen Fehler fehlt, ist ein kritischer Luecke.

Welche der 11 Trigger sind "tatsaechlich ausgeloest"? Die Code-Analyse liefert keine Daten dazu. Ohne diese Evidenz ist die Empfehlung "auf 7 reduzieren" willkuerlich.

#### Empfehlung
**Nicht willkuerlich reduzieren.** Stattdessen: jeden Trigger gegen die Konzeptdokumente pruefen. Trigger die in FK-20/FK-25 spezifiziert sind, bleiben. Trigger die NICHT spezifiziert sind (sondern v2-Eigenentwicklung), koennen entfallen. Eine Reduktion auf Basis von "wurde noch nie getriggert" ist ein Risiko.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Vereinfachungspotential in v3", Zeile "11 Eskalations-Trigger als Katalog"

---

### Element 18: Policy-Doku als frozen Dataclasses -> YAML/Config oder Docstrings

#### Was ist es?
Ueberbegriff fuer mehrere Elemente (NoSchedulerPolicy, FinalBuildStep, CrashScenario etc.) die als frozen Dataclasses implementiert sind, aber keine Runtime-Logik enthalten.

#### Warum als Vereinfachungspotential eingestuft?
Frozen Dataclasses fuer reine Doku-Zwecke sind Over-Engineering. Die Information kann in YAML-Config-Dateien, Docstrings oder Konzeptdokumenten stehen.

#### Gegenposition
Keine substanzielle Gegenposition. Typisierte Dokumentation im Code hat den Vorteil, dass sie von Tests validiert werden kann (z.B. "der Katalog hat genau 4 Eintraege"). Aber dieser Vorteil ist marginal.

#### Empfehlung
**Begruendet weglassen.** Fuer die Elemente die keine Runtime-Logik haben (NoSchedulerPolicy, FinalBuildStep, CrashScenario, ReviewFlowModel), ist die Migration zu Docstrings oder Konzeptdokumenten die richtige Massnahme. Fuer Elemente die Runtime-Logik treiben (WorkerArtifactDescriptor, ReviewTemplate), gilt dies NICHT -- siehe Einzelbewertungen oben.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Vereinfachungspotential in v3", Zeile "Policy-Doku als frozen Dataclasses"

---

### Element 19: Evidence-Fingerprint ueber Dateigroessen -> Robuster Hash

#### Was ist es?
Die Deadlock-Detection in der Implementation-Phase vergleicht "Evidence-Fingerprints" ueber aufeinanderfolgende Zyklen. Wenn der Fingerprint identisch ist, steckt die Pipeline fest (Worker produziert keine neuen Ergebnisse). In v2 basiert der Fingerprint auf Dateigroessen.

#### Warum als Vereinfachungspotential eingestuft?
Dateigroessen-basierte Fingerprints sind fragil: eine Datei kann sich inhaltlich aendern ohne ihre Groesse zu aendern. Ein SHA256-Hash waere robuster.

#### Gegenposition
Keine substanzielle Gegenposition. SHA256-Hashing ist eine triviale und robustere Alternative. Das Vereinfachungspotential ist hier korrekt identifiziert, wobei "Vereinfachung" im Sinne von "Verbesserung" zu lesen ist.

#### Empfehlung
**Begruendet verbessern.** In v3 sollte der Evidence-Fingerprint auf Datei-Hashes basieren, nicht auf Dateigroessen. Der Aufwand ist minimal, der Gewinn an Zuverlaessigkeit signifikant.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Vereinfachungspotential in v3", Zeile "Evidence-Fingerprint ueber Dateigroessen"

---

### Element 20: Yield/Resume via phase-state.json + pause_reason -> Expliziteres State-Machine Pattern

#### Was ist es?
In v2 wird der PAUSED-Mechanismus ueber Felder in PhaseState gesteuert: `status=PAUSED`, `pause_reason="awaiting_design_review"`, `paused_retry_count`, `last_paused_evidence_fingerprint`. Der Phase Runner interpretiert die pause_reason bei jedem Resume-Aufruf und entscheidet, welcher Zustand wiederhergestellt wird.

#### Warum als Vereinfachungspotential eingestuft?
Die Code-Analyse schlaegt ein "expliziteres State-Machine Pattern" vor. Der PAUSED-Mechanismus in v2 ist implizit: die pause_reason ist ein String der in if/elif-Ketten interpretiert wird, statt als typisierter Zustand in einer formalen State Machine.

#### Gegenposition
Der Yield/Resume-Mechanismus ist in FK-20 SS20.6.2 und FK-23 SS23.3.1 detailliert spezifiziert. Die Funktionalitaet ist essentiell. Die Frage ist nur die Implementierungsqualitaet. Ein explizites State-Machine Pattern (z.B. mit typed States und Transitions) waere robuster und leichter testbar.

#### Empfehlung
**Begruendet verbessern, nicht weglassen.** Die Yield/Resume-Funktionalitaet muss in v3 existieren. Die Implementierung als explizite State Machine (z.B. mit `PausedState`-Untertypen statt String-basierter pause_reason) ist eine architektonische Verbesserung.

#### Quellverweis
Code-Analyse, Abschnitt 5 "Vereinfachungspotential in v3", Zeile "Yield/Resume via phase-state.json + pause_reason"

---

## Kategorie 3: "Optional / Nice-to-have (aber spezifiziert)" (aus Konzept-Analyse)

---

### Element 21: ARE-Integration (must_cover, Evidence, ARE-Gate)

#### Was ist es?
Die Agent Requirements Engine (ARE) ist ein externes System das Requirements-Vollstaendigkeit prueft. AgentKit integriert: `are_must_cover` im Worker-Kontext, ARE-Evidence-Pruefung im Structural Check (Verify Layer 1), ARE-Gate als Closure-Blocker.

#### Warum als Optional eingestuft?
Die Konzept-Analyse sagt: "Optional / Nice-to-have (aber spezifiziert) -- via Feature-Flag." ARE ist explizit als optionale Komponente konzipiert (DK-00 nennt ARE als "optional"). Die Pipeline funktioniert ohne ARE -- der ARE-Gate wird uebersprungen wenn ARE nicht konfiguriert ist.

#### Gegenposition
Die Konzeptdokumente spezifizieren ARE als Pflichtanforderung fuer produktiven Betrieb, aber als optionale Komponente fuer die initiale Inbetriebnahme. Das ist ein feiner Unterschied: "optional bei Installation" ist nicht "optional im Zielbild". CLAUDE.md sagt: "ohne ARE-Bestaetigung kein Merge" -- das ist ein Pflichtgate.

#### Empfehlung
**Erst nach MVP, aber eingeplant.** Die Feature-Flag-Architektur muss von Anfang an vorhanden sein (ARE-Integration als toggelbar). Die eigentliche Implementierung kann nach dem MVP erfolgen. Die Schnittstelle (Feature-Flag-Check an den relevanten Stellen) sollte aber von Tag 1 existieren.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 1

---

### Element 22: VektorDB-Abgleich

#### Was ist es?
Semantische Suche ueber abgeschlossene Stories, Duplikat-Erkennung vor Story-Erstellung. Verwendet eine Vektordatenbank (Weaviate) fuer Embedding-basierte Aehnlichkeitssuche.

#### Warum als Optional eingestuft?
Die Konzept-Analyse sagt: "via Feature-Flag." VektorDB ist explizit als optionale Integration konzipiert. Die Pipeline funktioniert ohne VektorDB -- es findet dann keine Duplikat-Erkennung statt.

#### Gegenposition
Ohne VektorDB koennen doppelte Stories angelegt werden, die die gleiche Arbeit redundant ausfuehren. Das ist ein Effizienzproblem, aber kein Korrektheitsproblem.

#### Empfehlung
**Erst nach MVP.** VektorDB ist eine Optimierung, keine Kernfunktionalitaet. Die Pipeline funktioniert korrekt ohne Duplikat-Erkennung.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 2

---

### Element 23: LLM-Assessment-Sidecar im Worker-Health-Monitor

#### Was ist es?
Im Worker-Health-Monitor (FK-24 SS24.12) gibt es neben dem deterministischen Scoring-Modell einen optionalen LLM-Assessment-Sidecar. Dieser fuehrt eine unabhaengige LLM-basierte Bewertung des Worker-Zustands durch und liefert einen Korrekturfaktor von -10 bis +10 auf den deterministischen Score.

#### Warum als Optional eingestuft?
Die Konzept-Analyse (FK-24 SS24.12) stuft den LLM-Sidecar explizit als "Optional" ein. Der deterministische Score allein reicht fuer die Eskalationsentscheidung.

#### Gegenposition
Der LLM-Sidecar kann subtile Probleme erkennen die der deterministische Score nicht erfasst (z.B. Worker produziert Output der formal korrekt aber inhaltlich sinnlos ist). Ohne LLM-Assessment koennte ein Worker der in einer Endlosschleife sinnlosen Code produziert, unter dem deterministischen Radar durchrutschen.

#### Empfehlung
**Erst nach MVP.** Der deterministische Score mit Eskalationsleiter ist die Kernfunktionalitaet. Der LLM-Sidecar ist eine Verfeinerung die den Score praeziser macht, aber kein Pipeline-Blocker.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 3; Konzept-Analyse Abschnitt 1.11 ("Optional" in Tabelle)

---

### Element 24: Preflight-Turn im Review-Flow (Request-DSL, RequestResolver)

#### Was ist es?
Vor dem eigentlichen LLM-Review kann ein optionaler Preflight-Turn stattfinden: der Review-Agent sendet bis zu 8 strukturierte Requests (z.B. `NEED_FILE`, `NEED_SCHEMA`, `NEED_CALLSITE`), die ein deterministischer `RequestResolver` aufloest. Damit erhaelt der Reviewer genau den Kontext den er braucht, statt einen generischen Bundle.

#### Warum als Optional eingestuft?
Die Konzept-Analyse (FK-24 SS24.5b, DK-04 SS4.5.3.3) markiert den Preflight-Turn als "Optional (aber spezifiziert)." Er verbessert die Review-Qualitaet, ist aber nicht zwingend -- ohne Preflight erhaelt der Reviewer den Standard-Evidence-Bundle.

#### Gegenposition
Der Preflight-Turn adressiert ein reales Problem: LLM-Reviewer die irrelevanten Kontext bekommen, liefern schlechtere Reviews. Die Request-DSL ist in FK-24 und DK-04 detailliert spezifiziert (7 Request-Typen). Das ist kein nachtraeglicher Einfall, sondern ein durchdachtes Feature.

Das Risiko beim Weglassen: schlechtere Review-Qualitaet, mehr False Positives/Negatives im QA-Prozess. Das betrifft die Effektivitaet der 4-Layer-QA direkt.

#### Empfehlung
**Erst nach MVP, aber hohe Prioritaet fuer Post-MVP.** Der Preflight-Turn ist die groesste Hebelwirkung fuer Review-Qualitaet. Fuer den MVP reicht der statische Evidence-Bundle (via Evidence Assembly). Aber sobald die Pipeline laeuft, sollte der Preflight-Turn die naechste Erweiterung sein.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 4

---

### Element 25: LLM-Pool-basierte Reviews (ChatGPT, Gemini, Grok)

#### Was ist es?
Reviews durch konfigurierte LLMs: ChatGPT, Gemini, Grok ueber MCP Session Pools. Der Worker sendet Review-Anfragen an den Pool, erhaelt Antworten, und der Review-Guard validiert die Template-Sentinels.

#### Warum als Optional eingestuft?
Die Konzept-Analyse sagt: "via Feature-Flag." Die LLM-Pool-Integration haengt davon ab, ob die MCP-Session-Pool-Server laufen. Ohne sie kann kein Multi-LLM-Review stattfinden.

#### Gegenposition
**ACHTUNG: Diese Einstufung ist problematisch.** FK-24 SS24.5.1 stuft "Pflicht-Reviews durch konfigurierte LLMs" als **essentiell** ein. Die Konzept-Analyse selbst stuft die Review-Pflicht als "Ja" (essentiell) ein (Abschnitt 1.6). Reviews sind ein Kernbestandteil der 4-Layer-QA.

Die Frage ist nicht ob Reviews stattfinden (sie muessen), sondern ob sie ueber LLM-Pools oder ueber Claude-Sub-Agents laufen. Wenn Claude (der Worker selbst) die Reviews durchfuehrt, ist das kein Multi-Perspektiven-Review -- es ist Selbst-Review.

#### Empfehlung
**Review-Mechanismus ist essentiell, Pool-basierte Ausfuehrung ist optional.** V3 muss einen Review-Mechanismus haben. Fuer den MVP kann der Review durch einen separaten Claude-Sub-Agent laufen (statt ueber LLM-Pools). Die LLM-Pool-Integration (ChatGPT, Gemini, Grok) ist die bevorzugte Implementierung, aber ein Sub-Agent-basierter Fallback reicht fuer den MVP.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 5

---

### Element 26: Quorum bei Reviewer-Divergenz (Tiebreaker durch dritten Reviewer)

#### Was ist es?
Wenn zwei LLM-Reviewer divergierende Ergebnisse liefern (einer sagt PASS, einer sagt FAIL), wird ein dritter Reviewer als Tiebreaker eingesetzt. Das Quorum entscheidet dann per Mehrheit.

#### Warum als Optional eingestuft?
Die Konzept-Analyse stuft dies als Nice-to-have ein. Das Quorum setzt voraus, dass mindestens 3 LLM-Reviewer verfuegbar sind (Multi-LLM-Setup). Ohne Multi-LLM kein Divergenz-Problem, also kein Tiebreaker noetig.

#### Gegenposition
Das Quorum adressiert ein reales Problem: bei 2 Reviewern und Divergenz muss eine Entscheidung fallen. Ohne Quorum muesste man entweder konservativ (bei Divergenz = FAIL) oder liberal (bei Divergenz = PASS) entscheiden. Beides hat Nachteile.

#### Empfehlung
**Erst nach MVP.** Setzt Multi-LLM-Pool voraus. Fuer den MVP mit einem einzigen Reviewer gibt es keine Divergenz. Kann spaeter hinzugefuegt werden wenn Multi-LLM-Reviews implementiert sind.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 6

---

### Element 27: Context Sufficiency Builder (Pre-Step fuer Layer 2)

#### Was ist es?
Ein Pre-Step vor Layer 2 (Semantic Review) der prueft, ob genug Kontext fuer eine qualitativ hochwertige LLM-Bewertung vorhanden ist. Erzeugt `context_sufficiency.json`. Verhindert, dass ein LLM-Reviewer mit zu wenig Information eine schlechte Bewertung abgibt.

#### Warum als Optional eingestuft?
Die Konzept-Analyse stuft dies als Nice-to-have ein. Der Context Sufficiency Check ist ein Qualitaetsfilter, kein Pipeline-Gate. Ohne ihn laeuft der Review trotzdem -- er ist moeglicherweise weniger zuverlaessig.

#### Gegenposition
Ein Review ohne ausreichenden Kontext ist schlimmer als kein Review: er erzeugt False Confidence. Wenn der Reviewer nicht genug Kontext hat, kann seine Bewertung zufaellig richtig oder falsch sein -- das untegraebt das Vertrauen in die gesamte QA-Pipeline.

#### Empfehlung
**Erst nach MVP, aber wichtig.** Fuer den MVP sorgt der Evidence Assembler fuer einen Basis-Kontext. Der Context Sufficiency Check ist eine Verfeinerung die sicherstellt, dass der Kontext auch ausreicht. Kann nach dem MVP hinzugefuegt werden.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 7

---

### Element 28: Section-aware / Symbol-aware Bundle-Packing

#### Was ist es?
Eine Erweiterung des Evidence Assembly (FK-24 SS24.5a) die beim Zusammenstellen des Review-Bundles nicht nur ganze Dateien, sondern gezielt Sektionen (Klassen, Funktionen, Symbole) extrahiert. Reduziert die Bundle-Groesse und erhoert die Relevanz.

#### Warum als Optional eingestuft?
Die Konzept-Analyse stuft dies als Nice-to-have ein. Der Basis-Evidence-Assembler arbeitet auf Datei-Ebene. Section-/Symbol-aware Packing ist eine Optimierung fuer grosse Dateien.

#### Gegenposition
Bei grossen Dateien (>1000 LOC) ist der gesamte Dateiinhalt als Review-Kontext kontraproduktiv -- der Reviewer muss irrelevante Abschnitte ignorieren, was die Bewertungsqualitaet senkt und den Token-Verbrauch erhoeht.

#### Empfehlung
**Erst nach MVP.** Fuer den MVP reicht Datei-basiertes Packing. Die Optimierung auf Section-Ebene kann spaeter ergaenzt werden, wenn sich zeigt dass grosse Dateien ein Problem sind.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 8

---

### Element 29: Scope-Overlap-Check im Preflight (parallele Stories)

#### Was ist es?
Ein Check im Preflight der prueft, ob eine neue Story sich mit einer bereits laufenden Story ueberschneidet (gleiche Module, gleiche Dateien). Verhindert Merge-Konflikte durch parallele Arbeit am gleichen Code.

#### Warum als Optional eingestuft?
Die Konzept-Analyse stuft dies als Nice-to-have ein. Der Check setzt voraus, dass mehrere Stories parallel laufen (was der NoSchedulerPolicy entspricht). Fuer sequentielle Story-Abarbeitung ist er irrelevant.

#### Gegenposition
Wenn AgentKit jemals parallel arbeitet (was in den Konzepten vorgesehen ist -- `ParallelStoriesPolicy` erlaubt max 3), ist der Scope-Overlap-Check die Praevention gegen Merge-Konflikte. Ohne ihn werden Konflikte erst beim Merge erkannt, was den Merge-Loser zwingt, die Konflikte aufzuloesen -- potentiell komplex und fehleranfaellig.

#### Empfehlung
**Erst nach MVP.** Fuer den MVP laeuft eine Story nach der anderen. Der Overlap-Check wird relevant wenn parallele Story-Ausfuehrung implementiert wird.

#### Quellverweis
Konzept-Analyse, Zusammenfassung "Optional / Nice-to-have", Punkt 9

---

## Zusammenfassende Bewertungsmatrix

| # | Element | Quelle | Bewertung | Aktion |
|---|---|---|---|---|
| 1 | Dynamischer Import compose-prompt.py | Code | Ballast-Einstufung korrekt | Weglassen, als regulaeres Modul |
| 2 | SpawnReason Literal-Typ | Code | Ballast-Einstufung falsch | Uebernehmen, konsolidieren |
| 3 | NON_DETERMINISTIC_PHASE Konstanten | Code | Ballast-Einstufung korrekt | Weglassen, in Phase-Config kodieren |
| 4 | IncrementStep / INCREMENT_CYCLE | Code | Ballast-Einstufung fragwuerdig | Uebernehmen, Beschreibungen vereinfachen |
| 5 | ReviewTemplate / REVIEW_TEMPLATE_REGISTRY | Code | Ballast-Einstufung falsch | Uebernehmen, Metadaten reduzieren |
| 6 | FinalBuildStep Dataclasses | Code | Ballast-Einstufung korrekt | Weglassen (Doku-Artefakt) |
| 7 | CrashScenario / CRASH_SCENARIO_CATALOG | Code | Ballast-Einstufung korrekt | Weglassen (Doku-Artefakt) |
| 8 | Scheduling Policies (3 Klassen) | Code | Ballast-Einstufung korrekt | Weglassen (Doku-Artefakte) |
| 9 | WorkerContextItem / WORKER_CONTEXT_SPEC | Code | Ballast-Einstufung falsch | Uebernehmen als Validierungsgrundlage |
| 10 | ReviewFlowModel / ReviewFlowStep | Code | Ballast-Einstufung korrekt | Weglassen (Doku-Artefakt) |
| 11 | WorkerArtifactDescriptor / REGISTRY | Code | Ballast-Einstufung falsch | Uebernehmen, Datenstruktur vereinfachen |
| 12 | Telemetry Contract | Code | Ballast-Einstufung falsch | Uebernehmen, vereinfachen |
| 13 | _guard_failure / _loaded_from_file Flags | Code | Ballast-Einstufung falsch (2 von 3) | _guard_failure + _loaded_from_file uebernehmen |
| 14 | Exploration-Summary Markdown | Code | Ballast-Einstufung korrekt | Erst nach MVP |
| 15 | Multi-Repo Worktree Logic | Code | Ballast-Einstufung korrekt | Weglassen fuer MVP |
| 16 | PhaseState 40+ Felder | Code | Vereinfachung korrekt | Pydantic mit Untergruppen |
| 17 | 11 Eskalations-Trigger -> ~7 | Code | Vereinfachung fragwuerdig | Nicht willkuerlich reduzieren |
| 18 | Policy-Doku als Dataclasses | Code | Vereinfachung korrekt | Zu Docstrings/Config migrieren |
| 19 | Evidence-Fingerprint Dateigroessen | Code | Vereinfachung korrekt | SHA256-Hash verwenden |
| 20 | Yield/Resume String-basiert | Code | Vereinfachung korrekt | Typisierte State Machine |
| 21 | ARE-Integration | Konzept | Optional-Einstufung korrekt | Erst nach MVP, Feature-Flag von Tag 1 |
| 22 | VektorDB-Abgleich | Konzept | Optional-Einstufung korrekt | Erst nach MVP |
| 23 | LLM-Assessment-Sidecar | Konzept | Optional-Einstufung korrekt | Erst nach MVP |
| 24 | Preflight-Turn (Request-DSL) | Konzept | Optional-Einstufung korrekt | Erst nach MVP, hohe Prioritaet |
| 25 | LLM-Pool-basierte Reviews | Konzept | Optional-Einstufung problematisch | Review essentiell, Pool-Impl optional |
| 26 | Quorum / Tiebreaker | Konzept | Optional-Einstufung korrekt | Erst nach MVP |
| 27 | Context Sufficiency Builder | Konzept | Optional-Einstufung korrekt | Erst nach MVP |
| 28 | Section-aware Bundle-Packing | Konzept | Optional-Einstufung korrekt | Erst nach MVP |
| 29 | Scope-Overlap-Check | Konzept | Optional-Einstufung korrekt | Erst nach MVP |

---

## Kernbefund

Von 15 als "Ballast" eingestuften Elementen (Code-Analyse) sind **6 korrekt als Ballast identifiziert** (reine Doku-Artefakte ohne Runtime-Logik: Elemente 1, 3, 6, 7, 8, 10). **5 sind falsch eingestuft** und haben echte Runtime-Funktion oder sind Pflichtanforderungen aus den Konzeptdokumenten (Elemente 2, 5, 9, 11, 13-teilweise). Die restlichen 4 sind im Kern korrekt, aber die Empfehlung "weglassen" muss nuanciert werden zu "uebernehmen aber vereinfachen" (Elemente 4, 12, 14, 15).

Von 9 als "Optional / Nice-to-have" eingestuften Elementen (Konzept-Analyse) sind **8 korrekt als optional eingestuft** -- sie alle sind erst nach dem MVP relevant. **1 Element (LLM-Pool-Reviews) ist problematisch eingestuft**, weil die Review-Pflicht selbst essentiell ist und nur die spezifische Pool-basierte Implementierung optional.

Die Vereinfachungspotentiale (5 Elemente) aus der Code-Analyse sind ueberwiegend korrekt identifiziert. Einzige Ausnahme: die willkuerliche Reduktion der Eskalations-Trigger von 11 auf 7 ohne Evidenz.
