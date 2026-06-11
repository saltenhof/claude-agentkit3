# AG3-104 — Execution Remediation R2 (Konzept-/PROJECT_STRUCTURE-Prosa-Nachzug)

Doc-only Execution der freigegebenen Story AG3-104 (Spec-Review `review-r2.md`:
OVERALL APPROVE). Geaendert wurde ausschliesslich **`concept/`-Prosa (FK-07,
FK-73, FK-92) und `PROJECT_STRUCTURE.md`** plus **dieser Report**. **Kein
`src/`-/`tests/`-Diff** (verifiziert: `git diff -- src tests` leer). FK-76 wurde
inhaltlich nicht veraendert — §76.3 (kosmetische Paketverschiebung) und §76.8
(verbindliche Port-Surface) tragen die Aussage bereits; der Nachzug erfolgt
konsistenzpflichtig in PROJECT_STRUCTURE.md (BC-Registry).

Dieser Report ist das **Zielartefakt der ARCH-55-Spiegelung an AG3-078**
(§2.1 Item 6 / AK4 / CP5) und konsolidiert alle owner-losen Code-Bedarfe als
nummerierte PO-Eskalationen (CP1–CP3) bzw. Cross-Story-Voraussetzungen
(CP4–CP5) gemaess AK5/AK7. Alle file:line-Anker unten sind **gegen die
Code-Realitaet frisch verifiziert** und korrigieren stale Anker aus
`remediation-r1.md` (die Spec-Review-Phase zitierte aeltere Zeilenstaende).

## 1. Durchgefuehrte Prosa-Aenderungen (Owner pro Wert)

### AK1 — FK-07 §7.4 Port-Nomenklatur aspirational + §7.4.1 WorktreeManager-Drift
Datei: `concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`

