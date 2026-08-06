---
concept_id: FK-15
title: Security, Secrets, Identity und Zugriffsmodell
module: security
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: security
  - scope: secrets
  - scope: identity
  - scope: access-model
defers_to:
  - target: FK-01
    scope: trust-boundaries
    reason: Trust-Boundary-Modell ist in FK-01 definiert
  - target: FK-02
    scope: lock-mechanismus
    reason: QA-Artefaktschutz nutzt den zentralen Lock-Mechanismus aus FK-02
supersedes: []
superseded_by:
tags: [security, secrets, identity, berechtigungen, governance-schutz]
prose_anchor_policy: strict
formal_refs:
  - formal.state-storage.entities
---

# 15 — Security, Secrets, Identity und Zugriffsmodell

<!-- PROSE-FORMAL: formal.state-storage.entities -->

## 15.1 Bedrohungsmodell

AgentKit operiert in einem speziellen Bedrohungskontext: Die
"Angreifer" sind keine externen Akteure, sondern die eigenen
LLM-gesteuerten Agents. Das Fachkonzept (FK Kap. 2) dokumentiert
die systematischen Fehlverhaltensmuster:

| Bedrohung | Beschreibung | Beispiel |
|-----------|-------------|---------|
| Abkürzungen | Agent überspringt Schritte | Behauptet E2E-Tests durchgeführt zu haben |
| PASS by Absence | Crash erzeugt "0 Fehler" | Pipeline wertet stilles Scheitern als Erfolg |
| Evidence-Fabrication | Agent erzeugt plausible Fake-Artefakte | Gefälschte Screenshots, Logs |
| Destruktive Aktionen | Agent löscht statt zu fixen | Tests löschen, Force-Push, QA überschreiben |
| Scope-Drift | Agent weicht vom Auftrag ab | Orchestrator implementiert selbst |
| Governance-Umgehung | Agent versucht Guards auszuhebeln | QA-Artefakte direkt schreiben |

**Grundannahme:** Agents sind nicht bösartig, aber unzuverlässig.
Sie optimieren auf ihr unmittelbares Ziel und nehmen dabei
Abkürzungen, die den Gesamtprozess beschädigen. Die Sicherheits-
architektur muss diese Muster strukturell verhindern, nicht durch
Vertrauen in Prompt-Disziplin.

## 15.2 Trust Boundaries (Wiederholung aus Kap. 01)

```
Zone 1: Plattform (Harness — Claude Code / Codex; FK-76 — + Hooks)  — Agent kann nicht umgehen
Zone 2: Pipeline (deterministischer Code)    — Entscheidet, nicht der Agent
Zone 3: Agent-Ausführung (LLM-gesteuert)     — Nicht vertrauenswürdig
Zone 4: Externe LLMs (Pools)                 — Antworten nicht vertrauenswürdig
```

**Sicherheitsregel:** Keine Entscheidung in Zone 3 oder 4 darf ohne
Validierung durch Zone 1 oder 2 wirksam werden.

## 15.3 Rollenidentitäten und Principals

### 15.3.1 Technische Principals

AgentKit hat keine User-Accounts oder Login-Mechanismen. Die
"Identitäten" sind technische Principals, die sich aus dem
Ausführungskontext ergeben:

| Principal | Identifikation | Vertrauensstufe |
|-----------|---------------|----------------|
| **Mensch** | Direkte CLI-Interaktion, kein Agent-Spawn | Höchste — kann alles, wird nicht blockiert |
| **Interactive Agent** | Hauptagent ohne aktive Run-Bindung | Zone 3 — frei im Projekt, aber nur unter Basisschutz |
| **Orchestrator** (Hauptagent) | Harness-Session (Claude Code / Codex; FK-76), kein Parent-Agent | Zone 3 — darf steuern, nicht implementieren |
| **Worker** (Sub-Agent) | Von Orchestrator gespawnt, `subagent_type: worker` | Zone 3 — darf implementieren, nicht QA manipulieren |
| **QA-Agent** (Sub-Agent) | Von Orchestrator gespawnt, `subagent_type: qa` | Zone 3 — darf lesen und testen, nicht Produktivcode editieren |
| **Adversarial** (Sub-Agent) | Von Orchestrator gespawnt, `subagent_type: adversarial` | Zone 3 — darf nur in Sandbox schreiben |
| **Pipeline-Skript** | Python-Prozess, aufgerufen via Bash-Tool | Zone 2 — deterministisch, vertrauenswürdig |
| **Hook-Prozess** | Python-Prozess, aufgerufen vom Harness (Claude Code / Codex; FK-76) | Zone 1 — Plattform-Enforcement |
| **LLM-Hub** (extern) | Antwort auf Hub-Aufruf über FK-75 | Zone 4 — Antworten werden validiert, nie blind vertraut |

### 15.3.2 Principal-Erkennung

Hooks und Guards müssen erkennen, welcher Principal gerade agiert,
um rollenspezifische Regeln anzuwenden:

| Erkennungsmerkmal | Wie | Zuverlässigkeit |
|-------------------|-----|----------------|
| Hauptagent vs. Sub-Agent | Der Harness (Claude Code / Codex; FK-76 §76.4) setzt Hook-Kontext (`is_subagent`-Aequivalent); der Harness-Adapter normalisiert auf `principal_kind` (`main` / `subagent`) | Plattform-garantiert |
| Sub-Agent-Typ | `subagent_type` im Agent-Spawn-Prompt | Prompt-basiert — kann der Orchestrator setzen, aber der Hook validiert gegen erwartete Typen |
| Pipeline-Skript | Kein Harness-Kontext, direkter Python-Aufruf | Eindeutig — Skript wird nicht über Hook-Schicht aufgerufen |
| Story-Execution aktiv | Aktiver Run-/Lock-Record im State-Backend existiert | Service-seitig — vom Pipeline-Tooling gesteuert, nicht vom Agent |

**Projekt-Scope:** Backend-Principals agieren nie global, sondern
immer projektgebunden. Jeder Runtime- oder Analytics-Zugriff ist an
einen `project_key` gebunden; Cross-Project-Zugriffe sind nur fuer
explizite Admin-/Betriebs-Tools zulaessig.

## 15.4 Berechtigungsmodell

### 15.4.1 Berechtigungsmatrix

