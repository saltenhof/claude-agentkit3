# Neuschnitt des Suchvorhabens — AG3-161 bis AG3-171

Dieses Dokument belegt den Neuschnitt des VektorDB-/MCP-Vorhabens nach
`review-2-codex.md`, die Nachschaerfung nach `review-3-codex.md` und die
chirurgische Nachbesserung nach `review-4-codex.md` (G1–G5). Es ist
**kein Story-Paket** und wird nicht abgearbeitet.

Es enthaelt:

1. die **Story-Uebersicht** (Inhalt, Groesse, Kanten),
2. die **Herkunftsmatrix** — fuer jeden Scope-Punkt und jedes
   Akzeptanzkriterium der urspruenglichen vier Stories die neue Heimat;
   sie ist der Beleg gegen `review-2-codex.md` P1-6 („beim Split
   verloren"),
3. die **Befund-Abdeckung** aller vier Codex-Reviews,
4. die **vorentschiedenen Punkte** (E1–E11 aus Runde 2, F1–F10 aus
   Runde 3, G1–G5 aus Runde 4), die im Briefing umgesetzt und nicht neu
   aufzurollen sind.

**Aenderung gegenueber der Vorfassung (Runde 3):** Aus zehn Stories
werden **elf**. Die **Aktivierung** der VektorDB-Pflichtinfrastruktur ist
aus AG3-161 herausgeloest und bildet als **AG3-171** eine eigene atomare
Schnittkante (F1). Damit existiert kein landbarer Stand mehr, in dem eine
Installation einen Phantomeintrag schreibt oder flaechendeckend
ausfaellt.

**Aenderung gegenueber Runde 3:** Der Elfer-Schnitt bleibt unveraendert;
`review-4-codex.md` fuehrt zu fuenf gezielten Briefingkorrekturen
(G1–G5, §4.3) ohne neuen Grobschnitt. Wo eine G-Entscheidung eine E-/
F-Entscheidung praezisiert, gilt die G-Fassung.

**Hinweis zu den Review-Dateien:** `review-codex.md`,
`review-2-codex.md`, `review-3-codex.md` und `review-4-codex.md` bleiben
unveraendert in diesem Ordner. Der
Ordnername `AG3-161-vectordb-mcp-server-bundle` wurde bewusst **nicht**
umbenannt, damit die aus anderen Stories referenzierten Review-Pfade
gueltig bleiben; die Story selbst heisst inhaltlich
`vectordb-foundation-and-packaging` (siehe `status.yaml`
`story_title_short`).

## 1. Story-Uebersicht

| ID | Kurzname | Inhalt (Kern) | Groesse | Status | depends_on |
|---|---|---|---|---|---|
| AG3-161 | `vectordb-foundation-and-packaging` | **Vertragsvorbereitung** der Feature-Flag-Norm (Decision Record, Aktivierung erst in AG3-171), minimale projektlokale Bindung, Packaging (`mcp` + `weaviate-client` + gepinnte `tokenizers` nach `[project.dependencies]`, kein Extra) inkl. **Tokenizer-Package-Asset** mit Digest/Revision/Lizenz (G4), Endpunkt-Preflight fail-closed, Schema-Owner **nur normativ** (kein `schema.py`) | M | blocked | AG3-164 (G2) |
| AG3-162 | `vectordb-ingest-core-ssot` | Generischer Discovery-/Frontmatter-/Chunking-/Hashing-/Exclude-Kern unter `src/agentkit/` als SSOT; Profile `fk13_concept`, `fk13_story` (**Token**, Limit 1000, modellgebundener Tokenizer aus dem Package-Asset, fail-closed offline) und `ak3_tool` (12.000 Zeichen); entschiedene `E-CHUNK-001`-Overflow-Policy; `tools/concept_ingester` wird duenner Adapter; Drift-Test | M | blocked | AG3-161 (Sequenz **+ Tokenizer-Lieferung**, G4) |
| AG3-163 | `vectordb-schema-and-story-ingest` | Vollstaendiges `StoryContext`-Schema (Story- **und** Concept-Properties in einem Wurf, `schema.py` entsteht hier), Story-/Research-Ingest produktiv, **positive producergebundene Research-Erkennung** (`research/`-Pfad) mit Negativfaellen, Source-Type/Producer-Matrix + FK-13-Driftbereinigung | L | blocked | AG3-162 |
| AG3-164 | `are-mcp-phantom-registration` | Generischer MCP-Conformance-Check (Start+Timeout, `initialize`, `tools/list`) als Registrierungsvorbedingung; ARE-Phantomregistrierung schlaegt ehrlich fehl | M | **in_progress** | — |
| AG3-165 | `concept-corpus-validate-and-build` | `concept_validate` mit vollstaendigem Finding-/Exit-Code-Katalog (§13.9.7, `E-CHUNK-001` bleibt blockierend), `INDEX.yaml` + `concept_graph.json` + `corpus_revision`, drei Schutzringe installiert **und** feuernd (CP10b, Pre-/Post-Commit) | L | blocked | AG3-162 |
| AG3-166 | `concept-sync-resolver-and-oracle` | `concept_sync` (Validate als harte Vorbedingung, Metadaten), **vorentschiedener Shadow-Replace-Vertrag** (Generationen, CAS-Anker, GC, Tombstone) mit Leser-/Crash-/GC-Nachweis gegen echte Weaviate-Infrastruktur, ConceptGraphResolver, Freshness-Indikator, **Orakel als reviewtes Eingangsartefakt** (Digest + unabhaengige Freigabe) | L | blocked | AG3-163, AG3-165 |
| AG3-167 | `vectordb-mcp-tools-and-retrieval-quality` | MCP-Server + fuenf Tools, drei wirksame Suchmodi, Ergebnis-/Fehler-Envelopes, fail-closed, **realer Retrieval-Nachweis gegen echte Weaviate-Instanz**, Qualitaetsgate gegen das Orakel | L | blocked | AG3-166 |
| AG3-168 | `dual-harness-mcp-registration` | Projektlokale Registrierung in beiden Harnessen, ein Codex-TOML-Writer mit semantischem Merge, **vollstaendige Codex-Laufzeitbindung** (`env` mit `PROJECT_ID` + Endpunkt, `required = true`, ein Uebergabemechanismus), FK-76-Vertrag, Trust-Blocker, Registrierung erst nach Conformance-Check | M | blocked | AG3-164, AG3-167 |
| AG3-169 | `initial-index-and-sync-producers` | CP10a fuehrt `story_sync`+`concept_sync` mit `full_reindex` wirklich aus (Receipt, harter Fehlerpfad); Closure-Trigger, Post-Commit-Sync-Trigger, Freshness-Aktualisierung | M | blocked | AG3-163, AG3-165, AG3-166, AG3-168 |
| AG3-170 | `story-knowledge-skill-delivery` | Stiller Grep-Fallback entfaellt, Freshness-**Gate** und `concepts_dir` konsumiert, vollstaendiger FK-43-Bundle-Lifecycle, **komponierte Endabnahme** Install → Harness-Discovery → Retrieval je Harness plus Fremdprojekt-Negativfall | M | blocked | AG3-166, AG3-167, AG3-168, AG3-169, AG3-171 |
| AG3-171 | `vectordb-mandatory-activation` | **Atomare Aktivierung**: `branch_vectordb_enabled` entfaellt, CP10/CP10a unbedingt, `features.vectordb: false` wird harter Fehler, FK-50-/FK-03-/FK-21-Nachzuege, Negativ-/Positiv-E2E **mit konsumiertem CP10a-Erstindex aus AG3-169** (G1), Clean-Venv-Protokollnachweis | M | blocked | AG3-164, AG3-167, AG3-168, AG3-169 |

**Sofort startbar: keine Story dieses Pakets.** Nach der
Sicherheitskante G2 (`AG3-161 depends_on AG3-164`) ist **AG3-164** die
einzige laufende und zugleich die einzige nicht blockierte Story des
Pakets; sie ist bereits `in_progress`. Alle uebrigen zehn Stories stehen
auf `blocked`. Das ist ausdruecklich beabsichtigt und erfuellt
`stories/README.md` §3: Es bleibt **keine** weitere `ready`-Story ohne
offene Dependencies uebrig, die faelschlich als parallel startbar
erscheinen koennte. Erst wenn AG3-164 `completed` ist, wechselt
**AG3-161** auf `ready` — und dann als einzige Story dieses Pakets, weil
AG3-162 auf AG3-161 wartet. (Stories anderer Straenge — z. B.
AG3-131/132/133/134 — sind davon unberuehrt; die
Ein-Story-gleichzeitig-Regel gilt fuer die Ausfuehrung, nicht fuer den
Backlog-Zustand.)

**Gueltige Linearisierung (nach G1/G2):**
AG3-164 → AG3-161 → AG3-162 → {AG3-163, AG3-165} → AG3-166 → AG3-167 →
AG3-168 → **AG3-169 → AG3-171** → AG3-170.
AG3-163 und AG3-165 sind parallelisierbar (beide nur auf AG3-162).
AG3-169 und AG3-171 sind **nicht** mehr parallelisierbar: die
Aktivierung konsumiert den produktiven CP10a-Erstindex (G1). AG3-164 ist
nicht mehr beliebig einschiebbar, sondern steht wegen G2 am Anfang.

**Kanten sind direkt, nicht transitiv** (E11, nach `review-3-codex.md`
P2-1 vervollstaendigt):

| Story | direkte Kanten |
|---|---|
| AG3-161 | ← AG3-164 (Beseitigung des vorbestehenden Phantompfads; Voraussetzung des absoluten Null-Phantom-AC — **G2**) |
| AG3-162 | ← AG3-161 (Modul-/Vertragsschnitt **und** Tokenizer-Dependency/-Asset — **G4**) |
| AG3-166 | ← AG3-163 (Collection/Schreibpfad), AG3-165 (Validator/Graph) |
| AG3-168 | ← AG3-164 (Conformance-Check), AG3-167 (Server) |
| AG3-169 | ← AG3-163 (`story_sync`), AG3-165 (Validator/Build/Hook), AG3-166 (`concept_sync`/Freshness), AG3-168 (Registrierung) |
| AG3-170 | ← AG3-166 (Freshness), AG3-167 (Tools), AG3-168 (Harness-Bindung), AG3-169 (Producer), AG3-171 (aktivierter Installationspfad) |
| AG3-171 | ← AG3-164 (Check), AG3-167 (Server), AG3-168 (beide Registrierungen), **AG3-169 (produktiver CP10a-Erstindex — G1)** |

**Sicherheitskritische Aktivierungskante:** AG3-171 haengt an allen
**vier** Faehigkeiten, die die Aktivierung erst korrekt machen. Die
vierte Kante (AG3-169) ist mit **G1** ergaenzt: Ohne sie haette AG3-171
CP10a unbedingt geschaltet, waehrend CP10a noch ein Erfolgs-Placeholder
ist — Installation gruen, Index leer.

**Korrigierte Begruendung zur Kante AG3-161 ← AG3-164 (G2).** Dieses
Dokument hat frueher behauptet, eine Kante von AG3-161 auf AG3-164 sei
die falsche Loesung, weil sie einen flaechendeckenden
Installationsausfall erzeuge. **Diese Begruendung galt fuer die alte
AG3-161 mit Pflichtaktivierung.** Nach der Auslagerung der Aktivierung
nach AG3-171 (F1) aendert AG3-161 kein Flag-Verhalten mehr; die Kante
kann folglich keinen Ausfall erzeugen. Sie ist im Gegenteil
**notwendig**, weil AG3-161 AC 2 absolut zusagt, dass es nach der Story
keinen Installationslauf mit Phantomeintrag gibt — und der vorbestehende
Phantompfad bei `features.vectordb: true` erst durch AG3-164 beseitigt
wird. Das absolute Null-Phantom-AC bleibt deshalb unveraendert bestehen;
abgeschwaecht wird nichts.

## 2. Herkunftsmatrix

Lesart: „wo lebt dieser Inhalt jetzt". Kein Punkt ist entfallen; wo ein
Punkt durch eine PO-Entscheidung veraendert wurde, steht die Aenderung
dabei.

**Korrektur nach `review-3-codex.md` „Verlustpruefung".** Codex hat
festgestellt, dass die Matrix zwar keine Zeile verliert, an **vier**
Stellen aber den **materiellen Abschluss ueberschaetzt** hat: Die
genannte Heimat existierte, der Vertrag darin war jedoch unvollstaendig.
Die betroffenen Zeilen sind unten korrigiert und tragen jetzt den
tatsaechlichen Vertragsstand:

| Ueberschaetzte Stelle | Vorher behauptet | Jetzt tatsaechlich |
|---|---|---|
| Shadow-Replace | „Crash-Konsistenz als implementierbarer Vertrag" | Algorithmus **vorentschieden** (F3): Generationen, Staging+Digest/Sollmenge, CAS-Anker, gebundene Lesergeneration, GC mit Retry, Tombstone; Nachweis gegen echte Infrastruktur; Konfliktklausel |
| Oracle-Fixierung | „versioniertes Orakel mit Reviewpflicht" | Orakel ist **reviewtes Eingangsartefakt** (F5); Owner ist der **PO oder ein vom PO benannter, nicht implementierender fachlicher Reviewer/Orchestrator** (**G3** — der frueher benannte `Council-Orchestrator` ist nach `CLAUDE.md` unzulaessig); Artefakt liegt **versioniert vor** dem `in_progress`-Wechsel; Approval bindet Digest, Reviewer-Identitaet und einen **bereits existierenden** Commit-/Artefakt-Ref; AG3-166 materialisiert/validiert, waehlt nicht |
| Codex-Laufzeitbindung | „Codex-Eintrag mit `command`, `args`, `cwd`" | **vollstaendiger** Vertrag (F4): `env` mit `PROJECT_ID` und allen Endpunktwerten, `required = true`, EIN Uebergabemechanismus fuer beide Harnesse, Nachweise ueber die reale Codex-CLI |
| Atomarer Aktivierungszeitpunkt | „bewusster Uebergangszustand in AG3-161" | Uebergangszustand **entfaellt**; Aktivierung ist eigene Story **AG3-171** (F1) mit Negativ-/Positiv-E2E |

**Korrektur nach `review-4-codex.md` „Verlustpruefung".** Codex hat drei
weitere Stellen benannt, an denen diese Matrix mehr behauptet hat, als
belegt war. Alle drei sind mit G1/G2/G4 sachlich behoben; die
Matrix-Eintraege sind entsprechend korrigiert:

| Ueberschaetzte Stelle | Vorher behauptet | Jetzt tatsaechlich |
|---|---|---|
| Atomizitaet der Aktivierung | „AG3-171 ist die **atomare** Aktivierung" | Atomar **erst mit G1**: AG3-169 war keine Vorbedingung, also durfte AG3-171 CP10a unbedingt schalten, waehrend CP10a noch Erfolgs-Placeholder war. Jetzt `depends_on` inkl. **AG3-169**; AC 3 konsumiert beide Full-Sync-Receipts plus je eine Story- und Concept-Suche mit Treffern ohne manuellen Sync |
| Startbarkeit von AG3-161 | „sofort und eigenstaendig startbar (`depends_on: []`)" | **Nicht** sofort startbar: Das absolute Null-Phantom-AC setzt den AG3-164-Fix voraus. Jetzt `depends_on: [AG3-164]`, `status: blocked` (**G2**); das AC bleibt absolut und wird nicht abgeschwaecht |
| Modellgebundener Tokenizer | „vollstaendig entschieden (F7)" | Entschieden war nur der **Contract** (Einheit, Grenzregel, Overflow). Der **Lieferweg** fehlte. Jetzt mit **G4** entschieden: versioniertes Package-Asset mit Digest, Revision und Lizenz; `tokenizers==0.21.0` in `[project.dependencies]` (AG3-161); fail-closed offline; Clean-Venv-Test ohne Netz und ohne Model-Cache |

### 2.1 Alt-AG3-161 (`vectordb-mcp-server-bundle`)

| Alt | Inhalt | Neue Heimat | Anmerkung |
|---|---|---|---|
| Scope 1 | Decision Record + FK-13-Praezisierung Feature-Flag | **AG3-161** Scope 1 (Decision Record) + **AG3-171** Scope 1–3 (Wirksamkeit) | **Richtung gedreht (E1):** FK-13 wird **nicht** qualifiziert; `features.vectordb` wird deprecated, der optionale CP10-Ast entfaellt. **Landepunkt korrigiert (F1):** AG3-161 liefert nur den Vertrag; Code und die FK-50-/FK-03-/FK-21-Nachzuege landen atomar in AG3-171. |
| Scope 2 | `ProjectBinding`-Vertrag (stark) | **AG3-161** Scope 2 | **Reduziert (E3):** nur `project_root`, Containment, `cwd`, `project_id` nach bestehendem Vertrag, Endpunkt. Kollisionsfreie Neuidentitaet und Registry-CAS **verworfen**. |
| Scope 3 | Packaging (`mcp`, `weaviate-client`) | **AG3-161** Scope 3 + **AG3-171** Scope 5 | **Praezisiert (F6):** beide nach `[project.dependencies]`, kein neues Extra; Clean-Venv nach produktivem Installationsweg in AG3-161, der Protokollnachweis bis `initialize`/`tools/list` ueber das registrierte Kommando in AG3-171 (dort existiert der Server). |
| Scope 4 | Preflight fail-closed | **AG3-161** Scope 4 | unveraendert |
| Scope 5 | `StoryContext`-Schemaerzeugung als benannter Owner | **AG3-161** Scope 5 (**nur normativ**) + **AG3-163** Scope 1 (Datei + Erzeugung) | **E2 + F2:** Owner/Aufrufpunkt/Idempotenzvertrag stehen ausschliesslich im Decision Record; **kein `schema.py`** in AG3-161. Die Datei entsteht einmal, vollstaendig, in AG3-163. |
| AC 1 | Flag-Widerspruch aufgeloest, Decision Record | **AG3-161** AC 1 (Vertrag) + **AG3-171** AC 1/2/7 (Wirksamkeit) | Richtung nach E1, Landepunkt nach F1 |
| AC 2 | `ProjectBinding` typisiert, kollisionsfreie Identitaet | **AG3-161** AC 3 | Identitaetsherleitung entfaellt (E3); stattdessen Beleg, dass **keine** neue Identitaet eingefuehrt wurde |
| AC 3 | Negativtests (gleicher Praefix, kopierte Config, falsches `cwd`, Symlink/Traversal) | **AG3-161** AC 4 | „zwei Roots mit gleichem Praefix" und „kopierte Config" entfallen mit E3; Containment-/Traversal-/Fremdpfad-Negativtests bleiben |
| AC 4 | Dependencies + Clean-Venv | **AG3-161** AC 5 + **AG3-171** AC 6 | F6: eindeutige Heimat `[project.dependencies]`, Extra-Verbot als Test; Protokollnachweis in AG3-171 |
| AC 5 | Installationslauf scheitert bei unerreichbarem Endpunkt | **AG3-161** AC 6 | unveraendert; der Installationslauf-**Erfolgsfall** (Erstindizierung) wird in **AG3-169** abgenommen |
| AC 6 | Collection idempotent angelegt | **AG3-161** AC 7 (normative Owner-Festlegung, Nachweis „keine Datei") + **AG3-163** AC 1/2 (Erzeugung, Idempotenz) | E2 + F2 |
| AC 7 | Installer installiert/startet keine DB | **AG3-161** AC 8 | unveraendert |
| Out of Scope | Weaviate ausliefern/starten | **AG3-161** Out of Scope, in allen Folgestories wiederholt | PO-Vorgabe bleibt |

### 2.2 Alt-AG3-162 (`vectordb-schema-and-ingest`)

| Alt | Inhalt | Neue Heimat | Anmerkung |
|---|---|---|---|
| Scope 1 | `StoryContext`-Schema vollstaendig (§13.3.1 + §13.9.3) | **AG3-163** Scope 1 | jetzt inkl. Vectorizer und Erzeugung — ein Wurf (E2) |
| Scope 2 | Story-Ingest reparieren (Felder, deterministische ID, Hashes, Projektfilter, Re-Sync, `full_reindex`) | **AG3-163** Scope 2 | unveraendert; ergaenzt um `research` |
| Scope 3 (a) | `concept_validate` als produktiver Validator + harte Vorbedingung | **AG3-165** Scope 1 (Validator) + **AG3-166** Scope 1 (Vorbedingung) | Katalog jetzt vollstaendig erzwungen |
| Scope 3 (b) | `INDEX.yaml`, `concept_graph.json`, `corpus_revision` | **AG3-165** Scope 2 | — |
| Scope 3 (c) | `ConceptGraphResolver` | **AG3-166** Scope 3 | — |
| Scope 3 (d) | Shadow-Replace atomar | **AG3-166** Scope 2 | **F3: Algorithmus vorentschieden** — immutable `generation_id`, vollstaendiges Staging mit Digest-/Sollmengenvalidierung, ein CAS-faehiger Active-Generation-Anker je (`project_id`, `source_file`), am Anfragebeginn gebundene Lesergeneration, GC mit Retry, Tombstone; Konfliktklausel statt Code-Simulation |
| Scope 3 (e) | Pre-/Post-Commit-Trigger, Freshness-Gate | **AG3-165** Scope 3 (Ringe installiert+feuernd) + **AG3-169** Scope 5/6 (Sync-Trigger, Freshness-Aktualisierung) + **AG3-170** Scope 2 (Gate-Konsum) | E4 |
| Scope 3 (f) | konzeptspezifisches Chunking, Frontmatter, `.conceptignore`, Archiv | **AG3-162** Scope 1/3 (Kern+Profile) + **AG3-165** Scope 4 (Validierung/Build) + **AG3-166** Scope 1 (Metadaten/Archiv) | — |
| Scope 4 | konfigurierter `concepts_dir` massgeblich | **AG3-162** Scope 6; Konsum in **AG3-165**, **AG3-166**, **AG3-170** | — |
| Scope 5 | Discovery-/Chunking-Kern als SSOT (Entscheidung offen) | **AG3-162** vollstaendig | **E9: Entscheidung getroffen** — gemeinsamer Kern unter `src/agentkit/`, `tools/concept_ingester` wird Adapter, Profile bleiben getrennt |
| Scope 6 | Retrieval-Goldkorpus | **AG3-166** Scope 5 | **E6 + F5 + G3:** versioniertes Orakel mit fixem `k`, Recall, Modellbindung; die Werte kommen als **reviewtes Eingangsartefakt** (Owner: **PO oder ein vom PO benannter, nicht implementierender fachlicher Reviewer/Orchestrator**, versioniert **vor** dem `in_progress`-Wechsel), AG3-166 materialisiert und validiert sie und bindet Digest, Reviewer-Identitaet und einen bereits existierenden Commit-/Artefakt-Ref |
| AC 1 | Schema traegt alle Properties, Contract-Test | **AG3-163** AC 1 | — |
| AC 2 | Story mit vollstaendigen Feldern auffindbar | **AG3-163** AC 3 | — |
| AC 3 | zweiter Sync = genau ein Datensatz | **AG3-163** AC 4 | — |
| AC 4 | Delete + `full_reindex` konsistent | **AG3-163** AC 5 | — |
| AC 5 | Projektfilter auf jeder Operation, Zwei-Projekt-Test | **AG3-163** AC 6 | — |
| AC 6 | `concept_validate` blockiert Sync hart | **AG3-165** AC 1/2 (Katalog, Exit-Codes) + **AG3-166** AC 1 (Blockade) | — |
| AC 7 | `INDEX.yaml`/`graph`/`corpus_revision` konsistent, Zyklen scheitern | **AG3-165** AC 4 | — |
| AC 8 | Shadow-Replace atomar | **AG3-166** AC 4 | **F3:** konkurrierende Leser an jeder Umschaltphase, verlorenes CAS, Crash-Recovery, spaeteres GC und Tombstone — gegen **echte** Weaviate-Infrastruktur |
| AC 9 | Freshness-Gate blockiert nach FK-21 §21.11.4 | **AG3-166** AC 7 (Indikator) + **AG3-169** AC 9 (Aktualisierung) + **AG3-170** AC 2 (Hard Stop) | — |
| AC 10 | `concepts_dir`, `.conceptignore`, Archivpfad | **AG3-162** AC 4/7 + **AG3-165** AC 9 + **AG3-166** AC 6 | — |
| AC 11 | SSOT-Entscheidung getroffen + Drift-Test | **AG3-162** AC 1/2/3 | Entscheidung ist jetzt Vorgabe, nicht Aufgabe |
| AC 12 | Goldkorpus versioniert und dokumentiert | **AG3-166** AC 8/9 | + Orakelfelder, gebundener Digest, unabhaengige Freigabe, kumulativer Aenderungsschutz (Version **und** Neufreigabe) — F5 |

### 2.3 Alt-AG3-163 (`vectordb-mcp-surface-dual-harness`)

| Alt | Inhalt | Neue Heimat | Anmerkung |
|---|---|---|---|
| Scope 1 | MCP-Server + fuenf Tools + drei Suchmodi + `concept_search`-Semantik | **AG3-167** Scope 1–3 | — |
| Scope 2 | Ergebnis-/Fehlervertraege, Sync-Zaehler, Partial-Failure-Verbot | **AG3-167** Scope 4 | — |
| Scope 3 | Dual-Harness-Registrierung, ein Codex-Writer, FK-76, Trust-Blocker | **AG3-168** Scope 1–5 | **F4:** Codex-Eintrag jetzt vollstaendig — `command`, `args`, `cwd`, `env` (`PROJECT_ID` + alle Endpunktwerte), `required = true`; `env` ist der **einzige** Uebergabeweg fuer beide Harnesse |
| Scope 4 | Drei Belege (MCP-Client, reale Harness-Discovery, zweites Projekt) | **AG3-167** AC 9 (Protokoll gegen das Modul) + **AG3-168** Scope 7 (alle drei gegen das **registrierte** Kommando) | — |
| Scope 5 | Retrieval-Qualitaet messen | **AG3-167** Scope 8 | **E6:** Werte kommen aus dem Orakel (AG3-166), werden hier nur konsumiert |
| Scope 6 | Skill-Konsum, Grep-Fallback weg, FK-43-Lifecycle | **AG3-170** vollstaendig | — |
| AC 1 | Server startet ueber registriertes Kommando, fuenf Tools | **AG3-167** AC 1 (Modulstart) + **AG3-168** AC 9 (registriertes Kommando) | — |
| AC 2 | drei Suchmodi wirksam | **AG3-167** AC 3 | jetzt gegen echte Weaviate-Infrastruktur |
| AC 3 | `concept_search` nur Konzepte, `active`-Default, Authority-Ranking | **AG3-167** AC 4 | — |
| AC 4 | `story_search`/`story_sync`/`story_list_sources`/`concept_sync` nach §13.4.1/§13.9.5 | **AG3-167** AC 2/5 | Datenbasis von `story_list_sources` in **AG3-163** AC 10 |
| AC 5 | Contract-Test gegen FK-13 | **AG3-167** AC 2 | — |
| AC 6 | beide Registrierungen, idempotenter Merge, Fremdeintraege erhalten | **AG3-168** AC 1/1a/1b/1c/1d/2 | **F4:** feldweise Wertgleichheit beider Harnesse, Nicht-Default-Endpoint, zwei `project_id`s, Pflichtserver-Negativfall ueber die reale Codex-CLI, Verbot impliziter Zweitquellen |
| AC 7 | keine Benutzer-/Globalkonfiguration, zweites Projekt sieht nichts | **AG3-168** AC 5/6 | — |
| AC 8 | Kommando existiert, startet, bedient `initialize`/`tools/list`/Toolcall | **AG3-164** AC 3–6 (generischer Check) + **AG3-168** AC 8/9 (Anwendung) | **E7:** AG3-164 ist alleiniger Owner |
| AC 9 | Codex-Trust-Blocker sichtbar | **AG3-168** AC 7 | — |
| AC 10 | Recall@k/Top-k je Modus | **AG3-167** AC 11 | gegen fixiertes Orakel |
| AC 11 | fail-closed nach §13.8 | **AG3-167** AC 7 | — |
| AC 12 | Grep-Fallback entfernt, FK-43-Lifecycle abgenommen | **AG3-170** AC 1, 4–8 | — |
| AC 13 | Agent erhaelt in beiden Harnessen zitierbare Quellpassagen | **AG3-170** AC 9/10/11 (komponierte Endabnahme) + **AG3-167** AC 9 (Retrieval-Substanz) | **F9:** je Harness **ein** durchgehender Lauf Install → CP10/CP10a → Harness-Neustart → reale Discovery → Toolcall ueber das registrierte Kommando → gebundene Orakel-Treffer; danach Fremdprojekt negativ |

### 2.4 Alt-AG3-164 (`are-mcp-phantom-registration`)

| Alt | Inhalt | Neue Heimat | Anmerkung |
|---|---|---|---|
| Scope 1 | Ehrliches Fehlschlagen bei `features.are: true` | **AG3-164** Scope 3 | unveraendert |
| Scope 2 | Generalisierter Startbarkeits-Check | **AG3-164** Scope 1/2 | **E7 verschaerft:** Prozessstart mit Timeout, `initialize`, `tools/list`; Registrierung erst danach; Groesse S → **M** |
| Scope 3 | Reproduzierende Tests | **AG3-164** Scope 5 | um drei Falsch-Gruen-Faelle erweitert |
| Scope 4 | Bei FK-50/FK-03-Konflikt stoppen und melden | **AG3-164** Scope 6 | unveraendert |
| AC 1 | Lauf schlaegt fehl mit klarer Ursache | **AG3-164** AC 1 | — |
| AC 2 | kein `are-mcp`-Eintrag geschrieben | **AG3-164** AC 2 | — |
| AC 3 | Check gilt generisch | **AG3-164** AC 3 | — |
| AC 4 | `features.are: false` bleibt erfolgreich | **AG3-164** AC 7 | jetzt mit `SKIPPED`-vs.-`FAILED`-Abgrenzung |
| AC 5 | bestehende CP10-Tests bleiben gruen | **AG3-164** AC 8 | — |

### 2.5 Neu hinzugekommene Inhalte (kein Alt-Vorbild)

| Inhalt | Heimat | Anlass |
|---|---|---|
| Source-Type/Producer-Matrix ueber alle §13.3.2-Quellen inkl. `research` und Architektur-Dokumenten | **AG3-163** Scope 3, AC 7/8/8a | `review-2-codex.md` neues P1-6 (E8); **F8:** positive, producergebundene Research-Erkennung (`stories/<story-ordner>/research/**/*.md`) mit `review*.md`, Closure-/Audit- und unbekanntem Markdown als Negativfaellen |
| **Atomare Aktivierung der Pflichtinfrastruktur** als eigene Story | **AG3-171** vollstaendig | `review-3-codex.md` P0-1 (**F1**) |
| Token-Einheit, modellgebundener Tokenizer, exakte Grenzregel, entschiedene `E-CHUNK-001`-Overflow-Policy | **AG3-162** Scope 2/3, AC 3/6/6a; **AG3-165** AC 1a | `review-3-codex.md` P1-3 (**F7**) |
| **Tokenizer-Liefervertrag**: versioniertes Package-Asset mit Digest/Revision/Lizenz, gepinnte `tokenizers`-Runtime-Dependency, fail-closed offline | **AG3-161** Scope 3a, AC 5a/5b (Dependency, Asset, Packaging-Nachweis); **AG3-162** AC 3/6b (Contract, Digestpruefung, Clean-Venv ohne Netz und Cache) | `review-4-codex.md` P1-3 (**G4**) |
| Echte Weaviate-Testfixture entsteht einmal und wird konsumiert | **AG3-166** AC 4; Konsum in AG3-167, AG3-169, AG3-170, AG3-171 | `review-3-codex.md` P0-2 (**F3**) |
| FK-13-Driftbereinigung `story_sync` vs. `concept_sync`; CP9/9a vs. CP10/10a | **AG3-163** Scope 5, AC 9 | `review-codex.md` P0-1, `review-2-codex.md` P1-6 (E8) |
| CP10a fuehrt beide Full-Syncs aus, Sync-Receipt, harter Fehlerpfad, Installations-E2E | **AG3-169** | `review-2-codex.md` neues P0-3 (E4) |
| Verpflichtender Integrationstest gegen echte Weaviate-/Embedding-Infrastruktur | **AG3-167** Scope 7, AC 9/10 | `review-2-codex.md` neues P1-1 (E5) |
| Versioniertes Orakel mit fixem `k`, Recall/Rang, Modellbindung, Reviewpflicht | **AG3-166** Scope 5, AC 8/9 | `review-2-codex.md` neues P1-2 (E6) |
| Vollstaendiger Finding-/Exit-Code-Katalog als AC erzwungen | **AG3-165** AC 1–3 | `review-2-codex.md` P0-3 „teilweise" |
| Schutzringe **installiert und feuernd** statt nur installiert | **AG3-165** AC 5–8 | `review-2-codex.md` P0-3 „teilweise" |

## 3. Befund-Abdeckung

### 3.1 Ursprungsbefunde (`review-codex.md`, Urteil aus `review-2-codex.md`)

| Befund | Voriges Urteil | Jetzt geschlossen durch |
|---|---|---|
| P0-1 Tool-/Normvertrag | teilweise | AG3-161 (Vertrag) + **AG3-171** (Wirksamkeit), AG3-163 (FK-13-Drifts `story_sync`/`concept_sync` und CP9/9a) |
| P0-2 Story-Index nur Transportprototyp | teilweise | AG3-163 (Schema, IDs, Hashes, Projektfilter, `full_reindex`), AG3-167 (echter Weaviate-Nachweis), AG3-169 (Erstindizierung) |
| P0-3 fehlender Concept-Corpus-Lifecycle | teilweise | AG3-165 (vollstaendiger Katalog, Ringe feuernd), AG3-166 (vorentschiedener Shadow-Replace-Vertrag inkl. Leser-Konsistenz, F3) |
| P0-4 Projektisolation/Binding | geschlossen | AG3-161 (minimal, E3), AG3-168 (projektlokale Registrierung) |
| P0-5 Runtime-Stack/Installationsnachweis | teilweise | AG3-161 (Packaging nach `[project.dependencies]`, Preflight), AG3-163 (Schema-Handoff aufgeloest), AG3-167 (realer Lauf), AG3-169 (CP10a), **AG3-171** (regressiv landbarer CP10-Uebergang, Clean-Venv-Protokoll) |
| P1-1 Codex-Vertrag/Owner/Trust | geschlossen | AG3-168 inkl. vollstaendiger Laufzeitbindung (F4) |
| P1-2 zu grosser Scope, ARE-Fremdkoerper | teilweise | Elf-Story-Schnitt; AG3-164 separat und aufgewertet |
| P1-3 Discovery-/Chunking-SSOT | **offen** | AG3-162 (E9-Entscheidung als Vorgabe, ergaenzt um die F7-Token-/Overflow-Semantik) |
| P1-4 semantisches Falsch-Gruen | teilweise | AG3-166 (Orakel als Eingangsartefakt, F5), AG3-167 (Messung, echte Infrastruktur) |
| P1-5 FK-43-Lifecycle | geschlossen | AG3-170 |
| P2-1 Drei-Belege-Abnahme | geschlossen | AG3-168 Scope 7; komponiert in AG3-170 AC 9–11 (F9) |

### 3.2 Neue Findings (`review-2-codex.md`)

| Finding | Geschlossen durch |
|---|---|
| P0-1 Teilschema-Handoff 161→162 | **E2** — vollstaendige Schemaerzeugung inkl. aller Properties in **AG3-163**; AG3-161 benennt nur Owner/Aufrufpunkt/Idempotenz. |
| P0-2 Feature-Flag schwaecht die Norm | **E1** — Codex-Empfehlung uebernommen: `features.vectordb` deprecated, optionaler CP10-Ast entfaellt, FK-13 unveraendert; FK-50/FK-03/FK-21 nachgezogen (**AG3-161**). |
| P0-3 Index darf nach Installation leer bleiben | **E4** — **AG3-169** fuehrt beide Full-Syncs aus, mit Receipt, hartem Fehlerpfad und Installations-E2E ueber beide Quellarten; Closure- und Post-Commit-Trigger als ausgefuehrte Trigger abgenommen. |
| P1-1 Retrieval durch Test-Doubles ersetzbar | **E5** — **AG3-167** verlangt einen nicht ueberspringbaren Lauf gegen echte Weaviate-Instanz mit dem normierten Vectorizer, inkl. Beleg, dass kein Double aktiv ist. |
| P1-2 Goldkorpus nachtraeglich optimierbar | **E6** — versioniertes Orakel in **AG3-166** (fixes `k`, `expected_ids`/`forbidden_ids`, Recall/Rang, Modellbindung, Aenderungsschutz); **AG3-167** konsumiert nur. |
| P1-3 geteilte CP10-Ownership, Check zu schwach | **E7** — **AG3-164** alleiniger Owner, Erfolgsbegriff Start+Timeout/`initialize`/`tools/list`, Registrierung erst danach, Groesse **M**; **AG3-168** haengt an AG3-164 und konsumiert. |
| P1-4 162/163 zu gross fuer L | **E10** — Neuschnitt in zehn Stories entlang der Producer-Consumer-Kanten; jede Story eigenstaendig abschliessbar. |
| P1-5 `ProjectBinding` zu stark | **E3** — auf `project_root`, Containment, `cwd`, `project_id` reduziert (**AG3-161**); globale Identitaetsordnung und Registry-CAS verworfen. |
| P1-6 Normanteile beim Split verloren | **E8** — Source-Type/Producer-Matrix in **AG3-163** (alle vier Quellen mit Discovery, Tool-Owner, Initial-/Delta-Trigger, Delete-Semantik, Tests) plus diese Herkunftsmatrix als Verlustbeleg. |
| P2-1 Reverse-Kanten ungenau | **E11** — direkte Kanten, nach `review-3-codex.md` P2-1 vollstaendig gefuehrt: AG3-166 ← {163, 165}; AG3-168 ← {164, 167}; AG3-169 ← {163, 165, 166, 168}; AG3-170 ← {166, 167, 168, 169, 171}; AG3-171 ← {164, 167, 168}; AG3-164 unabhaengig startbar. |

### 3.3 Neue Findings (`review-3-codex.md`)

| Finding | Geschlossen durch |
|---|---|
| P0-1 AG3-161 nicht eigenstaendig landbar; Uebergang verbreitert Phantomeintrag | **F1** — Aktivierung als atomare Schnittkante in **AG3-171** (← 164, 167, 168). AG3-161 behaelt Packaging, minimales Binding und Vertragsvorbereitung und laesst den optionalen Ast bestehen. Der „bewusste Uebergangszustand" und das alte AC 9 entfallen; Ersatz ist das Negativ-/Positiv-E2E der Aktivierung (AG3-171 AC 3–5). |
| P0-2 Shadow-Replace weder entschieden noch testbar | **F3** — vollstaendiger Vertrag in **AG3-166** Scope 2 (immutable `generation_id`, Staging + Digest-/Sollmengenvalidierung, ein CAS-faehiger Active-Generation-Anker je (`project_id`, `source_file`), am Anfragebeginn gebundene Lesergeneration, GC mit Retry-Regel, Tombstone). AC 4 prueft konkurrierende Leser an jeder Umschaltphase, verlorenes CAS, Crash-Recovery und spaeteres GC gegen echte Weaviate-Infrastruktur. **Konfliktklausel:** fehlt der CAS-/Konsistenzvertrag, wird „atomar" normativ korrigiert statt im Code simuliert. |
| P0-3 Codex-Registrierung ohne Projekt-/Endpoint-Bindung | **F4** — **AG3-168** Scope 2/2a/4 und AC 1/1a/1b/1c/1d: `[mcp_servers.story-knowledge-base]` mit `command`, `args`, `cwd`, `env` (`PROJECT_ID` + vollstaendige Endpunktwerte) und `required = true`; Nicht-Default-Endpoint, zwei `project_id`s und Pflichtserver-Negativfall ueber die reale Codex-CLI. **Ein** Uebergabemechanismus fuer beide Harnesse: ausschliesslich `env`; Lesen aus `cwd`/Projektconfig ist verworfen. FK-76 traegt den Vertrag. |
| P1-1 Orakel nicht vor opportunistischer Erstwahl geschuetzt | **F5, korrigiert durch G3** — Orakel ist **reviewtes Eingangsartefakt** und Startgate von **AG3-166**; Owner der Erstellung ist der **PO oder ein vom PO benannter, nicht implementierender fachlicher Reviewer/Orchestrator** (nicht mehr der `Council-Orchestrator`). AG3-166 materialisiert und validiert, waehlt nicht. AC 8/9 verlangen gebundenen Digest, Freigabe durch einen vom Implementierer verschiedenen Reviewer, einen bereits existierenden Commit-/Artefakt-Ref und den Nachweis der zeitlichen Ordnung; Aenderungen brauchen Version **und** erneute unabhaengige Freigabe. |
| P1-2 „Dependency des Laufzeitprofils" erlaubt Extra | **F6** — **AG3-161**: `mcp` und `weaviate-client` nach `[project.dependencies]`, Extra-Verbot als Test, Clean-Venv ueber den produktiven Zielprojekt-Installationsweg. Der Protokollnachweis bis `initialize`/`tools/list` ueber das registrierte Kommando liegt in **AG3-171** AC 6 — vorher existiert das Servermodul nicht. |
| P1-3 Tokenzaehl-/Overflow-Semantik delegiert | **F7** — **AG3-162**: Einheit Token fuer `fk13_concept`/`fk13_story`, Tokenizer des FK-13-§13.2-Embedding-Modells, exakte Grenzregel (`<= 1000`), Overflow-Policy entschieden (deterministische Teilung unterhalb der Heading-Ebene + Befund). Die Achse „Zeichen oder Tokens" als Wahlmoeglichkeit entfaellt; nur `ak3_tool` behaelt 12.000 Zeichen. Fuer den Konzeptkorpus bleibt `E-CHUNK-001` in **AG3-165** blockierend. |
| P1-4 Research-Discovery als Negativfilter | **F8** — **AG3-163**: positive, producergebundene Erkennung ueber den kanonischen Pfad `stories/<story-ordner>/research/**/*.md`; AC 8 prueft `review*.md`, Closure-/Audit-Dokumente und unbekanntes Markdown als Negativfaelle; `story_list_sources` weist nur zugelassene Produzenten aus (AC 8a). |
| P1-5 leeres Produktionsmodul in AG3-161 | **F2** — kein `schema.py` in AG3-161; Modulort, Owner und Aufrufpunkt stehen nur im Decision Record. Die reale Datei entsteht einmal in **AG3-163** (dort als „neu" gefuehrt). AG3-161 AC 7 belegt die Nichtexistenz. |
| P1-6 keine komponierte Endabnahme | **F9** — **AG3-170** Scope 5 und AC 9–11: je Harness ein durchgehender Lauf (sauberes Zielprojekt + isolierter Userspace → produktiver Installationsbefehl → CP10/CP10a → Harness-Neustart(simulation) → reale Discovery → Toolcall ueber das registrierte Kommando → gebundene Orakel-Treffer beider Quellarten), danach Fremdprojekt negativ. Keine Backend-/Adapterabfrage ersetzt einen Schritt. |
| P2-1 `depends_on` nicht durchgaengig direkt | **F10** — direkte Kanten vollstaendig gefuehrt (siehe §1); neue Aktivierungskante AG3-171 ← {164, 167, 168} und Konsumkante AG3-170 ← AG3-171. |

### 3.4 Neue Findings (`review-4-codex.md`)

| Finding | Geschlossen durch |
|---|---|
| P0-1 AG3-171 aktiviert CP10a vor dessen echter Implementierung | **G1** — `AG3-171 depends_on` um **AG3-169** ergaenzt, `AG3-169 unblocks: [AG3-170, AG3-171]` nachgezogen. AG3-171 AC 3 konsumiert den **produktiven** CP10a-Erfolg: beide Full-Sync-Receipts erfolgreich, danach je eine Story- und eine Concept-Suche mit Treffern, **ohne** manuellen Sync-Aufruf. Blosse Ausfuehrung von CP10a genuegt nicht. Ziel-Linearisierung `... -> AG3-168 -> AG3-169 -> AG3-171 -> AG3-170`. |
| P1-1 AG3-161 behauptet einen Sicherheitszustand, den seine Dependencies nicht herstellen | **G2** — `AG3-161 depends_on: [AG3-164]`, `status: blocked`. Das absolute Null-Phantom-AC bleibt bestehen (keine Abschwaechung) und ist mit der Kante sachlich erfuellbar. Die alte SPLIT-Begruendung „Kante auf AG3-164 erzeugt flaechendeckenden Ausfall" ist korrigiert: Sie galt fuer die alte AG3-161 mit Pflichtaktivierung. Backlog-Stand dokumentiert (§1): keine faelschlich parallel startbare `ready`-Story. |
| P1-2 Oracle-Startgate verwendet eine nach `CLAUDE.md` unzulaessige Rolle | **G3** — Owner ist der **PO** oder ein vom PO benannter, **nicht implementierender** fachlicher Reviewer bzw. regulaerer Orchestrator. Das Eingangsartefakt liegt **versioniert vor** dem `in_progress`-Wechsel; das Approval bindet **Orakel-Digest, Reviewer-Identitaet und einen bereits existierenden Commit-/Artefakt-Ref**; der Story-Bericht weist die zeitliche Ordnung nach (AG3-166 Vorbedingung, Kontext, Scope 5, AC 8/9). |
| P1-3 Der modellgebundene Tokenizer hat keinen produktiven Liefervertrag | **G4** — Tokenizer wird als **versioniertes Package-Asset** ausgeliefert (`tokenizer.json`/Vokabular von `sentence-transformers/all-MiniLM-L6-v2`, `tokenizer_revision e4ce9877abf3edfe10b0d82785e83bdcb973e22e`), mit gebundenem SHA-256 und dokumentierter Apache-2.0-Lizenz. Runtime-Bibliothek **`tokenizers==0.21.0`** in `[project.dependencies]`; `transformers` ausdruecklich nicht erforderlich (AK3 bringt heute gar keine Tokenizer-Bibliothek mit). **Kein impliziter Netzabruf**, fail-closed bei fehlendem oder digestabweichendem Asset, kein zeichenbasierter Ersatz. Neues AC: Clean-Venv **ohne Netzwerk und ohne vorbefuellten Model-Cache** erfuellt denselben Token-Contract. Dependency + Asset in **AG3-161**, Contract in **AG3-162**; Kante vermerkt. |
| P2-1 Reverse-Kante von AG3-164 voruebergehend unvollstaendig | **dokumentarisch geschlossen** — `AG3-169.unblocks` fuehrt AG3-171 jetzt (G1). `AG3-164/` bleibt in dieser Nachbesserung **unangetastet** (die Story ist `in_progress` und wird unabhaengig reviewt). **Auflage:** Der Abschluss-/Status-Folgecommit von AG3-164 zieht die Reverse-Kanten nach — `AG3-164.unblocks` muss danach **AG3-161** (neue Kante aus G2) **und AG3-171** enthalten. `depends_on` bleibt autoritativ; bis dahin ist der Drift bekannt und gemeldet (`stories/README.md` §4.1). |

### 3.5 Groessenurteil aufgegriffen

Runde 2 (Codex): „AG3-161 = M plausibel, 162 = L nicht plausibel, 163 = L
nicht plausibel, 164 als echter Conformance-Check eher M."

Runde 3 (Codex, Abschnitt „Groessen- und Schnitturteil") ist
uebernommen. Ergebnis nach den F-Entscheidungen:

| Story | Groesse | Begruendung nach Runde 3 |
|---|---|---|
| AG3-161 | **M** | Nach Herausnahme der Aktivierung (F1) und des leeren `schema.py` (F2) eindeutig M — und jetzt auch eigenstaendig landbar. |
| AG3-162 | **M** | Plausibel, da Token-/Overflow-Semantik feststeht (F7). |
| AG3-163 | **L** | Plausibel am oberen Rand; Schema und Story-/Research-Schreibpfad bleiben ein kohaerenter vertikaler Schnitt. F8 praezisiert die Discovery, ohne den Umfang zu vergroessern. |
| AG3-164 | **M** | Unveraendert (E7). |
| AG3-165 | **L** | Plausibel; deterministischer Validate-/Build-/Hook-Strang. |
| AG3-166 | **L** | Codex sah „derzeit groesser als L". Entlastet durch F5 (Orakelwahl wird zum Eingangsartefakt und faellt aus dem Storyumfang heraus) und F3 (Algorithmus ist vorgegeben statt zu erarbeiten). Der verbleibende Zuwachs ist Testtiefe gegen echte Infrastruktur, kein zusaetzlicher Entwurfsraum. **L bleibt vertretbar; ein weiterer Schnitt wurde geprueft und verworfen**, weil Sync, Shadow-Replace und Freshness denselben Schreibpfad und dieselbe Generationensemantik teilen — ein Trennschnitt haette einen Zwischenstand mit halbem Sichtbarkeitsvertrag erzeugt. |
| AG3-167 | **L** | Plausibel; geschlossene MCP-/Retrieval-Vertikale. |
| AG3-168 | **M** | Plausibel nach Ergaenzung des Codex-`env`-/`required`-Vertrags (F4). |
| AG3-169 | **M** | Plausibel. |
| AG3-170 | **M** | Plausibel, da der komponierte E2E explizit ist (F9). |
| AG3-171 | **M** | Neu; enge Aktivierungsstory mit Konzeptnachzuegen und zwei E2E-Pfaden. |

Der von Codex benannte Ausnahmefall 161→164/167/168 („noch nicht
erfuellbarer Pflichtpfad vorgezogen") existiert nicht mehr: Der
Pflichtpfad wird erst in AG3-171 scharf geschaltet, wenn alle vier
Faehigkeiten (inkl. AG3-169, G1) im Stand sind.

**Runde 4 (Codex, „Groessen- und Schnitturteil")** bestaetigt alle elf
Groessen unveraendert. Die Anpassungen G1–G4 sind gezielte
Briefingkorrekturen und veraendern keinen Storyumfang: G1 und G2 fuegen
nur Kanten hinzu, G3 tauscht eine Rolle, G4 verschiebt Dependency und
Asset in den ohnehin bestehenden Packaging-Scope von AG3-161. AG3-166
bleibt L (der unzulaessige Oracle-Owner war laut Codex ausdruecklich
„kein weiterer Codeschnitt noetig").

## 4. Vorentschiedene Punkte (E1–E11 aus Runde 2, F1–F10 aus Runde 3)

Diese Entscheidungen sind vom PO getroffen und in den Briefings
umgesetzt. Ein Umsetzungsagent rollt sie **nicht** neu auf; er setzt sie
um. Bei Konflikt mit einem Konzept gilt die Regel aus
`stories/README.md` §4.2: **stoppen und melden**.
Wo eine F-Entscheidung eine E-Entscheidung praezisiert, gilt die
F-Fassung; wo eine G-Entscheidung eine E-/F-Entscheidung praezisiert,
gilt die G-Fassung.

### 4.1 Runde 2 (E1–E11)

| ID | Entscheidung | Heimat |
|---|---|---|
| E1 | VektorDB ist Pflichtinfrastruktur; `features.vectordb` deprecated; optionaler CP10-Ast entfaellt; FK-13 **nicht** abschwaechen; FK-21/FK-50-Nachzuege minimal | AG3-161 (Vertrag) / **AG3-171** (Wirksamkeit, siehe F1) |
| E2 | Vollstaendige Schemaerzeugung inkl. Felddefinition in **einer** Story; kein Teilschema, kein „erweitern" | AG3-161 (nur normative Owner-Festlegung, siehe F2) / AG3-163 (Datei + Erzeugung) |
| E3 | `ProjectBinding` minimal; keine neue globale Identitaetsordnung | AG3-161 |
| E4 | CP10a fuehrt beide Full-Syncs aus; Receipt; harter Fehlerpfad; laufende Producer | AG3-169 |
| E5 | Verpflichtender Test gegen echte Weaviate-Instanz mit normiertem Vectorizer; Testinfrastruktur, kein Installer-Bundling | AG3-167 |
| E6 | Versioniertes Orakel in der Corpus-Story; Oberflaeche konsumiert nur | AG3-166 / AG3-167 |
| E7 | AG3-164 alleiniger Owner des generischen MCP-Conformance-Checks; Groesse M | AG3-164 / AG3-168 |
| E8 | Vollstaendige Source-Type/Producer-Matrix; FK-13-Drifts bereinigt | AG3-163 |
| E9 | Ein generischer Ingest-Kern als SSOT; `tools/concept_ingester` wird Adapter; Profile parametrisiert und getrennt | AG3-162 |
| E10 | Weiter schneiden ohne Inhaltsverlust; jede Story eigenstaendig abschliessbar | dieser Schnitt |
| E11 | `depends_on` fuehrt **direkte** Kanten | alle `status.yaml` (vollstaendig gefuehrt, siehe F10) |

### 4.2 Runde 3 (F1–F10)

| ID | Entscheidung | Heimat |
|---|---|---|
| F1 | **Aktivierung ist eine atomare Schnittkante.** Packaging, minimales Binding und Vertragsvorbereitung bleiben in AG3-161; `features.vectordb: false` als harter Fehler, Entfall von `branch_vectordb_enabled` und unbedingtes CP10 wandern in die neue **AG3-171** (← AG3-164, AG3-167, AG3-168). Der „bewusste Uebergangszustand" entfaellt ersatzlos; das alte AG3-161 AC 9 ist durch ein Negativ-/Positiv-E2E ersetzt. Decision Record bleibt in AG3-161, Code-Wirksamkeit in AG3-171. | AG3-161 / **AG3-171** |
| F2 | **Kein leeres Produktionsmodul.** AG3-161 legt kein `schema.py` an; Modulort, Owner und Aufrufpunkt stehen nur im Decision Record/Technikkonzept. Die reale Datei samt vollstaendiger Operation entsteht einmal in AG3-163. | AG3-161 / AG3-163 |
| F3 | **Shadow-Replace vorentschieden.** Immutable `generation_id` je Dokumentversion; vollstaendiges Staging mit Digest-/Sollmengenvalidierung; ein CAS-faehiger Active-Generation-Anker je (`project_id`, `source_file`); Leser binden die Generation am Anfragebeginn; Retention/GC mit Retry-Regel; Tombstone fuer geloeschte Quellen. AC 4 prueft reale konkurrierende Leser an jeder Umschaltphase, verlorenes CAS, Crash-Recovery und spaeteres GC gegen echte Weaviate-Infrastruktur. **Konfliktklausel:** fehlt der CAS-/Konsistenzvertrag, wird „atomar" normativ korrigiert statt im Code simuliert. | AG3-166 |
| F4 | **Codex-Laufzeitbindung vollstaendig.** `[mcp_servers.story-knowledge-base]` mit `command`, `args`, `cwd`, `env` (`PROJECT_ID` + vollstaendige Endpunktwerte) und `required = true`; identischer Projekt-/Endpoint-Vertrag wie Claude Code; Nachweise mit Nicht-Default-Endpoint, zwei `project_id`s und Pflichtserver-Negativfall ueber die reale Codex-CLI. **Ein** Uebergabemechanismus fuer beide Harnesse: ausschliesslich `env` — Lesen aus `cwd`/Projektconfig ist verworfen. | AG3-168 (+ FK-76) |
| F5 | **Orakel vor Implementierungsstart.** Die `oracle-v1`-Datei bzw. ihre vollstaendige Wertetabelle liegt als reviewtes Eingangsartefakt vor; Owner der Erstellung ist **~~der Council-Orchestrator~~ → siehe G3** (PO bzw. vom PO benannter, nicht implementierender fachlicher Reviewer/Orchestrator). AG3-166 materialisiert und validiert sie, waehlt sie nicht. AC 8 verlangt gebundenen Digest und Freigabe durch einen vom Implementierer verschiedenen Reviewer; Aenderungen brauchen Version **und** erneute unabhaengige Freigabe. | AG3-166 |
| F6 | **Dependencies eindeutig.** `mcp` und `weaviate-client` nach `[project.dependencies]`; kein neues Extra. Der Clean-Venv-Test nutzt exakt den produktiven Zielprojekt-Installationsweg; der Protokollnachweis bis `initialize`/`tools/list` ueber das registrierte Kommando liegt in AG3-171 (dort existiert der Server). | AG3-161 / AG3-171 |
| F7 | **Token-Semantik vorgegeben.** `fk13_concept` und `fk13_story` rechnen in **Tokens** mit dem Tokenizer des FK-13-§13.2-Embedding-Modells; Grenzregel exakt (`<= 1000`). Overflow-Policy `E-CHUNK-001`: **deterministisch unterhalb der Heading-Ebene teilen, Befund protokollieren** — nur so geht kein normativer Inhalt verloren. Nur `ak3_tool` behaelt den 12.000-Zeichen-Vertrag. Die Achse „Zeichen oder Tokens" entfaellt aus der Parametrisierungsliste. Fuer den Konzeptkorpus bleibt `E-CHUNK-001` blockierend. | AG3-162 / AG3-165 |
| F8 | **Research-Discovery positiv binden.** Erkennung ueber den kanonischen Pfad `stories/<story-ordner>/research/**/*.md` statt ueber einen Negativfilter. AC prueft neben einem Positivfall mindestens `review*.md`, Closure-/Audit-Dokumente und unbekanntes Markdown als Negativfaelle; `story_list_sources` weist nur zugelassene Produzenten aus. | AG3-163 |
| F9 | **Komponierte Endabnahme.** Je Harness ein durchgehender Lauf: sauberes Zielprojekt + isolierter Userspace → produktiver Installationsbefehl → CP10/CP10a → Harness-Neustart(simulation) → reale Harness-Discovery → Toolcall ueber das registrierte Kommando → gebundene Orakel-Treffer beider Quellarten; danach derselbe Lauf aus einem Fremdprojekt negativ. Keine direkte Backend-/Adapterabfrage ersetzt den Harness-Schritt. | AG3-170 |
| F10 | **Groessen und Kanten.** Codex' Groessenurteil uebernommen (§3.5); `depends_on` fuehrt vollstaendig direkte Kanten; neue Aktivierungskante AG3-171 ← {AG3-164, AG3-167, AG3-168} (**erweitert um AG3-169, siehe G1**) und Konsumkante AG3-170 ← AG3-171. | alle `status.yaml` |

### 4.3 Runde 4 (G1–G5)

| ID | Entscheidung | Heimat |
|---|---|---|
| G1 | **Aktivierung braucht den echten Erstindex.** `AG3-171 depends_on` wird um **AG3-169** ergaenzt; `AG3-169 unblocks` fuehrt entsprechend `[AG3-170, AG3-171]`. AG3-171 AC 3 konsumiert den **produktiven** CP10a-Erfolg aus AG3-169: beide Full-Sync-Receipts erfolgreich, danach je eine Story- und eine Concept-Suche mit Treffern, **ohne** manuellen Sync-Aufruf. Dass CP10a „ausgefuehrt" wird, genuegt ausdruecklich nicht. Ziel-Linearisierung: `... -> AG3-168 -> AG3-169 -> AG3-171 -> AG3-170`. | AG3-171 / AG3-169 |
| G2 | **AG3-161 bekommt die Sicherheitskante.** `AG3-161 depends_on: [AG3-164]`, `status: blocked` bis AG3-164 `completed`. Das absolute Null-Phantom-AC bleibt bestehen und wird **nicht** abgeschwaecht; mit der Kante ist es sachlich erfuellbar. Die frueher hier gefuehrte Gegenbegruendung (Kante erzeuge flaechendeckenden Ausfall) galt fuer die alte AG3-161 mit Pflichtaktivierung und ist korrigiert. Backlog-Stand: keine weitere Story dieses Pakets ist `ready`; nur AG3-164 laeuft (§1). | AG3-161 / SPLIT §1 |
| G3 | **Orakel-Owner korrigiert.** `Council-Orchestrator` ist nach `CLAUDE.md` unzulaessig (Rolle gilt nur fuer Konzeptarbeit im Concept-Incubator nach DK-16/FK-78 und bezieht in Moderationsphasen keine inhaltliche Parteiposition). Neuer Owner: der **PO** oder ein vom PO benannter, **nicht implementierender** fachlicher Reviewer bzw. regulaerer Orchestrator. Das Eingangsartefakt liegt **versioniert vor** dem `in_progress`-Wechsel von AG3-166; das Approval bindet **Orakel-Digest, Reviewer-Identitaet und einen bereits existierenden** Commit-/Artefakt-Ref; der Story-Bericht weist die zeitliche Ordnung nach. | AG3-166 |
| G4 | **Tokenizer-Liefervertrag entschieden.** Der Tokenizer wird als **versioniertes Package-Asset** ausgeliefert (`tokenizer.json`/Vokabular des FK-13-§13.2-Modells `sentence-transformers/all-MiniLM-L6-v2`, `tokenizer_revision e4ce9877abf3edfe10b0d82785e83bdcb973e22e`), mit gebundenem SHA-256-Digest und dokumentierter Apache-2.0-Lizenz. Runtime-Bibliothek: die schlanke **`tokenizers`**-Bibliothek, gepinnt auf **`tokenizers==0.21.0`**; `transformers` ist nicht erforderlich und waere unverhaeltnismaessig (AK3 bringt heute keine Tokenizer-Bibliothek mit — `[project.dependencies]` fuehrt nur `argon2-cffi`, `pydantic`, `psycopg`, `psycopg-pool`, `pyyaml`, `psutil`). **Kein impliziter Netzabruf zur Laufzeit**; fehlendes oder digestabweichendes Asset bricht **hart** ab — kein Netz-Fallback, kein zeichenbasierter Ersatz. Neues AC: Clean-Venv-Test **ohne Netzwerk und ohne vorbefuellten Model-Cache** erfuellt denselben Token-Contract. **Zustaendigkeit:** Dependency und Asset in **AG3-161** (dort liegt `[project.dependencies]`), Token-Contract in **AG3-162**; die Kante AG3-162 ← AG3-161 ist damit auch eine Liefer-Kante. | AG3-161 / AG3-162 |
| G5 | **SPLIT-Matrix ehrlich gemacht.** Die drei von Codex benannten Ueberschaetzungen — AG3-171 „atomar" ohne AG3-169-Vorbedingung, AG3-161 „sofort und eigenstaendig startbar" trotz AG3-164-abhaengigem Null-Phantom-AC, modellgebundener Tokenizer „vollstaendig entschieden" ohne Lieferweg — sind mit G1/G2/G4 sachlich behoben und in der Korrekturtabelle (§2) als eigene Zeilen ausgewiesen. | SPLIT §1, §2 |

**Offene dokumentarische Auflage (review-4 P2-1):** Die Reverse-Kante in
`AG3-164/status.yaml` ist bewusst **nicht** in dieser Nachbesserung
angefasst worden (die Story ist `in_progress` und wird unabhaengig
reviewt). Sie gehoert in den **Abschluss-/Status-Folgecommit von
AG3-164**: `AG3-164.unblocks` muss danach **AG3-161** (Kante aus G2)
**und AG3-171** enthalten. `depends_on` bleibt autoritativ; bis dahin ist
der Drift bekannt und nach `stories/README.md` §4.1 gemeldet.
