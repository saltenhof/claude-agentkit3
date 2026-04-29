---
concept_id: FK-36
title: Compaction Resilience — Prompt-Persistenz fuer Sub-Agenten
module: compaction
domain: pipeline-framework
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: compaction
defers_to:
  - target: FK-30
    scope: hook-infrastructure
    reason: Recovery injector runs as PreToolUse hook within the hook infrastructure
  - target: FK-22
    scope: setup-preflight
    reason: Resume-Kapsel und Spawn-Spec werden im Setup/Worktree-Setup von FK-22 erzeugt
  - target: FK-68
    scope: telemetry
    reason: Recovery-Injector emittiert Telemetrie-Events ueber den Vertrag aus FK-68
supersedes: []
superseded_by:
tags: [compaction, context-recovery, resume-capsule, sub-agent, prompt-persistence]
formal_scope: prose-only
---

# FK-36: Compaction Resilience — Prompt-Persistenz fuer Sub-Agenten

## 36.1 Problemstellung

Claude Code komprimiert den Konversationskontext automatisch, sobald das Token-Limit
eines Agenten erreicht wird (Context Compaction). Das dabei erzeugte Summary ist
eine verlustbehaftete Zusammenfassung — es ist niemals bitgenau.

Konkrete Schadensszenarien fuer Sub-Agenten:

- **Guardrail-Drift**: Sicherheitsregeln, No-Mock-Verbote, Zero-Debt-Anforderungen
  aus CLAUDE.md werden im Summary paraphrasiert oder fehlen ganz.
- **Kontextverlust**: Story-spezifischer Kontext (Scope, Abhaengigkeiten, Pfade,
  akzeptierte Designentscheidungen) geht verloren oder wird verfaelscht.
- **Befehlsdrift**: Konkrete Auftragsbeschreibungen werden paraphrasiert. Der Agent
  handelt dann nach der paraphrasierten, nicht der originalen Version.
- **CLAUDE.md-Verlust**: Der CLAUDE.md-Verweis und dessen Inhalt sind nach Compaction
  nicht mehr zuverlaessig im Summary enthalten — Sub-Agenten erben CLAUDE.md nicht
  automatisch, und der Cache-Reset nach Compaction greift nur fuer den Main-Thread.

Das Problem betrifft ausschliesslich Sub-Agenten: Wenn ein Sub-Agent in eine
Compaction laeuft, ist sein Haupt-Orchestrator nicht betroffen. Das originale
Prompt, das der Orchestrator dem Sub-Agenten mitgegeben hat, existiert zwar als
Datei auf Disk (`prompt_file` im Spawn-Contract), aber der Sub-Agent hat nach
Compaction keinen Verweis mehr darauf.

## 36.2 Loesungsansatz

Spawn-Spec-basierte Recovery mit Ein-Phasen-Bindung und autoritativer Rehydrierung:

> **[Entscheidung 2026-04-08]** Element 1 — Der dynamische Import `compose-prompt.py` entfaellt in v3. Die Funktionalitaet wird als regulaeres Python-Modul implementiert. Alle Referenzen auf `compose-prompt.py` in diesem Dokument sind entsprechend als regulaere Module-Aufrufe umzusetzen.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 1.

1. **Compose-Time**: Das Prompt-Compose-Modul (`agentkit.prompting.compose`) erzeugt neben dem `prompt_file` eine
   kompakte `resume-capsule.md` sowie einen `spawn-spec--{spawn_key}.json`.
2. **Binding**: `SubagentStart`-Hook materialisiert das Per-Agent-Manifest in
   einem einzigen Schritt (Kind-`agent_id` → Spawn-Spec → Manifest).
3. **Autoritative Recovery**: `PreToolUse` im Sub-Agent injiziert die Kapsel
   via `additionalContext` wenn Compaction stattfand.
4. **Cleanup**: Nach Agent-Ende werden Manifest und Flags geloescht.

Dieser Ansatz ist deterministisch (kein LLM-Involvement), fail-open (kein Crash
wenn Artefakte fehlen), und raeumt seinen eigenen Zustand auf.

## 36.3 Empirische Validierung — Claude Code Source Code

Vor der Architektur wurden vier Validierungsblocker gegen den Claude Code Source
Code (`claude-code-source-code-main`, Stand 2026-04) geprueft.

### 36.3.1 Validierungsergebnisse

