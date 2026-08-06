# Inventur historischer `project.yaml`-Vertragsbrüche

Erstellt in AG3-226 (Runden 9–11), Grundlage von **AG3-228**.

Stand: 2026-08-06, Runde 11

## Ergebnis und Mengengrenze

Die Inventur enthält **11 geschlossene Vertragsfälle**. Ein Fall ist eine
Feld- oder Cross-Field-Regel, für die ein produktiver AK3-Writer bei einem
damals vertragsgültigen Installerlauf mindestens einen Zustand in
`.agentkit/config/project.yaml` persistieren konnte, den das heutige
`ProjectConfig` ablehnt.

**Auslassungen sind Teil der Menge.** `ABSENT` ist hier ein historischer Wert:
Wenn AK3 ein Feld bewusst nicht schrieb, die damalige Modellgrenze die Datei
akzeptierte und die heutige Modellgrenze gerade wegen der Auslassung
fail-closed abbricht, braucht ein bestehendes AK3-Projekt denselben
Migrationsentscheid wie bei einem expliziten Altwert. Ein Ausschluss von
Auslassungen würde reale, von AK3 erzeugte und heute nicht mehr ladbare Dateien
unsichtbar machen. Diese Entscheidung erweitert die Menge um sechs Fälle:
`project_key`, `pipeline.sonarqube`, `pipeline.ci`,
`pipeline.sonarqube.scanner_version`, `pipeline.config_version` und
`pipeline.llm_roles`.

Gezählt wird pro heute verletzter Feld-/Cross-Field-Regel, nicht pro beliebigem
Stringexemplar. Deshalb bilden alle durch dieselbe HTTP-Endpunktregel
ausgeschlossenen Komponenten einen Fall und alle durch dieselbe
gRPC-Endpunktregel ausgeschlossenen Formen einen weiteren Fall.

## Inventar

