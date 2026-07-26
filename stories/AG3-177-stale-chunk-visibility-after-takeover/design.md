# AG3-177 — Entwurf: Sichtbarkeit veralteter Chunks nach einer Claim-Uebernahme

- **Phase:** 1 (Entwurfsentscheidung). **Kein Produktionscode, keine Tests** in
  dieser Phase — AC1. Diese Reihenfolge ist der Grund, weshalb die Story
  existiert: in AG3-174 sind drei Mechanismen gescheitert, weil sie vor der
  Entscheidung gebaut wurden.
- **Stand:** 2026-07-26, Branch `feat/ag3-177-stale-chunk-visibility`.
- **Verbindlich unveraendert (aus AG3-174 abgenommen, hier nicht aufgerollt):**
  Generationsleiter, geordneter Delete, Abschlussordnung, Legacy-Konvergenz,
  D3-Erstschreiber-Abweisung, D9-Verbot automatischen Ablaufs.
- **Alle Messwerte in diesem Dokument sind gemessen**, nicht geschaetzt; die
  Messmethode steht jeweils dabei. Was nicht messbar war (Serververhalten ohne
  laufendes Weaviate), ist ausdruecklich als *nicht gemessen* gekennzeichnet.

---

## 1. Der Rest, wie er tatsaechlich ist

### 1.1 Der Mechanismus

Der Pre-Write-Fence (`assert_claim_held`) und der Upsert sind **getrennte
Operationen**; ebenso der abschliessende paginierte Lesevorgang und die daran
gebundenen konditionalen Deletes. Ein ueberholter Halter, der zwischen diesen
Operationen wieder anlaeuft, schreibt Objekte **seiner** — niedrigeren —
Generation. Bei **geaendertem** Inhalt tragen sie andere UUIDs
(`uuid5(project|source|chunk_id)` ueber veraendertem `chunk_id`/Inhalt) und liegen
daher **neben** den aktuellen Zeilen, statt sie zu ersetzen.

### 1.2 Die Beobachtungsgrenze — beide unabgedeckten Klassen

Der erforderliche Abschluss-Delete entfernt genau, was die **Beobachtungsgrenze
seines vorangehenden paginierten Lesevorgangs** erfasst hat. Diese Grenze ist
nicht der Zeitpunkt des Loeschens. Unabgedeckt bleiben deshalb **zwei** Klassen:

1. **Nach dem Abschluss-Delete eintreffende Zeilen.** Ein endlicher Durchgang
   kann ein danach eintreffendes Schreiben strukturell nicht abfangen.
2. **Waehrend des paginierten Lesens eintreffende Zeilen, die nicht in die
   Kandidatenmenge gelangen.** Eine Paginierung ist **kein Snapshot**: landet
   eine Zeile auf einer bereits gelesenen Seite (bzw. verschiebt sie die
   Offsets), erscheint sie in keiner Seite dieses Lesevorgangs und ist damit auch
   kein Delete-Kandidat.

Klasse 2 ist die von Codex in r9 nachgeschaerfte; sie ist unabhaengig von der
Zeit *nach* dem Delete und wird von einem zweiten Durchgang genauso wenig
erfasst wie von einem ersten.

### 1.3 Eintrittsbedingung — vollstaendig und ohne Beschoenigung

Alle vier Bedingungen muessen **gleichzeitig** zutreffen:

1. ein Sync haengt oder stirbt, **ohne** seinen Claim freizugeben, **und**
2. ein Administrator uebernimmt **bewusst** (`concept sync --reclaim`; es gibt
   keinen Zeitablauf, D9), **und**
3. der ueberholte Prozess **erwacht** und fuehrt seinen Upsert aus — er kann ein
   anderer Betriebssystemprozess sein, weshalb Prozessaufsicht ausserhalb dieser
   Schicht liegt (out of scope), **und**
4. es folgt **kein** weiterer Sync dieser Quelle — denn der naechste Sync
   entfernt die Zeilen (seine Generation ist zwangslaeufig hoeher, die
   Ordnungsbedingung greift).

