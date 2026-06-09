OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit — FAIL**

- **ERROR:** CCAG-Regelgeneralisierung verletzt FK-42, weil die Story Persistenz direkt als Scope/AC formuliert. FK-42 erlaubt eine Dauerregel erst nach bewusster Zusatzentscheidung; erste positive Entscheidung ist nur Einzelfall/Lease. Evidence: `stories/AG3-086-hook-guard-buildout/story.md:46`, `:64`; `concept/technical-design/42_ccag_tool_governance_permission_runtime.md:257`, `:269`, `:306`.  
  **Fix:** AC splitten: LLM erzeugt nur Vorschlag/Draft; `approved.yaml` wird erst nach expliziter Promote-/Confirm-Entscheidung geschrieben; Negativtest “keine Persistenz ohne Confirm”.

- **ERROR:** Permission-TTL bleibt konzeptionell unvollstaendig. Story nennt nur Ist-Code `DEFAULT_TTL_SECONDS = 600`, aber FK-93 fordert `permissions.request_ttl_s` Default 1800s. Evidence: `story.md:21`; `src/agentkit/governance/ccag/requests.py:41`; `concept/technical-design/93_standardwerte_schwellwerte_timeouts.md:64`.  
  **Fix:** Scope/AC um typisierte Config `permissions.request_ttl_s` Default 1800 ergaenzen oder explizit als vorgelagerten Konzept-/Config-Gap blockieren.

- **ERROR:** Guard-Signale sind behauptet, aber nicht akzeptanzscharf. Story sagt, Guards emittieren Signale fuer AG3-085, AC testen aber nur Block/Allow. FK-68 erwartet `integrity_violation` mit `guard/detail/stage`. Evidence: `story.md:51`, `:57-64`; `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md:368`.  
  **Fix:** AC fuer Event-Emission je gebautem Guard ergaenzen, mindestens Prompt-Integrity mit `stage=escape_detection|schema_validation|template_integrity`.

**2) AC-Schaerfe — FAIL**

- **ERROR:** Prompt-Integrity-AC widersprechen FK-31-Modussemantik. Story verlangt “permanent aktiv” mit drei Pruefstufen und Template-Block generell; FK-31 sagt permanent aktiv, aber im `ai_augmented`-Modus reduziert, Template-/Skill-Proof nur in `story_execution`, QA-Agents sind von Template-Integritaet ausgenommen. Evidence: `story.md:9`, `:39-43`, `:59-61`; `concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md:611`, `:615-626`.  
  **Fix:** AC mode-scharf machen: Freestyle/AI-Augmented reduced schema + escape; Story-Execution full; QA-Agent-Template-Ausnahme; Tests fuer beide Modi.

- **WARNING:** CCAG-Huellen-AC ist sprachlich missverstaendlich: “fehlt die Huelle -> fail-closed unzulaessig” kann als “fail-closed ist unzulaessig” gelesen werden. Evidence: `story.md:44`; FK meint: Aufruf ohne Huelle ist unzulaessig und fail-closed zu blocken, `concept/.../42_ccag_tool_governance_permission_runtime.md:203-216`.  
  **Fix:** Formulieren: “Fehlt die Huelle, ist der CCAG-Aufruf unzulaessig und erzeugt einen fail-closed Block.”

**3) Klarheit — WEAK**

- **ERROR:** Prompt-Integrity-Ist-Claim “Grep ... -> 0 Treffer” ist falsch. Unter `src/agentkit/resources/.../SKILL.md` existieren `AGENTKIT-SUBAGENT-V1` und `skill_proof`. Evidence: `story.md:20`; `src/agentkit/resources/skill_bundles/execute-userstory-core/4.0.0/SKILL.md:57-62`, `:64-69`, `:151-153`.  
  **Fix:** Claim korrigieren: kein Produktions-Guard/HookIdentifier vorhanden, aber Spawn-Header existiert bereits als Resource-/Skill-Vertrag und muss konsumiert werden.

- **WARNING:** FK-Verweis fuer WebCallBudget nennt `FK-30 §30.10`, das ist Worker-Health-Monitor, nicht WebCallBudget. Evidence: `story.md:8`; WebCallBudget steht in `concept/technical-design/30_hook_adapter_guard_enforcement.md:568-580`, Worker-Health in `:912`.  
  **Fix:** Quelle auf `FK-30 §30.5.1/§30.5.1a` und FK-68 §68.6 begrenzen; §30.10 nur bei AG3-080 lassen.

**4) Kontext-Sinnhaftigkeit — FAIL**

- **ERROR:** WebCallBudget-Ist-Zustand ist materiell falsch und laesst einen Duplicate-Owner offen. Story sagt, nur observationale Haelfte existiere und Emitter bleibe unveraendert observational; real blockiert `BudgetEventEmitter` bereits und ist als Pre-Hook `budget_event_emitter` verdrahtet. Evidence: `story.md:18`, `:33-35`, `:54`; `src/agentkit/telemetry/hooks/budget_event_emitter.py:1-6`, `:51-54`, `:112-149`; `src/agentkit/governance/runner.py:591-594`, `:913-987`; `src/agentkit/telemetry/hooks/base.py:21-23`.  
  **Fix:** Story muss die Migration explizit machen: Blocking aus `BudgetEventEmitter` entfernen/neutralisieren, `WebCallBudgetGuard` als alleinigen Block-Owner einfuehren, Runner-/Hook-ID-Pfade `budget` vs. `budget_event_emitter` sauber konsolidieren, Tests gegen Doppelblockade und falschen Owner.

**Must-Fix**

1. WebCallBudget-Ist-Zustand und Migrationsscope korrigieren, inklusive bestehendem `budget_event_emitter`-Blockpfad.
2. Prompt-Integrity mode-scharf und mit QA-Template-Ausnahme spezifizieren.
3. Falschen Prompt-Integrity-Nulltreffer korrigieren und Resource-Header als vorhandenen Anker aufnehmen.
4. CCAG-Regelgeneralisierung mit Confirm-/Promote-Barriere absichern.
5. Permission-TTL auf `permissions.request_ttl_s` Default 1800 oder expliziten Blocker bringen.
6. Event-Emission/Telemetry-AC fuer die neuen Guards ergaenzen.
