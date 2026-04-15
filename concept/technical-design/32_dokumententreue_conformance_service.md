---
concept_id: FK-32
title: Dokumententreue und Conformance-Service
module: conformance
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: conformance
defers_to:
  - target: FK-20
    scope: workflow-engine
    reason: Conformance checks are triggered at specific pipeline phases managed by the workflow engine
  - target: FK-33
    scope: stage-registry
    reason: Umsetzungstreue runs as a stage within the Verify pipeline's stage registry
  - target: FK-35
    scope: integrity-gate
    reason: Integrity-Gate verifies that doc-fidelity events exist in telemetry at closure
supersedes: []
superseded_by:
tags: [conformance, document-fidelity, llm-evaluation, strategy-compliance, drift-detection]
---

# 32 — Dokumententreue und Conformance-Service

## 32.1 Zweck

Dokumententreue stellt sicher, dass die Arbeit der Agents nicht
von bestehenden Architektur- und Strategieentscheidungen abweicht.
Es ist keine einzelne Prüfung, sondern eine gestufte Kette: Was
geprüft werden kann, hängt davon ab, welcher Gegenstand zu welchem
Zeitpunkt existiert (FK-06-035).

Anders als die Guards (Kap. 30/31) ist Dokumententreue **nicht
deterministisch**, sondern LLM-basiert. Sie erfordert einen
semantischen Abgleich, den kein Algorithmus leisten kann. Deshalb
läuft sie über den StructuredEvaluator (Kap. 11) — ein
deterministisches Python-Skript ruft ein LLM über den Browser-Pool
auf und validiert die Antwort.

**Architekturzuordnung:** Der `ConformanceService` ist im
Komponentenmodell eine eigenstaendige Top-Level-Komponente. Er ist
bewusst keiner einzelnen Phase untergeordnet, weil seine vier
Conformance-Ebenen von Story-Erstellung, Exploration, Verify und
Closure genutzt werden.

**Geltungsbereich:** Nur implementierende Story-Typen (Implementation,
Bugfix). Konzept- und Research-Stories erzeugen
Dokumente, keinen Code — für sie gelten andere, leichtgewichtige
Qualitätskriterien (Kap. 20.2.3). (FK-06-037/038)

## 32.2 Vier Ebenen

```mermaid
flowchart LR
    E1["Ebene 1:<br/>Zieltreue"] --> E2["Ebene 2:<br/>Entwurfstreue"]
    E2 --> E3["Ebene 3:<br/>Umsetzungstreue"]
    E3 --> E4["Ebene 4:<br/>Rückkopplungstreue"]

    E1 -.- T1["Story-Erstellung"]
    E2 -.- T2["Nach Exploration,<br/>vor Implementation"]
    E3 -.- T3["Verify-Phase<br/>(Schicht 2)"]
    E4 -.- T4["Closure-Phase<br/>(nach Merge)"]
```

| Ebene | Zeitpunkt | Was geprüft wird | Input | FK |
|-------|-----------|-----------------|-------|-----|
| 1. Zieltreue | Story-Erstellung | Passt die Absicht zur Strategie? Kollidiert das Vorhaben mit bestehenden Leitplanken? | Story-Beschreibung, Strategie-/Architekturdokumente | FK-06-056 |
| 2. Entwurfstreue | Nach Exploration, vor Implementation (nur Exploration Mode) | Ist der geplante Lösungsweg mit Architektur und Konzepten vereinbar? | Entwurfsartefakt, Referenzdokumente | FK-06-057 |
| 3. Umsetzungstreue | Nach Implementation, in Verify-Phase | Hat der Worker gebaut, was konzeptionell vorgesehen war? Gibt es undokumentierten Drift? | Code-Diff, Entwurf/Konzept, Handover, Referenzdokumente | FK-06-058 |
| 4. Rückkopplungstreue | Bei Closure (nach Merge) | Müssen bestehende Dokumente aktualisiert werden, damit künftige Prüfungen gegen eine korrekte Wahrheit laufen? | Finaler Change, bestehende Dokumentation | FK-06-059 |

## 32.3 Gemeinsames technisches Pattern

