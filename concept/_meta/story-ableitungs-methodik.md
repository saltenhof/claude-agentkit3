---
concept_id: META-STORY-DERIVATION
title: Story-Ableitungs-Methodik — von verankerten Konzepten zum umsetzungsreifen Backlog
module: meta
cross_cutting: true
status: active
doc_kind: methodology
authority_over:
  - scope: story-derivation-methodology
defers_to: []
supersedes: []
superseded_by:
tags: [meta, methodology, backlog, gap-analysis, traceability, dependency-graph, review]
formal_scope: prose-only
---

# Story-Ableitungs-Methodik — von verankerten Konzepten zum umsetzungsreifen Backlog

## 1. Zweck und Anlass

Dieses Dokument beschreibt normativ, wie aus dem Konzeptkorpus ein
umsetzungsreifer Story-Backlog abgeleitet wird. Es beantwortet die
Kernfrage jeder Ableitung: **Wie wird sichergestellt, dass in den
Stories nicht ein relevanter Teil dessen fehlt, was tatsaechlich
gebaut werden muss?**

Die Antwort ist methodisch, nicht heuristisch: Vollstaendigkeit wird
nicht behauptet oder erfuehlt, sondern **falsifizierbar gemacht**.
Jede Anforderung — explizit im Konzept stehend, implizit noetig oder
erst im Code sichtbar — erhaelt eine abzaehlbare Identitaet; jede
Identitaet erhaelt genau eine Disposition; jede Disposition wird
maschinell gegen den Backlog geprueft. Eine fehlende Zuordnung ist
damit ein sichtbarer Fehler, kein stilles Loch.

Referenzanwendung ist der Session-Ownership-Strang
(stories/README.md §6.7/§6.8, Stories AG3-137..AG3-156): 194 explizite
SOLL- und 25 implizite IMPL-Anforderungen, 4 Klaerungsbefunde mit
PO-Entscheidung, 20 Stories, zwei unabhaengige adversariale
Review-Linien, maschinell bewiesene Traceability.

## 2. Grundprinzipien (normativ)

### G1 — Nenner-Disziplin: Vollstaendigkeit braucht einen Nenner

Ohne abzaehlbaren Nenner ist „vollstaendig" eine Stimmung. Der erste
Schritt jeder Ableitung erzeugt deshalb ein ID-Inventar (SOLL-NNN),
in dem jede normative Aussage der Quellkonzepte einzeln gefuehrt wird
— mit Quellanker (FK-XX §Y / formal.<ctx>.<id>), Kategorie und
betroffenem Systemteil. Alles Weitere (Ist-Abgleich, Story-Schnitt,
Review) rechnet gegen diesen Nenner.

### G2 — Unabhaengige Projektionen, die einander pruefen

Mindestens drei Erhebungen, bewusst NICHT voneinander abgeleitet:
das SOLL-Inventar aus den Konzepten, der IST-Befund aus dem Code, die
impliziten Enabler aus Szenario-Walkthroughs. Wer den Ist-Befund aus
dem Soll-Inventar ableitet, findet nur, was er sucht — unabhaengige
Projektionen decken gegenseitig ihre Luecken auf.

### G3 — Autoritaetsordnung der Quellen

Der **Code gewinnt ueber Analysedokumente**: Jeder Datei:Zeile-Beleg
wird vor Uebernahme in ein Briefing am Code verifiziert; weicht der
Code ab, wird der Beleg korrigiert und die Abweichung gemeldet. Das
**Konzept gewinnt ueber das Story-Briefing**: Briefings paraphrasieren;
bei Konflikt gilt das Konzept, und der Konflikt stoppt den Prozess
(→ §5 Klaerungspunkte).

### G4 — Maschinelle Traceability statt gepflegter Listen

