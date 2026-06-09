OVERALL: CHANGES-REQUESTED

Typprüfung: `status.yaml` sagt `type: implementation`; keine doc-only- oder Frontend-Sonderprüfung.

**1. Konzept-Vollstaendigkeit: FAIL**

- ERROR: Optional-Katalog wird normativ angerissen, aber nicht vollständig in AC/Tests übernommen.  
  Evidence: Story-Index fordert “Vollständigkeit des mitgelieferten Pflicht-/Optional-Skill-Katalogs” in `var/concept-gap-analysis/_STORY_INDEX.md:126`. FK-43 trennt Pflicht-Skills in `concept/technical-design/43_skills_system_task_automation.md:186-195` und optionale Skills in `:197-203`. Story-AC2 testet aber nur “Pflicht-Skills” in `stories/AG3-095-execute-userstory-skill-quality/story.md:39`.  
  Fix: AC2 muss Pflicht- und optionale Bundles explizit abdecken: Pflicht: `create-userstory-core`, `create-userstory-are`, `execute-userstory-core`, `execute-userstory-are`, `lookup-userstory`, `llm-discussion`; optional: `manage-requirements`, `semantic-review`; `Research` explizit als “kein Bundle, Worker-Prompt” ausschließen.

- ERROR: Normativer `semantic-review`-Inhalt fehlt.  
  Evidence: FK-43 verlangt dedizierten Semantic-Review-Skill mit “mindestens 12 definierten Pruefdimensionen” und strukturiertem Artefakt in `concept/technical-design/43_skills_system_task_automation.md:211`. Story nennt `semantic-review` nur beispielhaft in `story.md:16` und hat keinen AC für 12 Dimensionen, Scores, Begründung, Gesamtartefakt.  
  Fix: Eigenen AC ergänzen: `semantic-review`-Bundle existiert und `SKILL.md` beschreibt mindestens die 12 FK-Dimensionen plus normierten Score, Begründung und strukturiertes QA-Artefakt.

- ERROR: `SkillQualityMetric`-Norm ist nicht vollständig operationalisiert.  
  Evidence: FK-43 verlangt Telemetrie-Projektionen plus Failure-Corpus-Befunde, inklusive `experiment_tag`-Verknüpfung mit Skill-Versionen in `concept/technical-design/43_skills_system_task_automation.md:494-510`. Story-AC3 sagt nur “typisiertes SkillQualityMetric” in `story.md:40`, ohne Felder, Berechnungsregeln, Projekt-/Zeitfilter oder Skill-Version.  
  Fix: Metric-Schema konkretisieren: Felder, Filterdimensionen (`project_key`, `skill_name`, `bundle_version`/Experiment-Tag, Zeitfenster), Aggregationsformeln und Fail-closed-Regeln.

**2. AC-Schaerfe: FAIL**

- ERROR: AC3 ist nicht testbar.  
  Evidence: Story fordert “Nutzungshaeufigkeit/Erfolg/Incident-Bezug” in `story.md:28`, aber AC3 reduziert das auf “liefert ein typisiertes SkillQualityMetric” in `story.md:40`. Keine erwarteten Felder, keine Zählerdefinition, kein Nenner für Erfolgsquote.  
  Fix: AC3 in konkrete Assertions aufspalten: z. B. `usage_count`, `successful_runs`, `failed_runs`, `avg_qa_rounds`, `remediation_count`, `incident_count`, `incident_ids`, `source_window`.

- ERROR: AC1 verwendet “vollstaendig” ohne die FK-43-Schritte als prüfbare Checkliste.  
  Evidence: FK-43 §43.3.3 listet konkrete Schritte: Story lesen, `POST /phases/setup/start`, State lesen, Worker spawnen, `POST /phases/implementation/start`, Remediation-Loop, Closure, Eskalation in `concept/technical-design/43_skills_system_task_automation.md:218-230`. AC1 in `story.md:38` sagt nur “vollstaendig”.  
  Fix: AC1 muss diese acht Schritte als Bundle-Content-Assertions enthalten, inklusive “keine eigenständige verify-Top-Phase”.

- WARNING: Pflichtbefehle sind zu grob benannt.  
  Evidence: `story.md:43` sagt “vier Konzept-Gates”, ohne die vier Befehle zu nennen; CLAUDE/AGENTS nennen konkret u. a. `check_concept_frontmatter.py`, `compile_formal_specs.py`, Remote-Gates.  
  Fix: Befehlsliste exakt ausschreiben, inklusive `scripts/ci/check_remote_gates.ps1`.

**3. Klarheit/Eindeutigkeit: FAIL**

