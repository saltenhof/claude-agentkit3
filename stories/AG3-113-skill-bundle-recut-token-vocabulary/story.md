# AG3-113: Skill-Bundle-Re-Cut — GitHub-Projects-Tokens raus, Token-Vokabular-Korrektur, create/lookup auf AK3-Control-Plane

**Typ:** Implementation (mit vorgelagertem Konzept-Delta via Approval-Flow)
**Groesse:** L
**Bounded Context:** `agent-skills` (FK-43, Bundles + `PlaceholderSubstitutor`-Vokabular) als Hauptlast; Konzept-Delta in **FK-43 §43.4.2** + **FK-03 §3.1** (+ `config/models.py` `ProjectConfig`); Verhaltens-Re-Cut der Skills `create-userstory-core` + `lookup-userstory-core` auf die bestehenden **AK3-Story-Backend-/Control-Plane-Surfaces (FK-91)**. Cleanup des toten v2-Adapters `integrations/github/projects.py`.

**Quell-Konzepte (autoritativ):**
- `FK-12 §12.1.1 / §12.7.1` — GitHub ist **Code-Backend**, nicht Story-Tracker. Story-Identitaet/-Status/-Attribute/-Closure/-Dependencies laufen ueber das AK3-Story-Backend (FK-17/FK-18/FK-91), nicht ueber GitHub. **Kein** `gh project` / `gh api graphql` auf ein Board, **kein** Board-Status-Setzen.
- `FK-43 §43.2.3 / §43.4.2` — **Token-Autoritaet**: der Substitutor ist read-only auf FK-03; „Nur in `.md`-Dateien. Einfaches String-Replace, keine Template-Engine"; fail-closed-on-unknown. Die autoritative Token-Tabelle wird hier auf **lowercase** korrigiert und **minimal** um die begruendeten Layout-Tokens erweitert.
- `FK-03 §3.1` — Projekt-Layout/Config-Quelle. Ebene-2-Prosa nennt `wiki_stories_dir: stories` und `guardrails_dir: _guardrails` bereits; das **Pydantic-Feld fehlt** im `ProjectConfig` (`config/models.py`, `extra="forbid"`). `concepts_dir` fehlt in Prosa **und** Modell.
- `FK-91` — Control-Plane-API + Story-Service (Anlage/Status/Attribute/List/Detail). `StoryService.create_story(...)` (`story_creation/create_flow.py:207`) ist der autoritative Story-Lifecycle-Owner.
- `FK-21 §21.10.2 / §21.11` — Story-Anlage ruft den **AK3-Story-Service**; `export-story-md` fuer Index/Wiki.
- `01_systemkontext §1.2` — „Story-Verwaltung laeuft ueber das AK3-Story-Backend, nicht ueber externe Project-Boards."

**PO-Entscheidungen (2026-06-12, verbindlich):**
- **D1 = lowercase**: alle Bundle-Tokens werden auf die FK-43-lowercase-Konvention umgestellt (heute UPPERCASE, matcht **keinen** Substitutor-Token — eigenstaendiger Bug).
- **D3 = Story-Anlage voll ueber AK3-Control-Plane**: `gh project`, `gh api graphql`, **und** `gh issue create` entfallen aus den Skills; `{{GH_CONFIG_EXPORT}}` (gh-Auth-Prelude) wird **gedroppt**. GitHub bleibt ausschliesslich Code-Backend (Branch/PR/Push) — kein Story-Traeger.
- **D2 = Proposal-Minimal**: nur die nach dem Re-Cut **tatsaechlich noch benoetigten** Layout-Tokens ueberleben, und zwar als typisierte FK-03/`ProjectConfig`-Felder; alles, was sich inlinen oder deterministisch ableiten laesst, wird **nicht** Token.
- **Toter Code mitnehmen**: `integrations/github/projects.py` (+ Re-Export) wird entsorgt.

---

## 1. Kontext / Ist-Zustand (belegt)

**Konzepte bereits sauber, Templates nicht — das ist der zu schliessende Drift.**

