# Bearbeitungs-Reihenfolge (Welle 2026-05-19+)

**Zweck**: Konkrete Bearbeitungsreihenfolge fuer die offenen Stories, die
sich aus dem topologischen `depends_on`-Graph in
`_story-schnitt-aus-themen.md §2` + den Stefan-Entscheidungen
vom 2026-05-19 ergibt.

Diese Datei ist *operative Arbeitsliste*. Sie wird nach jeder abgenommenen
Story aktualisiert (Status `done`/`completed`). Bei neuen User-Entscheidungen
(z. B. Splits, Vollumsetzungen) werden Reihenfolge **und** Begruendung hier
eingetragen — das Kontextgedaechtnis des Orchestrators ist KEINE persistente
Wahrheit.

---

## 1. Reihenfolge der aktuellen Welle

| # | Story | Groesse | Status | Vorbedingung erfuellt? |
|---|---|---|---|---|
| 1 | AG3-026 VerifySystem Top-Surface | M | done (2026-05-23, Pass-4 + Codex-PASS) | ja (AG3-021/022/023 done) |
| 2 | AG3-029 KpiAnalytics Top + Paket-Migration | M | done (2026-05-23, Pass-4 + Codex-PASS) | ja |
| 3 | AG3-030 RequirementsCoverage Top + AreClient | M | done (2026-05-23, Pass-2 + Sonar gruen erwartet) | ja |
| 4 | AG3-027 Skills Top-Surface (schlank) | M | done (2026-05-24, Pass-2.2 + Sonar gruen) | ja |
| 5 | AG3-031 Governance Top-Surfaces | M | done (2026-05-25, Pass-7 + 4x Codex-giftig; Codex-Adapter -> AG3-049) | ja |
| 6 | AG3-035 ProjectionAccessor + Reset-Purge | M | done (2026-06-01; LightWild 2c0eefb -> giftiger Codex-Recheck-r2 = BLOCK auf #6 (BC-Drift lebte + irrefuehrender Test) + #3. Echter Fix 80ae0ce: StoryContextQueryPort-Injection + Owner-Vertrag (ProjectionKindNotAccessorOwnedError); Sonar-Fix d838de1 (S1192/S1172). Final gruen im kumulativen HEAD 14df2eb: Jenkins #18 SUCCESS, Sonar Quality Gate OK (0 new/critical violations)) | ja |
| 7 | AG3-040 Postgres-Store-Komplettierung | M | Sub-Block (a) done+abgenommen (2026-06-01, kumulativ @01421c7: Jenkins #24 SUCCESS, Sonar OK; project_management Postgres/Wire/project_detail-Views + Counters auf vereinheitlichter Identitaet). Sub-Block (b): die fuer den Empfaenger-Vertrag noetige fc-Tabelle **`fc_incidents` ist mit AG3-028 (@8c3a24f) geliefert** (Schema+Repo+Accessor+Reset-Purge, FK-41 §41.3.1 / FK-69). `fc_patterns`/`fc_check_proposals` entstehen mit ihren Producern (PatternPromotion/CheckFactory, Folgestories). AG3-040.status.yaml bleibt in_progress, bis diese beiden fc-Tabellen + ihre Reset-Recompute/Unberuehrtheit (FK-69 §69.9) gebaut sind. |
| 7a | AG3-050 Story-Identity-Unifizierung | M | done (2026-06-01; Stefan-Vorgabe; Codex r1 BLOCK -> r2 PASS-MIT-WARNINGS; @01421c7 Jenkins #24 SUCCESS, Sonar OK. WARNING N1: Postgres-Concurrency-Allokation unbewiesen -> Folge, getrackt) |
| 8 | AG3-028 FailureCorpus (Vollumsetzung) | L | **done (2026-06-01 @8c3a24f: Jenkins #32 SUCCESS, Sonar Gate OK — new_coverage 84.7, 0 new/critical violations; giftige Codex r1–r7 -> PASS-MIT-WARNINGS).** Geliefert: FailureCorpus-Top-Surface (record_incident funktional, 5 NotImplementedError-Slots), IncidentTriage (DK-07 §7.3.6 reines OR), fc_incidents (FK-41 §41.3.1; global eindeutige FC-YYYY-NNNN via globalem Per-Jahr-Counter; project_key-gebunden; evidence/tags=list[str] DB-erzwungen Postgres+SQLite) accessor-owned (KONFLIKT-2), drei entitaets-scoped Lifecycle-Enums (KONFLIKT-1, nur IncidentStatus materialisiert), fc_incidents Reset-Purge + DRIFT-AG3-028-Marker aufgeloest. SCHEMA_VERSION -> 3.13.0. WARNING (getrackt): Postgres-Concurrency der FC-YYYY-NNNN-Allokation nicht lokal beweisbar (analog AG3-050 N1). | nach AG3-035 + AG3-040 |
| 9 | AG3-048 Skills-Persistenz + Installer + Hygiene | M | blocked | nach AG3-027 |
| 10 | AG3-049 Codex-Harness-Adapter (CodexSettingsWriter Vollausbau) | M | **done (2026-06-01 @93662c4: Jenkins #36 SUCCESS, Sonar Gate OK; Codex-Plan-Segen + giftige r1–r3 -> PASS).** CodexSettingsWriter produktiv: Command-Remap claude->codex mit Phase/Hook-ID-Validierung (validate_hook_selector), tokenweises Tool-Matcher-Mapping (Bash/apply_patch/`^mcp__.*_send$`, nicht-repraesentierbare Tokens entfallen mit Diagnose, unbekannt->ERROR), `.codex/hooks.json` dreistufig, Merge-Identitaet Event+Matcher+Command konsistent zum Claude-Writer (d93c0ee), fail-closed bei kaputter/malformed Shape, Fremd-Hooks verbatim erhalten. Trust-Layer-Grenze als AK6 dokumentiert (Aktivierung = FK-50-Folge). | nach AG3-031 (Codex-Adapter-Stub aus AG3-031 ausgelagert) |

**Anmerkung 1 (Zyklus-Vermeidung AG3-028 / AG3-040):** Der topologische Graph
zeigt einen scheinbaren Zyklus: AG3-040 deklariert `depends_on: AG3-028`
(weil es die `fc_`-Tabellen mitnimmt), AG3-028 deklariert nach
User-Entscheidung 2026-05-19 jetzt `depends_on: AG3-040`. Aufloesung in der
Praxis: AG3-040 wird in zwei Sub-Bloecken umgesetzt — (a) `Postgres-Store-
Komplettierung ohne fc_-Tabellen` zuerst (befriedigt AG3-028-Dep), (b)
`fc_-Tabellen-Block` als Teil von AG3-028 selbst (dort liegt der
Schema-Owner laut FK-69). Der Worker fuer AG3-040 muss diesen Schnitt
respektieren; der `depends_on: AG3-028` in AG3-040.status.yaml verweist
nur auf den `fc_-Tabellen`-Block, der mit AG3-028 zusammenfaellt.

**Anmerkung 2 (Foundation-Welle AG3-021..025, Status-Pflege 2026-05-31):**
AG3-023 (ArtifactManager L), AG3-024 (PhaseEnvelope M) und AG3-025
(AttemptRecord M) gehoeren zur fruehen Foundation-Welle (um AG3-021/022),
nicht zur hier gelisteten Welle 2026-05-19+. Sie waren faktisch
implementiert, mehrfach re-reviewed und auf `main` (letzte Impact-Commits
d11069e / 8631804 / 7e94165), aber ihre `status.yaml` stand faelschlich
auf `in_progress/setup` (Abnahme-Flip nie vollzogen). Am 2026-05-31 von
Stefan abgenommen und auf `completed/closure` gesetzt. AG3-026 (depends_on
AG3-023, bereits `completed`) belegt die produktive Nutzung des
ArtifactManager. Lehre: Abnahme = User-OK + status-Flip + Listenpflege in
einem Schritt, sonst entsteht genau dieser Drift.

**Anmerkung 3 (AG3-015 Prompt-Runtime, abgenommen 2026-06-01):**
AG3-015 (Prompt-Runtime FK-44-Completion, ausserhalb der Welle-2-Tabelle, war
`ready`) ist `completed`. Die Story wurde von Greenfield auf "Completion des
existierenden prompt_runtime" realignt (W6-Migration-Altbestand). Giftige
Codex-Reviews im Ping-Pong: r1 BLOCK (E1-E5) -> Remediation 4731e18; r2 BLOCK
(neuer N1: verify re-pin bricht C2 nach Rebind) -> Remediation 2fc1309; r3
PASS-MIT-WARNINGS (BLOCK aufgehoben). Final gruen im kumulativen HEAD 14df2eb
(Jenkins #18 SUCCESS, Sonar OK, 2639+ Tests). **Offene Folge W1** (owner-
zugeordnet, NICHT AG3-015): kein produktiver Run-Start-Pinner in der Pipeline
(Pin entsteht lazy beim ersten Verify-Audit) -> Setup-/Pipeline-Engine-
Folgeschnitt, offene Stefan-Entscheidung (siehe AG3-015 story.md "Offene
Folge"). Zusaetzlich: 5 e2e-Tests (Story-Seeding nach AG3-031-Preflight-Gate)
gefixt (commit 8d06d43).

**Anmerkung 4 (AG3-050 Story-Identity-Unifizierung, Stefan-Vorgabe 2026-06-01):**
Aus der AG3-040(a)-Feasibility + giftigem Codex-Recheck (W-DISPLAYID) entstanden:
dedizierte Story AG3-050. Drei Vorgaben: (A) StoryDependency-Kante/FK auf die
statische `stories`-Identitaet statt `story_contexts`; (B) Display-ID = reine
Anzeige-Formatierung (min-3 `:03d`) ueber EINE zentrale Formatter-Funktion,
Storage `story_number` (int), Sortierung numerisch; (C) genau EIN BC + EINE Klasse
als ID/Nummer-Quelle, toter `lifecycle.create_story`-Pfad raus. Beruehrt formal-spec
(FK-02/FK-18). **AG3-040(a)** (lokal committed `530c40c`, NICHT gepusht) bleibt
in_progress und wird nach AG3-050 abgenommen (Landmine entfernt). Reihenfolge:
AG3-050 -> AG3-040(a)-Abnahme -> dann AG3-028/Welle.

**Anmerkung 5 (AG3-032 Principal-Capability-Modell, THEME-006, abgenommen 2026-06-03):**
AG3-032 (FK-55 Principal/PathClass/OperationClass + harte Matrix + Conflict-Freeze-
Overlay, Enforcement vor CCAG) ist `completed` (@e1a411a: Jenkins #74 SUCCESS, Sonar
Quality Gate OK — violations/critical/blocker/open_hotspots = 0). **Konzeptkorrektur
mitgeliefert** (Stefan-Abnahme): FK-55 §55.1a (Durchsetzungsgrenzen, Schutzschichten,
Runner-Boundary-Class) + FK-30 §30.1/Glossar nachgeschaerft. Ehrliche Scope-Ziehung:
der Hook ist **Schicht A = Stufe 1+2** (direkte, klassifizierbare Tool-Ops, hart &
nicht umgehbar); **Stufe 3** (Obfuskation/beliebige Codeausfuehrung) ist explizit
**out-of-scope** — auf nativem Windows gibt es kein unprivilegiertes Per-Tool-Call-FS-
Containment (Kernel-FS-Sandbox/Landlock waere Schicht B, nur in Linux-/WSL2-Runner;
NICHT gebaut). Stufe-3-Schutz ruht auf Broker-Wahrheit + Akzeptanz-Gate. giftige Codex
r1 (8 ERROR -> remediation), r2 (B/C/D/E PASS + binding_invalid fail-open CONFIRMED ->
remediation), r3 PASS (fail-open geschlossen). LLM-Hub-Diskussion (5 Backends) lieferte
die Runner-Boundary-Class-Idee. **Folge:** AG3-033 (Self-Protection/Story-Creation-Guard)
und AG3-034 (Preflight 2/5-10 + IntegrityGate-8-Dim) sind damit unblockt (depends_on
AG3-032 erfuellt). **WICHTIG fuer AG3-033/034-Worker:** AG3-032 lieferte NICHT die in
deren story.md angenommenen Typnamen — real gilt PathClass `governance_plane`/
`git_internal`, OperationClass `write`/`execute`, 9 Principals (`pipeline_deterministic`/
`admin_service`/`human_cli` statt INSTALLER/RECOVERY), Freeze-Pfad-Konstante
`GOVERNANCE_FREEZE_EXPORT_*` in `core_types`. Gegen das gelieferte Modell implementieren,
nicht gegen die story.md-Code-Skizzen (Akzeptanzkriterien-Intent bleibt gueltig).

**Anmerkung 6 (AG3-033 Self-Protection-/Story-Creation-Guard, THEME-006, abgenommen 2026-06-03):**
AG3-033 (FK-30 §30.5.4 SelfProtectionGuard + FK-31 §31.5 / FK-21 §21.13
StoryCreationGuard als eigenstaendige Module, differenzierter Hook-Dispatch) ist
`completed` (@d784629: Jenkins #77 SUCCESS, Sonar Quality Gate OK —
violations/critical/new_violations/new_critical/open_hotspots = 0). Implementiert
gegen das real gelieferte AG3-032-Modell (story.md-Typnamen reconciled:
governance_plane/git_internal statt PROTECTED_GOVERNANCE_LOCK; write/execute statt
FILE_WRITE/SHELL_EXEC; Whitelist = FK-55 §55.3a privilegierte Principals statt
INSTALLER/RECOVERY). Per-Zone-Whitelist (harness-Zone -> nur pipeline_deterministic;
governance-Zone -> pipeline_deterministic/admin_service/human_cli). Self-Protection-
Registry-Pfade als governance_plane klassifiziert (Capability-Matrix kohaerent statt
UNCLASSIFIED_MUTATION). Capability-Enforcement (AG3-032) laeuft weiterhin ZUERST.
Threat-Stufe 3 (Obfuskation) bewusst out-of-scope (FK-55 §55.1a). giftige Codex r1
(A-F: .codex/hooks.json-Luecke, zu breite Whitelist, HTTP-Detection-Overclaim,
Registrierungs-Nexus, Docstring-Literale, spoofbarer Marker) -> Remediation -> r2
(ERROR B: Capability/Guard-Over-Narrowing) -> Remediation -> r3 PASS. Separater
Sonar-Refactor-Commit (@d784629) loeste 6 CRITICAL new_violations (S1192 +
PY_MODULE_TOP_LEVEL_MAX_LOC_100 in 2 Guards + AG3-032s operations.py/matrix_data.py).
**Offene WARNINGs (gespiegelt, getrackt):** (F) Skill-Marker (--via-skill/X-Skill)
ist agent-spoofbar (Stufe-1+2-Konvention, keine Attestierung; echte Skill-only-
Durchsetzung braucht Server-Attestierung, Zukunft); (D) "always active" haengt an der
Installer-Hook-Registrierung (FK-30 §30.3.1, Owner = Installer/AG3-031), als
Contract-Test gepinnt + dokumentiert. **Folge:** THEME-006 fast komplett — verbleibt
AG3-034 (Preflight 2/5-10 + IntegrityGate-8-Dim + Concept/Research-Drift), ebenfalls
durch AG3-032 unblockt.

**Anmerkung 7 (AG3-018 Fast-Modus — Konzept-Teil vorgezogen, 2026-06-03, Stefan-approved):**
Im Rahmen der AG3-034-Arbeit wurde ein **unified Sonar-Gate-Applicability-Modell**
gelandet (FK-33 §33.6.5 als Owner: 3 Zustaende APPLICABLE / NOT_APPLICABLE-Sonar-
nicht-verfuegbar / NOT_APPLICABLE-fast; Unterscheidung „bewusst-abwesend ≠ kaputt";
neuer FK-03-Schalter `sonarqube.available`; Re-Entry ueber den bestehenden
Cleanup-Remediation-Worker). Dabei wurde der **Konzept-Anteil von AG3-018**
mitgenommen: FK-24 §24.3.4 „Mode-Profil Fast" als kanonische Tabelle plus die
Fast-Referenzen quer durch FK-22 §22.4c, FK-27 §27.6a.4, FK-29 §29.1a.6, FK-35
§35.2.4a (sowie die `mode_lock`-Wertebereich-Vereinheitlichung `{null/idle |
standard | fast}` in FK-24 §24.3.3 + AG3-034 §2.1.2). **Folge:** Der verbleibende
Scope von AG3-018 ist die **CODE-Implementierung** (Mode-StrEnum, Phase-Routing,
Story-Scoped-Guard-Skip, Service-API-`mode`-Feld, Telemetrie-Tagging,
Pre-Merge-Rebase). Die AG3-018-Akzeptanzkriterien bleiben unveraendert; AC 1
(kanonische Tabelle) ist konzeptionell vorab erfuellt.

## 2. Begruendung der Reihenfolge

**AG3-026 zuerst (Top-Surface der Capability):**
VerifySystem ist die zentrale Capability, an der pipeline-framework,
implementation-phase, exploration-and-design alle haengen. Foundation
(021/022/023) ist done, also kann 026 sofort starten.

**AG3-029 / AG3-030 vor AG3-027 / AG3-031:**
Beide sind klar isoliert und etablieren BC-Top-Surfaces, die unabhaengig
voneinander pruefbar sind. Niedrige Komplexitaet (Paket-Migration und
no-op-Aktivierungslogik) — gute Aufwaerm-Stories nach AG3-026.

**AG3-027 (M, schlank) vor AG3-031:**
Skills-Top-Surface kann jetzt zuegig durch, weil Persistenz und Installer
in AG3-048 ausgelagert sind. AG3-031 (Governance-Hooks) ist konzeptuell
schwerer (Trust-Boundary-Anschluss) und kommt danach.

**AG3-035 + AG3-040 vor AG3-028:**
AG3-028 wurde am 2026-05-19 von "Top-Surface mit Protocol/Fake" auf
"vorgezogene Vollumsetzung" hochgestuft (Stefan-Entscheidung). Damit
braucht es `Telemetry.write_projection` produktiv — das liefert AG3-035
(ProjectionAccessor) und AG3-040 (Postgres-Store-Komplettierung).
Reihenfolge zwingend: erst Telemetry-Infrastruktur, dann FailureCorpus.

**AG3-048 zuletzt:**
Folge-Story zu AG3-027 (siehe Split-Entscheidung 2026-05-19). Setzt
auf den fertigen Skills-Top-Surface auf und bringt SQLite/Postgres-
Persistenz + BC12-Installer-Andockung + Repo-Hygiene mit.

## 2a. Stefan-Nach-Review-Entscheidungen 2026-05-19 (AG3-026)

Nach-Review 2026-05-19 lieferte 2 ERRORs + 2 WARNINGs. Entschieden:

- **E1 + E2 fix-pflichtig** (kein Wahlentscheid): Implementation-Phase-Handler auf `VerifySystem.run_qa_subflow` migrieren; `load_verify_decision_artifact` auf Stage `qa-policy-decision` / Filename `decision.json` (FK-27 §27.7) synchronisieren.
- **W1 (Layer-2 Stub-Payloads): Voll umsetzen.** Stefan entschied gegen die Stub-Variante. Drei echte LLM-Reviewer (`qa_review` / `semantic` / `doc_fidelity`) werden in AG3-026 implementiert. Damit zieht AG3-026 **Teile von AG3-043 (Layer-2-LLM-Evaluations) vor**. Konsequenz fuer AG3-043: Story muss um die drei in 026 erledigten Reviewer reduziert werden, sobald die Remediation done ist (TODO bei Remediation-Abschluss eintragen).
- **W2: PhaseEnvelopeView-DTO** in `verify_system/contract.py` (vier Felder `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint`). Caller baut den View. Kein `pipeline_engine`-Import in `verify_system`.
- **Sonar (13 violations / 5 critical)** sind Teil der Remediation, nicht separater Folge-Auftrag.

**Pass-3-Entscheidung 2026-05-22 (BC-Topology-Drift AG3-026):**
`verify_system/system.py` liest `StoryContext` weiterhin via `state_backend.load_story_context`
(BC-Topologie-Bruch: VerifySystem sollte ueber ArtifactManager + Top-Surfaces gehen).
Stefan-Entscheidung: **AG3-035 abwarten** (ProjectionAccessor loest das strukturell auf).
Bis dahin: DRIFT-AG3-035-Kommentar im Code + dieser Verweis. AG3-035-Scope wurde
entsprechend ergaenzt (siehe AG3-035-Story-Scope-Block).

Folge: AG3-026 bleibt in `_bearbeitungsreihenfolge.md` §1 auf `in_progress`, wird erst nach Remediation auf `done` gesetzt. Reihenfolge-Vorrang AG3-029 → AG3-026-Remediation → AG3-030 ist explizit von Stefan bestaetigt.

## 3. Stefan-Entscheidungen 2026-05-19 (zur Nachvollziehbarkeit)

- **AG3-027 Split (Variante A)**: Top-Surface schlank halten (M), drei
  ausgelagerte Bereiche in AG3-048 (M):
  - `skill_bindings`-Tabelle in state_backend
  - `installer/runner.py` Andockung (BC12)
  - `__pycache__`-Cleanup in `src/agentkit/project_ops/install/`
- **AG3-028 Vollumsetzung (Variante A)**: produktiver Schreibpfad
  ueber `Telemetry.write_projection` statt InMemory-Fake. Size M -> L,
  `depends_on` ergaenzt um AG3-035 + AG3-040.

## 4. Nach der Welle (THEME-006+)

THEME-006 (Governance/Trust-Boundary), THEME-007 (Telemetrie-Restbloecke),
THEME-008 (Persistenz-Restbloecke), THEME-009 (QA-Kernlogik) und
THEME-010 (Exploration-Phase) folgen nach Abschluss der hier
gelisteten Welle. Reihenfolge ergibt sich erneut aus
`_story-schnitt-aus-themen.md §2` plus etwaiger spaeterer
User-Entscheidungen.

## 5. Pflege-Regel

Wenn der Orchestrator eine Story abnimmt (User-OK + `status: completed`),
wird der Eintrag in der Tabelle (§1) auf `done` gesetzt und das
**naechste** Element wird zum aktuellen "WIP". Wenn neue Entscheidungen
die Reihenfolge aendern (Splits, Re-Prioritisierungen), wird sowohl §1
als auch §2 entsprechend ergaenzt — ohne diese Pflege ist die Datei
wertlos.
