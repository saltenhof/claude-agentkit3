# AG3-179 — Arbeitsbericht

Datum: 2026-08-01 (Runde 1), **2026-08-02 (Runde 2)**. Umsetzer und
Verifizierer Runde 1: Orchestrator (Worker-Modus, PO-Auftrag „setz jetzt mal
die 179 um gemaess der bisherigen Richtlinien"); Runde 2: Worker unter
Orchestrator-Auftrag nach dem ersten unabhaengigen Codex-Review.

**Die Story ist NICHT fertig.** Behobene Findings sind kein Abschluss
(CLAUDE.md, „Definition of Done: Codex-Review bis zum Abbruchkriterium"). Der
Stand geht erneut ins Review.

## Zaehlweise der Runden — verbindlich fuer dieses Dokument

Bis Runde 4 gab es **zwei verschiedene Abschnitte mit der Ueberschrift
„Runde 3"** (Codex-Review Runde 4, WARNING „doppelter Abschnitt"). Damit das
nicht wiederkehrt, steht die Regel hier:

- **Runde N** ist eine **ARBEITS**runde. Runde 1 ist die urspruengliche
  Umsetzung; jede weitere Runde N beantwortet **Codex-Review Runde N−1**.
- **Codex-Review Runde M** ist die M-te unabhaengige Pruefung. Sie wird immer
  mit diesem vollen Namen genannt, nie mit „Runde M" allein.

Daraus folgt der Verlauf: Runde 1 (Umsetzung) → Review 1 → Runde 2 → Review 2 →
Runde 3 → Review 3 → Runde 4 → Review 4 → Runde 5 (dieser Stand) → Review 5
steht aus. Der frueher „Runde 3 (2026-08-03)" ueberschriebene Abschnitt ist
Runde 4 und traegt jetzt diesen Namen; das Datum `2026-08-03` war zudem falsch
(alle Commits jenes Abschnitts tragen `2026-08-02`).

# Runde 1 (2026-08-01)

## Ergebnis in einem Satz

Es war **nicht ein** Defekt, sondern **drei** derselben Familie — nur der erste
stand in der Story. Alle drei sind an der Wurzel behoben, alle drei mit einem
Test belegt, der ohne den Fix rot ist.

## Was die Story beauftragt hatte

`_claim_intent` gab bei einer **lebenden** fremden Koordinations-Klinke sofort
auf. Da ein Schreiblauf die Klinke viermal nacheinander holt (Erwerb,
Revalidierung, Ziel-Write, Freigabe), warf ein unterlegener Mitbewerber damit
den rechtmaessigen Mutex-Eigentuemer aus dessen eigenem kritischen Abschnitt;
unter Nebenlaeufigkeit kam kein Schreiber durch.

**Behoben:** beschraenktes Warten (`INTENT_WAIT_SECONDS = 5.0`), danach
unveraendert fail-closed. Kein Bypass fuer den Eigentuemer — das haette die
Atomizitaet zwischen Ownership-Pruefung und Wirkung aufgegeben, also genau die
Eigenschaft, fuer die die Klinke existiert.

## Was beim Nachweis zusaetzlich zutage trat

Der geforderte Lastnachweis (100 Laeufe unter CPU-Konkurrenz, 0 rot) ging nach
dem ersten Fix **nicht** auf: 4 von 100 rot. Die im selben Zug nachgeruestete
Diagnose (beide Rennteilnehmer melden Exit-Code **und** stderr) zeigte, dass
beide Prozesse 5 s auf eine Klinke warteten, die **niemand** hielt.

**Zweiter Defekt — die Freigabe fiel still aus.** Das `unlink` der Klinke lief
unter `contextlib.suppress(OSError)`. Auf Windows blockiert bereits ein
**lesender** Mitbewerber das Loeschen (WinError 32). Gemessen, nicht vermutet:
ein 20-Zeilen-Probe-Skript reproduzierte die Blockade im ersten Versuch. Die
Freigabe tat dann nichts, und die Klinke lag bis zum Ablauf ihrer TTL (600 s)
herum, waehrend sie niemand hielt — jeder spaetere Schreiber meldete „ein
anderer Schreiber haelt die Klinke", was schlicht falsch war.

Das ist ein **Altbestand**, kein Folgefehler des Wartens. Mein Warten hat ihn
nur sichtbar gemacht, weil ein Wartender die Datei im Millisekundentakt oeffnete
und damit dem Halter das eigene Loeschen verbaute.

**Behoben:** nach compare-before-delete steht das Eigentum fest — die Loeschung
ist eine geschuldete Wirkung, kein Versuch. Loeschen und atomares Ersetzen
werden beschraenkt wiederholt; ein endgueltig gescheitertes Ersetzen ist harter
Abbruch, ein endgueltig gescheitertes Loeschen wird als WARNING mit Dateipfad
gemeldet statt verschluckt. Zusaetzlich liest ein Wartender die Payload nur noch
im Sekundentakt — der exklusive Create ist die billige Probe, die TTL misst
Minuten.

**Dritter Defekt — der Absturz.** Der Restlauf (1 von 100 rot) endete mit
Exit **1** und einem Traceback. Ursache: der Create fing nur `FileExistsError`;
jeder andere OS-Fehler an der Klinke beendete das CLI mit einer unbehandelten
Ausnahme — ausgerechnet mit dem Exit-Code, den derselbe Vertrag fuer
Validierungsfunde reserviert. Ein Absturz ist keine Aussage.

**Behoben:** ein vom Betriebssystem verweigerter Create ist ein verlorener
Anspruch mit regulaerem Fehlausgang und benannter Ursache. Dieselbe Behandlung
gilt jetzt an allen drei Stellen, an denen der Mutex-Verlust ohnehin schon
fail-closed behandelt wurde (Erwerb, Revalidierung, Ziel-Write) sowie in der
Freigabe, die im `finally` laeuft und einen fertigen Lauf nie in einen Absturz
verwandeln darf.

## Invarianten — unveraendert

`O_CREAT|O_EXCL` bleibt der Schiedsrichter. Compare-before-delete bleibt auf
jedem Pfad. TTL-basierte Uebernahme, Fencing-Token-CAS und Heartbeat bleiben.
Ein abgelaufenes Intent wird weiter **sofort** uebernommen und nicht ausgewartet.
Ein lebender fremder **Mutex** bleibt fuer jeden Mitbewerber ein harter Abbruch
(`test_two_processes_racing_a_live_mutex_both_abort` bleibt `[2, 2]`).

## Benannter Rest

Laesst ein Leser waehrend der ganzen Wiederholungsfrist kein Fenster, ueberlebt
die Klinke bis zu ihrer TTL. Die Wiederholung macht das sehr unwahrscheinlich,
nicht unmoeglich. Der Rest gehoert zur bereits in FK-78 deklarierten Grenze
„Aufraeumen verwaister Intents" und verschwindet erst mit einem
OS-Advisory-Lock (`fcntl.flock` / `msvcrt.locking`). Die WARNING benennt den
Fall, damit er nicht als „Schreiber X haelt die Klinke" fehlgelesen wird.

## Konzept

- **FK-78 §78.4** sagte woertlich „wer es nicht per O_CREAT|O_EXCL anlegen kann,
  verliert". Diese Norm war die Ursache in Textform und ist nachgezogen:
  Klinke vs. Eigentum, Wartefrist, geschuldete Wirkungen, Poll-Disziplin,
  verweigerter Create, erweiterte benannte Grenze.
- **Decision Record** `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md`.
- `concept/_meta/reference-integrity-baseline.yaml`: eine Zeilennummer
  nachgezogen (der Eintrag zeigt auf FK-78 und wandert mit dem Text).

## Testlage

Neu, jeder einzeln gegen den ungefixten Stand als rot belegt:

| Test | belegt |
|---|---|
| `test_a_live_latch_is_waited_out_instead_of_lost` | Warten statt sofortigem Verlust |
| `test_the_wait_budget_ends_in_a_fail_closed_refusal` | Frist ist beschraenkt, Ende ist fail-closed |
| `test_an_expired_latch_is_still_reclaimed_without_waiting` | abgelaufene Klinke wird nicht ausgewartet |
| `test_a_latch_without_a_payload_yet_is_waited_out_not_stolen` | Spalt Create↔Payload ist ein Halten |
| `test_a_reader_holding_the_latch_open_cannot_orphan_it` | Freigabe wartet den Leser aus |
| `test_a_refused_create_aborts_cleanly_instead_of_crashing` | verweigerter Create = Exit 2, kein Traceback |
| `test_a_refused_commit_aborts_cleanly_instead_of_crashing` | verweigerter Commit = Exit 2, kein Traceback |
| `test_a_flickering_competitor_cannot_evict_the_mutex_owner` | der Eigentuemer wird nicht mehr abgeschossen |

Dazu die Diagnose-Nachruestung im Wettlauf-Test: der Driver meldet Exit-Code
**und** stderr, die Assertion druckt beide Rennteilnehmer. Ohne diese Aenderung
waeren Defekt 2 und 3 nicht auffindbar gewesen — der Test meldete vorher nur
`[2, 2]` ohne jeden Grund.

Zwei bestehende Intent-Tests bekamen eine verkuerzte Wartefrist per
`monkeypatch`, damit sie nicht je 5 s leerlaufen. Verkuerzt wird das Budget,
nicht das Verhalten: beide pruefen weiterhin den fail-closed Ausgang.

## Vierter Befund — aus dem eigenen Umbau

Build #1205 lief erstmals seit #1203 bis zum Ende durch; die Unit-Stage war
gruen. Rot wurde das Quality Gate mit **genau einem** neuen Befund:
`python:S3776`, Cognitive Complexity 19 > 15 in `_claim_intent` — entstanden
durch meinen eigenen Umbau, weil die Warteschleife Probe-Kadenz, Frist und Poll
gleichzeitig in verschachtelten Zweigen trug.

Behoben durch Zerlegung (`_wait_out_the_latch`, `_sleep_until_spent`), nicht
durch Unterdrueckung: kein NOSONAR, kein Rule-Exclude, keine Gate-Aufweichung.

**Korrektur 2026-08-02 (Codex-INFO).** Die urspruengliche Aussage „Verhalten und
Reihenfolge unveraendert" war **falsch**. `_sleep_until_spent` liest die
monotone Uhr **neu**; vorher wurde fuer die Fristpruefung der vor der Probe
ermittelte Zeitpunkt wiederverwendet. Ueberschreitet die Probe selbst die Frist,
bricht die neue Fassung **frueher** ab. Sachlich besser, aber eben nicht
identisch. Unveraendert geblieben ist nur, dass eine gerade uebernommene Klinke
den Schlaf ueberspringt. Danach Lastnachweis erneut 0/150.

## Stand am Ende von Runde 1

Build **#1206** (Revision `2f9cdb15`) gruen. Quality Gate an der Quelle
nachgeprueft statt am Build-Status: `status OK`, neue Violations 0, neue
CRITICAL 0, Coverage neuer Code 89,8 % (Schwelle 80), Duplikate 0,29 %,
Security Hotspots 100 % reviewed — und **0 offene Issues insgesamt** auf `main`.

Damit war auch die Pipeline wieder frei: seit #1203 hatte dieser Defekt die
Unit-Stage und mit ihr SonarQube und das Quality Gate blockiert.

**Was hier fehlte:** ein unabhaengiges Review. Gruene CI ist kein
Abbruchkriterium. Der Abschluss beruhte allein auf Maschinenpruefung plus
eigenem Urteil — genau deshalb wurde die Story am 2026-08-02 auf
`in_progress` zurueckgesetzt.

# Runde 2 (2026-08-02) — Codex-Review: landefaehig NEIN

Das erste unabhaengige Codex-Review wies den gelandeten Stand mit **6 ERROR,
1 WARNING, 1 INFO** zurueck. Der Kern der Kritik war dreimal derselbe: **eine
Norm wurde geschrieben und im selben Commit gebrochen.** Alle acht Punkte sind
an der Wurzel behoben.

## F1 (ERROR) — endgueltig gescheiterte Freigabe meldete weiter Erfolg

`_remove_owned_file` lieferte `False`, und **kein** Aufrufer wertete das aus:
der Lauf druckte einen unstrukturierten `[WARNING]` auf stderr und beendete mit
`[units] OK` und Exit 0, obwohl `RUN.mutex` oder `RUN.mutex.intent` liegen
blieben und bis zum TTL-Ablauf (600 s) jeden weiteren Schreiber blockierten.
Das widersprach FK-78 §78.4 woertlich und erfuellte die Severity-Semantik nicht:
ein WARNING ohne Owner und ohne Folgeauftrag ist im Effekt ein ignorierter
Befund.

**Behoben an der Wurzel.** `_remove_owned_file` liefert jetzt den Grund des
Scheiterns statt eines stillen Booleans, und **jeder** Aufrufer wertet ihn aus.
Nicht ausgefuehrte geschuldete Loeschungen sammelt `_OwedEffects`; `_finish`
macht daraus einen **blockierenden ERROR-Befund im FK-78-Envelope**. Der Befund
benennt die liegengebliebene Datei, dass sie bis zum TTL-Ablauf jeden weiteren
Schreiber blockiert und manuell entfernt werden muss, und dass die Mutation
**moeglicherweise bereits gelandet** ist.

Bewusst als **Finding** und nicht als `incomplete_reason`: die Freigabe laeuft
im `finally` von `main()`, lange nachdem der Ausgang der Mutation feststeht.
`complete` bleibt `True`, der Report „wrote 4 unit(s)" bleibt stehen, der
bereits berechnete Befund wird nicht ueberschrieben — eine gelandete Mutation
wird nicht nachtraeglich als „nicht passiert" ausgegeben. Exit ist 1 (Findings)
bzw. bleibt 2, wenn der Lauf ohnehin INCOMPLETE war.

Zusaetzlich meldet die Freigabe jetzt auch den Fall, dass sie die Klinke fuer
den Release gar nicht erst bekommt und der **Mutex** deshalb liegen bleibt —
aber nur, wenn er noch unsere Nonce traegt. Ein uebernommener Mutex ist kein
Orphan und erzeugt keinen Befund.

## F2 (ERROR) — gescheitertes Payload-Write hinterliess eine leere Klinke

Nach erfolgreichem `O_CREAT|O_EXCL` gehoert die Klinke uns — es gab aber keinen
Cleanup-Pfad, wenn `write`/`close` scheitert. Die leere Datei blieb liegen und
war fuer jeden Folgelauf eine frisch gehaltene Klinke, die er bis zum Greifen
des mtime-Fallbacks auswartete, also eine volle TTL lang.

**Behoben.** `_settle_fresh_latch` entfernt die soeben angelegte Klinke wieder
und gibt den Anspruch regulaer fail-closed zurueck. `_write_fresh_latch` haelt
die beiden Fehlermodi sauber auseinander: scheitert `os.fdopen` selbst, hat es
den Descriptor nie uebernommen und muss ihn schliessen; scheitert erst das
`write`, gehoert der Descriptor bereits dem `with`-Block, und ein zweites
`close` wuerde eine fremde Datei treffen. Scheitert auch das Entfernen
endgueltig, greift F1.

## F3 (ERROR) — Read-then-Unlink konnte eine lebende Klinke loeschen

Compare-before-delete ist Lesen-dann-Loeschen und damit selbst nicht atomar.
FK-78 fuehrte das als „benannte Grenze" und nannte die belastbare Aufloesung
selbst. Deklarieren macht aus einer verletzten Kerninvariante keine korrekte
Implementierung.

**Behoben mit einem OS-Advisory-Lock** auf `RUN.mutex.intent.lock`
(`fcntl.flock` bzw. `msvcrt.locking`). Randbedingungen wie beauftragt:

- Lesen → Ablaufpruefung → erneute Identitaetspruefung → `unlink` laufen
  vollstaendig unter dem Lock (`_reclaim_expired_intent`, `_release_intent`).
- Die Lockdatei wird **nie** geloescht und traegt keinen Zustand.
- `O_CREAT|O_EXCL` bleibt Schiedsrichter des Anspruchs; der Lock serialisiert
  **nur** den Aufraeumpfad. Der Geltungsbereich wurde nicht erweitert.
- Beschraenktes Warten: die geschuldete Freigabe wartet bis
  `FILE_EFFECT_RETRY_SECONDS` und faellt danach fail-closed aus (mit Befund
  nach F1). Das opportunistische Einsammeln versucht den Lock **einmal** und
  laesst die Klinke sonst in Ruhe — wer den Lock haelt, fuehrt genau diesen
  Abschnitt gerade aus. Damit kommt kein neuer Timing-Wert hinzu.
- Der Lock wird nur ueber den kurzen Aufraeumabschnitt gehalten, nie ueber ein
  Warten; der Prozesstod gibt ihn frei.

Cross-Platform: die `sys.platform`-Verengung steht **inline** in
`_try_advisory_lock` und `_drop_advisory_lock`, nach dem Vorbild von
`installer/mcp_conformance/process.py`. `mypy src --strict` ist fuer win32,
`--platform linux` und `--platform darwin` sauber.

Vorab am lebenden System **gemessen**, nicht angenommen: `msvcrt.locking` sperrt
Byte 0 auch bei leerer Datei (Region jenseits EOF), und zwei Handles **im selben
Prozess** kollidieren — sonst waeren die Thread-basierten Tests wertlos.

FK-78 §78.4 fuehrt den Punkt jetzt als **geloest**, nicht mehr als Grenze. Was
als Rest bleibt, ist einzeln ausgeschrieben: Lock nicht bekommen (fail-closed,
nichts Falsches geloescht), Leser blockiert das `unlink` ueber die ganze Frist
(jetzt mit ERROR-Befund benannt), Netz-Dateisysteme ohne verlaessliche
Bereichssperre (Betriebsvoraussetzung), dauerhaft liegende Lockdatei (Absicht).

## F4 (ERROR) — Decision Record behauptete eine Ratifikation, die es nicht gab

**Behoben.** §5 heisst jetzt „Herkunft — was freigegeben ist und was nicht" und
trennt drei Klassen: (a) vom PO freigegeben ist die **Loesungsrichtung aus der
Story** (Raender 2.1, 2.3, 2.5); (b) vom Orchestrator gesetzt, dem PO
offengelegt, **Ratifikation ausstehend** sind die Raender 2.2, 2.4, 2.6, 2.7 und
die FK-93-Aenderungen; (c) offen ist die Ratifikation von (b). Der Satz „eine
Vorlage ist keine Ratifikation" steht ausdruecklich im Record.

Rand 2.4 ist zusaetzlich ueberarbeitet, weil F1 sein Verhalten aendert: „als
WARNING gemeldet" ist durch „blockierender ERROR-Befund im Envelope, niemals
Exit 0 und niemals OK" ersetzt, mit expliziter Korrekturnotiz, dass die
urspruengliche Umsetzung genau die stille Erfolgsmeldung war, die derselbe Rand
verbietet.

## F5 (ERROR) — verpflichtende Pre-Merge-Laeufe W2/W3

Siehe „Nachweise Runde 2". Die Ueberbehauptung „alle Konzept-Gates gruen" aus
Runde 1 bezog sich nur auf die statischen Gates.

## F6 (ERROR) — die Tests bewiesen ihre eigenen Aussagen nicht

- **Bounded-Test:** prueft jetzt eine **Obergrenze**. Ein Rettungs-Timer gibt
  die Klinke nach 10 s frei, damit eine unbegrenzte Implementierung
  *terminiert* statt die Suite haengen zu lassen — sie wird dann rot, sowohl an
  `nonce is None` als auch an der Obergrenze. Mit Fix: 0,2 s.
- **Flicker-Test:** hat eine **Startbarriere** (der Eigentuemer startet erst,
  wenn der Mitbewerber die Klinke tatsaechlich haelt) und zaehlt **beide**
  Richtungen der Kollision: der Eigentuemer muss mindestens einmal gewartet
  haben, der Mitbewerber muss die Klinke mindestens einmal besetzt vorgefunden
  haben. Ohne diese Zaehler waere der Test auch dann gruen, wenn der Hauptlauf
  alle vier Ansprueche vor der ersten Kollision abgeschlossen haette.
- **Zwei-Prozess-Test:** beide Rennteilnehmer melden jetzt **Haltezeitraeume**
  fuer Klinke und Mutex. Die Intervalle sind bewusst **konservativ innen**
  gemessen (Start nach dem Claim, Ende vor der Freigabe), sodass ein erkannter
  Ueberlapp immer eine echte Verletzung ist und nie ein Messartefakt. Der Test
  schliesst damit Gleichzeitigkeit im kritischen Abschnitt aus statt nur den
  Endzustand zu inspizieren, und er prueft zusaetzlich, dass **beide** Prozesse
  die Klinke ueberhaupt erreicht haben (sonst beweist das Rennen nichts).
- **Regressionstests fuer F1, F2, F3** sind neu.

Die vorhandenen `monkeypatch`-Eingriffe auf `INTENT_WAIT_SECONDS`, `os.open` und
`os.replace` sind unveraendert geblieben.

## F7 (WARNING) — FK-93-Abgrenzung

**Kriterium statt Einzelfall.** FK-93 hat einen neuen Abschnitt **§93.0
„Aufnahmekriterium"**: extern wahrnehmbare Werte gehoeren in den Katalog, weil
ein Betreiber sie am Verhalten bemerkt und gegen sie diagnostiziert; reines
internes Tuning bleibt im Code. Ausdruecklich festgehalten: **Abwesenheit eines
vergleichbaren Werts ist kein Argument.**

Neuer Abschnitt **§93.9a** in der Tabellenform der benachbarten „Fest im
Code"-Abschnitte (`Parameter | Default | Quelle | FK | Kapitel`) mit den drei
Werten: TTL von `RUN.mutex`/`RUN.mutex.intent` (600 s), Wartefrist auf eine
lebende fremde Klinke, Wiederholungsfrist geschuldeter Datei-Wirkungen. Poll-
Intervall und Probe-Kadenz bleiben ausdruecklich draussen, mit Begruendung. Die
alte, nicht tragfaehige Begruendung im Decision Record §3 ist ersetzt.

## Invarianten in Runde 2 — unveraendert

`O_CREAT|O_EXCL` bleibt der Schiedsrichter. Compare-before-delete bleibt auf
jedem Pfad (jetzt zusaetzlich serialisiert). TTL-basierte Uebernahme,
Fencing-Token-CAS und Heartbeat bleiben. Ein abgelaufenes Intent wird weiter
**sofort** uebernommen. Ein lebender fremder **Mutex** bleibt fuer jeden
Mitbewerber ein harter Abbruch (`test_two_processes_racing_a_live_mutex_both_abort`
bleibt `[2, 2]`). Dem Mutex-Eigentuemer wird die Klinke nicht erlassen. Keine
Unterdrueckung: kein NOSONAR, kein Rule-Exclude, kein unerklaertes
`noqa`/`type: ignore`, keine Gate-Aufweichung, keine abgeschwaechten Tests.

## Mutationsnachweis Runde 2

Jeder Eintrag: Fix an der Wurzel zurueckgedreht → Test rot; wiederhergestellt →
Test gruen. Alle sieben Mutationen einzeln gefahren.

| # | Mutation | Rot geworden |
|---|----------|--------------|
| M1 | `_finish` druckt wieder `[WARNING]` auf stderr statt einen Befund zu erzeugen | `..._never_reported_as_success` (Exit 0), `..._structured_finding_in_the_envelope` (leere `findings`) |
| M2 | `_settle_fresh_latch` entfernt die leere Klinke nicht mehr | `test_a_failed_latch_payload_write_gives_the_latch_back` |
| M3 | `_reclaim_expired_intent` ohne Advisory-Lock | `test_the_latch_cleanup_section_is_mutually_exclusive` (zweiter Aufraeumer trat ein) |
| M4 | `_release_intent` ohne Advisory-Lock | `..._cannot_get_the_cleanup_lock_reports_the_orphan`, `test_the_cleanup_lock_is_a_pure_serialization_device` |
| M5 | Wartebudget wird nie verbraucht (unbegrenztes Warten) | `test_the_wait_budget_ends_in_a_fail_closed_refusal` — terminierte nach 10,3 s ueber den Rettungs-Timer |
| M6 | lebende fremde Klinke wird sofort aufgegeben (Urspruengsdefekt) | `test_a_live_latch_is_waited_out_instead_of_lost`, `test_a_flickering_competitor_cannot_evict_the_mutex_owner` |
| M7 | lebender fremder Mutex darf uebernommen werden | beide Zwei-Prozess-Tests, und zwar **an der neuen Ueberlapp-Assertion**: „two processes held the mutex concurrently: mutex[…] vs mutex[…]" |

M7 belegt, dass die neue Gleichzeitigkeits-Erkennung wirklich greift und nicht
nur der Exit-Code geprueft wird.

## Konzept-Delta Runde 2

- **FK-78 §78.3** (Layout): `RUN.mutex.intent` (fehlte bisher, obwohl §78.4 es
  normativ verlangt) und `RUN.mutex.intent.lock` ergaenzt.
- **FK-78 §78.4**: Advisory-Lock normiert; geschuldete Loeschung = blockierender
  ERROR-Befund statt WARNING; Eigentum an der frisch angelegten Klinke; die
  „benannte Grenze" ist als **geloest** umgeschrieben, mit einzeln
  ausgeschriebenem Rest.
- **FK-93 §93.0/§93.9a**: Aufnahmekriterium + drei Werte.
- **Decision Record**: Raender 2.6/2.7 neu, Rand 2.4 korrigiert, §3 und §5 neu,
  Betroffenheitsmatrix nachgezogen.
- `reference-integrity-baseline.yaml`: FK-78-Zeilennummer 878 → 939.
- `.gitignore` und das deployte `gitignore-fragment.txt`: `RUN.mutex.intent`
  und `RUN.mutex.intent.lock` ergaenzt (die Lockdatei wird nie geloescht und
  waere sonst dauerhaft untracked; `RUN.mutex.intent` fehlte im Fragment
  ebenfalls, `RUN.mutex` dort auch).

## Nachweise Runde 2

Alle Kommandos ueber `.venv\Scripts\python`, Basis `474a97bd`.

**Lastnachweis (AC 2).** `bash <scratchpad>/ag3179_load.sh <log>` — unveraendertes
Skript, 8 CPU-Brenner + 150 isolierte Laeufe des Zwei-Prozess-Wettlauftests.
Ergebnis: **`TOTAL RED: 0 / 150`**. Die Quelle wurde waehrend des Laufs nicht
angefasst; die Brenner-Prozesse sind danach abgeraeumt (kontrolliert).

**Statische Gates — alle gruen.**

```
[concept-frontmatter]      OK: 90 docs, all lints passed
[formal-spec]              OK: 192 documents, 1802 ids, 2344 references
[concept-code-contracts]   OK: no truth-boundary contract violations
[PASS] concept-reference-integrity: 0 error(s), 55 report(s)
[PASS] concept-decision-record:     0 error(s)
[architecture-conformance] OK: no architecture contract violations
```

Die Zeilennummer des FK-78-Eintrags in `reference-integrity-baseline.yaml`
wanderte durch die Textaenderung von 878 auf 939 und ist nachgezogen; ohne das
meldete das Gate `STALE_BASELINE` **und** einen neuen Treffer.

**Lint und Typen.** `ruff check src tests` → `All checks passed!`.
`mypy src --strict` → `Success: no issues found in 1032 source files`, ebenso
mit `--platform linux` und `--platform darwin`. Die Advisory-Lock-Funktionen
sind der Grund, warum die drei Laeufe hier nicht kosmetisch sind.

**Volle Suite.** `pytest` → **10948 passed, 0 failed, 14 skipped**.

**Korrektur einer Fehlmeldung des Umsetzers** (gefunden bei der
Orchestrator-Gegenpruefung): Der Umsetzer meldete „4 failed" und stufte sie als
Bestandsdefekt ein, gegengeprueft per `git stash` auf `474a97bd`. Beides war
falsch. Die vier Fehlschlaege waren ein Artefakt **seiner Aufrufumgebung** — er
rief `pytest` aus einer Shell ohne `sh` im PATH. Seine Gegenprobe lief in
derselben Umgebung und hat damit den eigenen Artefakt reproduziert statt ihn zu
widerlegen. Eine Gegenprobe, die die verdaechtige Variable mitschleppt, beweist
nichts.

Mit `sh` im PATH laufen alle 76 Tests der betroffenen Datei gruen.

Der Restbefund ist kleiner, aber echt: `tests/unit/installer/test_ag3_176_vectordb_integration.py`
ruft `subprocess.run(["sh", ...])` und setzt damit `sh` im PATH voraus. Auf der
Linux-CI faellt das nie auf, auf einer Windows-Entwicklermaschine je nach Shell
schon. Als **WARNING an AG3-176 gespiegelt**, nicht stillschweigend uebergangen.

Ohne diese vier: alle 21 Tests in `test_mutex_race.py` gruen, `tests/contract`
komplett gruen (1222), `tests/unit/concept_toolchain` komplett gruen.

**W2 (pre-merge, LLM-gestuetzt).**
`check_concept_authority_prose.py --mode pre-merge --base 474a97bd` — Laufzeit
rund drei Stunden ueber den lokalen LLM-Hub (alle vier Backends gesund).
Ergebnis: **40 Befunde, alle `UNAUTHORIZED_SCOPE_ASSERTION`, alle in FK-93.**

**FK-78 und der Decision Record — die eigentlichen normativen Aenderungen
dieser Story — haben null Befunde.**

Die 40 verteilen sich so:

| Abschnitt | Befunde | von AG3-179 verursacht? |
|---|---|---|
| §93.6 Risikopunkte | 8 | nein (unveraendert) |
| §93.7 LLM-Evaluator | 8 | nein (unveraendert) |
| §93.8 Structural Checks | 11 | nein (unveraendert) |
| §93.9 Lock-Dateien | 5 | nein (unveraendert) |
| **§93.9a Mutex/Klinke** | **8** | **ja (neu)** |

Alle 40 sind dieselbe Befundklasse: FK-93 traegt `authority_over: [defaults]`
und `defers_to: []`, waehrend jede Katalogzeile einen Wert wiederholt, dessen
normativer Owner ein anderes Dokument ist. Das ist eine **Modellierungsluecke
des gesamten Katalogs**, die AG3-179 nur sichtbar gemacht hat: FK-93 kam durch
diese Story zum ersten Mal in eine Pre-Merge-Range.

**Triage.** Die **acht** Befunde aus §93.9a sind regelkonform **baselined**
(`concept/_meta/authority-prose-baseline.yaml`, je Eintrag mit konkreter
Begruendung: Katalogzeile ohne eigenen Normsatz, normativer Owner in Spalte
`Kapitel` = 78.4). Maschinell gegengeprueft: die acht Baseline-Keys treffen
exakt die acht gemeldeten Befunde, es bleiben 32 aktive.

Die **32** Bestandsbefunde sind **bewusst NICHT baselined**. Sie zu triagieren —
egal ob durch scope-qualifizierte `defers_to`-Kanten in FK-93 oder durch 32
Baseline-Eintraege — ist eine normative Entscheidung ueber ein cross-cutting
Autoritaetsdokument und liegt ausserhalb von AG3-179. Hier gilt „stoppen und
melden" statt heimlich verengen. **W2 ist damit nicht gruen, und das wird auch
nicht behauptet.** (W2 ist laut AGENTS.md ausdruecklich kein blockierendes
Push-Gate.)

Der in `status.yaml` als offen gefuehrte W2-Parserdefekt (Praeambel „Worked for
29s" vor dem JSON, markdown-escapte Unterstriche) ist **nicht** erneut
aufgetreten: er wurde bereits mit `8473ae84` (AG3-176) behoben, indem der
`\_`-normalisierte Zweig ebenfalls alle drei Extraktionskandidaten probiert.
Dieser Lauf lief ohne `EVALUATION_PARSE_FAILURE` durch.

**W3 (pre-merge, LLM-gestuetzt).**
`check_concept_scope_consistency.py` mit den sechs betroffenen
`authority_over`-Scopes (FK-78: `concept-incubation-technical`,
`incubator-artifact-schemas`, `promotion-closure`, `projection-manifest-format`,
`concept-toolchain`; FK-93: `defaults`).

- **Versuch 1** brach nach 3 von 12 Partitionen ab:
  `HUB_UNREACHABLE ... W2 Hub epoch send failed for model='qwen'`, gefolgt vom
  daraus abgeleiteten `INCOMPLETE_SWEEP completed=3 expected=12`. Das ist ein
  transienter Transportfehler, kein inhaltlicher Befund — `llm_health` meldete
  unmittelbar danach alle Backends wieder `ok`.
- **Versuch 2** brach **identisch** ab: derselbe Fehler, dasselbe Backend,
  exakt bei `completed=3 expected=12`. Damit ist er **reproduzierbar und nicht
  transient**.
- **Diagnose statt Rateschleife.** Der Befund ist dem Scope-Set
  `concept-toolchain` zugeordnet. Um zu trennen, ob der W3-Mechanismus
  grundsaetzlich scheitert oder nur eine bestimmte Partition, wurde ein
  gezielter Lauf ueber die **zwei Scope-Sets gefahren, die meine Aenderungen
  tragen** (`defaults` fuer FK-93, `concept-incubation-technical` fuer FK-78):
  `scope_sets=2, partitions=4, completed=4` — **vollstaendiger Sweep, kein
  INCOMPLETE**. Der Mechanismus funktioniert; die Blockade sitzt in einer
  Partition des `concept-toolchain`-Sets.

**Dieser Lauf hat einen echten Befund geliefert — und zwar einen von mir
verursachten:**

```
[ERROR] SCOPE_CONTRADICTION 93_standardwerte_schwellwerte_timeouts.md#93-9-lock-dateien
  scope='defaults' model=gemini
  Abschnitt 93.9 behauptet, dass automatische Lock-Freigaben durch TTL entfallen
  und Locks ausschliesslich ueber offizielle Pfade beendet werden. Abschnitt
  93.9a definiert jedoch eine explizite TTL von 600 Sekunden fuer die
  Mutex-Lock-Dateien 'RUN.mutex' und 'RUN.mutex.intent'.
```

Das ist **korrekt und nicht wegzudiskutieren**: mein neuer §93.9a stand
unmittelbar neben einer Zeile, die genau das Gegenteil sagt. **Behoben statt
baselined** — §93.9 gilt ausschliesslich fuer **Story-Locks** (Kapitel 02, FK-02)
und sagt das jetzt in Prosa und im Zeilentext; §93.9a grenzt sich
spiegelbildlich ab. Die FK-02-Regel selbst ist unveraendert; praezisiert ist nur
ihr Geltungsbereich. Im Decision Record als Matrixzeile nachgezogen.

**Gegenprobe nach dem Fix:**

```
concept-scope-consistency: PASS (scope_sets=2, partitions=4, completed=4, errors=0, reports=0)
```

Damit ist der Befund per Vorher/Nachher belegt: vorher genau ein
`SCOPE_CONTRADICTION`, nachher PASS bei identischem Sweep-Umfang.

**Restliche vier Scope-Sets** (`incubator-artifact-schemas`,
`promotion-closure`, `projection-manifest-format`, `concept-toolchain`) — vier
Anlaeufe, zwei klar getrennte Fehlerbilder, **keines davon in AK3-Code**:

Die Partitionierung wurde lokal ohne Hub nachgerechnet (deterministisch):

```
scope                             chunks  parts  Partitionsgroessen (Zeichen)
concept-incubation-technical          42      3  [29841, 35202, 2386]   <- lief durch
defaults                              16      1  [9786]                 <- lief durch
concept-toolchain                     32      2  [35666, 21209]         <- blockiert
incubator-artifact-schemas            32      2  [35666, 21209]         <- blockiert
projection-manifest-format            32      2  [35666, 21209]         <- blockiert
promotion-closure                     32      2  [35666, 21209]         <- blockiert
```

Die vier blockierten Sets sind **inhaltlich identisch** (dieselben 32 Chunks,
dieselben zwei Partitionen); es ist also **eine** Partition, die blockiert, nicht
vier verschiedene Probleme.

1. **`HUB_UNREACHABLE ... send failed for model='qwen'`** — reproduzierbar in
   zwei Laeufen, einmal als 4. von 12 Partitionen (`completed=3`), einmal als
   1. von 8 (`completed=0`). Die groesste je erfolgreich gesendete Partition
   misst 35202 Zeichen, die scheiternde 35666. Das ist eine Grenze im
   qwen-Adapter des Hubs, also in einem **externen Dienst**.
2. **Mit `--partition-max-chars 24000`** (identischer Inhalt, nur in mehr und
   kleinere Stuecke geschnitten — keine Verengung des Sweeps) kam der Transport
   durch, der Sweep brach aber sofort ab mit
   **`INVALID_EVALUATION_RESPONSE: reported quote is absent from '<chunk-id>'`**:
   ein Backend lieferte ein Zitat, das nicht woertlich im Chunk steht. Die
   Verbatim-Pruefung ist richtig und fail-closed — sie faengt genau die
   Halluzination ab, fuer die sie da ist.

**Der zweite Punkt legt eine echte Robustheitsluecke in UNSEREM Code offen** und
wird hier benannt, nicht umgangen: `collect_scope_findings`
(`tools/concept_governance/scope_execution.py`) wertet jede Partition
**genau einmal** aus und hat **keinen Retry**. W2 behandelt dieselbe Klasse von
Modell-Schlamperei mit zwei Versuchen und einem Korrektur-Prompt
(`evaluator.py`, `prompt.py` mit `retry=True`). Ein einziges nicht-woertliches
Zitat aus einem von vier Backends beendet damit den gesamten W3-Sweep. Diese
Asymmetrie zu beheben aendert den Vertrag eines Governance-Gates und gehoert
**nicht** in AG3-179 — sie ist als eigener Befund an den Auftraggeber gespiegelt
(WARNING), nicht stillschweigend liegengelassen.

**Ehrliche Gesamtaussage zu W3:** vollstaendig gesweept und **PASS** sind die
beiden Scope-Sets, die die Aenderungen dieser Story tragen — und genau dort hat
W3 auch den einen echten Befund geliefert, der prompt behoben wurde. Die vier
inhaltlich identischen Rest-Sets sind **blockiert, nicht gruen**, und werden
auch nicht als gruen ausgegeben. Es wurde weder `--limit` benutzt noch ein
Scope stillschweigend weggelassen.

# Runde 3 (2026-08-02) — zweites unabhaengiges Codex-Review

Das Review hat den Stand von Runde 2 erneut mit **landefaehig: nein**
zurueckgewiesen (6 ERROR, 3 WARNING). Der Advisory-Lock und alle sechs
Zusatzentscheidungen aus Runde 2 wurden dabei ausdruecklich **bestaetigt** und
sind unangetastet geblieben. Behoben sind in dieser Runde E1, E2, E3 und E5
sowie zwei **PO-Entscheidungen**, die waehrend der Runde eingegangen sind: ein
eigener Exit-Code fuer die gescheiterte Aufraeumwirkung, und die **Streichung
von E4**.

## RUECKNAHME: die Umfangsverengung bei W3

Der Bericht von Runde 2 hat den Pflichtumfang von W3 nachtraeglich auf die zwei
erfolgreichen Scope-Sets verengt („die beiden Scope-Sets, die die Aenderungen
dieser Story tragen"). **Das wird hiermit zurueckgenommen.** Die Verengung war
nicht zulaessig: bei einer Aenderung an `semantic_gate.py` und seinem
FK-78-Vertrag ist `concept-toolchain` offensichtlich betroffen — und genau
dieses Scope-Set war blockiert. Der Pflichtumfang **waren alle sechs**
betroffenen Scope-Sets; was davon nicht durchlief, war ein offener Befund und
kein verkleinerter Auftrag.

Diese Rueckname gilt unabhaengig davon, dass der Sweep fuer diese Story
inzwischen ausgesetzt ist (siehe unten): die **falsche Behauptung** wird
korrigiert, nicht durch die Aussetzung ersetzt.

## AUSGESETZT: die W2/W3-Pre-Merge-Pflicht fuer diese Story (PO-Entscheidung 2026-08-02)

Der PO hat die Qualitaetssicherung grundsaetzlich neu ausgerichtet: weg vom
LLM-Hub, an den Konzeptanteile geschickt werden in der Hoffnung auf saubere
Modellantworten, hin zur Harness-Bridge mit nativen KI-Agenten. Fuer diese Story
folgt daraus:

- **W3 wird nicht mehr bis zum vollstaendigen Sweep gejagt.** Der Ist-Stand ist
  unten praezise dokumentiert; nichts davon wird als gruen ausgegeben.
- **„W2 vollstaendig gruen" ist kein Abnahmekriterium mehr.** W2 wurde trotzdem
  gefahren und das Ergebnis wird unten berichtet und eingeordnet.
- **E3 bleibt vollstaendig im Auftrag** — mit der Praezisierung des PO: der
  Wurzelfix am FK-93-Autoritaetsmodell ist **nicht** deshalb zu machen, damit
  W2 gruen wird, sondern weil das fehlende Deferral-Modell eine **eigene
  Modellierungsschuld** ist. Sie ueberlebt jeden Umbau der Pruefmechanik: ein
  Katalog, der Autoritaet ueber fremde Werte beansprucht, ohne die Kanten zu
  erklaeren, ist auch dann falsch, wenn ihn kein LLM mehr prueft.

**Das ist eine bewusst dokumentierte Ausnahme, kein Uebergehen.** Der
Unterschied: ein Uebergehen waere, den Nachweis wegzulassen und nichts zu sagen;
hier ist die Pflicht benannt, die Aussetzung ist begruendet, ihr Urheber ist
benannt, und der offene Rest steht mit Fehlermodus und Reproduzierbarkeit da.
Im Decision Record ist es als Rand 2.4c festgehalten.

## E1 (ERROR) — „Datei fehlt" und „Datei ist unlesbar" waren dasselbe

`load_mutex_state` / `load_intent_state` liefern `None` sowohl fuer eine
**fehlende** als auch fuer eine **vorhandene, aber nicht lesbare oder
ungueltige** Datei — samt Issues, die verworfen wurden. Alle vier
compare-before-delete-Stellen (`_delete_own_mutex`, `_blocked_release`,
`_release_intent`, `_record_blocked_intent_release`) haben beides gleichgesetzt
und den zweiten Fall als „schon erledigt" verbucht. Ein Lesefehler beim finalen
Re-Read von `RUN.mutex` liess den Lauf mit Exit 0 und „OK" enden, waehrend die
Datei liegenblieb — und beim Mutex ist diese Klemme **permanent**, weil
`_take_over_mutex` ein nicht validierbares Payload abweist, statt es nach TTL zu
uebernehmen.

**Behoben an der Wurzel** durch eine explizite Klassifikation
(`_Ownership`: `OURS` / `FOREIGN` / `GONE` / `UNVERIFIABLE`):

- Nur `OURS` erlaubt ein Loeschen.
- `GONE` wird nur behauptet, wenn die Abwesenheit **beweisbar** ist
  (`_file_is_absent`: `FileNotFoundError` ja, jeder andere `OSError` nein).
  `Path.exists` waere hier falsch — es antwortet bei Rechte- und I/O-Fehlern
  ebenfalls `False` und haette die Verwechslung eine Ebene tiefer wieder
  eingebaut.
- `UNVERIFIABLE` wird **nie ungeprueft geloescht** und **nie als erledigt
  verbucht**: es wird zur geschuldeten, nicht erledigten Wirkung mit demselben
  blockierenden ERROR-Befund. **Die Issues des Laders sind die Begruendung** und
  werden nicht mehr verworfen.
- Der Befund benennt die Blockadedauer wahrheitsgemaess: `_Orphan.permanent`
  trennt die TTL-begrenzte Klemme (gueltige Datei, Intent mit mtime-Rueckfall)
  von der **permanenten** beim nicht validierbaren `RUN.mutex`.

Konzept nachgezogen: FK-78 §78.4 (neuer normativer Block „‚Weg' und ‚nicht
pruefbar' sind zwei verschiedene Antworten", vier nummerierte Regeln) und der
Decision Record (Rand 2.4b).

**Regressionstests fuer beide Dateien**, je mit Mutationsnachweis:

| Test | Deckt |
|---|---|
| `test_an_unverifiable_mutex_is_never_deleted_and_never_reported_as_success` | Mutex, End-to-End ueber die CLI inkl. Envelope, „PERMANENTLY", Lader-Diagnose |
| `test_an_unverifiable_latch_is_never_deleted_and_never_silently_released` | Intent, `_release_intent` |
| `test_a_release_that_cannot_claim_the_intent_reports_an_unverifiable_mutex` | Mutex, `_blocked_release` |
| `test_a_blocked_intent_release_reports_an_unverifiable_latch` | Intent, `_record_blocked_intent_release` |
| `test_only_a_file_not_found_error_proves_absence` | die Beweisregel selbst |
| `test_a_provably_absent_file_is_never_an_orphan` | Gegenprobe: „weg" bleibt still |

## E2 (ERROR) — der Release-Pfad war nicht gegen seine eigene Regression getestet

Neu: `test_the_release_section_is_mutually_exclusive` — derselbe **gestoppte**
Interleaving-Test wie fuer den Reclaim, aber ausdruecklich ueber
`_release_intent()`. Ein Releaser wird zwischen Identitaetspruefung und `unlink`
angehalten; waehrenddessen darf kein zweiter Aufraeumer in den Abschnitt.

**Mutationsnachweis mit genau der vom Review benannten Mutation** (Advisory-Lock
erwerben und sofort wieder freigeben, danach erst lesen und loeschen):

```
=== E2 target test ===
FAILED tests/unit/concept_toolchain/test_mutex_race.py::test_the_release_section_is_mutually_exclusive
1 failed in 1.65s
=== other release tests (must stay green) ===
4 passed in 2.15s
```

Die vier bestehenden Release-Tests (`..._cannot_get_the_cleanup_lock...`,
`..._pure_serialization_device`, `test_cleanup_never_removes_a_newly_claimed_intent`,
`test_a_reader_holding_the_latch_open_cannot_orphan_it`) bleiben unter der
Mutation **gruen** — genau das war der Befund.

## E3 (ERROR) — FK-93-Autoritaetsmodell an der Wurzel repariert

Das Review hat recht: kein False Positive. FK-93 trug `authority_over:
[defaults]` und `defers_to: []`, waehrend jede Katalogzeile einen anderswo
besessenen Wert wiedergibt. Die acht Baseline-Eintraege aus Runde 2 haben diese
Luecke in ihrer eigenen Begruendung benannt — eine Baseline ueber eine bekannte
Modellierungsluecke ist Unterdrueckung.

**Behoben:**

1. **34 scope-qualifizierte `defers_to`-Kanten** auf **18 Owner-Dokumente**
   (34 verschiedene Scopes, keine Dublette), je Katalogabschnitt auf den
   tatsaechlichen Owner der wiedergegebenen Werte und jede mit konkreter
   Begruendung: FK-02, FK-03, FK-10, FK-11, FK-13, FK-20, FK-21, FK-24, FK-33,
   FK-35, FK-41, FK-42, FK-50, FK-55, FK-68, FK-78, DK-03, DK-11.
2. **Neuer §93.0.1 „Autoritaet des Katalogs — Nachschlageort, nicht
   Normquelle"**: macht die Kante zur Pflegeregel, damit die Luecke nicht
   zurueckkehrt. Ausdruecklich: die Spalte `Kapitel` ersetzt die Kante nicht.
3. **Doppelte Ownership beseitigt:** §93.6 erklaerte sich selbst zur
   „normativen FK-93-Sollwert-Quelle" fuer die Risikopunkte — dieselbe Tabelle
   fuehrt FK-35 (§35.3). Die Behauptung ist entfernt; Normquelle ist FK-35.
4. **Falscher Kapitelverweis korrigiert:** §93.4 zeigte auf „Kapitel 14", das es
   nicht gibt; Telemetrie/Budget gehoert FK-68.
5. **Die acht Baseline-Eintraege sind entfernt**; `authority-prose-baseline.yaml`
   ist wieder leer, mit einer Notiz, warum sie entfernt wurden.

Die drei Werte aus §93.9a bleiben unveraendert im Katalog — sie erfuellen das
Aufnahmekriterium.

> **Stand ueberholt (Runde 4).** Die Zahlen oben beschreiben den Stand nach
> Runde 2. Runde 4 hat eine Kante ergaenzt (DK-10 als Wert-Owner der
> Review-Minima und Groessenklassen) und §93.0.1 differenziert, weil die
> Behauptung „jede Zeile hat einen fremden Owner" fuer §93.5a und §93.9a
> nachweislich falsch war. Aktuell: **35 Kanten auf 19 Owner-Dokumente, 35
> verschiedene Scopes**. Siehe Runde 4, R4.

**Grenze des heutigen Modells, benannt statt umgangen:** eine `defers_to`-Kante
auf ein `_meta`-Dokument ist im Frontmatter-Vertrag **nicht moeglich** (der Lint
kennt nur Contract-Dokumente als Ziele; `FK-00` ist als Index/Appendix
ausgeschlossen). §93.0.1 ist deshalb bewusst so formuliert, dass er nur eine
Anforderung von FK-93 an sich selbst (Scope `defaults`) aufstellt und keine
fremde Regel wiederholt. Das ist als Beobachtung gemeldet, nicht als Fix
kaschiert.

## E4 (W3-Retry) — vom PO GESTRICHEN, Arbeit verworfen

E4 war beauftragt und **war fertig implementiert**, als der PO am 2026-08-02
umgesteuert hat: die Qualitaetssicherung wird grundsaetzlich umgebaut — weg vom
LLM-Hub, an den Konzeptanteile geschickt werden in der Hoffnung auf saubere
Modellantworten, hin zur Harness-Bridge mit nativen KI-Agenten, denen von aussen
nur Leitplanken, Ziele und Nachweispflichten vorgegeben werden. In den
Retry-Vertrag des heutigen W3 zu investieren, waere Arbeit an einem Mechanismus,
der ohnehin ersetzt wird.

**Alles vollstaendig zurueckgebaut** (`git checkout` auf `02a89fd9`);
`tools/concept_governance/scope_execution.py` ist unangetastet. Verworfen wurde:

| Verworfen | Umfang |
|---|---|
| `scope_execution.py` | Retry, `_classify_with_one_correction`, `_sweep_partition`, `SCOPE_EVALUATION_ATTEMPTS`, `attempts` an `ScopeSweepError` |
| `scope_port.py`, `scope_evaluator.py`, `scope_transport.py` | `retry`-Parameter durchgereicht |
| `scope_prompt.py` + Prompt-Asset | `<!-- RETRY_CORRECTION -->`-Block, Marker-Vertrag, neuer SHA-Pin |
| `test_scope_execution.py` (neu, 8 Faelle) | geloescht |
| `test_scope_evaluator.py`, `helpers.py` | Aenderungen zurueckgenommen |
| `2026-08-02-w3-bounded-correction.md` (neuer Decision Record, 171 Zeilen) | geloescht |
| `konzept-konsistenz-governance.md` §6, Record 2026-07-14 §2, `AGENTS.md` | zurueckgenommen |
| 4 Mutationsnachweise (E4-M1 bis M4) | hinfaellig |

Grobe Groessenordnung: rund ein Fuenftel des Aufwands dieser Runde. Der Befund
selbst (W3 hat keinen Retry, W2 schon) bleibt damit **offen und unbehoben** —
bewusst, per PO-Entscheidung, nicht uebersehen.

**Was aus E4 NICHT verworfen wurde und warum:** die Reparatur der
Markdown-Escapes im Response-Parser (siehe unten). Sie ist kein Retry und keine
Vertragsaenderung, sondern ein Bugfix an einem Gate, das heute laeuft; sie wurde
von einem echten W2-Lauf erzwungen, nicht von E4. Sie beruehrt beide Parser,
weil beide denselben Defekt trugen. Wenn der Auftraggeber auch das verworfen
haben will, ist es ein Einzeiler — ich melde es als Entscheidung, statt es
stillschweigend mitlaufen zu lassen.

## E5 (WARNING) — Exit-1-Dokumentation

Alle Stellen nachgezogen; durch die PO-Entscheidung unten ohnehin neu
formuliert: `semantic_gate.py` (Modul-Docstring und `_mutation_problem`),
`test_mutex_race.py`, der Decision Record und `status.yaml`.

## PO-Entscheidung 2026-08-02 — eigener Exit-Code fuer die gescheiterte Aufraeumwirkung

Der PO hat den Vorschlag aus Rand 2.4 **ratifiziert, mit einer Aenderung**:
eine endgueltig gescheiterte geschuldete Loeschung meldet nicht Exit 1, sondern
einen eigenen, reservierten Code.

**Vergebene Zahl: `4`.** Sie war im Vertrag frei (`0` PASS, `1` Befunde,
`2` fehlende Voraussetzungen/INCOMPLETE, `3` Usage) — geprueft an
`findings.py` und an allen Fundstellen von `EXIT_*` im Repo.

**Rangfolge, explizit festgelegt und getestet: `2` > `1` > `4` > `0`.** `4` ist
bewusst der schwaechste Code, denn er behauptet, die Arbeit sei erledigt; wuerde
er `1` oder `2` verdraengen, meldete er das faelschlich. Umgesetzt in
`findings.exit_code_with_owed_effect`, das den Exit-Code **vor** dem Anhaengen
der Orphan-Befunde entscheidet. Der Befund selbst steht in **jedem** Fall
unveraendert als blockierender ERROR-Eintrag im Envelope.

Tests: `test_a_failed_owed_deletion_has_its_own_exit_code`,
`test_a_real_finding_outranks_a_failed_cleanup`,
`test_a_missing_prerequisite_outranks_a_failed_cleanup`,
`test_owed_effect_exit_code_is_ranked_last` (direkt am Vertrag).

**Nachgezogene Konsumenten** (der Punkt „ein neuer Code, den ein Aufrufer als
unbekannten Fehler behandelt, waere nur die halbe Miete"):

| Konsument | Aenderung |
|---|---|
| `concept_toolchain/findings.py` | `EXIT_OWED_EFFECT`, `exit_code_with_owed_effect`, Modul-Docstring |
| `concept_toolchain/semantic_gate.py` | Modul-Docstring, `_finish`, neue Ausgabezeile `CLEANUP FAILED` |
| FK-78 §78.14 | Exit-Code-Vertrag inkl. Rangfolge und Abgrenzung zu `check.py` |
| FK-78 §78.4 | Verweis auf den eigenen Code beim gescheiterten Loeschen |
| Decision Record 2026-08-01 | neuer Rand 2.4a, Matrixzeilen, §5 Klasse (a2) |
| Skill-Bundle `concept-incubation-core` — `references/process-core.md` | Exit-Zeile der Toolchain-Uebersicht |
| Skill-Bundle `concept-incubation-core` — `SKILL.md` | Gate-Schritt: Exit 4 ist kein „unbekannter Fehler", Handlungsanweisung |

Weitere Konsumenten wurden gesucht und **nicht** gefunden: es gibt keine
Wrapper-Skripte, Hooks oder Orchestrator-Aufrufe, die die Exit-Codes von
`semantic_gate.py` auswerten; `check.py` teilt nur `exit_code()` und ist
unveraendert (es schuldet keine Wirkungen und liefert `4` nie).

## Zusaetzlich behoben — vom W2-Lauf selbst erzwungen

**Der W2-Parser starb an einem markdown-escapten Pipe.** Der erste W2-Lauf
dieser Runde brach mit **einem** blockierenden Befund ab:

```
[ERROR] EVALUATION_PARSE_FAILURE technical-design/78_concept_incubation_process.md#78-4-...-006
  model=chatgpt: response unparseable after 2 attempts:
  Invalid JSON: invalid escape at line 1 column 184
```

Ursache: unsere Konzeptprosa ist Markdown, und Markdown escaped die Pipes in
Tabellen (`\|`). Ein Modell, das so eine Tabellenzelle woertlich zurueckzitiert,
sendet `\|` **innerhalb** eines JSON-Strings — dort ist das kein Escape, sondern
ein Syntaxfehler. Der Parser normalisierte bisher genau **ein** Zeichen (`\_`,
behoben in AG3-176 mit `8473ae84`). Das war ein Symptomfix: die naechste
Tabellenspalte bringt das naechste Zeichen.

**Behoben an der Wurzel** in einem neuen, geteilten Modul
`tools/concept_governance/json_escapes.py`: jede Backslash-Sequenz, die JSON
**nicht** als Escape kennt, wird auf ihr blosses Zeichen reduziert; gueltige
Escapes — einschliesslich `\\` und `\uXXXX` — werden **zuerst** gematcht und
unveraendert gelassen, damit ein echt escapter Backslash nie faelschlich
gefressen wird. Ein still korrumpiertes Zitat waere schlimmer als ein
abgelehntes, weil es durchgeht.

**Beide Gates gezogen, nicht nur das kaputte:** W3 (`scope_parser.py`) trug
denselben `\_`-Sonderfall und liest dieselben Tabellen; nur eines der beiden zu
reparieren haette die identische Falle im anderen stehen gelassen.

Der Repair aendert nur die **Form**: er wird als zusaetzlicher Parse-Kandidat
angeboten, und das reparierte Ergebnis muss weiterhin das strikte Schema
erfuellen. Eine inhaltlich falsche Antwort bleibt abgelehnt.

Tests: neu `tests/unit/tools/concept_governance/test_json_escapes.py`
(12 Faelle, bewusst mit `chr(92)` statt String-Literalen geschrieben — bei einem
Thema, das ausschliesslich aus Backslash-Zaehlerei besteht, wuerde ein selbst
falsch escaptes Literal das Falsche pruefen und dabei richtig aussehen), plus
zwei Faelle in `test_parser.py`. Mutationen: Rueckbau auf die
`\_`-Sonderbehandlung → 2 rot; naiver Repair, der auch gueltige Escapes frisst →
8 rot.

## Zusaetzlich behoben — nicht beauftragt, aber blockierend

**Der Flicker-Test war flaky.** `test_a_flickering_competitor_cannot_evict_the_mutex_owner`
zaehlte Kollisionen, die der Scheduler liefern musste. Gegenprobe auf dem
**unveraenderten** Stand `02a89fd9`: 1 von 8 Laeufen rot
(`collisions["count"] > 0` schlug fehl). Damit war „volle Suite 0 failed" nicht
verlaesslich erreichbar, und ein Kontenachweis, der auf Glueck beruht, beweist
ohnehin nichts.

Behoben, ohne die Aussage abzuschwaechen — beide Richtungen der Konkurrenz
werden jetzt **erzwungen** statt beobachtet: der Mitbewerber haelt seine erste
Klinke, bis der Eigentuemer nachweislich gewartet hat, und waehrend der
Eigentuemer die Klinke haelt, wird aus seinem eigenen kritischen Abschnitt ein
konkurrierender `O_CREAT|O_EXCL` versucht, der scheitern **muss**. Zusaetzlich
prueft der Test jetzt, dass niemand die Klinke stiehlt. 8 von 8 Laeufen gruen.

## Nachweise Runde 3

Alle Kommandos ueber `.venv\Scripts\python`, volle Suite ueber die Bash-Shell
mit `sh` im PATH (`/usr/bin/sh`) — die Umgebungsfalle aus Runde 2 ist damit
ausgeschlossen, nicht nur vermutet.

**Volle Suite.** `pytest` → **10982 passed, 0 failed, 14 skipped** (725 s).
Dieser Lauf ist der letzte **vollstaendige**; er enthaelt alle Aenderungen
dieser Runde ausser dem Rueckbau von E4 und wurde noch mit laufender
Container-Laufzeit gefahren.

**Einschraenkung des Abschlusslaufs — benannte Luecke, kein „gruen":** waehrend
der Arbeit migriert der PO die Infrastruktur dieser Maschine; das Laufwerk mit
der Docker-Installation wird geloescht und die Container-Laufzeit ist
absichtlich heruntergefahren. Der abschliessende Lauf **nach** dem E4-Rueckbau
lief deshalb ohne sie:

```
10410 passed, 40 skipped, 356 errors in 615.78s
FAILED: 0
```

**Alle 356 Errors haben genau eine Ursache**, maschinell gegengeprueft (alle
356 `ERROR at setup`-Bloecke geparst): die Session-Fixture
`postgres_container_url` aus `tests/fixtures/postgres_backend.py` findet keine
Container-Laufzeit und schlaegt fail-closed fehl. **Bloecke mit irgendeiner
anderen Ursache: 0.** Es gibt **null** `FAILED`.

Die dadurch nicht ausgefuehrten Postgres-gestuetzten Contract-, Integrations-
und E2E-Tests beruehren AG3-179 **nicht**: die Story aendert
`concept_toolchain/semantic_gate.py`, `concept_toolchain/findings.py` und
`tools/concept_governance/`; keiner dieser Pfade hat eine
Postgres-Abhaengigkeit. Zudem ist der E4-Rueckbau ein `git checkout` auf den
committeten Stand, fuegt also nichts hinzu, was sie beruehren koennte.
**Belegt ist das damit trotzdem nicht — es steht hier als Luecke, nicht als
gruen.** Der letzte **vollstaendige** Lauf (10982 passed, 0 failed) deckt alles
ausser dem Rueckbau ab.

**Fehler meinerseits, offengelegt:** als der erste Lauf mit 537 Errors kippte,
habe ich die Ursache korrekt als „Container-Laufzeit unten" erkannt — und sie
dann **selbst wieder hochgefahren**, um den Nachweis zu bekommen. Das hat die
laufende Migration des PO aktiv behindert. Auf seinen Hinweis sofort
zurueckgenommen: Lauf abgebrochen, Engine heruntergefahren, Nachweis ohne
Container wiederholt. Richtig waere gewesen, die weggebrochene Umgebung zu
**melden** statt sie zu reparieren.

**Korrektur 2026-08-02 (Codex-Review Runde 3, W2).** Die urspruengliche Fassung
dieses Absatzes behauptete „verifiziert (0 verbleibende Prozesse)" **ohne
Kommando und ohne Log** — also genau die Art Behauptung, die dieser Bericht
sonst zurueckweist. Der Selbstbericht ist entsprechend abgeschwaecht. Was
tatsaechlich belegt ist, stammt aus einer **unabhaengigen Gegenpruefung des
Orchestrators** (`Win32_Process`, gefiltert auf die Brenner-Kommandozeile):
**0 Brenner-Prozesse, 0 Docker-Prozesse**. Das ist der Beleg — nicht die
Selbstauskunft des Umsetzers.

**Lint und Typen.** `ruff check src tests` → `All checks passed!`.
`mypy src --strict` → `Success: no issues found in 1032 source files`, ebenso
mit `--platform linux` und `--platform darwin`.

**Statische Konzept-Gates — alle gruen** (`PYTHONPATH=src`):

```
[concept-frontmatter]      OK: 90 docs, all lints passed. Bounded-context layer: active.
[formal-spec]              OK: 192 documents, 1802 ids, 2344 references
[concept-code-contracts]   OK: no truth-boundary contract violations
[PASS] concept-reference-integrity: 0 error(s), 55 report(s)
[PASS] concept-decision-record:     0 error(s)
[architecture-conformance] OK: no architecture contract violations
```

Die wandernde FK-78-Zeilennummer in `reference-integrity-baseline.yaml` ist
erneut nachgezogen (939 → 965).

**Lastnachweis (AC 2).** `bash <scratchpad>/ag3179_load.sh <log>` — unveraendertes
Skript, 8 CPU-Brenner + 150 isolierte Laeufe des Zwei-Prozess-Wettlauftests:

```
TOTAL RED: 0 / 150
```

Der erste Anlauf dieses Nachweises wurde **verworfen und wiederholt**: ich hatte
bei Lauf 16 einen Docstring in `semantic_gate.py` geaendert. Auch wenn ein
Docstring das Verhalten nicht aendern kann — ein Lastnachweis, waehrend dessen
die Quelle angefasst wurde, ist kein Nachweis. Der hier berichtete Lauf lief
vollstaendig auf dem eingefrorenen Stand; die Brenner-Prozesse sind danach
kontrolliert abgeraeumt (0 verblieben, verifiziert).

**W2 (pre-merge)** — `check_concept_authority_prose.py --mode pre-merge --base
474a97bd`, drei Anlaeufe, **kein vollstaendiger Lauf**. W2 ist fail-closed: der
erste Fehler beendet den Sweep, es gibt kein Teilergebnis.

| # | Abbruch bei | Code | Ursache |
|---|---|---|---|
| 1 | FK-78 §78.11, Chunk 024 | `EVALUATION_TRANSPORT_FAILURE` | grok: `paste error: DOM query 'get_editor_text' timed out on tab 1` |
| 2 | FK-78 §78.4, Chunk 006 | `EVALUATION_PARSE_FAILURE` | chatgpt: markdown-escaptes `\|` → `Invalid JSON: invalid escape` — **unser Defekt, behoben** (siehe oben) |
| 3 | FK-78 §78.4, Chunk 008 | `EVALUATION_TRANSPORT_FAILURE` | qwen: `lease_id ... not found in registry for slot 0` |
| 4 | FK-78 §78.10, Chunk 020 | `EVALUATION_TRANSPORT_FAILURE` | qwen: `WinError 10061` — Hub verweigerte die Verbindung |

**Einordnung, ohne Beschoenigung:**

- Von den vier Abbruechen ist **genau einer unsere Schuld** (#2), und der ist an
  der Wurzel behoben; nach der Behebung trat er nicht wieder auf.
- Die drei uebrigen sind **Infrastruktur**: Browser-Automation-Timeout,
  Hub-Lease-Registry, verweigerte Verbindung. Jeweils unmittelbar davor bzw.
  danach meldete `llm_health` alle Backends `ok`. Auffaellig und mitgemeldet:
  vor jedem Abbruch stehen ein oder mehrere
  `W2 Hub epoch release failed ... request timed out` — die Epoch-Rotation des
  Hubs ist bei langen Laeufen instabil.
- **Kein Lauf hat FK-93 erreicht.** Alle vier starben in FK-78, das alphabetisch
  davor liegt. Es gibt daher **keinen Beleg**, dass die 40
  `UNAUTHORIZED_SCOPE_ASSERTION` durch die neuen Kanten verschwunden sind, und
  ebenso wenig, dass die entfernten acht Baselines keine `STALE_BASELINE`
  ausloesen. **Das wird hier ausdruecklich nicht behauptet.** Was belegt ist:
  FK-78 hat bis zum jeweiligen Abbruchpunkt **null** inhaltliche Befunde
  geliefert.
- Weiteres Jagen ist per PO-Entscheidung eingestellt.

**W3 (pre-merge)** — **nicht erneut gefahren**, per PO-Entscheidung
(„kein Retry, kein Jagen nach einem vollstaendigen Sweep"). Der zuletzt
erhobene Ist-Stand aus Runde 2 gilt unveraendert weiter und wird hier ohne
Verengung wiedergegeben:

| Scope-Set | Stand | Fehlermodus | Reproduzierbar |
|---|---|---|---|
| `defaults` | **PASS** (1 Partition, 9786 Zeichen) | — | — |
| `concept-incubation-technical` | **PASS** (3 Partitionen) | — | — |
| `concept-toolchain` | **BLOCKIERT** | `HUB_UNREACHABLE` (qwen) auf der 35666-Zeichen-Partition | **ja**, 2 Laeufe identisch |
| `incubator-artifact-schemas` | **BLOCKIERT** | dieselbe Partition (inhaltlich identisches Set) | ja |
| `promotion-closure` | **BLOCKIERT** | dieselbe Partition | ja |
| `projection-manifest-format` | **BLOCKIERT** | dieselbe Partition | ja |

Zweiter Fehlermodus, bei kleinerer Partitionierung (`--partition-max-chars
24000`): der Transport kam durch, der Sweep brach an
`INVALID_EVALUATION_RESPONSE: reported quote is absent from '<chunk-id>'` ab —
ein nicht woertliches Zitat. Die Verbatim-Pruefung ist richtig und
fail-closed; was fehlte, war der Retry. **Dieser Befund bleibt offen und
unbehoben** (E4 gestrichen).

Die groesste je erfolgreich gesendete Partition misst 35202 Zeichen, die
scheiternde 35666 — eine Groessengrenze im qwen-Adapter des Hubs, also in einem
externen Dienst. Die vier blockierten Sets sind **inhaltlich identisch**
(dieselben 32 Chunks, dieselben zwei Partitionen): es ist **eine** Partition,
die blockiert, nicht vier verschiedene Probleme.

**Keine Verengung, kein `--limit`, kein weggelassener Scope. Nichts davon ist
gruen, und nichts davon wird als gruen ausgegeben.**

**Mutationsnachweise Runde 3** — je Fix zurueckgedreht, Zieltest rot,
wiederhergestellt gruen. Elf Mutationen einzeln gefahren (die vier
E4-Mutationen sind mit E4 hinfaellig geworden):

| # | Mutation | Ergebnis |
|---|---|---|
| E1-M1 | `_delete_own_mutex`: unverifizierbar = weg | rot |
| E1-M2 | `_release_intent`: unverifizierbar = weg | rot |
| E1-M3 | `_blocked_release`: unverifizierbar = weg | rot |
| E1-M4 | `_record_blocked_intent_release`: unverifizierbar = weg | rot |
| E1-M5 | Blockademeldung verspricht immer TTL-Freigabe | rot |
| E1-M6 | `_file_is_absent` via `Path.exists` statt `stat` | rot (siehe unten) |
| E2 | Cleanup-Lock erwerben und sofort freigeben, dann lesen+loeschen | rot; die vier Bestandstests bleiben gruen |
| X1 | Exit 4 auf Exit 1 zurueckgefaltet | rot |
| X2 | Exit 4 verdraengt Befunde und INCOMPLETE | 2 rot |
| P1 | Parser zurueck auf die `\_`-Sonderbehandlung | 2 rot |
| P2 | naiver Escape-Repair, der auch gueltige Escapes frisst | 8 rot |

**Zu E1-M6, offengelegt:** die erste Fassung dieses Tests hat die Mutation
**nicht** gefangen — auf Python 3.14 delegiert `Path.exists` an
`os.path.exists` und laeuft an einem gepatchten `Path.stat` vorbei. Der Test
wurde daraufhin auf die Entscheidungsregel selbst gezogen
(`test_only_a_file_not_found_error_proves_absence`) und faengt die Mutation
seitdem. Festgehalten, weil ein Mutationsnachweis, der beim ersten Versuch
durchgeht, genau hier haette uebersehen werden koennen.

## Beobachtungen ausserhalb des Auftrags (WARNING, nicht behoben)

- `mypy tools/concept_governance --strict` meldet **einen Bestandsfehler** in
  `tools/concept_ingester/discovery.py:243` (`tuple[str, bool, str]` vs.
  `tuple[str, str, str]`). Auf `02a89fd9` identisch reproduziert, also kein
  Regress dieser Runde; die Projektvorgabe ist `mypy src` und die ist gruen.
- `ruff check tools` meldet **einen Bestandsbefund** C901 in
  `tools/concept_compiler/architecture_conformance.py:1409` (Complexity 20).
  Ausserhalb der Projektvorgabe `ruff check src tests`, die gruen ist.

Beide gehoeren nicht in diese Story, werden aber nicht stillschweigend
liegengelassen.

## Offen

- **Codex-Review Runde 3** steht aus. Ohne dessen Abbruchkriterium ist die
  Story nicht fertig.
- **Ratifikation** der Raender 2.2, 2.6, 2.7, 2.4b und der FK-93-Aenderungen
  durch den PO (Decision Record §5, Klassen b und c).
- **Jenkins/Sonar** auf dem aktuellen HEAD — Orchestrator-Aufgabe nach dem
  Commit.
- **Offen und bewusst unbehoben** (PO-Entscheidung, siehe oben): W3 wertet jede
  Partition genau einmal aus und hat keinen Retry, W2 hat zwei Versuche mit
  Korrekturprompt. Der Befund faellt mit dem geplanten QS-Umbau weg oder muss
  dort neu gestellt werden.
- **Unbelegt** (kein Beleg, keine Behauptung): dass die 40
  `UNAUTHORIZED_SCOPE_ASSERTION` in FK-93 durch die neuen Kanten verschwinden.
  Kein W2-Lauf hat FK-93 erreicht; alle vier starben vorher in FK-78. Der
  Wurzelfix steht unabhaengig davon (eigene Modellierungsschuld), aber sein
  Effekt auf W2 ist nicht gemessen.
- **Infrastrukturbefund an den Auftraggeber:** die Epoch-Rotation des LLM-Hubs
  ist bei langen W2-Laeufen instabil (`Hub epoch release failed ... timed out`
  vor jedem der drei Transport-Abbrueche, danach Lease-Registry-Fehler bzw.
  `WinError 10061`). Drei von vier W2-Laeufen sind daran gescheitert.

---

# Runde 4 (2026-08-02)

Umsetzer: Worker unter Orchestrator-Auftrag nach dem **dritten** unabhaengigen
Codex-Review (Urteil: landefaehig nein — 5 ERROR, 2 WARNING).

**Die Story ist weiterhin NICHT fertig.** Behobene Findings sind kein
Abschluss; der Stand geht erneut ins Review.

## R1 (ERROR) — Der Mutex-Erwerb arbitrierte nicht exklusiv

**Der Befund ist berechtigt und er ist der schwerste der Story.**
`_acquire_mutex` fragte `Path.exists()` und schrieb danach per
`_atomic_write_bytes`. Dieselbe Existenzpruefung wird ein paar hundert Zeilen
weiter oben in `_file_is_absent` ausdruecklich als untauglich beschrieben, weil
sie bei Rechte- und E/A-Fehlern `False` liefert. Ein einziges fehlschlagendes
`stat` auf einem **lebenden fremden** Mutex genuegte, um ihn mit der eigenen
Nonce zu ueberschreiben — beim Erwerb wurde aus „nicht pruefbar" still „weg".
Das ist ein **Safety**-Defekt (zwei Schreiber behaupten gleichzeitig
Alleineigentum), kein Liveness-Defekt, und er ist aelter als diese Story.

**Behoben** in `semantic_gate.py`:

- `_create_or_take_over_mutex()` erzeugt den frischen Mutex per
  `os.open(..., O_CREAT|O_EXCL|O_WRONLY)`.
- `FileExistsError` fuehrt in den validierten Takeover-Pfad (unveraendert:
  Payload-Gueltigkeit, TTL, Fencing-Token-CAS, Identitaets-Re-Read).
- Jeder **andere** `OSError` ist fail-closed mit
  `cannot create RUN.mutex exclusively: ...`, Exit 2, kein Traceback.
- `_settle_fresh_mutex()` schliesst den Zwei-Schritt-Spalt: scheitert der
  Payload-Write, wird der Anspruch zurueckgegeben. Ein leerer `RUN.mutex` ist
  kein gueltiges Payload und wuerde nach Rand 2.4b **permanent** klemmen — der
  Orphan wird deshalb mit `permanent=True` gefuehrt.
- `_unreadable_mutex_problem()` wendet die `_Ownership`-Klassifikation aus
  Runde 2 auch hier an: „verschwunden" wird nur bei **beweisbarer** Abwesenheit
  behauptet, sonst gilt „vorhanden, aber nicht validierbar".

**Belege — 4 neue Tests, alle gegen die zurueckgedrehte Fassung rot:**

| Test | prueft |
|---|---|
| `test_a_failing_stat_never_makes_a_live_mutex_look_absent` | den Stat-Fehler: `exists()` liefert `False` auf einem lebenden fremden Mutex, Ergebnis Exit 2 und Datei byte-identisch |
| `test_the_fresh_mutex_claim_wins_the_name_before_it_has_a_payload` | die O_EXCL-Kollision: gestopptes Interleaving im Payload-Bau; der Mitbewerber muss den Namen belegt vorfinden |
| `test_a_refused_mutex_create_aborts_cleanly_instead_of_crashing` | Nicht-EEXIST-Fehler als regulaerer Fehlausgang; weder Mutex noch Klinke bleiben liegen |
| `test_a_failed_mutex_payload_write_gives_the_claim_back` | zurueckgegebener Anspruch; der naechste Lauf findet das Verzeichnis benutzbar |

Mutationsnachweis: `_create_or_take_over_mutex` auf die alte
`exists()`-Fassung zurueckgedreht, Ergebnis **4 von 4 rot**; wiederhergestellt,
Ergebnis gruen.

**Konzept nachgezogen:** FK-78 §78.4 schreibt den exklusiven Create fuer
`RUN.mutex` jetzt aus und benennt, warum ein Read-then-Create unzulaessig ist.
Das ist **keine Lockerung**, sondern die Einloesung einer Zusage, die FK-78 die
ganze Zeit gemacht hat (Record Rand 2.8).

## R2 (ERROR) — Ein nach TTL fortgesetzter Releaser loeschte den Mutex seines Nachfolgers

**Der Befund ist berechtigt.** Rand 2.6 hatte compare-before-delete an der
**Klinke** atomar gemacht; am **Mutex** blieb `_delete_own_mutex()`
Read-then-Unlink.

**Entscheidung und Begruendung — sie steht im Code, nicht nur hier.** Das
Review liess zwei Wege zu. Den Verlust der Klinke zu **verhindern** ist keiner:
ein eingefrorener Prozess kann keinen Heartbeat senden, und keine Frist
unterscheidet ihn von einem toten — genau das ist der Grund, warum die Klinke
ueberhaupt eine TTL hat. Verhindern hiesse, das Problem durch das Problem zu
loesen. Gewaehlt ist deshalb der zweite Weg, **Erkennung**: der fortsetzende
Halter weist seinen Anspruch erneut nach, bevor er wirkt. Die Begruendung steht
im Docstring von `_MutexGuard._delete_own_mutex` und in `_latch_lost_reason`.

**Warum der bereits vorhandene Advisory-Lock das richtige Mittel ist:** jedes
Einsammeln einer Klinke braucht ihn, und jede Mutex-Uebernahme braucht die
Klinke. Wer ihn haelt und darunter feststellt, dass die Klinke noch seine ist,
weiss damit, dass niemand sie einsammeln, niemand sie halten und niemand den
Mutex uebernehmen kann. Der Kern ordnet die beiden Ereignisse — nicht eine
Datei, die wir selbst loeschen muessten.

**Behoben:**

- `_coordination_intent()` gibt die Klinken-Nonce heraus (`Iterator[str]`); ein
  Abschnitt, der auf Basis der Klinke loescht, muss sie nachweisen koennen.
- `_delete_own_mutex(intent_nonce)` haelt den Cleanup-Lock ueber „Klinke noch
  unsere" **und** compare-before-delete als **einen** Abschnitt.
- Klinke verloren bedeutet: **nicht geloescht**. Ein fremder Mutex bleibt
  unberuehrt und **ohne** Befund (er ist nicht unsere Schuld); ein noch eigener
  wird zur geschuldeten, nicht erledigten Wirkung nach Rand 2.4.

**Belege — 2 neue Tests:**

| Test | prueft |
|---|---|
| `test_a_stalled_release_cannot_lose_its_latch_and_delete_the_successor` | gestopptes Interleaving: A haelt die ueber ihre TTL hinaus gehaltene Klinke I1, liest M1 und stockt vor dem `unlink`; B faehrt den **echten** `_acquire_mutex` (I1-Reclaim, I2-Erwerb, M2-Uebernahme) und muss fail-closed scheitern; A setzt fort und loescht nur M1 |
| `test_a_releaser_whose_latch_was_reclaimed_refuses_to_delete` | den Erkennungszweig in beiden Ausgaengen: fremder Nachfolger-Mutex bleibt und erzeugt keinen Befund; noch eigener Mutex bleibt und wird zum Befund |

Der Test faehrt bewusst `_delete_own_mutex` direkt statt `release()`:
`release()` wuerde hier eine **frische** Klinke holen, und eine frische Klinke
ist per Definition nicht einsammelbar — der Stall, auf den es ankommt, ist der,
der die **bereits gehaltene** Klinke ueberlebt hat. Genau daran waere die erste
Fassung dieses Tests vorbeigelaufen; korrigiert vor der Abnahme.

**Mutationsnachweis, zwei Stufen:**

- Lock **und** Klinken-Nachweis entfernt, Ergebnis **beide** Tests rot.
- Lock behalten, nur den Klinken-Nachweis entfernt, Ergebnis: der
  Erkennungstest rot, der Interleaving-Test bleibt gruen. Das ist die richtige
  Aufteilung — der Lock allein deckt das Interleaving, der Nachweis deckt den
  Fall, in dem die Klinke schon vorher weg war.

**Konzept nachgezogen:** FK-78 §78.4 (Advisory-Lock gilt fuer **jedes**
Loeschen anhand beobachteter Identitaet, Klinke wie Mutex; erneuter
Klinken-Nachweis normiert), Record Rand 2.9.

## R3 (ERROR) — Die Escape-Reparatur verfaelschte woertliche Evidenz

**Der Befund ist berechtigt und die Vorgaengerloesung war falsch.** `token[1:]`
entfernte **jeden** nicht anerkannten Backslash. Aus einer woertlich zitierten
Tabellenzelle mit markdown-escapten Unterstrichen und Zellentrenner wurde eine
Zelle ohne sie; aus dem Pfad `C:\Program` wurde `C:Program`.

**Behoben an der Wurzel:** ein nicht anerkannter Backslash wird **verdoppelt**
statt entfernt. Das macht denselben Text parsebar **und** laesst den dekodierten
Wert Zeichen fuer Zeichen identisch. Gueltige Escapes (`\\`, `\"`, `\n`,
`\uXXXX`) bleiben unberuehrt.

**Was dabei zusaetzlich zutage trat — und was ich daraus entschieden habe.**
Der Escape-Leak trifft nicht nur Werte, sondern auch **Schema-Schluessel**
(`chunk\_id`, `has\_normative\_statements`). Nur zu verdoppeln haette diese
Faelle gebrochen, die bisher funktionierten. Der Unterschied ist keine
Geschmacksfrage: in einem **Wert** kann ein Backslash Inhalt sein, in einem
**Schluessel** nie — die Antwortschemata sind geschlossene Vokabulare aus
`snake_case`-Bezeichnern, ein Schluessel ist niemals ein Zitat. Umgesetzt als
zwei getrennte Reparaturen:

- `repair_markdown_escapes()` — Textebene, verdoppelt, bewahrt Worttreue.
- `normalize_schema_keys()` — arbeitet auf dem **geparsten** Dokument, wo
  „Schluessel" eine strukturelle Tatsache und keine Regex-Vermutung ist, und
  entfernt den Backslash nur dort. Angewandt an der Validierungsnaht beider
  Parser (`parser.py`, `scope_parser.py`).
- Der Regex-Fallback in `parser.py` liest wieder den **Rohtext** und erkennt den
  Feldnamen auch in escapter Schreibweise (`_escapable()`), damit die erfasste
  Assertion woertlich bleibt.

**Belege:** die Tests, die den falschen Vertrag festschrieben, sind korrigiert
(`test_only_invalid_escapes_are_repaired` traegt jetzt eine Spalte `verbatim`;
`test_escaped_table_pipe_json_is_strictly_revalidated` erwartet die Zelle
woertlich statt entschaerft). Neu: die genaue Zelle des W2-Laufs vom 2026-08-02
als Wort-fuer-Wort-Roundtrip, ein Windows-Pfad, und ein abgeschnittenes `\u12`.
**Mutationsnachweis:** `token[1:]` wiederhergestellt, Ergebnis **10 rot**
(7 davon inhaltlich zur Worttreue); zurueckgedreht, Ergebnis 55 gruen.

**Abgrenzung, unveraendert gueltig:** das bleibt ein eigenstaendiger
Parser-Bugfix. Neu ist die Einordnung — es ist **kein neuer Normsatz**, sondern
die Wiederherstellung des bestehenden Vertrags „quote assertion text exactly"
(`tools/concept_governance/prompts/scope_consistency_v1.md`, `QuotedAssertion`),
Record Rand 2.11.

## R4 (ERROR) — FK-93 verwies auf Eigentuemer, die die Werte nicht normieren

**Der Befund ist berechtigt.** §93.0.1 behauptete, **jede** Zeile in
§93.1–§93.12 gebe einen anderswo normierten Wert wieder. Eine `defers_to`-Kante
auf einen Owner, der den Wert nicht fuehrt, bezeugt maschinenlesbar etwas
Falsches — schlimmer als die fehlende Kante davor.

**Vorgehen:** jeder Katalogwert wurde gegen `concept/` geprueft (Wert **und**
Config-Pfad/Parametername, dazu die `FK-XX-NNN`-Ids der FK-Spalte). Ergebnis je
Abschnitt:

| Abschnitt | Zeilen | Wert extern verankert? | gewaehlter Weg |
|---|---|---|---|
| §93.1 Pipeline-Konfiguration | 7 | ja, alle (FK-03 §3.4.2 und das `project.yaml`-Beispiel; Scaffold zusaetzlich in `formal-spec/installer/invariants.md`) | Wiedergabe, Kante bleibt |
| §93.2 Policy-Engine | 2 | ja (FK-33, FK-20, FK-03) | Wiedergabe |
| §93.3 VektorDB | 2 | ja (FK-13, FK-21, DK-10) | Wiedergabe |
| §93.4 Telemetrie und Budget | 2 | ja (FK-68, FK-30) | Wiedergabe |
| §93.5 Governance-Beobachtung | 3 | ja (FK-35, inkl. `window_size: int = 50` und `cooldown_s: int = 300`) | Wiedergabe |
| **§93.5a Permission-Runtime** | **5** | **nein — weder Wert noch Config-Pfad ausserhalb FK-93** | **FK-93 als Normquelle belassen, je Zeile ausgewiesen** |
| §93.6 Risikopunkte | 10 | ja, alle (FK-35 §35.3.2/3, fuenf zusaetzlich FK-68) | Wiedergabe |
| §93.7 LLM-Evaluator | 4 | ja (FK-11) | Wiedergabe |
| §93.8 Structural Checks | 5 | ja (FK-33, FK-35) | Wiedergabe |
| §93.9 Lock-Dateien | 1 | ja (FK-71, FK-02, FK-10, FK-04) | Wiedergabe |
| **§93.9a Mutex und Klinke** | **3** | **nein — FK-78 §78.4 fuehrt die Regeln, nennt aber keine Sekundenzahl** | **FK-93 als Normquelle belassen, je Zeile ausgewiesen** |
| §93.10 Review-Haeufigkeit | 3 | ja — aber **nicht** bei FK-24, dorthin zeigte die Kante ins Leere; Wert-Owner ist DK-10 §10.4 (auch DK-02, DK-05) | **Kante auf DK-10 ergaenzt**, FK-24-Begruendung praezisiert |
| §93.11 Failure Corpus | 6 | ja (FK-41, DK-07, FK-60/62) | Wiedergabe |
| §93.12 Story-Groessen | 5 | ja (DK-10 §10.4) — **die Wiedergabe wich ab** | **an DK-10 angeglichen** (M: „ein Modul" zu 1-2 Module; Dateispannen ergaenzt) |

**Umgesetzt:**

1. **§93.0.1 differenziert** in zwei Zeilenklassen — „Wiedergabe" (Regelfall)
   und „katalog-eigener Wert" (Ausnahme, in der Spalte `Normquelle`
   ausgewiesen). Neu ausdruecklich: eine Kante darf nur behaupten, was ihr Ziel
   wirklich besitzt; die Ausnahme wird benannt, nie stillschweigend genutzt;
   eine abweichende Wiedergabe wird an den Owner angeglichen, nicht umgekehrt.
2. **§93.5a und §93.9a** sind je Zeile als katalog-eigen ausgewiesen; ihre
   `defers_to`-Begruendungen benennen jetzt, was FK-42/FK-55/FK-78 wirklich
   besitzen (die **Regel**), und nennen FK-93 als Owner des **Werts**.
3. **Neue Kante DK-10 / `story-lifecycle`** als Wert-Owner der Review-Minima
   und der Groessenklassen.
4. **§93.12 an DK-10 §10.4 angeglichen.**
5. **Offene Schuld benannt statt umgewidmet:** die Config-Pfade `permissions.*`
   stehen in **keinem** Konfigurationsmodell, auch nicht in FK-03. §93.5a sagt
   das jetzt und weist die Luecke FK-03 zusammen mit FK-42/FK-55 zu.

**Zahl nachgezaehlt:** **35** scope-qualifizierte Kanten auf **19**
Owner-Dokumente, **35** verschiedene Scopes, keine Dublette.

## R5 (ERROR) — Der aktive Record erklaerte eigene geltende Norm fuer unbeschlossen

**Der Befund ist berechtigt:** Raender gleichzeitig „nicht beschlossen" und „in
der Norm" zu fuehren, ist keine eindeutige normative Wahrheit.

**Umgesetzt** (Abschnitt 5 des Records): jeder Rand einzeln gegen die drei
Bedingungen des Agentenmandats (`AGENTS.md`, PO-Ratifikation 2026-08-02)
geprueft, mit benannter Ankerstelle, als Tabelle im Record.

**Ergebnis — alle geprueften Raender sind vom Mandat gedeckt:**

| Rand | Ankerstelle | Ergebnis |
|---|---|---|
| 2.2 | FK-78 §78.4: exklusiver Create als Schiedsrichter plus mtime-Rueckfall | gedeckt |
| 2.4b | FK-78 §78.4: „ein Aufraeumen ohne Identitaetspruefung ist auf keinem Pfad zulaessig" | gedeckt |
| 2.6 | FK-78 §78.4 **vor** dieser Story: fuehrte die Luecke als „benannte Grenze" und nannte die Aufloesungen woertlich — „ein OS-Advisory-Lock (`fcntl.flock` bzw. `msvcrt.locking`) oder fail-closed manuelle Recovery" | gedeckt |
| 2.7 | exklusiver Create in §78.4 plus Rand 2.4, der **vom PO ratifiziert** ist | gedeckt |
| 2.8 (neu) | FK-78 §78.4 nennt den exklusiven Create fuer `RUN.mutex` seit jeher | gedeckt |
| 2.9 (neu) | Rand 2.6 plus „compare-before-delete auf jedem Pfad" | gedeckt |
| 2.10 (neu) | FK-93 §93.0 („auch wenn sie fest im Code stehen") plus `_meta/assertion-authority.md` | gedeckt |
| Abschnitt 3 (§93.0, §93.9a, §93.9) | FK-93 `authority_over: defaults` und der Titel; fuer §93.9a zusaetzlich FK-78 §78.4 als Regel-Owner | gedeckt |

Der Anker fuer 2.6 ist **woertlich** nachgeprueft (`git show 81f28cde:` auf
FK-78, Fassung vor der Story) — er ist nicht rekonstruiert, sondern zitiert.

Rand **2.11** faellt nicht unter das Mandat: er ist kein neuer Normsatz, sondern
die Wiederherstellung eines bestehenden Vertrags.

**Damit entfaellt die offene Vor-Merge-Ratifikation.** Kein Rand scheitert an
Anker, Widerspruchsfreiheit oder Domaenengrenze; **es ist nichts einzuholen.**
Der Record fuehrt unter (c) nur noch zwei inhaltlich offene Punkte, die
ausdruecklich **keine** Freigaben sind: ob die Sekundenwerte aus §93.9a
konfigurierbar werden sollen, und die FK-03-Schuld bei den
`permissions.*`-Pfaden.

## W1 — Kantenzahl

`status.yaml` nannte **31**; nachgezaehlt waren es zum Zeitpunkt von Runde 2
**34** auf 18 Ziele — der Bericht nannte an anderer Stelle bereits 34/18, die
beiden Stellen widersprachen sich. Beide sind korrigiert und tragen jetzt den
Verweis auf den aktuellen Stand (**35 auf 19**). Weitere Fundstellen derselben
Zahl: keine. Die „32" an anderer Stelle im Bericht sind aktive W2-Befunde,
keine Kanten.

## W2 — „verifiziert (0 verbleibende Prozesse)"

Die Behauptung stand ohne Kommando und ohne Log da. Der Selbstbericht ist
abgeschwaecht; als Beleg zitiert ist die **unabhaengige Gegenpruefung des
Orchestrators** (`Win32_Process`, gefiltert auf die Brenner-Kommandozeile):
0 Brenner, 0 Docker-Prozesse.

Fuer **diese** Runde eigenstaendig nachgemessen, mit Ausschluss der eigenen
PID: nach dem Lastlauf **0 Brenner-Prozesse, 0 Docker-Prozesse**.

## Nachweise Runde 4

**Tests.**

```
tests/unit/                            8798 passed, 40 skipped   (464 s)
tests/unit/concept_toolchain/           399 passed               (davon 6 neu)
tests/unit/tools/concept_governance/     55 passed               (davon 3 neu, 2 korrigiert)
```

**Lastnachweis (AC 2)** — `bash <scratchpad>/ag3179_load.sh <log>`, 8 CPU-Brenner
plus 150 isolierte Laeufe des Wettlauf-Tests:

```
TOTAL RED: 0 / 150
```

Brenner danach abgeraeumt und gezaehlt **mit Ausschluss der eigenen PID**:
0 verbleibend.

**Lint und Typen.**

```
ruff check src tests                   All checks passed!
mypy src --strict                      Success: no issues found in 1032 source files
mypy src --strict --platform linux     Success: no issues found in 1032 source files
mypy src --strict --platform darwin    Success: no issues found in 1032 source files
```

**Statische Konzept-Gates** (`PYTHONPATH=src`) — alle sechs OK:
`check_concept_frontmatter` (90 docs), `compile_formal_specs` (192 Dokumente,
1802 Ids), `check_concept_reference_integrity`, `check_concept_code_contracts`,
`check_architecture_conformance`, `check_concept_decision_record`.

Die wandernde Zeilennummer in `reference-integrity-baseline.yaml` ist
nachgezogen (`78_concept_incubation_process.md` 965 zu 1006); ohne das meldete
das Gate `STALE_BASELINE` **und** einen unaufgeloesten Verweis.

**Keine Unterdrueckung:** kein NOSONAR, kein Rule-Exclude, kein neues
`noqa`/`type: ignore` ohne Begruendung am Ort, keine abgeschwaechte Assertion.
Alle neuen Unterdrueckungsmarker folgen dem in dieser Testdatei bereits
etablierten Muster (Zugriff auf private Namen als Testgegenstand,
Passthrough-Rueckgaben injizierter Funktionen).

## Nicht ausgefuehrt — benannte Luecken, nicht „gruen"

- **`tests/integration/`, `tests/contract/`, `tests/e2e/`** sind in dieser Runde
  **nicht** gefahren worden. Docker-Engine und die lokale Postgres-Datenbank
  sind wegen der laufenden Migration des PO absichtlich unten und wurden auf
  ausdrueckliche Anweisung **nicht** gestartet. Die Aenderungen dieser Runde
  liegen in `concept_toolchain/semantic_gate.py`, `tools/concept_governance/`
  und in Konzeptdokumenten; keiner dieser Pfade hat eine Datenbank- oder
  Container-Abhaengigkeit. **Belegt ist das damit nicht.**
- **`tests/unit/` selbst brauchte weder Docker noch Postgres** — 0 Failures,
  0 Errors, 40 Skips. Es gibt in dieser Runde also keinen Fehlschlag, der auf
  die Umgebung zurueckzufuehren waere; es gibt nur nicht gefahrene Ebenen.
- **Jenkins/Sonar** sind nicht erreichbar (bekannt, Migration).
- **Zwei Bestandsbefunde ausserhalb der Gate-Kommandos**, unveraendert und
  nicht von dieser Runde verursacht (auf dem sauberen Baum gegengeprueft):
  `ruff` C901 in `tools/concept_compiler/architecture_conformance.py:1409`
  (Komplexitaet 20 > 15) und ein `mypy`-Fehler in
  `tools/concept_ingester/discovery.py:243`. Beide liegen in `tools/`, das
  weder von `ruff check src tests` noch von `mypy src` erfasst wird. Gemeldet,
  nicht stillschweigend mitgenommen.

## Was nach Runde 4 offen bleibt

- **Codex-Review Runde 4** steht aus. Ohne dessen Abbruchkriterium ist die Story
  nicht fertig.
- **Nicht mehr offen:** die Ratifikation der Raender. Sie ist durch die
  Mandatspruefung erledigt (R5); nichts ist beim PO einzuholen.
- **Offen und bewusst unbehoben** (PO-Entscheidung Rand 2.4c): W3 wertet jede
  Partition genau einmal aus und hat keinen Retry.
- **Neu benannt, nicht in dieser Story geschlossen:** die Config-Pfade
  `permissions.*` fehlen im Konfigurationsmodell von FK-03.
- **Unbelegt** (unveraendert): der Effekt der FK-93-Kanten auf die
  `UNAUTHORIZED_SCOPE_ASSERTION`-Befunde von W2 ist nicht gemessen.

---

# Runde 5 (2026-08-02)

Umsetzer: Worker unter Orchestrator-Auftrag nach dem **vierten** unabhaengigen
Codex-Review (Urteil: landefaehig nein — 4 ERROR, 2 WARNING).

**Die Story ist weiterhin NICHT fertig.** Behobene Findings sind kein
Abschluss; der Stand geht erneut ins Review.

## Was Codex-Review Runde 4 gemeldet hat — vollstaendig

| # | Schwere | Gegenstand | Stand |
|---|---------|-----------|-------|
| E1 | ERROR | Klinken-Schutz griff nicht auf allen vier Wirkungspfaden | **behoben in Runde 4**, Commit `86f5f139` |
| E2 | ERROR | dieselbe Luecke auf dem zweiten Wirkungspfad | **behoben in Runde 4**, Commit `86f5f139` |
| R3 | ERROR | W2 verfaelscht woertliche Zitate bei **gueltigen** JSON-Escapes | **in dieser Runde behoben** |
| R4 | ERROR | Key-Normalisierung fuehrt widersprechende Felder still zusammen | **in dieser Runde behoben** |
| R5 | ERROR | FK-93 als eigene Normquelle (Rand 2.10) | **BLOCKIERT — wartet auf PO-Entscheidung** |
| R6 | WARNING | FK-93-Frontmatter widerspricht der neuen Autoritaetsregel | **BLOCKIERT — wartet auf PO-Entscheidung** |
| W-Datum | WARNING | neue Abschnitte auf `2026-08-03` datiert | **in dieser Runde bereinigt** |
| W-Doppel | WARNING | zwei verschiedene Abschnitte „Runde 3" | **in dieser Runde bereinigt** |

## R3 (ERROR) — Worttreue liess sich im Parser nicht beweisen

**Der Befund ist berechtigt, und Runde 4 hat ihn nur zur Haelfte behoben.**

Runde 4 hat die Escape-Reparatur worttreu gemacht: ein nicht anerkannter
Backslash wird verdoppelt statt entfernt. Damit war die Klasse der
**ungueltigen** Escapes erledigt — und genau dort endeten auch die Tests.

Der Reviewer hat die andere Haelfte reproduziert: ein woertlich aus einem Chunk
kopiertes `C:\new` ist **syntaktisch gueltiges JSON**, weil `\n` ein anerkanntes
Escape ist. Der rohe Kandidat wird deshalb **vor** jeder Reparatur akzeptiert,
und heraus kommt `C:` + Zeilenumbruch + `ew`. Es gibt keinen Syntaxfehler, an
dem irgendein Parser das merken koennte. Dieselbe Luecke erreicht man ganz ohne
Backslash: eine Paraphrase statt eines Zitats.

**Die Wurzel ist nicht der Parser, sondern die fehlende Pruefung.** W2 las die
Antwort und sah den Chunk nie wieder an. W3 tut seit AG3-159 genau das
Gegenteil: `scope_policy._validate_locus` verlangt, dass die gemeldete
Fundstelle im Chunktext vorkommt, und weist sie sonst fail-closed zurueck. W2
hatte denselben Vertrag im Prompt-Asset stehen — „ein kurzes woertliches Zitat
aus dem Abschnitt" — und setzte ihn nirgends durch.

**Behoben** in `tools/concept_governance/policy.py`: `_require_verbatim_quote()`
prueft jede gemeldete Assertion zeichengleich gegen `chunk.content` — kein
Whitespace-, kein Case-Normalisieren, exakt die Strenge von W3. Ein Verstoss ist
`EvaluationContractError`; `execution.py` bindet ihn an den Chunk und macht
daraus den benannten Befund `INVALID_EVALUATION_RESPONSE` — **derselbe Code, den
W3 fuer dieselbe Sache fuehrt** (`scope_execution.py`).

Das ist **keine Vertragsaenderung**. Der Vertrag stand im Prompt und im Modell;
neu ist allein, dass er durchgesetzt wird.

**Tests** (`tests/unit/tools/concept_governance/test_policy.py`, 4 neu) — drei
davon fahren die **ganze produktive Kette** (gepinnter Prompt, dreistufiger
Parser, Escape-Reparaturen, deterministische Policy) und skripten nur den
Transport, sind also die Bytes, die ein Modell wirklich geschickt hat:

- `test_a_valid_json_escape_corrupts_a_quote_without_any_syntax_error` — pinnt
  die Korruption selbst und belegt damit, **warum** keine Parser-Heuristik
  reicht.
- `test_a_quote_absent_from_the_chunk_is_rejected_fail_closed` — der
  reproduzierte Fall, jetzt `INVALID_EVALUATION_RESPONSE`, mit genau **einem**
  LLM-Aufruf: die Antwort **hat** geparst, der Defekt ist erst danach sichtbar.
- `test_a_correctly_escaped_verbatim_quote_stays_accepted` — Gegenprobe:
  gleicher Chunk, gleicher Backslash, korrekt escapt, keine Befunde.
- `test_a_paraphrased_assertion_is_rejected_like_a_corrupted_one` — dieselbe
  Regel faengt die Paraphrase ohne jeden Backslash.

## R4 (ERROR) — die Key-Normalisierung durfte nicht zusammenfuehren

`_strip_key_escapes()` schrieb normalisierte Schluessel ohne Kollisionspruefung
in ein `dict`. Im reproduzierten Fall trug ein Objekt `has_normative_statements`
mit `true` und dieselbe Bezeichnung markdown-escapt mit `false`; akzeptiert
wurde `false` — der Alias ueberschrieb die widersprechende Originalaussage,
still. In W3 ersetzt derselbe Mechanismus eine befuellte `contradictions`-Liste
durch einen Alias mit leerer Liste: ein Governance-Gate meldet PASS ueber
Evidenz, die ihm genannt wurde.

**Behoben an der Wurzel** in `json_escapes.py`. `normalize_schema_keys()`
normalisiert jetzt in einem `object_pairs_hook` und weist zwei Schluessel fuer
dasselbe Feld als `SchemaKeyCollisionError` zurueck. „Der letzte gewinnt" und
„der erste gewinnt" sind gleich willkuerlich; die Kollision ist ein **Befund**.

Zwei Dinge fielen dabei zusammen mit auf und sind mitbehoben:

1. **Der buchstaeblich doppelte Schluessel.** Zwei identische Schluessel
   brauchen gar keinen Alias — `json.loads` kollabiert sie von sich aus
   last-wins, und die Normalisierung war die einzige Stelle der Kette, die
   beide noch sieht. Derselbe Hook faengt beide Formen.
2. **Der zu breite `except ValueError`.** `SchemaKeyCollisionError` ist ein
   `ValueError`; der alte Handler haette den eigenen Befund verschluckt und den
   Kandidaten unveraendert weitergereicht. Jetzt wird nur
   `json.JSONDecodeError` als „ist kein JSON" behandelt.

Die Zurueckweisung laeuft ueber den **vorhandenen** Ablehnungspfad beider Gates:
in W2 wird sie zu `ResponseParseError` und damit zu `EVALUATION_PARSE_FAILURE`,
in W3 zu `ScopeResponseParseError` und damit zu `UNPARSEABLE_RESPONSE`. Kein
Traceback — genau der „ein Absturz traegt keine Aussage"-Defekt, den diese Story
am Mutex-Pfad behoben hat.

`parse_response()` ist dabei um `_first_valid()` herum neu geschnitten; die
beiden identischen Kandidaten-Schleifen waren vorher ausgeschrieben. Verhalten,
Reihenfolge der Kandidaten und Fehlertexte sind unveraendert.

**Tests** (7 neu): drei parametrisierte Kollisionsfaelle in **beiden**
Reihenfolgen plus den Alias-freien Doppel-Key, die W3-Form (`contradictions`
gegen einen Alias mit leerer Liste), eine Kollision in einem **verschachtelten**
Objekt und zwei Gegenproben (ein einzelner escapter Schluessel wird weiterhin
repariert; Nicht-JSON bleibt unveraendert). Dazu je ein Test pro Gate, dass die
Kollision als **benannte** Ablehnung ankommt statt als Traceback.

## R4 systematisch weitergezogen — jede Stelle mit derselben Begruendung

Die Begruendung von R4 lautet: *aus einer mehrdeutigen Antwort wird still eine
eindeutige, und niemand kann sehen, dass etwas verworfen wurde.* Diese
Begruendung endet nicht bei `json_escapes.py`. Geprueft wurde jede Stelle, an
der eine **LLM-Antwort** dekodiert wird:

| Stelle | Urteil |
|---|---|
| `tools/concept_governance/json_escapes.py` | **behoben** (Alias- und Literal-Kollision) |
| `tools/concept_governance/parser.py`, `scope_parser.py` | **behoben** (benannte Ablehnung statt Traceback) |
| `verify_system/llm_evaluator/structured_evaluator.py`, Stage 2 | **mitbehoben** — siehe unten |
| `verify_system/llm_evaluator/structured_evaluator.py`, Stage 3 | **ausgenommen und als WARNING benannt** — siehe unten |
| `verify_system/evidence/request_resolver.py::parse_preflight_response` | **ausgenommen**: die Antwort traegt kein Urteil und keine Evidenz, sondern die Bitte um **weiteren Kontext**; der Pfad degradiert ausserdem bewusst weich (leere Liste plus Log-Warnung) statt fail-closed. Diesen Vertrag zu verschaerfen ist eine Entscheidung seines Owners, kein Seiteneffekt dieser Story. |
| `integration_clients/multi_llm_hub/client.py` | **ausgenommen**: dekodiert den HTTP-Umschlag unseres **eigenen** Hub-Dienstes, nicht die Modellantwort. |
| alle uebrigen `json.loads` in `verify_system/` (Artefakte, Manifeste, Ledger, Budget-Zaehler) | **ausgenommen**: sie lesen Dateien, die unser eigener Code per `json.dumps` aus typisierten Modellen schreibt — ein doppelter Schluessel kann dort nicht entstehen. |
| `baseline.py` (`yaml.safe_load`) | **ausgenommen**: PyYAML kollabiert doppelte Mapping-Keys ebenfalls still, aber die Baseline ist eine **repo-eigene, reviewte** Datei und kein Fremdsystem-Output; `BaselineDocument.keys_must_be_unique` faengt die fachlich relevante Dublette bereits. Als Beobachtung benannt, nicht hier geaendert. |
| `scope_policy.evaluate_scope_policy` (`findings`-`dict`) | **ausgenommen**: dedupliziert **identische** Befunde ueber ihren vollstaendigen Schluessel; gleicher Schluessel heisst gleicher Befund, es geht keine Aussage verloren. |

**Mitbehoben — `structured_evaluator._stage2_extract_json`.** Dort dekodiert
`json.loads` die Layer-2-Bewertung. Ein Check-Objekt mit `status` zweimal — erst
`FAIL` mit Begruendung, dann `PASS` — kam als **PASS mit der Begruendung des
FAIL** an: ein still gekipptes Urteil in einem QA-Gate, exakt die Begruendung
von R4 an einer schwereren Stelle. Behoben mit demselben Mittel
(`_reject_duplicate_keys` als `object_pairs_hook`); Stage 2 verwirft den
Kandidaten, der Rest der dreistufigen Mechanik bleibt unangetastet.

**Ausgenommen und als WARNING benannt — Stage 3.** Der Regex-Rueckfall ist
**kein Decoder**, sondern eine dokumentierte Bergung aus Freitext: er sucht in
einem 550-Zeichen-Fenster um eine Check-Id den ersten `status`. Bei einer
mehrdeutigen Antwort nimmt er damit den **ersten** Wert — im obigen Beispiel
zufaellig den sicheren (`FAIL`), in umgekehrter Reihenfolge den unsicheren. Das
ist dieselbe Willkuer, aber sie laesst sich dort nicht mit derselben Regel
beheben: „zwei Werte fuer ein Feld" ist in Freitext nicht definiert, und das
Fenster ueberlappt regulaer den naechsten Check. Eine saubere Loesung aendert
den **Vertrag** des Stage-3-Rueckfalls (FK-11 §11.4.4, FK-34 §34.5.1) und
gehoert dessen Owner. Hier gemeldet, nicht stillschweigend mitgenommen — und
bewusst **nicht halb repariert**, weil eine halbe Verschaerfung wie eine ganze
aussieht.

## R3 systematisch weitergezogen — jede Stelle mit derselben Begruendung

Die Begruendung von R3 lautet: *eine als woertliches Zitat gemeldete Textstelle
wird nie mit ihrer Quelle verglichen.* Geprueft wurde jede Stelle, an der ein
LLM Evidenz **aus einem gelieferten Artefakt** zurueckmeldet:

| Stelle | Urteil |
|---|---|
| W2 `policy.evaluate_policy` (`NormativeAssertion.assertion`) | **behoben** |
| W3 `scope_policy._validate_locus` (`QuotedAssertion.assertion`) | **hatte die Pruefung bereits** — sie ist die Vorlage |
| W2-Regex-Rueckfall `_regex_response` | **abgedeckt**: seine Assertions laufen durch dieselbe Policy |
| `ContradictionGroup.explanation` (W3) | **ausgenommen**: freie Begruendung, kein behauptetes Zitat |
| `FormalizationCheck.reason` (P4-Triage) | **ausgenommen**: dito |
| `AuthorityFinding.assertion` / `BaselineEntry.assertion` | **ausgenommen**: konservieren ein bereits geprueftes Zitat als Schluessel; der Vergleich fand beim Erzeugen statt |
| `CheckResult.reason` / `.description` (Layer 2) | **ausgenommen**: Urteilsbegruendung in eigenen Worten; FK-34 verlangt dort kein Zitat, es gibt also keinen Vertrag durchzusetzen |
| FK-78 §78.14 (Ziel-Architektur Request-Pack/Receipt) | **geprueft, nichts zu tun**: die Rueckbindung ueber `chunk_digests[]` ist dort bereits normiert; Befundcodes des heutigen CLI zaehlt der Abschnitt nicht auf |

## R5 / R6 — BLOCKIERT, nicht von mir entschieden

Rand **2.10** des Decision Record („Der Wertekatalog darf Normquelle sein — aber
nur benannt") und das **FK-93-Frontmatter** (Zeilen 11–16) sind **unveraendert
geblieben**. Das Review weist die Konstruktion zurueck: der Vor-Story-Stand
bestimmte ausdruecklich das Gegenteil — ein nirgends sonst stehender Wert ist
eine Luecke **beim besitzenden Dokument** —, und eine Grundentscheidung zu
ersetzen ist keine Ausdetaillierung im Sinne des Agentenmandats. Dazu
widerspricht FK-93s eigenes Frontmatter der neuen Autoritaetsregel.

Das ist eine **Meta-Konzept-Entscheidung des PO**, keine Worker-Entscheidung.
Sie wird eingeholt; bis dahin bleibt der Stand wie er ist, ausdruecklich **ohne**
die Behauptung, er sei richtig.

**Folge fuer das formale Datums-WARNING:** das Datum in Rand 2.10
(`2026-08-03`) bleibt aus demselben Grund stehen. Es ist die **einzige**
verbliebene Fundstelle des falschen Datums, und sie steht nur deshalb noch dort,
weil der Rand eingefroren ist. Das ist bewusst und hier benannt, nicht
uebersehen.

## WARNING „Datum" — bereinigt

Sieben Fundstellen von `2026-08-03` gab es repo-weit (ausserhalb der
Verzeichnisse der parallel bearbeiteten Storys AG3-180 bis AG3-186). Alle
geprueft, sechs korrigiert:

```
concept/_meta/decisions/2026-08-01-...md:245   Rand 2.8      -> 2026-08-02
concept/_meta/decisions/2026-08-01-...md:267   Rand 2.9      -> 2026-08-02
concept/_meta/decisions/2026-08-01-...md:291   Rand 2.10     -> UNVERAENDERT (blockiert)
concept/_meta/decisions/2026-08-01-...md:316   Rand 2.11     -> 2026-08-02
stories/AG3-179-.../report.md:896              Korrektur     -> 2026-08-02
stories/AG3-179-.../report.md:1060             Ueberschrift  -> 2026-08-02
stories/AG3-179-.../status.yaml:275            Ueberschrift  -> 2026-08-02
```

Wer `2026-08-03` heute noch greppt, findet neben Rand 2.10 nur **Zitate** —
diesen Abschnitt, die Zaehlweise am Kopf des Berichts und die entsprechenden
Stellen in `status.yaml`. Keine davon datiert etwas.

## WARNING „doppelter Abschnitt" — bereinigt

Es gab zwei Abschnitte „Runde 3": den mit E1–E5 (zweites Review) und den mit
R1–R5 (drittes Review). Der zweite war falsch nummeriert; er ist **Runde 4** und
heisst jetzt so — samt „Nachweise Runde 4" und „Was nach Runde 4 offen bleibt".
Dasselbe in `status.yaml`.

Damit das nicht wiederkehrt, steht die Zaehlweise jetzt **einmal verbindlich am
Kopf dieses Berichts** („Zaehlweise der Runden"): Runde N ist eine Arbeitsrunde
und beantwortet Codex-Review Runde N−1; ein Review wird nie mit „Runde M" allein
bezeichnet. Ohne diese Regel war die Verwechslung nur eine Frage der Zeit — sie
ist ja schon zweimal passiert.

## Konzept-Delta Runde 5

Decision Record `2026-08-01-run-mutex-intent-bounded-wait.md`:

- **Rand 2.11a** (neu) — die Worttreue wird geprueft, nicht nur bewahrt.
- **Rand 2.11b** (neu) — zwei Schluessel fuer ein Feld sind ein Befund.
- **Rand 2.11** — die Feststellung „W2 prueft keine Worttreue" ist als
  historisch markiert und verweist auf 2.11a.
- **Betroffenheitsmatrix** — zwei Zeilen ergaenzt.
- **§5** — die Mandats-Feststellung deckt jetzt 2.11, 2.11a und 2.11b: alle drei
  betreffen denselben bestehenden Vertrag, keiner ist ein neuer Normsatz, es
  gibt also nichts zu ratifizieren.

Kein FK-Dokument geaendert. FK-78 §78.14 beschreibt die Ziel-Architektur der
Semantik-Gates und fuehrt keine Befundcodes des heutigen CLI — geprueft, nichts
nachzuziehen.

## Nachweise Runde 5

**Tests.**

```
tests/unit/                                  8852 passed, 14 skipped (490 s)
tests/unit/tools/concept_governance/           68 passed  (davon 13 neu)
tests/unit/verify_system/llm_evaluator/        41 passed  (davon  2 neu)
tests/contract/                              1228 passed              (67 s)
tests/integration/  -m "not requires_gh"      932 passed             (381 s)
```

Docker, Postgres und Weaviate liefen; `tests/contract/` und
`tests/integration/` sind damit erstmals seit Runde 3 wieder **gefahren** statt
als Luecke benannt.

**Lastnachweis (AC 2)** — `bash <scratchpad>/ag3179_load.sh <log>`, 8 CPU-Brenner
plus 150 isolierte Laeufe des Wettlauf-Tests, Quelle waehrend des Laufs nicht
angefasst:

```
TOTAL RED: 0 / 150
```

Brenner danach unabhaengig gezaehlt (`Win32_Process`, Filter auf die
Brenner-Kommandozeile, **mit Ausschluss der eigenen PID**): **0**.

**Lint und Typen.**

```
ruff check src tests                    All checks passed!
ruff check tools/concept_governance     All checks passed!
ruff check --select C901 (src tests
  tools/concept_governance)             All checks passed!
mypy src --strict                       Success: no issues found in 1029 source files
mypy src --strict --platform linux      Success: no issues found in 1029 source files
mypy src --strict --platform darwin     Success: no issues found in 1029 source files
mypy tools/concept_governance           0 Fehler im Modul (1 Bestandsfehler in
                                        tools/concept_ingester/discovery.py:243)
```

**Statische Konzept-Gates** (`PYTHONPATH=src`) — alle sechs OK:
`check_concept_frontmatter` (90 docs), `compile_formal_specs` (192 Dokumente,
1802 Ids), `check_concept_reference_integrity` (0 errors, 55 reports),
`check_concept_code_contracts`, `check_architecture_conformance`,
`check_concept_decision_record`.

Die wandernde Zeile in `reference-integrity-baseline.yaml`
(`78_concept_incubation_process.md` 1006) ist geprueft und **unveraendert
gueltig** — diese Runde aendert kein FK-Dokument, die Zeile ist nicht gewandert,
das Gate meldet kein `STALE_BASELINE`.

Ein Befund kam vom Gate selbst und ist behoben: der neue Verweis auf das
W2-Prompt-Asset stand als `prompts/authority_prose_v1.md` da und wurde als
repo-relativer Pfad gelesen (`UNRESOLVED_REPO_PATH`, ERROR). Jetzt vollstaendig
`tools/concept_governance/prompts/authority_prose_v1.md`.

**Mutationsnachweise Runde 5** — je Fix zurueckgedreht, Zieltests rot,
wiederhergestellt gruen. Zusaetzlich in **beide** Richtungen: auch eine zu
strenge Fassung muss auffallen, sonst beweisen die Gegenproben nichts.

| # | Mutation | Erwartet | Gemessen |
|---|---------|----------|----------|
| M1 | `_require_verbatim_quote()`-Aufruf entfernt | R3-Tests rot, Gegenproben gruen | 2 rot (der korrupte Lauf meldete **null** Befunde — genau der Defekt), 5 gruen |
| M2 | Kollisionspruefung entfernt (last-wins zurueck) | alle R4-Tests rot | 7 rot |
| M3 | `except json.JSONDecodeError` wieder zu `except ValueError` verbreitert | Kollision wird verschluckt, R4-Tests rot | 7 rot |
| M4 | Worttreue-Pruefung lehnt **alles** ab | Gegenproben rot | 3 rot (darunter beide Bestands-Policy-Tests) |
| M5 | Kollisionspruefung feuert bei **jedem** Schluessel | Gegenproben rot | 16 rot |
| M6 | `object_pairs_hook` in `structured_evaluator` Stage 2 entfernt | Urteil kippt still auf PASS | 1 rot |
| M7 | Duplikat-Pruefung feuert bei **jedem** Schluessel | Gegenproben rot | 11 rot |

**Keine Unterdrueckung:** kein NOSONAR, kein Rule-Exclude, kein neues
`noqa`/`type: ignore`, keine abgeschwaechte Assertion. Der einzige entfernte
Marker ist das `noqa: ANN401` an `_strip_key_escapes()` — die Funktion selbst
ist entfallen, weil `object_pairs_hook` die Rekursion uebernimmt.

## Nicht ausgefuehrt — benannte Luecken, nicht „gruen"

- **`tests/e2e/`** ist nicht gefahren (opt-in, nie Standard-CI).
- **`-m "not requires_gh"`** war auf `tests/integration/` gesetzt, wie in der
  CI-Stage. Tests mit echtem GitHub-Zugriff sind damit **nicht** belegt.
- **Jenkins/Sonar** nicht erreichbar; die Cognitive-Complexity-Grenze ist
  handgeprueft und ueber `ruff --select C901` gegengeprueft, **nicht** von Sonar
  bestaetigt.
- **W2/W3-Pre-Merge-Laeufe** sind fuer diese Story ausgesetzt (PO-Entscheidung,
  Rand 2.4c) und wurden nicht gefahren. Die Aenderungen dieser Runde **liegen im
  Code genau dieser Gates**; ihr Verhalten am lebenden Korpus ist damit nicht
  gemessen. Das ist die groesste benannte Luecke der Runde.
- **Zwei Bestandsbefunde in `tools/`**, unveraendert und nicht von dieser Runde
  verursacht: `ruff` C901 in
  `tools/concept_compiler/architecture_conformance.py:1409` und ein
  `mypy`-Fehler in `tools/concept_ingester/discovery.py:243`.

## Was nach Runde 5 offen bleibt

- **Codex-Review Runde 5** steht aus. Ohne dessen Abbruchkriterium ist die Story
  nicht fertig.
- **BLOCKIERT beim PO:** Rand 2.10 und das FK-93-Frontmatter (R5/R6).
- **Neu benannt (WARNING):** der Stage-3-Regex-Rueckfall des
  `StructuredEvaluator` nimmt bei mehrdeutigem Freitext den ersten Statuswert.
- **Unveraendert offen:** W3 ohne Retry (Rand 2.4c), die fehlenden
  `permissions.*`-Pfade in FK-03 und der ungemessene Effekt der FK-93-Kanten auf
  die W2-Befunde.
