# Orchestrator-Briefing — AG3-175

- **Datum:** 2026-07-27
- **Rolle des Verfassers:** Orchestrator (nicht Worker). Dieses Dokument liefert
  den **verifizierten Ist-Zustand** und **Scope-Entscheidungen**, damit der
  Coding-Worker keine Zeit mit Wiederentdeckung verliert.
- **Review-Budget:** **EINE** Codex-Runde (PO-Vorgabe, `status.yaml` Zeile 15).
  Deshalb ist die Sorgfalt vor dem Review entscheidend, nicht danach.

Alle Befunde unten sind **selbst am Code geprueft**, nicht aus der Story
uebernommen. Die Zeilenangaben stammen vom Stand `1e713f3a` (main).

---

## 1. Befund A — der P0-1-Defekt ist heute real vorhanden

`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:148-153`
registriert den Story-Knowledge-Base-Server als **hartcodiertes Literal ohne
`env`**:

```python
servers[_STORY_KNOWLEDGE_BASE_SERVER] = {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "agentkit.backend.vectordb.mcp_server"],
}
```

Dagegen fordert `src/agentkit/backend/vectordb/runtime_binding.py:33-37`
(`REQUIRED_ENV_KEYS`) **alle drei** Schluessel `PROJECT_ID`,
`WEAVIATE_HTTP_ENDPOINT`, `WEAVIATE_GRPC_ENDPOINT` als vorhanden und nicht-leer;
`RuntimeBinding.from_env` schlaegt sonst fehl (fail-closed, D2).

**Folge:** Der heute geschriebene Eintrag erzeugt einen Server, der beim Start
seine eigene Runtime-Bindung verweigert. Das ist genau die Luecke, die AC 2
(`env` mit `PROJECT_ID` + Endpunkt) und AC 5 (digest-/wertgleiche Bindung)
schliessen.

Zweitens `cp10.py:352-365`: `_conformance_gate` leitet die Probe **neu ab**
(`server_command_from_mcp_entry(entry)`) und baut danach ein **anderes** Objekt
mit einem zusaetzlich gesetzten `cwd`:

```python
cmd: McpServerCommand = server_command_from_mcp_entry(entry)
bound = McpServerCommand(command=cmd.command, args=cmd.args, env=cmd.env, cwd=cwd)
```

Der **geprobte** und der **geschriebene** Spec unterscheiden sich damit
nachweisbar im `cwd`. Das ist das „getrennt konstruierte Pruefkommando", das
Scope-Punkt 1 verbietet.

`McpServerSpec` (`runtime_binding.py:70-95`) ist der vorgesehene SSOT und traegt
im Docstring bereits „consumed UNCHANGED by AG3-175". `McpServerCommand`
(`mcp_conformance/types.py:92-98`) ist die Probe-Schnittstelle. Die Bruecke
`McpServerSpec -> McpServerCommand` muss **verlustfrei und einmalig** sein.

---

## 2. Befund B — SSOT-Kollision: es gibt bereits einen `.codex/config.toml`-Writer

Das steht **nicht** in der Story. Es ist der wichtigste Fund.

`src/agentkit/backend/installer/codex_settings.py` schreibt die Datei heute als
**festen Ganzdatei-String**:

- `build_codex_config_toml()` (Zeile 22-29) liefert genau drei Zeilen: einen
  Kommentar plus `[hooks.pre_tool_use] command = "agentkit-hook-codex"`.
- `write_codex_settings()` (Zeile 32-44) entscheidet die Neuschreibung per
  **Byte-Vergleich**: `config_path.read_text(...) == content`.

Daraus folgen zwei harte Kopplungen:

