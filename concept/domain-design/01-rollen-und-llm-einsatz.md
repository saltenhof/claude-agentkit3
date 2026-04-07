---
concept_id: DK-01
title: Spezialisierte Rollen und LLM-Einsatz
module: roles-and-llm
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: roles-and-llm
defers_to: []
supersedes: []
superseded_by:
tags: [roles, llm-selection, context-management, multi-llm, orchestrator]
---

# 01 — Spezialisierte Rollen und LLM-Einsatz

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 4
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Die systemische Qualität entsteht nicht aus einem einzelnen Agenten, der
alles richtig macht, sondern aus dem Zusammenspiel spezialisierter Rollen
mit unterschiedlichen Zielen. Ein Worker-Agent mit dem Auftrag "bringe
dieses Story-Ziel zum Fliegen" entwickelt eine fundamental andere Dynamik
als ein QA-Agent mit dem Auftrag "entdecke jede Abweichung und verhindere
sie". Allein dieses unterschiedliche Framing erzeugt ein Korrektiv, das
ein einzelner Agent mit beiden Aufgaben nicht leisten kann.

Das Prinzip skaliert über Story-Umsetzung hinaus: dedizierte Agents
prüfen die Einhaltung von Governance-Prozessen unabhängig von einzelnen
Stories. Andere bewerten die fachliche Vollständigkeit von Anforderungen
und Konzepten aus Stakeholder-Sicht. Die Ziele dieser Rollen sind nicht
zwingend gegenläufig, aber orthogonal. Sie beleuchten dieselbe Codebasis
aus Perspektiven, die sich gegenseitig kompensieren.

### 1.1 Nicht jede Rolle ist ein Agent

Ein zentrales Designprinzip: Nicht jeder LLM-Einsatz erfordert einen
Agent mit Dateisystem-Zugriff. AgentKit unterscheidet zwei Arten, wie
LLMs eingesetzt werden:

**LLM als Agent:** Autonomer Agent mit Dateisystem-Zugriff, der Code
lesen, schreiben und ausführen kann. Nur dort, wo aktive Artefakt-
Erzeugung nötig ist (Worker implementiert, Adversarial Agent schreibt
Tests).

**LLM als Bewertungsfunktion:** Deterministisches Python-Skript ruft
ein LLM über API oder Browser-Pool auf, liefert strukturierten Input
und fordert ein definiertes JSON-Response-Schema ein. Kein
Dateisystem-Zugriff, kein autonomes Handeln. Minimale Felder: Status
(PASS, PASS_WITH_CONCERNS, FAIL), Kurzgrund, Description. Das LLM
bewertet, die Pipeline entscheidet.

Diese Unterscheidung hält die Kosten niedrig (Browser-Pool-Aufrufe
sind kostenlos), die Ergebnisse maschinenlesbar und den Prozess
deterministisch steuerbar.

#### LLM-Role-Routing und Spawn-Contract

Die Zuordnung, welches LLM welche Rolle übernimmt, ist in der
Pipeline-Konfiguration als `llm_roles`-Mapping definiert (Rolle →
Pool). Die Laufzeit-Auflösung erfolgt über eine feste Kette:

1. Rolle bestimmen (z.B. `qa_review`, `semantic_review`)
2. Pool-Name aus `llm_roles` in `.story-pipeline.yaml` lesen
   (z.B. `chatgpt`, `gemini`)
3. MCP-Tool-Prefix ableiten (`chatgpt_acquire`, `chatgpt_send`, ...)
4. Acquire/Send/Release über den MCP-Pool ausführen
5. Telemetrie-Event schreiben (`llm_call` mit `pool` und `role`)

**Architektonische Grenzregel (Spawn-Contract):** Die Unterscheidung
zwischen Agent und Bewertungsfunktion bestimmt, wie eine Rolle
technisch realisiert wird:

- **Rollen ohne Dateisystem-Zugriff** (QA-Bewertung, Semantic Review,
  Dokumententreue, Governance-Adjudication, Design-Review,
  Design-Challenge): Das konfigurierte LLM wird direkt über den
  MCP-Pool aufgerufen (`LlmEvaluator.evaluate()`). Die Steuerung
  ist deterministisch — ein Python-Skript liefert strukturierten
  Input und fordert ein definiertes JSON-Response-Schema ein. Kein
  Agent-Spawn nötig.

- **Rollen mit Dateisystem-Zugriff** (Worker, Adversarial Agent):
  Ein Claude-Agent wird gespawnt, der autonom mit der Codebase
  arbeiten kann.

