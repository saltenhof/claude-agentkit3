OVERALL: CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-15 §15.5.2 verlangt zweistufige Secret-Detection: Pre-Commit-Hook und Structural Check, mit identischen Patterns. Evidence: `concept/technical-design/15_security_secrets_identity_zugriffsmodell.md:185-224` nennt Stufe 1 Pre-Commit-Hook und Stufe 2 `security.secrets`; Patterns “beide Stufen identisch”. Die Story scoped nur `composition_root`/Structural Check: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:29), [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:47). Realer Hook [.githooks/pre-commit](t:/codebase/claude-agentkit3/.githooks/pre-commit:1) macht nur Concept-Validation, keinen Secret-Scan.  
  Fix: Pre-Commit-Hook in Scope/AC aufnehmen, gemeinsame Pattern-Quelle fuer Hook und Structural Check verlangen, Tests fuer beide Stufen.

- ERROR: `StoryCustomFieldDefinition`/`StoryCustomFieldValue` sind unvollstaendig geschnitten. Evidence: FK-17 verlangt Definition-Felder `display_name`, `field_type`, `provider`, `provider_field_ref`, `is_required`, `allowed_values` und Value-Felder `value`, `value_status`, `source`, `last_synced_at`, `last_written_by`, `last_sync_attempt_at` neben Sync/Conflict: `concept/technical-design/17_fachliches_datenmodell_ownership.md:189-227`. Story nennt nur `provider_sync_status`, `conflict_detected`, `is_writable_by_agentkit`: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:33), [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:50).  
  Fix: AC mit allen FK-17-Feldern und Persistenz-/Roundtrip-Tests fuer Definition und Value.

- ERROR: Freeze-Nachweis deckt nur den Negativfall ab. Evidence: FK-55 fordert Audit und Integrity-Gate-Nachweis fuer Aktivierungszeit, geblockten Principal und offiziellen Aufloesungspfad: `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md:744-753`. Story/AC verlangen nur “fehlt -> blockiert”: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:35), [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:52).  
  Fix: kanonischen Proof-Record/Owner/Storage und positiven Roundtrip-Test spezifizieren.

**2. AC-Schaerfe: FAIL**

- ERROR: AC5 ist nicht eindeutig testbar und fachlich zu eng. Evidence: AC5 sagt “Hook-Kontext” und “echter Servicepfad”: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:51). FK-55 §55.9 nennt aber Service-API und Operator-CLI-Pfade: `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md:502-516`; existierendes `principals.py` attestiert privilegierte Principals ueber strukturellen Service-Attest, nicht nur Hook-Kontext: `src/agentkit/governance/principal_capabilities/principals.py:51-60`.  
  Fix: erlaubte Attestierungsquellen nach §55.3a explizit definieren, positive Servicepfad-Faelle einzeln nennen, Bash-Spoofing-Negativtest behalten.

- WARNING: AC7 erlaubt “Begruendung”, FK-55 verlangt “kurze, strukturierte Begruendung”. Evidence: FK-55 `concept/.../55_principal_capability_model_story_scope_enforcement.md:776-790`; Story [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:53).  
  Fix: Rueckkanal-Schema mit erlaubten Feldern, Typen und Laengen-/Strukturgrenzen angeben.

**3. Klarheit/Eindeutigkeit: FAIL**

- ERROR: Bounded Context ist fuer Custom Fields falsch/unklar. Evidence: Story ordnet alles `governance` + `state_backend` zu: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:5). FK-17 setzt Owner `story_context_manager` fuer beide Custom-Field-Entitaeten: `concept/technical-design/17_fachliches_datenmodell_ownership.md:189-210`; FK-18 Catalog-Owner ist ebenfalls `story_context_manager`: `concept/technical-design/18_relationales_abbildungsmodell_postgres.md:67-82`.  
  Fix: Owner pro Teilwert trennen: `guard_system` fuer `GuardDecision`, `story_context_manager` fuer Custom Fields, `state_backend` nur Persistenzadapter.

- WARNING: Quell-Konzepte sind unvollstaendig fuer den eigenen Scope. Evidence: Quell-Liste nennt bei Servicepfad nur §55.6: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:11), Scope/Hint verwenden aber §55.9, §55.10.3/Step 8 und §55.3a: [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:34), [story.md](t:/codebase/claude-agentkit3/stories/AG3-087-secret-detection-audit-tables/story.md:70).  
  Fix: §55.3a, §55.9 und §55.10.3 in Quell-Konzepte aufnehmen.

**4. Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Die Ist-Zustand-Line-Claims sind zwar wahr, aber der resultierende Scope passt nicht vollstaendig zum echten System: Secret-FK fordert Hook + Structural; echter Hook ist [.githooks/pre-commit](t:/codebase/claude-agentkit3/.githooks/pre-commit:1) und wird nicht angefasst. Damit wuerde AG3-087 nach Umsetzung weiterhin FK-15 verletzen.  
  Fix: Hook-Pfad realistisch benennen und in Scope/Tests aufnehmen.

- WARNING: Verifizierte Claims/Anchors: `composition_root.py:773` und `:805-806`, `checker.py:459`, `matrix.py:26`, `enforcement.py:49-52` stimmen; `guard_decisions`, `GuardDecision`, `story_custom_field`, `StoryCustomField`, `security.secrets_content`, `is_official_service_path` haben 0 Treffer; `freeze|conflict_freeze` in `governance/integrity_gate/` hat 0 Treffer. Keine falschen Ist-Zustand-Zeilen gefunden.

**Must-Fix ERRORs**

1. Pre-Commit-Hook/identische Secret-Patterns in Scope, AC und Tests aufnehmen.
2. Custom-Field-Entitaeten mit allen FK-17-Feldern und Owner `story_context_manager` spezifizieren.
3. Servicepfad-Attestierung nach §55.3a/§55.9/§55.10.3 eindeutig definieren; “Hook-Kontext only” entfernen.
4. Freeze-Proof als Audit-Record mit positivem Erzeugungs-/Persistenztest spezifizieren.
