# AG3-084 — Remediation R1 (Antwort auf hostile Codex-Review `review-r1.md`)

**Datum:** 2026-06-07
**Geaenderte Dateien:** `story.md`, `status.yaml` (und dieser Report). Kein Produktionscode, keine Tests, keine `concept/`-Dateien beruehrt.
**Scope-Disziplin:** Schnitt aus `_STORY_INDEX.md:90` strikt eingehalten — KPI-Endpoints (stories/guards/pools/pipeline/corpus + live), Fact-Rollup-Read statt StoryService (DRIFT-AG3-038-Fix), Filter/Vergleichsmodus. Kein Scope-Ausbau. Das umstrittene Design-Token-Add-on wurde aus AG3-084 **entfernt** und vollstaendig an den im Index benannten Owner AG3-092 geroutet (Scope-Reduktion, keine -Erweiterung).

---

## ERRORs (Must-Fix)

### E1 — FK-64 §64.2 falsch als Endpoint-Mandat zitiert (Review §1, §2 AC6, §4)
**Befund:** FK-64 §64.2 (`64_control_plane_design_system.md:91-99`) sagt: `DesignSystem` „gibt keine Tokens dynamisch aus und betreibt keinen eigenen HTTP-Endpunkt"; Boundary-Control liegt bei `control_plane`. Die Story behauptete §64.2 als `get_design_tokens`-Endpoint-Mandat (alt: Quell-Konzept-Zeile + AC6 + Scope 5).
**Resolution:** Quell-Konzept FK-64 §64.2 komplett aus AG3-084 entfernt. Kein FK-64-Erfuellungsclaim mehr. Design-Token-Lieferung (Modell **und** HTTP) vollstaendig nach AG3-092 verschoben (neue Schnitt-Entscheidung im Story-Kopf + §2.2 + Hinweis §6). AC6 (alt) ersatzlos gestrichen; AC-Nummerierung neu (jetzt 10 AKs).

### E2 — Projekt-/Tenant-Scope fehlt als testbarer AC (Review §1)
**Befund:** FK-63 §63.3.1 (`63_auswertung_und_dashboard.md:122-124`) verlangt projektgebundene Abfragen, nie ungefiltert ueber alle Projekte. `project_key` fehlte in den AKs.
**Resolution:** Neuer Scope-Pkt. 2 + neues **AC2**: `project_key` Pflicht (explizit oder eindeutig aus Projektkontext); fehlend/mehrdeutig → fail-closed; Cross-Project-Leak-Negativtest. FAIL-CLOSED-Guardrail ergaenzt.

### E3 — AC5 (alt) untestbar: `PeriodFilter` reicht nicht (Review §2)
**Befund:** Realer `PeriodFilter` (`fact_store/models.py:172-182`) hat nur `start`/`end`. Entity-/Story-Filter + Vergleichsmodus nicht ausdrueckbar.
**Resolution:** Scope-Pkt. 5 + **AC6** fordern ein **eigenes** typisiertes `KpiQueryFilter`-Modell (`period`, `entity_filter`, `story_filter`, `comparison_period`), gebunden an die FK-63-§63.4.2-Parameter (`project_key`/`from`/`to`/`guard`/`pool`/`story_type`/`story_size`) + Vergleichszeitraum. „nicht ueber `PeriodFilter` allein" explizit.

### E4 — Design-Token Owner/Pfad/Vertrag unklar bzw. Doppel-Ownership mit AG3-092 (Review §2 AC6, §4)
**Befund:** AG3-092 ist laut `_STORY_INDEX.md:117` Owner von `get_design_tokens`; AC6 nannte weder Pfad noch Owner noch Vertrag.
**Resolution:** Vollstaendig nach AG3-092 verschoben (siehe E1). In §2.2 als Out-of-Scope mit Owner AG3-092 markiert.

### E5 — Offene Schnitt-Frage Nr. 4 als entschieden behandelt (Review §3)
**Befund:** `_STORY_INDEX.md:175` stellt die Token-Endpoint-Zuordnung explizit als offene PO-Frage; die Story mandatierte sie trotzdem (alt Zeile 31).
**Resolution:** Schnitt-Frage im Story-Kopf **explizit geschlossen** zugunsten „beides in AG3-092 buendeln" — begruendet ueber FK-64 §64.2 + die zyklische Abhaengigkeit (E8). Story-Kopf dokumentiert die Entscheidung samt Quellzeilen.

### E6 — „DashboardService ausschliesslich Fact-Rollups" zu breit (Review §3, §4 Must-Fix 6)
**Befund:** `DashboardService.get_board` (`service.py:96-133`) liest **aktive** Stories aus `StoryService`; `fact_story` ist „one analytics row per **completed** story" (`fact_store/models.py:25-30`). Pauschalzwang kollidiert mit dem Board-Grain.
**Resolution:** Trust-Boundary-Fix praezise auf den **KPI-/Story-Metrics-Lesepfad** `get_story_metrics` (`service.py:135-161`, Import `:26`/`:144`) begrenzt. `get_board` explizit als **eigener, unangetasteter** Read-Pfad in §1, §2.1 Pkt. 3, §2.2 und AC3 (Regressionstest) ausgewiesen. Korrekte Anker eingesetzt.

