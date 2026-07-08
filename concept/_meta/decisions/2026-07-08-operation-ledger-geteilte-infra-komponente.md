---
concept_id: META-DEC-2026-07-08-OPERATION-LEDGER
title: Concept-Decision-Record — Operation-Ledger als geteilte Infrastruktur-Komponente
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, operation-ledger, control-plane, persistence, state-storage, bc-cut]
formal_scope: prose-only
---

# Concept-Decision-Record — Operation-Ledger als geteilte Infrastruktur-Komponente

Datum: 2026-07-08. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

Die Zerlegung der Persistence-Gesamtfassade
(`agentkit.backend.state_backend.store`, ~148 Funktionen ueber alle
Domaenen) in BC-aligned Stores plus geteilte Infrastruktur-Komponenten
(Zielbild-Design vom 2026-07-08: 12 Pro-BC-Stores +
`StateBackendConnectionManager`, `PersistenceJsonCodec`,
`PersistenceTestSupport`) hat eine Ownership-Frage aufgeworfen:

Wem gehoert der **Control-Plane-Operation-Ledger** — die Persistenz
der mutierenden Operationen (claim/finalize/commit/abort/repair),
der Inflight-Idempotenz (`op_id`, Body-Hash-Replay), der
Objekt-Mutation-Claims (Serialisierungsobjekte) sowie der daran
haengenden Instance-Identity- und Fence-Bindung?

