---
concept_id: DK-07
title: Failure Corpus als Lernschleife
module: failure-corpus
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: domain-failure-corpus
defers_to: []
supersedes: []
superseded_by:
tags: [failure-corpus, incidents, patterns, learning-loop, deterministic-guards]
formal_scope: prose-only
---

# 07 — Failure Corpus als Lernschleife

**Quelle:** Konsolidiert aus agentkit-domain-concept.md Kapitel 10 + failure-corpus-konzept.md
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

## 7.1 Grundprinzip

LLM-basierte Agenten produzieren nicht-deterministische Fehler. Dieselbe
Aufgabe kann beim ersten Mal gelingen und beim zweiten Mal auf eine
völlig andere Weise scheitern. Klassische Regressionstests greifen hier
nicht, weil der Fehler nicht reproduzierbar im Code steckt, sondern im
Verhalten des Agenten.

Der Failure Corpus ist die methodische Antwort darauf: Stochastisches
Agentenfehlverhalten wird in deterministische Pipeline-Guards
überführt. Er ist kein Wissensarchiv über alle Fehler. Er ist ein
Übersetzer. Sein Wert entsteht ausschließlich dann, wenn er drei
Artefakttypen sauber trennt.

### 7.1.1 Drei-Ebenen-Modell

| Ebene | Artefakt | Beschreibung |
|-------|----------|-------------|
| Incident | Einzelbeobachtung | Ein konkreter Fehlerfall mit Kontext, Symptom, Evidenz und Klassifikation |
| Pattern | Wiederkehrendes Muster | Normalisierte Invariante über mehrere Incidents, z.B. "Stories ohne Security-Ziel dürfen keine Permission-Logik ändern" |
| Check | Deterministischer Guard | Regel in der Pipeline, die das Pattern maschinell prüft |

Die Vermischung dieser Ebenen ist das größte Risiko. Nicht aus jedem
Incident wird ein Pattern, nicht aus jedem Pattern wird ein Check.
Das ist gewollt. Sobald man diese drei Ebenen vermischt, wird das
System unsteuerbar.

### 7.1.2 Aufnahmekriterien

Der Corpus nimmt nur Fälle auf, die mindestens eines dieser Kriterien
erfüllen:

- Merge-blockierend oder produktionsrelevant
- Wiederholt aufgetreten (gleicher Fehlertyp, verschiedene Kontexte)
- Teuer in Review, QA oder Nacharbeit (geschätzt >30 Minuten Rework)
- Gut in einen deterministischen Check überführbar

**Nicht aufnehmen:** Einmalige Model-Launen ohne Folgewert. Triviale
Fehler, die bestehende Tests ohnehin fangen. Rein menschliche
Prozessfehler ohne Agentenanteil.

---

## 7.2 Artefakt-Struktur

### 7.2.1 Incident-Record

Ein Incident beschreibt eine konkrete Beobachtung. Die Pflichtfelder
sind so gewählt, dass spätere Musterbildung möglich ist — ohne sie
kann man nicht clustern.

**Identifikation und Kontext:**

- Eindeutige ID (Schema: FC-YYYY-NNNN)
- Zeitstempel der Erstbeobachtung
- Story-/Task-Referenz, Epic-Referenz
- Pipeline-Run-ID, Branch, Commit-SHA
- Zielprojekt-Repository

**Agenten-Kontext:**

- Agentenrolle (Developer, QA, Architect etc.)
- Modell und Modellversion
- Prompt-Profil und Autonomie-Modus
- Phase und Schritt im Pipeline-Ablauf

**Symptom:**

- Erwartetes Verhalten (eine präzise Aussage)
- Tatsächliches Verhalten (eine präzise Aussage)
- Schweregrad (kritisch, hoch, mittel, niedrig)
- Erkennbarkeit (leicht, mittel, schwer)

**Detektion:**

- Wer hat erkannt (QA-Agent, Adversarial Agent, Pipeline-Gate, Mensch)
- Durch welchen Mechanismus (Gate-Rejection, Test-Failure, Review etc.)
- Konfidenz der Erkennung (wenn maschinell)

**Klassifikation:**

- Primäre Fehlerkategorie (aus dem Kategorien-Katalog, siehe Abschnitt 7.4)
- Sekundäre Kategorien (optional, maximal zwei)
- Freie Tags für Suche und Filterung

**Impact:**

- Merge blockiert ja/nein
- Produktion erreicht ja/nein
- Blast Radius (betroffene Module/APIs)
- Geschätzter Rework-Aufwand in Minuten

**Evidenz:**

