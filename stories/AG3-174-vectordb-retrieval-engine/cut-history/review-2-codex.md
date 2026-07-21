# Review 2 zu AG3-161 bis AG3-164

## Auflösung der Ursprungsbefunde

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — widersprüchlicher Tool-/Normvertrag | **teilweise** | Der von mir beanstandete Ausschluss von `project_id` ist durch die PO-Klarstellung gegenstandslos und korrekt entfernt. Der Feature-Flag-Konflikt wird in AG3-161 zwar adressiert, aber in der vorgeschlagenen Richtung nicht konsistent aufgelöst: FK-13 würde optionalisiert, während FK-21 §21.4.3/§21.11.4 die VektorDB weiter absolut als Pflicht führt. Ebenfalls offen bleiben die im Befund genannten FK-13-Drifts `story_sync` versus `concept_sync` für Konzeptquellen sowie CP9/9a versus FK-50 CP10/10a. |
| P0-2 — Story-Index nur Transportprototyp | **teilweise** | AG3-162 erfasst Felder, deterministische Identität, Hashing, Projektfilter, Delete, Re-Sync und Full-Reindex materiell. Noch nicht geschlossen ist der produktive Wirksamkeitsbeleg gegen eine echte Weaviate-Instanz; „echter Adapter“ kann weiterhin mit einem Fake-Client-Port getestet werden. Außerdem fehlt die zwingende Erstindizierung im Installer. |
| P0-3 — fehlender Concept-Corpus-Lifecycle | **teilweise** | AG3-162 nimmt Validator, Build-Artefakte, `corpus_revision`, Resolver, Shadow-Replace, Hooks, Freshness, Pfadkonfiguration, Excludes und Archivierung in Scope. Die AC erzwingen aber weder den vollständigen Finding-/Exit-Code-Katalog aus §13.9.7 noch die tatsächliche Installation und Ausführung der Pre-/Post-Commit-Trigger; auch die Crash-Konsistenz des behauptet „atomaren“ Mehrchunk-Replaces ist noch kein implementierbarer Vertrag. |
| P0-4 — Projektisolation/Binding | **geschlossen** | Die PO-Klarstellung korrigiert die ursprüngliche Prämisse: gefordert ist projektlokale Registrierung, nicht eine neue physische Collection oder das Verbot des FK-13-Parameters. Gemeinsame `StoryContext`-Collection plus `project_id` ist zulässig. Der jetzt zusätzlich entworfene starke `ProjectBinding` ist allerdings neue, nicht erforderliche Komplexität; siehe P1-5 unten. |
| P0-5 — Runtime-Stack und produktiver Installationsnachweis | **teilweise** | Externe Bereitstellung der Datenbank ist nach PO-Klarstellung korrekt; Compose gehört nicht ins Bundle. Packaging und Endpoint-Preflight sind in AG3-161 materiell erfasst, der MCP-Protokollnachweis in AG3-163. Offen bleiben der widersprüchliche Schema-Handoff 161→162 und ein verpflichtender E2E-Lauf gegen echte Weaviate-/Embedding-Infrastruktur. |
| P1-1 — Codex-Vertrag/Owner/Trust | **geschlossen** | AG3-163 legt FK-76-Ergänzung, TOML-Shape, einen Harness-Writer, CP10-Orchestrierung, semantischen Merge, Trust-Blocker und isoliertes `CODEX_HOME` fest. Das ist materiell. |
| P1-2 — zu großer Scope und ARE-Fremdkörper | **teilweise** | Der ARE-Defekt ist sauber separiert und die Hauptkette ist fachlich sinnvoll. AG3-162 und AG3-163 bleiben jedoch jeweils deutlich größer als ein realistisches L; zudem überschneiden sich AG3-163 und AG3-164 beim CP10-Startbarkeits-Owner. |
| P1-3 — Discovery-/Chunking-SSOT | **offen** | AG3-162 erkennt das Problem, delegiert die Architekturentscheidung aber weiterhin an den Umsetzungsagenten: gemeinsamer Kern **oder** normierte Disjunktheit. Das ist keine Auflösung vor Implementierungsstart. |
| P1-4 — semantisches Falsch-Grün | **teilweise** | Ergebnis-/Fehlerverträge und Goldkorpus sind vorhanden. Die Qualitätsziele werden aber erst während AG3-163 „festgelegt“; damit kann der Implementierer `k` und Schwellen nach dem beobachteten Ergebnis wählen. Ohne vorab fixierte Orakel und echten Embedding-Stack bleibt falsches Grün möglich. |
| P1-5 — vollständiger FK-43-Lifecycle | **geschlossen** | AG3-163 nennt immutable Bundle, Manifest-Digest, Profilselektion, beide Links, Binding-/Upgrade-Record, Alt-Pins, Verify und Harness-Neustart vollständig. |
| P2-1 — Drei-Belege-Abnahme | **geschlossen** | AG3-163 fordert getrennt MCP-Handshake/Toolcall, Discovery durch beide realen Harnesse und den zweiten Projektkontext. Das entspricht der Auflage. |

