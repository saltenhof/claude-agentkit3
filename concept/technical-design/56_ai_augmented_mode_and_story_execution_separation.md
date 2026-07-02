---
concept_id: FK-56
title: Betriebsmodi — AI-Augmented und Story-Execution sauber getrennt
module: operating-modes
domain: story-lifecycle
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: operating-modes
  - scope: run-binding
  - scope: baseline-vs-story-governance
defers_to:
  - target: FK-59
    scope: story-contract-classification
    reason: operating_mode wird dort explizit als abgeleitete Laufzeitachse eingeordnet
  - target: FK-30
    scope: hook-enforcement
    reason: Betriebsmodi werden technisch ueber Hooks und Run-Bindung wirksam
  - target: FK-55
    scope: principal-capabilities
    reason: Principals und Capabilities muessen mode-scharf interpretiert werden
  - target: FK-05
    scope: integration-stabilization
    reason: Stabilisierungs-Stories erzeugen keinen dritten Modus, sondern bleiben unter story_execution
  - target: FK-58
    scope: story-exit
    reason: Offizieller Exit aus story_execution nach ai_augmented wird dort normiert
supersedes: []
superseded_by:
tags: [operating-modes, ai-augmented, story-execution, run-binding, integrity]
prose_anchor_policy: strict
glossary:
  exported_terms:
    - id: operating-mode
      definition: >
        Abgeleitete Laufzeitachse der aktiven Session: ai_augmented
        (freies Arbeiten, kein Story-Regime) oder story_execution
        (explizit gebundener Story-Run mit vollem Guard-, QA- und
        Integrity-Regime). Wird deterministisch aus Run-Bindung, Lock
        und Worktree-Konsistenz abgeleitet, nicht persistent als
        Story-Feld gefuehrt.
      values: [ai_augmented, story_execution]
      see_also:
        - term: run-binding
          domain: story-lifecycle
        - term: execution-route
          domain: story-lifecycle
    - id: run-binding
      definition: >
        Aktive Session-Bindung an genau einen Story-Run, bestehend aus
        project_key, story_id, run_id, principal_type und
        worktree_roots. Voraussetzung fuer den Betriebsmodus
        story_execution. Fehlt die Bindung oder ist sie inkonsistent,
        gilt der Fehlerzustand binding_invalid, kein stiller Rueckfall
        auf ai_augmented.
      see_also:
        - term: operating-mode
          domain: story-lifecycle
    - id: run-ownership-record
      definition: >
        Kanonischer, DB-erzwungener Ownership-Anker eines Story-Runs
        mit Identitaet (project_key, story_id, run_id) und den
        Attributen owner_session_id, ownership_epoch, status,
        acquired_via und acquired_at. Pro Story existiert hoechstens
        ein aktiver Record; historische Records sind reine
        Audit-Fakten und nie Admission-Evidenz. Die Run-Bindung ist
        seine session-seitige Projektion.
      see_also:
        - term: run-binding
          domain: story-lifecycle
        - term: ownership-transfer
          domain: story-lifecycle
    - id: ownership-transfer
      definition: >
        Expliziter, zweistufig bestaetigter Uebergang eines aktiven
        Story-Runs von einer Session auf eine andere
        (Challenge-Confirm, CAS auf ownership_epoch). Der Run wird
        unter gleichem run_id fortgefuehrt; Uebergabeobjekt ist
        ausschliesslich der beim Confirm materialisierte
        takeover_base_sha (gepushter Stand), die worktree_roots der
        neuen Bindung sind Edge-gemeldet. Die entmuendigte Session
        geht nach binding_invalid mit Grund ownership_transferred.
      see_also:
        - term: run-binding
          domain: story-lifecycle
        - term: run-ownership-record
          domain: story-lifecycle
  internal_terms:
    - id: binding-invalid
      reason: >
        Blockierender Fehlerzustand bei gebrochener Story-Bindung (stale
        Lock, Worktree-Mismatch). Kein eigenstaendiger Betriebsmodus;
        nur BC-intern relevant fuer die Mode-Resolution-Logik.
formal_refs:
  - formal.operating-modes.entities
  - formal.operating-modes.state-machine
  - formal.operating-modes.commands
  - formal.operating-modes.events
  - formal.operating-modes.invariants
  - formal.operating-modes.scenarios
  - formal.story-exit.state-machine
  - formal.story-exit.invariants
  - formal.story-contracts.invariants
