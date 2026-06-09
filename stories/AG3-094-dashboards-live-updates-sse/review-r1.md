**OVERALL: CHANGES-REQUESTED**

**1) Konzept-Vollstaendigkeit: FAIL**

- **ERROR**: FK-63 §63.3.3 wird nicht vollständig abgedeckt. FK-63 verlangt „Beliebige Start-/End-Daten“, Entity-Filter auf „Guards, Pools oder Templates“, Story-Filter auf „Story-Typ, Story-Groesse oder Pipeline-Modus“ und Vergleich „Zwei Zeitraeume nebeneinander“ (`concept/technical-design/63_auswertung_und_dashboard.md:147`, `:149`, `:151`, `:153`). Die Story macht daraus nur „Filter (Zeitraum/Metrik/Status)“ und „mind. Metrik-Overlay“ (`stories/AG3-094-dashboards-live-updates-sse/story.md:28`).
  **Fix**: Entweder diese FK-63-Filter und den Zwei-Zeitraum-Vergleich als konkrete UI/API-/AC-Pflicht aufnehmen oder die Quell-Konzepte enger schneiden und die fehlenden FK-63-Teile mit Owner auslagern.

- **ERROR**: FK-91 Topic-Katalog wird falsch/unvollständig wiedergegeben. Die Story listet `stories/.../coverage`, aber lässt `failure_corpus` aus (`story.md:9`), obwohl FK-91 es als projekt-skopiertes Topic führt (`concept/technical-design/91_api_event_katalog.md:517`).
  **Fix**: Topic-Liste korrigieren und festlegen, ob AG3-094 `failure_corpus` bewusst nicht nutzt oder in Analytics/Live-Views berücksichtigt.

- **ERROR**: `kpi`-Live-Patch ist im Scope, obwohl das Wire-Schema offen ist. FK-91 sagt für `kpi`: „offen“ (`91_api_event_katalog.md:515`); die Story fordert trotzdem Analytics-Subscribe `kpi,telemetry` (`story.md:26`) und sagt selbst, das Schema müsse vorher festgelegt werden (`story.md:70`).
  **Fix**: `kpi`-Event-Schema inklusive Formal-Spec-Update in diese Story aufnehmen oder KPI-Live-Patching aus AG3-094 herausnehmen.

**2) AC-Schaerfe: FAIL**

- **ERROR**: AC1 ist nicht testbar, solange die Chart-Lib offen ist. AC1 fordert „funktional 1:1 zum Prototyp“ (`story.md:40`), aber die Story sagt „Chart.js vs. ECharts ... Nicht selbst entscheiden“ (`story.md:68`). Der Prototyp nutzt `echarts-for-react` (`frontend/prototype/src/components/AnalyticsView.tsx:15`) und `dataZoom` (`:382`).
  **Fix**: Chart-Lib im Story-Scope festlegen. Danach AC1 auf konkrete Feature-Parität pro Lib schärfen.

- **ERROR**: AC5 testet nicht die zentrale Analytics-Live-Anforderung. Es nennt `stories` und `planning` (`story.md:44`), aber nicht `kpi`/`telemetry`, obwohl Analytics laut Scope `kpi,telemetry` abonniert (`story.md:26`).
  **Fix**: AC für `kpi`-/`telemetry`-Event einfügen: konkretes Event rein, Chart/KPI-Karten re-fetch/patch nachweisbar aktualisiert.

- **WARNING**: AC8 ist zu ungenau: „vier Konzept-Gates“ und „Frontend-Test-/Lint-Lauf“ (`story.md:47`) sind keine reproduzierbaren Befehle.
  **Fix**: Exakte Befehle nennen, inkl. Arbeitsverzeichnis und Package-Manager.

**3) Klarheit/Eindeutigkeit: FAIL**