## Neue Findings

### P0-1 — AG3-161 kann kein produktives Schema ohne die AG3-162-Felddefinition anlegen

**Ort:** AG3-161 Scope 5/AC 6 (Z. 93–97, 140–142) gegenüber AG3-162 Scope 1 (Z. 60–63) und „`schema.py` erweitern“ (Z. 114).

AG3-161 soll die Collection idempotent erzeugen, erklärt aber gleichzeitig die eigentliche Felddefinition für AG3-162. Damit müsste 161 entweder ein Platzhalter-/Teilschema anlegen oder bereits Wissen aus 162 vorwegnehmen. 162 reißt denselben Owner unmittelbar wieder auf; bei Weaviate sind insbesondere Vectorizer-/Collection-Grundentscheidungen nicht beliebig nachträglich korrigierbar. Das verletzt ZERO DEBT und die verlangte eigenständige Abschließbarkeit.

**Empfehlung:** Die vollständige Schemaerzeugung einschließlich aller Story- und Concept-Properties nach AG3-162 verschieben. AG3-161 darf nur Owner, Port und Installations-Aufrufpunkt festlegen. Alternativ muss das komplette Schema bereits nach 161; dann darf 162 es nur konsumieren, nicht „erweitern“.

### P0-2 — Die Feature-Flag-Auflösung schwächt die Norm und lässt den Konflikt bestehen

**Ort:** AG3-161 Scope 1 (Z. 58–66), Out of Scope Z. 106–107; FK-13 §13.1; FK-21 §21.4.3 und §21.11.4; FK-50 CP10.

„Pflicht innerhalb eines Projekts mit aktivierter VektorDB“ ist tautologisch und macht aus einer Pflichtinfrastruktur faktisch ein frei abschaltbares Feature. Das ist keine bloße Präzisierung, sondern eine materielle Produktänderung zugunsten des heutigen Codes. FK-21 bleibt danach widersprüchlich. Der PO-Wunsch nach minimalen Konzeptänderungen spricht eher dafür, den Code an die bestehende Norm anzupassen als die Norm an den Drift.

**Empfehlung:** Bevorzugt `features.vectordb` nur noch als migrationsverträglichen/deprecated Config-Key akzeptieren, für unterstützte Zielprojekte aber `true` verlangen beziehungsweise den optionalen CP10-Ast entfernen; unerreichbarer externer Endpoint bleibt dann der harte Installationsfehler. Falls echte Projektklassen ohne VektorDB gewollt sind, müssen deren Applicability und ausgeschlossene AK3-Fähigkeiten explizit normiert und FK-21/FK-50/Skill-Verhalten gemeinsam geändert werden. Nur FK-13 zu qualifizieren ist nicht zulässig.

### P0-3 — Nach erfolgreicher Installation darf der Index weiterhin leer bleiben

**Ort:** AG3-161 AC 5–7; AG3-162 Scope/AC; AG3-163 AC 6–8; FK-50 CP10a; FK-13 §13.7.1 und §13.9.9.

Keine AC verlangt, dass CP10a nach Schemaerzeugung tatsächlich `story_sync(full_reindex=true)` und `concept_sync(full_reindex=true)` gegen den Zielkorpus ausführt und deren Erfolg prüft. Die Stories können daher Packaging, Schema, Tools und Registrierung grün melden, obwohl der Agent nach Installation keinen einzigen vorhandenen Inhalt findet. Ebenso sind der automatische Story-Closure-Sync und der Post-Commit-Concept-Sync nur teilweise beziehungsweise nur im Scope-Text erwähnt, nicht als ausgeführte Trigger abgenommen.

**Empfehlung:** AG3-162 muss CP10a und die laufenden Producer besitzen: Erstindizierung mit Sync-Receipt und hartem Fehlerpfad, Story-Closure-Trigger, Concept-Build/Post-Commit-Trigger sowie Freshness-Aktualisierung. Ein Installations-E2E mit vorbefülltem Story-/Concept-Korpus muss unmittelbar danach beide Quellarten finden, ohne manuellen Sync-Aufruf.

### P1-1 — Der reale Retrieval-Pfad kann weiterhin durch Test-Doubles ersetzt werden

**Ort:** AG3-162 DoD Z. 158–159; AG3-163 Scope 4/5 und AC 8/10/13.

