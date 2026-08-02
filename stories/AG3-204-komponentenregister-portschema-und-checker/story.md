# AG3-204 — Komponentenregister, Port-Schema und Architektur-Checker umsetzen

- **Typ:** implementation
- **Groesse:** **TBD** — leitet sich aus AG3-186 ab (bewusst ausserhalb des
  `S|M|L`-Enums aus `stories/README.md` §2.1)
- **Abhaengigkeiten:** `depends_on: ["AG3-186"]`
- **Quell-Konzept:** die in AG3-186 beschlossene Konzeptflaeche; FK-07 §7.7
  (Architektur-Checker), §7.9 (messbare Invarianten)
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-18 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`.

## Kontext

### Befund

AG3-186 grenzt Code ausdruecklich aus („Kein Code in dieser Story. Es ist
Konzeptarbeit; die Umsetzung eines Registers oder Checkers folgt als eigene
Story, wenn der Schnitt steht"). Diese Folge-Story existierte nicht — die
Umsetzung waere ohne Owner geblieben, und damit waere die Schicht genau das
geworden, wogegen sie gebaut wird: eine Aussage ohne maschinelle Wirkung.

Der Blueprint-Anlassfall beschreibt die Bauart des Scheiterns praezise: In einem
Korpus mit sauberen Bounded Contexts existierte eine zweistellige Zahl von
Komponentenbezeichnern, **deren saemtliche Nennungen in genau einer
syntaktischen Rolle standen — im Eigentuemerfeld — und keine einzige in einer
definierenden**. Drei unabhaengige Gruende hielten das offen: das Feld sah aus
wie Freitext; **wo eine Regel existierte, las sie kein Werkzeug**; wo ein Befund
notiert war, erzwang nichts seine Bearbeitung.

Diese Story schliesst den zweiten und dritten Grund.

## Scope

### In Scope

- Das Komponentenregister als maschinenlesbares Artefakt mit dem in AG3-186
  beschlossenen Schema.
- Das Port-Schema mit `id`, `visibility`, `consumers[]`, `operations[]`
  (typisierte Parameter und Rueckgabetyp) und `contract_ref`.
- Die Erweiterung des Architektur-Checkers um die neuen Invarianten.
- Die Migration des bestehenden Bestands in das Register.

### Out of Scope

- **Keine Konzeptaenderung.** Was gilt, steht nach AG3-186 fest; weicht die
  Umsetzung ab, ist das ein Fehler, keine Auslegung.
- Keine Aenderung am fachlichen Komponentenschnitt selbst.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/_meta/` (Register, Port-Schema) | neu/ersetzt | die maschinenlesbaren Artefakte |
| `concept/technical-design/_meta/module-registry.yaml` | entfernt oder ersetzt | traegt den Vertrag nicht |
| `tools/concept_compiler/architecture_conformance.py` | geaendert | neue Invarianten im Checker |
| `scripts/ci/check_architecture_conformance.py` | geaendert | Aufrufseite |
| `concept/formal-spec/architecture-conformance/entities.md` | geaendert | Registrierung neuer Entitaeten, falls AG3-186 sie dort verortet |
| `tests/` | neu | je Invariante ein Positiv- und ein Negativfall |
| `concept/_meta/decisions/2026-XX-XX-komponentenregister-umsetzung.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Das Register enthaelt den vollstaendigen Bestand**, nicht einen
   Ausschnitt. Die Vollstaendigkeitsregel aus AG3-186 (`KW-H1`: die
   Komponentenebene kann **nicht** partiell sein) ist maschinell erzwungen:
   ein Bestandteil des Repos ohne Registereintrag laesst das Gate rot werden.
2. **Das Port-Schema traegt den Praezisionsboden.** Ein *wirksamer* Port ohne
   Operationen, Parameternamen, Parametertypen und Rueckgabetyp macht das Gate
   rot. Nachgewiesen an einem konstruierten Port, der `S5` verfehlt.
3. **Bezeichnerfelder sind gepruefte Referenzkanten.** Ein Eigentuemerwert, der
   auf keine Definition zeigt, macht das Gate rot — und erzeugt **nie** implizit
   einen Eintrag. Nachgewiesen an genau dem Anlassfall: ein Bezeichner, der
   ausschliesslich in einem `owner:`-Feld vorkommt.
4. **Die Konsumart an der Kante wird ausgewertet.** Der Checker unterscheidet
   `sync` von `async` und meldet **keine** Zyklen mehr, die ueber
   `async`-Kanten laufen. Nachgewiesen an einem konstruierten Fall, der unter
   der alten Ein-Kantenart-Logik als Zyklus gemeldet worden waere.
5. **Signatur und Semantik bleiben getrennt.** Ein Registryeintrag mit einem
   prosaischen Vertragssatz in einem Freitextfeld macht das Gate rot.
6. **Der neue Checker ersetzt keinen bestehenden, sondern ergaenzt ihn an der
   in AG3-186 beschriebenen Naht.** Es entsteht **keine zweite Wahrheit** ueber
   den Repo-Schnitt. Nachgewiesen daran, dass beide Pruefungen dieselbe Quelle
   lesen.
7. **`module-registry.yaml` hat keinen Konsumenten mehr**, oder sie **ist** das
   neue Register. Ein dritter Zustand ist eine Kompatibilitaetsschicht.
8. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; Coverage haelt die 85-%-Schwelle; alle deterministischen
   Konzept-Gates gruen; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die konstruierten Rot-Faelle aus AC 2, 3, 4 und 5 sind mit Diff und
  Gate-Ausgabe im Story-Record dokumentiert und zurueckgenommen.
- Die Groesse dieser Story ist im Rahmen von AG3-186 gesetzt worden (nicht mehr
  `TBD`).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- Die in AG3-186 beschlossene Konzeptflaeche (Decision Record)
- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
  §7.7, §7.8, §7.9
- `concept/formal-spec/architecture-conformance/entities.md`
- `concept-incubator/konzeptpruefung-verfahren/workspace/C-befundbericht.md`
  C-4.1 (`KW-L0`–`KW-L3`, `KW-C2`, `KW-C4`, `KW-H1`, §5.1)

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS" — AC 7.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — AC 6.
- `CLAUDE.md` „FAIL-CLOSED" — AC 1 bis AC 5.
- `CLAUDE.md` „ZERO DEBT RULE" — AC 1: kein Teilbestand.
