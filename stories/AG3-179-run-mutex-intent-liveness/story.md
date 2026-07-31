# AG3-179 — RUN.mutex-Koordinations-Klinke: Liveness-Defekt

- **Typ:** implementation
- **Status:** ready
- **Groesse:** S
- **Betroffen:** `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py`
  (FK-78 §78.4, Mutation-Mutex des Concept-Councils)
- **Herkunft:** Orchestrator-Befund 2026-07-30 beim AG3-176-Abschlusslauf.

## Befund

Unter Nebenlaeufigkeit koennen **beide** konkurrierenden Schreiber abbrechen —
auch derjenige, der den Mutex rechtmaessig uebernommen hat. Es kommt dann
**gar keine** Mutation durch. Der Test, der genau das verbietet, existiert
bereits und faellt unter Last um:

```
tests/unit/concept_toolchain/test_mutex_race.py
  ::test_two_processes_racing_a_takeover_never_mutate_concurrently
AssertionError: no writer won the race: [2, 2]
```

Diagnose aus einem echten roten Lauf (stderr beider Rennteilnehmer):

```
[2] [units] INCOMPLETE: RUN.mutex is held by 'orch.alice' ... refusing to mutate
[2] [units] INCOMPLETE: another writer holds the RUN.mutex coordination intent ...
```

Zeile 1 ist der Verlierer — korrekt. **Zeile 2 ist der Gewinner**: er besass den
Mutex und wurde trotzdem hinausgeworfen.

## Ursache

`RUN.mutex.intent` ist eine **kurz gehaltene Klinke** zur Serialisierung der
kritischen Abschnitte, nicht das Eigentumsrecht — Eigentum traegt der Mutex mit
Nonce + TTL + Fencing-Token. Ein `units`-Lauf holt und gibt diese Klinke aber
**viermal** frei:

1. `_acquire_mutex` (Uebernahme/Anlage)
2. `_MutexGuard.revalidate()` (vor dem Dispatch)
3. `guard.write_bytes(...)` (Staging + Rename)
4. `guard.release()` (Compare-before-delete)

`_claim_intent` gibt bei einer **lebenden** fremden Klinke **sofort** auf
(`return None` -> `MutexLostError` -> Exit 2). Ein Mitbewerber, der zwischen
zwei Abschnitten des Eigentuemers die freie Klinke greift — und dann selbst am
lebenden Mutex scheitert —, erschlaegt damit den Eigentuemer im naechsten
Abschnitt. Beim symmetrischen Fall pingpongen beide und keiner kommt durch.

Es ist **fail-closed** — es entsteht kein inkonsistenter Zustand, keine
verschraenkte Schreibung. Aber es ist ein **Liveness-Defekt**: bei zwei
gleichzeitigen Orchestrator-Sessions kann eine Promotion grundlos komplett
scheitern.

## Belegte Abgrenzung: Bestandsdefekt auf main, keine AG3-176-Regression

Gleiche Maschine, gleicher Aufbau (8 parallele pytest-Prozesse als Lastquelle),
isolierter Test:

| Stand | Laeufe | rot | Quote |
|---|---|---|---|
| `HEAD` / main (`81f28cde`) | 96 | 10 | ~10 % |
| AG3-176-Branch | 48 | 2 | ~4 % |

Der erste, scheinbar gruene HEAD-Lauf (48/48) hatte die **ganze Testdatei**
laufen lassen statt nur des einen Tests — anderes Timing, damit kein gueltiger
Vergleich. Nach Angleich des Aufbaus faellt HEAD sogar haeufiger um. Der Defekt
ist damit **vor** AG3-176 vorhanden und wird dort nur erstmals sichtbar.

## Loesungsrichtung (Vorschlag, im Schnitt zu bestaetigen)

`_claim_intent` muss bei einer **lebenden** fremden Klinke **beschraenkt warten**
(kurze Polls bis zu einer Frist im Sekundenbereich) und **erst danach**
fail-closed aufgeben. Begruendung: die Klinke wird nur ueber eine Handvoll
Dateioperationen gehalten; sofortiges Aufgeben verwandelt normale Konkurrenz in
wechselseitigen Abbruch.

Alle bestehenden Invarianten bleiben unangetastet:

- `O_CREAT|O_EXCL` bleibt der Schiedsrichter der Klinke.
- Compare-before-delete beim Aufraeumen abgelaufener Klinken bleibt.
- TTL-basierte Uebernahme, Fencing-Token-Pruefung, Heartbeat bleiben.
- Ein lebender fremder **Mutex** blockiert weiterhin jeden Mitbewerber
  (`test_two_processes_racing_a_live_mutex_both_abort` bleibt `[2, 2]`).

**Ausdruecklich nicht:** dem Mutex-Eigentuemer erlauben, die Klinke zu
umgehen — das wuerde die Atomizitaet zwischen Uebernahme und kritischem
Abschnitt aufgeben, also genau die Eigenschaft, fuer die die Klinke existiert.

## Test-Beobachtbarkeit (Teil dieser Story)

Der Wettlauf-Test verwirft heute die Diagnose der Subprozesse — er meldet nur
`[2, 2]` ohne jeden Grund. Der vorbereitete Patch (Driver meldet Exit-Code **und**
stderr als JSON; Assertion druckt beide Rennteilnehmer) liegt bereit und gehoert
in diese Story, nicht in AG3-176:

`<scratchpad>/AG3-179-race-diagnostics.patch`

## Akzeptanzkriterien

1. Der rechtmaessige Mutex-Eigentuemer kann von einem Mitbewerber nicht mehr aus
   seinem eigenen kritischen Abschnitt geworfen werden.
2. `test_two_processes_racing_a_takeover_never_mutate_concurrently` ist unter
   Last stabil — Nachweis ueber einen Wiederholungslauf mit mindestens 100
   Durchlaeufen unter CPU-Konkurrenz, 0 rot.
3. Alle uebrigen Mutex-/Intent-Tests bleiben unveraendert gruen; insbesondere
   bleibt ein lebender fremder Mutex ein harter Abbruch.
4. Der Wettlauf-Test meldet im roten Fall die Diagnose beider Prozesse.
5. Keine Aufweichung der Fail-Closed-Semantik: nach Ablauf der Wartefrist wird
   weiterhin abgebrochen, nicht durchgewunken.