- Betroffene Dateien (Pfade)
- Diff-Referenz
- Review-Artefakt-Referenz
- Betroffene Tests
- Relevante Log-Ausschnitte

**Normalisierung:**

- Invariant-Kandidat: Die Regel, die hätte gelten müssen
  (z.B. "Stories ohne Security-Ziel dürfen keine Permission-Logik ändern")
- Pattern-Schlüssel: Ein normalisierbarer Schlüssel für Clustering
  (z.B. "scope_drift|security_logic_changed_without_scope")

**Auflösung:**

- Wer hat behoben (Agent, Mensch, beide)
- Fix-Strategie (Revert, Nachbesserung, Neuimplementierung)
- Mensch involviert ja/nein

### 7.2.2 Pattern-Record

Ein Pattern ist kein Einzelereignis, sondern die normalisierte Form
über mehrere Incidents.

**Pflichtfelder:**

- Eindeutige ID (Schema: FP-NNNN)
- Titel und Beschreibung des Musters
- Referenzen auf alle zugeordneten Incidents
- Primäre Fehlerkategorie
- Risikostufe (kritisch, hoch, mittel)
- Betroffene Agentenrollen
- Häufigkeit (Anzahl Vorkommen, Betrachtungszeitraum)

**Normalisierte Invariante:**

