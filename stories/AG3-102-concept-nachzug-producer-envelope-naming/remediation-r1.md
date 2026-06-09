# AG3-102 — Remediation R1 (Antwort auf review-r1.md)

Doc-only/Concept-Alignment-Story. Alle Befunde aus `review-r1.md` adressiert durch Angleichung der **Story-Prosa** an die Code-Realitaet bzw. an die autoritative BC-Cut/PROJECT_STRUCTURE-Soll-Wahrheit. Es wurden ausschliesslich `stories/AG3-102-*`-Dateien geaendert (`story.md`; `status.yaml` unveraendert — kein Feld war fachlich falsch).

Belege gesichtet: `producer.py:19-30`, `envelope.py:90/128-152`, `qa_artifact_names.py:79-91`, `producer_registry.py:65`, `postgres_schema.sql` (Tabellennamen), FK-71 §71.2 (`71_…:122-174`), FK-18 (alle Vorkommen, `18_…:92-763`), FK-42 (`42_…:95/372-374`), FK-56 (§56.9), FK-76 §76.3 (`76_…:151-155`), FK-92 §92.1.1 (`92_…:37`), `bc-cut-decisions.md` (BC 3 Z.263, BC 4 Z.313), `PROJECT_STRUCTURE.md:120/127/131`, `AG3-097/story.md:17,:56`.

---

## Finding → Resolution

### Must-Fix 1 — „keine concept/-Aenderung" widerspricht Story-Typ (Befunde 2 + 3, ERROR/WARNING)
**Befund:** Header sagte „keine `concept/`-Aenderung", obwohl Typ `concept/doc-only`, Scope „nur FK-Prosa" und DoD „Konzept-Prosa-Aenderung" sind.
**Resolution:** Header-Scope-Satz ersetzt durch „Doc-only-Scope: ausschliesslich FK-/Konzept-Prosa. Keine `src/`-/`tests/`-/Schema-Code-Aenderung." Explizit klargestellt, dass diese Story IST eine `concept/`-Prosa-Aenderung und nur Code/Test/Schema verboten ist. AC7 + Hinweise konsistent nachgezogen. (story.md Header, §6, AC7)

### Must-Fix 2 — FK-18-Scope zu eng (Befund 1, ERROR)
**Befund:** Scope/AC nur §18.4/§18.6a; stale Namen kommen aber in §18.3.x, §18.5.x, §18.13-18.16 u. a. vor -> FK-18 bliebe intern widerspruechlich. `phase_state_projection` muss ueber alle Vorkommen bereinigt werden.
**Resolution:** Scope (In-Scope 4) und AC2 auf **alle** Vorkommen ueber das gesamte FK-18-Dokument erweitert; §1 listet die belegten Sektionen mit `file:line` (§18.3.x bis §18.16). AC2 fordert ausdruecklich „FK-18 ist nach dem Nachzug intern widerspruchsfrei". `phase_state_projection -> phase_states`/`phase_snapshots` in den Scope aufgenommen, mit Hinweis wann welcher Name gemeint ist. (story.md §1 Tabellennamen-Absatz, §2.1.4, AC2)