---

# 56 — Betriebsmodi — AI-Augmented und Story-Execution sauber getrennt

<!-- PROSE-FORMAL: formal.operating-modes.entities, formal.operating-modes.state-machine, formal.operating-modes.commands, formal.operating-modes.events, formal.operating-modes.invariants, formal.operating-modes.scenarios, formal.story-exit.state-machine, formal.story-exit.invariants, formal.story-contracts.invariants -->

## 56.1 Zweck

AgentKit begleitet ein Projekt in zwei grundverschiedenen Betriebsarten:

1. `ai_augmented`
   - freies, menschlich gefuehrtes Arbeiten mit Harness-Agents
     (Claude Code oder Codex; FK-76)
   - keine aktive Story-Ausfuehrung
   - keine Workflow- oder Integrity-Pflichten
2. `story_execution`
   - explizit gebundener Story-Run mit `project_key + story_id + run_id`
   - volles Guard-, QA-, Verify- und Integrity-Regime

Dieses Kapitel zieht die Trennung normativ und technisch so scharf, dass
freie Arbeit nicht versehentlich als Story-Ausfuehrung behandelt wird.

**Grenze dieses Kapitels:** Der Modus `ai_augmented` wird hier nur als
Abwesenheit von Story-Execution-Regime beschrieben. Die konkrete
inhaltliche Arbeitsweise des Menschen in diesem freien Modus wird durch
AgentKit nicht weiter fachlich ausmodelliert.

## 56.2 Grundregel

**Ohne explizite Run-Bindung gibt es keinen Story-Governance-Modus.**

Das bedeutet:

- kein Orchestrator-Guard
- kein QA-Artefakt-Schutz
- kein QA-Agent-Guard
- kein Adversarial-Sandbox-Zwang fuer freie Agents
- kein Worker-Health-Monitor
- kein Integrity-Gate
- keine Verify-/Closure-/Story-Prozesspflichten

Es bleiben nur die immer-aktiven Basisschutzregeln und CCAG.

## 56.3 Die zwei Betriebsmodi

| Modus | Wann | Charakter |
|------|------|-----------|
| `ai_augmented` | kein gueltiger `story_execution`-Lock, keine aktive Run-Bindung fuer die Session | freies, interaktives Arbeiten |
| `story_execution` | gueltiger `story_execution`-Lock plus aktive Session-/Run-Bindung | deterministischer Story-Workflow |

**Klarstellung:** Systemische Integrations- und Stabilisierungslagen
gemäss FK-05 erzeugen **keinen dritten Betriebsmodus**. Sie bleiben ein
Spezialvertrag innerhalb von `story_execution`.

### 56.3a `operating_mode` ist keine Story-Hauptklassifikation

`operating_mode` wird nicht als kanonisches Story-Hauptfeld gefuehrt.

Er ist:

- session- und run-gebunden
- aus Lock, Bindung und Worktree-Konsistenz abgeleitet
- fachlich getrennt von `story_type` und `implementation_contract`

Damit darf ein stale oder verloren gegangener Session-Zustand nicht als
vermeintlich persistente Story-Semantik weiterleben.

**Soll-Namespace der Mode-Resolution:** Der BC-Cut und
`PROJECT_STRUCTURE.md` verorten den `OperatingModeResolver` unter
`agentkit.backend.story_context_manager.operating_mode_resolver`. Die
fachliche Richtung bleibt
`story_context_manager/operating_mode_resolver/`.

## 56.4 Principals im Moduskontext

Der Hauptagent ist nicht immer derselbe technische Principal.

| Modus | Hauptagent-Principal |
|------|-----------------------|
| `ai_augmented` | `interactive_agent` |
| `story_execution` | `orchestrator` |

**Normative Regel:** `interactive_agent` und `orchestrator` sind nicht
dieselbe Capability-Klasse. Der freie interaktive Agent ist kein
"gelockerter Orchestrator", sondern ein eigener Principal ausserhalb des
Story-Workflows.

## 56.5 Was immer aktiv bleibt

Diese Regeln gelten in beiden Modi:

- CCAG
- Governance-Selbstschutz
- destructive Git baseline guards:
  - kein Force-Push
  - kein `git reset --hard`
  - kein `git branch -D`
