---
name: create-userstory
description: >
  Create a new user story (implementation, concept, bugfix, or research). Use when the user
  asks to create, write, or draft a user story — e.g. "erstelle eine User Story fuer ...",
  "erstelle dazu eine User Story", "neue Story anlegen", "create a user story for ...",
  "mach ein Bugfix-Ticket fuer ...", "mach ein Konzept fuer ...", "erstelle eine Research Story".
  Handles GitHub issue creation, project field setup, and wiki directory creation.
argument-hint: "[description or context]"
allowed-tools: "Bash, Read, Glob, Grep, AskUserQuestion, Write, mcp"
---

# Create User Story

Context from user: $ARGUMENTS

## Step 0: Read Project Rules + VectorDB Preflight

Read `{{PROJECT_CODEBASE_ROOT}}/CLAUDE.md` first — all project rules apply.

Then read the full story specification for reference:
```
{{STORY_SPEC_PATH}}
```

**VectorDB Preflight Check (HARD REQUIREMENT):**

Before proceeding with story creation, verify that the VectorDB (Weaviate) is reachable:

```bash
python -m agentkit.vectordb.wait_for_weaviate --timeout 10
```

If exit code is NOT 0: **STOP immediately.** Inform the user:
"VectorDB (Weaviate) is not reachable. Story creation requires a running VectorDB instance.
Please start Weaviate first (docker compose up -d in the vectordb directory)."

Do NOT proceed with story creation if this check fails.

**VectorDB Facts (DO NOT hallucinate these):**
- Weaviate collection name: **`StoryContext`** (NOT "StoryChunk", NOT "Stories")
- Weaviate URL: read from `.story-pipeline.yaml` → `vectordb.url` (typically `http://localhost:9903`)
- Indexing is handled automatically by `python -m agentkit export-story-md` — do NOT call Weaviate directly

## Step 1: Determine Story Type

Evaluate from conversation context which of the **four story types** this is:

- **Implementation**: New functionality, enhancement, infrastructure — produces code + tests. Refactoring may occur as a technique inside implementation work, but is not its own story type. ID schema: `{{PROJECT_PREFIX}}-{NNN}`.
- **Concept**: Analysis, design work, architectural proposals — produces documents, NO code. ID schema: `{{PROJECT_PREFIX}}-{NNN}`.
- **Bugfix**: Fixing a defect in existing code — produces code + reproducing test. ID schema: `{{PROJECT_PREFIX}}-FIX-{NNN}`.
- **Research**: Investigation, experiment, evaluation — produces findings documents, code optional (prototypes). ID schema: `{{PROJECT_PREFIX}}-{NNN}`.

If unclear from context, ask the user.

## Step 2: Target Repo (FIXED — always primary)

**ALL issues are created in `{{GH_OWNER}}/{{GH_REPO_PRIMARY}}` — the project root repo.**
This is a HARD RULE, regardless of single-repo or multi-repo setup.
Code repos (`codebase/*`) are for code only, NEVER for issue tracking.
The GitHub Project aggregates issues from this single source.

## Step 2a: Story-Granularitaet pruefen — PFLICHTSCHRITT

**Grundsatz: So klein wie moeglich, so gross wie noetig.**

Bevor Informationen gesammelt werden, MUSS geprueft werden, ob die Anforderung in **mehrere kleine Stories** aufgeteilt werden sollte. Kleine Stories sind IMMER besser als grosse — sie sind leichter verifizierbar, produzieren weniger Context-Compaction-Probleme bei Agents, und ergeben praezisere Deliverables.

### Was ist eine gute Story-Groesse?

Eine Story umfasst eine **in sich abgeschlossene fachliche Funktionalitaet**, die sich mit Unit-Tests und Integrationstests vollstaendig verifizieren laesst. Diese Funktionalitaet muss NICHT End-to-End sichtbar sein — sie kann sich rein in der API einer Komponente manifestieren (z.B. eine neue Policy, ein neuer Algorithmus, ein Config-Refactoring).

**Zielgroesse: S bis M (1-8 Klassen).** L ist die Ausnahme, nicht die Regel. XL/XXL werden IMMER gesplittet.

### Wann splitten?

Splitten wenn EINER dieser Indikatoren zutrifft:

- **>8 Klassen** betroffen (neu + geaendert) → zu gross
- **Mehrere unabhaengige Concerns** in einem Konzept (z.B. Normalisierung + neue Policies + Hysterese → 3 Stories)
- **Abhaengigkeitskette erkennbar** (A muss vor B fertig sein → A und B sind separate Stories)
- **Verschiedene Module** mit jeweils eigenstaendiger Logik → pro Modul/Concern eine Story
- **"Und ausserdem..."**-Saetze im Scope → jedes "ausserdem" ist ein Split-Kandidat

### Wann NICHT splitten?

- **Eng verzahnte Klassen**, die nur zusammen Sinn ergeben (z.B. ein Record + sein Builder + seine Factory)
- **Eine fachliche Funktion**, die sich zufaellig ueber 2-3 Klassen erstreckt, aber als Einheit getestet wird
- Wenn der Split zu **einzelnen Methoden** fuehren wuerde — eine Story pro Methode ist zu feingranular. AUSNAHME: Wenn die gesamte Anforderung sich tatsaechlich in einer einzigen Methode manifestiert, dann ist das eine valide (kleine) Story.

### Ablauf bei Konzept-Dokumenten

Wenn die Quelle ein Konzeptdokument ist:

1. **Konzept lesen und fachliche Funktionseinheiten identifizieren** (nicht technische Klassen zaehlen)
2. **Abhaengigkeiten zwischen den Einheiten bestimmen**
3. **Pro Funktionseinheit eine Story vorschlagen** (Titel, Scope, Typ, geschaetztes Modul/scope_key)
4. **EINE konsolidierte Review-Vorlage** dem User praesentieren (via AskUserQuestion):
   - Alle vorgeschlagenen Stories mit Titel, Scope, Abhaengigkeiten
   - User entscheidet EINMAL ueber alles: Stories aendern/streichen
5. **Batch-Erstellung** aller genehmigten Stories in Abhaengigkeitsreihenfolge

### Large-Batch Orchestrator Pattern (>15 Stories)

When a concept document produces **more than 15 stories**, a single agent's context
window and ChatGPT's review capacity are strained. Use this pattern:

**Step 1: Size Assessment**

After identifying N functional units in the concept:

```
source_kb = size of concept document(s) in KB
projected_total_kb = source_kb + (N * 7)
```

If N > 15 OR projected_total_kb > 500: switch to Orchestrator Pattern.

**Step 2: Partition into Batches**

Split the N stories into batches of max 15, respecting dependency order.
Stories that depend on each other MUST be in the same batch or in sequential batches
(dependency target before dependent).

**Step 3: Orchestrator delegates to Sub-Agents**

The Orchestrator (you) spawns Sub-Agents sequentially:

```
Orchestrator (main context)
  ├── Sub-Agent 1: create stories 1-15
  │   ├── Per-story ChatGPT review (story-review-single.md + manifest)
  │   └── NO completeness check
  │
  ├── Sub-Agent 2: create stories 16-30
  │   ├── Per-story ChatGPT review (story-review-single.md + manifest)
  │   └── NO completeness check
  │
  └── Orchestrator: Completeness Check (AFTER all sub-agents finish)
```

Each Sub-Agent:
- Receives the FULL concept document + its assigned story range
- Generates a manifest for its batch (including `all_stories_summary` for ALL N stories,
  not just its batch — so ChatGPT knows the overall split)
- Runs per-story ChatGPT reviews (Step 5b Phase 2)
- Does NOT run the completeness check

