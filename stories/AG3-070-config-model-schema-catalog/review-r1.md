OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**
- ERROR: AG3-070 deckt die Owner-Pflicht `sonarqube.accept_frequency_fc_threshold` nicht ab. `_CROSS_STORY_PREREQS.md:6` weist das Feld explizit AG3-070 zu; FK-03 nennt es in `concept/technical-design/03_konfigurationsmodell_schemas_versionierung.md:184`, `:205`, `:458`. Die Story listet in Scope/AC nur `orchestrator_guard`/`policy`/`vectordb`/`telemetry`/`governance` (`story.md:33`, `:48`) und laesst `sonarqube` weg. Fix: `sonarqube.accept_frequency_fc_threshold: float = 0.25`, Validierung `0..1`, Default-Test und Negativtest in Scope/AC aufnehmen.
- PASS: Die VektorDB-Owner-Pflicht ist abgedeckt: `vectordb`-Stanza mit `similarity_threshold=0.7` und `max_llm_candidates=5` steht in Scope/AC (`story.md:33`, `:48`) und passt zur Index-Zeile (`_STORY_INDEX.md:66`).

**AC-Schaerfe: WEAK**
- ERROR: Loader-Exception ist unscharf/falsch an der Code-Grenze. Story fordert `ValueError` vom Loader (`story.md:30`, `:45`), der reale Loader kapselt Validierungsfehler aber als `ConfigError` (`src/agentkit/config/loader.py:101-106`). Fix: AC trennen in “Pydantic-Validator wirft `ValueError`” und “`load_project_config` liefert fail-closed `ConfigError` mit Ursache”, oder explizit eine Loader-API-Aenderung samt Test-Impact verlangen.
- WARNING: `Jedes versionierte Artefakt-/Config-Modell` ist als AC zu breit ohne Inventarliste (`story.md:34`, `:49`). FK-90 listet konkrete Schema-Familien (`concept/technical-design/90_schema_katalog.md:50-88`). Fix: in der Story eine explizite Pydantic-Owner-Inventarliste oder eine klar begrenzte Such-/Contract-Test-Regel aufnehmen.

**Klarheit: WEAK**
- ERROR: Ist-Zustand-Claim “Nur `installer/registration.py` traegt einen `config_version`-Record” ist falsch (`story.md:20`). Reale Treffer existieren u.a. in `src/agentkit/closure/post_merge_finalization/records.py:30`, `:55-56`, State-Mappers/Stores und Installer. Fix: umformulieren zu “kein `config_version` im Config-Modell/Loader; andere operative/telemetrische Records existieren und sind nicht das project.yaml-Pflichtfeld”.
- WARNING: Analog ist “Grep nur String-Referenzen in `installer/registration.py`” fuer `llm_roles` zu eng (`story.md:21`); Closure-Metrics und State-Store fuehren `llm_roles` (`src/agentkit/closure/post_merge_finalization/records.py:31`, `:57-58`). Fix: Claim auf “kein typisiertes Config-Feld” begrenzen.

**Kontext-Sinnhaftigkeit: FAIL**
- ERROR: Story ignoriert den bereits existierenden partiellen `SonarQubeConfig`-Owner. Der Code hat `SonarQubeConfig` und `PipelineConfig.sonarqube` (`src/agentkit/config/models.py:122`, `:173-180`, `:380`), aber kein `accept_frequency_fc_threshold`; `src/agentkit/config/__init__.py:22-25` exportiert Sonar-Config-Typen. Fix: AG3-070 muss diesen bestehenden Owner erweitern, nicht eine neue parallele Stanza einführen.
- WARNING: `status.yaml` hat `unblocks: []` (`status.yaml:10`), waehrend der Index direkte Abhaenger nennt: AG3-068/069 (`_STORY_INDEX.md:64-65`) sowie AG3-088/089/103 (`_STORY_INDEX.md:104-105`, `:144`). Fix: Status-Metadaten mit Index konsolidieren oder bewusst begruenden, warum `unblocks` leer bleibt.

**Must-Fix**
1. `sonarqube.accept_frequency_fc_threshold` in Scope, AC und Hinweise aufnehmen: Default `0.25`, `0..1`-Validierung, Tests.
2. Loader-Exception-Erwartung an reale `ConfigError`-Grenze anpassen oder API-Aenderung explizit machen.
3. Falsche Ist-Zustand-Grep-Claims zu `config_version` und `llm_roles` korrigieren.
4. Schema-Versionierungs-AC mit konkreter Pydantic-Owner-/Familienliste schaerfen.
5. `status.yaml.unblocks` gegen `_STORY_INDEX.md` abgleichen.