- **ERROR**: Die Story committet sich zu keiner Chart-Lib. Der Index sagt „Chart.js + SSE“ (`var/concept-gap-analysis/_STORY_INDEX.md:119`), FK-63 nennt Chart.js im Ist-Zustand (`concept/technical-design/63_auswertung_und_dashboard.md:85`), der normative Prototyp nutzt ECharts (`AnalyticsView.tsx:15`). FK-72 sagt zugleich, der Prototyp ist Soll und Konzeptaussagen dürfen ihm nicht widersprechen (`concept/technical-design/72_frontend_architektur.md:383`).
  **Fix**: Owner-Entscheidung in die Story schreiben: entweder ECharts beibehalten und Index/FK-Hinweis nachziehen, oder Chart.js verbindlich mit explizitem Feature-Paritätsnachweis.

- **ERROR**: Vergleichsmodus bleibt offen. Story: „mind. ... ggf. Projekt-/Story-Vergleich“ (`story.md:28`) und „Umfang ... klaeren“ (`story.md:69`). Das ist kein ausführbarer Scope.
  **Fix**: Exakt definieren: z. B. FK-63-konform zwei Zeiträume nebeneinander, plus Metrik-Overlay; Projekt-/Story-Vergleich ausdrücklich out of scope oder als Pflicht aufnehmen.

- **WARNING**: „Kein Polling“ ist sprachlich unsauber gegen die existierende SSE-Implementierung. AG3-003/SSE-Code pollt backendseitig den Event-Store (`src/agentkit/telemetry/sse_stream.py:161`, `:173`), FK-72 verbietet den Frontend-Polling-Loop (`concept/technical-design/72_frontend_architektur.md:280`).
  **Fix**: Formulierung auf „kein Frontend-REST-Polling; nur Initial-GET + EventSource“ ändern.

**4) Kontext-Sinnhaftigkeit: FAIL**

- **ERROR**: Falscher BC-Schnitt. Story nennt „Bounded Context: `frontend`“ (`story.md:5`). FK-72 sagt ausdrücklich: „Es gibt keinen UI-BC“ (`concept/technical-design/72_frontend_architektur.md:56`) und verortet Analytics bei `kpi_analytics` (`:136`).
  **Fix**: BC auf `kpi_analytics` Analytics-Slice + App-Shell/Live-Hook-Komposition ändern; keinen `frontend`-BC behaupten.

- **WARNING**: SSE-Backend-Owner ist bereits AG3-003. AG3-003 ist `completed` (`stories/AG3-003-sse-live-updates/status.yaml:4`) und scoped `/v1/projects/{project_key}/events` inkl. Topics-Filter (`stories/AG3-003-sse-live-updates/story.md:32`). AG3-094 sagt zwar später „Konsument“, aber Scope-Titel „Projekt-skopierte SSE-Live-Streams“ (`story.md:26`) lädt zur Doppelarbeit ein.
  **Fix**: Scope auf „Frontend-SSE-Consumer/Live-Hooks“ umbenennen und Backend-Endpoint-Änderungen explizit ausschließen.

- **PASS-Hinweis**: Die geprüften Ist-Zustand-Line-Claims stimmen: `echarts-for-react` bei `AnalyticsView.tsx:15`, Presets `:27`, Metric-Chips `:186-:202`, `dataZoom` `:382`, `selectProjectKpiStats` `storySelectors.ts:590`, `selectKpiDailySeries` `:652`. FK-Anker §63.2-§63.4, §72.12, §72.14.6 und §91.8 existieren.

**Must-Fix ERROR List**

1. Chart-Lib verbindlich entscheiden und ACs daran schärfen.
2. FK-63-Filter/Vergleich vollständig aufnehmen oder sauber auslagern.
3. `kpi`-Topic-Wire-Schema vor Live-Patch definieren oder KPI-Live-Patch streichen.
4. AC5 um `kpi`/`telemetry`-Analytics-Live-Test ergänzen.
5. FK-91 Topic-Liste inklusive `failure_corpus` korrigieren.
6. BC-Schnitt korrigieren: kein `frontend`-BC, Analytics bei `kpi_analytics` plus App-Shell-Komposition.
