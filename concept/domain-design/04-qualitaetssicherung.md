---
concept_id: DK-04
title: Mehrstufige Qualitätssicherung
module: quality-assurance
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: quality-assurance
defers_to: []
supersedes: []
superseded_by:
tags: [quality-assurance, verify, trust-classes, remediation, adversarial-testing]
---

# 04 — Mehrstufige Qualitätssicherung

**Quelle:** Konsolidiert aus agentkit-domain-concept.md Kapitel 7 + review-quality-improvement.md
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Dieses Kapitel beschreibt die fachlichen Prinzipien der
Qualitätssicherung. Die konkrete Verortung in der Pipeline (vier
Schichten der Verify-Phase) ist in [02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md), Abschnitt 2.2 definiert.

## 4.1 Deterministische vs. LLM-basierte Prüfung

Die Qualitätssicherung trennt strikt zwischen deterministischen Checks
(Skripte, keine LLMs) und LLM-basierten Bewertungen. Deterministische
Checks sind reproduzierbar und kostenlos. LLM-basierte Bewertungen
sind nicht-deterministisch, liefern aber semantisches Urteilsvermögen,
das kein Algorithmus leisten kann. Beide ergänzen sich, ersetzen sich
aber nicht.

Deterministische Checks laufen als Gate: Scheitern sie, wird die
LLM-Schicht gar nicht erst gestartet.

## 4.2 Trust-Klassen

Nicht jede Datenquelle ist gleich vertrauenswürdig. Das
Trust-Klassen-Modell bestimmt, welche Prüfergebnisse blocking sein
dürfen:

| Klasse | Datenquelle | Blocking erlaubt |
|--------|-------------|------------------|
| A | Datenbank, Backend-Health, ARE | Ja |
| B | Telemetrie, Prozess-Identität | Ja |
| C | Vom Worker selbst erzeugte Evidence (Screenshots, API-Logs) | Nein |

Kernregel: Klasse C darf nie blocking sein, weil der Agent seine
eigene Prüfung nicht bestehen können soll.

**Operative Konsequenz fuer Finding-Resolution:** Worker-Artefakte
(`protocol.md`, `handover.json`) duerfen den Status eines Findings
nicht autoritativ setzen. Wenn ein Worker ein Finding als `ADDRESSED`
markiert, ist das eine Behauptung (Trust C), kein Nachweis. Der
kanonische Resolution-Status eines Findings wird ausschliesslich
durch Layer 2 (StructuredEvaluator) im Remediation-Modus erzeugt
(siehe §4.6).

**Empirischer Beleg (BB2-012):** Der Worker markierte INV-6 als
`ADDRESSED` in `protocol.md` und `handover.json`, obwohl nur der
closed-phase-Teilfall behoben war. Der Wrong-Phase-Fall blieb offen.
Die Worker-Zusammenfassung in `risks_for_qa` hatte den offenen
Subcase bereits wegkomprimiert. Das System uebernahm die Teilbehebung
als Vollbehebung, weil keine andere Instanz den Finding-Status setzte.

## 4.3 Recurring Guards vs. Story-spezifische Prüfung

Innerhalb der Qualitätssicherung gibt es eine fundamentale
Timing-Unterscheidung:

**Recurring Prozess-Guards** werden unabhängig von der konkreten Story
definiert und gelten für alle Stories eines Typs. Sie prüfen, ob der
Agent den vorgeschriebenen Prozess eingehalten hat, nicht ob die
fachliche Lösung korrekt ist. Diese Guards können vor der Story
definiert werden, weil sie kein Implementierungswissen voraussetzen.

**Story-spezifische fachliche Prüfung** setzt Implementierungswissen
voraus (Tabellennamen, Spaltenstrukturen, erwartete Werte). Dieses
Wissen existiert zum Zeitpunkt der Story-Erstellung nicht. Die
Prüfung kann erst nach der Implementierung stattfinden und ist damit
nachträgliche Verifikation, kein TDD.

## 4.4 Zirkularitätsbruch durch Rollentrennung

Die fachliche Prüfung der Implementierung erfolgt nicht durch
denselben Agenten, der implementiert hat. In der Verify-Phase werden
zwei Mechanismen eingesetzt, die beide auf anderen LLMs basieren als
der Worker:

**LLM-Bewertungen** (Schicht 2 der Verify-Phase) laufen als
Skript-Aufrufe ohne Dateisystem-Zugriff. Sie bewerten die
Implementierung semantisch gegen Anforderungen und Konzept.

**Adversarial Testing** (Schicht 3 der Verify-Phase) ist der einzige
Agent mit Dateisystem-Zugriff in der Verify-Phase. Er baut aktiv
neue Tests, die der Worker nicht geschrieben hat, mit dem Ziel,
Fehler zu finden.

Wenn derselbe Agent seine eigene Arbeit prüft, ist die Validierung
zirkulär. Die Kombination aus anderem Modell und anderem Auftrag
bricht diese Zirkularität auf. Das Konzept der spezialisierten
Rollen ([01-rollen-und-llm-einsatz.md](01-rollen-und-llm-einsatz.md)) ist hier Voraussetzung, nicht Ergänzung.

## 4.4a Verify-Kontext-Differenzierung

### Problem: `mode` ist kein hinreichender Diskriminator fuer die Verify-Tiefe

Das Feld `mode` wird in der Setup-Phase gesetzt und bleibt ueber
den gesamten Story-Lifecycle konstant. Wenn die Pipeline nur `mode`
auswertet, werden bei Exploration-Mode-Stories spaetere Verify-
Durchlaeufe faelschlich als "leichtgewichtig" behandelt. Das ist ein
kritischer Governance-Fehler: Nach der Implementation wuerden Layer
2-4 uebersprungen, obwohl bereits Code existiert und volle QA noetig
ist.

### Loesung: Separates `verify_context`-Feld

Ein dediziertes `verify_context`-Feld identifiziert, in welchem
Kontext der aktuelle Verify-Durchlauf stattfindet:

| `verify_context` | Ausloeser | QA-Tiefe | Begruendung |
|------------------|-----------|----------|-------------|
| `post_implementation` | Verify nach abgeschlossener Implementation-Phase | Volle 4-Schichten-QA (Structural, Semantisch, Adversarial, Policy). | Dies ist der primaere QA-Durchlauf — unabhaengig davon, ob `mode = "exploration"` oder `mode = "execution"`. |
| `post_remediation` | Verify nach einer Remediation-Runde | Volle 4-Schichten-QA (Structural, Semantisch, Adversarial, Policy). | Nach einer Nachbesserung muss erneut die komplette QA laufen; ein Teilpfad waere ein Governance-Leck. |

