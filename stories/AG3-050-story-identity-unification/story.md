# AG3-050: Story-Identity-Unifizierung — ein ID-Generator, Anzeige-Padding, Dependency-FK auf Stammdaten

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-040(a) ist Konsument (wartet auf diese Story)
**Quell-Konzepte (autoritativ):**
- `FK-02 §2.11.2/§2.11.3` (Story-Identitaet, Display-ID-Materialisierung, StoryDependency-Owner)
- `FK-17 §17.3.2/§17.3.3` (Story = Stammdaten; StoryContext = Laufzeit-Snapshot)
- `FK-18 §18.6a/§18.12.1` (relationales Modell, Identitaets-Kataloge)
- `FK-91 §91.1a` (kanonische Story-Erzeugung via Control-Plane-API)
- `formal.frontend-contracts.entities` (Wire: story_summary/story_detail)

---

## 1. Kontext (Stefan-Vorgabe 2026-06-01)

Bei der Feasibility zu AG3-040(a) wurde eine systemische Identitaets-Inkonsistenz
aufgedeckt (Codex-Review-(a)-r2 W-DISPLAYID): die fachliche Story existiert in zwei
Projektionen — `stories` (Stammdaten, Entitaet `Story`) und `story_contexts`
(Laufzeit, Entitaet `StoryContext`) — mit **divergenten Display-ID-Formaten**
(unpadded `AG3-1` via `StoryService.create_story` vs. padded `AG3-001` via
`lifecycle.create_story`) und potenziell getrennten Nummern-Allokatoren. Zudem
referenziert `story_dependencies` per Foreign Key die **Laufzeit**-Tabelle
`story_contexts` statt der statischen Story-Stammdaten. Das Konzept (FK-02 §2.11.2,
FK-18 §18.6a) kennt **eine** Identitaet `(project_key, story_number)` und **ein**
Format — die Divergenz ist akzidenteller Implementierungs-Drift ohne Nutzen und eine
latente Drift-/Korrektheits-Quelle. Diese Story raeumt das auf.

## 2. Scope

### 2.1 In Scope

#### A — StoryDependency-Kante auf STATISCHE Story-Info (nicht Runtime)
Die `StoryDependency`-Entitaet/-Tabelle bindet fachlich (UML-Assoziation) und
relational (Foreign Key) an die **statische** Story-Stammdaten-Entitaet
(`Story`/`stories`), explizit **nicht** an `StoryContext`/`story_contexts` —
unabhaengig davon, ob der Schluessel zufaellig derselbe ist. Abhaengigkeiten sind
Story-Inhalt (Vorbedingungen, bekannt zur Definitionszeit), kein Laufzeitzustand.
- Konzept: FK-02 §2.11.3 (und FK-18 §18.x) explizit klarstellen: FK von
  `story_dependencies.story_id`/`.depends_on_story_id` -> statische `stories`-Identitaet.
- Code/Schema: `story_dependencies`-FK (postgres + sqlite) von `story_contexts` auf
  die `stories`-Stammdaten-Identitaet umziehen (eindeutiger Story-Schluessel; exakte
  Spalte — story_display_id-unique bzw. story_uuid — im Design begruenden).
- Migration: idempotente Schema-Migration (SCHEMA_VERSION-Bump), Reihenfolge
  beachten (Dependencies vor/relativ zu story_contexts); im Dev-Stand i.d.R. keine
  Daten, aber fail-closed validieren.

#### B — Display-ID-Format ist reine Anzeige-Formatierung (min-width 3); Storage numerisch + numerische Sortierung
- Kanonische Identitaet/Storage: `story_number` (int), beliebig hoch; **keine**
  String-Breite als technischer Constraint.
- Anzeige (ueberall im Frontend/Wire-Display): min. dreistellig mit fuehrenden Nullen
  via **einer einzigen zentralen Formatter-Funktion** `format_story_display_id(prefix,
  story_number) -> f"{prefix}-{story_number:03d}"` (wird bei >=1000 automatisch
  laenger — min-width, nicht max-width).
- **Sortierung ausschliesslich numerisch ueber `story_number`** — nirgends
  lexikografisch ueber die Display-ID (sonst `AG3-1000 < AG3-999`). Bestehende
  Sortierstellen pruefen und auf story_number-Ordering ziehen.
- Konzept: FK-02 §2.11.2 praezisieren: Padding ist Praesentation; Sortierung numerisch.

#### C — Genau EIN BC und genau EINE Klasse/Instanz erzeugt Story-IDs/Nummern
- Story- und ID/story_number-Erzeugung liegt in **genau einem** BC
  (`story_context_manager` laut FK-91 §91.1a / FK-02 §2.11.2) und darin in **genau
  einer** kanonischen Klasse/Instanz (der `create_story_atomic`-Allokationspfad hinter
  `StoryService.create_story`). 
