# Review 3 zum Neuschnitt AG3-161 bis AG3-170

## Aufloesung der Befunde aus Review 2

### Ursprungsbefunde aus `review-codex.md`

| Befund | Urteil | Begruendung |
|---|---|---|
| P0-1 — widerspruechlicher Tool-/Normvertrag | **geschlossen** | AG3-161 AC 1/2 richtet den Code an der Pflichtnorm aus; AG3-163 AC 7/9 entscheidet und prueft die Drifts `story_sync`/`concept_sync` sowie CP9/9a gegen CP10/10a. Die gefaehrliche Landereihenfolge dieser Aenderungen ist ein neuer P0-Befund unten, nicht mehr die inhaltliche Normentscheidung. |
| P0-2 — Story-Index nur Transportprototyp | **geschlossen** | AG3-163 AC 1–10 erzwingt Vollschema, Feldbelegung, deterministische Identitaet, Hash-Abgleich, Delete, `full_reindex`, Projektfilter und reale Quellen. AG3-167 AC 9–11 und AG3-169 AC 1–4 schliessen den produktiven Schreib-/Such- und Erstindizierungsnachweis. |
| P0-3 — fehlender Concept-Corpus-Lifecycle | **teilweise** | Katalog, Build-Artefakte und feuernde Schutzringe sind in AG3-165 materiell gebunden; Sync, Resolver und Freshness in AG3-166/169/170 ebenfalls. Der zentrale Shadow-Replace-Vertrag delegiert den Aktivierungsmechanismus aber weiterhin und beweist keine Leser-Konsistenz; siehe P0-2. |
| P0-4 — Projektisolation/Binding | **geschlossen** | Nach der PO-Klarstellung ist die gemeinsame Collection mit `project_id` korrekt. AG3-161 AC 3/4 begrenzt Schreibpfade, AG3-168 AC 5/6 erzwingt Projektlokalitaet und Fremdprojekt-Negativnachweis. |
| P0-5 — Runtime-Stack und produktiver Installationsnachweis | **teilweise** | Externe DB, Preflight, Clean-Venv, echtes Weaviate, Erstindex und E2E sind ueber 161/167/169 verteilt. Offen bleiben die exakte produktive Dependency-Heimat sowie der regressiv landbare CP10-Uebergang; siehe P0-1 und P1-2. |
| P1-1 — Codex-Vertrag/Owner/Trust | **teilweise** | Ein Writer, semantischer Merge, Trust-Blocker und reale Discovery sind in AG3-168 als AC gebunden. Der Codex-MCP-Eintrag laesst jedoch projektbezogene `env`-Werte und den Pflichtserver-Status offen; dadurch kann nur die Referenzumgebung gruen sein. Siehe P0-3. |
| P1-2 — zu grosser Scope und ARE-Fremdkoerper | **geschlossen** | ARE ist mit AG3-164 eigenstaendig und der restliche Umfang entlang belastbarer Producer-/Consumer-Grenzen verteilt. Einzelne Restgroessen werden unten gesondert bewertet. |
| P1-3 — Discovery-/Chunking-SSOT | **geschlossen** | E9 und AG3-162 AC 1–4 entscheiden eindeutig fuer einen Kern unter `src/agentkit/` und einen duennen Adapter. Die fruehere Wahlmoeglichkeit „gemeinsamer Kern oder Disjunktheit“ besteht nicht mehr. Die noch offene Tokenzaehl-Semantik ist ein neuer Vertragsrest, siehe P1-3. |
| P1-4 — semantisches Falsch-Gruen | **teilweise** | Echte Weaviate-/Embedding-Wirkung und konsumierende Messung sind in AG3-167 stark gebunden. Das initiale Orakel wird aber weiterhin vom Implementierer der AG3-166 selbst gewaehlt und nur formal versioniert; siehe P1-1. |
| P1-5 — vollstaendiger FK-43-Lifecycle | **geschlossen** | AG3-170 AC 4–8 bindet immutable Version, Digest, beide Links, Pinning, Record, Verify und Neustarthinweis materiell. |
| P2-1 — Drei-Belege-Abnahme | **geschlossen** | AG3-168 Scope 7 und AC 9/10 verlangen Protokoll gegen das registrierte Kommando, reale Discovery durch beide Harnesse und den negativen Zweitprojektbeleg. |

### Neue Befunde aus `review-2-codex.md`