### Invariante: Kein Structural-only-Verify fuer Code-Stories

Es gibt keinen gueltigen Structural-only-Verify-Pfad fuer
Implementation- und Bugfix-Stories. Sobald Code implementiert oder
nachgebessert wurde, sind Layer 2-4 Pflicht. Fehlende LLM-Reviews
bei Code-Stories sind ein HARD BLOCKER, kein Warning.

### Empirischer Anlass (BB2-057)

Eine Implementation-Story im Exploration Mode wurde nach der
Implementation ohne ein einziges LLM-Review durchgewunken. Die
Ursache: Der Phase Runner verwendete `mode == "exploration"` als
Trigger fuer einen Structural-Only-Pfad — unabhaengig davon, welche
Phase gerade verifiziert wurde. Der Orchestrator handelte korrekt
nach Phase-State-Vertrag: COMPLETED + leere `agents_to_spawn` →
Closure. Der Bug lag zu 100% im deterministischen Code (Phase
Runner), nicht im nicht-deterministischen Orchestrator.

Die Konsequenz: Die Story passierte ohne QA-Review, ohne Semantic
Review, ohne Governance. Die Guards (`guard.llm_reviews`,
`guard.multi_llm`) erkannten die Anomalie korrekt, waren aber nur
als WARNING klassifiziert — nicht als BLOCKER.

---

## 4.5 Review-Qualitätsverbesserung

> **Status:** Entwurf — in Konsolidierung
>
> **Provenienz:** Konsolidiert aus Sparring Claude + ChatGPT
>
> **Bezug:** Verify-Phase, Review-System, LLM-Bewertungen

### 4.5.1 Problemstellung

#### Ausgangslage

AgentKit führt Reviews in zwei architektonisch verschiedenen Tracks durch:

- **Track A — Sparring-Reviews während der Implementierung:** Der Worker-Agent sendet Code an externe LLMs (ChatGPT, Gemini) über MCP-Pools mit vordefinierten Prompt-Templates. Dialogischer Flow, Konversationskontinuität auf demselben Slot, freiformige Antworten.

- **Track B — StructuredEvaluator in Verify Schicht 2:** Drei parallele Evaluator-Aufrufe (QA-Review 12 Checks, Semantic Review 1 Check, Doc-Fidelity 1 Check) mit festen ContextBundle-Feldern, JSON-Schema-Validierung, fail-closed-Semantik.

#### Identifizierte Probleme

**Problem 1: Worker-kuratierte Evidenz (Track A)**

Der Worker entscheidet eigenständig, welche Dateien im Review-Bundle landen. Es gibt keinen systemseitigen Mechanismus, der sicherstellt, dass autoritative Nachbarquellen (Schemas, Interfaces, Runtime-Pfade, Konzeptdokumente) mitgeliefert werden.

Empirischer Beleg — BB2-011: Der Worker schickte die geänderten Dateien (token_counter.py, errors.py, strict_loader.py, reference_schema.yaml, Tests), aber NICHT: schemas.py (ProviderConfig-Definition), protocols.py (TokenCounter-Protocol), provider_adapter.py (Konsument), die echte model_registry.yaml. Die Reviewer konnten Schema-Compliance-Behauptungen nicht gegen autoritative Quellen verifizieren.

Das ist kein Usability-Problem, sondern ein **Governance-Problem**: Die zu prüfende Instanz entscheidet, welche Evidenz der Prüfer sieht.

**Problem 2: Fehlende Autoritätsmarkierung (Track A)**

Die externen Review-Templates sagen "Review the attached source files", unterscheiden aber nicht zwischen primären Änderungen, normativem Referenzmaterial und Worker-Behauptungen. Der Reviewer hat keine epistemische Hierarchie.

Im Kontrast dazu haben die internen QA-Prompts (qa-semantic.md) bereits explizite Source Precedence:
1. Story Specification / Acceptance Criteria (höchste Autorität)
2. Concept Documents
3. CLAUDE.md / Guardrails
4. Code und Evidenz-Artefakte
5. Worker-Protocol-Claims (niedrigste Autorität)

Externe Reviewer erhalten diese Strukturierung nicht.

**Problem 3: Reviewer-Divergenz (übergreifend)**

BB2-011 P1: ChatGPT bewertet REWORK (4 BLOCKINGs), Gemini bewertet PASS (0 Findings) — bei identischem Material. ChatGPTs zentrale Befunde (z.B. fehlender Feature-Flag-Whitelist-Check) waren substanziell korrekt und wurden später implementiert. Gemini hat die vorhandenen Informationen nicht scharf genug ausgewertet.

Das ist teilweise ein Kontextproblem, aber teilweise auch ein **Kalibrierungsproblem**: Verschiedene LLMs haben unterschiedliche Sensitivität (Recall vs. Precision).

**Problem 4: Starre Bundle-Kompression (Track B)**

ContextBundles werden bei Überlänge mit dem "beginning + end"-Protokoll beschnitten (32.000 Zeichen pro Bundle). Für Review-Evidenz ist das problematisch, weil relevante Stellen häufig in der Mitte liegen: Schema-Felder, Guardrail-Absätze, Call-Site-Details, Testabschnitte.

#### Was bereits funktioniert

- **Mediation-Prozess:** BB2-010 zeigt, dass Divergenzen sauber aufgelöst werden (FIX, OUT OF SCOPE, DOCUMENT). Der Mechanismus ist wirksam.
- **P4-Synthesis:** Cross-Pass-Kausalitätsketten (z.B. "structured-output branch blind spot" in BB2-010) werden zuverlässig identifiziert, weil die Synthesis auf demselben Slot läuft.
- **Interne QA-Prompts:** qa-semantic.md hat bereits Step 0 (Scope Assessment), Applicability-Regeln und explizite Source Precedence. Das ist ein gutes Muster, das extern fehlt.

### 4.5.2 Grundsatzentscheidung

**Kein einheitliches "Review Preflight Protocol".**

Zwei architektonisch verschiedene Systeme brauchen zwei verschiedene Lösungen:

| Aspekt | Track A (Sparring) | Track B (StructuredEvaluator) |
|--------|-------------------|------------------------------|
| Steuerung | Worker-Agent (dialogisch) | Python-Orchestrierung (deterministisch) |
| Kontext | merge_paths (Worker-kuratiert) | ContextBundle (6 feste Felder) |
| Antwortformat | Freitext-Tabelle | JSON-Schema (CheckResult) |
| Multi-Turn | Ja (Konversationskontinuität) | Nein (1 Prompt → 1 Response) |
| Fehlerbehandlung | Worker integriert Feedback | fail-closed + Retry mit Schema-Hint |
| Lösung | Evidence Assembler + DSL | Context Sufficiency Builder + Packing |

### 4.5.3 Track A: Sparring-Reviews — vier Säulen

#### 4.5.3.1 Säule 1 — Evidence Assembler (systemseitig)

**Ziel:** Die Zusammenstellung des Review-Bundles wird vom Worker auf das System verlagert. Der Worker darf ergänzen, aber nicht kuratieren.

**Strategie: Hybrid mit deterministischem Kern**

Der Assembler arbeitet in drei Stufen:

**Stufe 1 — Deterministischer Kern (ohne Sprachwissen)**

Für jede geänderte Datei (aus Git-Diff) automatisch einsammeln:
- Story-Spec (aus StoryContext bzw. dessen `context.json`-Export → story_dir)
- Concept-Docs (aus StoryContext bzw. dessen `context.json`-Export → concept_paths)
- Guardrail-Dokumente (aus Pipeline-Config → guardrails.dir)
- Modul-Nachbarn: `__init__.py`, `schemas.py`, `protocols.py`, `config.py`, `types.py` im selben Verzeichnis und übergeordneten Verzeichnis
- Referenzierte YAML/JSON-Configs im selben Modul

Diese Stufe braucht kein Sprachwissen und liefert bereits den größten Mehrwert gegenüber dem Status quo.

**Stufe 2 — Leichte sprachspezifische Extraktion**

Für Python, TypeScript und Java: Pragmatische Import-Extraktion aus den geänderten Dateien. Kein volles AST-Framework (kein ts-morph, kein JavaParser), sondern regelbasiertes Parsing. Aufgelöste Imports werden als SECONDARY_CONTEXT-Dateien in das Bundle aufgenommen. Nicht auflösbare Referenzen werden als UNRESOLVED markiert und nicht eskaliert.

**Python** (einfachster Fall):
- `from X import Y` und `import X` → auflösen auf Dateipfade relativ zum Repo-Root

**TypeScript** (6 Pattern-Klassen):
1. Normale ES-Imports: `import X from '...'`, `import {A,B} from '...'`, `import * as X from '...'`
2. Type-only Imports: `import type { Foo } from '...'` (Interfaces/DTOs/Props — review-relevant)
3. Side-effect Imports: `import './polyfill'`, `import './globals.css'`
4. Re-exports als Barrel-Signal: `export * from './x'`, `export {A,B} from './y'`
5. Legacy CommonJS: `import mod = require('mod')`, `const x = require('...')`
6. Dynamische Imports mit String-Literal: `await import('./foo')` (nur bei String-Literal)

*Path-Alias-Auflösung:*
- Nächstes `tsconfig.json`/`jsconfig.json` vom File aufwärts suchen
- `extends` auflösen, `compilerOptions.baseUrl` + `paths` mergen
- Nur einfache Fälle: exakter Alias `@/foo → src/foo` und ein-Wildcard `@app/* → src/*`
- Kandidatenliste: `file.ts`, `file.tsx`, `file.js`, `file.jsx`, `file.d.ts`, `dir/index.ts`, `dir/index.tsx`
- Scheitert Alias-Auflösung → als extern markieren, nicht eskalieren

*Barrel-Export-Auflösung:*
- Wenn Import auf `index.ts`/`index.tsx` zeigt: Barrel-Datei ins Bundle + alle `export * from`/`export {...} from`-Targets **eine Ebene tief**
- Bei named Imports (z.B. `import { UserCard } from '@/components'`): per Regex in der Barrel-Datei das Leaf-Modul identifizieren und gezielt aufnehmen
- Danach stoppen — kein rekursives Barrel-Resolving

*Framework-Hinweise:*
- React/Next.js: Kein eigener Syntax-Support nötig; Hauptmehrwert liegt in tsconfig-Alias-Resolving (`@/...`-Pattern) und colocated Files (Component.tsx + Component.test.tsx + Component.module.css → gehört in Stufe 1)
- Angular: Optional `@Component({ templateUrl, styleUrl })` per Regex extrahieren — diese Dateien sind fast immer review-relevant

**Java** (Imports + Package-Index + Spring-Heuristiken):

Reine Import-Extraktion ist bei Java/Spring zu schwach, weil (a) same-package Typen ohne Import nutzbar sind und (b) Spring-Verdrahtung über Annotations/Scanning läuft.

*Import-Patterns (4 Formen laut JLS):*
1. `import a.b.C;`
2. `import a.b.*;`
3. `import static a.b.C.MEMBER;`
4. `import static a.b.C.*;`

*Source-Root-Erkennung:*
- Maven/Gradle-Konvention: `src/main/java`, `src/test/java`
- Bei Multi-Module-Repos: pro Modul auflösen

*Package-Index (same-package Heuristik):*
- `package`-Statement jeder geänderten Datei erfassen
- Repoweiten `package → Klassen-Dateien`-Index aufbauen
- In geänderter Datei per Regex nach einfachen Typnamen in `extends`, `implements`, Feldtypen, Konstruktorparametern, `throws`, Annotation-Attributen mit `Foo.class`, `@Bean`-Rückgabetypen suchen
- Treffer gegen gleichen Package-Index matchen → als SAME_PACKAGE_HEURISTIC ins Bundle

*Spring-Boot-Heuristiken (eigene Regex-Klasse, nicht als normale Imports behandelt):*
- `@SpringBootApplication(...)` — Application Class + scanBasePackages
- `@ComponentScan(...)` — explizite Scan-Grenzen
- `@Import(...)` — zusätzliche Config-Klassen
- `@EntityScan(...)` — Entity-Packages
- `@EnableJpaRepositories(...)` — Repository-Packages
- `@Autowired` nur als Signal (zeigt DI-Relevanz an, reicht nicht für Datei-Auflösung)

