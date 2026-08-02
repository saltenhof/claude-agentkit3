---
concept_id: META-DEC-2026-08-01-RUN-MUTEX-INTENT-BOUNDED-WAIT
title: Concept-Decision-Record — Coordination-Intent ist eine Klinke mit Wartefrist (FK-78 §78.4)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-incubation, mutex, liveness, FK-78]
formal_scope: prose-only
---

# Concept-Decision-Record — Coordination-Intent ist eine Klinke mit Wartefrist (FK-78 §78.4)

Datum: 2026-08-01, **ueberarbeitet 2026-08-02** nach einem unabhaengigen
Codex-Review (siehe Rand 2.4, 2.6, 2.7 sowie Abschnitt 3 und 5).
**Korrektur mehrerer Defekte derselben Familie** (Story AG3-179). Das
Coordination-Intent `RUN.mutex.intent` wird bei lebender fremder Klinke
beschraenkt ausgewartet statt sofort aufgegeben (Rand 2.1); seine Freigabe darf
nicht mehr still ausfallen (Rand 2.4); die Klinke gehoert nach dem exklusiven
Create ihrem Ersteller einschliesslich der Bereinigung (Rand 2.7); und
compare-before-delete laeuft unter einem OS-Advisory-Lock, womit die bisher als
Grenze gefuehrte Read-then-Unlink-Luecke geschlossen ist (Rand 2.6).

## 1. Anlass

FK-78 §78.4 sagte bisher: „wer es nicht per O_CREAT|O_EXCL anlegen kann,
verliert." Das las sich wie die strengere Variante und war die kaputte.

Ein Schreiblauf haelt die Klinke nicht ueber seine ganze Laufzeit, sondern holt
sie **viermal** nacheinander: Erwerb/Uebernahme des Mutex, Revalidierung vor dem
Dispatch, Ziel-Write, Freigabe. Zwischen zwei dieser Abschnitte ist sie frei. Ein
Mitbewerber, der genau dann zugreift und anschliessend selbst am lebenden Mutex
scheitert, hat die Klinke in der Hand, waehrend der rechtmaessige Eigentuemer
seinen naechsten Abschnitt beginnen will — und der bricht dann ab. Im
symmetrischen Fall pingpongen beide und **kein** Schreiber kommt durch.

Belegt im echten Zwei-Prozess-Rennen: beide Teilnehmer meldeten Exit 2, einer
davon mit `another writer holds the RUN.mutex coordination intent` — das war der
Prozess, der den Mutex rechtmaessig besass. Quote auf `main` unter Last rund 10 %;
im CI-Lauf blockierte der Befund die gesamte Pipeline.

Es entstand dabei nie ein inkonsistenter Zustand — der Defekt ist reine Liveness.
Genau das machte ihn langlebig: fail-closed sieht aus wie Korrektheit.

## 2. Entscheidung

**Das Intent ist eine kurz gehaltene Klinke, kein Eigentumsrecht.** Eigentum
traegt der Mutex mit Nonce, TTL und Fencing-Token. Daraus folgt normativ:

**2.1 Beschraenktes Warten statt sofortigem Aufgeben.** Wer die Klinke nicht per
O_CREAT|O_EXCL anlegen kann, wartet in kurzen Polls bis zu einer Frist im
Sekundenbereich und bricht **erst danach** fail-closed ab. Die Klinke wird nur
ueber eine Handvoll Dateioperationen gehalten; Warten ist deshalb der Normalfall
und nicht die Ausnahme.

**2.2 Auch der noch leere Create wird ausgewartet.** Exklusiver Create und das
Schreiben der Payload sind zwei Schritte. Eine soeben angelegte, noch nicht
beschriebene Klinke ist ein Halten, keine Leiche — sie wird ausgewartet und
nicht als unlesbar eingesammelt. Der mtime-Fallback fuer verwaiste Klinken
(§78.4, benannte Grenze) bleibt davon unberuehrt, weil er erst nach TTL greift.

**2.3 Kein Freibrief fuer den Eigentuemer.** Ausdruecklich **nicht** entschieden
wurde die naheliegende Alternative, dem Mutex-Eigentuemer das Umgehen der Klinke
zu erlauben. Das haette die Atomizitaet zwischen Ownership-Pruefung und Wirkung
aufgegeben — also genau die Eigenschaft, fuer die die Klinke existiert. Eine
Uebernahme koennte dann wieder zwischen Pruefung und Heartbeat schluepfen.

**2.4 Wirkungen an der Klinke duerfen nicht still ausfallen.** Beim Nachweis der
Behebung trat ein zweiter, aelterer Defekt derselben Familie zutage: auf
Plattformen mit verbindlicher Dateisperrung blockiert schon ein **lesender**
Mitbewerber das `unlink` der Klinke (Windows, WinError 32). Der Code fing genau
diesen Fehler ab und verwarf ihn — die Freigabe tat dann nichts, und die Klinke
lag bis zum Ablauf ihrer TTL herum, waehrend sie niemand hielt. Jeder spaetere
Schreiber meldete daraufhin „ein anderer Schreiber haelt die Klinke", was
schlicht falsch war.

Das ist kein Windows-Detail, sondern eine Modellfrage: nach
compare-before-delete steht das Eigentum fest, die Loeschung ist damit eine
**geschuldete Wirkung** und kein Versuch. Loeschen und atomares Ersetzen werden
deshalb beschraenkt wiederholt; ein endgueltig gescheitertes Ersetzen ist harter
Abbruch. Ergaenzend liest ein Wartender die Payload nur noch im Sekundentakt
nach — der exklusive Create ist die billige Probe, und haeufiges Lesen ist genau
das, was dem Halter die Freigabe blockiert.