Das Zielbild-Design schlug die Zuordnung zum BC
`governance-and-guards` vor („Idempotenz/Claims/Fencing =
Enforcement"). Die `domain-registry.yaml` kennt keinen
control-plane-BC; `control_plane` wird im BC-Cut-Decision-Log
durchgaengig als R-Frontend/Fassade gefuehrt (vgl. ARCH-57).

## 2. Entscheidung

Drei Festlegungen:

1. **Der Operation-Ledger wird als vierte geteilte
   Infrastruktur-Komponente `ControlPlaneOperationLedger` modelliert**
   — neben `StateBackendConnectionManager`, `PersistenceJsonCodec`
   und `PersistenceTestSupport`. Er ist **kein Fach-BC**, erhaelt
   **keinen Eintrag in `domain-registry.yaml`** und wird **nicht**
   `governance-and-guards` zugeordnet.
   - Klassifikation: T-Infrastruktur der Control-Plane-
     Transport-Boundary (Bluttyp T; Vokabular-Disziplin des
     BC-Cut-Logs: Komponente/Klasse/Schnittstelle).
   - Modul-Prefix: `agentkit.backend.state_backend.operation_ledger`.
   - Konsumenten-Regel: Konsument ist der Control-Plane-Dispatch
     (R-Fassade). Fach-BC-Stores importieren den Ledger nicht; ihre
     Commands deklarieren Serialisierungsobjekt und Idempotenz nur
     ueber den Katalog (FK-91 §91.1a Regeln 5/13).
   - Normative Heimat der Regeln bleibt unveraendert: FK-91 §91.1a
     (Regel 5 Idempotenz, Regel 13 Serialisierungsobjekt, Regel 15
     Ownership-Fencing beim Commit, Regel 17 Reconcile ueber
     `GET /v1/project-edge/operations/{op_id}`) sowie
     `formal.state-storage` (`state-storage.entity.
     inflight-operation-record`, `state-storage.entity.
     object-mutation-claim`, CAS-Finalize-/Claim-Invarianten) und
     FK-10 §10.5 (instanzgebundene Claims, Start-Rekonsiliierung,
     Betriebsannahme „genau eine aktive Control-Plane-Writer-Instanz
     pro Datenbank"). Dieser Record ordnet nur die
     Komponenten-Ownership; er normiert keine neue Mechanik.
2. **Zerlegung des im Design gebuendelten Pakets** (Ledger +
   instance-identity + ownership-fences), weil die Bestandteile
   verschiedene kanonische Heimaten haben:
   - **Ownership-Fences:** Run-Ownership-Record inkl. Aktiv-Invariante
     und `ownership_epoch` → story-lifecycle-Persistenz; Guard-/
     Enforcement-Semantik (Takeover-Exklusivitaet, Modus-Aufloesung)
     → governance-and-guards. Bestaetigt bestehende Entscheidung
     META-DEC-2026-07-02-SESSION-OWNERSHIP (FK-02 §2.6, FK-56
     §56.8a/§56.13, FK-30 §30.6.3); keine Neuentscheidung. Die
     Fence-Pruefung beim Finalize (FK-91 §91.1a Regel 15) ist
     Ledger-Mechanik und liest den Ownership-Record als Cross-BC-Read
     (zulaessig nach FK-17 §17.5).
   - **Instance-Identity** (`backend_instance_id` + Boot-Inkarnation,
     Boot-Singleton, Start-Rekonsiliierung): Topologie-Infrastruktur
     des zentralen Core (DK-00 §1a, FK-01 §1.1a, FK-10 §10.5) →
     gehoert zur Infrastruktur-Komponente
     `StateBackendConnectionManager` (Instanz-/Verbindungs-Lifecycle).
     Der Ledger konsumiert die Identitaet fuer die Claim-Bindung.
   - **Inflight-Idempotenz-Helper** der bisherigen Fassade folgen dem
     Ledger.
3. **Capability-Abgrenzung zu governance-and-guards:**
   `admin_abort_inflight_operation` bleibt Operation-Klasse
   `admin_transition` (FK-55). governance-and-guards normiert
   weiterhin, **wer** abbrechen/reparieren darf (Principal/Capability);
   der Ledger verantwortet, **wie** der Abbruch transaktional wirkt
   (CAS gegen `operation_epoch`, audited Reconcile-Repair-Zustand,
   `formal.state-storage.invariants`). Diese Trennung ist der Grund,
   warum die Design-Intuition „Enforcement = governance" hier nicht
   zur Komponenten-Ownership fuehrt.

### Namensentscheidungen

- **`ControlPlaneOperationLedger`** (nicht `OperationStore`, nicht
  `GovernanceRuntimeStore`-Teil): „Control-Plane" benennt die Boundary,
  an der die FK-91-Regeln gelten; „Ledger" folgt dem im Zielbild-Design
  etablierten Sprachgebrauch (`control_plane_operation`-Ledger) und dem
  Buchungscharakter (claim → finalize, kein Update-in-place).
  Englische Bezeichner gemaess ARCH-55.
- Modul unterhalb `state_backend` (nicht unterhalb eines
  control-plane-Namespaces), weil die Komponente Persistenz-
  Infrastruktur ist und die R-Fassade sie nur konsumiert
  (Anti-Laundering: die R-Schnittstelle exponiert keine T-Typen).

## 3. Alternativen

- **Zuordnung zu governance-and-guards (Design-Vorschlag):**
  verworfen. governance-and-guards normiert Agent-Verhalten
  (Principals, Capabilities, Guards/Hooks, Integrity-Gate, Eskalation
  — FK-30/31/35/42/55). API-Transaktionssemantik ist dort fachfremd;
  kein Konzeptdokument stuetzt die Zuordnung, und die formale
  Verankerung liegt bereits im cross-cutting `state-storage`-Kontext.
  Die Zuordnung wuerde zwei Verantwortungen vermischen und dem BC eine
  zweite, konzeptfremde Fachlichkeit einpflanzen.
- **Neuer Registry-BC `control-plane-runtime`:** verworfen. Die
  Registry fuehrt bewusst keinen control-plane-BC; `control_plane` ist
  R-Fassade (ARCH-57, BC-Cut-Log). Ein neuer Fach-BC wuerde eine
  Fachlichkeit behaupten, die die Konzeptwelt nicht hat, und waere ein
  groesserer normativer Eingriff als noetig.
- **Aufschub:** verworfen. Die Store-Zerlegung haengt an dieser
  Entscheidung (Phase-2-Gate der Fassaden-Migration); ohne Owner
  muesste die Migration den Ledger im Compat-Shim zuruecklassen
  (ZERO-DEBT-Verstoss).

## 4. Impact-Sweep (P3)

Semantische Suche ueber den Konzept-Index (agentkit3-concepts:
`concept_search` u.a. „Control-Plane Operation Ledger Idempotenz claim
finalize", „Session-Ownership Run-Ownership Fencing", „Edge-Command
push-freshness") und lexikalische Sweeps ueber `concept/` am
2026-07-08 (ripgrep):

- `operation.?ledger|control_plane_operation|inflight` →
  FK-91 §91.1a (Regeln 5/13/15/17, Heimat der Transport-Regeln),
  FK-10 §10.5 (Claim-Bindung, Start-Rekonsiliierung),
  FK-55 (Operation-Klassen-Tabelle: `admin_abort_inflight_operation`
  unter `admin_transition`),
  `formal-spec/state-storage/entities.md`
  (`inflight-operation-record`, `object-mutation-claim`),
  `formal-spec/state-storage/invariants.md` (instanzgebundene Claims,
  CAS-Finalize, audited Admin-Abort),
  `formal-spec/architecture-conformance/invariants.md`
  (Funktions-Inventar `save/load_control_plane_operation_global`),
  `formal-spec/frontend-contracts/invariants.md`
  (`cancel_not_during_inflight` — Frontend-Verhalten, fachfremd).
- `instance.?identity|backend_instance` → FK-10 §10.5, FK-91 §91.1a,
  `formal-spec/state-storage/*` (dieselben Stellen wie oben).
- Registry-/BC-Cut-Pruefung: `domain-registry.yaml` (kein
  control-plane-BC), `bc-cut-decisions.md` (control_plane als
  R-Frontend; Vokabular-Disziplin; shared-Komponenten-Muster
  WorktreeManager).

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-91 §91.1a | nicht betroffen | bleibt normative Heimat der Transport-Regeln; dieser Record aendert keine Aussage, er ordnet Komponenten-Ownership |
| FK-10 §10.5 | nicht betroffen | Betriebsannahme und Claim-Bindung unveraendert; reines Referenzziel |
| formal.state-storage (entities, invariants) | nicht betroffen | bereits korrekte cross-cutting Heimat der Ledger-Entitaeten/-Invarianten; Record bestaetigt sie |
| FK-55 (Operation-Klassen) | nicht betroffen | Capability-Autoritaet (WER darf `admin_abort_inflight_operation`) bleibt governance-and-guards; Ledger owns nur die transaktionale Wirkung |
| META-DEC-2026-07-02-SESSION-OWNERSHIP | nicht betroffen | Fence-/Ownership-Split wird bestaetigt, nicht geaendert |
| domain-registry.yaml | nicht betroffen | bewusst kein neuer BC-Eintrag |
| bc-cut-decisions.md | nicht betroffen | keine BC-Komponente und keine shared-Fachkomponente (Muster WorktreeManager greift nicht: T-Infrastruktur unterhalb der Stores, keine Fachlichkeit); Vokabular- und Sichtbarkeitsregeln unberuehrt |
| formal.architecture-conformance.invariants | perspektivisch betroffen (Migrationsschnitt) | Funktions-Inventar referenziert heutige Fassaden-Namen (`save/load_control_plane_operation_global`); Umbenennung/Neuzuordnung erfolgt im Migrations-Diff mit eigener Anpassung, nicht durch diesen Record |
| PROJECT_STRUCTURE.md | perspektivisch betroffen (Migrationsschnitt) | neues Modul `state_backend/operation_ledger` entsteht erst mit der Migration; Struktur-Doku wird dort nachgezogen |
| Zielbild-Design der Fassaden-Zerlegung (Arbeitsstand) | geaendert | `GovernanceRuntimeStore` verliert Ledger/Claims/Instance-Identity; Fences folgen dem 2026-07-02-Split; Inflight-Helper wandern zum Ledger — Arbeitsdokument, nicht normativ |