*Wildcard-Imports (`import a.b.*`):*
- Nicht blind expandieren; stattdessen nur Typen aufnehmen, deren Simple Names in der geänderten Datei tatsächlich vorkommen

**Confidence-Labels für alle Sprachen:**

Jede aufgelöste Referenz erhält ein Label, das dem Reviewer die Zuverlässigkeit anzeigt:
- `RESOLVED_IMPORT` — direkt aufgelöster Import
- `RESOLVED_ALIAS` — über tsconfig/jsconfig-Alias aufgelöst
- `BARREL_CONTEXT` — über Barrel-Export eine Ebene tief aufgelöst
- `SAME_PACKAGE_HEURISTIC` — Java same-package Typname-Match
- `SPRING_SCAN_HEURISTIC` — über Spring-Annotation gefunden
- `UNRESOLVED_DYNAMIC` — dynamischer/berechneter Specifier, nicht auflösbar

**Grenzen ohne AST (akzeptierte Einschränkungen):**
- TypeScript: dynamische/berechnete Specifier, komplexe package.json exports/imports, tiefe Barrel-Ketten, Monorepo-Self-References — für Review-Kontext akzeptabel
- Java: Classpath-Scanning, @Bean-Factory-Methoden, @Profile/Conditional Beans, Reflection, XML/Properties/YAML-Verdrahtung, Annotation-Meta-Komposition — moderat relevant, durch Package-Index und Spring-Heuristiken teilweise kompensiert

**Stufe 3 — Worker-Hinweise (nur additiv)**

handover.json und worker-manifest.json dürfen zusätzliche Dateien vorschlagen, die der Assembler einbezieht. Aber:
- Worker-Hinweise ersetzen nie den deterministischen Kern
- Worker-Hinweise werden als WORKER_ASSERTION markiert, nicht als SECONDARY_CONTEXT
- Der Assembler warnt, wenn der Worker Dateien vorschlägt, die er gleichzeitig geändert hat (Selbstreferenz)

**Bundle-Größen-Limit:** Das assemblierte Bundle darf unkomprimiert 350 KB nicht überschreiten. Bei Überschreitung priorisiert der Assembler: PRIMARY_NORMATIVE > PRIMARY_IMPLEMENTATION > SECONDARY_CONTEXT > WORKER_ASSERTION. Innerhalb einer Klasse wird nach Relevanz (geänderte Dateien zuerst, dann direkte Imports, dann Heuristik-Treffer) gekürzt.

**Design-Prinzip:** Der Assembler muss auch ohne Stufe 2 (Sprachwissen) nützlich sein. Stufe 1 allein behebt bereits das Kernproblem der worker-kuratierten Bundles.

#### 4.5.3.2 Säule 2 — Autoritätsklassen im Bundle

Jede Datei im Review-Bundle erhält eine Autoritätsklassifikation:

| Klasse | Bedeutung | Beispiele |
|--------|-----------|-----------|
| `PRIMARY_NORMATIVE` | Autoritative Spezifikationsquellen | Story-Spec, Concept-Docs, Schema-Definitionen, Guardrail-Dokumente |
| `PRIMARY_IMPLEMENTATION` | Geänderte Dateien und deren Tests | Alle Dateien im Git-Diff |
| `SECONDARY_CONTEXT` | Nachbardateien für Verifikation | Aufgelöste Imports, Call-Sites, Configs |
| `WORKER_ASSERTION` | Vom Worker deklarierte Informationen | handover.json Claims, protocol.md |

**Darstellung im Prompt:**

Statt "The source files for this story are attached — review them all" wird das Bundle dem Reviewer strukturiert präsentiert:

```
## Bundle-Inhalt

### PRIMARY_NORMATIVE (autoritative Quellen — höchste Beweiskraft)
- story.md (Story-Spezifikation mit Akzeptanzkriterien)
- TK-02_appendix.md (Architektur-Referenz)

### PRIMARY_IMPLEMENTATION (geänderte Dateien — Prüfgegenstand)
- token_counter.py
- errors.py
- strict_loader.py
- test_token_counter.py
- test_strict_loader.py

### SECONDARY_CONTEXT (Nachbarquellen — für Verifikation)
- schemas.py (ProviderConfig-Definition, importiert von strict_loader.py)
- protocols.py (TokenCounter-Protocol, implementiert von token_counter.py)
- provider_adapter.py (Konsument von token_counter und errors)

### WORKER_ASSERTION (Worker-Claims — niedrigste Beweiskraft)
- handover.json: changes_summary, risks_for_qa, acceptance_criteria_status
```

> **[Entscheidung 2026-04-08]** Element 24 — Preflight-Turn / Request-DSL ist Pflicht. FK-26 §26.5b, 7 Request-Typen.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 24.

#### 4.5.3.3 Säule 3 — Request-DSL (einmaliger Nachforderungs-Turn)

**Ziel:** Der Reviewer kann in einer strukturierten ersten Runde fehlenden Kontext nachfordern, bevor der eigentliche Review beginnt.

**7 maschinenauflösbare Request-Typen:**

| Request-Typ | Semantik | Beispiel |
|-------------|----------|---------|
| `NEED_FILE(path_or_pattern, why)` | Konkrete Datei nachfordern | `NEED_FILE("agentframework/llm/model_registry.yaml", "Fallback-Prioritäten verifizieren")` |
| `NEED_SCHEMA(symbol_or_file, why)` | Schema/Interface/DTO nachfordern | `NEED_SCHEMA("ProviderConfig", "extra=forbid prüfen")` |
| `NEED_CALLSITE(symbol, why)` | Aufrufer eines Symbols finden | `NEED_CALLSITE("create_token_counter", "Factory-Nutzung verifizieren")` |
| `NEED_RUNTIME_BINDING(config_or_flag, why)` | Config-Bindung prüfen | `NEED_RUNTIME_BINDING("provider_fallback_enabled", "Flag-Binding verifizieren")` |
| `NEED_TEST_EVIDENCE(test_or_command, why)` | Testergebnis anfordern | `NEED_TEST_EVIDENCE("pytest tests/llm/", "Grüne Suite bestätigen")` |
| `NEED_CONCEPT_SOURCE(doc_section, why)` | Konzeptdokument-Abschnitt | `NEED_CONCEPT_SOURCE("TK-13 §4.10", "Error-Taxonomie-Spezifikation")` |
| `NEED_DIFF_EXPANSION(file, region, why)` | Erweiterten Diff-Kontext | `NEED_DIFF_EXPANSION("provider_adapter.py", "chat() method", "Vollständige Methode sehen")` |

