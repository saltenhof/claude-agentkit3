OVERALL: CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-64 §64.2 wird falsch wiedergegeben. Story sagt: "`FK-64 §64.2` ... `get_design_tokens`-Endpoint" und AC6 fordert einen Read-Endpoint. FK-64 sagt dagegen: `DesignSystem` "gibt keine Tokens dynamisch aus und betreibt keinen eigenen HTTP-Endpunkt"; Boundary-Control liegt bei `control_plane` ([64_control_plane_design_system.md](T:/codebase/claude-agentkit3/concept/technical-design/64_control_plane_design_system.md:91), Zeilen 91-99). Fix: Entweder Story auf reinen `control_plane`-Adapter ohne dynamischen `DesignSystem`-HTTP-Owner umschneiden oder Konzept/Story-Index vorher explizit anpassen. Nicht als FK-64 §64.2-Erfüllung behaupten.

- ERROR: Projekt-/Tenant-Scope aus FK-63 fehlt als testbarer AC. FK-63 verlangt, dass alle Dashboard-Abfragen projektgebunden sind und nie ungefiltert über alle Projekte laufen ([63_auswertung_und_dashboard.md](T:/codebase/claude-agentkit3/concept/technical-design/63_auswertung_und_dashboard.md:122), Zeilen 122-124). Story erwähnt `project_key` nicht in AC1-7. Fix: AC ergänzen: `project_key` ist Pflicht oder aus authentisiertem Projektkontext eindeutig; fehlend/mehrdeutig wird fail-closed abgelehnt; Cross-Project-Leak-Test.

- WARNING: FK-63 Reset-/Gueltigkeitsregel ist nur indirekt abgedeckt. FK-63 verlangt, dass vollständig zurückgesetzte/korrupt verworfene Runs nicht in KPI-Sichten sichtbar bleiben und Facts bereits bereinigt sind ([63_auswertung_und_dashboard.md](T:/codebase/claude-agentkit3/concept/technical-design/63_auswertung_und_dashboard.md:126), Zeilen 126-129; Reset-Regel Zeilen 202-204). Story deckt "leere Rollups" ab, aber nicht "keine Late-Filter-Kompensation, nur bereinigte Facts". Fix: expliziten AC aufnehmen: Endpoints lesen nur bereinigte Facts/runtime projections; kein Query-Late-Fix für reset/corrupt runs; Test mit bereinigtem vs. unbereinigtem FactStore-Vertrag.

**2) AC-Schaerfe: FAIL**

- ERROR: AC5 ist technisch untestbar/falsch zugeschnitten: "Zeitraum-/Entity-/Story-Filter + Vergleichsmodus funktionieren ueber `PeriodFilter`". Der echte `PeriodFilter` hat nur `start` und `end` ([models.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/fact_store/models.py:172), Zeilen 172-182). Entity-, Story-Filter und Vergleichsmodus können darüber nicht ausgedrückt werden. Fix: eigenes Query-Modell definieren, z. B. `KpiQueryFilter(period, entity_filter, story_filter, comparison_period)`, mit konkreten Query-Parametern aus FK-63 §63.4.2 (`project_key`, `from`, `to`, `guard`, `pool`, `story_type`, `story_size`) und Vergleichsparametern.

- ERROR: AC6 fordert einen "`get_design_tokens` ... Read-Endpoint", nennt aber keinen Pfad, keinen Owner und keinen Vertrag. Gleichzeitig ist AG3-092 laut Story-Index der Owner für "Python-Token-Owner `kpi-and-dashboard.DesignSystem` + `get_design_tokens`" ([ _STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:117)). Fix: Pfad, Response-Schema und Owner eindeutig machen oder AC aus AG3-084 entfernen und vollständig AG3-092 geben.

- WARNING: "ehrlicher EMPTY-Status" ist nicht definiert. Aktuelles `DashboardViewStatus` kennt nur `OK` und `UNAVAILABLE` ([views.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/views.py:18), Zeilen 18-23). Fix: festlegen, ob `EMPTY` ein neues Enum, ein Response-Feld, HTTP 200 mit leerer `rows`-Liste oder ein per-endpoint Status ist; Contract-Test dazu.

- WARNING: AC1 "an control_plane-/BFF-Konvention (AG3-091) angedockt" ist mehrdeutig. FK-63 nennt `/api/kpi/*`, die reale Control-Plane-Konvention ist `/v1/...` ([91_api_event_katalog.md](T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md:99), Zeilen 99-137; [http.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/http.py:247), Zeilen 247-317). Fix: verbindlichen finalen Pfad festlegen, z. B. `/v1/kpi/...` oder FK-63 bewusst als BFF-Pfad belassen und Mapping testen.

