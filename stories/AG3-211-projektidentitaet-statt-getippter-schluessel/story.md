# AG3-211 — Ein Projekt existiert serverseitig genau einmal

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-10 (Registrierung, Dev-Kern-Topologie), FK-15
  (Projektbindung des Tokens), AG3-020 (Projekt-Repositories)
- **Herkunft:** PO-Anforderung vom 2026-08-03, entstanden bei der Klaerung des
  Rollenmodells in AG3-180.

## Kontext

### Die Anforderung

Der erste Bediener installiert AK3 in einen Projektordner; damit entsteht das
Projekt **serverseitig**. Ein zweiter Bediener installiert AK3 in **seine**
Arbeitskopie desselben Projekts. Serverseitig darf dabei **kein zweites Projekt
entstehen** — der zweite Bediener wird der vorhandenen Instanz zugeordnet.

### Befund — gemessen, mit Locator

`create_project` (`src/agentkit/backend/project_management/lifecycle.py:39`) ist
eine **reine Fabrik ohne jede Dublettenpruefung**. Eindeutigkeit entsteht allein
ueber den `project_key` als Primaerschluessel.

**Ein getippter Schluessel ist keine Identitaet.** Daraus folgen zwei Fehler,
die heute beide moeglich sind:

| Fall | Was passiert | Wirkung |
|---|---|---|
| Zwei Bediener, dasselbe Repository, **verschiedene** Schluessel | zwei Projekte serverseitig | Storys, Telemetrie und Ownership zerfallen in zwei Haelften, die nichts voneinander wissen |
| Zwei Bediener, **verschiedene** Repositories, derselbe Schluessel | Primaerschluesselkonflikt | der Zweite wird abgewiesen oder — schlimmer — an ein fremdes Projekt gebunden |

Beide Faelle sind heute weder erkannt noch benannt.

### Die Entscheidung ist gefallen: der Schluessel wird abgeleitet, nicht getippt

**PO-Entscheidung 2026-08-03.** AK3 fuehrt zwei Sorten Repositories: ein
**Root-Repository**, das das Projekt repraesentiert, und optionale
**Codebase-Repositories**. Der harte `project_key` wird kuenftig aus dem
Root-Repository **abgeleitet**; fuer die Oberflaeche kommt ein frei waehlbarer
**Alias** hinzu.

Damit verschwindet die Fehlerursache, statt geprueft zu werden: Zwei Bediener,
die dasselbe Root-Repository klonen, erhalten denselben Schluessel — sie koennen
gar nicht auseinanderlaufen, weil niemand mehr etwas tippt.

Zwei Dinge stehen dem heute im Weg, beide gemessen:

**(a) Ein erstklassiges Root-Repository existiert nicht.**
`ProjectConfiguration` (`src/agentkit/backend/project_management/entities.py:14`)
fuehrt **zwei** Kandidaten nebeneinander:

- `repo_url: str` — validiert als Mitglied von `repositories`
- `repositories[0]` — laut Docstring „the conventional primary repo
  (**UI convention**)"

Nichts erzwingt `repo_url == repositories[0]`. Das sind zwei Wahrheiten ueber
dasselbe. Bevor ein Schluessel daraus abgeleitet wird, muss **eine** davon das
Root-Repository sein und die andere verschwinden. (An derselben Stelle, Zeile
26: „Forward-compatibility for legacy DB rows without a `repositories` key" —
eine Kompatibilitaetsschicht, die nach der Ausnahmslos-Regel ohnehin faellt.)

**(b) Der bloesse Repository-*Name* ist nicht eindeutig.** `acme/app` und
`other/app` heissen beide `app`. Der Schluessel traegt deshalb den Namensraum
mit — `owner/name`, aus der normalisierten URL ableitbar bei GitHub, Azure
DevOps und Gitea gleichermassen. Er bleibt damit ein lesbarer Slug und ist
trotzdem eindeutig.