„Echter Adapter“, echter Dateikorpus und offizieller MCP-Client beweisen noch keine echte Weaviate-Suche: Der Adapter besitzt bewusst einen injizierbaren Client-Port. Auch Recall@k kann gegen vorpräparierte Treffer eines Doubles grün werden. Damit bliebe gerade Embedding, Schema-Vektorisierung, Filterprojektion und Hybrid/BM25/Vector-Übersetzung ungetestet.

**Empfehlung:** Einen verpflichtenden Integrationstest gegen eine echte, testseitig bereitgestellte Weaviate-Instanz mit dem in FK-13 fixierten Vectorizer/Embedding-Modell verlangen. Das ist Testinfrastruktur, kein Installer-Bundling. Derselbe Lauf muss Ingest → MCP-Handshake → `story_search` und `concept_search` abdecken. Unit-Tests am Client-Port bleiben ergänzend zulässig.

### P1-2 — Goldkorpus und Qualitätsgate sind nachträglich optimierbar

**Ort:** AG3-162 Scope 6/AC 12; AG3-163 Scope 5/AC 10.

AG3-162 definiert nur Inhaltsklassen des Goldkorpus; AG3-163 darf `k`, Queries und Erwartungen selbst festlegen. Ein Implementierer kann damit triviale Queries, großes `k` oder schwache Schwellen wählen und formal bestehen.

**Empfehlung:** Bereits in AG3-162 eine versionierte Oracle-Datei festschreiben: Query-ID, Modus, erwartete/ausgeschlossene Dokument- und Abschnitts-IDs, fixes `k`, Mindest-Recall beziehungsweise Rangobergrenze und zulässige Modell-/Versionsbindung. AG3-163 darf diese Werte nur konsumieren; Änderungen daran benötigen einen sichtbaren Review.

### P1-3 — AG3-163 und AG3-164 besitzen denselben CP10-Startbarkeitsbelang

**Ort:** AG3-163 Z. 77–85, 118 und AC 8; AG3-164 Scope 2/AC 3; jeweilige `depends_on`.

AG3-164 ownt einen generischen Startbarkeits-Check für jeden CP10-MCP-Server, AG3-163 ändert CP10 für denselben Nachweis. Ohne Kante können beide denselben Code und Vertrag unterschiedlich ausprägen; 163 würde 164 unmittelbar wieder öffnen. Zudem prüft AG3-164 bislang nur, ob ein Kommando „auflöst“. Ein vorhandenes Programm, das sofort stirbt oder kein MCP spricht, würde wieder grün.

**Empfehlung:** AG3-164 zum alleinigen Owner des generischen Checks machen und als Erfolg mindestens Prozessstart mit Timeout, MCP-`initialize` und `tools/list` verlangen; Registrierung erst nach bestandenem Check schreiben. AG3-163 hängt zusätzlich von AG3-164 ab und konsumiert den Check für den Story-Server. Mit diesem Umfang ist AG3-164 eher **M** als S. Alternativ den generischen Check vollständig nach AG3-163 verschieben und AG3-164 davon abhängig machen.

### P1-4 — AG3-162 und AG3-163 sind weiterhin zu groß für L

**Ort:** vollständiger Scope beider Stories.

AG3-162 umfasst Schema, Story-Ingest, vollständige Validierungssuite, Graph-/Index-Build, Resolver, atomaren Sync, zwei Hook-Lifecycles, Freshness, SSOT-Refactoring und Goldkorpus. AG3-163 umfasst fünf Tools, Contractmodell, drei Suchmodi, Qualitätsmessung, zwei reale Harness-Integrationen, TOML-Migration, Trust, Installer und vollständigen Skill-Upgrade-Lifecycle. Beide enthalten mehrere eigenständig risikoreiche L-Pakete.

**Empfehlung:** Weiter schneiden, ohne Inhalt zu verlieren. Mindestens: (a) StoryContext-Schema + Story-Ingest + CP10a/Closure-Produzenten, (b) Concept-Validator/Build/Graph/SSOT, (c) Concept-Sync/Resolver/Freshness/Goldkorpus, (d) MCP-Tools + Qualitätsgate, (e) Dual-Harness-/Skill-Installation. Die Kanten folgen den Producer-Consumer-Beziehungen. AG3-161 ist nach Entfernung der Schemaimplementierung als M plausibel; die heutigen Größen 162=L und 163=L sind es nicht.

### P1-5 — Der starke `ProjectBinding` überschreitet die korrigierte PO-Anforderung

**Ort:** AG3-161 Z. 28–38, Scope 2/AC 2–3; AG3-163 Scope 4(c)/AC 7.

