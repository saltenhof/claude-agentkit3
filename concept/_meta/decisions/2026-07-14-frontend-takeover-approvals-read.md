---
concept_id: META-DEC-2026-07-14-FRONTEND-TAKEOVER-APPROVALS-READ
title: Concept-Decision-Record — Frontend-Takeover-Approvals-Read
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, frontend, takeover, governance, AG3-153]
formal_scope: prose-only
---

# Concept-Decision-Record — Frontend-Takeover-Approvals-Read

Datum: 2026-07-14. Record gemaess META-CONCEPT-CONSISTENCY P3,
auf Grundlage des Design Freeze fuer AG3-153.

## 1. Anlass

FK-91 §91.8.2 verlangt fuer den lossy projektuebergreifenden
Governance-Stream bei jedem Connection-Aufbau einen Initial-GET des
fachlichen Read-Models
`frontend-contracts.entity.takeover_approval_request`. FK-91 §91.1a
enthielt fuer diesen bereits normierten Read noch keine HTTP-Bindung.
Ohne diese Bindung koennte das globale Frontend-Overlay einen
Event-Verlust oder den Zustand „approved mit frischer pending
Challenge“ nicht deterministisch rekonstruieren.

## 2. Entscheidung

`GET /v1/governance/takeover-approvals` ist die read-only,
projektuebergreifende HTTP-Bindung fuer offene Takeover-Freigaben.
Der Endpoint ist ausschliesslich fuer eine authentifizierte
Strategen-Cookie-Session zulaessig und projiziert die formale Entity
aus der persistenten Approval-Queue zusammen mit der aktuell
verknuepften Challenge des Owner-BC. Reads nehmen keinen Claim und
keine Story-Sperre. Der Endpoint erzeugt keine zweite Approval-
Wahrheit und keine neue Tabelle; K5 bleibt Postgres-only.

## 3. Alternativen

- Reines Vertrauen auf SSE wurde verworfen, weil FK-91 §91.8.2 den
  Stream ausdruecklich als lossy definiert.
- Projektweises Frontend-Polling wurde verworfen, weil es
  projektuebergreifende Freigaben von der aktuellen Projektauswahl
  abhaengig machen und den globalen Stream umgehen wuerde.
- Eine neue Read-Model-Tabelle wurde verworfen, weil Approval und
  Challenge bereits autoritativ im Story-Lifecycle-Owner vorliegen.
- Thin-Client-Token-Auth wurde verworfen; FK-91 §91.8.1 bindet die
  globale Governance-Freigabe an den menschlichen UI-BFF-Pfad.

## 4. Impact-Sweep (P3)

Der Sweep ueber FK-91, FK-72, FK-56, die formalen
Frontend-Vertraege, die vorhandenen Ownership-Endpoints und die
Postgres-Persistenz bestaetigt genau eine fehlende Konzeptbindung:
die Endpoint-Zeile in FK-91 §91.1a. FK-91 §91.8.1/§91.8.2/§91.8.3,
FK-72 §72.4/§72.14.7 und
`frontend-contracts.entity.takeover_approval_request` normieren
Skoping, Re-Sync, Slot und Feldform bereits und werden nicht
geaendert. Es entstehen weder ein neues Schema noch neue
Transfer-Semantik oder Ownership-Wirkungen.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-91 §91.1a | geaendert | Fehlende HTTP-Bindung des bereits normierten Initial-GET wird nachgezogen. |
| FK-91 §91.8.1/§91.8.2/§91.8.3 | geprueft, nicht geaendert | Globaler Stream, Lossy-Re-Sync und Governance-Topic tragen die Entscheidung bereits. |
| FK-72 §72.4/§72.14.7 | geprueft, nicht geaendert | Shell-Slot, globaler Overlay und Initial-GET-Recovery sind bereits normiert. |
| FK-56 §56.13b/§56.13c | geprueft, nicht geaendert | Menschliche Freigabe und Verlustkorridor bleiben unveraendert. |
| `formal.frontend-contracts` | geprueft, nicht geaendert | Entity, Commands und Event bleiben autoritativ und unveraendert. |
| `state-storage` / K5 | nicht betroffen | Keine neue Tabelle; der sanktionierte Postgres-Read verbindet bestehende Records. |
| Ownership-Transfer-Mechanik | nicht betroffen | Read und Stream besitzen keine Ownership-Wirkung. |
