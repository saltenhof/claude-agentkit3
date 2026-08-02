---
concept_id: FK-93
title: Standardwerte, Schwellwerte und Timeouts
module: defaults
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: defaults
# Der Katalog besitzt genau eine eigene Norm: das Aufnahmekriterium (§93.0,
# Scope `defaults`). Jede Katalogzeile darunter gibt einen Wert wieder, dessen
# normativer Owner ein anderes Dokument ist. Genau dafuer traegt FK-93 je
# Abschnitt eine scope-qualifizierte `defers_to`-Kante auf den Owner. Ohne diese
# Kanten behauptet der Katalog Autoritaet, die er nicht hat -- die Spalte
# `Kapitel` ist ein Lesehinweis fuer Menschen und ersetzt keine
# maschinenlesbare Autoritaetskante (siehe META-CONCEPT-CONSISTENCY P2).
defers_to:
  # §93.0.1 stellt KEINE fremde Regel auf: es sagt, was dieser Katalog von
  # sich selbst verlangt (Scope `defaults`). Die allgemeine Prosa-Autoritaets-
  # regel liegt in META-CONCEPT-CONSISTENCY (P2) und die Ownership-Regel in
  # META-ASSERTION-AUTHORITY; auf `_meta`-Dokumente ist im heutigen
  # Frontmatter-Vertrag keine `defers_to`-Kante moeglich (der Lint kennt nur
  # Contract-Dokumente als Ziele), weshalb §93.0.1 bewusst nur ueber FK-93
  # selbst spricht.
  # --- 93.1 Pipeline-Konfiguration -------------------------------------
  - target: FK-03
    scope: configuration
    reason: >-
      §93.1 gibt Pipeline-Konfigurationswerte wieder; Bedeutung, Defaults und
      Config-Pfade normiert FK-03.
  - target: FK-03
    scope: config-schema-validation
    reason: >-
      §93.1 nennt Config-Pfade und ihre zulaessigen Werte; die Schema-Validierung
      dieser Pfade normiert FK-03.
  - target: FK-03
    scope: config-versioning
    reason: >-
      §93.1 fuehrt `config_version`; die Versionierung des Konfigurationsmodells
      normiert FK-03.
  - target: FK-10
    scope: runtime
    reason: >-
      §93.1 gibt Laufzeit-Schalter (Feature-Flags) wieder; ihre Laufzeitwirkung
      normiert FK-10.
  - target: FK-10
    scope: deployment
    reason: >-
      §93.1 gibt die Zielprojekt-Scaffold-Option wieder; Deployment-Wirkung und
      Opt-in-Semantik normiert FK-10.
  - target: FK-10
    scope: directory-structure
    reason: >-
      §93.1 verweist auf das Default-Zielprojekt-Scaffold; die Verzeichnisstruktur
      selbst normiert FK-10.
  - target: FK-50
    scope: installer
    reason: >-
      §93.1 gibt die Installer-Option `default_project_structure` wieder; der
      Installer-Checkpoint normiert sie in FK-50.
  # --- 93.2 / 93.8 Policy-Engine und Structural Checks ------------------
  - target: FK-33
    scope: policy-engine
    reason: >-
      §93.2 gibt den Major-Threshold wieder; die Aggregationsregel der
      Policy-Engine normiert FK-33.
  - target: FK-33
    scope: deterministic-checks
    reason: >-
      §93.8 gibt Mindestgroessen deterministischer Checks wieder; die Checks
      selbst normiert FK-33.
  - target: FK-33
    scope: stage-registry
    reason: >-
      §93.8 gibt Schwellwerte wieder, die an Stage-Definitionen haengen; die
      Stage-Registry normiert FK-33.
  - target: FK-20
    scope: feedback-loop
    reason: >-
      §93.2 gibt die maximale Zahl Feedback-Runden wieder; die Schleife selbst
      normiert FK-20.
  - target: FK-20
    scope: workflow-engine
    reason: >-
      §93.2 gibt Werte wieder, die den Workflow-Abbruch steuern; die
      Zustandsmaschine normiert FK-20.
  # --- 93.3 VektorDB -----------------------------------------------------
  - target: FK-13
    scope: vectordb
    reason: >-
      §93.3 gibt Retrieval-Schwellwerte wieder; Bedeutung und Wirkung normiert
      FK-13.
  # --- 93.4 Telemetrie und Budget ---------------------------------------
  - target: FK-68
    scope: telemetry
    reason: >-
      §93.4 gibt Web-Call-Limit und -Warnung wieder; das Telemetrie- und
      Budgetmodell normiert FK-68.
  # --- 93.5 / 93.6 Governance-Beobachtung -------------------------------
  - target: FK-35
    scope: governance-observation
    reason: >-
      §93.5 und §93.6 geben Schwellwerte und Risikopunkte der
      Governance-Sensorik wieder; beide normiert FK-35.
  - target: FK-35
    scope: integrity-gate
    reason: >-
      §93.8 gibt Mindestgroessen wieder, gegen die das Integrity-Gate prueft;
      das Gate normiert FK-35.
  - target: FK-35
    scope: escalation
    reason: >-
      §93.6 fuehrt Sofort-Stopp-Signale; die Eskalationswirkung normiert FK-35.
  - target: DK-03
    scope: governance
    reason: >-
      §93.5 und §93.6 dienen der fachlichen Governance-Regel; deren
      Domaenensicht liegt in DK-03.
  # --- 93.5a Permission-Runtime -----------------------------------------
  - target: FK-42
    scope: ccag-tools
    reason: >-
      §93.5a gibt Fristen der Permission-Runtime wieder; die Runtime normiert
      FK-42.
  - target: FK-55
    scope: principal-capability-model
    reason: >-
      §93.5a gibt Lease- und Request-Fristen wieder; das Capability-Modell
      normiert FK-55.
  - target: FK-55
    scope: story-scoped-capabilities
    reason: >-
      §93.5a begrenzt offene Requests je Run; die Story-Scope-Durchsetzung
      normiert FK-55.
  # --- 93.7 LLM-Evaluator ------------------------------------------------
  - target: FK-11
    scope: llm-evaluator
    reason: >-
      §93.7 gibt Aufruf-, Laengen- und Retry-Grenzen des Evaluators wieder; der
      Evaluator wird in FK-11 normiert.
  - target: FK-11
    scope: llm-provider
    reason: >-
      §93.7 gibt Send-Timeout und Acquire-Retries wieder; das Provider- und
      Pool-Verhalten normiert FK-11.
  - target: FK-11
    scope: prompt-execution
    reason: >-
      §93.7 gibt die maximale Description-Laenge wieder, die im Prompt
      durchgesetzt wird; die Prompt-Ausfuehrung normiert FK-11.
  # --- 93.9 / 93.12 Story-Locks und Story-Groessen -----------------------
  - target: FK-02
    scope: domain-model
    reason: >-
      §93.9 gibt die Freigabe-Regel fuer Story-Locks wieder und §93.12 die
      Story-Groessen; beide sind im Domaenenmodell FK-02 normiert.
  - target: FK-10
    scope: locking
    reason: >-
      §93.9 und §93.9a geben Lock-Dateien und ihre Fristen wieder; der
      Sperrmechanismus als Laufzeitthema ist in FK-10 normiert.
  - target: FK-21
    scope: story-classification
    reason: >-
      §93.12 gibt die Groessenklassen wieder; ihre Zuordnung normiert FK-21.
  # --- 93.9a Concept-Incubator ------------------------------------------
  - target: FK-78
    scope: concept-incubation-technical
    reason: >-
      §93.9a gibt TTL, Wartefrist und Wiederholungsfrist des Mutations-Mutex
      wieder; normiert sind sie in FK-78 §78.4.
  - target: FK-78
    scope: concept-toolchain
    reason: >-
      §93.9a benennt Werte, die die Inkubator-Toolchain durchsetzt; die
      Toolchain-Vertraege normiert FK-78.
  # --- 93.10 Review-Haeufigkeit -----------------------------------------
  - target: FK-24
    scope: story-types
    reason: >-
      §93.10 gibt Review-Minima je Story-Groesse wieder; Story-Typ und
      Terminalitaet normiert FK-24.
  - target: DK-11
    scope: review-quality
    reason: >-
      §93.10 dient der fachlichen Review-Qualitaetsregel; deren Domaenensicht
      liegt in DK-11.
  # --- 93.11 Failure Corpus ---------------------------------------------
  - target: FK-41
    scope: failure-corpus
    reason: >-
      §93.11 gibt Aufnahmeschwelle und Zielwerte des Failure-Corpus wieder;
      normiert sind sie in FK-41.
  - target: FK-41
    scope: pattern-promotion
    reason: >-
      §93.11 gibt die Promotionsregel (3x / 30 Tage) wieder; sie ist in FK-41
      normiert.
  - target: FK-41
    scope: check-factory
    reason: >-
      §93.11 gibt Deaktivierungszeitraum und FP-Schwelle der Check-Factory
      wieder; normiert sind sie in FK-41.