| ID | Annahme | Ergebnis | Quellverweis | Konsequenz |
|----|---------|----------|--------------|------------|
| VB-01 | `SessionStart(source="compact")` feuert im Sub-Agent mit `agent_id` | **Teilweise widerlegt** — Hook feuert, aber `createBaseHookInput(undefined)` liefert kein `agent_id` (`sessionStart.ts:132`, `compact.ts:591`) | `query.ts:453-468`, `autoCompact.ts:160-182` | SessionStart nicht als agent_id-basierter Primaerpfad tragfaehig |
| VB-02 | `agent_id` in PostCompact/PreToolUse im Sub-Agent verfuegbar | **Geteilt** — PreToolUse: JA (`hooks.ts:3394`, bekommt `toolUseContext`). PostCompact: NEIN (`hooks.ts:4034`, `createBaseHookInput(undefined)`) | `coreSchemas.ts:397-400` | PreToolUse ist der einzige Hook mit belastbarer Identitaet im Sub-Agent |
| VB-03 | `SubagentStart` liefert `agent_id` des Kind-Agents | **Vollstaendig validiert** — Required-Feld, Kind-ID, identische ID in allen spaeterenKind-Hooks (`runAgent.ts:532`, `coreSchemas.ts:540-548`) | `uuid.ts:24-27` (Format: `a{hex16}`) | SubagentStart ist der zuverlaessige Bindungspunkt |
| VB-04 | `InstructionsLoaded(load_reason="compact")` laedt CLAUDE.md im Sub-Agent | **Widerlegt fuer Sub-Agents** — `resetGetMemoryFilesCache('compact')` nur fuer Main-Thread (`postCompactCleanup.ts:22-60`). Built-in Agents haben `omitClaudeMd: true` | `runAgent.ts:385-398` | Kritische Guardrails muessen in Resume-Kapsel enthalten sein |

### 36.3.2 Zusatzbefunde

| Befund | Detail | Quelle |
|--------|--------|--------|
| `agent_id`-Verfuegbarkeit nach Hook-Typ | PreToolUse/PostToolUse: JA. SessionStart(compact)/PostCompact: NEIN. SubagentStart/SubagentStop: JA (Required) | `coreSchemas.ts`, `hooks.ts` |
| Compaction-Ausschluss | `querySource` in `{session_memory, compact, marble_origami, reactive_compact, context_collapse}` unterdrueckt Autocompact | `autoCompact.ts:160-182` |
| Standard-Sub-Agent querySource | `'agent'`, `'agent:custom'`, `'agent:explore'` — Compaction moeglich | `querySource.ts` |
| Worktree-Isolation | **Kein** Ein-Agent-pro-Worktree. Alle Agents einer Story teilen denselben Worktree. QA-Agents (semantic + guardrail) laufen parallel im selben cwd | `phase_runner.py:3999-4035` |
| `subagent_type`-Durchreichung | Claude Code leitet `subagent_type` 1:1 als `agent_type` in alle Hooks durch | `AgentTool.tsx:318-356` |
| `additionalContext`-Limit | Claude Code SDK begrenzt auf 10.000 Zeichen — darueber Auslagerung in Datei mit Preview | `coreSchemas.ts` |

### 36.3.3 Verworfene Architekturvarianten

Folgende Ansaetze wurden durch die Validierung als nicht tragfaehig identifiziert:

- **SessionStart(compact) als agent_id-basierter Primaerpfad** — VB-01 widerlegt
- **PostCompact-Flag mit agent_id** — VB-02 widerlegt (kein `agent_id`)
- **cwd-basierter PostCompact-Marker** — widerlegt durch fehlende Worktree-Isolation
  (parallele QA-Agents teilen cwd)
- **Pending Spawn Record (PreToolUse→SubagentStart Zwei-Phasen-Korrelation)** —
  kein eindeutiger Join-Key zwischen den beiden Hooks bei parallelen Spawns
- **Scan-Heuristik ueber offene Manifeste** — nicht-deterministisch bei
  Parallelitaet und verschachtelten Agents
- **CLAUDE.md-Reload fuer Sub-Agents verlassen** — VB-04 widerlegt

## 36.4 Resume-Kapsel

### 36.4.1 Erzeugung

Die Resume-Kapsel wird bei Compose-Time vom Prompt-Compose-Modul (`agentkit.prompting.compose`) als
**eigenstaendiges Artefakt** erzeugt — zeitgleich mit dem `prompt_file`,
aber aus den strukturierten Quelldaten (`StoryContext`/`context.json`-Export, Story-Metadaten),
NICHT durch Extraktion/Truncation des Prompts (DD-12, Dual-Write).

Pfad: `_temp/qa/{story_id}/resume-capsule--{spawn_key}.md`.

### 36.4.2 Inhalt (Positiv-Liste)

- Story-ID, Story-Typ, Zielzustand
- Enger Scope: betroffene Dateien und Pfade
- Bindende Akzeptanzkriterien (komprimierte normative Fassung)
- Kritische Story-spezifische Non-Negotiables
- **Kritische Guardrails aus CLAUDE.md in kuratierter Kurzform** (siehe 36.4.6)
- Verweis auf kanonisches `prompt_file` als Langform

### 36.4.3 Ausschluesse (Negativ-Liste)

Die Kapsel enthaelt NICHT:

- **Volltext von CLAUDE.md**: Nur der kuratierte Invarianten-Block (36.4.6), nicht
  das gesamte Dokument. Volltext wuerde Platz verschwenden und Widerspruchsrisiko
  schaffen.
