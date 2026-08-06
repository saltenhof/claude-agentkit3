# AG3-230 — Der Installer bringt alles mit, einmal pro Maschine

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `unblocks: [AG3-217]` — eine Neuregistrierung ohne diese
  Story wuerde denselben Fehler frisch materialisieren
- **Herkunft:** PO-Vorgabe vom 2026-08-06, praezisiert am selben Tag

## Die Zielarchitektur

> „Es gibt einen Installer, und der bringt alles mit, was es braucht. Der darf
> nirgendwo hin verweisen auf irgendwelche anderen Verzeichnisse und darauf
> bauen, dass dort schon irgendwas rumliegt, was der lokale Hook oder sonst wer
> braucht."

**Praezisierung des PO (2026-08-06): eine Maschinen-Runtime, keine
projektlokale.**

> „Wenn Du auf einem Rechner zum Beispiel drei Projekte hast, dass es an einer
> zentralen Stelle — zum Beispiel irgendwo im Userhome-Verzeichnis — die
> zentralisierten Bibliotheken gibt, die sich alle drei Projekte teilen. Und
> wenn Du ein Update installieren moechtest, dass Du das dann auch nur einmal
> installieren musst und nicht fuer alle drei parallel."
>
> „Richtig ist, dass die Runtime genauso sauber isoliert ist wie die
> projektlokalen Sachen auch. Also dass die Runtimes nicht uebergriffig sind
> auf ganz andere Python-Tools und sich ohne venv in die Systemkonfiguration
> einnisten."

Daraus folgen vier Eigenschaften, und **alle vier sind Zusagen**, nicht
Wuensche:

1. **Eine Stelle je Maschine**, im Benutzerbereich — nicht systemweit, nicht
   pro Projekt.
2. **Geteilt von allen Projekten** dieser Maschine.
3. **Ein Update, einmal installiert**, wirkt fuer alle Projekte — jedenfalls,
   soweit es nur die Runtime betrifft.
4. **Genauso isoliert wie AG3-189 es fuer AK3 selbst erzwungen hat:** eigene
   venv, keine System-`site-packages`, kein Uebergriff auf fremde
   Python-Werkzeuge, kein Einnisten in die Systemkonfiguration.

Und die tragende Zusage bleibt:

> **Ein instabiler Zustand in der AK3-Codebase ist fuer die Projekte, die AK3
> verwenden, unsichtbar.**

## Was die Maschinen-Runtime enthaelt — und was nicht

Sie traegt **Project Edge und dessen Abhaengigkeiten**. Sie traegt **nicht** den
Kern. `META-DEC-2026-08-03-EDGE-UND-KERN-SIND-ZWEI-DISTRIBUTIONEN` hat
entschieden, dass Edge den Kern nicht importiert; AG3-208/209 trennen die
Distributionen. **Diese Story zementiert diesen Schnitt nicht ein, sie setzt
ihn voraus.** Faellt bei der Umsetzung auf, dass Edge heute doch den Kern
braucht, ist das ein Befund mit Vorlage — kein Anlass, den Kern auf jede
Maschine zu schieben.