**Korrektur 2026-08-02 (Codex-Review):** Die urspruengliche Fassung dieses Rands
sagte, ein endgueltig gescheitertes Loeschen werde „als WARNING mit Dateipfad
gemeldet". Umgesetzt war das als Text auf stderr bei **Exit 0** und der Meldung
„OK" — also genau die stille Erfolgsmeldung, die derselbe Rand verbietet. Ein
WARNING ohne Owner und ohne Folgeauftrag erfuellt die Severity-Semantik nicht;
ein Befund, fuer den niemand spaeter Zeit bekommt, ist im Effekt ein ignorierter
Befund. Normativ gilt daher jetzt: ein endgueltig gescheitertes Loeschen ist ein
**blockierender ERROR-Befund im Envelope**, niemals Exit 0 und niemals „OK". Der
Befund benennt die liegengebliebene Datei, wie lange sie jeden weiteren
Schreiber blockiert, und dass die Mutation **moeglicherweise bereits
gelandet** ist. Der bereits berechnete Befund des Laufs darf dabei weder
verlorengehen noch verfaelscht werden — die Freigabe laeuft im Teardown, lange
nachdem der Ausgang der Mutation feststeht; eine gelandete Mutation wird nicht
nachtraeglich als „nicht passiert" ausgegeben.

Symmetrisch dazu gilt das auch fuer den Erwerb: ein vom Betriebssystem
**verweigerter** Create — nicht „existiert bereits", sondern „darf gerade
nicht" — ist ein verlorener Anspruch mit regulaerem Fehlausgang. Bisher war nur
`FileExistsError` behandelt; jeder andere OS-Fehler an der Klinke beendete das
CLI mit einem Traceback und Exit 1, also ausgerechnet mit dem Code, den derselbe
Vertrag fuer **blockierende Validierungsbefunde** reserviert. Jeder Exit-Code
dieses CLIs traegt eine eigene, unterscheidbare Aussage (`1` Befunde, `2`
fehlende Voraussetzungen, `4` gescheiterte Aufraeumwirkung, Rand 2.4a); ein
Absturz traegt keine.

Der Rest ist benannt: laesst ein Leser waehrend der ganzen Wiederholungsfrist
kein Fenster, ueberlebt die Klinke bis zu ihrer TTL. Der ERROR-Befund benennt
diesen Fall mit Dateipfad.

**Korrektur 2026-08-02 (Codex-Review Runde 2): „weg" und „nicht pruefbar" sind
nicht dasselbe.** Die Lader `load_mutex_state` / `load_intent_state` liefern
`None` sowohl fuer eine **fehlende** als auch fuer eine **vorhandene, aber nicht
lesbare oder ungueltige** Datei. Compare-before-delete hat beide Faelle gleich
behandelt und den zweiten damit als „schon erledigt" verbucht: ein Lesefehler
beim finalen Re-Read von `RUN.mutex` liess den Lauf mit Exit 0 und „OK" enden,
waehrend die Datei liegenblieb. Normativ gilt jetzt:

- Eine Datei, deren Identitaet nicht gelesen werden kann, wird **niemals
  ungeprueft geloescht** — die Vergleichsgroesse von compare-before-delete
  fehlt ja gerade.
- Sie wird ebenso wenig als erledigt verbucht, sondern ist eine **geschuldete,
  nicht erledigte Wirkung** und damit derselbe blockierende ERROR-Befund. Die
  Diagnose des Laders (Locator + Meldung) ist die Begruendung des Befunds und
  wird nicht verworfen.
- „Weg" darf nur behauptet werden, wenn die Abwesenheit **beweisbar** ist
  (`FileNotFoundError`); ein fehlgeschlagenes `stat` ist kein Beweis.
- Die Dauer der Blockade wird wahrheitsgemaess benannt: eine **gueltige**
  liegengebliebene Datei wird nach TTL uebernommen, eine **ungueltige**
  `RUN.mutex` dagegen **nie** — sie wird als ungueltiges Payload abgewiesen,
  bevor die TTL ueberhaupt betrachtet wird. Diese Klemme ist damit **permanent**
  und nur von Hand aufloesbar; der Befund sagt das so. Beim Intent bleibt die
  Klemme TTL-begrenzt, weil dort der mtime-Rueckfall greift.

**2.4a Eigener Exit-Code fuer die gescheiterte Aufraeumwirkung**
(PO-Entscheid 2026-08-02). Der Vorschlag aus Rand 2.4 ist ratifiziert, mit
einer Aenderung: eine endgueltig gescheiterte geschuldete Loeschung meldet
**nicht** Exit 1, sondern den **reservierten Exit-Code `4`** — „die Mutation ist
abgeschlossen, aber eine geschuldete Aufraeumwirkung ist endgueltig gescheitert;
die liegengebliebene Datei blockiert weitere Schreiber".

Begruendung: „Arbeit erledigt, Aufraeumen gescheitert" ist semantisch etwas
anderes als „Validierungsbefund" (`1`) und als „Vorbedingung fehlt" (`2`). Ein
Konsument muss die drei Faelle unterscheiden koennen, **ohne die Meldung zu
parsen**. Der Preis — ein Vertragsbestandteil mehr, den alle Konsumenten kennen
muessen — ist bewusst akzeptiert.

Verbindlich dazu:

- `4` gilt **ausschliesslich** fuer diesen Fall. Read-only-Checks (`check.py`)
  liefern ihn nie.