- ERROR: Quell-Konzept-Angabe ist sachlich falsch/irreführend.  
  Evidence: Story behauptet `FK-43 §43.3.1` sei “Pflicht-/Optional-Skills” in `story.md:7`; tatsächlich ist §43.3.1 nur “Pflicht-Skills” in `concept/technical-design/43_skills_system_task_automation.md:186`, optionale Skills stehen in §43.3.2 `:197`.  
  Fix: Quell-Konzepte ändern auf `FK-43 §43.3.1`, `§43.3.2`, `F-43-029`, `§43.3.3`, `§43.6.2`.

- ERROR: Story widerspricht sich bei fehlenden Datenfeldern.  
  Evidence: In Scope verlangt `collect_quality_metrics` funktional aus bestehenden Quellen in `story.md:28`; Out of Scope sagt bei fehlenden Feldern “melden ... nicht hier ein zweites Telemetrie-Modell bauen” in `story.md:35`; Hinweis wiederholt das in `story.md:60`. Real fehlen Skill-Zuordnungsfelder in `StoryMetricsRecord` (`src/agentkit/closure/post_merge_finalization/records.py:10-31`).  
  Fix: Entweder AG3-095 blockieren/abhängig machen von Telemetrie-/Failure-Corpus-Erweiterung, oder Scope auf ein fail-closed Metric-Skeleton mit explizitem Owner-Hand-off reduzieren. Nicht beides gleichzeitig.

- WARNING: Resource-Pfad ist unklar und gefährlich.  
  Evidence: Story nennt `resources/skill_bundles/` in `story.md:5`, `:16`, `:49`, `:57`; reale Bundles liegen unter `src/agentkit/resources/skill_bundles/`.  
  Fix: Alle Pfade paketrelativ präzisieren: `src/agentkit/resources/skill_bundles/...`.

**4. Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Ist-Zustand-Dateipfad ist falsch.  
  Evidence: Story behauptet Bundle vorhanden unter `resources/skill_bundles/execute-userstory-core/4.0.0/` in `story.md:16`; dieser Root-Pfad existiert nicht. Real existiert `src/agentkit/resources/skill_bundles/execute-userstory-core/4.0.0/manifest.json`, mit `skill_name: execute-userstory` und `profile: CORE`.  
  Fix: Ist-Zustand korrigieren und Guardrail-Referenz in `story.md:49` ebenfalls auf `src/agentkit/resources/skill_bundles/` ändern.

- ERROR: Failure-Corpus-Top-Surface ist keine nutzbare Datenquelle für die geforderte Metric.  
  Evidence: Story nennt “Failure-Corpus-Top-Surface ... als Datenquellen” in `story.md:20` und Scope `:28`. Real `FailureCorpus` hat funktional nur `record_incident` in `src/agentkit/failure_corpus/top.py:90-126`; `suggest_patterns`, `confirm_pattern`, `derive_check`, `approve_check`, `report_effectiveness` werfen `NotImplementedError` in `:128-204`.  
  Fix: Owner-Entscheidung ergänzen: entweder neue Failure-Corpus-Lese-Top-Surface in Scope aufnehmen, oder ausdrücklich `Telemetry.ProjectionAccessor.read_projection(FC_INCIDENTS)` als Quelle verwenden und den Konzeptkonflikt zu FK-43 §43.6.2 benennen.

- ERROR: Per-Skill-Metriken sind aus realen bestehenden Projektionen nicht ableitbar.  
  Evidence: FK fordert Skill-Version-Verknüpfung über `experiment_tag` in `concept/technical-design/43_skills_system_task_automation.md:507-510`; `Incident` hat nur `tags`, `impact`, `pattern_ref`, kein `experiment_tag`, in `src/agentkit/failure_corpus/incident.py:180-195`. `StoryMetricsRecord` hat `qa_rounds`, `final_status`, `llm_roles`, aber kein `skill_name`/`skill_version` in `src/agentkit/closure/post_merge_finalization/records.py:10-31`.  
  Fix: Vor AG3-095 klären: Wo entsteht die Skill-Usage/Experiment-Zuordnung? Wenn neues Feld nötig ist, eigene Telemetrie/Failure-Corpus-Story oder explizite Scope-Erweiterung mit Owner.

**Must-Fix ERROR List**

1. Quell-Konzepte auf §43.3.2/F-43-029 erweitern und optionale Skills vollständig in ACs testen.  
2. `semantic-review`-Bundle-Inhaltsanforderungen aus F-43-029 als AC aufnehmen.  
3. `SkillQualityMetric`-Schema und Aggregationsregeln konkret definieren.  
4. Konflikt “bestehende Quellen” vs. fehlende Skill-/Experiment-Felder auflösen.  
5. Failure-Corpus-Lesequelle/Owner sauber entscheiden.  
6. Falschen Resource-Pfad `resources/skill_bundles` auf `src/agentkit/resources/skill_bundles` korrigieren.  
7. AC1 als konkrete FK-43-§43.3.3-Schrittliste formulieren, inklusive Verbot einer separaten Verify-Top-Phase.