**Ablauf:**

```
Worker assembliert Bundle (via Evidence Assembler)
  → chatgpt_send(PREFLIGHT-Prompt + merge_paths)
  → ChatGPT antwortet mit 0-8 strukturierten Requests
  → System löst Requests deterministisch auf
  → chatgpt_send(REVIEW-Prompt + erweiterte merge_paths)
  → ChatGPT führt den eigentlichen Review durch
```

**Wichtige semantische Abgrenzung:**

- `evidence_sufficiency` = War genug Material da, um die erhobenen Claims zu stützen?
- `review_completeness` = Wurden alle relevanten Probleme gefunden?
- Das DSL garantiert **nur** evidence_sufficiency, **nie** review_completeness
- "Reviewer hat keine weiteren Requests" bedeutet "keine weiteren erkennbaren Evidenzlücken", NICHT "der Review ist vollständig"

**Empirischer Beleg:** BB2-011 P1 Gemini hatte dasselbe Material wie ChatGPT, fand aber null Findings. Mehr Kontext hätte Gemini nicht geholfen — Gemini hat die vorhandene Information nicht scharf genug gelesen. Das DSL löst nur "known unknowns", nicht "unknown unknowns".

**Begrenzung:** Max 8 Requests pro Reviewer. Jeder Request wird deterministisch aufgelöst (Datei lesen, Grep ausführen, Test ausführen). Timeout: 30 Sekunden pro Request. Nicht auflösbare Requests werden als "UNRESOLVED" dokumentiert und dem Reviewer mitgeteilt.

**Aktivierung:** Immer — unabhängig von Story-Größe. Eine größenabhängige Aktivierung (z.B. nur ab M) würde voraussetzen, dass die Story-Größe zuverlässig geschätzt ist. Empirisch ist das nicht der Fall: LLMs schätzen Story-Größen nicht zuverlässig ein. Daher volles Programm für jede Story.

> **[Entscheidung 2026-04-08]** Element 26 — Quorum / Tiebreaker ist Pflicht. Dritter Reviewer bei Divergenz.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 26.

#### 4.5.3.4 Säule 4 — Divergenz-Instrumentierung und Quorum

**Grundposition:** Reviewer-Divergenz ist primär produktive Asymmetrie, nicht Defekt.

**Komplementäre Reviewer-Rollen:**
- ChatGPT = skeptical auditor (hoher Recall, findet mehr Issues, höhere False-Positive-Rate)
- Gemini = spec-conservative (geringerer Recall, weniger False Positives, höhere Merge-Readiness-Tendenz)

Diese Asymmetrie ist gewollt: Verschiedene Reviewer beleuchten verschiedene Fehlermodi.

**Quorum statt Scoring:**

Wenn zwei Reviewer (z.B. ChatGPT und Gemini) zu unterschiedlichen Verdikten kommen, spannt der QA-Agent ein Quorum auf: Ein dritter Reviewer (z.B. Grok) wird hinzugezogen. Die Mehrheitsentscheidung (2 gegen 1) ergibt das finale Verdikt. Dieses Modell entspricht dem bestehenden ARE Peer-Review-Quorum.

**Ablauf:**

```
Verdikt A (Reviewer 1) != Verdikt B (Reviewer 2):
  → QA-Agent schickt Review-Bundle an Reviewer 3 (Tiebreaker)
  → Mehrheitsentscheidung: 2 gegen 1 gewinnt
  → Finales Verdikt aus den übereinstimmenden zwei Reviewern
```

Kontextvollständigkeit wird bereits durch Evidence Assembly (Säule 1) und
Context Sufficiency (§4.5.4) sichergestellt — kein zusätzliches
evidence-getriebenes Retry-Routing erforderlich.

**Der QA-Agent steuert das Quorum eigenständig.** Die Pipeline
(Orchestrator) delegiert die Quorum-Auslösung vollständig an den
QA-Agenten (Worker). Das Quorum produziert kein FAIL in der
Policy-Engine — es liefert das finale Verdikt.

**Was das Design explizit NICHT macht:**
- Reviewer-Kalibrierung vorab (beide auf dieselbe Härte trimmen)
- Divergenz als automatischen Fehler behandeln
- Quorum-Ergebnis als Gate in der Policy Engine
- Numerische Schwellwerte oder qualitative Score-Kategorien (LOW/MEDIUM/HIGH)

### 4.5.4 Track B: StructuredEvaluator — Context Sufficiency Builder + Packing

#### 4.5.4.1 Design-Entscheidung: Kein zusätzlicher LLM-Turn

Der StructuredEvaluator-Contract ist auf "ein Prompt → strukturierte Checks → Aggregation" optimiert:
- Feste Check-IDs pro Rolle (12 für QA, 1 für Semantic, 1 für Doc-Fidelity)
- JSON-Schema-Validierung mit fail-closed-Semantik
- Retry nur für Format-Fehler, nicht für Kontext-Nachforderungen
- Unbekannte Check-IDs werden verworfen

Ein Preflight-Roundtrip wäre hier ein Fremdkörper. Stattdessen wird der Kontext VOR dem Evaluator deterministisch optimiert.

> **[Entscheidung 2026-04-08]** Element 27 — Context Sufficiency Builder ist Pflicht-Gate VOR dem Review. Reviews finden IMMER statt.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 27.

#### 4.5.4.2 Context Sufficiency Builder (neue deterministische Stufe)

Läuft vor jedem `LlmEvaluator.evaluate()`-Aufruf:

**Prüfungen:**
1. Sind alle 6 Bundle-Typen vorhanden? (story_spec, diff_summary, concept_excerpt, handover, arch_references, evidence_manifest)
2. Trunkierungs-Risiko: Welche Bundles überschreiten das 32.000-Zeichen-Limit?
3. Normative Quellen: Sind Concept-Docs und Guardrails als Primärquelle vorhanden oder nur als Summary/Auszug?
4. Handover-Qualität: Enthält handover.json substantielle risks_for_qa oder nur Platzhalter?