**Step 4: Orchestrator runs Completeness Check**

After ALL Sub-Agents have finished and ALL stories are created:

1. Collect all N story.md files from disk (they were exported by each Sub-Agent)
2. Concatenate into `_temp_all_stories.md`
3. Run the completeness check (story-review-completeness.md) with:
   - Source: original concept document(s)
   - Stories: ALL N story.md files
   - NO manifest (independent judgment)

If the combined payload (source + all stories) exceeds 500 KB:
Split the completeness check into rounds:

```
Round 1: source + stories 1-15 → "Are these stories consistent with the source?
         List which source requirements they cover."
Round 2: source + stories 16-30 → same question
Round 3: synthesis → "Here are the coverage reports from rounds 1 and 2.
         Are there any source requirements NOT covered by either set?
         Any overlaps between the sets?"
```

4. Report completeness results to the user
5. If gaps/overlaps found → propose fixes before declaring the batch done

**Sub-Agent Prompt Template:**

Each Sub-Agent MUST receive:
```
Read {{PROJECT_CODEBASE_ROOT}}/CLAUDE.md first — all project rules apply.

Task: Create stories {K} through {M} from the attached concept document.
Use the /create-userstory skill for each story.

Context:
- Concept document: {path}
- Total stories planned: {N} (you are creating batch {B} of {total_batches})
- All planned stories (for manifest): {all_stories_summary_json}
- Your stories: {stories_K_through_M_details}

Important:
- Per-story ChatGPT review: YES (Step 5b Phase 2 with manifest)
- Completeness check: NO — the orchestrator handles this after all batches
```

## Step 2b: Related Story Search (mandatory)

Before creating the story, check if similar stories already exist.