Ein Claude-Agent als Proxy für eine Bewertungsfunktion ist
architektonisch falsch. Wenn eine Rolle nur Text bewerten soll —
ohne Dateien zu lesen, zu schreiben oder auszuführen — dann muss
die Bewertung deterministisch gesteuert werden, nicht durch einen
autonomen Agent. Der Agent wäre unnötige Indirektion: höhere Kosten,
geringere Steuerbarkeit, kein Nutzen.

### 1.2 Rollentrennung durch Zugriffsrechte

Die Rollentrennung wird nicht nur durch unterschiedliche Aufträge
erreicht, sondern auch durch unterschiedliche Zugriffsrechte. Jede Rolle
hat ein definiertes Set an erlaubten Tools und Operationen. Ein
Orchestrator darf Agents starten und Ergebnisse lesen, aber keinen Code
schreiben. Ein QA-Agent darf Code lesen und Tests ausführen, aber keine
Quelldateien editieren, damit er Fehler findet statt sie stillschweigend
zu korrigieren. Ein Worker darf implementieren, aber keine QA-Artefakte
überschreiben. Diese Einschränkungen verhindern, dass ein Agent aus
seiner Rolle ausbricht, auch wenn sein Auftrag das nahelegen würde.

### 1.3 Multi-LLM als Pflicht

Der gezielte Einsatz unterschiedlicher LLMs pro Rolle ist nicht
optional, sondern konfigurierte Pflicht. Systematische Schwächen einer
Modellfamilie (Bestätigungstendenz, Overconfidence, blinde Flecken)
werden durch eine andere Modellfamilie in einer anderen Rolle
adressiert. Welche LLMs für welche Rollen eingesetzt werden, ist in
der Pipeline-Konfiguration festgelegt, nicht dem Agent überlassen.

### 1.4 Kontext-Selektion

Agenten erhalten nicht den gesamten verfügbaren Kontext, sondern nur
den für ihre aktuelle Aufgabe relevanten. Story-Metadaten (betroffene
Module, Story-Typ, Tech-Stack) selektieren automatisch die passenden
Regel- und Wissensabschnitte aus getaggten Sektionen der
Projektdokumentation. Irrelevante Abschnitte werden gar nicht erst
in den Prompt injiziert.

### 1.5 Schlanker Orchestrator

Der Orchestrator-Agent erhält bewusst minimalen Kontext. Seine Aufgabe
ist Steuerung: Ist ein Schritt erfolgreich abgeschlossen? Was ist der
nächste Schritt? Die Pipeline kommuniziert mit ihm ausschließlich über
kontrollrelevante Steuerungsinformationen — Outcome einer Phase,
Fehlerklasse, ob ein Retry sinnvoll ist, welche Phase als nächste
startet — nicht über Inhaltsdaten.

Steuerungsinformationen umfassen: Phasenergebnis (PASS / FAIL /
ESCALATE / BLOCKED), Fehlerklasse (z.B. fehlende Precondition,
Policy-Verletzung, Infrastrukturfehler), Retry-Fähigkeit und
Phasenübergang. Sie sind strukturiert, knapp und schema-gebunden.
Was sie nicht enthalten: Story-Kontext, Anforderungsdetails,
Code-Diffs, Analyseinhalte — also alles, was nur für die ausführenden
Agenten relevant ist.

Diese Steuerungsinformationen bekommt der Orchestrator ausschließlich
aus dem **Phasen-Steuerungsartefakt** — einer durch AgentKit
bereitgestellten, reduzierten Steuerungsprojektion des Laufzustands.
Er liest keine Rohkontextdateien und keine ungefilterten
Tool- oder Agent-Ausgaben.

Diese Einschränkung ist kein Mangel, sondern ein Stabilitätsmerkmal:
Ein Orchestrator, der große Inhaltsmassen in seinem Kontextfenster
akkumuliert, verliert über lange Laufzeiten — mehrere Stories,
Eskalationsschleifen, Rework-Zyklen — zunehmend seine
Steuerungsorientierung. Kontextkompression und -verlust treffen
Steuerungslogik härter als Detailwissen. Der schlanke Orchestrator
bleibt auch nach vielen Iterationen in seiner Rolle.

Das Prinzip wird durch den Orchestrator-Guard (Abschnitt 3.2 in [03-governance-und-guards.md](03-governance-und-guards.md)) als
technisch erzwungene Invariante durchgesetzt: Der Orchestrator-Agent
hat keinen Lesezugriff auf Inhaltsartefakte der Content-Plane. Er
kann das Prinzip nicht aus Hilfsbereitschaft umgehen, weil der
Zugriff auf Plattformebene blockiert wird.
