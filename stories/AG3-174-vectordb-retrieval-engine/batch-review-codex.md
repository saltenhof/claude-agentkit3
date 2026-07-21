# Batch-Review AG3-174 / AG3-175 / AG3-176

## AG3-174 — VektorDB-Retrieval-Engine

### P0-1 — Die Source-/Producer-Closure und die Loeschdomänen der beiden Sync-Tools sind nicht durch ACs erzwungen

**Ort:** `story.md:60-66`, `story.md:119-138`; FK-13 §13.3.2, §13.7.2 und §13.9.5.

Der Scope nennt zwar alle vier Quellen, AC 3 beweist aber nur eine exportierte Story. Weder Concept- noch Architektur- oder Research-Ingest, die positive Research-Erkennung noch deren Negativmenge sind abnahmeverbindlich. Schwerer wiegt: FK-13 §13.7.2 enthält noch die alte Formulierung „alle Chunks des Projekts löschen“, während die spätere und durch den Decision Record bestätigte Tool-Trennung Story/Research und Concept/Architektur verschiedenen Sync-Tools zuweist. Ein formal grüner `story_sync(full_reindex=true)` könnte daher Concept-Chunks löschen; der unmittelbar folgende `concept_sync` könnte umgekehrt Story-Chunks löschen.

**Konkrete Auflage:** AC 3/4 um eine tabellarische Source-/Producer-Closure erweitern:

- `story.md` → `source_type=story` → ausschließlich `story_sync`;
- `stories/<story-ordner>/research/**/*.md` → `research` → ausschließlich `story_sync`;
- konfigurierte Konzept- und Architekturquellen → `concept` → ausschließlich `concept_sync`;
- `review*.md`, Closure-/Audit-Artefakte und sonstiges unbekanntes Markdown sind negative Research-Fälle;
- `story_list_sources` weist nur diese zugelassenen Producer aus;
- `full_reindex` löscht jeweils nur die vom aufgerufenen Tool besessenen Source-Types innerhalb des gebundenen `project_id`.

Ein Sequenztest muss `story_sync(full_reindex=true)` und `concept_sync(full_reindex=true)` in beiden Reihenfolgen ausführen und danach beide Quellklassen unverändert vorfinden. Delete, verschwundene Quelldatei, inkrementeller Re-Sync und idempotenter Re-Sync sind je Source-Type zu prüfen.

### P0-2 — Der normierte Drei-Ringe-Corpus-Lifecycle ist beim Kollabieren der Stories teilweise verlorengegangen

**Ort:** `story.md:67-72`, `story.md:100-111`, `story.md:124-138`; AG3-176 `story.md:42-59`; FK-13 §13.9.9, insbesondere Zeilen 583-643; FK-50 CP 10b.

AG3-174 besitzt Validator und Build-Artefakte, AG3-176 nur Post-Commit-Producer und Skill. Niemand besitzt abnahmeverbindlich `concept lint --changed`/`concept lint <file>`, `concept doctor --summary`, `concept validate --staged`, den Candidate-Corpus aus staged plus unveränderten Dateien, `concept validate --corpus --strict`, `concept build`, die manuelle CLI `concept sync` oder die tatsächlich feuernde CP10b-/Pre-Commit-Installation. Der aktuelle Bestand bestätigt die Lücke: `cp10b_concept_validation_hook()` registriert nur einen Intent und erklärt das Hook-Script ausdrücklich für out of scope (`cp10.py:429-448`). Damit kann die Story grün werden, obwohl Ring 1 und Ring 2 überhaupt nicht existieren.

**Konkrete Auflage:** Ohne zusätzliche Story teilen, aber die Ownership explizit machen:

- AG3-174 liefert die produktiven CLI-/Service-Operationen für `lint`, `doctor`, `validate --staged`, `validate --corpus --strict`, `build` und `sync`, alle auf demselben Parser/Discovery-SSOT.
- AG3-176 installiert und testet Ring 2 über CP10b/Pre-Commit, Ring 3 über den vorgesehenen CI-/Post-Commit-Pfad sowie `concept build --sync`; bestehende Secret-Detection bleibt erhalten.
- ACs müssen die drei Ringe als tatsächlich ausgeführt prüfen: staged Candidate-Corpus blockiert einen neu erzeugten Cross-File-Fehler, `--strict` eskaliert Warnings, Post-Commit baut vor dem Sync und ein Fehler setzt keine Freshness.

