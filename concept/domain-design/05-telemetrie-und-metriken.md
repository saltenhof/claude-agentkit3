---
concept_id: DK-05
title: Telemetrie, Metriken und KPIs
module: telemetry
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: domain-telemetry
defers_to: []
supersedes: []
superseded_by:
tags: [telemetry, metrics, kpis, events, observability]
formal_scope: prose-only
---

# 05 — Telemetrie, Metriken und KPIs

**Quelle:** Konsolidiert aus agentkit-domain-concept.md Kapitel 8 + Appendix E
**Datum:** 2026-04-04 (erweitert um KPI-Fachlichkeit)
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Die Telemetrie erfuellt drei Aufgaben:

1. **Nachvollziehbarkeit** (was ist passiert?): Jede autonome
   Agentenhandlung wird als Event protokolliert.
2. **Pruefbarkeit** (wurde der Prozess eingehalten?): Die Telemetrie
   ist selbst Pruefgegenstand des Integrity-Gates bei Closure.
3. **Optimierbarkeit** (wird das System mit der Zeit besser?):
   Aus Events und Workflow-Metriken werden KPIs abgeleitet, die
   nachgelagert Trends, Engpaesse und Verbesserungspotenziale
   sichtbar machen.

Die ersten beiden Aufgaben wirken **waehrend** der Story-Umsetzung
(Events speisen Gates, Guards, Governance-Beobachtung). Die dritte
Aufgabe wirkt **nach** der Story-Umsetzung (KPIs informieren
Entscheidungen ueber Story-Sizing, LLM-Auswahl, Prompt-Qualitaet,
QA-Effektivitaet).

**Plattformentscheidung:** Die kanonische Speicherung von Telemetrie,
Workflow-State und KPI-Rohdaten erfolgt in einer systemweiten
PostgreSQL-Instanz, nicht in projektlokalen Dateien oder SQLite-DBs.

Deterministische Pipeline-Schritte (Structural Checks, LLM-Bewertungen
ueber Skripte) brauchen keine Telemetrie-Nachweise, weil ihr Ablauf
durch den Code garantiert ist. Telemetrie-Nachweise sind dort relevant,
wo Agents autonom handeln und der Prozess nicht durch Code erzwungen
wird.

## 5.1 Telemetrie-Ereignisse

Die folgende Tabelle definiert die konkreten Ereignisse, die während
einer Story-Bearbeitung erhoben werden und bei Closure nachweisbar
sein müssen.

**Worker-Lifecycle:**

| Ereignis | Wann | Erwartungswert |
|----------|------|----------------|
| `agent_start` | Worker-Agent wird gestartet | Genau 1 pro Story-Durchlauf |
| `agent_end` | Worker-Agent beendet regulär | Genau 1, nach agent_start |
| `increment_commit` | Worker committet ein Inkrement | >= 1 pro Story |
| `drift_check` | Worker prüft Impact/Konzept-Konformität | >= 1 pro Story (bei jedem Inkrement erwartet) |

**Worker-Reviews:**

| Ereignis | Wann | Erwartungswert |
|----------|------|----------------|
| `review_request` | Worker fordert Review von Pflicht-LLM an | Abhängig von Story-Grösse (XS/S: >= 1, M: >= 2, L/XL: >= 3) |
| `review_response` | Pflicht-LLM liefert Review-Ergebnis | Gleiche Anzahl wie review_request |
| `review_compliant` | Review lief über freigegebenes Template | Jeder review_request muss ein review_compliant haben |

**Adversarial Testing:**

| Ereignis | Wann | Erwartungswert |
|----------|------|----------------|
| `adversarial_start` | Adversarial Agent wird gestartet | Genau 1 (nur bei implementierenden Stories) |
| `adversarial_sparring` | Adversarial holt sich zweites LLM für Edge-Case-Ideen | >= 1 (Pflicht) |
| `adversarial_test_created` | Adversarial erzeugt einen neuen Test | >= 1 (mindestens ein neuer Test erwartet) |
| `adversarial_end` | Adversarial Agent beendet | Genau 1, nach adversarial_start |

**Multi-LLM-Beteiligung:**

| Ereignis | Wann | Erwartungswert |
|----------|------|----------------|
| `llm_call` mit Pool-Kennung | LLM wird über Pool aufgerufen (ChatGPT, Gemini, Grok) | Abhängig von Konfiguration: pro konfiguriertem Pflicht-Reviewer >= 1 |

**Governance:**

| Ereignis | Wann | Erwartungswert |
|----------|------|----------------|
| `integrity_violation` | Ein Guard wurde verletzt | Erwartet: 0 (jeder Eintrag ist ein Befund) |
| `web_call` | Agent führt Web-Suche/-Abruf durch | <= konfiguriertes Budget (Default: 200) |