- Secret-/Credential-Schutz
- Prompt-Integrity-Basisschutz gegen Governance-Escape und kaputte
  Spawn-Strukturen
- Story-Create-Guard, sofern Stories weiterhin nur ueber den
  offiziellen Pfad angelegt werden duerfen

## 56.6 Was nur in `story_execution` aktiv ist

- Branch-Isolation auf `story/{story_id}`
- Orchestrator-Guard
- QA-Artefakt-Schutz
- QA-Agent-Guard
- Adversarial-Sandbox-Guard
- storybezogene Capability-Freeze-Logik
- Worker-Health-Monitor
- Verify-/Closure-Prozess
- Integrity-Gate
- storygebundene Governance-Beobachtung

## 56.7 Technische Aktivierung

`story_execution` darf nie aus Prompt, Branchname oder lokaler Datei
allein geraten werden.

Es braucht **beides**:

1. einen kanonischen, gueltigen Lock-/Run-Record im State-Backend
2. eine aktive Session-Bindung auf genau diesen Run

Die Session-Bindung enthaelt in Multi-Repo-Faellen keine einzelne
`worktree_root`, sondern die Menge der erlaubten `worktree_roots`.

Hooks und Guards lesen diese Lage im Normalfall nicht per
State-Backend-Roundtrip, sondern aus einer lokal publizierten,
abgeleiteten Projektion:

- `_temp/governance/current.json`
- `_temp/governance/bundles/{export_version}/session.json`
- `_temp/governance/bundles/{export_version}/lock.json`
- `_temp/governance/bundles/{export_version}/qa-lock.json`

Fehlt beides, gilt:

- `ai_augmented`

Existiert dagegen bereits eine Session-Bindung, aber Lock oder
Worktree-Match sind inkonsistent, gilt **nicht** freier Modus, sondern
ein blockierender Fehlerzustand.

Die Run-Bindung ist dabei mehr als eine Modus-Voraussetzung: Sie ist
der session-seitige Anker der Eigentumsfrage. Wem die Umsetzung einer
Story gehoert, beantwortet kanonisch der Run-Ownership-Record
(§56.8a); die Bindung ist dessen session-seitige Projektion.

## 56.7a Invalide Story-Bindung

Wenn eine Session an einen Story-Run gebunden ist, aber mindestens eine
der technischen Voraussetzungen wegbricht, geht der Modus auf
`binding_invalid`.

Typische Ursachen:

- Lock-Record verloren oder stale
- Worktree stimmt nicht mehr mit der Bindung ueberein
- Run wurde extern beendet, Session ist aber noch gebunden
- Ownership wurde per Transfer entzogen (`ownership_transferred`,
  §56.13)

**Wirkung:**

- keine storygebundene Normalfortsetzung
- kein stiller Rueckfall in freien Modus
- mutierende Story-Aktionen blockieren fail-closed
- Mensch muss per offiziellem Pfad aufraeumen oder neu binden

**Der Grund ist explizit:** `binding_invalid` traegt einen
maschinenlesbaren Grund als Attribut des Fehlerzustands; ein eigener
Status pro Ursache existiert nicht. Mit dem Ownership-Transfer
(§56.13) kommt der Grund `ownership_transferred` hinzu. Fuer ihn gilt
praezisierend: Lesende Zugriffe — einschliesslich der Rekonsiliierung
eigener frueherer Mutationen ueber `GET operations/{op_id}` — bleiben
der entmuendigten Session erlaubt; mutierende Story-Aktionen werden
deterministisch mit Klartext-Grund und Verweis auf den neuen Owner
abgewiesen.

## 56.8 Run-Bindung

Die aktive Session-Bindung enthaelt mindestens:

- `project_key`
- `story_id`
- `run_id`
- `principal_type`
- `worktree_roots`
- `binding_version`

Lokale Exporte sind nur Materialisierung. Kanonisch bleibt der
State-Backend-Eintrag. Fuer Hook-Entscheidungen ist `current.json`
der einzige lokale Einstieg; einzelne Exportdateien oder
Worktree-Projektionen sind fuer sich allein nie ausreichend.
Story-spezifische Zusatzsignale wie der QA-Artefakt-Schutz werden aus
dem vollstaendigen Bundle gelesen; auch `qa-lock.json` ist fuer sich
allein nie autoritativ.

