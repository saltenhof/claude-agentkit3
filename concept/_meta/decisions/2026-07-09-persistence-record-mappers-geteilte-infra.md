---
concept_id: META-DEC-2026-07-09-PERSISTENCE-RECORD-MAPPERS
title: Concept-Decision-Record — Record-Row-Mapper als geteilte Infrastruktur
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, persistence, state-storage, mappers, bc-cut]
formal_scope: prose-only
---

# Concept-Decision-Record — Record-Row-Mapper als geteilte Infrastruktur

Datum: 2026-07-09. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

Die BC-aligned Zerlegung der Persistence-Gesamtfassade
(`agentkit.backend.state_backend.store`) in 12 Pro-BC-Stores plus vier
geteilte Infrastruktur-Komponenten (`StateBackendConnectionManager`,
`PersistenceJsonCodec`, `PersistenceTestSupport`,
`ControlPlaneOperationLedger`; Zielbild-Design 2026-07-08,
META-DEC-2026-07-08-OPERATION-LEDGER) ist in den Phasen 1–6a
abgeschlossen: alle Stores existieren und werden produktiv genutzt.

Die Phase-3-Review (GLM) hat eine offene Kopplung markiert: die neuen
Pro-BC-Stores importieren weiterhin `store.mappers` — einen
~1.200-Zeilen-Record↔Row-Mapper (records ↔ DB-Row-`dict`), der heute
unter dem zu loeschenden `store/`-Fassaden-Paket liegt. Damit gilt die
Zielbild-Invariante „ein Store haengt nur an geteilter Infrastruktur"
noch nicht buchstaeblich, und das `store/`-Paket kann nicht geloescht
werden, solange die Mapper dort wohnen.

## 2. Entscheidung

1. **Die Record-Row-Mapper werden als sanktionierte geteilte
   Infrastruktur aus dem `store/`-Fassaden-Paket herausgeloest** und
   unter einem eigenen Persistenz-Infrastruktur-Prefix
   `agentkit.backend.state_backend.persistence_mappers` angesiedelt.
   - Klassifikation: T-Infrastruktur der Persistenz-Grenze (Bluttyp T),
     reine, zustandslose Serialisierung Domaenen-Record ↔ backend-
     neutrales Row-`dict`. Kein Fach-BC, **kein** Eintrag in
     `domain-registry.yaml`.
   - Es ist eine Serialisierungs-Utility (Schwester von
     `PersistenceJsonCodec`), keine fachliche Komponente. Die
     Backend-spezifische SQL-Ebene (postgres_store/sqlite_store)
     konsumiert die Row-`dict`s unveraendert; die Mapper bleiben
     backend-neutral.
2. **Zerlegung des Mapper-Monolithen nach Record-Familie** in
   kohaerente Sub-Module (z. B. story-/context-, runtime-/phase-state-,
   qa-/verify-, control-plane-/ledger-, telemetry-Mapper), jede Datei
   ehrlich unter den LoC-Gates (`PY_FILE_MAX_LOC_1200`,
   `PY_MODULE_TOP_LEVEL_MAX_LOC_100`). Ein duennes Paket-`__init__`
   liefert ehrliche statische Re-Exports (`from ._x import name as name`
   + explizites `__all__`) — keine dynamische Reflection, kein
   `.pyi`-Schatten, kein Metric-Gaming.
3. **Konsumenten-Regel:** Pro-BC-Stores, der `ControlPlaneOperationLedger`
   und die verbleibenden echten `store/`-Repositories importieren die
   Mapper aus `persistence_mappers`. Die Mapper importieren keinen
   Pro-BC-Store und keine Fach-BC-Logik; Record-Typen werden — wie in
   den Stores etabliert — als `TYPE_CHECKING`-Annotationen referenziert.
   Damit entsteht keine store→store-Kante und kein Zyklus (ARCH-03).

## 3. Alternativen

- **Mapper pro BC in den jeweiligen Store verlagern:** verworfen. Die
  echten `store/`-Repositories (Backend-Implementierung) nutzen dieselben
  Mapper; eine Pro-BC-Co-Location wuerde Repositories dazu zwingen, aus
  den Stores zu importieren (neue Kopplung), oder gemeinsame Row-Helfer
  duplizieren. Serialisierung ist generische Infrastruktur — genau der
  Fall, den „nur generische Infrastruktur ist gemeinsam" adressiert.
- **`store.mappers` als Compat-Shim zuruecklassen:** verworfen
  (ZERO-DEBT). Blockiert die Loeschung des Fassaden-Pakets und
  zementiert die von der Review markierte Kopplung.
- **Monolith 1:1 verschieben (ohne Split):** verworfen. ~1.200 Code-
  Zeilen liegen am `PY_FILE_MAX_LOC_1200`-Gate; eine reine Verschiebung
  wuerde das Anti-God-File-Zielbild verfehlen und den naechsten Zuwachs
  blockieren.

## 4. Impact-Sweep (P3)

Lexikalische Sweeps ueber `concept/` und `src/` am 2026-07-09:
- `store.mappers|record.*row|row.*record` → betrifft nur den
  Implementierungsschnitt (kein Konzeptdokument normiert einen
  Mapper-Modulpfad); die formalen Row/Record-Entitaeten
  (`formal-spec/state-storage/entities.md`) sind unberuehrt, weil
  Feld-Semantik und Row-Form unveraendert bleiben.
- Registry-/BC-Cut-Pruefung: `domain-registry.yaml` (kein neuer BC),
  `bc-cut-decisions.md` (Muster geteilter Infra-Komponenten unterhalb
  der Stores; Mapper sind Utility, keine Fachkomponente).

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| formal.state-storage (entities, invariants) | nicht betroffen | Row-Form und Feld-Semantik unveraendert; reine Modul-Relokation |
| domain-registry.yaml | nicht betroffen | bewusst kein neuer BC-Eintrag; T-Utility |
| bc-cut-decisions.md | nicht betroffen | keine Fachkomponente; Sichtbarkeits-/Vokabularregeln unberuehrt |
| META-DEC-2026-07-08-OPERATION-LEDGER | nicht betroffen | Ledger-Ownership unveraendert; Ledger wird Mapper-Konsument |
| PROJECT_STRUCTURE.md | perspektivisch betroffen (Migrationsschnitt) | neues Modul `state_backend/persistence_mappers` entsteht mit Phase 6b; Struktur-Doku wird dort nachgezogen |
| Zielbild-Design der Fassaden-Zerlegung (Arbeitsstand) | geaendert | ergaenzt die geteilte Infrastruktur um die Mapper-Utility; loest die in der Phase-3-Review markierte `store.mappers`-Kopplung |
