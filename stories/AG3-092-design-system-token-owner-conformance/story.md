# AG3-092: Design-System (Token-Owner + Token-Conformance)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `kpi-and-dashboard` (FK-64) — die visuelle Sprache aller Control-Plane-Sichten. Token-Owner-Komponente + CSS-Custom-Property-Tokens, konsumiert von der Frontend-App-Shell (AG3-093) und den Dashboards/Charts (AG3-094). Die HTTP-Lieferung der Tokens laeuft ueber die `control_plane_http`-`kpi_analytics/http/`-Boundary (AG3-090), nicht ueber einen Endpunkt in `DesignSystem` selbst.
**Quell-Konzepte (autoritativ):**
- `FK-64 §64.2` — Komponenten-Ownership: `kpi-and-dashboard.DesignSystem` haelt **ausschliesslich** Token-Definitionen + Komponentenrichtlinien (Token-Skalen, Typografie, Spacing, Farben, Komponentenregeln), UI-Layer ohne Laufzeit-Logik; gibt **keine** Tokens dynamisch aus und betreibt **keinen eigenen** HTTP-Endpunkt — Boundary-Control bei `control_plane` (`64_control_plane_design_system.md:89-99`).
- `FK-64 §64.5` — Farbsystem: neutrale Farben (`bg-*`/`surface-*`/`border-*`/`text-*`, §64.5.1), Akzentfarben (Tuerkis/Gelb-Orange, §64.5.2), semantische Farben (Success/Warning/Danger/Info/**Done**/**Cancelled**, §64.5.3, `:178-188`).
- `FK-64 §64.6` — Typografie: Schriftfamilien (§64.6.1), Groessenskala `text-xs..text-3xl` mit `px`-Verbot fuer Schriftgroessen (§64.6.2, `:210-220`), semantische Textrollen Label/Body/UI/Title/Panel-Title/Page-Title/KPI (§64.6.3, `:222-237`).
- `FK-64 §64.7` — Spacing/Dimensionen/Border: Spacing-Skala `space-1..space-8` (§64.7.1), Hairline/Border-Token (§64.7.2), Radii small/medium/large/pill (§64.7.3).
- `FK-64 §64.8` — Buttons und Controls: Button-Groessen Standard/Compact/Icon (§64.8.1), Varianten Primary/Secondary/Compact/Ghost/Danger (§64.8.2, `:279-303`) — Quelle der Control-Tokens (Button-Hoehen/-Paddings).
- `FK-64 §64.14` — Status, Badges und Severity: Story-Status-Mapping Backlog/Approved/In Progress/Done/Cancelled (`:412-418`); Severity-Badges PASS/WARNING/ERROR getrennt vom Story-Status (`:420-430`).
- `FK-64 §64.17` — CSS-Architektur: globale Werte als Tokens, View-CSS referenziert Tokens, keine `font-size`-Literale ausserhalb der Token-Definition, Farben ueber Token-Familien, Button-Hoehen/-Paddings ueber Control-Tokens, dynamische Inline-Styles nur fuer datengetriebene Werte (`:454-470`).
- `FK-64 §64.18` — Konformitaetsregel (7 Punkte): semantische Textrollen, Control-Tokens, Statusfarben nicht umdeuten, keine neuen lokalen Schriftgroessen, Pflichtrollen in Sheet/Kanban/Graph/Inspector, Inspector-Tastaturbedienung nicht verschlechtern, Akzente begruendet (`:472-488`).

---

## 1. Kontext / Ist-Zustand (belegt)

Der Prototyp traegt die Design-Werte heute **nur als CSS** ohne typisierten Owner und ohne Conformance-Pruefung:

- Token-/Style-Quelle: `frontend/prototype/src/design-system.css` (CSS-Custom-Properties: Farben `--ak-*` inkl. Status-Tokens `--ak-status-*`/`--ak-done`/`--ak-cancelled`-Aequivalent `--ak-status-cancelled`, Spacing `--space-*`, Radii `--radius-*`, Typo-Skala `--text-*`, semantische Rollen `--type-*`, Control-Tokens `--control-*`) und `frontend/prototype/src/styles.css` (Komponentenklassen wie `ak-panel`, `ak-button`, `ak-badge`, `kpi-tile`). Es gibt **keinen** Python-Token-Owner `kpi-and-dashboard.DesignSystem`.
- Im Repo existieren nur Stubs: `kpi_analytics/views.py:66-74` `DesignTokens` (flaches `dict[str, str]`, „Stub for AG3-029") und `kpi_analytics/top.py:172-184` `get_design_tokens()` (raises `NotImplementedError`, „implemented in follow-up story (FK-64)"). Diese Stubs sind durch das reale Token-Modell zu ersetzen, nicht daneben zu bauen.
- Es gibt keine maschinelle Conformance-Pruefung gegen FK-64 §64.6/§64.8/§64.17/§64.18 (z. B. „keine `font-size`-Literale ausserhalb der Token-Definition").
- Im Prototyp sind Inline-Styles datengetrieben verwendet (zulaessig nach FK-64 §64.17): z. B. `frontend/prototype/src/App.tsx` Slotbar-Breite (`hub-slotbar`, `:1566`), Sparkline-Hoehen (`:2081`), und in `frontend/prototype/src/components/AnalyticsView.tsx` ECharts-Hexwerte (`SERIES_COLORS`, `:38-51`) — Letztere sind Diagramm-Serienfarben; sie werden als eigene Token-Familie `chart.series.*` in den Owner aufgenommen (siehe Scope 2.1.6), weil AG3-094 sie als Tokens konsumiert.

## 2. Scope

### 2.1 In Scope
1. **Python-Token-Owner `kpi-and-dashboard.DesignSystem`** (FK-64 §64.2): typisiertes Datenmodell (Pydantic) der Token-Familien — Farben/Statusfarben (§64.5, inkl. Done/Cancelled), Typografie-Skala + semantische Textrollen (§64.6), Spacing/Radii/Border (§64.7), Control-Tokens fuer Button-Hoehen/-Paddings (§64.8). **Kein eigener** HTTP-Endpunkt **in** `DesignSystem`, **keine** Laufzeit-Logik (FK-64 §64.2). Reine Definition + Komponentenrichtlinien als Datenmodell. Ersetzt den `DesignTokens`-Stub (`kpi_analytics/views.py:66-74`).
2. **`get_design_tokens` als Datenmodell-Lieferung** (nicht Stub): liefert das typisierte Token-Set aus dem Owner; ersetzt den `NotImplementedError`-Stub (`kpi_analytics/top.py:172-184`).
3. **HTTP-Lieferung der Tokens ueber die `control_plane`-Boundary** (FK-64 §64.2): Die Tokens werden ueber die `control_plane_http`-`kpi_analytics/http/`-Adapter-Schicht (Owner AG3-090) als **statischer** Read-Endpoint ausgeliefert. Der Endpunkt liegt **nicht** in `DesignSystem` (FK-64 §64.2: `DesignSystem` betreibt keinen eigenen Endpunkt) und gibt **keine** Tokens dynamisch aus (er serialisiert das deterministische Token-Set des Owners). AG3-090 stellt das `kpi_analytics/http/`-Modul + die projekt-skopierte Konvention bereit; diese Story haengt die Token-Route als duennen Adapter (keine Fachlogik im http-Layer) dort an. **Owner-Klarstellung:** AG3-084 routet Token-Datenmodell **und** HTTP-Lieferung explizit zu AG3-092 (`stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:13`, `:44`); AG3-092 ist damit alleiniger Owner, AG3-084 liefert **keinen** Design-Token-Endpoint.
4. **CSS-Custom-Property-Tokens als Auspraegung des Owners (Single Source of Truth, eine Richtung verbindlich entschieden):** Der **Python-Owner ist die autoritative Token-Definition**; die CSS-Custom-Properties in `design-system.css` sind seine Auspraegung. Diese Story baut einen **deterministischen Conformance-Abgleich**, der belegt, dass `design-system.css` exakt den Owner-Token-Werten entspricht (kein Wert-Drift, kein paralleles Pflegen zweier Listen). Build-Zeit-Generierung der CSS aus dem Owner ist **nicht** verpflichtend; verpflichtend ist der maschinelle Gleichheitsbeleg gegen die normative Prototyp-CSS (die visuellen Werte des Prototyps sind 1:1 zu uebernehmen). Damit ist die in der Review bemaengelte Doppel-Richtung aufgeloest: Owner = Quelle, CSS = gepruefte Auspraegung.
5. **Token-Conformance-Pruefung** gegen FK-64 §64.6/§64.8/§64.17/§64.18: maschinelle Pruefung der **Token-Ebene + View-CSS-Referenzdisziplin**, die mind. folgendes erzwingt:
   - keine `font-size`-Literale ausserhalb der Token-Definition (§64.17, `:464`),
   - keine neuen lokalen Schriftgroessen-Skalen ausserhalb der Token-Definition (§64.18 Pt. 4),
   - Farben nur ueber Token-Familien (Ad-hoc-Hex nur in Token-Definitionen; §64.17, `:466-467`),
   - Button-Hoehen/-Paddings (Control-Groessen) aus Control-Tokens (§64.18 Pt. 2 / §64.17, `:465`),
   - Statusfarben nicht umgedeutet — eine Statusfarb-Familie darf nicht mit fremder Semantik belegt werden (§64.18 Pt. 3 / §64.14).
   Verstoss = Conformance-Fail (Konzept-Drift, FK-64 §64.18).
6. **Chart-Serienfarben-Token-Familie `chart.series.*`** (FK-64 §64.17 / §64.15): die Prototyp-`SERIES_COLORS` (`frontend/prototype/src/components/AnalyticsView.tsx:38-51`) werden als eigene Token-Familie im Owner gefuehrt, sodass Ad-hoc-Chart-Hex aus der Conformance heraus auf Tokens zeigt. AG3-094 konsumiert diese Familie fuer das Chart-Theming (AG3-094 §2.1.6 / AC8); diese Story **definiert** die Familie, **wendet** sie aber nicht in Chart-Komponenten an (das ist AG3-094).
7. **Architektonisch saubere Token-Struktur** (PO-Mandat): die Token-Familien sind klar geschnitten (Color/Status/Typography/Spacing/Control/Chart) statt als flache CSS-Wand — besserer Aufbau als der Prototyp, funktional dieselben visuellen Werte.

### 2.2 Out of Scope (mit Owner)
- **`control_plane_http`-Namespace + `kpi_analytics/http/`-Adapter-Modul + projekt-skopierte URL-Konvention/Tenant-Scope-Middleware** — **AG3-090** (`depends_on`). FK-64 §64.2: Boundary-Control bei `control_plane`. AG3-092 haengt die Token-Route an das von AG3-090 bereitgestellte `kpi_analytics/http/`-Modul; sie baut **keine** eigene HTTP-Topologie/Middleware. Liegt das Modul/die Konvention bei Implementierungsbeginn nicht vor, wird die Abhaengigkeit gemeldet (kein Eigenbau).
- **Frontend-Read-Model-/API-Surface-Konvention** (`/v1/projects/{key}/...`) — **AG3-091**. Diese Story richtet die Token-Route nach dieser Konvention aus; sie definiert die Konvention nicht selbst.
- **Anwendung der Tokens in App-Shell/Views + Pflichtrollen-Vergabe in Sheet/Kanban/Graph/Inspector** (FK-64 §64.18 Pt. 5/6) — **AG3-093**. Die view-seitige Vergabe der semantischen Pflichtrollen und die Inspector-Tastaturbedienung sind Frontend-Komponentenbau und werden in AG3-093 verprobt; AG3-092 liefert nur die Token-Familien + die Token-Ebenen-Conformance, **nicht** den Pflichtrollen-Audit pro View (siehe AC4-Begruendung).
- **Chart-Theming** (ECharts-Farbbindung der Serien/Achsen/Grid an die `chart.series.*`-Tokens) — **AG3-094** (Dashboards/Charts). Diese Story definiert die Token-Familie; AG3-094 wendet sie an.
- **Frontend-Conformance als Python-Architektur-Konformanz** — FK-72 §72.10 stellt klar: Frontend-Code ist nicht im Scope der Python-Architektur-Konformanz. Die Token-Conformance hier ist eine **eigene** Design-System-Pruefung, kein Python-`entities.md`-Eintrag.

## 3. Akzeptanzkriterien
1. `kpi-and-dashboard.DesignSystem` existiert als typisierter Token-Owner (Pydantic) mit Color-/Status-/Typography-/Spacing-/Control-/Chart-Familien gemaess FK-64 §64.5/§64.6/§64.7/§64.8; **kein** HTTP-Endpunkt in `DesignSystem`, **keine** Laufzeit-Logik (Test: Modell instanziierbar, keine I/O). Der `DesignTokens`-Stub (`kpi_analytics/views.py:66-74`) ist ersetzt.
2. `get_design_tokens` liefert das typisierte Token-Set aus dem Owner (Datenmodell, nicht Stub; `kpi_analytics/top.py:172-184` ist real) — Test: Rueckgabe enthaelt alle Token-Familien, deterministisch.
3. Die Tokens sind ueber die `control_plane_http`-`kpi_analytics/http/`-Boundary (AG3-090) als statischer Read-Endpoint erreichbar; der Endpunkt liegt **nicht** in `DesignSystem` und gibt das deterministische Owner-Token-Set aus (Test: Route serialisiert das Owner-Set, kein dynamisches Berechnen). Liegt die AG3-090-Boundary noch nicht vor, wird die Abhaengigkeit gemeldet (kein HTTP-Eigenbau).
4. CSS-Tokens und Python-Owner sind **eine** Wahrheit, Richtung Owner→CSS: ein deterministischer Abgleich belegt, dass die CSS-Custom-Properties in `frontend/prototype/src/design-system.css` exakt den Owner-Token-Werten entsprechen (kein Wert-Drift). Negativtest: ein eingeschleuster CSS-Wert-Drift wird vom Abgleich erkannt.
5. Token-Conformance-Pruefung schlaegt fehl bei je einem gezielt eingeschleusten Verstoss (Negativtests):
   - `font-size`-Literal ausserhalb der Token-Definition (§64.17);
   - neue lokale Schriftgroessen-Skala ausserhalb der Token-Definition (§64.18 Pt. 4);
   - Ad-hoc-Hex ausserhalb Token-Definition (§64.17);
   - nicht-Token-Control-Groesse (Button-Hoehe/-Padding ausserhalb der Control-Tokens, §64.18 Pt. 2);
   - umgedeutete Statusfarbe (eine Statusfarb-Familie mit fremder Semantik belegt, §64.18 Pt. 3 / §64.14).
6. Token-Conformance-Pruefung ist PASS auf dem konformen Token-Set/Prototyp-CSS (Positivtest).
7. Statusfarben-Familie deckt die FK-64-§64.5.3/§64.14-Semantik **vollstaendig** ab: `success/warning/danger/info` (Severity-/Gate-Semantik) **plus** `done` und `cancelled` (Story-Terminalzustaende) **plus** die Story-Status-Tokens `backlog/approved/in_progress` (FK-64 §64.14, Prototyp `--ak-status-*`/`--ak-done`/`--ak-status-cancelled`, `design-system.css:56-66`/`:255-283`) ohne Umdeutung (Test: Mapping stabil, Story-Status→Token deckt Backlog/Approved/In Progress/Done/Cancelled).
8. Chart-Serienfarben-Familie `chart.series.*` existiert im Owner (deckt die Prototyp-`SERIES_COLORS`, `AnalyticsView.tsx:38-51`, ab) und ist Teil des `get_design_tokens`-Outputs; ein Test belegt, dass die Familie die im Prototyp genutzten Serienfarben referenziert (Token statt Ad-hoc-Hex), damit AG3-094 sie konsumieren kann.
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

10. **End-to-End ohne Stub (Frontend-Abnahme-Haertekriterium, verbindlich — User-Direktive 2026-06-11):** Diese Story gilt **erst dann als fertig**, wenn die Token-Lieferung **End-to-End gegen die reale `control_plane`-Backend-Surface** verprobt ist — **ohne Stubbing/`NotImplemented`** an der Token-Owner- oder HTTP-Grenze: ein echter Consumer-Request laeuft ueber die reale `control_plane_http`-`kpi_analytics`-Boundary an den realen Token-Owner und liefert das echte typisierte Token-Set zurueck, belegt durch einen **echten End-to-End-Integrationstest** (kein Mock an der Owner-/HTTP-Grenze; der bestehende `NotImplemented`-Stub ist nachweislich ersetzt). Verbot von „Token-Owner gebaut, aber HTTP-Surface nicht real verdrahtet".

## 4. Definition of Done
- AK 1–10 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** **ein** Token-Owner als Quelle; CSS-Tokens sind dessen gepruefte Auspraegung (Richtung Owner→CSS festgelegt), keine zweite parallel gepflegte Wertliste.
- **TYPISIERT STATT STRINGS:** Token-Familien als Pydantic-Modell, keine losen Dicts/Strings (der flache `dict[str, str]`-Stub wird ersetzt).
- **KEINE LAUFZEIT-LOGIK / BOUNDARY-RESPEKT:** `DesignSystem` ist UI-Layer-Definition ohne Endpunkt/IO (FK-64 §64.2); die HTTP-Token-Lieferung laeuft ueber die `control_plane_http`-`kpi_analytics/http/`-Boundary (AG3-090), nicht ueber `DesignSystem`.
- **FAIL CLOSED:** Conformance-Verstoss ist ein Fehler (Konzept-Drift), keine Warnung-zum-Wegklicken (FK-64 §64.18).
- **ARCH-55:** Token-Namen, Rollen-Bezeichner, Modellfelder englisch; deutsche UI-Label sind die einzige erlaubte Ausnahme (nicht Teil der Token-Definition).
- **ZERO DEBT:** `get_design_tokens` und das Token-Modell sind real (Datenmodell), kein Stub-als-Done; beide Stubs (`views.py:66-74`, `top.py:172-184`) werden ersetzt.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Normative funktionale Soll-Quelle (Concept-as-Code): `frontend/prototype/src/design-system.css` + `frontend/prototype/src/styles.css` (Token-Werte, Komponentenklassen `ak-panel`/`ak-badge`/`ak-button`/`kpi-tile`). Die visuellen Werte sind 1:1 zu uebernehmen, aber sauber in Token-Familien geschnitten.
- FK-64 §64.2 ist der harte Boundary-Hinweis: **kein** Endpunkt **in** `DesignSystem`. Die HTTP-Token-Lieferung gehoert in das `control_plane_http`-`kpi_analytics/http/`-Adapter-Modul (AG3-090) als duenner, statischer Read-Adapter — Boundary-Control bei `control_plane`. AG3-092 ist Owner des Token-Modells **und** dieser Token-Route (AG3-084 routet beides hierher, `AG3-084/story.md:13`/`:44`); baue aber **keine** eigene HTTP-Topologie/Middleware (das ist AG3-090).
- FK-64-§§ exakt: Farben/Status §64.5, Typografie §64.6, Spacing/Border/Radii §64.7, Buttons/Control-Tokens §64.8, Status/Severity §64.14, CSS-Architektur §64.17, Konformitaetsregel §64.18. (Die fruehere Story-Behauptung „Control-Tokens/Statusfarben in §64.5-§64.7" war falsch gemappt und ist korrigiert.)
- Stubs ersetzen, nicht daneben bauen: `kpi_analytics/views.py:66-74` (`DesignTokens`) und `kpi_analytics/top.py:172-184` (`get_design_tokens`).
- Statusfarben **vollstaendig**: Done und Cancelled (FK-64 §64.5.3, `:178-188`) sowie die Story-Status-Tokens (FK-64 §64.14, `:412-418`) gehoeren ins Modell und in die Tests — nicht nur success/warning/danger/info.
- Pflichtrollen-Vergabe pro View (Sheet/Kanban/Graph/Inspector, §64.18 Pt. 5/6) ist **nicht** AG3-092, sondern AG3-093 (Frontend-Views). AG3-092 liefert die Token-Familien + die Token-Ebenen-/CSS-Referenz-Conformance.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Conformance-Negativ-/Positivtests (alle fuenf Negativfaelle aus AC5), CSS-↔-Owner-Abgleichtest (AC4), Statusfarben-Vollstaendigkeitstest (AC7), `chart.series.*`-Test (AC8).

## 7. Cross-Story-Voraussetzungen / geklaerte Punkte
- **`get_design_tokens`-Owner (geklaert):** Token-Datenmodell **und** HTTP-Lieferung gehoeren zu AG3-092. AG3-084 hat den Schnitt bereits zugunsten AG3-092 entschieden und liefert keinen Design-Token-Endpoint (`stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:13`, `:44`). Damit ist die fruehere zyklische „AG3-092 depends_on AG3-084 fuer den Endpoint"-Konstruktion aufgeloest; AG3-092 haengt fuer die HTTP-Boundary an **AG3-090** (control_plane_http + `kpi_analytics/http/`).
- **Chart-Serienfarben-Tokens (geklaert):** `chart.series.*` ist Teil von AG3-092 (Scope 2.1.6 / AC8), weil AG3-094 sie als Tokens konsumiert (`stories/AG3-094-dashboards-live-updates-sse/story.md:44`, AC8 `:75`). Die fruehere offene Frage „Chart-Serienfarben als Tokens?" ist damit zugunsten „ja, Token-Familie im Owner" entschieden.
- **Token-Generierungsrichtung (geklaert):** Owner ist Quelle, CSS ist gepruefte Auspraegung (Scope 2.1.4 / AC4); keine Build-Zeit-Generierung verpflichtend, aber deterministischer Gleichheitsbeleg.
- **Genuine Cross-Story-Voraussetzung:** AG3-090 muss das `control_plane_http`-`kpi_analytics/http/`-Adapter-Modul + die projekt-skopierte Konvention bereitstellen, bevor die Token-HTTP-Route (AC3) implementierbar ist; AG3-091 liefert die Read-Model-/URL-Konvention. Fehlt beides bei Implementierungsbeginn, ist die Token-Datenmodell-Lieferung (AC1/AC2) + Conformance (AC4-AC8) trotzdem baubar; nur AC3 (HTTP-Route) wartet auf AG3-090.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