Damit ist auch **FK-10 §10.2.3** („AgentKit hat keine kanonische projektlokale
Runtime") gewahrt: Eine Maschinen-Runtime ist nicht projektlokal. Der frueher
befuerchtete Konzeptkonflikt entfaellt.

## Der belegte Ist-Zustand

Gemessen an `T:\codebase\intima` am 2026-08-06. Installiert wurden **zwei
Dateien** (`tools/agentkit/concept_toolchain`, `tools/agentkit/projectedge.py`),
keine Umgebung, keine Bibliotheken. Dafuer **drei Verweise zurueck** in den
Entwicklungsbaum:

```
tools/hooks/pre-commit                 'T:\codebase\claude-agentkit3\.venv\Scripts\python.exe'
.codex/config.toml           command = "T:\\codebase\\claude-agentkit3\\.venv\\Scripts\\python.exe"
.agentkit/config/control-plane.json   "ca_file": "T:\\...\\var\\devcert\\cert.pem"
```

Auch der **TLS-Vertrauensanker** zeigt dorthin.

**Ursache:** `resolve_ak3_interpreter()` (`backend/installer/interpreter.py:38`)
liefert `sys.executable` — den Interpreter **des Prozesses, der installiert**.
Es gibt keine Trennung zwischen „wo AK3 gerade laeuft" und „was auf der
Zielmaschine liegen muss". Auf einer echten Client-Maschine gibt es kein
`T:\codebase\claude-agentkit3`; die Installation waere tot, bevor sie das erste
Mal laeuft.

**Der intima-Totalausfall vom 2026-08-06 ist daraus vollstaendig erklaerbar.**
Dort war ein Commit nur noch mit `--no-verify` moeglich — wir haben einen
fremden Entwickler gezwungen, seine eigenen Guardrails zu umgehen.

## Zwei Funde, die den Umbau schwerer machen als er aussieht

**1. Der Venv-Pfad ist ein Cache-Schluessel, keine blosse Zeichenkette.**
`installer/paths.py:183-195` faltet `ak3_interpreter_command` und
`ak3_wrapper_command` in `materialized_skill_variant_input_digest(...)`, der das
Variantenverzeichnis benennt. **Wer die Runtime verschiebt oder ersetzt,
verwaist stillschweigend jede materialisierte Skill-Variante** — die alten
Verzeichnisse bleiben, die Links zeigen darauf, niemand meldet es.

Das trifft diese Story doppelt: beim Umzug **und** bei jedem Runtime-Update
(Eigenschaft 3). Ein Update, das die Runtime ersetzt und die Varianten
verwaisen laesst, hat die Zusage nicht eingeloest, sondern verschoben.

**2. Es sind siebzehn Schreiber, nicht drei Artefakte.** Fuenf betten den
Venv-Pfad ein: `tools/hooks/pre-commit` und `post-commit`
(`git_hook_dispatch.py:251,262`), `.claude/settings.json` (**zwei unabhaengige
Produzenten**: `runner.py:605-612` und `settings_writer.py:477`),
`.codex/config.toml`, `.mcp.json` (`cp10_mcp_registration.py:213,290`).
`.installed-manifest.json` ist sauber. Die absoluten Projektwurzel-Pfade in
`.codex/config.toml` (`cwd`) und `.mcp.json` (`concepts_dir`, `stories_dir`)
sind Selbstbezuege und korrekt **keine** Verstoesse.

Dazu zwei weitere nicht-eigenstaendige Baeume: `prompts/` als Hardlinks nach
`%PROGRAMDATA%\AgentKit\prompt-bundles`, und `.claude|.codex/skills/` als
Verzeichnis-Links nach `%PROGRAMDATA%` oder in `site-packages`.

## Scope

### In Scope

- **Eine Maschinen-Runtime im Benutzerbereich**, vom Installer angelegt und
  gepflegt, geteilt von allen Projekten dieser Maschine.
- **Sie ist isoliert wie AK3 selbst**: eigene venv, keine System-`site-packages`,
  kein Uebergriff auf fremde Python-Werkzeuge, kein systemweiter Eingriff.
- **Kein materialisiertes Artefakt verweist auf einen Pfad ausserhalb der
  Zielinstallation oder der Maschinen-Runtime.** Weder Interpreter noch
  Vertrauensanker noch Konfiguration noch Hook.
- **Ein Runtime-Update wirkt einmal fuer alle Projekte** — und laesst keine
  verwaisten Skill-Varianten zurueck.
- **Die Trennung „wo AK3 laeuft" gegen „was installiert wird"** wird modelliert.
  `resolve_ak3_interpreter()` beantwortet die erste Frage; die zweite braucht
  einen eigenen Eigentuemer.
- **Upgrade zieht Bestandsinstallationen mit**, sichtbar gemeldet.
- Normative Nachfuehrung in FK-10 und FK-50, Decision Record.

### Out of Scope

- Der Distributionsschnitt Edge/Kern. Er ist entschieden (AG3-208/209) und wird
  vorausgesetzt.
- Welche Bibliotheken Edge braucht, ist **keine offene Frage**: Es sind die, die
  der materialisierte Code importiert. Ergibt die Messung mehr als erwartet,
  ist das ein Befund mit Vorlage, kein Anlass, den Umfang zu kuerzen.

## Akzeptanzkriterien

1. **Kein materialisiertes Artefakt enthaelt einen Pfad ausserhalb der
   Zielinstallation oder der Maschinen-Runtime.** Deterministischer Sweep ueber
   **alle** siebzehn Schreiber, nicht per Sichtpruefung; die Methode wird
   genannt. Die bekannten Selbstbezuege (`cwd`, `concepts_dir`, `stories_dir`)
   sind ausdruecklich ausgenommen.
2. **Der Nachweis laeuft auf einer Maschine ohne AK3-Checkout**, ohne Netzzugang
   und ohne vorbereitete Python-Umgebung; danach gelingt ein echter Commit mit
   aktiven Hooks. **Ein anderes Verzeichnis auf derselben Platte genuegt
   nicht** — das beweist nur, dass beide Haelften nebeneinanderliegen.
3. **Die Runtime ist nicht uebergriffig.** Belegt: keine System-`site-packages`
   sichtbar, kein Eintrag ausserhalb des Benutzerbereichs, kein fremdes
   Python-Werkzeug auf der Maschine veraendert. Das ist dieselbe Zusage, die
   AG3-189 fuer AK3 selbst erzwungen hat — hier fuer die Runtime.
4. **Zwei Projekte teilen eine Runtime.** Belegt an zwei Installationen auf
   derselben Maschine: eine Runtime, zwei Projekte, beide lauffaehig.
5. **Ein Runtime-Update wirkt einmal fuer beide** — und **verwaist keine
   Skill-Variante**. Der Digest-Fund oben ist der Pruefstein: Nach dem Update
   zeigt kein Link auf ein totes Variantenverzeichnis, und es bleibt keines
   unbenannt zurueck.
6. **Bestandsinstallationen werden gehoben**, sichtbar gemeldet mit Projekt und
   Feld.
7. **Instabilitaet der AK3-Codebase ist unsichtbar.** Test: Eine Aenderung an
   den AK3-Quellen beeinflusst ein bereits installiertes Zielprojekt **nicht**.
   Das ist die Kernzusage; ohne diesen Beleg ist die Story nicht fertig.
8. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle
   deterministischen Gates gruen; volle Suite gruen auf Jenkins; Coverage haelt
   die 85-%-Schwelle.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg.
- AC 2 ist **nicht** durch eine Simulation ersetzbar. Faellt der Lauf aus, ist
  das eine benannte Luecke mit Grund — nie „gruen".
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN — AC 2, AC 7
- `CLAUDE.md` §FEHLENDES BESCHAFFEN STATT UMGEHEN — der Installer beschafft,
  die Zielmaschine nicht
- `CLAUDE.md` §ZERO DEBT RULE — der Anlassfall steht oben, samt dem
  `--no-verify`, zu dem wir jemanden gezwungen haben
- `CLAUDE.md` §FAIL-CLOSED — AC 5, keine stillen Waisen