Die Bindung ist zugleich die session-seitige Projektion des
Run-Ownership-Records (§56.8a): Sie loest den Betriebsmodus auf und
traegt die Session-Sicht (Principal, Worktrees, `binding_version`),
ist dem Ownership-Record aber nachgeordnet. Bei Widerspruch zwischen
Bindung und aktivem Ownership-Record gilt der Ownership-Record.

### 56.8a Run-Ownership-Record

Der Umsetzungs-Lebenszyklus einer Story — ihr aktiver Run, ihr
Worktree-Regime, ihr Phasenfortschritt — gehoert hoechstens einer
Session, und waehrend eines aktiven Execution-Regimes genau einer.
Damit diese Regel nicht nur Konvention ist, wird sie an einem
kanonischen, DB-erzwungenen **Run-Ownership-Record** verankert:

- **Identitaet:** `(project_key, story_id, run_id)` — DB-erzwungen
  genau eine Zeile pro Run.
- **Attribute:** `owner_session_id`, `ownership_epoch` (monoton
  steigender Zaehler, beginnend bei 1 mit dem Setup), `status`
  (`active | transferred | ended | reset | split | closed`),
  `acquired_via` (`setup | takeover | recovery`), `acquired_at` sowie
  ein Audit-Verweis auf den ausloesenden Vorgang.
- **Aktiv-Invariante pro Story:** DB-erzwungen (Partial-Unique)
  existiert hoechstens ein Record mit `status=active` pro
  `(project_key, story_id)`. Alle Regime-Mutationen adressieren den
  aktuell aktiven Ownership-Record der Story, nicht irgendeinen
  Record zu einem `run_id`.
- **Historische Records sind audit-only.** Records mit anderem Status
  als `active` sind reine Audit-Fakten und niemals Admission-Evidenz;
  insbesondere kann ein entmuendigter Ex-Owner seine Bindung nicht
  ueber committed Run-Operationen re-materialisieren.
- **Fencing aller Regime-Mutationspfade:** Jeder mutierende Pfad des
  Execution-Regimes — ausdruecklich auch `complete_phase`,
  `fail_phase` und die Closure sowie die serverseitigen
  Executor-Pfade (`pipeline_deterministic`, `admin_service`) — fenct
  gegen `owner_session_id` und `ownership_epoch` des aktiven Records.
  System-Principals sind keine konkurrierenden Owner: Sie mutieren
  als gefencte Executor im Auftrag des aktuellen Execution-Regimes.
- **Accountability und Kontinuitaet:** Wer etwas verantwortet hat,
  haengt an `run_id + ownership_epoch`; die fachliche Kontinuitaet
  (Artefakte, Attempts, QA-Historie) haengt am `run_id`.

Formal: `operating-modes.entity.run-ownership-record` mit den
Invarianten `at_most_one_active_ownership_per_story`,
`historical_ownership_records_are_never_admission_evidence` und
`story_execution_mutations_require_current_ownership_epoch`.

## 56.9 Mode-Resolution

Der Hook darf den Modus nicht aus Host-UI oder Prompt erraten. Er leitet
ihn deterministisch ab:

```python
def resolve_operating_mode(event: HookEvent) -> str:
    current = load_current_edge_pointer()
    if current is None:
        return "ai_augmented"

    bundle = load_edge_bundle(current)
    if bundle.session.session_id != event.session_id:
        return "binding_invalid"

    if bundle.lock.status != "ACTIVE":
        return "binding_invalid"

    if not worktree_matches_binding(event.cwd, bundle.session.worktree_roots):
        return "binding_invalid"

    return "story_execution"
```

### 56.9a Bounded Re-Sync statt DB-Roundtrip pro Hook

Hooks fuehren keine zentrale Abfrage pro Tool-Call aus. Stattdessen
gilt:

- offizielle Zustandswechsel materialisieren lokal ein komplettes
  Edge-Bundle inklusive story-spezifischer Zusatzlocks wie
  `qa-lock.json`
- `current.json` zeigt atomar auf genau ein vollstaendiges Bundle
- jedes Bundle traegt ein `sync_after`
- nur der erste Hook nach Ablauf von `sync_after` darf einen bounded
  Re-Sync gegen AK3 ausloesen