Alle vier Ebenen nutzen dasselbe technische Grundgerüst:

```python
def check_fidelity(
    level: str,                    # "goal" | "design" | "impl" | "feedback"
    evaluator: StructuredEvaluator,
    context: FidelityContext,
) -> FidelityResult:
    """
    1. Referenzdokumente identifizieren (32.4)
    2. Kontext-Bundle zusammenstellen (Kap. 11, arch_references)
    3. StructuredEvaluator aufrufen (1 Check pro Ebene)
    4. Ergebnis: PASS / PASS_WITH_CONCERNS / FAIL
    5. Telemetrie-Event schreiben
    """
    refs = identify_references(level, context)

    # 3-Tier Prompt-Größenkontrolle (§32.4b)
    data_size = len(context.subject.encode()) + len(refs.encode())
    merge_paths: list[str] | None = None

    if data_size >= HARD_LIMIT_BYTES:
        return FidelityResult(
            level=level, status="FAIL",
            reason=f"Payload ({data_size} bytes) exceeds hard limit ({HARD_LIMIT_BYTES})",
            description="LLM call blocked — payload too large for reliable evaluation.",
            references_used=refs,
        )

    if data_size >= FILE_UPLOAD_THRESHOLD_BYTES:
        merge_paths = _write_temp_files(context.subject, refs, context.story_id)
        # Inline-Kontext wird durch Pointer-Text ersetzt
        subject_inline = f"[Subject uploaded as file — {len(context.subject)} chars]"
        refs_inline = f"[References uploaded as file — {len(refs)} chars]"
    else:
        subject_inline = context.subject
        refs_inline = refs

    try:
        result = evaluator.evaluate(
            role="doc_fidelity",
            prompt_template=PROMPT_TEMPLATES[level],
            context={
                "subject": subject_inline,
                "references": refs_inline,
                "story_description": context.story,
            },
            expected_checks=[f"{level}_fidelity"],
            story_id=context.story_id,
            run_id=context.run_id,
            merge_paths=merge_paths,
        )
    finally:
        if merge_paths:
            for path in merge_paths:
                Path(path).unlink(missing_ok=True)

    return FidelityResult(
        level=level,
        status=result.checks[0].status,
        reason=result.checks[0].reason,
        description=result.checks[0].description,
        references_used=refs,
    )
```

### 32.3.1 Prompt-Templates

| Ebene | Prompt-Template | Kernfrage an das LLM |
|-------|----------------|---------------------|
| Zieltreue | `prompts/doc-fidelity-goal.md` | "Passt diese Story-Absicht zur Strategie? Kollidiert sie mit Leitplanken?" |
| Entwurfstreue | `prompts/doc-fidelity-design.md` | "Ist dieser Lösungsweg mit der bestehenden Architektur vereinbar?" |
| Umsetzungstreue | `prompts/doc-fidelity-impl.md` | "Hat der Worker gebaut, was konzeptionell vorgesehen war? Gibt es undokumentierten Drift?" |
| Rückkopplungstreue | `prompts/doc-fidelity-feedback.md` | "Müssen bestehende Dokumente aktualisiert werden?" |

### 32.3.2 Response-Schema

Alle vier Ebenen nutzen das CheckResult-Schema des
StructuredEvaluator (Kap. 11.4):

```json
{
  "check_id": "design_fidelity",
  "status": "FAIL",
  "reason": "Neuer Service widerspricht Microservice-Schnittgröße aus Architektur-Guideline",
  "description": "Der Entwurf führt einen monolithischen BrokerService ein, der Trading, MarketData und OrderManagement vereint. Die Architektur-Guideline definiert max. 3 Bounded Contexts pro Service."
}
```

## 32.4 Referenzdokument-Identifikation

### 32.4.1 Problem

Die Qualität der Dokumententreue-Prüfung hängt davon ab, welche
Referenzdokumente dem LLM als Kontext mitgegeben werden. Zu
wenige → Konflikte werden übersehen. Zu viele → Kontext-
Verschmutzung, LLM verliert den Fokus.

### 32.4.2 Zwei Quellen