| Nr. | Feld und heutiger Locator | Verschärfung | Historischer, heute abgelehnter Wert | Produktiver Writer | Migration vorhanden? |
|---:|---|---|---|---|---|
| 1 | `project_key`; `src/agentkit/backend/config/models.py:952` (`ProjectConfig.project_key`) | `9b50b89df525af872918e2e7bfa9ae4ea1aa915d` machte das Feld verpflichtend. | `ABSENT` | `e5c00724280eee12c9567375563b52ffde14bc19`, `_build_project_yaml`, schrieb die erste produktive Form ohne `project_key`. | Nein. |
| 2 | `pipeline.sonarqube`; `src/agentkit/backend/config/models.py:837` und `:1023` (`_validate_sonarqube_codeproducing`) | `fba49c8cbfd26147706ae15caf4d1d69b450f121` verlangte die Stanza für die vom Writer verwendeten codeerzeugenden Storytypen. | `ABSENT` bei `story_types` mit `implementation`/`bugfix` | `e5c00724280eee12c9567375563b52ffde14bc19`, `_build_project_yaml`; alle Writerrevisionen bis zum Parent der Verschärfung ließen die Stanza aus. | Nein. |
| 3 | `pipeline.ci`; `src/agentkit/backend/config/models.py:838` und `:1074` (`_validate_ci_codeproducing`) | `9647d993df3302e85f6c8226c76082df40d49ef4` verlangte die Stanza für codeerzeugende Storytypen. | `ABSENT` bei `story_types` mit `implementation`/`bugfix` | `e5c00724280eee12c9567375563b52ffde14bc19`, `_build_project_yaml`; auch der Sonar-Writer aus `fba49c8c` schrieb noch kein `ci`. | Nein. |
| 4 | `pipeline.sonarqube.scanner_version`; `src/agentkit/backend/config/models.py:262` und `:289` (`SonarQubeConfig._validate_active_requires_endpoint`) | `9647d993df3302e85f6c8226c76082df40d49ef4` verlangte bei `available=true, enabled=true` zusätzlich die Scanner-Version. | `ABSENT` in einer aktiven Sonar-Stanza | `fba49c8cbfd26147706ae15caf4d1d69b450f121`, `_default_sonarqube_stanza`, schrieb aktive Sonar-Konfigurationen noch ohne `scanner_version`. | Nein. |
| 5 | `pipeline.config_version`; `src/agentkit/backend/config/models.py:822` und `:842` (`PipelineConfig._check_config_version`) | `95bb7616be0e27125476e1846dea67d7b9998f12` führte die verpflichtende, einzige Projektschema-Version `3.0` ein. | `ABSENT` | `e5c00724280eee12c9567375563b52ffde14bc19`, `_build_project_yaml`; der Writer ließ das Feld bis einschließlich `9647d993` aus. | Nein. Der Upgrade-Reader verweigert eine erfundene Ausgangsversion ausdrücklich fail-closed. |
| 6 | `pipeline.llm_roles`; `src/agentkit/backend/config/models.py:829` und `:860` (`_validate_multi_llm_requires_llm_roles`) | `95bb7616be0e27125476e1846dea67d7b9998f12` führte `features.multi_llm=true` als Default und die Pflicht-Rollenbelegung gemeinsam ein. | `ABSENT`; bei heutiger Auswertung wird das ebenfalls ausgelassene `features` mit `multi_llm=true` vorbelegt, wodurch die fehlende Rollen-Stanza abgelehnt wird. | `e5c00724280eee12c9567375563b52ffde14bc19`, `_build_project_yaml`; der Writer ließ `features` und `llm_roles` bis einschließlich `9647d993` aus. | Nein. |
| 7 | Cross-Field `pipeline.sonarqube` → `pipeline.ci`; `src/agentkit/backend/config/models.py:1123` (`ProjectConfig._validate_sonarqube_requires_ci`) | `b16fdc47c303e99161d0e826c6b40b600e0ecc95` verlangte für anwendbares Sonar eine verfügbare und aktivierte CI. | `sonarqube.available=true`, `sonarqube.enabled=true` zusammen mit `ci.available=false`, `ci.enabled=false` | `9647d993df3302e85f6c8226c76082df40d49ef4`, `_default_sonarqube_stanza` + `_default_ci_stanza`, exponierte beide damaligen Installerentscheidungen und schrieb diese Kombination. | Nein. |
| 8 | `pipeline.features.vectordb`; `src/agentkit/backend/config/models.py:67` und `:102` (`Features._require_vectordb`) | `8473ae84c465ef97709236a2763fad10dcc23da3` machte VectorDB verpflichtend und lehnte `false` ab. | YAML-Boolean `false` | `ad7c8244862ce2898e81de2568f793f020ddc257`, `_build_project_yaml`, führte `features_vectordb` mit Default `false` als persistierten Wert ein. | **Ja, AG3-226:** exakt `false` wird zu `true`; keine Koercion anderer Werte. |
| 9 | `pipeline.permissions`; heutige Ablehnung über `PipelineConfig.model_config(extra="forbid")` bei `src/agentkit/backend/config/models.py:820`; ehemaliger Owner wurde entfernt. | `0ae0c1186412b92138a22be47bc1ca069e70eb5f` entfernte `PermissionsConfig` und `PipelineConfig.permissions`. | `permissions: {request_ttl_s: 1800}` | `8473ae84c465ef97709236a2763fad10dcc23da3`, `_write_yaml_if_changed` beziehungsweise der CP5-Kandidatendump, materialisierte den seit `cb7e36e3` vorhandenen Modelldefault erstmals produktiv per `candidate.model_dump(..., exclude_none=True)`. | **Ja, AG3-226:** die gesamte obsolete Stanza wird gezielt entfernt. |
| 10 | `pipeline.vectordb.weaviate_http_endpoint`; `src/agentkit/backend/config/models.py:582`, Validator im selben `VectorDbConfig` | `d44c949c1054c5c4cd557ec484cf338ca94a77e2` band die Modellmenge an den Consumer und verbot nichtleeren Pfad, Query, Fragment und Userinfo. | Zum Beispiel `http://weaviate.internal:9903/v1`, `http://weaviate.internal:9903?tenant=a`, `http://weaviate.internal:9903#node` oder `http://user@weaviate.internal:9903`; ein bloßer abschließender `/` bleibt gültig. | `74af1adc8c1c282b3c66b1acf589523c62dbf0ee`, `_build_project_yaml`, schrieb jeden durch das damalige `VectorDbConfig` akzeptierten HTTP(S)-Endpunkt unverändert. | Nein. |
| 11 | `pipeline.vectordb.weaviate_grpc_endpoint`; `src/agentkit/backend/config/models.py:583`, Validator im selben `VectorDbConfig` | `d44c949c1054c5c4cd557ec484cf338ca94a77e2` beschränkte auf einen Consumer-kompatiblen Host mit Port, optional mit `grpc://` oder `grpcs://`. | Zum Beispiel `http://weaviate.internal:50051`, `https://weaviate.internal:50051`, `//weaviate.internal:50051` oder das mehrdeutige `weaviate:internal:50051`; diese bestanden zuvor die bloße Trennung am letzten Doppelpunkt. | `74af1adc8c1c282b3c66b1acf589523c62dbf0ee`, `_build_project_yaml`, schrieb jeden durch den damaligen `VectorDbConfig` akzeptierten gRPC-String unverändert. | Nein. |

