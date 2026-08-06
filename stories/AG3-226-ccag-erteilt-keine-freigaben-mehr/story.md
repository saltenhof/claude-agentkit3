# AG3-226 — Der Gatekeeper bleibt, die Genehmigungsinstanz geht

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []` — `unblocks: [AG3-214]`
- **Herkunft:** PO-Entscheid vom 2026-08-05

## Anlass

Die zweite Abschlussreview zu AG3-214 fand einen produktiv erreichbaren
Schreibpfad, der die Kernzusage jener Story widerlegt:

> `governance/runner.py:2165` — `_escalate_expired_permission_requests()` liest
> abgelaufene Permission-Requests ueber Project Edge, konstruiert danach aber
> `StateBackendPhaseEnvelopeRepository` und schreibt den kanonischen
> `PhaseState` **direkt aus dem Hook-Prozess**. Ohne prozesslokale Lease faellt
> `_borrow_pool_or_writer_connection()` (`_connection.py:145`) ausdruecklich auf
> eine normale Pool-Verbindung zurueck.

Erreichbar ueber **beide** installierten Hook-Einstiege (`claude_code.py:200`,
`codex/cli.py:77`). Der zugehoerige Integrationstest
(`test_ccag_ttl_escalation_rest_pg.py:99`) macht genau diesen Mischpfad gruen —
„real REST" betrifft dort nur den Lesevorgang.

## Der Entscheid

Der PO hat nicht die Absicherung des Schreibpfads gewaehlt, sondern seinen
Wegfall:

> „Du kannst ja sonst auch den CCAG Hook bestehen lassen, aber in die Zaehne
> ziehen im Sinne von, dass er keine Freigaben mehr erteilt, sondern einfach
> nur die anderen Agentaufgaben uebernimmt."

**Ohne Genehmigungsverfahren gibt es keine ablaufenden Permission-Requests —
und damit keine TTL-Eskalation, die leasefrei schreibt.** Der Pfad verschwindet,
statt abgesichert zu werden. Das ist der staerkere Fix: Ein Weg, den es nicht
gibt, kann nicht umgangen werden.

## Warum der Hook bleibt und nicht entfernt wird

`principal_capabilities/enforcement.py:100-111` haelt fest, dass FK-91 §91.4 den
**Sub-Agent-Spawn** (`Agent`) unter dem `ccag_gatekeeper`-Matcher katalogisiert
(`Bash|Write|Edit|Read|Grep|Glob|Agent`). Die Capability-Schicht laesst den
Spawn bewusst mit ALLOW-Huelle durch — mit der ausdruecklichen Begruendung, dass
danach `prompt_integrity` **und CCAG** die eigentliche Autoritaet sind.

Eine Deregistrierung haette diesen Matcher mitgenommen und damit eine
Durchsetzungsstelle beseitigt, die eine **andere** Zusage traegt. Deshalb:
Registrierung bleibt, Autoritaet geht.

## Offene Auslegung — vom Orchestrator getroffen, korrigierbar

„Keine Freigaben mehr erteilen" laesst zwei Lesarten zu:

- **(A) CCAG ist keine Permission-Autoritaet mehr** — es genehmigt nicht und
  blockiert nicht nach Permission-Regeln; das Permission-Request-Verfahren
  entfaellt vollstaendig.
- **(B) Nur das Genehmigen entfaellt**, das Blockieren nach Regel bleibt.

**Gewaehlt ist (A)**, weil „in die Zaehne ziehen" die Autoritaet als Ganzes
meint und „nur die anderen Agentaufgaben uebernimmt" eine Rolle **neben** der
Permission-Runtime beschreibt.

**Der Unterschied ist nicht kosmetisch**, deshalb steht er hier: Unter (A)
verliert die Agent-Kante ihre CCAG-Blockade und `prompt_integrity` sowie die
Principal-Capability-Schicht sind die verbleibende Autoritaet. Unter (B) bliebe
eine Blockademoeglichkeit erhalten. Erweist sich (A) als zu weit, ist das eine
PO-Korrektur an dieser Stelle — kein neuer Entscheid.

## Scope

### In Scope

- **Das Permission-Request-Verfahren entfaellt** — Anlage, Genehmigung, Ablauf
  und TTL-Eskalation. Damit entfaellt auch
  `_escalate_expired_permission_requests()` als produktiver Pfad.
- **Der Hook bleibt registriert** und behaelt seinen Matcher; die uebrigen
  Aufgaben laufen weiter.
- **Kein Loeschen von Code** ohne Not: Was durch den Entscheid unerreichbar
  wird, wird als unerreichbar kenntlich — nicht heimlich stehengelassen und
  nicht vorschnell entfernt. Wo Code nur noch dem entfallenen Verfahren dient
  und keine andere Aufgabe traegt, ist sein Verbleib zu begruenden.
- **Bestehende Zielprojekte**: Traegt eine `.claude/settings.json` bereits die
  Registrierung, bleibt sie gueltig — der Hook laeuft ja weiter. Aendert sich
  am materialisierten Eintrag etwas, muss der Upgrade-Pfad es mitziehen.
- **FK-42** (CCAG-Runtime) und die betroffenen Stellen in **FK-30**, **FK-55**
  und **FK-91** sagen, was der Gatekeeper noch tut und was nicht.

### Out of Scope

- Die Absicherung des Schreibpfads ueber den Writer-Lease. Sie wird
  gegenstandslos; **AG3-214** fuehrt den Befund als geroutet, nicht als behoben.
- Die uebrigen vier Befunde der AG3-214-Review. Sie bleiben dort.
- `prompt_integrity` und die Principal-Capability-Schicht. Sie sind betroffen,
  aber nicht Gegenstand — ausser einer Feststellung nach AC 3.

## Akzeptanzkriterien

1. **Es existiert kein produktiver Pfad mehr, auf dem der CCAG-Hook
   Control-Plane-State schreibt.** Nachgewiesen durch einen Sweep mit Methode
   ueber beide Hook-Einstiege, nicht durch Sichtpruefung.
2. **Der Gatekeeper erteilt keine Freigaben.** Ein Test beweist, dass ein
   Vorgang, der frueher eine Genehmigung erhalten haette, heute keine bekommt.
   Und ein zweiter, dass daraus **kein stilles Erlauben** wird, das vorher ein
   Blockieren war — oder, falls doch, dass genau das die gewollte Wirkung von
   Auslegung (A) ist und benannt im Konzept steht.
3. **Die Agent-Kante bleibt durchgesetzt.** Ausdruckliche Feststellung, was den
   Sub-Agent-Spawn nach der Aenderung absichert — mit Locator. Faellt dabei auf,
   dass `prompt_integrity` allein nicht traegt, ist das ein Befund mit
   PO-Vorlage, nicht ein stiller Rest.
4. **Der Matcher ueberlebt.** `ccag_gatekeeper` bleibt registriert, und der
   Sub-Agent-Spawn wird weiterhin darunter katalogisiert (FK-91 §91.4). Test.
5. **Konzept und Code sagen dasselbe.** FK-42, FK-30, FK-55 und FK-91 sind
   nachgezogen; keine Stelle behauptet weiter ein Genehmigungsverfahren.
   Decision Record fuer den Entscheid.
6. **Kein toter Code ohne Aussage.** Was durch den Entscheid unerreichbar wird,
   ist entweder entfernt oder traegt eine Begruendung, warum es bleibt.
7. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle sechs
   deterministischen Konzept-Gates gruen; volle Suite gruen auf Jenkins.
8. Coverage haelt die 85-%-Schwelle.

## Definition of Done

- AC 1-8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FAIL-CLOSED — AC 2 und AC 3 pruefen ausdruecklich, dass aus dem
  Wegfall einer Autoritaet kein stilles Erlauben wird
- `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN — kein zweiter Pfad, der das
  alte Verfahren am Leben haelt
- `CLAUDE.md` §ZERO DEBT RULE — AC 6
