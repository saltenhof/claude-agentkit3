# AG3-069 — Remediation R1 (Antwort auf review-r1.md)

**Modus:** Story-Dokument-Remediation nach giftiger Codex-Review. Es wurde **kein** Produktionscode, **kein** Test, **kein** Konzept und **keine** Fremd-Story angefasst. Geaendert wurden ausschliesslich `story.md` und `status.yaml` dieser Story.

Belege wurden gegen die realen Quellen verifiziert: `concept/technical-design/05_integration_stabilization_contract.md`, `concept/technical-design/37_verify_context_und_qa_bundle.md` (§37.1.3, Z. 183–205), `concept/formal-spec/integration-stabilization/{events,invariants,scenarios}.md`, `src/agentkit/story_context_manager/types.py`, `.../routing_rules.py`, `src/agentkit/verify_system/stage_registry/data.py`, `var/concept-gap-analysis/_STORY_INDEX.md`, `stories/AG3-072-.../story.md`, `stories/AG3-067-.../{story.md,status.yaml}`.

---

## Must-Fix (ERROR)

### MF1 — FK-37 §37.1.3: vier Pflichtchecks exakt, inkl. `integration_target_matrix_passed`
**Befund:** Story nannte als "vier Vertrags-Pflichtpruefungen" `declared_surfaces_only`, Approval, Budget, Binding; FK-37 §37.1.3 fordert `integration_target_matrix_passed`, `declared_surfaces_only`, `stabilization_budget_not_exhausted`, `stability_gate`.
**Verifiziert:** FK-37 §37.1.3 (37_verify_context_und_qa_bundle.md:189-192) listet genau diese vier.
**Resolution:** Scope §2.1.11 und AC12 nennen jetzt **exakt** die vier FK-37-Checks inkl. Schichtzuordnung (§37.1.3: `declared_surfaces_only`→Schicht 1; `stabilization_budget_not_exhausted`→Hook/Capability, im Subflow auditierend; `integration_target_matrix_passed`/`stability_gate`→Subflow-/Closure-Precondition). Manifest-Approval-Vorbedingung und Bindungs-Integritaet sind explizit als **zusaetzliche** fail-closed Vorbedingungen modelliert, **nicht** als Ersatz fuer die FK-37-Liste. Quell-Konzept-Anker um `FK-37 §37.1.3` mit den vier Checks erweitert.

### MF2 — FK-05 §5.5.2: vollstaendiger Manifest-Mindestfeldsatz
**Befund:** Story forderte nur Surfaces/Seams, Version, Hash, Binding.
**Verifiziert:** FK-05 §5.5.2 (05_…:140-152): `project_key`, `story_id`, `implementation_contract`, `target_seams`, `allowed_repos_paths`, `integration_targets`, `allowed_contract_changes`, `stabilization_budget`, `out_of_contract_examples`.
**Resolution:** Scope §2.1.1 und AC1 fuehren jetzt den **vollstaendigen** §5.5.2-Feldsatz plus Version und Hash auf.

### MF3 — FK-05 §5.11: Closure-Precondition als AC + Negativtest
**Befund:** Story registrierte `stability_gate`, verlangte aber keine Closure-Precondition.
**Verifiziert:** FK-05 §5.11 (05_…:323-333): Closure nur bei `stability_gate=PASS` + erreichten Integrationszielen + keiner offenen Manifest-Verletzung + keinem Replan-/Split-Bedarf. Invariante `closure_requires_stability_gate_pass` (invariants.md:57-59).
**Resolution:** Neuer Scope-Punkt §2.1.8 + AC9 (Negativtest pro Bedingung), als Blockierpunkt in §2.3 verankert.

### MF4 — FK-05 §5.14: Telemetrie aufgenommen
**Befund:** Eigene Telemetrie fuer Manifest-Freigabe, Undeclared-Surface, Budget-Erschoepfung fehlte komplett.
**Verifiziert:** FK-05 §5.14 Punkt 6 (05_…:382-383); Formal-Spec events.md:27-43 (`integration_manifest_approved`/`undeclared_surface_detected`/`stabilization_budget_exhausted`/`stability_gate_passed` mit Producer `human_cli`/`guard_system`/`pipeline_deterministic`).
**Resolution:** Neuer Scope-Punkt §2.1.10 + AC11 mit benannten Events und Producer-Bindung an die Formal-Spec.

### MF5 — Budget: Regression-Cap ergaenzt
**Befund:** Budget-AC zu eng (nur Schleifen/Surfaces/Contract-Changes).
**Verifiziert:** FK-05 §5.9 (05_…:283): "zulaessige Regressionen zwischen zwei Verify-Zyklen".
**Resolution:** §2.1.3 und AC4 fuehren die **Regression-Cap** als vierte Cap mit eigenem Test ("ein Test pro Cap, inkl. Regression-Cap").

### MF6a — Repo-Set-/Worktree-Grenze als testbare AC
**Befund:** Fehlte als testbare AC.
**Verifiziert:** FK-05 §5.5.5 (05_…:183-192); Invariante `manifest_may_not_expand_repo_set` (invariants.md:39-41).
**Resolution:** §2.1.1 (Repo-Set-Grenze) + AC3 (Negativtest fuer Pfade ausserhalb `worktree_roots`/participating Repos).

