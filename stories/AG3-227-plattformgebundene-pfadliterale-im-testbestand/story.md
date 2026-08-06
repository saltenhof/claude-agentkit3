# AG3-227 — Der Testbestand traegt eine Plattformannahme, die die CI nicht teilt

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: [AG3-189]` — dort ist die Ursache belegt
- **Herkunft:** Abschluss-Sweep aus AG3-189 R23, 2026-08-06

## Anlass

Jenkins-Build **#1241** meldete 13 Fehlschlaege. Sieben gehoerten AG3-189, und
ihre Analyse hat zwei Dinge zutage gefoerdert, die zusammengehoeren:

**1. Der Testdefekt.** `C:/proj` und `T:/project` sind auf POSIX **relative**
Pfade. Tests, die einen Laufwerksbuchstaben als absoluten Projektpfad annehmen,
pruefen auf Linux einen anderen Sachverhalt als auf Windows — oder werden aus
dem falschen Grund gruen.

**2. Der Produktionsdefekt, den die Annahme verdeckt hat.** Auf Linux ist der
venv-Interpreter regulaer ein **terminaler Symlink**. Der Eigentumsbeweis
verwarf jeden Symlink. Damit veroeffentlichte `resolve_ak3_interpreter()` einen
Pfad, dem derselbe Produktionscode niemals Loeschautoritaet geben konnte:
**Detach hat auf Linux nie funktioniert.** Belegt unabhaengig von den Literalen
durch zwei Tests, die `tmp_path` benutzen und trotzdem fielen.

Der zweite Punkt ist der eigentliche Grund fuer diese Story. Ein
plattformgebundener Testbestand ist nicht nur unsauber — **er verbirgt
Produktionsdefekte auf der Plattform, auf der die CI laeuft.** Genau das ist der
in `CLAUDE.md` beschriebene Fall: Eingabe und Erwartung stammen aus derselben
Annahme, also kann die Suite ihre eigene Blindstelle nicht sehen.

## Die Inventur — und was sie nicht ist

```text
252 Laufwerksliteral-Treffer in 45 Testdateien
  davon   3 in den 2 von AG3-189 mandatierten Dateien (behoben)
  davon 249 in 43 Dateien ausserhalb  -> Gegenstand dieser Story
  0 WindowsPath/PosixPath-Konstruktionen ausserhalb des Mandats