- mutierende Story-Entscheidungen blockieren fail-closed, wenn der
  Bundle-Stand zu alt oder inkonsistent ist
- story-spezifische Guard-Entscheidungen duerfen fehlende lokale
  Zusatzsignale nicht stillschweigend ignorieren

## 56.10 Integrity-Gate-Abgrenzung

Das Integrity-Gate ist **kein** allgemeiner Live-Guard fuer freie
Projektarbeit. Es prueft ausschliesslich Story-Runs in der Closure-Phase.

Im `ai_augmented`-Modus gibt es deshalb:

- kein `integrity_gate_started`
- kein `integrity_gate_result`
- keine Closure-FAIL-Codes
- keine Pflicht auf Story-Telemetrie, Verify oder Review-Proofs

## 56.11 Prompt-Integrity im freien Modus

Der Prompt-Integrity-Guard bleibt aktiv, aber reduziert:

- Governance-Escape-Erkennung bleibt aktiv
- Freestyle-Spawn-Schema bleibt aktiv
- storyspezifische Template-Integritaet und Skill-Proof-Pflichten gelten
  nur in `story_execution`

Damit duerfen freie Sub-Agents im Projekt arbeiten, ohne in die
Story-Template-Maschinerie gezwungen zu werden.

## 56.12 Ende eines Story-Runs

Ein Story-Run endet technisch erst, wenn:

1. der Lock-/Run-Record beendet ist
2. die Session-Bindung geloest ist
3. das lokale Edge-Bundle auf den deaktivierten Zustand
   umgeschaltet wurde und Tombstones alte Exporte entfernt haben

Erst danach faellt die Session wieder auf `ai_augmented` zurueck.

### 56.12a Rueckfall nach offiziellem Story-Exit

Ein Rueckfall in `ai_augmented` ist auch ueber den offiziellen
Story-Exit gemaess FK-58 zulaessig.

Dabei gilt:

- kein stiller Rueckfall
- kein Mischzustand
- erst Exit-Gate, dann Binding-Revocation, dann `ai_augmented`

## 56.13 Ownership-Transfer (Takeover)

Es gibt einen offiziellen Uebergang
`story_execution`(Session A) → `story_execution`(Session B): den
Ownership-Transfer. Er ist der einzige Weg, einen aktiven Run unter
neuem Owner fortzufuehren — als Ergaenzung zu den Endpfaden
Story-Exit (FK-58), Reset (FK-53) und Split (FK-54), die den Run
beenden statt uebertragen. Der Transfer folgt fuenf Grundsaetzen:

1. **Nur explizit, nie automatisch.** Ausloeser ist immer ein Mensch
   (UI bzw. `human_cli`) oder ein Agent ueber den offiziellen
   Control-Plane-Pfad. Kein Heartbeat, kein Monitor und kein
   sonstiger Automatismus entreisst einer Session ihren Run;
   Ownership laeuft niemals aufgrund clientseitiger Stille ab.
2. **Zweistufig, informiert, CAS-gesichert** (§56.13a).
3. **Vollstaendig:** B wird Owner, A wird entmuendigt (§56.13c).
4. **Selbst eine Story-Mutation:** Der Transfer wird hinter laufenden
   Mutationen derselben Story serialisiert und wirkt dadurch als
   Fence; es gibt kein Fenster, in dem beide Sessions schreiben.
5. **Kein Ping-Pong** (§56.13d).

### 56.13a Challenge-Confirm-Protokoll

Der Transfer ist ein zweistufiges Challenge-Confirm-Protokoll:

- Die Anfrage (`request-run-ownership-takeover`) beantwortet das
  System nicht mit Vollzug, sondern mit einem **Challenge, der die
  Entscheidungsgrundlage versioniert**: mindestens
  `owner_session_id`, `ownership_epoch`, `binding_version`,
  Phasenstand sowie die Anzeigedaten (Principal, gebunden seit,
  letzter API-Kontakt mit Nicht-Diagnose-Hinweis, offene
  Jobs/`op_id`s, bisherige Takeover-Historie). Diese Daten stammen
  aus dem Owner-BC selbst, nicht aus einem moeglicherweise
  nachlaufenden Read-Model.
- Jede Anfrage traegt eine **Begruendungspflicht** (freies,
  auditiertes Begruendungsfeld).