{{#IF_STORY_VECTORDB}}
### Semantic + Structural Search

1. Formulate 1-2 search queries from the topic/title of the new story.
2. Call `story_search` MCP tool (or fallback: `python {{USERSTORY_BUNDLE_PATH}}/vectordb/search.py "query"`):
   ```
   story_search(query="<topic keywords>", limit=10)
   ```
3. Additionally, run a structural GitHub search:
   ```bash
   {{GH_CONFIG_EXPORT}}
   gh issue list --repo {{GH_OWNER}}/{{GH_REPO_PRIMARY}} --search "<keywords>" --state all --limit 10
   ```
4. **If semantic search returns results with score > 0.7:**
   - Show the user the top-5 results with Story-ID, Title, Status, Score
   - Ask: "Es gibt aehnliche bestehende Stories. Soll die Story trotzdem angelegt werden?"
   - If yes: add cross-references in "Verwandte Stories" or "Abhaengigkeiten" section of the issue body
   - If no: abort story creation
5. **If no relevant results (all scores < 0.7):** proceed to Step 3
6. Integrate results into the issue body:
   - Related stories → "Verwandte Stories" section
   - Dependencies → "Abhaengigkeiten" section
{{/IF_STORY_VECTORDB}}
{{^IF_STORY_VECTORDB}}
### Structural Search (Fallback — no VectorDB)

Run a GitHub issue search to check for existing similar stories:

```bash
{{GH_CONFIG_EXPORT}}
gh issue list --repo {{GH_OWNER}}/{{GH_REPO_PRIMARY}} --search "<keywords from topic>" --state all --limit 10
```

If matches found: present to user and ask whether to proceed.
{{/IF_STORY_VECTORDB}}

## Step 3: Gather Required Information

If not already clear from conversation context, ask the user for the needed information.

**For Implementation Stories (Pflichtfelder + optionale Quellen):**
- Title (short, descriptive)
- Kontext (why does this story exist? business value? 2-4 sentences)
- Module(s) (e.g. {{MODULES_EXAMPLE}})
- Dependencies (other story IDs, or "Keine")
- In Scope / Out of Scope
- Acceptance criteria (concrete, testable)
- Technical details (classes, patterns, config, API changes — concrete enough for an agent to implement)
- Konzeptquellen (Pfade zu Dateien im `concept/`-Verzeichnis — ganze Dokumente, keine Kapitelreferenzen. Wenn keine Konzepte vorliegen oder sie zu grob sind: `Concept Quality = Low` setzen — das triggert automatisch Exploration in der Pipeline.)
- Externe autoritaere Quellen (optional — URLs zu OpenAPI-Specs, Jira-Artikeln, Schnittstellendokumentationen etc. Bindend fuer die Implementierung.)
- Guardrail references
- Notes for the implementer
- Size estimate (XS/S/M/L/XL/XXL)
- Epic name

**For Bugfix Stories:**
- Title (short, descriptive)
- What is the bug? (observed behavior, expected behavior, reproduction steps)
- Evidenz (screenshots, logs, stack traces — if available)
- Reproducer-Ebene (Unit / Integration / E2E — determines test strategy)
- Root cause analysis (if known — hypothesis only at creation time)
- Proposed fix approach (if known — hypothesis only at creation time)
- Module(s) affected
- Scope / Non-Goals (explicitly: what is NOT being touched)
- Dependencies (other story IDs, or "Keine")
- Konzeptquellen (optional — nur wenn der Bug sich auf ein Konzept bezieht, z.B. "Verhalten weicht von Konzept ab". Pfade zu Dateien im `concept/`-Verzeichnis.)
- Externe autoritaere Quellen (optional — URLs falls der Bug eine externe Schnittstelle betrifft)
- Size estimate (typically XS or S)

**For Concept Stories:**
- Title (short, descriptive)
- Kontext (why this analysis/concept? business need?)
- Fragestellungen (concrete questions to be answered)
- Analyse-Scope (In Scope / Out of Scope)
- Expected deliverables (documents, design proposals)
- Konzeptquellen (optional — ein Feinkonzept kann auf einem Fachkonzept aufbauen. Pfade zu Dateien im `concept/`-Verzeichnis.)
- Externe autoritaere Quellen (optional — URLs zu externen Ressourcen die als Input dienen)
- Guardrail references
- Size estimate (XS/S/M/L)
- Epic name

**For Research Stories:**
- Title (short, descriptive)
- Kontext (why this investigation? what is the trigger?)
- Forschungsfragen (concrete research questions)
- Methodik / Vorgehen (how to investigate? data sources? tools?)
- Erwartete Quelltypen (which source categories are most relevant: academic, official, journalistic, community — helps prioritize search strategy)
- Downstream-Nutzung (where do the results flow? concept story? implementation? strategy amendment?)
- Expected outcomes (what should exist at the end?)
- Module / Bereich (affected area)
- Guardrail references
- Size estimate (XS/S/M/L)
- Epic name

**Hinweis zu Research:** Research-Stories haben keine formalen Konzeptquellen oder externen
autoritaeren Quellen als Eingangsreferenzen. Hintergrundinformationen kommen aus der
Problembeschreibung. Das Ergebnis der Research IST die Quelle, nicht umgekehrt.

## Step 3a: Label-Matching

Lese die kuratierte Label-Liste:

```
Read {{WIKI_STORIES_DIR}}/story-labels.md
```

Wenn die Datei existiert und Labels enthaelt:

1. Vergleiche den Story-Inhalt (Titel, Scope, Kontext, ACs) mit den Label-Beschreibungen.
2. Waehle **1 bis 3** passende Labels aus der Tabelle.
3. Erfinde KEINE neuen Labels — nur aus der Liste waehlen.
4. Wenn kein Label passt: keine Labels vergeben (ist valide).

Die ausgewaehlten Labels werden in Step 5 im `gh issue create`-Aufruf als `--label` gesetzt.

Wenn die Datei leer ist oder nicht existiert: keine Labels vergeben, ohne Warnung fortfahren.

## Step 3b: Concept Discovery Engine (PFLICHTSCHRITT)

Bevor Konzept-Referenzen als Freitext erfasst werden, MUSS eine strukturierte
Konzept-Suche stattfinden. Dieser Schritt spiegel die Rigoroesitaet von Step 3a
(Requirements) fuer Konzept-Referenzen.

### 3b.1 — INDEX.yaml lesen (oder Fallback)

```
Read {{CONCEPTS_DIR}}/INDEX.yaml
```

Wenn INDEX.yaml nicht vorhanden:
- Fallback: `Glob {{CONCEPTS_DIR}}/**/*.md` — alle Konzeptdokumente enumerieren
- Appendix-Verzeichnisse (`appendix/`) erkennen und Companion-Beziehungen ableiten

### 3b.2 — Keyword-Suche (Pflicht) + Semantische Suche (optional, wenn VectorDB MCP verfuegbar)

**Primaerpfad (immer):** Grep-basierte Keyword-Suche ueber `{{CONCEPTS_DIR}}` mit
Schluesselwoertern aus Titel, Scope und ACs:
```bash
Grep "<Schluesselwort-aus-Titel>" {{CONCEPTS_DIR}}
Grep "<Schluesselwort-aus-AC>" {{CONCEPTS_DIR}}
```

**Optionaler Zusatz (nur wenn `concept_search` als MCP-Tool im Skill-Kontext aufrufbar ist):**
```
concept_search(query="<Story-Titel + Scope als Query>", limit=15)
```
Fuer jedes Akzeptanzkriterium zusaetzlich:
```
concept_search(query="<AC-Text>", limit=5)
```
Hinweis: `concept_search` ist ein VectorDB-MCP-Tool und steht nur zur Verfuegung wenn
das AgentKit-VectorDB-MCP-Server-Plugin aktiv und in den erlaubten Tools registriert ist.
Ist es nicht verfuegbar, genuegt der Grep-basierte Primaerpfad vollstaendig.

### 3b.3 — Grep-basierte Exakt-Suche

Klassen-/Interface-Namen, Konfig-Keys, Event-Typen aus den Technischen Details:
```bash
Grep "<KlassenName>" {{CONCEPTS_DIR}}
```

### 3b.4 — Trigger-Rules anwenden

- Story aendert State-Schema → TK-01 + Appendix pruefen
- Story betrifft Pipeline/Routing → TK-08 pruefen
- Story betrifft UI/Farben/Theme → Design-System-Konzept pruefen
- Story betrifft Guard/Policy → TK-06 + Appendix pruefen
- Fuer JEDES selektierte Hauptkonzept → Appendix pruefen (Pflicht, adressiert M-02)
- Erwaehnung von `TK-*`, `AF-*`, `Kap.*` im Story-Body → diese muessen in Referenzen erscheinen

### 3b.5 — Authority-Deferrals verfolgen

Aus INDEX.yaml: `defers_to`-Beziehungen lesen.
Aus Konzept-Text: Cues erkennen (`"→ siehe"`, `"governed by"`, `"defers to"`).
Zielkonzept automatisch als Kandidat aufnehmen, markiert als `[DEFERRAL]`.

### 3b.6 — Exclusion Rationale (Pflicht)

Jedes entdeckte aber nicht referenzierte Konzept MUSS als `excluded` mit Begruendung
dokumentiert werden. Stille Auslassung ist ein Guardrail-Verstoss (adressiert M-01, M-06).

### 3b.7 — Konsistenzpruefung

Story-Inhalt (Scope, ACs, Technische Details) gegen extrahierte Konzept-Regeln abgleichen.
Widersprueche flaggen: `[KONFLIKT] <Inhalt> widerspricht <Konzept> <Abschnitt>`.
Guardrail-Regel: "Concepts are the single source of truth. When a story contradicts
a concept, the concept wins."

### Output: Konzept-Referenz-Matrix

```
--- Konzept-Referenzen (Concept Discovery Engine) ---

Included:
| Konzept | Abschnitt | Typ | Begruendung |
|---------|-----------|-----|-------------|
| `{{CONCEPTS_DIR}}/TK-07-error-routing.md` | Kap. 2+3 | primary | Error-Routing-Spez. |
| `{{CONCEPTS_DIR}}/TK-07-appendix.md` | Appendix I.4 | appendix | Referenz-Impl. |
| `{{CONCEPTS_DIR}}/TK-01-base-state.md` | Kap. 1 | foundational | State-Schema-Modif. |

Excluded (mit Rationale):
| Konzept | Abschnitt | Begruendung |
|---------|-----------|-------------|
| `{{CONCEPTS_DIR}}/TK-09-ui.md` | Kap. 4 | Keine UI-Aenderung in dieser Story |

Konflikte / Deferrals:
- [DEFERRAL] TK-04 → TK-07 fuer Farbsystem (automatisch aufgeloest)
- [KONFLIKT] Story-Farbschema widerspricht TK-07 Kap. 7
```

Diese Matrix wird in Step 3d (Zusammenfassung) dem User praesentiert.

## Step 3c: Repo-Affinitaet bestimmen (PFLICHTSCHRITT)

Bestimme welche Repositories von dieser Story betroffen sind. Dies steuert die
Worktree-Erstellung bei der Execution — ein fehlendes Repo fuehrt dazu, dass der
Worker dort keinen Branch bekommt und auf main arbeitet.

**Ablauf:**

1. Lese `.story-pipeline.yaml` → `repos`-Sektion.
2. Identifiziere ALLE Dateien/Verzeichnisse die von der Story betroffen sind:
   - Aus "Betroffene Dateien" / "Technische Details" (starke Evidenz)
   - Aus "Konzept-Referenzen" die als Aenderungsziel markiert sind (nicht blosse Referenzen)
   - Aus "Scope / In Scope" wenn Pfade genannt werden
3. Ordne jeden Dateipfad einem Repo zu:
   - Pruefe ob der Pfad unter dem `path` eines konfigurierten Repos liegt
   - Laengstes Praefix-Match gewinnt (spezifischster Pfad)
   - Dateien im Projekt-Root (z.B. `concept/`, `stories/`, `docs/`) gehoeren zum Root/Wiki-Repo
4. Bestimme:
   - **PRIMARY_REPO**: Das Repo mit den meisten/wichtigsten Aenderungen
   - **PARTICIPATING_REPOS**: Alle Repos mit mindestens einer betroffenen Datei (komma-separiert)
5. Bei nur einem konfigurierten Repo: PRIMARY_REPO = dieses Repo, PARTICIPATING_REPOS = dieses Repo
6. Wenn ein Dateipfad keinem Repo zugeordnet werden kann: Warnung an den User — das Root/Wiki-Repo
   fehlt moeglicherweise in `.story-pipeline.yaml`.

**WICHTIG:** Das `Module`-Feld ist fachlich (Domaenenzuordnung), NICHT operativ. Module ≠ Repo.
Eine Story kann `Module: backend` haben, aber Dateien im Root-Repo aendern (z.B. API-Contract-Dokumente).
Die Repo-Zuordnung basiert immer auf den tatsaechlichen Dateipfaden, nie auf dem Module-Feld.

Merke dir PRIMARY_REPO und PARTICIPATING_REPOS fuer Step 6c (Project Fields setzen).

## Step 3d: Mode-Determination-Felder bestimmen (PFLICHTSCHRITT)

Diese Felder steuern, ob die Pipeline im **Execution Mode** oder **Exploration Mode**
läuft. Alle drei Felder sind Pflichtfelder. Fehlende oder ungültige Werte → Exploration Mode (fail-closed).

### Change Impact (Pflicht — fail-closed: lieber zu hoch als zu niedrig)

| Wert | Bedeutung |
|------|-----------|
| `Local` | Änderungen bleiben innerhalb einer Klasse/Methode |
| `Component` | Änderungen innerhalb eines Moduls/einer Komponente |
| `Cross-Component` | Mehrere Komponenten betroffen, kein API-Design-Bruch |
| `Architecture Impact` | Neue Schnittstellen, Datenmodelle, externe Integrationen |

F-21-023: Zu niedrig deklarierten Impact erkennt Verify und eskaliert.
Faustregel: neue Klasse/Interface → `Component`; neuer API-Endpunkt → `Architecture Impact`.

### New Structures (Pflicht)

`true` wenn neue APIs, Datenmodelle, Interfaces oder Services eingeführt werden.
`false` wenn nur bestehende Strukturen geändert werden.

### Concept Quality (Pflicht — Default: `High`)

Bewertung der Konzeptqualität für den Story-Scope. REF-032 + Remediation: Pflichtfeld, ersetzt
`Maturity`, `Requires Exploration` und `External Integrations`. Immer setzen — leerer Wert ist ungültig.

| Wert | Bedeutung | Pipeline-Auswirkung |
|------|-----------|---------------------|
| `High` | Konzepte sind vollständig, klar und direkt umsetzbar | Kein Exploration-Trigger (Default) |
| `Medium` | Konzepte sind vorhanden aber haben Lücken | Kein Exploration-Trigger |
| `Low` | Konzepte fehlen oder sind für den Scope zu grob | **Exploration-Trigger** |

Standard-Vorgehen: Immer einen Wert setzen. Default ist `High` — nur abweichen wenn begründet.
Wenn keine Konzepte vorliegen → `Low` setzen (Exploration wird durch Trigger 4 ausgelöst).
Ohne Konzept-Pfade löst Trigger 1 (fehlende valide Konzept-Pfade) zusätzlich Exploration aus.

### Konsistenz-Guidance (Agent prüft, blockiert aber nicht hart)

Folgende Kombinationen sind fast immer fachlich inkonsistent — der Agent soll
sie erkennen und dem User erklären (aber nicht automatisch überschreiben):

- `New Structures=true` + `Change Impact=Local` → sehr unwahrscheinlich, User befragen
- Leere Konzeptquellen bei Implementation + `Concept Quality=High` → Warnung: "Ohne Konzepte löst Trigger 1 (keine validen Konzept-Pfade) automatisch Exploration aus."
- `Concept Quality=Low` + `Change Impact=Local` + `New Structures=false` → unwahrscheinlich (Low deutet auf größere Unsicherheit hin)

Diese Regeln leben **nur im Skill-Prompt**, nicht im Python-Validator. Fachliche
Entscheidungen trifft der Mensch — der Validator prüft nur "gesetzt + gültiger Wert".

### Zusammenfassung zur Bestätigung (AskUserQuestion — einmalig)

Vor Step 4 dem User EINMAL alle Felder inklusive Konzept-Discovery zeigen.
Format fuer AskUserQuestion:

```
=== Story-Analyse fuer: <TITEL> ===

Mode-Determination-Felder (REF-032 + Remediation: 4-Trigger-Modell, kein Maturity):
  Change Impact:   {WERT}  [Trigger 2: Architecture Impact → Exploration]
  New Structures:  {WERT}  [Trigger 3: true → Exploration]
  Concept Quality: {WERT}  [Trigger 4: Low → Exploration] (Pflicht, Default: High)
  Konzept-Pfade:   {vorhanden / fehlen}  [Trigger 1: fehlen → Exploration]
  → Pipeline-Mode: {Execution / Exploration}

--- Konzept-Referenzen (Concept Discovery Engine) ---

Included:
| Konzept | Abschnitt | Typ | Begruendung |
|---------|-----------|-----|-------------|
| ...     | ...       | primary / appendix / foundational / deferral | ... |

Excluded (mit Rationale):
| Konzept | Abschnitt | Begruendung |
|---------|-----------|-------------|
| ...     | ...       | ... |

Konflikte / Deferrals:
- [DEFERRAL] ...
- [KONFLIKT] ...

Externe Quellen: {URLs oder "Keine"}

Aktion: ok / Felder aendern / Referenzen anpassen / Konflikte aufloesen?
```

User entscheidet EINMAL ueber Mode-Felder UND Konzept-Referenzen.

## Step 4: Determine Next Story ID

Story IDs are managed as **project-level sequences**, independent of GitHub issue numbers.
Two separate counters: `{{PROJECT_PREFIX}}-{NNN}` for implementation/concept/research stories, `{{PROJECT_PREFIX}}-FIX-{NNN}` for bugfix stories.

**IMPORTANT:** GitHub issue numbers are NOT story IDs. A story `{{PROJECT_PREFIX}}-097` might be GitHub issue `#102`.
The story ID is determined by scanning existing stories across ALL repos via the GitHub Project.

### Find the next number

Use the `next_story_id` Python module which reads the "Story ID" custom field from the GitHub
Project and cross-checks with wiki directories:

```bash
# For feature stories:
STORY_ID=$(python -m agentkit.stories.next_story_id feature)
echo "Next feature story ID: $STORY_ID"

# For bugfix stories:
STORY_ID=$(python -m agentkit.stories.next_story_id fix)
echo "Next bugfix story ID: $STORY_ID"
```

The script outputs a single line with the next ID (e.g. `{{PROJECT_PREFIX}}-042` or `{{PROJECT_PREFIX}}-FIX-003`).
It reads the `storyId` field from the GitHub Project items and falls back to title parsing for
items where the field is not yet set. Wiki directories are cross-checked as a second source.

Store the determined story ID for all subsequent steps:
- Implementation/Concept/Research: `STORY_ID={{PROJECT_PREFIX}}-{NNN}` (e.g. `{{PROJECT_PREFIX}}-097`)
- Bugfix: `STORY_ID={{PROJECT_PREFIX}}-FIX-{NNN}` (e.g. `{{PROJECT_PREFIX}}-FIX-002`)

## Step 5: Create the GitHub Issue

### Activate Skill Marker

Before creating the issue, set the governance marker so the story-creation-guard hook allows `gh issue create`:

```bash
mkdir -p _temp/governance && echo "$STORY_ID" > _temp/governance/.skill-create-userstory-active
```

### GitHub CLI Prerequisite

All `gh` commands require:
```bash
{{GH_CONFIG_EXPORT}}
```

### IMPORTANT: No Heredocs — Use Temp File + `--body-file`

**Heredocs (`<<'EOF'`) DO NOT WORK in the Bash tool.** The Bash tool wraps commands in
single quotes for `bash -c '...'`. Heredoc delimiters like `<<'ISSUE_EOF'` contain single
quotes that prematurely terminate the outer quoting, causing `unexpected EOF` parse errors.

**Mandatory approach:**
1. Use the **Write tool** to create a temp file at `{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md`
2. Use `gh issue create --body-file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"`
3. **Delete the temp file immediately** after the issue is created: `rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"`

### For Implementation Stories

**Step 5a:** Use the **Write tool** to create `{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md` with the full issue body. Use the following template (fill in all placeholders):

```markdown
## Problem Context
[Why this story exists. Business value. 2-4 sentences.]

## Target State
[What is the desired end state after this story is complete? Describe the system behaviour or
outcome that will be true once the implementation is done. 2-4 sentences.]

## Solution Approach
[High-level implementation approach. Which classes/modules change? Key design decisions.]
- Affected modules/areas: {{MODULES_EXAMPLE}}
- Planned implementation details:
  - [Classes/components to add or modify]
  - [Key configuration, API, or database changes]
  - [External authoritative sources to follow, if any]

## Acceptance Criteria
- AC-1: [Concrete, testable criterion 1]
- AC-2: [Concrete, testable criterion 2]
- AC-3: [Concrete, testable criterion 3]

## Scope

### In Scope
- [Concrete deliverable 1]
- [Concrete deliverable 2]

### Out of Scope
- [What is explicitly NOT part of this story]

## Non-Negotiables
- [Hard constraint 1]
- [Hard constraint 2]

## Dependencies
- [Other story IDs or "None"]

## Concept References
- `{{CONCEPTS_DIR}}/XX-yyy.md` - Chapter N - primary - primary specification
- `{{CONCEPTS_DIR}}/ZZ-zzz.md` - Chapter N - excluded on purpose; document here only if that exclusion matters for scope

## Guardrail References
{{GUARDRAIL_REFS}}

## Definition of Done
{{DOD_FEATURE}}
```

**STOP: Before creating the issue, execute Steps 5a-section-validate, 5a.1 and 5b below. Return here only after ALL are PASS.**

### Step 5a-section-validate: Story Section Validation (PFLICHTSCHRITT)

**After writing the issue body temp file and BEFORE the concept reference validation:**

Validate the issue body against the canonical section schema. The story body must contain
all required sections (Target State, Acceptance Criteria, Definition of Done) with meaningful
content — not placeholder text.

```bash
python -m agentkit story validate --file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

**Exit codes:**
- `0` (PASS): All required sections present with meaningful content. Proceed.
- `1` (WARN): Warnings present. **Fix the warnings before proceeding.** Only PASS (exit 0) is acceptable.
- `2` (FAIL): Required sections missing or empty. **Fix the issue body before proceeding.**

If FAIL: Fix the missing/empty sections in the temp file and re-validate. Do NOT proceed
with a FAIL result — the pipeline will produce warnings or errors during execution.

**Step 5c:** Create the issue using `--body-file` and delete the temp file:

```bash
{{GH_CONFIG_EXPORT}}

ISSUE_URL=$(gh issue create --repo {{GH_OWNER}}/{{GH_REPO_PRIMARY}} \
  --title "${STORY_ID}: <Title>" \
  <LABEL_FLAGS> \
  --body-file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md")

ISSUE_NR=$(echo "$ISSUE_URL" | grep -oP '\d+$')
echo "Created GitHub issue #$ISSUE_NR with story ID $STORY_ID: $ISSUE_URL"

rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

Replace `<LABEL_FLAGS>` with `--label "<label>"` for each label selected in Step 3a.
If no labels were selected: omit the `--label` flag entirely.

### For Bugfix Stories

**Step 5a:** Use the **Write tool** to create `{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md` with the bugfix issue body. Template:

```markdown
## Problem Context
[What happens currently? Include observed behaviour, expected behaviour, repro steps,
available evidence, and error messages.]
- Observed behaviour: [What happens currently?]
- Expected behaviour: [What should happen instead?]
- Reproduction steps:
  1. [Step 1]
  2. [Step 2]
  3. [Step 3]
- Available evidence: [Screenshots, logs, stack traces, or "No external evidence available"]

## Target State
[What is the desired end state once this bug is fixed? Describe the correct system behaviour
that will be true after the fix is applied. 2-4 sentences.]

## Solution Approach
[Root cause analysis + proposed fix approach - which classes/methods change how?
"Noch nicht analysiert" is acceptable at creation time.]
- Affected modules/areas: [Affected module(s)]
- Reproducer level: [Unit / Integration / E2E]
- Planned code/test touch points:
  - [File or component 1]
  - [File or component 2]

## Acceptance Criteria
- AC-1: [Concrete, testable criterion: bug no longer reproducible]
- AC-2: [Reproducer test added and passing]
- AC-3: [No regression in existing tests]

## Scope

### In Scope
- [What will be fixed - concrete and narrow]

### Out of Scope
- [What is explicitly NOT part of this fix - no refactoring, no feature additions]

## Non-Negotiables
- [No hidden refactoring beyond the fix scope]
- [No behavioural regression in existing supported flows]

## Dependencies
- [Other story IDs or "None"]

## Concept References
- [List exact concept refs if the bug is constrained by concepts; otherwise "None at story creation."]

## Guardrail References
{{GUARDRAIL_REFS}}

## Definition of Done
{{DOD_BUGFIX}}
```

**STOP: Before creating the issue, execute Steps 5a-section-validate, 5a.1 and 5b below. Return here only after ALL are PASS.**

### Step 5a-section-validate: Story Section Validation (PFLICHTSCHRITT)

**After writing the issue body temp file and BEFORE the concept reference validation:**

Validate the issue body against the canonical section schema. The story body must contain
all required sections (Target State, Acceptance Criteria, Definition of Done) with meaningful
content — not placeholder text.

```bash
python -m agentkit story validate --file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

**Exit codes:**
- `0` (PASS): All required sections present with meaningful content. Proceed.
- `1` (WARN): Warnings present. **Fix the warnings before proceeding.** Only PASS (exit 0) is acceptable.
- `2` (FAIL): Required sections missing or empty. **Fix the issue body before proceeding.**

If FAIL: Fix the missing/empty sections in the temp file and re-validate. Do NOT proceed
with a FAIL result — the pipeline will produce warnings or errors during execution.

**Step 5c:** Create the issue and delete the temp file:

```bash
{{GH_CONFIG_EXPORT}}

ISSUE_URL=$(gh issue create --repo {{GH_OWNER}}/{{GH_REPO_PRIMARY}} \
  --title "${STORY_ID}: <Title>" \
  <LABEL_FLAGS> \
  --body-file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md")

ISSUE_NR=$(echo "$ISSUE_URL" | grep -oP '\d+$')
echo "Created GitHub issue #$ISSUE_NR with story ID $STORY_ID: $ISSUE_URL"

rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

Replace `<LABEL_FLAGS>` with `--label "<label>"` for each label selected in Step 3a.

### For Concept Stories

**Step 5a:** Use the **Write tool** to create `{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md` with the concept issue body. Template:

```markdown
## Problem Context
[Warum diese Analyse/dieses Konzept? Business-Bedarf? 2-4 sentences.]

## Target State
[What is the desired end state once this concept/analysis is complete? What knowledge,
design decisions, or documents will exist that do not exist today? 2-4 sentences.]

## Solution Approach
[How will the analysis/design be performed? What questions must be answered, what artefacts
must be produced, and which area is affected?]
- Affected modules/areas: {{MODULES_EXAMPLE}}
- Key questions:
  - [Concrete question 1]
  - [Concrete question 2]
- Expected deliverables:
  - [Document 1]
  - [Document 2]

## Acceptance Criteria
- AC-1: [Fragestellung 1 beantwortet mit Begruendung]
- AC-2: [Analyse-/Design-Dokument erstellt und reviewed]

## Scope
### In Scope
- [Was wird analysiert/designed]
### Out of Scope
- [Was wird NICHT analysiert]

## Non-Negotiables
- [Name the hard design constraints or architectural boundaries]
- [State any mandatory output quality bar or review expectation]

## Dependencies
- [Other story IDs or "None"]

## Concept References
- `{{CONCEPTS_DIR}}/fachkonzept.md` - Chapter N - primary - input for this analysis
- [Add further exact concept references or "None at story creation"]

## Guardrail References
{{GUARDRAIL_REFS}}

## Definition of Done
{{DOD_CONCEPT}}
```

**STOP: Before creating the issue, execute Steps 5a-section-validate, 5a.1 and 5b below. Return here only after ALL are PASS.**

### Step 5a-section-validate: Story Section Validation (PFLICHTSCHRITT)

**After writing the issue body temp file and BEFORE the concept reference validation:**

Validate the issue body against the canonical section schema. The story body must contain
all required sections (Target State, Acceptance Criteria, Definition of Done) with meaningful
content — not placeholder text.

```bash
python -m agentkit story validate --file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

**Exit codes:**
- `0` (PASS): All required sections present with meaningful content. Proceed.
- `1` (WARN): Warnings present. **Fix the warnings before proceeding.** Only PASS (exit 0) is acceptable.
- `2` (FAIL): Required sections missing or empty. **Fix the issue body before proceeding.**

If FAIL: Fix the missing/empty sections in the temp file and re-validate. Do NOT proceed
with a FAIL result — the pipeline will produce warnings or errors during execution.

**Step 5c:** Create the issue and delete the temp file:

```bash
{{GH_CONFIG_EXPORT}}

ISSUE_URL=$(gh issue create --repo {{GH_OWNER}}/{{GH_REPO_PRIMARY}} \
  --title "${STORY_ID}: <Title>" \
  <LABEL_FLAGS> \
  --body-file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md")

ISSUE_NR=$(echo "$ISSUE_URL" | grep -oP '\d+$')
echo "Created GitHub issue #$ISSUE_NR with story ID $STORY_ID: $ISSUE_URL"

rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

Replace `<LABEL_FLAGS>` with `--label "<label>"` for each label selected in Step 3a.

### For Research Stories

**Step 5a:** Use the **Write tool** to create `{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md` with the research issue body. Template:

```markdown
## Problem Context
[Warum diese Untersuchung? Was ist der Anlass? 2-4 sentences.]

## Target State
[What is the desired end state once this research is complete? What findings, recommendations,
or documents will exist? 2-4 sentences.]

## Solution Approach
[How will the research be conducted? Which questions, source classes, and downstream uses matter?]
- Research questions:
  - [Research question 1]
  - [Research question 2]
- Methodology: [How the investigation will be performed]
- Expected source classes: [official, academic, institutional, expert, community, ...]
- Downstream use: [What this research will inform next]
- Affected modules/areas: [Affected area/module]

## Acceptance Criteria
- AC-1: [Forschungsfrage 1 beantwortet - mit Quellennachweis]
- AC-2: [Forschungsfrage 2 beantwortet - mit Quellennachweis]
- AC-3: [Findings dokumentiert (research.md)]
- AC-4: [Quellenregister vollstaendig (sources.md)]
- AC-5: [Empfehlungen formuliert (downstream-faehig)]

## Scope

### In Scope
- [Was wird untersucht? Welche Aspekte, Technologien, Quellen?]

### Out of Scope
- [Was wird NICHT untersucht? Keine Implementation, kein Prototyp, etc.]

## Non-Negotiables
- [Use primary/authoritative sources wherever possible]
- [No implementation or prototype work inside this story]

## Dependencies
- [Other story IDs or "None"]

## Concept References
- [List exact concept refs if this research depends on them; otherwise "None at story creation."]

## Guardrail References
{{GUARDRAIL_REFS}}

## Definition of Done
{{DOD_RESEARCH}}
```

**STOP: Before creating the issue, execute Steps 5a-section-validate, 5a.1 and 5b below. Return here only after ALL are PASS.**

### Step 5a-section-validate: Story Section Validation (PFLICHTSCHRITT)

**After writing the issue body temp file and BEFORE the concept reference validation:**

Validate the issue body against the canonical section schema. The story body must contain
all required sections (Target State, Acceptance Criteria, Definition of Done) with meaningful
content — not placeholder text.

```bash
python -m agentkit story validate --file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

**Exit codes:**
- `0` (PASS): All required sections present with meaningful content. Proceed.
- `1` (WARN): Warnings present. **Fix the warnings before proceeding.** Only PASS (exit 0) is acceptable.
- `2` (FAIL): Required sections missing or empty. **Fix the issue body before proceeding.**

If FAIL: Fix the missing/empty sections in the temp file and re-validate. Do NOT proceed
with a FAIL result — the pipeline will produce warnings or errors during execution.

**Step 5c:** Create the issue and delete the temp file:

```bash
{{GH_CONFIG_EXPORT}}

ISSUE_URL=$(gh issue create --repo {{GH_OWNER}}/{{GH_REPO_PRIMARY}} \
  --title "${STORY_ID}: <Title>" \
  <LABEL_FLAGS> \
  --body-file "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md")

ISSUE_NR=$(echo "$ISSUE_URL" | grep -oP '\d+$')
echo "Created GitHub issue #$ISSUE_NR with story ID $STORY_ID: $ISSUE_URL"

rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"
```

Replace `<LABEL_FLAGS>` with `--label "<label>"` for each label selected in Step 3a.

## Step 5a-validate: Konzeptquellen-Validierung (PFLICHTSCHRITT)

**Nach dem Erstellen des Issue-Body und VOR dem ChatGPT-Review:**

Wenn der Issue-Body eine `## Konzept-Referenzen`-Sektion mit Pfaden enthält
(nicht nur den Platzhalter), validiere JEDEN referenzierten Pfad:

1. Beginnt der Pfad mit `concept/`? (Konzeptquellen muessen im `concept/`-Verzeichnis liegen)
2. Ist der Pfad relativ zum Projektroot (kein `..`, kein absoluter Pfad)?
3. Existiert die Datei unter diesem Pfad?
4. Ist die Datei nicht leer?

```bash
# Fuer jeden Pfad in Konzept-Referenzen:
PFAD="{PFAD}"
if [[ "$PFAD" != concept/* ]]; then
  echo "FEHLER: $PFAD liegt nicht im concept/-Verzeichnis"
elif [[ "$PFAD" == *..* ]]; then
  echo "FEHLER: $PFAD enthaelt Path-Traversal"
elif ! test -s "{{PROJECT_CODEBASE_ROOT}}/$PFAD"; then
  echo "FEHLER: $PFAD nicht gefunden oder leer"
else
  echo "OK: $PFAD"
fi
```

**Bei FEHLER:** STOP. Melde dem User welche Referenz nicht aufloesbar ist.
Keine stille Akzeptanz. Der User muss den Pfad korrigieren oder die Referenz
entfernen, bevor die Story erstellt wird.

**Externe Quellen** (URLs etc.) werden NICHT validiert — Erreichbarkeit
externer Systeme kann sich aendern und ist zur Erstellungszeit nicht garantiert.

## Step 5a.1: Body-to-Reference Konsistenzcheck (PFLICHTSCHRITT)

**Nach Step 5a-validate, VOR dem ChatGPT-Review:**

Pruefe ob jede `TK-*`- und `AF-*`-Erwaehnung im Issue-Body in der
Konzept-Referenzen-Tabelle steht.

**Option A — Python-Validator (bevorzugt):**
```bash
python {{PROJECT_CODEBASE_ROOT}}/userstory/tools/validate_concept_refs.py \
  --issue-body {{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md \
  --concept-root {{CONCEPTS_DIR}} \
  --index {{CONCEPTS_DIR}}/INDEX.yaml
```
Exit-Code 0 = PASS. Exit-Code 1 = Findings.

**Option B — Manuell (wenn Python nicht verfuegbar):**
1. Extrahiere alle `TK-*`, `AF-*`, `Kap.*`, `Section *` und `Appendix *` aus dem Issue-Body
   (ausserhalb der Referenzen-Sektion)
2. Vergleiche mit den Pfaden in der `## Konzept-Referenzen`-Tabelle
3. Jede Erwaehnung ohne Match → `[HARD STOP]`

**Bei HARD STOP:** Entweder Referenz in die Tabelle aufnehmen ODER
Erwaehnung aus dem Body entfernen. Kein stilles Ueberspringen.

## Step 5b: ChatGPT Story Review (MANDATORY)

**Every story MUST be reviewed by ChatGPT before the issue is created.**
This review is template-based — you provide structured DATA (manifests), never the review prompt.
The prompt comes EXCLUSIVELY from the template files in `prompts/`.

### 5b.1 Size Guard — BEFORE any review

Calculate the projected total review payload:

```
source_material_kb = total size of ALL input documents in KB
projected_stories_kb = N_stories * 7  (average 7 KB per story)
total_projected_kb = source_material_kb + projected_stories_kb
```

**If total_projected_kb > 500:** STOP. Inform the user:
"The combined review input (source material + projected story content) would be ~{total_projected_kb} KB,
which exceeds the 500 KB limit for reliable ChatGPT review. Consider:
- Creating fewer stories per batch (split the work into multiple rounds)
- Reducing the scope of source material per round
Current breakdown: {source_material_kb} KB source + {N_stories} stories * 7 KB = {total_projected_kb} KB"

Do NOT proceed with story creation until the user confirms a smaller scope.

This guard also protects your own context window — creating stories from megabytes of input
degrades your own output quality.

### 5b.2 Prepare Source Context

Write `{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md` using the Write tool.
This file MUST contain ALL input material that was used to create this story/these stories:

- **User request**: The original $ARGUMENTS or conversation context
- **Concept documents**: FULL relevant sections (not just paths)
- **Feature lists**: The relevant entries
- **Architecture docs**: The relevant sections
- **Guardrail references**: The relevant passages

Format: Concatenate all sources with clear `## Source: <name>` headings.

### 5b.3 Route: Single-Story or Batch?

**Determine the review strategy based on how many stories are being created:**

---

#### Single-Story Review (Szenario A/B: one story, no split)

Use template: `prompts/story-review-standalone.md`

**Phase 0 — Sufficiency Probe (neuer erster Send, PFLICHT):**

1. `llm_acquire(owner="create-story-review", llms=["chatgpt"], description="Story review for single story creation")`
2. **Phase 0 Send** — Context-Sufficiency-Probe:
   `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: "Bevor du das Review startest: Welche zusaetzlichen Dokumente, Sektionen, Appendices oder Konzepte brauchst du, um ein optimales Review zu geben? Antworte NUR mit: CONTEXT_SUFFICIENT — oder — NEEDS_CONTEXT: <komma-separierte Liste>"
   - `merge_paths`: `["{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md", "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"]`
3. **Auswerten:**
   - Bei `CONTEXT_SUFFICIENT`: direkt zu Phase 1.
   - Bei `NEEDS_CONTEXT: <Liste>`:
     a. Direkte Datei-Reads der genannten Dokumente (Pflichtpfad).
        Optional, wenn `concept_search` als MCP-Tool im Kontext verfuegbar ist:
        `concept_search(query="<Begriff>", limit=5)` fuer jeden genannten Begriff.
     b. Appende die gefundenen Inhalte an `_temp_source_context.md`.
     c. Weiter zu Phase 1. **Maximal eine Gap-Closure-Runde.**

**Phase 1 — Eigentliches Review:**

4. `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: Content of `prompts/story-review-standalone.md` (read the file, do NOT paraphrase)
   - `merge_paths`: `["{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md", "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"]`
5. Parse `VERDICT: PASS` or `VERDICT: REWORK`
6. `llm_release(session_id="...", token="...")`
7. Cleanup: `rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md"`

---

#### Batch Review (Szenario C/D/E: N stories from shared source)

Three phases: (1) per-story manifest review, (2) completeness check, (3) release.

**Phase 1: Generate Manifest**

Write `{{PROJECT_CODEBASE_ROOT}}/_temp_manifest.json` with this structure:

```json
{
  "creation_scenario": "N stories from 1 concept",
  "source_documents": ["concept-xy.md"],
  "total_stories": 5,
  "decomposition_rationale": "Split by implementation phases: ...",
  "requirements_mapping": [
    {
      "story_id": "BB2-030",
      "story_title": "...",
      "covers": ["Concept section 4.1-4.3"],
      "not_covers": ["Sections 4.4-4.9 → other stories"],
      "rationale": "Focuses on error detection only"
    }
  ],
  "all_stories_summary": [
    "BB2-030: Error detection (Concept 4.1-4.3)",
    "BB2-031: Retry logic (Concept 4.4-4.5)",
    "BB2-032: Monitoring (Concept 4.6-4.9)"
  ]
}
```

**YOU provide the manifest data. YOU do NOT write the review prompt.**

**Phase 2: Per-Story Reviews (one ChatGPT session)**

Use template: `prompts/story-review-single.md`

1. `llm_acquire(owner="create-story-batch-review", llms=["chatgpt"], description="Batch story review for N stories from concept")`
2. **First send** — manifest + source + template + first story:
   `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: Content of `prompts/story-review-single.md`
   - `merge_paths`: `["{{PROJECT_CODEBASE_ROOT}}/_temp_manifest.json", "{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md", "{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"]`
3. Parse `VERDICT` for story 1. On REWORK → handle (see below).
4. **Subsequent sends** (stories 2..N) — update `_temp_issue_body.md` with next story, then:
   `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: "Review the next story draft per the same template and manifest:"
   - `merge_paths`: `["{{PROJECT_CODEBASE_ROOT}}/_temp_issue_body.md"]`
   (Manifest + source context retained from send 1)
5. Parse `VERDICT` for each story.

**Do NOT release the ChatGPT session yet — Phase 3 follows.**

**Phase 3: Completeness Check (the closing bracket)**

Use template: `prompts/story-review-completeness.md`

This check runs AFTER all individual story reviews pass. It uses a DIFFERENT
template that does NOT include the manifest — ChatGPT must judge independently.

1. Write ALL story drafts into `{{PROJECT_CODEBASE_ROOT}}/_temp_all_stories.md`
   (concatenate all N drafts with `---` separators and story IDs as headings)
2. `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: Content of `prompts/story-review-completeness.md`
   - `merge_paths`: `["{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md", "{{PROJECT_CODEBASE_ROOT}}/_temp_all_stories.md"]`
   (Note: NO manifest — ChatGPT judges coverage independently)
3. Parse `COMPLETENESS VERDICT`
4. `llm_release(session_id="...", token="...")`
5. Cleanup: `rm -f "{{PROJECT_CODEBASE_ROOT}}/_temp_source_context.md" "{{PROJECT_CODEBASE_ROOT}}/_temp_manifest.json" "{{PROJECT_CODEBASE_ROOT}}/_temp_all_stories.md"`

---

### On PASS (individual story)

Proceed to Step 5c for that story (create the GitHub Issue).

### On REWORK (individual story)

1. Show ChatGPT's feedback to the user
2. Ask: "ChatGPT has flagged issues with story {ID}. Shall I rework it?"
3. If yes: rework the story, regenerate `_temp_issue_body.md`, re-send for review
4. If no (user overrides): proceed to Step 5c — document the override in the issue body

### On GAPS_FOUND / OVERLAPS_FOUND / ISSUES_FOUND (completeness check)

1. Show the completeness analysis to the user
2. For gaps: propose additional stories or scope extensions
3. For overlaps: propose scope adjustments to eliminate duplication
4. User decides how to proceed

## Step 6: Add to GitHub Project and Set Custom Fields

**Step 6a: Add issue to the project:**

```bash
{{GH_CONFIG_EXPORT}}
gh project item-add {{GH_PROJECT_NUMBER}} --owner {{GH_OWNER}} --url "$ISSUE_URL"
```

**Step 6b: Get the project item ID:**

```bash
{{GH_CONFIG_EXPORT}}
ITEM_ID=$(gh project item-list {{GH_PROJECT_NUMBER}} --owner {{GH_OWNER}} --format json --limit 200 | python -c "
import sys, json
data = json.loads(sys.stdin.read())
target_repo = '{{GH_OWNER}}/{{GH_REPO_PRIMARY}}'
for item in data.get('items', []):
    content = item.get('content', {})
    # Match by issue number AND repository to avoid cross-repo collisions
    repo = content.get('repository', '')
    nr = content.get('number', -1)
    if nr == $ISSUE_NR and (not repo or target_repo in repo):
        print(item['id'])
        break
")
echo "Item ID: $ITEM_ID"
```

**If ITEM_ID is empty:** The item may not have appeared in the project yet (race condition).
Wait 3 seconds and retry once. If still empty, report the error.

**Step 6c: Set custom fields via GraphQL:**

Project ID: `{{GH_PROJECT_ID}}`

Field IDs and option IDs:

{{GH_PROJECT_FIELDS_TABLE}}

Set all fields (replace placeholders):

```bash
{{GH_CONFIG_EXPORT}}

# Status = Backlog
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_STATUS_ID}}",
    value: { singleSelectOptionId: "{{GH_STATUS_BACKLOG_OPTION}}" }
  }) { projectV2Item { id } }
}'

# Story ID (custom field)
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_STORY_ID_ID}}",
    value: { text: "'"$STORY_ID"'" }
  }) { projectV2Item { id } }
}'

