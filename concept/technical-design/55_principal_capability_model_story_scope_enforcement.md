---
concept_id: FK-55
title: Principal- und Capability-Modell mit storybezogener Enforcement-Semantik
module: principal-capabilities
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: principal-capability-model
  - scope: story-scoped-capabilities
  - scope: capability-freeze
  - scope: official-service-principals
defers_to:
  - target: FK-30
    scope: hook-infrastructure
    reason: Capability-Entscheidungen werden ueber Hook-Enforcement technisch durchgesetzt
  - target: FK-31
    scope: guard-rules
    reason: Branch-/Orchestrator-/QA-/Adversarial-Guards materialisieren das Capability-Modell
  - target: FK-35
    scope: escalation-and-integrity
    reason: Freeze- und Resolution-Folgen muessen am Integrity-Gate nachweisbar sein
  - target: FK-42
    scope: ccag
    reason: CCAG darf harte Capabilities nicht aufweichen
supersedes: []
superseded_by:
tags: [principal, capability, story-scope, freeze, guard-enforcement, permissions]
prose_anchor_policy: strict
formal_refs:
  - formal.principal-capabilities.entities
  - formal.principal-capabilities.state-machine
  - formal.principal-capabilities.commands
  - formal.principal-capabilities.events
  - formal.principal-capabilities.invariants
  - formal.principal-capabilities.scenarios
---

# 55 — Principal- und Capability-Modell mit storybezogener Enforcement-Semantik

<!-- PROSE-FORMAL: formal.principal-capabilities.entities, formal.principal-capabilities.state-machine, formal.principal-capabilities.commands, formal.principal-capabilities.events, formal.principal-capabilities.invariants, formal.principal-capabilities.scenarios -->

## 55.1 Zweck

Dieses Kapitel zieht die in DK-01, DK-06, FK-30, FK-31 und FK-35
bereits angelegte Trennung zwischen Rolle, Verantwortung und Zugriff
zu einem technisch umsetzbaren Capability-Modell zusammen.

Die Leitfrage lautet nicht:

> Was darf der Agent laut Prompt?

sondern:

> Welche Operationen kann ein Principal auf Plattformebene technisch
> ueberhaupt ausfuehren?

Das Ziel ist, dass ein Orchestrator oder anderer Principal nicht aus
Hilfsbereitschaft, Zeitdruck oder absichtlichem Regelbruch in
verbotene Mutationen ausbrechen kann.

## 55.2 Grundprinzip

AK3 unterscheidet strikt zwischen:

1. **fachlichen Rollen**
   - z.B. `qa_review`, `semantic_review`, `doc_fidelity`
2. **technischen Principals**
   - also Ausfuehrungsidentitaeten mit Capability-Profil

Nicht jede fachliche Rolle ist ein eigener Principal. Ein
StructuredEvaluator ohne Dateisystemzugriff benoetigt keinen eigenen
schreibfaehigen Principal. Umgekehrt darf ein Principal mit
Schreibrechten nur fuer exakt definierte Pfad- und Operationsklassen
verwendet werden.

## 55.3 Kanonische Principals

AK3 verwendet normativ diese Principal-Typen:

| Principal | Zweck | Typische Instanz |
|-----------|------|------------------|
| `orchestrator` | reine Ablaufsteuerung, Agent-Spawn, Phasenrouting | Hauptagent |
| `worker` | Story-Umsetzung in produktiven Repo-Pfaden | Implementation-Worker |
| `qa_reader` | Review, Tests, Befundermittlung ohne Produktiv-Write | QA-/Review-Agent |
| `adversarial_writer` | Schreiben und Ausfuehren adversarialer Tests in Sandbox | Adversarial-Agent |
| `llm_evaluator` | strukturierte Bewertung ohne lokale Toolrechte | QA-/Semantic-/Conformance-Evaluator |
| `pipeline_deterministic` | deterministische AgentKit-Skripte mit offizieller Mutationshoheit | Setup, Verify, Closure |
| `human_cli` | menschlich ausgeloeste administrative Entscheidungen | `agentkit ...` durch Menschen |
| `admin_service` | offizieller administrativer Servicepfad innerhalb AgentKit | `StoryResetService`, `StorySplitService`, spaeter Konfliktauflosung |

