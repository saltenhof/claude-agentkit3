---
concept_id: FK-75
title: Multi-LLM-Hub — Foundation-Adapter zum externen Hub
module: multi-llm-hub
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: hub-adapter-contract
  - scope: hub-management-ui-data
defers_to:
  - target: FK-07
    scope: component-architecture
    reason: Bluttyp-Klassifizierung als R-Foundation laeuft ueber FK-07
  - target: FK-91
    scope: api-catalog
    reason: API-Vertrag laeuft ueber FK-91
  - target: FK-44
    scope: prompt-runtime
    reason: fachliche Routing-Regeln (welches Modell fuer welche Phase) leben in prompt_runtime, nicht hier
supersedes: []
superseded_by:
tags: [multi-llm-hub, foundation, llm-pools, adapter]
formal_scope: prose-only
---

# 75 — Multi-LLM-Hub

## 75.1 Zweck

Multi-LLM-Hub ist ein **Foundation-Adapter** (Bluttyp R) zum externen
Multi-LLM-Hub-System. Der Hub selbst ist eine **Pflicht-Dependency**
von AK3, aber **kein AK3-Code** — er ist Nachbarsystem.

AK3 nutzt den Hub fuer Sessions, Backend-Slot-Belegung,
Multi-Target-Sends an LLM-Provider (ChatGPT, Gemini, Grok, Qwen,
Kimi, …). Dieses Foundation-Modul stellt den Adapter dazu bereit.

## 75.2 Verantwortung

| Aufgabe | Inhalt |
|---|---|
| **Session-Lifecycle** | acquire/release/resume von Hub-Sessions ueber die externe Hub-API |
| **Backend-Status** | Slot-Auslastung, Health, Error-Listen — Leseproxy auf den Hub |
| **Send-Operationen** | broadcast/group/single an die Hub-API durchreichen |
| **Hub-Cockpit-Read-Models** | Sessions, Backend-Metriken, Holders in Form, die das Frontend rendern kann |

## 75.3 Was Multi-LLM-Hub nicht tut

- **Kein eigenes Routing.** „Welches Modell fuer welche Pipeline-Phase"
  ist eine fachliche Entscheidung — sie gehoert nach `prompt_runtime`
  (FK-44), wenn AK3 sie ueberhaupt selbst trifft. Der Hub-Adapter
  liefert nur die Mittel.
- **Kein eigenes Quota- oder Cost-Modell.** Wenn AK3 fachliche
  Quotas/Cost-Limits einfuehrt, leben sie in `prompt_runtime`, nicht
  hier. Der Hub-Adapter setzt nur um, was er von oben bekommt.
- **Kein Hub-Frontend-Hosting.** Das Hub-eigene UI lebt im
  Hub-Repository, nicht in AK3. AK3 bietet mit dem Hub-Cockpit
  (FK-72) eine **eigene** Sicht auf die Hub-Daten, die fuer
  AK3-Nutzer relevant sind.

## 75.4 Datenfluss

```
Multi-LLM-Hub (extern)  ◄──REST──►  agentkit.multi_llm_hub  ──►  control_plane_http
                                            │                          │
                                            └──►  Konsumenten:         ▼
                                                  - prompt_runtime   /v1/hub
                                                  - Frontend Hub-Cockpit
```

## 75.5 API-Endpunkte (Auswahl)

Offiziell katalogisiert in **FK-91**.

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/v1/hub/status` | Pool-Uebersicht, Backend-Health |
| `GET` | `/v1/hub/sessions` | aktive und resumable Sessions |
| `POST` | `/v1/hub/sessions` | acquire (proxy zur externen Hub-API) |
| `POST` | `/v1/hub/sessions/{id}/messages` | send (broadcast/group/single, proxy) |
| `POST` | `/v1/hub/sessions/{id}/release` | release (proxy) |

Der Adapter setzt Auth, Retry und Fehlerbehandlung um. Er traegt
keine eigene fachliche Aussage; das ist Eigenschaft eines R-Adapters
nach FK-07 §7.3.

## 75.6 Bluttyp und Klassifizierung

Multi-LLM-Hub ist **`adapter_boundary`** (FK-07 §7.3):

- **Bluttyp R**, weil er ein externes System adaptiert.
- Kein A-BC, weil AK3 das Hub-Konzept fachlich nicht besitzt.
- Im Lint-Tool als `boundary_module` mit
  `bloodgroup: R, boundary_kind: adapter_boundary` modelliert
  (`entities.md`).

## 75.7 Frontend-Slice

Das Hub-Cockpit im Frontend lebt unter
`frontend/src/foundation/multi_llm_hub/` und nutzt die REST-API von
75.5. Inhalt: Session-Liste, Backend-Metrik-Karten,
Multi-Target-Chat-Sicht. Detail siehe FK-72 §72.5 Sicht 5.

## 75.8 Verhalten bei Hub-Ausfall

Der Hub ist Pflicht-Dependency. Wenn er nicht erreichbar ist, schlagen
LLM-getriebene Pipeline-Phasen fehl. Der Adapter meldet
Verbindungsfehler als technische Errors; die fachliche Reaktion
(Fail-Closed, Retry-Strategie, Pause) liegt bei den Konsumenten
(`prompt_runtime`, `pipeline_engine`).