### P0-3 — Die fail-closed Eingabegrenzen sind nur behauptet; geerbte Nachsicht kann weiterhin formal grün bleiben

**Ort:** `story.md:51-86`, `story.md:124-138`. Konkreter Bestand: `weaviate_adapter.py:98-123` ersetzt falsch typisierte `title`/`snippet` durch Leerstrings, `weaviate_adapter.py:313` ignoriert `search_mode`, und `weaviate_adapter.py:329` ersetzt einen fehlenden Score durch `0.0`.

Die Story fordert FAIL-CLOSED, benennt aber keine adversarialen Verträge für YAML-Frontmatter, MCP-Toolargumente, Tokenizer-Asset oder Weaviate-Antworten. Ein Implementierer kann `yaml.safe_load` mit Last-wins bei doppelten Keys, Pydantic-Koerzierung (`"false"`, `1`, `"10"`) und `.get(..., default)` verwenden und trotzdem alle heutigen ACs erfüllen. Genau diese Fehlerklasse hat AG3-164 mehrfach produziert.

**Konkrete Auflage:** Ein eigenes AC „strikte externe Grenzen“ mit echten Negativmatrizen ergänzen:

- Frontmatter: ungültiges UTF-8, doppelte Namen auf jeder Ebene, unbekannte YAML-Tags, nicht endliche Zahlen, Lone Surrogates, falsche Container-/Skalartypen, unzulässige Enums und übermäßige Tiefe führen zu benanntem Validierungsfehler; keine Typkoerzierung.
- MCP-Eingaben: strikte Enums/Booleans/Integer, positive begrenzte `limit`-Werte, keine bool-as-int-Koerzierung und kein fremdes `project_id`.
- Weaviate-Antworten: fehlende/falsch typisierte Pflichtfelder, NaN/Infinity-Score, fehlerhafte Pagination und unvollständige Write-/Delete-Zähler sind harte, benannte Fehler und niemals leeres Ergebnis oder Erfolg. Die derzeitigen Defaults sind zu entfernen.
- Tokenizer: Digestprüfung vor dem Parsen; beschädigtes, tief verschachteltes oder semantisch inkompatibles Asset ist ein harter Fehler ohne Netz-/Cache-Fallback.

Die Tests dürfen am externen Adapterport Fakes nutzen, müssen aber jeweils beweisen, dass kein Teil-Write, keine Freshness-Änderung und kein Success-Envelope entsteht.

### P0-4 — Prozessbindung, Projektfilter und registrierter Server-Spec bilden noch keinen geschlossenen Vertrag

**Ort:** `story.md:46-50`, `story.md:79-86`, AC 4; AG3-175 `story.md:33-43`, AC 2/4; FK-13 §13.4.1/§13.9.5 (optionales `project_id`).

Der Server wird per `PROJECT_ID`/Endpoint-Environment projektlokal gestartet, die Tools akzeptieren aber weiterhin ein optionales `project_id`. Es ist nicht festgelegt, ob `cwd`, Projektconfig, Environment oder Toolparameter autoritativ sind. Ein Server kann das korrekte Environment ignorieren, auf localhost/defaults gehen oder ein fremdes `project_id` akzeptieren; `initialize` und `tools/list` bestehen trotzdem. AC 4 auf Backend-Ebene reicht dafür nicht.

**Konkrete Auflage:** Einen einzigen typisierten `McpServerSpec`/`RuntimeBinding` als SSOT festlegen und in beiden Stories referenzieren:

- `PROJECT_ID` sowie HTTP-/gRPC-Endpunkt kommen für den MCP-Prozess ausschließlich aus dem registrierten `env`; `cwd` ist Arbeits-/Containment-Grenze, keine zweite Konfigurationsquelle.
- Fehlende, leere oder falsch typisierte Bindungswerte stoppen den Server fail-closed.
- Ein ausgelassener Tool-Parameter wird auf die gebundene Projekt-ID gesetzt; ein abweichend übergebenes `project_id` wird abgelehnt, nicht als Cross-Project-Abfrage ausgeführt. Das gilt auch für `story_list_sources`.
- AG3-174 testet den gestarteten Subprozess mit Nicht-Default-Endpunkt sowie einen Fremdprojekt-Override. AG3-175 probt exakt den anschließend geschriebenen Spec; kein getrennt konstruiertes Prüfkommando.

### P1-1 — AC 6 überverspricht Crash-Konsistenz und lässt Retry-/Nebenläufigkeitssemantik offen

**Ort:** `story.md:73-78`, `story.md:127-130`; FK-13 §13.9.9.

Der Scope bildet die PO-Entscheidung korrekt ab: kein CAS, kein Generations-Zeiger, Leser dürfen ein kurzes Übergangsfenster sehen. „Nach Abbruch mitten im Sync bleibt ein konsistenter Generationsstand“ kann jedoch wieder als atomare Crash-Garantie gelesen werden. Bei einem harten Abbruch nach dem Schreiben der neuen, aber vor dem Löschen der alten Generation sind zwei vollständige Generationen gerade der ehrliche Zustand. Zusätzlich ist nicht bestimmt, wo der Abschlussmarker liegt, wann er geschrieben wird, wie ein Retry Reste bereinigt und was zwei überlappende Writer tun.

**Konkrete Auflage:** AC 6 auf den implementierbaren Bounded-Window-Vertrag zuschneiden:

1. neue Sollgeneration vollständig schreiben und Sollmenge validieren;
2. alte/fremde Chunks derselben Source erst danach löschen;
3. erst nach erfolgreichem Delete ein digestgebundenes Sync-Receipt mit `corpus_revision` publizieren;
4. Crash davor lässt den letzten Abschlussmarker unverändert; Retry erkennt und bereinigt vollständige/partielle Reste deterministisch;
5. parallele Syncs desselben `(project_id, source_file)` werden durch einen benannten Single-Writer-Mechanismus serialisiert oder fail-closed abgewiesen.

Explizit festhalten: Ein sofortiger Single-Generation-Zustand nach Prozessabsturz ist **nicht** garantiert; Leser dürfen im normierten Fenster beide Generationen sehen. So wird weder CAS eingeschmuggelt noch falsche Atomizität behauptet.

### P1-2 — Mehrere normierte Detailverträge sind nicht abnahmeverbindlich

**Ort:** `story.md:67-72`, AC 5/7/8; FK-13 §13.9.7, §13.9.10-13.

AC 5 prüft nur Zyklen/gebrochene Authority-Kanten. Ein Implementierer kann den größten Teil des Finding-Katalogs, die fünf Authority-Ranking-Regeln, Archiv-/Appendix-Metadaten oder die besondere `.conceptignore`-Semantik auslassen. Insbesondere unterscheiden sich `research/**`, `research/**/*`, `*.md` und `drafts/*.md` normativ; ein Standard-`Path.match` erfüllt diese Semantik nicht zwingend.

**Konkrete Auflage:** Tabellengetriebene Contract-Tests ergänzen für jeden Error-/Warning-Code und Exit 0/1/2/3, alle fünf Ranking-Regeln mit deterministischem Tie-Break, Core/Appendix/Archiv, alle vier genannten Glob-Grenzfälle sowie Gleichheit der Discovery-Menge in Validate, Build und Sync. `E-CHUNK-001` bleibt blockierend, auch wenn der generische Chunker den Inhalt deterministisch in Teilchunks zerlegen kann.

### P1-3 — `story_list_sources` und der Tokenizer-Pin delegieren weiterhin Vertragsentscheidungen

**Ort:** `story.md:39-45`, `story.md:79-83`, AC 1/8; FK-13 §13.4.1 Zeilen 166-168 und §13.2.