**Normative Reduktion:** Weitere Principals duerfen nicht ad hoc aus
Prompts entstehen. Neue Principal-Typen erfordern ein eigenes
Feinkonzept oder eine Erweiterung dieses Kapitels.

## 55.3a Principal-Attestierung

Ein `principal_type` ist nur gueltig, wenn er technisch attestiert
wurde. Prompt-Inhalt, Agent-Beschreibung oder Kommandostring sind
kein Nachweis.

Zulaessige Attestierungsquellen:

1. Hook-Kontext der Plattform (`is_subagent`, Prozesskontext)
2. aktiver Lock-/Run-Kontext im State-Backend
3. lokaler Export der aktiven Story-/Freeze-Bindung
4. expliziter Service-Attest fuer `pipeline_deterministic`,
   `admin_service` oder `human_cli`

Fehlt ein solcher Nachweis, gilt fail-closed die restriktivste
Bewertung.

## 55.4 Pfad- und Objektklassen

Capabilities werden nicht nur auf Tool-Namen, sondern auf
Pfad-/Objektklassen aufgeloest.

| Klasse | Beispiele | Bedeutung |
|--------|-----------|-----------|
| `codebase_story_scope` | Dateien in den fuer die Story aktiven Repo-Worktrees | Produktiver Story-Write-Scope |
| `codebase_out_of_scope` | produktive Repo-Pfade ausserhalb des Story-Scope | fuer Worker/QA/Adversarial verboten |
| `qa_sandbox` | `_temp/adversarial/{story_id}/`, ephemere QA-Arbeitsbereiche | nur fuer Adversarial/official promotion |
| `control_plane` | `phase_state_projection`, Marker, reduzierte Steuerungsartefakte | lesbar fuer Orchestrator |
| `content_plane` | `context.json`, `are_bundle.json`, handover- oder bundleartige Inhaltsartefakte | fuer Orchestrator gesperrt |
| `governance_plane` | `_temp/governance/**`, Lock-Exporte, Guardrail-Zustaende | nur offizielle Servicepfade |
| `git_internal` | `.git/**`, Refs, Index, Worktree-Interna | nie frei manipulierbar |
| `repo_admin_surface` | GitHub-Issue-/Project-Status, Story-Custom-Fields, Split-/Reset-Aktionen | nur offizielle AgentKit-Kommandos |

## 55.5 Operationsklassen

Jeder Tool-Aufruf wird vor der Entscheidung auf eine
Operationsklasse normalisiert:

| Operation | Beispiele |
|-----------|-----------|
| `read` | `Read`, `Grep`, `Glob`, `cat`, lesende Git-/Shell-Aufrufe |
| `write` | `Write`, `Edit`, Shell-Dateimutationen |
| `execute` | Testlauf, Build, Toolausfuehrung |
| `git_mutation` | Commit, Push, Branch-/Worktree-Aenderung |
| `curate` | semantische Mutation an Story-/ARE-/Dependency-Zuordnungen |
| `admin_transition` | Reset, Split, offizielle Konfliktaufloesung, registrierte Servicepfade |

## 55.6 Capability-Entscheidung

Die Capability-Entscheidung wird nicht aus Prompts gelesen, sondern aus
einem festen Tupel:

```text
(principal_type,
 project_key,
 story_id?,
 run_id?,
 active_story_scope,
 active_freeze?,
 tool_name,
 operation_class,
 path_class,
 command_signature?)
```

Die Plattform entscheidet daraus deterministisch:

- `ALLOW`
- `BLOCK`
- `ALLOW_VIA_OFFICIAL_SERVICE_PATH`

CCAG darf nur bei einem potentiellen `ALLOW` oder `ASK` innerhalb der
bereits erlaubten Capability-Zone helfen. Ein `BLOCK` aus dem harten
Capability-Modell bleibt `BLOCK`.

### 55.6.1 Modus-scharfe Unknown-Permission-Regel

