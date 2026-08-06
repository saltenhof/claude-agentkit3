# AG3-230 — Der Installer bringt alles mit

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `unblocks: [AG3-217]` — eine Neuregistrierung ohne diese
  Story wuerde denselben Fehler erneut materialisieren
- **Herkunft:** PO-Vorgabe vom 2026-08-06

## Die Zielarchitektur

> „Es gibt einen Installer, und der bringt alles mit, was es braucht. Der darf
> nirgendwo hin verweisen auf irgendwelche anderen Verzeichnisse und darauf
> bauen, dass dort schon irgendwas rumliegt, was der lokale Hook oder sonst wer
> braucht."

Das Backend laeuft auf einem zentralen Server. Auf dem Entwicklerrechner liegt
**Project Edge**, und alles, was dort hin soll, wird von AK3 **explizit dorthin
installiert** — inklusive saemtlicher Bibliotheken. Die Zielmaschine hat keinen
Zugriff auf die AK3-Codebase und kann sich keine Python-Bibliotheken ziehen.

Die Folge ist die eigentliche Zusage dieser Story:

> **Ein instabiler Zustand in der AK3-Codebase auf einem anderen Rechner ist
> fuer die Projekte, die AK3 verwenden, unsichtbar.**

## Der Ist-Zustand ist ein fataler Fehler, kein Randfall

Gemessen an `T:\codebase\intima` am 2026-08-06.

**Installiert wurden zwei Dateien:**

```
tools/agentkit/concept_toolchain
tools/agentkit/projectedge.py
```

Keine eigene Umgebung, keine Bibliotheken.

**Dafuer drei Verweise zurueck in den Entwicklungsbaum:**

```
tools/hooks/pre-commit                 'T:\codebase\claude-agentkit3\.venv\Scripts\python.exe'
.codex/config.toml           command = "T:\\codebase\\claude-agentkit3\\.venv\\Scripts\\python.exe"
.agentkit/config/control-plane.json   "ca_file": "T:\\codebase\\claude-agentkit3\\var\\devcert\\cert.pem"
```

Nicht nur der Interpreter — auch der **TLS-Vertrauensanker** zeigt dorthin.

**Die Ursache:** `resolve_ak3_interpreter()`
(`backend/installer/interpreter.py:38`) liefert `sys.executable`, also den
Interpreter **des Prozesses, der gerade installiert**. Das ist richtig, solange
der Installer *innerhalb* der Project-Edge-Installation laeuft. Hier lief er aus
dem Quell-Checkout — es gibt an dieser Stelle keine Trennung zwischen „wo AK3
gerade laeuft" und „was auf der Zielmaschine liegen muss".

**Auf einer echten Client-Maschine gibt es kein `T:\codebase\claude-agentkit3`.**
Diese Installation waere tot, bevor sie das erste Mal laeuft. Was hier
funktioniert, funktioniert ausschliesslich, weil Entwicklungsbaum und
Zielprojekt auf derselben Platte liegen.

**Der intima-Totalausfall vom 2026-08-06 ist daraus vollstaendig erklaerbar.**
Nicht „der Arbeitsbaum ist zufaellig produktiv", sondern: es existiert gar keine
installierte Fassung, die etwas anderes haette sein koennen. Dort war ein Commit
nur noch mit `--no-verify` moeglich — wir haben einen fremden Entwickler
gezwungen, seine eigenen Guardrails zu umgehen.

## Scope

### In Scope

- **Der Installer materialisiert eine vollstaendige, eigenstaendige Project-Edge-
  Installation im Zielprojekt** — Laufzeit, alle von AK3 benoetigten
  Bibliotheken, Hooks, Prompts, Manifeste, Vertrauensanker.
- **Kein materialisiertes Artefakt verweist auf einen Pfad ausserhalb der
  Zielinstallation.** Nicht der Interpreter, nicht der Vertrauensanker, nicht
  die Konfiguration, nicht ein Hook.