# Size (replace <SIZE_OPTION_ID> with correct ID from table above)
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_SIZE_ID}}",
    value: { singleSelectOptionId: "<SIZE_OPTION_ID>" }
  }) { projectV2Item { id } }
}'

# Module
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_MODULE_ID}}",
    value: { text: "<MODULE>" }
  }) { projectV2Item { id } }
}'

# Primary Repo (from Step 3b — canonical repo ID, e.g. "backend", "root")
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_PRIMARY_REPO_ID}}",
    value: { text: "<PRIMARY_REPO>" }
  }) { projectV2Item { id } }
}'

# Participating Repos (from Step 3b — comma-separated canonical repo IDs, e.g. "root, backend")
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_PARTICIPATING_REPOS_ID}}",
    value: { text: "<PARTICIPATING_REPOS>" }
  }) { projectV2Item { id } }
}'

# Epic
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_EPIC_ID}}",
    value: { text: "<EPIC>" }
  }) { projectV2Item { id } }
}'

# Story Type (replace <STORY_TYPE_OPTION_ID> with correct ID from table above)
# Options: Implementation={{GH_STORY_TYPE_IMPLEMENTATION_OPTION}}, Concept={{GH_STORY_TYPE_CONCEPT_OPTION}},
#          Bugfix={{GH_STORY_TYPE_BUGFIX_OPTION}}, Research={{GH_STORY_TYPE_RESEARCH_OPTION}}
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_STORY_TYPE_ID}}",
    value: { singleSelectOptionId: "<STORY_TYPE_OPTION_ID>" }
  }) { projectV2Item { id } }
}'