Fuer unbekannte Permissions gelten abhaengig vom Ausfuehrungsmodus
unterschiedliche Regeln:

| Modus | Unbekannte Permission | Ergebnis |
|------|------------------------|----------|
| `story_execution` | keine passende Regel, nicht hart verboten | `BLOCK` + `permission_request_opened` |
| `interactive_admin` | keine passende Regel | externer Prompt zulaessig |
| `ai_augmented` | keine passende Regel | externer Prompt zulaessig |

**Normative Regel:** Im `story_execution`-Modus darf ein Tool-Aufruf nie
an einem nativen Host-Prompt haengen. Der Hook blockiert sofort und
erzeugt stattdessen einen auswertbaren Permission-Fall.

## 55.7 Storybezogene Scope-Aufloesung

Das Modell darf den Orchestrator nicht einfach global kastrieren.
Deshalb werden Schreibrechte storybezogen geschnitten.

### 55.7.1 Story-Scope-Quelle

Der aktive Story-Scope ergibt sich aus:

1. den Participating Repos / Worktrees der Story
2. den projektlokalen Story-Arbeitsverzeichnissen
3. explizit registrierten ephemeren Sandboxes

### 55.7.2 Worker

`worker` darf:

- `read`, `write`, `execute` in `codebase_story_scope`
- `read` auf relevante Control-/Content-Plane-Artefakte
- keine Mutation an `git_internal`
- keine Mutation an `governance_plane`
- keine ARE-Kuratierung
- keine Repo-/Project-Admin-Operationen

### 55.7.3 QA Reader

`qa_reader` darf:

- `read` in `codebase_story_scope`
- `execute` fuer Tests und Analyse
- keine `write` auf produktive Codebase
- keine Mutation an QA-Artefakten ausser ueber offizielle Pipeline-Skripte

### 55.7.4 Adversarial Writer

`adversarial_writer` darf:

- `read` in `codebase_story_scope`
- `write` und `execute` nur in `qa_sandbox`
- keine direkte Promotion in produktive Repo-Pfade

### 55.7.5 Orchestrator

`orchestrator` darf:

- `read` auf `control_plane`
- Agent-Spawn und Phasenuebergaenge initiieren
- offizielle AgentKit-Kommandos ausloesen, soweit sie fuer
  Orchestrator-Aufrufe explizit freigegeben sind

`orchestrator` darf **nicht**:

- `read` oder `write` auf `content_plane`
- `write` auf `codebase_story_scope`
- irgendeine Mutation an `git_internal`
- `write` auf `governance_plane`
- `curate` an ARE-/Story-/Dependency-Daten
- `admin_transition` ohne menschlich oder systemseitig privilegierten Pfad

## 55.8 Freeze-Modell fuer harte Konfliktfaelle

Bei `normative_conflict`, `authoritative_snapshot_divergence` oder
vergleichbaren HARD-STOP-Signalen wird ein storybezogener
`conflict_freeze` aktiviert.

### 55.8.1 Wirkung des Freeze

Solange `conflict_freeze` aktiv ist:

- `orchestrator` verliert jede storybezogene Mutationsberechtigung
- `worker`, `qa_reader` und `adversarial_writer` duerfen fuer diese
  Story keine neuen produktiven Fortschritte erzeugen
- nur `human_cli`, `pipeline_deterministic` oder `admin_service`
  duerfen ueber offizielle Pfade weiterfuehren

### 55.8.2 Ziel

Der Freeze ist keine freundliche Bitte, sondern eine technische
Sperrschicht. Er verhindert gerade, dass ein Orchestrator nach einem
HARD STOP "aufräumt", "repariert" oder Guard-Schranken umgeht.

## 55.9 Offizielle Servicepfade

Mutationen an besonders sensiblen Zonen duerfen nur ueber explizite
Servicepfade erfolgen.

| Pfad | Principal |
|------|-----------|
| `agentkit run-phase closure ...` interne Git-Mutationen | `pipeline_deterministic` |
| `agentkit split-story ...` | `admin_service` / `human_cli` |
| `agentkit reset-story ...` | `admin_service` / `human_cli` |
| `agentkit cleanup --story ...` fuer stale Runtime-Reste | `pipeline_deterministic` oder `human_cli` |
| kuenftig `agentkit resolve-conflict ...` | `admin_service` / `human_cli` |

