---
concept_id: DK-03
title: Fail-Closed Governance
module: governance
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: governance
defers_to: []
supersedes: []
superseded_by:
tags: [governance, guards, fail-closed, integrity-gate, document-fidelity]
---

# 03 — Fail-Closed Governance

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 6
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Das Grundprinzip ist: Jede Unklarheit ist ein Fehler. Fehlende Artefakte,
ungültige Formate, unbekannte Zustände, nicht erreichbare Systeme: alles,
was nicht explizit PASS ist, ist FAIL. Kein Guard scheitert still. Kein
fehlender Prüfgegenstand wird als "nicht relevant" gewertet.

Alle Guards nutzen dasselbe Funktionsprinzip: Die Agent-Plattform
(Claude Code) bietet eine Hook-Schicht, die jede Aktion eines Agenten
abfängt, bevor sie ausgeführt wird. AgentKit klinkt sich in diese
Schicht ein. Damit ist die Durchsetzung plattformseitig garantiert.
Ein Agent kann die Hooks nicht umgehen, weil sie Teil der Infrastruktur
sind, in der er operiert, nicht Teil seines eigenen Codes.

Die Governance besteht aus neun Komponenten: vier permanente Guards
(Hook-basiert, während der Story-Bearbeitung aktiv), eine
Dokumententreue-Prüfung (LLM-basiert, vor/nach Implementierung), ein
Integrity-Gate (vor Closure), eine Governance-Beobachtung
(kontinuierlich, Anomalie-Erkennung), ein Worker-Health-Monitor
(Stagnation und Loop-Erkennung während der Implementation) und das
Phase-Transition-Enforcement (Laufzeit-Erzwingung des
Phasenübergangsgraphen).

### 3.1 Branch-Guard

**Verantwortung:** Erzwingt, dass alle Änderungen einer Story isoliert
auf einem eigenen Branch stattfinden. Das dient zwei Zwecken: Erstens
verhindert es, dass ein Agent die Git-Historie beschädigt oder seinen
zugewiesenen Scope verlässt. Zweitens schafft es die Grundlage für die
Qualitätssicherung, denn der Branch macht alle Modifikationen einer
Story unabhängig von sonstigen Änderungen an der Codebase sichtbar.
Die QA-Agents können dadurch gezielt prüfen, was geändert wurde, was
dadurch möglicherweise gebrochen wurde und was explizit abgesichert
werden muss.

**Wann aktiv:** Sobald ein Agent in einem Story-Worktree arbeitet.

**Auslöser:** Jeder Git-Befehl, den ein Agent ausführt.

**Was geprüft wird:**

| Aktion | Bewertung |
|--------|-----------|
| Commit, Push auf Story-Branch | Erlaubt |
| Checkout/Switch auf Main oder Master | Blockiert |
| Push auf Main oder Master | Blockiert |
| Force-Push (auf jeden Branch) | Blockiert |
| Rebase auf Main oder Master | Blockiert |
| Hard-Reset | Blockiert |
| Branch löschen (force) | Blockiert |

**Ergebnis bei Blockade:** Der Befehl wird nicht ausgeführt. Der Agent
erhält keine Details darüber, warum er blockiert wurde (opake
Fehlermeldung), damit er nicht lernt, den Guard gezielt zu umgehen.

### 3.2 Orchestrator-Guard

**Verantwortung:** Schützt den Orchestrator-Agenten vor zwei Arten
von Kontext-Verschmutzung: Zugriff auf die Codebase des Zielsystems
und Zugriff auf Story-Kontext-Datendateien. Beide Zugriffsmuster
führen zum selben Ergebnis — der Orchestrator akkumuliert inhaltliche
Details, die er für seine Steuerungsaufgabe nicht braucht, und
driftet erfahrungsgemäß in Aufgaben ab, die nicht seine sind
(Scope-Drift aus Hilfsbereitschaft, siehe [00-uebersicht.md](00-uebersicht.md) Abschnitt 3 und [01-rollen-und-llm-einsatz.md](01-rollen-und-llm-einsatz.md) Abschnitt 1.5).

Der Guard blockiert nicht pauschal alle Lese- und Schreiboperationen.
Der Orchestrator muss Protokolle schreiben, Statussignale lesen und
die Completion-Outputs seiner Sub-Agents auswerten können. Blockiert
werden gezielt zwei Schutzzonen:

**Schutzzone 1 — Codebase des Zielsystems:**
Der Bereich, in dem der Quellcode des Zielsystems liegt. Liest der
Orchestrator Quellcode, beginnt er typischerweise selbst zu
implementieren, statt zu delegieren.

**Schutzzone 2 — Inhaltsartefakte der Content-Plane:**
Alle Artefakte, die fachliche Story-Inhalte tragen: ARE-Bundle,
Story-Kontext, Code-Diff-Details, Analyseinhalte, Anforderungslisten
und gleichwertige Inhaltsdaten, unabhängig von Dateiname oder
Speicherort. Die Grenze verläuft nicht entlang von Dateinamen,
sondern entlang von Artefaktklassen: **Control-Plane-Artefakte**
(Phasenergebnis, Fehlerklasse, Steuerungszustand) sind erlaubt;
**Content-Plane-Artefakte** (Story-Inhalt, Anforderungen, Analysedaten)
sind blockiert.