| Quelle | Mechanismus | Stärke |
|--------|-----------|--------|
| **Explizit deklariert** | Worker oder Story-Ersteller benennt Referenzdokumente (im Entwurfsartefakt `konformitaetsaussage.referenzdokumente` oder in Issue-Feldern `Konzept-Referenzen`, `Guardrail-Referenzen`) | Gezielt, keine False Positives |
| **Automatisch ergänzt** | Manifest-Indexer (Kap. 01 P6) identifiziert Dokumente anhand von Story-Metadaten (Modul, Typ) und Dokumenten-Tags | Findet Dokumente, die der Ersteller übersehen hat |

### 32.4.3 Manifest-Indexer

Der Manifest-Indexer scannt die Projektdokumentation und baut
einen Index:

```json
{
  "documents": [
    {
      "path": "concepts/api-design-guidelines.md",
      "scope": "architecture",
      "modules": ["*"],
      "story_types": ["implementation", "bugfix"],
      "sections": [
        {"heading": "REST-Konventionen", "anchor": "rest-konventionen"},
        {"heading": "Versionierung", "anchor": "versionierung"}
      ]
    },
    {
      "path": "concepts/trading-architecture.md",
      "scope": "architecture",
      "modules": ["trading-engine", "broker-client"],
      "story_types": ["*"],
      "sections": [...]
    }
  ]
}
```

**Matching:** Für eine Story mit `module: trading-engine` und
`story_type: implementation` werden alle Dokumente geliefert, deren
`modules` den Wert `trading-engine` oder `*` enthalten UND deren
`story_types` den Wert `implementation` oder `*` enthalten.

### 32.4.4 Pflege des Index

Der Manifest-Index wird **nicht automatisch generiert**. Er wird
als Datei im Projekt gepflegt (z.B. `_guardrails/manifest-index.json`
oder über Tags in den Dokumenten selbst). Der Installer kann
einen initialen Index erzeugen, aber die Pflege obliegt dem
Menschen.

**Kein automatisches Scanning:** Der Index enthält bewusst
kuratierte Einträge. Nicht jedes Markdown im Projekt ist ein
Referenzdokument für die Dokumententreue. Der Mensch entscheidet,
welche Dokumente normativ sind.

## 32.4b Prompt-Größenkontrolle (3-Tier)

### 32.4b.1 Problem

Die Payload-Größe der Dokumententreue-Aufrufe variiert stark.
Zieltreue (Ebene 1) hat kompakte Eingaben (Story-Body + wenige
Referenzdokumente). Umsetzungstreue (Ebene 3) und Rückkopplungstreue
(Ebene 4) können sehr große Diffs enthalten — bei umfangreichen
Stories mehrere hundert Kilobyte.

Ein LLM-Aufruf mit übergroßem Inline-Kontext scheitert oder
produziert degradierte Ergebnisse. Gleichzeitig darf relevanter
Kontext nicht verloren gehen — Trunkierung ist keine akzeptable
Strategie, weil sie semantisch relevante Teile abschneiden kann.

### 32.4b.2 Drei Stufen

Die Conformance-Service-Funktion `check_fidelity()` entscheidet
anhand der Gesamtgröße von Subject + Referenzdokumenten, welcher
Übertragungsweg gewählt wird:

| Stufe | Bedingung | Verhalten |
|-------|-----------|-----------|
| **Tier 1 — Inline** | `data_size < FILE_UPLOAD_THRESHOLD` | Subject und Referenzen werden als Inline-Text im Prompt-Kontext an den Evaluator übergeben. Normaler Weg. |
| **Tier 2 — Datei-Upload** | `FILE_UPLOAD_THRESHOLD ≤ data_size < HARD_LIMIT` | Subject und Referenzen werden in temporäre Dateien geschrieben und per `merge_paths` (Kap. 11, Hub-Mechanismus) als zusammengefasster Upload an das LLM gesendet. Der Inline-Kontext enthält nur einen kurzen Pointer-Text. |
| **Tier 3 — Blockade** | `data_size ≥ HARD_LIMIT` | Der LLM-Aufruf wird **nicht durchgeführt**. `check_fidelity()` liefert sofort `FAIL` mit einer Beschreibung, die erklärt, dass die Payload die maximale Verarbeitungsgrenze überschreitet. |