FK-13 sagt für `story_list_sources` nur „Übersicht über Source-Types und Projekte“; AC 8 spricht trotzdem von „Rückgabefeldern“. Es gibt daher keine prüfbare Feldliste. Außerdem sind gepinnte Revision, Runtime-Bibliothek, Asset-Dateien und Lizenz im neuen normativen Record nicht konkret benannt. Der alte Schnitt hatte `tokenizers==0.21.0`, Revision `e4ce9877abf3edfe10b0d82785e83bdcb973e22e`, Asset/Vokabular und Apache-2.0 bereits festgelegt; beim Kollabieren ist diese Festlegung verloren gegangen.

**Konkrete Auflage:** Vor Implementierungsstart normativ oder im PO-gebundenen Briefing festschreiben:

- minimale `story_list_sources`-Shape (mindestens gebundenes `project_id`, `source_type`, Producer/Tool, Source-/Chunk-Zähler und letzte erfolgreiche Revision/Freshness; keine fremden Projekte);
- exakte Modell-/Tokenizer-Revision, Bibliotheksversion, Asset-Liste, Digest-Datei und Lizenznachweis;
- `weaviate-client>=4.9,<5.0` als FK-13-konformer Runtime-Pin statt des heutigen optionalen `>=4.0`-Extras.

### P1-4 — Der vorgeschlagene SSOT-Modulort widerspricht dem normierten Parser-Owner

**Ort:** `story.md:51-56`, `story.md:103-110`; FK-13 §13.9.13 Zeilen 755-758.

FK-13 legt `discover_concept_files()` im Parser-Modul `agentkit/concepts/parser.py` als zentralen Owner für Validation, Build, Graph und Sync fest. Die Story legt denselben Owner unter `backend/vectordb/ingest/` an. Das ist kein bloßes Dateinamendetail: Der Corpus-Parser ist fachlich nicht vom VektorDB-Backend abhängig und muss auch für Lint/Validate ohne Weaviate nutzbar sein.

**Konkrete Auflage:** Den generischen Corpus-/Discovery-Kern unter einem transportfreien Domain-Paket wie `src/agentkit/concepts/` ansiedeln; `backend/vectordb/ingest` und `tools/concept_ingester` werden Adapter/Konsumenten. Alternativ muss FK-13 vorab bewusst auf den neuen Owner geändert werden. Keinen zweiten Parser anlegen.

### P2-1 — Größe L ist nur als Backlog-Klammer vertretbar

**Ort:** `status.yaml:8`, gesamte Scope-Liste.

AG3-174 vereinigt Packaging, Tokenizer, Projektbindung, drei Ingest-Profile, Vollschema, vier Producer, Validator/CLI/Build/Graph, Sync-Lifecycle, Resolver und eine komplette MCP-Oberfläche. Das ist trotz ausgelagerter Konzeptarbeit und E2E faktisch XL und deutlich größer als die früher einzeln als M/L bewerteten Vertikalen.

**Konkrete Auflage:** Der PO-Schnitt kann bestehen bleiben, aber vor `in_progress` braucht die Story einen verbindlichen internen Implementierungsplan mit den oben genannten Teilvertikalen, je Teilvertikale eigenem Modul- und Testbudget sowie einem Integrationsgate vor MCP. „L“ darf nicht als Planungsannahme für einen kurzen Lauf verwendet werden; kein God-File und keine bis zum Ende aufgeschobene Integration.

## AG3-175 — Dual-Harness-Registrierung

### P0-1 — Conformance-Prüfung und geschriebene Registrierung sind nicht digest-/wertgleich gebunden

**Ort:** `story.md:33-44`, AC 2/4.

„Check bestanden“ beweist nur dann die spätere Registrierung, wenn der Check genau denselben vollständig gerenderten `command`/`args`/`cwd`/`env`-Spec startet, der anschließend in beide Dateien geschrieben wird. Die Story erlaubt derzeit getrennte Konstruktion: Ein harmloses Prüfkommando kann bestehen, während ein anderer oder unvollständiger Eintrag persistiert wird. Ebenso beweist feldweise Gleichheit der zwei Dateien nicht, dass AG3-174 diese Werte konsumiert.

