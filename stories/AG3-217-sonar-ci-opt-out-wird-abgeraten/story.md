# AG3-217 — Der Sonar-/CI-Opt-out bleibt zulaessig, aber niemand waehlt ihn versehentlich

- **Typ:** implementation
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-03 §3 (Konfigurationsmodell, `sonarqube.available` /
  `ci.available`), FK-50 (Installer)
- **Herkunft:** PO-Hinweis am 2026-08-04 beim Vorbereiten der
  Wiederregistrierung von `ibkr-tax-analyzer`.

## Kontext

### Befund — belegt, mit Locator

`ibkr-tax-analyzer` ist mit `sonarqube.available: false` und
`ci.available: false` registriert (`.agentkit/config/project.yaml`), obwohl es
`implementation`- und `bugfix`-Stories fuehrt — also codeproduzierend ist.

Der PO hielt das zunaechst fuer einen Installer-Defekt: „AK3 hat Jenkins und
Sonar verpflichtend, ohne die kannst du AK3 gar nicht im Projekt benutzen, um
Stories zu entwickeln."

**Die Pruefung ergab das Gegenteil.** FK-03 §3 erlaubt den Opt-out
ausdruecklich:

> `false` erklaert „kein Sonar" — das `sonarqube_gate` ist dann an allen drei
> Lifecycle-Gate-Punkten **NOT_APPLICABLE** (kein fail-closed; FK-33 §33.6.5).
> Das ist **auch fuer codeproduzierende Projekte ausdruecklich zulaessig** —
> Konsequenz: keine Sonar-Qualitaetsdurchsetzung, der Betreiber akzeptiert das
> bewusst.

Die CLI setzt genau das um (`cli/installer_commands.py:186-206`):
`--sonarqube-available` / `--ci-available` mit Default `true` und der Hilfe
„Use `--no-…` only for the conscious opt-out".

`ibkr-tax-analyzer` ist also nicht durch einen Bug so entstanden, sondern ueber
einen Weg, den das Konzept vorsieht.

### PO-Entscheid 2026-08-04

> „hmmm das war mir nicht bewusst, dass es als Standardweg des Betriebs
> verankert wurde. meine entscheidung: lassen, aber im installer ein warning
> ausgeben, dass von diesem Modus strikt abgeraten wird"

**FK-03 bleibt unveraendert.** Der Opt-out bleibt zulaessig; er wird nicht
verboten und nicht fail-closed. Was fehlt, ist die Deutlichkeit an der Stelle,
an der jemand ihn waehlt.

## WICHTIG — das ist KEIN Severity-WARNING im Sinne von `CLAUDE.md`

`CLAUDE.md` §SEVERITY-SEMANTIK definiert WARNING als **„Handlungsauftrag mit
aufschiebender Wirkung"**, der „aktiv an den Auftraggeber zu spiegeln" ist mit
der Frage „wie wollen wir hier vorgehen", und dessen stilles Liegenlassen ein
ZERO-DEBT-Verstoss waere.

**Das trifft hier nicht zu.** Der Betreiber hat bereits entschieden, und die
Entscheidung ist zulaessig. Es gibt keinen offenen Handlungsauftrag, kein
„spaeter zu erledigen", nichts zu spiegeln.

Was gebaut wird, ist eine **Abratung zum Entscheidungszeitpunkt**: laut,
unuebersehbar, inhaltlich konkret — und danach abgeschlossen. Wer hier einen
Spiegelungs- oder Nachverfolgungsmechanismus baut, hat die Anforderung
missverstanden und erzeugt genau die Warning-Flut, wegen der `CLAUDE.md` sonst
zu ERROR raet.

Umgekehrt gilt: Die Ausgabe darf **nicht** so beilaeufig sein, dass sie im
Installationsprotokoll untergeht. Sie ist der einzige Moment, in dem jemand
erfaehrt, was er gerade abwaehlt.

## Scope

### In Scope

- Eine deutliche Abratung im Installer, sobald `--no-sonarqube-available` oder
  `--no-ci-available` gesetzt wird — je Flag mit eigener, konkreter Aussage.
- Die Abratung benennt die **Konsequenz**, nicht nur die Tatsache: welche
  Qualitaetsdurchsetzung entfaellt, an welchen Gate-Punkten, und was das fuer
  codeproduzierende Storys bedeutet.
- Verschaerfte Ausgabe, wenn das Projekt **codeproduzierend** ist (Story-Typen
  enthalten `implementation` oder `bugfix`) — dort ist der Verzicht am
  teuersten.

### Out of Scope

- **Keine Aenderung an FK-03.** Der Opt-out bleibt normativ zulaessig; das ist
  der Kern des Entscheids.
- Kein fail-closed, kein Abbruch, keine Rueckfrage, kein interaktiver Prompt.
  Der Installer laeuft nicht-interaktiv und muss es bleiben.
- Keine Nachverfolgung, kein Wiedervorlage-Mechanismus, kein Eintrag in eine
  Warnungsliste (siehe Abschnitt oben).

## Akzeptanzkriterien

1. **Wer den Opt-out waehlt, liest die Konsequenz.** `--no-sonarqube-available`
   und `--no-ci-available` erzeugen je eine eigene, konkret formulierte
   Abratung auf der Fehlerausgabe. Sie nennt, was entfaellt — nicht nur, dass
   etwas entfaellt. Nachgewiesen durch je einen Test, der die Ausgabe prueft.
2. **Ohne Opt-out ist es still.** Der Regelfall (`available: true`) erzeugt
   keine Ausgabe. Ein Hinweis, der immer erscheint, wird nicht gelesen.
   Negativtest.
3. **Codeproduzierende Projekte bekommen die schaerfere Form.** Enthalten die
   Story-Typen `implementation` oder `bugfix`, benennt die Ausgabe zusaetzlich,
   dass genau fuer diese Story-Typen die Qualitaetsdurchsetzung entfaellt.
   Nachgewiesen an beiden Faellen.
4. **Der Installer bricht nicht ab und fragt nicht nach.** Exit-Code und Ablauf
   sind unveraendert; der Lauf bleibt nicht-interaktiv. Nachgewiesen durch
   einen Test, der einen vollstaendigen Opt-out-Lauf erfolgreich beendet.
5. **FK-03 ist unveraendert.** Kein Decision Record noetig, solange die Norm
   nicht angefasst wird — die Abratung ist eine Ergonomie-Massnahme, keine
   normative Aenderung. Wird beim Umsetzen doch eine Konzeptaenderung noetig,
   ist das eine Mandatsanfrage.
6. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC 1-6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Anmerkung zur Wiederregistrierung

`ibkr-tax-analyzer` wird nach dieser Story **mit** Sonar und CI neu registriert
— nicht weil der Opt-out unzulaessig waere, sondern weil er dort nie bewusst
gewaehlt wurde. Seine `control-plane.json` traegt zusaetzlich den Legacy-Port
`9080` (statt `9702`) und `ca_file: null`; das Projekt ist damit ohnehin nicht
funktionsfaehig registriert.

## Guardrail-Referenzen

- `CLAUDE.md` §SEVERITY-SEMANTIK — und ihre bewusste Nicht-Anwendung hier,
  siehe Abschnitt oben
- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN" — die Abratung ist keine
  Uebergangsloesung, sondern der Endzustand