supersedes: []
superseded_by:
tags: [defaults, thresholds, timeouts, configuration, reference]
formal_scope: prose-only
---

# 93 — Standardwerte, Schwellwerte und Timeouts

## 93.0 Aufnahmekriterium — was in diesen Katalog gehoert

Der Katalog ist kein Sammelbecken fuer jede Zahl im Code. Massgeblich ist
**externe Wahrnehmbarkeit**:

- **In den Katalog gehoert ein Wert, wenn ein Betreiber ihn am Verhalten
  des Systems bemerkt** — weil er eine Wartezeit, eine Frist, eine
  Ablehnung, eine Blockade oder eine Mengenbegrenzung erklaert, die
  jemand von aussen sieht und gegen die er diagnostiziert. Solche Werte
  brauchen einen benannten Ort, an dem sie nachschlagbar sind, auch wenn
  sie fest im Code stehen (Spalte `Quelle`).
- **Im Code bleibt ein Wert, wenn er reines internes Tuning ist** — Poll-
  und Probe-Intervalle, Puffergroessen, Kadenzen. Sie sind ohne Wirkung
  auf das, was ein Betreiber beobachtet; ihre Aenderung veraendert kein
  zugesagtes Verhalten, sondern nur dessen Kosten.

Abwesenheit eines vergleichbaren Werts ist **kein** Argument gegen die
Aufnahme eines neuen: dass ein verwandter Wert bisher fehlt, heisst nur,
dass er ebenfalls fehlt. Entschieden wird nach dem Kriterium, nicht nach
dem Praezedenzfall.

