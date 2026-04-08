---
concept_id: FK-15
title: Security, Secrets, Identity und Zugriffsmodell
module: security
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
    scope: sperrdatei-mechanismus
    reason: QA-Artefaktschutz nutzt Sperrdatei-Mechanismus aus FK-02
supersedes: []
superseded_by:
tags: [security, secrets, identity, berechtigungen, governance-schutz]
---

# 15 — Security, Secrets, Identity und Zugriffsmodell

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
Zone 1: Plattform (Claude Code + Hooks)     — Agent kann nicht umgehen
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
| **Orchestrator** (Hauptagent) | Claude-Code-Session, kein Parent-Agent | Zone 3 — darf steuern, nicht implementieren |
| **Worker** (Sub-Agent) | Von Orchestrator gespawnt, `subagent_type: worker` | Zone 3 — darf implementieren, nicht QA manipulieren |
| **QA-Agent** (Sub-Agent) | Von Orchestrator gespawnt, `subagent_type: qa` | Zone 3 — darf lesen und testen, nicht Produktivcode editieren |
| **Adversarial** (Sub-Agent) | Von Orchestrator gespawnt, `subagent_type: adversarial` | Zone 3 — darf nur in Sandbox schreiben |
| **Pipeline-Skript** | Python-Prozess, aufgerufen via Bash-Tool | Zone 2 — deterministisch, vertrauenswürdig |
| **Hook-Prozess** | Python-Prozess, aufgerufen von Claude Code | Zone 1 — Plattform-Enforcement |
| **LLM-Pool** (extern) | MCP-Server, Antwort auf `{pool}_send` | Zone 4 — Antworten werden validiert, nie blind vertraut |

### 15.3.2 Principal-Erkennung

Hooks und Guards müssen erkennen, welcher Principal gerade agiert,
um rollenspezifische Regeln anzuwenden:

| Erkennungsmerkmal | Wie | Zuverlässigkeit |
|-------------------|-----|----------------|
| Hauptagent vs. Sub-Agent | Claude Code setzt Hook-Kontext (`is_subagent` Flag) | Plattform-garantiert |
| Sub-Agent-Typ | `subagent_type` im Agent-Spawn-Prompt | Prompt-basiert — kann der Orchestrator setzen, aber der Hook validiert gegen erwartete Typen |
| Pipeline-Skript | Kein Claude-Code-Kontext, direkter Python-Aufruf | Eindeutig — Skript wird nicht über Hook-Schicht aufgerufen |
| Story-Execution aktiv | Marker-Datei `_temp/governance/active/{story_id}.active` existiert | Dateisystem — vom Pipeline-Tooling gesteuert, nicht vom Agent |

## 15.4 Berechtigungsmodell

### 15.4.1 Berechtigungsmatrix

| Aktion | Mensch | Orchestrator | Worker | QA-Agent | Adversarial | Pipeline-Skript |
|--------|--------|-------------|--------|----------|-------------|----------------|
| Code lesen | ✅ | ❌ (Guard) | ✅ | ✅ | ✅ | ✅ |
| Code schreiben | ✅ | ❌ (Guard) | ✅ | ❌ (Guard) | ❌ (nur Sandbox) | ✅ |
| Tests schreiben | ✅ | ❌ | ✅ | ❌ | ✅ (nur Sandbox) | ✅ |
| Tests ausführen | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| QA-Artefakte schreiben | ✅ | ❌ | ❌ (Sperrdatei) | ❌ (Sperrdatei) | ❌ (Sperrdatei) | ✅ |
| QA-Artefakte lesen | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Commit auf Main | ✅ | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ✅ |
| Commit auf Story-Branch | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| Force-Push | ✅ | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ❌ (Guard*) | ❌ |
| GitHub Issue ändern | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Sperrdatei erstellen/löschen | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| LLM-Pool aufrufen | ✅ | ✅ | ✅ | ❌ | ✅ (Sparring) | ✅ (Evaluator) |
| Agents spawnen | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |

*Guard = nur aktiv im Story-Execution-Modus (Sperrdatei vorhanden,
Kap. 12.4.1). Im AI-Augmented-Modus sind Branch-Guards inaktiv.

### 15.4.2 Durchsetzungsmechanismen

| Einschränkung | Mechanismus | Umgehbar durch Agent? |
|--------------|------------|---------------------|
| Orchestrator darf nicht auf Codebase zugreifen | `orchestrator_guard.py` (PreToolUse-Hook) | Nein — Hook ist Plattform-Infrastruktur |
| Worker darf keine QA-Artefakte schreiben | Sperrdatei + Hook (Kap. 02.7) | Nein — Sperrdatei vom Pipeline-Tooling, nicht vom Agent |
| Adversarial darf nur in Sandbox schreiben | CCAG-Regel `scope: subagent` | Nein — CCAG ist Hook-basiert |
| Branch-Guard (Story-Execution) | `branch_guard.py` (PreToolUse-Hook) + Sperrdatei | Nein — Hook + Sperrdatei |
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
diese spezifischen Operationen **keine Sperrdatei benötigt** —
sie sind immer aktiv, als Basisschutz.