- **Konzepte fuehren kein GitHub-Projects mehr:** `concept/.../01_systemkontext_und_architekturprinzipien.md:211-213` schliesst externe Boards explizit aus; FK-12 §12.1.1 macht GitHub zum Code-Backend. Woertliche Suche `gh project`/`GH_FIELD`/`GH_PROJECT`/„GitHub Projects" ueber `concept/` = **0 Treffer**. **Die Konzeptebene ist nicht Gegenstand des Re-Cuts** (nur das additive Vokabular-Delta, s. Scope).
- **Die zwei ausgelieferten Bundles tragen noch ~30 Board-Tokens + 12× `{{GH_CONFIG_EXPORT}}`:**
  - `src/agentkit/resources/skill_bundles/create-userstory-core/4.0.0/SKILL.md` — „Step 6: Add to GitHub Project and Set Custom Fields" (`:1204-1375`): `gh project item-add` (`:1210`), `gh project item-list` (`:1217`), 11× `gh api graphql mutation updateProjectV2ItemFieldValue` (`:1250-1372`) mit `{{GH_PROJECT_ID}}`/`{{GH_FIELD_*}}`/`{{GH_*_OPTION}}`; „Step 4: Determine Next Story ID" (`:528-557`) liest die ID angeblich „from the GitHub Project custom field"; Status-Setzen „via GitHub Project Board UI or GraphQL CLI" (`:1429-1430`).
  - `src/agentkit/resources/skill_bundles/lookup-userstory-core/4.0.0/SKILL.md` — „Source B — GitHub Issue + Project Board" (`:57-96,110-114`): `gh project item-list {{GH_PROJECT_NUMBER}}`, Board-Feld-Match, `{{REPO_LAYOUT_TABLE}}`, „GitHub Project: {{GH_OWNER}}/projects/{{GH_PROJECT_NUMBER}}".
- **Casing-Bruch (eigenstaendiger Bug):** Bundles nutzen `{{GH_OWNER}}`/`{{PROJECT_PREFIX}}` (UPPERCASE), `PlaceholderSubstitutor._MANDATORY_PLACEHOLDERS` (`skills/placeholder.py:38-45`) kennt nur lowercase `gh_owner/gh_repo/project_prefix/project_key`. **Kein** Bundle-Token matcht aktuell — der Substitutor wuerde auf jedem heute brechen.
- **Die AK3-Backend-Fundamente existieren bereits** (Re-Cut ist Verdrahtung auf vorhandene Owner, kein Neubau):
  - Next-Story-ID-Sequenz: Tabelle `story_number_counters(project_key, next_story_number)` in **beiden** Stores (`state_backend/sqlite_store.py:143,1223-1229`; `postgres_store.py:333-338`, INSERT…ON CONFLICT-Increment). Der Skill-Kommentar „reads … from the GitHub Project" (`create-…:538`) ist **stale** — die Wahrheit ist der Backend-Counter.
  - Story-Anlage/-Status/-Attribute: `StoryService.create_story(...)` (`story_creation/create_flow.py:207`, FK-91); `python -m agentkit story validate` und `python -m agentkit export-story-md` werden vom Skill bereits aufgerufen (`create-…:650/1397`).
  - Story-Read (Lookup): `StoryService.list_stories/get_story` (`story/service.py:34-41`); Repo-Layout deterministisch aus `config.repositories[]` (`config/models.py:818`).
- **Toter v2-Adapter:** `integrations/github/projects.py` (332 Z.) implementiert `gh project`/GraphQL-Operationen; **kein** Konsument ausserhalb `integrations/github/` (nur Re-Export `integrations/github/__init__.py`). v2-Leftover, FK-12-§12.1-widrig, funktionslos.
- **Konditionale Block-Direktiven** (`{{#IF_STORY_VECTORDB}}`/`{{^…}}`/`{{/…}}`, `{{#IF_WIKI_INDEX}}`, `{{#IF_CLARIFICATION_ANSWERS}}`) matchen `\w+` **nicht** und passieren den Substitutor heute unersetzt. Sie sind ein **separater** Render-Mechanismus (nicht Teil dieser Vokabular-Korrektur) — hier nur als Inkonsistenz festgehalten, **nicht** in Scope (s. Out of Scope).

## 2. Scope

### 2.1 In Scope

