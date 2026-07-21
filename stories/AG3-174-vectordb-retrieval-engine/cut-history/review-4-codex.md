# Review 4 zum Neuschnitt AG3-161 bis AG3-171

## Aufloesung der Befunde aus Review 3

| Review-3-Befund | Urteil | Begruendung |
|---|---|---|
| P0-1 — AG3-161 nicht eigenstaendig landbar / vorgezogene Aktivierung | **teilweise** | Die Aktivierung ist richtig aus AG3-161 herausgeloest und in AG3-171 an Conformance, Server und Dual-Harness-Registrierung gebunden. AG3-171 kann aber noch vor AG3-169 landen und macht damit den weiterhin leeren CP10a-Pfad unbedingt; siehe P0-1. Zudem setzt AG3-161 AC 2 den Abschluss von AG3-164 voraus, ohne ihn als Dependency zu fuehren; siehe P1-1. |
| P0-2 — Shadow-Replace unentschieden und nicht testbar | **geschlossen** | AG3-166 Scope 2 entscheidet Generation, Staging, Sollmengen-/Digestpruefung, CAS-Anker, leserseitiges Pinning, GC und Tombstone. AC 4 bindet verlorenes CAS, Crashpunkte und konkurrierende Leser an echte Weaviate-Infrastruktur; die Konfliktklausel verbietet eine simulierte Scheinsicherheit. |
| P0-3 — Codex ohne wirksame Projekt-/Endpoint-Bindung | **geschlossen** | AG3-168 AC 1/1a–1d erzwingt `env` als einzigen Uebergabeweg, Nicht-Default-Endpoint, getrennte `project_id`s, `required = true` und den realen Codex-Negativfall. FK-76 ist expliziter normativer Owner. |
| P1-1 — Orakel nicht vor opportunistischer Erstwahl geschuetzt | **teilweise** | Digest, vorgelagertes Startgate, feste Wertetabelle und unabhaengige Freigabe sind als AC vorhanden. Der benannte Owner `Council-Orchestrator` ist fuer diese Arbeit nach `CLAUDE.md` jedoch unzulaessig und der Vor-Start-Beleg ist noch zu leicht selbst zu behaupten; siehe P1-2. |
| P1-2 — Runtime-Dependencies koennen im Extra verschwinden | **geschlossen** | AG3-161 AC 5 bindet `mcp` und `weaviate-client` an `[project.dependencies]`, verbietet das Extra und prueft den produktiven Installationsweg. Dass der Protokollnachweis erst in AG3-171 erfolgt, ist ein sauberer Handoff, weil das Servermodul vorher nicht existiert. |
| P1-3 — Tokenzaehl-/Overflow-Semantik delegiert | **teilweise** | Einheit, Grenzwert, Sondertoken-Regel, Teilungsreihenfolge und Rekonstruktionsnachweis sind materiell entschieden. Nicht entschieden ist, wie der exakte Modell-Tokenizer im produktiven, gegebenenfalls offline laufenden Paket verfuegbar wird; siehe P1-3. |
| P1-4 — Research-Discovery als Restfilter | **geschlossen** | AG3-163 bindet Research positiv an `stories/<story-ordner>/research/**/*.md` und verlangt Negativfaelle fuer Review-, Closure-, Audit- und unbekannte Markdown-Dateien. |
| P1-5 — leeres `schema.py` | **geschlossen** | AG3-161 verbietet die Datei ausdruecklich; AG3-163 erzeugt Schema und Produktionsmodul erstmals vollstaendig. |
| P1-6 — keine komponierte Endabnahme | **geschlossen** | AG3-170 AC 9–11 verlangt je Harness einen durchgehenden Installations-, CP10/CP10a-, Neustart-, Discovery- und Retrieval-Lauf samt Fremdprojekt-Negativfall. Direkte Backend-Abkuerzungen sind ausgeschlossen. |
| P2-1 — direkte Producer-/Consumer-Kanten unvollstaendig | **teilweise** | Die meisten direkten Kanten sind nachgezogen. Es fehlt insbesondere AG3-169 als zwingende Aktivierungsvorbedingung von AG3-171; zudem konsumiert AG3-171 direkt den Decision Record aus AG3-161 und die reale Fixture aus AG3-166, ohne diese Kanten nach der selbst gesetzten E11-Semantik auszuweisen. |

