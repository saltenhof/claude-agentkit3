---
concept_id: META-DEC-2026-07-20-MCP-CONFORMANCE-REGISTRATION-GATE
title: Concept-Decision-Record — Generischer MCP-Conformance-Check als CP10-Registrierungsvorbedingung
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, installer, mcp, conformance, CP10, AG3-164]
formal_scope: prose-only
---

# Concept-Decision-Record — Generischer MCP-Conformance-Check als CP10-Registrierungsvorbedingung

Datum: 2026-07-20 (Review-Rework). Record gemaess META-CONCEPT-CONSISTENCY P3
und W4, auf Grundlage von Story AG3-164 und PO-Entscheidung E7.

## 1. Anlass

CP 10 registrierte MCP-Server-Eintraege in der Zielprojekt-`.mcp.json`
(unter anderem `are-mcp` mit Kommando `agentkit-are-mcp`), ohne zu
pruefen, ob dahinter ein lauffaehiger MCP-Server steht. Der Installer
meldete Erfolg fuer eine Faehigkeit, die nicht existierte (Phantom-
registrierung). Dieselbe Fehlklasse betraf den spaeteren
Story-Knowledge-Base-Server.

## 2. Entscheidung

AG3-164 ist **alleiniger Owner** des generischen MCP-Conformance-Checks.
Der Check ist servertyp-unabhaengig und prueft mindestens:

1. Kommandoaufloesung (relative Pfade gegen effektives `cwd`)
2. Prozessstart mit monotoner Deadline, reserviertem Teardown-Anteil und
   plattformspezifischer Prozessklammer (POSIX Process-Group; Windows Job
   Object: CREATE_SUSPENDED → Assign → Resume; fail-closed bei
   Klammer-Fehler als `mcp_process_control_error`). Der synchrone OS-Popen
   ist plattformabhaengig nicht unterbrechbar und liegt ausserhalb des
   kontrollierten Budgets.
3. MCP `initialize` ueber stdio (JSON-RPC 2.0 disjunkt, striktes UTF-8,
   unterstuetzte `protocolVersion`, `capabilities.tools` als Objekt,
   `serverInfo.name/version`)
4. MCP-Methode tools/list mit wohlgeformter, nicht leerer Tool-Liste
   (jedes Tool: nichtleerer `name`, Objekt-`inputSchema`)
   <!-- REF-INTEGRITY:IGNORE-LINE MCP method tools/list is not a repo path -->

Die Registrierung in `.mcp.json` erfolgt **ausschliesslich im mutierenden
REGISTER-Pfad nach** bestandenem Check. Bei Nichtbestehen:
Checkpoint-Status `FAILED` mit maschinenlesbarem `reason`
(`mcp_command_not_found`, `mcp_process_exited`, `mcp_timeout`,
`mcp_protocol_error`, `mcp_tools_list_empty`,
`mcp_process_control_error`) — kein Warnpfad, kein Teil-Schreiben,
kein stiller Snapshot-Fallback.

Die vorhandene Ziel-`.mcp.json` wird in allen Modi (REGISTER / DRY_RUN /
VERIFY) mit einem **gemeinsamen strikten Loader** gelesen (CP 10 Merge und
ARE-MCP-Präsenz in CP 10c). Ist die Datei vorhanden, liest auch die
ARE-MCP-Präsenzprüfung sie in jedem Modus; nur bei fehlender Datei leiten
DRY_RUN/VERIFY aus `features.are` ab. Parse-/Shape-Fehler (ungültiges UTF-8,
Parser-Recursion, doppelte Namen, Nicht-JSON-Konstanten, nicht-endliche
Floats, isolierte Surrogates, Nicht-Objekt-Root, ungültiges `mcpServers` oder
nicht-objektförmiger Server-Eintrag) sind `FAILED` /
`mcp_configuration_invalid` ohne Mutation und ohne Conformance-Start.
Schreiben setzt `allow_nan=False`. Wire- und Config-Loader teilen die reinen
JSON-/Unicode-Hilfen. Wire-Fehler bleiben `mcp_protocol_error` und werden
nicht mit Dateikonfigurationsfehlern vermischt.

**Dry-run** bleibt reine Planableitung ohne Prozessstart. **Verify**
bleibt read-only auf Konfigurationsshape und Soll/Ist-Differenz ohne
Prozessstart. Ein aktiver MCP-Healthcheck in Dry-run/Verify ist
**nicht** Teil dieser Entscheidung (eigene normative Entscheidung mit
Security-Impact).

