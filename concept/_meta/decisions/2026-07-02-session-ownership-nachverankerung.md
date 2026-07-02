---
concept_id: META-DEC-2026-07-02-SESSION-OWNERSHIP
title: Concept-Decision-Record — Session-Ownership-Nachverankerung K2/K3
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, session-ownership, api-catalog, events]
formal_scope: prose-only
---

# Concept-Decision-Record — Session-Ownership-Nachverankerung K2/K3

Datum: 2026-07-02. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

Die freigegebene GAP-Analyse des Session-Ownership-Strangs
(`_temp/gap-analyse-session-ownership.md`, §2 Befunde K2/K3;
Gegenprobe aus `gap-01-soll-inventar.md`, Punkte 1+4) hat zwei
Luecken der normativen Verankerung selbst (Commit `3ae011e4`)
identifiziert:

- **K2:** Die FK-02-§2.6-Invariantenzeile zum Session-Ownership-
  Prinzip fehlte (Entwurfs-Soll, im Verankerungs-Diff nicht
  umgesetzt); der in FK-30 §30.6.3 referenzierte
  `takeover-reconcile-worktree`-Pfad hatte keinen Wire-Contract
  (kein FK-91-Endpoint).
- **K3:** FK-72 §72.14.7 fordert einen benutzeruebergreifenden
  Takeover-Freigabe-Overlay, aber der einzige normierte Push-Kanal
  war projekt-skopiert (`GET /v1/projects/{key}/events`).

K1 (Worktree-Remote-Topologie) ist **nicht** Teil dieser
Entscheidung — die PO-Entscheidung steht aus.

## 2. Entscheidung

Drei Eingriffe, alle rein normativ (Konzept-Prosa, keine neuen
formal-spec-Objekte, keine Anker-Aenderungen):

1. **FK-02 §2.6** erhaelt eine Invariantenzeile: „Eine
   Story-Umsetzung gehoert hoechstens einer Session; Ownership endet
   nie automatisch" — Durchsetzung Run-Ownership-Record mit
   DB-erzwungener Aktiv-Invariante + `ownership_epoch`-Fence,
   Mechanismus als Referenz auf FK-56 §56.8a/§56.13 und
   `formal.operating-modes.invariants` (Single-Assertion: keine
   Paraphrase der Mechanik).
2. **FK-91 §91.1a** erhaelt die Endpoint-Zeile
   `POST /v1/project-edge/story-runs/{run_id}/ownership/takeover-reconcile-worktree`
   (Snapshot-Abgleich durch den neuen Owner; Erfolg hebt
   `takeover_reconcile_required` auf, Drift fuehrt zu
   `contested_local_writes`; mutierende Operation mit
   client-beigestelltem `op_id` nach Regel 5 und
   Serialisierungsobjekt nach Regel 13). **FK-30 §30.6.3** verweist
   fuer den Wire-Contract minimal-invasiv auf FK-91 §91.1a; die
   Guard-Semantik (Exklusivitaet des Aufhebungspfads) bleibt allein
   in FK-30.
3. **FK-91 §91.8.1** normiert den projektuebergreifenden
   governance-Stream `GET /v1/events/governance` (Katalog-Zeile +
   Absatz: buendelt das `governance`-Topic ueber alle Projekte,
   dieselben Wire-Schemas wie der projekt-skopierte Stream, lossy
   gemaess §91.8.2 mit Initial-GET-Re-Sync); die
   governance-Topic-Zeile in §91.8.3 verweist fuer den
   benutzeruebergreifenden Konsum auf §91.8.1. **FK-72 §72.14.7 (2)**
   erhaelt genau einen Satz: Der globale Overlay speist sich aus
   diesem projektuebergreifenden Stream, nicht aus dem
   projekt-skopierten (Transport-Detail nur in FK-91).

### Namensentscheidungen

- **`takeover-reconcile-worktree`** (nicht `reconcile-worktree`):
  Das letzte Pfadsegment entspricht woertlich dem in FK-30 §30.6.3
  etablierten Pfadnamen, und die Nachbarzeilen der
  Ownership-Gruppe folgen dem Muster `ownership/takeover-*`
  (`takeover-request`, `takeover-confirm`). FK-30 und FK-91 nutzen
  damit denselben Namen ohne Umbenennung im Bestand.
- **`GET /v1/events/governance`** (nicht
  `GET /v1/events?topics=governance`): Bestandskonvention ist ein
  eigenes Pfadsegment unter `/v1/events/` fuer nicht
  projekt-skopierte Streams (`/v1/events/hub`); `?topics=` ist im
  Bestand ein Filter **innerhalb** eines Streams, kein
  Stream-Selektor. Ein globaler All-Topic-Stream `/v1/events` wird
  bewusst nicht eingefuehrt (minimaler Normierungsumfang).