**Normative Regel:** Ein freier Bash-Befehl darf nie denselben
Capability-Status erhalten wie ein offizieller Servicepfad.

## 55.9a Permission-Request- und Lease-Modell

Damit unbekannte Freigaben nicht den laufenden Tool-Call blockieren,
trennt AK3 strikt zwischen:

1. `permission_request`
   - ein offener, auditierbarer Einzelfall
   - noch keine neue Dauerregel
2. `permission_lease`
   - eine explizit erteilte, befristete Ausnahme fuer
     `project_key + story_id + run_id + principal_type +
     tool_name + operation_class + path_class + request_fingerprint`
3. persistenter CCAG-Regel
   - nur nach bewusster, dauerhafter Freigabe

**Wichtige Regel:** Die erste Entscheidung ist immer ein Einzelfall.
Ein `permission_request` darf ohne ausdrueckliche Zusatzentscheidung
nicht automatisch in eine neue Dauerregel uebergehen.

**Einzelfall-Schaerfe:** Eine Lease ist bewusst enger geschnitten als
eine Dauerregel. Sie bindet an einen normalisierten Request-Fingerprint
und darf optional mit `max_uses = 1` als consume-once-Lease modelliert
werden.

**Run-Zustandsregel:** `permission_request_opened` setzt den aktiven Run
auf `PAUSED`. `permission_request_expired` fuehrt ohne menschliche
Entscheidung zu `ESCALATED`. Eine Freigabe erzeugt nur die Lease; sie
setzt den Run nicht implizit fort. Fuer die Fortsetzung ist ein
expliziter Resume-Pfad notwendig.

### 55.9a.1 Externe Permission-Substrate

Claude Codes native Permission-Dialoge, TTY-Interaktivitaet und
hostseitige Sonderfaelle fuer `.git`, `.claude`, `.vscode`, `.idea`
oder `.husky` sind fuer AK3 kein autoritatives Sicherheitsmodell,
sondern ein `external_permission_substrate`.

Dieses Substrat kann Verhalten ausloesen, das AK3 nicht vollstaendig
kontrolliert. Deshalb gilt:

- externe Prompts sind nie Source of Truth fuer Capability-Entscheidungen
- aktiver Story-Fortschritt darf nicht von ihnen abhaengen
- ihr Auftreten im `story_execution`-Modus ist ein
  `external_permission_interference_detected`-Fall

## 55.10 Technische Umsetzung

### 55.10.1 Principal-Erkennung

Der Hook-Kontext wird um einen normativen `principal_type`-Wert
erweitert. Fehlt dieser, gilt fuer sicherheitsrelevante Faelle
fail-closed die restriktivste Bewertung.

**Minimale Ableitungsregel:**

- `is_subagent == false` -> mindestens `orchestrator`
- privilegiertere Typen wie `pipeline_deterministic`,
  `admin_service` und `human_cli` erfordern einen expliziten
  Attestierungsnachweis
- ohne Attestierung wird kein Aufruf in einen privilegierten
  Principal hochgestuft

### 55.10.2 Pfadklassifikation

Vor jeder Entscheidung werden Tool-Input und Shell-Argumente auf
kanonische Pfadklassen normalisiert. Regex auf Git-Befehle allein
reichen nicht aus. Insbesondere muessen Bash-Dateimutationen unter
`.git/**`, `_temp/governance/**` und `content_plane` direkt erkannt und
blockiert werden, selbst wenn kein `git`-Subkommando vorkommt.

**Performance-Regel:** Der Hook darf keine teure semantische
Shell-Interpretation betreiben. Er arbeitet primaer mit:

- lokal exportierten Story-Scope-Pfaden
- geschuetzten Prefix-Tabellen
- preisguenstiger Pfadnormalisierung

Kann ein Ziel nicht billig und kanonisch aufgeloest werden, ist die
Entscheidung fail-closed `BLOCK`.

### 55.10.3 Auswertungsreihenfolge

