# AG3-136 — Projekt-Katalog-Read-Surface erzwingen (`load_projects` off-port) + decommission-Reroute

- **Typ:** implementation
- **Größe:** S
- **depends_on:** [] (härtet gelandeten Code auf `main`)
- **Quell-Konzept:** FK-07 §7.6/§7.7.5/§7.9 (Read-Surface-Disziplin), `formal.architecture-conformance.invariants`, AG3-127 (project_management `ProjectRepository`-Port)
- **Herkunft:** entdeckt bei der AG3-128-Landung (Codex-Review + eigene Vollständigkeits-Enumeration der Read-Loader), am Code verifiziert.

## Kontext / Problem (verifiziert)

AG3-128 hat die `_global`-Read-Loader-Familie (story/telemetry/control-plane) vollständig per `read_surface_rule` gepinnt — jeder dieser 15 Read-Model-Loader ist jetzt maschinell auf seine Surface beschränkt. **Nicht** erfasst ist die **Projekt-Katalog-Read-Familie**: `load_projects` (und ggf. `load_project*`) ist ein öffentlicher Fassaden-Read-Loader, der von **keiner** `read_surface_rule` abgedeckt ist, und `boundary.state_backend_repository.importable_by` bleibt `any`.

Genau **ein** echter Off-Port-Importeur besteht (verifiziert):
- `src/agentkit/backend/installer/lifecycle/decommission.py:434` — `from agentkit.backend.state_backend.store import load_projects` (A-Code liest den Projekt-Katalog direkt von der generischen Fassade, statt über den `ProjectRepository`-Port aus AG3-127).

Das ist derselbe Durchgriff-Typ wie die Execution-Event-Lesung, die AG3-128 in decommission bereits auf den sanktionierten Composition-Root-Wrapper umgeleitet hat — nur für eine andere Read-Familie und mangels Regel unentdeckt von der Konformanz-Suite.

**Warum eigene Story (nicht in AG3-128):** eigene Regel-Familie (Projekt-Reads über `ProjectRepository`, nicht die `_global`-Familie), eigener Import-Audit nötig (composition_root, project_management und decommission sind legitime/aktuelle Nutzer — eine zu weite Sperre färbt konformen Code rot). AG3-128 blieb bewusst auf die `_global`-Familie fokussiert.

## Scope

### In Scope
1. **decommission-Reroute:** `installer/lifecycle/decommission.py` liest den Projekt-Katalog nicht mehr direkt von `state_backend.store`, sondern über die veröffentlichte Read-Kante (AG3-127 `ProjectRepository`-Port bzw. den sanktionierten Composition-Root-Wrapper, analog zur Execution-Event-Umleitung). Verhaltensgleich.
2. **Projekt-Read-Surface pinnen:** die Projekt-Katalog-Read-Loader (`load_projects`, ggf. weitere `load_project*`) maschinell auf die legitime Surface beschränken — entweder als neue `read_surface_rule` (Symbol-genau, bevorzugt, analog AG3-128) oder über den `ProjectRepository`-Port-Vertrag. Import-Audit ALLER aktuellen Importeur zuerst; die konforme Welt muss danach **0 Violations** ergeben (keine falsche Rot-Baseline).
3. **Formal-Spec + Prosa mitziehen** (falls neue Regel): deklarativer `invariants:`-Twin, `version`-Bump; FK-07-§7.9-Prosa um die Projekt-Read-Grenze ergänzen.

### Out of Scope
- Die `_global`-Read-Loader-Familie (AG3-128, erledigt).
- Umbau des `ProjectRepository`-Ports selbst (AG3-127, erledigt) — nur nutzen.

## Akzeptanzkriterien
1. `installer/lifecycle/decommission.py` importiert `load_projects` nicht mehr direkt von `state_backend.store`; der Projekt-Katalog-Read läuft über die veröffentlichte Read-Kante. Verhaltensgleichheit durch Test belegt (decommission-Audit-Trail unverändert).
2. Ein Off-Port-Import der Projekt-Katalog-Read-Loader wird maschinell fail-closed gemeldet (AC004 o. ä.; CLI non-zero Exit); der konforme CURRENT-Zustand bleibt **0 Violations**.
3. Import-Audit belegt: alle legitimen aktuellen Importeur (composition_root, project_management-Port-Adapter) bleiben zulässig; kein konformer Code wird rot.
4. Falls neue Regel: deklarativer Twin synchron, `version` gebumpt, FK-07-Prosa nachgezogen.
5. ARCH-55 (englische IDs/messages); Quality-Gates grün (pytest -n0 unit/integration/contract, Coverage ≥85, mypy×2, ruff, 4 Konzept-Gates).

## Definition of Done
- AK 1-5 erfüllt; Codex-Review PASS; Konzept-Edits (falls normativ) dem PO vorgelegt; auf `origin/main`; `status.yaml` → completed; README nachgezogen.

## Guardrail-Referenzen
- **FAIL-CLOSED / NO ERROR BYPASSING:** Off-Port-Projekt-Read maschinell verboten; Regel nicht aufweichen, um grün zu werden — Code (Reroute) fixen.
- **SINGLE SOURCE OF TRUTH:** genau eine Read-Kante für den Projekt-Katalog (`ProjectRepository`-Port).
- **FIX THE MODEL:** die Lücke entstand, weil die Projekt-Read-Familie nicht gepinnt war — Spec + Checker + Reroute gemeinsam ziehen.