### Must-Fix 3 — FK-42 falsch als „Code autoritativ" (Befund 4, ERROR)
**Befund:** Story erklaerte `governance/ccag/` als code-autoritativ und wollte FK-42/PROJECT_STRUCTURE von `ccag_permission_runtime` auf `ccag` zurueckziehen. Widerspricht `bc-cut-decisions.md` BC 4 (Z.313) und `PROJECT_STRUCTURE.md:127`, die `ccag_permission_runtime` als Soll fuehren.
**Resolution:** Authority umgekehrt: BC-Cut/PROJECT_STRUCTURE bleiben autoritativ; `ccag_permission_runtime/` bleibt Soll-Namespace; FK-42 wird NICHT auf `ccag/` zurueckgezogen. Die Code-Verzeichnis-Divergenz `governance/ccag/` ist als **Code-Folgeauftrag** in Out-of-Scope verschoben (governance-BC; FK-42 vermerkt selbst „CCAG-Implementierung steht aus", `42_…:372-374`). AC4 fordert explizit „FK-42 NICHT als Code autoritativ". (story.md §1 FK-42-Punkt, §2.1.7, §2.2, AC4)

### Must-Fix 4 — FK-56 nicht sauber gespiegelt (Befund 4, ERROR)
**Befund:** AG3-097 hat den Code-Namespace `operating_mode_resolver` bereits als Scope/AC; AG3-102 liess offen, ob FK den heutigen Code-Ort uebernimmt.
**Resolution:** „Owner-Frage offen" entfernt. Soll-Namespace `operating_mode_resolver/` bleibt autoritativ (BC-Cut BC 3 Z.263, `PROJECT_STRUCTURE.md:120`); Code-Fix eindeutig an **AG3-097** gespiegelt (verifiziert: `AG3-097/story.md:17,:56` fuehrt den Namespace als Scope/AC). FK-56 wird NICHT auf `guard_evaluation.py`/`projectedge/runtime.py` zurueckgezogen. (story.md §1 FK-56-Punkt, §2.1.8, §2.2, AC4)

### Must-Fix 5 — AC6 zu unkonkret (Befund 2, ERROR)
**Befund:** AC6 nannte die Pflicht-Gate-Commands nicht explizit.
**Resolution:** Zu AC7 geschaerft mit den konkreten Commands: `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py` und vor „fertig" `scripts/ci/check_remote_gates.ps1` (alle drei Skript-Pfade als existent verifiziert) plus expliziter leerer `src/`/`tests/`/Schema-Diff. (story.md AC7)

### Befund 2 (Teil) — AC3 nannte FK-56 nur in Klammer (ERROR)
**Resolution:** FK-56 ist jetzt eigener Satzgegenstand in §2.1.8 und in AC4 (zusammen mit FK-42), nicht nur als Klammerzusatz.

### Befund 3 (WARNING) — FK-76/FK-56 gemeinsam als „optional/kosmetisch"
**Befund:** „optional/kosmetisch" gilt fuer FK-76 (§76.3-Hinweis), aber NICHT fuer FK-56 — `bc-cut-decisions.md` fuehrt `operating_mode_resolver` autoritativ.
**Resolution:** FK-76 und FK-56 sauber getrennt: FK-76 bleibt aspirational/kosmetisch (FK markiert das selbst, `76_…:151-155`); FK-56 ist ein verbindlicher Code-Folgeauftrag an AG3-097, nicht „optional". (story.md §1 FK-56 vs. FK-76, §2.1.6 vs. §2.1.8)

### Anchor-Korrekturen (FIX WRONG ANCHORS)
- **Producer-Namen-Quelle:** R1/alte Story verorteten die illustrativen Producer-Namen bei FK-71 §71.2. Der Code-Kommentar (`qa_artifact_names.py:79-85`) attribuiert die illustrative Quelle korrekt FK-**35** §35.2.4 und die kanonische Liste FK-27 §27.7. Anker auf `qa_artifact_names.py:86-91` praezisiert (Konstanten stehen ab Z.86, nicht 79) und Quell-Attribution korrigiert. FK-71 fuehrt zusaetzlich eine eigene illustrative Producer-Tabelle (`71_…:166-174`) — ebenfalls referenziert.
- **FK-71 Wire-Werte:** Anker auf konkrete Zeilen `71_…:122` (Beispiel `type`), `:141` (Pflichtfeld-Tabelle), `:125-126`/`:143-144` (Timestamps mit `+01:00`-Nicht-UTC-Offset) gesetzt.
- **`producer: Producer` Enforcement:** `envelope.py:90` (Feld-Deklaration) statt unspezifischem Verweis.
- **FK-18:** Vorkommen mit Sektions- und Zeilenbelegen versehen (§1).
- **bc-cut-decisions.md / PROJECT_STRUCTURE.md:** Soll-Namespaces mit Zeilennummern verankert (BC 3 Z.263, BC 4 Z.313; PROJECT_STRUCTURE Z.120/127/131).

### ARCH-55
Geprueft: keine deutschen Code-Identifier/Keys in der Prosa eingefuehrt; alle technischen Bezeichner (Enum-Werte, Tabellennamen, Namespaces, Producer-Ids) englisch. (AC6)

### AG3-057-Template
Struktur erhalten: Header (Typ/Groesse/BC/Quell-Konzepte) + §1 Kontext/Ist-Zustand + §2 Scope (In/Out mit Owner) + §3 Akzeptanzkriterien + §4 DoD + §5 Guardrail-Referenzen + §6 Hinweise fuer den Sub-Agent.

---

## Genuine Cross-Story-Voraussetzungen (Code-Folgeauftraege — nicht in AG3-102 lieferbar)

Diese Punkte sind echte Code-Abhaengigkeiten ausserhalb dieser doc-only-Story. AG3-102 behauptet NICHT, eine andere Story liefere etwas ausserhalb ihres Scopes — die Zuordnungen sind gegen die jeweiligen Story-Scopes geprueft:

1. **FK-56 / `operating_mode_resolver`-Code-Umzug -> AG3-097.** Verifiziert: `AG3-097/story.md:17,:56` fuehrt den `operating_mode_resolver`-Namespace bereits als eigenen Scope/AC. Belastbar gespiegelt.
2. **FK-42 / `governance/ccag/` -> `governance/ccag_permission_runtime/`-Code-Umzug.** Owner: governance-BC-Code-Story zur (laut FK-42 noch ausstehenden) CCAG-Implementierung. **Kein** bestehender Story-Scope verifiziert, der genau diesen Verzeichnis-Umzug bereits traegt — daher als **offener Code-Folgeauftrag** gemeldet (PO/Backlog), nicht einer Story zugeschrieben, deren Scope das nicht deckt.
3. **FK-76 / `harness_adapters/` -> `harness_integration/`-Code-Umzug.** Von FK-76 selbst als kosmetisch/optional markiert. Owner: optionale harness-/installation-BC-Folge-Story; **kein** existierender Scope verifiziert — als optionaler offener Folgeauftrag gemeldet.
4. **Fehlende Tabellen** (Code, nicht doc-only, nur referenziert): `guard_decisions` + `story_custom_field_*` -> AG3-087; `kpi_projections`/Read-Models -> AG3-081/AG3-083.
5. **Producer-Seed-Registry / FK-42 TTL->ESCALATED / FK-56 binding_invalid** — Code, Owner AG3-061/064 bzw. AG3-086 bzw. AG3-097 (nur referenziert).

Hinweis: Punkte 2 und 3 sind als **offene PO-/Backlog-Folgeauftraege** formuliert statt einer konkreten Story zugeschrieben, weil kein bestehender Story-Scope verifiziert werden konnte, der genau diesen Code-Verzeichnis-Umzug traegt. Damit wird Must-Fix 3/4 erfuellt (kein offener Owner-Konflikt) ohne einer Story etwas ausserhalb ihres Scopes anzudichten.
