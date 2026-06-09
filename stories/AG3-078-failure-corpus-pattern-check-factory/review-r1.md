OVERALL: CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**

- ERROR: `review-checks` ist unvollstaendig. FK-41 sagt: Mensch entscheidet „freigeben, anpassen oder verwerfen“ ([FK-41](t:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:557)). Die Story modelliert nur `approved`/`rejected` ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:35), [story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:56)).  
  Fix: `adjust/revise` als Review-Entscheidung mit Persistenz-/Validierungsregeln aufnehmen oder explizit mit Owner/Story auslagern.

- ERROR: FK-41 §41.6.2 verlangt ein dauerhaft dokumentiertes Beispiel für die Invariantenschaerfung: „muss ... dokumentiert sein“ ([FK-41](t:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:490)). Die Story hat dazu keinen Scope/AC.  
  Fix: AC ergaenzen: Referenzbeispiel wird in einem benannten Konzept-/Prompt-/Test-Artefakt gepflegt und per Konzept-Gate geprueft.

- WARNING: FK-41 §41.6.4 nennt neben `fc_check_proposals` auch Export unter `checks/CHK-{NNNN}/proposal.json` ([FK-41](t:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:524)). Story beschraenkt sich auf Projection-Schreiben ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:35)).  
  Fix: klaeren, ob Legacy-Export noch Pflicht ist; wenn nein, Owner/Concept-Nachzug benennen, sonst AC aufnehmen.

**AC-Schaerfe: FAIL**

- ERROR: AC1 ist nicht testbar genug. „Symptom-Aehnlichkeit“ ist nicht definiert ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:33), [story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:53)).  
  Fix: deterministische Cluster-Regel festlegen, z. B. normalisierte Symptom-Signatur, Token-/Hash-Verfahren, Schwellenwert und Tie-Breaker.

- ERROR: „Hohe Schwere bei 1“ verwischt die FK-Regel. FK fordert „produktionsrelevantem oder sicherheitskritischem Impact“ ([FK-41](t:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:388)); die Story testet nur „hohe Schwere bei 1“ ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:53)).  
  Fix: klare Mapping-Regel: welche `IncidentSeverity`/`impact`/`tags` zaehlen als produktionsrelevant oder sicherheitskritisch.

- ERROR: „guenstige Checkbarkeit“ ist unbestimmt. FK: 2 Incidents reichen, wenn ein Check mit niedriger FP-Gefahr ableitbar ist ([FK-41](t:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:389)). Story benennt keinen Nachweisweg vor der Promotion ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:33)).  
  Fix: festlegen, ob `false_positive_risk == low` aus Check-Proposal, deterministischer Kategorie-Matrix oder Human-Review kommt.

**Klarheit/Eindeutigkeit: FAIL**

- ERROR: Status-Begriffe widersprechen FK und Code. Story fordert `status=confirmed` ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:34)); FK-Schema und Core-Code kennen `accepted`, nicht `confirmed` ([FK-41](t:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:219), [failure_corpus.py](t:/codebase/claude-agentkit3/src/agentkit/core_types/failure_corpus.py:103)).  
  Fix: persistierter Pattern-Status muss `accepted` sein; `confirm_pattern`/`confirmed_at` bleiben nur Aktions-/Audit-Begriffe.

- ERROR: Effectiveness ist datenmodellseitig unklar. Story will `story_metrics` fuer TP/FP/no-findings lesen ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:36)), aber `StoryMetricsRecord` enthaelt keine `check_ref`, Check-Outcome-, Override- oder No-Finding-Felder ([records.py](t:/codebase/claude-agentkit3/src/agentkit/closure/post_merge_finalization/records.py:14)). `ProjectionFilter` kennt auch kein `check_ref` oder `since_days` ([projection_accessor.py](t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:119)).  
  Fix: Story muss die notwendige Metrikquelle mit Schema-Owner benennen und entweder `story_metrics` sauber erweitern oder ein eigenes FC-Check-Outcome-Read-Model definieren.

**Kontext-Sinnhaftigkeit: FAIL**

- ERROR: `Telemetry.write_projection` fuer `FC_PATTERNS`/`FC_CHECK_PROPOSALS` passt nicht zum realen Code. Der Accessor weist diese Kinds aktuell fail-closed als extern besessen ab ([projection_accessor.py](t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:97), [projection_accessor.py](t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:271)); vorhandene Repos haben `save()` ([fc_pattern_repository.py](t:/codebase/claude-agentkit3/src/agentkit/state_backend/store/fc_pattern_repository.py:160), [fc_check_proposal_repository.py](t:/codebase/claude-agentkit3/src/agentkit/state_backend/store/fc_check_proposal_repository.py:185)).  
  Fix: Scope/AC explizit auf ProjectionAccessor-Ownership-Wiring erweitern oder Story auf die vorhandenen Repository-Ports ausrichten.

- ERROR: Sonar-Schwellenwert existiert im Code nicht. Story verlangt `sonarqube.accept_frequency_fc_threshold` aus Config ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:38)); `SonarQubeConfig` definiert nur `available`, `enabled`, `base_url`, `token_env`, `min_version`, `plugins`, `quality_gate`, `scanner_version` ([models.py](t:/codebase/claude-agentkit3/src/agentkit/config/models.py:173)).  
  Fix: Config-Feld mit Owner/Migration/Tests in Scope aufnehmen oder harte Dependency auf eine Code-Story setzen, die das Feld vorher liefert.

- NIT: Ist-Zustand-Glob ist minimal ungenau: Story listet die `failure_corpus/*.py`-Dateien ohne `__init__.py` ([story.md](t:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:22)); real existiert `src/agentkit/failure_corpus/__init__.py`. Der Kernbefund „kein cli.py“ stimmt.

Verifizierte Anker/Ist-Zustand: FK-41 §§41.5/41.6/41.6.7/41.9/41.10 existieren; Gap-Report `gap-fk-36-45.md` hat `## FK-41` ([gap](t:/codebase/claude-agentkit3/var/concept-gap-analysis/gap-fk-36-45.md:240)); Top-Stubs bei `suggest_patterns` bis `report_effectiveness` stimmen ([top.py](t:/codebase/claude-agentkit3/src/agentkit/failure_corpus/top.py:128)); kein `failure-corpus` in `cli/main.py`.

**Must-Fix ERRORs**

1. Pattern-Status `confirmed` auf `accepted` korrigieren.
2. `review-checks`-Pfad `anpassen/revise` spezifizieren.
3. Clustering, hohe Schwere und guenstige Checkbarkeit testbar definieren.
4. Effectiveness-Datenquelle real modellieren; aktuelles `story_metrics` reicht nicht.
5. ProjectionAccessor-/Repository-Schreibpfad fuer `fc_patterns`/`fc_check_proposals` eindeutig machen.
6. `sonarqube.accept_frequency_fc_threshold` als reales Config-Feld/Dependency klaeren.
7. F-41-070 Referenzbeispiel in Scope/AC aufnehmen.