Zusaetzlich muss der Inhalt sich **geaendert** haben; bei identischem Inhalt
trifft der Nachzuegler dieselbe UUID und ueberschreibt inhaltsgleich.

**Wahrscheinlichkeitsaussage, ehrlich:** Bedingung 1–3 ist ein
Betriebsstoerfall, kein Normalbetrieb. Bedingung 4 ist dagegen **nicht** selten:
Konzept-Syncs laufen ereignisgetrieben (Post-Commit-Hook, Installation, manuell),
nicht periodisch — eine Quelle, die niemand mehr aendert, wird auch nicht mehr
synchronisiert. Der Zeitraum ist damit **nicht zeitlich begrenzt**: Stunden, Tage
oder nie. Genau diese Unbegrenztheit — nicht die Eintrittswahrscheinlichkeit —
ist der Grund, weshalb Codex einen endlichen Sweep als Loesung verworfen hat.

### 1.4 Auswirkung — und was ausdruecklich **nicht** betroffen ist

**Betroffen:** die Suche kann zwei widersprechende Fassungen desselben
Abschnitts liefern; `story_list_sources` zaehlt die Ueberzaehligen mit; waehrend
`corpus_revision` den neueren Stand meldet. Ein Agent koennte veralteten
Normtext als gueltig lesen — das trifft den Kernnutzen der Faehigkeit.

**Nicht betroffen** (in AG3-174 storage-seitig sichergestellt, durch Tests
belegt): kein Loeschen der Daten einer neueren Generation in beiden
Wettlauf-Reihenfolgen; keine Umkehrung der gemeldeten Freshness; keine
Verdraengung des Abschlussvermerks; kein Datenverlust. Es ist ein **Melde- und
Sichtbarkeitsproblem**, kein Integritaetsproblem.

---

## 2. Bewertung der drei Formen

### 2.1 Form (a) — Stale-Write storage-seitig verhindern

**Vorbefund: nicht verfuegbar. Bestaetigt — und in einem Punkt zu korrigieren:
die vorgeschlagene Emulation wuerde das Problem nicht einmal loesen.**

**Gemessen** (Introspektion des installierten `weaviate-client 4.22.0`):

| Operation | Parameter | Vorbedingung? |
|---|---|---|
| `data.insert` | `properties, references, uuid, vector` | nur implizit ueber die **Objekt-ID** (Duplikat schlaegt fehl) |
| `data.insert_many` | `objects` | keine |
| `data.update` | `uuid, properties, references, vector` | keine |
| `data.replace` | `uuid, properties, references, vector` | keine |
| `batch.add_object` | `properties, references, uuid, vector` | keine |
| `data.delete_many` | `where, verbose, dry_run` | **ja — die einzige konditionale Mutation** |

Textsuche ueber die Datenschicht des Clients nach `if_match`, `etag`,
`precondition`, `compare_and`, `expected`, `version`, `cas`: **0 Treffer**.
`ConsistencyLevel` (`ONE/QUORUM/ALL`) betrifft Replikationsquorum, nicht
Konditionalitaet. `with_tenant` partitioniert Mandanten (ein Shard je Mandant),
ist kein Praedikat und waere als „eine Generation = ein Mandant" unbegrenztes
Mandantenwachstum bei gleichzeitig unveraendertem Bedarf an einem
quellenweisen Autoritaets-Lookup — also Form (b) mit zusaetzlicher
Shard-Verwaltung.

**Korrektur am Vorbefund.** Die Begruendung „generationsgescopte UUIDs zerstoeren
die deterministische Chunk-Identitaet" ist richtig, aber sie ist nicht der
entscheidende Einwand. Der entscheidende Einwand ist: **generationsgescopte UUIDs
verhindern den Stale-Write ueberhaupt nicht.** Ein Nachzuegler haelt seine eigene
Generation und wuerde unter *seinen* generationsgescopten UUIDs schreiben — die
Zeilen existieren danach genauso, nur unter anderem Namen. Erreicht wuerde
lediglich Unterscheidbarkeit, und die liefert `owning_generation` (§13.3.1)
bereits. Der Identitaetsschaden waere also ein Preis **ohne Gegenleistung**:

- die Projektion und die Identitaetspruefung laufen **vor** dem Claim
  (`_validate_objects_against_target` prueft
  `uuid == deterministic_uuid(project, source, chunk_id)`, `sync.py:1150`, und
  wird vor `self._claim(...)` aufgerufen, `sync.py:477/480`) — die Generation ist
  dort noch nicht bekannt;
- der Story-Export projiziert Objekte voellig ohne Claim (N42) und koennte
  endgueltige Identitaeten nicht mehr bilden.

**Ein anderes Speicherprimitiv?** Konkret gepruefte Optionen: (i) ein Store mit
konditionalen Updates fuer die Chunks selbst — das waere ein Wechsel der
Korpus-Persistenz und damit eine andere Story als diese; (ii) den
Autoritaetszeiger in den bestehenden State-Backend legen — verhindert den Write
nicht und schuf ein zweites operatives Wahrheitszentrum fuer Korpuszustand
(CLAUDE.md: SSOT), waehrend der Abschlussvermerk die Wahrheit fuer Freshness ist.
**Ergebnis: (a) bleibt verworfen, mit geschaerfter Begruendung.**

### 2.2 Form (b) — Retrieval schliesst nicht-autoritative Generationen aus

**Vorbefund bestaetigt: die einzige Form, die den Rest wirklich schliesst.**
Ergaenzt um eine gemessene Kostenrechnung und um eine **dritte,
guenstigere Filterform**, die im Vorbefund fehlt.

#### 2.2.1 Die unvermeidbare Zutat: ein quellenweiser Autoritaetswert

Generationen sind **quellenweise** Leitern. Es gibt daher **keinen einzelnen
Skalar**, der projektweit autoritativ von veraltet trennt: eine Stale-Zeile der
Quelle A mit Generation 5 liegt ueber der autoritativen Generation 2 der Quelle B.

Auch der naheliegende Diskriminator `corpus_revision` hilft **nicht** als
globaler Gleichheitsfilter: ein inkrementeller Sync schreibt nur die geaenderten
Quellen neu, also tragen unveraenderte Quellen legitim aeltere Revisionen; ein
Filter „Revision == aktuelle Projektrevision" wuerde gueltige Treffer
ausschliessen. `corpus_revision` funktioniert nur **quellenweise** — und damit
ist es derselbe Lookup wie `(source_file, owning_generation)`. Hinzu kommt:
`corpus_revision` ist heute **keine** `StoryContext`-Property (§13.3.1), waehrend
`owning_generation` es ist. Der Revisions-Diskriminator kostet also
zusaetzlich eine Schema-Erweiterung und einen Stempel im Schreibpfad, ohne
irgendetwas billiger zu machen.

**Folge:** jede Variante von (b) braucht die Abbildung
`{source_file -> autoritative Generation}`. Sie ist aus den Abschlussvermerken
ableitbar (`list_receipts`; das Pruning haelt je Quelle die hoechste Generation),
also **ohne** neue Zustandsquelle.

#### 2.2.2 Gemessen: Kosten des Autoritaets-Lookups

Messmethode: reale Feldlaengen eines Abschlussvermerks (9 Properties), gegen
`FETCH_PAGE_SIZE = 1000` und `MAX_FETCH_OBJECTS = 200000` aus dem Adapter.

| Quellen im Projekt | Abschlussvermerke | Nutzlast | Round Trips |
|---|---|---|---|
| 75 (AK3-Konzeptkorpus, gemessen) | 75 | ~23 KiB | **1** |
| 242 (AK3 gesamt: 75 Konzept + 167 Story, gemessen) | 242 | ~73 KiB | **1** |
| 1000 (grosses Zielprojekt) | 1000 | ~301 KiB | **1** |