### 32.4b.3 Schwellwerte

| Konstante | Wert | Begründung |
|-----------|------|------------|
| `FILE_UPLOAD_THRESHOLD_BYTES` | 50 KB | Inline-Kontext bleibt unter typischen Prompt-Größen für zuverlässige LLM-Verarbeitung |
| `HARD_LIMIT_BYTES` | 500 KB | Auch per Datei-Upload nicht sinnvoll verarbeitbar — LLM-Qualität degradiert bei dieser Größe |

Konfigurierbar in `pipeline.yaml` unter `conformance.file_upload_threshold`
und `conformance.hard_limit`.

### 32.4b.4 Temporäre Dateien

Bei Tier 2 erzeugt `check_fidelity()` temporäre Dateien:

- Erstellt mit `NamedTemporaryFile(delete=False)`, Prefix
  `fidelity-subject-{story_id}-` bzw. `fidelity-refs-{story_id}-`
- An den Evaluator als `merge_paths=[subject_path, refs_path]`
  übergeben
- **Cleanup im `finally`-Block** — garantierte Löschung auch bei
  Evaluator-Fehlern
- `merge_paths` wird nur beim ersten Send übergeben, nicht beim
  Retry — das LLM hat die Dateiinhalte bereits

### 32.4b.5 Designentscheidung: Kein Trunkieren

Trunkierung (`content[:32000]`) ist für die Dokumententreue-Prüfung
**nicht zulässig**. Begründung: Wenn ein Referenzdokument abgeschnitten
wird, kann das LLM Konflikte in den abgeschnittenen Teilen nicht
erkennen. Das Prüfergebnis wäre falsch-positiv (PASS trotz Konflikt).

Die korrekte Strategie bei zu großen Payloads ist Tier 2 (Upload)
oder Tier 3 (Blockade mit klarer Fehlermeldung), nie stilles
Abschneiden.

**Abgrenzung zum Verify-Layer-2-Bundle (Kap. 27.5b):** Das
Context-Bundle der Layer-2-Evaluatoren (Umsetzungstreue, Adversarial)
nutzt ein separates Packing-Verfahren mit `BUNDLE_TOKEN_LIMIT`
(Kap. 27.5b.2). Dieses ist symbol-aware und verlustbehaftet — dort
ist kontrollierte Kompression akzeptabel, weil der Layer-2-Evaluator
eine andere Prüffrage stellt (Code-Qualität, nicht Dokumententreue).
Für die Dokumententreue-Spezifische Prüfung gilt die 3-Tier-Regel
dieses Abschnitts.

## 32.5 Ebene 1: Zieltreue

### 32.5.1 Trigger

Aufgerufen vom Story-Erstellungs-Skill (Kap. 21.5), nach dem
VektorDB-Abgleich.

### 32.5.2 Input

| Input | Quelle |
|-------|--------|
| Story-Beschreibung | Issue-Body (Problemstellung, Lösungsansatz, ACs) |
| Strategie-Dokumente | Manifest-Index gefiltert auf `scope: strategy` |
| Architektur-Dokumente | Manifest-Index gefiltert auf `scope: architecture` |

### 32.5.3 Bei FAIL

Story-Definition muss überarbeitet werden. Zurück zur Konzeption
(Kap. 21.2). Kein automatischer Retry — der Agent muss die Story
inhaltlich anpassen.

## 32.6 Ebene 2: Entwurfstreue

### 32.6.1 Trigger

Aufgerufen vom Phase Runner innerhalb der Exploration-Phase,
nachdem der Worker den Draft-Entwurf geschrieben und strukturell
validiert hat, aber bevor der Entwurf eingefroren wird (Kap. 23.3,
Kap. 25.4). Nur im Exploration Mode.

### 32.6.2 Input

| Input | Quelle |
|-------|--------|
| Draft-Entwurfsartefakt | Arbeitsstand des Exploration-Workers vor Freeze |
| Vom Worker deklarierte Referenzdokumente | `konformitaetsaussage.referenzdokumente` aus dem Entwurf |
| Vom System ergänzte Referenzdokumente | Manifest-Index gefiltert auf betroffene Module und Story-Typ |
| Story-Beschreibung | `context.json` |

