# Worker-Review-Rubric — das Maß, an dem deine Story gemessen wird

> **An den Worker:** Lies die **Story und ihre Akzeptanzkriterien selbst** — sie werden hier
> NICHT wiederholt. Diese Datei ist das **Prüf-Raster**, mit dem ein giftiger, adversarialer
> Codex-Review dein Ergebnis hinterher systematisch zerlegt. Geh die Kategorien **selbst durch,
> bevor du „fertig" sagst** — versuche, deine eigene Arbeit gegen jede Kategorie zu brechen.
> Wenn du auch nur funkenweise gegen eine Kategorie verstößt und schlampst, kommt das als
> **unendliche Remediation-Runden** zurück (und kostet dich, nicht mich). Du bist erwachsen:
> mach beim ersten Mal einen sauberen, vollständigen Job statt einer Minimalantwort auf den
> Story-Text.

Die Konzept- und Guardrail-Basis (`CLAUDE.md`, `concept/`, `guardrails/`) gilt zusätzlich und
hat Vorrang — diese Rubric ist die *Review-Brille*, nicht ihr Ersatz.

## Die Kategorien (so geht der Review vor)

1. **Fail-closed-Vollständigkeit** — Jeder fehlende, ungültige, leere oder Fehler-Zustand bricht
   **hart** ab. Kein Fail-open, kein stiller Skip, kein „Default-auf-erlaubt", kein
   Warning-statt-Error für etwas, das niemand später anfasst. Frage dich: *Wo könnte mein Code
   bei schlechtem/fehlendem Input trotzdem erfolgreich durchlaufen?* — das ist ein Befund.

2. **Single Source of Truth** — Eine Wahrheit / ein Prädikat / ein Owner pro Regel. Keine zweite,
   abweichende oder duplizierte Logik (auch nicht in Docstrings/Prompttext/Tests). Wenn dieselbe
   Regel an zwei Stellen kodiert ist, driften sie.

3. **Durchsetzung an der Grenze, nicht beim bequemen Aufrufer** — Invarianten am **Port / Modell /
   Eintrittspunkt** erzwingen, sodass **kein** Pfad sie umgehen kann (CLI, direkter Konstruktor,
   API, interner Aufruf). Validierung nur im CLI/Parser ist ein Loch, wenn ein direkter Aufruf
   daran vorbeikommt.

4. **Blast-Radius / alle Aufrufer** — Bei jeder Verhaltensänderung den **gesamten** Baum nach
   Konsumenten/Aufrufern greppen (Produktiv **und** Tests) und alle anpassen. Nichts darf still
   auf alten Annahmen weiterlaufen. „Meine gezielten Tests sind grün" ≠ „die Suite ist grün".

5. **Konzepttreue** — Die in der Story zitierten `FK`/`DK`/`formal-spec`-Abschnitte **selbst
   lesen** (nutze den `agentkit3-concepts`-MCP). Reihenfolge, Ownership, Status-Achsen und
   Semantik müssen **exakt** passen. Bei Konzept-Konflikt/-Drift: **stoppen und melden**, nicht
   raten oder eine zweite Annahme einbauen.

6. **Adversariale Inputs** — Gegen `leer`, `whitespace-only`, Control-Chars/`\n`, Unicode/Non-ASCII,
   Path-Traversal (`..`/`.`), Slashes, überlange Werte, Duplikate, Grenzwerte (min/max) prüfen.
   Regex: `fullmatch`/`\A…\Z` statt `^…$`+`match` (Python `$` toleriert finales `\n`), anchored,
   **ReDoS-frei** (keine verschachtelten Quantifier). Determinismus: gleicher Input → gleicher
   Output (keine Zeit-/Reihenfolge-/Dict-Order-Quelle).

7. **Negativtests am Gate + echte Pfade** — Jedes fail-closed-Gate hat einen **reproduzierenden
   Negativtest** (verweigert bei schlechtem Input). Tests beweisen den **echten** Pfad — keine
   vorab injizierten Zustände/Felder, die genau den Produktivpfad umgehen; keine Tautologien;
   keine gegen-ein-Test-Duplikat-gepinnten Contracts (gegen die SSOT-Quelle pinnen). Gültige
   Grenzwerte werden **akzeptiert** (kein Over-Reject).

8. **Scope-Disziplin** — Exakt der Story-Scope. Out-of-Scope bleibt OOS **mit benanntem Owner**.
   Kein Scope-Creep, kein God-Composition (keine Ownership aus fremden BCs in einen zentralen
   Bauplan ziehen). Aber: notwendige *Konsequenzen* der eigenen Änderung (z. B. ein Aufrufer, der
   durch dein neues fail-closed bricht) gehören mit gefixt — das ist nicht OOS.

9. **Keine Attrappen für Kernlogik** — Echte Komponenten, echte Artefakte, echte Integrationspfade.
   Stubs/Mocks NUR an echten externen Grenzen (Git/Netz/Sonar/Worker-Spawn) und nur, wenn ein
   isolierter Unit-Test sonst technisch unmöglich ist. Kein no-op-Default-Sink, der in Produktion
   nie etwas tut und als „erledigt" verkauft wird.
   **Gebaut ≠ verdrahtet (wiederkehrende Falle, AG3-041 + AG3-043):** Eine neue Fähigkeit muss am
   **Composition-Root** (`build_*` / DI) **produktiv verdrahtet** sein — kein `None`-/Stub-Default,
   der in Produktion auf den alten Passthrough/Reviewer/Stub zurückfällt. Verifiziere am echten
   Produktiv-Eintrittspunkt (nicht nur im Test): läuft meine neue Logik im Default-Pfad wirklich,
   oder ist sie gebaut und nie aktiv? Letzteres ist ein ERROR.

10. **Pflicht-Gates wirklich grün — inkl. Sonar antizipieren** — Vor „fertig":
    `pytest` (volle Suite + Coverage ≥85% — nicht nur gezielt), `mypy src` **und**
    `mypy src --platform linux`, `ruff check src tests`, der LOC-Linter (0 issues), die 4
    Konzept-Gates. **Und** den Sonar-Quality-Gate *vorwegnehmen*: typische new_violations selbst
    vermeiden — `S3776` Cognitive Complexity ≤15 (Funktionen klein/in Helper schneiden),
    `S1110` redundante Klammern, `S7632` Suppression-Kommentar-Syntax (sauberes `# noqa: <CODE>`,
    Begründung als eigene Zeile), `S5713` redundante Exception-Klasse (Subklasse, die von einer
    bereits gefangenen Basis abgeleitet ist), `S5886`/`S5890` (dataclasses.replace/typing).
    Hooks/Suppressions ohne unerklärten `noqa`/`type: ignore`.

---

### Wartung dieser Rubric (Orchestrator, nicht Worker)

Lebendes Dokument. Nach jeder giftigen Review: für jeden Befund prüfen, ob seine **Kategorie**
hier strukturell verankert war.
- **Nicht verankert** → der Worker hatte keine Chance → Kategorie hier ergänzen/schärfen.
- **Verankert** → der Befund ist Sorgfaltsmangel des Workers, **kein** Rubric-Loch.

So konvergiert die Rubric; verbleibende Findings sind sauber als Schlampigkeit (nicht als
fehlende Anweisung) zuordenbar.