Ein Abschlussvermerk je Quelle, eine Seite bis 1000 Quellen → **ein zusaetzlicher
Round Trip pro Suchanfrage**. Ein Cache entfernt diesen Read nicht: Retrieval und
Sync sind verschiedene Prozesse (MCP-Server vs. CLI), eine Gueltigkeitspruefung
waere selbst ein Read. Er reduziert nur das Paging bei sehr vielen Quellen.

#### 2.2.3 Gemessen: Kosten des Vorfilters auf dem heissen Pfad

Messmethode: der Filter wird mit der **clienteigenen** Protobuf-Abbildung
(`weaviate.collections.filters._FilterToGRPC.convert`) serialisiert und
`ByteSize()` abgelesen — das ist exakt das, was pro Anfrage ueber die Leitung
geht.

| Quellen | (A) `any_of` aus `AND(source_file, generation)` | (B) `any_of` aus Gleichheit auf **einem** Schluessel | (C) `contains_any` auf **einem** Schluessel |
|---|---|---|---|
| 75 | 7 427 B | 5 327 B | **3 698 B** |
| 242 | 23 960 B | 17 184 B | **11 881 B** |
| 1000 | 99 002 B | 71 002 B | **49 024 B** |
| 5000 | 499 002 B | — | **249 024 B** |

Struktur, nicht nur Groesse:

- **(A)** OR ueber N Zweige mit je 2 Blattbedingungen → 150 / 484 / 2000
  Blattbedingungen (gemessen) fuer 75 / 242 / 1000 Quellen.
- **(B)/(C)** benoetigen **eine** zusaetzliche, aus zwei bestehenden Feldern
  abgeleitete Property (`f"{source_file}|{generation}"`), im Store beim Schreiben
  gestempelt wie `owning_generation`. Damit wird der Filter ein Test auf **einem**
  Feld: (B) OR ueber N Gleichheiten, (C) **eine** Mengenbedingung mit N Werten.

**(C) ist die guenstigste Form und fehlt im Vorbefund.** Preis: eine
denormalisierte, abgeleitete Property (Redundanz aus `source_file` +
`owning_generation`; kein zweites Wahrheitszentrum, aber Konsistenzpflicht per
Konstruktion) und eine in Phase 2 **noch zu verifizierende** Semantikfrage:
`contains_any` auf einem FIELD-tokenisierten Textfeld muss Ganzwert-Mengen-
Gleichheit bedeuten. Ohne laufenden Weaviate ist das **nicht gemessen**; der
sichere Rueckfall ist (B) mit derselben Ein-Feld-Struktur bei doppelter Groesse.
(Fuer `concept_status` wurde in D8 aus genau diesem Grund `any_of`-aus-Gleichheit
gewaehlt.)

**Alle drei Suchmodi** nehmen `filters` und `limit` identisch
(`hybrid`/`bm25`/`near_text`, gemessen an den Signaturen) — der Vorfilter braucht
**keine** Modus-Sonderbehandlung. **Nicht gemessen** (kein Server verfuegbar) und
daher als Risiko benannt: bei `vector` (`near_text`) muss eine restriktive
Filterbedingung im HNSW-Graph mehr Kandidaten durchsuchen, um `limit` zu fuellen —
das ist das bekannte Verhalten gefilterter ANN-Suche und betrifft Latenz und
Recall, nicht Korrektheit.

**Die Wire-Groesse bricht nichts:** der Client verhandelt
`grpc.max_send_message_length` aus dem Server-Meta, Default
`MAX_GRPC_MESSAGE_LENGTH = 104 858 000` B (~100 MiB). 49 KiB bei 1000 Quellen
sind davon weit entfernt. Die Kosten sind Auswertung und Planung, nicht
Transport.

#### 2.2.4 Gemessen: warum der Nachfilter `limit` nicht exakt halten kann