### 93.0.1 Autoritaet des Katalogs — Nachschlageort, nicht Normquelle

Dieser Abschnitt (das Aufnahmekriterium) ist die **einzige** eigene Norm des
Katalogs; sie ist der Inhalt des Scopes `defaults`, den FK-93 besitzt. **Jede**
Zeile in den Abschnitten §93.1 bis §93.12 gibt dagegen einen Wert wieder,
dessen normativer Owner ein **anderes** Dokument ist. Der Katalog aendert an
diesen Werten nichts; er macht sie an einem Ort nachschlagbar.

FK-93 verlangt daher von sich selbst:

- **Jeder Abschnitt dieses Katalogs traegt eine scope-qualifizierte
  `defers_to`-Kante auf den Owner der Werte, die er wiedergibt.** Ohne sie
  beansprucht FK-93 Autoritaet, die es nicht hat.
- **Die Spalte `Kapitel` ersetzt diese Kante nicht.** Sie ist ein Lesehinweis
  fuer Menschen; die Kante ist maschinenlesbare Frontmatter.
- **Ein neuer Abschnitt ohne passende Kante ist unvollstaendig.** Wer eine
  Katalogzeile ergaenzt, deren Owner hier noch keine Kante hat, ergaenzt
  beides in einem Zug.
- **Kein Abschnitt dieses Katalogs erklaert sich selbst zur Normquelle.** Steht
  ein Wert nirgendwo sonst, ist das eine Luecke beim besitzenden Dokument und
  wird dort geschlossen, nicht hier umgewidmet.

## 93.1 Pipeline-Konfiguration

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Config-Version | `"3.0"` | `config_version` | — | 03 |
| Multi-LLM | `true` (Pflicht) | `features.multi_llm` | FK-04-018 | 03 |
| VektorDB | `true` (Pflicht; `false` ist kein regulärer Abschaltwert) | `features.vectordb` | — | 03 |
| ARE | `false` | `features.are` | FK-09-001 | 03 |
| Telemetry | `true` | `features.telemetry` | — | 03 |
| Multi-Repo | `false` | `features.multi_repo` | — | 03 |
| Default-Zielprojekt-Scaffold | `false` (Opt-in) | Installer-Option `default_project_structure` / CLI `--default-project-structure` | — | 10, 50 |

