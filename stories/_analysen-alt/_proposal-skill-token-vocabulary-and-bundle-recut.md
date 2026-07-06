# Proposal — Skill Placeholder-Vocabulary Korrektur + Bundle-Re-Cut (GitHub als Code-Backend, Story-Backend ist AK3)

Status: PROPOSAL (read-only Analyse, kein Code, keine Story, keine Konzeptänderung)
Datum: 2026-06-11
Autor-Kontext: derived/confirmed Thesis substantiieren + aktionierbar machen. Kein Re-Opening der Thesis.

> Lesehinweis: Jede Aussage ist mit Konzept-§ oder `Datei:Zeile` belegt. Wo die Datenlage von der
> Auftrags-Prämisse abweicht (z. B. „FK-03 §3.1 hat die Layout-Felder bereits"), wird das **explizit
> korrigiert statt nachgesprochen** — der Owner verlangt Ableitung, nicht Nacherzählung.

---

## 0. Kernbefund in einem Satz

Die ~30 GitHub-Projects-V2-Board-Tokens in den ausgelieferten Bundles (`{{GH_FIELD_*}}`,
`{{GH_*_OPTION}}`, `{{GH_PROJECT_ID}}`, `{{GH_PROJECT_NUMBER}}`, `{{GH_PROJECT_FIELDS_TABLE}}`)
sind **funktionslos** für AK3: sie setzen voraus, dass AK3 ein GitHub-Projects-Board als
Story-Tracker treibt — was FK-12 §12.1.1/§12.7 explizit verbietet und was kein einziger
Produktionspfad im Code tut. Sie sind v2-Carry-over. Der Skill-Substitutor
(`skills/placeholder.py`) kennt ohnehin nur 4 Tokens und würde auf jeden dieser Tokens
**fail-closed** brechen. Der korrekte Schritt ist ein **Skill-Behavior-Re-Cut** der beiden
betroffenen Bundles auf das AK3-Story-Backend / die Control-Plane-API (FK-91), nicht bloßes
Token-Löschen.

---

## 1. EVIDENCE BLOCK — Substanziierung der Thesis

### 1.1 Story-/Project-Management ist AK3-owned (Code)

Die vollständige Story-/Projekt-Verwaltung existiert als eigenständige, typisierte AK3-Domäne mit
eigener Persistenz und Control-Plane-API:

| Surface | Datei (`src/agentkit/...`) | Beleg |
|---|---|---|
| Story-Read-Service (List/Detail) | `story/service.py:28` `class StoryService` | baut List/Detail aus `StoryContext` + Phase-State, nicht aus GitHub (`story/service.py:34-41`) |
| Story-Read-Repository | `story/repository.py` | liest ausschließlich aus `state_backend.store` (`story/repository.py:8-15`: `load_story_context_global`, `load_story_contexts_global`, …) |
| Story-Lifecycle-Service (autoritativ) | `story_context_manager/service.py` `StoryService.create_story` (referenziert in `story_creation/create_flow.py:24,48,207`) | „authoritative story lifecycle service (FK-91)" (`story_creation/create_flow.py:102`) |
| Story-Creation-Flow | `story_creation/create_flow.py:80` `class StoryCreationReconciler` | reconciliert gegen `self._story_service.create_story(...)` (`:207`) — **kein** GitHub-Projects-Aufruf im gesamten Modul |
| Control-Plane-API (FK-91) | `control_plane/http.py`, `control_plane/dispatch.py`, `control_plane/repository.py`, `control_plane_http/` | Pre-Start-Guard liest persistierten `StoryStatus` **über die Story-Service** (`control_plane/dispatch.py:73-83` `ApprovalReader` „Implemented by the AK3 story-service … CONSUMES the authoritative persisted status; it never writes story status truth") |
| Project-Management-Domäne | `project_management/{entities,service,repository,lifecycle,views,http}.py` | eigene Project-Entität + Lifecycle, FK-73/DK-14 |
| Execution-Planning-Domäne | `execution_planning/{dependency_graph,readiness,lifecycle,repository}.py` | Dependencies/Readiness/Waves AK3-intern (FK-70) |
| State-Backend (Persistenz) | `state_backend/{postgres_store,sqlite_store,postgres_schema.sql}.py` | die operative Wahrheit (SQLite/Postgres), `project_key`-skopiert |

Folgerung: Story-Identität, -Status, -Attribute, Board-Sichten, Dependencies, Closure-Metriken werden
durchgängig im AK3-Backend gehalten und über die Control-Plane bewegt — exakt wie FK-12 §12.1.1
fordert. Kein Produktionspfad mutiert oder liest ein GitHub-Projects-Board.

### 1.2 FK-12 — GitHub ist Code-Backend, NICHT Story-Tracker (Konzept, verbatim)

FK-12 §12.1 (`technical-design/12_github_integration_repo_operationen.md`):
> „AgentKit betreibt keinen eigenen GitHub-Adapter oder REST-Client. Alle GitHub-Interaktionen laufen
> über die `gh`/`git` CLI …"

FK-12 §12.1.1 „Abgrenzung zur Story-Autoritaet" (verbatim):
> „Story-Identitaet, Story-Status, Board-Sichten und Story-Detaildaten liegen ausschliesslich im
> **AK3-Story-Backend** (siehe FK-17 / FK-18 fuer Datenmodell und Persistenz, FK-91 fuer die
> Control-Plane-API). GitHub ist nicht die Wahrheitsquelle fuer Story-Lifecycle und enthaelt kein
> Story-Tracking. GitHub bleibt ausschliesslich: Repository-Backend fuer Code-Operationen;
> Branch-/PR-Mechanik fuer Story-Branches `story/{story_id}`. Statuswechsel, Story-Attribute,
> Closure-Metriken, Dependencies und administrative Operationen werden ueber den AK3-Story-Service
> ausgefuehrt, nicht ueber GitHub-Mechanik."

FK-12 §12.7.1 (verbatim):
> „Story-Status, Story-Attribute, Story-Erstellung, Story-Closure-Status und Closure-Metriken laufen
> ueber das AK3-Story-Backend (FK-17/FK-18/FK-91), nicht ueber GitHub."

FK-12 §12.7 Tabelle: die EINZIGEN GitHub-Operationen in der Pipeline sind Setup (Branch/Worktree),
Worker (Commits/Push) und Closure (Push/Merge) — **kein** `gh project`, **kein** `gh api graphql`
auf ein Projects-Board.

FK-21 §21.10.2 (Story-Anlage): „Der Skill ruft den **AK3-Story-Service** auf und legt die Story mit
allen ermittelten Attributen an … (siehe FK-91)." FK-21 §21.13: ein PreToolUse-Guard verhindert sogar,
dass Agents „Stories direkt am AK3-Story-Service vorbei anlegen". Es gibt keinerlei Konzeptpfad, der
Story-Anlage über ein GitHub-Projects-Board vorsieht.

### 1.3 FK-43 §43.4.2 — Token-Autorität: genau 4 Tokens, alle aus FK-03 (verbatim)

FK-43 §43.4.2 (`technical-design/43_skills_system_task_automation.md`) — `PlaceholderSubstitutor`
substituiert **read-only** aus `PipelineConfig` (FK-03); „Die substituierten Felder stammen
ausschliesslich aus FK-03":

| Platzhalter | Quelle in `project.yaml` (FK-03) |
|---|---|
| `{{gh_owner}}` | `config.github_owner` |
| `{{gh_repo}}` | `config.repositories[0].name` (deterministisch erstes Repo) |
| `{{project_prefix}}` | `config.project_prefix` |
| `{{project_key}}` | `config.project_key` |

FK-43 §43.2.3 listet dieselben 4 Tokens (mit der Klarstellung `{{project_key}}` =
„Story-Backend-Identifier", `{{gh_owner}}`/`{{gh_repo}}` = „Code-Backend"). Mehr Tokens kennt die
Konzept-Autorität nicht.

Code deckt sich exakt: `skills/placeholder.py:38-45` `_MANDATORY_PLACEHOLDERS = {gh_owner, gh_repo,
project_prefix, project_key}`; `:144-161` mappt sie 1:1 auf `config.github_owner`,
`config.repositories[0].name`, `config.project_prefix`, `config.project_key`. Plus genau EIN
manifest-gespeister Sonderfall `{{AGENT_SPAWN_SKILL_PROOF}}` (`:47-49`, AG3-110, Quelle:
`.installed-manifest.json`, **nicht** `project.yaml`). Jeder andere Token ⇒
`UnknownPlaceholderError` (fail-closed, `:190-200`).

### 1.4 Kein Produktionscode konsumiert die GH-Projects-Board-Tokens / die Projects-Adapter-API

`integrations/github/projects.py` (332 Zeilen) implementiert `gh project`-/GraphQL-Operationen
(`list_project_items`, Field-Mutations etc.). Grep über das gesamte Repo:

- Die einzige Nicht-Test-Referenz ist der Re-Export in `integrations/github/__init__.py:31-46`.
- **Kein** Modul außerhalb von `integrations/github/` importiert oder ruft `projects.py`-Symbole
  (`list_project_items`, `ProjectItem`, Field-Setter). Grep über `src/` (ausgenommen `projects.py`):
  nur `__init__.py` (Re-Export) + `tests/unit/integrations/github/test_projects.py` (Selbsttest) +
  `tests/e2e/github_live/test_projects.py` (opt-in Live-Test, nie Standard-CI).
- Kein `pipeline_engine`, `story_creation`, `control_plane`, `project_management`, `cli`, `closure`
  oder `workers`-Pfad berührt es.

**Charakterisierung `integrations/github/projects.py`: totes v2-Leftover.** Es ist eine
nirgends-verdrahtete Adapter-Bibliothek. Es widerspricht zwar FK-12 §12.1 („AgentKit betreibt keinen
eigenen GitHub-Adapter") nur insofern, als es einen Projects-Wrapper bereitstellt, der nie aufgerufen
wird; faktisch ist es schlicht funktionslos. (Entsorgung ist NICHT Teil dieses Proposals — separat zu
bewerten; hier nur als Beleg, dass die Board-Tokens keinen lebenden Konsumenten haben.)

Die Board-Tokens selbst (`{{GH_FIELD_*}}`, `{{GH_*_OPTION}}`, `{{GH_PROJECT_ID/NUMBER}}`) haben **keine
Quelle**: weder in den 4 FK-43-Tokens, noch in `PlaceholderSubstitutor`, noch als Feld in
`config/models.py:783 ProjectConfig` (`extra="forbid"`, `:813`). Sie sind unauflösbar by construction.

### 1.5 Token-Inventar (vollständig, dedupliziert über alle 8 ausgelieferten Bundles)

Quelle: `src/agentkit/resources/skill_bundles/*/4.0.0/SKILL.md`. Verteilung:

- **create-userstory-core**: trägt ALLE ~30 Board-Tokens + die Layout-/Render-Tokens (siehe §2).
- **lookup-userstory-core**: `{{GH_PROJECT_NUMBER}}`, `{{GH_REPO_LOCAL_PATH}}`, `{{GH_OWNER}}`,
  `{{GH_CONFIG_EXPORT}}`, `{{REPO_LAYOUT_TABLE}}`, `{{WIKI_STORIES_DIR}}`, `{{WIKI_STORIES_INDEX}}`,
  `{{PROJECT_NAME}}`, `{{PROJECT_PREFIX}}`, + Block-Tokens `{{#IF_WIKI_INDEX}}`/`{{/IF_WIKI_INDEX}}`.
- **execute-userstory-core**: `{{PROJECT_PREFIX}}`, `{{USERSTORY_BUNDLE_PATH}}`,
  `{{AGENT_SPAWN_SKILL_PROOF}}`, `{{#IF_CLARIFICATION_ANSWERS}}`.
- **create-userstory-are, execute-userstory-are, llm-discussion-core, manage-requirements-core,
  semantic-review-core**: **keine** Tokens. (Die ARE-Create-Variante referenziert bereits „the AK3
  story backend" und „backend reconciliation remain owned by AgentKit runtime components" —
  `create-userstory-are/4.0.0/SKILL.md:18,27-29`. Der CORE-Bundle ist also der Ausreißer, nicht die Norm.)

Damit ist der Re-Cut-Blast-Radius präzise: **create-userstory-core** (Hauptlast) und
**lookup-userstory-core** (Read-Seite). Alle übrigen Bundles sind nicht betroffen.

---

## 2. TOKEN DISPOSITION TABLE

Klassen: **(A) KEEP** = einer der 4 FK-43-Tokens; **(B) KEEP-CANDIDATE** = legitimer
Projekt-Layout/Config-Wert mit konkreter (ggf. noch zu schaffender) FK-03-Quelle; **(C) DROP** =
GH-Projects-Board-Node-IDs / GH-Story-Tracking-Annahmen; **(D) RENDER-BLOCK** = generierter Inhalt.

> Achtung Schreibweise: die Bundles nutzen UPPERCASE (`{{GH_OWNER}}`, `{{PROJECT_PREFIX}}`), FK-43 und
> der Substitutor nutzen lowercase (`{{gh_owner}}`, `{{project_prefix}}`). Das ist ein **eigenständiger
> Bug** (kein Bundle-Token matcht aktuell den Substitutor), siehe §6/Open Decision 1. In der Tabelle
> ist die FK-43-Zuordnung nach Semantik, nicht nach Casing gemacht.

### (A) KEEP — mappt direkt auf FK-43 §43.4.2 / FK-03

| Token (Bundle-Schreibweise) | FK-43-Token | FK-03-Quelle | Timing |
|---|---|---|---|
| `{{GH_OWNER}}` | `{{gh_owner}}` | `config.github_owner` (`config/models.py:822`) | install-time |
| `{{PROJECT_PREFIX}}` | `{{project_prefix}}` | `config.project_prefix` (`config/models.py:817`, default `project_key.upper()` `:963-968`) | install-time |
| `{{GH_REPO_PRIMARY}}` | `{{gh_repo}}` | `config.repositories[0].name` (`config/models.py:818`) | install-time |
| `{{AGENT_SPAWN_SKILL_PROOF}}` | (5. Sonderfall, AG3-110) | `.installed-manifest.json` → `agent_spawn_skill_proof` (`skills/placeholder.py:163-184`) | install-/read-time (manifest-fed) |

Hinweis: `{{AGENT_SPAWN_SKILL_PROOF}}` ist kein FK-03-Token, aber bereits **autoritativ modelliert und
implementiert** (AG3-110). Es bleibt unverändert — nur in `execute-userstory-core` vorhanden, nicht von
diesem Re-Cut berührt.

### (B) KEEP-CANDIDATE — legitime Layout/Config-Werte (FK-03-Quelle teils noch zu schaffen)

| Token | Wofür | FK-03-Status | Timing-Empfehlung |
|---|---|---|---|
| `{{WIKI_STORIES_DIR}}` | Story-Wiki-Verzeichnis (`stories/`) | **Konzept:** FK-03 §3.1 Ebene 2 nennt `wiki_stories_dir: stories` (`03_…md:99`). **Code:** Feld fehlt in `ProjectConfig` (`:813 extra="forbid"`). ⇒ Konzept↔Code-Gap | install-time |
| `{{GUARDRAILS_DIR}}` (impliziert via `{{GUARDRAIL_REFS}}`-Render) | Guardrail-Verzeichnis | FK-03 §3.1 nennt `guardrails_dir: _guardrails` (`03_…md:100`); Code-Feld fehlt ebenso | install-time |
| `{{CONCEPTS_DIR}}` | Konzept-Wurzel (Discovery-Engine, Pfad-Validierung) | **Weder** FK-03 §3.1 **noch** `ProjectConfig` haben ein `concepts_dir`-Feld. Müsste neu nach FK-03 (+ Modell). | install-time |
| `{{PROJECT_CODEBASE_ROOT}}` | Repo-Root für temp-Dateien / CLAUDE.md-Read | Kein FK-03-Feld. Ableitbar: Projekt-Root ist der harness-`cwd`/Bind-Punkt-Parent. Kandidat für **derived** statt config-Feld. | install-time ODER runtime (Open Decision 2) |
| `{{USERSTORY_BUNDLE_PATH}}` | Pfad zu mitgelieferten Tools (`vectordb/search.py`, `tools/validate_concept_refs.py`) im Bundle | Kein FK-03-Feld. Ableitbar aus Bundle-Root (das Bundle kennt seinen eigenen Pfad). Kandidat für **derived**. | install-time |
| `{{STORY_SPEC_PATH}}` | Pfad zur Story-Spezifikation (Referenzdoku) | Kein FK-03-Feld. Prüfen ob noch benötigt nach Re-Cut, sonst DROP. | install-time |
| `{{WIKI_STORIES_INDEX}}` | Pfad zur Story-Index-Datei (nur in `{{#IF_WIKI_INDEX}}`-Block) | Ableitbar aus `wiki_stories_dir`. Kandidat **derived**. | install-time |
| `{{PROJECT_NAME}}` | Anzeige-Name in Summary/Lookup | `config.project_name` (`config/models.py:816`) — existiert. ⇒ leicht hebbar, aber NICHT in FK-43-4er. Open Decision: aufnehmen oder durch `{{project_key}}` ersetzen. | install-time |

**Wichtige Korrektur zur Auftrags-Prämisse:** Der Auftrag sagt „FK-03 already has these per §3.1
(`wiki_stories_dir`/`guardrails_dir`)". Das stimmt für die **Konzept-Prosa** (FK-03 §3.1 Ebene 2,
`03_…md:99-101`), **nicht** für das **Code-Modell**: `ProjectConfig` (`config/models.py:783-825`,
`extra="forbid"`) hat diese Felder nicht. `concepts_dir`/`story_spec_path`/`project_codebase_root`
fehlen sogar in beiden. Wer einen Layout-Token behalten will, muss die FK-03-Quelle (Prosa **und**
Pydantic-Feld) zuerst schaffen — sonst bricht der fail-closed-Substitutor (NO ERROR BYPASSING).

### (C) DROP — GH-Projects-Board-Node-IDs + GH-Story-Tracking-Annahmen

Alle folgenden setzen ein von AK3 getriebenes GitHub-Projects-Board voraus (FK-12 §12.1.1: existiert
nicht). Keiner hat eine FK-03-Quelle oder einen lebenden Code-Konsumenten (§1.4):

- Projekt-Node-IDs: `{{GH_PROJECT_ID}}`, `{{GH_PROJECT_NUMBER}}`
- Field-IDs (12): `{{GH_FIELD_STATUS_ID}}`, `{{GH_FIELD_STORY_ID_ID}}`, `{{GH_FIELD_SIZE_ID}}`,
  `{{GH_FIELD_MODULE_ID}}`, `{{GH_FIELD_PRIMARY_REPO_ID}}`, `{{GH_FIELD_PARTICIPATING_REPOS_ID}}`,
  `{{GH_FIELD_EPIC_ID}}`, `{{GH_FIELD_STORY_TYPE_ID}}`, `{{GH_FIELD_CREATED_AT_ID}}`,
  `{{GH_FIELD_CHANGE_IMPACT_ID}}`, `{{GH_FIELD_NEW_STRUCTURES_ID}}`, `{{GH_FIELD_CONCEPT_QUALITY_ID}}`
- Single-Select-Option-IDs (~15): `{{GH_STATUS_BACKLOG_OPTION}}`, `{{GH_STATUS_APPROVED_OPTION}}`,
  `{{GH_STORY_TYPE_IMPLEMENTATION_OPTION}}`, `{{GH_STORY_TYPE_CONCEPT_OPTION}}`,
  `{{GH_STORY_TYPE_BUGFIX_OPTION}}`, `{{GH_STORY_TYPE_RESEARCH_OPTION}}`,
  `{{GH_CHANGE_IMPACT_LOCAL_OPTION}}`, `{{GH_CHANGE_IMPACT_COMPONENT_OPTION}}`,
  `{{GH_CHANGE_IMPACT_CROSS_COMPONENT_OPTION}}`, `{{GH_CHANGE_IMPACT_ARCHITECTURE_IMPACT_OPTION}}`,
  `{{GH_NEW_STRUCTURES_TRUE_OPTION}}`, `{{GH_NEW_STRUCTURES_FALSE_OPTION}}`,
  `{{GH_CONCEPT_QUALITY_HIGH_OPTION}}`, `{{GH_CONCEPT_QUALITY_MEDIUM_OPTION}}`,
  `{{GH_CONCEPT_QUALITY_LOW_OPTION}}`
- `{{GH_REPO_LOCAL_PATH}}` (lookup) — wird nur für `cd … && gh project item-list` benutzt; entfällt mit
  dem Board-Lookup. (Falls ein lokaler Repo-Pfad nach Re-Cut anderweitig gebraucht wird, separat als
  derived prüfen — aber nicht als Board-Token behalten.)

Sonderfall `{{GH_CONFIG_EXPORT}}`: kein Board-Node-ID, sondern ein Shell-Export-Prelude für `gh`-Auth
(Token-Env). Es wird in den Bundles ausschließlich vor `gh issue …`/`gh project …`/`gh api graphql`
benutzt. Nach Re-Cut entfällt jeder `gh project`/`gh api graphql`-Aufruf. Ob `gh issue create`
überhaupt bleibt, ist eine offene Designfrage (§4/§6): wenn die Story-Anlage vollständig über die
Control-Plane läuft, entfällt `{{GH_CONFIG_EXPORT}}` ⇒ **DROP**. Bis dahin als
**DROP-pending-design** markiert (Secret-Hygiene: Open Decision 3).

### (D) RENDER-BLOCK — generierter Inhalt (kein Config-Token)

Diese sind keine Config-Substitutionen, sondern Stellen, an denen Inhalt **gerendert** würde. Sie
matchen `\w+` und würden vom Substitutor heute ebenfalls fail-closed brechen (`placeholder.py:190-200`).

| Token | Inhalt | Überlebt Re-Cut? | Produzent nach Re-Cut |
|---|---|---|---|
| `{{GH_PROJECT_FIELDS_TABLE}}` | Tabelle aus Field-IDs/Option-IDs des Boards | **Nein** — reine Board-Mechanik | — (entfällt mit DROP-Gruppe C) |
| `{{REPO_LAYOUT_TABLE}}` (lookup) | Repo-Layout-Übersicht | Ja, aber: aus `config.repositories[]` deterministisch renderbar. Kandidat für install-time-Render aus FK-03. | Installer/Materializer (aus `repositories[]`) ODER statischer Prosatext |
| `{{GUARDRAIL_REFS}}` | DoD-/Guardrail-Referenzblock | Ja — projektneutraler Referenztext | statischer Bundle-Inhalt ODER aus `guardrails_dir` gerendert |
| `{{DOD_FEATURE}}`, `{{DOD_BUGFIX}}`, `{{DOD_CONCEPT}}`, `{{DOD_RESEARCH}}` | Definition-of-Done-Templates pro Story-Typ | Ja — fachlich notwendig, board-unabhängig | statischer Bundle-Inhalt (am besintegrierten: direkt in `SKILL.md` inlinen, kein Token) |
| `{{MODULES_EXAMPLE}}` | Beispielmodul-Liste im Issue-Template | Ja — rein illustrativ | statischer Bundle-Inhalt (Beispieltext) |

Empfehlung D: Diese sollten **nicht als Substitutionstokens** weiterleben. Entweder direkt in den
Bundle-Text inlinen (DoD/Guardrail/Modules — sie sind projektneutral) oder als deterministischer
Installer-Render aus FK-03 (`REPO_LAYOUT_TABLE`). Ein Render-Token, der nicht im 4er-Vokabular liegt,
ist sonst ein weiterer unauflösbarer Token.

### Disposition-Zählung

- **(A) KEEP: 4** (`GH_OWNER`, `PROJECT_PREFIX`, `GH_REPO_PRIMARY`, `AGENT_SPAWN_SKILL_PROOF`)
- **(B) KEEP-CANDIDATE: 8** (`WIKI_STORIES_DIR`, `GUARDRAILS_DIR`, `CONCEPTS_DIR`,
  `PROJECT_CODEBASE_ROOT`, `USERSTORY_BUNDLE_PATH`, `STORY_SPEC_PATH`, `WIKI_STORIES_INDEX`,
  `PROJECT_NAME`)
- **(C) DROP: ~30** (2 Project-IDs + 12 Field-IDs + ~15 Option-IDs + `GH_REPO_LOCAL_PATH`;
  `GH_CONFIG_EXPORT` als DROP-pending-design)
- **(D) RENDER-BLOCK: 7** (`GH_PROJECT_FIELDS_TABLE` [stirbt], `REPO_LAYOUT_TABLE`, `GUARDRAIL_REFS`,
  `DOD_FEATURE/BUGFIX/CONCEPT/RESEARCH`, `MODULES_EXAMPLE`)
- Block-Direktiven (kein Config-Token, Template-Konditionalsyntax, matchen `\w+` **nicht** und passieren
  den Substitutor heute unersetzt durch): `{{#IF_STORY_VECTORDB}}`/`{{^…}}`/`{{/…}}`,
  `{{#IF_WIKI_INDEX}}`/`{{/…}}`, `{{#IF_CLARIFICATION_ANSWERS}}`. Diese sind ein **separater** Mechanismus
  (konditionales Rendering), den der heutige `string-replace`-Substitutor gar nicht implementiert
  (FK-43 §43.4.2: „Einfaches String-Replace, keine Template-Engine"). ⇒ eigene Designfrage, nicht Teil
  der Token-Vokabular-Korrektur, hier nur als Inkonsistenz festgehalten.

---

## 3. PROPOSED TARGET VOCABULARY (minimal, owner-klar)

Zielzustand: das kleinste Vokabular, das nach Re-Cut **vollständig auflösbar** ist (damit
fail-closed-on-unknown gültig bleibt).

| Token | Klasse | Einzige autoritative Quelle | Timing |
|---|---|---|---|
| `{{gh_owner}}` | A | FK-03 `config.github_owner` | install-time |
| `{{gh_repo}}` | A | FK-03 `config.repositories[0].name` | install-time |
| `{{project_prefix}}` | A | FK-03 `config.project_prefix` (default `project_key.upper()`) | install-time |
| `{{project_key}}` | A | FK-03 `config.project_key` | install-time |
| `{{AGENT_SPAWN_SKILL_PROOF}}` | A* | `.installed-manifest.json → agent_spawn_skill_proof` (AG3-110) | manifest-fed |
| `{{wiki_stories_dir}}` | B | FK-03 §3.1 (Prosa vorhanden) **+ neues `ProjectConfig`-Feld** | install-time |
| `{{guardrails_dir}}` | B | FK-03 §3.1 (Prosa vorhanden) **+ neues `ProjectConfig`-Feld** | install-time |
| `{{concepts_dir}}` | B | **neu** in FK-03 + `ProjectConfig` | install-time |

Optional (nur falls der Re-Cut sie noch braucht — sonst weglassen): `{{project_name}}`
(`config.project_name` existiert), `{{usersory_bundle_path}}`/`{{project_codebase_root}}`/
`{{wiki_stories_index}}` als **derived** (aus Bundle-Root bzw. Projekt-Root bzw. `wiki_stories_dir`),
nicht als Config-Felder.

Regel für FK-43 §43.4.2: **Die 4-Token-Tabelle darf NUR um die begründeten KEEP-CANDIDATEs erweitert
werden**, und ein KEEP-CANDIDATE darf erst in die Tabelle, wenn seine FK-03-Quelle existiert (Prosa
+ Pydantic-Feld). Für `wiki_stories_dir`/`guardrails_dir` bedeutet das: FK-03 §3.1 Prosa steht bereits,
es fehlt nur das `ProjectConfig`-Feld (`config/models.py`). Für `concepts_dir` fehlt beides.
Casing: das Zielvokabular nutzt **lowercase** (FK-43/Substitutor-Konvention); die Bundles werden im
Re-Cut auf lowercase umgestellt (Open Decision 1).

Minimalismus-Begründung: Jeder zusätzliche Token vergrößert die Substitutions-Oberfläche und die
fail-closed-Fläche. Render-Inhalte (DoD, Guardrail-Block, Modules-Beispiel) gehören **inline in die
Bundles**, nicht ins Token-Vokabular.

---

## 4. BUNDLE RE-CUT SCOPE (Skill-Behavior, nicht nur Token-Löschen)

### 4.1 Was sich ändert — Prinzip

Heute beschreiben `create-userstory-core` Step 5/6 und `lookup-userstory-core` Step 2/Reference,
**ein GitHub-Projects-Board zu treiben/zu lesen**:

- `create-userstory-core/4.0.0/SKILL.md:1204-1375` „Step 6: Add to GitHub Project and Set Custom
  Fields": `gh project item-add` (`:1210`), `gh project item-list` (`:1217`), 11×
  `gh api graphql mutation updateProjectV2ItemFieldValue` (`:1250-1372`) mit `{{GH_PROJECT_ID}}`,
  `{{GH_FIELD_*}}`, `{{GH_*_OPTION}}`.
- `create-userstory-core/…:528-557` „Step 4: Determine Next Story ID" liest die Story-ID „from the
  GitHub Project custom field" (`python -m agentkit.stories.next_story_id`, das laut Skill „reads the
  Story ID custom field from the GitHub Project").
- `lookup-userstory-core/…:57-96,110-114` „Source B — GitHub Issue + Project Board": `gh project
  item-list {{GH_PROJECT_NUMBER}}` Match über `storyId`-Board-Feld + `{{REPO_LAYOUT_TABLE}}` +
  „GitHub Project: `{{GH_OWNER}}/projects/{{GH_PROJECT_NUMBER}}`".

Der Re-Cut ersetzt **das Verhalten**: Story-Anlage, Status, Felder, Next-ID und Lookup laufen über das
**AK3-Story-Backend / Control-Plane (FK-91)** — nicht über ein Projects-Board. Das ist kein
Token-Entfernen, sondern ein Umschreiben der Schritte auf die autoritativen AK3-Surfaces.

### 4.2 Konkrete AK3-Surfaces, die der re-cut Skill aufrufen soll

| Skill-Schritt heute (Board) | Re-Cut-Ziel (AK3) | Beleg-Surface |
|---|---|---|
| Step 6c GraphQL-Feld-Mutations | Story-Attribute über Story-Lifecycle-Service setzen | `StoryService.create_story(...)` (`story_creation/create_flow.py:207`, FK-91); FK-21 §21.10.2 „Der Skill ruft den AK3-Story-Service auf … (siehe FK-91)" |
| Step 6a/6b `gh project item-add/item-list` | entfällt — es gibt kein Board | FK-12 §12.7.1 |
| Step 4 Next-Story-ID aus Board-Feld | Next-ID aus AK3-Backend (Story-Contexts/`project_prefix`-Sequenz) | `story/repository.py` (`load_story_contexts_global`); FK-91 (ID-Sequenz im Backend), DK-10 §10.1 |
| Step 5 `gh issue create` (Code-Issue) | **Design-Frage** (§6): bleibt GitHub ein Code-Issue-Träger oder läuft die Story-Anlage rein über das Backend + `story.md`-Export? FK-12 §12.7 listet `gh issue create` NICHT als Pipeline-GitHub-Op. | FK-12 §12.7 Tabelle; FK-21 §21.11 (`export-story-md`) |
| lookup Source B Board-Query | List/Detail über Story-Read-Service | `StoryService.list_stories/get_story` (`story/service.py:34-41`), FK-91 |
| lookup `{{REPO_LAYOUT_TABLE}}` | aus `config.repositories[]` deterministisch | `config/models.py:818` |

Story-Status-Übergänge (Backlog→Approved etc.) sind ausdrücklich AK3-Backend-Operationen
(FK-12 §12.1.1; `control_plane/dispatch.py:73-83` liest persistierten Status). Der Re-Cut entfernt die
Skill-Anweisung, Status „via GitHub Project Board UI or GraphQL CLI" zu setzen
(`create-userstory-core/…:1429-1430`).

### 4.3 Eigene, substanzielle Story (oder Stories)

Dieser Re-Cut ist **kein Anhängsel von AG3-111**. Er umfasst: (a) ein Konzept-Delta für das
Token-Vokabular (FK-43 §43.4.2 um die begründeten KEEP-CANDIDATEs erweitern + FK-03/`ProjectConfig`
um `wiki_stories_dir`/`guardrails_dir`/`concepts_dir`), (b) das Umschreiben von create-userstory-core
auf FK-91-Surfaces, (c) das Umschreiben von lookup-userstory-core auf den Story-Read-Service, (d) das
Inlinen der Render-Blöcke (DoD/Guardrail/Modules) bzw. das deterministische Rendern von
`REPO_LAYOUT_TABLE`. Schnitt-Empfehlung: **Konzept-Delta als eigene (Concept-)Story**, **create-Re-Cut**
und **lookup-Re-Cut** je als eigene Implementation-Story (lookup ist kleiner; create trägt die Hauptlast
und ggf. die Backend-Next-ID-Frage).

AG3-111s Substitutions-Delivery wird erst **nach** diesem Re-Cut korrekt: erst dann tragen die Bundles
ausschließlich auflösbare Tokens, und die fail-closed-on-unknown-Semantik
(`skills/placeholder.py:190-200`) ist nicht mehr falsch-positiv (heute würde sie auf JEDEM Board-Token,
jedem Layout-Token und jedem Render-Token brechen).

---

## 5. IMPACT ON THE PAUSED CHAIN (AG3-111 / 110 / 086)

### 5.1 Heutiger (paused) Zustand

- **AG3-111** (`skills/materialize.py`, `stories/AG3-111-skill-placeholder-read-time-substitution/`):
  liefert substituierten Bundle-Inhalt an den Harness, **wiederverwendet** `PlaceholderSubstitutor`
  (`materialize.py:17-20`), SELF-ATOMIC mit Rollback von Variant-Write + Link bei jedem Fehler
  (`materialize.py:23-26`). Korrekt **als Mechanik** — aber gegen Bundles, die heute ~46
  nicht-auflösbare Tokens tragen, schlägt die Materialisierung fail-closed fehl.
- **AG3-110** (`skills/placeholder.py:47-184`): manifest-fed `{{AGENT_SPAWN_SKILL_PROOF}}`. Unabhängig
  vom Board-Problem, bleibt korrekt.
- **AG3-086** (`stories/AG3-086-hook-guard-buildout/`): Hook-Guard, der den Spawn fail-closed blockiert,
  wenn der Skill-Proof-Header unaufgelöst bleibt (`placeholder.py:12-19`). Hängt am sauberen
  Substitutions-Ende von 111/110.

### 5.2 Wie sich der Re-Cut auswirkt

Sobald die Bundles nur noch das kleine, auflösbare Zielvokabular (§3) tragen:

- **AG3-111** ist als entworfen **korrekt**: Materialisierung + fail-closed-Substitutor stimmen, weil
  jeder verbleibende Token eine Quelle hat. Bekannte Restarbeit unabhängig vom Board-Thema: die
  **Rollback-Atomicity-Fix** (SELF-ATOMIC-Disziplin, `materialize.py:23-26`) — bleibt gültig und ist
  nach dem Re-Cut die einzige offene 111-Korrektur.
- **AG3-110/086** entsperren über das kombinierte E2E (Substitution liefert vollständig auflösbaren
  Header ⇒ Guard lässt Spawn zu, bzw. blockiert nur bei echt fehlendem Proof — nicht mehr
  falsch-positiv wegen Board-Tokens).

### 5.3 Neue Abhängigkeitsreihenfolge (normativ)

```
[Bundle-Re-Cut (create + lookup) + Token-Vokabular-Konzept-Delta (FK-43 §43.4.2 + FK-03/ProjectConfig)]
        │
        ▼
AG3-111 (Rework: gegen das saubere Vokabular + Rollback-Atomicity-Fix)
        │
        ▼
AG3-110 / AG3-086 (Closure via kombiniertem E2E)
```

Begründung der Reihenfolge: AG3-111 darf nicht „grün" werden gegen Bundles, die FK-12/FK-43 verletzen —
sonst zementiert die Substitutions-Delivery ein Vokabular, das die Architektur unterläuft (FIX THE
MODEL, NOT THE SYMPTOM). Der Re-Cut + das Konzept-Delta sind die Vorbedingung.

---

## 6. OPEN DECISIONS (nur echt-offene, Mensch nötig)

1. **Casing-Konvention (final call).** Bundles nutzen UPPERCASE (`{{GH_OWNER}}`, `{{PROJECT_PREFIX}}`),
   FK-43 §43.4.2 + Substitutor (`placeholder.py:38-45`) nutzen lowercase. Aktuell matcht **kein**
   Bundle-Token den Substitutor — das ist real gebrochen. Vorschlag (ableitbar): auf **lowercase**
   vereinheitlichen (FK-43 ist die Token-Autorität). Bestätigung erbeten, weil der Re-Cut alle Bundles
   umschreibt und die Entscheidung einmalig fixiert werden sollte.

2. **KEEP-CANDIDATE-Layout-Tokens: install-time vs. runtime, und config-Feld vs. derived.**
   `wiki_stories_dir`/`guardrails_dir`: FK-03 §3.1-Prosa vorhanden, aber Pydantic-Feld fehlt — als
   echtes `ProjectConfig`-Feld aufnehmen (install-time)? `project_codebase_root`/`usersory_bundle_path`/
   `wiki_stories_index`: als **derived** (aus Projekt-/Bundle-Root) statt Config-Feld? Empfehlung:
   Config-Felder für die drei Verzeichnisse, derived für die Pfade — aber install-time/runtime-Grenze
   braucht die menschliche Entscheidung (FK-43 §43.4.2 ist install-time read-time, AG3-111 liefert
   read-time materialisiert).

3. **Secret-Hygiene / Schicksal von `{{GH_CONFIG_EXPORT}}`.** Hängt an der Designfrage, ob `gh issue
   create` als Code-Issue-Träger bleibt (FK-12 §12.7 listet es NICHT als Pipeline-GitHub-Op) oder ob
   Story-Anlage rein über das Backend + `export-story-md` läuft. Bleibt `gh issue create`, bleibt ein
   Auth-Prelude nötig — dann ist die Secret-Hygiene (`SONARQUBE_TOKEN`-Muster aus FK-03 §3.1: „Verweis
   auf ENV/Secret-Store — NIE inline-Token", `03_…md:177`) auf das `gh`-Token zu übertragen. Entfällt
   `gh issue create`, entfällt `{{GH_CONFIG_EXPORT}}` ⇒ DROP. Reine Skill-Behavior-/Architektur-Frage,
   nicht ableitbar ohne Owner-Intent.

(Bewusst NICHT als Open Decision gelistet, weil ableitbar: alle Board-Tokens der Gruppe C — sie haben
keine FK-03-Quelle und keinen lebenden Konsumenten ⇒ DROP ist die einzige konzepttreue Wahl.
`integrations/github/projects.py`-Entsorgung — separat, nicht Scope dieses Proposals.)

---

## Anhang — zentrale Belegstellen (file:line / §)

- FK-12 §12.1 / §12.1.1 / §12.7.1 — GitHub = Code-Backend, AK3-Story-Backend = Story-Autorität
  (`technical-design/12_github_integration_repo_operationen.md`)
- FK-43 §43.2.3 / §43.4.2 — exakt 4 Tokens, alle aus FK-03 read-only
  (`technical-design/43_skills_system_task_automation.md`)
- FK-21 §21.10.2 / §21.13 — Story-Anlage über AK3-Story-Service (FK-91); Guard gegen Backend-Umgehung
- FK-03 §3.1 Ebene 2 — `wiki_stories_dir`/`guardrails_dir` in Prosa (`…/03_…md:99-101`); 4 FK-03-Quellen
- `src/agentkit/skills/placeholder.py:35,38-45,144-161,190-200` — 4 Tokens + fail-closed
- `src/agentkit/skills/materialize.py:1-26` — AG3-111 Delivery + SELF-ATOMIC Rollback
- `src/agentkit/config/models.py:783-825` — `ProjectConfig` (`extra="forbid"`), FK-03-Felder, KEINE Layout-Dirs
- `src/agentkit/story/{service,repository}.py`, `story_creation/create_flow.py:80,102,207`,
  `control_plane/dispatch.py:73-83` — AK3 Story-/Control-Plane-Surfaces (FK-91)
- `src/agentkit/integrations/github/projects.py` (+ `__init__.py:31-46`) — totes v2-Leftover, 0 Prod-Konsumenten
- Bundles: `create-userstory-core/4.0.0/SKILL.md:1204-1375` (Board-Mechanik),
  `lookup-userstory-core/4.0.0/SKILL.md:57-96,110-114` (Board-Lookup),
  `create-userstory-are/4.0.0/SKILL.md:18,27-29` (bereits AK3-Backend-Sprache)
