# AG3-189 — AK3-Interpreter- und Installationsisolation

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-187
- **Quell-Konzept:** FK-10 (Runtime/Deployment, Interpreterbindung), FK-22
  (Preflight)
- **Herkunft:** Erste echte Fremdinstallation am 2026-08-02. Ausgezogen aus
  AG3-180 am 2026-08-02 nach unabhaengigem Codex-Review des Schnitts aus
  Commit `77b4b034` (Auflage ERROR-5).

## Kontext

### Befund — belegt, mit Locator

Auf der Entwicklungsmaschine zeigt `_editable_impl_agentkit.pth` im Benutzer-
`site-packages` auf `T:\codebase\claude-agentkit3\src`. Das ist genau die
Konstellation, vor der `CLAUDE.md` warnt: **AK3 und AK2 teilen den Paketnamen
`agentkit`.** Ein globaler Install ueberschreibt AK2 und zerstoert dessen
Claude-Code-Hooks.

Sie ist ausserdem der Grund, warum ein beliebiger PATH-Python AK3 ueberhaupt
importieren konnte — und damit der Grund, warum der Interpreter-Defekt so lange
unentdeckt blieb, der am 2026-08-02 in zwei Commits behoben wurde:
`01a27de1` („MCP-Interpreter binden") und `cb3662c4` („Git-Hooks dispatchen
ueber den aufgeloesten AK3-Interpreter"). Solange jeder Python das Paket sieht,
faellt eine fehlende Interpreterbindung nirgends auf.

### Was am ersten Schnitt falsch war

Der urspruengliche AC8 lautete: „Entweder AK3 laesst sich nicht mehr global
editierbar installieren, **oder** es erkennt die Konstellation und warnt beim
Start." Die Warnalternative ist unzulaessig:

- `CLAUDE.md` (§Operations) sagt **„Niemals `pip install` ohne venv-Prefix"** —
  das ist eine PO-Grundregel, keine Empfehlung, die eine Warnung erfuellen
  koennte.
- Nach der Severity-Semantik aus `CLAUDE.md` und `AGENTS.md` ist ein WARNING ein
  „Handlungsauftrag mit aufschiebender Wirkung". Der Schaden hier tritt aber
  **sofort** ein und trifft ein **anderes Produkt** (AK2), dessen Betreiber die
  Warnung nie sieht. „Wo aufschiebbares Handeln in der Praxis nicht passiert,
  ist ERROR die richtige Wahl."
- Eine Warnung, die ein Agent in einem nicht-interaktiven Lauf erzeugt, ist eine
  Zeile in einem Protokoll, das niemand liest.

## Scope

> **Neuschnitt 2026-08-03 (PO-Entscheid).** AG3-206 trug dasselbe
> venv-Kriterium. Diese Story ist ab jetzt der **alleinige** Eigentuemer der
> Durchsetzung: Installationsart, Interpreterbegriff, Verweigerung. AG3-206
> behaelt ausschliesslich die **Vollstaendigkeit** der Umgebung (deklarierte
> gegen importierbare Abhaengigkeiten) und die Sichtbarkeit verschluckter
> Hook-Fehler. Aus AG3-206 hierher gewandert ist auch deren offene Frage:
> **legt AK3 die venv selbst an, oder verlangt es eine vorhandene und
> verweigert sonst den Dienst?** Beides erfuellt den Decision Record; die Wahl
> bestimmt, ob der Installer Umgebungen erzeugt oder nur prueft.

> **PO-ENTSCHEID 2026-08-04 — beide offenen Fragen sind beantwortet.**
>
> **(a) AK3 legt die venv selbst an.** Der Installer erzeugt sie, er prueft sie
> nicht nur. Die Alternative wuerde verlangen, dass der Nutzer weiss, was AK3
> alles braucht, und es von Hand installiert — das ist genau die Aufgabe, fuer
> die ein Installer existiert. Eine vorhandene venv vorauszusetzen und sonst
> den Dienst zu verweigern ist damit **ausgeschlossen**, nicht nur nachrangig.
>
> **(b) Die Isolation bleibt dauerhaft, ueber AG3-209 hinaus.** Die Annahme,
> AG3-208/AG3-209 wuerden diese Story gegenstandslos machen, ist falsch: sie
> loesen den *Paketnamenskonflikt* mit AK2, nicht das *Isolationsproblem*. AK3
> bringt Drittbibliotheken mit. Werden die systemweit sichtbar gemacht,
> kollidieren sie mit dem, was auf der fremden Maschine ohnehin installiert
> ist. Die Maschine, auf der der Client ProjectEdge betreibt, gehoert uns
> nicht — wir kontaminieren sie nicht, weder mit unseren Abhaengigkeiten noch
> mit AK3 selbst. Die Isolation ist also kein Provisorium bis AG3-209, sondern
> die dauerhafte Betriebsform. Die durchgestrichene Out-of-Scope-Praemisse
> unten bleibt sachlich richtig (der Namenskonflikt stirbt), aendert aber an
> dieser Story nichts.

### In Scope

- Fail-closed-Verweigerung einer globalen (nicht-venv) Installation von AK3.
- Ein einziger, aufloesbarer AK3-Interpreterbegriff, den alle Einsprungpunkte
  benutzen (CLI, Installer, Git-Hooks, MCP-Server, Harness-Hooks).
- Bereinigung der bestehenden globalen editierbaren Installation als
  dokumentierter, ausfuehrbarer Weg.
- Normative Nachfuehrung in FK-10 (Interpreterbindung, Installationsgrenze)
  samt Decision Record.

### Out of Scope

- Kein Umbau der `pyproject.toml`-Paketstruktur ueber das hinaus, was die
  Verweigerung braucht.
- Keine Umbenennung des Paketnamens `agentkit`. Der Namenskonflikt mit AK2 wird
  hier **isoliert**, nicht aufgeloest.
  **ACHTUNG — diese Praemisse ist ueberholt (2026-08-03).** Die Grundentscheidung
  ist inzwischen gefallen: `agentkit` ist der Framework-Name und gehoert keinem
  Artefakt allein; jede Distribution bekommt eine eigene, kollisionsfreie
  Importwurzel (Decision Record
  `concept/_meta/decisions/2026-08-03-edge-und-kern-sind-zwei-distributionen.md`
  §4.1, umgesetzt in AG3-208/AG3-209). **Damit stirbt der AK2-Konflikt, statt
  eingezaeunt zu werden.** Vor Umsetzungsbeginn ist deshalb zu klaeren, ob diese
  Story ihre Isolation ueberhaupt noch braucht oder nur noch den Zeitraum bis
  AG3-209 ueberbrueckt. Das entscheidet der PO, nicht der Implementierer.
- Die bereits gelandeten Interpreter-Fixes (`01a27de1`, `cb3662c4`) werden
  nicht erneut gemacht; diese Story sorgt dafuer, dass ihr Fehlen kuenftig
  auffaellt.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `pyproject.toml` | geaendert | Build-/Install-Hook, der eine Installation ausserhalb eines venv fail-closed abweist |
| `src/agentkit/backend/` (Interpreter-Aufloesung) | geaendert | genau ein Ort, der den AK3-Interpreter bestimmt |
| `src/agentkit/backend/installer/` | geaendert | Preflight-Checkpoint „Installation ist isoliert" |
| `src/agentkit/bundles/target_project/` (Hook-Assets) | geaendert | Hooks rufen den aufgeloesten Interpreter, nie `python` vom PATH |
| `concept/technical-design/10_runtime_deployment_speicher.md` | geaendert | Installationsgrenze und Interpreterbindung normativ |
| `concept/technical-design/22_setup_preflight_worktree_guard_activation.md` | geaendert | Preflight-Checkpoint |
| `concept/_meta/decisions/2026-XX-XX-installationsisolation.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/integration/installer/` | neu | Installationsversuch ausserhalb venv schlaegt fehl; Hook-Test ohne PATH-Injektion |

## Akzeptanzkriterien

1. **Eine globale, nicht-venv Installation von AK3 schlaegt fehl** — editierbar
   wie nicht-editierbar. Der Fehlschlag ist fail-closed und benennt den Grund
   (Paketnamenskonflikt mit AK2) und den zulaessigen Weg. **Eine Warnung
   erfuellt dieses Kriterium nicht.**

   **1a. Der Installer legt die venv selbst an** (PO-Entscheid 2026-08-04).
   Der zulaessige Weg aus AC 1 ist keine Anleitung, die der Nutzer befolgt,
   sondern ein Schritt, den der Installer ausfuehrt. Nachgewiesen an einer
   Maschine ohne vorbereitete Umgebung: ein einziger Installationsaufruf
   erzeugt die venv, installiert AK3 samt deklarierten Abhaengigkeiten hinein
   und hinterlaesst im System-`site-packages` nichts. Existiert bereits eine
   brauchbare venv, wird sie benutzt statt ersetzt; eine unbrauchbare wird mit
   benanntem Grund abgelehnt, nicht stillschweigend repariert.

   **1b. Die Isolation ist die dauerhafte Betriebsform, kein Provisorium**
   (PO-Entscheid 2026-08-04). Sie schuetzt nicht nur AK2 vor dem geteilten
   Paketnamen, sondern die fremde Maschine vor den Drittbibliotheken, die AK3
   mitbringt. Begruendung und Verweigerung duerfen deshalb **nicht** allein auf
   den AK2-Namenskonflikt abstellen — sonst wird die Regel mit AG3-209
   gegenstandslos, obwohl der Grund fortbesteht.
2. **Die heute vorhandene globale editierbare Installation ist beseitigt** und
   der Weg dorthin ist dokumentiert und ausfuehrbar. Nachgewiesen daran, dass
   `_editable_impl_agentkit.pth` im Benutzer-`site-packages` danach nicht mehr
   existiert und ein PATH-Python `import agentkit` **nicht** aufloest.
3. **Es gibt genau einen Ort, der den AK3-Interpreter bestimmt.** Alle
   Einsprungpunkte — CLI, Installer, Git-Hooks, MCP-Server, Harness-Hooks —
   beziehen ihn von dort. Nachgewiesen daran, dass eine Aenderung an diesem
   einen Ort **alle** Einsprungpunkte umlenkt; eine repo-weite Suche nach
   direkten `python`/`sys.executable`-Aufrufen in Einsprungpunkten weist jeden
   verbleibenden Treffer namentlich aus.
4. **Ein Einsprungpunkt, der `python` vom PATH nimmt, faellt maschinell auf**,
   bevor er landet. Diese Pruefung laeuft im selben Gate wie die uebrigen
   Lint-/Typ-Pruefungen, nicht als optionales Skript.
5. **Der Nachweis laeuft ohne PATH-Injektion.** Der heutige Test
   `test_real_hook_pair_...` injiziert ein falsches `python` ueber den PATH und
   *verlangt*, dass der Hook es aufruft — er schreibt damit den defekten
   Vertrag fest. Der neue Nachweis zeigt das Gegenteil: der Hook laeuft korrekt,
   **obwohl** ein falsches `python` im PATH steht. Der alte Test ist korrigiert
   oder entfernt, nicht ergaenzt.
6. **Ein realer Commit im Fremdprojekt laeuft durch.** Nachgewiesen an einer
   Installation in ein Projekt ausserhalb dieses Repos, in dem anschliessend
   ein Commit mit aktiven Hooks gelingt — der Fall, an dem es am 2026-08-02
   gescheitert ist.
7. **Konzept nachgezogen** (FK-10, FK-22) mit Decision Record und
   Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Coverage haelt die 85-%-Schwelle.
- Alle deterministischen Konzept-Gates gruen; Decision Record im Diff oder
  gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/10_runtime_deployment_speicher.md` — Laufzeit- und
  Deployment-Grenzen
- `concept/technical-design/22_setup_preflight_worktree_guard_activation.md` —
  Preflight-Checkpoints
- `PROJECT_STRUCTURE.md` — `src/`-Layout, Deployment-Unit-first

## Guardrail-Referenzen

- `CLAUDE.md` §Operations — „Niemals `pip install` ohne venv-Prefix"; AK2 und
  AK3 teilen den Package-Namen `agentkit`.
- `CLAUDE.md` „SEVERITY-SEMANTIK" — hier ist ERROR die richtige Stufe; eine
  Warnung ist kein Schutz.
- `CLAUDE.md` „NO ERROR BYPASSING" — keine Umgehungspfade.
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 6 verlangt einen
  echten Commit in einem echten Fremdprojekt.