# Created At (today's date)
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_CREATED_AT_ID}}",
    value: { date: "'"$(date +%Y-%m-%d)"'" }
  }) { projectV2Item { id } }
}'

# Change Impact
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_CHANGE_IMPACT_ID}}",
    value: { singleSelectOptionId: "<CHANGE_IMPACT_OPTION_ID>" }
  }) { projectV2Item { id } }
}'
# Options: {{GH_CHANGE_IMPACT_LOCAL_OPTION}} | {{GH_CHANGE_IMPACT_COMPONENT_OPTION}} | {{GH_CHANGE_IMPACT_CROSS_COMPONENT_OPTION}} | {{GH_CHANGE_IMPACT_ARCHITECTURE_IMPACT_OPTION}}

# New Structures
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_NEW_STRUCTURES_ID}}",
    value: { singleSelectOptionId: "<NEW_STRUCTURES_OPTION_ID>" }
  }) { projectV2Item { id } }
}'
# Options: {{GH_NEW_STRUCTURES_TRUE_OPTION}} | {{GH_NEW_STRUCTURES_FALSE_OPTION}}

# Concept Quality (Pflicht — immer setzen, Default: "High")
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "{{GH_PROJECT_ID}}",
    itemId: "'"$ITEM_ID"'",
    fieldId: "{{GH_FIELD_CONCEPT_QUALITY_ID}}",
    value: { singleSelectOptionId: "<CONCEPT_QUALITY_OPTION_ID>" }
  }) { projectV2Item { id } }
}'
# Options: {{GH_CONCEPT_QUALITY_HIGH_OPTION}} | {{GH_CONCEPT_QUALITY_MEDIUM_OPTION}} | {{GH_CONCEPT_QUALITY_LOW_OPTION}}
# Low → triggert Exploration in der Pipeline. High = Standard.
# Low → triggert Exploration in der Pipeline. Bei Concept/Research nicht relevant (kein Exploration-Mode).
```

### Remove Skill Marker

Issue and project fields are set — remove the governance marker:

```bash
rm -f _temp/governance/.skill-create-userstory-active
```

## Step 7: Create Wiki Story Directory and Export story.md

```bash
STORY_DIR="{{WIKI_STORIES_DIR}}/${STORY_ID}_<kebab-case-slug>"
mkdir -p "$STORY_DIR"
```

**IMPORTANT: Do NOT write story.md yourself using the Write tool.**
Instead, run the deterministic export command which fetches the issue from GitHub,
writes an exact copy with YAML frontmatter, AND indexes the story in VectorDB:

```bash
python -m agentkit export-story-md \
  --story-id "$STORY_ID" \
  --issue-nr $ISSUE_NR \
  --story-dir "$STORY_DIR" \
  --story-type "<STORY_TYPE>" \
  --module "<MODULE>" \
  --epic "<EPIC>"