**Konkrete Auflage:** Den in AG3-174 geforderten unveränderlichen `McpServerSpec` einmal rendern, strikt validieren, mit AG3-164 probieren und genau dieses Objekt ohne erneute Ableitung in beide Harness-Formate projizieren. Ein Contract-Test verändert nach der Probe ein Feld und muss den Write verhindern. Nicht-Default-Endpunkte, leerer/falscher `cwd`, fehlende Environment-Felder und abweichende `PROJECT_ID` gehören in die Negativmatrix.

### P1-1 — „Kein Teil-Schreiben“ behauptet eine nicht definierte Zwei-Dateien-Transaktion

**Ort:** `story.md:42-44`, AC 4/5.

Für `.mcp.json` und `.codex/config.toml` gibt es keine gemeinsame atomare Dateisystemtransaktion. Die heute absolute Formulierung ist bei Prozessabsturz zwischen beiden Replaces nicht haltbar und lädt zu einer Scheinsicherung ein.

**Konkrete Auflage:** Vertrag ehrlich begrenzen: Beide Bestandsdateien werden vor dem ersten Write strikt gelesen, konfliktgeprüft und vollständig gerendert; Conformance oder ein Parse-/Konfliktfehler bewirkt **null Writes**. Jeder Einzelwrite ist atomar. Bei I/O-Fehler nach dem ersten Write wird best-effort aus gebundener Before-Image zurückgerollt und ein benannter `registration_incomplete`-Fehler geliefert; ein Wiederholungslauf konvergiert idempotent. Das unvermeidbare Crashfenster zwischen zwei Dateien wird dokumentiert, nicht als Atomizität verkauft.

### P1-2 — Der neue TOML-Rand braucht eine explizite Striktheits- und Erhaltungs-Matrix

**Ort:** `story.md:36-41`, AC 1/5; FK-76 §76.5.4.

„Unparsebar/konfligierend“ allein erzwingt nicht, dass nicht-tabellenförmiges `mcp_servers`, falsch typisierte Serverfelder, ungültiges UTF-8, Symlink-/Junction-Ausbruch oder ein fremd belegter eigener Servername vor jedem Write abgelehnt werden. Umgekehrt darf ein zu strenger Writer unbekannte fremde Tabellen/Keys nicht verwerfen.

**Konkrete Auflage:** Adversarialer Contract-Test für: ungültiges UTF-8, doppelte Tabelle/Keys, Root-/`mcp_servers`-/Server-Shape falsch, falsche Typen für `command`, `args`, `cwd`, `env`, `required`, eigener Name fremd belegt, Symlink außerhalb des Project-Roots. Alle Fälle: benannter Fehler, beide Dateien byte-identisch. Positiv: fremde Top-Level-Tabellen, fremde MCP-Server und unbekannte harness-spezifische Felder bleiben semantisch wertgleich erhalten. Benutzerpfade werden auch über Environment-/Symlink-Aliase nie beschrieben.

### P2-1 — Größe S ist für einen robusten TOML-Writer zu knapp

**Ort:** `status.yaml:8`, `story.md:36-44`.

Ein neuer semantischer TOML-Writer mit Foreign-Data-Erhalt, Konfliktklassifikation, Zwei-Dateien-Koordination und Conformance-Bindung ist keine reine Konfigurationszeile. Bei unverändertem Scope ist **M** die realistische Größe. Die Story bleibt fachlich klein und gut isoliert; die Größenkorrektur erfordert keinen weiteren Schnitt.

## AG3-176 — VektorDB-Installer-Integration

### P0-1 — Der bestehende Preflight-Baustein ist in der Installer-Verwendung fail-open für ungültige Projektkonfiguration

**Ort:** `story.md:31-36`, AC 1. Bestand: `wait_for_weaviate.py:93-125` fällt bei fehlender/ungültiger Projektconfig oder fehlendem VektorDB-Block auf localhost/default port zurück.

Die Story fordert, den bestehenden Baustein „einzuhängen“, aber kein AC verbietet dessen Default-Fallback. Ein falsch geschriebener Zielendpunkt kann deshalb unbemerkt gegen eine zufällig lokal laufende Weaviate-Instanz geprüft werden. Das ist derselbe geerbte-Nachsicht-Fehler an der Installer-Grenze.