| Befund | Urteil | Begruendung |
|---|---|---|
| P0-1 — Teilschema-Handoff | **geschlossen** | AG3-161 AC 7 verbietet Property-/Vectorizer-Erzeugung; AG3-163 AC 1/2 erzeugt das vollstaendige Story- und Concept-Schema in einem Lauf und bindet die Sollmenge per Contract-Test. Das vorgezogene leere Produktionsmodul ist dennoch unnoetig; siehe P1-5. |
| P0-2 — Feature-Flag schwaecht die Norm | **geschlossen** | E1 uebernimmt die richtige Richtung: FK-13 bleibt Pflichtnorm, `false` wird Fehler, der optionale Ast soll entfallen. Die Entscheidung selbst ist richtig; nur ihr vorgesehener Landepunkt ist falsch. |
| P0-3 — Index darf nach Installation leer bleiben | **geschlossen** | AG3-169 AC 1–4 verlangt beide real ausgefuehrten Full-Syncs, Receipt, harte Fehler und anschliessende Suche ueber beide Quellarten ohne manuellen Aufruf. Closure- und Post-Commit-Produzenten sind in AC 7/8 ebenfalls als ausgefuehrte Trigger gebunden. |
| P1-1 — Retrieval durch Test-Doubles ersetzbar | **geschlossen** | AG3-167 AC 9/10 macht den echten Weaviate-/Vectorizer-Lauf nicht ueberspringbar und verlangt den expliziten Beleg, dass kein Client-Double aktiv ist. AG3-169 verwendet dieselbe echte Fixture fuer den Installerpfad. |
| P1-2 — Goldkorpus nachtraeglich optimierbar | **teilweise** | AG3-166 liegt zeitlich vor AG3-167 und definiert die richtigen Orakelfelder. Konkrete Queries, `k` und Schwellen sind vor Implementierungsbeginn aber noch nicht fixiert oder unabhaengig bestaetigt; Versionsanhebung verhindert keine opportunistische Erstwahl. Siehe P1-1. |
| P1-3 — geteilte CP10-Ownership / zu schwacher Check | **geschlossen** | AG3-164 ist alleiniger Owner; AC 4–6 prueft fehlendes Kommando, Prozess-Tod, Protokollfehler, echten `initialize`-/`tools/list`-Positivpfad und Teardown. AG3-168 konsumiert den Check explizit. |
| P1-4 — AG3-162/163 zu gross | **geschlossen** | Der Zehn-Story-Schnitt trennt Ingest-Kern, Schema/Story-Ingest, Corpus-Build, Concept-Sync, MCP, Registrierung, Producer und Skill. AG3-166 bleibt am oberen L-Rand, ist nach Schliessung seines Algorithmusvertrags aber noch als L vertretbar. |
| P1-5 — `ProjectBinding` zu stark | **geschlossen** | AG3-161 Scope 2 und AC 3/4 reduzieren auf Root, Containment, `cwd`, bestehenden `project_id`-Vertrag und Endpunkt; die neue globale Identitaetsordnung ist ausdruecklich ausgeschlossen. |
| P1-6 — Normanteile beim Split verloren | **geschlossen** | AG3-163 bindet die vier Quellenrollen, ihre Producer, Trigger und Delete-Semantik in Matrix und AC 7–10. Die Herkunftsmatrix ist stichprobenartig gegen FK-13 und die vier Alt-Scope-Gruppen konsistent; ein Scope-/AC-Verlust ist nicht erkennbar. Die konkrete Research-Discovery ist jedoch zu breit; siehe P1-4. |
| P2-1 — Reverse-/Direktkanten ungenau | **teilweise** | Die entscheidenden Join-Kanten 166 ← {163,165} und 168 ← {164,167} sind korrekt. AG3-169 und 170 nennen dagegen bewusst nur transitive Vorlaeufer, obwohl SPLIT E11 direkte Producer-/Consumer-Kanten verspricht; ausserdem fehlt die sicherheitskritische Aktivierungskante. Siehe P0-1 und P2-1. |

## Neue Findings

### P0-1 — AG3-161 ist nicht eigenstaendig landbar; der benannte Uebergang verbreitert den Phantomeintrag auf alle Installationen

**Ort:** AG3-161 Kontext „Bewusster Uebergangszustand“ und Scope 1, insbesondere AC 1/2/9; `status.yaml depends_on: []`; AG3-164 Scope 2; AG3-167 Scope 1; SPLIT.md §1.