Nach der Klarstellung verlangt der PO nur projektlokale Registrierung; FK-13s `project_id`-Trennung genügt. AG3-161 fordert trotzdem eine neue kollisionsfreie Identität, Registry-/Config-/Root-CAS-artige Kreuzprüfung und verwirft zwei Roots mit gleichem Story-Präfix. Das verändert die FK-13-Beispielbindung `{project_prefix}` und schafft eine neue Sicherheitsinvariante, die der PO ausdrücklich nicht verlangt hat.

**Empfehlung:** Auf das Minimum reduzieren: Installer erhält den autoritativen `project_root`, schreibt ausschließlich darunter `.mcp.json`/`.codex/config.toml`, setzt das projektlokale `cwd` und befüllt `project_id` nach dem bestehenden FK-13-/Projektconfig-Vertrag. Nur tatsächlich benötigte Pfadnormalisierung/Containment typisieren. Eine neue globale Identitätsordnung nur mit eigenem fachlichem Anlass und Decision Record einführen.

### P1-6 — Drei normierte Daten-/Triggeranteile sind beim Split nur noch implizit oder verloren

**Ort:** FK-13 §13.3.2 und §13.7.1 gegenüber AG3-162/163.

Research-Ergebnisse und Architektur-Dokumente aus der FK-13-Quellentabelle haben in AG3-162 keinen Ingest-Owner. Der automatische Story-Closure-Sync ist nicht als AC gebunden. Auch die widersprüchliche historische Zuordnung von Konzepten zu `story_sync` beziehungsweise `concept_sync` wird in keiner Story normativ bereinigt. Die ursprüngliche Story referenzierte §13.7 zumindest ausdrücklich am Toolscope; der neue Split darf diese Anteile nicht still verlieren.

**Empfehlung:** Vor Implementierung eine vollständige Source-Type/Producer-Matrix in AG3-162 aufnehmen (`story`, `concept`, `research`, Architektur) und für jede Quelle Discovery, Tool-Owner, Initial-/Delta-Trigger, Delete-Semantik und Tests festlegen. Die Matrix löst zugleich `story_sync` versus `concept_sync` und bindet `story_list_sources` an reale Produzenten.

### P2-1 — Reverse-Kanten sind ungenau

**Ort:** AG3-161 `unblocks: [AG3-162, AG3-163]`; AG3-163 `depends_on: [AG3-162]`.

AG3-161 entblockt AG3-163 nur transitiv; direkt ist 162 der Blocker. Nach Auflösung von P1-3 benötigt 163 außerdem die 164-Kante.

**Empfehlung:** Direkte Kanten führen: 161 → 162; 164 unabhängig startbar; 163 abhängig von 162 **und** 164. Bei weiterem Scope-Schnitt entsprechend den tatsächlichen Producer-Consumer-Kanten verfeinern.

## Größen- und Schnitturteil

- **AG3-161 = M:** nach Entfernung der vorgezogenen Schemaimplementierung und Reduktion des überstarken `ProjectBinding` plausibel; aktuell eher M/L.
- **AG3-162 = L:** nicht plausibel; mehrere L-Pakete.
- **AG3-163 = L:** nicht plausibel; mindestens Tool-/Retrieval-Kern und Harness-/Skill-Lieferung trennen.
- **AG3-164 = S:** nur für bloßes `PATH`-Checking plausibel, genau das wäre aber falsches Grün. Als echter generischer MCP-Conformance-Check eher M.

Der Grundschnitt Fundament → Storage/Corpus → Oberfläche ist fachlich richtig. Die konkrete Übergabe ist noch nicht stabil: 161 erzeugt ein von 162 zu erweiterndes Schema, 162 liefert keinen ausdrücklich installierten Erstindex, und 163/164 teilen CP10-Ownership.

## Gesamturteil

**Rework.** Die Überarbeitung ist substanziell und schließt P1-1, P1-5 und P2-1 sauber; sie ist keine bloße Umformulierung. Vor Umsetzung bleiben jedoch drei harte Falsch-Grün-Pfade: Teilschema 161→162, erfolgreiche Installation ohne Erstindex und Retrievaltests ohne echte Weaviate-/Embedding-Wirkung. Die Feature-Flag-Auflösung akzeptiere ich **nicht** in der vorliegenden Form; sie verschlechtert den Pflichtvertrag und lässt FK-21 widersprüchlich.

**Darf ein Umsetzungsagent jetzt auf AG3-161 losgelassen werden? Nein.** Zuerst müssen mindestens P0-1 und P0-2 dieses Reviews im Briefing aufgelöst werden: Schemaimplementierung sauber einer Story zuordnen und die Feature-/Applicability-Entscheidung normübergreifend korrigieren. Danach kann AG3-161 als eigenständig abschließbares Fundament starten.