**Konkrete Auflage:** Für den Installationspfad sind Projektconfig, explizit validierter Endpoint und erwartete Weaviate-Kompatibilität zwingend. Kein localhost-Fallback bei einer projektgebundenen Installation. Negativtests: fehlender/malformed VektorDB-Block, ungültiger Host/Port/gRPC-Port, erreichbarer Nicht-Weaviate-Dienst, nicht-ready und inkompatible Weaviate-Version; jeweils benannter harter Fehler vor Registrierung/CP10a. Nur der ausdrücklich projektlose Diagnose-CLI-Pfad darf dokumentierte Defaults behalten.

### P0-2 — Die Pflichtaktivierung ist durch den permissiven YAML-/Feature-Vertrag noch umgehbar oder mehrdeutig

**Ort:** `story.md:45-52`, AC 4. Bestand: `config/loader.py:87` nutzt `yaml.safe_load`; `Features` und `VectorDbConfig` sind nicht strikt (`models.py:73-104`, `models.py:531-549`), `features.vectordb` defaultet auf `False`.

Der Decision Record entscheidet nur explizites `false`; die Story entscheidet nicht, was ein fehlender deprecateter Schlüssel bedeutet. Mit dem heutigen Default ist „fehlt“ nicht von `false` unterscheidbar. Doppelte YAML-Namen sind Last-wins, und Pydantic kann in den verschachtelten Modellen Typen koerzieren. Damit kann der Agent entweder alte unterstützte Projekte flächendeckend ablehnen oder mehrdeutige Konfiguration akzeptieren.

**Konkrete Auflage:** Den Migrationsvertrag vor Codeänderung exakt festhalten und testen: empfohlen ist „fehlend = Pflichtinfrastruktur aktiv“, `true = akzeptierter Migrationswert`, **nur** echtes Boolean `false = benannter harter Fehler`; Strings, Zahlen, Null und doppelte `features`-/`vectordb`-/Endpoint-Keys sind `configuration_invalid`. Die YAML-Ladegrenze muss doppelte Keys, Lone Surrogates, unzulässige Tags und extreme Tiefe fail-closed behandeln. Keine Aktivierungs-, Registrierungs- oder Preflight-Wirkung vor vollständiger strikter Configvalidierung.

### P0-3 — CP10b und die normierten Hook-Ringe haben weiterhin keinen Implementierungsowner

**Ort:** `story.md:42-59`, `story.md:70-79`, AC 3/5; FK-13 §13.9.9, FK-50 CP 10b.

Dies ist die Installer-Story, aber die betroffenen Dateien und ACs erwähnen CP10b/Pre-Commit nicht. „Post-Commit-Concept-Trigger“ schließt Ring 2 nicht ein. Ohne die unter AG3-174 P0-2 geforderte Ergänzung kann die Installation Erfolg melden, obwohl die harte Corpus-Validierung beim Commit nie feuert.

**Konkrete Auflage:** CP10b als expliziten Scope-/AC-Punkt aufnehmen: materialisierter projektlokaler Pre-Commit-Dispatch, `concept validate --staged`, Candidate-Corpus, Erhalt der Secret-Detection, Idempotenz sowie REGISTER/DRY_RUN/VERIFY. Post-Commit muss `concept build` vor `concept sync` ausführen; CI/Corpus-Strict-Owner und manueller CLI-Pfad sind ebenfalls nachzuweisen.

### P1-1 — CP10a-Receipts und Producer-Zustandsübergänge sind zu schwach spezifiziert

**Ort:** `story.md:37-44`, AC 2/3.

„Receipt vorhanden“ lässt offen, ob es an Projekt, Source-Set, Zähler und Revision gebunden ist. „Trigger ausgeführt“ lässt einen Fire-and-Forget-Task zu, der sofort verloren geht oder Freshness trotz fehlgeschlagenem Sync fortschreibt.