- **Rangfolge, staerkstes zuerst: `2` vor `1` vor `4` vor `0`.** Treffen mehrere
  zu, gewinnt der fachlich schwerwiegendere Befund. `4` ist bewusst der
  schwaechste, denn er behauptet, die Arbeit sei erledigt — wuerde er `1` oder
  `2` verdraengen, meldete er das faelschlich.
- Der Befund im Envelope bleibt in **jedem** dieser Faelle unveraendert ein
  blockierender ERROR-Eintrag mit Datei, Blockadewirkung (inklusive der
  Permanenz bei der Mutex-Datei) und dem Hinweis auf die moeglicherweise bereits
  gelandete Mutation. Nur die Entscheidung ueber den Exit-Code faellt anders
  aus.
- Nachgezogene Konsumenten: `findings.py` (Vertrag und Rangfolge),
  `semantic_gate.py` (Modul-Docstring und Ausgabe), FK-78 §78.4 und §78.14,
  das Skill-Bundle `concept-incubation-core` (Toolchain-Aufrufe und
  Gate-Schritt).

**2.4c Die W2/W3-Pre-Merge-Pflicht ist fuer AG3-179 ausgesetzt**
(PO-Entscheidung 2026-08-02). Der PO richtet die Qualitaetssicherung
grundsaetzlich neu aus: weg vom LLM-Hub, an den Konzeptanteile geschickt werden
in der Hoffnung, dass Modelle sauber antworten, hin zur Harness-Bridge mit
nativen KI-Agenten, die ihre Strategie selbst waehlen und denen von aussen nur
Leitplanken, Ziele und Nachweispflichten vorgegeben werden. Fuer diese Story
gilt daher:

- Der vollstaendige W3-Sweep wird **nicht** weiter verfolgt; der Ist-Stand ist
  im Story-Record mit Scope, Fehlermodus und Reproduzierbarkeit dokumentiert.
- „W2 vollstaendig gruen" ist **kein Abnahmekriterium** dieser Story mehr. W2
  wurde gefahren, das Ergebnis ist berichtet und eingeordnet.
- Ein zuvor beauftragter **bounded Retry fuer W3** wurde gestrichen und
  vollstaendig zurueckgebaut: in einen Mechanismus zu investieren, der ohnehin
  ersetzt wird, waere Arbeit gegen den eigenen Plan. Der zugrundeliegende
  Befund (W3 wertet jede Partition genau einmal aus, W2 korrigiert einmal
  nach) bleibt damit **offen und unbehoben** — bewusst, nicht uebersehen.

**Diese Aussetzung ist eine dokumentierte Ausnahme, kein Uebergehen.** Der
Unterschied ist der Text selbst: die Pflicht ist benannt, die Aussetzung ist
begruendet, ihr Urheber ist benannt, und der offene Rest steht mit
Fehlermodus da, statt zu verschwinden.

**Was die Aussetzung ausdruecklich NICHT beruehrt:** die FK-93-Aenderungen aus
Abschnitt 3. Das fehlende Deferral-Modell des Katalogs ist eine **eigene
Modellierungsschuld** und kein W2-Artefakt; ein Katalog, der Autoritaet ueber
fremde Werte beansprucht, ohne die Kanten zu erklaeren, ist auch dann falsch,
wenn ihn kein Werkzeug mehr prueft.

**2.5 Nichts an der Strenge geaendert.** Schiedsrichter bleibt O_CREAT|O_EXCL;
compare-before-delete bleibt auf jedem Pfad; ein abgelaufenes Intent wird weiter
sofort uebernommen und nicht ausgewartet; nach Fristablauf wird abgebrochen, nicht
durchgewunken; ein lebender fremder **Mutex** bleibt fuer jeden Mitbewerber ein
harter Abbruch.

**2.6 Compare-before-delete laeuft unter einem OS-Advisory-Lock**
(neu 2026-08-02). Compare-before-delete ist Read-then-Unlink und damit selbst
nicht atomar. Aufraeumer A liest die abgelaufene Nonce N1 und pausiert vor dem
`unlink`; B loescht N1, legt exklusiv N2 an und beginnt seinen kritischen
Abschnitt; A setzt fort und loescht N2, weil die erwartete Nonce nicht Teil der
Loeschoperation ist — ein dritter Schreiber kann jetzt parallel eine Klinke
anlegen. Das ist eine verletzte Kerninvariante, und eine verletzte
Kerninvariante wird nicht deklariert, sondern behoben; FK-78 hatte sie bis dahin
als „benannte Grenze" gefuehrt und die belastbare Aufloesung (Advisory-Lock oder
fail-closed manuelle Recovery) selbst benannt.

Umgesetzt ist die erste Variante: **jedes** Loeschen der Klinke anhand einer
zuvor beobachteten Identitaet — regulaere Freigabe wie Einsammeln einer
abgelaufenen Klinke — laeuft vollstaendig unter einem Advisory-Lock auf
`RUN.mutex.intent.lock` (`fcntl.flock` bzw. `msvcrt.locking`). Randbedingungen,
die zur Norm gehoeren: Lesen, Ablaufpruefung, erneute Identitaetspruefung und
`unlink` sind ein Abschnitt; die Lockdatei wird **nie** geloescht und traegt
keinen Zustand (eine loeschbare Lockdatei haette dasselbe Problem); der
Geltungsbereich bleibt eng — Schiedsrichter des Anspruchs ist weiterhin
`O_CREAT|O_EXCL`, serialisiert wird nur der Aufraeumpfad; auf den Lock wird
beschraenkt gewartet und danach fail-closed abgebrochen; er wird nur ueber den
kurzen Aufraeumabschnitt gehalten, damit der Prozesstod ihn freigibt.

