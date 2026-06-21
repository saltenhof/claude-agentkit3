---
concept_id: FK-76
title: Agent-Harness-Integration
module: harness-integration
domain: harness-integration
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: harness-integration
  - scope: harness-adapter
  - scope: harness-settings
  - scope: harness-invocation
  - scope: harness-cli-wrapper
  - scope: harness-io-contract
  - scope: subagent-hybrid-lifecycle
defers_to:
  - target: FK-30
    scope: hook-definition-and-enforcement
    reason: FK-30 ist Owner der harness-neutralen Hook-/Guard-DEFINITION und des Enforcement-Verhaltens (guard_evaluation). FK-76 ownt ausschliesslich die harness-SPEZIFISCHE Anbindung (Adapter, CLI-Wrapper, Settings-Schemas, Lifecycle) und trifft keine Policy.
  - target: FK-50
    scope: installer-orchestration
    reason: FK-50 (Installer) ruft zur Install-Zeit die Harness-Registrierung/-Bindung auf und orchestriert die parallele Installation. FK-76 ownt das Settings-FORMAT und die Adapter; FK-50 ownt das WANN/Reihenfolge des Aufrufs.
  - target: FK-11
    scope: llm-provider-execution
    reason: FK-11 unterscheidet LLM-als-Agent vs. LLM-als-Bewertungsfunktion und ownt Pool-/Prompt-Execution. FK-76 ist das Heim fuer die Agent-Harness-Anbindung, auf die FK-11 §11.1 verweist.
  - target: FK-07
    scope: component-architecture
    reason: Bluttyp-Klassifizierung (Adapter/AT) und Komponenten-/Importgrenzen werden in FK-07 normiert.
supersedes: []
superseded_by:
tags: [harness, agent-harness, adapter, claude-code, codex, meta-harness, settings]
prose_anchor_policy: strict
formal_refs: []
formal_scope: prose-only
glossary:
  exported_terms:
    - id: agent-harness
      definition: >
        Externe Agent-Laufzeitumgebung, in der ein AK3-Agent (Orchestrator,
        Worker, Adversarial) laeuft und Werkzeuge ausfuehrt — aktuell Claude
        Code oder Codex. Der Harness liefert allgemeine Agent-Faehigkeiten
        (Datei-Edit, Shell, Git, Tool-Aufrufe). AK3 ist ein Meta-Harness, der
        diesen Harness um prozessuale und Governance-Capabilities erweitert,
        ohne selbst die allgemeinen Agent-Faehigkeiten bereitzustellen.
      see_also:
        - term: harness-adapter
          domain: harness-integration
        - term: guard-system
          domain: governance-and-guards
    - id: harness-adapter
      definition: >
        Harness-spezifische Mediationsschicht (Bluttyp AT) pro Agent-Harness
        im Soll-Namespace agentkit.harness_integration.{claude_code,codex}.
        Die aktuelle Code-Verortung liegt unter
        agentkit.harness_client.harness_adapters. Mappt
        harness-native Mechanik (Tool-Namen, stdin/stdout, Exit-Codes, Settings-
        Format) auf das harness-neutrale Modell und zurueck. Enthaelt keine
        Guard-Regeln und trifft keine Policy.
      see_also:
        - term: harness-port
          domain: harness-integration
        - term: hook-enforcement
          domain: governance-and-guards
    - id: harness-port
      definition: >
        Schmale, harness-neutrale Schnittstelle, ueber die AK3-BCs den
        Agent-Harness ansprechen (z. B. Settings-Materialisierung, Invocation,
        Capability-Abfrage), ohne harness-spezifische Dateien (.claude/...,
        .codex/...) zu kennen. Konkrete Adapter implementieren den Port; die
        Verdrahtung erfolgt ueber die Composition-Root.
      see_also:
        - term: harness-adapter
          domain: harness-integration
    - id: harness-settings
      definition: >
        Harness-spezifische, auf der Platte materialisierte Hook-/Tool-
        Registrierung eines Projekts: .claude/settings.json (Claude Code) bzw.
        .codex/hooks.json (Codex). FK-76 ist der alleinige Owner dieser Schemas;
        die Hook-INHALTE (welche Guards) stammen harness-neutral aus FK-30.
      see_also:
        - term: harness-adapter
          domain: harness-integration
---

# 76 — Agent-Harness-Integration

## 76.1 Zweck

