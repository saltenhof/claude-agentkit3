---
concept_id: DK-04
title: Mehrstufige Qualitätssicherung
module: quality-assurance
domain: verify-system
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: quality-assurance
defers_to:
  - FK-26
supersedes: []
superseded_by:
tags: [quality-assurance, verify, trust-classes, remediation, adversarial-testing]
formal_scope: prose-only
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

> Review-Qualitätsverbesserung (Track A: Sparring-Reviews mit Vier Säulen — Evidence Assembler, Autoritätsklassen, Request-DSL, Divergenz-Quorum; Track B: Context Sufficiency Builder + Section-aware Packing) ist ausgegliedert nach **DK-11 (Review-Qualitätsverbesserung)**. Die technische Spezifikation der Säulen liegt in FK-28 (Evidence Assembly), FK-46 (Import-Resolver), FK-47 (Request-DSL und Preflight-Turn) und FK-37 (Verify-Context und QA-Bundle).

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

