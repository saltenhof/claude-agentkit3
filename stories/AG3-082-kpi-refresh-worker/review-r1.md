OVERALL: CHANGES-REQUESTED

Story-Typ: `implementation` ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/status.yaml:3)). Kein Frontend-Review; kein `type: concept`.

Ist-Zustand-Claims: Die Kernclaims zu fehlenden Definitionen, `top.py:74-103`, `sync_state` und vorhandenem `FactStore`/`ProjectionAccessor` sind im Code belegt. Ausnahme: AG3-081 ist nicht „geliefert“, sondern selbst `draft/review_pending`.

**1) Konzept-Vollständigkeit: FAIL**
- ERROR: FK-62 verlangt `sync_analytics(trigger, project_key, hint_story_id, client)` mit explizitem Trigger; die Story spezifiziert nur `sync_analytics(project_key, hint_story_id=None)` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:29)) gegen FK-62-Pseudocode ([62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:381)). Fix: Trigger-Vertrag explizit modellieren oder sauber begründen, wie `KpiAnalytics.refresh_analytics(project_key, hint_story_id)` den FK-Trigger ohne Informationsverlust abbildet.
- ERROR: Harte Ownership-Regel fehlt als AC: Runtime-Lesen ausschließlich über `ProjectionAccessor`, Schreiben ausschließlich über `FactStore` ([62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:632), [62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:659)). Story erwähnt FactStore nur guardrail-artig ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:60)). Fix: eigenes AC für Import-/Boundary-Compliance und Test/Architecture-Check aufnehmen.
- ERROR: `guard_invocation_counters`-Drain ist unvollständig. FK-62 verlangt Übertragen und Löschen verarbeiteter Einträge ([62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:311)); AC7 verlangt nur Drain in `fact_guard_period` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:50)). Fix: AC um „processed rows deleted, reset removes scratchpad rows“ erweitern.
- WARNING: Dashboard-Catch-up/Survivorship-Bias aus FK-62 §62.3.7 fehlt. FK-62 verlangt Materialisierung nicht geschlossener `RUNNING/ESCALATED/PAUSED` Stories beim Dashboard-Sync ([62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:562)). Fix: entweder in Scope/AC aufnehmen oder mit Konzeptkonflikt zu FK-60 offen klären.

**2) AC-Schärfe: FAIL**
- ERROR: AC1 „deltagetrieben“ ist nicht testbar genug. FK-60/FK-62 nennen konkrete Dirty Sets und Quellen ([60_kpi_katalog_und_architektur.md](T:/codebase/claude-agentkit3/concept/technical-design/60_kpi_katalog_und_architektur.md:360), [62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:470)); die Story nennt keine vollständige Dirty-Set-Matrix ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:44)). Fix: Dirty Sets je Tabelle/Quelle als testbare Matrix ergänzen.
- ERROR: AC3 „Fehler mittendrin“ ist zu unscharf für Atomizität ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:46)). Fix: Fehlerpunkt konkretisieren, z. B. nach Period-Replace vor Cursor-Update; assert: keine Fact-Änderung und `last_event_id` unverändert.
- ERROR: AC5 vermischt `purge_story_analytics` mit FK-69-Purge, obwohl der Pfad als AG3-081-Out-of-Scope markiert ist ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:48), [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:39)). Fix: AC präzisieren: „ruft vorhandenen AG3-081-Purge-Port auf“ oder „implementiert ihn“; nicht beides.
- WARNING: AC8 verlangt fail-closed bei unbekannter `schema_version`, nennt aber keine erwartete Version und keinen Speicherort/Key-Vertrag ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:51)). Fix: erwarteten Wert und Migrationszustand festlegen.

**3) Klarheit/Eindeutigkeit: FAIL**
- ERROR: Scope-Widerspruch bei Read-Model-Purge. In Scope: „purgt die FK-69-Read-Models“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:31)); Out of Scope: „Read-Model-Purge-Pfad ... AG3-081“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:39)). Fix: Owner und Verantwortungsgrenze eindeutig formulieren.
- ERROR: P50/P95-Spalten sind widersprüchlich. Story will `_percentile` in `response_time_p50_ms`/p95 speisen ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:32)), aber FK-62 markiert p95 als INVENTAR ([62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:202)) und AG3-083 erweitert Spalten erst nach AG3-082 ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:38)). Fix: AG3-082 nur `_percentile` + vorhandene Spalten rechnen lassen oder AG3-083-Abhängigkeit/Story-Reihenfolge ändern.
- WARNING: „atomare Transaktion pro Refresh-Einheit“ ist undefiniert ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:29)). Fix: Einheit definieren: ganzer Projekt-Refresh inkl. Cursor oder je Dirty-Slice.

**4) Kontext-Sinnhaftigkeit: FAIL**
- ERROR: Story verlangt „nur über FactStore-Owner“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:60)), aber vorhandener `FactStore` hat nur Read/Upsert, keine Transaction/Delete/Replace-Slice-API ([store.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/fact_store/store.py:87), [repository.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/fact_store/repository.py:83)). Fix: Scope explizit um FactStore/FactRepository-Transaktions- und Replace/Delete-Ports erweitern.
- ERROR: Aktuelles Schema/Model hat nur `avg_latency_ms`, keine P50/P95-Felder ([postgres_schema.sql](T:/codebase/claude-agentkit3/src/agentkit/state_backend/postgres_schema.sql:849), [models.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/fact_store/models.py:72)). Fix: keine Schreibpflicht auf fehlende Spalten in AG3-082, oder Story-Reihenfolge zu AG3-083 ändern.
- WARNING: Story behauptet, AG3-081 liefere Hot-Path/Purge ([story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:24)), aber AG3-081 ist `draft/review_pending`. Fix: als Voraussetzung „AG3-081 completed“ formulieren oder AG3-082 erst nach AG3-081 reviewen/freigeben.

Must-fix ERROR list:
1. Trigger-Vertrag von `sync_analytics` gegen FK-62 klären.
2. ProjectionAccessor-/FactStore-Ownership als testbare AC aufnehmen.
3. `guard_invocation_counters`-Drain inklusive Löschen verarbeiteter Rows spezifizieren.
4. Dirty-Set-Matrix und atomare Rollback-Tests konkretisieren.
5. Read-Model-Purge-Scope-Widerspruch beheben.
6. P50/P95/AG3-083-Spaltenkonflikt beheben.
7. FactStore/Repository-API-Erweiterung für Transaktion/Delete/Replace-Slices explizit in Scope nehmen.