AK3 ist ein **Meta-Harness**: ein Harness auf dem Harness. Die konkreten
Agent-Harnesses **Claude Code** und **Codex** liefern bereits allgemeine
Agent-Faehigkeiten (Datei-Edit, Shell, Git, Tool-Aufrufe). AK3 fuegt **keine**
allgemeinen Agent-Faehigkeiten hinzu, sondern **prozessuale und
Governance-Capabilities** (Story-Pipeline, 4-Schichten-QA, Guards, Telemetrie,
Closure), damit Agents grosse, anspruchsvolle Softwareprojekte hochautomatisiert
umsetzen koennen.

FK-76 ist das Heim der **harness-spezifischen Anbindung** dieser Meta-Harness-
Erweiterung an die jeweilige Agent-Laufzeit:

- die Harness-Adapter (`claude_code`, `codex`),
- die CLI-Wrapper `agentkit-hook-claude` / `agentkit-hook-codex`,
- die harness-spezifischen Settings-Schemas (`.claude/settings.json`,
  `.codex/hooks.json`),
- stdin/stdout/Exit-Code-Konventionen,
- den Sub-Agent-/Hybrid-Lifecycle (ein Harness spawnt den anderen).

## 76.2 Abgrenzung (wer was ownt)

| Belang | Owner |
|---|---|
| Harness-**neutrale** Hook-/Guard-**Definition** + Enforcement-Verhalten (`guard_evaluation`) | governance-and-guards (FK-30) |
| Harness-**spezifische** Adapter, CLI-Wrapper, Settings-Schemas, Lifecycle | **harness-integration (FK-76)** |
| Install-zeitliche Registrierung/Bindung (WANN/Reihenfolge, parallel) | installation-and-bootstrap (FK-50) |
| LLM-Pool/Prompt-Execution, Agent-vs-Bewertungsfunktion | FK-11 |
| Externer Multi-LLM-Hub (Modell-Provider-Sessions) | FK-75 |

**Trennregel:** FK-30 definiert *was* ein Guard tut und *dass* er an einem
logischen Punkt greift (harness-neutral). FK-76 definiert *wie* das auf einem
konkreten Harness eingehaengt und transportiert wird. FK-76 trifft **keine
Policy** (z. B. ist es unzulaessig, Exit-Code/stderr/Timeout im Adapter als
allow/deny/warn umzudeuten — die Decision kommt aus `guard_evaluation`).

**Abgrenzung zu installation-and-bootstrap:** FK-50 ownt „Hook/Wrapper-Bindung"
im Sinne der **Install-Orchestrierung** (CP 9 ruft `register_hooks` pro Harness,
Merge-Modus, Reihenfolge). FK-76 ownt das **Format und die Adapter**, die dabei
geschrieben werden. FK-50 kennt das Settings-Schema nicht selbst, sondern
delegiert an FK-76.

## 76.3 Adapter-Architektur

Hook-Auswertung ist in zwei Subkomponenten gespalten:

- **`governance.guard_evaluation`** (BC governance-and-guards, A-Kern,
  harness-neutral): nimmt eine generische `HookEvent`-Struktur, ruft die Guards,
  gibt eine Decision zurueck.
- **`harness_integration.{harness}`** (BC harness-integration, AT-Insel pro
  Harness): mappt harness-spezifische Mechanik auf die generische
  `HookEvent`-Struktur und liefert die harness-spezifische Decision-
  Repraesentation zurueck.

Aktuelle Adapter:

| Adapter | Status | Modul-Pfad |
|---|---|---|
| `claude_code` | implementiert | Soll: `agentkit.harness_integration.claude_code`; aktuell: `agentkit.harness_client.harness_adapters.claude_code` |
| `codex` | implementiert (CLI `agentkit-hook-codex`) | Soll: `agentkit.harness_integration.codex`; aktuell: `agentkit.harness_client.harness_adapters.codex` |

Weitere Harnesses (Qwen Code, Gemini-CLI, …) folgen demselben Pattern. Es gibt
**keine Plugin-Registry** und **keine Capability-Selection-Policy** — jeder
Adapter ist ein fest verdrahtetes Sub-Modul.

> **Code-Verortung (Hinweis, nicht normativ fuer die Konzept-Sicht):** Die
> reale Code-Verortung ist heute `agentkit.harness_client.harness_adapters`. Die
> physische Verschiebung nach `agentkit.harness_integration` ist kosmetisch
> (Paketname = BC-Name) und kann als eigene Folge-Story erfolgen. Verbindlich
> ist die BC-**Zugehoerigkeit** (dieses Doc) und die Importrichtung (§76.9),
> nicht der Verzeichnisname.

## 76.4 Adapter-Vertrag

Ein Harness-Adapter erfuellt drei Pflichten:

1. **Eingangs-Mapping**: harness-spezifischer Hook-Event → generische
   `HookEvent`. Tool-Namen, Tool-Argumente, Principal-Identifikation und
   Operation-Klasse (`bash_command`/`file_write`/`file_edit`/`file_read`/
   `unknown_tool`) werden auf die harness-neutralen Felder abgebildet.
   Mutierende Operationen erhalten `freshness_class = mutation`, reine
   Leseoperationen `baseline_read`, unbekannte Tools `guarded_read`.
   **Wichtig:** Die zulaessigen `freshness_class`-/`operation_class`-Werte und
   ihre Guard-Semantik werden in FK-30 / `guard_evaluation` definiert; FK-76
   ordnet nur harness-native Tool-Events diesen Klassen zu (reines Mapping,
   keine Policy-Definition).
2. **Ausgangs-Mapping**: generische Decision (`allow`/`block` mit Begruendung) →
   harness-spezifischer Output. Claude Code: JSON-Decision auf stdout,
   Exit-Code 2 = block, 0 = allow. Codex: das harness-eigene Aequivalent.
3. **Sub-Agent-Lifecycle**: wenn der Harness Sub-Agent-Spawn unterstuetzt,
   mappt der Adapter die Sub-Agent-Identifikation (`principal_kind = main` vs.
   `subagent`), damit `guard_evaluation` zwischen Haupt- und Sub-Agent
   unterscheiden kann.

Der Adapter ist **AT** im Sinne der Bluttypen-Methodik (`software-blutgruppen.md`
§4.2): Mediation zwischen fachlicher Domaene (`guard_evaluation`) und
harness-spezifischer Mechanik. Die Guard-Regeln selbst liegen NICHT im Adapter.

## 76.5 Harness-Settings-Schemas (alleiniger Owner)

FK-76 ist der **einzige normative Owner** der harness-spezifischen Settings-
Dateiformate. Die Hook-INHALTE (Matcher + Command pro Guard) sind harness-
neutral und stammen aus FK-30 §30.3.1; FK-76 definiert die harness-spezifische
**Materialisierung**.

### 76.5.1 Claude Code — `.claude/settings.json`

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "command": "agentkit-hook-claude pre branch_guard" }
    ],
    "PostToolUse": [
      { "matcher": "Agent|Bash|*_send", "command": "agentkit-hook-claude post telemetry" }
    ]
  }
}
```

Identitaet eines Eintrags ist `(hook_event_name, matcher, command)` — mehrere
Guards duerfen denselben Matcher teilen (z. B. `Bash` fuer `branch_guard` UND
`story_creation_guard`); ein Merge nach Matcher allein ist unzulaessig
(verwirft Guards).

### 76.5.2 Codex — `.codex/hooks.json`

Codex verwendet eine **dreistufige** Shape (Event → Matcher-Gruppe →
Handler-Liste), nicht die flache Claude-Form:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "agentkit-hook-codex pre branch_guard" }
        ]
      }
    ]
  }
}
```

Regeln (verifiziert gegen `developers.openai.com/codex/hooks`; die Live-Doku ist
Drift-Check, dieses Schema ist die Spezifikation):

- Command-Wrapper: `agentkit-hook-claude {phase} {hook_id}` →
  `agentkit-hook-codex {phase} {hook_id}` (parse/validate; abweichende Form →
  typisierter Fehler, kein stiller Passthrough).
- Tool-Matcher-Mapping (tokenweise) gegen das reale Codex-Tool-Vokabular:
  `Bash`→`Bash`; `Write`+`Edit`→ EIN `apply_patch`; bekannt-nicht-
  repraesentierbare Tokens (`Read`/`Grep`/`Glob`/`Agent`/`WebSearch`/
  `WebFetch`/`*_send`, je nach Live-Doku) entfallen **tokenweise** mit Diagnose;
  ein Matcher, der nach Entfall leer ist, schreibt keinen Codex-Hook
  (dokumentierte Nicht-Anwendbarkeit); ein Token ausserhalb des bekannten
  §30.3.1-Satzes → ERROR (FAIL CLOSED).
- Merge-Identitaet: Event + Matcher + Command/Handler (mehrere Handler je
  Matcher-Gruppe erlaubt).

### 76.5.3 Codex-Trust-Layer

Repo-lokale Codex-Hooks laufen nur in **trusted** `.codex`-Layern; nicht-managed
Hooks werden uebersprungen. Die tatsaechliche Trust-Aktivierung ist
Installer-Sache (FK-50/FK-51); FK-76 bildet die Aktivierungsgrenze ab.