## 93.2 Policy-Engine

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Major-Threshold | 3 | `policy.major_threshold` | FK-05-209 | 33 |
| Max Feedback-Runden | 3 | `policy.max_feedback_rounds` | — | 20 |

## 93.3 VektorDB

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Similarity-Schwellenwert | 0.7 | `vectordb.similarity_threshold` | FK-05-018 | 13 |
| Max LLM-Kandidaten | 5 | `vectordb.max_llm_candidates` | FK-05-020 | 13 |

## 93.4 Telemetrie und Budget

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Web-Call-Limit (nur Research) | 200 | `telemetry.web_call_limit` | FK-08-019 | 68 |
| Web-Call-Warnung (nur Research) | 180 | `telemetry.web_call_warning` | FK-08-019 | 68 |

## 93.5 Governance-Beobachtung

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Risikoscore-Schwelle | 30 | `governance.risk_threshold` | — | 35 |
| Rolling-Window-Breite | 50 Events | `governance.window_size` | — | 35 |
| Cooldown | 300 Sekunden | `governance.cooldown_s` | FK-06-128 | 35 |

## 93.5a Permission-Runtime und Requests

| Parameter | Default (FK-Soll) | Config-Pfad | FK | Kapitel |
|-----------|-------------------|-------------|-----|---------|
| Permission-Request-TTL | 1800s (30 Min) | `permissions.request_ttl_s` | — | 42 / 55 |
| Permission-Pause-TTL | 3600s (60 Min) | `permissions.pause_ttl_s` | — | 42 / 55 |
| Permission-Lease-TTL | `run_scoped` | `permissions.lease_ttl` | — | 55 |
| External-Prompt-Grace in Story-Run | 0s | `permissions.story_execution_external_prompt_grace_s` | — | 42 / 55 |
| Max offene Permission-Requests pro Run | 1 | `permissions.max_open_requests_per_run` | — | 55 |

## 93.6 Risikopunkte (Governance-Sensorik)

Die folgende Punktetabelle gibt die Gewichtungen der Governance-Sensorik
nachschlagbar wieder. Normquelle ist **FK-35** (Scope `governance-observation`,
Sofort-Stopp zusaetzlich `escalation`) — die frueher hier stehende Behauptung,
FK-93 sei die Sollwert-Quelle, war doppelte Ownership gegenueber FK-35, das
dieselbe Tabelle fuehrt (§93.0.1).

| Signal | Punkte | FK | Kapitel |
|--------|--------|-----|---------|
| Orchestrator liest/schreibt Code | +10 | FK-06-099 | 35 |
| Orchestrator Bash ohne Sub-Agent | +8 | FK-06-100 | 35 |
| Schreiben außerhalb Story-Scope | +8 | FK-06-101 | 35 |
| >= 3 identische QA-Fails | +15 | FK-06-104 | 35 |
| Kein Phasenfortschritt >= 4h | +12 | FK-06-105 | 35 |
| Hoher Edit-Revert-Churn | +10 | FK-06-106 | 35 |
| Sub-Agent scheitert mehrfach | +12 | FK-06-107 | 35 |
| Wiederholte Drifts | +15 | FK-06-108 | 35 |
| Governance-Dateien verändert | **Sofort-Stopp** | FK-06-102 | 35 |
| Secret-Zugriff | **Sofort-Stopp** | FK-06-103 | 35 |

## 93.7 LLM-Evaluator

| Parameter | Default | Quelle | FK | Kapitel |
|-----------|---------|--------|-----|---------|
| Max LLM-Aufrufe pro Check | 2 (1 + 1 Retry) | Fest im Code | FK-05-163 | 11 |
| Max Description-Länge | 300 Zeichen | Im Prompt + Validierung | FK-05-158 | 11 |
| Send-Timeout | 2400s (40 Min) | Fest im Code | — | 11 |
| Acquire-Retries | 5 | Fest im Code | — | 11 |

## 93.8 Structural Checks

| Parameter | Default | Quelle | FK | Kapitel |
|-----------|---------|--------|-----|---------|
| Min Protocol-Größe | 50 Bytes | Fest im Code | — | 33 |
| Min Structural-Artefakt-Größe | 500 Bytes | Fest im Code | FK-06-077 | 35 |
| Min Check-Anzahl | 5 | Fest im Code | FK-06-077 | 35 |
| Min Decision-Größe | 200 Bytes | Fest im Code | FK-06-078 | 35 |
| Min Adversarial-Artefakt-Größe | 200 Bytes | Fest im Code | — | 35 |

