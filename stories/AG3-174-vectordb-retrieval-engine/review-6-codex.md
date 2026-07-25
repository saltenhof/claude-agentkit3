# AG3-174 — Codex Review r6

- **Datum:** 2026-07-25
- **Reviewer:** Codex (read-only, Fortsetzung r1–r5-Session)
- **Branch:** nach 5 r5-Remediation-Commits + 3 D7-Commits
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (998), 412 Tests
  gruen, Tree clean; FK-13-Diff rein additiv, `doc_kind` unberuehrt.

## VERDICT: REJECT

Nicht `APPROVE-PENDING-Q2`: vier Blocker bleiben, und AC5 ist nicht erfuellt.

**Aber massive Konvergenz.** Von 18 offenen Punkten bleiben **vier eigenstaendige
Ursachen** (die 7 „still-open" + 4 „neu" beschreiben dieselben vier Probleme)
plus ein P2.

## Geschlossen

Neu geschlossen: N04, N06, N08, N16, N21, N24, N26, N28, N31, N32, R04, P2-1, P2-2.

Stabil geschlossen (ueber mehrere Runden bestaetigt): R01, R02, R03, R05, R06,
R07, R08, R09, R11, R12, R13, R14, N01, N02, N03, N05, N07, N09, N10, N11, N13,
N14, N18, N19, N22, N25.

## Die vier verbleibenden Ursachen

**N33 (= N15/N27) P0 `sync.py:541` — Check-then-Mutate-Race im Claim-Fencing.**
Jeder Fence ist ein Read, gefolgt von einem separaten Upsert/Delete/Receipt-
Insert (Zeilen 544, 567, 581). Ein administrativer Reclaim *zwischen*
erfolgreichem `assert_claim_held()` und der Mutation erlaubt dem ueberholten
Halter weiter zu schreiben, zu loeschen oder zu publizieren. Die Tests uebernehmen
nur *vor* dem ersten Check oder aus Callbacks *nach* einem Upsert.
Codex-Vorschlag: storage-erzwungene epoch-konditionale Mutationen **oder** ein
Takeover-Protokoll, das den alten Prozess nachweislich stilllegt. **→ D3 nicht
vollstaendig eingehalten. Braucht eine PO-Entscheidung (siehe unten).**

**N34 (= N17/N29) P0 `sync.py:355` — Receipt-Eingaben nicht vor dem ersten
Write geprueft.** `sync_source()` validiert Objekte, aber nicht
`corpus_revision`: mit gueltigen Objekten und `corpus_revision=""` persistiert die
neue Generation, *bevor* `SyncReceipt.verify()` die leere Revision ablehnt.
Auflage: jedes Pflicht-Abschlussfeld vor dem Claim validieren, in allen drei
Sync-Pfaden; Seeded-Store-Test mit Nullmutation. **→ reiner Code-Fix.**

**N35 (= N12/N30) P0 `weaviate_adapter.py:988` — Named-Vector-Source-Property-
Drift passiert die Komposition.** `configured_vectorizer_model()` liest nur
`_NamedVectorizerConfig.model` und ignoriert `source_properties`: eine
Collection, die nur `title` vektorisiert statt der SSOT-gewaehlten narrativen
Properties, passiert, solange Pooling und `vectorizeClassName` stimmen.
**→ reiner Code-Fix.**

**N36 (= R10) P0 `mcp_server.py:189` — Rule-4-Beweis umgeht den echten
Transport-Filter; AC5 damit unerfuellt.** Jede `concept_search` legt **genau
einen** `concept_status`-Filter an (Default `active`, sonst `draft` oder
`archived`). Aktive und Draft-Dokumente koennen deshalb in einem echten
Ergebnis **nie koexistieren** — ein „Abzug fuer draft/archived" kann also
niemals eine Reihenfolge aendern. Der Test fragt `concept_status="draft"` ab,
waehrend der Recording-Client einen *aktiven* FK-13-Treffer liefert, den ein
echter Weaviate-Filter ausschliessen wuerde. Codex-Auflage: entweder einen
Ergebnismengen-Vertrag ratifizieren, unter dem Status koexistieren, **oder**
Regel/AC revidieren — danach ein filtertreuer Real-Path-Test. **→ Konzept-
Inkohaerenz in FK-13. Braucht eine PO-Entscheidung (siehe unten).**

**P2-3 `corpus_doubles.py:267` / `test_sync.py:512`** — Lease-Wortlaut in
Test-Doku veraltet (es gibt keinen Zeitablauf mehr).

## D7 — Bewertung: bestanden

> „The authorized concept change is accurate and bounded." FK-13 §13.9.5/§13.9.11
> trennen `module` von `authority_scope`, benennen letzteren als reinen
> Ranking-Eingang, definieren das Abwesenheitsverhalten und erhalten die
> Tier-Praezedenz. §13.9.6 und sein `doc_kind`-Vokabular sind unberuehrt. Der
> P3-Record enthaelt Entscheidung, Alternativen, Impact-Sweep,
> Betroffenheitsmatrix und passenden Commit-Trailer.

> „The code-side `authority_scope` implementation is strict": Abwesenheit
> akzeptiert; explizites null, leer/whitespace und falsche Typen scheitern vor
> dem Retrieval. Erreicht nie die Transport-Filter, faellt nie auf `module`
> zurueck, kein zweiter Source-of-Truth im Service. **Regeln 1 und 2 sind
> echt produktiv** mit revert-sensitiven Gegenbeispielen; grosse
> Aehnlichkeitswerte koennen ihre Tiers nicht ueberspringen.

**Einschraenkung:** AC5 bleibt unerfuellt — nicht wegen D7, sondern wegen der
Rule-4-Inkohaerenz (N36). Die D7-Implementierung der Regeln 1/2 ist korrekt; die
Schlussfolgerung „alle fuenf Regeln" im Report ist es nicht.

## W2/W3 und Q2

Der gemeldete Korpuszustand ist korrekt: 75 Dokumente, 2075 Chunks, 273
Erst-Fehler pro Datei. Der neue Decision Record ist genau der eine zusaetzliche
Fehler (`doc_kind: decision-record` → E-SCHEMA-003); vorher 272.

Beide Gates laden den kompletten Korpus (`concept_governance.chunks.load_chunks()`
→ `tools.concept_ingester.discovery.discover()`), *bevor* irgendeine
LLM-Bewertung stattfindet; Discovery wirft auf den Parse-Fehlern, also sind W2s
Changed-Document-Filter und W3s Scope-Selektion nie erreichbar.

Urteil: Die blockierende Fehlerklasse ist **vorbestehend und Q2-gebunden**; diese
Story hat sie numerisch um **einen** bewusst nichtkonformen Decision Record
verschlechtert, aber **keine neue Fehlerklasse** eingefuehrt. Da D7 normativ ist,
braucht der W2/W3-Nachweis vor dem Landen entweder die Q2-Aufloesung oder einen
expliziten Governance-Waiver.

## Scope / Decisions

Kein Leakage in AG3-172/173/175/176. Die Aenderungen an Story-Export,
Split-Composition und Repair sind notwendige AG3-174-Integrationskorrekturen.

D1, D2, D4, D5, D6 und der autorisierte D7-Scope eingehalten. **D3 nicht
vollstaendig** — N33 erlaubt einem ueberholten Writer, nach dem Takeover zu
mutieren.