Was bleibt, ist in FK-78 §78.4 als Rest ausgeschrieben (Lock nicht bekommen =
keine Bereinigung, fail-closed; Leser blockiert das `unlink` ueber die ganze
Frist; Netz-Dateisysteme ohne verlaessliche Bereichssperre; die dauerhaft
liegende Lockdatei). Keiner dieser Punkte verletzt eine Kerninvariante.

**2.7 Die exklusiv angelegte Klinke gehoert ihrem Ersteller — samt Bereinigung**
(neu 2026-08-02). Exklusiver Create und Payload-Write sind zwei Schritte.
Scheitert der Write (volle Platte, I/O-Fehler), blieb bisher eine leere Datei
liegen; jeder Folgelauf las sie als frisch gehaltene Klinke und wartete sie aus,
bis nach einer vollen TTL der mtime-Fallback griff. Normativ gilt: nach dem
erfolgreichen Create wird eine nicht beschreibbare Klinke wieder entfernt und
der Anspruch geht regulaer fail-closed verloren. Scheitert auch dieses Entfernen
endgueltig, greift Rand 2.4.

**2.8 Auch der frische `RUN.mutex` wird exklusiv erzeugt** (neu 2026-08-02,
Codex-Review Runde 3). FK-78 §78.4 sagt seit jeher `O_CREAT|O_EXCL` fuer den
Mutations-Mutex — im Code stand dort ein `Path.exists()` mit anschliessendem
atomarem Replace. Dieselbe Existenzpruefung wird wenige hundert Zeilen weiter
oben ausdruecklich als untauglich beschrieben, weil sie bei Rechte- und
E/A-Fehlern `False` liefert. Ein einziges fehlschlagendes `stat` auf einem
**lebenden fremden** Mutex genuegte damit, ihn mit der eigenen Nonce zu
ueberschreiben: aus „nicht pruefbar" wurde beim Erwerb still „weg".

Das ist ein **Safety**-Defekt, kein Liveness-Defekt — zwei Schreiber koennen
gleichzeitig Alleineigentum behaupten — und er ist aelter als diese Story.
Normativ gilt: der Kern entscheidet, ob ein Name frei war. `FileExistsError`
fuehrt in den validierten Takeover-Pfad; jeder andere OS-Fehler am Create ist
ein verlorener Anspruch mit regulaerem Fehlausgang. Der Zwei-Schritt-Spalt
zwischen Create und Payload gilt auch hier (Rand 2.7): scheitert der
Payload-Write, wird der Anspruch zurueckgegeben — ein leerer `RUN.mutex` ist
kein gueltiges Payload und wuerde nach Rand 2.4b **permanent** klemmen.

Das ist keine Lockerung, sondern die Einloesung einer Zusage, die FK-78 die
ganze Zeit gemacht hat.

**2.9 Die Mutex-Freigabe laeuft unter dem Advisory-Lock und weist die Klinke
erneut aus** (neu 2026-08-02, Codex-Review Runde 3). Rand 2.6 hat
compare-before-delete an der **Klinke** atomar gemacht; am **Mutex** blieb es
Read-then-Unlink. Der Ablauf: A haelt Klinke I1 und pausiert laenger als deren
TTL. B sammelt I1 ein, erwirbt I2, uebernimmt den ebenfalls abgelaufenen Mutex
und schreibt M2. A setzt fort und loescht nach Pfad — also M2, den Mutex eines
**lebenden** Eigentuemers, der weiterarbeitet, waehrend seine Sperre weg ist.

Zwei Wege standen offen. Den Verlust der Klinke zu verhindern ist **keiner**:
ein eingefrorener Prozess kann keinen Heartbeat senden, und keine Frist
unterscheidet ihn von einem toten — genau deshalb hat die Klinke eine TTL.
Verhindern hiesse, das Problem durch das Problem zu loesen. Entschieden ist
daher der zweite Weg, **Erkennung**: der fortsetzende Halter weist seinen
Anspruch erneut nach, bevor er wirkt.

Das Mittel ist der bereits normierte Lock. Jedes Einsammeln einer Klinke
braucht ihn, und jede Mutex-Uebernahme braucht die Klinke; wer ihn haelt und
darunter feststellt, dass die Klinke noch seine ist, weiss damit, dass niemand
sie halten und niemand den Mutex uebernehmen kann. Verbindlich: „Klinke noch
unsere" und compare-before-delete des Mutex sind **ein** Abschnitt unter dem
Lock. Ist die Klinke schon eingesammelt, wird nicht geloescht — ein fremder
Mutex bleibt unberuehrt und **ohne** Befund (er ist nicht unsere Schuld), ein
noch eigener wird zur geschuldeten, nicht erledigten Wirkung nach Rand 2.4.

**2.10 Der Wertekatalog darf Normquelle sein — aber nur benannt**
(neu 2026-08-03, Codex-Review Runde 3). §93.0.1 (Runde 2) behauptete, **jede**
Zeile in §93.1–§93.12 gebe einen Wert wieder, dessen Owner anderswo liegt.
Fuer §93.5a und §93.9a ist das nachweislich falsch: deren Werte stehen
repo-weit ausserhalb FK-93 nirgends. Die dazugehoerige `defers_to`-Kante machte
damit einen fremden Owner **maschinenlesbar**, der die Behauptung inhaltlich
nicht besitzt — schlimmer als die fehlende Kante davor, weil vorher nur unklar
war, was jetzt falsch bezeugt ist.

Normativ gilt jetzt die Unterscheidung zweier Zeilenklassen:

- **Wiedergabe** (Regelfall): der Wert ist anderswo normiert. Die
  scope-qualifizierte `defers_to`-Kante benennt diesen Owner; der Katalog
  aendert nichts.