## Methode und Reproduzierbarkeit

1. **Historienachse.** Untersucht wurde die von `HEAD` erreichbare produktive
   Historie ab Einführung von `_build_project_yaml` und dem zugehörigen
   `project.yaml`-Write in `e5c00724` unter
   `src/agentkit/project_ops/install/runner.py`. Die Funktionshistorie wurde mit
   `git log -L :_build_project_yaml:<jeweiliger runner.py-Pfad>` über die
   Konsolidierung nach `src/agentkit/installer/runner.py` und die spätere
   Umbenennung nach `src/agentkit/backend/installer/runner.py` verfolgt.
   `ba96f4b3` konsolidierte den bereits vorhandenen Writer, führte ihn aber nicht
   ein und änderte seine Wertausgabe nicht. Semantische Writerrevisionen sind
   `e5c00724`, `9b50b89d`, `fba49c8c`, `9647d993`, `95bb7616`, `ad7c8244`,
   `7593c9d1`, `a73cdfb2`, `74af1adc` und `8473ae84`. Der reine Refactor
   `caa16f12` änderte ebenfalls keinen Wertvertrag. Zwischen `e5c00724` und
   `ba96f4b3` änderte `c36242b3` nur die deployte Verzeichnisstruktur und
   `17131af2` fügte lediglich die Installer-Fassade hinzu; die für diese
   Inventur relevante Writer-Ausgabe blieb unverändert. Der frühere Startpunkt
   ändert die Fallmenge deshalb nicht: Es kommt kein Fall hinzu, es fällt keiner
   weg und kein `ABSENT` wird zu einem geschriebenen Wert.
2. **Writerachse.** Geprüft wurden `_build_project_yaml`,
   `_default_sonarqube_stanza`, `_default_ci_stanza`, CP5
   (`cp_05_pipeline_config`) und die beiden Serialisierungspfade
   `_write_yaml_if_changed` sowie der ab `8473ae84` verwendete validierte
   `ProjectConfig.model_dump(mode="json", exclude_none=True)`. Damit ist auch
   der nicht explizit in `_build_project_yaml` stehende, aber vom Modelldump
   materialisierte `pipeline.permissions`-Default erfasst.