```

This command does THREE things in one deterministic step:
1. Fetches the issue via `gh issue view`
2. Writes `story.md` with YAML frontmatter (1:1 copy of GitHub Issue)
3. Indexes the story in VectorDB (Weaviate) for semantic search

If the command fails (including VectorDB indexing failure), report the error —
do NOT fall back to writing story.md manually or skipping indexing.

## Step 8: Present Summary

After all steps complete, present to the user:

```
Story created:
- Story ID: {{PROJECT_PREFIX}}-{NNN} (or {{PROJECT_PREFIX}}-FIX-{NNN})
- GitHub Issue: #<ISSUE_NR> in {{GH_OWNER}}/<REPO>
- Project: Added to {{PROJECT_NAME}} — Status=Backlog, Story ID=<STORY_ID>, Size=<SIZE>, Module=<MODULE>, Epic=<EPIC>, Created=<DATE>
- Wiki: {{WIKI_STORIES_DIR}}/<STORY_DIR>/story.md
- URL: <ISSUE_URL>

Note: GitHub issue number (#<ISSUE_NR>) and story ID (<STORY_ID>) are independent.
The story ID is the canonical reference used in prompts, telemetry, and directory names.

Status is Backlog. To start execution, set the status to "Approved" first
(via GitHub Project Board UI or GraphQL CLI update with option "{{GH_STATUS_APPROVED_OPTION}}").
```