- **Katalog-eigener Wert** (Ausnahme): kein Dokument ausserhalb FK-93 traegt
  den Wert. Dann ist FK-93 die Normquelle **fuer die Zahl**, waehrend das
  besitzende Dokument die **Regel** normiert, der die Zahl dient. Solche
  Zeilen sind in der Tabelle als solche ausgewiesen, und die Kante des
  Abschnitts beschreibt, was das Ziel tatsaechlich besitzt — nie den Wert.

Das entspricht §93.0, das Werte ausdruecklich auch dann aufnimmt, wenn sie
„fest im Code stehen". Der frueher dort stehende Satz, ein nirgends sonst
stehender Wert sei „eine Luecke beim besitzenden Dokument", bleibt fuer die
Wiedergabe-Klasse richtig und ist fuer die Ausnahme praezisiert: die Ausnahme
ist zu benennen, nicht stillschweigend zu nutzen.

**2.11 Die Escape-Reparatur bewahrt Worttreue** (neu 2026-08-02, Codex-Review
Runde 3; **kein neuer Normsatz, sondern die Wiederherstellung eines
bestehenden Vertrags**). W2/W3 verlangen im Prompt-Asset „quote assertion text
exactly" und modellieren die Antwort als `QuotedAssertion`. Die Reparatur der
markdown-Escapes entfernte jedoch **jeden** nicht anerkannten Backslash: aus
einer woertlich zitierten Tabellenzelle mit markdown-escapten Unterstrichen
und einem markdown-escapten Zellentrenner wurde eine Zelle **ohne** diese
Backslashes, und aus dem Pfad `C:\Program` wurde `C:Program`.
W2 nahm die veraenderte Assertion an — es pruefte damals keine Worttreue gegen
den Chunk, siehe Rand 2.11a —, W3 verwarf sie danach zu Recht. Die Toolchain
erzeugte die Korruption selbst.

Ein nicht anerkannter Backslash wird deshalb **verdoppelt** statt entfernt: das
macht denselben Text parsebar und laesst den dekodierten Wert Zeichen fuer
Zeichen identisch. Der Backslash im **Schluessel** bleibt eine eigene
Reparatur — dort ist er nie Inhalt, sondern ein Schema-Bezeichner —, und sie
entscheidet das am **geparsten** Dokument, wo „Schluessel" eine Tatsache und
keine Regex-Vermutung ist.

**2.11a Die Worttreue wird gePRUEFT, nicht nur bewahrt** (neu 2026-08-02,
Codex-Review Runde 4; wie 2.11 **kein neuer Normsatz, sondern die Durchsetzung
des bestehenden Vertrags**). Rand 2.11 hat die Reparatur worttreu gemacht und
dabei festgehalten, dass W2 die Worttreue nicht prueft. Genau daran haengt der
Rest: eine Reparatur kann nur die Verfaelschungen verhindern, die sie **selbst**
verursacht. Ein woertlich kopiertes `C:\new` ist **gueltiges** JSON — `\n` ist
ein anerkanntes Escape —, wird deshalb vor jeder Reparatur angenommen und
dekodiert zu `C:` + Zeilenumbruch + `ew`. Keine Parser-Heuristik kann das sehen;
nur der Vergleich mit dem Chunk kann es. Dasselbe gilt fuer eine schlichte
Paraphrase, die gar keinen Backslash braucht.

Normativ gilt: eine als woertliches Zitat gemeldete Assertion, die im bewerteten
Chunk nicht **zeichengleich** vorkommt, ist eine ungueltige Antwort und wird
fail-closed als benannter Befund `INVALID_EVALUATION_RESPONSE` zurueckgewiesen.
Das ist dieselbe Regel und derselbe Code, die W3 seit AG3-159 fuehrt
(`scope_policy._validate_locus`); der Vertrag „woertliches Zitat" gilt damit auf
beiden Gates statt auf einem.

**2.11b Zwei Schluessel fuer ein Feld sind ein Befund, keine Wahl** (neu
2026-08-02, Codex-Review Runde 4; ebenfalls **kein neuer Normsatz**). Die
Schluessel-Reparatur aus Rand 2.11 normalisiert `has\_normative\_statements` zu
`has_normative_statements`. Traegt dasselbe Objekt beide Schreibweisen mit
**verschiedenen** Werten, entstand daraus stillschweigend ein einziges Feld,
dessen Wert die Reihenfolge entschied. Dieselbe Mechanik konnte in W3 eine
befuellte `contradictions`-Liste durch einen Alias mit `[]` ersetzen — ein Gate,
das PASS meldet, obwohl ihm der Widerspruch genannt wurde. Fuer buchstaeblich
doppelte Schluessel tut `json.loads` von sich aus dasselbe.

„Der letzte gewinnt" und „der erste gewinnt" sind gleich willkuerlich, und beide
sind still. Normativ gilt: zwei Schluessel, die auf dasselbe Feld fallen, sind
eine ungueltige Antwort und werden fail-closed zurueckgewiesen. Die
Zurueckweisung laeuft ueber den bereits vorhandenen Ablehnungspfad beider Gates
und traegt damit einen benannten Befund, keinen Traceback.

## 3. Abgrenzung

**Ueberarbeitet 2026-08-02.** Die urspruengliche Fassung begruendete die
Nicht-Aufnahme in FK-93 damit, dass FK-93 „auch die Mutex-TTL nicht fuehrt".
Abwesenheit ist kein Argument; sie zeigt nur, dass der andere Wert ebenfalls
fehlt. Massgeblich ist ein Kriterium, und dieses Kriterium ist jetzt in FK-93
§93.0 ausgeschrieben: **extern wahrnehmbare Werte gehoeren in den Katalog**,
weil ein Betreiber sie am Verhalten bemerkt und gegen sie diagnostiziert; reine
interne Tuning-Werte bleiben im Code.