**Ergänzungen:**
- Automatisch fehlende Nachbar-Artefakte nachladen (analog zum Evidence Assembler, aber für die 6 Bundle-Felder)
- Concept-Excerpt durch Primärquelle ersetzen: Konzeptdokumente über `concept_paths` aus `StoryContext` bzw. dessen `context.json`-Export auflösen und aus dem `concept/`-Verzeichnis des Zielprojekts laden, wenn vorhanden und innerhalb des Token-Limits
- Externe autoritäre Quellen (`external_sources` aus `StoryContext` bzw. dessen `context.json`-Export) als Referenzen an den Reviewer weiterreichen. Bei Nichterreichbarkeit: unresolved evidence gap — kein PASS auf Claims, die diese Quelle benötigen (FK 21.3.3)

**Artefakt:**
Schreibt `context_sufficiency.json` ins QA-Verzeichnis:

```json
{
  "schema_version": "1.0",
  "story_id": "BB2-042",
  "stage": "context_sufficiency",
  "bundles": {
    "story_spec": {"status": "present", "chars": 4200, "truncated": false},
    "diff_summary": {"status": "present", "chars": 28500, "truncated": false},
    "concept_excerpt": {"status": "summary_only", "chars": 8200, "truncated": false,
                        "note": "Primärquelle TK-02 nicht verfügbar, nur Auszug"},
    "handover": {"status": "present", "chars": 3100, "truncated": false},
    "arch_references": {"status": "missing"},
    "evidence_manifest": {"status": "present", "chars": 45000, "truncated": true,
                          "truncated_from": 62000}
  },
  "sufficiency": "reviewable_with_gaps",
  "gaps": ["arch_references missing", "concept_excerpt is summary only"]
}
```

**Vollstaendigkeit der Bundle-Loader:** Der Context Sufficiency
Builder MUSS fuer alle 6 konfigurierten Bundle-Typen eigene Loader
haben. Fehlende Loader (z.B. fuer `story_spec` und `handover`)
fuehren dazu, dass auf Disk vorhandene Daten als "missing"
klassifiziert werden — ein systematischer Fehler, der die
Sufficiency-Bewertung verfaelscht. Die Loader-Abdeckung ist eine
Implementierungs-Invariante: Jeder Bundle-Typ in der Konfiguration
erfordert einen korrespondierenden Loader.

**Path-Resolution fuer Concept-Excerpts:** Concept-Pfade in
Im `StoryContext` bzw. dessen `context.json`-Export koennen Concept-Pfade als nackte Dateinamen gespeichert sein (z.B.
`02-komponentenstruktur.md` statt
`_concept/technical-design/02-komponentenstruktur.md`). Der Builder
muss eine Fallback-Suche in bekannten Concept-Verzeichnissen
(`_concept/domain-design/`, `_concept/technical-design/` etc.)
durchfuehren, wenn der direkte Pfad nicht existiert. Ohne diese
Fallback-Logik werden vorhandene Concept-Dokumente faelschlich als
fehlend gemeldet.

**Kanonische Feldnamen:** Der Builder MUSS die Feldnamen aus der
zentralen Story-Sections-Definition (`story_sections.py`)
verwenden. Diese ist die Single Source of Truth fuer
Bundle-Feldnamen. Eigene Key-Suchen (z.B. `arch_references` statt
`concept_paths`) fuehren zu Naming-Mismatches, bei denen vorhandene
Daten nicht gefunden werden. Was die Setup-Phase unter einem
bestimmten Feldnamen speichert, muss die nachgelagerte Pipeline
unter exakt demselben Namen konsumieren.

**Sufficiency-Klassifikation — Trunkierung vs. fehlende Daten:**
Trunkierung allein (Daten vorhanden, aber auf Token-Limit gekuerzt)
rechtfertigt `REVIEWABLE_WITH_GAPS`, nicht `PARTIALLY_REVIEWABLE`.
Nur fehlende Pflichtfelder (z.B. `story_spec`, `diff_summary`)
rechtfertigen die niedrigere Stufe `PARTIALLY_REVIEWABLE`. Die
Unterscheidung ist wesentlich: Trunkierte Daten ermoeglichen ein
eingeschraenktes, aber informiertes Review. Fehlende Pflichtfelder
bedeuten, dass der Reviewer zentrale Informationen nicht hat.

**Policy-Integration:** Die `sufficiency`-Klassifikation ist ein **Audit-Metadatum**, kein Gate-Faktor. Die Policy Engine loggt eine WARNING bei `reviewable_with_gaps` oder `partially_reviewable`, blockiert aber nicht.

> **[Entscheidung 2026-04-08]** Element 28 — Section-aware Bundle-Packing ist Pflicht. FK-34-121 normativ.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 28.

#### 4.5.4.3 Smarteres Bundle-Packing

**Problem:** Die aktuelle "beginning + end"-Trunkierung (evaluator.py `truncate_bundle()`) verwirft die Mitte des Dokuments — genau dort, wo Review-relevante Details oft liegen.

**Verbesserung: Section-/Symbol-aware Kompression**

Statt blindem Mittelschnitt:

1. **Priority-Order pro Evaluator-Rolle:**
   - QA-Review: Akzeptanzkriterien-Abschnitte haben Vorrang vor allgemeinem Kontext
   - Doc-Fidelity: Design-Referenzen haben Vorrang vor Implementation-Details

2. **Section-aware Packing:**
   - Markdown-Überschriften als Segmentierungspunkte
   - Ganze Abschnitte behalten oder weglassen (nie mitten im Satz schneiden)
   - Weggelassene Abschnitte durch einzeilige Platzhalter ersetzen: `[Section "X" omitted — N chars]`

3. **Symbol-aware Extraktion (für Code-Bundles):**
   - Geänderte Funktionen/Klassen vollständig behalten
   - Unveränderte Nachbarn nur mit Signatur, nicht mit Body

**Context Sufficiency Builder und Packing sind ein gemeinsames Arbeitspaket**, nicht sequentiell. Sufficiency-Checks sind nur so gut wie das Packing — wenn stumpf gekürzt wird, beurteilt der Builder die Qualität eines bereits verzerrten Bundles.

## 4.6 Finding-Resolution und Remediation-Haertung

> **Provenienz:** Multi-LLM-Sparring (Claude + ChatGPT + Grok),
> validiert gegen BB2-012 Protokollmaterial
>
> **Leitprinzip:** Reduktion von Wahrheitsquellen statt zusaetzliche
> Governance-Mechanik. Null neue Artefakttypen, null neue Tracking-
> Systeme, aber harte Gate-Wirkung ueber die bestehende Architektur.