Der Hinweis dokumentiert Debt, terminiert ihn aber nicht innerhalb der Story. Nach AG3-161 laeuft CP10 unbedingt und registriert ein nicht existierendes Modul. Landet 161 vor 164, meldet jede Installation weiterhin Erfolg mit Phantomeintrag; landet 164 vorher, scheitert danach jede Installation ehrlich, aber global, bis AG3-167/168 landet. Beides verletzt die geforderte eigenstaendige Abschliessbarkeit und die ZERO-DEBT-Regel. AC 9 verlangt gerade nur die Dokumentation des Defekts und macht ihn damit formal gruen.

Eine blosse Kante `AG3-161 depends_on: [AG3-164]` reicht nicht: Sie beseitigt das falsche Gruen, erzeugt aber den flaechendeckenden Installationsausfall. Die richtige atomare Schnittkante ist die **Aktivierung**. `features.vectordb=false`-Fehler, Entfall von `branch_vectordb_enabled` und unbedingtes CP10 muessen in AG3-168 (oder eine eigene abschliessende Activation-Story) verschoben werden, die direkt von AG3-164 und AG3-167 abhaengt und Server, Conformance und beide Registrierungen im selben landbaren Stand besitzt. AG3-161 darf vorher Packaging, minimales Binding und Vertragsvorbereitung liefern, den optionalen Ast aber noch nicht entfernen. AC 9 ist durch ein Negativ-/Positiv-E2E der atomaren Aktivierung zu ersetzen.

### P0-2 — Der Shadow-Replace ist weder algorithmisch entschieden noch mit dem geforderten Sichtbarkeitsvertrag testbar

**Ort:** AG3-166 Scope 2 und AC 4; FK-13 §13.9.9 Zeilen 624–627.

„Neue Chunks schreiben, validieren, alte loeschen“ ist fuer sich nicht atomar: Neue Chunks sind vor der Loeschung sichtbar; bei Wiederverwendung deterministischer UUIDs entsteht waehrend des Schreibens ein alter/neuer Mischstand. AG3-166 nennt eine Generationsmarkierung nur als Beispiel und ueberlaesst damit die zentrale Persistenz- und Lesersemantik dem Umsetzungsagenten. Die drei Crashpunkte pruefen nur den Zustand nach einem Abbruch, nicht einen konkurrierenden Leser waehrend Write, Aktivierung und Garbage Collection. Ein Fake-/Test-Port kann das leicht gruener erscheinen lassen als Weaviate es garantiert.

Vor Start von AG3-166 muss der Vertrag festlegen: immutable `generation_id` je Dokumentversion; vollstaendiges Staging und Digest-/Sollmengenvalidierung; einen einzelnen CAS-faehigen Active-Generation-Anker je (`project_id`, `source_file`); Suchabfragen, die genau die am Anfragebeginn gebundene Generation lesen; Retention/GC der Vorgaengergeneration mit Retry-Regel; Tombstone-Verfahren fuer geloeschte Quellen. AC 4 muss zusaetzlich reale konkurrierende Leser an jeder Umschaltphase, verlorenes CAS, Crash-Recovery und spaeteres GC gegen echte Weaviate-Infrastruktur pruefen. Falls Weaviate den benoetigten CAS-/Konsistenzvertrag nicht bietet, ist „atomar“ normativ zu korrigieren statt im Code zu simulieren.

### P0-3 — Die Codex-Registrierung kann mit Defaults gruen werden, ohne produktiv an Projekt und Endpoint gebunden zu sein

**Ort:** AG3-168 Scope 2 und AC 1/6/9/10 gegen Scope 1; AG3-161 Scope 2; FK-13 §13.4.3.