- **Template-Boilerplate**: Alles was nur Form ist, nicht Bindung.
- **Zwischenstaende**: "Du hast bereits Datei X gelesen", "aktuelle Hypothese
  ist Y" — kurzlebiger Kontext der sich zwischen Spawn und Compaction aendert.
- **Evidence-Bloecke**: Bundle-Inhalte, Diffs, Logs, Tool-Outputs.
- **Instabile temporaere Pfade**: Ausser sie sind kanonisch Teil des Auftrags.

### 36.4.4 Groessenlimit

Maximal 8.000 Zeichen. Claude Code SDK begrenzt `additionalContext` auf
10.000 Zeichen — darueber wird der Output in eine Datei ausgelagert und nur
als Preview+Pfad dargestellt. 8K gibt 2K Sicherheitspuffer fuer den
Recovery-Header (`[COMPACTION RECOVERY] ...`).

### 36.4.5 Charakter

Die Kapsel ist ein **Resume Contract**, kein "kleines Prompt". Sie enthaelt
nur das, was der Agent wissen MUSS um seinen Auftrag fortzusetzen — nicht
alles was er wissen KOENNTE.

### 36.4.6 Guardrail-Invarianten-Block

Da `InstructionsLoaded(load_reason="compact")` fuer Sub-Agents nicht feuert
(VB-04), muss die Kapsel die kritischen, nicht verhandelbaren Guardrails
aus CLAUDE.md in komprimierter Form enthalten:

- Zero Debt Rule
- No Mock/Stub Ban
- No Error Bypassing
- Data Extraction Completeness
- Evidenzpflicht (kein Deliverable ohne Proof)

Dieser Block ist ein **kuratierter Invarianten-Extrakt**, nicht eine Kopie
von CLAUDE.md. Er wird bei Compose-Time aus einer gepflegten Guardrail-Liste
erzeugt und versioniert (`guardrail_version` im Spawn-Spec).

## 36.5 Spawn-Spec

### 36.5.1 Erzeugung

Der Spawn-Spec wird bei Compose-Time vom Prompt-Compose-Modul (`agentkit.prompting.compose`) erzeugt —
zeitgleich mit `prompt_file` und Resume-Kapsel. Pfad:
`_temp/qa/{story_id}/spawn-spec--{spawn_key}.json`

### 36.5.2 Inhalt

```json
{
  "story_id": "BB2-056",
  "spawn_key": "qa-semantic--r2",
  "agent_type_base": "qa-semantic",
  "round": 2,
  "prompt_file": "<absoluter Pfad>",
  "prompt_hash": "<SHA256>",
  "resume_capsule_file": "<absoluter Pfad>",
  "resume_capsule_hash": "<SHA256>",
  "guardrail_version": "2026-04-03",
  "created_at": "<ISO-8601>"
}
```

### 36.5.3 Rolle

Der Spawn-Spec ist der **kanonische Bindungspunkt** zwischen Compose-Time und
Runtime. Er enthaelt alle Metadaten die `SubagentStart` braucht, um das
Per-Agent-Manifest zu materialisieren — ohne Laufzeit-Heuristiken.

## 36.6 Korrelation Parent → Sub-Agent

### 36.6.1 Spawn-Key als Compound-Identifier

Die Korrelation basiert auf `subagent_type` als eindeutigem Spawn-Key.
Claude Code reicht `subagent_type` 1:1 als `agent_type` in alle Hooks durch
(`AgentTool.tsx:318-356`).

**Format**: `{agent_type_base}--story={story_id}--r{round}`

Beispiele:
- `worker-implementation--story=BB2-056--r1`
- `qa-semantic--story=BB2-056--r2`
- `remediation_worker--story=BB2-056--r3`
- `qa-guardrail--story=ODIN-042--r1`

Der Spawn-Key ist **selbstbeschreibend**: `manifest_writer` kann `story_id`,
Rolle und Runde deterministisch parsen, ohne externe Marker oder cwd-Heuristik.

**Eindeutigkeits-Invariante**: Pro `spawn_key` existiert zu jedem Zeitpunkt
hoechstens ein aktiver Sub-Agent. Dies ist by construction garantiert, da
`story_id` und Round-Counter gemeinsam eindeutig sind.

**Erweiterbarkeit**: Bei zukuenftiger Mehrfachinstanzierung desselben Typs
in derselben Runde kann das Format auf
`{base}--story={id}--r{round}--slot{n}` erweitert werden.

### 36.6.2 Protokoll-Status von subagent_type

`subagent_type` ist ab FK-36 ein **stabiler Vertragsbestandteil**, nicht ein
UI-Label:

- **Setter**: Ausschliesslich der Orchestrator beim Agent-Spawn
- **Format**: `{base}--story={id}--r{N}`, Delimiter ist `--`
- **Invariante**: Claude Code reicht den Wert unveraendert durch
- **Konsumenten**: SubagentStart-Hook, PreToolUse-Hook (via `agent_type`)
- **Normalisierung verboten**: AgentKit darf den Wert nicht kuerzen, umbenennen
  oder normalisieren nachdem er gesetzt wurde