**3) Klarheit/Eindeutigkeit: FAIL**

- ERROR: Story behandelt eine offene Schnittfrage als entschieden. `_STORY_INDEX.md` fragt explizit: "Endpoint in AG3-084, Token-Owner+Conformance in AG3-092. Akzeptabel, oder beides in AG3-092 bündeln?" ([ _STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:175)). Story mandatiert trotzdem Endpoint und nicht-leeres Modell in AG3-084 ([story.md](T:/codebase/claude-agentkit3/stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:31), Zeile 31). Fix: offene Schnittfrage vor Freigabe entscheiden und Story entsprechend schneiden.

- ERROR: "DashboardService liest ausschliesslich aus Fact-Rollups" ist zu breit. Der echte `DashboardService.get_board()` liest aktive Story-/Kanban-Daten aus `StoryService` ([service.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/dashboard/service.py:87), Zeilen 87-133), während `fact_story` laut Modell "one analytics row per completed story" ist ([models.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/fact_store/models.py:25), Zeilen 25-30). Fix: Scope auf KPI/story-metrics-Analytics begrenzen oder Board-Read-Model separat mit korrektem Owner benennen. Nicht pauschal Board-/DashboardService auf Fact-Rollups zwingen.

- WARNING: "runtime-Pfad" ist nicht eindeutig. FK-63 benennt für Runtime-Daten `ProjectionAccessor` als DB-Zugriffs-Owner ([63_auswertung_und_dashboard.md](T:/codebase/claude-agentkit3/concept/technical-design/63_auswertung_und_dashboard.md:245), Zeilen 245-251). Story sagt nur "runtime-Pfad". Fix: Live-Endpoint explizit über `telemetry-and-events.ProjectionAccessor` oder einen benannten schmalen Port spezifizieren.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: FK-Anker/Sections existieren, aber die FK-64-Aussage ist inhaltlich gegenläufig. Gefundene Sections: FK-63 §63.3 bei Zeile 111, FK-63 §63.4 bei Zeile 189, FK-64 §64.2 bei Zeile 70. Der konkrete Claim "`get_design_tokens`-Endpoint aus FK-64 §64.2" ist falsch, weil §64.2 gerade keinen eigenen HTTP-Endpunkt erlaubt.

- ERROR: AG3-092 hängt von AG3-084 ab, aber AG3-084 will bei Design Tokens einen späteren AG3-092-Owner konsumieren ("wenn AG3-092 den Owner stellt, konsumiert dieser Endpoint ihn"). Das ist zeitlich/cyclisch unsauber: AG3-092 row depends_on AG3-084 ([ _STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:117)); AG3-084 status depends only on AG3-082/AG3-091 ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-084-dashboard-backend-kpi-endpoints/status.yaml:7)). Fix: Design-token delivery vollständig nach AG3-092 verschieben oder AG3-092 vorziehen/splitten.

- PASS: Die Ist-Zustand-Datei-/Line-Claims zu KPI-Endpunkten, `StoryService`-Drift, `get_dashboard_view`, `PeriodFilter` und `DesignTokens` sind im Kern wahr. Belege: keine `/api/kpi`/`api/live/stories` Treffer in `src/agentkit`; `StoryService` import in [service.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/dashboard/service.py:14), Zeilen 14-26; `NotImplementedError` für Nicht-`story` in [top.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/top.py:137), Zeilen 137-142; `get_design_tokens` wirft in [top.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/top.py:172), Zeilen 172-184; leerer `DesignTokens`-Stub in [views.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/views.py:66), Zeilen 66-74.

**Must-Fix ERRORs**

1. FK-64/Design-token Endpoint-Konflikt auflösen; Story darf §64.2 nicht als Endpoint-Mandat behaupten.
2. Projekt-/Tenant-Scope als expliziten AC mit Negativtest ergänzen.
3. AC5 ersetzen: `PeriodFilter` reicht nicht für Entity-/Story-/Comparison-Filter.
4. Design-token Owner/Pfad/Response-Vertrag oder Verschiebung nach AG3-092 eindeutig entscheiden.
5. Offene Schnittfrage AG3-084 vs. AG3-092 vor Story-Freigabe schließen.
6. Pauschales "DashboardService ausschliesslich Fact-Rollups" korrigieren, weil es mit bestehendem Board-Read-Pfad und `fact_story`-Grain kollidiert.