| Aktion | Mensch | Orchestrator | Worker | QA-Agent | Adversarial | Pipeline-Skript |
|--------|--------|-------------|--------|----------|-------------|----------------|
| Code lesen | ✅ | ❌ (Guard) | ✅ | ✅ | ✅ | ✅ |
| Code schreiben | ✅ | ❌ (Guard) | ✅ | ❌ (Guard) | ❌ (nur Sandbox) | ✅ |
| Tests schreiben | ✅ | ❌ | ✅ | ❌ | ✅ (nur Sandbox) | ✅ |
| Tests ausführen | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| QA-Artefakte schreiben | ✅ | ❌ | ❌ (Lock-Record + Hook) | ❌ (Lock-Record + Hook) | ❌ (Lock-Record + Hook) | ✅ |
| QA-Artefakte lesen | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Commit auf Main | ✅ | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ✅ |
| Commit auf Story-Branch | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Force-Push | ✅ | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ❌ |
| AK3-Story-Status ändern (Backend) | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Lock-Record erstellen/beenden | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| LLM-Hub aufrufen | ✅ | ✅ | ✅ | ❌ | ✅ (Sparring) | ✅ (Evaluator) |
| Agents spawnen | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Zentralen Workflow-State mutieren | ✅ (über Admin/CLI) | ❌ | ❌ | ❌ | ❌ | ✅ |

**AI-Augmented-Ergaenzung:** Außerhalb einer aktiven Run-Bindung wird
der Hauptagent als `Interactive Agent` behandelt. Für ihn gelten:

| Aktion | Interactive Agent |
|--------|-------------------|
| Code lesen | ✅ |
| Code schreiben | ✅ |
| Tests ausführen | ✅ |
| Agents spawnen | ✅ |
| Story-Workflow-State mutieren | ❌ außer über offizielle Project-Edge-Pfade; die CLI bleibt dem Menschen vorbehalten |
| Immer-aktive Basisschutzregeln umgehen | ❌ |

*Guard = nur aktiv im Story-Execution-Modus (aktiver Lock-Record
vorhanden,
Kap. 12.4.1). Im AI-Augmented-Modus sind Branch-Guards inaktiv.

### 15.4.2 Durchsetzungsmechanismen

| Einschränkung | Mechanismus | Umgehbar durch Agent? |
|--------------|------------|---------------------|
| Orchestrator darf nicht auf Codebase zugreifen | `orchestrator_guard.py` (PreToolUse-Hook) | Nein — Hook ist Plattform-Infrastruktur |
| Worker darf keine QA-Artefakte schreiben | zentraler Lock-Record + Hook (Kap. 02.7) | Nein — Lock-Record vom Pipeline-Tooling, nicht vom Agent |
| Worker/Orchestrator dürfen keine DB-Credentials besitzen | State-Backend-Zugriff nur über Hook- oder Project-Edge-Principals; CLI-Principals sind menschlich | Nein — Credentials bleiben außerhalb der Agent-Prompts und Workspaces |
| Backend-Zugriff nur im Projekt-Scope | Principals sind auf genau einen `project_key` oder einen expliziten Admin-Scope begrenzt | Nein — Row-/Schema-Scope liegt außerhalb der Agent-Kontrolle |
| Adversarial darf nur in Sandbox schreiben | dedizierter Adversarial-Guard | Nein — Hook ist Plattform-Infrastruktur |
| Branch-Guard (Story-Execution) | `branch_guard.py` (PreToolUse-Hook) + aktiver Lock-/Run-Record | Nein — Hook + State-Backend |
| QA-Agent darf keinen Code editieren | PreToolUse-Guard auf Write/Edit für Principal `qa` — erlaubt nur Lesen und Test-Ausführung | Nein — Hook-basiert, analog zum Orchestrator-Guard |
| Force-Push verboten | `branch_guard.py` | Nein — auch im AI-Augmented-Modus aktiv (Sonderregel, s.u.) |

### 15.4.3 Immer-aktive Regeln

Bestimmte Regeln gelten **unabhängig vom Betriebsmodus** — auch im
AI-Augmented-Modus, weil sie destruktiv und schwer rückgängig zu
machen sind:

| Regel | Begründung |
|-------|-----------|
| Kein Force-Push auf irgendeinen Branch | Überschreibt Remote-Historie, nicht rückgängig |
| Kein `git reset --hard` | Verwirft uncommitted Arbeit |
| Kein `git branch -D` (force delete) | Löscht Branch ohne Merge-Check |
| Keine Secrets im Commit | `.env`, `.pem`, `.key` etc. im Diff → Structural Check blockiert |

Diese Regeln werden über den Branch-Guard durchgesetzt, der für
diese spezifischen Operationen **keinen Story-Lock-Record benötigt** —
sie sind immer aktiv, als Basisschutz.

## 15.5 Secrets-Verwaltung

### 15.5.1 Grundregel: Keine Secrets im Repository

AgentKit speichert keine Secrets im Repository, im Code, in allgemeiner
editierbarer Konfiguration oder in fachlichen Artefakten. Laufzeitlich benoetigte
Credentials liegen ausschliesslich in den unten benannten dedizierten
Credential-Speichern ausserhalb des Repositories: das Strategenpasswort nur als
Argon2id-Hash in der Core-Auth-Datei, ein ProjectEdge-Bearer-Token im Klartext in
`.agentkit/credentials` auf der Edge-Maschine. Diese eng begrenzten
Credential-Dateien sind weder allgemeine Konfiguration noch ein fachliches
Artefakt; ihre wirksamen Dateirechte und Lebenszyklen sind in §15.10.3 und
§15.10.4 verbindlich festgelegt.

| Secret-Typ | Wo gespeichert | Zugriff durch AgentKit |
|-----------|---------------|----------------------|
| GitHub-Token (persoenlich) | `gh` CLI (OS Keychain) | Implizit über `gh` CLI-Aufrufe |
| AK3-/Edge-Dienst-Identitaet (Code-Backend, `story/*`-Refs; provider-neutral, Mechanik im Provider-Adapter, FK-12 §12.1) | Backend-verwaltet, nie im Repo | Nur ueber den offiziellen Edge-Push-Pfad (§15.5.4) |
| LLM-Hub-Auth | Hub-intern (z.B. Browser-Cookies) | Kein Zugriff — der Hub verwaltet Auth selbst |
| Weaviate | Kein Auth (localhost-only) | Direkt über HTTP/gRPC |
| ARE | MCP-Server-Config | Kein direkter DB-Zugriff |

### 15.5.2 Secret-Detection (zweistufig)

Secrets werden an **zwei Stellen** abgefangen:

**Stufe 1: Pre-Commit-Hook (verhindert das Entstehen)**

> **Hinweis:** Der Pre-Commit-Hook verwendet pfadbasiertes
> Dispatching für funktionale Checks (Versionsbump,
> Concept-Validation; Kap. 13.9).
> Die Secret-Detection bleibt davon **unberührt** — sie ist
> global aktiv und läuft bei jedem Commit, unabhängig von den
> geänderten Pfaden. Details: Kap. 30.5.3.

