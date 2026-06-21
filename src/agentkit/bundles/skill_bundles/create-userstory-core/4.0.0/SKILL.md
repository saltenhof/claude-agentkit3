---
name: create-userstory
description: >
  Create a new user story (implementation, concept, bugfix, or research). Use when the user
  asks to create, write, or draft a user story — e.g. "erstelle eine User Story fuer ...",
  "erstelle dazu eine User Story", "neue Story anlegen", "create a user story for ...",
  "mach ein Bugfix-Ticket fuer ...", "mach ein Konzept fuer ...", "erstelle eine Research Story".
  Creates the story in the AK3 Story-Backend (control plane) and the wiki story directory.
argument-hint: "[description or context]"
allowed-tools: "Bash, Read, Glob, Grep, AskUserQuestion, Write, mcp"
---

# Create User Story

Context from user: $ARGUMENTS

Story identity, status, attributes and lifecycle are owned by the **AK3 Story-Backend**
(control plane), not by GitHub. GitHub is the **code backend only** (branches, PRs;
FK-12 §12.1.1). This skill creates the story via the deployed AK3 control-plane tool
`projectedge create-story` — there is NO `gh issue create`, NO `gh project`, NO
`gh api graphql` board mutation, and NO standalone next-story-id step. The backend
allocates the Story-ID atomically and validates the story in a non-bypassable
create boundary.

## Step 0: Read Project Rules + VectorDB Preflight

Read `CLAUDE.md` (project root) first — all project rules apply.

**VectorDB Preflight Check (HARD REQUIREMENT):**

Before proceeding with story creation, verify that the VectorDB (Weaviate) is reachable:

```bash
python -m agentkit.backend.vectordb.wait_for_weaviate --timeout 10
```

If exit code is NOT 0: **STOP immediately.** Inform the user:
"VectorDB (Weaviate) is not reachable. Story creation requires a running VectorDB instance.
Please start Weaviate first (docker compose up -d in the vectordb directory)."

Do NOT proceed with story creation if this check fails. The control-plane create
boundary also fails closed on an unavailable VectorDB (the reconciliation gate),
so a green preflight avoids a late fail-closed rejection.

**VectorDB Facts (DO NOT hallucinate these):**
- Weaviate collection name: **`StoryContext`** (NOT "StoryChunk", NOT "Stories")
- Weaviate URL: read from `.story-pipeline.yaml` → `vectordb.url` (typically `http://localhost:9903`)
- Indexing and the related-story reconciliation are handled by the control-plane
  create boundary and `python -m agentkit export-story-md` — do NOT call Weaviate directly

## Step 1: Determine Story Type

Evaluate from conversation context which of the **four story types** this is:

- **Implementation**: New functionality, enhancement, infrastructure — produces code + tests. Refactoring may occur as a technique inside implementation work, but is not its own story type. ID schema: `{{project_prefix}}-{NNN}`.
- **Concept**: Analysis, design work, architectural proposals — produces documents, NO code. ID schema: `{{project_prefix}}-{NNN}`.
- **Bugfix**: Fixing a defect in existing code — produces code + reproducing test. ID schema: `{{project_prefix}}-FIX-{NNN}`.
- **Research**: Investigation, experiment, evaluation — produces findings documents, code optional (prototypes). ID schema: `{{project_prefix}}-{NNN}`.

If unclear from context, ask the user.

## Step 2: Target Repos

The story records its participating repositories (Step 3c). Code repos are for code
only — story identity and tracking live in the AK3 Story-Backend, never on a
GitHub Project board.

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
Read CLAUDE.md (project root) first — all project rules apply.

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

Before creating the story, check if similar stories already exist. The related-story
search runs against the **AK3 Story-Backend** (FK-91 Story-Read-Service) and the
VectorDB — never against GitHub issues.