### 32.6.3 Zweite, unabhängige Prüfung

Der Worker hat bereits selbst eine Konformitätsprüfung durchgeführt
(Schritt 5 der Exploration, Kap. 23.3.2). Die Entwurfstreue-Prüfung
ist die **zweite, unabhängige** Prüfung durch ein anderes LLM
(FK-05-087). Das stellt sicher, dass der Worker sich nicht selbst
ein PASS ausstellt.

### 32.6.4 Bei FAIL

Eskalation an Mensch. Pipeline stoppt mit `status: ESCALATED`.
Der Mensch muss den Konflikt mit der Architektur klären — z.B.
den Entwurf anpassen, die Architektur-Leitplanken lockern, oder
die Story verwerfen.

### 32.6.5 Gate für freigabepflichtige Entscheidungen

Ein nicht-leerer Block `offene_punkte.freigabe_noetig` führt nicht
zu einer sofortigen menschlichen Pause nach Stufe 1. Diese Punkte
gehen zunächst in Design-Review, Prämissen-Challenge,
Design-Challenge und H2-Nachklassifikation ein. Erst das Ergebnis
der Nachklassifikation entscheidet:

- Klasse 2: KI löst den Punkt im Feindesign-Subprozess selbst auf.
- Klasse 1/3/4: Pipeline pausiert für menschliche Klärung.

## 32.7 Ebene 3: Umsetzungstreue

### 32.7.1 Trigger

Läuft als Teil der Verify-Phase (Schicht 2), parallel zu
QA-Bewertung und Semantic Review (Kap. 27.4).

### 32.7.2 Input

| Input | Quelle |
|-------|--------|
| Code-Diff | `git diff` gegen Base-Ref |
| Entwurfsartefakt oder Konzeptquellen | `entwurfsartefakt.json` (Exploration Mode) oder Konzeptdokumente aus `concept_paths` (Execution Mode) |
| Handover-Paket | `handover.json` (insbesondere `drift_log`) |
| Referenzdokumente | Manifest-Index gefiltert |

### 32.7.3 Was geprüft wird

- Hat der Worker gebaut, was konzeptionell vorgesehen war?
- Gibt es undokumentierten Drift (Änderungen, die weder im
  Entwurf stehen noch im `drift_log` begründet sind)?
- Wurden neue Strukturen eingeführt, die nicht deklariert waren?

### 32.7.4 Bei FAIL

Story geht in den Feedback-Loop (Mängelliste an Remediation-
Worker). Bei signifikantem Drift oder Impact-Verletzung gibt es
keinen automatischen Rücksprung in die Exploration-Phase; der Fall
wird an den Menschen eskaliert.

### 32.7.5 Unterschied zu Impact-Violation-Check

| Prüfung | Methode | Was |
|---------|--------|-----|
| Impact-Violation (Kap. 23.8) | Deterministisch (Structural Check, Schicht 1) | Überschreitet der tatsächliche Änderungsumfang den deklarierten Impact? (quantitativ) |
| Umsetzungstreue (diese Ebene) | LLM-basiert (Schicht 2) | Hat der Worker gebaut, was konzeptionell vorgesehen war? (semantisch) |

Beide prüfen Abweichungen, aber auf verschiedenen Ebenen:
Impact-Violation ist quantitativ (wie viele Module, neue APIs),
Umsetzungstreue ist semantisch (passt die Lösung zum Konzept).

## 32.8 Ebene 4: Rückkopplungstreue

### 32.8.1 Trigger

Aufgerufen in der Closure-Phase, nach dem Merge, vor den
Postflight-Gates (Kap. 27.12).

### 32.8.2 Input

| Input | Quelle |
|-------|--------|
| Finaler Change | `git diff` auf Main (nach Merge) |
| Bestehende Dokumentation | Manifest-Index (alle normativen Dokumente) |

### 32.8.3 Was geprüft wird

Müssen bestehende Dokumente aktualisiert werden, damit künftige
Dokumententreue-Prüfungen gegen eine korrekte Wahrheit laufen?
(FK-06-063)

