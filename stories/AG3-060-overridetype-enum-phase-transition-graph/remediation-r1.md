# AG3-060 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` only. No production code, tests, or concept
files touched; `status.yaml` left unchanged (no field is genuinely wrong — see
below). Every code anchor below was re-verified against the real tree at
remediation time and corrected to `file:line`.

## Must-Fix ERRORs

### MF1 — Transition-Owner unscharf/falsch geschnitten (review §Konzept-Vollstaendigkeit ERROR, §Must-Fix 1)
**Finding:** Story forderte `PHASE_TRANSITION_GRAPH` als „Single source im
Phase-Runner/`pipeline_engine`" (frueher `story.md:29`), aber der reale
FK-45-Eintrittspfad sitzt in `control_plane/dispatch._enforce_transition`
(`src/agentkit/control_plane/dispatch.py:393`) und nutzt story-typ-spezifische
Kanten/Guards der `WorkflowDefinition` (`dispatch.py:417`; Kanten in
`process/language/definitions.py:93-96/116-117/134-135/151-152`). Ein statischer
zweiter Graph, der `setup -> exploration` global erlaubt, waere eine zweite
operative Wahrheit.
**Resolution:** Owner explizit gesetzt. Der §-Quell-Konzept-Block, §1
(Ist-Zustand + neue Kontext-Sinnhaftigkeit-Bullets), §2.1 Punkt 3+5 und die
Hinweise deklarieren jetzt: die story-typ-spezifische `WorkflowDefinition`
(konsumiert von `_enforce_transition`) bleibt die operative Transition-Wahrheit;
`PHASE_TRANSITION_GRAPH` + `is_valid_phase_transition` sind ein benannter
**Phasen-Superset-Vorfilter** ueber `PhaseName`, der als Erst-Gate VOR der
workflow-spezifischen Pruefung laeuft — bevorzugt aus
`WorkflowDefinition.get_transitions_from(...)` ABGELEITET (eine Pflegequelle),
sonst statisch MIT Konsistenztest. Er kann nur frueher ablehnen, nie zusaetzlich
erlauben. Verdrahtung explizit in `control_plane/dispatch`, nicht im
`pipeline_engine`. (Resolved in-story.)

### MF2 — ESCALATED-vs-`rejected`-Contract entscheiden (review §Konzept-Vollstaendigkeit ERROR, §Must-Fix 2)
**Finding:** Story verlangte „ungueltiger Uebergang -> ESCALATED" (frueher
`story.md:31`, `:46`) entsprechend FK-45 §45.2-Prosa; real liefert der
Pre-Engine-Dispatch `status="rejected"` ohne Engine-Eintritt
(`dispatch._rejected`, `src/agentkit/control_plane/dispatch.py:549-557`).
**Resolution:** Entscheidung getroffen und begruendet: der bestehende
Dispatch-Contract (`status="rejected"`, `dispatched=False`, kein persistierter
PhaseState/AttemptRecord; FK-45 §45.3) bleibt. ESCALATED bleibt der vom Engine
produzierte persistierte Endzustand (`engine.py:698-721`). Diese Story fuehrt
KEINEN „ESCALATED-vor-Engine"-Pfad ein (waere zweite Eskalations-Wahrheit).
`reset-escalation`-Recovery aus dem ESCALATED-Endzustand ist AG3-076 (FK-45
§45.4). Dokumentiert in §1 (Kontext-Sinnhaftigkeit-Bullet), §2.1 Punkt 5, §2.2
(neuer Out-of-Scope-Punkt), AC6+AC7, Guardrails (FAIL CLOSED) und Hinweise. Die
Tests assertieren `status="rejected"`/`dispatched=False`. (Resolved in-story;
ein evtl. woertlicher FK-45-§45.2-Prosa-Nachzug ist ein doc-/contract-Drift am
FK-45-Owner, siehe Cross-Story-Voraussetzungen.)