{{#IF_STORY_VECTORDB}}
### Semantic + Structural Search

1. Formulate 1-2 search queries from the topic/title of the new story.
2. Call the `story_search` MCP tool (semantic VectorDB search over the AK3
   Story-Backend's indexed stories):
   ```
   story_search(query="<topic keywords>", limit=10)
   ```
3. Additionally, run a structural search over the local wiki story directory
   (the authoritative local mirror that `agentkit export-story-md` writes 1:1
   from the backend story; FK-91 §91.1a `/v1/projects/{project_key}/stories/search?q=`
   is the corresponding server-side read surface):
   ```bash
   ls {{wiki_stories_dir}}/ | grep -i "<keywords>"
   grep -ril "<keywords>" {{wiki_stories_dir}}/
   ```
4. **If semantic search returns results with score > 0.7:**
   - Show the user the top-5 results with Story-ID, Title, Status, Score
   - Ask: "Es gibt aehnliche bestehende Stories. Soll die Story trotzdem angelegt werden?"
   - If yes: add cross-references in "Verwandte Stories" or "Abhaengigkeiten" section of the story body
   - If no: abort story creation
5. **If no relevant results (all scores < 0.7):** proceed to Step 3
6. Integrate results into the story body:
   - Related stories → "Verwandte Stories" section
   - Dependencies → "Abhaengigkeiten" section

The atomic create boundary (Step 5c) additionally runs the fail-closed VectorDB
reconciliation incl. the LLM adjudicator against the backend, so a near-duplicate
that slips through here is still caught at creation time.
{{/IF_STORY_VECTORDB}}
{{^IF_STORY_VECTORDB}}
### Structural Search (Fallback — no VectorDB)

Search the local wiki story directory (the authoritative local mirror written
1:1 from the backend by `agentkit export-story-md`) for existing similar stories:

```bash
ls {{wiki_stories_dir}}/ | grep -i "<keywords from topic>"
grep -ril "<keywords from topic>" {{wiki_stories_dir}}/
```

If matches found: present to user and ask whether to proceed. The create boundary
(Step 5c) still runs the backend-side reconciliation fail-closed regardless.
{{/IF_STORY_VECTORDB}}

## Step 3: Gather Required Information

If not already clear from conversation context, ask the user for the needed information.

**For Implementation Stories (Pflichtfelder + optionale Quellen):**
- Title (short, descriptive)
- Kontext (why does this story exist? business value? 2-4 sentences)
- Module(s) (e.g. backend, frontend, pipeline)
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
Read {{wiki_stories_dir}}/story-labels.md
```

Wenn die Datei existiert und Labels enthaelt:

1. Vergleiche den Story-Inhalt (Titel, Scope, Kontext, ACs) mit den Label-Beschreibungen.
2. Waehle **1 bis 3** passende Labels aus der Tabelle.
3. Erfinde KEINE neuen Labels — nur aus der Liste waehlen.
4. Wenn kein Label passt: keine Labels vergeben (ist valide).

Die ausgewaehlten Labels werden in Step 5 als `--label`-Argumente an das
`projectedge create-story`-Tool uebergeben.

Wenn die Datei leer ist oder nicht existiert: keine Labels vergeben, ohne Warnung fortfahren.

## Step 3b: Concept Discovery Engine (PFLICHTSCHRITT)

Bevor Konzept-Referenzen als Freitext erfasst werden, MUSS eine strukturierte
Konzept-Suche stattfinden. Dieser Schritt spiegelt die Rigoroesitaet von Step 3a
(Requirements) fuer Konzept-Referenzen. Konzeptquellen liegen im `concept/`-Verzeichnis.

### 3b.1 — INDEX.yaml lesen (oder Fallback)

```
Read concept/INDEX.yaml
```

Wenn INDEX.yaml nicht vorhanden:
- Fallback: `Glob concept/**/*.md` — alle Konzeptdokumente enumerieren
- Appendix-Verzeichnisse (`appendix/`) erkennen und Companion-Beziehungen ableiten

### 3b.2 — Keyword-Suche (Pflicht) + Semantische Suche (optional, wenn VectorDB MCP verfuegbar)

**Primaerpfad (immer):** Grep-basierte Keyword-Suche ueber `concept/` mit
Schluesselwoertern aus Titel, Scope und ACs:
```bash
Grep "<Schluesselwort-aus-Titel>" concept/
Grep "<Schluesselwort-aus-AC>" concept/
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
Grep "<KlassenName>" concept/
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
| `concept/TK-07-error-routing.md` | Kap. 2+3 | primary | Error-Routing-Spez. |
| `concept/TK-07-appendix.md` | Appendix I.4 | appendix | Referenz-Impl. |
| `concept/TK-01-base-state.md` | Kap. 1 | foundational | State-Schema-Modif. |

Excluded (mit Rationale):
| Konzept | Abschnitt | Begruendung |
|---------|-----------|-------------|
| `concept/TK-09-ui.md` | Kap. 4 | Keine UI-Aenderung in dieser Story |

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
   - **PARTICIPATING_REPOS**: Alle Repos mit mindestens einer betroffenen Datei
5. Bei nur einem konfigurierten Repo: PRIMARY_REPO = dieses Repo, PARTICIPATING_REPOS = dieses Repo
6. Wenn ein Dateipfad keinem Repo zugeordnet werden kann: Warnung an den User — das Root/Wiki-Repo
   fehlt moeglicherweise in `.story-pipeline.yaml`.

**WICHTIG:** Das `Module`-Feld ist fachlich (Domaenenzuordnung), NICHT operativ. Module ≠ Repo.
Eine Story kann `Module: backend` haben, aber Dateien im Root-Repo aendern (z.B. API-Contract-Dokumente).
Die Repo-Zuordnung basiert immer auf den tatsaechlichen Dateipfaden, nie auf dem Module-Feld.

Merke dir PRIMARY_REPO und PARTICIPATING_REPOS — sie werden in Step 5 als `--repo`-Argumente
an das `projectedge create-story`-Tool uebergeben (der erste `--repo` ist das PRIMARY_REPO).

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

## Step 4: Story-ID (vom Backend alloziert)

Es gibt **keinen** eigenen Schritt zur Bestimmung der naechsten Story-ID und **keinen**
`agentkit story validate`-Aufruf (existiert nicht als Subcommand). Die Story-ID wird vom
AK3-Story-Backend **atomar** waehrend `create-story` alloziert und zurueckgegeben; die
Story-Section-Validierung passiert non-bypassable in der Create-Boundary (AG3-068). Der
ID-Prefix folgt dem Schema aus Step 1:
- Implementation/Concept/Research: `{{project_prefix}}-{NNN}`
- Bugfix: `{{project_prefix}}-FIX-{NNN}`

Du musst die ID also **nicht** vorab berechnen — sie kommt aus der Tool-Antwort.

## Step 5: Story-Body schreiben + im Backend anlegen

Schreibe zuerst den vollstaendigen Story-Body in eine Temp-Datei, lasse ihn von ChatGPT
reviewen (Step 5a–5b), und uebergib ihn dann an das `projectedge create-story`-Tool.

### Step 5a: Story-Body-Datei schreiben

Use the **Write tool** to create `_temp_story_body.md` with the full story body.
Use the template for the story type (fill in all placeholders):

#### For Implementation Stories

```markdown
## Problem Context
[Why this story exists. Business value. 2-4 sentences.]

## Target State
[What is the desired end state after this story is complete? Describe the system behaviour or
outcome that will be true once the implementation is done. 2-4 sentences.]

## Solution Approach
[High-level implementation approach. Which classes/modules change? Key design decisions.]
- Affected modules/areas: [e.g. backend, pipeline]
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
- `concept/XX-yyy.md` - Chapter N - primary - primary specification
- `concept/ZZ-zzz.md` - Chapter N - excluded on purpose; document here only if that exclusion matters for scope

## Guardrail References
- Project guardrails (`guardrails/architecture-guardrails.md`, `guardrails/testing-guardrails.md`) apply.
- List the concrete ARCH-NN / TEST-NN references relevant to this story, or "Standard project guardrails".

## Definition of Done
- All acceptance criteria met and demonstrably verified.
- New business logic covered by unit tests; bugfixes carry a reproducing test.
- Pipeline negative paths at phase boundaries proven where relevant.
- `mypy` (strict) and `ruff` clean; coverage stays >= 85%.
- No ZERO-DEBT remainders (no silent TODOs, no half-finished model transitions).
- Concept fidelity: no implicit deviation from `concept/`; conflicts surfaced explicitly.
```

#### For Bugfix Stories

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
- Project guardrails apply; bugfix requires a reproducing test (testing-guardrails).
- List the concrete references relevant to this fix, or "Standard project guardrails".

## Definition of Done
- Bug no longer reproducible; a reproducing test was added first (red) and now passes (green).
- No regression in the existing suite; no refactoring beyond the fix scope.
- `mypy` (strict) and `ruff` clean; coverage stays >= 85%.
- No ZERO-DEBT remainders.
```

#### For Concept Stories

```markdown
## Problem Context
[Warum diese Analyse/dieses Konzept? Business-Bedarf? 2-4 sentences.]

## Target State
[What is the desired end state once this concept/analysis is complete? What knowledge,
design decisions, or documents will exist that do not exist today? 2-4 sentences.]

## Solution Approach
[How will the analysis/design be performed? What questions must be answered, what artefacts
must be produced, and which area is affected?]
- Affected modules/areas: [e.g. backend, pipeline]
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
- `concept/fachkonzept.md` - Chapter N - primary - input for this analysis
- [Add further exact concept references or "None at story creation"]

## Guardrail References
- Project guardrails apply (no code produced; concept fidelity is the bar).
- List the concrete references relevant to this concept, or "Standard project guardrails".

## Definition of Done
- All raised questions answered with rationale; design/analysis document produced and reviewed.
- Output is concept-faithful and consistent with `concept/`; conflicts surfaced explicitly.
- No ZERO-DEBT remainders (no open questions silently dropped).
```

#### For Research Stories

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
- Project guardrails apply (primary/authoritative sources; no implementation work).
- List the concrete references relevant to this research, or "Standard project guardrails".

## Definition of Done
- All research questions answered with source evidence; findings (research.md) + sources (sources.md) complete.
- Recommendations formulated and downstream-usable.
- No ZERO-DEBT remainders.
```

**STOP: Before creating the story, execute Steps 5a-validate, 5a.1 and 5b below. Return here only after ALL are PASS.**

## Step 5a-validate: Konzeptquellen-Validierung (PFLICHTSCHRITT)

**Nach dem Erstellen des Story-Body und VOR dem ChatGPT-Review:**

Wenn der Story-Body eine `## Concept References`-Sektion mit Pfaden enthält
(nicht nur den Platzhalter), validiere JEDEN referenzierten Pfad:

1. Beginnt der Pfad mit `concept/`? (Konzeptquellen muessen im `concept/`-Verzeichnis liegen)
2. Ist der Pfad relativ zum Projektroot (kein `..`, kein absoluter Pfad)?
3. Existiert die Datei unter diesem Pfad?
4. Ist die Datei nicht leer?

```bash
# Fuer jeden Pfad in Concept References:
PFAD="{PFAD}"
if [[ "$PFAD" != concept/* ]]; then
  echo "FEHLER: $PFAD liegt nicht im concept/-Verzeichnis"
elif [[ "$PFAD" == *..* ]]; then
  echo "FEHLER: $PFAD enthaelt Path-Traversal"
elif ! test -s "$PFAD"; then
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

Pruefe ob jede `TK-*`- und `AF-*`-Erwaehnung im Story-Body in der
Concept-References-Tabelle steht.

**Option A — Python-Validator (bevorzugt, falls im Zielprojekt vorhanden):**
```bash
python userstory/tools/validate_concept_refs.py \
  --story-body _temp_story_body.md \
  --concept-root concept/ \
  --index concept/INDEX.yaml
```
Exit-Code 0 = PASS. Exit-Code 1 = Findings.

**Option B — Manuell (wenn Python-Validator nicht verfuegbar):**
1. Extrahiere alle `TK-*`, `AF-*`, `Kap.*`, `Section *` und `Appendix *` aus dem Story-Body
   (ausserhalb der Referenzen-Sektion)
2. Vergleiche mit den Pfaden in der `## Concept References`-Tabelle
3. Jede Erwaehnung ohne Match → `[HARD STOP]`

**Bei HARD STOP:** Entweder Referenz in die Tabelle aufnehmen ODER
Erwaehnung aus dem Body entfernen. Kein stilles Ueberspringen.

## Step 5b: ChatGPT Story Review (MANDATORY)

**Every story MUST be reviewed by ChatGPT before it is created in the backend.**
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

Write `_temp_source_context.md` using the Write tool.
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
   - `merge_paths`: `["_temp_source_context.md", "_temp_story_body.md"]`
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
   - `merge_paths`: `["_temp_source_context.md", "_temp_story_body.md"]`
5. Parse `VERDICT: PASS` or `VERDICT: REWORK`
6. `llm_release(session_id="...", token="...")`
7. Cleanup: `rm -f "_temp_source_context.md"`

---

#### Batch Review (Szenario C/D/E: N stories from shared source)

Three phases: (1) per-story manifest review, (2) completeness check, (3) release.

**Phase 1: Generate Manifest**

Write `_temp_manifest.json` with this structure:

```json
{
  "creation_scenario": "N stories from 1 concept",
  "source_documents": ["concept-xy.md"],
  "total_stories": 5,
  "decomposition_rationale": "Split by implementation phases: ...",
  "requirements_mapping": [
    {
      "story_id": "<assigned after creation>",
      "story_title": "...",
      "covers": ["Concept section 4.1-4.3"],
      "not_covers": ["Sections 4.4-4.9 → other stories"],
      "rationale": "Focuses on error detection only"
    }
  ],
  "all_stories_summary": [
    "Error detection (Concept 4.1-4.3)",
    "Retry logic (Concept 4.4-4.5)",
    "Monitoring (Concept 4.6-4.9)"
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
   - `merge_paths`: `["_temp_manifest.json", "_temp_source_context.md", "_temp_story_body.md"]`
3. Parse `VERDICT` for story 1. On REWORK → handle (see below).
4. **Subsequent sends** (stories 2..N) — update `_temp_story_body.md` with next story, then:
   `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: "Review the next story draft per the same template and manifest:"
   - `merge_paths`: `["_temp_story_body.md"]`
   (Manifest + source context retained from send 1)
5. Parse `VERDICT` for each story.

**Do NOT release the ChatGPT session yet — Phase 3 follows.**

**Phase 3: Completeness Check (the closing bracket)**

Use template: `prompts/story-review-completeness.md`

This check runs AFTER all individual story reviews pass. It uses a DIFFERENT
template that does NOT include the manifest — ChatGPT must judge independently.

1. Write ALL story drafts into `_temp_all_stories.md`
   (concatenate all N drafts with `---` separators and titles as headings)
2. `llm_send` with:
   - `session_id`: from acquire result
   - `token`: from acquire result
   - `target`: `"chatgpt"`
   - `message`: Content of `prompts/story-review-completeness.md`
   - `merge_paths`: `["_temp_source_context.md", "_temp_all_stories.md"]`
   (Note: NO manifest — ChatGPT judges coverage independently)
3. Parse `COMPLETENESS VERDICT`
4. `llm_release(session_id="...", token="...")`
5. Cleanup: `rm -f "_temp_source_context.md" "_temp_manifest.json" "_temp_all_stories.md"`

---

### On PASS (individual story)

Proceed to Step 5c for that story (create it in the backend).

### On REWORK (individual story)

1. Show ChatGPT's feedback to the user
2. Ask: "ChatGPT has flagged issues with this story. Shall I rework it?"
3. If yes: rework the story, regenerate `_temp_story_body.md`, re-send for review
4. If no (user overrides): proceed to Step 5c — document the override in the story body

### On GAPS_FOUND / OVERLAPS_FOUND / ISSUES_FOUND (completeness check)

1. Show the completeness analysis to the user
2. For gaps: propose additional stories or scope extensions
3. For overlaps: propose scope adjustments to eliminate duplication
4. User decides how to proceed

## Step 5c: Create the Story in the AK3 Backend

Create the story via the deployed AK3 control-plane tool `projectedge create-story`.
This drives `ProjectEdgeClient.create_story` against the tenant-scoped Story-Backend
(FK-91 §91.1a): it allocates the Story-ID atomically, runs the fail-closed
reconciliation (VectorDB-gated related-story check incl. the LLM adjudicator), and
validates the body in a non-bypassable create boundary. There is NO `gh issue create`.

```bash
python tools/agentkit/projectedge.py create-story \
  --project-key {{project_key}} \
  --title "<Title>" \
  --type "<implementation|bugfix|concept|research>" \
  --repo "<PRIMARY_REPO>" \
  [--repo "<additional participating repo>" ...] \
  --story-body "_temp_story_body.md" \
  --epic "<EPIC>" \
  --module "<MODULE>" \
  --size "<XS|S|M|L|XL|XXL>" \
  --mode "<execution|exploration>" \
  [--label "<label>" ...]
```

Notes:
- `--repo` is repeatable; the **first** `--repo` is the PRIMARY_REPO, the remaining ones
  are the additional PARTICIPATING_REPOS (Step 3c).
- `--story-body` accepts a file path (preferred — pass `_temp_story_body.md`) or literal text.
- `--label` is repeatable; pass one per label selected in Step 3a. Omit entirely if none.
- `--mode` mirrors the Step 3d Pipeline-Mode determination (Exploration vs. Execution).
- Mode-determination attributes (Change Impact, New Structures, Concept Quality) belong in
  the story body; the backend derives the pipeline mode from them and `--mode`.

**Exit codes:**
- `0`: success. The tool prints JSON on stdout including the allocated Story-ID
  (`story_id`), `op_id`, and the reconciliation counters. Capture `story_id` for Step 6.
- `3` (fail-closed create rejection): the create boundary / reconciliation rejected the
  story. The tool prints a stable error contract on stderr with an `error_code`
  (`configuration_error`, `validation_failed`, `vectordb_unavailable`,
  `conflict_adjudication_unavailable`, `transport_error`, ...). Report it to the user and
  fix the root cause — do NOT retry blindly and do NOT fall back to any GitHub path.
- `2`: argparse usage error (a malformed invocation).

Delete the temp body file after a successful create:
```bash
rm -f "_temp_story_body.md"
```

## Step 6: Create Wiki Story Directory and Export story.md

Use the `story_id` returned by Step 5c.

```bash
STORY_ID="<story_id from Step 5c JSON>"
STORY_DIR="{{wiki_stories_dir}}/${STORY_ID}_<kebab-case-slug>"
mkdir -p "$STORY_DIR"
```

**IMPORTANT: Do NOT write story.md yourself using the Write tool.**
Instead, run the deterministic export command which writes an exact copy with YAML
frontmatter AND indexes the story in VectorDB (Weaviate):

```bash
python -m agentkit export-story-md \
  --story-id "$STORY_ID" \
  --story-dir "$STORY_DIR"
```

The export reads the story 1:1 from the AK3 backend by `--story-id`, so the
story type / module / epic are taken from the backend record (do NOT pass them
on the command line — the parser only accepts `--story-id`, `--story-dir` and an
optional `--project-root`).

This command writes `story.md` with YAML frontmatter (a 1:1 copy of the backend story)
and indexes the story in VectorDB for semantic search. If the command fails (including
VectorDB indexing failure), report the error — do NOT fall back to writing story.md
manually or skipping indexing.

## Step 7: Present Summary

After all steps complete, present to the user:

```
Story created:
- Story ID: <STORY_ID> (allocated by the AK3 backend)
- Backend: created in the AK3 Story-Backend (control plane) — status Backlog
- Wiki: {{wiki_stories_dir}}/<STORY_DIR>/story.md
- Repos: <PRIMARY_REPO> (primary), <PARTICIPATING_REPOS>

The story ID is the canonical reference used in prompts, telemetry, and directory names.

Status is Backlog. To start execution, the story must be approved first
(status-transition backlog → approved via the AK3 control plane, FK-91 §91.1a
`POST /v1/stories/{story_id}/approve` — a human release action).
```