Die Entscheidung muss in genau dieser Reihenfolge fallen:

1. Hook-Event lesen
2. `execution_mode` aus lokalen Lock-/Run-Exports ableiten
3. `principal_type` fail-closed aufloesen
4. `story_scope_binding` aus State-Backend lesen
4. Tool-Aufruf auf `operation_class` normalisieren
5. betroffene Ziele auf `path_class` normalisieren
6. harte Capability-Matrix pruefen
7. aktives `conflict_freeze` ueberlagern
8. nur wenn erlaubt: offiziellen Servicepfad pruefen
9. nur wenn weiterhin nicht blocked: Modusregel fuer unbekannte
   Permissions anwenden
10. erst danach: zentrale CCAG-Entscheidung auswerten
11. stale Permission-Requests lazy expirieren
12. erst danach, falls zulaessig: externer Prompt pruefen
13. Ergebnis + Begruendung als Event emittieren

### 55.10.4 Referenz-Pseudocode

```python
def evaluate_capability(event: HookEvent) -> CapabilityVerdict:
    mode = derive_execution_mode_from_local_locks(event)
    principal = resolve_principal_type(event)           # fail-closed
    scope = load_story_scope_binding(event.project_key, event.story_id)
    freeze = load_active_conflict_freeze(event.project_key, event.story_id)
    expire_stale_permission_requests(event.project_key, event.story_id, event.run_id)

    op_class = classify_operation(event.tool_name, event.tool_input)
    path_classes = classify_targets(event.tool_name, event.tool_input, scope)

    for path_class in path_classes:
        if hard_matrix_denies(principal, op_class, path_class, scope):
            return deny("hard_matrix", principal, op_class, path_class)

        if freeze and freeze_denies(principal, op_class, path_class):
            return deny("freeze_overlay", principal, op_class, path_class)

    if is_official_service_path(event, principal):
        return allow("official_service_path", principal, op_class)

    ccag_decision = evaluate_ccag(event.tool_name, event.tool_input,
                                  event.is_subagent, mode)
    if mode == "story_execution" and ccag_decision == "unknown_permission":
        open_permission_request(event, principal, op_class, path_classes)
        return deny("unknown_permission", principal, op_class, path_classes)
    if ccag_decision == "block_by_rule":
        return deny("ccag_block_rule", principal, op_class, path_classes)
    if ccag_decision == "allow":
        return allow("ccag_allow_rule", principal, op_class, path_classes)
    return ask_external_or_allow(event, principal, op_class, path_classes)
```

Die entscheidende Eigenschaft ist:

- `ccag_or_allow(...)` wird niemals aufgerufen, wenn harte Matrix oder
  Freeze bereits `deny` geliefert haben.
- im `story_execution`-Modus fuehrt eine unbekannte Freigabe nicht zu
  einem wartenden Prompt, sondern zu `permission_request_opened` +
  `deny`

### 55.10.4 Story-Scope-Export fuer Hooks

Der Hook liest den storybezogenen Scope nicht live aus langsamen
Abfragen zusammen. Beim Story-Start bzw. bei Scope-Aenderungen wird ein
lokaler Export materialisiert, z. B.:

```text
.agent-guard/scope.json
```

Dieser Export enthaelt mindestens:

- `project_key`
- `story_id`
- `run_id`
- `participating_repo_roots`
- `sandbox_roots`
- `content_plane_roots`
- `governance_roots`
- `freeze_version`
- `permission_state_version`

Der Export ist ein Hook-Hilfsartefakt, nicht die kanonische Wahrheit.
Kanonisch bleibt das State-Backend. Fehlt der Export oder ist er
inkonsistent, gilt fail-closed.

### 55.10.4a Lokaler Permission-State-Export

Offene Permission-Requests und aktive Leases werden zusaetzlich lokal
materialisiert, z. B. in:

```text
.agent-guard/permission_state.json
```

Der Export enthaelt mindestens:

- offene `permission_request`-IDs fuer `story_id + run_id`
- `expires_at`
- aktive `permission_lease`-Fingerprints
- `permission_state_version`

