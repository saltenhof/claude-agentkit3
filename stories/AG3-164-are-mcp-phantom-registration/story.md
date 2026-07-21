# AG3-164 — Generischer MCP-Conformance-Check als Registrierungsvorbedingung; ARE-Phantomregistrierung schlaegt ehrlich fehl

- **Typ:** implementation
- **Groesse:** M
- **depends_on:** [AG3-172] — Landeblocker: die Pflichtsuite ist wegen
  einer Postgres-Schema-/Katalog-Race unter xdist nicht deterministisch
  (Vorbestandsdefekt, kein AG3-164-Code). Autoritativ in `status.yaml`.
  Fachlich unabhaengig startbar; keine Kante in die VektorDB-Kette.
- **unblocks:** [AG3-168, AG3-171] — beide konsumieren den generischen
  Conformance-Check, praegen ihn nicht neu aus.
- **Quell-Konzept:** FK-50 (Installer-Checkpoint-Engine, CP10,
  Fehlerfall-Tabelle, `FAILED`-Semantik); FK-03 §3.1 (`are.mcp_server`
  an `features.are` gebunden)
- **Herkunft:** Ist-Stand-Befund 2026-07-20; Codex-Review
  `stories/AG3-161-vectordb-mcp-server-bundle/review-codex.md` P1-2;
  `review-2-codex.md` neues P1-3 (geteilte CP10-Ownership,
  Startbarkeits-Check zu schwach, Groesse M statt S).

## Kontext / Problem

`cp10.py:76-82` registriert bei `features.are: true` in der
Zielprojekt-`.mcp.json` den Server-Key `are-mcp` mit dem Kommando
`agentkit-are-mcp`. Dieser Konsolen-Befehl ist **nicht** in
`pyproject.toml` unter `[project.scripts]` registriert und existiert
nicht im Repository. Der Installer schreibt damit einen toten Eintrag und
meldet den Checkpoint als erfolgreich. Die bestehenden CP10-Tests pruefen
ausschliesslich das JSON-Merge-Verhalten.

Dieselbe Fehlklasse trifft den Story-Knowledge-Base-Server: CP10 schreibt
`python -m agentkit.backend.vectordb.mcp_server`, obwohl das Modul erst
mit AG3-167 entsteht. **Zwei Stories duerfen diesen Belang nicht
getrennt ausbilden** — sonst praegen sie denselben Code und Vertrag
unterschiedlich aus, und die eine reisst die andere wieder auf
(`review-2-codex.md` neues P1-3).

**PO-Entscheidung E7 (verbindlich, nicht neu aufzurollen):** AG3-164 ist
**alleiniger Owner** des generischen Checks. Erfolg heisst **mindestens**:
Prozessstart mit Timeout, MCP `initialize`, `tools/list`. **Blosses
Aufloesen eines Kommandos genuegt nicht** — ein vorhandenes Programm, das
sofort stirbt oder kein MCP spricht, waere sonst wieder gruen. Die
Registrierung wird **erst nach bestandenem Check** geschrieben. AG3-168
haengt von dieser Story ab und konsumiert den Check fuer den
Story-Server.

**Verworfene Aufloesungen** (Codex P1-2, ausdruecklich zurueckgewiesen):

- Den Eintrag ersatzlos entfernen — widerspricht FK-50/FK-03, die die
  Registrierung an `features.are` binden.
- Die Luecke als „sichtbar normiert" stehenlassen — ein toter Befehl
  wird dadurch nicht ZERO-DEBT-konform.

## Scope

### In Scope

1. **Generischer MCP-Conformance-Check.** Ein wiederverwendbarer,
   servertyp-unabhaengiger Check mit genau diesem Erfolgsbegriff:
   - Kommando aufloesbar (Interpreter/Konsolenbefehl existiert im
     Zielprofil);
   - **Prozessstart** mit hartem Timeout und definiertem Abbruchpfad
     (kein haengender Subprozess, kein Zombie);
   - **MCP `initialize`** ueber stdio erfolgreich;
   - **`tools/list`** liefert eine wohlgeformte, nicht leere Antwort;
   - Prozess wird in jedem Ausgang sauber beendet.
   Der Check ist **generisch** — er kennt weder ARE noch VektorDB, nur
   Kommando, Argumente, `cwd` und Umgebung.
