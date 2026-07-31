# Konzept-Konsistenz-Bewertung AG3-176 (Quermechanik) — Opus

**Prüfgegenstand:** Die drei Konzeptänderungen der Story AG3-176 (Working Tree, uncommitted):
- `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md` (FK-50) — substanziell
- `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md` — Addendum
- `concept/_meta/reference-integrity-baseline.yaml` — mechanische Zeilennummern-Nachführung

**Methode:** Primärquellen selbst gelesen (concept_search-MCP nicht verfügbar — Weaviate down — daher grep/Read).
Code-Verifikation durch eigenen Sub-Agent (per-Claim, mit Datei:Zeile). Datum: 2026-07-28.

---

## (a) Gesamturteil

**Gemischt — kein reiner Nachzug.** Der Änderungssatz zerfällt sauber in zwei Teile:

1. **Kern (Optionalitätsentfernung): legitimer, vollständig ratifizierter Nachzug.**
   Die Entfernung von `branch_vectordb_enabled` und `SKIPPED`/`vectordb_disabled`, `features.vectordb: false`
   = harter Fehler, CP 10 unbedingt — das ist **exakt** die im Decision Record 2026-07-21 (Rand 1) verankerte
   Norm, deren Code-Entfernung dort ausdrücklich „einer späteren Story vorbehalten" war. AG3-176 **ist** diese
   Story; das Addendum (Diff, Zeilen 41–44) und die Matrixzeile 114 dokumentieren den Nachzug korrekt.
   Verankert zusätzlich in FK-13 §13.1 (Z. 42–49) und FK-03 §3.1 (Z. 233–238). Der Code implementiert es
   (models.py:100–106, orchestrator.py:113–117). **Keine neue Entscheidung.**

2. **CP 10a / CP 10b — Detailtext: enthält NEUE, PO-nicht-ratifizierte normative Aussagen.**
   Der FK-50-Diff schreibt substanziellen neuen Normtext zu CP 10a (typisiertes Receipt-Schema, story_sync→
   concept_sync-Reihenfolge, Empty-Corpus=Erfolg, transaktionales Receipt-Paar mit byte-exakter Restaurierung)
   und CP 10b (Post-Commit build→`sync --full`, argv-Härtung, Git-staged-fail-closed) in den Korpus. Dieser
   Text ist **nicht** vom Decision Record 2026-07-21 Rand 1 gedeckt — er stammt aus den **Story-eigenen
   Review-Befunden** (176-P0-1 … P2-1, siehe story.md Z. 42–116), nicht aus einer PO-Entscheidung. Er
   beschreibt zwar das tatsächlich implementierte Verhalten **korrekt** (Code-Agent: alle 6 Claims CONFIRMED),
   aber er verankert damit neue Norm im Konzeptkorpus, die der PO in dieser Form nie ratifiziert hat.

**Fazit:** Der *Kernauftrag der Änderung* ist ein sauberer Nachzug. Aber der Änderungssatz **schmuggelt an drei
Stellen neue normative Entscheidungen mit** (Detail siehe (c)). Ehrlich in beide Richtungen: nichts davon
widerspricht dem Code — im Gegenteil, FK-50 ist jetzt **genauer am Code** als mehrere Nachbardokumente. Aber
„genau am Code" ≠ „vom PO ratifiziert". Die neuen Aussagen sollten dem PO vorgelegt werden.

---

## (b) Befunde je Dimension

### Dimension 1 — Nachzug vs. neue Entscheidung

**Gedeckt (echter Nachzug):**
- Decision Record 2026-07-21 §1 (Z. 31–39): „`features.vectordb: false` ein harter Konfigurationsfehler, kein
  Abschaltpfad. Der Optionalitätszweig (`branch_vectordb_enabled`) ist als **deprecated** markiert; die
  Code-Entfernung ist einer späteren Story vorbehalten." → FK-50-Entfernung ist der bewusst vorbehaltene Schritt.
