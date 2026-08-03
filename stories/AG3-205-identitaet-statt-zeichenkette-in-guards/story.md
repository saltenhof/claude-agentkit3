# AG3-205 — Guards entscheiden Identitaet, nicht Zeichenketten

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** FK-05 (Guards), FK-10 §10.2.9 (Detach), FK-51 §51.6
  (Hook-Registrierung), `guardrails/architecture-guardrails.md`
- **Herkunft:** Acht unabhaengige Codex-Reviewrunden am 2026-08-02/03 zum
  Secret-Scan-Hotfix. Ab Runde 7 wanderten die Befunde aus dem Hotfix heraus in
  die Governance-Schicht: dieselbe Fehlerklasse, funfmal, davon zweimal
  sicherheitswirksam. Diese Story schneidet, was **nicht** zum Hotfix gehoert.

## Kontext

### Die Fehlerklasse — eine, nicht funf

Jeder betroffene Ort entscheidet eine **Identitaet** — welches Kommando wird
ausgefuehrt, welche Datei ist gemeint, welcher Endpunkt wird gerufen — und
implementiert diese Entscheidung als **Zeichenkettenvergleich**. Der Name
behauptet Identitaet, die Implementierung prueft ein Vorkommen.

Der Schaden geht in **beide** Richtungen, und beide sind belegt:

- **Fail-open:** `agentkit reset-story && git push --force origin main` galt als
  offizielles Kommando (behoben im Hotfix). `agentkit reset-story & git push
  --force` galt es weiterhin, weil ein einzelnes `&` in der Sperrliste fehlte.
- **Fail-closed am falschen Ort:** `echo "do not push --force into docs"` wird
  als gefaehrliche Mutation blockiert. Ein Pfad `/repo/not.git` ebenso.

Beides ist derselbe Defekt. Und beides ist so teuer wie der Anlassfall dieses
ganzen Strangs: ein Gate, das korrekte Arbeit ablehnt, erzieht zu `--no-verify`;
ein Gate, das Zerstoerung durchlaesst, schuetzt nie wieder.

### Befunde, alle reproduziert

| Ort | Eingabe | Ergebnis |
|---|---|---|
| `branch_guard._is_official_allow_path` | `agentkit reset-story & git push --force origin main` | erlaubt, vor jeder Gefahrenpruefung |
| `branch_guard._target_branch` | `FOO=1 git switch main`, `env git checkout main`, `/usr/bin/git checkout main`, `command git rebase main` | Branch-Wechsel unerkannt |
| `branch_guard` Gefahrenmuster | `echo "do not push --force into docs"`, `echo "rm .git/config"` | faelschlich blockiert |
| `branch_guard` Pfadschutz | `/repo/not.git` blockiert; `.GIT/config` unter Windows erlaubt | beide falsch |
| `artifact_guard._is_active_story_qa_dir` | `T:\repo\_TEMP\QA\AG3-1\structural.json` | erlaubt, obwohl derselbe Pfad |
| `story_creation_guard` | `echo agentkit story create`, `POST /archive?next=/v1/stories` | gilt als Story-Erzeugung |
| `skill_usage_check` | `echo agentkit semantic-review` | gilt als Ad-hoc-Review, blockiert |
| `scope_guard` | erlaubt `T:\Repo\Worktree`, Ziel `t:\repo\worktree\x.py` | blockiert; Junction nach draussen erlaubt |

### Zweiter Gegenstand: Feldvertraege der generischen Git-Leser

`CompositionSubprocessGitBackend`, `composition_verify._git`,
`commit_hook._git_output` und `command_executor._run_git` dekodieren **alle**
Felder mit einem Codec. Sie liefern aber gemischt: fremde Pfade und Diffs (die
verlustfrei bleiben muessen) und ASCII-Maschinenwerte wie SHA, Branch und
Revision (die eine Protokollverletzung fail-closed melden muessen). Ein
`abc\udce4` aus `rev-parse HEAD` landet ueber `CandidateRef` in
`urllib.parse.urlencode` und wirft dort `UnicodeEncodeError` — reproduziert.

Der Decision Record vom 2026-08-03 fordert bereits den Vertrag des einzelnen
Feldes. Diese Leser erfuellen ihn nicht.

### Dritter Gegenstand: FK-51 beschreibt einen Producer, den es nicht gibt

