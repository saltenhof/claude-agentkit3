# AG3-019: Phase-/Substep-Visualisierung mit Mode-Label im UI-Prototyp

**Typ:** Implementation (UI-Prototyp)
**Groesse:** M
**Abhaengigkeiten:** keine harte (arbeitet mit Mock-Daten); fachliche
Vorlage ist die Mode-Profil-Tabelle aus `stories/AG3-018-fast-modus/story.md`
**Quell-Konzept:** FK-72 (Frontend-Architektur), insb. §72.13 "Prototyp
als normative Quelle fuer UI-Verhalten"; FK-22-29 (Phase-Substep-Sequenzen);
Mode-Profil aus AG3-018

---

## Kontext und Workflow-Klammer

Der versionierte UI-Prototyp unter `frontend/prototype/` ist gemaess
FK-72 §72.13 die **normative Quelle fuer UI-Verhalten**. Layout,
Funktionsumfang und UX-Verhalten werden zuerst im Prototyp
materialisiert und vom User reviewt — erst danach erfolgt der
**Konzept-Rueckfluss** in FK-72 / FK-91 / FK-39 (separate Folge-
Story, noch nicht angelegt; wird nach User-Feedback geschnitten).

Diese Story integriert die Phase- und Substep-Visualisierung sowie
das Mode-Label **ausschliesslich im Prototyp**. Backend-Erweiterung
(PhaseStateCore-Substep-Feld, API-Schema, StrEnum) ist
**explizit Out of Scope** — sie kommt nach dem Konzept-Rueckfluss.

## Was die Story liefern soll

1. **Phase-Stepper** mit allen vier Phasen: Setup, Exploration,
   Implementation, Closure. Aktuelle Phase visuell hervorgehoben;
   abgeschlossene Phasen als "completed" markiert.
2. **Sub-Stepper** unterhalb des Phase-Steppers fuer die Substeps
   der **aktiven** Phase. Substep-Sequenz pro Phase aus den
   Mermaids in FK-22, 23, 26, 27, 29 (Substep-Liste auch in
   AG3-018 §Mode-Profil hinterlegt — uebernimm dieselbe Reihenfolge).
3. **Mode-Label** prominent am Story-Header. Bei `mode === "fast"`:
   gut sichtbares "FAST"-Badge (z.B. orange/auffaellig). Bei
   `mode === "execution"` oder `mode === "exploration"`: neutrales
   "STANDARD"-Label oder kein Label — Designentscheidung im Prototyp,
   diese ist Teil der User-Vorlage.
4. **Fast-Profil-Hinweise** (optional, aber sinnvoll fuer Reviews):
   Substeps die im Fast-Profil OUT sind, ausgegraut darstellen.
   Substeps die MOD sind, mit Tooltip oder Hinweis "abgespeckt im
   Fast-Modus".
5. **Mock-Daten** decken folgende Demo-Szenarien ab:
   - Standard-Mode-Story mitten in der Implementation-Phase,
     Substep `qa_layer2_llm`
   - Fast-Mode-Story am Anfang der Implementation-Phase,
     Substep `worker_start`
   - Standard-Mode-Story in Exploration, Substep `design_review`
   - Standard-Mode-Story in Closure, Substep `branch_merge`
   - Bonus: einfacher Demo-Schalter (Buttons / Toggle), um zwischen
     diesen Mock-States hin- und herzuwechseln, damit der User die
     Visualisierung interaktiv durchklicken kann.

Die Substep-Werte und ihre Reihenfolge orientieren sich an der
Liste aus der AG3-018-Story (§"Mode-Profil"). Diese Liste ist die
fachliche Vorgabe — im Prototyp werden die Werte hardcoded oder
als TypeScript-Konstante abgelegt (kein Backend-Schema noetig).

## Workflow

1. **Iterativ vorgehen**: erst Phase-Stepper, dann Sub-Stepper, dann
   Mode-Label, dann Fast-Profil-Hinweise. Pro Schritt lokal testen
   (`npm run dev` aus `frontend/prototype/`).
2. **Vorlage**: sobald die Visualisierung steht, das Ergebnis dem
   User vorlegen — entweder per Screenshot/Loom oder ueber den
   laufenden Dev-Server. Erlaeuterung der vier Mock-Szenarien
   beilegen.
3. **Feedback einarbeiten**: User-Feedback in Folgeiterationen
   einarbeiten. Story bleibt `in_progress`, bis User explizit
   freigibt.
4. **Erst nach User-Freigabe**: `status: completed` setzen.
   Konzept-Rueckfluss kommt als **eigene Folge-Story** (vom User
   nach Freigabe geschnitten — nicht in dieser Story anlegen).

## Scope

### In Scope