## 5.2 Workflow-Metriken

Zusätzlich zur Ereignis-Telemetrie erfasst jeder Pipeline-Run
strukturierte Metriken, die den Vergleich über Stories hinweg
ermöglichen:

| Metrik | Was gemessen wird |
|--------|-------------------|
| Durchlaufzeit | Gesamtdauer von Preflight bis Closure |
| QA-Runden | Wie oft ging die Story von Verify zurück an den Worker |
| Adversarial-Befunde | Anzahl der vom Adversarial Agent gefundenen Fehler |
| Adversarial-Tests erzeugt | Anzahl der neu erzeugten Tests |
| Geänderte Dateien | Anzahl der Dateien im Diff |
| Inkremente | Anzahl der vertikalen Slices, die der Worker commited hat |

Zusammen mit Experiment-Tags (Prompt-Version, Modell, Config-Profil,
AgentKit-Version) machen diese Metriken Verbesserungen oder
Regressionen quantifizierbar. Wenn nach einer Prompt-Aenderung die
QA-Runden steigen oder die Adversarial-Befunde zunehmen, ist das ein
messbares Signal.

## 5.3 KPIs — Nachgelagerte Optimierung

### 5.3.1 Abgrenzung zu Events und Metriken

Events (5.1) und Workflow-Metriken (5.2) dienen der Laufzeit-
Governance und der unmittelbaren Pruefbarkeit. KPIs dienen einem
anderen Zweck: Sie beantworten strategische Fragen ueber die
Leistungsfaehigkeit des Gesamtsystems und informieren Entscheidungen,
die nicht waehrend einer einzelnen Story getroffen werden, sondern
ueber viele Stories und Zeitraeume hinweg.

**Events** = Rohdaten, entstehen waehrend der Story-Ausfuehrung,
speisen Gates und Guards.

**Workflow-Metriken** = Pro-Story-Zusammenfassungen, entstehen bei
Closure, ermoeglichen Story-zu-Story-Vergleich.

**KPIs** = Abgeleitete Kennzahlen, entstehen durch Aggregation
ueber Events und Metriken, ermoeglichen Trend-Analyse, LLM-Auswahl,
Prozess-Optimierung und Governance-Kalibrierung.

### 5.3.2 Entscheidungsdomaenen

Jede KPI beantwortet eine konkrete Entscheidungsfrage. Die KPIs
gliedern sich in zehn Domaenen:

**Domaene 1 — Story-Dimensionierung und Pipeline-Steuerung**

Sind die Stories richtig geschnitten? Funktioniert die
Pipeline-Steuerung? Typische Kennzahlen: Compaction-Haeufigkeit,
QA-Runden-Trend, Eskalationsrate, Modus-Verteilung
(Execution vs. Exploration).

Handlungen: Stories verkleinern, ACs praezisieren, Sizing-Kriterien
rekalibrieren.

**Domaene 2 — LLM-Selektion und -Performance**

Welche LLMs setzen wir fuer welche Aufgaben ein? Typische
Kennzahlen: Antwortzeiten (Median, P95), Verfuegbarkeit,
Verdict-Uebernahme-Rate, Finding-Praezision, Dissens-Rate.

Handlungen: Langsame oder unzuverlaessige Pools ersetzen,
LLM-Rollen-Zuordnung aendern, Prompts optimieren.

**Domaene 3 — Governance-Gesundheit**

Funktionieren die Guards? Sind die Agenten-Prompts gut genug?
Typische Kennzahlen: Violation-Rate pro Guard, Prompt-Injection-
Versuche, Orchestrator-Rollenverletzungen, Integrity-Gate-Blockaden.

Handlungen: Prompts hardenen, Guard-Schwellenwerte kalibrieren,
Sandbox-Policies verschaerfen.

**Domaene 4 — Dokumententreue und Konzept-Konformitaet**

Halten sich Agents an die konzeptionellen Vorgaben? Typische
Kennzahlen: Konflikt-Rate der 4 Dokumententreue-Ebenen,
Drift-Erkennungsrate.

Handlungen: Konzepte aktualisieren oder Worker-Prompts schaerfen.

**Domaene 5 — QA-Effektivitaet**

Wird der QA-Prozess mit der Zeit besser? Typische Kennzahlen:
First-Pass-Success-Rate, Finding-Ueberlebensrate, Check-Effektivitaet,
Adversarial-Trefferquote, Finding-Resolution-Qualitaet.

Handlungen: QA-Prompts verbessern, unwirksame Checks entfernen,
Remediation-Strategie anpassen.

**Domaene 6 — Review-Qualitaet und Evidence Assembly**

Liefern wir den Reviewern die richtigen Informationen? Typische
Kennzahlen: Template-Effektivitaet, Bundle-Vollstaendigkeit,
Preflight-Wirksamkeit.