## 3. Alternativen

- **Keine Nachverankerung / Aufschub:** verworfen. Die
  GAP-Analyse setzt K2/K3 als Vorbedingung vor die Story-Kandidaten
  GAP-ST-08 (Reconcile-Wire-Contract) und GAP-ST-10 (globaler
  Push-Kanal); ohne Nachverankerung haetten beide Stories haengende
  Vorbedingungen bzw. muessten Wire-Namen selbst erfinden
  (Verstoss gegen Single-Assertion und Konzepttreue).
- **Neue formal-spec-Objekte (Commands/Events) sofort mitziehen:**
  verworfen fuer diese Nachverankerung. Die Endpoints sind
  Katalog-Zeilen wie ihre Nachbarn; die formale Ausmodellierung
  gehoert in den Story-Schnitt (ST-08/ST-10), nicht in die
  Nachverankerung.
- **K1 mitentscheiden:** verworfen; PO-Entscheidung steht aus
  (explizit ausgenommen).

## 4. Impact-Sweep (P3)

Lexikalische Sweeps ueber `concept/` am 2026-07-02 (ripgrep):

- `reconcile-worktree|takeover_reconcile_required|contested_local_writes`
  → FK-30 §30.6.3 (Heimat der Guard-Zustaende), FK-72 §72.14.7 (3)
  (Anzeige-Referenz). Keine weiteren Fundstellen, keine
  formal-spec-Fundstellen.
- `/v1/events|projekt-skopiert|projektneutral|projektuebergreifend`
  → FK-91 §91.8 (Katalog-Heimat), FK-72 §72.12 (Mechanismus; §72.12.6
  delegiert den Katalog explizit an FK-91),
  `formal-spec/frontend-contracts/README.md` + `events.md`
  (Hub-out-of-scope-Aussagen). Sonstige Treffer („projektuebergreifend")
  sind fachfremd (Blutgruppen-Methodik, KPI-Aggregationsverbot).
- `§2.6`-Referenzen → keine Fremdreferenz auf FK-02 §2.6 im Korpus.
- Referenzziel-Pruefung: `state-storage.entity.takeover-worktree-snapshot`
  (formal-spec/state-storage/entities.md),
  `frontend-contracts.event.takeover_approval_changed` und
  `frontend-contracts.entity.takeover_approval_request`
  (formal-spec/frontend-contracts) existieren.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-02 §2.6 | geaendert | neue Invariantenzeile (reine Referenz auf FK-56/formal) |
| FK-91 §91.1a | geaendert | Endpoint-Zeile `takeover-reconcile-worktree` in der Ownership-Gruppe |
| FK-91 §91.8.1 | geaendert | Stream-Zeile `GET /v1/events/governance` + normativer Absatz; „Beide" → „Alle" Endpunkte |
| FK-91 §91.8.3 | geaendert | governance-Topic-Zeile: benutzeruebergreifender Konsum verweist auf §91.8.1 statt implizit auf den projekt-skopierten Stream |
| FK-30 §30.6.3 | geaendert (Wortlaut minimal) | Wire-Contract-Verweis auf FK-91 §91.1a ergaenzt; Pfadname unveraendert, keine Anker geaendert |
| FK-72 §72.14.7 (2) | geaendert | ein Satz: Overlay speist sich aus dem projektuebergreifenden governance-Stream (FK-91 §91.8.1) |
| FK-72 §72.12.2 | nicht betroffen | Tabelle zeigt die Endpoint-Form; §72.12.6 delegiert den vollstaendigen Stream-/Topic-Katalog explizit an FK-91 (Single-Assertion: Katalog-Wahrheit liegt in FK-91 §91.8.1) |
| FK-72 §72.14.7 Wire-Bindung | nicht betroffen | referenziert die Event-Schema-Definition (Topic `governance`, FK-91 §91.8.3), nicht den Konsum-Kanal des Overlays |
| FK-56 §56.8a/§56.13 | nicht betroffen | reines Referenzziel; Aussagen unveraendert |
| formal-spec (operating-modes, state-storage, frontend-contracts) | nicht betroffen | keine neuen formal-Objekte: Endpoints sind Katalog-Zeilen wie die Nachbarn; der governance-Stream traegt dieselben Wire-Schemas (`formal.frontend-contracts.events`), keine zweite Event-Definition |
| formal-spec/frontend-contracts/README.md + events.md | nicht betroffen | Hub-out-of-scope-Aussagen betreffen `/v1/events/hub`; der governance-Stream nutzt die bestehenden frontend-contracts-Schemas und braucht dort keine Scope-Aenderung |
| `_temp/gap-*`-Dokumente, `stories/README.md` §6.7 | nicht betroffen | Arbeits- bzw. Prozessdokumente, nicht normativ |
