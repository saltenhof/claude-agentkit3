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
defers_to: []
supersedes: []
superseded_by:
tags: [defaults, thresholds, timeouts, configuration, reference]
formal_scope: prose-only
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
| Default-Zielprojekt-Scaffold | `false` (Opt-in) | Installer-Option `default_project_structure` / CLI `--default-project-structure` | — | 10, 50 |

## 93.2 Policy-Engine

**Status: KONFORM (kein Nachzug noetig)**

Code-Werte stimmen mit FK-93 ueberein:
`verify_system/remediation/loop_counter.py:40` (`DEFAULT_MAX_FEEDBACK_ROUNDS = 3`),
`verify_system/policy_engine/engine.py:31` (`DEFAULT_MAJOR_THRESHOLD: int = 3`).

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Major-Threshold | 3 | `policy.major_threshold` | FK-05-209 | 33 |
| Max Feedback-Runden | 3 | `policy.max_feedback_rounds` | — | 20 |

## 93.3 VektorDB

**Status: KONFORM**

Code-Werte stimmen mit FK-93 ueberein. Die Defaults sind in
`src/agentkit/backend/config/models.py:518-519` (`VectorDbConfig`) implementiert
und werden in `src/agentkit/backend/story_creation/vectordb_reconciliation.py:230-234`
aktiv genutzt. Der `integration_clients/vectordb/`-Pfad ist nicht der Owner dieser
Defaults — der kanonische Owner ist `VectorDbConfig` in `backend/config/models.py`.

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Similarity-Schwellenwert | 0.7 — **KONFORM** (`config/models.py:518`) | `vectordb.similarity_threshold` | FK-05-018 | 13 |
| Max LLM-Kandidaten | 5 — **KONFORM** (`config/models.py:519`) | `vectordb.max_llm_candidates` | FK-05-020 | 13 |

## 93.4 Telemetrie und Budget

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Web-Call-Limit (nur Research) | 200 | `telemetry.web_call_limit` | FK-08-019 | 14 |
| Web-Call-Warnung (nur Research) | 180 | `telemetry.web_call_warning` | FK-08-019 | 14 |

## 93.5 Governance-Beobachtung

**Status: KONFORM (implementiert durch AG3-085)**

Die Governance-Sensorik ist vollstaendig implementiert. Alle drei Defaults
stimmen mit FK-93 ueberein (verifiziert gegen
`src/agentkit/backend/governance/governance_observer/config.py`):
- `DEFAULT_RISK_THRESHOLD = 30` (`:20`)
- `DEFAULT_WINDOW_SIZE = 50` (`:18`)
- `DEFAULT_COOLDOWN_S = 300` (`:22`)

Config-Pfade sind ebenfalls gebunden via `GovernanceConfig` in
`src/agentkit/backend/config/models.py`.

| Parameter | Default | Config-Pfad | FK | Kapitel |
|-----------|---------|-------------|-----|---------|
| Risikoscore-Schwelle | 30 — **KONFORM** | `governance.risk_threshold` | — | 35 |
| Rolling-Window-Breite | 50 Events — **KONFORM** | `governance.window_size` | — | 35 |
| Cooldown | 300 Sekunden — **KONFORM** | `governance.cooldown_s` | FK-06-128 | 35 |

## 93.5a Permission-Runtime und Requests

**Status Permission-Request-TTL: KONFORM (implementiert durch AG3-086 + AG3-070)**

FK-93-Sollwert 1800s (30 Min) ist deckungsgleich mit dem Code:
`src/agentkit/backend/governance/ccag/requests.py:46` `DEFAULT_TTL_SECONDS: int = 1800`.
Der Config-Pfad `permissions.request_ttl_s` ist als getyptes Feld implementiert:
`src/agentkit/backend/config/models.py:570` `request_ttl_s: int = 1800` in
`PermissionsConfig`. Kein Drift. Kein PO-Klaerbedarf mehr.

| Parameter | Default (FK-Soll) | Config-Pfad | FK | Kapitel |
|-----------|-------------------|-------------|-----|---------|
| Permission-Request-TTL | 1800s (30 Min) — **KONFORM** (AG3-086 Code-Wert + AG3-070 Config-Pfad) | `permissions.request_ttl_s` | — | 42 / 55 |
| Permission-Pause-TTL | 3600s (60 Min) | `permissions.pause_ttl_s` | — | 42 / 55 |
| Permission-Lease-TTL | `run_scoped` | `permissions.lease_ttl` | — | 55 |
| External-Prompt-Grace in Story-Run | 0s | `permissions.story_execution_external_prompt_grace_s` | — | 42 / 55 |
| Max offene Permission-Requests pro Run | 1 | `permissions.max_open_requests_per_run` | — | 55 |

