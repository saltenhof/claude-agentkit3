# failure-corpus — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `failure-corpus` |
| Display-Name | `Failure-Corpus` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-07`, `FK-41` |
| Codebase-Hauptpfade | `src/agentkit/failure_corpus/` |

## 1. Executive Summary

Der Bounded Context failure-corpus ist konzeptionell vollstaendig spezifiziert (DK-07, FK-41, BC-Cut BC 13) und der BC-Schnitt mit drei Sub-Komponenten (IncidentTriage, PatternPromotion, CheckFactory) sowie ~27 Klassen ist fixiert. In der Codebase existiert jedoch ausschliesslich ein leerer `__init__.py`-Stub — keine einzige Klasse, kein Schema, kein Test, keine Sub-Komponente ist implementiert. Der BC ist damit vollstaendig im Zustand "nicht umgesetzt". Zuzueglich bestehen sieben konzeptinterne Refactor-Offenposten (bc-cut-decisions.md #52–#58), die das Konzept selbst noch nachziehen muss, bevor stabile Implementierung beginnen kann.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 12 |
| B — Teilweise umgesetzt | 0 |
| C — Drift / Fehler | 1 |

## 2. Konzept-Soll (Kurzfassung)

- **Top-Komponente `FailureCorpus` mit 6 Top-Surface-Methoden** — `bc-cut-decisions.md §BC13`; `FK-41 §41.1`
- **`IncidentTriage`-Sub: Aufnahme, Normalisierung, Ingress-Kriterien, Persistierung in `fc_incidents` via `Telemetry.write_projection`** — `FK-41 §41.3.1`, `FK-41 §41.4`
- **`PatternPromotion`-Sub: Clustering, Promotion-Regeln (Wiederholung/HoheSchwere/Checkbarkeit), menschliche Bestaetigung als Pflicht** — `FK-41 §41.5`
- **`CheckFactory`-Sub: 6-Schritt-Check-Ableitung (Schaerfen via LlmEvaluator, Check-Typ-Mapping deterministisch, Proposal-Generierung via LlmEvaluator, menschliche Freigabe, Story-Erzeugung, Wirksamkeitspruefung)** — `FK-41 §41.6`
- **`FailureCategory`-Enum mit exakt 12 Werten** — `FK-41 §41.4.1`; `bc-cut-decisions.md §BC13`
- **`PromotionStatus`-Enum fuer alle drei Artefakt-Ebenen (Incident/Pattern/Check)** — `FK-41 §glossary`; `bc-cut-decisions.md §BC13`
- **Drei Postgres-Tabellen `fc_incidents`, `fc_patterns`, `fc_check_proposals` als kanonische Wahrheit** — `FK-41 §41.3`
- **JSONL-Dateien unter `.agentkit/failure-corpus/` nur als Legacy-Export, nicht operative Wahrheit** — `FK-41 §41.3.4`; `bc-cut-decisions.md §BC13 Punkt 6`
- **Auto-Deaktivierung von Checks (90 Tage ohne Fund UND >3 False Positives), kritische Checks ausgenommen** — `FK-41 §41.6.7`; `DK-07 §7.6 Schritt 6`
- **Keine LLM-Judging-Checks: Checks sind ausschliesslich deterministisch** — `FK-41 §41.7`; `DK-07 §7.8.4`
- **CLI als Boundary-Control des aufrufenden BC; FailureCorpus selbst ist transport-agnostisch** — `FK-41 §41.9`; `bc-cut-decisions.md #58`
- **Wirksamkeitspruefung liest via `Telemetry.read_projection` aus `story_metrics` (Owner: story-closure)** — `FK-41 §41.6.7`; `bc-cut-decisions.md #57`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/failure_corpus/__init__.py` — leere Datei, kein Inhalt; das Paket existiert als Verzeichnis-Stub ohne jegliche Implementierung

Keine weiteren Python-Dateien vorhanden. Keine Tests unter `tests/unit/`, `tests/integration/` oder `tests/contract/` fuer diesen BC.

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Top-Komponente `FailureCorpus` inkl. aller 6 Top-Surface-Methoden (`record_incident`, `suggest_patterns`, `confirm_pattern`, `derive_check`, `approve_check`, `report_effectiveness`) | `bc-cut-decisions.md §BC13`; `FK-41 §41.1` | Kein Code vorhanden; kompletter Neubau erforderlich |
| A2 | Value-Types `IncidentId`, `PatternId`, `CheckId` (NewType), `FailureCategory`-StrEnum (12 Werte), `PromotionStatus`-StrEnum, `IncidentCandidate`-Pydantic-Modell | `bc-cut-decisions.md §BC13 Klassen-Skizzen`; `FK-41 §41.4.1` | Basis-Datenmodelle fehlen vollstaendig |
| A3 | Sub-Komponente `IncidentTriage`: Klassen `IncidentTriage`, `Incident`, `IncidentNormalizer`, `IngressCriteria`, `IncidentRepository`, `IncidentSeverity` | `bc-cut-decisions.md §BC13`; `FK-41 §41.4` | Kein Code vorhanden |
| A4 | Sub-Komponente `PatternPromotion`: Klassen `PatternPromotion`, `FailurePattern`, `PatternClusterer`, `PromotionRule`, `PatternConfirmation`, `PatternRepository`, `RiskLevel` | `bc-cut-decisions.md §BC13`; `FK-41 §41.5` | Kein Code vorhanden |
| A5 | Sub-Komponente `CheckFactory`: Klassen `GeneratedCheckProposal`, `CheckType`, `CheckSharpener`, `CheckTypeMapper`, `CheckProposalGenerator`, `CheckApprovalWorkflow`, `CheckImplementationStoryGenerator`, `CheckEffectivenessTracker`, `AutoDeactivator`, `CheckRepository` | `bc-cut-decisions.md §BC13`; `FK-41 §41.6` | Kein Code vorhanden; groesste Sub (~10 Klassen) |
| A6 | Persistierung aller drei Artefakt-Typen in Postgres-Tabellen `fc_incidents`, `fc_patterns`, `fc_check_proposals` via `Telemetry.write_projection` | `FK-41 §41.3.1–41.3.3` | Schemas und Schreib-Logik fehlen; Schema-Owner ist dieser BC |
| A7 | Wirksamkeitspruefung (Schritt 6): Lese-Zugriff auf `story_metrics` via `Telemetry.read_projection`; Rueckschreiben von Effectiveness-Feldern in `fc_check_proposals` | `FK-41 §41.6.7` | Auto-Deaktivierungslogik und kritisch-Ausnahme nicht vorhanden |
| A8 | Integration mit `verify-system.LlmEvaluator` fuer Schritt 1 (Invariante schaerfen) und Schritt 3 (Proposal erstellen) via `prompt-runtime.PromptRuntime.materialize_prompt` | `FK-41 §41.6.2`, `FK-41 §41.6.4`; `bc-cut-decisions.md #54` | Cross-BC-Aufruf fehlt vollstaendig |
| A9 | Integration mit `Integrations.github`-Adapter fuer Schritt 5 (CheckImplementationStoryGenerator erzeugt regulaere Implementation-Story) | `FK-41 §41.6.6`; `bc-cut-decisions.md #55` | Story-Erzeugungsfluss nicht vorhanden |
| A10 | `record_incident`-Schnittstelle als Empfaenger fuer `governance-and-guards`, `verify-system`, `story-closure` (eingehende Capture-Akteure) | `FK-41 §41.4.2`; `bc-cut-decisions.md §BC13 Beziehungen` | Top-Surface-Empfang fehlt; Gegenstelle-BCs koennen nicht anliefern |
| A11 | Tests: Unit-Tests fuer Promotion-Regeln, Ingress-Kriterien, Check-Typ-Mapping; Contract-Tests fuer `fc_*`-Schemas; Integration-Tests fuer Incident-Roundtrip | `guardrails/testing-guardrails.md`; `CLAUDE.md §Tests` | Keine Tests auf keiner Ebene vorhanden |
| A12 | Formal-Spec-Referenzen `formal.deterministic-checks.invariants` und `formal.deterministic-checks.scenarios` (laut FK-41 Frontmatter) | `FK-41 §PROSE-FORMAL`; `FK-41 frontmatter formal_refs` | Formale Spezifikation noch nicht erarbeitet oder verlinkt |