Fuer Claude Code verlangt die Story `PROJECT_ID` und Weaviate-Endpunkt in `env`; fuer Codex nennt sie nur `command`, `args`, `cwd`. Die aktuelle offizielle Codex-Konfiguration unterstuetzt projektlokale `.codex/config.toml`, `env`, `cwd` und `required`; ein Pflichtserver kann mit `required=true` den Codex-Start bei fehlgeschlagener Initialisierung blockieren. Ohne einen identischen Projekt-/Endpoint-Vertrag kann der Test auf `localhost:9903` bestehen, waehrend ein Zielprojekt mit abweichendem Endpoint gegen die falsche Collection/Instanz laeuft; ohne `required=true` kann Codex trotz nicht initialisiertem Pflichtserver weiterlaufen. Quelle: [OpenAI Codex MCP-Dokumentation](https://developers.openai.com/codex/mcp/).

FK-76 und AG3-168 muessen fuer Codex mindestens `[mcp_servers.story-knowledge-base]` mit `command`, `args`, `cwd`, `env` (`PROJECT_ID` und vollstaendige Endpunktwerte) sowie `required = true` festlegen. AC brauchen einen Nicht-Default-Endpoint, zwei verschiedene `project_id`s und den Negativfall „Server initialisiert nicht ⇒ Codex-Start/Resume scheitert“, jeweils ueber die reale Codex-CLI. Falls der Server Werte stattdessen autoritativ aus `cwd`/Projektconfig liest, muss **dieser eine** Mechanismus fuer beide Harnesse normiert werden; zwei implizite Quellen sind unzulaessig.

### P1-1 — Das Orakel ist nur vor die Messstory verschoben, nicht vor opportunistische Erstwahl geschuetzt

**Ort:** AG3-166 Kontext E6, Scope 5 und AC 8/9; SPLIT E6.

Der Umsetzungsagent der AG3-166 darf den Goldkorpus, die Queries, `k`, `min_recall` und `max_rank` erstmals selbst festlegen. `oracle_version` schuetzt nur spaetere Aenderungen; Version 1 kann bereits trivial sein. „Reviewpflichtig gekennzeichnet“ und „Reviewbeleg“ bestimmen weder einen unabhaengigen Principal noch ein Gate vor AG3-167.

Die konkrete Oracle-v1-Datei oder mindestens ihre vollstaendige Wertetabelle muss vor Implementierungsstart als reviewtes Input-Artefakt vorliegen. AC 8 soll einen gebundenen Digest sowie die Freigabe durch einen vom Implementierer verschiedenen Reviewer verlangen; AG3-166 materialisiert/validiert sie, waehlt sie aber nicht. Aenderungen brauchen Version **und** erneute unabhaengige Freigabe. Damit wird E6 wirklich zum fixierten Orakel statt nur zu einer Dateiform.

### P1-2 — „Dependency des Laufzeitprofils“ erlaubt weiterhin ein optionales Extra

**Ort:** AG3-161 Scope 3 und AC 5; `pyproject.toml` `[project.dependencies]`/`[project.optional-dependencies]`.

AK3 besitzt derzeit eine Basisinstallation und ein optionales `weaviate`-Extra. Die Formulierung „echte Dependencies des Profils, in dem der Server laufen soll“ legt weder den konkreten Owner noch den produktiven Installationsbefehl fest. Ein Agent kann ein neues Extra anlegen, den Clean-Venv-Test mit `.[vectordb]` gruen machen und die normale Installation weiterhin ohne `mcp`/`weaviate-client` ausliefern.

AG3-161 muss festlegen, ob beide Pakete in `[project.dependencies]` liegen oder welcher bereits produktiv vom Installer installierte Profilvertrag sie garantiert. Der Clean-Venv-Test muss exakt denselben Installationsweg wie ein Zielprojekt verwenden und danach das registrierte Serverkommando bis `initialize`/`tools/list` starten; ein eigens nur fuer den Test installiertes Extra ist kein Beleg.

### P1-3 — AG3-162 delegiert die Tokenzaehl- und Overflow-Semantik trotz FK-13 an den Implementierer

**Ort:** AG3-162 Scope 1/2/3 und AC 3/6; FK-13 §13.3.3 und §13.9.4.

Scope 2 laesst als Parametrisierungsachse ausdruecklich „Einheit: Zeichen oder Tokens“ offen, waehrend `fk13_concept` und `fk13_story` sowie FK-13 etwa 1.000 **Tokens** verlangen. Ebenfalls offen bleiben Tokenizer/Modellbindung und was mit einem langen Abschnitt ausser dem Befund passiert. Damit kann ein zeichenbasierter Kern formal als konfigurierbar gelten und dennoch die FK-13-Profile falsch schneiden.

Fuer beide FK-13-Profile sind Token als Einheit, ein deterministischer zum Embedding-Modell gebundener Tokenizer und die exakte Grenzregel vorzugeben. `E-CHUNK-001` muss festlegen, ob der Chunk verworfen, der gesamte Lauf blockiert oder deterministisch unterhalb der Heading-Ebene geteilt wird; diese Policy darf AG3-165 nicht erst indirekt erraten. Nur das `ak3_tool`-Profil darf seinen 12.000-Zeichen-Vertrag behalten.

### P1-4 — Die Research-Discovery klassifiziert jedes fremde Markdown im Story-Ordner als Research

**Ort:** AG3-163 Source-Type/Producer-Matrix, Zeile „Research-Artefakte in `stories/*/`“; AC 7/8.

„Nicht-`story.md`-Markdown“ umfasst auch Review-, Closure-, Audit- und sonstige Betriebsdokumente. Das ist keine belastbare Producer-Definition fuer „Research-Ergebnisse“ aus FK-13 und kann Retrieval mit nicht autoritativen oder sensiblen Arbeitsartefakten kontaminieren. Die Tests fordern nur irgendein Research-Markdown und koennen mit einem handverlesenen Fixture gruen werden.

Die Matrix braucht eine positive, producergebundene Erkennung (kanonischer Pfad/Dateiname oder typisiertes Frontmatter) statt eines negativen Restfilters. AC 8 muss neben einem Positivfall mindestens `review*.md`, Closure-/Audit-Dokumente und unbekannte Markdown-Dateien als Negativfaelle pruefen. `story_list_sources` darf nur tatsaechlich zugelassene Produzenten ausweisen.

### P1-5 — AG3-161 plant ein Produktionsmodul ohne produktives Verhalten

**Ort:** AG3-161 Scope 5, Betroffene Dateien `src/agentkit/backend/vectordb/schema.py`, AC 7.

Ein neues `schema.py`, das weder Properties noch Vectorizer noch Collection-Erzeugung enthalten darf, ist ein Platzhalter im Produktionscode. Ein „Idempotenzvertrag“ ohne Operation kann nicht getestet werden und wird in AG3-163 unmittelbar wieder geoeffnet. Das widerspricht der behaupteten eigenstaendigen Abschliessbarkeit, auch wenn es noch kein Teilschema in Weaviate erzeugt.

AG3-161 soll Modulort, Owner und Aufrufpunkt nur im Decision Record/Technikkonzept festlegen. Die reale Datei samt vollstaendiger Operation entsteht einmal in AG3-163. Alternativ muss 161 eine bereits nutzbare, schemaunabhaengige Port-Schnittstelle mit eigenem Verbraucher liefern; ein leeres Owner-Shell-Modul ist nicht zulässig.

### P1-6 — Die Endabnahme erzwingt noch keinen einzigen komponierten Install→Harness→Retrieval-Lauf

**Ort:** AG3-170 Scope 5 und AC 9; AG3-168 Scope 7; AG3-169 AC 1.

Die Einzelbelege sind stark, koennen aber weiterhin in getrennten Fixtures erbracht werden: 168 beweist Discovery, 169 Erstindex, 170 „relevante Passagen“. AC 9 sagt nicht explizit, dass ein frisch installiertes Zielprojekt ueber das **registrierte Kommando** in jeder realen Harness-CLI ohne manuellen Sync genau die Orakel-IDs aus Story und Konzept liefert. Ein Agent kann daher drei grüne Teiltests ohne funktionsfaehige Komposition vorlegen.

AG3-170 AC 9 sollte je Harness einen durchgehenden Lauf verlangen: sauberes Zielprojekt + isolierter Userspace → produktiver Installationsbefehl → CP10/CP10a → Harness-Neustart/Neustartsimulation → reale Harness-Discovery → Toolcall ueber das registrierte Kommando → gebundene Orakel-Treffer beider Quellarten; danach derselbe Lauf aus einem Fremdprojekt negativ. Keine direkte Backend-/Adapterabfrage darf den Harness-Schritt ersetzen.

### P2-1 — `depends_on` ist nicht durchgaengig die versprochene direkte Producer-/Consumer-Sicht

**Ort:** SPLIT.md §1/E11; AG3-169 und AG3-170 `status.yaml`/Header.

AG3-169 konsumiert direkt `story_sync` (163), Validator/Build/Hook (165), `concept_sync`/Freshness (166) und Registrierung (168), listet aber nur 168. AG3-170 konsumiert direkt Freshness (166), Tools (167), Harness-Bindung (168) und Producer (169), listet aber nur 169. Die lineare Ausfuehrung funktioniert transitiv, die behauptete direkte Kantensemantik jedoch nicht.

Entweder E11 auf „minimale Release-Gates; transitive Kanten werden nicht wiederholt“ korrigieren oder die direkten Kanten vollstaendig fuehren. Fuer Impact- und Owner-Analyse ist die zweite Variante konsistenter mit SPLIT.md. Die Aktivierungsabhängigkeit aus P0-1 ist davon unabhaengig und zwingend.

## Verlustpruefung

Die Herkunftsmatrix wurde gegen die beiden Reviews, die Scope-/AC-Gruppen der vier Vorgaenger und FK-13 stichprobenartig geprueft. Vollschema, Story-/Research-Ingest, kompletter Concept-Validator, Build-Artefakte, Resolver, Shadow-Replace, Freshness, alle fuenf Tools, drei Suchmodi, Dual-Harness-Registrierung, Erstindex, laufende Trigger und Skill-Lifecycle haben jeweils eine neue Heimat und ueberwiegend ein erzwingendes AC. **Ein kompletter Alt-Scope-Punkt oder ein komplettes Alt-AC ist nicht verlorengegangen.**

Die Matrix ueberschaetzt an vier Stellen den materiellen Abschluss: Shadow-Replace (P0-2), Oracle-Fixierung (P1-1), Codex-Laufzeitbindung (P0-3) und der atomare Aktivierungszeitpunkt (P0-1). Das sind keine Matrix-Zeilenverluste, sondern unvollstaendige Vertraege innerhalb der angegebenen Heimat.

## Groessen- und Schnitturteil

| Story | Urteil |
|---|---|
| AG3-161 = M | Nach Herausnahme der Aktivierung und des leeren `schema.py` eher **M**, plausibel. Im jetzigen Scope wegen normativer Migration plus riskantem Installer-Rollout nicht eigenstaendig landbar. |
| AG3-162 = M | **M plausibel**, sobald Token-/Overflow-Semantik feststeht. |
| AG3-163 = L | **L plausibel**, am oberen Rand; Schema und Story-/Research-Schreibpfad bilden noch einen kohärenten vertikalen Schnitt. |
| AG3-164 = M | **M plausibel** fuer echten Prozess-/MCP-Conformance-Check samt CP10-Integration. |
| AG3-165 = L | **L plausibel**, gross, aber als deterministischer Validate-/Build-/Hook-Strang kohärent. |
| AG3-166 = L | **derzeit groesser als L**, weil Sync, ungelöster atomarer Aktivierungsalgorithmus, Resolver, Freshness und Oracle zusammenkommen. Nach Vorentscheidung des Shadow-Protokolls sollte mindestens Oracle-Erstellung/Freigabe als Input vorgezogen werden; dann ist L vertretbar. |
| AG3-167 = L | **L plausibel**, hoher Infrastrukturanteil, aber eine geschlossene MCP-/Retrieval-Vertikale. |
| AG3-168 = M | **M plausibel**, nach Ergaenzung des Codex-`env`-/`required`-Vertrags; hier ist der richtige Ort fuer die atomare Pflichtaktivierung. |
| AG3-169 = M | **M plausibel**. |
| AG3-170 = M | **M plausibel**, wenn der komponierte E2E explizit wird. |

Die Uebergaenge 162→163, {163,165}→166, 166→167, 167→168, 168→169 und 169→170 sind fachlich sinnvoll. Spaetere Stories erweitern teilweise dieselben Hook-/Installerdateien, reissen aber die vorherigen fachlichen Vertraege nicht zwingend auf. Die Ausnahme ist 161→164/167/168: Dort wird ein noch nicht erfuellbarer Pflichtpfad vorgezogen und der Zwischenstand ist weder funktionsfaehig noch korrekt fail-closed ohne globalen Ausfall.

## Gesamturteil

**Rework.** Der Zehn-Story-Schnitt ist substanziell besser, die Herkunftsmatrix ist im Kern ehrlich und die meisten Review-2-Befunde sind materiell geschlossen. Noch nicht akzeptabel sind jedoch der bewusst landbare CP10-Phantom-/Ausfallzustand, der unentschiedene Shadow-Replace-Vertrag und die unvollstaendige Codex-Laufzeitbindung. Dazu bleiben mehrere gezielte Falsch-Gruen-Pfade bei Oracle, Packaging und Endabnahme.

**Darf ein Umsetzungsagent jetzt auf die erste Story losgelassen werden? Ja — aber ausschließlich auf AG3-164.** AG3-164 ist unabhaengig, reproduziert einen realen Defekt und verbessert das System fail-closed, ohne den VektorDB-Pflichtpfad zu verbreitern. **AG3-161 darf trotz `status: ready` nicht gestartet werden.** Vor seinem Start muss mindestens P0-1 umgesetzt und sein Status/dependency-Schnitt korrigiert werden; sinnvoll ist, die eigentliche Pflichtaktivierung nach AG3-168 zu verlagern.