## Neue Findings

### P0-1 — AG3-171 aktiviert CP10a vor dessen echter Implementierung

**Ort:** `AG3-171/status.yaml` und Story-Header `depends_on`; AG3-171 Scope 1, Out-of-Scope „Erstindizierungsinhalt“ und AC 3; AG3-169 Kontext sowie AC 1–4; `SPLIT.md` Linearisierung und F1/F10.

AG3-171 darf nach dem aktuellen Graphen parallel zu AG3-169 landen. Sie entfernt dann den Optionalitaetsast und fuehrt CP10a unbedingt aus, obwohl erst AG3-169 den heutigen Erfolgs-Placeholder durch beide echten Full-Syncs, Receipt und harte Fehlerbehandlung ersetzt. AG3-171 AC 3 verlangt zwar, dass CP10a „ausgefuehrt“ wird, aber weder einen nichtleeren Index noch einen Sync-Receipt oder die unmittelbar anschliessende Suche. Damit kann die atomare Aktivierung formal gruen sein, waehrend eine Neuinstallation keinen vorhandenen Story- oder Konzeptinhalt findet. Das ist exakt der bereits identifizierte Falsch-Gruen-Pfad „Index bleibt nach Installation leer“.

**Empfehlung:** AG3-171 muss direkt von AG3-169 abhaengen; AG3-169 dokumentiert entsprechend `unblocks: [AG3-170, AG3-171]`. AG3-171 AC 3 muss den produktiven CP10a-Erfolg aus AG3-169 konsumieren: beide Full-Sync-Receipts erfolgreich, danach je eine Story- und Concept-Suche ohne manuellen Sync. Die sichere Reihenfolge lautet `... -> AG3-168 -> AG3-169 -> AG3-171 -> AG3-170`.

### P1-1 — AG3-161 behauptet einen Sicherheitszustand, den seine Dependencies nicht herstellen

**Ort:** AG3-161 AC 2 und Definition of Done; `status.yaml depends_on: []`; `SPLIT.md` „Sofort startbar“ und Absatz zur vermeintlich falschen Kante auf AG3-164.

AG3-161 laesst den optionalen CP10-Ast richtigerweise unveraendert. Damit beseitigt sie aber auch den vorbestehenden Phantomeintrag bei `features.vectordb: true` nicht. AC 2 behauptet trotzdem absolut, nach der Story gebe es keinen Installationslauf mit Phantomeintrag. Das ist nur wahr, wenn AG3-164 zuvor abgeschlossen wurde. Der aktuelle Graph erzwingt das nicht. Die Begruendung in `SPLIT.md`, eine Kante auf AG3-164 erzeuge einen globalen Ausfall, galt fuer die alte AG3-161 mit Pflichtaktivierung; nach deren Auslagerung gilt sie nicht mehr.

**Empfehlung:** AG3-161 auf `depends_on: [AG3-164]` und bis zu dessen Abschluss auf `blocked` setzen. Alternativ muesste AC 2 auf die schwaechere, aber ehrliche Aussage „AG3-161 erzeugt oder verbreitert keinen neuen Phantompfad“ reduziert werden. Wegen der ausdruecklichen Null-Phantom-Zusage und des laufenden AG3-164-Fixes ist die harte Kante vorzuziehen.

### P1-2 — Das Oracle-Startgate verwendet eine nach CLAUDE.md unzulaessige Rolle

**Ort:** AG3-166 Header „Vorbedingung“, Kontext F5, Scope 5 und AC 8/9; `CLAUDE.md` Work Modes.

`CLAUDE.md` erlaubt den `Council-Orchestrator` ausschliesslich fuer Konzeptarbeit im Concept-Incubator nach DK-16/FK-78; zudem darf er in Moderationsphasen keine inhaltliche Parteiposition beziehen. Queries, `k`, Recall- und Rangschwellen eines Testorakels festzulegen ist weder Concept-Incubator-Arbeit noch neutrale Moderation. Der benannte Owner kann das Startgate daher nicht regelkonform erfuellen. Ein Approval-Feld mit lediglich einem anderen Namen verhindert ausserdem keine nachtraeglich erzeugte Scheinfreigabe.

