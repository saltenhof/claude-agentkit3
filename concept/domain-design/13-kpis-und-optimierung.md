---
concept_id: DK-13
title: KPIs und nachgelagerte Optimierung
module: kpi-domain
domain: kpi-and-dashboard
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: kpi-domain
defers_to:
  - DK-05
  - FK-60
  - FK-61
  - FK-62
  - FK-63
supersedes: []
superseded_by:
tags: [kpi, dashboard, telemetrie]
formal_scope: prose-only
---

# 13 — KPIs und nachgelagerte Optimierung

**Quelle:** Konsolidiert aus DK-05 §5.3 (Stand 2026-04-02)
**Datum:** 2026-04-29 (ausgegliedert aus DK-05 entlang BC kpi-and-dashboard)
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

## 13.1 KPIs — Nachgelagerte Optimierung

### 13.1.1 Abgrenzung zu Events und Metriken

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

### 13.1.2 Entscheidungsdomaenen

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

### 13.1.3 Aggregationsebenen

KPIs werden auf drei Ebenen ausgewertet:

- **Pro Story**: Einzelne Story als Betrachtungseinheit
  (z.B. Durchlaufzeit, QA-Runden, LLM-Aufrufe)
- **Pro Entitaet und Periode**: Eine benannte Entitaet
  (Guard, LLM-Pool, Review-Template, Check) ueber einen
  Zeitraum (Woche, Monat)
- **Pro Periode**: Globale System-Kennzahlen ueber einen
  Zeitraum (First-Pass-Rate, Incident-Volumen)

### 13.1.4 Prinzipien

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

### 13.1.5 Technische Realisierung

Der vollstaendige KPI-Katalog mit allen Kennzahlen, Formeln,
Koernungen und der technischen Architektur (Speicherung,
Aggregation, Dashboard) ist in den technischen Feinkonzepten
FK-60 bis FK-63 definiert.

---