Der Nachfilter (suchen wie heute, dann nicht-autoritative Treffer clientseitig
verwerfen) kostet nur den einen Autoritaets-Read — bricht aber die
`limit`-Semantik: `limit` wird serverseitig angewandt, das Verwerfen danach
unterfuellt das Ergebnis.

Ueberfetchen behebt das nur scheinbar. Ein wiederauferstandener Schreiber hat
eine **vollstaendige Generation** einer Quelle geschrieben; im realen AK3-Korpus
sind das **bis zu 56 Chunks je Quelle, Median 28** (gemessen ueber 2 079 Chunks /
75 Quellen). Bei `limit = 10` (Default; Max 100) koennen also alle
zurueckgegebenen Treffer stale sein, und der noetige Ueberfetch-Faktor ist im
Allgemeinen **unbegrenzt** — exakte `limit`-Semantik erfordert eine Schleife mit
unbestimmt vielen Runden. **Exaktheit gibt es nur mit dem Vorfilter.**

#### 2.2.5 Was (b) am Rand noch braucht — und was gratis ist

- Die Retrieval-Profile geben `owning_generation` heute **nicht** zurueck
  (gemessen: 16/13/13 Rueckgabefelder je Quelltyp, `source_file` enthalten,
  Generation nicht). Der Nachfilter muesste sie intern anfordern und vor dem
  Envelope entfernen — die Rueckgabefelder aus §13.9.5 bleiben unveraendert. Der
  Vorfilter braucht das nicht.
- Die **Generation bleibt in jedem Fall von der Abfrageoberflaeche fern**: kein
  Parameter, kein Rueckgabefeld (§13.9.5 unveraendert).
- **Die Zaehler sind gratis korrigierbar.** `list_sources` liest heute schon
  *alle* Zeilen je Quelltyp **und** alle Abschlussvermerke
  (`engine.py:947–952`). `source_count`/`chunk_count` um nicht-autoritative
  Zeilen zu bereinigen kostet **keinen** zusaetzlichen Transport.
- **Ungefilterte Leser sehen die Zeilen weiterhin.** (b) macht sie unsichtbar
  fuer `concept_search`/`story_search` und fuer die Zaehler; sie existieren
  physisch weiter, bis der naechste Sync sie entfernt. Wer die Collection direkt
  liest (Betrieb, Debugging), sieht sie. Das ist ehrlich zu benennen, statt „der
  Rest ist geschlossen" zu behaupten.

### 2.3 Form (c) — den Rest als Vertrag ratifizieren

Ehrliches Dokumentieren statt Beheben. Zu liefern waere:

1. **Vertragstext** (FK-13 §13.9.9): benennt ausdruecklich, dass die Suche im
   engen Fall aus 1.3 veraltete Treffer liefern kann; nennt beide unabgedeckten
   Klassen aus 1.2; behauptet **keine** zeitliche Schranke und **keine**
   Atomizitaet; benennt, was garantiert bleibt (kein Loeschen fremder neuerer
   Daten, keine Freshness-Umkehrung).
2. **Betriebshinweis:** nach jedem administrativen Reclaim ist ein Sync dieser
   Quelle auszufuehren — das ist der deterministische Aufraeumpfad und schliesst
   den Fall vollstaendig. Der Reclaim ist ohnehin eine bewusste Handlung
   (`--reclaim`), also ein natuerlicher Ort fuer diese Pflicht.
3. **Beobachtbarkeit — und das ist der Kern der Lieferung.** Sie ist **billig**:
   `list_sources` haelt schon alle Zeilen und alle Abschlussvermerke, also laesst
   sich je Quelltyp ein `stale_chunk_count` (Zeilen, deren `owning_generation`
   nicht die autoritative Generation ihrer Quelle ist) **ohne zusaetzlichen
   Read** bilden. Ein Wert > 0 ist ein WARNING nach der Severity-Semantik: ein
   Handlungsauftrag mit aufschiebender Wirkung, der aktiv gespiegelt wird.
   Achtung Vertragsflaeche: `story_list_sources` hat in §13.4.1/D1 feste
   Rueckgabefelder — ein zusaetzliches Feld ist eine (kleine) ratifizierte
   Konzeptaenderung, oder der Wert wird ueber Telemetrie/CLI statt ueber das
   Tool-Envelope gemeldet.