**Empfehlung:** Als Owner den PO oder einen vom PO benannten, nicht implementierenden fachlichen Reviewer beziehungsweise regulaeren Orchestrator festlegen. Das Eingangsartefakt muss vor dem Statuswechsel auf `in_progress` versioniert vorliegen; Approval bindet Orakel-Digest, Reviewer-Identitaet und einen bereits existierenden Commit/Artefakt-Ref. Der Story-Bericht weist diese zeitliche Ordnung nach.

### P1-3 — Der modellgebundene Tokenizer hat keinen produktiven Liefervertrag

**Ort:** AG3-162 F7, Scope 1–3 und AC 3/6a; AG3-161 Packaging/AC 5; `pyproject.toml`.

AG3-162 bindet korrekt an den Tokenizer von `sentence-transformers/all-MiniLM-L6-v2`, entscheidet aber weder Laufzeitbibliothek noch Modellrevision, Asset-Bezug oder Offline-Verhalten. Im aktuellen `pyproject.toml` existiert keine entsprechende Runtime-Dependency. Ein Agent kann deshalb mit einem lokal gecachten oder nur im Dev-Profil vorhandenen Hugging-Face-Modell gruene Tests erzeugen; im installierten Zielprojekt scheitert das Chunking oder laedt unkontrolliert aus dem Netz. Modellname allein ist keine reproduzierbare Tokenizer-Identitaet.

**Empfehlung:** Vor AG3-162 festschreiben: konkrete Runtime-Bibliothek und Version, unveraenderliche Modell-/Tokenizer-Revision, Lieferweg des Tokenizer-Artefakts samt Digest und Lizenz sowie fail-closed Offline-Verhalten. Ein Clean-Venv-Test ohne Netzwerk und ohne vorbefuellten Model-Cache muss denselben Token-Contract erfuellen. Fuer die robuste Minimalvariante sollte das passende `tokenizer.json`/Vokabular als versioniertes Package-Asset geladen werden, nicht zur Laufzeit implizit aus dem Netz.

### P2-1 — Reverse-Kante von AG3-164 ist voruebergehend unvollstaendig

**Ort:** `AG3-164/status.yaml unblocks`, AG3-171 `depends_on`, `stories/README.md` §2.1.

`AG3-164.unblocks` nennt AG3-171 nicht. Da `depends_on` autoritativ und `unblocks` nur dokumentarisch ist, ist das waehrend der laufenden AG3-164-Umsetzung vertretbar und kein Ausfuehrungsblocker. Es bleibt aber ein nach `stories/README.md` meldepflichtiger Backlog-Drift und darf nach Abschluss der laufenden Story nicht dauerhaft liegenbleiben.

**Empfehlung:** Beim Abschluss-/Status-Folgecommit von AG3-164 die Reverse-Kante ergaenzen. Zusaetzlich nach der P0-Korrektur AG3-169 als Unblocker von AG3-171 dokumentieren.

## Antworten auf die vorgelegten Punkte

1. **`AG3-170 depends_on AG3-171` ist richtig.** AG3-170 ist nicht nur eine isolierte Skill-Paketierung, sondern die komponierte Endabnahme des produktiven Pflichtzustands. Ein Lauf ueber den optionalen Altast waere nicht derselbe Vertragsnachweis. Die Koppelung ist deshalb beabsichtigt und AG3-170 bleibt die letzte Story. Vorher muss allerdings AG3-171 seinerseits von AG3-169 abhaengen.
2. **Die Aufteilung des Clean-Venv-Belegs ist sauber.** AG3-161 beweist die tatsaechliche Runtime-Paketierung ueber den produktiven Installationsweg; erst AG3-171 kann das spaeter vorhandene registrierte Kommando bis `initialize`/`tools/list` pruefen. AG3-161 behauptet an dieser Stelle keine bereits funktionsfaehige MCP-Oberflaeche. Das neue Falsch-Gruen in AG3-161 liegt stattdessen in AC 2 und der fehlenden AG3-164-Kante.
3. **Der bekannte `unblocks`-Drift in AG3-164 ist temporaer vertretbar.** `depends_on` bleibt korrekt autoritativ. Unter ZERO DEBT gehoert die Reverse-Kante jedoch in den Abschluss-/Status-Folgecommit von AG3-164; „in_progress und deshalb jetzt nicht anfassen“ rechtfertigt nur den Aufschub, nicht das dauerhafte Liegenlassen.