Der Orchestrator kommuniziert mit der Pipeline ausschließlich über
das Phasen-Steuerungsartefakt ([01-rollen-und-llm-einsatz.md](01-rollen-und-llm-einsatz.md) Abschnitt 1.5) — eine durch AgentKit
bereitgestellte, strukturierte Steuerungsprojektion. Direkter Zugriff
auf Rohkontextdaten ist nicht zulässig.

Diese zweite Schutzzone stellt das Prinzip des schlanken Orchestrators
([01-rollen-und-llm-einsatz.md](01-rollen-und-llm-einsatz.md) Abschnitt 1.5) als technisch erzwungene Invariante sicher, nicht nur
als Konvention.

**Wann aktiv:** Während der gesamten Story-Bearbeitung, aktiviert beim
Setup, deaktiviert bei der Closure.

**Auslöser:** Jede Datei-Operation des Orchestrators, die auf eine
der beiden Schutzzonen zielt.

**Was geprüft wird:**

| Artefaktklasse | Bewertung |
|----------------|-----------|
| Prompts, Templates, Skills, Dokumentation | Erlaubt |
| Phasen-Steuerungsartefakt (reduzierte Steuerungsprojektion) | Erlaubt |
| AgentKit-eigene Dateien, Konzepte | Erlaubt |
| Kontrollbezogene Protokolle und Audit-Logs (ohne Story-/Analyseinhalt) | Erlaubt |
| Codebase des Zielsystems (Control-Plane: Quellcode, Build, Konfiguration) | Blockiert |
| Inhaltsartefakte der Content-Plane (Story-Kontext, ARE-Bundle, Analysedaten) | Blockiert |

**Risikohinweis — Sub-Agent-Outputs:**
Completion-Outputs von Sub-Agents, die der Orchestrator auswertet,
sind ein potenzieller Rückkanal für Inhaltsmassen. Ein Worker, der
seinen Output mit Analysedetails, vollständigen Anforderungslisten
oder Code-Inhalten befüllt, kann die Schutzzone faktisch umgehen.
Diesem Risiko wird durch Output-Disziplin der Agenten begegnet:
Orchestrator-lesbare Outputs sollen knapp und steuerungsorientiert
sein. Die technische Absicherung durch ein formales Output-Schema
ist Gegenstand der Feinkonzepte.

**Ergebnis bei Blockade:** Der Zugriff wird verweigert. Der Orchestrator
muss die Aufgabe an einen Worker-Agent delegieren, statt sie selbst zu
übernehmen.

### 3.3 QA-Artefakt-Schutz

**Verantwortung:** Stellt sicher, dass QA-Ergebnisse nur von den dafür
vorgesehenen Prozessschritten geschrieben werden, nicht vom
implementierenden Agent. Ein Worker, der seine eigenen QA-Ergebnisse
überschreibt, könnte sich selbst ein PASS ausstellen.

**Wann aktiv:** Permanent während der Story-Bearbeitung.

**Auslöser:** Jede Schreiboperation auf Dateien im QA-Verzeichnis.

**Geschützte Artefakte:** Structural-Check-Ergebnisse, Policy-Decisions,
Semantic-Review-Berichte, Closure-Artefakte.

**Ergebnis bei Blockade:** Die Schreiboperation wird verweigert mit einer
opaken Fehlermeldung. Der Verstoß wird in einem Audit-Log protokolliert.

### 3.4 Prompt-Integrity-Guard

**Verantwortung:** Kontrolliert jeden Agent-Spawn (Sub-Agent-Erzeugung)
auf Governance-Konformität. Ohne diesen Guard könnte ein Agent
Sub-Agents mit beliebigen Prompts starten, die Skill-Pipeline umgehen,
Governance-Override-Anweisungen injizieren oder Worker-Templates
manipulieren.

**Wann aktiv:** Permanent. Greift bei jedem Versuch, einen Sub-Agent
zu erzeugen.

**Auslöser:** Jede Agent-Spawn-Operation.

**Was geprüft wird (drei Stufen):**

| Stufe | Prüfgegenstand | Ergebnis bei Verstoß |
|-------|----------------|---------------------|
| Governance-Escape-Erkennung | Prompt wird auf adversariale Muster geprüft (z.B. "ignoriere alle vorherigen Anweisungen", "umgehe Governance"). Regex-basiert, kein LLM. | Sofortige Blockade mit opaker Fehlermeldung |
| Spawn-Schema-Validierung | Jeder Sub-Agent muss einen strukturierten Header tragen: Modus, Rolle, Story-ID und Skill-Nachweis. Im Story-Ausführungsmodus muss der Nachweis einem gültigen Token aus dem installierten Manifest entsprechen und auf einen autorisierten Prompt verweisen. | Blockade |
| Template-Integritätsprüfung | Im Story-Ausführungsmodus wird der tatsächliche Prompt-Text gegen das installierte statische Template abgeglichen (whitespace-normalisiert). Nur Worker-Agents unterliegen dieser Prüfung, QA-Agents sind ausgenommen (sie arbeiten mit dynamisch zusammengesetzten Prompts). | Blockade |

**Designprinzipien:**

- **Opake Fehlermeldungen:** Der blockierte Agent erfährt keine
  Details über den Grund der Blockade. Das verhindert, dass ein Agent
  lernt, den Guard gezielt zu umgehen.