Ein Git-Pre-Commit-Hook (`tools/hooks/pre-commit`) prüft den
Staging-Bereich auf Secrets, **bevor** der Commit erzeugt wird.
Wenn Secrets erkannt werden, wird der Commit abgelehnt. Damit
landen Secrets nie in der Git-Historie — der Agent müsste sonst
die Historie umschreiben, was durch den Branch-Guard (kein
Hard-Reset) verboten ist.

**Stufe 2: Structural Check (Absicherung im QA-Subflow)**

Der Structural Check `security.secrets` (Schicht 1 des QA-Subflows
innerhalb der Implementation-Phase) prueft den vollstaendigen
Git-Diff nochmals als Absicherung — falls
der Pre-Commit-Hook umgangen wurde (z.B. `--no-verify`, was aber
durch den Self-Protection-Guard blockierbar ist).

**Geprüfte Patterns (beide Stufen identisch):**

| Pattern | Blockiert |
|---------|----------|
| `.env`, `.env.*` | Ja (BLOCKING) |
| `*.pem`, `*.key`, `*.p12` | Ja (BLOCKING) |
| `credentials.json`, `serviceaccount.json` | Ja (BLOCKING) |
| `*_SECRET*`, `*_TOKEN*`, `*_PASSWORD*` | Ja (BLOCKING) |
| `*.keystore`, `*.jks` | Ja (BLOCKING) |

Zusätzlich scannt der Check Diff-Inhalte auf Credential-Präfixe. Geführt
werden die Familien, die die Aussteller tatsächlich vergeben:

| Aussteller | Präfixe |
|---|---|
| AWS Access Key ID | `AKIA` (dauerhaft), `ASIA` (temporär, STS) |
| GitHub Token | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_` |
| OpenAI API Key | `sk-` (einschliesslich `sk-proj-`) |

**Ein Präfix allein ist kein Treffer.** Gescannt wird die *Form* des
ausgestellten Credentials, nicht die blosse Zeichenfolge. Ein Treffer
verlangt beides:

1. **Token-Anfang.** Unmittelbar vor dem Präfix darf kein Token-Zeichen
   (`[A-Za-z0-9_-]`) stehen. Fachprosa, die das Präfix im Wortinneren
   trägt — `risk-adjusted`, `task-`, `desk-` —, ist damit kein Treffer.
   Die Ankerung sitzt vor dem *Präfix*, nicht vor dem Wort.
2. **Mindestkörper.** Nach dem Präfix muss eine Mindestzahl von
   Token-Zeichen folgen.

Beide Bedingungen sind Pflicht. Ohne (1) blockiert der Scan deutsche und
englische Prosa dauerhaft und erzieht damit zu `--no-verify`; ohne (2)
genügt ein Präfix am Zeilenanfang. Ein Scanner, der Fliesstext ablehnt,
schützt nichts — er wird umgangen.

**Der Mindestkörper ist eine Falsch-Positiv-Untergrenze, kein
Aussteller-Vertrag.** Er liegt bewusst unterhalb der kürzesten
dokumentierten Ausstellung, damit ein verkürztes oder geändertes
Upstream-Format weiterhin trifft. Auf der realen Länge gesetzt wäre er
ein Fail-open, das niemand bemerkt. Die durchgesetzten Zahlen stehen in
`src/agentkit/backend/governance/guard_system/secret_patterns.py` —
abgeleitet aus dieser Regel, nicht als eigene Norm daneben.

**Grenze des Werkzeugs, ausdrücklich benannt:** Der Scan adressiert das
*versehentliche* Einchecken. Ein zerlegtes Literal, Base64 oder
URL-Encoding umgehen jeden Zeilenscanner; wer absichtlich exfiltriert,
wird hier nicht gefasst.

**Eingebüßte Abdeckung, ebenso ausdrücklich:** Eine Zerlegung *hinter*
einem vollständigen Präfix (`"sk-" "proj-…"`) wurde von einer reinen
Substring-Suche noch getroffen und wird von der Formprüfung nicht mehr
getroffen. Das ist bewusst hingenommen — und **nicht alternativlos**: ein
sprachnaher Matcher, der benachbarte String-Literale zusammenzieht,
fänge den Fall. Der Scan arbeitet absichtlich sprachneutral auf der
Rohzeile und kennt keine Grammatik; deshalb endet die Abdeckung hier.

Siehe `concept/_meta/decisions/2026-08-03-secret-scan-prueft-form-nicht-zeichenfolge.md`.

### 15.5.3 Governance-Beobachtung: Secret-Zugriff

Die Governance-Beobachtung (Kap. 68.8, FK 6.6) erkennt
Zugriffe auf Secrets als Hook-Signal:

| Signal | Reaktion |
|--------|---------|
| Agent liest `.env` oder Credential-Dateien | Sofortiger Stopp (kein Score, kein LLM) |
| Agent schreibt Dateien mit Secret-Patterns im Namen | Sofortiger Stopp |

Das ist einer der wenigen Fälle, in denen der Hook nicht
über einen Risikoscore eskaliert, sondern sofort und hart
blockiert.

### 15.5.4 Code-Backend-Dienst-Identitaet und Ref-Schutz (story/*)

Fuer Story-Branches gilt ein zweistufiges Schutzmodell (Mechanik der
Ref-Regeln: FK-12 §12.1.3; Capability-Einordnung: FK-55 §55.9):

1. **Ref-Schutz im Code-Backend:** `story/*`-Refs sind
   regelgeschuetzt. Direkte Entwickler-Pushes — auch
   Fast-Forward-Pushes — sind verboten; geschrieben wird nur ueber
   die **AK3-/Edge-Dienst-Identitaet** (provider-neutrale Service-Identitaet; konkrete Mechanik ausschliesslich im Provider-Adapter, FK-12 §12.1/§12.1.3), und AK3 gibt die
   Schreibfaehigkeit nur fuer den aktuellen
   `(owner_session, ownership_epoch)` frei (FK-56 §56.8a). Die
   Dienst-Identitaet ist ein von AK3 verwaltetes Credential; sie liegt
   nie im Repository und ist nicht das persoenliche
   Entwickler-Token aus §15.5.1.
2. **Edge-Push-Gate (online-pflichtig):** Der offizielle Push-Pfad
   des Edge verifiziert die Ownership **online** unmittelbar vor dem
   Push (bounded); ohne Server-Bestaetigung kein Push — offline
   heisst: lokale Arbeit ja, Push nein. Der Re-Sync-Fallback auf ein
   lokal vorhandenes Edge-Bundle (FK-56 §56.9a) gilt fuer den
   Push-Pfad ausdruecklich **nicht** (fail-closed): Ein stales
   ACTIVE-Bundle darf keinen Push mehr erlauben.

Edge-Selbstdisziplin allein (Hook-Guard auf der eigenen Maschine)
ist als Schutz gegen Ex-Owner-Pushes unzureichend — der Hook-Guard
wirkt nur lokal, ein stales Bundle koennte `git push` weiter
erlauben, und Fast-Forward-Pushes umgehen Force-Push-Verbote. Erst
die serverseitige Stufe 1 macht die Schranke belastbar.

**`main`-Update (`merge_local`, Closure).** Die hier fuer `story/*` beschriebene
Dienst-Identitaet wird **nicht** zu einem eigenen `main`-Credential ausgeweitet.
Der finale `main`-Update laeuft als CLI-Pfad ueber die vorauthentifizierte
Host-`git`-CLI (FK-12 §12.1); der Project Edge haelt dafuer kein Credential. Die
Autorisierung ist das `merge_local`-Commission-Gating (Ownership-Epoch FK-56
§56.8a, alle Closure-Verdicts PASSED, serverseitige Push-Verifikation FK-29
§29.1a) — `main` wird nie direkt, sondern nur ueber diesen gegateten Backend-Auftrag
fortgeschrieben. Herleitung: Concept-Decision-Record
`META-DEC-2026-07-13-MERGE-LOCAL-MAIN-CREDENTIAL`.

## 15.6 Opake Fehlermeldungen

### 15.6.1 Prinzip

Guards geben dem Agent **keine Details** darüber, warum eine Aktion
blockiert wurde (FK-06-017, FK-06-093). Das verhindert, dass der
Agent lernt, den Guard gezielt zu umgehen.

### 15.6.2 Fehlermeldungen

| Guard | Meldung an Agent | Details für Mensch |
|-------|-----------------|-------------------|
| Branch-Guard | `"Operation not permitted."` | — (einfache Regel, Mensch versteht den Kontext) |
| Orchestrator-Guard | `"Operation not permitted."` | — |
| QA-Artefakt-Schutz | `"Operation not permitted."` | — |
| Integrity-Gate | `"GOVERNANCE VIOLATION DETECTED. Immediately stop all work."` | Fehler-Codes im Violation-Record des State-Backends |

### 15.6.3 Audit-Log

Das Integrity-Gate schreibt bei Blockade einen strukturierten
Violation-Record in das State-Backend:

```json
{
  "ts": "2026-03-17T11:30:00+01:00",
  "failure_codes": ["NO_SEMANTIC_REVIEW", "NO_GEMINI_EVIDENCE"],
  "command_prefix": "story_service.close_story story_id=ODIN-042 ..."
}
```

Der Mensch kann dieses Log lesen. Der Agent sieht nur die opake
Meldung.

## 15.7 Härtung der Governance-Komponenten

### 15.7.1 Selbstschutz

Die Governance-Beobachtung (FK-06-102) erkennt Versuche, die
Governance selbst zu manipulieren:

| Manipulationsversuch | Erkennung | Reaktion |
|---------------------|-----------|---------|
| Agent ändert harness-spezifische Hook-Settings (z. B. `.claude/settings.json` fuer Claude Code; harness-eigenes Aequivalent fuer Codex; FK-76 §76.5) | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent ändert `.agentkit/config/project.yaml` | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent versucht Edge-Bundle- oder Lock-Mechanismus lokal zu umgehen | Hook-Signal: Governance-Datei verändert oder fehlender offizieller Project-Edge-Write-Pfad | Sofortiger Stopp |
| Agent ändert harness-spezifische Skill-Symlinks (z. B. `.claude/skills/` fuer Claude Code; FK-76) | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent versucht State-Backend-Zugangsdaten zu lesen/ändern | Guard + Secret-Schutz | Sofortiger Stopp |

**Geschützte Pfade** (immer, unabhängig vom Betriebsmodus; harness-spezifische Pfade sind Beispiele und werden vom jeweiligen Adapter eingebracht — siehe FK-76):

```
.agentkit/config/project.yaml
.claude/settings.json                  # Beispiel: Claude-Code-Adapter
.claude/skills/                        # Beispiel: Symlink fuer Claude Code
.codex/config.toml                     # Beispiel: Codex-Adapter
_temp/governance/
.agent-guard/
```

### 15.7.2 Hook-Integrität

Hooks können vom Agent nicht deaktiviert werden, weil:

1. Hook-Registrierung liegt in der harness-spezifischen Settings-Datei (z. B. `.claude/settings.json` fuer Claude Code; harness-eigenes Aequivalent fuer Codex; FK-76 §76.5) und ist geschützt
2. Hook-Skripte liegen im `agentkit`-Paket (nicht im Zielprojekt)
3. Der Harness ruft Hooks als externen Prozess auf — der Agent
   hat keinen Einfluss auf den Aufrufmechanismus
4. Ein Agent, der die harness-spezifische Settings-Datei editieren will, wird
   vom Governance-Selbstschutz-Hook blockiert

### 15.7.3 Lock-Integrität

Zentrale Lock-Records können vom Agent nicht manipuliert werden, weil:

1. Lock-Records liegen im State-Backend (geschützter Zustandsraum)
2. Nur Pipeline-Skripte (Zone 2) schreiben Lock-Records
3. Der Guard-Pfad blockiert unzulässige Sub-Agent-Aktionen
4. Locks enden nie automatisch (kein PID-/TTL-Mechanismus), sondern
   nur über offizielle Pfade — Closure, Exit, Reset, Split,
   Ownership-Transfer (Kap. 02.7); explizites, auditiertes Handeln
   ist der gewollte Pfad, einen freien Löschpfad für Agents gibt
   es nicht

## 15.8 Netzwerk-Sicherheit

### 15.8.1 Dienstspezifische Bind-Grenzen

Lokal betriebene Hilfsdienste werden nicht unbeabsichtigt nach außen
exponiert. Der AgentKit-Core ist davon zu unterscheiden: seine Control-Plane
bindet gemaess FK-10 entweder auf Loopback oder als bewusst eingerichteter,
per HTTPS und API-Authentifizierung geschuetzter dedizierter Server. Die Wahl
der Core-Topologie darf die lokale Erstzugangs-CLI aus §15.10.3 nicht
einschraenken; diese CLI oeffnet selbst keinen Netzwerk-Endpunkt.

| Dienst | Binding | Expose |
|--------|---------|--------|
| LLM-Hub (REST) | `127.0.0.1:9600` (loopback) bzw. zentraler Host | Lokal oder Team-Server |
| Weaviate (HTTP/gRPC) | `localhost:9903/50051` | Nur lokal |
| MCP-Server (stdio) | Kein Netzwerk | Prozess-lokal |
| AgentKit Control Plane | Loopback oder dedizierter Server gemaess FK-10 | HTTPS und API-Auth; kein anonymer Bootstrap-Endpunkt |

### 15.8.2 Ausgehende Verbindungen

| Ziel | Protokoll | Zweck |
|------|----------|-------|
| `github.com` | HTTPS | `gh` CLI, `git push/pull` |
| LLM-Anbieter-Sites | HTTPS | nur vom **LLM-Hub** (Backend-Automation), nicht von AK3 |
| Docker Hub | HTTPS | Weaviate-Image-Pull (einmalig) |

Keine outbound-Verbindungen von AgentKit-Code selbst. Die
LLM-Anbieter-Verbindungen macht der **LLM-Hub**, nicht AK3; AK3 spricht
nur den Hub-Endpunkt sowie `gh`/`git` an. Die konkreten Modelle sind
austauschbar — AgentKit kennt nur den Hub und die Modellnamen.

## 15.9 Datenschutz und Datenflüsse

### 15.9.1 Was an externe LLMs gesendet wird

Über den LLM-Hub werden an externe Modelle gesendet:

| Daten | Wann | Enthält |
|-------|------|---------|
| QA-Bewertung (Schicht 2) | QA-Subflow innerhalb Implementation | Code-Diff, Story-Beschreibung, Konzept-Auszuege |
| Semantic Review | QA-Subflow innerhalb Implementation | Aggregierte Befunde + Diff |
| Dokumententreue-Pruefung | Exploration/Implementation (QA-Subflow)/Closure | Entwurf + Referenzdokumente |
| Adversarial-Sparring | QA-Subflow innerhalb Implementation | Implementierungsbeschreibung |
| Konzept-Feedback | Konzept-Stories | Konzeptdokument |
| Governance-Adjudication | Bei Anomalie | Verdichtete Event-Episode |
| VektorDB-Konfliktbewertung | Story-Erstellung | Story-Beschreibung + Top-5-Treffer |
| Worker-Reviews (Sparring) | Implementation | Code-Auszüge, Architekturkontext |

**Keine Secrets in LLM-Prompts:** Die Kontext-Bundles (Kap. 11)
enthalten keine `.env`-Inhalte, keine API-Keys, keine Credentials.
Der Secret-Detection-Check (15.5.2) wirkt präventiv auf Code-Ebene.

### 15.9.2 Was lokal bleibt

| Daten | Speicherort | Nicht an LLMs |
|-------|------------|--------------|
| Telemetrie (State-Backend + Export) | State-Backend, Audit-Exports | Nie |
| QA-Artefakte | State-Backend | Nie (nur deren Inhalt wird als Kontext gesendet) |
| Locks | State-Backend | Nie |
| Failure Corpus | State-Backend / Artefaktspeicher | Nie (nur aggregierte Patterns ggf. in Check-Proposals) |
| Git-Historie | `.git/` | Nie direkt (nur Diffs) |
| Skill-Bindungen | harness-spezifische Skill-Symlinks (z. B. `.claude/skills/` fuer Claude Code; FK-76) | Nie |

## 15.10 API-Authentifizierung (UI-BFF und Project-API)

### 15.10.1 Geltungsbereich

Die Control-Plane-HTTP-Schicht und ihre erreichbaren Endpunkte
(UI-BFF auf 9701, Project-API auf 9702, vgl. FK-10 §10.7) machen
API-Authentifizierung erforderlich. AK3 wird primaer
**lokal** auf einem Strategen-Laptop betrieben, der gelegentlich in
fremden Netzwerken haengt — minimaler Schutz gegen netzwerkseitigen
Drittzugriff ist Pflicht.

Berechtigungsmodell ist explizit **single-user, single-tenant**: ein
einzelner Stratege bedient die UI, ein oder mehrere Thin-Clients in
Zielprojekten bedienen die Project-API. Es gibt **keine** Rollen,
**keine** Multi-User-Kapazitaet und **keine** feinkoernigen Rechte.
Sobald ein authentifizierter Aufrufer durch ist, sieht und kann er im
Rahmen seines Endpunkt-Surfaces alles, was die Endpunkte fachlich
zulassen.

Das interne Principal-Modell (15.3, 15.4) bleibt davon unberuehrt —
es regelt agentenseitige Berechtigungen *innerhalb* von AK3. Die
API-Auth ist die *aeussere* Schicht zwischen Aufrufer und Control-Plane.

### 15.10.2 Identitaetsklassen

Drei klar abgegrenzte Aufrufer-Klassen:

| Klasse | Aufrufer | Auth-Mechanismus | Zugriffsumfang |
|---|---|---|---|
| **Stratege** | Mensch im Browser/CLI | Cookie-basierte Session nach Login mit lokalem Passwort | administrative Auth-Oberflaechen der Control-Plane-Profile sowie UI-BFF (9701), alle UI-Sichten |
| **Thin-Client** | Maschinen-Prozess im Zielprojekt | Bearer-Token im `Authorization`-Header | Project-API (9702), alle projektbezogenen Mutations- und Lesepfade |
| **Worker-Agent** | AK3-internes Subprocess | kein API-Auth (selbe Prozesssphaere, Trusted-Path) | nur ueber AK3-Domain-Schichten, nicht ueber HTTP |

Ein Worker-Agent geht nicht ueber HTTP an die Control-Plane — er
laeuft in derselben Prozesssphaere wie AK3 und nutzt die fachlichen
Komponenten direkt. Er braucht damit keinen API-Auth.

UI-BFF und Project-API sind gemaess FK-10 zwei HTTPS-Listener **derselben
Control-Plane-Laufzeit und desselben Writer-Prozesses**. Die fruehere
Prozessgrenze ist keine Sicherheitsannahme mehr. Ihre Schutzwirkung wird
innerhalb des Prozesses explizit hergestellt: jeder Listener hat einen eigenen
Auth-Middleware-Kontext, beide Kontexte teilen ausschliesslich die autoritativen
Credential-/Session-Owner, die Bind-Adressen sind getrennt konfigurierbar und
werden exklusiv durch den Writer-Prozess gebunden; ein fremder Prozess darf
keine Listener-Adresse mitbenutzen. Eine fail-closed Surface-Policy begrenzt die
Routen. Angenommene Requests bleiben bis zu ihrem vollstaendigen Ruecklauf an
die Writer-Lease gebunden; nichttransaktionale Auth-Wirkungen pruefen den Fence
commit-nah erneut, und erkannter Lease-Verlust beendet beide Listener ohne
Erfolgsantwort. Der UI-BFF akzeptiert keine
Project-Tokens und exponiert keine Project-Edge-, Installer-, Telemetrie- oder
maschinenbezogenen Governance-Routen. Die Project-API exponiert keine
Dashboard-/Planning- und Takeover-Approval-UI-Routen. Die Portnamen beschreiben
weiterhin den primaeren Konsumenten. Login und
die nur Strategen erlaubten administrativen Auth-Routen sind auf beiden
Profilen erreichbar: der Browser nutzt typischerweise 9701, die Operator-CLI
fuer Auth-Administration und den vorgelagerten Projektkontext-Bootstrap die
konfigurierte Project-API-Basis (typischerweise 9702). `register-project`
selbst verwendet ausschliesslich die zuvor gespeicherte Project-Credential.
Autorisierung erfolgt am Principal: eine gueltige Strategen-Session darf
diese Administrationsrouten sowie die expliziten Human-Governance-Routen fuer
Takeover/Recovery, Admin-Abort, Story-Split, Story-Reset, Story-Exit und
Permission-Entscheide verwenden. Bei diesen Story-Administrationsrouten ist
die serverseitig authentisierte Strategen-Session die handelnde Identitaet;
ein Payload darf weder Principal noch Session attestieren. Ziel-Identitaeten,
etwa die aktive Run-Session beim Story-Exit, werden aus dem autoritativen
Writer-State aufgeloest. Auf jeder anderen Project-API-Route wird die
Strategen-Session `403 Forbidden` abgewiesen. Ein Project-Token
wird auf Strategen-Administrationsrouten ebenfalls stets mit `403 Forbidden`
abgewiesen. Die enge Strategen-Ausnahme der Third-Party-Validation vor der
ersten Project-Credential und jede Tokenanlage/-widerrufung teilen ueber beide
Listener dieselbe prozesslokale Credential-Transition-Grenze; zwischen der
Pruefung "noch kein Token" und dem Domainhandler kann kein paralleler Request
das erste Token publizieren. Projektfachliche Project-API-Routen bleiben
projekt- und tokengebunden.

### 15.10.3 Strategen-Login (UI-BFF)

- **Erzeuger und Klartextgrenze**: der Backend-Admin waehlt das Passwort
  fuer den einzigen Strategen-Account `admin` in einem direkt bedienten
  interaktiven Terminal. Das Passwort wird nicht von AK3 erzeugt oder
  nachtraeglich angezeigt. Sein Klartext lebt nur im Speicher des
  Admin-CLI-Prozesses und des unmittelbar pruefenden Servers; er wird weder
  persistiert noch auf stdout/stderr oder in ein Zugriffsprotokoll geschrieben.
- **Einmaliger Erstzugang**: `<absolute-agentkit-wrapper> auth bootstrap` ist die einzige
  nicht-authentifizierte Mutation fuer das Strategenpasswort. Sie laeuft direkt
  im interaktiven Terminal auf der Core-Maschine und ruft den lokalen
  Credential-Owner auf; eine anonyme HTTP-Bootstrap-Route existiert nicht.
  Deshalb leitet der Erstzugang keine Einschraenkung fuer die produktiven
  Core-Listener ab: deren Loopback- oder dedizierte Server-Topologie bleibt
  unter FK-10 §10.2.5 autoritativ. Insbesondere setzt ein Remote-Core keinen
  nicht normierten lokalen Proxy voraus.
- **Atomare Einmaligkeit und Admin-Kenntnis**: die CLI verlangt ein echtes
  Terminal und zweimal dieselbe vom Backend-Admin eingegebene Zeichenfolge, bevor
  sie den lokalen Credential-Owner aufruft. Ein betriebssystemspezifischer Prozess-Lock und die
  atomare Publikation der vollstaendigen Auth-Datei bilden eine gemeinsame
  Einmaligkeitsgrenze. Bei konkurrierenden Aufrufen gewinnt genau einer; jeder
  weitere Aufruf endet mit `bootstrap_already_completed`. Weil der Backend-Admin das
  Passwort vor der Publikation selbst kennt, kann kein Zustand „Hash vorhanden,
  Passwort unbekannt“ entstehen.
- **Speicherung**: serverseitig liegt ausschliesslich der Argon2id-Hash in der
  dafuer vorgesehenen Auth-Datei ausserhalb des Repositories, standardmaessig
  `~/.config/agentkit/auth.json`, ueberschreibbar durch
  `AGENTKIT_AUTH_CONFIG`. Nicht im Code, nicht in `concept/`, nicht in `var/`.
  Auf POSIX wird der wirksame Modus `0600` gesetzt und nachgemessen; auf Windows
  wird eine vererbungsfreie DACL mit genau einem expliziten `FullControl`-Allow
  fuer die SID des ausfuehrenden Benutzers gesetzt und nachgemessen. Kann AK3
  diese Wirkung nicht herstellen oder spaeter nicht bestaetigen, bleibt der
  Zugang fail-closed. Das persistierte Dokument ist schema-geschlossen:
  `username` ist verpflichtend und exakt `admin`, `hash_algorithm` exakt
  `argon2id`, der PHC-Hash muss selbst den Argon2id-Typ tragen, unbekannte
  Felder sind verboten. Abweichende, fehlende oder widerspruechliche Felder
  machen das gesamte Credential ungueltig und fuehren nur zum opaken
  Auth-Fehler.
- **Login-Endpoint** auf der gemeinsamen Control-Plane-Auth-Oberflaeche: nimmt
  Username (Pflicht-Feld, exakt `admin`) und Passwort entgegen,
  prueft gegen den Hash, setzt bei Erfolg ein Session-Cookie.
- **Session-Cookie** ist HttpOnly, Secure (sobald TLS aktiv), SameSite
  strict. Inhalt: opake Session-ID, server-seitig in einer owner-only
  geschuetzten, atomar geschriebenen Session-Datei gehalten, die beide
  Listener-Kontexte im selben Writer-Prozess unter demselben
  betriebssystemspezifischen Prozess-Lock teilen. Jeder Session-Record ist an
  die beim Login aktive Passwortgeneration
  gebunden. Lebensdauer z. B. 24 Stunden, automatische Verlaengerung bei
  Aktivitaet; abgelaufene Records werden beim naechsten Session-Zugriff unter
  dem Prozess-Lock aus der Datei entfernt.
- **Logout** invalidiert die Session-ID server-seitig.
- **Lebensdauer und Widerruf**: das Passwort gilt ohne automatische Frist bis
  zur authentifizierten Rotation ueber `POST /v1/auth/password`. Die Rotation
  traegt eine clientseitige `op_id`, laeuft unter dem einheitlichen
  Idempotenzvertrag aus FK-91 §91.1a und ersetzt den Hash atomar, bevor sie alle
  vorhandenen Strategen-Sessions in der gemeinsamen Listener-Laufzeit widerruft; das
  alte Passwort kann danach keine neue Session erzeugen. Passwortpruefung und
  Session-Erzeugung sowie Hash-Ersetzung und Gesamtwiderruf bilden jeweils eine
  gemeinsame Transition unter demselben Prozess-Lock. Session-Erzeugung,
  gleitende Validierung, einzelner Widerruf und Gesamtwiderruf sind ebenfalls
  innerhalb des einen Writer-Prozesses serialisiert; eine parallel validierte Session kann nach
  dem Gesamtwiderruf nicht wieder in den Store publiziert werden. Die atomare
  Hash-Ersetzung wechselt zugleich die Passwortgeneration, sodass jede alte
  Session bereits bei der Validierung fail-closed abgelehnt wird, auch wenn die
  nachlaufende physische Bereinigung der Session-Datei scheitert. Nach einem
  solchen Post-Commit-Fehler bleibt der Idempotenz-Claim fuer denselben
  Klaerungsfall erhalten; er wird nie als erneut ausfuehrbar freigegeben.
  Geht die
  Antwort verloren,
  meldet sich der Backend-Admin mit
  dem bereits bekannten neuen Passwort an und wiederholt exakt dieselbe
  `op_id`/Body-Kombination; der Replay liefert das gespeicherte Ergebnis ohne
  zweite Rotation. Eine abweichende Body-Kombination zur gleichen `op_id` wird
  fail-closed abgewiesen. Die Operator-CLI zeigt die `op_id` vor dem
  Netzwerkaufruf an und nimmt sie fuer einen normalen Replay explizit wieder
  entgegen. Stirbt der Server nach atomarer Hash-Publikation, aber vor
  Finalisierung des Idempotenz-Records, ist der aktuelle Credential-Zustand
  jedoch kein eindeutiger Beleg dafuer, dass genau dieser Claim ihn erzeugte:
  `last_rotation_op_id` ist zugleich die aktuelle Passwortgeneration und kann
  durch eine spaetere Rotation ersetzt werden. Die Start-Rekonsiliierung
  rekonstruiert deshalb keinen Erfolg, sondern finalisiert den eigenen
  frueheren Auth-Claim ohne Admin-Eingriff als `failed`. Das beendet den
  Claim-Lebenszyklus, macht eine bereits atomar publizierte Passwortgeneration
  aber nicht rueckgaengig. Derselbe Retry erhaelt
  `409 operation_conflict`; eine zeitbasierte Uebernahme,
  Erfolgsrekonstruktion aus einem lediglich passenden Hash oder erneute
  Rotation unter dem alten Claim gibt es nicht.
- **CSRF-Schutz**: SameSite-strict deckt den Hauptfall ab. Zusaetzlich
  wird ein CSRF-Token pro Session ausgegeben und bei jeder
  mutierenden Anfrage erwartet.
- **Abbruch und Wiederaufnahme**: ein Abbruch vor der atomaren Publikation
  hinterlaesst keine Auth-Datei und `auth bootstrap` wird wiederholt. Da die
  einzige produktive Bootstrap-Oberflaeche das Passwort vor der Publikation
  interaktiv entgegennimmt und bestaetigen laesst, gibt es auf dieser
  Oberflaeche keinen Pfad, der ein maschinell erzeugtes, dem Backend-Admin unbekanntes
  Passwort publiziert. Nach der
  Publikation kennt der Backend-Admin sein selbst gewaehltes Passwort und setzt mit
  `auth login` beziehungsweise `auth issue-token` fort. Ein fehlgeschlagener
  Login oder eine noch nicht begonnene Tokenausstellung veraendert den Hash
  nicht. Ohne echtes Terminal brechen alle Geheimnis-verarbeitenden
  Auth-CLI-Verben vor dem Einlesen oder Erzeugen eines Geheimnisses ab und
  verweisen auf den direkten Aufruf in einem interaktiven Terminal.

Detailparameter wie Session-ID-Format, Hash-Kosten und Dateiname bleiben
Implementierungsdetail. Normativ sind Cookie-Session mit lokalem Passwort und
der oben beschriebene gemeinsame Zustandsowner im einen Writer-Prozess.

### 15.10.4 Thin-Client-Token (Project-API)

- **Bearer-Token** im HTTP-Header `Authorization: Bearer <token>`.
- **Rollen und Erzeuger**: Backend-Admin und Client-Bediener sind verschiedene
  Personen auf verschiedenen Maschinen. Der Backend-Admin meldet sich mit dem
  Strategenpasswort an und erzeugt das Token kernseitig mit
  `<absolute-agentkit-wrapper> auth issue-token`. Die Core-CLI erzeugt Token-ID und kryptographisch
  zufaelliges Tokengeheimnis in ihrem Speicher; zum Server gelangen nur
  Token-ID und SHA-256-Hash. Weder HTTP-Antwort noch Idempotenz-Record enthalten
  den Klartext. Nach bestaetigter Registrierung gibt die CLI den Klartext genau
  einmal im direkt bedienten Admin-Terminal aus und legt auf der Core-Maschine
  keine `.agentkit/credentials` an.
- **Uebergabe und Client-Annahme**: der Admin uebergibt das Token ausserhalb von
  AK3 an den Client-Bediener. AK3 besitzt dafuer weder Antrag, Freigabe,
  Warteschlange noch sonstigen Uebergabezustand. Auf dem Entwicklerrechner liest
  `<absolute-agentkit-wrapper> auth store-token` ausschliesslich das ausgehaendigte Token ein; das
  Strategenpasswort ist weder Eingabe noch Umgebungsvariable noch Datei dieses
  Pfades. Vor der lokalen Publikation prueft die CLI das Token mit einem
  authentisierten, read-only Projektaufruf ueber HTTPS. Ein ungueltiges oder zum
  falschen Projekt gehoerendes Token wird nicht gespeichert.
- **Interaktive Klartextgrenze**: `issue-token` und `store-token` verlangen
  stdin, stdout und stderr an einem echten Terminal. Ohne Terminal wird vor
  Erzeugung, Einlesen oder Ausgabe des Tokens fail-closed abgebrochen;
  stdout/stderr erhalten kein Token.
- **Tokens werden pro Thin-Client-Registrierung ausgestellt** —
  ein Projekt kann mehrere Tokens haben (z. B. ein Token pro
  registriertem Zielprojekt-Workspace).
- **Erste Projektregistrierung ohne Rollenvermischung**: der Projektkontext
  besteht kernseitig, bevor der Admin ein daran gebundenes Token ausstellt. Der
  Backend-Admin darf genau diesen noch nicht vorhandenen, credential-losen
  Kontext ueber das strategengeschuetzte `POST /v1/projects` anlegen; ein
  bereits vorhandener Project-Key wird ohne Mutation mit `409` abgewiesen.
  Dieser vorgelagerte Bootstrap ist nicht `register-project` und darf kein
  vorhandenes Projekt aktualisieren. Der
  Client-Bediener speichert das ausgehaendigte Token vor `register-project`.
  CP10d und jeder weitere Edge-Aufruf verwenden ausschliesslich diese aktive
  Projekt-Credential; `register-project` liest kein Strategenpasswort und baut
  keine temporaere Strategen-Session auf. Ein fehlendes, ungueltiges oder
  unsicheres Credential blockiert vor CP10d mit dem Verweis auf `store-token`.
  Installer, regulaerer ProjectEdge und Governance-Hook-Client behandeln diesen
  Zustand gleich und halten waehrend der Projektregistrierung denselben lokalen
  Credential-Prozesslock.
- **Speicherung serverseitig**: Tokens werden gehasht in einer
  dedizierten Tabelle gehalten (Projekt-FK, Token-Label,
  Erstellungsdatum, ggf. Ablaufdatum). Nach der einmaligen adminseitigen
  Anzeige wird der Klartext serverseitig nie ausgegeben oder gespeichert.
- **Speicherung clientseitig**: das Zielprojekt haelt das Token im Klartext in
  der dedizierten projekt-lokalen Credential-Datei `.agentkit/credentials`.
  Diese Datei ist Geheimnisspeicher, keine allgemeine editierbare
  Konfigurationsquelle, und liegt ausserhalb der Versionsverwaltung. Fuer sie
  gelten dieselben nachgemessenen Rechte wie fuer die Auth-Datei: POSIX `0600`,
  Windows eine geschuetzte DACL mit ausschliesslichem `FullControl` fuer die
  aktuelle Benutzer-SID. Ein nicht bestaetigbarer Schutz sperrt die Verwendung.
- **Abbruch und Wiederaufnahme**: `issue-token` zeigt `op_id` und Token-ID vor
  dem Netzwerkaufruf, aber den Klartext erst nach bestaetigter Registrierung.
  Bleibt das Ergebnis unbekannt oder stirbt die CLI vor der Klartextausgabe,
  widerruft der Admin die zuvor ausgegebene Token-ID und stellt ein neues Token
  aus; ein unbekanntes serverseitig gueltiges Token bleibt damit nicht liegen.
  `store-token` prueft zuerst den Bearer gegen den Core und publiziert danach die
  vollstaendige aktive Credential atomar. Ein Abbruch vor der Publikation wird
  durch erneutes `store-token` wiederholt, ein Abbruch danach findet die
  vollstaendige aktive Datei. Der gesamte lokale Credential-Uebergang ist durch
  einen nicht-blockierenden Betriebssystem-Prozesslock pro Credential-Datei
  serialisiert; Installer, regulaerer ProjectEdge und Governance-Client koennen
  keinen teilweise publizierten Zustand beobachten.
- **Revocation**: ein Token kann ueber die Project-Management-API
  oder `auth revoke-token` explizit widerrufen werden. Die CLI zeigt ihre
  adminseitige `op_id` vor dem Request und akzeptiert sie beim Retry erneut.
  Die kernseitige Revocation greift nicht auf den Laptop-Dateibaum zu. Nach
  Revocation werden Anfragen mit diesem Token mit `401 Unauthorized` abgelehnt;
  eine dort noch liegende widerrufene Credential bleibt sichtbar unbrauchbar
  und wird durch die naechste explizite `store-token --replace`-Publikation
  ersetzt.
- **Lebensdauer und Rotation**: ohne explizit gesetztes Ablaufdatum gilt ein
  Token bis zu seinem Widerruf. Rotation besteht aus zwei getrennten,
  rollengetrennten Schritten mit einer ausserhalb von AK3 liegenden Uebergabe:
  Der Admin stellt ein neues Token aus, der Client-Bediener prueft und
  publiziert es mit `store-token --replace`, danach widerruft der Admin das alte
  Token anhand seiner Token-ID. Bis zum Widerruf bleiben beide Tokens gueltig.

Tokens sind **projektgebunden**. Ein Token, das fuer Projekt A
ausgestellt wurde, darf nicht auf Projekt B operieren. Das wird
serverseitig in der Auth-Middleware geprueft, bevor der jeweilige
BC-Router uebernimmt.

### 15.10.5 Verhalten bei fehlender oder ungueltiger Auth

- **Fehlender Cookie/Token** auf einem geschuetzten Endpoint → `401
  Unauthorized`, opake Fehlermeldung.
- **Ungueltiger Cookie/Token** (abgelaufen, widerrufen, falsch) → `401
  Unauthorized`, opake Fehlermeldung.
- **Token gehoert nicht zum angefragten Projekt** → `403 Forbidden`,
  opake Fehlermeldung.
- **Login-Endpoint, Health-Check, ggf. SSE-Heartbeat und der eng begrenzte
  Logout-Replay bei bereits fehlender Zielsitzung** sind die einzigen
  Endpoints ohne Auth-Pflicht. Der Logout-Replay ist keine allgemeine anonyme
  Mutation: er kann ausschliesslich den bereits erreichten Zustand „keine
  Session“ bestaetigen, setzt den Loesch-Cookie erneut und besitzt keinen
  weiteren Seiteneffekt. Eine anonyme Bootstrap-Mutation gibt es auf der
  HTTP-Oberflaeche nicht.
- **Administrative Auth-Oberflaechen** fuer Passwortrotation, Logout sowie
  Auflistung, Registrierung und Widerruf von Project-Tokens verlangen einen
  authentifizierten Strategen-Principal. Fuer Logout gilt das bei einer
  vorhandenen gueltigen Zielsitzung; ein fehlendes oder bereits ungueltiges
  Session-Cookie wird als idempotenter Replay des bereits erreichten
  Abmeldezustands mit Erfolg beantwortet. Ein Project-Token wird auf allen
  administrativen Auth-Oberflaechen einschliesslich Logout mit `403 Forbidden`
  abgewiesen, auch wenn es fuer das im Pfad oder Header benannte Projekt
  gueltig ist.

### 15.10.6 Erweiterbarkeit (out of scope fuer v1)

Das Auth-Konzept ist bewusst minimal. Folgende Erweiterungen sind
nicht in v1 enthalten, aber strukturell **nicht ausgeschlossen**:

- Mehrere Strategen-Konten mit jeweils eigenem Passwort
- OIDC-/SSO-Anbindung
- Rollen- und Berechtigungsmodell pro Projekt (Owner, Operator,
  Viewer)
- Token-Scopes (read-only vs. read-write)
- mTLS fuer Maschinen-Clients

Wenn eine dieser Erweiterungen relevant wird, ist die Auth-Schicht
als R-Boundary ausgelegt, in dem die zusaetzlichen Mechanismen
nachgezogen werden koennen, ohne die fachlichen BCs anzufassen.

---

*FK-Referenzen: FK-04-012 bis FK-04-017 (Rollentrennung durch
Zugriffsrechte), FK-06-001 bis FK-06-006 (Fail-Closed-Grundprinzipien),
FK-06-017/FK-06-033/FK-06-093 (opake Fehlermeldungen),
FK-06-099 bis FK-06-103 (Governance-Beobachtung Hook-Signale),
FK-05-140 (Secrets im Diff)*