### 4.6.1 Problem: Uebersetzungsluecke zwischen Finding und Status

Zwischen Review, Remediation und Closure besteht eine operative
Luecke: Das Trust-Klassen-Modell (§4.2) definiert die Beweiskraft
korrekt (Worker = Trust C, nie blocking), aber in der Praxis setzt
keine andere Instanz den Finding-Resolution-Status. Worker-Artefakte
(`protocol.md`, `handover.json`) wirken als de-facto Statusquelle.

Das Integrity-Gate (03, §3.6) prueft Existenz und Plausibilitaet,
aber nicht die Quelle des Resolution-Status und nicht den
semantischen Aufloesungsgrad einzelner Findings.

Folge: Eine Teilbehebung wird als Vollbehebung fortgeschrieben, wenn
der Worker sie so markiert.

### 4.6.2 Korrektur 1: Layer-2-Finding-Resolution im Remediation-Modus

Wenn eine Story sich in Remediation-Runde 2+ befindet, erhaelt der
Layer-2-StructuredEvaluator (QA-Review, 12+n Checks) die konkreten
Findings der Vorrunde als zusaetzlichen Prompt-Kontext.

**Wichtig:** Die Findings werden direkt aus den Review-Artefakten der
Vorrunde gelesen, NICHT aus Worker-Zusammenfassungen. BB2-012 zeigt,
dass Worker-Zusammenfassungen den offenen Subcase wegkomprimieren.

Der Evaluator bewertet pro Finding:

| Status | Bedeutung |
|--------|-----------|
| `fully_resolved` | Das Finding ist vollstaendig durch Code und Tests abgesichert |
| `partially_resolved` | Ein Teil des Findings ist adressiert, ein anderer Teil bleibt offen |
| `not_resolved` | Das Finding ist nicht adressiert |

Diese Bewertung erfolgt als zusaetzliche Check-IDs im bestehenden
QA-Review-Output — kein neues Artefakt, sondern Erweiterung des
bestehenden Evaluator-Outputs. Die Bewertung hat Trust B
(LLM-basiert), genau wie alle anderen 12+1+1 Layer-2-Checks.

**Gate-Bindung:** Closure blockiert, wenn mindestens ein Finding den
Status `partially_resolved` oder `not_resolved` hat. Kein degradierter
Modus — ein offenes Finding ist ein harter Blocker.

### 4.6.3 Korrektur 2: Mandatory Adversarial Targets

Wenn Layer 2 ein Finding vom Typ `assertion_weakness` mit konkret
testbarem Negativfall identifiziert, wird das Finding als **mandatory
adversarial target** an Layer 3 uebergeben — nicht als loses
"concern" (einzeilige Summary), sondern als strukturiertes Target:

- Finding-ID / Herkunft (z.B. "P3-Review, INV-6")
- Normative Referenz (z.B. "Story-AC INV-6 verlangt aktive Phase")
- Bereits adressierter Teil
- Offener Teil (der konkrete Negativfall)

Der Adversarial Agent muss pro mandatory target entweder:
- einen Test schreiben, der den benannten Negativfall abdeckt, ODER
- explizit `UNRESOLVABLE: Grund` melden

**Gate-Rueckkopplung:** Wenn ein mandatory target nicht erfuellt
(kein Test) und nicht als `UNRESOLVABLE` begruendet wird, schlaegt
das deterministisch auf die Layer-2-Finding-Resolution zurueck: Das
zugehoerige Finding wird mindestens `partially_resolved`. Die
Rueckkopplung nutzt den bestehenden Remediation-Loop (max 3 Runden).

**Abgrenzung:** Mandatory Targets sind **finding-derived** (dynamisch,
pro Story, aus konkreten Review-Findings). Sie sind KEINE
praedefinierten Missionen aus einer statischen Bibliothek (bewusst
abgelehnt, siehe §4.5.5). Der stochastische, explorative Charakter
des Adversarial Testing bleibt fuer alles ausserhalb der mandatory
targets erhalten.

