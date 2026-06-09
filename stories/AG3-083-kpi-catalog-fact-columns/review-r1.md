OVERALL: CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-61 ist unterdeckt. FK-61 definiert pro Collection-Point nicht nur `[R]/[N]`, sondern Event/Payload, Prozesspunkt und Ziel-Fact-Tabelle: [61_kpi_erhebung_nach_domaenen.md](T:/codebase/claude-agentkit3/concept/technical-design/61_kpi_erhebung_nach_domaenen.md:48). Die Story reduziert das auf Klassifikation/Event-Owner: [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:27). Fix: AC/Scope muss fuer alle 40 KPIs den FK-61-Mapping-Vertrag pruefen: source event/payload, process point, target fact table, `[R]/[N]`, owner.

- ERROR: Story verlangt p95 als Zielspalte, obwohl FK-62 §62.2.3 `response_time_p95_ms` explizit als INVENTAR/nicht aktiv markiert: [62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:202). Story: “p50/p95 in `fact_pool_period`” [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:46). Fix: p95 aus AG3-083 streichen oder vorher FK-60/FK-62 per Konzeptstory aktivieren.

**2. AC-Schaerfe: FAIL**

- ERROR: AC1/AC2 sind gameable. “Test zaehlt 40 + prueft Status” [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:41) beweist nicht, dass es die 40 FK-60-AKTIV-KPIs sind. Fix: Contract-Test muss die exakte FK-60-Active-ID-Menge plus pro KPI Name, Koernung, Formel, Entscheidungsfrage, Status, Datenquellenklasse validieren.

- ERROR: AC4 laesst “eine Wahrheit” offen, obwohl FK-62 autoritativ ist. Story erlaubt “FK-62-Namen, oder bewusst dokumentierte Code-Realitaet” [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:28). Fix: entweder FK-62-Namen verbindlich machen oder eine separate Konzeptaenderung verlangen; Code-Realitaet darf FK nicht still overrulen.

- WARNING: AC5 “mit AG3-081 konsolidiert” [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:45) nennt keine kanonischen Feldnamen. Fix: AC muss `are_gate_result.total_requirements`, `covered_requirements` und `integrity_gate_result.blocked_dimensions` als erwartete Wire Keys festnageln.

**3. Klarheit/Eindeutigkeit: FAIL**

- ERROR: Scope widerspricht sich bei Migrationen. Namensabweichungen wie `qa_rounds` -> `qa_round_count` und `started_at` -> `opened_at` sind keine “nur additiven” Spalten, aber Migrationstrategie ist out of scope: [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:28), [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:38). Fix: Migration/Compatibility explizit in-scope nehmen oder Scope auf additive neue Spalten ohne Rename reduzieren.

- ERROR: AG3-082-Abhaengigkeit ist logisch inkonsistent. Story/status sagen `depends_on: AG3-082` [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/status.yaml:8), aber Story sagt zugleich, AG3-082 rechnet gegen die hier definierten Spalten [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:21). Fix: AG3-083 muss AG3-082 unblocken, oder AG3-082 darf nicht Owner der Fuelllogik fuer diese neuen Spalten sein.

**4. Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Implementierungsorte sind falsch/unvollstaendig. Story nennt `fact_store/models.py`, `postgres_schema.sql`, `sqlite_store.py` [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:65). Real relevant sind auch `src/agentkit/state_backend/store/fact_repository.py` mit Column-/Mapper-/UPSERT-Truth [fact_repository.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/fact_repository.py:308) und SQLite-DDL liegt in der Migration [v_3_4_analytics.sql](T:/codebase/claude-agentkit3/src/agentkit/state_backend/migration/versions/v_3_4_analytics.sql:18), angewendet aus `sqlite_store.py` [sqlite_store.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/sqlite_store.py:976). Fix: Ownerliste auf `kpi_analytics/fact_store/models.py`, `state_backend/postgres_schema.sql`, `state_backend/migration/versions/...`, `state_backend/store/fact_repository.py`, plus bootstrap/contract tests korrigieren.

- WARNING: Ist-Zustand-Katalogclaim ist im Kern wahr: Skeleton bei [catalog.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/catalog.py:139), leerer init bei [catalog.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/catalog.py:141). Aber Docstring-Zeilen sind 3-5, nicht 4-6. Fix: Zeilenangabe korrigieren.

- PASS: Genannte FK-Anker existieren: FK-60 §60.4 [60_kpi_katalog_und_architektur.md](T:/codebase/claude-agentkit3/concept/technical-design/60_kpi_katalog_und_architektur.md:388), FK-61 §61.12.2 [61_kpi_erhebung_nach_domaenen.md](T:/codebase/claude-agentkit3/concept/technical-design/61_kpi_erhebung_nach_domaenen.md:364), FK-62 §62.2.1-§62.2.5 [62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:101).

**Must-Fix ERROR List**

1. FK-61-Mapping-Vertrag vollstaendig in Scope/AC aufnehmen.
2. p95-Spalte entfernen oder vorher per Konzept aktivieren.
3. AC1 auf exakte FK-60-Active-ID-/Feldmenge schaerfen.
4. FK-62 als Namenswahrheit verbindlich machen; keine “Code-Realitaet”-Alternative ohne Konzeptaenderung.
5. Rename-vs-additive-Migration klaeren.
6. AG3-082 Dependency/Owner-Reihenfolge korrigieren.
7. Reale Implementierungsorte inklusive `fact_repository.py` und SQLite-Migration nennen.