- **Die Beschaffung liegt beim Installer, nicht bei der Zielmaschine.** Kein
  `pip install` zur Installationszeit auf der Zielmaschine, kein Netzzugang, kein
  vorausgesetztes Werkzeug ausser dem, was der Installer selbst mitbringt.
- **Die Trennung zwischen „wo AK3 laeuft" und „was installiert wird"** wird
  modelliert. `resolve_ak3_interpreter()` beantwortet die erste Frage; die
  zweite braucht einen eigenen Eigentuemer.
- **Upgrade zieht mit.** Eine bestehende Installation, die heute auf den
  Entwicklungsbaum zeigt, wird beim Upgrade auf die eigenstaendige Form
  gehoben — sichtbar gemeldet, nicht still.
- **Normative Verankerung** in FK-10 (Runtime/Deployment) und FK-50
  (Installer/Checkpoints) samt Decision Record.

### Out of Scope

- Die Frage, welche Bibliotheken Project Edge braucht, ist **nicht** offen: Es
  sind die, die der materialisierte Code importiert. Findet die Umsetzung
  heraus, dass Project Edge mehr braucht als erwartet, ist das ein Befund mit
  Vorlage — kein Anlass, den Umfang zu kuerzen.
- Die Aufteilung Backend/Server gegen Project Edge wird nicht neu verhandelt.

## Akzeptanzkriterien

1. **Kein materialisiertes Artefakt im Zielprojekt enthaelt einen Pfad ausserhalb
   der Zielinstallation.** Nachgewiesen durch einen deterministischen Sweep
   ueber **alle** materialisierten Dateien — Hooks, Harness-Konfigurationen,
   `.agentkit/**`, Vertrauensanker —, nicht durch Sichtpruefung. Der Sweep
   nennt seine Methode.
2. **Der Nachweis laeuft auf einer Maschine ohne AK3-Checkout.** Eine
   Installation in einem Container ohne AK3-Quellen, ohne Netzzugang und ohne
   vorbereitete Python-Umgebung; danach laeuft ein echter Commit mit aktiven
   Hooks durch. **Alles andere beweist nur, dass beide Haelften zufaellig
   nebeneinanderliegen** (`CLAUDE.md` §REALITAETSNACHWEIS AN
   FREMDSYSTEM-GRENZEN).
3. **Ein Regelbruch faellt maschinell auf, bevor er landet.** Ein Gate weist
   jeden materialisierten Verweis auf einen installationsfremden Pfad ab. Es
   ist gegen einen kuenstlich eingefuegten Verstoss geprueft — ein Gate, das
   falsch gruen meldet, entwertet jede Aussage, die es je gemacht hat.
4. **Bestandsinstallationen werden gehoben.** `T:\codebase\intima` (und jedes
   andere registrierte Projekt) zeigt nach dem Upgrade auf seine eigene
   Installation. Die Aenderung wird sichtbar gemeldet, mit Projekt und Feld.
5. **Der Vertrauensanker gehoert dazu.** Ein Zielprojekt vertraut nach der
   Installation keinem Zertifikat, das im Entwicklungsbaum liegt.
6. **Instabilitaet der AK3-Codebase ist unsichtbar.** Ein Test belegt, dass eine
   Aenderung an den AK3-Quellen ein bereits installiertes Zielprojekt **nicht**
   beeinflusst. Das ist die Kernzusage; ohne diesen Beleg ist die Story nicht
   fertig.
7. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle
   deterministischen Gates gruen; volle Suite gruen auf Jenkins; Coverage haelt
   die 85-%-Schwelle.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg.
- AC 2 ist **nicht** durch eine Simulation ersetzbar. Faellt der Lauf aus, ist
  das eine benannte Luecke mit Grund — nie „gruen".
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — AC 2 und AC 6
- `CLAUDE.md` §FEHLENDES BESCHAFFEN STATT UMGEHEN — der Installer beschafft,
  die Zielmaschine nicht
- `CLAUDE.md` §ZERO DEBT RULE — der belegte Anlassfall steht oben, samt dem
  `--no-verify`, zu dem wir jemanden gezwungen haben
- `CLAUDE.md` §FAIL-CLOSED — AC 3