Handlungen: Evidence Assembler verbessern, Templates ueberarbeiten.

**Domaene 7 — VektorDB und Wissensmanagement**

Funktioniert die semantische Suche? Typische Kennzahlen:
Similarity-Schwellenwert-Kalibrierung (False-Positive/False-Negative),
Duplikat-Erkennungsrate.

Handlungen: Schwellenwert anpassen, Indexierungs-Strategie aendern.

**Domaene 8 — ARE-Integration**

Funktioniert die Anforderungsverknuepfung? Typische Kennzahlen:
ARE-Gate PASS/FAIL-Rate, Evidence-Abdeckungsrate.

Handlungen: Anforderungs-Templates praezisieren, Worker-Prompts
fuer Evidence-Einreichung verbessern.

**Domaene 9 — Failure Corpus und Lernschleife**

Lernt das System aus Fehlern? Typische Kennzahlen:
Incident-Volumen, Konversionsraten (Incident → Pattern → Check),
Check-Wirksamkeit (True-Positive/False-Positive).

Handlungen: Aufnahmekriterien verschaerfen, Pattern-Review
beschleunigen, unwirksame Checks deaktivieren.

**Abgrenzung zum Failure Corpus (Kap. 07)**: Analytics aggregiert
ueber Failure-Corpus-Entitaeten (Incidents, Patterns, Checks) und
misst deren Verteilung und Trends. Der Failure Corpus selbst erzeugt,
promotet und steuert den Lifecycle dieser Entitaeten. Analytics
misst — Failure Corpus lernt.

**Domaene 10 — Prozess-Effizienz und Trends**

Wo verbringen wir Zeit? Wird es besser? Typische Kennzahlen:
Phasen-Zeitverteilung, Story-Vorhersagbarkeit, rollierende
Durchschnitte fuer Durchlaufzeit und QA-Runden.

Handlungen: Pipeline-Phasen straffen, Sizing-Kriterien
verbessern, systemische Qualitaetsprobleme frueh erkennen.

### 5.3.3 Aggregationsebenen

KPIs werden auf drei Ebenen ausgewertet:

- **Pro Story**: Einzelne Story als Betrachtungseinheit
  (z.B. Durchlaufzeit, QA-Runden, LLM-Aufrufe)
- **Pro Entitaet und Periode**: Eine benannte Entitaet
  (Guard, LLM-Pool, Review-Template, Check) ueber einen
  Zeitraum (Woche, Monat)
- **Pro Periode**: Globale System-Kennzahlen ueber einen
  Zeitraum (First-Pass-Rate, Incident-Volumen)

### 5.3.4 Prinzipien

- **Jede KPI beantwortet eine Entscheidungsfrage.** Keine Erhebung
  ohne zugehoerige Handlung.
- **Events sind Rohdaten, KPIs sind Ableitungen.** Kein Automatismus
  — zwischen Event und KPI liegt eine bewusste Aggregations- und
  Interpretationsschicht.
- **Analytics konsumiert, definiert nicht.** Die Semantik von
  Incidents, Patterns, Events und Pipeline-Phasen wird in den
  jeweiligen Fachdomaenen definiert, nicht im Analytics-System.
- **Nachgelagert, nicht eingreifend.** KPIs loesen keine
  automatischen Aktionen waehrend der Story-Ausfuehrung aus.
  Sie informieren menschliche Entscheidungen zwischen Stories.

### 5.3.5 Technische Realisierung

Der vollstaendige KPI-Katalog mit allen Kennzahlen, Formeln,
Koernungen und der technischen Architektur (Speicherung,
Aggregation, Dashboard) ist in den technischen Feinkonzepten
FK-60 bis FK-63 definiert.

---

## Anhang — Telemetrie-Event-Schema

Alle Telemetrie-Events folgen einem kanonischen Schema. Es gibt keine
Varianten oder alternativen Formate. Events werden in einer
relationalen Datenbank gespeichert. Bei Story-Closure wird die
Telemetrie zusaetzlich als JSONL-Datei exportiert (Archivierung,
menschliche Lesbarkeit). Referenz: Hauptkonzept Kapitel 8.

### E.1 Kanonische Felder

| Feld | Typ | Beschreibung | Pflicht |
|------|-----|-------------|---------|
| project_key | String | Mandanten-Schluessel des Zielprojekts | Ja |
| story_id | String | Story-Kennung innerhalb des Projekts | Ja |
| run_id | String (UUID) | Bezeichner des Pipeline-Runs (ein Run umfasst einen vollständigen Story-Durchlauf) | Ja |
| event_id | String (UUID) | Eindeutiger Bezeichner des Events | Ja |
| event_type | String | Typ des Events (siehe Katalog in E.2) | Ja |
| occurred_at | String (ISO 8601 mit Offset) | Fachlicher Zeitpunkt des Events, intern UTC-normalisiert | Ja |
| source_component | String | Fachliche Herkunft des Events (z.B. `telemetry_hook`, `guard_system`) | Ja |
| severity | Enum | `debug`, `info`, `warning`, `error`, `critical` | Ja |
| payload | Objekt | Strukturierter Inhalt, abhängig vom event_type (siehe E.3) | Ja |

