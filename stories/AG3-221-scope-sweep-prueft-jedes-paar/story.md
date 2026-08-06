# AG3-221 — Der Sweep prüft jedes Paar, oder er sagt, dass er es nicht tut

- **Typ:** implementation
- **Groesse:** L
- **Status:** `blocked` — PO-Entscheidung ueber die Kosten steht aus
- **Abhaengigkeiten:** `depends_on: [AG3-219]`
- **Herkunft:** unabhaengige Reviewrunde zu AG3-219 R4, 2026-08-05

## Befund — belegt, mit Locator

`tools/concept_governance/scope_sets.py:58-60` zerlegt ein geschlossenes
Scope-Set in **disjunkte** Partitionen; `scope_execution.py:45-48` bewertet
jede Partition **isoliert**. Chunks aus verschiedenen Partitionen erscheinen
damit **nie gemeinsam** in einem Prompt.

Folge: Ein Widerspruch zwischen zwei Aussagen, die in unterschiedliche
Partitionen fallen — etwa `lock-0` und `lock-2` — ist fuer den Sweep
**unsichtbar**. Vor AG3-219 meldete der Lauf sich trotzdem als vollstaendig.

`tests/unit/tools/concept_governance/test_scope_runner.py:41-56` schrieb dieses
Verhalten fest: drei Chunks je Scope auf zwei Partitionen, Erwartung
`result.ok`. Ein Test, der den Defekt als Zusage festhaelt — dieselbe Klasse
Problem, die AG3-214 an drei Stellen hatte.

### Was AG3-219 bereits erledigt hat

Die Sofortpflicht — **kein PASS fuer einen Lauf, der nicht alles gesehen hat**
— ist umgesetzt: Zerfaellt ein Scope-Set in mehr als eine Partition, meldet der
Sweep `INCOMPLETE_SWEEP` mit Scope und Partitionszahl. Die Luecke ist damit
**sichtbar und benannt**, nicht geschlossen.

Diese Story schliesst sie.

### Wodurch der Defekt groesser wurde

AG3-219 hat die Partitionsgrenze von 48.000 auf 30.000 Zeichen gesenkt und
damit die Zahl der Partitionen erhoeht. Das war **notwendig und richtig**: Der
neue `authority-prose/v2`-Prompt ist laenger, und 30.000 ist der gemessene
Wert, bei dem der reale Korpus gerade passt (Maximum 29.982, `oversized=0` bei
251 Scope-Sets und 975 Partitionen). Die Grenze steht nicht zur Debatte; die
Partitionierungsstrategie tut es.

## Die Entscheidung, die der PO treffen muss

Vollstaendige Abdeckung heisst: **jedes Chunk-Paar eines Scope-Sets steht
einmal gemeinsam in einem Prompt.** Das erfordert ueberlappende, paar-deckende
Partitionen statt disjunkter.

Die Kosten sind real: Jede Bewertung ist ein LLM-Aufruf ueber den
Multi-LLM-Hub, und deren Zahl waechst deutlich ueber die heutige lineare
Partitionierung hinaus. Der Hub hat zwoelf Slots ueber fuenf browsergetriebene
Backends; Durchsatz ist die knappe Ressource, nicht Rechenzeit.

Zwei Wege, beide vertretbar:

- **A — Vollstaendigkeit.** Paar-deckende Partitionen bauen. Passt ein
  einzelnes Chunk-**Paar** nicht unter die 30.000 Zeichen, endet der Sweep
  fail-closed statt es zu ueberspringen. Teuer, aber die Zusage
  „Scope-Set-Konsistenz" stimmt danach.
- **B — Ehrlichkeit als Endzustand.** AK3 lebt bewusst mit
  **Partitionskonsistenz** und sagt das **ueberall**, wo es heute
  Scope-Set-Konsistenz zusagt: FK-78, der Decision Record, die Gate-Ausgabe.
  Billig, und die Zusage stimmt danach ebenfalls — sie ist nur kleiner.

**Was nicht geht, ist der heutige Zwischenzustand ohne Entscheidung:** eine
grosse Zusage, eine kleine Pruefung, und ein `INCOMPLETE_SWEEP`, das auf Dauer
zur Tapete wird. `CLAUDE.md` §SEVERITY-SEMANTIK ist an dieser Stelle deutlich:
Ein Befund, fuer den niemand spaeter Zeit bekommt, ist im Effekt ein
ignorierter Befund.

## Scope

### In Scope — bei Entscheidung A

- Paar-deckende Partitionierung: jedes Chunk-Paar eines Scope-Sets wird
  mindestens einmal gemeinsam bewertet.
- Fail-closed, wenn ein einzelnes Paar die Zeichengrenze sprengt.
- Messung des tatsaechlichen Mehraufwands am realen Korpus (Zahl der
  Bewertungen vorher/nachher, Laufzeit) — **vor** dem Vollausbau, als
  Entscheidungsgrundlage.

### In Scope — bei Entscheidung B

- FK-78, der Decision Record und die Gate-Ausgabe sagen **Partitionskonsistenz**
  statt Scope-Set-Konsistenz.
- `INCOMPLETE_SWEEP` entfaellt als Dauerzustand, weil der Sweep dann
  vollstaendig ist — gemessen an dem, was er zusagt.

### Out of Scope

- Die 30.000-Zeichen-Grenze. Sie ist gemessen.
- Der Evidenzvertrag (`authority-prose/v2`, Spannen statt Zitate) — AG3-219.

## Akzeptanzkriterien

Werden nach der PO-Entscheidung ausformuliert. Unabhaengig von ihr gilt:

1. **Die Zusage und die Pruefung stimmen ueberein.** Nachgewiesen dadurch, dass
   die normative Formulierung und das tatsaechliche Sweep-Verhalten Wort fuer
   Wort dasselbe sagen.
2. **Ein Test beweist den Cross-Partition-Fall** — entweder dass er gefunden
   wird (A) oder dass er ausdruecklich ausserhalb der Zusage liegt (B).
3. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; volle Suite
   gruen auf Jenkins.

## Definition of Done

- AC erfuellt, jedes mit benanntem Beleg.
- **Realitaetsnachweis** gegen den echten Multi-LLM-Hub, nicht nur Unit-Tests
  (`CLAUDE.md` §REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §SEVERITY-SEMANTIK — ein Befund ohne Zeit ist ein ignorierter
  Befund
- `CLAUDE.md` §ZERO DEBT RULE — „Schuld, die wie ein Entwurf aussieht, kostet
  mehr als Schuld, die wie ein Fehler aussieht"
- `CLAUDE.md` §FAIL-CLOSED
