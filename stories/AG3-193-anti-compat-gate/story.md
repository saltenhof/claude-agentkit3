# AG3-193 — Anti-Compat-Gate

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-182", "AG3-191", "AG3-192"]`
- **Quell-Konzept:** FK-07 §7.7/§7.9 (Architektur-Checker, messbare
  Invarianten)
- **Herkunft:** PO-Grundregel vom 2026-08-02 (`CLAUDE.md`). Ausgezogen aus
  AG3-182 am 2026-08-02 nach unabhaengigem Codex-Review (Auflage ERROR-9).

## Kontext

### Befund

Die Regel „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS" steht seit dem
2026-08-02 in `CLAUDE.md` (Commit `7f0a69e6`). Sie wird heute von **niemandem
durchgesetzt**. Der Bestand, den AG3-182, AG3-191 und AG3-192 abtragen, ist
ueber Monate entstanden, obwohl dieselbe Haltung schon vorher galt — nur eben
nicht maschinell.

Der belegte Anlassfall zeigt, warum eine Regel ohne Gate nicht traegt: der
Compat-Alias `serve-control-plane` hielt den Legacy-Port `9080` am Leben, die
Portmigration auf `9702` erreichte den Installer nie, und **jede frische
Installation schrieb eine `control-plane.json`, die auf einen Port zeigte, auf
dem nichts lauscht.** Niemand hat den Alias verteidigt — er ist einfach
niemandem aufgefallen.

### Warum diese Story hinter dem Rueckbau haengt

Ein Gate, das auf einem Bestand scharf gestellt wird, der die Regel noch
verletzt, hat zwei Ausgaenge: es ist rot und wird abgeschaltet, oder es startet
mit einer Ausnahmeliste. Eine Ausnahmeliste zum Zeitpunkt der Einfuehrung ist
eine Kompatibilitaetsschicht fuer das Gate selbst.

## Scope

### In Scope

- Ein deterministisches Gate, das neue Kompatibilitaetskonstrukte erkennt,
  bevor sie landen — im selben Pflichtlauf wie `ruff` und `mypy`.
- Die Festlegung, was maschinell entscheidbar ist und was nicht, mit
  Begruendung.
- Fuer den nicht entscheidbaren Rest: ein benannter, nicht-maschineller
  Traeger — nicht „faellt hinten runter".

### Out of Scope

- Der Rueckbau selbst — **AG3-182**, **AG3-191**, **AG3-192**.
- Keine Verschaerfung anderer bestehender Schwellwerte.
- Keine neue Sonar-Regel-Konfiguration ueber das hinaus, was das Gate braucht.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `scripts/ci/` (neues Gate-Skript) | neu | die Pruefung selbst |
| `Jenkinsfile` | geaendert | Gate laeuft im Pflichtlauf, blockierend |
| `.githooks/pre-commit` | geaendert | lokale Durchsetzung analog zu den Konzept-Gates |
| `pyproject.toml` | geaendert | falls die Pruefung als `ruff`-Regel oder Plugin realisierbar ist |
| `tools/` bzw. `src/agentkit/` je nach Realisierungsort | neu | AST-basierte Erkennung, falls Textsuche nicht traegt |
| `concept/_meta/decisions/2026-XX-XX-anti-compat-gate.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/` | neu | Positiv- und Negativfaelle des Gates |

## Akzeptanzkriterien

1. **Ein neuer Deprecated-Alias, ein Re-Export-Shim oder ein „legacy"-Default
   faellt maschinell auf, bevor er landet.** Nachgewiesen an drei konstruierten
   Aenderungen — je eine pro Klasse —, die das Gate **rot** machen. Jede der
   drei ist danach zurueckgenommen.
2. **Das Gate ist trennscharf gegen Prosa und fremde APIs.** Eine Datei, die
   „LEGACY surface" als Bezeichnung einer **fremden** Client-API fuehrt (z. B.
   `integration_clients/vectordb/weaviate_adapter.py`), erzeugt keinen Befund.
   Nachgewiesen daran, dass das Gate auf dem Stand nach AG3-182/191/192
   **gruen ohne Ausnahmeliste** ist.
3. **Es gibt keine Ausnahmeliste zum Zeitpunkt der Einfuehrung.** Wird spaeter
   eine noetig, traegt jeder Eintrag eine fachliche Begruendung und ein Datum;
   „vorerst" ist keine.
4. **Das Gate laeuft im Pflichtlauf und ist blockierend.** Ein uebersprungener,
   abgebrochener oder nicht gefahrener Gate-Lauf ist im Ergebnis von einem
   bestandenen unterscheidbar (siehe AG3-195).
5. **Was maschinell nicht entscheidbar ist, ist benannt und hat einen
   Traeger.** Die Story sagt ausdruecklich, welche Klasse von
   Kompatibilitaetskonstrukten das Gate **nicht** faengt, warum, und was
   stattdessen traegt (Review-Pruefachse, Checkliste, Konzeptregel). Die
   Feststellung „das geht maschinell nicht" ist zu **begruenden**, nicht zu
   behaupten.
6. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`, alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die drei konstruierten Rot-Faelle aus AC 1 sind mit Diff und Gate-Ausgabe im
  Story-Record dokumentiert.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
  §7.7 (deterministischer Checker gegen den Python-Code), §7.9 (messbare
  Invarianten)
- `concept/_meta/konzept-konsistenz-governance.md` §5 — Muster fuer
  deterministische Durchsetzungswerkzeuge

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS" — dieses Gate ist
  ihre Durchsetzung.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 3 und AC 4.
- `AGENTS.md` „Pflicht-Gates vor 'fertig'" — das Gate reiht sich dort ein.