### 4.2 B — Teilweise umgesetzt

Keine Befunde in dieser Kategorie.

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug, Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Paket-Stub ohne `__init__.py`-Inhalt verdeckt fehlende Implementierung | `src/agentkit/failure_corpus/__init__.py` | `bc-cut-decisions.md §BC13`; `CLAUDE.md §ZERO DEBT RULE` | Ein leerer Stub signalisiert nach aussen, das Paket existiere, obwohl keine einzige oeffentliche Klasse oder Funktion vorhanden ist. Consumer-BCs (governance-and-guards, verify-system, story-closure) wuerden bei Import sofort scheitern. Kein Konzept-Drift im engeren Sinn, aber ZERO-DEBT-Verletzung: halbfertiger Architekturuebergang ohne Implementierung. |

## 5. Ableitungen / Empfehlungen

1. **Konzept-Refactor-Offenposten zuerst schliessen (bc-cut-decisions.md #52–#58):** Sieben noch offene Konzeptklaerungen (FK-69-Split fuer fc_*-Tabellen-Schema-Ownership, FK-41 JSONL-Wording, LLM-Aufruf-Modul-Pfade, Story-Erzeugung Schritt 5, CLI-Boundary-Control-Wording, Auto-Deaktivierung Lese-Schnittstelle, QA-Evaluation als Capture-Akteur) sollten vor der Implementierung praezisiert werden — sonst riskiert die Implementierung, gegen ein noch unklares Konzept zu bauen.

2. **Basismodelle und `IncidentTriage`-Sub zuerst implementieren (A2, A3, A6):** `FailureCategory`, `PromotionStatus`, `IncidentCandidate`, `Incident`, `IncidentNormalizer`, `IngressCriteria` und `IncidentRepository` sind Fundament aller weiteren Subs. Ohne `IncidentTriage` kann `PatternPromotion` nicht aufgebaut werden und kein eingehender Capture-Akteur liefern. Risiko: Alle drei eingehenden BCs (governance-and-guards, verify-system, story-closure) sind blockiert.

3. **Top-Surface `FailureCorpus.record_incident` priorisiert herstellen (A1, A10):** Die Top-Surface-Methode `record_incident` ist das erste Integrationsziel fuer alle Capture-Akteure. Sie kann frueher fertig sein als die vollstaendige IncidentTriage-Sub und sollte als erstes stabiles Interface exponiert werden.

4. **Formale Spezifikation `formal.deterministic-checks.*` klaeren (A12):** FK-41 referenziert zwei formale Specs im Frontmatter (`formal.deterministic-checks.invariants`, `formal.deterministic-checks.scenarios`). Ob diese Dateien existieren oder noch erstellt werden muessen, ist vor dem Implementierungsstart zu klaeren — sie sind normative Grundlage fuer die deterministischen Check-Invarianten.

5. **Unit-Tests fuer Promotion-Regeln und Check-Typ-Mapping von Anfang an schreiben (A11):** Die drei Promotion-Regeln (Wiederholung, HoheSchwere, Checkbarkeit) und das deterministische Category-to-CheckType-Mapping sind reine Logik ohne externe Abhaengigkeiten — ideale erste Unit-Tests. Ohne diese Tests fehlt Negativpfad-Abdeckung an einer der sicherheitsrelevantesten Stellen des BC.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/07-failure-corpus.md` (DK-07)
  - `concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md` (FK-41)
  - `concept/_meta/bc-cut-decisions.md` (Abschnitt BC 13 vollstaendig; Refactor-Liste #52–#58; uebergreifende Entscheidungen)
  - `stories/_gap-analyse-schema.md`
  - `CLAUDE.md`
- **Punktuell via Grep:**
  - Pattern `failure.corpus|failure_corpus` in `bc-cut-decisions.md`: BC-13-Abschnitt und alle Querverweise lokalisiert
  - Pattern `failure.corpus` in `concept/technical-design/_meta/domain-registry.yaml`: Display-Name und contract_docs bestaetigt
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/failure_corpus/**/*`: nur `__init__.py` und `__pycache__`-Dateien gefunden, keine weiteren Python-Dateien
  - Glob `tests/**/failure_corpus*` und `tests/**/*failure*`: keine Treffer — keine Tests vorhanden