**Konkrete Auflage:** Für beide CP10a-Syncs ein typisiertes Receipt mit `project_id`, Tool/owned source types, discovered/unchanged/upserted/deleted/failed, `empty_corpus`, Start-/Endrevision und Status. `empty_corpus=true` ist Erfolg mit Nullmengen; Transport-/Parse-/Partialfehler ist Fehler ohne Success/Freshness. Closure bleibt gemäß FK-13 nicht blockierend, muss aber den Task zuverlässig starten und Fehler beobachtbar protokollieren. Post-Commit: Build-Erfolg → Sync-Erfolg → Freshness-Advance; jeder vorherige Fehler lässt die alte Revision stehen. Retry/Idempotenz jeweils testen.

### P1-2 — Betroffene Produktionspfade und Skill-Abnahme sind unvollständig

**Ort:** `story.md:53-59`, `story.md:70-79`, AC 3/5.

Der bestehende Story-Closure-Trigger liegt in `backend/closure/`, Hook-Wiring in Installer/Governance; nur `backend/vectordb/` als Producer-Pfad zu nennen kann zu einer zweiten, unverdrahteten Implementierung führen. AC 5 prüft den Bundle-Lifecycle, aber nicht die fachlichen Hard Stops für fehlenden/stalen Graph, VektorDB-/Toolfehler oder abweichendes `concepts_dir`.

**Konkrete Auflage:** Betroffene Dateien um die existierenden Closure-/Postflight- und Hook-Owner ergänzen; dort nur Ports auf die AG3-174-Engine verdrahten. Bundle-Contract-Tests müssen beweisen: konfigurierte `concepts_dir` statt Default, `corpus_revision`-Mismatch/fehlender Graph/VektorDB-Fehler = Hard Stop, kein Grep-/Dateiscan-Fallback, und beide Harness-Bundles/Links referenzieren dieselbe immutable Version.

### P2-1 — „Atomare Pflichtaktivierung“ ist begrifflich missverständlich

**Ort:** `status.yaml:3`, `story.md:20`, `story.md:45`.

Gemeint ist eine landbare Schnittkante, nicht eine transaktionale Laufzeitoperation. Im selben Vorhaben wurde „atomar“ beim Shadow-Replace gerade bewusst entfernt.

**Konkrete Auflage:** In Titel und Text „schnittkonsistente Pflichtaktivierung“ oder „gemeinsam landende Aktivierung“ verwenden und ausdrücklich von der nicht-atomaren Bounded-Window-Semantik abgrenzen.

## Übergreifende Prüfung

### Vollständigkeit und Verlust gegenüber dem alten Schnitt

Erhalten und klar beheimatet sind Packaging, minimales ProjectBinding, gemeinsamer Ingest-Kern, Vollschema, Story-/Concept-Sync, Validator/Build/Graph, Authority-Resolver, die fünf MCP-Tools, Dual-Harness-Registrierung, Preflight, CP10a, laufende Producer, Pflichtaktivierung und Skill-Lifecycle. Die Entfernung von CAS/Generations-Zeiger ist **kein Verlust**, sondern entspricht der neuen PO-Entscheidung. Ebenso sind Goldkorpus, reale Weaviate-Retrievalqualität, reale Harness-Discovery und komponierter Install-E2E absichtlich in die nachgelagerte PO-Abnahme verschoben; ihr Fehlen ist in diesem Review kein Finding.

Materiell verloren oder nur noch im Fließtext vorhanden sind dagegen:

1. die drei Schutzringe inklusive Ring-1-/Ring-2-CLI und CP10b;
2. die vollständige Source-Type/Producer/Delete-Matrix samt Research-Negativfällen;
3. die exakte Tokenizer-Revision/Bibliotheks-/Lizenzbindung;
4. der „exakt geprüfter = exakt geschriebener = exakt konsumierter Server-Spec“-Beleg;
5. eine vollständige Abnahme der Validator-, Ranking- und `.conceptignore`-Kataloge.

FK-13 §13.5 ist kein Verlust: Der zweistufige Story-Abgleich ist im Bestand produktiv unter `backend/story_creation/vectordb_reconciliation.py` und `conflict_adjudicator.py` implementiert. Für FK-13 §13.6 (semantische Ergänzung der P6-Kontextselektion) ist dagegen weder im Bestand noch in 174-176 ein produktiver Consumer erkennbar. Das blockiert den MCP-Kern nicht, ist aber als **P1-Nachweisauflage** zu behandeln: Entweder im Paket einen bestehenden Owner samt Contract-Test referenzieren oder einen expliziten Folgeowner festhalten; nicht still als „durch MCP vorhanden“ abhaken.

