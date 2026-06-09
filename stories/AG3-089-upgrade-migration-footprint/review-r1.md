OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**
- **ERROR:** FK-51 §51.3 wird falsch umgeschnitten. Die Story macht daraus „Erst-Upgrade / Re-Upgrade / Cross-Major“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:36)); FK-51 definiert aber die drei Szenarien als unveraenderte Config+Bindung, nutzerangepasste Config, neue Skill-/Prompt-Variante ([51_upgrade...md](T:/codebase/claude-agentkit3/concept/technical-design/51_upgrade_migration_customization_preservation.md:76)).  
  **Fix:** Scope/AC auf die echten drei FK-Szenarien mit Digest-/Bundle-/Binding-Entscheidungskriterien umstellen.
- **ERROR:** Story verlangt bei erkannter Anpassung generell „blockiert/meldet … statt zu ueberschreiben“ und „mutiert nicht“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:39), [story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:54)). FK-51 §51.3.2 sagt fuer angepasste Config aber: `.bak` erstellen, dann neue Version schreiben, Mensch zieht Anpassungen nach ([51_upgrade...md](T:/codebase/claude-agentkit3/concept/technical-design/51_upgrade_migration_customization_preservation.md:89)).  
  **Fix:** Schreibverhalten pro Quelle differenzieren: Config-Migration gemaess FK mit Backup/Explizitheit; Cleanup/Binding-Schreibpfade fail-closed gegen erkannte Anpassungen.
- **WARNING:** Git-Hook-Migration deckt nicht explizit ab, dass unerkannte Pre-Commit-Anpassungen als `.bak` gesichert werden muessen ([51_upgrade...md](T:/codebase/claude-agentkit3/concept/technical-design/51_upgrade_migration_customization_preservation.md:177)).  
  **Fix:** Scope/AC-Test fuer „unerkannter alter pre-commit -> `.bak`, keine stille Zerstoerung“ aufnehmen.

**2) AC-Schaerfe: FAIL**
- **ERROR:** AC3 testet Hook-Migration und Dispatching, aber nicht den FK-51.6.1-Schutzfall `.bak` fuer unerkannte Anpassungen ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:51)).  
  **Fix:** Negativ-/Preservation-Test ergaenzen.
- **ERROR:** Kein AC beweist die drei echten §51.3-Szenarien; AC1/2 fokussieren nur `3->4` Migration, AC3 Hooks, AC4 Cleanup, AC5/6 Footprint ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:49)).  
  **Fix:** Drei Szenario-Tests aufnehmen: unchanged skip, config digest mismatch, explicit new bundle/profile binding.

**3) Klarheit: WEAK**
- **ERROR:** „Nur eine der vier Lesequellen existiert als Top-Surface“ ist falsch/irrefuehrend ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:21)). Prompt-Projektbinding existiert als `resolve_project_prompt_binding`/`PromptBundleBinding` ([resources.py](T:/codebase/claude-agentkit3/src/agentkit/prompt_runtime/resources.py:37), [resources.py](T:/codebase/claude-agentkit3/src/agentkit/prompt_runtime/resources.py:105)); CCAG hat `load_rules`/Runtime-Surface ([rules.py](T:/codebase/claude-agentkit3/src/agentkit/governance/ccag/rules.py:345)); Config-Loader/Model existieren ([loader.py](T:/codebase/claude-agentkit3/src/agentkit/config/loader.py:52), [models.py](T:/codebase/claude-agentkit3/src/agentkit/config/models.py:335)); Skill-Surface existiert ([top.py](T:/codebase/claude-agentkit3/src/agentkit/skills/top.py:625)).  
  **Fix:** Ist-Zustand korrigieren: Aggregat/Invariante fehlen, mehrere Owner-Lesesurfaces existieren bereits.
- **ERROR:** `ProjectPromptPin` wird als realer Anker genannt ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:24)), existiert aber nicht; `pins.py` hat `PromptRunPin`, Projektbinding liegt in `resources.py`.  
  **Fix:** Auf `resolve_project_prompt_binding` / `PromptBundleBinding` / `PromptRuntime.update_binding` umankern.

**4) Kontext-Sinnhaftigkeit: WEAK**
- **PASS:** Index-Row und `status.yaml` stimmen: AG3-089 Scope/Dependencies in `_STORY_INDEX.md:105`; `depends_on: AG3-070, AG3-088` in [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/status.yaml:8).
- **PASS:** Wichtige Fehlstandsanker sind real: `PROJECT_CONFIG_VERSION = "1"` ([runner.py](T:/codebase/claude-agentkit3/src/agentkit/installer/runner.py:75)); `update_upgraded` bei Re-Run ([runner.py](T:/codebase/claude-agentkit3/src/agentkit/installer/runner.py:1343)); `installer/upgrade` fehlt; `Skills.resolve_binding` existiert ([top.py](T:/codebase/claude-agentkit3/src/agentkit/skills/top.py:625)).
- **WARNING:** `Governance.register_hooks` wird mit `governance/hook_registration.py` verankert ([story.md](T:/codebase/claude-agentkit3/stories/AG3-089-upgrade-migration-footprint/story.md:25)); die Methode sitzt tatsaechlich in [runner.py](T:/codebase/claude-agentkit3/src/agentkit/governance/runner.py:193), `hook_registration.py` liefert nur Typen.  
  **Fix:** Callable-Anker auf `governance/runner.py:193`, Typ-Anker auf `hook_registration.py`.

**Must-Fix**
1. §51.3-Scope und ACs auf die echten drei FK-Szenarien korrigieren.
2. Widerspruch zwischen „keine Mutation“ und FK-51.3.2 Backup+Write aufloesen.
3. `ProjectPromptPin` und falsche/unsaubere Top-Surface-Anker korrigieren.
4. Ist-Zustand „nur eine Lesequelle existiert“ berichtigen.
5. AC fuer Git-Hook `.bak` bei unerkannter Anpassung ergaenzen.