- Aenderungen im UI-Prototyp unter `frontend/prototype/`:
  - Komponenten fuer Phase-Stepper, Sub-Stepper, Mode-Label
  - Mock-Daten / Demo-States in `src/data.ts` (oder analog)
  - Demo-Schalter zum Wechseln der Mock-States (klein, nur
    Prototyp-Werkzeug)
  - Styling im Stil des bestehenden Prototyps (Design-System aus
    `src/design-system.css` und `src/styles.css` weiter nutzen,
    keine neue Design-Sprache einfuehren)
- TypeScript-Konstanten fuer Phase- und Substep-Werte (Enum-aehnlich,
  abgeleitet aus AG3-018 §Mode-Profil; nur Prototyp-intern)
- Lokales `npm run dev` und `npm run build` muessen weiterhin
  fehlerfrei laufen

### Out of Scope (NICHT anfassen)

- Backend-Erweiterung: `PhaseStateCore`, `Substep`-StrEnum,
  Service-API-Response-Schema, `agentkit.backend.control_plane.api.*`
- Konzept-Rueckfluss in FK-72 / FK-91 / FK-39 — wird erst **nach**
  User-Feedback in einer Folge-Story geschnitten
- AK3-Story-Backend-Anpassung
- SSE-Live-Updates (Folge-Story)
- Neue npm-Dependencies einfuehren ohne User-Rueckfrage; Stepper
  bevorzugt mit eigenem React+CSS bauen, nicht mit Library

## Betroffene Dateien (Auswahl)

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `frontend/prototype/src/App.tsx` | Modifiziert | Story-Inspector-Bereich um Stepper + Mode-Label erweitern |
| `frontend/prototype/src/data.ts` | Modifiziert | Mock-States fuer die Demo-Szenarien |
| `frontend/prototype/src/components/PhaseStepper.tsx` (oder analog) | Neu | Phase-Stepper-Komponente |
| `frontend/prototype/src/components/SubStepper.tsx` | Neu | Sub-Stepper-Komponente |
| `frontend/prototype/src/components/ModeLabel.tsx` | Neu | Mode-Label-Komponente |
| `frontend/prototype/src/lib/phases.ts` (oder analog) | Neu | Phase- und Substep-Konstanten (TypeScript-Enums) |
| `frontend/prototype/src/styles.css` | Modifiziert | Styling fuer die neuen Komponenten |

(Komponenten-Splittung kann variieren; entscheidend ist, dass die
Prototyp-Codequalitaet konsistent zum bestehenden Stil bleibt.)

## Akzeptanzkriterien

1. Der Prototyp zeigt den Phase-Stepper mit allen vier Phasen und
   den Sub-Stepper fuer die aktive Phase.
2. Der Mode-Label-Bereich zeigt bei `mode === "fast"` ein gut
   sichtbares Label, bei Standard-Mode ein neutrales/kein Label.
3. Die vier Demo-Szenarien sind ueber einen Demo-Schalter im
   Prototyp wechselbar.
4. Im Fast-Mode werden OUT-Substeps ausgegraut, MOD-Substeps haben
   einen Tooltip/Hinweis.
5. `npm run build` aus `frontend/prototype/` laeuft ohne TypeScript-
   oder Vite-Fehler durch.
6. Der bestehende Prototyp-Inhalt bleibt funktional erhalten —
   keine Regressionen.
7. Kein Backend-Code geaendert; keine neue npm-Dependency ohne
   User-Rueckfrage hinzugefuegt.
8. Der User hat das Ergebnis explizit freigegeben.

## Definition of Done

- Komponenten implementiert und stilistisch konsistent zum
  bestehenden Prototyp
- `npm run build` gruen
- Mock-Demo-Schalter funktioniert; alle vier Szenarien sind
  visuell durchspielbar
- Vorlage an User erfolgt; Feedback eingearbeitet
- User-Freigabe vorliegt
- Aenderungen committed (`stories: AG3-019: ...`)

## Konzept-Referenzen

- FK-72 §72.13 — Prototyp als normative Quelle fuer UI-Verhalten
- FK-22, 23, 26, 27, 29 — Substep-Sequenzen pro Phase (Mermaids)
- AG3-018 §Mode-Profil — fachliche Vorgabe der Substep-Liste und
  IN/OUT/MOD-Auszeichnung pro Mode

## Guardrail-Referenzen

- **SINGLE SOURCE OF TRUTH**: Substep-Liste ist im Prototyp
  TypeScript-Konstante; sie ist im Konzept noch nicht kanonisiert
  (kommt mit Konzept-Rueckfluss-Folge-Story). Bis dahin ist die
  AG3-018-Story die fachliche Quelle.
- **ZERO DEBT**: Konzept-Rueckfluss wird **nicht in dieser Story**
  improvisiert — er ist bewusst eigene Folge-Story nach User-
  Feedback. Diese Trennung ist die Anti-Schuld-Massnahme.
- **NO ERROR BYPASSING**: Bei `npm run build`-Fehlern Root Cause
  beheben, nicht ignorieren.
