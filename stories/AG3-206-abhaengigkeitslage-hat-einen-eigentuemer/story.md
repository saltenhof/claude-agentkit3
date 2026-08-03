# AG3-206 — Die Abhaengigkeitslage bekommt einen Eigentuemer

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** `concept/_meta/decisions/2026-08-03-abhaengigkeiten-leben-in-einer-venv.md`,
  FK-10 (Installer), FK-51 (Upgrade/Migration)
- **Herkunft:** Fremdinstallation `intima`, 2026-08-03. PO-Entscheidung am
  selben Tag: venv.

## Kontext

### Befund — gemessen, nicht vermutet

Eine einzige Session, **164 Hook-Fehler**, zwei Ursachen:

| Anzahl | Hook | Ursache |
|---:|---|---|
| 90 | `agentkit-hook-claude {pre\|post} <id>` | `ModuleNotFoundError: No module named 'tomlkit'` |
| 74 | `python .agentkit/hooks/pre_tool_use.py` | `ModuleNotFoundError: No module named 'agentkit.governance'` |

`tomlkit` steht seit jeher als **Pflicht**-Abhaengigkeit in `pyproject.toml`. Es
fehlte trotzdem, und der Importfehler lief ueber **22 Stufen**, bevor er starb.
Ein einzelnes fehlendes Drittpaket hat damit die gesamte Guard-Kette
stillgelegt: `commit_hook`, `skill_usage_check`, `health_monitor`, `budget`,
`prompt_integrity` — keiner davon hat gelaufen, keiner hat es gemeldet.

Der zweite Defekt (Scaffold-Hook) ist am 2026-08-03 im Hotfix behoben. Der
erste ist es **nicht**: er ist keine Instanz, sondern ein fehlender Eigentuemer.

### Warum es niemand gemerkt hat

Fehlschlagende Hooks mit „non-blocking status code" erreichen das Modell nicht.
Sie stehen vollstaendig im Session-Transcript
(`~/.claude/projects/<slug>/<session-id>.jsonl`, Attachments vom Typ
`hook_non_blocking_error` mit komplettem Traceback) — aber nur, wenn jemand
zufaellig hinsieht.

**Ein Hook, der seinen eigenen Fehlschlag verschluckt, ist von einem
funktionierenden Hook nicht zu unterscheiden.** Dieselbe Bauart hat drei
unabhaengige Defekte an einem Tag verborgen; ein vierter (`tools/governance/*`
auf User-Ebene, mit `2>/dev/null || true`) taeuscht bis heute Erfolg vor.

## Scope

### In Scope

- **Preflight:** die deklarierten Abhaengigkeiten aus `pyproject.toml` werden
  gegen die **tatsaechlich importierbaren** geprueft, fail-closed.
- **Sichtbarkeit:** ein Werkzeug, das `hook_non_blocking_error`-Attachments aus
  den Transcripts aggregiert (nach Hook gruppiert, nach Fehlertext
  dedupliziert). Ohne das bleibt diese Fehlerklasse strukturell unsichtbar.
- Hooks, die ihren Fehlschlag verschlucken, verlieren diese Eigenschaft — oder
  der Verlust wird begruendet.

### Out of Scope

- **Die Durchsetzung der venv-Politik selbst — Owner: AG3-189.** Dass eine
  globale, nicht-venv Installation fail-closed abgewiesen wird und dass es
  genau **einen** aufloesbaren AK3-Interpreter gibt, traegt AG3-189 (dort AC 1
  und AC 3). Diese Story prueft die **Vollstaendigkeit** der Umgebung, nicht
  ihre **Art**. (Neuschnitt 2026-08-03 auf PO-Entscheid: beide Storys trugen
  dasselbe Kriterium.)
- Die Entscheidung venv vs. global — getroffen, siehe Decision Record.
- Der Scaffold-Hook — im Hotfix vom 2026-08-03 behoben.
- CCAG — auf PO-Ansage deaktiviert (Regeldateien fliegen aus dem Scaffold), der
  Code bleibt unangetastet in der Codebase.

## Akzeptanzkriterien

1. **Der Preflight faellt, bevor irgendetwas laeuft.** Eine fehlende
   Pflicht-Abhaengigkeit bricht die Installation mit Namen des Pakets und dem
   Kommando ab, das sie beschafft. Nachgewiesen an einer Umgebung, der genau
   ein deklariertes Paket fehlt.
2. **Der Nachweis laeuft gegen die Deklaration, nicht gegen eine Liste.** Eine
   neue Zeile in `pyproject.toml` ist ohne Codeaenderung mitgeprueft — eine
   gepflegte Zweitliste ist genau die zweite Wahrheit, die den Fall erzeugt hat.
3. **Die Hook-Fehlerklasse ist auswertbar.** Das Werkzeug liefert aus einem
   Transcript die Fehler nach Hook gruppiert und nach Text dedupliziert;
   nachgewiesen am realen Transcript vom 2026-08-03 mit seinen 164 Fehlern.
4. **Kein Hook taeuscht mehr Erfolg vor.** Jeder Hook, der seinen Fehlschlag
   verschluckt, wird benannt und entweder korrigiert oder mit Begruendung
   dokumentiert. Ein `|| true` ohne Begruendung ist ein Fehler.
5. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1–5 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- **Realitaetsnachweis:** der Preflight ist einmal gegen eine echte,
  unvollstaendige Umgebung gelaufen — nicht nur gegen eine simulierte.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Beruehrungspunkte

- **AG3-189** traegt die venv-Durchsetzung und den Interpreterbegriff. Die dort
  offene Frage „legt AK3 die venv selbst an oder verlangt es eine vorhandene"
  ist mit dem Schnitt ebenfalls dorthin gewandert — sie gehoert zur Art der
  Umgebung, nicht zu ihrer Vollstaendigkeit.
- **AG3-209** teilt AK3 in zwei Distributionen. Danach ist „die deklarierten
  Abhaengigkeiten" nicht mehr eine Liste, sondern zwei. Der Preflight aus AC 1
  muss deshalb gegen die Deklaration des **jeweils installierten Artefakts**
  pruefen, nicht gegen eine Gesamtliste. Keine Abhaengigkeitskante: wer zuerst
  landet, zieht den anderen nach.

## Guardrail-Referenzen

- `CLAUDE.md` „FEHLENDES BESCHAFFEN STATT UMGEHEN" — eine fehlende
  Abhaengigkeit wird entscheidungsreif gemeldet, nicht umgangen.
- `CLAUDE.md` „FAIL-CLOSED" — eine unvollstaendige Umgebung ist ein Fehler,
  keine Toleranzlage.
- `CLAUDE.md` „ZERO DEBT RULE" — der fehlende Eigentuemer wird hergestellt,
  nicht dokumentiert und liegen gelassen.