Ohne diesen Export koennen `max_open_requests_per_run`, lazy expiry und
lease-basierte Retries nicht billig genug im Hook durchgesetzt werden.

### 55.10.5 Atomarer Conflict-Freeze

`conflict_freeze` wird doppelt materialisiert:

1. kanonisch als Lock-/Freeze-Record im State-Backend
2. lokal als Hook-schnell lesbarer Export mit `freeze_version`

Die Aktivierung muss atomar in diesem Sinn sein:

- zuerst Freeze-Record persistieren
- danach lokalen Export mit derselben `freeze_version` schreiben
- jeder nachfolgende Hook-Call prueft auf diese Version

Ein Call mit veraltetem oder fehlendem Freeze-Kontext wird blockiert.

### 55.10.6 Freeze-Overlay

Nach der Basisentscheidung wird ein storybezogenes Freeze-Overlay
angewandt:

- wenn `conflict_freeze` aktiv ist und `principal_type == orchestrator`,
  dann `BLOCK` fuer alle `write`, `git_mutation`, `curate`,
  `admin_transition` ausser offiziell freigegebene Pfade

### 55.10.7 Offizielle Servicepfade sind nicht per Bash spooffaehig

Ein offizieller Servicepfad ist nur dann privilegiert, wenn er mit
einem Service-Attest ausgefuehrt wird.

Das bedeutet explizit:

- `agentkit split-story ...` oder `agentkit resolve-conflict ...` als
  freier Bash-String eines Agenten ist **nicht** automatisch ein
  offizieller Servicepfad
- privilegiert sind nur durch Plattform/CLI attestiere Aufrufe von
  `human_cli`, `pipeline_deterministic` oder `admin_service`

### 55.10.8 Integrity-Nachweis

Wurde ein `conflict_freeze` gesetzt, muss spaeter im Audit und am
Integrity-Gate nachweisbar sein:

- wann der Freeze aktiviert wurde
- welcher Principal geblockt wurde
- ueber welchen offiziellen Pfad die Aufloesung geschah

Fehlt dieser Nachweis, ist der Run nicht closure-faehig.

### 55.10.9a Permission-Timeouts

Ein `permission_request` ist kein unendlicher Schwebezustand. Es traegt
mindestens:

- `requested_at`
- `expires_at`
- `resolution`

Laeuft die Frist ab, ohne dass der Mensch explizit entscheidet, wird der
Fall deterministisch als `DENIED` abgeschlossen. Diese Ablehnung erzeugt
keine neue Regel und keine neue Lease.

Die Expiration wird nicht durch einen permanenten Daemon erzwungen,
sondern lazy beim naechsten relevanten Hook-/CLI-Zugriff materialisiert.

### 55.10.10 Rueckkanalgrenze zum Orchestrator

Die Capability-Grenze endet nicht am Dateisystem. Auch der semantische
Rueckkanal zum Orchestrator ist zu begrenzen.

Sub-Agents und offizielle Servicepfade duerfen an den Orchestrator nur
schema-gebundene Steuerungsausgaben liefern, z. B.:

- `status`
- `error_class`
- `next_step`
- `artifact_refs`
- kurze, strukturierte Begruendung

Nicht zulaessig sind ueber diesen Rueckkanal:

- rohe Code-Diffs
- Zitate aus `context.json` oder `are_bundle.json`
- vollstaendige Inhaltsartefakte
- freie Prompt- oder Bundle-Listen

Das Ziel ist, dass `orchestrator` auch ueber Sub-Agent-Outputs nicht
wieder faktisch in einen Content-Plane-Principal zurueckverwandelt
wird.

## 55.11 Architekturentscheidung

Die Sicherheitsgrenze in AK3 verlaeuft nicht zwischen "gutem" und
"boesem" Agenten, sondern zwischen **Capabilities, die ein Principal
technisch hat**, und denen, die er nicht hat.

Das System darf also nicht darauf bauen, dass der Orchestrator seine
Prompt-Regeln befolgt. Es muss so geschnitten sein, dass er verbotene
Aktionen selbst bei absichtlichem Regelbruch nicht mehr ausfuehren
kann.