- **Parsing**: `story_id` wird aus dem `story=`-Segment extrahiert. Fehlt es,
  ist der Agent nicht FK-36-gemanagt (fail-open).

### 36.6.3 Story-Kontext-Marker

`.agentkit-story.json` ist ein Pflichtartefakt der Setup-Phase (DD-13). Es
dient als cwd-basierter Story-Discriminator fuer PostCompact-Epoch-Scoping
(DD-04), NICHT als Primaerquelle fuer Manifest-Bindung (dafuer: Spawn-Key).

**Standort:**
- Implementation/Bugfix: `{worktree_path}/.agentkit-story.json`
- Concept/Research: `_temp/qa/{story_id}/agent-root/.agentkit-story.json`

**Inhalt:**
```json
{
  "story_id": "BB2-056",
  "run_id": "a1b2c3d4-...",
  "created_at": "<ISO-8601>"
}
```

**Producer:** `_phase_setup()` in `phase_runner.py`.

**Verwendung:** Ausschliesslich `epoch_writer` (PostCompact) via Walk-up-Suche
im `cwd`. `manifest_writer` nutzt stattdessen den Spawn-Key (DD-06).

**Concept/Research Agent-Root:** Fuer Stories ohne Worktree wird ein dediziertes
Arbeitsverzeichnis unter `_temp/qa/{story_id}/agent-root/` angelegt. Der
Agent wird per Prompt-Instruktion angewiesen, nach Step 0 dorthin zu wechseln.

## 36.7 Lifecycle

### 36.7.1 Schritt 0: Compose-Time (deterministisch, kein Hook)

Das Prompt-Compose-Modul (`agentkit.prompting.compose`) erzeugt fuer jeden geplanten Agent-Spawn:
- `prompt_file` (vollstaendiges composed Prompt, wie bisher)
- `resume-capsule--{spawn_key}.md` (kompakter Recovery-Extrakt mit Guardrails)
- `spawn-spec--{spawn_key}.json` (Metadaten fuer Runtime-Bindung)

Alle Dateien liegen unter `_temp/qa/{story_id}/`. Die Erzeugung ist
deterministisch — das Prompt-Compose-Modul kennt die Prompt-Struktur und kann die
relevanten Teile mechanisch extrahieren.

### 36.7.2 Schritt 1: Ein-Phasen-Manifest bei SubagentStart

- **Trigger**: `SubagentStart`-Hook (Parent-Kontext, feuert nach Agent-ID-Erzeugung,
  vor Agent-Start)
- **Hook-Script**: `python -m agentkit.compaction.manifest_writer`
- **Verfuegbare Daten im Hook-Input**:
  - `agent_id` (Required, Kind-Agent-ID)
  - `agent_type` (Required, = spawn_key, z.B. `qa-semantic--story=BB2-056--r2`)
  - `session_id`, `cwd`
- **Ablauf**:
  1. Lese `agent_type` aus Hook-stdin → `spawn_key`
  2. Parse `story_id` aus spawn_key (Format: `{base}--story={id}--r{N}`)
  3. Lade `_temp/qa/{story_id}/spawn-spec--{spawn_key}.json`
  4. Verifiziere `resume_capsule_hash` gegen aktuelle Kapsel-Datei (Drift-Check)
  5. Lese aktuellen Story-Epoch aus dem zentralen Compaction-State-Store → `baseline_epoch`
  6. Schreibe `_temp/agent-prompts/{agent_id}.manifest.json`:
     ```json
     {
       "agent_id": "<agent_id>",
       "spawn_key": "<spawn_key>",
       "story_id": "<story_id>",
       "prompt_file": "<aus Spawn-Spec>",
       "prompt_hash": "<aus Spawn-Spec>",
       "resume_capsule_file": "<aus Spawn-Spec>",
       "resume_capsule_hash": "<aus Spawn-Spec>",
       "guardrail_version": "<aus Spawn-Spec>",
       "baseline_epoch": 0,
       "recovered_epoch": 0,
       "created_at": "<ISO-8601>"
     }
     ```
- **Kein `.active`-Marker mehr**: `baseline_epoch` und `recovered_epoch` werden
  direkt im Manifest gespeichert. Der separate `.active`-Datei entfaellt.
- **Fail-open**: Wenn Spawn-Key nicht parsebar, Spawn-Spec fehlt, oder
  Hash-Mismatch → Warning auf stderr, exit 0. Agent startet ohne
  Recovery-Faehigkeit.

### 36.7.3 Schritt 2: Autoritative Recovery bei PreToolUse

- **Trigger**: `PreToolUse`-Hook (beliebiges Tool, Sub-Agent-Kontext)
- **Hook-Script**: `python -m agentkit.compaction.recovery_injector`
- **Verfuegbare Daten im Hook-Input**:
  - `agent_id` (aus `toolUseContext`, nur im Sub-Agent)
  - `tool_name`, `tool_input`