2. **Registrierung erst nach bestandenem Check.** CP10 schreibt einen
   `mcpServers`-Eintrag **ausschliesslich** nach bestandenem Check. Bei
   Nichtbestehen: `FAILED` mit klarer, maschinenlesbarer Ursache
   (Kommando fehlt / Prozess gestorben / Timeout / kein MCP /
   Toolliste leer) — kein Warnpfad, kein Teil-Schreiben, kein
   nachtraegliches Aufraeumen halbgeschriebener Konfiguration.
3. **Ehrliches Fehlschlagen des ARE-Falls.** Solange `agentkit-are-mcp`
   nicht existiert, scheitert ein Installationslauf mit
   `features.are: true` beim zustaendigen Checkpoint mit klarer Ursache,
   statt einen toten Eintrag zu schreiben und Erfolg zu melden.
4. **Fehlerbild und Ausgang normativ verankern.** Der Check und seine
   `FAILED`-Ursachen werden in FK-50 (CP10) aufgenommen — inklusive der
   Abgrenzung zu `SKIPPED` (*bewusst-abwesend*, z. B. `features.are:
   false`) gegenueber `FAILED` (*konfiguriert, aber nicht lauffaehig*).
5. **Tests, die den Defekt reproduzieren:** `features.are: true` ohne
   existierenden Befehl fuehrt zum Fehlschlag; ein Kommando, das startet
   und sofort stirbt, ebenfalls; ein Kommando, das laeuft aber kein MCP
   spricht, ebenfalls; ein echter, MCP-sprechender Testserver fuehrt zu
   erfolgreicher Registrierung.
6. **Konfliktregel:** Zeigt die Analyse, dass FK-50/FK-03 die
   ARE-Registrierung anders vorsehen als CP10 sie umsetzt: **stoppen und
   melden**, nicht eigenmaechtig abweichen.

### Out of Scope (mit Owner)

- Den ARE-MCP-Server implementieren (eigener Strang, im Story-Bericht zu
  benennen).
- **Anwendung des Checks auf den Story-Knowledge-Base-Server und die
  Codex-Registrierung:** AG3-168 — dort konsumiert, hier gebaut.
- MCP-Server, Tools und Retrieval: AG3-167.
- Aenderungen an der ARE-Fachlogik.

## Betroffene Dateien

