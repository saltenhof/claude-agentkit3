# AG3-176 — Codex-Review der Konzeptinhalte (D1–D5), Runde 1

- **Auftrag:** PO 2026-07-30 — „Wenn du die Konzeptinhalte mit Codex Review
  abgesichert hast, dann habe ich da keinen Einspruch."
- **Agent:** Codex, read-only (`job-87499f79`), 114 Tool-Calls, 12,6 min.
- **Pruefgegenstand:** `git diff -- concept/` auf
  `feat/ag3-176-vectordb-installer-integration` (9 Dateien, +85/-48).

## Verdikt

**NICHT BESTANDEN** — 2 BLOCKER, 5 MAJOR.

## Befunde

### R-01 — BLOCKER — Untergeschobene Hook-Norm
`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md`, §CP 10b.
Neu normiert: „Kann Git die staged Pfade nicht ermitteln, endet der Hook
ungleich null." und „Pfade werden als argv uebergeben, nicht in Shelltext
interpoliert." Beides folgt **nicht** aus dem Beschluss 2026-07-21 Rand 1 und
gehoert nicht zu D1–D5; es war bisher reines Implementierungsverhalten
(`hook_dispatch.py`). Durch die Aufnahme in FK-50 wird es erstmals Konzeptnorm.
**Korrektur:** entfernen oder als bewusste Norm ratifizieren.

### R-02 — BLOCKER — D5 setzt einen neuen und zugleich falschen Dependency-Vertrag
`concept/technical-design/01_systemkontext_und_architekturprinzipien.md`, §P7.
FK-01 behauptet „`mcp[cli]` >= 1.2.0 … Pflicht". Der ratifizierte Beschluss gibt
das nicht her, und `pyproject.toml` verlangt tatsaechlich nur `mcp>=1.0` — weder
das `cli`-Extra noch 1.2.0. Fuer `weaviate-client` (`>=4.9,<5.0`) stimmt es.
**Korrektur:** FK-01 auf `mcp>=1.0` angleichen; ein strengerer Vertrag waere
eigene Norm und muesste im Packaging erzwungen werden.

### R-03 — MAJOR — Der neue D2-SSOT ist kein vollstaendiges Receipt-Schema
`13_retrieval_vektordb_wissenszugriff.md`, §13.9.9. Der „Feldschema-Vertrag"
zaehlt nur Feldnamen auf; Typen, Wertebereiche, feste `tool`/`source_types`-
Kombinationen, zulaessiger Status, Dateipfade, Semantik von
`start_revision`/`end_revision` und der Umgang mit unbekanntem Commit-Ausgang
fehlen. Der Code entscheidet all das eigenstaendig (`cp10a_initial_sync.py`),
inklusive des Zustands `commit_outcome_unknown`.
**Korrektur:** kompakte Schema-/Semantiktabelle in FK-13; `commit_outcome_unknown`
ausdruecklich regeln; FK-50 verweist weiter nur.

### R-04 — MAJOR — „Empty Corpus mit Null-Zaehlern" widerspricht dem Full-Reindex
`13_retrieval_vektordb_wissenszugriff.md`, §13.9.9. Bei einem zuvor nichtleeren,
jetzt leeren Korpus loescht der Full-Reindex die verschwundenen Quellen
(`sync.py:895-900`, `968-1018`); das Receipt traegt dann gleichzeitig
`empty_corpus=true`, `discovered=0` und `deleted>0`. Der Uebergang ist explizit
getestet (`test_ag3_176_vectordb_integration.py:1077-1100`). Der neue Vertrag
laesst diesen gueltigen Fall nicht zu.
**Korrektur:** festlegen, dass „Null-Zaehler" die Entdeckungs-/Upsert-Zaehler
meint und `deleted` positiv sein darf — oder die Implementierung aendern.

### R-05 — MAJOR — Der Restkorpus behauptet weiterhin den entfernten VectorDB-Zweig
FK-13 §13.1, FK-03 §3.1 und `concept/_meta/bc-cut-decisions.md` sagen weiterhin,
die Code-Entfernung sei einer spaeteren Story vorbehalten bzw. die
CheckpointEngine habe Branch-Knoten fuer `feature.vectordb`. Der Zweig ist
tatsaechlich weg (`flow.py:9-26`, FK-50:475-478).
**Korrektur:** Passagen als umgesetzt markieren/entfernen; in
`bc-cut-decisions.md` nur noch ARE/Sonar als Branch nennen.

### R-06 — MAJOR — FK-13 ordnet Konzeptquellen weiterhin `story_sync` zu
FK-13 §13.4.1 nennt unter `story_sync` weiterhin „Konzepte, Architektur,
Research". Der Beschluss trennt: Konzept/Architektur ueber `concept_sync`,
Story/Research ueber `story_sync`. Der Code trennt ebenso.
**Korrektur:** Konzepte/Architektur dort streichen, auf §13.9.5 verweisen.

### R-07 — MAJOR — FK-13 haelt einen zweiten, nicht ausfuehrbaren Post-Commit-Vertrag
FK-13 §13.9.9 nennt `concept build --sync`. Diesen Aufruf gibt es nicht
(`cli.py:307-312`: `build` kennt kein `--sync`). FK-30 und FK-50 verlangen zwei
getrennte Aufrufe (`build`, dann `sync` ohne `--full`).
**Korrektur:** beide Stellen auf „`concept build`, danach `concept sync` ohne
`--full`" umstellen.

## Positiv verifiziert

- D1-Codeabgleich: nur strikt erkanntes `false` wird `vectordb_required`
  (`config_boundary.py:36-47`); Pruefung liegt vor Preflight und CP1.
- VectorDB-Flow-Zweig und `vectordb_disabled` sind im Checkpoint-Graph entfernt;
  ARE bleibt unabhaengiger optionaler Branch.
- D3: Post-Commit fuehrt `build` vor **inkrementellem** `sync` aus, ohne `--full`.
- FK-50 dupliziert das Receipt-Feldschema nicht, sondern verweist auf FK-13.
- Zweiter Receipt-Write restauriert die vorherigen Bytes beider Dateien und
  meldet einen Restore-Fehler ehrlich (`cp10a_initial_sync.py:173-201`).
- Referenz-Baseline: nur drei Zeilennummern verschoben, **keine** neue
  Unterdrueckung.
- Kein stilles Endpoint-Defaulting; ungueltige Typen/fehlende Endpunkte
  fail-closed.
- `pytest tests/unit/concept_toolchain`: 374 bestanden (AG3-179-Flake trat nicht auf).
- `check_concept_frontmatter.py` PASS (90 Dokumente);
  `compile_formal_specs.py` PASS (192 Dokumente, 1802 IDs, 2344 Referenzen,
  149 Szenarien); `check_concept_reference_integrity.py` PASS (0 Fehler,
  55 baseline-gedeckte Reports).

## Grenzen des Reviews

- MCP-Tools nicht als Codex-Tools exponiert; `concept_search`/`concept_get`/
  `concept_glossary_search` wurden ueber die Projekt-`.venv` direkt aufgerufen.
- Der Weaviate-Index traegt noch den Stand **vor** dem Working-Tree-Diff; die
  Treffer dienten der Discovery, belegt wurde gegen die lokalen Dateien.
- W2/W3 nicht ausgefuehrt (LLM-Pre-Merge-Gates, keine deterministischen Gates).
- Jenkins/Sonar nicht als gruen attestiert (read-only-Auftrag; Jenkins lieferte
  401 fuer den anonymen Check).
