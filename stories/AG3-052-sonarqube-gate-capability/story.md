# AG3-052: SonarQube-Green-Gate-Capability (FK-33 §33.6) — commit-gebundene Attestation, Accepted-Ledger-Reconciler, 3-Zustands-Applicability

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:**
- AG3-026 (VerifySystem-Top-Surface + Stage-Registry/Policy-Engine — Andockpunkt der Stage)
- AG3-021 (Kern-Enums: PolicyVerdict / Trust-Klassen / Severity)
- FK-03-Config-Modell (vorhanden) — neue `sonarqube`-Stanza inkl. `available`
**Unblocks:**
- AG3-034 (Dim 9 `SONARQUBE_GREEN` + Setup-green-main-Precondition koennen erst auf dieser Capability aufsetzen)

**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-33 §33.6.3` (SonarQube-Green-Gate normativ: Green-Definition, commit-gebundene Attestation, 3-Punkt-Verankerung, Branch-Plugin)
- `FK-33 §33.6.4` (Accepted-Ledger / Sechs-Augen-Prinzip / deterministischer Single-Match-Reconciler — FK-33 ownt Gate-Semantik + Reconciler-Vertrag; Quorum-Prozess ist Governance-Forward-Ref)
- `FK-33 §33.6.5` (3-Zustands-Applicability-Modell — nach Nachschärfung 2026-06-03 @ce379e6 bereits konzeptuell verankert)
- `FK-33 §33.2.2 / §33.8.3` (`sonarqube_gate`-Stage in der Stage-Registry; Layer-1 deterministisch, Trust A, Abfolge nach Schicht 3)
- `FK-03` (`sonarqube`-Config-Stanza inkl. `available` / `enabled`)
- `FK-50 §50.3 CP 10d` (Installer-Vorbedingung, applicability-konditional)
- `FK-10 §10.2.2` (Laufzeit-Abhaengigkeit, `available`-qualifiziert)
- `DK-04 §4` (Mehrstufige QS / Trust-Klassen)
- `formal.deterministic-checks.*` (entities/commands/events/invariants/state-machine/scenarios — inkl. der 2026-06-03 ergaenzten Applicability-/NOT_APPLICABLE-Invarianten)

---

## 1. Kontext

Das SonarQube-Green-Gate ist laut FK-33 §33.6.3 die normative, deterministische
Layer-1-Capability "SonarQube gruen?" (Trust-Klasse A, blocking), die an drei
Lifecycle-Punkten gebraucht wird (Setup-Vorbedingung FK-22 §22.4c, QA-Subflow
§27.6a nach Schicht 3, Closure-Pre-Merge FK-29 §29.1a / Integrity-Gate FK-35
§35.2.4a Dim 9). **Sie ist heute im Code NICHT implementiert** (kein
`sonarqube_gate`, keine commit-gebundene Attestation, kein `integrations/sonar`-
Adapter, kein `sonarqube.available`-Config). Das QA-Subflow-/Policy-Engine-/
Stage-Registry-Fundament (`verify_system/`, `verify_system/policy_engine/`) sowie
das FK-03-Config-Modell existieren.

Diese Story baut die **Capability** (Adapter + Attestation + Ledger-Reconciler +
Applicability-Aufloesung + Config + Installer-Check) und dockt sie an **EINEM**
Lifecycle-Punkt an: dem **QA-Subflow** (FK-33-eigener Andockpunkt, Punkt 2). Die
beiden anderen Andockpunkte sind **Konsumenten**: die Setup-green-main-Precondition
(FK-22) und der Closure-Pre-Merge-Scan/Dim 9 (FK-29/FK-35) werden von **AG3-034**
(das nach dieser Story wiederaufgenommen wird) bzw. der Closure-Story verdrahtet —
sie rufen die hier gebaute Capability-API auf. So bleibt der Schnitt sauber:
**AG3-052 = Capability + QA-Subflow-Stage**; Setup/Closure-Call-Sites = Folge.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 SonarQube-Adapter (`integrations/sonar/`) — duenner, fail-closed Client
- Thin Adapter ueber die SonarQube-Web-API: Lese-Operationen `qualitygates/project_status` (per `analysisId`/`ceTaskId`), `ce/task` (Analyse-Status), `project_analyses`/`navigation/component` fuer `sonar_last_analyzed_revision`, `issues/search` (offene, nicht-akzeptierte Issues fuer die Overall-Code-Invariant), und die `Administer Issues`-Operation `issues/do_transition`/`issues/set_tags` fuer den Reconciler (scoped Token).
- KEINE Fachlogik im Adapter (CLAUDE.md: integrations = duenne Adapter). Auth/Token aus der FK-03-Config; Erreichbarkeit/Version/Branch-Plugin werden fail-closed behandelt.
- Trennung "konfiguriert-aber-unerreichbar/rot" (fail-closed) vs "nicht verfuegbar deklariert" (NOT_APPLICABLE) — der Adapter meldet Erreichbarkeit; die Applicability-Entscheidung trifft die Capability (2.1.4), NICHT der Adapter.

#### 2.1.2 Commit-gebundene Attestation (FK-33 §33.6.3)
- `SonarAttestation`-Modell (Pydantic, ArtifactEnvelope-konform wo zutreffend) — **Feldset 1:1 gemaess `formal.deterministic-checks.entities.sonar-attestation` (identity_key `analysis_id`), exakte Attributnamen:** `analysis_id`, `ce_task_id`, `quality_gate_status`, `quality_gate_hash`, `quality_profile_hash`, `analysis_scope_hash`, `new_code_definition`, `exception_ledger_hash`, `last_analyzed_revision`, `sonarqube_version`, `branch_plugin_version`, `scanner_version`, `status` — plus die `commit_sha`/`tree_hash`-Bindung aus FK-33 §33.6.3. (Worker prueft die Attributliste 1:1 gegen die formale Entity; fehlt/weicht ein Feld ab → fail-closed.)
- **`config_hash` (FK-03 Config-Hash, Drift)** ist KEIN Attestation-Feld, sondern eine aus `quality_gate_hash` + `quality_profile_hash` + den drei Versionen **abgeleitete** Groesse fuer die Drift-Erkennung; sie wird hier gebildet/gebunden, die Verwaltung der *registrierten Erwartung* ist out-of-scope (§2.2). `overall_zero_violations` ist KEIN Attestation-Feld, sondern das **Green-Kriterium** (Invariante, naechster Punkt).
- **Green-Definition (Broken-Window / Overall-Code-Invariant):** gruen ⇔ Quality Gate OK **UND** Zero-Violations-overall (keine offenen nicht-akzeptierten Issues im gesamten Scope, nicht nur New Code). AK liest den Gate-Status + die Overall-Condition; AK interpretiert KEINE Einzelregeln (Toleranzen liegen ausschliesslich im Sonar-Quality-Gate-Profil).
- **Kein Live-Read:** das Gate bindet sich an die konkrete Analyse (Scanner mit `sonar.qualitygate.wait=true`, QG per `analysisId`/`ceTaskId`), nicht an "ist `projectKey` gerade gruen?". Stale-Reads ausgeschlossen (Attestation gilt nur fuer `commit_sha`/`tree_hash`).

#### 2.1.3 Accepted-Ledger + deterministischer Single-Match-Reconciler (FK-33 §33.6.4)
- **Ledger-Artefakt** als versioniertes Repo-Artefakt mit robuster Identitaet: Eintrag fuehrt mindestens `rule_key`, `file_path`, `normalized_code_fingerprint`, `expected_message_pattern`, semantische Begruendung, `approved_by[3]`, `approved_commit`, `expiry`/`review_after`, `scope` (`branch-only` | `main-eligible`). Speicher-/Ablageort + Schema nach FK-71-Envelope-Disziplin.
- **Deterministischer Reconciler (Single-Match, fail-closed):** wendet eine Ausnahme **nur an, wenn genau EIN** aktuelles Sonar-Issue auf den Eintrag matcht (Match ueber `rule_key` + `normalized_code_fingerprint` + `expected_message_pattern`, NICHT ueber instabile `issueKey`/Zeilennummer). Bei **0 oder >1** Matches → fail-closed. Reconciler laeuft als **deterministischer Pipeline-Schritt** mit scoped `Administer Issues`-Token; Worker/Agent haben KEINE Issue-Admin-Rechte.
- Reconciler wird auf den finalen Branch-Scan angewandt; der Ledger-Hash ist Teil der Attestation (2.1.2). (Post-Merge-Reconcile gegen `main` ist Closure-seitig, FK-29 — hier nur die Reconciler-Capability + der Branch-Scan-Aufruf; siehe Out-of-Scope.)

#### 2.1.4 3-Zustands-Applicability-Aufloesung (FK-33 §33.6.5)
- Eine `resolve_applicability(...)`-Funktion (FK-33 ist Owner) liefert `APPLICABLE` | `NOT_APPLICABLE_UNAVAILABLE` | `NOT_APPLICABLE_FAST`:
  - APPLICABLE ⇔ `sonarqube.available == true` (FK-03) **UND** `mode != fast` **UND** `story_type ∈ {implementation, bugfix}`.
  - NOT_APPLICABLE_UNAVAILABLE ⇔ `sonarqube.available == false` → Stage SKIP (kein fail-closed).
  - NOT_APPLICABLE_FAST ⇔ `mode == fast` → Stage entfaellt (Closure nutzt Sanity-Gate; nicht hier).
- **Airtight:** bewusst-abwesend (`available:false` → SKIP) vs konfiguriert-aber-rot/stale/unerreichbar (`available:true` → fail-closed). Niemals fail-open.

#### 2.1.5 QA-Subflow-Stage-Integration (FK-33 §33.2.2 / §33.8.3, Punkt 2)
- Registrierung der `sonarqube_gate`-Stage in der Stage-Registry: Layer-1 deterministisch, Trust-Klasse A (blocking), Abfolge **nach Schicht 3**, Story-Typ-Geltung `implementation`/`bugfix`. Konkret wird der Andockpunkt im bestehenden AG3-026-Fundament verdrahtet — entweder durch Erweiterung des layer-basierten `select_layers`/Routing-Pfads (`verify_system/routing.py`, `system.py`) oder durch Materialisierung des `StageExecutionPlan` aus der Stage-Registry (§33.2); der Worker waehlt den konzepttreuen Weg und belegt ihn.
- Andockung an den Policy-Engine-/Schicht-Sequenz-Pfad gemaess der nachgeschaerften deterministic-checks-State-Machine: APPLICABLE → `read-attestation` → `run-sonarqube-gate` (gruen → `sonarqube_gate_passed`; rot/stale/unerreichbar → fail-closed `failed` **direkt**, nicht ueber Policy); NOT_APPLICABLE_UNAVAILABLE → `sonarqube_gate_not_applicable` → Policy laeuft weiter; `mode==fast` → Stage entfaellt (Tests-gruen-Floor). KEIN fail-open.
- **Reconciler-Verdrahtung (verbindlich):** im APPLICABLE-Branch-Scan wird der Accepted-Ledger-Reconciler (2.1.3) auf **genau den finalen Branch-Scan angewandt, BEVOR** das Gruen/Rot-Verdikt feststeht; 0/>1-Match failt fail-closed **vor** der Policy. (Reconciler darf nicht nur isoliert existieren — er muss im Stage-Pfad aufgerufen werden; siehe AC4.)
- Branch-Vermessung setzt das Community Branch Plugin voraus (harte Umgebungsabhaengigkeit, deklariert in 2.1.6); fehlt/inaktiv das Plugin auf einem `available:true`-Server, manifestiert sich das als API-Fehler → fail-closed (konfiguriert-aber-unerreichbar).

#### 2.1.6 Config (FK-03) + Installer-Checkpoint (FK-50)
- FK-03 `sonarqube`-Stanza ist KONZEPTUELL vorhanden (Nachschärfung @ce379e6); das **Code-Config-Modell existiert noch nicht** und wird hier gebaut: `SonarQubeConfig` (frozen, `extra="forbid"`, in `PipelineConfig`) mit `available`/`enabled`/`base_url`/`token_env`/`min_version`/`plugins.community_branch.min_version`/`quality_gate.default_profile`. Validierung exakt gemaess FK-03 §3 (SonarQubeConfig): `available==true AND enabled==true AND fehlende base_url/token_env → ValueError`; **Cross-Field-Regel wortgetreu zu FK-03:** ein Projekt mit codeproduzierenden Stories + `available:true` + `enabled:false` → `ValueError` (unzulaessig); `available:false` ist auch fuer codeproduzierende Projekte zulaessig (kein ValueError, Gate NOT_APPLICABLE); reine concept/research-Projekte duerfen ohnehin `enabled:false`/`available:false` setzen.
- FK-50 CP 10d — Installer-Checkpoint applicability-konditional. **In-Scope hier: die Vorbedingungs-Pruefungen** — bei `available:false` → `SKIPPED`/`reason="not_applicable"` (NICHT FAILED); bei `available:true` fail-closed: (a) Erreichbarkeit + `min_version`, (b) Token-Rolle inkl. **`Administer Issues`** (fuer den Reconciler), (c) **Branch-Plugin vorhanden + Branch-Plugin-Conformance-Self-Test** auf einem Wegwerf-Mini-Projekt (Plugin wirklich funktionsfaehig, nicht nur installiert). Default-Quality-Gate-Profil als ausgeliefertes Artefakt unter `resources/target_project/` (SSOT; Pfad-Existenz im Installer-Verify). **NICHT hier:** die CP10d-Config-Drift-Behandlung gegen die registrierte CP7-Erwartung (out-of-scope, §2.2 — Owner Installer/AG3-039); diese Story bildet/bindet nur den abgeleiteten `config_hash`.

#### 2.1.7 Tests
- Unit: Green-Definition (QG-OK + Overall-Zero vs nur New-Code), Attestation-Bindung (stale-commit → ungueltig), Reconciler Single-Match/0-Match/Multi-Match (fail-closed), Applicability-Aufloesung (alle 3 Zustaende + absent≠unreachable), Config-Cross-Field-Regel.
- Integration: QA-Subflow-Stage end-to-end gegen einen **gestubbten** Sonar-Client (echte Capability-/Reconciler-Logik, nur die externe HTTP-Grenze gestubbt — MOCKS-Ausnahme: externes System im Unit-Test nicht verfuegbar) — APPLICABLE-gruen → passed; rot → failed; available:false → SKIP→Policy; fast → Stage entfaellt.
- Contract: `sonarqube_gate`-Stage-Registry-Eintrag (Layer/Trust/Abfolge/Story-Typ) + Attestation-/Ledger-Schema-Pinning + formal.deterministic-checks-Konformitaet.

### 2.2 Out of Scope (bewusst, mit Owner)
- **Setup-green-main-Precondition-Call-Site (FK-22 §22.4c)** und **Closure-Pre-Merge-Scan + Dim 9 (FK-29 §29.1a / FK-35 §35.2.4a)** — Konsumenten der hier gebauten Capability; verdrahtet in **AG3-034** (Wiederaufnahme) bzw. der Closure-Story. AG3-052 stellt nur die aufrufbare Capability-API + den QA-Subflow-Andockpunkt.
- **Post-Merge-Reconcile gegen `main` + Merge-Serialisierungs-Lock** — Closure-Orchestrierung (FK-29 §29.1a). Hier nur die Reconciler-Capability + Branch-Scan.
- **Sechs-Augen-Quorum-PROZESS** (welche QS-Agents, wie das Quorum erhoben/gegen das Repo-Artefakt durchgesetzt wird, Exception-Budget-Eskalation) — Governance-Forward-Ref (FK-33 §33.6.4 explizit offen). AG3-052 baut das Ledger-Artefakt + den deterministischen Reconciler-Vertrag + die `approved_by[3]`-Pflichtfelder; die Quorum-ERHEBUNG ist Folge-Story.
- **Remediation-Loop-Mechanik (FK-27)** und der **Cleanup-Remediation-Worker** (rot main → scope-fremder Aufraeum-Worker) — eigene/bestehende Owner; hier nur das fail-closed-Verdikt, das sie ausloest.
- **Config-Drift-Detektion gegen registrierte Erwartung (FK-50 CP10d / FK-03 Config-Hash gegen CP7):** AG3-052 bildet/bindet nur den aus den Attestation-Bestandteilen (`quality_gate_hash` + `quality_profile_hash` + den drei Versionen) **abgeleiteten** `config_hash`; `config_hash` ist KEIN `SonarAttestation`-Feld (siehe 2.1.2). Der WORKFLOW "Profil-Aenderung erfordert vollen `main`-Rescan vor Erwartungs-Update", der gegen die in CP7/`project_registry` registrierte Config-Hash-Erwartung prueft, ist out-of-scope — Owner: Installer/CP7 (AG3-039 `project_registry`, derzeit `ready`). AG3-052 fuehrt KEINE Abhaengigkeit auf AG3-039 ein, weil es nur den Hash bildet/bindet, nicht die registrierte Erwartung verwaltet.
- **Security-/SCA-/Secret-/Lizenz-/Container-Scans** — eigene Layer-1-Checks (FK-33 §33.3.2), NICHT dieses Gate (Scope-Ehrlichkeit).
- **Live-SonarQube-Server-Provisionierung** — Betriebs-/Installer-Thema; Tests laufen gegen den gestubbten Client.

## 3. Betroffene Dateien (Richtwert)
| Datei | Art | Beschreibung |
|---|---|---|
| `src/agentkit/integrations/sonar/__init__.py` + `client.py` | Neu | Duenner SonarQube-Web-API-Adapter (read + reconcile-transition), fail-closed |
| `src/agentkit/verify_system/sonarqube_gate/` (`__init__.py`, `attestation.py`, `gate.py`, `applicability.py`, `ledger.py`, `reconciler.py`) | Neu | Capability: Attestation, Green-Def, Applicability, Accepted-Ledger, Single-Match-Reconciler |
| `src/agentkit/verify_system/policy_engine/` bzw. Stage-Registry | Modifiziert | `sonarqube_gate`-Stage registrieren (Layer 1 / Trust A / Abfolge nach Schicht 3) |
| `src/agentkit/core_types/` (Config) + FK-03-Config-Modell | Modifiziert | `sonarqube`-Stanza (`available`/`enabled`/url/token-ref/min-version/branch-plugin) + Cross-Field-Regel |
| `src/agentkit/.../installer` (CP 10d) | Modifiziert | Applicability-konditionaler Sonar-Checkpoint (SKIPPED vs FAILED) |
| `src/agentkit/resources/target_project/` | Neu | Default-Quality-Gate-Profil-Artefakt (SSOT) |
| `tests/unit/verify_system/sonarqube_gate/*` | Neu | Green-Def, Attestation, Reconciler, Applicability, Config |
| `tests/integration/verify_system/test_sonarqube_gate_subflow.py` | Neu | QA-Subflow-Stage gegen gestubbten Client |
| `tests/contract/verify_system/test_sonarqube_gate_stage.py` | Neu | Stage-Registry-/Attestation-/Ledger-Schema-Pinning + formal.deterministic-checks |

## 4. Akzeptanzkriterien
1. **Green-Definition** = Quality-Gate-OK **UND** Overall-Zero-Violations (nicht nur New-Code); AK interpretiert keine Einzelregeln. Test belegt: QG-OK aber Overall-Issues → rot.
2. **Commit-gebundene Attestation**: Das `SonarAttestation`-Modell traegt das Feldset **1:1 mit den exakten Attributnamen von `formal.deterministic-checks.entities.sonar-attestation`** (`analysis_id`, `ce_task_id`, `quality_gate_status`, `quality_gate_hash`, `quality_profile_hash`, `analysis_scope_hash`, `new_code_definition`, `exception_ledger_hash`, `last_analyzed_revision`, `sonarqube_version`, `branch_plugin_version`, `scanner_version`, `status`) plus `commit_sha`/`tree_hash`-Bindung (FK-33 §33.6.3); ein gruener Status fuer einen veralteten Commit (`last_analyzed_revision != main HEAD`) ist ungueltig. Kein Live-`projectKey`-Read. Contract-Test pinnt die Attributliste 1:1 gegen die formale Entity (kein erfundenes/umbenanntes Feld).
3. **Accepted-Ledger** mit den FK-33-§33.6.4-Pflichtfeldern (inkl. `normalized_code_fingerprint`, `approved_by[3]`, `scope`); `exception_ledger_hash` ist Teil der Attestation (AC2).
4. **Reconciler Single-Match fail-closed + verdrahtet**: genau 1 Match → angewandt; 0 oder >1 → fail-closed (Unit-Test je Fall). Match ueber stabile Identitaet (`rule_key`+`normalized_code_fingerprint`+`expected_message_pattern`), nicht `issueKey`/Zeile. Worker hat keine Issue-Admin-Rechte (scoped Token im deterministischen Schritt). **Integration-Test belegt die VERDRAHTUNG:** im APPLICABLE-Branch-Scan wird der Reconciler aufgerufen, BEVOR das Gruen/Rot-Verdikt feststeht, und ein 0/>1-Match failt fail-closed VOR der Policy-Aggregation (nicht nur isolierte Reconciler-Unit).
5. **3-Zustands-Applicability** korrekt + airtight: APPLICABLE / NOT_APPLICABLE_UNAVAILABLE (SKIP) / NOT_APPLICABLE_FAST (Stage entfaellt); konfiguriert-aber-unerreichbar/rot → fail-closed (niemals als SKIP). Test je Zustand + der absent≠unreachable-Fall.
6. **QA-Subflow-Stage** registriert (Layer 1 / Trust A / Abfolge nach Schicht 3 / `impl`+`bugfix`) und im Schicht-Sequenz-Pfad konform zur nachgeschaerften `formal.deterministic-checks`-State-Machine (APPLICABLE → read-attestation → run-sonarqube-gate → gruen=passed/rot=failed-direkt; available:false → not_applicable → policy; fast → entfaellt). Kein fail-open.
7. **Config (FK-03)** exakt validiert (Cross-Field-Regel wortgetreu) + **Installer-CP (FK-50 CP10d) Vorbedingungs-Teil** (Config-Drift-gegen-CP7-Erwartung ist OOS §2.2): `available:false` → CP SKIPPED/`reason="not_applicable"` (nicht FAILED); `available:true` fail-closed → (a) Erreichbarkeit+min_version, (b) Token-Rolle inkl. `Administer Issues`, (c) Branch-Plugin vorhanden **+ Conformance-Self-Test** auf Wegwerf-Mini-Projekt. Default-QG-Profil ausgeliefert. Tests belegen SKIPPED-vs-FAILED je Fall + den Self-Test.
8. **Capability-API** ist so geschnitten, dass AG3-034 (Dim 9, green-main) + die Closure-Story sie an Punkt 1 + 3 aufrufen koennen, ohne diese Story zu beruehren (klarer Vertrag, dokumentiert).
9. **Architecture-Conformance** (AK10-analog): Adapter duenn (`integrations/sonar` ohne Fachlogik), Capability in `verify_system`, keine zweite Wahrheit; ggf. `entities.md`-Registrierung der neuen Module.
10. **Pflichtbefehle gruen**: pytest unit+integration+contract; mypy default + `--platform linux`; ruff; Coverage ≥ 85%; LOC-Linter (`scripts/python/py_loc_to_sonar.py` — der projekteigene Python-LOC-zu-Sonar-Reporter, orthogonal zum hier gebauten `sonarqube_gate`) 0 Issues; vier CI-Konzept-Gates gruen.

## 5. Definition of Done
- AK 1-10 erfuellt; `.venv\Scripts\python -m pytest` gruen; mypy/ruff gruen; Konzept-Gates + LOC-Linter gruen.
- giftige Codex-Review (+ ggf. Grok) → PASS; Jenkins SUCCESS; Sonar Quality Gate OK.
- Aenderungen committed auf `main`; AG3-034 als unblockt vermerkt (Dim 9 + green-main koennen aufsetzen).

## 6. Konzept-Referenzen (autoritativ)
- **FK-33 §33.6.3** — Green-Definition, commit-gebundene Attestation, 3-Punkt-Verankerung, Branch-Plugin
- **FK-33 §33.6.4** — Accepted-Ledger / Sechs-Augen / Single-Match-Reconciler-Vertrag
- **FK-33 §33.6.5** — 3-Zustands-Applicability (Owner)
- **FK-33 §33.2.2 / §33.8.3** — Stage-Registry-Eintrag / Layer-vs-Abfolge
- **FK-03 / FK-50 §50.3 / FK-10 §10.2.2** — Config / Installer / Laufzeit-Abhaengigkeit (applicability-konditional)
- **DK-04** — Mehrstufige QS / Trust-Klassen
- **formal.deterministic-checks.*** — inkl. der 2026-06-03 ergaenzten Applicability-Invarianten/State-Machine

## 7. Guardrail-Referenzen
- **FAIL CLOSED**: konfiguriert-aber-unerreichbar/rot/stale → BLOCK; 0/>1 Ledger-Match → BLOCK. `available:false` ist KEIN fail-open, sondern deklarierte Nicht-Anwendbarkeit.
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH**: Toleranzen NUR im Sonar-QG-Profil, nicht im AK-Code; Ledger als EIN versioniertes Artefakt mit robuster Identitaet; Default-QG-Profil als SSOT-Artefakt.
- **MOCKS NUR IM AUSNAHMEFALL**: nur die externe SonarQube-HTTP-Grenze im Test gestubbt; Capability-/Reconciler-/Applicability-Logik echt getestet.
- **integrations = duenne Adapter**: keine Fachlogik in `integrations/sonar`.

## 8. Hinweise fuer den Sub-Agent
- Echtes SonarQube ist im Unit-/Integrationstest NICHT verfuegbar — gegen einen gestubbten Client testen; KEINE Live-Server-Abhaengigkeit in CI.
- Issue-Identitaet in SonarQube ist instabil — Reconciler MUSS ueber `rule_key` + `normalized_code_fingerprint` + `expected_message_pattern` matchen, nicht ueber `issueKey`/Zeilennummer.
- Die 3-Zustands-Applicability ist bereits konzeptuell verankert (FK-33 §33.6.5, @ce379e6) — exakt dieses Modell implementieren; absent≠unreachable airtight halten.
- Setup/Closure-Call-Sites NICHT hier verdrahten (Out-of-Scope) — nur die Capability-API bereitstellen.
- AK2 NICHT veraendern.