- **Kein Diagnostic-Leak:** Bei Template-Abweichungen werden keine
  Diff-Details an den Agent zurückgegeben, damit die Template-Struktur
  nicht preisgegeben wird.
- **Kein menschlicher Eingriff zur Laufzeit:** Der Guard arbeitet
  vollständig automatisiert. Die Konfiguration erfolgt bei der
  Installation über das Manifest.

### 3.5 Dokumententreue-Prüfung

Dokumententreue ist keine einzelne Prüfung, sondern eine gestufte Kette.
Was geprüft werden kann, hängt davon ab, welcher Gegenstand zu welchem
Zeitpunkt überhaupt existiert. Anders als die übrigen Guards ist die
Dokumententreue-Prüfung nicht deterministisch, sondern LLM-basiert:
Sie erfordert einen semantischen Abgleich, den nur ein Sprachmodell
leisten kann.

**Geltungsbereich:** Die Dokumententreue-Prüfung betrifft nur
Story-Typen, die eine Implementierung produzieren (Implementation,
Bugfix). Konzept- und Research-Stories erzeugen Dokumente, keinen
Code. Für sie gibt es weder eine Entwurfstreue-Prüfung noch einen
Execution/Exploration-Modus noch einen Impact-Violation-Check. Das ist
ein Grundprinzip: Nicht jeder Guard wird auf jede Story-Art
angewendet. Welche Guards für welchen Story-Typ gelten, ergibt sich
aus der Natur des Artefakts, das die Story produziert.

#### Execution Mode vs. Exploration Mode