---

## 3. Empfehlung

**Empfohlen: (c) jetzt, mit vollem Observability-Anteil — und (b) in der Form
(C)/(B) als eigene, spaeter entscheidbare Ausbaustufe, nicht jetzt.**

Begruendung, in der Reihenfolge ihres Gewichts:

1. **(b) schliesst den Rest wirklich, aber der Preis liegt auf dem heissesten
   Pfad des Systems.** Gemessen: **+1 Round Trip pro Suchanfrage** und ein
   Filter, der mit der Zahl der Quellen waechst (3,7 KiB bei 75, 11,9 KiB bei
   242, 49 KiB bei 1000 Quellen in der guenstigsten Form). Dazu ein **nicht
   gemessenes** Recall-/Latenzrisiko der gefilterten ANN-Suche. Das ist eine
   dauerhafte Belastung **jeder** Suche fuer einen Fall, der vier gleichzeitige
   Bedingungen braucht.
2. **Der Aufraeumpfad existiert und ist deterministisch.** Ein Sync der Quelle
   entfernt die Zeilen sicher (hoehere Generation, Ordnungsbedingung). Es fehlt
   nicht das Mittel, sondern der **Anstoss** — und genau den liefert
   Beobachtbarkeit: sichtbar gemachter Rest plus Betriebspflicht nach dem
   Reclaim.
3. **Beobachtbarkeit ist gemessen billig** (kein zusaetzlicher Read, siehe
   2.3/3), waehrend Exklusion gemessen teuer ist. Das ist ein sehr ungleiches
   Kosten-/Nutzenverhaeltnis fuer denselben Fall.
4. **Es bleibt ehrlich.** (c) verlangt, den Rest zu benennen statt zu
   beschoenigen — und die Beobachtbarkeit macht ihn **erkennbar**, was die Story
   ausdruecklich als Kern von (c) fordert. Nach SEVERITY-SEMANTIK ist ein
   erkannter, gespiegelter Rest zulaessig; ein verschwiegener nicht.

**Gegen die Empfehlung spricht** — und der PO soll das mitwaegen: (c) laesst ein
Fenster offen, in dem ein Agent veralteten Normtext als gueltig lesen kann, und
das trifft den Kernnutzen. Wer diese Moeglichkeit gar nicht akzeptieren will,
muss (b) waehlen; dann ist Form **(C)** (eine Mengenbedingung auf einem
abgeleiteten Autoritaetsschluessel) die guenstigste gemessene Variante, mit (B)
als semantisch sicherem Rueckfall.

**Nicht empfohlen:** (b) als **Nachfilter**. Er ist billiger im Read, kann aber
`limit` nicht exakt halten (2.2.4, unbegrenzter Ueberfetch) — ein zweiter
Kompromiss anstelle einer Loesung.

### Groessen

| Form | Groesse | Inhalt |
|---|---|---|
| (a) | — | verworfen, nur Belegpflicht (dieses Dokument) |
| (b) | **M** (Hauptaufwand) | Autoritaets-Lookup, Filterbildung, ggf. abgeleitete Property + Schema-/Read-back-Pflege, Zaehlerbereinigung, Race-Tests beider Reihenfolgen, Konzept + Decision Record |
| (c) | **S** | Vertragstext, Betriebshinweis, `stale_chunk_count`-Beobachtbarkeit (ohne zusaetzlichen Read), Erkennbarkeitstest, Decision Record |

---

## 4. Wirkung auf FK-13 §13.9.9

§13.9.9 traegt den Rest heute als **offenen, nicht ratifizierten** Punkt: Absatz
„Offener Restbefund (nicht ratifiziert)" mit beiden Klassen aus 1.2, dem Satz
„dieser Zeitpunkt ist **nicht zeitlich begrenzt**", der Zuordnung an eine
Folgestory und dem ausdruecklichen „**kein** akzeptierter Vertrag".