## 76.6 Hybrid-Form: Sub-Agent ueber zweiten Harness

Ein Harness-Adapter kann einen **anderen Harness** als Sub-Agent spawnen
(z. B. Claude Code spawnt einen Codex-Sub-Agent). Disziplin:

- Der Sub-Agent **laeuft durch die Hooks des aeusseren Harness** — vermittelt
  durch dessen Adapter, nicht durch einen Inner-Harness-Adapter.
- Der Sub-Agent erscheint in den Outer-Hooks als regulaerer Sub-Agent
  (`principal_kind = subagent`), nicht als „fremder Harness".
- Das gesamte Guard-Regelwerk des aeusseren Harness gilt auch fuer den
  Sub-Agent (QA-Artefaktschutz, Branch-Guard, Worker-Health-Monitor).

Diese Hybrid-Form ist die **Standard-Empfehlung** fuer harness-uebergreifendes
Arbeiten.

## 76.7 Installation: parallele Registrierung

Die Installation registriert **beide Harnesses parallel** (Mechanik: FK-50
§CP9). FK-76 liefert das Format; FK-50 ruft `register_hooks` pro Harness und
materialisiert ueber den jeweiligen Adapter:

- Settings fuer Claude Code (`.claude/...`) werden geschrieben.
- Settings fuer Codex (`.codex/hooks.json`) werden geschrieben.
- Wrapper-Schnitt: **FK-76** definiert das Wrapper-Protokoll und die
  Command-Namen (`agentkit-hook-claude`, `agentkit-hook-codex`); **FK-50**
  definiert Installationsort (z. B. `tools/agentkit/`), Dateierzeugung und
  Merge-/Preservation-Strategie. Die Wrapper selbst sind harness-neutral.

Es gibt **keine** „aktiver Harness"-Konfiguration im Projekt; der Stratege
waehlt beim Session-Start `claude` oder `codex`.

**Zweistufiges Skill-Laden und Re-Install-Vertrag.** Der Harness liest
Skills in zwei Stufen: Stufe 1 — beim **Session-Start** wird die
`SKILL.md`-Frontmatter (`name` + `description`) **aller** gebundenen
Skills eager in die Discovery-Liste gelesen; Stufe 2 — der restliche
Inhalt (Body + gebundelte Dateien) wird **lazy erst beim Aufruf** des
Skills gelesen. AK3 startet keine Sessions selbst (Owner ist der Harness;
Sessions koennen parallel laufen) und kann die Bindung daher zur Laufzeit
nicht umhaengen. Skill-Bindungen sind **install-zeit-fest** (FK-43
§43.5.3). Ein Re-Install/Upgrade aendert die Bundle-Bindung; weil eine
ueber den Re-Install hinweg laufende Session bereits alte Header im
Kontext haelt und danach neue Bodies laed (Header-Body-Schieflage), gilt
der Betriebsvertrag: **Nach einem Re-Install muessen die Harnesses neu
gestartet werden.** Die Mechanik der Aufforderung liegt beim Installer
(FK-50 CP8).

## 76.8 Was bewusst NICHT Teil ist

FK-76 bleibt eine **duenne** BC (keine „God-Foundation"):

- Keine Guard-Policy, keine Hook-Definition (FK-30).
- Keine Story-, Prompt-, QA- oder Telemetrie-Semantik.
- Keine Installations-Strategie jenseits der adapter-spezifischen Artefakte (FK-50).
- Keine Plugin-Registry, keine Harness-Selection-Policy.
- Oeffentliche Surface klein: `HarnessPort`, `HarnessInvocation`,
  `HarnessHookEnvelope`, `HarnessCapability`, `HarnessAdapterResult` plus die
  Settings-Writer.

## 76.9 Importrichtung (normativ)

- `harness_integration` (aktuell physisch `governance.harness_adapters`)
  **importiert** harness-neutrale Contracts aus
  `governance` (z. B. `HookDefinition`, `HookEvent`, `GuardVerdict`).
- `governance` **importiert** `harness_integration` **nicht** im Kern; wo
  `register_hooks` die Settings materialisiert, geschieht das ueber einen
  harness-neutralen Port + Dependency-Injection (Composition-Root), nicht ueber
  einen harten Import konkreter Adapter.
- `installation-and-bootstrap` ruft `harness_integration` zur Install-Zeit auf.
- `prompt-runtime` darf den `HarnessPort` nutzen, kennt aber keine
  `.claude`/`.codex`-Interna.
- Andere BCs greifen nur ueber die exponierte Surface zu; konkrete Adapter sind
  nicht direkt importierbar.