dazu Backslash-/UNC-Fundstellen ohne Laufwerksliteral in 6 weiteren Dateien
```

Die vollstaendige Fundstellenliste mit Zeilennummern steht im Ergebnis von
AG3-189 R23 und ist der Startpunkt, **nicht** die Arbeitsliste.

> **Diese 249 Treffer sind eine Inventur, keine Defektliste.** Der Sub-Agent hat
> das ausdruecklich festgehalten: viele Treffer sind bewusst opaque Wire-Werte
> oder **absichtliche Windows-Gegenbeispiele**. Wer sie pauschal ersetzt,
> zerstoert genau die Faelle, die Windows-Semantik pruefen sollen — und merkt es
> nicht, weil danach alles gruen ist.

**NACHTRAG 2026-08-06 — ein belegter Fall der Klasse 1, gefunden in AG3-189.**
`tests/contract/installer/test_mcp_registration_binding.py:44` setzt
`_PROJECT = "C:/projects/demo"`. Auf POSIX ist das **kein absoluter Pfad**. Der
Test ist heute gruen, weil beide Vergleichsseiten aus demselben Literal
abgeleitet werden und `abspath` denselben cwd-Praefix ergaenzt — er ist also
selbstkonsistent, aber **cwd-abhaengig**. Das ist exakt die Konstellation, die
R23 in den Nachbartests per `tmp_path` beseitigt hat: gruen aus dem falschen
Grund.

Betroffen sind **13 Fundstellen** in dieser Datei, viele davon ausserhalb von
Fixture-Kontexten. Die Umstellung ist ein Umbau der gesamten Contract-Datei und
wurde deshalb dort nicht vorgenommen. Der Fall ist ein guter Pruefstein fuer
AC 1: Er gehoert **nicht** zu Klasse 2 oder 3, obwohl er gruen ist.

Die Verteilung ist stark ungleich: allein
`tests/integration/control_plane/test_takeover_confirm_pg.py` traegt 41 Treffer,
`tests/unit/control_plane/test_runtime.py` 48, `tests/unit/skills/test_placeholder.py` 28.
Drei Dateien enthalten damit knapp die Haelfte.

## Scope

### In Scope

- **Jeder der 249 Treffer wird einer von drei Klassen zugeordnet**, und die
  Zuordnung ist begruendet:
  1. **Defekt** — das Literal wird als absoluter Pfad verwendet und traegt auf
     Linux eine andere Bedeutung. Wird behoben.
  2. **Absichtlich** — der Test prueft Windows-Semantik als solche. Bleibt, und
     die Absicht wird an der Stelle sichtbar gemacht.
  3. **Opaque** — der Wert ist ein durchgereichter Zeichenkettenwert ohne
     Pfadsemantik (Wire-Wert, Fixture-Kennung). Bleibt.
- **Behebung der Klasse 1** so, dass der gepruefte Sachverhalt derselbe bleibt.
- **Eine Regel, die verhindert, dass die Klasse zurueckkehrt.** Deterministisch
  und im selben Gate wie ruff/mypy, nicht als optionales Skript.
- Die sechs Backslash-/UNC-Fundstellen ohne Laufwerksliteral.

### Out of Scope

- Produktionscode. Findet die Bereinigung einen **weiteren** verdeckten
  Produktionsdefekt wie den aus AG3-189, ist das ein Befund mit PO-Vorlage und
  gehoert in eine eigene Story — nicht nebenbei behoben.
- Die Frage, ob AK3 auf Linux vollstaendig betriebsfaehig ist. Diese Story
  raeumt den Testbestand, sie beantwortet die Betriebsfrage nicht.

## Akzeptanzkriterien

1. **Jeder der 249 Treffer ist klassifiziert** — Defekt, absichtlich oder
   opaque — mit Begruendung je Fundstelle. Eine Sammelbegruendung pro Datei
   genuegt nur, wenn alle Treffer dieser Datei nachweislich denselben Fall
   tragen.
2. **Klasse 1 ist behoben, und der gepruefte Sachverhalt ist derselbe
   geblieben.** Je behobenem Test ist zu sagen, was er vorher geprueft hat und
   was er jetzt prueft. **Ein Test, der auf Linux einen anderen Fall prueft als
   auf Windows, ist zwei Tests mit einer Zusage und erfuellt dieses Kriterium
   nicht.**
3. **Klasse 2 ist als Absicht erkennbar.** Ein Windows-Gegenbeispiel, das nur
   zufaellig wie ein vergessenes Literal aussieht, wird beim naechsten Sweep
   wieder als Befund gemeldet. Die Absicht steht an der Stelle.
4. **Die Klasse kann nicht zurueckkehren.** Ein deterministischer Check laeuft
   im regulaeren Gate und weist neue plattformgebundene Pfadliterale ab. Er
   fuehrt eine **sichtbare, begruendete Ausnahmeliste** fuer Klasse 2 und 3 —
   keine stille Unterdrueckung.
5. **Der Check meldet nicht faelschlich gruen.** Er ist gegen mindestens einen
   kuenstlich eingefuegten Verstoss jeder erfassten Form geprueft. Ein Gate, das
   falsch gruen meldet, entwertet jede Aussage, die es je gemacht hat.
6. **Der Nachweis laeuft auf Linux.** Die betroffenen Tests sind auf Linux gruen
   nachgewiesen, nicht nur auf Windows. Faellt der Linux-Lauf aus, ist das eine
   benannte Luecke mit Grund — nie „gruen".
7. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle sechs
   deterministischen Konzept-Gates gruen; volle Suite gruen auf Jenkins.
8. Coverage haelt die 85-%-Schwelle.

## Definition of Done

- AC 1-8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Hinweis zum Zuschnitt

Die Story ist gross, aber **nicht unbegrenzt**: Das Universum ist vor
Arbeitsbeginn vollstaendig aufgezaehlt (249 Treffer, 43 Dateien, plus sechs
Backslash-Fundstellen) und liegt als Liste mit Zeilennummern vor. Das ist der
Unterschied zu AG3-189, wo eine Universalzusage ueber eine nie aufgezaehlte
Menge 22 Reviewrunden gekostet hat. Wer den Zuschnitt teilen will, teilt entlang
der drei grossen Dateien — nicht entlang „erstmal die einfachen".

## Guardrail-Referenzen

- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — AC 6; die Suite kann
  Uebereinstimmung mit der Welt nicht aus sich selbst beweisen
- `CLAUDE.md` §ZERO DEBT RULE — AC 1, keine Restluecke in der Klassifikation
- `CLAUDE.md` §NO ERROR BYPASSING — AC 4, sichtbare Ausnahmen statt stiller
  Unterdrueckung
- `guardrails/testing-guardrails.md`