1. **Konzept-Delta (ZUERST, via Codex-Approval-Flow — kein stiller Konzept-Edit):**
   - **FK-43 §43.4.2:** die autoritative Token-Tabelle auf **lowercase** fixieren (D1) und **minimal** um genau die Layout-Tokens erweitern, die der Re-Cut (Scope 2.2/2.3) **nachweislich noch braucht**. Ein Layout-Token darf erst in die Tabelle, wenn seine FK-03-Quelle (Prosa **und** Pydantic-Feld) existiert.
   - **FK-03 §3.1 + `config/models.py` `ProjectConfig`:** fuer die ueberlebenden Layout-Tokens je ein typisiertes, install-time `ProjectConfig`-Feld (Kandidaten laut Proposal §3: `wiki_stories_dir`, `guardrails_dir`, `concepts_dir`). **Nur** aufnehmen, was ein ueberlebender Token wirklich referenziert; alles Ableitbare bleibt **derived** (z. B. `project_codebase_root`/`userstory_bundle_path`/`wiki_stories_index`), kein Config-Feld.
   - Ablauf strikt: **Codex absegnen (write=false) → Edit `concept/…` + `config/models.py` → Codex re-review → GAC-1/Concept-Gates gruen.** Erst danach der Bundle-Re-Cut.
2. **`PlaceholderSubstitutor`-Vokabular an FK-43 angleichen:** den bekannten Token-Satz (`_MANDATORY_PLACEHOLDERS` + Config-Value-Mapping, `skills/placeholder.py:38-161`) auf die korrigierte FK-43-Tabelle bringen (lowercase 4 KEEP + die ueberlebenden Layout-Tokens 1:1 auf die neuen `ProjectConfig`-Felder). **FK-43 ist die Autoritaet** — der Code folgt dem Konzept. `{{AGENT_SPAWN_SKILL_PROOF}}` (AG3-110) bleibt unveraendert. Keine Template-Engine, weiterhin reines String-Replace + fail-closed-on-unknown.
3. **`create-userstory-core/4.0.0/SKILL.md` Verhaltens-Re-Cut (D3):**
   - **Step 6 (Board)** vollstaendig entfernen: kein `gh project item-add/item-list`, keine `gh api graphql` Field-Mutations; Story-Attribute/Status werden ueber den **AK3-Story-Lifecycle-Service / Control-Plane (FK-91)** gesetzt (Story-Anlage ruft `StoryService.create_story(...)` bzw. die Control-Plane-Operation; die Skill-Schritte beschreiben den AK3-Pfad).
   - **Step 4 Next-ID:** auf den AK3-Backend-Counter (`story_number_counters`) verdrahten; der stale „reads from GitHub Project"-Kommentar wird korrigiert. Existiert die `next_story_id`-Modul-Surface nicht backend-gespeist, **fail-closed melden** statt Board-Fallback.
   - **`gh issue create` + `{{GH_CONFIG_EXPORT}}`** entfernen (D3): Story-Anlage laeuft ueber das Backend + `export-story-md`; kein gh-Auth-Prelude mehr.
   - alle verbliebenen Board-/Option-/Field-/Project-Tokens **droppen**; Render-Blocks (DoD-Templates `{{DOD_*}}`, `{{GUARDRAIL_REFS}}`, `{{MODULES_EXAMPLE}}`) **inline** in den Bundle-Text schreiben (projektneutral); `{{REPO_LAYOUT_TABLE}}` deterministisch aus `config.repositories[]` (inline-Render-Anweisung oder Installer-Render) statt Token.
4. **`lookup-userstory-core/4.0.0/SKILL.md` Verhaltens-Re-Cut (D3):**
   - „Source B — GitHub Issue + Project Board" entfernen; Lookup laeuft ueber den **Story-Read-Service** (`StoryService.list_stories/get_story`, FK-91); kein `gh project item-list`, keine Board-Feld-Matches, keine „GitHub Project: …/projects/…"-Referenz.
   - `{{REPO_LAYOUT_TABLE}}` wie oben (aus `config.repositories[]`), alle Board-Tokens droppen.