Nicht jede Story mit Implementierung braucht denselben Ablauf. Eine
Story, die ein detailliertes Architekturkonzept mitbringt, kann direkt
implementiert
werden. Eine Story, die nur ein funktionales Ziel beschreibt ("Integriere
Broker-API X"), hat zum Zeitpunkt der Freigabe noch keinen Lösungsrahmen.
Architekturentscheidungen entstehen erst während der Bearbeitung. Ohne
prüfbaren Entwurf kann keine sinnvolle Dokumententreue-Prüfung
stattfinden.

AgentKit unterscheidet deshalb zwei Umsetzungsmodi:

**Execution Mode:** Die Story bringt ein belastbares Konzept mit. Der
Worker implementiert direkt. Die Dokumententreue wird als
Conformance-Check nach der Implementierung geprüft (hat der Worker
gebaut, was konzeptionell freigegeben wurde?).

**Exploration Mode:** Die Story hat keinen belastbaren Lösungsrahmen
oder ist architekturwirksam. Der Worker durchläuft zuerst eine
leichtgewichtige Konzeptionsphase, die ein standardisiertes
Entwurfsartefakt produziert. Dieses Artefakt wird gegen bestehende
Architektur- und Strategiedokumente geprüft. Erst nach bestandener
Prüfung beginnt die eigentliche Implementierung.

#### Kriterienkatalog für die Modusermittlung

Die Entscheidung zwischen Execution und Exploration ist keine
LLM-Tagesentscheidung, sondern erfolgt deterministisch anhand von
sechs Kriterien, die als strukturierte Felder am GitHub-Issue hängen.
Fehlende Felder werden fail-closed behandelt: Ein fehlendes Feld zählt
immer zugunsten von Exploration.

Die Modus-Ermittlung gilt nur für implementierende Story-Typen
(Implementation, Bugfix). Konzept- und Research-Stories
durchlaufen einen eigenen, dokumentenorientierten Ablauf ohne
Exploration/Execution-Unterscheidung.

| Kriterium | Feld-Typ | Execution | Exploration |
|-----------|----------|-----------|-------------|
| Story-Typ | Enum | Bugfix, Implementation | (kein Story-Typ erzwingt allein Exploration) |
| `concept_paths` (aus Issue-Body) | Pfadliste | Mindestens ein gültiger Pfad (nur bei Implementation execution-sperrend; bei Bugfix nicht, s. FK 22.8.1) | Leere Liste oder keine gültige Referenz |
| Reifegrad | Enum | "Solution Approach" oder "Architecture Concept" | "Goal Only" oder leer |
| Change-Impact | Enum | Local, Component | Cross-Component, Architecture Impact |
| Neue Strukturen (APIs, Datenmodelle) | Boolean | false | true |
| Externe Integrationen | Boolean | false | true |

**Entscheidungsregel (Whitelist, fail-closed):** Eine Story geht nur
dann in den Execution Mode, wenn alle sechs Kriterien in der
Execution-Spalte stehen. Steht auch nur ein Kriterium in der
Exploration-Spalte, geht die Story in den Exploration Mode. Der Default
ist Exploration.

Zusätzlich erzwingt ein erkannter Konflikt aus dem VektorDB-Abgleich
bei der Story-Erstellung ([02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md) Abschnitt 2.1) den Exploration Mode, auch wenn
alle sechs Kriterien auf Execution stehen.

#### Vier Ebenen der Dokumententreue

| Ebene | Zeitpunkt | Was geprüft wird | Input |
|-------|-----------|------------------|-------|
| Zieltreue | Story-Erstellung | Passt die Absicht zur Strategie? Kollidiert das Vorhaben mit bestehenden Leitplanken? | Story-Beschreibung, Strategie-/Architekturdokumente |
| Entwurfstreue | Nach Konzeptionsphase, vor Implementierung (nur Exploration Mode) | Ist der geplante Lösungsweg mit Architektur und Konzepten vereinbar? | Entwurfsartefakt des Workers, Referenzdokumente |
| Umsetzungstreue | Nach Implementierung, in der Verify-Phase | Hat der Worker gebaut, was konzeptionell vorgesehen war? Gibt es undokumentierten Drift? | Code-Diff, freigegebener Entwurf oder Konzept, Referenzdokumente |
| Rückkopplungstreue | Bei Closure | Müssen bestehende Dokumente aktualisiert werden, damit künftige Prüfungen gegen eine korrekte Wahrheit laufen? | Finaler Change, bestehende Dokumentation |

Die Zieltreue-Prüfung findet bereits während der Story-Erstellung statt
([02-pipeline-orchestrierung.md](02-pipeline-orchestrierung.md) Abschnitt 2.1). Die Entwurfstreue-Prüfung findet nur im Exploration Mode
statt und ist das Gate zwischen Konzeption und Implementierung. Die
Umsetzungstreue-Prüfung findet bei allen Stories statt und ist Teil der
Verify-Phase. Die Rückkopplungstreue-Prüfung bei Closure stellt sicher,
dass die Dokumentation nicht veraltet, denn eine veraltete Dokumentation
macht alle zukünftigen Prüfungen unzuverlässig.

#### Impact-Violation-Check

Die Kriterien am Issue deklarieren den erwarteten Impact (lokal,
komponentenübergreifend, architekturwirksam). In der Verify-Phase
prüft ein zusätzlicher Structural Check, ob die tatsächliche
Implementierung den deklarierten Impact überschritten hat. Wenn ein
Bugfix mit deklariertem Impact "Local" tatsächlich Datenmodelle ändert
oder neue Schnittstellen einführt, wird das als Verletzung gewertet.
War die Story im Exploration Mode (es gab einen freigegebenen
Entwurf), wird an den Menschen eskaliert. Es gibt keinen automatischen
Rücksprung in die Exploration-Phase; die Entscheidung über ein neues
Explorationsmandat trifft der Mensch bewusst. War die Story im
Execution Mode, wird ebenfalls an den Menschen eskaliert, weil die
Issue-Metadaten falsch deklariert waren.

#### Ein Worker darf ein Konzept nicht stillschweigend überschreiben

Wenn ein Worker im Execution Mode von einem mitgelieferten Konzept
abweichen will oder muss, muss er die Abweichung explizit markieren,
eine Begründung liefern und eine erneute Dokumententreue-Prüfung
auslösen. Stillschweigendes Überschreiben eines freigegebenen Konzepts
durch die Implementierung wird durch den Umsetzungstreue-Check in der
Verify-Phase erkannt.

### 3.6 Integrity-Gate

**Verantwortung:** Letzte Verteidigungslinie vor der Story-Closure.
Validiert, dass der definierte Prozess tatsächlich und vollständig
durchlaufen wurde. Nicht der Inhalt der Ergebnisse wird geprüft (das
ist Aufgabe der QA in [04-qualitaetssicherung.md](04-qualitaetssicherung.md)), sondern ob die Ergebnisse existieren,
plausibel sind und von den richtigen Prozessschritten erzeugt wurden.

**Wann aktiv:** Unmittelbar vor der Closure-Phase. Scheitert das Gate,
wird an den Menschen eskaliert, nicht an einen Agenten.

**Was geprüft wird (7 Dimensionen):**

| Dimension | Prüfgegenstand |
|-----------|----------------|
| QA-Verzeichnis | Existiert das QA-Verzeichnis für diese Story? |
| Context-Integrität | Ist der Story-Context vorhanden, konsistent und als PASS bewertet? |
| Structural-Check-Tiefe | Wurden Structural Checks durchgeführt, und zwar in ausreichender Tiefe (nicht nur ein Stub)? Wurden sie vom richtigen Prozessschritt erzeugt? |
| Policy-Decision | Existiert eine Policy-Entscheidung (`decision.json`), ist sie plausibel und wurde sie vom richtigen Prozessschritt erzeugt? **Fehlen ist ein harter Blocker** — `decision.json | MISSING` darf nie zu `Closure | DONE` fuehren. |
| Semantic-Validierung | Wurde bei Implementierungs- und Bugfix-Stories ein Semantic Review durchgeführt (nicht übersprungen)? |
| Verify-Phase | Hat mindestens ein Verify-Durchlauf stattgefunden? |
| Timestamp-Kausalität | Liegen die Zeitstempel der Artefakte in der richtigen Reihenfolge? (Context vor Decision, nicht umgekehrt) |

**Telemetrie-Nachweise:**

Neben den sieben Artefakt-Dimensionen prüft das Integrity-Gate konkrete
Einträge in der Story-Telemetrie. Diese Einträge werden während der
Story-Bearbeitung automatisch durch die Hook-Schicht erfasst und müssen
bei Closure vollständig vorliegen.

| Telemetrie-Nachweis | Was belegt wird | Fehlt wenn |
|---------------------|-----------------|------------|
| `agent_start` Event mit Story-ID | Worker-Agent wurde gestartet | Kein Worker-Agent lief für diese Story |
| `agent_end` Event mit Story-ID | Worker-Agent hat regulär beendet | Agent ist abgestürzt oder wurde abgebrochen |
| Mindestens ein `chatgpt_call` Event | ChatGPT wurde als Review-LLM einbezogen | Kein Multi-LLM-Review stattgefunden (ChatGPT-Seite) |
| Mindestens ein `gemini_call` Event | Gemini wurde als Review-LLM einbezogen | Kein Multi-LLM-Review stattgefunden (Gemini-Seite) |
| `review_compliant` Event mit gültigem Template-Sentinel | LLM-Review erfolgte über ein freigegebenes Review-Template | Agent hat freiformuliert statt über den vorgeschriebenen Review-Skill |
| Kein `integrity_violation` Event | Kein Guard wurde während der Bearbeitung verletzt | Agent hat versucht, geschützte Artefakte zu manipulieren |
| Web-Call-Count innerhalb Budget | Forschungs-/Webzugriffe blieben im definierten Budget | Agent hat exzessiv Web-Calls getätigt |

Multi-LLM ist Pflicht: Neben Claude muss mindestens ein weiteres LLM
konfiguriert sein, idealerweise zwei. Die Telemetrie muss nachweisen,
dass alle konfigurierten Pflicht-Reviewer tatsächlich aufgerufen wurden.
Welche LLMs das sind, ergibt sich aus der Pipeline-Konfiguration.

**Pflicht-Artefakt-Pruefung:**

Vor der Dimensionspruefung validiert das Gate die Existenz aller
Pflicht-Artefakte. Fehlende Pflicht-Artefakte sind ein sofortiger
harter Blocker — die Dimensionspruefung wird gar nicht erst
gestartet.

| Pflicht-Artefakt | Bedeutung bei Fehlen |
|------------------|---------------------|
| `structural.json` | Structural Checks wurden nicht ausgefuehrt |
| `decision.json` | Policy-Evaluation hat nicht stattgefunden |
| `context.json` | Story-Context wurde nicht aufgebaut |

**Empirischer Beleg (BB2-012):** `decision.json` fehlte, trotzdem
lief Closure durch und das Issue wurde geschlossen. Das war ein
konkreter Defekt in der Gate-Logik.

**Ergebnis bei Scheitern:** Die Story kann nicht geschlossen werden. Die
Fehlermeldung ist bewusst opak gehalten und nennt nur einen
Fehlercode, keine detaillierte Erklärung. Das verhindert, dass ein
Agent gezielt die fehlende Dimension nachliefert, um das Gate zu
passieren. Die Details werden in ein Audit-Log geschrieben, das dem
Menschen zugänglich ist.

#### BLOCKED als valider Worker-Exit-Status

BLOCKED ist ein valider Worker-Exit-Status neben COMPLETED. Wenn ein
Worker eine unlösbare Constraint-Kollision erkennt (z.B. Pre-Commit-Hook
blockiert dauerhaft, fehlende Dependency, unauflösbarer Policy-Konflikt),
kann er sauber eskalieren, statt endlos weiterzuversuchen.

BLOCKED wird als korrekte Worker-Leistung behandelt, nicht als
Versagen. Eine professionelle Eskalation einer unlösbaren Situation ist
wertvoller als ein unkontrollierter Endlos-Loop. Der Phase Runner
setzt bei `status: BLOCKED` im worker-manifest den Phase-Status auf
ESCALATED mit `escalation_reason: "worker_blocked"` und übernimmt
die Blocker-Details (`blocking_issue`, `blocking_category`,
`recommended_next_action`) in den Phase-State. Der Orchestrator kann
dann gezielt reagieren — z.B. einen Hook anpassen, eine Ausnahme
konfigurieren oder einen spezialisierten Fix-Worker spawnen.

Empirischer Anlass: Ein Worker lief 8 Stunden in einer Endlosschleife,
weil ein Pre-Commit-Hook (Secret-Detection) seinen Commit dauerhaft
blockierte und er keine Möglichkeit hatte, eine unlösbare Situation
zu melden. Der Worker hatte die fachliche Aufgabe vollständig
abgeschlossen (419 grüne Tests, alle Module implementiert), konnte
aber nicht committen, durfte nicht bypassen und musste regelkonform
endlos versuchen, den "Fehler" zu beheben.

#### Phase-Transition-Enforcement

Der Phasenübergangsgraph (`PHASE_TRANSITION_GRAPH`) wird zur Laufzeit
erzwungen. Jeder `run_phase()`-Aufruf prüft, ob der Übergang von der
vorherigen Phase (aus der persistierten `phase-state.json`) zur
aktuellen Phase im Graphen erlaubt ist. Ungültige Übergänge werden
fail-closed blockiert — die Phase wird nicht betreten, der Status wird
auf ESCALATED gesetzt.

Zusätzlich zum Graphen-Enforcement werden semantische Vorbedingungen
geprüft: Wenn `mode="exploration"` gesetzt ist, muss die
Exploration-Phase mit `exploration_gate_status="approved_for_implementation"`
abgeschlossen sein, bevor die Implementation-Phase starten darf. Die
Closure-Phase erfordert eine abgeschlossene Verify-Phase
(`phase-state-verify.json` mit `status=COMPLETED`).

Dieses Enforcement ist eine zusätzliche Verteidigungslinie
(Defense-in-Depth), die Orchestrator-Fehler sofort abfängt, statt sie
erst in späteren Phasen zu erkennen. Empirischer Anlass: Ein
Orchestrator rief `run_phase("implementation")` auf, ohne vorher die
Exploration-Phase durchzulaufen. Der Fehler wurde erst in der
Verify-Phase erkannt — eine Phase zu spät.

### 3.7 Governance-Beobachtung

Im hochautomatisierten Betrieb (60+ Stories, Mensch schaut nicht
permanent zu) braucht es eine kontinuierliche Beobachtung des
Gesamtprozesses. Diese Beobachtung ist kein eigenständiger Agent,
sondern eine in die bestehende Infrastruktur eingebettete
Governance-Schicht, die aus drei Komponenten besteht.

#### Sensorik: Hooks und Phasen-Skripte

Die Hook-Schicht und die Phasen-Skripte sammeln Signale. Hooks sehen
jede einzelne Aktion in Echtzeit, Phasen-Skripte sehen Fortschritt
und Outcomes über längere Zeiträume. Beide führen nur billige,
deterministische Heuristiken aus, keine LLM-Aufrufe.

**Hook-basierte Anomalie-Signale:**

| Signal | Was erkannt wird |
|--------|-----------------|
| Orchestrator liest/schreibt Code | Rollenverletzung: Orchestrator driftet in die Implementierung |
| Orchestrator führt Bash ohne aktiven Sub-Agent | Orchestrator arbeitet selbst statt zu delegieren |
| Schreiben außerhalb des Story-Scope | Scope-Verletzung: Agent fasst Dinge an, die nicht zur Story gehören |
| Governance-Dateien vom überwachten Prozess verändert | Möglicher Manipulationsversuch an der eigenen Governance |
| Zugriff auf Secrets/Credentials | Sicherheitskritischer Zugriff |

**Skript-basierte Anomalie-Signale:**

| Signal | Was erkannt wird |
|--------|-----------------|
| >= 3 identische QA-Fails in Folge | Retry-Loop ohne Zustandsänderung |
| Story ohne Phasenfortschritt >= 4 Stunden | Stagnation, möglicherweise festgefahren |
| Hoher Edit-Revert-Churn | Agent ändert und verwirft wiederholt dieselben Dateien |
| Sub-Agent scheitert mehrfach ohne verwertbares Artefakt | Non-konvergierende Ausführung |
| Wiederholte Architektur-/Scope-Drifts im selben Run | Systematisches Abweichen vom Konzept |

Die Hooks normalisieren jede Aktion zu einem kompakten Event
(Zeitstempel, Akteur, Story, Phase, Tool-Klasse, Ziel-Pfad,
Risiko-Flags) und akkumulieren einen Risikoscore über Rolling Windows.
Nicht jedes Event wird einzeln bewertet, nur Schwellenüberschreitungen
lösen die nächste Stufe aus.

#### Incident-Kandidat und LLM-Adjudication

Wenn die Sensorik einen Schwellenwert überschreitet, wird ein
Incident-Kandidat erzeugt: eine verdichtete Episode aus mehreren
korrelierten Events mit Evidenz-Referenzen. Nur dieser Kandidat geht
an ein LLM zur Bewertung, nicht der rohe Eventstrom.

Das LLM ist nicht der Wächter, sondern der Richter über vorselektierte
Fälle. Es erhält den Kandidaten mit Kontext und liefert ein
strukturiertes JSON mit: Incident-Typ, Schweregrad, Konfidenz,
Evidenz-Zusammenfassung und empfohlene Maßnahme. Das LLM entscheidet
nicht, es klassifiziert.

#### Deterministische Maßnahmen

Die finale Entscheidung über Maßnahmen ist deterministisch und
regelbasiert, nicht LLM-abhängig:

| Situation | Maßnahme |
|-----------|----------|
| Harter Governance-Verstoß (Secrets, Governance-Manipulation) | Sofortiger Stopp, kein LLM nötig |
| LLM-Klassifikation: kritisch + hohe Konfidenz | Story pausieren, Mensch benachrichtigen |
| LLM-Klassifikation: hoch + unsicher | Incident dokumentieren, erhöhtes Monitoring |
| LLM-Klassifikation: mittel | Incident im Failure Corpus protokollieren |
| LLM-Klassifikation: niedrig | Nur im Governance-Log festhalten |

"Incident ja/nein" und "Prozess stoppen ja/nein" sind zwei
verschiedene Entscheidungen. Ein Incident kann nur dokumentiert werden,
zu erhöhtem Monitoring führen, die Story pausieren oder den gesamten
Prozess stoppen. Die Schwere bestimmt die Reaktion, nicht das LLM.

#### Performance-Schutz

Damit die Governance-Beobachtung den Prozess nicht verlangsamt:

- Hooks führen nur billige Checks durch (Pfad-Match, Counter,
  Phasen-Regel), keine LLM-Aufrufe pro Event
- Events werden normalisiert und in Rolling Windows akkumuliert,
  nicht als Vollhistorie vorgehalten
- LLM-Adjudication nur bei Schwellenüberschreitung, nicht bei jedem
  auffälligen Event
- Deduplizierung und Cooldowns verhindern wiederholte LLM-Aufrufe
  für dasselbe Muster
- Normale, erwartete Aktionen werden nur gezählt, nicht analysiert

### 3.8 Worker-Health-Monitor

**Verantwortung:** Überwacht laufende Worker-Agents auf Stagnation,
Endlosschleifen und Constraint-Konflikte. Interveniert gestuft, bevor
der Worker unkontrolliert Ressourcen verbraucht. Das Monitoring ist
rein extern und persistent — es basiert nicht auf dem Gedächtnis des
Agenten (das durch Context Compaction verloren gehen kann), sondern
auf beobachtbaren Signalen aus der Hook-Schicht.

**Wann aktiv:** Während der gesamten Implementation-Phase, ab
Worker-Spawn bis Worker-Termination.

**Auslöser:** Jeder Tool-Call des Workers. Der PostToolUse-Hook
berechnet nach jedem Tool-Call den Score und persistiert ihn. Der
PreToolUse-Hook liest den Score vor dem nächsten Tool-Call und
entscheidet über Intervention.

**Scoring-Modell (0-100 Punkte):** Ein gewichtetes Scoring-Modell
bewertet den Zustand eines laufenden Workers anhand mehrerer
Heuristiken mit unterschiedlicher Aussagekraft:

| Heuristik | Max Punkte | Stärke | Erkennt |
|-----------|------------|--------|---------|
| Laufzeit vs. Erwartung | 30 | Stark | Überschreitung der nach Story-Typ und Größe normalisierten Laufzeit (P50/P75/P95) |
| Repetitions-Muster | 25 | Stark | Wiederholte grep/edit-Zyklen auf dieselbe Datei ohne Fortschritt (Sliding Window) |
| Hook/Commit-Konflikte | 25 | Sehr stark | Wiederholtes Scheitern an Pre-Commit-Hooks mit identischem Reason |
| Fortschritts-Stagnation | 20 | Stark | Kein Commit, kein Manifest, kein Handover trotz grüner Tests |
| Tool-Call-Anzahl | 10 | Schwach | Überschreitung der Soft/Hard-Limits (nur als Verstärker, nicht eigenständig) |
| LLM-Assessment | -10 bis +10 | Korrekturfaktor | Asynchrone Einschätzung eines externen LLMs zur Loop-Wahrscheinlichkeit |

Der Gesamtscore ergibt sich aus der Summe aller Komponenten. In der
Praxis liegt er zwischen 0 und 100, da nicht alle Heuristiken
gleichzeitig ihr Maximum erreichen. Die Score-Berechnung ist
vollständig deterministisch; das LLM-Assessment ist ein Pflicht-
Korrekturfaktor, der den Score in beide Richtungen verschieben kann.
Deterministische Eingriffe (Hard Stop) bleiben auch ohne LLM-Antwort
möglich (Timeout-Sicherheit), aber der Sidecar wird immer gestartet.

> **[Entscheidung 2026-04-08]** Element 23 — LLM-Assessment-Sidecar ist Pflicht. Kein Feature-Flag. Der Sidecar-Prozess ist keine optionale Erweiterung, sondern integraler Bestandteil der Produktionsarchitektur.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 23.

**Eskalationsleiter:**

| Score | Stufe | Reaktion |
|-------|-------|----------|
| < 50 | Normalbetrieb | Kein Eingriff. Kein LLM-Assessment. |
| 50-69 | Warnung | LLM-Assessment anfordern (asynchron über Sidecar-Prozess). Einmalige Warnung an den Worker. |
| 70-84 | Soft-Intervention | Strukturierte Selbstdiagnose-Aufforderung via PreToolUse-Hook (Tool-Call wird blockiert, Agent erhält Nachricht). Der Worker muss seinen Status deklarieren: PROGRESSING, BLOCKED oder SPARRING_NEEDED. Danach 4-5 Tool-Calls Beobachtung. |
| >= 85 | Hard Stop | Worker wird deterministisch beendet. Finale Nachricht instruiert den Worker, ein worker-manifest mit `status: BLOCKED` zu schreiben. Ein letzter Tool-Call wird zugelassen, danach permanente Blockade. |

Pro Scoring-Fenster gibt es maximal eine Soft-Intervention und einen
Hard Stop. Der Monitor wiederholt keine Interventionen. Wenn nach der
Soft-Intervention der Score weiter steigt, geht es direkt zum Hard
Stop.

**Designprinzip:** Determinismus zuerst — der Hard Stop muss auch
ohne LLM-Antwort möglich sein. Der Sidecar-Prozess wird immer
gestartet und ist kein optionaler Baustein. Wenn der Sidecar ausfällt
oder der MCP-Pool nicht erreichbar ist, funktioniert die
deterministische Score-Berechnung unverändert weiter — der
LLM-Anteil fällt auf 0 zurück. Das LLM-Assessment ist damit kein
Voraussetzung für deterministische Interventionen, aber der Sidecar
selbst ist Pflicht.

**LLM-Assessment-Sidecar:** Der Sidecar-Prozess läuft nicht im Hook
(das würde den Worker blockieren), sondern parallel zum Worker und
pollt kontinuierlich. Der Sidecar startet mit dem Worker-Spawn und
läuft bis zu dessen Terminierung. LLM-Abfragen werden bei Score >= 50
ausgelöst: ein externes LLM (rotierend über konfigurierte Pools) wird befragt,
ob das beobachtete Tool-Call-Muster auf einen Loop hindeutet. Das
Ergebnis fließt als Korrekturfaktor in die nächste Score-Berechnung
ein. Debounce-Regeln verhindern übermäßige LLM-Aufrufe: maximal ein
pending Assessment, Mindestabstand 10 Minuten, neues Assessment nur
bei Score-Anstieg >= 10 Punkte.

**Persistenz:** Der Score, die Einzelkomponenten, das Tool-Call-Log
und der Interventions-Verlauf werden in
`_temp/qa/<STORY-ID>/agent-health.json` persistiert. Damit ist der
Zustand auch über Context-Compaction-Zyklen hinweg verfügbar und für
Post-mortem-Analysen nutzbar.

**Zusammenspiel mit bestehenden Mechanismen:** Der Worker-Health-
Monitor ergänzt die bestehenden Budgets (Web-Call-Budget, Feedback-
Runden-Budget) und den PAUSED-Deadlock-Guard. Das Web-Call-Budget
limitiert externe Zugriffe, der Deadlock-Guard greift nach Worker-
Completion (Evidence-Fingerprint), der Health-Monitor greift
präventiv während der Worker-Laufzeit. Alle drei sind orthogonal.

> **[Entscheidung 2026-04-08]** Element 19 — Evidence-Fingerprint wird verbessert: SHA256-Hash statt Dateigroessen. Trivial, robust.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 19.

### 3.9 Eskalationsklassen und Mandatsgrenzen

AgentKit unterscheidet vier Klassen von Eskalationen. Nicht jede
Eskalation erfordert menschliches Eingreifen — die Klasse bestimmt,
ob der Mensch entscheidet oder der Agent die Auflösung selbst
verantwortet.

| Klasse | Bezeichnung | Auslöser | Wer entscheidet |
|--------|-------------|----------|-----------------|
| 1 | Fachliche Lücke oder Normativ-Konflikt | (a) Fehlende Fachkonzepte, fehlende Domänendaten — das benötigte Wissen existiert nicht im System. (b) Normative Quellen widersprechen sich untereinander und der Widerspruch ist innerhalb des Konzeptrahmens nicht auflösbar — menschliche Präzedenzentscheidung nötig. | Mensch |
| 2 | Technische Feindesign-Entscheidung | Unaufgelöste technische Details innerhalb des normativen Rahmens: Schnittstellensemantik, Schema-Ausprägungen, Scope-Zuordnungen zwischen Stories. Das Wissen liegt in Konzepten, Code und Specs vor. | Agent (Multi-LLM-Beratung) |
| 3 | Scope-Explosion | Der Implementierungsumfang wächst signifikant über den deklarierten Story-Scope hinaus (quantitative Schwellen: Klassen-Count, neue Schnittstellen, Komplexitätsindikatoren). Die Story muss neu geschnitten werden. | Mensch (Story-Split) |
| 4 | Breaking Change außerhalb der deklarierten Tragweite | Die notwendige Änderung überschreitet den deklarierten Wirksamkeitsgrad der Story (Komponente → Architektur, Architektur → Applikation). Bestehende Schnittstellen oder Implementierungen müssen angepasst werden, was über den Story-Scope hinausgeht. | Mensch |

**Mandatsgrenze:** Die zentrale Unterscheidung ist, ob eine
Entscheidung Wissen oder Autorität erfordert, die nicht in den
normativen Quellen (Fach-/IT-Konzepte, Code, Story-Specs) enthalten
ist. Klasse 1 erfordert neues Domänenwissen oder menschliche
Präzedenzentscheidung bei Normativ-Konflikten. Klassen 3 und 4
erfordern Autorität über Story-Scope und Systemgrenzen. Klasse 2
erfordert weder neues Wissen noch neue Autorität — die Antwort liegt
im bestehenden Rahmen und wird durch den Agenten mit Multi-LLM-
Beratung aufgelöst.

**Prüfreihenfolge:** Die Klassifikation erfolgt fail-closed —
restriktivste Klasse zuerst: 1 → 3 → 4 → 2 → methodenlokal.
Damit wird kein Fall zu früh als autonom aufgelöst, der eigentlich
an den Menschen eskaliert werden müsste.

**Zeitpunkt und Routing:** Die Klassifikation erfolgt nicht schon
beim ersten Schreiben des Exploration-Drafts, sondern nach
Design-Review, Prämissen-Challenge und ggf. Design-Challenge auf
Basis konkreter Findings. Das Routing ist dann eindeutig:

- **Klasse 2** bleibt innerhalb des KI-Mandats. Die Exploration
  löst den Punkt selbst im Feindesign-Subprozess mit Multi-LLM-
  Beratung auf.
- **Klasse 1/3/4** pausieren die Pipeline für menschliche
  Entscheidung. Das sind keine endgültigen Abbrüche, sondern
  resumable Klärungspunkte.

**Tragweite als Bezugsrahmen für Klasse 4:** Ob ein Breaking Change
eskaliert werden muss, ist relativ zum deklarierten Wirksamkeitsgrad
der Story (kanonische Enum: `Local`, `Component`, `Cross-Component`,
`Architecture Impact` — DK-02 §Issue-Schema). Eine als
`Architecture Impact` deklarierte Refactoring-Story hat das Mandat
für anwendungsweite Schnittstellenänderungen. Eine als `Component`
deklarierte Story hat dieses Mandat nicht. Der Vergleich zwischen
festgestellter und deklarierter Tragweite ist deterministisch prüfbar.

Referenz: FK-25 (Mandatsgrenzen und Feindesign-Autonomie),
FK-35 §35.4 (Eskalationspunkte).