- Die Regel als präzise Aussage
  (z.B. "Wenn Story-Scope keine Security-Änderung umfasst, dürfen
  definierte sensitive Pfade nicht verändert werden.")
- Signatur: Konkrete Merkmale, an denen das Pattern erkennbar ist
  (Dateipfad-Muster, Story-Tags, Diff-Charakteristiken)

**Promotion-Begründung:**

- Warum wurde dieses Pattern promoviert? (Wiederholung, Schwere,
  günstige Checkbarkeit — mindestens eines der drei)

**Verknüpfung:**

- Abgeleiteter Check (wenn vorhanden)
- False-Positive-Risiko-Einschätzung
- Owner (Rolle oder Person, die für dieses Pattern verantwortlich ist)

### 7.2.3 Check-Record

Ein Check beschreibt den abgeleiteten deterministischen Guard.

**Pflichtfelder:**

- Eindeutige ID (Schema: CHK-NNNN)
- Titel und Ziel des Checks
- Referenz auf das Quell-Pattern
- Ausführungsstufe in der Pipeline (pre-merge, artifact-gate,
  architecture-gate, qa-gate)
- Check-Typ (siehe Abschnitt 7.6)

**Regel-Definition:**

- Eingabedaten (Story-Metadaten, Changed Files, Diffs, Artefakte etc.)
- Regel als präzise Aussage
- Determinismus: ja (zwingend — kein LLM-Judging)

**Fehlermeldung:**

- Klare, handlungsanweisende Meldung bei Auslösung

**Ausnahmen:**

- Definierte Bedingungen, unter denen der Check nicht gilt
- Override-Mechanismus (wer darf, mit welcher Begründung)

**Validierung:**

- Positive Testfälle (sollen den Check auslösen)
- Negative Testfälle (sollen den Check passieren)
- False-Positive-Rate-Ziel (empfohlen: unter 5%)
- Review-Intervall (empfohlen: 30 Tage nach Aktivierung)

**Owner:**

- Verantwortliche Rolle für Pflege und Sunset

### 7.2.4 Ablagestruktur

Alle drei Artefakttypen werden im Repository versioniert und sind
damit reviewbar, auditierbar und in der Historie nachvollziehbar.

```
failure-corpus/
  taxonomy.yaml              -- Kategorien-Katalog
  incidents/
    2026/
      03/
        FC-2026-0038.yaml
  patterns/
    FP-0012.yaml
  checks/
    CHK-0027.yaml
  fixtures/
    chk-0027/
      should_fail_1/
      should_pass_1/
```

Gesamtgröße pro Incident-Record: unter 10 KB. Keine Binär-Anhänge
im Corpus — externe Artefakte werden per Referenz verlinkt.

---

## 7.3 Erfassung

Die Erfassung ist mehrstufig. Fünf Akteure erfassen Incidents, jeder
mit eigenem Trigger und Schwerpunkt.

### 7.3.1 Erfassungsakteure

| Akteur | Trigger | Schwerpunkt |
|--------|---------|-------------|
| Governance-Beobachtung | Schwellenüberschreitung in Hooks oder Phasen-Skripten, LLM-klassifiziert | Anomalien im Orchestrator- und Agent-Verhalten, Prozessverletzungen |
| Pipeline (automatisch) | QA-Gate schlägt fehl, Pre-Merge-Verstoß, Post-Merge-Rollback | Harte Trigger, erzeugt Roh-Incident |
| Adversarial Agent | Gezielte Provokation | Systemische Schwächen, die im Normalbetrieb noch nicht aufgetreten sind |
| QA-Bewertung | Normalisierung automatischer Funde | Pflichtfelder befüllen, Kategorie setzen, ähnliche Incidents identifizieren |
| Mensch | Eskalation | Produktionsrelevante Vorfälle, neue Fehlertypen, Post-Merge-Impact |

Die Governance-Beobachtung ist der primäre Erfassungsmechanismus für
Incidents. Sie erkennt Anomalien über Hook-Heuristiken und
Phasen-Schwellen, verdichtet sie zu Incident-Kandidaten und lässt
diese durch ein LLM klassifizieren. Klassifizierte Incidents fließen
automatisch in den Failure Corpus.

### 7.3.2 Automatisch durch die Pipeline

Die Pipeline erzeugt provisorische Incidents bei harten Triggern:

- **QA-Gate schlägt fehl** mit klarer Policy-, Scope- oder
  Architekturverletzung (nicht bei jedem fehlgeschlagenen Test)
- **Adversarial-Test findet verwertbare Schwäche** (Evidence-Fabrication,
  Prompt-Injection-Anfälligkeit, Policy-Umgehung)
- **Pre-Merge-Checks finden kritische Verstöße** (bekannte Patterns,
  sensitive Pfade verändert)
- **Post-Merge-Rollback oder Hotfix** wird auf Agenten-Output
  zurückgeführt

Die Pipeline erzeugt nur den Roh-Incident mit Status "observed". Sie
erzeugt niemals eigenständig ein Pattern.

### 7.3.3 Durch den QA-Agenten

Der QA-Agent ist der wichtigste Erfassungsakteur für den Normalbetrieb.
Seine Aufgaben bei der Erfassung:

- Incident normalisieren (alle Pflichtfelder befüllen)
- Kategorie setzen
- Evidenz verlinken
- Erwartetes vs. tatsächliches Verhalten präzise formulieren
- Pattern-Kandidat-Schlüssel ableiten
- Ähnliche bestehende Incidents identifizieren

Der QA-Agent führt keine eigenständige Pattern-Promotion durch.

### 7.3.4 Durch den Adversarial Testing Agent

Der Adversarial Agent erfasst Fälle, die nicht versehentlich auftreten,
sondern durch gezielte Provokation sichtbar werden:

- Prompt-Injection-Anfälligkeit
- Evidence-Fabrication unter Druck
- Scope-Aufweichung bei mehrdeutigen Anforderungen
- Policy-Umgehung durch geschickte Argumentation
- Unsafe Tool Use

Diese Fälle werden als Incident mit Herkunft "adversarial" markiert.
Sie sind wertvoll, auch wenn sie im Produktivbetrieb noch nicht
aufgetreten sind, weil sie systemische Schwächen aufdecken.

### 7.3.5 Durch den Menschen

Menschen erfassen manuell nur in drei Situationen:

- **Hohe Schwere:** Produktionsrelevanter oder sicherheitskritischer
  Vorfall, der automatisch nicht erkannt wurde
- **Post-Merge-Impact:** Fehler, der erst nach Merge auffällt und
  auf Agentenverhalten zurückzuführen ist
- **Neuer Fehlertyp:** Offensichtlich neues Fehlermuster, das Agenten
  falsch klassifizieren würden

Der Mensch ist nicht Datenerfasser für jeden Kleinkram, sondern
Eskalationsinstanz und Pattern-Entscheider.

### 7.3.6 Erfassungs-Schwelle

Nicht jeder fehlgeschlagene Test wird ein Incident. Die Schwelle:

- Severity mindestens "mittel" ODER
- Merge wurde blockiert ODER
- Rework-Aufwand geschätzt über 30 Minuten ODER
- Der Fehlertyp ist noch nicht im Corpus vertreten

Damit bleibt das Volumen handhabbar. Ziel: Unter 20 neue Incidents
pro Monat bei normalem Betrieb.

---

## 7.4 Kategorien-Katalog

Feste Top-Level-Kategorien als Enum, darunter freie Tags. Freie
Kategorien allein werden chaotisch. Ein starres Megaschema wird
bürokratisch. Daher: stabiles Gerüst, flexibles Detail.

### 7.4.1 Top-Level-Kategorien (Enum, erweiterbar nur per Review)

| Kategorie | Beschreibung |
|---|---|
| **scope_drift** | Änderung außerhalb des Story-/Task-Scopes. Agent fasst Dinge an, die nicht Teil der Aufgabe sind. |
| **architecture_violation** | Bruch von Architektur-, Modul-, Layer-, Ownership- oder Schnittstellenregeln. |
| **evidence_fabrication** | Agent behauptet, Analyse/Prüfung/Test durchgeführt zu haben, ohne reale Evidenz. |
| **hallucination** | Agent behauptet Dateien, APIs, Tests, Bibliotheken oder Befunde, die nicht existieren. |
| **test_omission** | Relevante Tests fehlen trotz Änderung. Agent liefert Code ohne ausreichende Absicherung. |
| **assertion_weakness** | Tests existieren, beweisen aber die fachliche Korrektheit nicht. Schein-Absicherung. |
| **unsafe_refactor** | Opportunistische Umbauten mit Regressionseffekt. Agent "bereinigt" Code, der nicht Teil der Aufgabe war. |
| **policy_violation** | Verstoß gegen definierte Arbeits- oder Sicherheitsregeln des Frameworks. |
| **tool_misuse** | Falsches Tool, falscher Scope, falsche Artefaktbearbeitung. |
| **state_desync** | Agent arbeitet auf veraltetem oder falschem Repo-/Datei-/Branch-Zustand. |
| **requirements_miss** | Acceptance Criteria oder Guardrails nicht umgesetzt, obwohl sie explizit spezifiziert waren. |
| **review_evasion** | Agent erzeugt Output, der Schwächen kaschiert statt offenlegt. Kaschierendes Verhalten. |

### 7.4.2 Freie Tags

Tags sind frei und dienen der Filterung. Beispiele:

security, sql, integration-test, spring, migration, cross-module,
high-blast-radius, controller, authz, database, api, frontend

Tags werden nicht normiert. Sie wachsen organisch und werden bei Bedarf
konsolidiert.

### 7.4.3 Katalog-Erweiterung

Eine neue Top-Level-Kategorie wird nur aufgenommen, wenn:

- Mindestens 5 Incidents mit dem Tag "custom:[Kategoriename]" existieren
- Kein bestehender Top-Level-Typ den Fall abdeckt
- Ein Mensch die Aufnahme bestätigt

Damit bleibt die Taxonomie stabil, aber nicht starr.

---

## 7.5 Pattern-Promotion (Muster-Erkennung)

Ein Pattern entsteht nicht beim zweiten nervigen Vorfall. Sonst
explodiert die Anzahl und jedes Pattern verwässert die Aufmerksamkeit.

### 7.5.1 Promotion-Kriterien

Ein Incident wird zum Pattern, wenn mindestens eine dieser Regeln
erfüllt ist:

**Regel A — Wiederholung:**

- Mindestens 3 Incidents innerhalb von 30 Tagen
- Gleicher Top-Level-Typ
- Gleiche oder sehr ähnliche Invariante
- Idealerweise über mindestens 2 verschiedene Stories oder Pipeline-Runs

**Regel B — Hohe Schwere:**

- 1 Incident reicht, wenn der Fehler:
  - produktionsrelevant oder sicherheitskritisch ist
  - hohen Blast Radius hat
  - klar deterministisch prüfbar ist

**Regel C — Günstige Checkbarkeit:**

- 2 Incidents reichen, wenn:
  - ein Check mit niedriger False-Positive-Gefahr ableitbar ist
  - der Check früh in der Pipeline ausführbar ist
  - die Kosten des Fehlers deutlich höher als die Check-Kosten sind

### 7.5.2 Erkennung: automatisch vorschlagen, menschlich bestätigen

**Automatisiert:**

- Clustering ähnlicher Incidents anhand von Kategorie, Pattern-
  Schlüssel und betroffenen Dateipfad-Mustern
- Vorschlag "Candidate Pattern" mit Begründung und Incident-Referenzen
- Wochenreport mit offenen Clustern

**Menschlich bestätigt:**

- QA-Plattform-Owner bestätigt oder verwirft Candidate Patterns
- Bei Architektur- oder Security-Fällen: Architekt bestätigt
- Kein Pattern wird ohne menschliche Bestätigung aktiviert

Das ist zentral. Ohne menschliche Bestätigung erzeugt das System
zu viele schlechte Checks, die den Entwicklungsfluss blockieren.

---

## 7.6 Check-Ableitung

Hier liegt der eigentliche Wert des Failure Corpus. Der Check muss
nicht clever sein, sondern zuverlässig.

### 7.6.1 Grundprinzip

Ein bestätigtes Pattern wird zum deterministischen Guard. Kein
LLM-Judging als "deterministischen Check" verkaufen. Wenn ein Check
ein LLM braucht, gehört er in den Semantic Review, nicht in den
Failure Corpus. Der Prozess ist so gestaltet, dass er weitgehend
automatisiert abläuft und den Menschen nur an einer einzigen Stelle
einbezieht: der Freigabe.

### 7.6.2 Check-Typen

| Check-Typ | Beschreibung | Beispiel |
|---|---|---|
| **Changed-File-Policy** | Prüft, ob geänderte Dateien zum Story-Scope passen | "Keine Security-Dateien ohne Security-Story" |
| **Artifact-Completeness** | Prüft, ob alle geforderten Artefakte vorhanden sind | "Review-Artefakt muss Diff-Referenz enthalten" |
| **Test-Obligation** | Prüft, ob für bestimmte Änderungen Tests vorhanden sind | "Änderung an Controller erfordert Controller-Test" |
| **Sensitive-Path-Guard** | Blockiert Änderungen an definierten sensitiven Pfaden ohne Berechtigung | "Policy-Dateien nur mit Architekten-Freigabe" |
| **Forbidden-Dependency** | Prüft, ob unerlaubte Abhängigkeiten eingeführt wurden | "Kein direkter DB-Zugriff aus Controller-Layer" |
| **Fixture-Replay** | Prüft bekannte Fehlermuster gegen reale Fixtures | "Bekanntes Halluzinationsmuster gegen Fixture testen" |

### 7.6.3 Zuordnung Fehlerkategorie zu Check-Typ

| Fehlerkategorie | Check-Typ |
|-----------------|-----------|
| scope_drift, unsafe_refactor | Changed-File-Policy |
| evidence_fabrication, review_evasion | Artifact-Completeness |
| test_omission, assertion_weakness | Test-Obligation |
| policy_violation, tool_misuse | Sensitive-Path-Guard |
| architecture_violation | Forbidden-Dependency |
| hallucination, state_desync | Fixture-Replay |
| requirements_miss | Artifact-Completeness |

Wenn die Zuordnung nicht eindeutig ist (Pattern passt auf mehrere
Typen), wird der einfachste Typ gewählt. Kein menschliches Urteil
nötig, die Zuordnung ist deterministisch.

### 7.6.4 Ableitungsprozess

#### Schritt 1: Invariante schärfen

**Wer:** Ein LLM als Bewertungsfunktion (Skript-Aufruf, kein Agent).

**Input:** Das bestätigte Pattern mit seinen Incident-Referenzen,
den konkreten Symptomen und dem vom QA-Prozess vorgeschlagenen
Invariant-Kandidaten.

**Was passiert:** Das LLM formuliert aus dem Invariant-Kandidaten
eine präzise, deterministische Regel. Beispiel: Aus "Agent ändert
Security-Dateien ohne Security-Story" wird "Wenn das Issue-Feld
'Module' nicht 'security' enthält, dürfen keine Dateien in den Pfaden
security/, auth/ oder Dateien mit 'Permission' oder 'Policy' im
Namen verändert werden."

**Output:** Eine Regel als strukturierter Text mit Eingabedaten
(welche Felder/Pfade), Bedingung und erwarteter Reaktion.

#### Schritt 2: Check-Typ zuordnen

**Wer:** Automatisch durch Mapping von Fehlerkategorie auf Check-Typ
(siehe Abschnitt 7.6.3).

Meistens ist die Zuordnung eindeutig. Im Zweifel den einfachsten Typ
wählen.

#### Schritt 3: Check-Proposal erstellen

**Wer:** Ein LLM als Bewertungsfunktion (Skript-Aufruf).

**Input:** Die geschärfte Invariante aus Schritt 1, der Check-Typ
aus Schritt 2, die Incident-Evidenzen.

**Was passiert:** Das LLM erzeugt einen Check-Proposal mit:

- Pattern-Referenz
- Regel-Definition
- Benötigte Eingabedaten (Story-Metadaten, Changed Files, Diffs,
  Artefakte)
- Pipeline-Stufe (so früh wie möglich)
- Check-Typ
- Invariante als Regel
- False-Positive-Risiko-Einschätzung
- Geschätzte Kosten (Laufzeit, Komplexität)
- Je zwei Positive-Fixtures (sollen den Check auslösen) und
  Negative-Fixtures (sollen passieren)

**Output:** Ein strukturiertes Dokument im Failure-Corpus-Verzeichnis
(checks/CHK-NNNN) mit Status "draft".

#### Schritt 4: Menschliche Freigabe

**Wer:** Der Mensch, im Rahmen des wöchentlichen 15-Minuten-
Review-Slots (siehe Abschnitt 7.8).

**Was passiert:** Der Mensch sieht die Liste offener Check-Proposals
und entscheidet pro Proposal: freigeben, anpassen oder verwerfen.
Das ist die einzige Stelle, an der der Mensch in der Check-Ableitung
aktiv wird.

**Output:** Status wechselt von "draft" auf "approved" oder
"rejected".

#### Schritt 5: Implementieren und einbauen

**Wer:** Ein Worker-Agent (reguläre AgentKit-Story).

**Was passiert:** Für jeden freigegebenen Check-Proposal wird
automatisch eine Story vom Typ "Implementation" erzeugt, die den Check
implementiert. Der Worker baut den Check als deterministisches Skript,
testet gegen die im Proposal definierten Fixtures und registriert den
Check in der Pipeline-Konfiguration (Stage-Registry).

**Arbeitsteilung im Detail:**

- QA-Agent erstellt Proposal und Fixture-Fälle (Was soll den Check
  auslösen? Was soll ihn passieren?)
- Developer-Agent implementiert den Check
- QA-Agent validiert gegen Positive/Negative Fixtures
- Mensch reviewt nur bei heiklen Checks oder hohem False-Positive-Risiko

**Kernregel für Pipeline-Stufe:** Der Check gehört an die früheste
deterministische Stelle in der Pipeline, nicht ans letzte Review-Gate.

| Check-Typ | Pipeline-Stufe |
|-----------|----------------|
| Changed-File-Policy | Pre-Merge (frühestmöglich) |
| Sensitive-Path-Guard | Pre-Merge |
| Artifact-Completeness | Artefakt-Prüfung (Verify Schicht 1) |
| Test-Obligation | Structural Checks (Verify Schicht 1) |
| Forbidden-Dependency | Structural Checks (Verify Schicht 1) |
| Fixture-Replay | Structural Checks (Verify Schicht 1) |

**Output:** Implementierter Check, registriert in der Pipeline,
Status wechselt auf "active".

#### Schritt 6: Automatische Wirksamkeitsprüfung

**Wer:** Ein Phasen-Skript, das bei jedem Pipeline-Run mitläuft.

**Was passiert:** Jeder aktive Check hat ein Aktivierungsdatum. Das
Skript zählt automatisch mit, wie oft der Check in den letzten
30/90 Tagen ausgelöst hat (true positives), wie oft er fälschlich
ausgelöst hat (false positives, erkennbar an Override durch den
Menschen) und wie oft er ohne Fund durchlief.

Nach 30 Tagen wird automatisch ein Wirksamkeits-Report pro Check
erzeugt und im wöchentlichen Review-Slot dem Menschen angezeigt.
Kein Kalendereintrag, kein Wecker: Der Report erscheint automatisch,
der Mensch sieht ihn beim nächsten Review.

**Deaktivierungsregel (automatisch):** Checks, die in 90 Tagen
keinen einzigen realen Fund hatten und mehr als 3 False Positives
produziert haben, werden automatisch deaktiviert und der Mensch wird
im nächsten Review darüber informiert. Der Mensch kann die
Deaktivierung rückgängig machen. Ausnahme: Checks, die aus Patterns
mit Schweregrad "kritisch" oder "sicherheitskritisch" abgeleitet
wurden, sind von der Auto-Deaktivierung ausgenommen und können nur
manuell durch den Menschen deaktiviert werden.

**Output:** Status wechselt auf "tuned" (angepasst) oder "retired"
(deaktiviert).

---

## 7.7 Lifecycle

Nicht jeder Incident wird ein Pattern. Nicht jedes Pattern wird ein
Check. Das ist gewollt.

### 7.7.1 Incident-Status

| Status | Bedeutung |
|---|---|
| **observed** | Roher Fund, automatisch oder manuell erfasst |
| **triaged** | Klassifiziert, Evidenz ergänzt, Pflichtfelder befüllt |
| **clustered** | Ähnlichen Incidents zugeordnet |
| **promoted** | In ein Pattern übernommen |
| **closed_one_off** | Einzelfall ohne weiteren Präventionswert |
| **archived** | Nur noch historisch relevant |

### 7.7.2 Pattern-Status

| Status | Bedeutung |
|---|---|
| **candidate** | Vorgeschlagen, noch nicht bestätigt |
| **accepted** | Menschlich bestätigt, Check-Ableitung möglich |
| **check_proposed** | Check-Spezifikation liegt vor |
| **check_active** | Deterministischer Check ist in der Pipeline aktiv |
| **monitoring** | Check läuft, wird auf Wirksamkeit beobachtet |
| **retired** | Pattern ist nicht mehr relevant oder Check wurde entfernt |

### 7.7.3 Check-Status

| Status | Bedeutung |
|---|---|
| **draft** | Spezifikation erstellt, noch nicht implementiert |
| **approved** | Menschlich freigegeben, Implementierung steht aus |
| **active** | In der Pipeline aktiv |
| **tuned** | Nach Nutzen-Review angepasst |
| **retired** | Deaktiviert, weil nicht mehr relevant oder zu viele False Positives |
| **rejected** | Vom Menschen im Review verworfen |

### 7.7.4 Aufbewahrung und Löschung

- Incident-Metadaten werden dauerhaft aufbewahrt (sie begründen, warum
  ein Check existiert)
- Große Logs und vollständige Tool-Traces: nach 90 Tagen bereinigen
- Diffs und Review-Artefakte: nach 180 Tagen bereinigen, wenn Incident
  im Status "archived"
- Patterns und Checks: versioniert behalten, auch nach Retirement
  (Entscheidungshistorie)
- Incidents werden nie hart gelöscht, sondern archiviert

Begründung: Ohne die Incident-Historie verliert man die Begründung,
warum ein Check existiert. Dann werden Checks zu unbegründeten Regeln,
die niemand mehr hinterfragt oder entfernen traut.

---

## 7.8 Anti-Patterns

Hier scheitern solche Ansätze in der Praxis.

### 7.8.1 Alles sammeln

Das Corpus wird zur Müllhalde. Jeder fehlgeschlagene Test, jede
Kleinigkeit wird erfasst. Bei 250k LOC und hohem Agenten-Durchsatz
entsteht innerhalb von Wochen ein unbrauchbares Archiv.

**Gegenmaßnahme:** Strikte Aufnahmekriterien (Abschnitt 7.1.2). Nur
Fälle mit echtem Präventionswert. Ziel: unter 20 neue Incidents pro
Monat.

### 7.8.2 Nur Narrative speichern

"Agent war irgendwie schlecht" ist wertlos. Ohne Diff, Gate-Referenz,
Story-Kontext, Agentenrolle, Erwartung und Impact kann man später
nichts clustern und kein Pattern ableiten.

**Gegenmaßnahme:** Strukturierte Pflichtfelder. Kein Freitext-only.

### 7.8.3 Aus jedem Vorfall sofort einen Check bauen

Dann entsteht Check-Spam mit hoher False-Positive-Rate. Agenten werden
durch übermäßige Guards verlangsamt, ohne dass die Checks echten
Wert liefern.

**Gegenmaßnahme:** Pattern-Promotion erst nach Schwellenkriterien
(Abschnitt 7.5). Kein Check ohne menschliche Bestätigung des Patterns.

### 7.8.4 Checks mit LLM-Judging als "deterministisch" verkaufen

Ein LLM, das prüft ob ein anderes LLM einen Fehler gemacht hat, ist
kein deterministischer Guard. Es ist ein weiterer probabilistischer
Prüfer mit eigenen Fehlerquellen.

**Gegenmaßnahme:** Nur echte deterministische Checks (Dateipfad-Regeln,
Diff-Regeln, statische Analyse, Fixture-Replays). Wenn ein Check ein
LLM braucht, ist er kein Failure-Corpus-Check, sondern gehört in das
Semantic Review.

### 7.8.5 Pattern und Incident vermischen

Dann weiß niemand mehr, ob etwas ein Einzelfall, eine Vermutung oder
ein etablierter Guard ist. Die drei Ebenen (Incident, Pattern, Check)
verlieren ihre Trennschärfe.

**Gegenmaßnahme:** Strikte Artefakttrennung. Drei Verzeichnisse, drei
ID-Schemata, klare Referenzen.

### 7.8.6 Kein Owner pro Check

Checks ohne Owner veralten. Sie blockieren unnötig, niemand traut sich
sie zu entfernen, und die Pipeline wird immer langsamer.

**Gegenmaßnahme:** Jeder Check hat einen Owner. Owner ist für
Nutzen-Review und Sunset verantwortlich.

### 7.8.7 Checks zu spät in der Pipeline

Ein Scope-Drift-Check, der erst nach vollständiger QA feuert, spart
kaum Rework-Kosten. Der Fehler ist dann bereits durch mehrere
Agenten-Runden gelaufen.

**Gegenmaßnahme:** Checks an die früheste deterministische Stelle
(Abschnitt 7.6.4, Schritt 5).

### 7.8.8 Kategorien frei wuchern lassen

Ohne festes Top-Level-Enum wird Reporting unmöglich. Jeder Agent
erfindet eigene Kategorien, Clustering scheitert, Trend-Analysen sind
sinnlos.

**Gegenmaßnahme:** Festes Enum mit Review-Pflicht für Erweiterungen
(Abschnitt 7.4.3).

### 7.8.9 Failure Corpus als Compliance-Theater

Der Sinn ist nicht Dokumentation. Der Sinn ist Fehlerkosten senken.
Wenn der Corpus nur gefüllt wird, aber nie Checks entstehen, ist er
Aufwand ohne Wert.

**Gegenmaßnahme:** Wöchentlicher Review-Slot (15 Minuten). Offene
Incidents sichten, Cluster prüfen, Candidate Patterns bestätigen oder
verwerfen.

### 7.8.10 Kein Sunset-Mechanismus

Checks akkumulieren sich über die Zeit. Ohne regelmäßige Prüfung
auf Relevanz wird die Pipeline immer langsamer und restriktiver.

**Gegenmaßnahme:** Nutzen-Review nach 30 Tagen, dann alle 90 Tage.
Checks ohne Fund in 90 Tagen und mit False-Positive-Rate über 5%
werden deaktiviert.

---

## 7.9 Einführungsstrategie

Der Failure Corpus wird stufenweise eingeführt, nicht als Big Bang.

### Phase 1: Minimal (sofort)

- Incident-Record mit den definierten Pflichtfeldern
- Top-Level-Taxonomie (12 Kategorien)
- Manuelle Pattern-Promotion durch den Menschen
- 1 wöchentlicher Review-Slot (15 Minuten)
- Nur 3 Check-Typen: Changed-File-Policy, Artifact-Completeness,
  Test-Obligation

### Phase 2: Stabilisierung (nach 8-12 Wochen Betrieb)

- Automatisches Clustering ähnlicher Incidents
- Candidate-Pattern-Vorschläge durch den QA-Agenten
- Fixture-basierte Validierung neuer Checks
- False-Positive/False-Negative-Metriken
- Sensitive-Path-Guard und Forbidden-Dependency als zusätzliche
  Check-Typen

### Phase 3: Reife (nach 6+ Monaten Betrieb)

- Aktive Vorschläge für neue Patterns mit Kosten-Nutzen-Schätzung
- Automatische Priorisierung nach Rework-Kosten
- Sunset-Mechanismus für nutzlose Checks
- Trend-Reports über Fehlerkategorien

---

## 7.10 Synthese-Notizen

Das Umsetzungskonzept wurde im Multi-LLM-Sparring erarbeitet
(ChatGPT GPT-4o, Grok xAI, Claude Opus 4.6; Synthese am 2026-03-16).

### 7.10.1 Übereinstimmung aller drei Quellen

Alle drei Sparring-Partner stimmen überein:

- **Drei-Ebenen-Trennung** (Incident, Pattern, Check) ist zwingend
- **Menschliche Bestätigung** vor Pattern-Promotion ist nötig
- **Deterministische Checks**, kein LLM-Judging
- **Nicht alles sammeln** — strenge Aufnahmekriterien
- **Frühe Einbindung** in die Pipeline statt spätes Review-Gate
- **Owner und Sunset** für jeden Check

### 7.10.2 Wo die Quellen divergierten

- **Schwellen für Pattern-Promotion:** ChatGPT schlägt 3 Incidents
  in 30 Tagen als Standard vor, Grok ebenfalls 3 Incidents, aber mit
  stärkerem Fokus auf Impact-Schwelle. Die Synthese übernimmt das
  Drei-Regeln-Modell (Wiederholung, Schwere, Checkbarkeit), das alle
  drei Szenarien abdeckt.

- **Automatisierungsgrad bei Erfassung:** Grok schlägt 70/30
  (automatisch/manuell) vor. ChatGPT differenziert stärker nach
  Akteuren (Pipeline, QA-Agent, Adversarial Agent, Mensch). Die
  Synthese folgt ChatGPTs Akteur-Modell, weil es präziser zur
  AgentKit-Rollenstruktur passt.

- **Corpus-Größe:** Grok setzt ein hartes Limit (unter 1000 aktive
  Einträge). ChatGPT setzt auf Relevanz-Filter statt Größen-Limit.
  Die Synthese setzt auf Aufnahmekriterien und Archivierung statt auf
  harte Limits, ergänzt aber ein Monats-Ziel (unter 20 neue Incidents).

- **Kategorien:** ChatGPT liefert 12 Kategorien mit starkem Fokus auf
  agentenspezifisches Fehlverhalten (review_evasion, assertion_weakness).
  Grok liefert 9 Kategorien mit stärkerem Fokus auf technische Fehler
  (performance, non-determinism). Die Synthese übernimmt ChatGPTs
  12er-Set, weil es die agentspezifischen Muster besser abdeckt.
  Performance- und Non-Determinism-Fälle werden über Tags abgebildet.