Danach sind aufgenommen (FK-93 §93.9a): die TTL von `RUN.mutex` und
`RUN.mutex.intent` (600s), die Wartefrist auf eine lebende fremde Klinke und die
Wiederholungsfrist geschuldeter Datei-Wirkungen. Im Code bleiben das
Poll-Intervall und die Probe-Kadenz. Normativ bleibt in FK-78 weiterhin
„beschraenkt warten, dann fail-closed" — die Sekundenzahl steht im Katalog, nicht
im Normsatz.

Kein neuer Scope, keine neue Faehigkeit: die Nebenlaeufigkeitsgarantien sind
unveraendert, nur erreicht sie der Mechanismus jetzt auch tatsaechlich. Neu ist
allein die Lockdatei `RUN.mutex.intent.lock` im Lauf-Verzeichnis.

## 4. Betroffenheitsmatrix

| # | Gegenstand | Datei / Abschnitt | Klassifikation | Aenderung |
|---|-----------|-------------------|----------------|-----------|
| 2.1 | Klinke vs. Eigentum | FK-78 §78.4 | geaendert | Intent als kurz gehaltene Klinke benannt; Wartefrist statt sofortigem Verlieren |
| 2.1 | Takeover-Satz | FK-78 §78.4 | geaendert | „wer es nicht anlegen kann, verliert" → „wer es auch nach Ablauf der Wartefrist nicht anlegen kann, verliert" |
| 2.2 | Leerer Create | FK-78 §78.4 | geaendert | Spalt zwischen Create und Payload-Write ist ein Halten, kein verwaistes Intent |
| 2.3 | Eigentuemer-Bypass | FK-78 §78.4 | nicht-betroffen | ausdruecklich verworfen; Atomizitaet Pruefung↔Wirkung bleibt |
| 2.4 | Geschuldete Wirkungen | FK-78 §78.4 | geaendert | Loeschen/Ersetzen werden wiederholt; gescheitertes Ersetzen = Abbruch, gescheitertes Loeschen = blockierender ERROR-Befund im Envelope, nie Exit 0 und nie „OK" |
| 2.4 | Poll-Disziplin | FK-78 §78.4 | geaendert | Wartende lesen die Payload nur im Sekundentakt; der exklusive Create ist die Probe |
| 2.4 | Verweigerter Create | FK-78 §78.4 | geaendert | nicht-EEXIST-Fehler am Create = verlorener Anspruch mit Exit-Code, kein Traceback |
| 2.6 | Aufraeumen verwaister Intents | FK-78 §78.4 | **geloest** | war benannte Grenze; compare-before-delete laeuft jetzt unter OS-Advisory-Lock, Abschnitt ist kernel-serialisiert |
| 2.6 | Lockdatei | FK-78 §78.4, Layout-Block | neu | `RUN.mutex.intent.lock` im Lauf-Verzeichnis; reines Serialisierungsmittel, wird nie geloescht |
| 2.6 | Verbleibender Rest | FK-78 §78.4 | ersetzt | Lock nicht bekommen / Leser blockiert `unlink` / Netz-FS ohne Bereichssperre — ausgeschrieben statt als eine Sammelgrenze |
| 2.7 | Eigentum an der frischen Klinke | FK-78 §78.4 | neu | gescheiterter Payload-Write entfernt die Klinke wieder; leere Klinke blockiert sonst eine volle TTL |
| 3 | Aufnahmekriterium des Wertekatalogs | FK-93 §93.0 | neu | extern wahrnehmbar → Katalog; reines internes Tuning → Code; Abwesenheit ist kein Argument |
| 3 | Mutex-/Klinken-Werte | FK-93 §93.9a | neu | TTL 600s, Wartefrist, Wiederholungsfrist aufgenommen; Poll und Probe bewusst nicht |
| 3 | Abgrenzung Story-Locks | FK-93 §93.9 | geaendert | Klarstellung nach W3-Befund `SCOPE_CONTRADICTION`: §93.9 gilt nur fuer Story-Locks (Kapitel 02) und beruehrt die TTL-Uebernahme des Inkubator-Mutex nicht; keine Aenderung der FK-02-Regel selbst |
| 2.4a | Exit-Code fuer gescheiterte Aufraeumwirkung | FK-78 §78.14 | neu | reservierter Exit-Code `4` „Mutation fertig, geschuldetes Aufraeumen gescheitert"; Rangfolge `2` > `1` > `4` > `0`; nur `semantic_gate.py` |
| 2.4a | Exit-Code-Konsumenten | Skill-Bundle `concept-incubation-core` (SKILL.md, references/process-core.md) | geaendert | `4` in der Aufrufuebersicht und im Gate-Schritt benannt; ausdruecklich kein „unbekannter Fehler" |
| 2.4b | „Weg" vs. „nicht pruefbar" | FK-78 §78.4 | neu | nicht verifizierbare Datei wird nie ungeprueft geloescht und nie als erledigt verbucht; Abwesenheit muss beweisbar sein; Permanenz der Mutex-Klemme wird benannt |
| 2.4c | W2/W3-Pre-Merge-Pflicht | Story-Record AG3-179 | ausgesetzt | PO-Entscheidung: QS wird auf Harness-Bridge mit nativen Agenten umgebaut; Ist-Stand dokumentiert, nichts Gruenes behauptet, W3-Retry gestrichen und zurueckgebaut |
| 2.4c | FK-93-Kanten | FK-93 Frontmatter | nicht-betroffen | eigene Modellierungsschuld, unabhaengig von der Pruefmechanik |
| 2.8 | Exklusiver Create des Mutex | FK-78 §78.4 | geaendert | `O_CREAT|O_EXCL` statt Read-then-Create ausgeschrieben; `FileExistsError` → Takeover, jeder andere OS-Fehler → fail-closed; leeres Mutex-Payload wird zurueckgegeben |
| 2.9 | Atomizitaet der Mutex-Freigabe | FK-78 §78.4 | geaendert | geschuldete Loeschung des `RUN.mutex` laeuft unter dem Advisory-Lock und weist die Klinke darunter erneut aus; Erkennung statt Verhinderung |
| 2.10 | Zeilenklassen des Wertekatalogs | FK-93 §93.0.1, §93.5a, §93.9a, Frontmatter | geaendert | „Wiedergabe" vs. „katalog-eigener Wert"; Kanten benennen, was das Ziel wirklich besitzt; Ausnahme muss ausgewiesen sein |
| 2.10 | Wert-Owner der Review-/Groessenwerte | FK-93 Frontmatter, §93.12 | geaendert | DK-10 als Wert-Owner ergaenzt (FK-24 traegt die Zahlen nicht); Modulzahl der Groesse M an DK-10 §10.4 angeglichen |
| 2.11 | Worttreue der Escape-Reparatur | `tools/concept_governance/json_escapes.py`, `parser.py`, `scope_parser.py` | geaendert | Bugfix gegen den bestehenden Vertrag „quote assertion text exactly"; kein neuer Normsatz |
| 2.11a | Durchsetzung der Worttreue in W2 | `tools/concept_governance/policy.py`, `execution.py` | geaendert | gemeldetes Zitat muss zeichengleich im bewerteten Chunk stehen, sonst `INVALID_EVALUATION_RESPONSE`; identisch zur W3-Regel in `scope_policy.py`; kein neuer Normsatz |
| 2.11b | Kollidierende Schema-Schluessel | `tools/concept_governance/json_escapes.py`, `parser.py`, `scope_parser.py` | geaendert | zwei Schluessel fuer dasselbe Feld werden fail-closed als benannter Befund zurueckgewiesen statt still zusammengefuehrt; kein neuer Normsatz |
| — | Layout des Lauf-Verzeichnisses | FK-78 §78.3 | geaendert | `RUN.mutex.intent` (bisher fehlend) und `RUN.mutex.intent.lock` ergaenzt |
| — | Mutex-Semantik | FK-78 §78.4 | nicht-betroffen | Nonce, TTL, Heartbeat, Fencing-Token-CAS unveraendert |