5. **Vokabular-Endzustand verifizieren:** nach dem Re-Cut tragen **beide** SKILL.md (und alle weiteren `.md` der zwei Bundles) ausschliesslich Tokens aus der korrigierten FK-43-Tabelle (lowercase 4 KEEP + ggf. ueberlebende Layout-Tokens + `{{AGENT_SPAWN_SKILL_PROOF}}`). `PlaceholderSubstitutor.substitute_spawn_header(content, config, project_root)` ueber jede dieser `.md` **loest vollstaendig auf** — **kein** `UnknownPlaceholderError`, **kein** residualer `{{...}}`-Token (Ausnahme: die absichtlichen Nicht-`{{}}`-Marker `<STORY-ID>`/`<ROUND>` und die konditionalen Block-Direktiven `{{#…}}`/`{{^…}}`/`{{/…}}`, die ein separater Mechanismus sind — s. Out of Scope).
6. **Toten v2-Adapter entsorgen:** `integrations/github/projects.py` loeschen + den Re-Export aus `integrations/github/__init__.py` entfernen; vorher belegen, dass **kein** lebender Konsument existiert (Grep ueber `src/`, ausgenommen `integrations/github/` selbst + Tests). Die zugehoerigen reinen Selbsttests (`tests/unit/integrations/github/test_projects.py`, opt-in `tests/e2e/github_live/test_projects.py`) entsprechend mit entfernen.
7. **Tests + Belege:** s. §3 — Vokabular-Vollaufloesung beider Bundles (real, kein Stub des Substitutors), `ProjectConfig`-Feld-Roundtrip + Defaults, kein lebender Konsument von `projects.py` mehr (Import-/Grep-Assertion), Skill-Inhalt frei von Board-Tokens/`gh project`/`gh api graphql`/`gh issue create`/`{{GH_CONFIG_EXPORT}}`.

### 2.2 Out of Scope (mit Owner)