---

## WARNINGs

### W1 — FK-63 Reset-/Gueltigkeitsregel nur indirekt (Review §1)
**Befund:** FK-63 §63.3.1 (Z. 126-129) + §63.4.1 Reset-Regel (Z. 202-204): keine Late-Filter-Kompensation, nur bereinigte Facts.
**Resolution (im Story gefixt):** Neuer Scope-Pkt. 6 + **AC7**: nur bereinigte Facts/Runtime-Projektionen, kein Late-Query-Fix; Vertragstest bereinigter vs. unbereinigter FactStore. Upstream-Bereinigung (AG3-071/081/082) als Out-of-Scope-Owner benannt.

### W2 — EMPTY-Status undefiniert (Review §2)
**Befund:** `DashboardViewStatus` (`views.py:18-23`) kennt nur `OK`/`UNAVAILABLE`.
**Resolution (im Story gefixt):** Scope-Pkt. 7 + **AC8**: `DashboardViewStatus.EMPTY` als additiver englischer Enum-Wert; HTTP 200 + leere `rows` + expliziter Status; Contract-Test fixiert das Verhalten.

### W3 — AC1 Pfad-Konvention mehrdeutig `/api/*` vs `/v1/*` (Review §2)
**Befund:** FK-63 nennt `/api/kpi/*`; reale Control-Plane-Konvention ist `/v1/...` (`91_api_event_katalog.md:99-137`; `control_plane/http.py:296-301`).
**Resolution (im Story gefixt):** **AC1** legt verbindlich fest: FK-63-`/api/...`-Pfade werden auf `/v1/...` gemappt (analog `/v1/dashboard/...`, `control_plane/http.py:298-301`), konkreter finaler Pfad im Routen-Test fixiert; bei fehlender AG3-091-Konvention Abhaengigkeit melden.

### W4 — „runtime-Pfad" nicht eindeutig (Review §3)
**Befund:** FK-63 §63.5 (Z. 245-251) benennt `telemetry-and-events.ProjectionAccessor` (FK-69) als Runtime-Schema-Lese-Owner.
**Resolution (im Story gefixt):** Scope-Pkt. 4 + **AC5** spezifizieren den Live-Endpoint explizit ueber `telemetry-and-events.ProjectionAccessor`; der Adapter selbst ist Out-of-Scope (Owner FK-69), hier nur konsumiert.

---

## Zusaetzlich behoben

### E7 — Falsche Code-Anker korrigiert
- `service.py:14-18` (alt, Zeile 5/18) → praezisiert: DRIFT-Kommentar `service.py:14-18`, Import `:26`, KPI-Read `:144`, Methode `get_story_metrics` `:135-161`, Board-Pfad `get_board` `:96-133`.
- `views.py:66` (DesignTokens) entfaellt (Design-Tokens out of scope); stattdessen korrekt `DashboardViewStatus` `views.py:18-23` fuer den EMPTY-Fix verankert.
- `PeriodFilter` korrekt auf `fact_store/models.py:172-182` verankert.
- `top.py:137-141`/`:142` und `:172-184` bestaetigt (von der Review als PASS verifiziert) — beibehalten; der `get_design_tokens`-Anker (`top.py:172-184`) ist nicht mehr in AG3-084 referenziert, da out of scope.
- Control-Plane-Konvention `control_plane/http.py:296-301`/`:298-301` neu als realer Anker fuer den Pfad-Fix.

### E8 — Zyklische/zeitliche Inkonsistenz Design-Tokens (Review §4)
**Befund:** AG3-092 `depends_on` AG3-084 (`_STORY_INDEX.md:117`), aber AG3-084 wollte spaeter den AG3-092-Owner konsumieren → zyklisch.
**Resolution:** Durch die vollstaendige Verschiebung der Token-Lieferung nach AG3-092 (E1/E5) entfaellt der Zyklus. `status.yaml` `unblocks` von `[]` auf `[AG3-092]` korrigiert (spiegelt die Index-Kante AG3-092→depends_on→AG3-084 korrekt als unblocks-Richtung).

---

## status.yaml — Aenderung
- `unblocks: []` → `unblocks: [AG3-092]` (korrigiert; AG3-092 haengt laut `_STORY_INDEX.md:117` von AG3-084 ab). `depends_on: [AG3-082, AG3-091]` unveraendert (korrekt).

## Bestaetigung
Geschrieben wurden ausschliesslich: `story.md`, `status.yaml`, `remediation-r1.md`. Produktionscode, Tests und `concept/`-Dateien wurden **nicht** angefasst. Template-Struktur (AG3-057) beibehalten: Kopf + §1 Kontext/Ist-Zustand + §2 Scope (In/Out) + §3 Akzeptanzkriterien + §4 DoD + §5 Guardrails + §6 Sub-Agent-Hinweise.