## 5. Herkunft — was freigegeben ist und was nicht

Dieser Abschnitt trennt bewusst drei Klassen. Ratifiziert ist nur die erste.

**(a) Vom PO freigegeben.** PO-Auftrag 2026-08-01: „setz jetzt mal die 179 um
gemaess der bisherigen Richtlinien." Damit freigegeben ist die
**Loesungsrichtung, die in der Story AG3-179 stand**: beschraenktes Warten auf
eine lebende fremde Klinke statt sofortigem Aufgeben, Invarianten unangetastet,
kein Bypass fuer den Mutex-Eigentuemer. Das sind die Raender 2.1, 2.3 und 2.5.

**(a2) Vom PO ratifiziert, mit Aenderung — 2026-08-02.** Der PO hat den
Vorschlag aus Rand 2.4 (gescheiterte geschuldete Loeschung ist ein blockierender
Befund, nie ein stiller Erfolg) **ratifiziert**, aber die Signalisierung
geaendert: nicht Exit 1, sondern der reservierte **Exit-Code `4`** mit der in
**Rand 2.4a** festgelegten Rangfolge. Rand 2.4 ist damit in der Sache
beschlossen; 2.4a ist die vom PO vorgegebene Fassung seiner Aussenwirkung.

**(a3) Vom PO entschieden — 2026-08-02.** Rand **2.4c**: Aussetzung der
W2/W3-Pre-Merge-Pflicht fuer diese Story und Streichung des W3-Retrys, weil die
Qualitaetssicherung auf Harness-Bridge mit nativen KI-Agenten umgebaut wird.
Zugleich hat der PO ausdruecklich bestaetigt, dass die FK-93-Aenderungen
(Abschnitt 3) davon **unberuehrt** im Auftrag bleiben, weil sie eine eigene
Modellierungsschuld beheben und keine Zuarbeit an ein Pruefwerkzeug sind.

**(b) Vom Agentenmandat gedeckt — Ausdetaillierung entlang eines Ankers.**
Die Raender **2.2, 2.4b, 2.6, 2.7, 2.8, 2.9, 2.10** und die FK-93-Aenderungen
aus Abschnitt 3 standen **nicht** in der Story. Sie sind bei der Umsetzung und
in den Codex-Reviews zutage getreten und unter der stehenden Anweisung
„Befunde an der Wurzel beheben" entschieden.

Die frueheren Fassungen dieses Abschnitts fuehrten sie als „gesetzt und
offengelegt, Ratifikation ausstehend" — und liessen sie zugleich in der Norm
gelten. Das war keine eindeutige normative Wahrheit. Massgeblich ist das
**Agentenmandat** (`AGENTS.md`, PO-Ratifikation 2026-08-02): ein Agent darf
neue normative Inhalte schaffen, wenn sie (1) die **Ausdetaillierung** eines
groeber definierten Konzeptinhalts mit **benennbarer Ankerstelle** sind,
(2) dem Bestand **nicht widersprechen** und (3) **keine neue Konzeptdomaene**
eroeffnen. Jeder Rand ist einzeln dagegen geprueft:

| Rand | Ankerstelle | (1) Ausdetaillierung | (2) widerspruchsfrei | (3) keine neue Domaene | Ergebnis |
|---|---|---|---|---|---|
| 2.2 | FK-78 §78.4: `O_CREAT\|O_EXCL` als Schiedsrichter der Klinke plus mtime-Rueckfall fuer verwaiste Klinken | ja — praezisiert, ab wann eine Klinke verwaist ist | ja — der mtime-Rueckfall bleibt unveraendert und greift erst nach TTL | ja | **gedeckt** |
| 2.4b | FK-78 §78.4: „ein Aufraeumen ohne Identitaetspruefung ist auf keinem Pfad zulaessig" | ja — sagt, was gilt, wenn die Vergleichsgroesse selbst nicht lesbar ist | ja — strengere Auslegung derselben Regel, keine Ausnahme davon | ja | **gedeckt** |
| 2.6 | FK-78 §78.4 (Fassung vor dieser Story) fuehrte die Read-then-Unlink-Luecke als „benannte Grenze" und nannte die belastbaren Aufloesungen **woertlich**: „ein OS-Advisory-Lock (`fcntl.flock` bzw. `msvcrt.locking`) oder fail-closed manuelle Recovery" | ja — waehlt eine der beiden vom Konzept selbst benannten Optionen und schreibt ihre Randbedingungen aus | ja — Schiedsrichter bleibt `O_CREAT\|O_EXCL`, der Lock serialisiert nur den Aufraeumpfad | ja — die Lockdatei ergaenzt das von §78.3 besessene Layout | **gedeckt** |
| 2.7 | FK-78 §78.4 (exklusiver Create) plus Rand 2.4, **vom PO ratifiziert** (geschuldete Wirkungen fallen nicht still aus) | ja — sagt, wem die Klinke im Spalt zwischen Create und Payload gehoert | ja | ja | **gedeckt** |
| 2.8 | FK-78 §78.4 nennt `O_CREAT\|O_EXCL` fuer `RUN.mutex` **seit jeher** | ja — der Code loeste die Zusage nicht ein; der Rand schreibt sie aus | ja — er stellt die Konzepttreue her, statt von ihr abzuweichen | ja | **gedeckt** |
| 2.9 | Rand 2.6 (Advisory-Lock, gedeckt) und FK-78 §78.4 „compare-before-delete auf jedem Pfad" | ja — dehnt einen bereits normierten Mechanismus auf den zweiten Pfad aus, auf dem dieselbe Luecke besteht | ja — kein Bypass, keine gelockerte Invariante | ja | **gedeckt** |
| 2.10 | FK-93 §93.0 (Aufnahmekriterium: Werte gehoeren auch dann in den Katalog, wenn sie „fest im Code stehen"); Ownership-Regel in `concept/_meta/assertion-authority.md` | ja — klassifiziert die Zeilen, die §93.0 bereits zulaesst | ja — **beseitigt** einen Widerspruch (§93.0.1 gegen §93.5a/§93.9a), statt einen zu schaffen | ja — FK-93 besitzt den Scope `defaults` | **gedeckt** |
| Abschnitt 3 (§93.0, §93.9a, §93.9) | FK-93 `authority_over: defaults` und der Titel des Dokuments; fuer §93.9a zusaetzlich FK-78 §78.4 als Regel-Owner | ja — sagt aus, was in den bereits besessenen Scope gehoert | ja — §93.9 stellt klar und aendert die FK-02-Regel nicht | ja | **gedeckt** |

Die Raender **2.11, 2.11a und 2.11b** sind keine neuen Normsaetze und fallen
nicht unter das Mandat. Alle drei betreffen denselben bestehenden Vertrag
„quote assertion text exactly" bzw. „ein kurzes woertliches Zitat aus dem
Abschnitt" (`tools/concept_governance/prompts/scope_consistency_v1.md`,
`tools/concept_governance/prompts/authority_prose_v1.md`, `QuotedAssertion`): 2.11 stellt ihn wieder her,
nachdem die Reparatur ihn verletzt hatte, 2.11a setzt ihn auf dem Gate durch,
das ihn bisher nur verlangte, und 2.11b verhindert, dass die Reparatur zwei
widersprechende Antworten zu einer verschmilzt. Nichts davon erweitert, lockert
oder ersetzt eine Regel; es gibt dafuer also auch nichts zu ratifizieren.

Damit ist **keine** offene PO-Ratifikation mehr als Vor-Merge-Auflage
erforderlich. Das ist keine Selbstermaechtigung, sondern die Anwendung der
Regel, die der PO am 2026-08-02 dafuer gesetzt hat: verboten ist Erfindung,
nicht Ableitung. Wo ein Anker gefehlt haette, waere der PO zu holen gewesen —
in dieser Story fehlt keiner.

**(c) Offen.** Nur noch inhaltlich offen, nicht als Freigabe: ob die konkreten
Sekundenwerte aus FK-93 §93.9a kuenftig konfigurierbar werden sollen — heute
sind sie fest im Code, was der Katalog auch so ausweist. Ausserdem benannt und
**nicht** in dieser Story geschlossen: die Konfigurationspfade `permissions.*`
aus §93.5a fehlen im Konfigurationsschema von FK-03; das ist eine
Modellierungsschuld bei FK-03/FK-42/FK-55 und wird dort geschlossen, nicht
hier (§93.5a benennt sie).