Von Hand gepflegte ID-Zuordnungen driften — empirisch in der
Referenzanwendung: der maschinelle Abgleich fand Zuordnungsluecken,
die zwei menschliche Review-Runden uebersehen hatten. Matrix- und
Graph-Konsistenz werden deshalb per Skript geprueft (→ §9), nicht per
Sichtpruefung.

### G5 — Adversariale Reviews mit Selbstverifikation in beide Richtungen

Jede Stufe (Entwurf, GAP-Analyse, Story-Schnitt) durchlaeuft
unabhaengige adversariale Reviews — bevorzugt zwei Reviewer mit
verschiedener Staerke (Codebase-nah und konzeptionell). Findings
werden nie ungeprueft uebernommen: Der Ableitende verifiziert jedes
Finding selbst — **Annahme wie Verwerfung brauchen einen Beleg**. In
der Referenzanwendung war ein plausibel klingender Reviewer-Vorschlag
(Ledger-Identitaet des Ownership-Records) konzeptwidrig; der wahre
Kern des Findings war ein Briefing-Selbstwiderspruch. Beides zu sehen
erfordert die eigene Verifikation am Konzept.

### G6 — Fail-closed-Zwischenzustaende

Ein Backlog wird story-weise gelandet. Deshalb muss **jede
Zwischenlandung betriebssicher** sein: Kein Deployment-Zustand darf
eine Schutzluecke tragen, die erst eine spaetere Story schliesst.
Das erzeugt eigene Kanten und Scope-Entscheidungen (→ §8).

## 3. Phase 0 — Normative Basis sichern

Stories werden ausschliesslich aus **verankerten** Konzepten
abgeleitet, nie aus Entwuerfen. Vorgelagert gilt: Entwurf →
mehrstufige Review (bis Freigabe) → normative Verankerung in den
zustaendigen Dokumenten/formal-specs → P3-Decision-Record
(konzept-konsistenz-governance.md). Offene Konzeptfragen, die die
Ableitung beruehren, werden VOR dem Schnitt entschieden — nicht in
Stories versteckt.

## 4. Phase 1–3 — Die drei Erhebungen

### 4.1 SOLL-Inventar (explizite Anforderungen)

Strukturierte Traversierung der verankernden Commits bzw. der
Quellkonzepte: Jede normative Aussage wird als SOLL-ID gefuehrt.
Erfasst werden ausdruecklich **alle Anforderungsarten**:

- **funktional** (Verhalten, Ablaeufe, Kommandos, Endpoints),
- **nicht-funktional** (Invarianten, Fail-closed-Semantik, Idempotenz-
  und Serialisierungs-Garantien, Atomizitaet, Sicherheits- und
  Credential-Klassen, Degradationsverhalten),
- **Daten-/Zustandsmodell** (Entitaeten, Identitaeten, Kardinalitaeten,
  Statusvokabulare, Persistenzmodelle),
- **Contracts** (Wire-Schemas, Events, Read-Models, CLI-Tabellen),
- **UI-/Anzeige-Pflichten** (inkl. Pflichttexte),
- **Betrieb** (Runbooks, Migrationsreihenfolgen, Admin-Pfade).

Pflicht-Gegenprobe: Das Inventar wird gegen die freigegebene
Entwurfsfassung rueckgeprueft (idealerweise durch einen zweiten,
unabhaengigen Agenten). Ergebnis muss eine **leere Differenz** sein —
sonst ist die Extraktion unvollstaendig. Wird der Konzeptstand nach
Beginn erweitert (Nachverankerungen), waechst der Nenner explizit
(neue ID-Bloecke), und ueberholte IDs wandern in eine
**SUPERSEDED-Audit-Liste** mit Nachfolger-Verweis — nie stilles
Loeschen.

### 4.2 IST-Befund (unabhaengig)

