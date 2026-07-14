---
concept_id: META-DEC-2026-07-14-CCAG-CENTRAL-OWNER
title: Concept-Decision-Record — CCAG-Central-Owner
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, ccag, permissions, persistence, governance, AG3-131]
formal_scope: prose-only
---

# Concept-Decision-Record — CCAG-Central-Owner

Datum: 2026-07-14. Record gemaess META-CONCEPT-CONSISTENCY P3 und
W4, auf Grundlage des Design Freeze fuer AG3-131.

## 1. Anlass

FK-10 §10.1.0 I5 und §10.3.1/§10.3.2 verlangen fuer K5 eine
zentrale Postgres-Wahrheit. CCAG-Permission-Requests und -Leases
lagen bisher produktiv in lokalen SQLite-Dateien; die Identitaet der
Mode-Lock-Holder lag nur in Story-Markern. Damit konnten lokale
Artefakte eine zweite Governance-Wahrheit bilden und ein zentral
nicht persistierter Request blieb fuer Menschen unsichtbar.

## 2. Entscheidung

Permission-Requests, Permission-Leases und Mode-Lock-Holder-
Identitaeten besitzen genau einen kanonischen Owner in Postgres.
Der Hook oeffnet und liest Requests sowie konsumiert Leases ueber
die Control-Plane-REST-API mit passendem Projekt-Token. Nur eine
authentifizierte Strategen-Cookie-Session darf Requests entscheiden
oder Leases gewähren; diese Autorisierung erfolgt vor der Mutation.
Ein Grant erzeugt nur die gebundene Lease und setzt den Run nicht
fort.

Lokale Request-/Lease-Dateien, der Mode-Lock-Marker und
`permission_state.json` sind hoechstens kurzlebige, verwerfbare
Read-Projektionen. Fehlen, Ablauf oder Divergenz blockieren
fail-closed und erlauben keinen Rueckfall auf lokale Wahrheit.
Unentschiedene abgelaufene Requests werden beim naechsten zentralen
Zugriff deterministisch als `expired` mit `resolution=denied`
materialisiert. Ein Fehler beim zentralen Oeffnen eines Requests ist
ein sichtbarer benannter Block-Fault.

## 3. Alternativen

- SQLite als kanonischer Hook-Store wurde verworfen, weil dies I5
  sowie die serververmittelte Dev↔Core-Grenze verletzt.
- Dual Writes nach Postgres und lokal wurden verworfen, weil sie
  Recovery und Konfliktaufloesung auf zwei Wahrheiten verteilen.
- Der lokale Mode-Lock-Marker als Release-Owner wurde verworfen;
  nur `(project_key, story_id, run_id)` im zentralen Holder-Set
  bestimmt Recovery und Release.
- Automatisches Resume nach Lease-Grant wurde verworfen, weil eine
  menschliche Freigabe keine Run-Transition impliziert.
- Daemon-getriebene Expiry wurde verworfen; FK-55 subsection 55.10.9a bindet
  die Materialisierung an den naechsten Zugriff.

## 4. Impact-Sweep (P3/W4)

Der Sweep umfasst FK-10 §10.1.0 I5/§10.3.1/§10.3.2, FK-42
§42.1/§42.5/§42.7, FK-55 §55.9a/§55.10.4/§55.10.4a and subsection 55.10.9a,
FK-91 §91.1a, die formalen Principal-Capability-Vertraege, den
State-Backend-Schema-Owner, Hook-REST, Setup/Closure und lokale
Projektionen. Die lokalen CCAG-Regeldateien bleiben unveraenderte
Konfiguration. Keine andere Capability- oder Story-Ownership-
Semantik wird erweitert.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-10 I5/§10.3.1/§10.3.2 | bestaetigt | Postgres ist der einzige K5-Owner; Dev greift serververmittelt zu. |
| FK-42 §42.1/§42.5 | bestaetigt | CCAG bleibt letzte Komfortschicht; unbekannte Story-Mutation blockiert und oeffnet zentral. |
| FK-42 §42.7 | geprueft, nicht geaendert | Projektlokale Rule-YAML bleibt Konfiguration, nicht Runtime-State. |
| FK-55 §55.9a/§55.10.4 | formalisiert | Scope-Bindung, Auth-Split, `max_uses` und No-Auto-Resume werden gepinnt. |
| FK-55 §55.10.4a and subsection 55.10.9a | formalisiert | Projektionen blockieren bei Divergenz; Expiry wird lazy denied. |
| FK-91 §91.1a | geaendert | HTTP-Bindungen fuer Request-Read/Open/Resolve und Lease-Grant/Consume werden nachgezogen. |
| `formal.principal-capabilities.entities` | geaendert | Request-Status/Audit und Lease-Verbrauch vervollstaendigen die Persistenzform. |
| `formal.principal-capabilities.commands` | geaendert | REST- und Auth-Bindung sowie getrenntes Grant/Consume werden normiert. |
| `formal.principal-capabilities.invariants` | geaendert | Zentraler Owner, Projection-Fail-Closed, Auth-Split und No-Auto-Resume werden explizit. |
| `formal.principal-capabilities.events` | geaendert | Atomarer Lease-Verbrauch erhaelt ein formales Lifecycle-Event. |
| State-Backend / Mode-Lock | geaendert | Holder-Child-Set ist Recovery-Wahrheit; Summary wird atomar daraus abgeleitet. |
| Lokale CCAG-Regeln | nicht betroffen | `.agentkit/ccag/rules/` bleibt lokale Policy-Konfiguration. |

## 6. P4-Formalisierungspruefung

Ja. Die Entscheidung ist als formale Entity-, Command-, Invariant-
und Event-Aenderung ausdrueckbar und wurde dort umgesetzt. Es ist
kein Baseline-Eintrag fuer einen unformalisierten W2-/W3-Befund
erforderlich.