- **Ablauf**:
  1. Wenn kein `agent_id` im Input → exit 0 (Main-Thread, kein Recovery noetig)
  2. Pruefe ob `_temp/agent-prompts/{agent_id}.manifest.json` existiert →
     wenn nein: exit 0 (kein gemanagter Agent)
  3. Pruefe ob `_temp/agent-prompts/{agent_id}.recovered` existiert →
     wenn ja: exit 0 (bereits recovered, kein erneuter Inject)
  4. **Compaction-Erkennung**: Pruefe ob seit `.active`-Marker eine Compaction
     stattfand. Zwei komplementaere Signale:
     - **PostCompact-Signal**: `_temp/agent-prompts/.compact-epoch` Datei mit
       monotonem Counter. Wenn Counter > Wert in `.active` → Compaction erkannt.
     - **Erster Tool-Call-Guard**: Beim allerersten PreToolUse nach Agent-Start
       (`.active` existiert, `.first-tool` nicht) → schreibe `.first-tool` Marker,
       exit 0. Damit wird der erste regulaere Tool-Call nicht als Recovery
       fehlinterpretiert.
  5. Wenn Compaction erkannt:
     a. Lese Manifest → `resume_capsule_file`, `resume_capsule_hash`
     b. Wenn keine valide Kapsel vorhanden → Warn + Allow (exit 0, fail-open)
     c. Verifiziere `resume_capsule_hash` (Drift-Check, Warn bei Mismatch)
     d. **Abgestufte Policy nach Tool-Typ:**
        - Read/Glob/Grep/WebSearch/WebFetch: **Allow** + Inject (exit 0)
        - Write/Edit/Bash: **Allow** + Inject + Warn-Header (exit 0)
        - Agent (Sub-Agent-Spawn): **Allow** + Inject + Warn-Header (exit 0)
          (DD-09 revidiert: kein hartes Deny bei story-scoped Detection)
     e. Gib Kapsel-Inhalt via `additionalContext` zurueck:
        ```
        [COMPACTION RECOVERY — Originaler Auftrag wiederhergestellt]

        {Kapsel-Inhalt}

        Kanonisches Vollprompt: {prompt_file}
        [ENDE COMPACTION RECOVERY]
        ```
     f. Aktualisiere `recovered_epoch = current_epoch` im Manifest
- **Compaction-Erkennung**: Lese `story_id` aus Manifest → lese Story-Epoch
  aus dem zentralen Compaction-State-Store → vergleiche mit `recovered_epoch` im Manifest.
  `current_epoch > recovered_epoch` → Compaction erkannt.
- **Fail-open**: Wenn Manifest fehlt, Kapsel fehlt, oder Hash-Mismatch →
  Warning auf stderr, exit 0. Agent arbeitet degradiert weiter.

### 36.7.4 Schritt 3: Story-Scoped Compaction-Epoch (PostCompact)

- **Trigger**: `PostCompact`-Hook (read-only, kein Decision Control)
- **Hook-Script**: `python -m agentkit.compaction.epoch_writer`
- **Verfuegbare Daten**: `trigger` (manual/auto), `compact_summary`, `session_id`,
  `cwd` — **kein `agent_id`**, **kein `agent_type`**
- **Ablauf**:
  1. Walk-up-Suche: Suche `.agentkit-story.json` ab `cwd` aufwaerts bis
     Repository-Root oder Filesystem-Root. Nimm den naechsten Marker.
  2. Extrahiere `story_id` aus dem Marker.
  3. Oeffne den zentralen Compaction-State-Store
  4. Atomar: `UPSERT epoch = epoch + 1 WHERE (project_key, story_id)`
  5. Kein Marker gefunden → Warning, kein Epoch-Update (fail-open).
- **Zweck**: Stellt ein **story-scoped** Compaction-Signal bereit, das
  `PreToolUse` auswerten kann. Die Story-Zuordnung erfolgt ueber den
  cwd-Marker (`.agentkit-story.json`), da PostCompact kein `agent_id` hat.
- **Cross-Story-Isolation**: Jede Story hat ihren eigenen Epoch-Counter.
  Compaction in Story A beeinflusst nur Story A's Agents, nicht Story B.
- **Zentraler Store statt Dateien**: Atomares `epoch = epoch + 1` ohne
  Lost-Update bei parallelen Compactions. Der Epoch-State ist kein
  projektlokales SQLite-Artefakt mehr.

### 36.7.5 Schritt 4: Cleanup

- **Trigger**: `SubagentStop`-Hook (Parent-Kontext)
- **Hook-Script**: `python -m agentkit.compaction.cleanup`
- **Verfuegbare Daten**: `agent_id` (Required), `agent_type`
- **Ablauf**:
  1. Lese `agent_id` aus Hook-Input
  2. Loesche: `{agent_id}.manifest.json`, `{agent_id}.active`,
     `{agent_id}.recovered`, `{agent_id}.first-tool`
  3. Wenn Dateien nicht existieren: kein Fehler (idempotent)