### MF3 — Statischen Graph gegen workflow-spezifische Kanten absichern / AC-Schaerfe (review §AC-Schaerfe FAIL ERROR, §Must-Fix 3)
**Finding:** AC 4/5 testeten nur den abstrakten Graphen, nicht die
workflow-spezifischen Guards/Edge-Ordering-Regeln. Bestehender Dispatch spiegelt
„first passing edge wins" (`dispatch._first_passing_edge`,
`src/agentkit/control_plane/dispatch.py:456-472`, `:430-453`) und darf fuer
Bugfix/Concept/Research kein `setup -> exploration` zulassen
(`definitions.py:116/134/151`).
**Resolution:** AC neu geschnitten. AC4: Superset-Matrix-Test + Konsistenztest
„Superset == Vereinigung der vier Workflow-Kanten". AC5 (neu): `setup ->
exploration` nur bei Implementation+Exploration-Mode admittiert,
Bugfix/Concept/Research fail-closed `rejected`; `_first_passing_edge`-Ordering
regressionsgetestet (erste passierende Kante gewinnt, auch wenn Ziel != angefragte
Phase). §2.1 Punkt 6 nimmt die entsprechenden Test-Pflichten auf. (Resolved
in-story.)

### MF4 — `OverrideType`-Owner eindeutig festlegen (review §AC-Schaerfe WARNING, §Must-Fix 4)
**Finding:** Owner war offen formuliert: „in `core_types` (oder `process/language`)"
(frueher `story.md:27`), Widerspruch zum SSOT-Ziel (`story.md:56`).
**Resolution:** Owner eindeutig auf `core_types` gesetzt — neues Modul
`src/agentkit/core_types/override.py`, parallel zu den bestehenden Kern-Enums
(`core_types/severity.py`, `pause_reason.py`, `exploration.py`, real per Glob
verifiziert). `process/language` und `pipeline_engine` IMPORTIEREN von dort; keine
Re-Definition. Festgehalten in §2.1 Punkt 1 + Hinweise. (Resolved in-story.)

### MF5 — Falschen `_check_preconditions`-Anchor + unvollstaendige `OverridePolicy`-Beschreibung korrigieren (review §Klarheit WARNING+NIT, §Must-Fix 5)
**Finding:** Story nannte `_check_preconditions` in `pipeline_engine/engine.py:192-303`
(frueher `story.md:18`); real existieren dort `_evaluate_transitions`
(`engine.py:192`) und `_can_enter_phase` (`engine.py:209`), kein
`_check_preconditions`. `OverridePolicy` wurde mit drei Booleans beschrieben,
real sind es sechs (`process/language/model.py:79-88`).
**Resolution:** Anchor korrigiert auf die realen Symbole `_evaluate_transitions`
(`:192`) / `_can_enter_phase` (`:209`) und den realen Pre-Engine-Pfad
`dispatch._enforce_transition` (`:393-453`) ergaenzt; explizite „Korrektur des
fruheren Ankers"-Notiz in §1. `OverridePolicy` vollstaendig als sechs Booleans
gelistet (`allow_skip`, `allow_force_pass`, `allow_force_fail`, `allow_jump`,
`allow_truncate`, `allow_freeze_retries`), Anchor auf `model.py:79-88` korrigiert.
(Resolved in-story.)

## WARNINGs
- **W1 — `OverrideType`-Owner offen:** identisch mit MF4 (Review fuehrt es als
  WARNING in §AC-Schaerfe). Resolved wie oben.
- **W2 — Ist-Zustand-Anchor falsch/irrefuehrend (`_check_preconditions`):**
  identisch mit MF5. Resolved wie oben; zusaetzlich der reale Dispatch-Pfad
  `_enforce_transition` aufgenommen.

## NIT
- **`OverridePolicy` nur drei Booleans genannt:** in MF5 mitbehoben — jetzt alle
  sechs Booleans gelistet.

## Korrigierte/verifizierte Code-Anker (review §Kontext-Sinnhaftigkeit FAIL)
Gegen den realen Tree nachgeprueft und in der Story korrigiert/praezisiert:
`control_plane/dispatch.py:393-453` (`_enforce_transition`), `:417`
(`get_transitions_from`-Konsum), `:456-472` (`_first_passing_edge`), `:549-557`
(`_rejected`), `:264-270` (Erstaufruf-nur-`setup`/run-admission);
`pipeline_engine/engine.py:192` (`_evaluate_transitions`), `:209`
(`_can_enter_phase`), `:293-303` (`_transition_target_for`), `:698-721`
(ESCALATED-Endzustands-Mapping), `:1530/1549/1582` (String-Literal-Vergleiche,
per Grep `override_type ==` belegt); `process/language/model.py:79-88`
(`OverridePolicy`, sechs Booleans), `:227` (`get_transitions_from`);
`process/language/definitions.py:93-96` (Implementation-Kanten inkl. guarded
`setup->exploration`), `:116-117` (Bugfix), `:134-135` (Concept), `:151-152`
(Research); `phase_state_store/models.py:66` (`override_type: str`);
`story_context_manager/models.py:58` (`PhaseName`), `:457`/`:493`
(`verify`-Hard-Reject); `core_types/` (existierende Kern-Enums als Owner-Vorlage).
Die im Review als falsch markierte Aussage „keine Doppel-Implementierung" + neuer
globaler Graph ist entfernt; ersetzt durch den belegten Superset-Vorfilter mit
einem Owner (§1 / §2.1 Punkt 3).

## status.yaml
Unveraendert. `depends_on: [AG3-001, AG3-054]` ist korrekt und deckt diese
Remediation: AG3-001 etabliert die `core_types`-Kern-Enums (neuer Owner
`core_types/override.py`), AG3-054 etabliert den `control_plane`-Dispatch +
Run-Admission, an den das Transition-Erst-Gate andockt. Konsistent mit
`_STORY_INDEX.md` Z. 46. `phase: review_pending` bleibt korrekt fuer den
laufenden Review-Zyklus; `status: draft` unveraendert (noch keine
Implementierung/Commit autorisiert).

## Genuine cross-story Voraussetzungen / Folge-Einheiten
1. **AG3-076 (Welle 3, Lifecycle/Recovery) — Operator-/Recovery-CLI.** Owner von
   `reset-escalation`/`run-phase`/`resume`/`cleanup` (FK-45 §45.4,
   `_STORY_INDEX.md` Z. 77). AG3-060 liefert nur die Transition-Bausteine + den
   Pre-Dispatch-Reject; Recovery aus dem persistierten ESCALATED-Endzustand
   bleibt AG3-076. Kein Scope-Transfer noetig; AG3-060 ist ohne AG3-076 lauffaehig
   (Reject ist terminal, Recovery ist separater Operator-Pfad).
2. **doc-/contract-Drift-Nachzug — FK-45 §45.2 „-> ESCALATED" vs. realer
   Pre-Dispatch-`rejected`.** Die §45.2-Prosa formuliert das Enforcement als
   `run_phase()`-internes ESCALATED; der reale v3-Schnitt verlagert es vor den
   Engine-Eintritt mit `rejected`-Contract (FK-45 §45.3). Code/Architektur ist
   autoritativ; die Prosa-Angleichung ist ein doc-only-Nachzug am FK-45-Owner
   (Muster `_STORY_INDEX.md` doc-only-Welle), **nicht** Teil des AG3-060-Code-Cuts.
   AG3-060 respektiert den realen Contract und meldet den Drift, mehr nicht.

Hinweis zur Cut-Treue (MF1/MF3): Die Absicherung des Superset-Graphen gegen die
story-typ-spezifischen Kanten ist bewusst INNERHALB AG3-060 gehalten, weil sie die
unmittelbare, untrennbare Konsequenz davon ist, dass `is_valid_phase_transition`
phasen-typ-unspezifisch ist; der `_STORY_INDEX.md` traegt keine andere Story, die
die Workflow-Kanten-Konsistenz liefert. Es findet KEINE Aenderung der
story-typ-spezifischen Workflow-Definitionen statt — diese bleiben die
unveraenderte autoritative Wahrheit, die AG3-060 nur konsumiert/vorfiltert.
