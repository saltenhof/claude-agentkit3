# AG3-179 — Arbeitsbericht

Datum: 2026-08-01 (Runde 1), **2026-08-02 (Runde 2)**. Umsetzer und
Verifizierer Runde 1: Orchestrator (Worker-Modus, PO-Auftrag „setz jetzt mal
die 179 um gemaess der bisherigen Richtlinien"); Runde 2: Worker unter
Orchestrator-Auftrag nach dem ersten unabhaengigen Codex-Review.

**Die Story ist NICHT fertig.** Behobene Findings sind kein Abschluss
(CLAUDE.md, „Definition of Done: Codex-Review bis zum Abbruchkriterium"). Der
Stand geht erneut ins Review.

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

## Offen

- **Codex-Review Runde 2** steht aus. Ohne dessen Abbruchkriterium ist die
  Story nicht fertig.
- **Ratifikation** der Raender 2.2, 2.4, 2.6, 2.7 und der FK-93-Aenderungen
  durch den PO (Decision Record §5, Klassen b und c).
