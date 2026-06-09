# AG3-092 — Remediation R1

Antwort auf `review-r1.md` (CHANGES-REQUESTED). Geaendert wurden ausschliesslich
`story.md` und `status.yaml` von AG3-092. Kein Produktionscode, keine Tests, keine
`concept/`-Dateien, keine Fremd-Story-Dateien.

## Must-Fix-Findings → Resolution

### 1. `get_design_tokens`-Owner-Konflikt AG3-092/AG3-084 (ERROR, Konzept-Vollstaendigkeit + Kontext-Sinnhaftigkeit)
**Befund:** AG3-092 wies den HTTP-Endpoint AG3-084 zu, AG3-084 routet Datenmodell **und** HTTP-Lieferung explizit nach AG3-092 → zyklisch / Owner-Duplikat.
**Resolution (in-story, Owner-Entscheidung uebernommen, die AG3-084 bereits getroffen hat):**
- AG3-092 ist jetzt alleiniger Owner von Token-Datenmodell **und** HTTP-Lieferung (Scope 2.1.3, AC3, §7). Begruendung mit Beleg: `AG3-084/story.md:13` + `:44` routen beides hierher und AG3-084 liefert keinen Token-Endpoint.
- FK-64-§64.2-Boundary gewahrt: Der Endpunkt liegt **nicht in** `DesignSystem`, sondern als duenner, statischer Read-Adapter in der `control_plane_http`-`kpi_analytics/http/`-Schicht (Owner AG3-090). `DesignSystem` betreibt weiterhin keinen eigenen Endpunkt und gibt nichts dynamisch aus.
- Zyklus aufgeloest: `depends_on` von AG3-084 auf **AG3-090** geaendert (AG3-090 stellt das `kpi_analytics/http/`-Modul + die URL-Konvention; das ist die reale HTTP-Boundary-Voraussetzung). Beleg AG3-090: `stories/AG3-090-bff-topology-control-plane-http/story.md:9`, `:44` (kpi_analytics/http/-Modul). Kein Fremd-Story-File geaendert; nur AG3-092 self-consistent gemacht.

### 2. FK-64-Abschnittsreferenzen falsch gemappt (ERROR, Konzept-Vollstaendigkeit)
**Befund:** „Control-Tokens/Statusfarben in §64.5-§64.7" ist falsch; real: §64.5 Farben, §64.6 Typografie, §64.7 Spacing, §64.8 Controls, §64.14 Status/Severity.
**Resolution:** Quell-Konzepte (Kopf), Scope und AC durchgaengig auf die realen §§ korrigiert: §64.5 Farben/Status, §64.6 Typografie, §64.7 Spacing/Border/Radii, §64.8 Buttons/Control-Tokens, §64.14 Status/Severity, §64.17 CSS-Architektur, §64.18 Konformitaetsregel. Anker mit Zeilenbelegen ergaenzt (`64_control_plane_design_system.md:178-188`, `:279-303`, `:412-430`, `:454-488`).

### 3. Status-/Chart-Token-Abdeckung unvollstaendig (ERROR, Konzept-Vollstaendigkeit + WARNING Klarheit)
**Befund:** AC6 forderte nur success/warning/danger/accent/neutral/info; FK-64 verlangt zusaetzlich Done + Cancelled + Story-Status-Mapping; Prototyp hat `--ak-done`/`--ak-status-*`. Zudem fordert AG3-094 bereits Chart-Tokens aus AG3-092.
**Resolution:**
- AC7 (vormals AC6) deckt jetzt success/warning/danger/info **plus** done/cancelled **plus** Story-Status-Tokens backlog/approved/in_progress ab (FK-64 §64.5.3 `:178-188`, §64.14 `:412-418`; Prototyp `design-system.css:56-66`/`:255-283`). Mapping deckt alle fuenf Story-Status.
- Neue Scope 2.1.6 + AC8: Chart-Serienfarben-Familie `chart.series.*` aus den Prototyp-`SERIES_COLORS` (`AnalyticsView.tsx:38-51`) im Owner; konsumiert von AG3-094 (`AG3-094/story.md:44`, AC8 `:75`). Offene Frage 7 „Chart-Serienfarben als Tokens?" damit zugunsten „ja" entschieden — beseitigt den Widerspruch zu AG3-094.