- **Housekeeping**: Installer-Checkpoint prueft `_temp/agent-prompts/` auf
  Dateien aelter als 24 Stunden und loescht sie. Kein legitimer Agent laeuft
  laenger als 24 Stunden.

## 36.8 Hook-Konfiguration

### 36.8.1 Neue Hook-Eintraege

```python
# Schritt 1: Ein-Phasen-Manifest bei Agent-Spawn
SubagentStart:
  python -m agentkit.compaction.manifest_writer

# Schritt 2: Autoritative Recovery (jeder Tool-Call im Sub-Agent)
PreToolUse:
  python -m agentkit.compaction.recovery_injector

# Schritt 3: Compaction-Epoch-Signal (agent-unabhaengig)
PostCompact:
  python -m agentkit.compaction.epoch_writer

# Schritt 4: Cleanup nach Agent-Ende
SubagentStop:
  python -m agentkit.compaction.cleanup
```

### 36.8.2 Interaktion mit bestehenden Hooks

- **prompt_integrity_guard** (FK-30): Laeuft auf PreToolUse/Agent. Kein Konflikt
  mit `recovery_injector` — verschiedene Matcher (Agent vs. alle Tools).
- **Telemetrie** (FK-68): Laeuft auf PreToolUse. `recovery_injector` ist
  reihenfolge-unabhaengig zur Telemetrie — beide lesen, keiner blockiert.
- **branch_guard, orchestrator_guard, integrity**: Laufen auf anderen Matchern
  (Bash, Write, Edit). Kein Konflikt.
- **SubagentStart ist neu** — kein bestehender Hook auf diesem Event.

## 36.9 Dateiformat

### 36.9.1 Manifest-Datei

`_temp/agent-prompts/{agent_id}.manifest.json`

- Encoding: UTF-8
- Format: JSON (Pydantic-serialisierbar)
- Felder: siehe 36.7.2

### 36.9.2 Spawn-Spec

`_temp/qa/{story_id}/spawn-spec--{spawn_key}.json`

- Encoding: UTF-8
- Format: JSON (Pydantic-serialisierbar)
- Felder: siehe 36.5.2
- Erzeugt vom Prompt-Compose-Modul (`agentkit.prompting.compose`), nicht von einem Hook

### 36.9.3 Resume-Kapsel

`_temp/qa/{story_id}/resume-capsule--{spawn_key}.md`

- Encoding: UTF-8, keine BOM
- Format: Plaintext Markdown
- Max 8.000 Zeichen
- Enthaelt Guardrail-Invarianten-Block (36.4.6)
- Erzeugt vom Prompt-Compose-Modul (`agentkit.prompting.compose`), nicht von einem Hook

### 36.9.4 Story-Kontext-Marker

`.agentkit-story.json` im Worktree-Root

- Encoding: UTF-8
- Format: JSON
- Felder: `story_id`, `worktree_id`, `created_at`
- Erzeugt beim Worktree-Setup (FK-22)

### 36.9.5 Signal- und Flag-Dateien

- `_temp/agent-prompts/{agent_id}.first-tool` — leere Datei, erster Tool-Call Marker
- zentraler Compaction-State-Store — Story-scoped Epoch-Store
  (`(project_key, story_id) -> epoch, updated_at`)

**Entfallene Dateien (ab Revision 2):**
- ~~`{agent_id}.active`~~ → ersetzt durch `baseline_epoch` im Manifest
- ~~`{agent_id}.recovered`~~ → ersetzt durch `recovered_epoch` im Manifest
- ~~`.compact-epoch`~~ → ersetzt durch zentralen Compaction-State-Store

## 36.10 Sicherheitsaspekte

- **Sensitive Inhalte**: Resume-Kapseln und Spawn-Specs koennen Story-Kontext
  und Pfade enthalten. Nicht fuer Commit gedacht.
- **Gitignore**: `_temp/` ist gitignored. Keine zusaetzliche Konfiguration noetig.
- **Cleanup ist Pflicht**: Phase 4 (Cleanup) ist ein Sicherheitsmerkmal.
  Verwaiste Prompt-Referenzen sind ein Informationsleck.
- **Housekeeping**: Installer-Checkpoint loescht Dateien >24h in
  `_temp/agent-prompts/`.
- **Input-Validierung**: Hook-Scripts validieren `agent_id` (nur alphanumerisch
  + Bindestriche) um Path-Traversal zu verhindern.
- **Artifact-Drift**: Hash-Verifikation in Manifest und Spawn-Spec schuetzt gegen
  unbeabsichtigtes Lesen ueberschriebener Dateien.
- **Agent-Spawn-Deny**: Im Recovery-Zustand werden Agent-Spawns blockiert (DD-09),
  um Kaskadenschaeden unter potenziellem Auftragsdrift zu verhindern.

## 36.11 Grenzen

- **Nur Sub-Agenten**: Schuetzt nur Sub-Agenten die ueber AgentKit (via
  `Agent`-Tool) gestartet werden. Der Hauptagent (Orchestrator) ist nicht
  geschuetzt — sein Kontext-Verlust bei Compaction ist ein eigenes Problem.
