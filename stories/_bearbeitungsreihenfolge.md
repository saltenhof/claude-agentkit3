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
| 7 | AG3-040 Postgres-Store-Komplettierung | M | Sub-Block (a) done+abgenommen (2026-06-01, kumulativ @01421c7: Jenkins #24 SUCCESS, Sonar OK; project_management Postgres/Wire/project_detail-Views + Counters auf vereinheitlichter Identitaet). Sub-Block (b) fc_-Tabellen offen -> AG3-028 (Anmerkung 1). AG3-040.status.yaml bleibt in_progress bis (b). |
| 7a | AG3-050 Story-Identity-Unifizierung | M | done (2026-06-01; Stefan-Vorgabe; Codex r1 BLOCK -> r2 PASS-MIT-WARNINGS; @01421c7 Jenkins #24 SUCCESS, Sonar OK. WARNING N1: Postgres-Concurrency-Allokation unbewiesen -> Folge, getrackt) |
| 8 | AG3-028 FailureCorpus (Vollumsetzung) | L | blocked | nach AG3-035 + AG3-040 |
| 9 | AG3-048 Skills-Persistenz + Installer + Hygiene | M | blocked | nach AG3-027 |
| 10 | AG3-049 Codex-Harness-Adapter (CodexSettingsWriter Vollausbau) | M | blocked | nach AG3-031 (Codex-Adapter-Stub aus AG3-031 ausgelagert) |

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