| Form | Was sich in §13.9.9 aendert | Decision Record |
|---|---|---|
| (a) | entfaellt (nicht gewaehlt); der Absatz bliebe unveraendert | — |
| (b) | Der Absatz wird **ersetzt**: der Rest ist fuer das Retrieval geschlossen. Neu zu sagen ist, **wodurch** (quellenweiser Autoritaetsfilter, Generation bleibt intern), und ehrlich zu halten, dass die Zeilen **physisch weiter existieren**, bis der naechste Sync sie entfernt — Unsichtbarkeit ist keine Abwesenheit. §13.3.1 erhaelt ggf. die abgeleitete Autoritaets-Property; §13.9.5 bleibt unveraendert (kein neuer Parameter, kein neues Rueckgabefeld). | **ja** (P3) |
| (c) | Der Absatz wird von „offen, nicht ratifiziert" auf **ratifizierter Vertrag** umgestellt: gleicher Sachverhalt, aber als bewusst uebernommene Eigenschaft, plus Betriebspflicht nach dem Reclaim und Verweis auf die Beobachtbarkeit. Die Saetze „nicht zeitlich begrenzt" und „keine Atomizitaet" **bleiben**. Faellt der Zaehler in das Tool-Envelope, ist §13.4.1/D1 mitbetroffen. | **ja** (P3) |

In beiden Faellen gilt: keine Grenze behaupten, die nicht gehalten wird; keine
Atomizitaet; §13.9.6/`doc_kind` bleibt unberuehrt (Frage Q2 ist offen und nicht
Gegenstand dieser Story).

---

## 5. Was Phase 2 offen verifizieren muss (kein Blocker fuer die Entscheidung)

1. `contains_any`-Semantik auf einem FIELD-tokenisierten Textfeld (Ganzwert?) —
   nur mit laufendem Weaviate messbar; Rueckfall ist Form (B).
2. Latenz/Recall der gefilterten `near_text`-Suche unter dem Vorfilter — nur mit
   laufendem Weaviate messbar.
3. Bei (c): ob der `stale_chunk_count` im Tool-Envelope oder in
   Telemetrie/CLI gemeldet wird (Vertragsflaeche §13.4.1/D1).

---

## 6. Die Entscheidungsfrage an den PO

> Der Rest ist ein Sichtbarkeitsproblem mit vier gleichzeitigen
> Eintrittsbedingungen, aber **ohne zeitliche Schranke**: bis zum naechsten Sync
> derselben Quelle kann die Suche eine veraltete Fassung mitliefern.
>
> **(b)** schliesst das fuer die Suche — Preis, gemessen: **+1 Read pro
> Suchanfrage** und ein mit der Quellenzahl wachsender Filter (3,7 / 11,9 /
> 49 KiB bei 75 / 242 / 1000 Quellen), dazu ein nicht gemessenes Recall-/
> Latenzrisiko bei der Vektorsuche; die Zeilen existieren physisch weiter.
> Groesse **M**.
>
> **(c)** behebt nichts, macht den Rest aber **erkennbar** (gemessen ohne
> zusaetzlichen Read) und verpflichtet den Betrieb, nach einem Reclaim einen Sync
> zu fahren — der deterministische Aufraeumpfad. Groesse **S**. Preis: im engen
> Fall kann ein Agent bis dahin veralteten Normtext als gueltig lesen.
>
> **Frage:** Ratifizieren wir **(c)** — Vertrag plus Beobachtbarkeit plus
> Betriebspflicht — und halten **(b)** in der gemessen guenstigsten Form als
> spaeter entscheidbare Ausbaustufe? Oder ist „die Suche darf nie eine veraltete
> Fassung zeigen" eine harte Anforderung, dann **(b)** jetzt und die
> Suchpfadkosten bewusst uebernommen?