Eigenstaendige Code-Erhebung je Systembereich mit Datei:Zeile-Belegen
und Ampelbewertung: Was existiert, was existiert als abzuloesendes
Gegenmodell, was fehlt vollstaendig (Grep-Nullbefunde fuer die
Kernbegriffe des Zielmodells sind selbst Belege). Der IST-Befund
liefert spaeter die „Betroffene Dateien"-Grundlage der Briefings —
und er findet **tragfaehige Praezedenz-Muster** (bestehende
CAS-/Migrations-/Fixture-Mechaniken), an denen sich die Stories
ausrichten, statt Parallelmechanik zu erfinden.

### 4.3 Implizite Anforderungen und Glue (Enabler-Erhebung)

Die gefaehrlichste Fehlklasse: Anforderungen, die **in keinem
Konzeptsatz stehen**, ohne die aber nichts laeuft. Zwei Techniken,
kombiniert:

**(a) Szenario-Walkthroughs.** End-to-End-Szenarien des Zielmodells
werden Schritt fuer Schritt am realen Code durchgespielt („Session A
stirbt mitten in Phase 3 — was passiert beim naechsten Boot? Wer
raeumt die halbfertige Operation? Woher weiss die UI davon?"). Jeder
Schritt, an dem der Ablauf ohne einen ungenannten Baustein bricht,
erzeugt eine IMPL-ID. Walkthroughs decken vor allem Reihenfolge- und
Uebergangsprobleme auf (z. B.: das alte Schutzmodell darf erst
entfallen, wenn das neue Verwaisungs-Handling existiert — sonst gibt
es einen Deployment-Zustand ganz ohne Schutz).

**(b) Enabler-Katalog.** Eine systematische Checkliste von
Anforderungs-Klassen, die Konzepte notorisch implizit lassen, wird
gegen das Zielmodell abgefragt:

- Persistenz-Enabler: Tabellen, Migrationen, **Backfill von
  Bestandsdaten** (laufende Vorgaenge!), Schema-Bootstrap;
- Identitaet/Bootstrap: Dienst-/Instanz-Identitaeten, Inkarnationen,
  Startup-Rekonsiliierung;
- Uebergangs- und Reihenfolgezustaende: Was gilt zwischen zwei
  Story-Landungen? (→ G6);
- Transportkanaele: Push-/Stream-Kanaele, die eine geforderte Anzeige
  erst moeglich machen (das „View braucht App-Shell und
  Window-Manager"-Muster: eine geforderte Sicht impliziert Navigation,
  Datenkanal, Read-Model und Aktualisierungsmechanik);
- Beobachtbarkeit: Events, Telemetrie, Statusabfragen fuer alles, was
  asynchron wurde;
- Admin-/Recovery-Werkzeuge: Abort, Recover, Aufloesungswege fuer jeden
  neuen Blocker-Zustand (jeder fail-closed-Zustand braucht einen
  definierten Ausweg);
- Betriebs-Dokumentation: Runbooks fuer neue Betriebsfaelle;
- Test-Infrastruktur: Fixtures, Fakes/Ports, Negativpfad-Muster;
- Deployment-/Bundle-Assets: deployte Client-Werkzeuge, die neue
  Vertraege mitsprechen muessen.

IMPL-IDs sind dem SOLL-Nenner **gleichrangig**: gleiche
Dispositionspflicht, gleiche Traceability.

## 5. Phase 4 — Klaerungspunkte (K-Befunde)

Was die Erhebungen aufdecken, die Konzepte aber nicht beantworten
(Topologie-Annahmen, Betriebsmodelle, Timeout-Constraints), wird als
K-Befund gefuehrt und **vor dem Schnitt** dem PO zur Entscheidung
vorgelegt — mit vollstaendigem Kontext und, wo moeglich, einer
fertigen Entscheidungsvorlage inklusive Story-Vorschlag (Lehre der
Referenzanwendung: eine Frage mit fertig geschnittenem
Story-Kandidaten ist schneller entschieden als eine offene
Empfehlung). Entschiedene K-Befunde werden normativ verankert
(zurueck zu Phase 0 fuer das Delta), erst dann geschnitten.
Konflikte zwischen Befund und bestehendem Konzept sind harte Stopps
(CLAUDE.md: Konzepttreue), keine stillschweigenden Abweichungen.

## 6. Phase 5 — Dispositions-Matrix

Jede SOLL-/IMPL-ID erhaelt **genau eine** Zeile in der
Dispositions-Matrix:

- **NEU** — eine Story baut es;
- **UMBAU** — eine Story baut Bestehendes um;
- **RUECKBAU** — eine Story entfernt ein Gegenmodell (immer mit
  Ordnungs-Kante hinter dem Ersatz, → §8);
- **KONZEPT-DONE** — rein normativ erledigt, kein Code noetig;
- **SUPERSEDED** — durch spaetere Entscheidung ueberholt
  (Audit-Zeile mit Nachfolger-IDs);
- **KLAERUNG** — blockiert auf K-Befund (muss vor dem Schnitt leer
  sein).

Muss eine ID auf zwei Stories verteilt werden, ist das ein
**deklarierter Split**: exakt zwei Zeilen, jede mit benanntem Anteil
(z. B. „Schema-Anteil" / „Verhaltens-Anteil"). Undeklarierte
Mehrfachzuordnung ist ein Fehler; ebenso eine Split-Deklaration mit
mehr oder weniger als zwei Zeilen. Beides prueft das Skript (→ §9).

## 7. Phase 6 — Story-Schnitt

### 7.1 Schnittkriterien

- **Fachliche Kohaerenz + eine verifizierbare Landung**: Eine Story
  ist eine zusammenhaengende, einzeln testbare und einzeln landbare
  Einheit — kein Sammelbecken, kein Splitter, der ohne Nachbarn nicht
  pruefbar ist.
- **Fundament zuerst, rein additiv**: Schema/Records/Repositories als
  eigene Story ohne Verhaltensaenderung; Verhalten (Fencing, Vollzug)
  folgt in Konsumenten-Stories.
- **Rueckbau als eigene Story**, hart hinter dem Ersatz geordnet.
- **God-Story-Verbot**: Zu grosse Kandidaten werden mit benannten
  Anteilen gesplittet. Ist ein grosses Fundament nicht sinnvoll
  teilbar, traegt es einen **deklarierten internen Schnitt**
  (Teilschritte mit je eigenem Akzeptanzkriterium).
- **Querschnitts-Auflagen** gelten fuer jede Story und stehen im
  Briefing (in der Referenzanwendung: Postgres-only-Festlegung,
  Blutgruppen-Klassifikation neuer Module, Bundle-Asset-Scope).

### 7.2 Briefing-Standard

Jedes Story-Paket (status.yaml + story.md, stories/README.md §2)
enthaelt:

1. Header mit Typ/Groesse/depends_on — **jede Kante mit
   Ein-Satz-Begruendung** (warum existiert sie fachlich);
2. Kontext mit **am Code verifizierten** Datei:Zeile-Belegen;
3. Scope In/Out — jeder ausgegrenzte Teil mit **benanntem
   Nachbar-Owner** (AG3-ID). Verweist Story A etwas an Story B, muss
   B es In Scope fuehren — sonst faellt es zwischen die Stories;
4. Betroffene-Dateien-Tabelle (aus IST-Befund + eigener Verifikation);
5. **fail-closed formulierte Akzeptanzkriterien** mit expliziten
   Negativpfaden an Phasen-/Zustandsgrenzen (testing-guardrails);
6. Definition of Done (Gate-Suite, Review, Merge, Status, README);
7. **maschinenlesbare Traceability-Zeile** `**Deckt ab:** ...` mit
   exakt den Matrix-IDs samt Split-Annotationen. Stories ausserhalb
   des Nenners (Review-Funde, Sonderstraenge) deklarieren ihre Quelle
   explizit in dieser Zeile;
8. Konzept-Referenzen (nur verifizierte Anker) und
   Guardrail-Referenzen (konkret einschlaegig, nicht generisch).

## 8. Phase 7 — Abhaengigkeitsgraph (Bauplan)

### 8.1 Kanten-Taxonomie

Kanten werden aus fuenf Quellen ermittelt und im Header begruendet:

1. **Produzent→Konsument**: Schema vor Verhalten, Maschinerie vor
   Nutzung, Read-Surface vor Anzeige. Dazu gehoert die oft uebersehene
   Regel: **Wer neue mutierende Endpoints einfuehrt, haengt an der
   Idempotenz-/Serialisierungs-Maschinerie** — das Deklarieren eines
   Scopes ersetzt nicht deren Nutzung.
2. **Schutz-Ordnungskanten (G6)**: Rueckbau erst nach Ersatz; kein
   Zwischenzustand ohne Schutz. Kommt der volle Schutz erst spaeter,
   setzt die fruehere Story einen **minimalen Blocker** (z. B. ein
   Admission-Blocker, der beim Vollzug mitgesetzt wird und bis zur
   Vollausbau-Story nur einen auditierten Admin-Ausweg hat).
3. **Traegerschicht-Kanten**: Infrastruktur (Queues, Adapter,
   Kanaele), ueber die andere Stories ihre Auftraege abwickeln.
4. **Anzeige-/Datenquellen-Kanten**: UI-Stories erst hinter allen
   Stories, deren Zustaende/Jobs sie darstellen.
5. **Sequenz-Kanten**: vom PO verfuegte Reihenfolge ohne technische
   Notwendigkeit — zulaessig, aber **als Sequenz-Kante gekennzeichnet**
   und von technischen Kanten unterscheidbar.

### 8.2 Topologie-Probe und Symmetrie

- Jede Story hat ausschliesslich Vorbedingungen, die entweder Ist sind
  oder von einer Vorgaenger-Story produziert werden — **keine
  haengende Vorbedingung**.
- `unblocks` ist die exakte Umkehrung von `depends_on`; `ready` sind
  genau die Stories ohne offene Vorbedingungen; der Graph ist
  zyklenfrei. Alles maschinell geprueft (→ §9).
- **Anti-Pattern: ordnungsabhaengige Fallback-Klauseln.** Saetze wie
  „falls Story X noch nicht gelandet ist, nutze uebergangsweise Y"
  sind verboten — sie verstecken eine Kante und erzeugen
  Doppel-Ownership. Entweder die Kante ziehen, oder (wo echte
  Reihenfolge-Neutralitaet gewollt ist) eine **beidseitig formulierte
  Uebergabe** mit expliziter Abloesungspflicht in beiden Briefings.

## 9. Maschinelle Pruefungen

Ein Pruefskript verifiziert den kompletten Schnitt gegen Matrix und
Plan; es ist Teil der Ableitung, nicht optional:

- **Matrix-Deckung**: Die `**Deckt ab:**`-Zeile jeder Story expandiert
  (Bereiche `NNN–MMM`, Einzel-IDs) und wird exakt gegen die
  Matrix-Zeile geprueft — fehlende und ueberzaehlige IDs sind Fehler;
  deklarierte Splits muessen die Anteil-Annotation tragen und global
  in genau zwei Stories liegen.
- **Nenner-Vollstaendigkeit**: Jede SOLL-/IMPL-ID des Inventars liegt
  in genau einer Matrix-Zeile (Splits deklariert), inklusive
  SUPERSEDED-Audit.
- **Graph-Konsistenz**: depends_on je Story gegen den kanonischen
  Plan; unblocks als exakte Umkehrung; Status ready/blocked konsistent
  zu den Kanten; Groesse/Typ konsistent.

Grundsatz: Was das Skript pruefen kann, prueft kein Mensch mehr per
Auge — Menschen und Reviewer konzentrieren sich auf Semantik.

## 10. Phase 8 — Review-Regime des Schnitts

1. **Doppelte adversariale Review** des Gesamtschnitts durch zwei
   unabhaengige Reviewer-Linien (Codebase-nah + konzeptionell), mit
   explizitem Pruefauftrag statt offener Bitte: Scope-Loecher zwischen
   benachbarten Stories, Widersprueche zwischen Briefings,
   Reihenfolge-Fallen, Konzept-Treue-Stichproben,
   Ist-Beleg-Stichproben, God-Task-Kritik.
2. **Naiver-Bauer-Test** (Pflichtfrage an beide Reviewer): *Wenn ein
   gehorsamer Implementierer GENAU diese Stories in
   depends_on-Reihenfolge umsetzt und nur tut, was in den Briefings
   steht — entsteht das verankerte Zielmodell vollstaendig, und ist
   jede Zwischenlandung betriebssicher?* Der Test operationalisiert
   Vollstaendigkeit als Vorhersage statt als Gefuehl.
3. **Selbstverifikation jedes Findings** (G5) am Konzept und am Code;
   Annahme, konzepttreue Abwandlung oder belegte Verwerfung. Wo ein
   Reviewer die Korrektur woertlich diktiert, gilt der umgesetzte
   Wortlaut als geschlossen; alles andere geht in eine
   Verifikations-Runde.
4. **Severity-Disziplin**: ERRORs blockieren die Freigabe; WARNINGs
   werden aktiv an den PO gespiegelt („wie wollen wir hier vorgehen"),
   bevorzugt mit fertiger Entscheidungsvorlage (→ §5); nichts bleibt
   still liegen (ZERO DEBT).
5. **Funde ausserhalb des Nenners** (Reviews finden regelmaessig
   Nachbar-Probleme derselben Klasse): eigene Story mit explizitem
   Herkunfts-Vermerk in der Deckt-ab-Zeile — der Nenner wird nicht
   rueckwirkend umgeschrieben, die Audit-Spur bleibt ehrlich.
6. Remediation-Ergebnisse laufen erneut durch Skript + Verifikation,
   bis beide Reviewer-Linien freigeben.

## 11. Anti-Patterns (Kurzliste)

- Vollstaendigkeit ohne Nenner behaupten („sieht komplett aus").
- Ist-Befund aus dem Soll-Inventar ableiten (zirkulaer).
- Analysedokument-Belege ungeprueft in Briefings uebernehmen.
- Undeklarierte Mehrfachzuordnung einer ID; Splits ohne Anteilsnamen.
- Ordnungsabhaengige Fallback-Klauseln statt Kanten.
- Rueckbau vor dem Ersatz; Schutzluecken zwischen Landungen.
- God-Stories ohne internen Schnitt; UI vor ihren Datenquellen.
- Reviewer-Findings ungeprueft uebernehmen ODER ungeprueft abtun.
- Klaerungspunkte als lose Frage spiegeln statt mit
  Entscheidungsvorlage samt Story-Vorschlag.
- Handgepflegte Traceability ohne maschinellen Beweis.

## 12. Abgrenzung

- `konzept-konsistenz-governance.md` (META-CONCEPT-CONSISTENCY)
  sichert die Widerspruchsfreiheit des Konzeptkorpus **selbst** (P1–P5,
  W1–W4); dieses Dokument normiert die **Ableitung** aus einem
  konsistenten Korpus. Beide greifen ineinander: Ableitung nur aus
  verankerten Konzepten (Phase 0) setzt die Governance voraus.
- `stories/README.md` bleibt der operative Rahmen fuer Anatomie,
  Status-Lebenszyklus und Abarbeitung der Stories; dieses Dokument
  beschreibt, wie die dortigen Pakete entstehen.
- Die Werkzeug-Umsetzung der Konsistenz-Governance (W1–W4) ist als
  AG3-157..AG3-160 geschnitten; die maschinelle Schnitt-Pruefung aus
  §9 ist ein Werkzeug der jeweiligen Ableitung und wird pro Strang
  mitgefuehrt.
