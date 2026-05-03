---
concept_id: FK-74
title: Concept-Catalog — Foundation-Adapter fuer FK-Doc-Verlinkung
module: concept-catalog
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: concept-resolver
  - scope: concept-cross-references
  - scope: concept-rendering-contract
defers_to:
  - target: FK-07
    scope: component-architecture
    reason: Bluttyp-Klassifizierung als R-Foundation laeuft ueber FK-07
  - target: FK-91
    scope: api-catalog
    reason: API-Vertrag laeuft ueber FK-91
supersedes: []
superseded_by:
tags: [concept-catalog, foundation, conceptrefs, backlinks, markdown]
formal_scope: prose-only
---

# 74 — Concept-Catalog

## 74.1 Zweck

Concept-Catalog ist ein **Foundation-Adapter** (Bluttyp R), der den
Markdown-Konzept-Korpus (`concept/`) als typisierte Lese-Repraesentation
zugaenglich macht. Er ist **kein** A-BC: er besitzt keine fachlichen
Invarianten, kein Aggregat mit Lebenszyklus. Er indexiert, resolvt
und rendert.

Konsumenten:
- `governance` — Concept-Konformitaets-Pruefung
- `requirements_coverage` — Story↔Concept-Bezug
- `story_context_manager` — `conceptRefs` aus Story-Spezifikationen
- Frontend `foundation/concept_catalog/` — der Concept-Browser

## 74.2 Verantwortung

| Aufgabe | Inhalt |
|---|---|
| **ConceptRef-Resolver** | nimmt eine ConceptRef-ID (z. B. `FK-70`, `DK-04`) und liefert Pfad, Titel, Frontmatter, Status |
| **Cross-Reference-Graph** | berechnet vorwaerts (`defers_to`, `formal_refs`) und rueckwaerts (Backlinks) zwischen Concepts |
| **Markdown-Rendering-Vertrag** | liefert Markdown-Inhalt (oder gerendertes HTML) zu einer ConceptRef |
| **Suche** | Volltext- und Frontmatter-Suche ueber den Konzept-Korpus |
| **Versionierung** | Lese-Adresse zeigt auf den aktuellen Konzept-Stand. Versions-Snapshots sind Aufgabe von Audit-Bundles, nicht des Catalogs |

## 74.3 Was Concept-Catalog nicht tut

- **Keine fachliche Pruefung.** Ob ein Concept-Verweis korrekt
  verstanden, eingehalten oder verletzt wurde, ist Sache von
  `governance` (Integrity-Gate, Konformitaets-Checks).
- **Kein Schreiben.** Concept-Catalog ist read-only. Konzept-Dokumente
  werden vom Menschen oder Agent direkt im Repository editiert; der
  Catalog liest, was dort steht.
- **Kein eigener Lebenszyklus.** Concepts haben keinen Status, keine
  Promotion, kein Archiv im Sinne eines Aggregats. Was im Repo liegt,
  ist sichtbar; was geloescht wird, verschwindet.

## 74.4 Datenfluss

```
concept/**/*.md  ──(Filesystem)─►  concept_catalog
                                         │
                                         ▼
                                   in-memory Index
                                         │
            ┌───────────────────────────┴──────────────────┐
            ▼                                              ▼
   Lese-API (REST)                                 Konsument-Imports
   /v1/concepts/...                                (governance, ...)
            │                                              │
            ▼                                              ▼
   Frontend Concept-Browser                       fachliche Pruefungen
```

## 74.5 API-Endpunkte (Auswahl)

Offiziell katalogisiert in **FK-91**.

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/v1/concepts` | Liste aller Concepts (mit Filter nach Layer/Status/Domain) |
| `GET` | `/v1/concepts/{ref}` | Detail (Frontmatter, Pfad, Backlinks, Cross-Refs) |
| `GET` | `/v1/concepts/{ref}/content` | Markdown-Inhalt |
| `GET` | `/v1/concepts/search?q=…` | Suche |

## 74.6 Bluttyp und Klassifizierung

Concept-Catalog ist **`adapter_boundary`** (FK-07 §7.3):

- **Bluttyp R**, weil er Repraesentations-Ueberfuehrung leistet
  (Filesystem-Markdown ↔ typisierte Read-Repraesentation).
- Kein A-BC, weil keine fachlichen Invarianten.
- Im Lint-Tool als `boundary_module` mit
  `bloodgroup: R, boundary_kind: adapter_boundary` modelliert
  (`entities.md`).

## 74.7 Frontend-Slice

Der Concept-Browser im Frontend lebt unter
`frontend/src/foundation/concept_catalog/`. Er nutzt die REST-API von
74.5 und stellt Navigation, Backlink-Anzeige, ConceptRef-Aufloesung
und Markdown-Rendering bereit.