3. **Modellachse.** Die vollständige `ProjectConfig`-Historie wurde mit
   `git log --follow` geprüft. Für die Inventur maßgebliche Modellrevisionen
   sind `9b50b89d` (Project-Key), `fba49c8c` (Sonar), `9647d993` (Scanner und
   CI), `95bb7616` (Projektschema `3.0` und LLM-Rollen), `b16fdc47`
   (Sonar/CI-Cross-Field), `74af1adc` und `d44c949c` (Endpunktmenge),
   `8473ae84` (VectorDB-Pflicht und validierter Modelldump) sowie `0ae0c118`
   (Entfernung der Permissions-Stanza). Vor `95bb7616` waren die Dateien
   unversioniert; seitdem ist die einzige produktiv geschriebene
   `pipeline.config_version` durchgehend `3.0`. Die Konstante
   `PROJECT_CONFIG_VERSION = "1"` im Installer ist ausschließlich die Version
   des Registry-Eintrags und wurde deshalb nicht als `project.yaml`-Modellversion
   fehlklassifiziert.
4. **Vergleich.** Für jede Writerrevision wurden alle durch ihre deklarierten
   `InstallConfig`-Entscheidungen erreichbaren Ausgaben gegen das damalige und
   das heutige Modell verglichen. Bei Booleschen Entscheidungen wurden alle
   produktiv exponierten Kombinationen geprüft; bei frei gesetzten Endpunkten
   wurden die durch den damaligen Validator zugelassenen Äquivalenzklassen
   gegen die heutigen Consumer-gebundenen Validatoren verglichen.
5. **Migrationsachse.** Die registrierten Migrationen und die beiden
   versionsunabhängigen AG3-226-Transformationen in
   `src/agentkit/backend/installer/upgrade/config_migration.py` wurden jedem
   Fall zugeordnet. Nur Fälle 8 und 9 haben derzeit eine Migration.

## Bewusste Ausschlüsse

- Handgeschriebene/operatorseitig veränderte Dateien sowie Beispiele,
  Fixtures und Test-Writer: Sie beweisen keinen von AK3 erzeugten Altzustand.
- Aufrufe, die schon dem damaligen typisierten `InstallConfig`-Vertrag
  widersprachen, und Dateien aus fehlgeschlagenen Teilinstallationen: Ohne
  diese Grenze wäre jede frei typwidrig injizierbare Python-Struktur ein
  angeblicher Writerwert und die Menge prinzipiell unabschließbar.
- Nicht persistierte Modelldefaults vor Einführung des validierten Modelldumps
  in `8473ae84`: Modellbesitz allein ist kein Writernachweis.
- Die alten `pipeline.vectordb.host`-/Port-Felder aus `6a800376`: Der
  produktive `_build_project_yaml` schrieb sie nie; `74af1adc` führte direkt
  die beiden Endpunktfelder ein.
- Weiterhin akzeptierte Änderungen, etwa ein HTTP-Endpunkt mit bloßem
  abschließendem `/`, reine Defaultänderungen und heutige Ablehnung an einer
  Fremdsystemgrenze nach erfolgreichem `ProjectConfig`-Load: Gegenstand ist die
  heutige `project.yaml`-Modellgrenze, nicht jede spätere Laufzeitprüfung.
- Nicht auf `HEAD` gelandete Branch-Zustände. Der in der erreichbaren Historie
  sichtbare WIP-Commit `d7b7dbe7` wurde dennoch gegen seinen gelandeten
  Nachfolger `a73cdfb2` abgeglichen; er fügt keinen weiteren Writerwert hinzu.

## Geschlossenheit und Folgestory

Die Menge ist unter der oben definierten Grenze **geschlossen**: vollständige
erreichbare Historie des produktiven Writers, seiner Hilfswriter, des CP5-
Persistenzpfads und aller `ProjectConfig`-Modellrevisionen ist abgeglichen;
jeder heutige Ablehnungsfall hat entweder einen Writerbeleg in der Tabelle oder
einen begründeten Ausschluss.

In AG3-226 werden gemäß PO-Grenze ausschließlich die bereits aufgenommenen
Fälle 8 (`features.vectordb=false`) und 9 (`pipeline.permissions`) migriert.
Die neun übrigen Fälle sind unverändert und bilden den Umfang der Folgestory.
