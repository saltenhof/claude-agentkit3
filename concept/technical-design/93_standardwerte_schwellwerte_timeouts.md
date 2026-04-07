---
concept_id: FK-93
title: Standardwerte, Schwellwerte und Timeouts
module: defaults
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: defaults
defers_to: []
supersedes: []
superseded_by:
tags: [defaults, thresholds, timeouts, configuration, reference]
---

# 93 — Standardwerte, Schwellwerte und Timeouts

## 93.1 Pipeline-Konfiguration

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Config-Version | `"3.0"` | `config_version` | — | 03 |
| Multi-LLM | `true` (Pflicht) | `features.multi_llm` | FK-04-018 | 03 |
| VektorDB | `false` | `features.vectordb` | — | 03 |
| ARE | `false` | `features.are` | FK-09-001 | 03 |
| Telemetry | `true` | `features.telemetry` | — | 03 |
| Multi-Repo | `false` | `features.multi_repo` | — | 03 |

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
| Web-Call-Limit (nur Research) | 200 | `telemetry.web_call_limit` | FK-08-019 | 14 |
| Web-Call-Warnung (nur Research) | 180 | `telemetry.web_call_warning` | FK-08-019 | 14 |

## 93.5 Governance-Beobachtung

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Risikoscore-Schwelle | 30 | `governance.risk_threshold` | — | 35 |
| Rolling-Window-Breite | 50 Events | `governance.window_size` | — | 35 |
| Cooldown | 300 Sekunden | `governance.cooldown_s` | FK-06-128 | 35 |

## 93.6 Risikopunkte (Governance-Sensorik)

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

| Parameter | Default | Quelle | Kapitel |
|-----------|---------|--------|---------|
| Lock-TTL | 86400s (24h) | In Lock-Datei | 02 |
| PID-Prüfung | Primär (vor TTL) | Fest im Code | 02 |

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