- **Nur initiales Prompt**: Sichert das initiale Prompt (via Kapsel), nicht den
  laufenden Konversationsverlauf. Zwischenergebnisse und Tool-Antworten gehen
  bei Compaction verloren — das ist nicht adressiert.
- **1-Tool-Call-Degradation**: Der erste Tool-Call nach Compaction kann unter
  degradiertem Kontext stattfinden, bevor die Recovery greift. Agent-Spawns
  werden in diesem Fall blockiert (DD-09).
- **Token-Re-Compaction**: Wenn das re-injizierte Prompt selbst gross ist, kann
  ein neues Compaction-Event ausgeloest werden. Die Kapsel ist deshalb bewusst
  kompakt (8K).
- **Within-Story False Positives**: Der story-scoped Epoch-Counter
  unterscheidet nicht zwischen Agents derselben Story. Wenn ein paralleler
  QA-Agent compacted, sieht der andere Agent erhoehten Epoch und wird
  ebenfalls recovered. Dies ist harmlos (konservative Recovery, begrenzt
  durch `recovered_epoch` im Manifest).
- **Worktree-Pfade**: Manifest und Kapsel muessen ausserhalb kurzlebiger
  isolierter Worktrees liegen. `_temp/qa/` und `_temp/agent-prompts/` liegen
  im Projekt-Root — kein Problem solange Worktrees Unterverzeichnisse sind.

## 36.12 Ausbaustufen

### Stufe 1: Einfacher Sub-Agent

Ein Orchestrator spawnt einen Worker-Agent. Der Worker compacted.
→ PreToolUse injiziert Resume-Kapsel via Manifest-Lookup. Standard-Fall.

### Stufe 2: Parallele Sub-Agenten

Orchestrator spawnt qa-semantic--r1 + qa-guardrail--r1 parallel. Beide koennen
unabhaengig compacten.
→ Jeder Agent hat eigenes Manifest (via eigene `agent_id`) und eigenen
Spawn-Spec (via eigenen `spawn_key`). Kein Shared State, keine Race Condition.
Compact-Epoch-Counter ist global, aber PreToolUse wertet agent-spezifisch aus.

### Stufe 3: Verschachtelte Sub-Agenten

Worker-Agent spawnt eigenen Research-Sub-Agent. Research-Agent compacted.
→ Worker schreibt Manifest fuer Research-Agent (via SubagentStart Hook).
Recovery funktioniert identisch — jede Ebene ist autark.

### Stufe 4: Feedback-Runden

Orchestrator spawnt remediation_worker--r2 nach fehlgeschlagener QA. Spaeter
qa-semantic--r2 und qa-guardrail--r2.
→ Jede Runde hat eigene Spawn-Specs und Kapseln (via Round-Suffix im
spawn_key). Keine Kollision mit vorherigen Runden.

## 36.13 Design-Entscheidungen

### DD-01: Kein erneutes Speichern des Prompts

Das composed Prompt wird NICHT separat gespeichert. `prompt_file` (erzeugt vom
Prompt-Compose-Modul) ist die Single Source of Truth. Duplikation wuerde
Sync-Probleme erzeugen.

### DD-02: Resume-Kapsel als Compose-Time-Artefakt

Die Kapsel wird bei Compose-Time erzeugt, nicht spaeter. Das Prompt-Compose-Modul
kennt die Prompt-Struktur und kann relevante Teile mechanisch extrahieren.
Keine LLM-Zusammenfassung, keine Laufzeit-Abhaengigkeit.

### DD-03: PreToolUse als autoritativer Recovery-Punkt (revidiert)

**Vorher**: SessionStart(source="compact") als Primaerpfad.
**Jetzt**: PreToolUse im Sub-Agent ist der einzige autoritative Recovery-Punkt.

**Begruendung**: SessionStart(compact) feuert zwar im Sub-Agent, aber ohne
`agent_id` (VB-01). Ohne belastbare Identitaet ist kein deterministischer
Manifest-Lookup moeglich. PreToolUse ist der einzige Sub-Agent-Hook mit
`agent_id` aus `toolUseContext` (VB-02).

### DD-04: PostCompact als Story-Scoped Epoch-Signal (revidiert, 2x)

**Erste Revision**: Globaler Epoch-Counter statt agent-spezifischer Marker.
**Zweite Revision**: Story-scoped Epoch via zentralem Compaction-State-Store + cwd-Marker statt global.

**Begruendung**: Globaler Counter verursacht Cross-Story False Positives bei
paralleler Story-Bearbeitung. `session_id` ist nicht nutzbar (alle Stories
teilen eine CLI-Session). `cwd` + Walk-up-Suche nach `.agentkit-story.json`
liefert die Story-Zuordnung. Der zentrale Store garantiert Atomizitaet.

### DD-05: Ein-Phasen-Manifest in SubagentStart (revidiert)