- FK-13 §13.1 (Z. 42): „VektorDB-Abgleich ist immer aktiv. Keine Feature-Flag-Stufung." — Kern-Norm.
- FK-21 §21 (Z. 306): identischer Wortlaut — bestätigt „FK-21 unberührt" aus dem Decision Record.

**NEU / über die verankerte Norm hinausgehend (im FK-50-Diff):**

1. **Platzierung + Reason-Code der Config-Grenze.** FK-50 Z. 475–476 / Z. 569 / Z. 937 behaupten neu:
   „`features.vectordb: false` ist bereits an der strikten Konfigurationsgrenze ein harter Fehler" mit
   `reason=configuration_invalid` und „Konfigurationsgrenze vor CP 1". Das Decision Record sagt nur „harter
   Konfigurationsfehler" — **ohne** Platzierung („vor CP 1") und **ohne** Reason-Code. `configuration_invalid`
   ist zwar anderweitig verankert, aber mit **anderer Bedeutung**: Decision Record 2026-07-28 (endpoint-
   consolidation) Z. 135 definiert es als „die **konsumierte Projektkonfiguration** fehlt oder ist [ungültig]".
   FK-50 dehnt diesen Code auf einen neuen Trigger (Feature-Flag `false`) aus. Vertretbar, aber eine
   Semantik-Erweiterung, die nirgends als solche entschieden wurde.

2. **CP 10a — story_sync VOR concept_sync (Reihenfolge).** Alttext führte nur `concept_sync(full_reindex=true)`
   aus. Neu (FK-50 Z. 615–616): „Führt `story_sync(full_reindex=true)` und danach `concept_sync(full_reindex=
   true)` aus." Neue geordnete Aussage. (Code bestätigt: mcp_server.py:373→380.)

3. **CP 10a — typisiertes Receipt-Schema.** FK-50 Z. 617–622 definiert neu ein Receipt „mit Projekt-ID,
   Tool/Quelltypen, Countern, Empty-Corpus-Kennzeichen sowie Start-/End-Revision und Status". Dieses konkrete
   Zähler-/Feldschema (discovered/unchanged/upserted/deleted/failed/empty_corpus) ist **in FK-13 nicht
   verankert** (grep über 13_*.md: keine Treffer für die Counter-Namen; `project_id` existiert nur als
   Objekt-/Tool-Property, nicht als Install-Receipt). Der fachliche Owner des Sync-Receipt-Kontrakts ist
   fachlich FK-13 (Retrieval-Engine) — hier wird er in FK-50 (Installer) niedergeschrieben (SSOT-Geruch, s. D4).

4. **CP 10a — Empty-Corpus=Erfolg mit Null-Countern** (FK-50 Z. 619) und **Teilfehler publiziert keine
   Freshness** (Z. 620). Erstes ist neu; Zweites aus FK-13-Freshness-Semantik ableitbar.

5. **CP 10a — transaktionales Receipt-Paar + byte-exakte Restaurierung** (FK-50 Z. 620–622): „Beide lokalen
   Receipts werden als transaktionales Paar geschrieben; bei einem Fehler des zweiten Writes werden die exakten
   vorherigen Bytes beider Dateien restauriert." **Nirgends in FK-13/FK-30 verankert** (grep: 0 Treffer außer
   FK-50 selbst). Genuin neue Design-Norm.

6. **CP 10b — Post-Commit build→`sync --full`** (FK-50 Z. 636–640). Build-vor-Sync ist in FK-30 §30.5.4a
   verankert — **aber** §30.5.4a beschreibt den Sync als **inkrementell** („~2–5s bei inkrementellem Sync",
   Z. 666–667), FK-50 sagt `sync --full`. Divergenz (s. D2). Zusätzlich neu: „Pfade werden als argv übergeben,
   nicht in Shelltext interpoliert" (Z. 640) und „Kann Git die staged Pfade nicht ermitteln, endet der Hook
   ungleich null" (Z. 638–639) — Security-/fail-closed-Details, in FK-30 nicht vorhanden.

