# AG3-182 — Flow-/Node-Vokabularmigration in einem Zug

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-193
- **Quell-Konzept:** FK-01 (Workflow-DSL), FK-07 §7.8 (Modulgrenzen)
- **Herkunft:** PO-Grundregel vom 2026-08-02 (`CLAUDE.md`, „KEINE
  KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS"). Restbestand nach Commit
  `01a27de1`. Neu geschnitten am 2026-08-02 nach unabhaengigem Codex-Review
  (Auflage ERROR-9).

## Kontext

### Warum die Regel richtig ist — der teuerste Beleg

Es gibt kein produktives Projekt mit AK3. Jede Kompatibilitaetsschicht schuetzt
damit niemanden und erzeugt einen zweiten Pfad, den ab sofort jeder mitliest,
mitpflegt und mitprueft.

Der Compat-Alias `serve-control-plane` hielt den Legacy-Port `9080` am Leben.
Die Portmigration auf `9702` erreichte den Installer nie — **jede frische
Installation schrieb eine `control-plane.json`, die auf einen Port zeigte, auf
dem nichts lauscht.** Die Schicht hat nichts geschuetzt und genau den Fehler
erzeugt, gegen den sie angeblich half.

### Befund — belegt, mit Locator

Am 2026-08-02 wurde ein grosser Teil des Bestands entfernt (Commit `01a27de1`):
drei CLI-Verben, mehrere Compat-Module, `GuardResult.PASS/.FAIL` samt zwei
`NOSONAR`, fuenf `read_*_record`-Wrapper, tote Nahtstellen, zwei Doppel-Reads.

**Stehen geblieben ist das Flow-/Node-Vokabular**, weil es nicht mechanisch
entfernbar war. `src/agentkit/backend/process/language/model.py` fuehrt heute
`NodeDefinition` (`:136`) und `FlowDefinition` (`:176`) als kanonische Formen —
und daneben laufen die phasen-spezifischen Altformen weiter:

| Ort | Was |
|---|---|
| `backend/process/language/__init__.py:33,38,39` | `PhaseDefinition`, `TransitionRule`, `WorkflowDefinition` als exportierte Namen |
| `backend/process/language/model.py:141` | Docstring benennt „legacy phase-specific fields used by the engine today" |
| `backend/process/language/model.py:217` | `FlowDefinition.get_phase(name)` |
| `backend/process/language/model.py:240` | `FlowDefinition.phase_names` |
| `backend/process/language/builder.py:20-24,340,378-424,473-474` | Builder produziert `WorkflowDefinition`, `PhaseDefinition`, `TransitionRule` |

**Gemessener Umfang** (Kommando:
`grep -rn "PhaseDefinition\|TransitionRule\|WorkflowDefinition\|\.phases\b\|get_phase(\|phase_names" src tests --include=*.py`):
**327 Stellen in 38 Dateien**, davon 48 Stellen des Zugriffsvokabulars
(`.phases`, `get_phase(`, `phase_names`) in `src/agentkit`.

**Warum der Umbau nicht trivial ist** — und warum das trotzdem kein Grund ist,
den zweiten Namen zu behalten:

- `FlowDefinition.name` kollidiert mit dem kanonischen `NodeDefinition.name`.
- `.phases` und `get_phase(` existieren gleichlautend auf **anderen** Objekten;
  eine reine Textersetzung trifft die falschen Stellen.

## Scope

### In Scope

- Die vollstaendige Migration des Flow-/Node-Vokabulars in **einem** Zug:
  Typen, Attribute, Methoden, Builder, alle Aufrufstellen in `src/` und
  `tests/`.
- Die Aufloesung der beiden Namenskollisionen **vor** der Umbenennung.
- Der Konzeptnachzug ueberall, wo ein entfernter Name normativ erwaehnt war.

### Out of Scope

- **Keine Umbenennung aus Geschmacksgruenden.** Diese Story entfernt
  Kompatibilitaets**schichten** — Konstrukte, die einen zweiten Weg zum selben
  Ziel offenhalten. Ein schlecht gewaehlter, aber **einziger** Name ist kein
  Fall fuer diese Story.
- Die QA-/Policy-Fallbacks im `verify_system` — **AG3-191**.
- Die restlichen produktiven Aliase und Compat-Pfade — **AG3-192**.
- Das Gate gegen den Rueckfall — **AG3-193**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/backend/process/language/model.py` | geaendert | kanonische Form bleibt, Altform verschwindet; `get_phase`, `phase_names`, `.phases` |
| `src/agentkit/backend/process/language/__init__.py` | geaendert | Altnamen aus dem Export entfernen — kein Re-Export-Shim |
| `src/agentkit/backend/process/language/builder.py` | geaendert | Builder produziert nur noch die kanonischen Typen |
| `src/agentkit/backend/**` (die uebrigen der 38 Dateien) | geaendert | Aufrufstellen wandern mit |
| `tests/**` | geaendert | Tests folgen dem kanonischen Namen; keine Doppelpflege |
| `concept/technical-design/01_*.md` bzw. die FK-Dokumente, die die Altnamen normativ fuehren | geaendert | Konzeptnachzug |
| `concept/_meta/decisions/2026-XX-XX-flow-node-vokabular.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Der Umbau laeuft als EIN Zug.** Kanonischer Name bleibt, alter
   verschwindet, alle Aufrufstellen wandern mit. **Es gibt keinen Commit und
   keinen Zwischenstand, in dem beide Namen gleichzeitig aufloesbar sind** —
   auch nicht innerhalb eines Branches, auch nicht „nur fuer Tests".
2. **Die Namenskollisionen sind vor der Umbenennung aufgeloest** und die
   Aufloesung ist im Code begruendet: `FlowDefinition.name` gegen
   `NodeDefinition.name`, sowie die gleichlautenden `.phases` / `get_phase(`
   auf anderen Objekten. Der Nachweis benennt fuer jede der 48
   Zugriffsvokabular-Stellen in `src/agentkit`, auf welchem Objekt sie sitzt.
3. **Nach dem Umbau loest keiner der Altnamen mehr auf.** Nachgewiesen durch
   einen Test, der den Import von `PhaseDefinition`, `TransitionRule` und
   `WorkflowDefinition` versucht und **erwartet, dass er scheitert** — nicht
   durch eine Textsuche.
4. **Kein `NOSONAR`, kein Rule-Exclude, kein unerklaertes `noqa` oder
   `type: ignore` bleibt zurueck**, das die Migration verdeckt. Am 2026-08-02
   fanden sich zwei `NOSONAR`, die genau das taten.
5. **Konzeptnachzug vollstaendig:** jede normative Erwaehnung eines entfernten
   Namens ist nachgezogen. Nachgewiesen ueber einen Lauf von
   `check_concept_reference_integrity.py` und eine Volltextsuche ueber
   `concept/`, deren verbleibende Treffer namentlich ausgewiesen sind.
6. **Volle Suite gruen**, `ruff` clean, `mypy --strict` gruen fuer `win32`,
   `linux` und `darwin`, alle deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- `.venv\Scripts\python -m pytest` gruen; Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`
  §7.8 (Importgrenzen), §7.9 (messbare Invarianten)
- Die FK-Dokumente, die das Workflow-Vokabular normativ fuehren — der Umsetzer
  ermittelt sie ueber `concept_search` und weist die Liste im Story-Record aus.

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS" — der Schnitt wird
  an **einer** Stelle gemacht, nicht an zweien nacheinander.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 4.
- `CLAUDE.md` „STRUKTURREGELN DES REPOS SIND VERBINDLICH" — keine zirkulaeren
  Abhaengigkeiten durch die Aufloesung der Namenskollisionen.