### Kanten und eigenständige Abschließbarkeit

Die fachliche Reihenfolge `AG3-174 → AG3-175 → AG3-176`, zusätzlich `AG3-175 ← AG3-164`, ist richtig. Sie erzeugt keinen Phantomeintrag: 174 liefert erst einen startbaren Server, 175 registriert ihn nur nach dem bereits vorhandenen Guard, 176 entfernt den optionalen Ast erst zusammen mit echtem CP10a. Jede Story kann nach Schließung der Findings einen eigenständig sinnvollen Stand landen.

AG3-172 ist in `AG3-174/status.yaml:19-21` nur als Kommentar-Landevoraussetzung geführt. Wenn `depends_on` die einzige maschinenlesbare Sperre ist, reicht das nicht. Entweder `depends_on: [AG3-172]` setzen oder eine vom Workflow tatsächlich geprüfte Completion-/Merge-Vorbedingung in die DoD aufnehmen. Entwicklung von 174 darf parallel beginnen; landen darf sie erst nach 172.

### Schnitt- und Größenurteil

Der Dreier-Schnitt ist fachlich kohärent:

- 174 besitzt die harnessneutrale Retrieval-/Corpus-Engine,
- 175 ausschließlich die Formatprojektion und Registrierung je Harness,
- 176 Installer, Trigger, Aktivierung und Skill-Auslieferung.

Ein weiterer Backlog-Split ist nicht zwingend und würde dem PO-Ziel widersprechen. Die Größenangaben sind aber zu optimistisch: 174 ist XL als eine Klammer, 175 eher M, 176 nach vollständiger Ring-/Hook-Integration L. Für 174 ist deshalb ein interner, verbindlicher Teilplan zwingend; dies ist keine Rückkehr zu elf Stories, sondern Ausführungsdisziplin innerhalb einer Story.

### Noch delegierte Entscheidungen

Vor Übergabe an einen Umsetzungsagenten müssen folgende Punkte fest sein, nicht „sinnvoll implementiert“ werden:

- konkrete `story_list_sources`-Shape;
- autoritative MCP-Runtime-Bindung und Umgang mit fremdem `project_id`;
- Ort/Schreibzeitpunkt des abgeschlossenen Sync-Receipts bzw. `corpus_revision`-Markers, Retry und überlappende Writer;
- Semantik eines fehlenden deprecateten `features.vectordb`-Schlüssels;
- exakter Tokenizer-/Library-Pin;
- ehrliche Zwei-Dateien-Fehlersemantik der Harness-Registrierung.

## Gesamturteil

| Story | Urteil | Begründung |
|---|---|---|
| **AG3-174** | **Rework** | Der fachliche Schnitt stimmt, aber Source-/Delete-Closure, Drei-Ringe-Lifecycle, strikte Eingabegrenzen und Runtime-Bindung sind noch echte Falsch-Grün-Pfade. |
| **AG3-175** | **Rework** | Klein und richtig isoliert, aber der probierte und der persistierte Server-Spec sind nicht identisch gebunden; Zwei-Dateien- und TOML-Fehlersemantik müssen präzisiert werden. |
| **AG3-176** | **Rework** | Aktivierungskante und Reihenfolge sind richtig, doch Preflight-Fallback, permissive Configgrenze und fehlender CP10b-Owner erlauben eine formal grüne, praktisch falsche Installation. |

**Urteil zum Dreier-Schnitt:** **tragfähig, kein erneuter Grobschnitt erforderlich.** Die Stories sollten jedoch erst nach Einarbeitung der genannten P0/P1-Auflagen an Umsetzungsagenten gehen. Die Auflagen sind innerhalb der bestehenden drei Owner lösbar; sie verlangen weder die gestrichene CAS-Mechanik noch Story-E2E gegen echte Weaviate-Infrastruktur.
