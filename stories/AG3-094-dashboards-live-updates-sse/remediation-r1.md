# AG3-094 — Remediation R1 (Antwort auf review-r1.md, giftige Codex-Review)

**Scope der Remediation:** ausschliesslich `story.md` rewrite (+ Pruefung `status.yaml`). Kein Produktionscode, keine Tests, keine `concept/`-Dateien beruehrt. Prototyp (`AnalyticsView.tsx`/`storySelectors.ts`) ist normative Soll-Quelle; alle Anker gegen die realen Dateien verifiziert.

**Methodik:** jeden zitierten Anker gegen die echte Datei:Zeile gegengelesen (FK-63/FK-72/FK-91, Prototyp, AG3-003, _STORY_INDEX). Review-Zeilennummern sind 1-basiert und stimmten alle; korrigiert wurden nur unscharfe/fehlende Verweise in der Story selbst.

---

## 1. Konzept-Vollstaendigkeit

### ERROR — FK-63 §63.3.3 unvollstaendig (Filter + Zwei-Zeitraum-Vergleich)
**Befund:** Story machte aus §63.3.3 (beliebiger Zeitraum, Entity-Filter Guards/Pools/Templates, Story-Filter Typ/Groesse/Modus, Zwei-Zeitraum-Vergleich) nur „Filter (Zeitraum/Metrik/Status)" + „mind. Metrik-Overlay".
**Resolution:** In Scope 2.1.5 vollstaendig aufgenommen: Custom-Zeitraum (beliebige Start-/End-Daten), Entity-Filter (Guards/Pools/Templates), Story-Filter (Typ/Groesse/Pipeline-Modus), Zwei-Zeitraum-Vergleich nebeneinander + Metrik-Overlay. Als serverseitige Query-Parameter an `/api/kpi/*` (AG3-084) durchgereicht, kein clientseitiges Nachrechnen. AC7 macht das testbar (UI-Auswahl → korrekte Query-Parameter). Projekt-/story-uebergreifender Cross-Entity-Vergleich explizit Out of Scope (FK-63 fordert ihn nicht). Anker korrigiert auf §63.3.3 Z.142-154 (Story zitierte vorher das ungenaue „§63.4").

### ERROR — FK-91 Topic-Katalog falsch (`failure_corpus` fehlte)
**Befund:** Story listete den Topic-Katalog ohne `failure_corpus`, obwohl FK-91 §91.8.3 (Z.517) es als projekt-skopiertes Topic fuehrt.
**Resolution:** Festgelegt, dass AG3-094 `failure_corpus` **nutzt** — als Funnel in Analytics, gestuetzt auf FK-72 §72.11.3 (Z.258: „failure_corpus — Funnel in Analytics, kein eigenes Browser-View in v1"). Analytics-Topic-Set ist jetzt `kpi,telemetry,failure_corpus` (Scope 2.1.3, AC3). Eigenes Failure-Corpus-Browser-View an **AG3-078** geroutet (Out of Scope). Quell-Konzept-Anker auf FK-91 §91.8.3 Z.506-518 praezisiert.

### ERROR — `kpi`-Live-Patch trotz offenem Wire-Schema
**Befund:** Story forderte Analytics-Subscribe `kpi,telemetry` + KPI-Live-Patch, sagte aber selbst, das Schema sei offen (FK-91 §91.8.3 Z.515: `kpi` = „offen").
**Resolution:** KPI-**feldgranulares** Patching aus dem Event-Payload aus dem Scope genommen (Out of Scope, an AG3-081/AG3-084 + Formal-Spec geroutet). AG3-094 abonniert `kpi` und macht bei einem `kpi`-Event nur **Re-Fetch (Initial-GET-Re-Sync)** der Analytics-Sicht — robust gegen das offene Schema. AC5 entsprechend praezisiert (Re-Sync, kein Event-Patch). Damit ist die Story nicht mehr von der offenen Schema-Definition blockiert.

## 2. AC-Schaerfe

### ERROR — AC1 nicht testbar (Chart-Lib offen)
**Befund:** AC1 „funktional 1:1 zum Prototyp", aber Chart-Lib „nicht selbst entscheiden".
**Resolution:** Chart-Lib im Scope verbindlich entschieden = **ECharts** (Scope 2.1.2, Begruendung FK-72 §72.13 Z.383-385: Prototyp ist Soll). AC1 auf konkrete ECharts-Feature-Paritaet geschaerft: Aggregat-Karten, Multi-Series, Preset+Custom-Zeitraum, Min/Max-Band-Toggle, `dataZoom` inside+slider, Cross-`axisPointer`-Tooltip mit Band-Helper-Filter — je ein Komponententest.

### ERROR — AC5 ohne `kpi`/`telemetry`-Analytics-Live-Test
**Befund:** AC5 testete nur `stories`/`planning`, nicht das zentrale Analytics-Live (`kpi`/`telemetry`).
**Resolution:** AC5 um `kpi`-Event (loest Analytics-Re-Fetch/Re-Sync aus, Karten/Charts zeigen neuen `/api/kpi/*`-Stand) und `telemetry`-Event (Mode-Lock-Projektion aktualisiert abhaengigen UI-Anteil) erweitert.

### WARNING — AC8 zu ungenau (Gates/Frontend-Lauf)
**Befund:** „vier Konzept-Gates" + „Frontend-Test-/Lint-Lauf" sind keine reproduzierbaren Befehle.
**Resolution:** Zu AC9 (vorher AC8) ausgebaut mit exakten Befehlen inkl. Arbeitsverzeichnis (Repo-Root) und Package-Manager: `.venv\Scripts\python -m pytest tests/{unit,integration,contract} -n0`, `mypy src` + `--platform linux`, `ruff check src tests`, Coverage-Befehl mit `--cov-fail-under=85`, Konzept-Gate-Suite, und Frontend `npm run build|test|lint` im AG3-093-Frontend-Ordner (Package-Manager wie dort; Prototyp = npm).

## 3. Klarheit/Eindeutigkeit

### ERROR — keine Chart-Lib-Festlegung
**Befund:** Index sagt Chart.js, FK-63 Ist-Zustand Chart.js, Prototyp ECharts; FK-72 sagt Prototyp ist Soll.
**Resolution:** Owner-Entscheidung in die Story geschrieben: **ECharts beibehalten** (Prototyp normativ, FK-72 §72.13 Z.383-385). Klargestellt, dass die Chart.js-Erwaehnung (Index Z.119, FK-63 Z.85) das **alte stdlib-QA-Dashboard** (Ist-Zustand) meint, nicht die Soll-App. Index-/FK-Prosa-Nachzug auf ECharts an **AG3-103** (doc-only) delegiert — kein Code-Anteil hier.

### ERROR — Vergleichsmodus offen
**Befund:** „mind. … ggf. Projekt-/Story-Vergleich" + „Umfang … klaeren" = nicht ausfuehrbar.
**Resolution:** Exakt definiert (Scope 2.1.5): Zwei-Zeitraum-Vergleich (FK-63-konform) **plus** Metrik-Overlay = Pflicht; projekt-/story-uebergreifender Cross-Entity-Vergleich = explizit Out of Scope. Keine offenen „klaeren"-Formulierungen mehr im Scope.

### WARNING — „Kein Polling" sprachlich unsauber
**Befund:** Backend-SSE pollt den Event-Store (`sse_stream.py`); FK-72 verbietet nur den Frontend-Polling-Loop.
**Resolution:** Durchgaengig auf „kein **Frontend-REST-Polling-Loop**; nur Initial-GET + `EventSource`" umformuliert (Scope 2.1.3, AC4, Guardrail-Block). Explizit ergaenzt, dass der serverseitige Event-Store-Poll Sache von AG3-003 und **nicht** Gegenstand dieser Story ist. Anker FK-72 §72.12.1 Z.281.

## 4. Kontext-Sinnhaftigkeit

### ERROR — falscher BC-Schnitt (`frontend`)
**Befund:** Story behauptete „Bounded Context: `frontend`"; FK-72 §72.3 (Z.56) „Es gibt keinen UI-BC", Analytics bei `kpi_analytics` (§72.6 Z.136).
**Resolution:** BC korrigiert auf **`kpi_analytics`-Analytics-Slice (Composer) + App-Shell-Live-Hook-Komposition**; „kein `frontend`-BC" mit Anker FK-72 §72.3 Z.56 / §72.6 Z.136 explizit notiert. Guardrail-Block „KEIN UI-BC" ergaenzt.

### WARNING — SSE-Backend-Owner ist AG3-003
**Befund:** Scope-Titel „Projekt-skopierte SSE-Live-Streams" lud zur Doppelarbeit ein; AG3-003 (`completed`) besitzt `/v1/projects/{key}/events` + Topics-Filter.
**Resolution:** Story-Titel und Scope auf **„Frontend-SSE-Consumer/Live-Hooks"** umbenannt. Backend-Endpoint-Aenderungen explizit ausgeschlossen (Out of Scope: „AG3-094 aendert keine Backend-Endpoints und baut nur den Frontend-Consumer"; AG3-003 als `depends_on`/`completed` benannt). `depends_on` in status.yaml fuehrt AG3-003 bereits korrekt.

---

## Must-Fix ERROR-Liste (1:1 Abgleich)

| # | Must-Fix (review-r1.md) | Status | Wo |
|---|---|---|---|
| 1 | Chart-Lib verbindlich + ACs schaerfen | RESOLVED | Scope 2.1.2, AC1 |
| 2 | FK-63-Filter/Vergleich vollstaendig oder auslagern | RESOLVED | Scope 2.1.5, AC7, Out-of-Scope (Cross-Entity) |
| 3 | `kpi`-Wire-Schema vor Live-Patch oder KPI-Live-Patch streichen | RESOLVED | KPI-feldgranular gestrichen → Re-Fetch; Out of Scope an AG3-081/084 |
| 4 | AC5 um `kpi`/`telemetry`-Analytics-Live-Test | RESOLVED | AC5 |
| 5 | FK-91 Topic-Liste inkl. `failure_corpus` | RESOLVED | Quell-Konzepte, Scope 2.1.3, AC3; Browser-View an AG3-078 |
| 6 | BC-Schnitt korrigieren (kein `frontend`, Analytics = `kpi_analytics`) | RESOLVED | BC-Zeile, Guardrail-Block |

## Warnings (1:1 Abgleich)

| Warning | Status | Wo |
|---|---|---|
| AC8 unpraezise Befehle | RESOLVED (in Story gefixt) | AC9 |
| „Kein Polling" sprachlich | RESOLVED (in Story gefixt) | Scope 2.1.3, AC4, Guardrails |
| SSE-Backend-Owner AG3-003 | RESOLVED (in Story gefixt + Owner-Routing) | Titel, Scope, Out of Scope |

## Anker-Korrekturen (falsch/ungenau → real)

- BC: `frontend` → `kpi_analytics` (FK-72 §72.6 Z.136), „kein UI-BC" (FK-72 §72.3 Z.56).
- Filter-Anker: ungenaues „§63.4" → **§63.3.3 Z.142-154**.
- Topic-Katalog: **§91.8.3 Z.506-518** (statt pauschal §91.8); `failure_corpus` Z.517; `kpi`-offen Z.515.
- Lossy-Re-Sync: praezisiert auf **§72.12.4 Z.306** (Story zitierte zuvor §72.14.6 nur fuer Reconnect/Offline; §72.14.6 Z.503 bleibt korrekt fuer Edge-Cases).
- Pattern Initial-GET+Subscribe: **§72.12.1 Z.270/Z.280-281**.
- Prototyp-Normativitaet: **FK-72 §72.13 Z.383-385**.
- Hub zurueckgestellt: **FK-91 §91.8.4 Z.520**.
- Prototyp-Selektor-Pfad vervollstaendigt: `frontend/prototype/src/store/storySelectors.ts:590`/`:652` (Story hatte teils nur `store/storySelectors.ts`).
- Prototyp-Feature-Anker praezisiert: `dataZoom` `:382`-`:398`, Band `:284`-`:316`, Cross-Tooltip `:342`/`:344`-`:356`, Presets `:27`-`:32`, `SERIES_COLORS` `:38`-`:51`.

## PASS-Hinweis-Bestaetigung

Die vom Review als korrekt bestaetigten Ist-Zustand-Anker (`echarts-for-react` `AnalyticsView.tsx:15`, Presets `:27`, Metric-Chips `:186-:202`, `dataZoom` `:382`, `selectProjectKpiStats` `storySelectors.ts:590`, `selectKpiDailySeries` `:652`) wurden nachgeprueft und unveraendert/praezisiert uebernommen.

---

## status.yaml

Geprueft, **nicht geaendert**. Felder korrekt: `status: draft`, `phase: review_pending`, `depends_on: [AG3-084, AG3-093, AG3-003]` (deckt sich mit _STORY_INDEX Z.119 und dem korrigierten Scope: AG3-003 = SSE-Backend, AG3-084 = KPI-Endpoints, AG3-093 = App-Shell). `type: implementation`, `size: M` stimmen mit Index ueberein. Kein falsches Feld gefunden.

## Geaenderte/geschriebene Dateien

- `stories/AG3-094-dashboards-live-updates-sse/story.md` — rewrite (Template-Struktur von AG3-057 beibehalten).
- `stories/AG3-094-dashboards-live-updates-sse/remediation-r1.md` — dieser Report.
- `status.yaml` — **nicht** geaendert (alle Felder korrekt).

Scope strikt innerhalb des _STORY_INDEX-Schnitts (Z.119) gehalten: Dashboards/Charts auf KPI-Endpoints + projekt-skopierter Frontend-SSE-Consumer + Vergleichs-/Filter-UI. Keine Scope-Erweiterung; alle ueber den Schnitt hinausgehenden Punkte an Owner-Stories (AG3-003/078/081/084/092/093/103) geroutet.