- Die Bestaetigung (`confirm-run-ownership-takeover`, mit
  Challenge-Echo) ist ein **CAS auf
  `ownership_epoch`/`binding_version`**: Jede zwischenzeitliche
  Aenderung der Eigentumslage — Transfer, Exit, Reset, Split,
  Closure — invalidiert offene Challenges. Von zwei konkurrierenden
  Confirms gewinnt deterministisch genau einer; der zweite scheitert
  am veralteten Challenge und fragt neu an — dann gegen den neuen
  Owner und mit sichtbarer Takeover-Historie.
- Ein Challenge darf **befristet** sein. Die Frist ist ein
  Entscheidungs-Verfall (die offene Anfrage verfaellt), niemals ein
  Ownership-Entzug.

### 56.13b Berechtigung und menschliche Frontend-Freigabe

Die **Anfrage** steht `human_cli`/`admin_service` sowie Agents
(`interactive_agent`/`orchestrator`) ueber den offiziellen
Project-Edge-Pfad offen. Der **Vollzug** des Entmuendigens einer
fremden aktiven Session erfordert bei agenteninitiiertem Request eine
**menschliche Freigabe im Frontend**:

- Der agenteninitiierte Takeover-Request erzeugt eine ausstehende
  Freigabe-Anfrage, die im Frontend als **globaler
  Notification-Overlay** erscheint (Frontend-Verankerung: FK-72) —
  sofort sichtbar und **benutzeruebergreifend**: Sie ist nicht an
  einen spezifischen Benutzer gebunden; jeder eingeloggte Benutzer
  sieht sie und kann entscheiden. Erst die Bestaetigung in diesem
  Dialog vollzieht den Transfer.
- Der anfragende Agent erhaelt deterministisch die Antwort
  `pending_human_approval` — mit der expliziten Information, dass ein
  Benutzer die Uebernahme im Frontend freigeben muss —, sodass der
  Orchestrator seinen Benutzer informieren kann; den Ausgang
  beobachtet er ueber `GET operations/{op_id}`.
- Die ausstehende Freigabe gehoert zur Permission-Request-Familie
  (FK-42, FK-90): Sie darf als offene Anfrage verfallen (dann
  DENIED), entzieht aber niemals bestehendes Eigentum.
- Menschlich initiierte Takeovers (UI/CLI) durchlaufen denselben
  informierten Challenge-Dialog direkt. Der Vollzug wird als
  Operation der Klasse `admin_transition` (FK-55) gefuehrt und
  vollstaendig auditiert.

### 56.13c Atomarer Vollzug und Wirkung auf den Ex-Owner

Der Vollzug ist eine atomare Mutation:

- Ownership-Record per CAS auf B umgeschrieben:
  `ownership_epoch + 1`, `acquired_via=takeover`;
- A's Bindung revoked; neue Bindung fuer B's `session_id` auf
  denselben `run_id`, mit neuer `binding_version`; die
  `worktree_roots` der neuen Bindung sind die von B's Edge
  gemeldeten physischen Pfade (§56.13e, FK-10 §10.2.4a);
- Tombstone fuer A's lokales Edge-Bundle (Invalidierung der lokalen
  Projektion, analog §56.12);
- **Transfer-Record materialisiert:** Beim Confirm wird pro
  teilnehmendem Repo ein **`takeover_base_sha`** atomar festgehalten
  — der zu diesem Zeitpunkt gemeldete **gepushte** Head des
  Story-Branch. Der `takeover_base_sha` ist das einzige
  Uebergabeobjekt des Transfers (Pushed-only-Regel, FK-10 §10.2.4b):
  ein SHA, nie ein Dateizustand — keine Binaer-Diffs, keine
  Untracked-Manifeste. Das normierte Schema
  (`state-storage.entity.takeover-transfer-record`: je Repo
  `takeover_base_sha`, Push-Frische, `base_quality`,
  Challenge-/Confirm-Referenzen) liegt beim Speichervertrag
  (formal.state-storage) und wird hier nur referenziert.