## 15.5 Secrets-Verwaltung

### 15.5.1 Grundregel: Keine Secrets im Repository

AgentKit speichert keine Secrets. Keine API-Keys, keine Passwörter,
keine Token im Code, in der Konfiguration oder in Artefakten.

| Secret-Typ | Wo gespeichert | Zugriff durch AgentKit |
|-----------|---------------|----------------------|
| GitHub-Token | `gh` CLI (OS Keychain) | Implizit über `gh` CLI-Aufrufe |
| LLM-Pool-Auth | Pool-intern (z.B. Browser-Cookies) | Kein Zugriff — Pools verwalten Auth selbst |
| Weaviate | Kein Auth (localhost-only) | Direkt über HTTP/gRPC |
| ARE | MCP-Server-Config | Kein direkter DB-Zugriff |

### 15.5.2 Secret-Detection (zweistufig)

Secrets werden an **zwei Stellen** abgefangen:

**Stufe 1: Pre-Commit-Hook (verhindert das Entstehen)**

> **Hinweis:** Der Pre-Commit-Hook verwendet seit der
> ConceptContext-Einführung (Kap. 13.9) pfadbasiertes Dispatching
> für funktionale Checks (Versionsbump, Concept-Validation).
> Die Secret-Detection bleibt davon **unberührt** — sie ist
> global aktiv und läuft bei jedem Commit, unabhängig von den
> geänderten Pfaden. Details: Kap. 30.5.3.

Ein Git-Pre-Commit-Hook (`tools/hooks/pre-commit`) prüft den
Staging-Bereich auf Secrets, **bevor** der Commit erzeugt wird.
Wenn Secrets erkannt werden, wird der Commit abgelehnt. Damit
landen Secrets nie in der Git-Historie — der Agent müsste sonst
die Historie umschreiben, was durch den Branch-Guard (kein
Hard-Reset) verboten ist.

**Stufe 2: Structural Check (Absicherung in der Verify-Phase)**

Der Structural Check `security.secrets` (Schicht 1 der Verify-Phase)
prüft den vollständigen Git-Diff nochmals als Absicherung — falls
der Pre-Commit-Hook umgangen wurde (z.B. `--no-verify`, was aber
durch CCAG blockierbar ist).

**Geprüfte Patterns (beide Stufen identisch):**

| Pattern | Blockiert |
|---------|----------|
| `.env`, `.env.*` | Ja (BLOCKING) |
| `*.pem`, `*.key`, `*.p12` | Ja (BLOCKING) |
| `credentials.json`, `serviceaccount.json` | Ja (BLOCKING) |
| `*_SECRET*`, `*_TOKEN*`, `*_PASSWORD*` | Ja (BLOCKING) |
| `*.keystore`, `*.jks` | Ja (BLOCKING) |

Zusätzlich scannt der Check Diff-Inhalte auf Patterns wie
`AKIA` (AWS Access Key), `ghp_` (GitHub PAT), `sk-` (OpenAI Key).

### 15.5.3 Governance-Beobachtung: Secret-Zugriff

Die Governance-Beobachtung (Kap. 14.8, FK 6.6) erkennt
Zugriffe auf Secrets als Hook-Signal:

| Signal | Reaktion |
|--------|---------|
| Agent liest `.env` oder Credential-Dateien | Sofortiger Stopp (kein Score, kein LLM) |
| Agent schreibt Dateien mit Secret-Patterns im Namen | Sofortiger Stopp |

Das ist einer der wenigen Fälle, in denen der Hook nicht
über einen Risikoscore eskaliert, sondern sofort und hart
blockiert.

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
| Integrity-Gate | `"GOVERNANCE VIOLATION DETECTED. Immediately stop all work."` | Fehler-Codes in `integrity-violations.log` |
| CCAG (Sperrdatei-basiert) | `"Operation not permitted."` | Sperrdatei-Inhalt zeigt Story-ID und Scope |

### 15.6.3 Audit-Log

Das Integrity-Gate schreibt bei Blockade einen JSON-Eintrag in
`_temp/qa/{story_id}/integrity-violations.log`:

```json
{
  "ts": "2026-03-17T11:30:00+01:00",
  "failure_codes": ["NO_SEMANTIC_REVIEW", "NO_GEMINI_EVIDENCE"],
  "command_prefix": "gh issue close 42 ..."
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
| Agent ändert `.claude/settings.json` (Hook-Registrierung) | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent ändert `.claude/ccag/rules/*.yaml` | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent ändert `.story-pipeline.yaml` | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent löscht Sperrdatei | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |
| Agent ändert `.installed-manifest.json` | Hook-Signal: Governance-Datei verändert | Sofortiger Stopp |

**Geschützte Pfade** (immer, unabhängig vom Betriebsmodus):

```
.claude/settings.json
.claude/ccag/rules/
.story-pipeline.yaml
.installed-manifest.json
_temp/governance/locks/
_temp/governance/active/{story_id}.active
```

### 15.7.2 Hook-Integrität

Hooks können vom Agent nicht deaktiviert werden, weil:

1. Hook-Registrierung liegt in `.claude/settings.json` (geschützt)
2. Hook-Skripte liegen im `agentkit`-Paket (nicht im Zielprojekt)
3. Claude Code ruft Hooks als externen Prozess auf — der Agent
   hat keinen Einfluss auf den Aufrufmechanismus
4. Ein Agent, der `.claude/settings.json` editieren will, wird
   vom Governance-Selbstschutz-Hook blockiert

### 15.7.3 Sperrdatei-Integrität

Sperrdateien können vom Agent nicht manipuliert werden, weil:

1. Sperrdateien liegen in `_temp/governance/locks/` (geschützter Pfad)
2. Nur Pipeline-Skripte (Zone 2) schreiben Sperrdateien
3. Der CCAG-Hook blockiert Sub-Agent-Zugriff auf den Lock-Pfad
4. PID + TTL als Stale-Detection (Kap. 02.7) — kein manuelles
   Löschen nötig

## 15.8 Netzwerk-Sicherheit

### 15.8.1 Localhost-Only

Alle AgentKit-Dienste laufen auf `localhost`. Keine eingehenden
Netzwerkverbindungen von außen:

| Dienst | Binding | Expose |
|--------|---------|--------|
| LLM-Pools (REST) | `127.0.0.1:{port}` | Nur lokal |
| Weaviate (HTTP/gRPC) | `localhost:9903/50051` | Nur lokal |
| MCP-Server (stdio) | Kein Netzwerk | Prozess-lokal |
| VNC (Gemini/Grok) | `127.0.0.1:5900/5901` | Nur lokal |

### 15.8.2 Ausgehende Verbindungen

| Ziel | Protokoll | Zweck |
|------|----------|-------|
| `github.com` | HTTPS | `gh` CLI, `git push/pull` |
| LLM-Web-Interfaces | HTTPS | LLM-Pools (Browser-Automation an jeweiligen Anbieter) |
| Docker Hub | HTTPS | Weaviate-Image-Pull (einmalig) |

Keine outbound-Verbindungen von AgentKit-Code selbst. Alle
externen Verbindungen laufen über die Pools oder `gh`/`git`.
Die konkreten LLM-Anbieter (aktuell ChatGPT, Gemini, Grok) sind
austauschbar — AgentKit kennt nur Pool-Namen, nicht Anbieter-URLs.

## 15.9 Datenschutz und Datenflüsse

### 15.9.1 Was an externe LLMs gesendet wird

Über die Browser-Pools werden an externe LLMs gesendet:

| Daten | Wann | Enthält |
|-------|------|---------|
| QA-Bewertung (Schicht 2) | Verify-Phase | Code-Diff, Story-Beschreibung, Konzept-Auszüge |
| Semantic Review | Verify-Phase | Aggregierte Befunde + Diff |
| Dokumententreue-Prüfung | Exploration/Verify/Closure | Entwurf + Referenzdokumente |
| Adversarial-Sparring | Verify-Phase | Implementierungsbeschreibung |
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
| Telemetrie (SQLite + JSONL-Export) | `_temp/agentkit.db`, `_temp/story-telemetry/` | Nie |
| QA-Artefakte | `_temp/qa/` | Nie (nur deren Inhalt wird als Kontext gesendet) |
| Sperrdateien | `_temp/governance/locks/` | Nie |
| Failure Corpus | `.agentkit/failure-corpus/` | Nie (nur aggregierte Patterns ggf. in Check-Proposals) |
| Git-Historie | `.git/` | Nie direkt (nur Diffs) |
| Manifest | `.installed-manifest.json` | Nie |

---

*FK-Referenzen: FK-04-012 bis FK-04-017 (Rollentrennung durch
Zugriffsrechte), FK-06-001 bis FK-06-006 (Fail-Closed-Grundprinzipien),
FK-06-017/FK-06-033/FK-06-093 (opake Fehlermeldungen),
FK-06-099 bis FK-06-103 (Governance-Beobachtung Hook-Signale),
FK-05-140 (Secrets im Diff)*
