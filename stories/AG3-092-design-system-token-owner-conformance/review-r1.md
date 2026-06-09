CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**
- ERROR: AG3-092 weist den HTTP-`get_design_tokens`-Endpoint AG3-084 zu (`stories/AG3-092.../story.md:38-39`), AG3-084 routet aber Design-Token-Datenmodell **und HTTP-Lieferung** explizit nach AG3-092 und nennt AG3-084+später AG3-092 zyklisch (`stories/AG3-084.../story.md:11-14`). Fix: Schnitt eindeutig entscheiden; nach aktueller AG3-084-Story muss AG3-092 den Endpoint entweder selbst liefern oder AG3-084/Index vorher korrigiert werden.
- ERROR: FK-64-Abschnitte sind falsch gemappt. AG3-092 behauptet Control-Tokens/Statusfarben in §64.5-§64.7 (`story.md:8`, `:26`, `:29`), tatsächlich sind §64.5 Farben, §64.6 Typografie, §64.7 Spacing; Controls stehen in §64.8 (`concept/technical-design/64_control_plane_design_system.md:279-303`), Status/Severity in §64.14 (`:407-430`). Fix: Referenzen und Scope/AC auf §64.5, §64.6, §64.7, §64.8, §64.14, §64.17, §64.18 korrigieren.
- ERROR: Statusfarben-AC ist unvollständig. AG3-092 AC6 fordert nur `success/warning/danger/accent/neutral/info` (`story.md:50`), FK-64 verlangt zusätzlich `Done` und `Cancelled` (`64_control_plane_design_system.md:178-188`) und Story-Status-Mapping (`:412-418`); der Prototyp hat auch `--ak-done`/Status-Tokens (`frontend/prototype/src/design-system.css:56-66`, `:255-258`). Fix: Done/Cancelled und Story-Status-Tokens in Modell und Tests aufnehmen.

**AC-Schaerfe: WEAK**
- ERROR: Conformance-AC deckt nicht den eigenen Scope ab. Scope fordert Statusfarben-nicht-umdeuten und semantische Textrollen/Pflichtrollen aus §64.18 (`story.md:29-35`), AC4 testet aber nur `font-size`, Hex und Control-Groesse (`story.md:48`). Fix: Negativtests für Statusfarben-Umdeutung, neue/lokale Typo-Rollen und fehlende Pflichtrollen in Sheet/Kanban/Graph/Inspector ergänzen oder diese bewusst aus Scope nehmen.
- WARNING: “CSS-Tokens und Python-Owner sind eine Wahrheit” bleibt operativ unscharf, weil die Story zwei Richtungen zulässt (`story.md:28`, `:74`). Fix: vor Autorisierung eine Richtung festlegen: Generierung aus Owner oder CSS als Quelle plus deterministischer Abgleich.

**Klarheit: FAIL**
- ERROR: Falscher Prototyp-Anker: `frontend/prototype/src/AnalyticsView.tsx` existiert nicht (`story.md:21`, `:73`). Realer Pfad ist `frontend/prototype/src/components/AnalyticsView.tsx` (`frontend/prototype/src/components/AnalyticsView.tsx:38-51`). Fix: alle AnalyticsView-Anker korrigieren.
- WARNING: Die Story nennt “Chart-Serienfarben als Tokens?” als offene Frage (`story.md:72-73`), AG3-094 verlangt aber bereits “Chart-Farben kommen aus Design-Tokens (AG3-092)” (`stories/AG3-094.../story.md:75`). Fix: AG3-092 muss die Chart-Token-Familie liefern oder AG3-094 zurück auf “offen” ändern.

**Kontext-Sinnhaftigkeit: FAIL**
- ERROR: Nachbarstory-Konflikt/Owner-Duplikat ist real. AG3-092 sagt Endpoint out of scope zu AG3-084 (`story.md:39`), AG3-084 sagt kein Design-Token-Endpoint in AG3-084 und Routing zu AG3-092 (`stories/AG3-084.../story.md:13`). Fix: eine Story zum Owner machen und Index/status konsistent nachziehen.
- WARNING: `status.yaml` ist inkonsistent zu Abhängigkeiten: AG3-093 hängt direkt von AG3-092 ab (`stories/AG3-093.../status.yaml:8-10`, `_STORY_INDEX.md:118`), AG3-092 hat aber `unblocks: []` (`stories/AG3-092.../status.yaml:8-10`). Fix: `unblocks` mindestens `AG3-093` aufnehmen; AG3-094 ist indirekt über AG3-093 bzw. konsumiert Tokens.

**Must-Fix**
1. AG3-092/AG3-084 `get_design_tokens`-Owner-Konflikt auflösen.
2. FK-64-Abschnittsreferenzen korrigieren und Scope/AC auf reale §§ ausrichten.
3. Status-/Chart-Token-Abdeckung vervollständigen.
4. Falschen `AnalyticsView.tsx`-Pfad korrigieren.
5. AC-Negativtests für alle beanspruchten Conformance-Regeln ergänzen.
6. `status.yaml` `unblocks` konsistent setzen.