- Der duplizierte Pfad `story_context_manager.lifecycle.create_story` (padded,
  separater Allokator, kein produktiver Aufrufer ausser Tests) wird **entfernt** bzw.
  auf die kanonische Quelle konsolidiert. Kein zweiter `allocate_next_story_number`.
- Tests, die am Legacy-Pfad haengen, auf den kanonischen Pfad migrieren.
- Konzept: FK-02 §2.11.2 / FK-91 §91.1a klarstellen: eine kanonische Erzeugungs-/
  Allokationsquelle; Duplikat ist verboten (ZERO DEBT, Drift-Vermeidung).

### 2.2 Out of Scope
- Vollstaendige physische Zusammenlegung der Tabellen `stories`/`story_contexts`
  (die Trennung Stammdaten/Laufzeit bleibt; nur Identitaet + ID-Erzeugung + Dependency-
  Kante werden vereinheitlicht).
- AG3-040(a)-Counters selbst (bereits korrekt; profitiert nur von der einheitlichen Identitaet).

## 3. Betroffene Dateien (Richtwert, Worker verifiziert)

| Datei | Aenderung | Punkt |
|---|---|---|
| `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md` | Modifiziert | A/B/C Klarstellungen |
| `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` | Modifiziert | A (FK-Ziel), Identitaet |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | A (FK), B (Sortier-Index) |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | A (FK), Schema |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump + Migration |
| `src/agentkit/story_context_manager/<formatter>.py` | Neu/zentral | B (format_story_display_id) |
| `src/agentkit/story_context_manager/service.py` + `story_repository.py` | Modifiziert | B (Formatter-Einsatz), C (einzige Allokation) |
| `src/agentkit/story_context_manager/lifecycle.py` + `__init__.py` | Entfernt/konsolidiert | C |
| Tests (unit/contract/integration) | Neu/Migriert | A/B/C-Belege |

## 4. Akzeptanzkriterien

1. **A-Konzept:** FK-02 §2.11.3 (+FK-18) halten explizit fest, dass die
   StoryDependency-Kante auf die statische `stories`-Identitaet zeigt, nicht auf
   `story_contexts`.
2. **A-Schema:** `story_dependencies`-FKs (postgres + sqlite) referenzieren die
   statische `stories`-Identitaet; idempotente Migration mit SCHEMA_VERSION-Bump;
   FK-Verletzung (unbekannte Story) faellt fail-closed.
3. **B-Formatter:** Eine einzige `format_story_display_id`-Funktion erzeugt
   `{prefix}-{number:03d}`; story_number=42 -> `AG3-042`, =1000 -> `AG3-1000`.
4. **B-Sortierung:** Story-Listen werden numerisch nach `story_number` sortiert;
   ein Test mit Nummern u.a. >=1000 beweist korrekte Reihenfolge (kein
   lexikografischer Bug). Keine Sortierstelle nutzt die Display-ID lexikografisch.
5. **C-Single-Source:** Es existiert genau ein kanonischer Story-/ID-Erzeugungspfad
   (`StoryService.create_story` -> `create_story_atomic`); `lifecycle.create_story`
   und ein etwaiger zweiter `allocate_next_story_number` sind entfernt/konsolidiert.
   Ein Test/Audit belegt: kein produktiver Aufrufer des Legacy-Pfads.
6. **Kein Wire-Bruch:** REST-/Wire-Vertrag fuer story_display_id bleibt String;
   Contract-Tests gruen.
7. **Pflichtbefehle gruen:** pytest (unit+contract+integration, non-e2e), mypy strict,
   ruff clean, 4 CI-Gates OK (insb. architecture-conformance), Coverage >=85%.

## 5. Definition of Done
- AK 1-7 erfuellt; committed + gepusht; Jenkins SUCCESS + Sonar Quality Gate OK.
- Giftige Codex-Review bestanden (Ping-Pong bis keine offenen Issues).
- AG3-040(a) danach abnehmbar (Landmine entfernt).

## 6. Konzept-Referenzen
- FK-02 §2.11.2/§2.11.3 — Story-Identitaet, Display-ID, StoryDependency-Owner
- FK-17 §17.3.2/§17.3.3 — Story (Stammdaten) vs StoryContext (Laufzeit)
- FK-18 §18.6a/§18.12.1 — relationales Modell, Identitaets-Kataloge
- FK-91 §91.1a — kanonische Story-Erzeugung (Control-Plane)

## 7. Guardrail-Referenzen
- **FIX THE MODEL, NOT THE SYMPTOM:** eine Identitaet, eine ID-Quelle — kein Drift.
- **SINGLE SOURCE OF TRUTH:** ein BC, eine Klasse fuer ID-Erzeugung; Dependency-Kante
  an der statischen Wahrheit.
- **ZERO DEBT:** duplizierter (toter) Pfad wird entfernt, nicht nur deprecaten.
- **FAIL CLOSED:** FK-Constraint gegen statische Story; unbekannte Dependency-Story blockiert.