Beispiele:
- Story hat eine neue API eingeführt → API-Design-Guidelines
  müssen um diese API erweitert werden
- Story hat ein Architekturmuster geändert → Architektur-
  Dokumentation ist veraltet
- Story hat eine Konfiguration geändert → Betriebsdokumentation
  muss aktualisiert werden

### 32.8.4 Bei FAIL

**Keine Blockade.** Die Story ist bereits gemergt. Ein FAIL
erzeugt:

1. Eine **Warnung** an den Menschen, welche Dokumente
   aktualisiert werden sollten
2. Einen **Incident im Failure Corpus** (Kap. 41) — automatisch
   erfasst über die Pipeline-Erfassung (FK-10-011). Kategorie:
   `requirements_miss`, Tag: `doc_staleness`. Das Incident wird
   als `INSERT INTO events` in die Telemetrie-DB geschrieben
   und vom Failure-Corpus-Erfassungsmechanismus aufgegriffen.
3. Optional: automatische Erzeugung einer Follow-up-Story
   (Typ: Concept) für die Dokumentations-Aktualisierung

## 32.9 Konzept-Überschreibungsschutz

### 32.9.1 Regel (FK-06-069)

Wenn ein Worker im Execution Mode von einem mitgelieferten Konzept
abweichen will oder muss, muss er:

1. Die Abweichung explizit markieren (im Handover `drift_log`)
2. Eine Begründung liefern
3. Eine erneute Dokumententreue-Prüfung auslösen

### 32.9.2 Erkennung (FK-06-070)

Stillschweigendes Überschreiben eines freigegebenen Konzepts wird
durch die Umsetzungstreue (Ebene 3) erkannt. Das LLM vergleicht
den Code-Diff mit dem Konzept und identifiziert undokumentierten
Drift.

### 32.9.3 Zusätzliche Hook-basierte Erkennung

Die Drift-Erkennung per `increment_commit`-Hook (Kap. 26.3.5)
fängt signifikanten Drift bereits während der Implementation
ab — bevor er in der Verify-Phase erkannt wird. Damit wird
das Problem früher sichtbar und der Worker kann korrigieren,
bevor er das gesamte Handover fertigstellt.

## 32.10 Telemetrie

Jede Dokumententreue-Prüfung erzeugt ein `llm_call`-Event in
der SQLite-DB mit `role: doc_fidelity`:

```sql
INSERT INTO events (story_id, run_id, ts, event_type, pool, role, payload)
VALUES (?, ?, datetime('now'), 'llm_call', 'gemini', 'doc_fidelity',
        '{"level": "design", "status": "PASS"}');
```

Das Integrity-Gate prüft bei Closure, dass für jede relevante
Ebene ein `llm_call` mit `role: doc_fidelity` in der Telemetrie
vorliegt:

| Story-Modus | Erwartete Ebenen |
|------------|-----------------|
| Exploration Mode | Ebene 2 (Entwurfstreue) + Ebene 3 (Umsetzungstreue) + Ebene 4 (Rückkopplungstreue) |
| Execution Mode | Ebene 3 (Umsetzungstreue) + Ebene 4 (Rückkopplungstreue) |
| Story-Erstellung | Ebene 1 (Zieltreue) — wird nicht vom Integrity-Gate geprüft (kein Closure) |

## 32.11 Konfiguration

| Parameter | Config-Pfad | Default |
|-----------|-------------|---------|
| LLM-Rolle für Dokumententreue | `llm_roles.doc_fidelity` | `gemini` |
| Manifest-Index-Pfad | `guardrails_dir` + `manifest-index.json` | `_guardrails/manifest-index.json` |
| Guardrail-Dokumente-Pattern | `guardrails_pattern` | `*.md` |

---

*FK-Referenzen: FK-06-035 bis FK-06-070 (Dokumententreue komplett),
FK-05-083 bis FK-05-089 (Exploration: Selbst-Konformität + Freeze +
unabhängige Prüfung),
FK-05-100 bis FK-05-103 (Drift-Prüfung und erneute Dokumententreue)*