Die Normalisierung bleibt noetig, weil `git@github.com:acme/app.git`,
`https://github.com/acme/app.git`, `https://github.com/acme/app` und
`https://GitHub.com/ACME/app.git` dasselbe Repository bezeichnen und vier
verschiedene Zeichenketten sind. Das ist dieselbe Fehlerklasse, die **AG3-205**
(„Guards entscheiden Identitaet statt Zeichenketten") fuer Kommando- und
Pfadidentitaet traegt; das Normalisierungsmodell ist zu teilen, nicht doppelt zu
bauen.

**Folge, die zu entscheiden ist:** Wird das Root-Repository umbenannt oder
verschoben, aendert sich der abgeleitete Schluessel — die Identitaet bricht. Das
ist beherrschbar, aber kein Automatismus (siehe AC 6a).

## Scope

### In Scope

- **Ein benanntes, normiertes Identitaetskriterium** fuer „dasselbe Projekt",
  mit ausgeschriebener Normalisierung und ausgeschriebenen Grenzen.
- **Zuordnung statt Neuanlage:** eine Registrierung, deren Identitaet auf ein
  vorhandenes Projekt zeigt, ordnet zu und erzeugt nichts Neues.
- **Fail-closed bei Mehrdeutigkeit:** wo die Identitaet nicht eindeutig
  bestimmbar ist, wird abgebrochen und benannt — nie geraten.
- **Widerspruchsfall:** eine Registrierung, deren Identitaet auf ein vorhandenes
  Projekt zeigt, deren uebrige Angaben (Schluessel, Name, Repositories) aber
  abweichen, ist ein benannter Fehler — kein stilles Ueberschreiben und kein
  stilles Uebernehmen.
- Normative Nachfuehrung in FK-10 samt Decision Record.

### Out of Scope

- **Erstzugang, Strategenpasswort und Projekt-Token** — AG3-180. Diese Story
  entscheidet, **welchem** Projekt ein Bediener zugeordnet wird, nicht **womit**
  er sich ausweist.
- **Kommando- und Pfadidentitaet in den Guards** — AG3-205. Gemeinsames
  Normalisierungsmodell pruefen, nicht zweimal bauen.
- **Mehrbenutzerbetrieb, Rollen, Rechte je Bediener** — FK-15 bleibt
  unveraendert; hier geht es allein um die Projektidentitaet.
- **Nachtraegliches Zusammenfuehren** zweier bereits getrennt angelegter
  Projekte. Wenn der Bestand solche Paare enthaelt, werden sie **gemeldet**,
  nicht automatisch verschmolzen — eine Verschmelzung ist eine eigene
  Grundentscheidung mit Datenfolgen.

## Akzeptanzkriterien

0. **Das Root-Repository ist ein erstklassiges Feld mit genau einer Wahrheit.**
   `repo_url` und die UI-Konvention `repositories[0]` sind zu **einem** Feld
   zusammengefuehrt; die andere Stelle entfaellt ersatzlos. Die
   Legacy-Vorwaertskompatibilitaet fuer Zeilen ohne `repositories`
   (`entities.py:26`) faellt mit — Kompatibilitaetsschichten sind ausnahmslos
   verboten. Nachgewiesen daran, dass es nach der Aenderung **keine** Stelle
   mehr gibt, an der beide Angaben auseinanderlaufen koennen.
1. **Der `project_key` wird aus dem Root-Repository abgeleitet, nicht getippt.**
   Er traegt den Namensraum mit (`owner/name`-Form, als Slug). Eine
   Registrierung nimmt keinen frei gewaehlten Schluessel mehr entgegen. Fuer die
   Oberflaeche existiert ein **Alias**, der frei waehlbar und aenderbar ist und
   **keine** Identitaetswirkung hat.
2. **Die Ableitung ist normiert.** Ausgeschrieben ist, wie die Repository-Angabe
   normalisiert wird (Protokoll, Gross-/Kleinschreibung, `.git`-Suffix,
   Benutzerteil, Port, abschliessender Schraegstrich) und was **ausdruecklich
   nicht** normalisiert wird. Nachgewiesen an einer Tabelle aequivalenter und
   nicht-aequivalenter Schreibweisen, jede als Test.
2. **Der zweite Bediener erzeugt kein zweites Projekt.** Nachgewiesen an einem
   Ablauf, in dem eine zweite Registrierung desselben Projekts aus einer
   **anderen Arbeitskopie** erfolgt: danach existiert serverseitig **genau ein**
   Projekt, und die zweite Arbeitskopie ist ihm zugeordnet.
3. **Auch bei abweichender Schreibweise.** AC 2 gilt ebenso, wenn die zweite
   Registrierung die Repository-Angabe in einer anderen zulaessigen Form
   fuehrt. Nachgewiesen mit mindestens drei Schreibweisen aus AC 1.
4. **Verschiedene Projekte bleiben verschieden.** Zwei Registrierungen mit
   verschiedener Identitaet erzeugen zwei Projekte — auch dann, wenn Schluessel
   oder Name kollidieren. Der Schluesselkonflikt wird als solcher benannt.
5. **Mehrdeutigkeit bricht ab.** Laesst sich die Identitaet nicht eindeutig
   bestimmen (keine Repository-Angabe, mehrere gleichrangige Kandidaten,
   unaufloesbare Form), endet die Registrierung fail-closed mit Nennung des
   Grundes und des zulaessigen Wegs — sie raet nicht.
6. **Der Widerspruchsfall ist entschieden und getestet.** Zeigt die Identitaet
   auf ein vorhandenes Projekt, weichen aber Alias, Story-Praefix oder
   Codebase-Repositorienliste ab, ist das Verhalten ausgeschrieben und geprueft.
   Stilles Ueberschreiben der Serverseite und stilles Uebernehmen der
   Clientseite sind beide unzulaessig.
6a. **Umbenennung des Root-Repositories ist entschieden, nicht dem Zufall
   ueberlassen.** Wird es umbenannt oder verschoben, aendert sich der abgeleitete
   Schluessel. Ausgeschrieben und getestet ist, was dann gilt: ob das Projekt
   seine Identitaet behaelt und die neue Form zugeordnet wird, oder ob ein
   benannter Fehler entsteht. **Nicht zulaessig ist der stille Fall** — dass
   dieselbe Arbeit nach einer Umbenennung als neues Projekt erscheint und
   niemand es merkt.
7. **Der Bestand ist erhoben.** Enthaelt der vorhandene Projektkatalog Paare,
   die nach dem neuen Kriterium dasselbe Projekt waeren, werden sie **benannt**
   — mit Locator und Anzahl. Automatisch verschmolzen wird nichts.
8. **Realitaetsnachweis:** zwei getrennte Arbeitskopien desselben Repositories
   auf demselben Rechner, beide registriert, gegen einen echten laufenden Kern.
   Ein Nachweis, der beide Registrierungen im selben Prozess und mit demselben
   Zustand fuehrt, erfuellt dieses Kriterium nicht.
9. **Konzept nachgezogen** (FK-10) mit Decision Record und
   Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–9 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Volle Suite gruen, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
  `darwin`; Coverage haelt 85 %.
- Jenkins gruen gegen den Kandidaten-SHA, Sonar-Gate OK.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Beantwortete Frage — PO-Entscheidung 2026-08-03

Das Identitaetskriterium ist entschieden: **der `project_key` wird aus dem
Root-Repository abgeleitet**, ein frei waehlbarer **Alias** bedient die
Oberflaeche. Damit entfaellt der getippte Schluessel als Identitaetstraeger.

Die Alternative — ein serverseitig vergebener Bezeichner, den der erste Bediener
bekommt und der zweite eingibt — ist damit **verworfen**: sie verlagert eine
Uebergabe auf den Menschen, waehrend die Anforderung ausdruecklich lautete, dass
die Zuordnung **automatisch** geschieht.

**Offen bleibt allein AC 6a** (Verhalten bei Umbenennung des
Root-Repositories); dem PO bei Umsetzungsbeginn vorzulegen, sobald die
Ableitungsregel steht.

## Guardrail-Referenzen

- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — ein getippter Schluessel ist
  kein Identitaetsmodell; eine Dublettenpruefung darauf waere ein Symptomfix.
- `CLAUDE.md` „FAIL-CLOSED" — unbestimmbare Identitaet bricht ab.
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT" — ein Projekt, eine
  serverseitige Instanz.
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 8 verlangt zwei
  echte Arbeitskopien gegen einen echten Kern.