## Verlustpruefung

Die Herkunftsmatrix wurde stichprobenartig gegen die Review-Befunde, die vier Vorgaenger-Stories und FK-13 geprueft. Vollschema, Story-/Research-Ingest, Concept-Validate/Build/Sync, Resolver und Freshness, alle fuenf Tools und Suchmodi, beide Harness-Registrierungen, Erstindex und laufende Producer sowie Skill-/Bundle-Lifecycle besitzen weiterhin eine konkrete Heimat und Akzeptanzkriterien. Ein kompletter Scope-Punkt oder ein komplettes altes AC ist nicht verlorengegangen.

Die Matrix ueberschaetzt den Abschluss weiterhin an drei Stellen: Sie nennt AG3-171 „atomar“, obwohl AG3-169 keine Vorbedingung ist; sie bezeichnet AG3-161 als sofort und eigenstaendig startbar, obwohl dessen Null-Phantom-AC AG3-164 voraussetzt; und sie behandelt den modellgebundenen Tokenizer als vollstaendig entschieden, obwohl dessen produktiver Lieferweg fehlt.

## Groessen- und Schnitturteil

| Story | Urteil |
|---|---|
| AG3-161 = M | **M plausibel.** Nach der Sicherheitskante auf AG3-164 eigenstaendig abschliessbar. |
| AG3-162 = M | **M plausibel**, sobald der Tokenizer-Liefervertrag feststeht; ohne ihn steckt noch Entwurfsarbeit im Briefing. |
| AG3-163 = L | **L plausibel**, am oberen Rand, aber ein geschlossener Schema-/Story-Ingest-Schnitt. |
| AG3-164 = M | **M plausibel** fuer echten Subprozess-/MCP-Conformance-Check und CP10-Integration. |
| AG3-165 = L | **L plausibel** als zusammenhaengender Validate-/Build-/Hook-Strang. |
| AG3-166 = L | **L am oberen Rand, aber vertretbar**, weil Shadow-Protokoll und Orakelformat vorgegeben sind. Der unzulaessige Oracle-Owner ist zu korrigieren, kein weiterer Codeschnitt noetig. |
| AG3-167 = L | **L plausibel** fuer MCP-Vertraege, reale Weaviate-Integration und Retrieval-Qualitaet. |
| AG3-168 = M | **M plausibel**; Registrierung, Merge, Trust und reale Harness-Nachweise bilden einen Schnitt. |
| AG3-169 = M | **M plausibel** fuer Erstindex, Receipts und die zwei laufenden Producer. |
| AG3-170 = M | **M plausibel** als Bundle-Lieferung plus abschliessende Kompositionsabnahme. |
| AG3-171 = M | **M plausibel** als enge Aktivierungs-/Migrationsstory, nach Aufnahme von AG3-169 als Vorbedingung. |

Die Uebergaenge 162→{163,165}→166→167→168→169 sind fachlich tragfaehig; spaetere Stories konsumieren die zuvor abgeschlossenen Vertraege. Die korrekte sicherheitskritische Schlussfolge ist `AG3-169 -> AG3-171 -> AG3-170`, nicht `{AG3-169, AG3-171} -> AG3-170`.

## Gesamturteil

**Rework.** Der Elfer-Schnitt ist fachlich weitgehend belastbar und wesentlich besser als die Vorfassungen. Die Pflichtaktivierung ist aber noch nicht atomar: Ohne die harte Kante AG3-171 ← AG3-169 kann das Paket mit erfolgreicher Installation und leerem Index formal gruen werden. Die drei P1-Punkte sind gezielte Briefingkorrekturen, kein Anlass fuer einen weiteren Grobschnitt.

**Darf jetzt ein Umsetzungsagent auf AG3-161 losgelassen werden? Nein.** AG3-164 ist bereits `in_progress`, und `stories/README.md` erlaubt nur eine gleichzeitig laufende Story. Darueber hinaus ist AG3-161s absolutes Null-Phantom-AC ohne abgeschlossene AG3-164 sachlich nicht erfuellbar. Nach Abschluss von AG3-164 und Nachziehen der Dependency/status-Kante darf AG3-161 gestartet werden. Die derzeit richtige laufende erste Story ist AG3-164.