### MF6b — Reklassifikation / No-Retroactive-Legalization
**Befund:** Fehlte, obwohl FK-05 §5.7/§5.13 im Index-Scope liegt und AG3-072 die enge Reklassifikation explizit AG3-069 zuordnet.
**Verifiziert:** FK-05 §5.7.3/§5.13 (05_…:247-261, :348-363); Invariante `reclassification_may_not_legalize_pre_manifest_cross_scope_delta` (invariants.md:45-47); **AG3-072 story.md:49** ("Enge Reklassifikation auf `integration_stabilization` … — AG3-069"). _STORY_INDEX.md:65 fuehrt FK-05 §5.2-§5.14 als AG3-069-Scope.
**Resolution:** Owner ist **in-story** (AG3-069), korrekt — AG3-072 routet ausdruecklich hierher. Neuer Scope-Punkt §2.1.9 + AC10: Reklassifikationspfad mit frischer `evidence_epoch`, manifestgebundenem Overlay und Quarantaene vorbestehender Cross-Scope-Deltas. In §2.2 und §6 ist die Abgrenzung zu AG3-072 (Standard-Split bleibt dort) explizit gemacht.

### MF7 — Falsche Ist-Zustand-/Grep-Zeile korrigiert
**Befund:** Review las die Zeile als "0 Treffer"-widersprechend.
**Verifiziert:** Grep `integration_scope_manifest`/`manifest_approval` ueber `src/agentkit/**/*.py` → 0 Treffer; `types.py:24-26` enthaelt nur das Enum mit dem Wert `integration_stabilization` (kein Manifest/Approval).
**Resolution:** §1 praezisiert: "0 Treffer in `src/agentkit/**/*.py`; in `types.py` existiert ausschliesslich der Enum-Wert `integration_stabilization` (`types.py:26`)". Hinweis: der vom Review zitierte Code-Anker `types.py:24` ist real korrekt (Klassenkopf `ImplementationContract`); die Story verankert jetzt zusaetzlich `types.py:26` (Enum-Wert) und `types.py:37`/`:50-54` (Profil-Referenz).

### MF8 — AG3-067-Dependency geklaert/ergaenzt
**Befund:** `status.yaml` fehlte `AG3-067`, obwohl die Story den integration_stabilization-Kontextanteil an den Context-Sufficiency-Builder andocken will.
**Verifiziert:** AG3-067 status.yaml besitzt den `ContextSufficiencyBuilder` (AG3-067 story.md §2.1.1); _STORY_INDEX.md:58 weist FK-37-Builder AG3-067 zu.
**Resolution:** `AG3-067` in `status.yaml depends_on` ergaenzt; Scope §2.2 und §1/§6 dokumentieren das Andocken an den AG3-067-Builder ohne Zweitbau. Story bleibt damit self-consistent (dockt an, baut nicht gegen den Builder vorbei).

---

## WARNING

### W1 — "produktive Integrationsarbeit blockiert" operationalisiert
**Befund:** An mehreren Stellen nicht ausreichend konkret.
**Resolution:** Neuer Abschnitt **§2.3 Blockierpunkte** benennt die fuenf konkreten Punkte mit FK-05-Anker: Worker-Spawn (§5.5.1), Setup/Routing (§5.6), PreToolUse-Write-Guard (§5.12), Capability-/Hook-Layer (§5.9), Closure-Precondition (§5.11). AC2 referenziert diese Blockierpunkte.

---

## Code-Anker-Korrekturen (file:line gegen realen Code)
- `types.py:24-26` (Enum), `types.py:37`/`:50-54` (Profil-Referenz) — verifiziert.
- `routing_rules.py:23-42` (`get_phases_for_story`/`should_run_exploration` werten nur `mode`/`execution_route`, kein `implementation_contract`) — verifiziert, in §1 verankert.
- `stage_registry/data.py:61-157` (`LAYER_1_STAGES`, kein `stability_gate`) — verifiziert, in §1 verankert.
- Formal-Spec-Anker `events.md:27`, `invariants.md:26-66` — verifiziert, in Quell-Konzepten/§6 verankert.

---

## Template-/Sprach-Treue
- AG3-057-Template-Struktur (Abschnitte 1–6 inkl. "Out of Scope (mit Owner)", AC mit Pflichtbefehlszeile, Guardrail-Referenzen, Hinweise fuer den Sub-Agent) beibehalten; ein operationalisierender Unterabschnitt §2.3 ergaenzt (gleiche Konvention wie Geschwister-Stories mit Abgrenzungsblock).
- ARCH-55: alle neuen Identifier/Wire-Keys englisch (`integration_scope_manifest`, `manifest_approval_record`, `stabilization_budget`, `stability_gate`, `seam_allowlist`, `declared_surfaces_only`, `integration_target_matrix_passed`, `stabilization_budget_not_exhausted`, `evidence_epoch`, Telemetrie-Event-IDs). Fach-Prosa bleibt deutsch (zulaessig).

---

## Genuine cross-story prerequisites
- **AG3-064** (Stage-Registry-Vollausbau) — `stability_gate` haengt sich ein; hartes `depends_on` (bestand).
- **AG3-070** (Config-Modell) — Config-Konsum; hartes `depends_on` (bestand).
- **AG3-067** (ContextSufficiencyBuilder) — der FK-37 §37.1.3-Kontextanteil dockt an dessen Builder an; `depends_on` **neu ergaenzt**.
- **AG3-072** liefert **nicht** die Reklassifikation — AG3-072 routet sie ausdruecklich an AG3-069; daher in-story, **kein** prerequisite. AG3-072 ist umgekehrt schwach abhaengig von dieser Story fuer den engen Reklassifikationspfad (dort bereits als Out-of-Scope→AG3-069 dokumentiert).

## Geaenderte Dateien (nur AG3-069)
- `stories/AG3-069-integration-stabilization-machinery/story.md`
- `stories/AG3-069-integration-stabilization-machinery/status.yaml` (depends_on: +AG3-067)
- `stories/AG3-069-integration-stabilization-machinery/remediation-r1.md` (dieses Dokument)