`SKIPPED` bleibt dem *bewusst-abwesenden* Fall vorbehalten
(`features.vectordb` und `features.are` beide false →
`reason=vectordb_disabled`). *Konfiguriert, aber nicht lauffaehig* ist
im Register-Pfad immer `FAILED`.

FK-50 §50.3 CP 10 traegt die Conformance-Vorbedingung, den
Ursachenkatalog und die `SKIPPED`-vs.-`FAILED`-Abgrenzung sowie die
Modusgrenze. FK-03 §3.1 bleibt unveraendert. AG3-168 konsumiert denselben
Check und praegt ihn nicht neu aus.

Der Kindprozess erhaelt nur ein **Minimal-Environment** (plattformnotwendige
Startvariablen + explizite `entry.env`); Installer-/CI-Secrets werden nicht
vererbt.

## 3. Alternativen

- Eintrag ersatzlos entfernen — verworfen (widerspricht FK-50/FK-03).
- Luecke als „sichtbar normiert“ stehenlassen — verworfen (ZERO DEBT).
- Nur Kommandoaufloesung als Erfolg — verworfen (PO E7).
- Pro Server-Typ eigener Check — verworfen (geteilte Ownership).
- Conformance auch in Dry-run/Verify — verworfen (bricht
  side-effect-freien Modusvertrag; Security-Blast-Radius).

## 4. Impact-Sweep (P3)

Lexikalisch/semantisch gepruefte Betroffenheit nach Code- und
Konzeptkorrektur (Rework nach review-1-codex):

| Artefakt / Scope | Klassifikation | Begruendung |
|------------------|----------------|-------------|
| FK-50 §50.3 CP 10 | **geaendert** | Conformance-Vorbedingung, Ursachenkatalog, SKIPPED/FAILED, Register-only-Gate, Dry-run/Verify-Modusgrenze |
| FK-50 §50.6 Fehlerfall-Tabelle | **geaendert** | MCP-`mcp_*`-FAILED-Zeilen + bewusst-abwesend SKIPPED |
| FK-50 §50.2 / ExecutionMode dry-run/verify | **referenziert-jetzt** | Vertrag bewusst **nicht** geaendert: kein Prozessstart in dry-run/verify |
| FK-03 §3.1 `features.are` / `are.mcp_server` | **nicht-betroffen** | Bindung bleibt; nur ehrliches FAILED bis Server existiert |
| `formal-spec/installer/invariants.md` (`verify_project_is_read_only`, `dry_run_never_mutates_…`) | **referenziert-jetzt** | Invarianten bestaetigt; Implementierung muss sie einhalten (kein aktiver Healthcheck) |
| Installer-Package `mcp_conformance` (types/protocol/transport/process/check) | **geaendert** | generischer Check, fachlich geschnitten |
| Installer CP10 (`bootstrap_checkpoints/cp10.py`) | **geaendert** | Gate nur im REGISTER-Pfad vor Write |
| Checkpoint-Reasons (`checkpoint_engine/reasons.py`) | **geaendert** | SSOT der `mcp_*`-Reason-Tokens |
| ExecutionMode (`checkpoint_engine/execution_mode.py`) | **nicht-betroffen** | Vertrag unveraendert genutzt |
| Tests unit/integration installer MCP | **geaendert** | adversarial, slow-response, process-tree, SDK-interop, Idempotenz, Dry-run-Plan |
| AG3-168 | **referenziert-jetzt** | konsumiert Check spaeter |
| Trust-Boundary / Prozesslebenszyklus | **geaendert** | Installer startet fremdes Kommando nur in REGISTER; Minimal-Env; Prozessbaum-Kill |
| Security (Secret-Vererbung) | **geaendert** | kein volles `os.environ` an den Probe-Prozess |
| K5 Postgres / Frontend / Ownership | **nicht-betroffen** | ausserhalb Scope |

## 5. Betroffenheitsmatrix (Kurzform)

| Bereich | Status |
|---------|--------|
| Konzept FK-50 | geaendert |
| Konzept FK-03 | nicht-betroffen (Referenz) |
| Formal Installer-Invarianten Dry-run/Verify | referenziert-jetzt (eingehalten) |
| Code Installer CP10 + Conformance + Reasons | geaendert |
| Tests | geaendert |
| Downstream AG3-168 | referenziert-jetzt |
| Security/Prozess | geaendert (REGISTER-only + Minimal-Env + Tree-Kill) |