## 93.6 Risikopunkte (Governance-Sensorik)

**Status: KONFORM (implementiert durch AG3-085)**

Die folgende Punktetabelle ist normative FK-93-Sollwert-Quelle.
Die Governance-Sensorik ist implementiert (siehe §93.5). Signal-Gewichte
sind in `src/agentkit/backend/governance/governance_observer/models.py:54-62`
(`RISK_POINTS`-Dict) kodiert; alle Punkt-Werte entsprechen den
FK-93-Sollwerten (+10, +8, +8, +15, +12, +10, +12, +15).

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

**Status: KONFORM**

Alle vier Werte sind im Code implementiert. Der Owner ist
`src/agentkit/backend/verify_system/llm_evaluator/llm_client.py`, nicht
`integrations/llm_pools/` (dieses Verzeichnis enthaelt nur ein leeres
`__init__.py` und ist kein Owner dieser Konstanten).

| Parameter | Default | Quelle | FK | Kapitel |
|-----------|---------|--------|-----|---------|
| Max LLM-Aufrufe pro Check | 2 (1 + 1 Retry) | Fest im Code | FK-05-163 | 11 |
| Max Description-Länge | 300 Zeichen | Im Prompt + Validierung | FK-05-158 | 11 |
| Send-Timeout | 2400s (40 Min) — **KONFORM** (`llm_evaluator/llm_client.py:68` `SEND_TIMEOUT_SECONDS = 2400.0`) | Fest im Code | — | 11 |
| Acquire-Retries | 5 — **KONFORM** (`llm_evaluator/llm_client.py:78` `MAX_ACQUIRE_RETRIES = 5`) | Fest im Code | — | 11 |

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

**Status: KONFORM (AG3-078 abgeschlossen)**

Alle FK-93-relevanten Failure-Corpus-Schwellwerte sind im Code implementiert:

- `src/agentkit/backend/failure_corpus/incident_triage.py:53` `_REWORK_THRESHOLD_MIN = 30` (Aufnahmeschwelle 30 Min)
- `src/agentkit/backend/failure_corpus/pattern_promotion.py:74` `_REPETITION_WINDOW_DAYS = 30`, `:77` `_REPETITION_MIN_COUNT = 3`
- `src/agentkit/backend/failure_corpus/effectiveness.py:44` `_AUTO_DEACTIVATE_MIN_FP = 3` (fp > 3)
- `src/agentkit/backend/failure_corpus/effectiveness.py:119` `window_days: int = 90` (90-Tage-Fenster)
- `src/agentkit/backend/failure_corpus/effectiveness.py` `report_effectiveness()` ist der Wirksamkeits-Report-Einstiegspunkt

**ARCH-55-Status (bereits saniert):** `PromotionRule`- und `PatternRiskLevel`-Enum-Werte
in `src/agentkit/backend/failure_corpus/pattern.py` sind englisch:
`repetition`, `high_severity`, `favorable_checkability` (`pattern.py:49-51`);
`medium`, `high`, `critical` (`pattern.py:57-59`). Kein ARCH-55-Verstoss.

| Parameter | Default | Quelle | FK | Kapitel |
|-----------|---------|--------|-----|---------|
| Aufnahmeschwelle: Rework-Zeit | 30 Minuten — **KONFORM** (`incident_triage.py:53`) | Fest im Code | FK-10-016 | 41 |
| Ziel: Incidents/Monat | < 20 | Richtlinie | FK-10-017 | 41 |
| Pattern-Promotion: Wiederholung | 3x / 30 Tage — **KONFORM** (`pattern_promotion.py:74` window, `:77` min-count) | Fest im Code | FK-10-032 | 41 |
| Check-Deaktivierung: Zeitraum | 90 Tage — **KONFORM** (`effectiveness.py:119`) | Fest im Code | FK-10-080 | 41 |
| Check-Deaktivierung: FP-Schwelle | > 3 (mehr als 3) — **KONFORM** (`effectiveness.py:44`) | Fest im Code | FK-10-080 | 41 |
| Wirksamkeits-Report | Nach 30 Tagen — **KONFORM** (`effectiveness.py:report_effectiveness()`) | Fest im Code | FK-10-077 | 41 |

## 93.12 Story-Größen

| Größe | Beschreibung | Review-Minimum |
|-------|-------------|---------------|
| XS | Triviale Änderung (1-2 Dateien) | 1 |
| S | Kleine Änderung (ein Modul) | 1 |
| M | Mittlere Änderung (mehrere Dateien, ein Modul) | 2 |
| L | Große Änderung (mehrere Module) | 3 |
| XL | Sehr große Änderung (architekturwirksam) | 3 |