1. **Zerstoerung der Registrierung.** Merged AG3-175 eine Tabelle
   `[mcp_servers.story-knowledge-base]` in dieselbe Datei, ist der Byte-Vergleich
   in `write_codex_settings` ungleich — ein spaeterer Installationslauf
   **ueberschreibt die Datei** und loescht die MCP-Registrierung. Damit waere
   AC 1 („idempotent") im echten Mehrlauf-Betrieb falsch, obwohl ein
   Einzeltest gruen ist.
2. **Detach klassifiziert falsch.** `lifecycle/detach.py:341-360`
   (`_remove_ak3_codex_config`) entfernt die Datei **nur wenn sie byte-gleich**
   `build_codex_config_toml()` ist; alles andere gilt als **fremd** und wird
   bewusst erhalten (FK-10 §10.2.9). Mit einer eingemergten MCP-Tabelle bleibt
   also eine **von AK3 selbst geschriebene** Registrierung nach dem Detach
   liegen, und `.codex/` bleibt nicht-leer, sodass auch das
   Verzeichnis-Cleanup (`_remove_empty_dir`) nicht greift.
   Belegt durch `tests/integration/installer/test_detach.py:631` (byte-gleich ->
   entfernt) und `:644-658` (fremd -> erhalten).

### Scope-Entscheidung des Orchestrators (verbindlich)

Die Story verlangt ausdruecklich „**Ein** Codex-TOML-Writer im Harness-Adapter"
und nennt SINGLE SOURCE OF TRUTH als Guardrail-Referenz. Ein zweiter Writer
neben `codex_settings.py` ist damit ausgeschlossen.

**In Scope, verbindlich:**

- **Konsolidierung:** Es gibt danach **genau einen** semantischen
  `.codex/config.toml`-Writer. Der bestehende Hook-Eintrag
  (`[hooks.pre_tool_use]`) wird ueber **denselben** Writer erzeugt, nicht mehr
  ueber einen konkurrierenden Ganzdatei-String.
- **Die zwei gekoppelten Aufrufstellen ziehen mit:** Install-Idempotenz
  (`write_codex_settings`) und Detach-Klassifikation
  (`_remove_ak3_codex_config`) duerfen nicht mehr auf **Byte-Gleichheit mit
  einem Fixstring** beruhen, sondern auf **semantischer AK3-Ownership** (welche
  Tabellen/Keys gehoeren AK3, welche sind fremd). Fremde Inhalte bleiben
  weiterhin erhalten und werden weiterhin als `preserved_foreign_files`
  gemeldet — diese Zusicherung ist **nicht** zu schwaechen.

**Begruendung:** Die Konsolidierung ist der ausdruecklich beauftragte Teil; die
zwei Aufrufstellen sind **notwendige Korrektheitsfolge** derselben Aenderung.
Sie stehen zu lassen hiesse, einen halbfertigen Architekturuebergang zu
liefern, in dem alte und neue Semantik parallel herumgetragen werden — genau
das verbietet ZERO DEBT. Es ist keine Scope-Ausweitung um neue Faehigkeiten:
an Detach wird **ausschliesslich das Klassifikationspraedikat** angepasst, kein
neues Verhalten.

**Nicht in Scope:** irgendeine weitere Detach-/Lifecycle-Funktionalitaet,
Migration bestehender Zielprojekte, Aenderungen an der Claude-Code-Hook-Kette.

**Nachweispflicht:** Ein Test, der **zwei aufeinanderfolgende
Installationslaeufe** fahrt und beweist, dass die MCP-Registrierung den zweiten
Lauf ueberlebt. Und ein Test, der beweist, dass Detach eine Datei mit
AK3-Hook + AK3-MCP-Tabelle **aufraeumt**, eine mit zusaetzlicher fremder
Tabelle dagegen **erhaelt**.

---

## 3. Befund C — die Konfigurationsquelle fuer `env` fehlt heute

`McpServerSpec` braucht `PROJECT_ID`, `WEAVIATE_HTTP_ENDPOINT`,
`WEAVIATE_GRPC_ENDPOINT` als vollstaendige Werte. Der Ist-Zustand liefert das
nicht:

- `src/agentkit/backend/config/models.py:531-549` (`VectorDbConfig`) traegt nur
  `host: str | None` und `port: int | None` — **kein gRPC-Port**, keine
  vollstaendigen Endpunkte.
- `PROJECT_ID` hat dagegen bereits einen SSOT-Resolver:
  `vectordb/project_binding.py:resolve_authoritative_project_id` (project.yaml
  `project_prefix` ist Autoritaet, `PROJECT_ID`-Env ist Fallback, Divergenz =
  harter Fehler, D2). **Diesen wiederverwenden, keinen zweiten bauen.**
- `vectordb/wait_for_weaviate.py:36-39` haelt `DEFAULT_HOST`/`DEFAULT_PORT`.
  Diese Defaults sind fuer AG3-175 **kein** zulaessiger Bezug: D2 verbietet
  synthetisierte Endpunkte, und `runtime_binding._reject_localhost`
  (Zeile 55-67) lehnt genau `http://localhost:8080`, `http://127.0.0.1:8080`,
  `localhost:50051`, `127.0.0.1:50051` ab.

**Aufgabe:** Entscheide und begruende, wo die zwei Endpunkte typisiert
herkommen. Zulaessig ist die **Erweiterung des bestehenden Fachmodells**
(`VectorDbConfig`) um die noetigen typisierten Felder. **Nicht** zulaessig ist
eine zweite Konfigurationsquelle, eine Hilfsdatei, ein Env-Direktzugriff im
Checkpoint oder ein synthetisierter Default. Fehlt die Konfiguration, ist das
ein **benannter FAILED-Checkpoint ohne Write**, kein Rateweg.

**Beobachtung, kein Auftrag:** Die Sperrliste enthaelt `localhost:50051` und
`127.0.0.1:50051`, waehrend FK-13 den lokalen gRPC-Port `:50051` nennt. Ein
lokaler Betrieb muss den Host also anders schreiben. Das ist ratifizierte
D2-Semantik aus AG3-174 und hier **nicht** neu aufzurollen — nur nicht
versehentlich als Bug „reparieren".

---

## 4. Befund D — TOML schreiben braucht eine Werkzeugentscheidung

Gemessen: `tomllib` ist Stdlib (3.11) und **liest** nur. Es ist **kein**
TOML-Writer installiert (`pip list | grep -i toml` ist leer), und
`pyproject.toml` fuehrt keinen.

Der Optionsraum, jede Option mit einer echten Konsequenz:

| Option | Erhalt | Kosten |
|---|---|---|
| `tomli-w` | Werte ja, **Kommentare/Formatierung nein** | kleine neue Runtime-Dependency |
| `tomlkit` | Werte, Kommentare, Formatierung (Round-Trip) | groessere Dependency, reichere API |
| Eigener Emitter | nach Bauart | eigener Code an einem fail-closed-Pfad; hohe Testlast |

AC 7 fordert Erhalt fremder Inhalte „**semantisch wertgleich**" — Kommentare
sind streng genommen kein Wert. Aber: die **AK3-eigene** Datei traegt heute
einen Kommentar (`codex_settings.py:26`), und ein Zielprojekt kann fremde
Codex-Konfiguration kommentiert pflegen. Ein kommentarvernichtender Writer
veraendert also fremdes Eigentum in einer Weise, die ein Nutzer als Datenverlust
erlebt.

**Entscheide begruendet und dokumentiere die Entscheidung in `impl-plan.md`.**
Eine neue Runtime-Dependency in `pyproject.toml` ist zulaessig, muss aber im
Plan **explizit ausgewiesen** werden (Name, Version-Pin, Lizenz) — der PO hat
bei AG3-174 (D5) auf exakte Pins bestanden; dieselbe Erwartung gilt hier.

---

## 5. Testumgebung — gemessene Fakten, die dich sonst in die Irre fuehren

- `pyproject.toml` hat `addopts = "-n 4 --dist loadfile"` und **kein `--cov`**.
  Ein blankes `pytest` misst **keine** Coverage. Wer „Coverage haelt 85 %"
  behauptet, muss `--cov` explizit gefahren haben. Ein `coverage report` ohne
  vorherigen `--cov`-Lauf liest eine **veraltete** `.coverage` — genau so sind in
  AG3-174 ueber mehrere Runden bedeutungslose Zahlen entstanden.
- `pytest-randomly` ist aktiv: Reihenfolgeabhaengigkeiten fallen zufaellig auf.
  Bei einem Verdacht den Seed festnageln und die Reproduktion belegen.
- Alle Python-Aufrufe **nur** ueber `.venv\Scripts\python -m ...`. AK3 und AK2
  teilen den Paketnamen `agentkit`; ein globaler Install zerstoert AK2.

---

## 6. Was „fertig" bedeutet

Zusaetzlich zur Definition of Done der Story:

1. **Kein „done" ohne Beleg.** Fuer jedes AC: der konkrete Test (Pfad +
   Testname) und der tatsaechliche Lauf-Output. Keine Zusammenfassung ohne
   Ausgabe.
2. **Revert-Probe fuer jede Zusicherung, die eine Negativaussage macht** (AC 3,
   4, 5, 6, 7): Der Test muss beim Zurueckdrehen des Fixes **rot** werden. Ein
   Test, der auch ohne die Produktionsaenderung gruen ist, belegt nichts. Wenn
   du eine Revert-Probe nicht durchfuehren kannst, sag das — behaupte sie nicht.
3. **Keine Mocks/Stubs** ausser im engen Ausnahmefall aus CLAUDE.md. Die
   Zwei-Dateien-Fehlersemantik (AC 6) braucht einen **simulierten I/O-Fehler** —
   das ist ein zulaessiger, weil sonst unerreichbarer Negativpfad; halte ihn
   minimal und begruende ihn im Bericht.
4. **Englisch** fuer Code, Bezeichner, Wire-/TOML-/JSON-Keys, Fehlernamen,
   Kommentare (ARCH-55). Berichte/Plaene duerfen deutsch sein.
5. **Stoppen statt splitten.** Findest du ein Problem ausserhalb dieses
   Briefings und der Story: melden, nicht eigenmaechtig ausweiten und nicht
   still weglassen.