Alle Punkte 2–6 entstammen laut story.md den **Review-Achsen 176-P0-1/P0-2/P0-3/P1-1/P2-1** (story.md Z. 42–105),
nicht dem PO-Decision-Record. Das Story-Addendum im Decision Record (Z. 41–44) nennt sie **nicht** — es deckt
ausschließlich die Branch-/SKIPPED-Entfernung.

### Dimension 2 — Querkonsistenz mit anderen Konzepten

**Live-Widerspruch (aktiv, nicht mit-nachgezogen):**
- `concept/_meta/decisions/2026-07-20-mcp-conformance-registration-gate.md:76–79` (Frontmatter `status: active`):
  „`SKIPPED` bleibt dem *bewusst-abwesenden* Fall vorbehalten (`features.vectordb` und `features.are` beide
  false → `reason=vectordb_disabled`)." Das ist jetzt **direkt kontradiktorisch** zu FK-50 (SKIPPED/
  vectordb_disabled entfernt). Ein aktives, cross-cutting Decision Record trägt eine Norm, die AG3-176
  aufgehoben hat. Nicht aktualisiert. **Muss nachgezogen oder mit Supersede-Vermerk versehen werden.**

**Doc-Doc-Inkonsistenz (Config-Modell-Autorität hinkt nach):**
- `concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md` §3.1 (Z. 63) zeigt
  `vectordb: bool = False` und §3.2.1 (Z. 462–476) den `@model_validator` — **ohne** vectordb-Ablehnung
  (nur are/e2e/multi_llm werden geprüft). Der Code (`models.py:100–106`) hat inzwischen einen
  `@field_validator("vectordb")`, der `false` ablehnt. FK-03 ist die Config-Modell-**Autorität** und zeigt den
  „false = harter Fehler"-Validator **nicht**. Die Prosa Z. 233–238 sagt zwar „deprecated / harter
  Konfigurationsfehler", der gezeigte Schema-Snippet widerspricht dem aber. FK-50 ist hier genauer als FK-03.

- `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md:26`: „| VektorDB | `false` |
  `features.vectordb` | … |" — listet den **Default `false`**. Spannung zu „false = harter Fehler".
  (Vorbestehend; nicht durch AG3-176 erzeugt, aber jetzt schärfer sichtbar.)

- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md:474–479`: `weaviate-client` und
  `mcp[cli]` als **„Optionale Dependencies"** unter „Feature-Flag `features.vectordb: true`". Widerspricht
  „Pflichtinfrastruktur". Vorbestehend (schon vor 2026-07-21 veraltet), aber jetzt klarer Widerspruch zu FK-50.

- `concept/technical-design/30_hook_adapter_guard_enforcement.md` §30.5.4a: (a) Z. 669–670 sagt der Post-Commit-
  Hook werde „über Checkpoint **CP 9d**" registriert — FK-50 verortet den Concept-Hook-Dispatch nun bei
  **CP 10b**. Checkpoint-Nummern-Drift. (b) Z. 646/657/666–667 beschreiben den Post-Commit-Sync **inkrementell**
  (`concept sync`, „inkrementellem Sync"), FK-50 sagt `sync --full`. Beide Drifts vorbestehend im Ansatz, durch
  AG3-176 aber verschärft (FK-50 legt sich jetzt fest).

**Sauber / konsistent (ehrlich in die Gegenrichtung):**
- **ARE-Optionalität sauber unberührt:** FK-03 Z. 570–571 („`features.are: false` — ARE entfällt komplett, kein
  Fehler"), FK-03 §3.2.1 Z. 472–475 (bindet `are.mcp_server` an `features.are`), FK-50-Diff behält
  „ARE-MCP-Server nur bei `features.are: true` (FK-03 §3.1 …)". Code bestätigt (cp10_mcp_registration.py:199–212).
  Kein Kollateralschaden an der ARE-Optionalität. **Sehr gut abgegrenzt.**
- FK-13 §13.1/§13.8 und FK-21 §21.4.3/§21 sind mit FK-50 konsistent (beide: Pflicht, fail-closed).

### Dimension 3 — Konsistenz mit dem Code

**Vollständig konsistent — alle 6 FK-50-Claims durch den Code CONFIRMED** (Sub-Agent, Datei:Zeile):
- `features.vectordb: false` → harter Fehler **vor CP 1**: `models.py:100–106` (`@field_validator`) +
  `orchestrator.py:113–117` (`_candidate_config`, vor `engine.run` in Z. 226); Reason `configuration_invalid`
  (config_boundary.py:56–60). Reihenfolge bewiesen (flow.py:25–27 Docstring).
- Kein `branch_vectordb_enabled`/`vectordb_disabled`/SKIPPED-Pfad im Produktionscode mehr (flow.py:76–85,
  registry.py:86–95; `vectordb_enabled` existiert nur noch als „always true"-Kompatibilitäts-Bool).
- CP 10 registriert Story-KB **unbedingt**, ARE nur bei `features.are` (cp10_mcp_registration.py:199–212).
- CP 10a: Receipt-Typ **`InitialSyncReceipt`** (cp10a_initial_sync.py:43, strict/frozen/extra=forbid) mit exakt
  den Feldern; story_sync→concept_sync (mcp_server.py:373→380); Empty=Erfolg (Z. 153/156); transaktionales
  Paar + byte-Restore (`_publish_pair` Z. 173–202, `_restore` Z. 164–170). **Doktext deckungsgleich.**
- CP 10b: Secret-Detection immer (hook_dispatch.py:115–120, vor Concept-Check); staged-fail → exit≠0
  (Z. 75–77/105); Post-Commit build→`sync --full` (Z. 51, verify: git_hook_dispatch.py:539–545); argv/kein
  `shell=True` (Z. 85–91).

**Einzige Ungenauigkeit (kein Widerspruch):** FK-50 schreibt `agentkit concept validate/build/sync`, der Code
ruft `python -m agentkit.backend.vectordb.cli … validate/build/sync --full` (hook_dispatch.py:15–51). Gleiche
Subkommandos/Reihenfolge, aber **kein** `agentkit concept`-Binary. Doktext sollte auf die reale Invocation
angeglichen werden (Kosmetik, ARCH-55-nah).

### Dimension 4 — Konsistenz mit Guardrails

**Kein Regelverstoß; die Änderung verstärkt mehrere Guardrails:**
- **FAIL-CLOSED / NO ERROR BYPASSING:** Entfernung des `SKIPPED`/`vectordb_disabled`-Weichpfads und harte
  Config-Grenze sind lupenreiner FAIL-CLOSED-Ausbau. `guardrails/` enthält keine vectordb-spezifische Regel
  (grep: 0 relevante Treffer) → kein Konflikt.
- **FIX THE MODEL, NOT THE SYMPTOM:** Optionalitätszweig statt Workaround entfernt — im Sinne des Zielbilds.

**Ein Guardrail-Geruch (nicht -Verstoß) — SSOT / „keine zweite operative Wahrheit":** Der CP-10a-Sync-Receipt-
Kontrakt (Feldschema + transaktionales Paar + byte-Restore) ist jetzt als **Norm in FK-50** niedergeschrieben,
aber **nicht** in FK-13 (dem fachlichen Owner der Retrieval-/Sync-Engine) verankert. CLAUDE.md „SINGLE SOURCE
OF TRUTH / FIX THE MODEL" verlangt genau einen fachlichen Owner. Empfehlung: den Receipt-Kontrakt in FK-13
verankern und FK-50 darauf verweisen lassen, statt ihn im Installer-Dokument zu erfinden.

---

## (c) Was der PO persönlich ratifizieren/entscheiden sollte

1. **Reuse/Erweiterung von `configuration_invalid`** für den Trigger „`features.vectordb: false`" **und** die
   Platzierung „harter Fehler an der strikten Konfigurationsgrenze **vor CP 1**". Das Decision Record sagte nur
   „harter Konfigurationsfehler" ohne Reason-Code und ohne Platzierung; `configuration_invalid` ist bislang mit
   der Bedeutung „konsumierte Projektkonfig fehlt/ungültig" (Decision 2026-07-28) belegt.

2. **Der CP-10a-Receipt-Kontrakt als Norm** — konkretes Feldschema, story_sync→concept_sync-Reihenfolge,
   Empty-Corpus=Erfolg, **transaktionales Receipt-Paar mit byte-exakter Restaurierung**. Genuin neue Design-
   Entscheidungen, nur über Story-Reviews (P1-1) legitimiert, nicht über ein PO-Decision-Record. Zusätzlich die
   **Owner-/SSOT-Frage:** gehört das nach FK-13 (Engine) statt FK-50 (Installer)?

3. **CP-10b Post-Commit `sync --full`** — die Festlegung auf **Full**-Sync widerspricht der inkrementellen
   Beschreibung in FK-30 §30.5.4a. Der PO sollte entscheiden, welcher der beiden Texte gilt, und den anderen
   nachziehen.

(Zur Klarstellung: Die **Branch-/SKIPPED-Entfernung + `false`=harter Fehler + CP 10 unbedingt** braucht **keine**
neue Ratifizierung — sie ist durch Rand 1 gedeckt.)

---

## (d) Gefundene Querinkonsistenzen (kompakt)

| # | Ort | Art | Zustand | Dringlichkeit |
|---|-----|-----|---------|---------------|
| 1 | `_meta/decisions/2026-07-20-mcp-conformance-registration-gate.md:76–79` | anderes **aktives** Decision Record hält `SKIPPED`/`vectordb_disabled` (both-false) für gültig | **Live-Widerspruch** zu FK-50 | hoch — mit-nachziehen oder supersede |
| 2 | FK-03 §3.1 Z. 63 + §3.2.1 Z. 462–476 | Config-Autorität zeigt `vectordb: bool = False` **ohne** Ablehn-Validator | Doc hinkt hinter Code (models.py:100–106) + FK-50 | hoch — FK-03 zeigt nicht die geltende Norm |
| 3 | FK-30 §30.5.4a Z. 646/657/666–667 vs. Z. 669–670 | Post-Commit: **inkrementell** + Registrierung via **CP 9d** | widerspricht FK-50 (`sync --full`, CP 10b) | mittel |
| 4 | §93.1 Z. 26 | VektorDB-Default `false` | Spannung zu „false=harter Fehler" | mittel (vorbestehend) |
| 5 | FK-01 Z. 474–479 | weaviate/mcp als **optionale** Deps unter `features.vectordb: true` | widerspricht „Pflichtinfrastruktur" | mittel (vorbestehend) |
| 6 | FK-50 Z. 636–640 | `agentkit concept …` als Invocation | Code nutzt `python -m …vectordb.cli` | niedrig (Kosmetik) |
| — | CP-10a-Receipt-Kontrakt in FK-50 statt FK-13 | SSOT/Owner | neue Norm im falschen Owner-Dokument | mittel (D4) |

**Doc-Code-Abweichungen:** außer #6 (Invocation-Naming) **keine** — FK-50 beschreibt den Code korrekt. Die
Abweichungen liegen umgekehrt: **Nachbardokumente (FK-01/03/30/93 + Decision 2026-07-20) hinken FK-50/Code
hinterher.** Das ist die eigentliche Quer-Baustelle dieser Story.

**Guardrail-Konflikte:** keine harten Verstöße; ein SSOT-/Owner-Geruch (Receipt-Kontrakt, s. D4/c-2).