**Vorher**: PreToolUse/Agent schreibt Manifest im Parent-Kontext.
**Jetzt**: SubagentStart materialisiert das Manifest in einem einzigen Schritt.

**Begruendung**: SubagentStart ist der erste Hook mit gesicherter Kind-`agent_id`
(VB-03). Ein Zwei-Phasen-Ansatz (PreToolUse→SubagentStart) hat ein ungeloestes
Binding-Problem bei parallelen Spawns — es gibt keinen eindeutigen Join-Key
zwischen den beiden Hooks. Der Ein-Phasen-Ansatz eliminiert dieses Problem.

### DD-06: subagent_type als Compound-Spawn-Key mit Story-ID (revidiert, 2x)

**Erste Revision**: Compound-Key `{base}--r{round}`.
**Zweite Revision**: Story-ID im Key: `{base}--story={id}--r{round}`.

**Begruendung**: `manifest_writer` braucht `story_id` fuer den Spawn-Spec-Pfad.
SubagentStart's `cwd` ist der Parent-Kontext (ggf. Projekt-Root, nicht
Worktree). Mit Story-ID im Spawn-Key ist der Lookup deterministisch.
Trennung: Spawn-Key fuer Binding, cwd-Marker fuer Compaction-Scope.

### DD-07: Prompt-Hash fuer Artifact-Drift-Schutz (beibehalten)

Manifest und Spawn-Spec speichern SHA256-Hashes von `prompt_file` und
`resume_capsule_file`. Wenn ein spaeterer Compose-Lauf die Datei ueberschreibt,
erkennt die Recovery den Drift und warnt.

### DD-08: Kritische Guardrails IN Kapsel (revidiert)

**Vorher**: CLAUDE.md nicht in Kapsel duplizieren — Claude Code laedt
Instruktionsdateien nach Compaction erneut.
**Jetzt**: Kuratierter Invarianten-Block mit kritischen Guardrails in der Kapsel.

**Begruendung**: `resetGetMemoryFilesCache('compact')` greift nur fuer den
Main-Thread (VB-04, `postCompactCleanup.ts:22-60`). Built-in Agents haben
`omitClaudeMd: true`. Fuer Custom-Sub-Agents ist CLAUDE.md-Reload nach
Compaction nicht garantiert. Der Invarianten-Block ist bewusst kompakt und
versioniert, um Widerspruchsrisiko zu minimieren.

### DD-09: Agent-Spawn-Policy im Recovery-Zustand (revidiert)

**Vorher**: Hartes Deny (exit 2) fuer Agent-Spawns bei Recovery.
**Jetzt**: Inject + Warn (exit 0), kein hartes Deny.

**Begruendung**: Mit story-scoped Epoch sind within-story False Positives
moeglich (paralleler Agent compacted, nicht dieser). Hartes Deny wuerde
bei False Positives legitime Arbeit blockieren. Zusaetzlich: Der alte Code
blockierte Agent-Spawns bevor geprueft wurde, ob eine Kapsel ueberhaupt
vorhanden ist — Deny ohne Wiederherstellungspfad ist destruktiv.

### DD-10: First-Tool-Guard gegen False-Positive-Recovery (revidiert)

**Vorher**: Ack-Mechanismus zwischen SessionStart und PreToolUse gegen
Doppel-Recovery.
**Jetzt**: `.first-tool` Marker verhindert, dass der allererste Tool-Call
nach Agent-Start als Recovery fehlinterpretiert wird.

**Begruendung**: Ohne SessionStart als Primaerpfad gibt es kein Doppel-Recovery-
Risiko mehr. Das verbleibende Problem ist die Unterscheidung zwischen
"Agent gerade gestartet, noch keine Compaction" und "Compaction stattgefunden".
Der First-Tool-Guard loest dies: Beim ersten Tool-Call wird nur der Marker
gesetzt, kein Recovery versucht.

### DD-11: SessionStart und PostCompact nicht im Recovery-Kern (neu)

SessionStart(compact) und PostCompact werden bewusst nicht als tragende
Recovery-Saeulen gefuehrt:

- SessionStart(compact): Feuert im Sub-Agent, aber ohne `agent_id`. Koennte
  kuenftig als best-effort Frueh-Recovery genutzt werden, wenn ein
  agent_id-unabhaengiger Lookup-Mechanismus gefunden wird.
- PostCompact: Liefert nur das globale Epoch-Signal. Kein Manifest-Lookup,
  kein agent-spezifischer Marker.

Beide bleiben im System (SessionStart fuer kuenftige Optimierung, PostCompact
fuer das Epoch-Signal), aber die Architektur funktioniert auch ohne sie.

## 36.14 Sparring-Referenz

Architektur erarbeitet in strukturiertem Sparring:
- **Claude (Opus)**: Source-Code-Validierung, empirische Befunde, Architektur-Entwurf
- **ChatGPT**: Konzept-Challenge, Korrelations-Analyse, Haertungsvorschlaege

Sparring-Protokoll:
`_temp/refactoring-stories/REF-019a_compaction-resilience-concept/sparring-protocol.md`
