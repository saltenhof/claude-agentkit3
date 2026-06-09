OVERALL: CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: **FAIL**. FK-61 wird jetzt deutlich besser abgedeckt, aber die Story macht fuer `[N]`-KPIs einen falschen pauschalen AG3-081-Event/Payload-Owner daraus.
- AC-Schaerfe: **FAIL**. AC3/Negativpfad ist zu eng und wuerde FK-61-konforme `[N]`-KPIs ohne neues Event faelschlich blockieren.
- Klarheit/Eindeutigkeit: **FAIL**. AG3-082/AG3-083-Reihenfolge und p95 sind repo-weit weiter widerspruechlich; ausserdem verweist Scope auf nicht existente `§2.3`.
- Kontext-Sinnhaftigkeit: **WEAK**. Die realen Code-Orte und meisten Anchors sind korrekt, aber `_STORY_INDEX.md` und AG3-082-Story sind nicht konsolidiert.

**Remaining/New Must-Fix ERRORs**
1. ERROR: `[N]`-KPI-Owner-Regel ist fachlich falsch.
   Evidence: AG3-083 verlangt, dass `[N]`-KPIs ausschliesslich auf AG3-081 EventType/Payload zeigen und testet `[N]` ohne AG3-081-Event/Payload als Fehler: [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:39), [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:45), [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:78). FK-61 hat aber `[N]`-KPIs ohne neues Event, z. B. `execution_vs_exploration_ratio` liest `runtime.story_metrics.mode`: [61_kpi_erhebung_nach_domaenen.md](T:/codebase/claude-agentkit3/concept/technical-design/61_kpi_erhebung_nach_domaenen.md:132), `guard_violation_rate_by_guard` nutzt Scratchpad-Counter statt Event: [61_kpi_erhebung_nach_domaenen.md](T:/codebase/claude-agentkit3/concept/technical-design/61_kpi_erhebung_nach_domaenen.md:171), `phase_time_distribution` nutzt `phase_state_projection`: [61_kpi_erhebung_nach_domaenen.md](T:/codebase/claude-agentkit3/concept/technical-design/61_kpi_erhebung_nach_domaenen.md:342).
   Fix: Modell/AC auf exakte FK-61-Source-Klassen umstellen: existing event, new event, enriched payload, scratchpad, runtime metric/read-model/projection. Negativtest nur gegen den jeweils laut FK-61 erforderlichen Owner, nicht pauschal AG3-081 EventType/Payload.

2. ERROR: AG3-082/AG3-083-Reihenfolge und p95 sind nicht repo-weit konsolidiert.
   Evidence: AG3-083 sagt `depends_on: AG3-038, AG3-081` und `unblocks: AG3-082`: [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/status.yaml:8). Der Gap-Index sagt aber weiter AG3-083 `depends_on AG3-038, AG3-082`: [_STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:89). AG3-082 sagt sogar noch “AG3-083 (depends_on AG3-082)” und “inkl. response_time_p50_ms/p95”: [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:52), waehrend AG3-083 p95 korrekt ausschliesst: [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:43).
   Fix: `_STORY_INDEX.md`, AG3-082 story/status und AG3-083 status/story auf eine Reihenfolge bringen. Wenn AG3-082 gegen AG3-083-Spalten rechnet, muss AG3-082 von AG3-083 abhaengen. p95 darf in AG3-082 nur als reine `_percentile`-Hilfsfunktion/Test vorkommen, nicht als AG3-083-Zielspalte/Persistenzziel.

3. ERROR: Falscher Selbst-Anchor.
   Evidence: AG3-083 verweist bei Rename-/additiver Migration auf `§2.3`, aber die Story hat nur `§2.1` und `§2.2`: [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:41).
   Fix: Entweder `§2.3` ergaenzen oder den Verweis auf die vorhandene Out-of-Scope-/Migrationspassage korrigieren.

**Round-1 Status**
E2, E3, E4 und E7 sind fuer AG3-083 selbst im Kern behoben. E1 ist nur teilweise behoben wegen der falschen `[N]`-Owner-Verallgemeinerung. E5 ist inhaltlich weitgehend behoben, aber der fehlende `§2.3`-Anchor bleibt. E6 ist nicht geloest, solange AG3-082 und `_STORY_INDEX.md` weiter widersprechen.