### E.2 Event-Typ-Katalog

Die folgende Tabelle listet alle definierten Event-Typen mit ihrer
Zuordnung zu Actor-Typ und Phase.

| Event-Typ | Actor-Typ | Phase | Beschreibung |
|------------|-----------|-------|-------------|
| agent_start | worker | setup | Worker-Agent wurde gestartet |
| agent_end | worker | closure | Worker-Agent hat regulär beendet |
| increment_commit | worker | implementation | Worker hat ein Inkrement commited |
| drift_check | worker | implementation | Worker hat Impact-/Konzept-Konformität geprüft |
| review_request | worker | implementation | Worker hat Review von Pflicht-LLM angefordert |
| review_response | worker | implementation | Pflicht-LLM hat Review-Ergebnis geliefert |
| review_compliant | worker | implementation | Review lief über freigegebenes Template |
| adversarial_start | adversarial | verify | Adversarial Agent wurde gestartet |
| adversarial_sparring | adversarial | verify | Adversarial hat zweites LLM für Edge-Case-Ideen geholt |
| adversarial_test_created | adversarial | verify | Adversarial hat einen neuen Test erzeugt |
| adversarial_end | adversarial | verify | Adversarial Agent hat beendet |
| llm_call | script | implementation, verify | LLM wurde über Pool aufgerufen |
| integrity_violation | script | beliebig | Ein Guard wurde verletzt |
| web_call | worker, adversarial | implementation, verify | Agent hat Web-Suche oder -Abruf durchgeführt |

### E.3 Detail-Struktur nach Event-Typ

Das `payload`-Feld ist ein strukturiertes Objekt, dessen Felder vom
Event-Typ abhängen. Die folgenden Tabellen definieren die Pflichtfelder
pro Event-Typ.

> **[Entscheidung 2026-04-08]** Element 12 — Telemetry Contract: Crash-Detection (Start/End-Paarung, agent_start/agent_end) ist essentiell. Event-Count-Vertrag auf Minimum-Schwellen ("mindestens 1 Review", "mindestens 1 Drift-Check"), keine exakten Zaehler pro Story-Groesse.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 12.

**agent_start, agent_end:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| story_id | String | Redundant zum Top-Level-Feld, dient der Konsistenzprüfung |
| model | String | Eingesetztes LLM-Modell |

**increment_commit:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| commit_hash | String | Git-Commit-Hash |
| changed_files | Array von Strings | Im Inkrement geänderte Dateien |
| increment_number | Integer | Laufende Nummer des Inkrements |

**drift_check:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| result | Enum (pass, drift_detected) | Ergebnis der Drift-Prüfung |
| description | String | Beschreibung bei erkanntem Drift |

**review_request, review_response:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| reviewer_model | String | Eingesetztes Review-LLM |
| review_scope | String | Was reviewed wurde (z.B. "increment_1", "pre_handover") |

**review_compliant:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| template_sentinel | String | Kennung des verwendeten Review-Templates |

**adversarial_sparring:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| sparring_model | String | Eingesetztes Sparring-LLM |
| edge_cases_proposed | Integer | Anzahl der vorgeschlagenen Edge Cases |

**adversarial_test_created:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| test_file | String | Pfad der erzeugten Testdatei |
| test_type | Enum (unit, integration, e2e) | Art des Tests |
| finding | Boolean | Hat der Test einen Fehler aufgedeckt |

**llm_call:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| pool_name | String | Name des Pools (chatgpt, gemini, grok) |
| purpose | String | Zweck des Aufrufs (review, sparring, qa_evaluation, semantic_review) |
| model | String | Konkretes Modell im Pool |

`chatgpt_call` und `gemini_call` sind keine eigenständigen Event-Typen,
sondern `llm_call`-Events mit dem jeweiligen `pool_name`-Wert. Diese
Vereinheitlichung stellt sicher, dass neue LLM-Pools keine
Schema-Änderung erfordern.

**integrity_violation:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| guard | String | Name des verletzten Guards (branch_guard, orchestrator_guard, qa_artifact_protection) |
| action_blocked | String | Beschreibung der blockierten Aktion |

**web_call:**

| Feld | Typ | Beschreibung |
|------|-----|-------------|
| url | String | Aufgerufene URL oder Suchanfrage |
| call_type | Enum (search, fetch) | Art des Web-Zugriffs |