FK-51 §51.6 fuehrt das Kommando-Muster `python -m agentkit.` fuer registrierte
Hooks. Der tatsaechliche Producer emittiert ausschliesslich
`agentkit-hook-claude` und `agentkit-hook-codex`. Der Hotfix hat Detach auf den
realen Producer zurueckgeschnitten; **die Konzeptaussage bleibt offen** und
gehoert hierher — nicht als stille Anpassung des Codes an die Prosa oder
umgekehrt.

## Scope

### In Scope

- **Ein** gemeinsames Modell fuer „welches Kommando wird ausgefuehrt" und
  **ein** gemeinsames Modell fuer Pfadidentitaet; alle Guards benutzen sie.
- Pfadidentitaet heisst: Plattform-Case-Semantik, `..`-Aufloesung und
  Link-/Junction-Aufloesung — nicht `normpath` plus `startswith`.
- Kommandoidentitaet heisst: das ausgefuehrte Programm, hinter
  Umgebungspraefixen (`FOO=1`), `env`, `command`, absoluten Pfaden — und Text in
  `echo`/`printf` ist kein Kommando.
- HTTP-Identitaet heisst: normalisierter Pfad plus Methode, nicht Teilstring in
  der URL.
- Feldvertraege in den generischen Git-Lesern.
- FK-51 §51.6 und der reale Producer werden zur Deckung gebracht.

### Out of Scope

- Der Secret-Scan-Hotfix selbst (`fccf101b..ff0aa56c`) — abgeschlossen.
- Neue Guards oder neue Regeln. Diese Story macht die vorhandenen Regeln
  **wahr**, sie verschaerft nichts.

## Akzeptanzkriterien

1. **Ein Modell, nicht funf.** Kommando- und Pfadidentitaet liegen je an genau
   einer Stelle; jeder Guard ruft sie auf. Eine zweite Heuristik daneben ist
   ein Fehler, kein Sonderfall.
2. **Jeder Befund der Tabelle oben ist ein Regressionstest**, mit der dort
   genannten Eingabe.
3. **Die vom Review verlangten Faelle sind abgedeckt** — BranchGuard: einzelnes
   `&`, `FOO=1 git`, `env git`, absoluter Git-Pfad, `command git`, harmlose
   `echo`/`printf`-Texte mit `push --force` und `rm .git/config`,
   `/repo/not.git` bleibt erlaubt, `.GIT/config` blockiert unter Windows,
   exakte offizielle Kommandos mit Argumenten bleiben erlaubt. ArtifactGuard:
   kanonischer Pfad blockiert, `not_temp/qa` erlaubt, Windows-Casevarianten
   blockieren, Story-ID als exaktes Segment, `..`-Normalisierung,
   Junction-Alias auf ein geschuetztes Artefakt.
4. **Beide Richtungen sind belegt.** Fuer jeden Guard existiert mindestens ein
   Test, der zeigt, dass er nicht ueberschiesst — ein blockierender Guard mit
   Fehlalarm ist derselbe Schaden wie ein durchlaessiger.
5. **Feldvertraege umgesetzt:** die generischen Git-Leser dekodieren SHA,
   Branch und Revision strikt und fremde Pfade/Diffs verlustfrei; nachgewiesen
   an einem Wert mit ungueltigem Byte, der fail-closed auffaellt statt in
   `urlencode` zu laufen.
6. **FK-51 §51.6 und der Producer stimmen ueberein**, mit Decision Record.
7. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/05_*` — Guard-Modell
- `concept/technical-design/10_*` §10.2.9 — chirurgisches Detach
- `concept/technical-design/51_upgrade_migration_customization_preservation.md`
  §51.6 — Hook-Registrierung und Kommando-Muster
- `concept/_meta/decisions/2026-08-03-secret-scan-prueft-form-nicht-zeichenfolge.md`
  — die Feldvertragsregel, die hier eingeloest wird

## Guardrail-Referenzen

- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — funf Heuristiken sind das
  Modellproblem; jede einzeln zu flicken war in Runde 7 und 8 nachweislich
  nicht genug.
- `CLAUDE.md` „NO ERROR BYPASSING" — ein Guard, der am Praefix vorbei erlaubt,
  ist ein Bypass, kein Randfall.
- `CLAUDE.md` „ZERO DEBT RULE" — die Befunde sind vorgefunden; sie werden
  sichtbar gehalten und behoben, nicht umgedeutet.