| Datei | Aenderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/installer/mcp_conformance.py` | neu | generischer Check (Start, Timeout, `initialize`, `tools/list`, Teardown) |
| `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py` | aendern | Registrierung erst nach bestandenem Check; benannte `FAILED`-Ursachen |
| `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md` | aendern | CP10: Conformance-Vorbedingung, Ursachenkatalog, `SKIPPED`-vs.-`FAILED`-Abgrenzung |
| `tests/unit/installer/checkpoint_engine/test_checkpoints.py` | erweitern | Negativpfade + Positivpfad mit echtem Testserver |
| `tests/integration/installer/` | neu/erweitern | Conformance gegen einen minimalen echten MCP-Testserver |

## Akzeptanzkriterien

1. Ein Installationslauf mit `features.are: true` und nicht existierendem
   `agentkit-are-mcp` schlaegt fehl mit klarer, maschinenlesbarer
   Ursache; ein Test beweist es.
2. In diesem Fall wird **kein** `are-mcp`-Eintrag in die
   Zielprojekt-`.mcp.json` geschrieben — auch kein teilweiser.
3. Der Check ist **generisch** und gilt fuer alle von CP10 registrierten
   MCP-Server; ein Test belegt die Anwendung auf mindestens zwei
   unterschiedliche Serverdefinitionen.
4. **Falsches Gruen ausgeschlossen:** Drei Negativfaelle scheitern
   jeweils benannt — (a) Kommando existiert nicht, (b) Prozess startet
   und stirbt sofort, (c) Prozess laeuft, beantwortet aber `initialize`
   nicht bzw. liefert keine Toolliste. Ein reiner „Kommando loest auf"-Pfad
   existiert nicht mehr.
5. **Positivpfad real:** Ein minimaler, echter MCP-Testserver besteht
   `initialize` und `tools/list` und wird registriert.
6. **Ressourcensauberkeit:** In allen Ausgaengen (Erfolg, Timeout, Tod,
   Protokollfehler) bleibt kein Subprozess zurueck; ein Test prueft das.
7. Ein Lauf mit `features.are: false` bleibt unveraendert erfolgreich
   (`SKIPPED` mit `reason`, nicht `FAILED`).
8. Bestehende CP10-Tests (Merge-Idempotenz, Erhalt fremder Eintraege,
   Dry-Run/Verify) bleiben gruen.
9. FK-50 traegt die Conformance-Vorbedingung und den Ursachenkatalog;
   Konzept-Gates sind gruen.

## Definition of Done

- Alle Akzeptanzkriterien erfuellt.
- `pytest` gruen, Coverage haelt 85 %; `mypy src`, `ruff check src tests`
  sauber; Konzept-Gates gruen.
- Keine Mocks fuer den Conformance-Pfad: der Positivfall laeuft gegen
  einen echten Subprozess mit echtem MCP-Handshake.
- Story-Bericht benennt, ob und wo der ARE-Server als Folgearbeit
  gefuehrt wird, und dokumentiert die Auswirkung auf laufende
  Installationen (VektorDB-Eintrag wird bis AG3-167/168 ehrlich rot —
  bewusster, in AG3-161 benannter Uebergangszustand).

## Abdeckung (Traceability)

**Deckt ab:** review-codex.md P1-2 (ARE-Fremdkoerper separiert, beide
verworfenen Aufloesungen ersetzt); review-2-codex.md neues P1-3 (AG3-164
alleiniger Owner des generischen Checks, Erfolgsbegriff verschaerft,
Registrierung erst nach bestandenem Check, Groesse M); Alt-AG3-164
Scope 1–4 und Alt-AC 1–5 vollstaendig; Alt-AG3-163 AC 8 (Startbarkeits-
und Protokollnachweis) im generischen Teil.

## Konzept-Referenzen

FK-50 (CP10, Idempotenz, `FAILED`-/`SKIPPED`-Semantik, Fehlerfall-Tabelle) ·
FK-03 §3.1 (`features.are`, `are.mcp_server`)

## Guardrail-Referenzen

- **FAIL-CLOSED:** konfiguriert-aber-nicht-lauffaehig ist `FAILED`, nicht
  `SKIPPED`.
- **ZERO DEBT:** kein toter Eintrag, keine „sichtbar normierte Luecke".
- **NO ERROR BYPASSING:** kein Warnpfad und kein Teil-Schreiben bei
  nicht bestandenem Check.
- **SINGLE SOURCE OF TRUTH:** genau ein Conformance-Check fuer alle
  CP10-Registrierungen.
- **ARCH-55:** Ursachencodes und Bezeichner englisch.

## Querschnitts-Auflagen

- **Blutgruppen-Klassifikation:** Ursachen-/Ausgangsklassifikation =
  **A**; Subprozess-/stdio-Transport = **T**; CP10-Verdrahtung = **R**.
- **Bundle-Assets:** `bundles/target_project/.mcp.json`-Vorlagen nur
  anfassen, falls der Ausgangswechsel sie beruehrt.
- **K5 Postgres-only:** nicht einschlaegig.

## Abnahmestand (Council-Orchestrator, 2026-07-21)

Code-Freigabe durch den unabhaengigen Reviewer in `review-11-codex.md`:
**AG3-164 ist im eigenen Code abnahmereif.** Zehn adversariale
Review-Runden (`review-{1..11}-codex.md`), zehn Remediation-Runden. Die in
elf Runden verfolgte Fehlerklasse "geerbte Nachsicht an fail-closed-Grenzen"
ist ueber Wire und Config strukturell geschlossen (finaler Musterdurchgang,
neun Punkte). Conformance-Testumfang 42 -> 109.

Bewusst festgehaltene Praezisierung (Reviewer-Auflage, kein Defekt): Der
Erhalt fremder `.mcp.json`-Eintraege im **Erfolgspfad** ist
**semantisch/wertegenau**, nicht lexikalisch byte-genau — der Merge
serialisiert deterministisch neu (Einrueckung, sortierte Keys). Die
Byte-Identitaet gilt ausschliesslich auf dem **Fehlerpfad** (keine
Mutation). Eine woertlich byte-erhaltende JSON-Patch-Engine waere fuer
diese Story unverhaeltnismaessig; falls je normativ gewuenscht, eigene
PO-Entscheidung und Story.

**Noch nicht `completed`** — zwei offene (b)-Orchestrator-Punkte:
1. **AG3-172** (Postgres-Schema-/Katalog-Race unter xdist) ist
   autoritativer Landeblocker (`depends_on`): keine Landung auf
   nicht-hermetischer Pflichtsuite.
2. Nach AG3-172: Status `completed`, vollstaendige CI-/Coverage-Belege.

**ARE-Folgearbeit:** Der eigentliche `agentkit-are-mcp`-Server ist als
**AG3-173** angelegt (`depends_on: [AG3-164]`); diese Story macht den
ARE-Pfad nur ehrlich rot, AG3-173 macht ihn gruen.