- **AG3-111-Substitutions-Delivery-Surface** (materialisierte Skill-Variante, Read-Time-Auslieferung) — **AG3-111**. Diese Story macht die Bundles nur *aufloesbar*; das Ausliefern an den Harness-Bindungspunkt ist AG3-111.
- **`{{AGENT_SPAWN_SKILL_PROOF}}` / `substitute_spawn_header` / Manifest-Producer / Token-Stabilitaet** — **AG3-110**. Bleibt unveraendert; nur in `execute-userstory-core` vorhanden, **nicht** Gegenstand dieses Re-Cuts.
- **Konditionales Block-Rendering** (`{{#IF_…}}`/`{{^…}}`/`{{/…}}`) — separater Render-Mechanismus, **nicht** Teil der Vokabular-Korrektur. Falls noetig, eigene Story; hier nur geflaggt (FK-43 §43.4.2: „keine Template-Engine").
- **`execute-userstory-core` Bundle** — traegt keine Board-Tokens (nur `{{PROJECT_PREFIX}}`/`{{USERSTORY_BUNDLE_PATH}}`/`{{AGENT_SPAWN_SKILL_PROOF}}`); soweit es **lowercase**/Layout-Token-Anpassungen braucht, die das gemeinsame Vokabular betreffen, mitziehen — aber **kein** Verhaltens-Re-Cut (keine Board-Schritte vorhanden).
- **AG3-086 prompt-integrity guard** — fremder Owner, unveraendert.
- **Generelle GitHub-Integrations-Refaktorierung** (`client.py`/`issues.py`) — nur `projects.py` ist hier in Scope; `gh`/`git`-Code-Operationen (Branch/PR/Push, FK-12 §12.7) bleiben unangetastet.
- **AK2 / `.mcp.json`** — nicht anfassen.

### 2.3 Methodischer Hinweis (Minimalitaet)

Der Re-Cut **minimiert** die Token-Oberflaeche aktiv: jeder vermeidbare Token (Render-Inhalt, ableitbarer Pfad) wird inline/derived statt Token. Ziel ist das **kleinste vollstaendig aufloesbare Vokabular**, damit fail-closed-on-unknown gueltig bleibt. Ein Layout-`ProjectConfig`-Feld wird **nur** geschaffen, wenn ein ueberlebender Token es referenziert; sonst nicht.

## 3. Akzeptanzkriterien

1. **Konzept-Delta via Approval-Flow:** FK-43 §43.4.2 fuehrt die korrigierte (lowercase) Token-Tabelle inkl. der genau benoetigten Layout-Tokens; FK-03 §3.1 + `ProjectConfig` tragen die zugehoerigen typisierten install-time Felder (mit Default + Validierung). Der Konzept-Edit ist via Codex absegnen → Edit → re-review erfolgt; GAC-1 + Concept-Gates (`check_concept_frontmatter.py`, `compile_formal_specs.py`) gruen.
2. **Substitutor-Vokabular == FK-43:** `PlaceholderSubstitutor` kennt genau die FK-43-Tabelle (lowercase), mappt die Layout-Tokens 1:1 auf die neuen `ProjectConfig`-Felder; unbekannte Tokens brechen weiterhin fail-closed (`UnknownPlaceholderError`). Test: jeder Tabellen-Token loest auf; ein nicht-gelisteter bricht.
3. **create-userstory-core board-frei + AK3-verdrahtet:** Im re-cut `SKILL.md` gibt es **kein** `gh project`, **kein** `gh api graphql` (Board), **kein** `gh issue create`, **kein** `{{GH_CONFIG_EXPORT}}`, **keinen** `{{GH_FIELD_*}}`/`{{GH_*_OPTION}}`/`{{GH_PROJECT_*}}`-Token. Story-Anlage/-Status/-Attribute/Next-ID laufen ueber AK3 (StoryService/Control-Plane + `story_number_counters` + `export-story-md`). Test/Assertion: Inhaltsscan + Verweis auf die AK3-Surfaces.
4. **lookup-userstory-core board-frei + AK3-verdrahtet:** keine „Source B"-Board-Query, kein `gh project item-list`, keine Board-Feld-Matches; Lookup ueber `StoryService.list_stories/get_story`; `{{REPO_LAYOUT_TABLE}}` aus `config.repositories[]`. Test/Assertion: Inhaltsscan.
5. **Vokabular vollstaendig aufloesbar (Kernkriterium, NO-STUB):** `PlaceholderSubstitutor.substitute_spawn_header(...)` ueber **jede** `.md` der beiden Bundles laeuft ohne `UnknownPlaceholderError` durch; das Ergebnis enthaelt **keinen** residualen `{{...}}`-Token (ausser `<STORY-ID>`/`<ROUND>` und den konditionalen `{{#…}}`/`{{^…}}`/`{{/…}}`-Direktiven). Test gegen ein reales `ProjectConfig` + reales Manifest, kein Mock des Substitutors.
6. **Casing (D1):** kein UPPERCASE-`{{...}}`-Config-Token mehr in den re-cut Bundles; alle Config-Tokens lowercase. Test: Grep-Assertion.
7. **Toter Adapter entsorgt:** `integrations/github/projects.py` existiert nicht mehr; der Re-Export ist aus `integrations/github/__init__.py` entfernt; `import agentkit.integrations.github` und ein Grep ueber `src/` belegen **keinen** lebenden `projects`-Konsumenten; Suite gruen ohne die entfernten Selbsttests.
8. **Idempotenz/Determinismus:** wiederholte Substitution desselben Bundles + Configs ist byte-identisch (Vorbereitung fuer AG3-111-Materialisierung). Test.
9. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/skills`, `tests/unit/config`, `tests/unit/integrations`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff check src tests`; GAC-1 `check_architecture_conformance.py` (0 Errors); Concept-Gates; Coverage >= 85 %.

## 4. Definition of Done

- AK 1–9 erfuellt; Konzept-Delta (AK1) via Approval-Flow; giftiges Doppel-Review (Codex + Fable) PASS.
- AG3-111 wird durch diese Story entblockt: nach dem Re-Cut tragen die Bundles ausschliesslich aufloesbare Tokens, und AG3-111s Substitutions-Delivery (materialisierte Variante) ist gegen die realen Bundles ausfuehrbar. `AG3-111.depends_on += AG3-113` (Metadaten-Nachzug, bereits eingetragen).
- Commit/Push erst nach grünem Doppel-Review (Orchestrator-Policy). `.mcp.json` nicht mitcommitten.

## 5. Guardrail-Referenzen

- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** Story-Wahrheit liegt im AK3-Backend (FK-12 §12.1.1); der Re-Cut baut **keine** zweite Story-Wahrheit auf GitHub-Board-Basis weiter, sondern ruft die vorhandenen FK-91-Surfaces. Token-Vokabular hat **eine** Autoritaet (FK-43 §43.4.2); der Substitutor-Code folgt dem Konzept.
- **KONZEPT-APPROVAL:** FK-43/FK-03-Delta NUR ueber den Codex-Absegnungs-Flow (kein stiller Konzept-Edit).
- **FAIL-CLOSED / NO ERROR BYPASSING:** fail-closed-on-unknown bleibt; kein Board-Fallback, kein Dummy-Token, kein weicher Pfad. Fehlt eine AK3-Surface (z. B. backend-gespeiste Next-ID), wird das gemeldet, nicht umgangen.
- **TYPISIERT STATT STRINGS:** Layout-Tokens nur mit typisiertem `ProjectConfig`-Feld (Default + Validierung), englische Bezeichner.
- **ARCH-55:** Code/Bezeichner/Config-Felder englisch; Konzept-/Skill-Prosa darf deutsch/englisch bleiben wie bestehend; keine deutschen Wire-/Config-Keys.
- **ZERO DEBT:** keine halben Board-Reste, kein totes `projects.py` mehr, keine unaufloesbaren Tokens.
- **Globale Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (GAC-1 0 Errors, GAC-2 Architektur-Guardrails) gelten.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Reihenfolge ist verbindlich:** erst Konzept-Delta (FK-43/FK-03 + `ProjectConfig`) via Codex-Approval-Flow, dann Substitutor-Vokabular, dann Bundle-Re-Cut, dann Vokabular-Verifikation, dann Dead-Code. Substituiere nie gegen ein Bundle, dessen Tokens das Konzept/der Substitutor noch nicht kennt.
- **Minimalismus:** bevorzuge Inline (DoD/Guardrail/Modules) und Derived (Pfade) gegenueber neuen Tokens/Config-Feldern. Schaffe ein `ProjectConfig`-Feld **nur**, wenn ein ueberlebender Token es braucht. Belege je ueberlebendem Layout-Token die FK-03-Quelle.
- **AK3-Surfaces sind gebaut — verdrahten, nicht neu bauen:** `StoryService.create_story` (`story_creation/create_flow.py:207`), `StoryService.list_stories/get_story` (`story/service.py:34-41`), Next-ID `story_number_counters` (`state_backend/{sqlite,postgres}_store.py`), `python -m agentkit story validate` / `export-story-md`. Pruefe die **reale** `next_story_id`-Modul-Surface: liest sie schon den Backend-Counter, nur der Kommentar ist stale, dann Kommentar korrigieren; liest sie wirklich ein Board-Feld, auf den Counter umstellen; fehlt sie, fail-closed melden.
- **`placeholder.py` darfst du fuer das Vokabular anpassen** (das ist Teil dieser Vokabular-Korrektur, FK-43-Autoritaet) — aber **nicht** `substitute_spawn_header`/den Manifest-Pfad (AG3-110) und **nicht** die AG3-086-Guard-Logik.
- **Konditionale Block-Direktiven nicht „loesen":** `{{#IF_…}}`/`{{^…}}`/`{{/…}}` sind ein separater Mechanismus (Out of Scope). Lass sie stehen; sie matchen das `\w+`-Token-Muster nicht und passieren den Substitutor.
- **Dead-Code zuletzt + belegt:** vor dem Loeschen von `projects.py` Grep-Beleg „kein lebender Konsument" (ausser Re-Export + Selbsttests). Re-Export aus `__init__.py` mit entfernen; entfernte Selbsttests dokumentieren.
- AK2 / `.mcp.json` nicht anfassen. Kein Commit/Push ohne expliziten Orchestrator-Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (Vokabular-Vollaufloesung beider Bundles, ProjectConfig-Feld-Roundtrip, board-frei-Assertion create+lookup, casing-Assertion, projects.py-kein-Konsument), Konzept-Approval-Beleg (Codex-Absegnung + re-review).

## 7. Offene Punkte (explizit)

- **Konkrete ueberlebende Layout-Token-Liste:** wird beim Re-Cut empirisch bestimmt (welche Tokens nach Inlining/Derive real noch im Bundle stehen). Default-Erwartung laut Proposal §3: ggf. `wiki_stories_dir`/`guardrails_dir`/`concepts_dir` als Config-Felder; `project_codebase_root`/`userstory_bundle_path`/`wiki_stories_index` derived. Wenn der Re-Cut **gar kein** Layout-Token uebrig laesst (alles inline/derived/4-KEEP), entfaellt das FK-03/`ProjectConfig`-Feld-Delta — das ist der sauberste Ausgang und ausdruecklich erlaubt.
- **`next_story_id`-Modul-Realzustand:** vor dem Re-Cut verifizieren (Backend-Counter vs. Board-Feld vs. fehlend) und entsprechend verdrahten/melden.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md`:
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (`PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`).
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN); Konflikt = hart stoppen und melden.
