# AG3-179 — Abschlussbericht

Datum: 2026-08-01. Umsetzer und Verifizierer: Orchestrator (Worker-Modus,
PO-Auftrag „setz jetzt mal die 179 um gemaess der bisherigen Richtlinien").

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

## Belege

- Lastnachweis (AC 2): siehe `status.yaml`; Aufbau = 8 CPU-Brenner + isolierter
  Wettlauf-Test, identisch zum Aufbau, mit dem der Defekt urspruenglich als
  Bestandsdefekt auf `main` belegt wurde.
- Volle Suite, `ruff check src tests`, `mypy src --strict` fuer **win32, linux
  und darwin**, sowie alle Konzept-Gates: siehe `status.yaml`.