## 93.9 Lock-Dateien

Dieser Abschnitt gilt **ausschliesslich fuer Story-Locks** (Kapitel 02). Andere
Sperrmechanismen mit eigener Norm sind nicht erfasst — insbesondere nicht der
Mutations-Mutex und die Koordinations-Klinke des Concept-Incubators (§93.9a,
FK-78 §78.4), deren TTL-basierte Uebernahme dort ausdruecklich normiert ist.

| Parameter | Default | Quelle | Kapitel |
|-----------|---------|--------|---------|
| Automatische Freigabe eines Story-Locks (TTL/PID) | Entfällt — Story-Locks enden nur über offizielle Pfade (Closure, Exit, Reset, Split, Ownership-Transfer); Stale-Anzeige nur als Information | Fest im Code | 02 |

## 93.9a Concept-Incubator: Mutations-Mutex und Koordinations-Klinke

Alle drei Werte sind extern wahrnehmbar (§93.0): sie erklaeren, wie lange
ein Schreiber wartet, wie lange ein Lauf-Verzeichnis nach einem Absturz
blockiert bleibt und ab wann eine nicht ausfuehrbare Wirkung als
blockierender Befund gemeldet wird.

Abgrenzung zu §93.9: Mutex und Klinke des Concept-Incubators sind **keine
Story-Locks**. Fuer sie ist die TTL-basierte Uebernahme eines verwaisten
Halters ausdruecklich vorgesehen (FK-78 §78.4) — das Verbot automatischer
TTL-Freigabe aus §93.9 gilt fuer Story-Locks und beruehrt sie nicht.

| Parameter | Default | Quelle | FK | Kapitel |
|-----------|---------|--------|-----|---------|
| TTL von `RUN.mutex` und `RUN.mutex.intent` (Uebernahme nach Absturz) | 600s (10 Min) | Fest im Code (`MUTEX_TTL_SECONDS`) | — | 78.4 |
| Wartefrist auf eine lebende fremde Klinke, danach fail-closed | 5s | Fest im Code (`INTENT_WAIT_SECONDS`) | — | 78.4 |
| Wiederholungsfrist geschuldeter Datei-Wirkungen (Loeschen, atomares Ersetzen, Advisory-Lock) | 5s | Fest im Code (`FILE_EFFECT_RETRY_SECONDS`) | — | 78.4 |

Bewusst **nicht** im Katalog, weil reines internes Tuning ohne extern
beobachtbare Zusage: das Poll-Intervall der Warteschleife
(`INTENT_POLL_SECONDS`) und die Probe-Kadenz, mit der ein Wartender die
Payload der Klinke nachliest (`INTENT_PROBE_SECONDS`).

## 93.10 Review-Häufigkeit

| Story-Größe | Min Reviews | FK | Kapitel |
|-------------|-----------|-----|---------|
| XS, S | 1 | FK-05-119 | 24 |
| M | 2 | FK-05-120 | 24 |
| L, XL | 3 | FK-05-121 | 24 |

## 93.11 Failure Corpus

| Parameter | Default | Quelle | FK | Kapitel |
|-----------|---------|--------|-----|---------|
| Aufnahmeschwelle: Rework-Zeit | 30 Minuten | Fest im Code | FK-10-016 | 41 |
| Ziel: Incidents/Monat | < 20 | Richtlinie | FK-10-017 | 41 |
| Pattern-Promotion: Wiederholung | 3x / 30 Tage | Fest im Code | FK-10-032 | 41 |
| Check-Deaktivierung: Zeitraum | 90 Tage | Fest im Code | FK-10-080 | 41 |
| Check-Deaktivierung: FP-Schwelle | > 3 (mehr als 3) | Fest im Code | FK-10-080 | 41 |
| Wirksamkeits-Report | Nach 30 Tagen | Fest im Code | FK-10-077 | 41 |

## 93.12 Story-Größen

| Größe | Beschreibung | Review-Minimum |
|-------|-------------|---------------|
| XS | Triviale Änderung (1-2 Dateien) | 1 |
| S | Kleine Änderung (ein Modul) | 1 |
| M | Mittlere Änderung (mehrere Dateien, ein Modul) | 2 |
| L | Große Änderung (mehrere Module) | 3 |
| XL | Sehr große Änderung (architekturwirksam) | 3 |