**Empirischer Beleg (BB2-012):** Der Wrong-Phase-Fall ("tool_failed
in Phase B nach nur Phase A") war im P3-Review konkret benannt. Der
Adversarial Agent hat ihn NICHT eigenstaendig gefunden, obwohl er
Dateisystem-Zugriff hatte. Als mandatory target waere der Gegenfall
gezielt adressiert worden.

### 4.6.4 Verworfene Alternativen

| Alternative | Warum abgelehnt |
|-------------|-----------------|
| Separates Resolution-Artefakt (`verify-resolution.json`) | Waere Trust B in separatem Gefaess — dieselbe Beweiskraft wie Layer-2-Check, aber zusaetzliche Infrastruktur |
| Proof-Obligation-Tracking (`open / satisfied / waived`) | Neues Statusobjekt mit eigenem Lifecycle, erhoeht Systemkomplexitaet ohne proportionalen Mehrwert |
| Statische Missionsbibliothek fuer Adversarial | Macht Adversarial vorhersagbar, Worker lernt die Schablonen |
| Context Sufficiency als hartes Gate | Audit-Metadatum ist die richtige Abstraktionsebene (siehe §4.5.4.2) |

### 4.5.5 Explizite Nicht-Entscheidungen

| Was | Warum nicht |
|-----|-------------|
| Reviewer-Kalibrierung vorab | Zerstört produktive Varianz. Die Kombination "skeptischer Auditor + konservativer Reviewer" liefert breitere Suchfläche als zwei identisch kalibrierte Reviewer. |
| Reviewability als Gate in der Policy Engine | Erzeugt Paradox: "Alles PASS, aber ich blockiere weil mir theoretisch Info fehlte." Bleibt Audit-Metadatum. |
| Einheitliches Protokoll für beide Tracks | Track A ist dialogisch und verträgt Multi-Turn. Track B ist maschinengesteuert und fail-closed. Ein Protokoll für beide wäre für mindestens einen Track ein Fremdkörper. |
| Vollständigkeitsversprechen durch DSL | BB2-011 Gemini zeigt: Identisches Material, null Findings. Das Problem war nicht fehlendes Material, sondern fehlende Sensitivität. DSL löst nur "known unknowns". |
| Voller AST-Parser für den Evidence Assembler | Blockiert die Lösung an Parser-Infrastruktur. Deterministischer Kern + leichte Import-Extraktion genügt als erster Schritt. |
| Preflight nur ab Story-Größe M | LLMs schätzen Story-Größen nicht zuverlässig. Größenabhängige Aktivierung wäre auf unzuverlässigem Input gebaut. Immer volles Programm. |
| Numerische Divergenz-Schwelle / Score-Kategorien | Quorum statt Scoring: Verdikt A != Verdikt B → dritter Reviewer, 2 gegen 1 entscheidet. Kein deterministisches Scoring-Modell benötigt. |

### 4.5.6 Umsetzungsreihenfolge

| Schritt | Maßnahme | Begründung |
|---------|-----------|-------------|
| 1 | Evidence Assembler für Track A | Größter Hebel — behebt das Kernproblem worker-kuratierter Bundles. Deterministischer Kern funktioniert ohne Sprachwissen. |
| 2 | Autoritätsmarkierung im Bundle | Ermöglicht epistemische Differenzierung im Prompt. Voraussetzung für sinnvolles DSL. |
| 3 | Request-DSL | Gap-Reduction für bekannte Lücken. Nutzt die bestehende Multi-Turn-Architektur (DialogueRunner, Slot-Kontinuität). |
| 4 | Context Sufficiency Builder + smarteres Packing (Track B, ein Paket) | Deterministisch, kein zusätzlicher LLM-Turn. Sufficiency und Packing zusammen, weil Sufficiency-Checks auf gutem Packing basieren. |
| 5 | Divergenz-Telemetrie + Quorum | Operationalisiert Bewertungsasymmetrie. Verdikt A != Verdikt B → dritter Reviewer (Quorum). QA-Agent steuert eigenständig. |

### 4.5.7 Empirische Basis

#### BB2-011: Token Counting + Provider Config + Error Taxonomy

- **P1 ChatGPT:** REWORK — 4 BLOCKINGs (fehlender Feature-Flag-Whitelist-Check, deprecated-Field-Testproblem, Mock-Grenzfall, Retry-Semantik-Ambiguität)
- **P1 Gemini:** PASS — 0 Findings
- **Synthese:** Beide konvergieren auf MERGE-READY. ChatGPTs P1-Befund (Whitelist) wurde implementiert.
- **Lektion 1:** Worker hat schemas.py, protocols.py, provider_adapter.py, model_registry.yaml nicht mitgeliefert. Environment-Kontext systematisch unterkuratiert.
- **Lektion 2:** Divergenz war nicht nur Kontext-Problem — Gemini hat vorhandene Information nicht scharf genug ausgewertet. Kalibrierung allein löst das nicht.

#### BB2-010: LLM Provider Adapter + Model Normalizer

- **P1-P4:** Specialized Review Pipeline (4 Passes x 2 LLMs)
- **P4 Synthesis:** 5 BLOCKINGs, 3 IMPORTANTs, 1 NOTE mit 4 Causal Chains
- **Mediation:** 4 Divergenzen sauber aufgelöst (FIX: Loader-API einheitlich machen; OUT OF SCOPE: Fallback-Runtime ist BB2-041; DOCUMENT: Normalizer-Vertrag präzisieren; DEFER: ABC-Erweiterung für BB2-040)
- **Lektion 3:** Mediation funktioniert als Kompensation für Divergenz. Der Mechanismus ist wirksam.
- **Lektion 4:** Cross-Pass-Kausalitätsketten (P1+P2+P3 → "structured-output branch blind spot") sind der größte Qualitätsgewinn der Multi-Pass-Architektur.

### 4.5.8 Abhängigkeiten und Voraussetzungen

| Voraussetzung | Status | Für |
|---------------|--------|------|
| StoryContext / `context.json`-Export mit `concept_paths`, `guardrail_paths` | Vorhanden | Evidence Assembler Stufe 1 |
| Git-Diff-Zugriff aus dem Worker-Kontext | Vorhanden | Evidence Assembler Stufe 1 |
| Import-Extraktion Python/TS/Java | Neu zu bauen | Evidence Assembler Stufe 2 |
| ContextBundle-Erweiterung (Autoritätsklassen) | Neu zu bauen | Autoritätsmarkierung |
| Review-Prompt-Templates Anpassung | Bestehende Templates erweitern | Autoritätsmarkierung |
| Preflight-Prompt-Template (neu) | Neu zu erstellen | Request-DSL |
| ContextBundle Sufficiency-Prüfung | Neu zu bauen | Context Sufficiency Builder |
| Section-aware Truncation | Ersetzt truncate_bundle() | Smarteres Packing |
| Divergenz-Prüfung + Quorum-Anweisung im QA-Prompt | check_divergence() + Worker-Template-Erweiterung | Divergenz-Telemetrie |
| mediation-round.md Template | Bereits vorhanden | Auto-Mediation |

### 4.5.9 Geklärte Fragen

Alle ursprünglich offenen Fragen wurden geklärt:

| # | Frage | Entscheidung | Methode |
|---|-------|-------------|---------|
| F1 | Sprachspezifische Extraktion TS/Java | Detailliertes Pattern-Set für TS (6 Klassen + Alias + Barrel) und Java (Imports + Package-Index + Spring-Heuristiken). Siehe Sektion 4.5.3.1 Stufe 2. | Sparring mit ChatGPT |
| F2 | Bundle-Größen-Grenzen | 350 KB unkomprimiert. Priorisierung nach Autoritätsklasse bei Überschreitung. Siehe Sektion 4.5.3.1. | Nutzer-Entscheidung |
| F3 | Preflight-Kosten für kleine Stories | Immer volles Programm, keine Story-Größen-Abhängigkeit. LLMs schätzen Story-Größen nicht zuverlässig. | Nutzer-Entscheidung |
| F4 | Divergenz-Mechanismus | Quorum statt Scoring. Verdikt A != Verdikt B → dritter Reviewer (Tiebreaker), 2 gegen 1 gewinnt. QA-Agent steuert eigenständig. Kein deterministisches Score-Modell. | Nutzer-Entscheidung |
| F5 | Rückwirkung auf Worker-Templates | Template-Update der Worker-Prompts (worker-implementation.md, worker-bugfix.md). Kein konzeptuelles Problem, reine Umsetzungsaufgabe. | Nutzer-Entscheidung |