- **§7.4 (vor §7.4.1):** Neuer Aspirations-Hinweis. Die Provided-Contract-Port-Namen
  in §7.4.1–§7.4.6 sind als **Zielbild (aspirational)** gekennzeichnet, konsistent
  mit §7.6 (Repository-Regel „noch im Umbau") und §7.7.4 („bewusst noch nicht voll
  maschinell erzwungen"). Reale Symbole namentlich gegenuebergestellt:
  - `StoryContextPort` existiert **nicht**; reales Pendant `StoryContextQueryPort`
    (`src/agentkit/verify_system/protocols.py:120` Protocol-Def;
    `src/agentkit/verify_system/system.py:102/129/185`;
    `src/agentkit/exploration/ports.py:10`).
  - Exploration-Protocol-Ports: `exploration/ports.py:36` `RunScopeResolver`,
    `:57` `ChangeFrameReader`, `:82` `WorkerDraftPresenceReader`,
    `:111` `ChangeFrameWriter`, `:152` `DeclaredImpactReader`.
  - Closure-Runtime-Ports: `closure/runtime_ports.py:104` `ProductiveSanityGatePort`,
    `:202` `ProductiveDocFidelityFeedbackPort`, `:260` `ProductiveVectorDbSyncPort`,
    `:390` `ProductiveTelemetryEvidencePort`, `:495` `ProductiveGuardDeactivationPort`,
    `:522` `ProductiveGuardCounterFlushPort`, `:563` `ProductiveModeLockReleasePort`.
  - **Owner pro Wert:** Doku-Angleichung hier; Port-Namen-Vereinheitlichung im Code
    = Code-Folgearbeit ohne Backlog-Owner -> PO-Eskalation (CP, betroffene BCs).
- **§7.4.1 (nach WorktreeManager-Zeile):** Neuer Drift-Hinweis. Soll-Schnitt = shared
  `agentkit.worktree_manager` (`bc-cut-decisions.md:275-283`, Owner
  `architecture-conformance.group.story_context_manager`, `:278`; gefuehrt in
  `PROJECT_STRUCTURE.md:219`/`:297`) gegen die verstreute Code-Realitaet
  (`governance/setup_preflight_gate/worktree.py`, `closure/multi_repo_saga.py`;
  kein Top-Level `worktree_manager/`). **Owner pro Wert:** Drift ist Code-Bedarf
  gegen den **bestehenden** Owner `story_context_manager` -> **CP1**, nicht owner-los.

### AK2 — PROJECT_STRUCTURE.md `harness-integration` als BC 17 (drei Stellen)
Datei: `PROJECT_STRUCTURE.md`

- (a) **Zaehlung:** „16 fachliche Bounded Contexts" -> „17 …".
- (b) **Baum-Aufzaehlung:** Block „# ---- BC 17: harness-integration ----" mit realem
  Ort `governance/harness_adapters/` und Soll-Paket-Hinweis `agentkit.harness_integration`
  (FK-76 §76.3, kosmetisch).
- (c) **Verantwortungstabelle:** Zeile `governance/harness_adapters/` (BC 17
  `harness-integration`, `bounded-contexts.yaml:245`).
- Zusatz-Notizblock nach der Tabelle: Paketverschiebung (§76.3) = **OPTIONAL**;
  Port-Surface (§76.8: `HarnessPort`/`HarnessInvocation`/`HarnessHookEnvelope`/
  `HarnessCapability`/`HarnessAdapterResult` + Settings-Writer) = **VERBINDLICHE,
  geownete Code-Soll-Surface** (Owner-BC `harness-integration`), heute nicht als
  Symbole vorhanden -> **CP2**.

### AK3 — FK-73 §73.6 Baseline-Hash-Owner + FK-92 §92.4 slugify-Owner
- `concept/technical-design/73_project_management.md` §73.6: Code-Realitaet-Notiz —
  `ProjectConfiguration` (`src/agentkit/project_management/entities.py:14`, Felder
  `:34`/`:35` …) traegt **kein** Baseline-Hash-Feld; Integrity-Gate bestaetigt das
  Fehlen (`src/agentkit/governance/integrity_gate/dim9_drift.py:26-30`). Owner =
  **project-management** (Project-Entitaet), **nicht** AG3-070 (`project-config`).
  Kein Backlog-Owner (GAP-Analyse `stories/project-management-gap-analyse.md` §4.1
  listet nur A1–A4) -> **CP3**.
- `concept/technical-design/92_verzeichnis_namenskonventionen.md` §92.4: Code-Realitaet-
  Notiz — `slugify` existiert **nicht** im Code (`def slugify` -> 0). Code-Home =
  Story-Creation-BC; AG3-068 ownt `story_creation`/`story.md`-Export (FK-21 §21.11),
  enumeriert `slugify` aber **nicht** -> **CP4** (AG3-068-Scope erweitern oder
  dedizierte Konventions-Story).

### AK6 — ARCH-55-Konsistenz in der angepassten Prosa
Keine deutschen Code-Identifier/Wire-Keys in den ergaenzten Prosa-Bloecken
eingefuehrt. Erwaehnte deutsche Werte (`wiederholung`/`mittel`/`niedrig` …) erscheinen
ausschliesslich als **Zitate des Ist-Standes** im Spiegel-Block unten, nicht als neu
eingefuehrte Identifier.

## 2. ARCH-55-Spiegel an AG3-078 (AK4 / Item 6 / CP5) — vollstaendig, kein Wert ausgelassen

AG3-078 (`stories/AG3-078-failure-corpus-pattern-check-factory`) ist Schema-Owner von
`fc_patterns`/`fc_check_proposals` und damit der **einzige** Code-Owner dieser Werte.
Die folgenden deutschen Enum-Werte UND die korrespondierenden SQLite-CHECK-Constraints
sind **ein** ARCH-55-Code-/Schema-Fix in AG3-078 (hier NICHT codiert, AG3-078-Dateien
NICHT editiert):

- `PromotionRule` (`src/agentkit/failure_corpus/pattern.py:40` Klasse;
  Werte `:49` `WIEDERHOLUNG="wiederholung"`, `:50` `HOHE_SCHWERE="hohe_schwere"`,
  `:51` `CHECKBARKEIT="checkbarkeit"`).
- `PatternRiskLevel` (`pattern.py:54` Klasse; Werte `:57` `MITTEL="mittel"`,
  `:58` `HOCH="hoch"`, `:59` `KRITISCH="kritisch"`).
- `FalsePositiveRisk` (`src/agentkit/failure_corpus/check_proposal.py:53` Klasse;
  Werte `:61` `NIEDRIG="niedrig"`, `:62` `MITTEL="mittel"`, `:63` `HOCH="hoch"`).
  Hinweis: der Docstring `:56-58` markiert ARCH-55 dort selbst als „out of scope —
  concept-level change" — genau dieser Code-Fix ist via CP5 an AG3-078 zu fuehren.
- SQLite-CHECK-Constraints, dieselben deutschen Werte
  (`src/agentkit/state_backend/sqlite_store.py:964` `promotion_rule … CHECK (… IN (…))`,
  `:967` `risk_level … CHECK (…)` der `fc_patterns`-Tabelle;
  `:1048` `false_positive_risk … CHECK (…)` der `fc_check_proposals`-Tabelle).

Anker-Korrektur ggue. `remediation-r1.md`: die dortigen Anker `pattern.py:50-60`,
`check_proposal.py:56-58`, `sqlite_store.py:800-805` stammten aus der Spec-Review-Phase
und sind gegen den heutigen Code praezisiert (pattern.py:40/49-51/54/57-59,
check_proposal.py:53/61-63, sqlite_store.py:964/967/1048).

## 3. Konsolidierte PO-Eskalationen / Cross-Story-Voraussetzungen (AK5 / AK7)

Jeder Code-Bedarf ohne Backlog-Owner ist nummeriert ausgewiesen — kein offener
Owner-Konflikt verbleibt:

- **CP1 (PO-Eskalation, WARNING -> aktiv an PO spiegeln):** WorktreeManager-
  Konsolidierung (Code). Owner-BC `story-lifecycle`/`story_context_manager`
  (`bc-cut-decisions.md:278`). Kein Backlog-Eintrag -> Code-Folge-Story anlegen.
- **CP2 (PO-Eskalation):** `harness_integration`-Paketverschiebung (optional) +
  **verbindliche** Port-Surface §76.8 (Code). Owner-BC `harness-integration`
  (`bounded-contexts.yaml:245`). Kein Backlog-Eintrag -> Code-Folge-Story.
- **CP3 (PO-Eskalation):** SonarQube-Baseline-Hash-`configuration`-Feld der
  Project-Entitaet (Code). Owner-BC `project-management`; **nicht** AG3-070. Kein
  Backlog-Eintrag (GAP-Analyse §4.1) -> Code-Story gegen project-management.
- **CP4 (Cross-Story-Voraussetzung):** `slugify` (FK-92 §92.4, Code). Code-Home
  Story-Creation-BC; nicht im AG3-068-Scope enumeriert -> AG3-068-Scope erweitern
  oder dedizierte Verzeichnis-Konventions-Story.
- **CP5 (Cross-Story-Voraussetzung):** Deutsche `failure-corpus`-Enum-/CHECK-Werte
  (§2 oben, vollstaendig) -> **AG3-078** (Schema-Owner). Spiegel-Vermerk = dieser
  Report; keine AG3-078-Datei editiert.

## 4. Verifikationsstatus

- Geaenderte Dateien dieser Execution: `concept/technical-design/07_…md`,
  `concept/technical-design/73_project_management.md`,
  `concept/technical-design/92_verzeichnis_namenskonventionen.md`,
  `PROJECT_STRUCTURE.md`, `stories/AG3-104-*/remediation-r2.md`. **Sonst nichts.**
- `git diff -- src tests`: **leer** (kein `src/`-/`tests/`-Diff).
- Doc-only-Gates gruen: `scripts/ci/check_concept_frontmatter.py`,
  `scripts/ci/compile_formal_specs.py`, `scripts/ci/check_architecture_conformance.py`
  (GAC-1, Exit 0).
- Keine fremde Story-Datei (AG3-068/070/078) editiert; keine Code-/Test-Datei
  angefasst; `.mcp.json`/`mcps/` unangetastet; kein Commit.