**Immobilitaet des Uebergabeobjekts:** Der Challenge (§56.13a) zeigt
den Kandidaten-SHA und die Push-Frische VOR der Entscheidung an. Ein
**Pre-Confirm-Refresh** ist optional zulaessig — eine Anfrage an A's
Edge, den aktuellen Stand zu pushen: bounded, best-effort und NUR vor
der menschlichen Entscheidung. **Nach dem Confirm aendert kein A-Push
mehr das Uebergabeobjekt.** Weicht der Remote-Head des Story-Branch
danach vom `takeover_base_sha` ab (z. B. durch einen regelwidrig
durchgeschluepften Push), ist das der blockierende Zustand
`remote_branch_diverged_after_takeover` (FK-30 §30.6.3) — kein
stilles Mitnehmen; der SHA-Vergleich macht den Verstoss sichtbar und
zuordenbar.

**Verlustkorridor-Kommunikation (Pflichttext):** Challenge und
Freigabe-Overlay (FK-72 §72.14.7) muessen sinngemaess anzeigen:
„Uebernommen wird ausschliesslich der gepushte Stand `<sha>`. Nicht
gepushte Commits, uncommittete Aenderungen und untracked Dateien der
bisherigen Session werden nicht uebertragen; sie koennen lokal
quarantaeniert werden, sind aber fuer AgentKit kein Uebergabegut."
Die Freigabe-Entscheidung muss diese Konsequenz unmissverstaendlich
vor sich haben.

Wirkung auf A: Die Session geht in `binding_invalid` mit explizitem
Grund `ownership_transferred` (§56.7a) — kein stiller Rueckfall auf
`ai_augmented`. Jeder weitere mutierende Call von A wird
deterministisch abgewiesen (Fence auf
`owner_session_id`/`ownership_epoch` in allen Regime-Mutationspfaden,
ausdruecklich auch `complete_phase`/`fail_phase`/Closure), mit
Klartext-Grund und Verweis auf den neuen Owner. Lesende Zugriffe —
einschliesslich `GET operations/{op_id}` zur Rekonsiliierung eigener
frueherer Mutationen — bleiben A erlaubt. A's Edge quarantaeniert
beim naechsten Kontakt (Reconcile → `ownership_transferred`) lokale
nicht-gepushte Reste lokal, auditiert als lokales Ereignis; nichts
davon geht ans Backend. Push-Versuche des Ex-Owners scheitern
zweifach: am Edge-Push-Gate und am Code-Backend-Ref-Schutz
(FK-12 §12.1.3, FK-15 §15.5.4).

### 56.13d Ping-Pong-Schranke

Nach einem Transfer gilt: Die entmuendigte Session kann nicht
unmittelbar per Confirm zurueckuebernehmen; ein erneuter Transfer
derselben Story kurz darauf erfordert einen privilegierten Principal
(`human_cli`/`admin_service`) und Begruendung. Die Takeover-Historie
ist Teil des Challenge und wird in der UI prominent angezeigt. Damit
ist wiederholtes gegenseitiges Entreissen kein technisches Wettrennen
(das verhindert schon das CAS), sondern ein sichtbarer
Governance-Verstoss.

### 56.13e Run-Kontinuitaet und Worktree-Uebernahme

Der Transfer fuehrt denselben Run fort: **gleicher `run_id`, neue
`ownership_epoch`**. Op-Historie, Attempts und QA-Artefakte bleiben
einem Run zugeordnet; Branch und gepushter Story-Stand gehoeren
fachlich der Story, nicht der Session. Physisch uebergeben wird aber
**kein Dateizustand**: Das Uebergabeobjekt ist der beim Confirm
materialisierte `takeover_base_sha` (§56.13c); B provisioniert bzw.
richtet exakt auf diesen SHA aus. Die `worktree_roots` der neuen
Bindung sind die von B's Edge gemeldeten Pfade (FK-10 §10.2.4a); die
Invariante `story_execution_requires_lock_binding_and_worktree_match`
bindet B an genau diese gemeldeten Worktrees.

**Klassifikation ueber Worktree-Identitaet, nicht
Maschinen-Identitaet:** Nicht „Same-Machine vs. Cross-Machine"
entscheidet, sondern ob B exakt denselben physischen Worktree ueber
den Story-Kontext-Marker (`.agentkit-story.json`, FK-36 §36.6.3) und
die Pfadbindung verifiziert:

- **Same-Worktree-Takeover:** B uebernimmt den **Worktree-Pfad**,
  nicht den Inhalt. Der Reconcile (FK-30 §30.6.3) verschiebt den
  vorhandenen Stand **vollstaendig und atomar in eine lokale
  Quarantaene-Ablage** (Verzeichnis-Move/-Copy — **nie `git
  stash`**: normale Stashes verlieren ignored files, `stash -a`
  nimmt potenziell riesige oder secret-haltige Ignored-Baeume mit)
  und reprovisioniert den Pfad sauber aus `takeover_base_sha`. A's
  lokale Deltas sind fuer AgentKit inexistent, fuer Menschen ggf.
  wertvoll: Quarantaene statt stiller Loeschung, auditiert als
  lokales Ereignis. Der gepushte Story-Branch wird dabei nie
  resettet.
- **Reprovisionierung (anderer Pfad / andere Maschine):** B's Edge
  erstellt einen frischen Worktree aus `takeover_base_sha`
  (`provision_worktree`, FK-91 §91.1b). Existiert am Ziel ein
  alter/schmutziger Worktree derselben Story, ist das der Zustand
  `local_stale_or_dirty_takeover_target` (FK-30 §30.6.3): gleiche
  Quarantaene-Mechanik, nie stilles Ueberschreiben. Zwei Sessions
  auf derselben Maschine mit anderem Checkout oder zwei Maschinen
  desselben Entwicklers sind Reprovisionierungs-Faelle — die Person
  ist irrelevant, die Worktree-Identitaet zaehlt.

Das Verwerfen des gepushten Story-Stands bleibt eine getrennte,
explizite Wahl (Story-Reset, FK-53), kein Takeover-Bestandteil; die
menschliche Verwertung quarantaenierter Inhalte liegt ausserhalb des
Takeover-Vertrags (FK-31 §31.1.3c). Die Run-Fortfuehrung ist nur
zulaessig, weil die neue `ownership_epoch` als Fence in allen
Mutations- und Abschlusspfaden wirkt (§56.8a) — sonst koennte der
Ex-Owner ueber run-scoped Pfade weiterwirken. Accountability haengt
an `run_id + ownership_epoch`; die Verantwortungsgrenze ist der SHA:
Was B ab `takeover_base_sha` produziert, ist B's Epoche.

### 56.13f Freeze-Zustaende als Admission-Blocker

Temporaere Sperr-/Sonderzustaende — etwa `conflict_freeze` (FK-55),
ein administrativer Split-Freeze oder Reconcile-/Repair-Zustaende —
sind story-scoped **Admission-Blocker** mit eigener `freeze_epoch`,
`freeze_reason` und Audit-Spur. Der Ownership-Record bleibt dabei
`active`; der Freeze blockiert zusaetzlich. Mutierende Admissions
erfordern beides: aktiven Ownership-Record **und** keinen
blockierenden Freeze — ausgenommen die explizit erlaubten
Reconcile-/Repair-/Admin-Kommandos, die den Zustand aufloesen. Jeder
Eintritt in einen solchen Zustand invalidiert offene
Takeover-Challenges; `confirm-run-ownership-takeover` scheitert,
solange die Story nicht takeover-admissible ist.

### 56.13g Crash-Recovery als Transfer-Spezialfall

Die Crash-Recovery (FK-20, `agentkit recover-story`) ist ein
Spezialfall des Transfers mit `acquired_via=recovery` — allerdings
mit **neuem Run**: Anders als beim Takeover ist der alte Run-Zustand
dort nicht vertrauenswuerdig. Recovery-/Self-Rebind-Faelle, in denen
dieselbe Harness-Identitaet ihre eigene verwaiste Arbeit wieder
aufnimmt, benoetigen keine menschliche Mitzeichnung.

### 56.13h Administrative Entmuendigung: der Disown-Baustein

Jeder offizielle Pfad, der eine aktive fremde Bindung entzieht oder
invalidiert — Ownership-Transfer, Story-Exit (FK-58), Reset (FK-53),
Split (FK-54) — nutzt denselben **Disown-Baustein**:

- Audit-Eintrag mit Grund,
- Owner-Notification beim naechsten Kontakt,
- Edge-Tombstone,
- deterministische Reconcile-Antwort fuer den Ex-Owner.

Damit erhaelt der Ex-Owner auf jedem Pfad dieselbe klare,
maschinenlesbare Auskunft statt stiller Fehlversuche.