### 4. Falscher `AnalyticsView.tsx`-Pfad (ERROR, Klarheit)
**Befund:** `frontend/prototype/src/AnalyticsView.tsx` existiert nicht; real `frontend/prototype/src/components/AnalyticsView.tsx`.
**Resolution:** Alle Anker (Ist-Zustand §1, Scope 2.1.6, AC8, §7) auf `frontend/prototype/src/components/AnalyticsView.tsx:38-51` korrigiert (verifiziert via Glob/Read).

### 5. AC-Negativtests fuer alle beanspruchten Conformance-Regeln (ERROR, AC-Schaerfe)
**Befund:** AC4 testete nur font-size/Hex/Control-Groesse; Scope beansprucht Statusfarben-nicht-umdeuten + Typo-Rollen.
**Resolution:** AC5 listet jetzt fuenf gezielte Negativtests: (a) font-size-Literal, (b) neue lokale Schriftgroessen-Skala (§64.18 Pt.4), (c) Ad-hoc-Hex, (d) nicht-Token-Control-Groesse (§64.18 Pt.2), (e) umgedeutete Statusfarbe (§64.18 Pt.3 / §64.14). Der per-View-Pflichtrollen-Audit (§64.18 Pt.5/6, Sheet/Kanban/Graph/Inspector) wurde **bewusst aus Scope genommen** und an AG3-093 (Frontend-Views) geroutet (Scope 2.2), da er view-/komponentenseitig ist, nicht token-/CSS-referenzseitig — saubere Schnitt-Begruendung statt halbem Anspruch.

### 6. `status.yaml` `unblocks` inkonsistent (WARNING, Kontext-Sinnhaftigkeit)
**Befund:** AG3-093 depends_on AG3-092, aber AG3-092 hatte `unblocks: []`.
**Resolution:** `unblocks: [AG3-093, AG3-094]` gesetzt (AG3-093 direkt, `AG3-093/status.yaml:8-10`; AG3-094 konsumiert die Token-Familien, `AG3-094/story.md:44`/AC8). `depends_on` zugleich auf AG3-090 korrigiert (siehe Finding 1).

## WARNING-Findings → Resolution

### „CSS-Tokens und Python-Owner sind eine Wahrheit" operativ unscharf (WARNING, AC-Schaerfe)
**Resolution:** Richtung verbindlich entschieden — **Owner = Quelle, CSS = gepruefte Auspraegung** (Scope 2.1.4, AC4, §7). Keine Build-Zeit-Generierung verpflichtend; verpflichtend ist der deterministische Gleichheitsbeleg + Negativtest gegen eingeschleusten CSS-Drift.

### „Chart-Serienfarben als Tokens?" offen vs. AG3-094-Anspruch (WARNING, Klarheit)
**Resolution:** Siehe Finding 3 — Familie `chart.series.*` in Scope aufgenommen; Widerspruch zu AG3-094 beseitigt; AG3-094 unveraendert (kein Fremd-File angefasst).

## Genuine Cross-Story-Voraussetzung (gemeldet, nicht hier geschlossen)
- **AG3-090** muss das `control_plane_http`-`kpi_analytics/http/`-Adapter-Modul + die projekt-skopierte URL-Konvention bereitstellen, bevor die Token-HTTP-Route (AC3) implementierbar ist; **AG3-091** liefert die Read-Model-/URL-Konvention. Token-Datenmodell (AC1/AC2) + Conformance (AC4–AC8) sind unabhaengig davon baubar; nur AC3 wartet auf AG3-090. Dokumentiert in story.md §7. (Hinweis: Der Master-Index `_STORY_INDEX.md:117` listet AG3-092 noch mit `depends_on AG3-084` und FK-64 §64.2/§64.5-§64.7; die Korrektur des Index-Eintrags ist eine PO/Index-Owner-Aktion — nicht story-seitig ueberschrieben.)

## Geaenderte Dateien (nur AG3-092)
- `stories/AG3-092-design-system-token-owner-conformance/story.md` (vollstaendig ueberarbeitet, AG3-057-Template-Struktur beibehalten)
- `stories/AG3-092-design-system-token-owner-conformance/status.yaml` (`depends_on`, `unblocks`)
- `stories/AG3-092-design-system-token-owner-conformance/remediation-r1.md` (dieses Dokument)
