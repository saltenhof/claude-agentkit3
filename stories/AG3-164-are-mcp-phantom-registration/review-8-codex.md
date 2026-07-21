# Implementierungsreview 8 — AG3-164

## Auflösung der Befunde aus Review 7

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — Pydantic-Koerzierung am MCP-Wire | **geschlossen** | `protocol.py:343-408` validiert `InitializeResult` und `ListToolsResult` jetzt mit `strict=True`. Echte Subprozessproben mit `"yes"`, `1`, `0`, `"true"`, `"on"` und `"off"` in `capabilities.prompts.listChanged` sowie `tools[].annotations.readOnlyHint` endeten ausnahmslos in `mcp_protocol_error`. |
| P1-1 — Terminate- und Job-Close-Fehler nicht gemeinsam sichtbar | **geschlossen** | `process.py:340-357` aggregiert beide Fehler mit `merge_control_details()` und propagiert den kombinierten `mcp_process_control_error`. Der öffentliche Boundary-Test `test_mcp_conformance.py:839-864` weist beide Ursachen nach; mein fokussierter Lauf war grün. |
| P2-1 — veralteter Dependency-Kommentar | **geschlossen** | `test_mcp_conformance.py:43-49` bezeichnet `mcp` korrekt als harte Runtime-Abhängigkeit und Contract-Oracle. Es gibt keinen Skip oder optionalen Produktionsfallback. |

## Abschlussprüfung der MCP-Wire-Grenze

Der von Review 7 beanstandete Wire-Pfad ist materiell geschlossen:

- Alle zwölf verlangten koerzierbaren Boolean-Gegenproben liefen als echte
  Subprozesse und wurden mit `False / mcp_protocol_error` abgewiesen.
- Der offizielle MCP-SDK-Server bestand als echter Subprozess. Ein zusätzlicher
  echter Server mit unbekannten Extension-Keys auf Result-, Capability-,
  `serverInfo`-, Tool- und JSON-Schema-Ebene blieb ebenfalls zulässig.
- `mcp.types` wird hart importiert; es existiert kein optionaler Import und kein
  weicher Ersatzvalidator.
- Der erneute Sweep über Transport, Envelope, JSON und Schema fand am MCP-Wire
  keine weitere Nachsicht: stdout wird strikt als UTF-8 dekodiert; Nicht-JSON-
  Konstanten, Zahlenüberlauf, doppelte Namen und isolierte Surrogates werden
  verworfen; Notification und Response werden disjunkt validiert; die
  SDK-Modelle laufen strikt. Das `errors="replace"` in `transport.py:192`
  betrifft ausschließlich begrenztes stderr-Diagnosetextmaterial und ist kein
  Protokoll- oder Entscheidungsinput.

Die strikte SDK-Umstellung hat damit nicht ins Gegenteil ausgeschlagen. Die
vom Auftraggeber dreimal stabil gemeldeten 95 Tests sowie die positiven
SDK-/Extension-Proben stützen die Interoperabilität.

## Neue Findings

### P0-1 — CP10 lädt und schreibt die externe `.mcp.json` weiterhin permissiv und meldet dabei falsch grün

**Ort:**
`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:188-195,291-298,482-497`;
fehlende Negativabdeckung neben
`tests/unit/installer/checkpoint_engine/test_cp10_mcp_conformance.py:290-321`.

Der verlangte systematische Sweep über *alle* externen Eingabegrenzen endet
nicht in `protocol.py`. CP10 liest die bereits vorhandene projektlokale
`.mcp.json` zweimal mit bloßem `json.loads()` und serialisiert mit dem ebenfalls
permissiven `json.dumps()`-Default. Dadurch gelten Python-Hilfen statt eines
fail-closed JSON-/Konfigurationsvertrags.

Vier echte REGISTER-Läufe mit einem wohlgeformten, konformen MCP-Subprozess
ergaben:

| vorhandene `.mcp.json` | tatsächlicher Ausgang |
|---|---|
| Fremdeintrag enthält `NaN` | `UPDATED`, kein Reason; CP10 schreibt das nicht RFC-konforme `NaN` erneut |
| zwei Top-Level-Namen `mcpServers` | `UPDATED`; der erste Fremdeintrag geht durch Last-wins-Parsing still verloren |
| Root ist `[]` | `UPDATED`; der vorhandene Root wird still durch den neuen MCP-Root ersetzt |
| `mcpServers` ist eine Zahl | `UPDATED`; der vorhandene Wert wird still ersetzt |

Damit kann der Installer trotz bestandener Server-Conformance Erfolg melden,
eine ungültige Zielkonfiguration erzeugen beziehungsweise vorhandene fremde
Konfiguration vernichten. Das verletzt FAIL-CLOSED sowie AC 8 (`Erhalt fremder
Einträge`) materiell. Der Parserpfad ist Vorbestand, wird aber vom in dieser
Story geänderten CP10-Registrierungspfad konsumiert und liegt innerhalb des
ausdrücklich zu erhaltenden Merge-Vertrags. Er kann deshalb nicht als externer
Altdefekt ausgeblendet werden.

**Konkreter Fix:**

1. Eine einzige strikte Loader-Funktion für die Ziel-`.mcp.json` einführen und
   sowohl in `cp10_mcp_registration()` als auch `_are_mcp_registered()` nutzen.
   Sie muss doppelte Namen auf jeder Ebene, `NaN`/`Infinity`/`-Infinity`, durch
   Zahlenüberlauf entstandene nicht-endliche Floats sowie einen Nicht-Objekt-
   Root ablehnen. Ein vorhandenes `mcpServers` muss ein Objekt sein; eine
   strukturell ungültige vorhandene Serverdefinition darf nicht still
   überschrieben werden.
2. Parse- und Shape-Fehler in REGISTER, DRY_RUN und VERIFY als benanntes
   `FAILED` ohne Mutation zurückgeben. Falls kein passender generischer
   Ursachencode existiert, `mcp_configuration_invalid` in Reasons und FK-50
   ergänzen; `mcp_protocol_error` sollte nicht still zu einem
   Dateikonfigurationsfehler umgedeutet werden.
3. Beim Schreiben `allow_nan=False` als Defense in Depth setzen. Die
   existierende Datei muss bei jedem Fehler byte-identisch bleiben.
4. Reale CP10-Negativtests für doppelte Namen (Top-Level und verschachtelt),
   Nicht-JSON-Konstanten, Nicht-Objekt-Root und falschen `mcpServers`-Typ
   ergänzen. Die Tests müssen `FAILED`, benannte Ursache, keinen
   Conformance-Start bei bereits ungültiger Konfiguration und unveränderte
   Bytes nachweisen. Ein Standards-strikter Parser muss jede erfolgreich
   geschriebene Datei lesen können.

Der Fix ist lokal und proportional. Dies als dokumentierbare Restgrenze zu
führen wäre nicht angemessen: Gerade das stille Verlieren fremder Einträge ist
ein Kerngegenbeispiel zum ausdrücklich regressionsgeschützten CP10-Merge.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Der reale CP10-Pfad liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite bei gescheiterter Conformance | **erfüllt** | Alle gewünschten Server passieren das Gate vor dem einzigen atomaren Write; ein Probe-Fehler lässt die Datei byte-identisch. |
| AC 3 — generischer Check für mindestens zwei Definitionen | **erfüllt** | Unterschiedliche Serverdefinitionen nutzen denselben serverunabhängigen Check. |
| AC 4 — Falsch-Grün ausgeschlossen | **nicht vollständig erfüllt** | Der MCP-Probevertrag selbst ist jetzt strikt und die geforderten Negativklassen scheitern. CP10 meldet jedoch bei ungültiger vorhandener `.mcp.json` weiterhin Erfolg und schreibt beziehungsweise verwirft Inhalt (neues P0-1). |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller SDK-Server bestehen `initialize` und `tools/list` als echte Subprozesse. |
| AC 6 — Ressourcensauberkeit | **erfüllt** | Prozessbaum-, Deadline- und kombinierte Cleanup-Fehlerpfade sind umgesetzt und getestet; aus Review 7 bleibt kein Ressourcenbefund offen. |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt ohne Probe und Write `SKIPPED`. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **nicht erfüllt** | Gültiger Fremdinhalt wird erhalten; doppelte Namen oder ein formal/strukturell ungültiger vorhandener Root werden dagegen still last-wins verarbeitet beziehungsweise ersetzt. |
| AC 9 — FK-50 und Konzept-Gates | **erfüllt für den Conformance-Vertrag** | Conformance, Ursachen und Prozesskontrolle sind normativ konsistent und die Gates sind grün. Falls für P0-1 ein neuer Konfigurations-Ursachencode eingeführt wird, muss die FK-50-Tabelle im selben Rework ergänzt werden. |

## Gesamturteil

**Nein — AG3-164 ist in seinem eigenen Code noch nicht abnahmereif. Urteil:
Rework.** Die Review-7-Befunde am MCP-Conformance-Code sind vollständig
geschlossen, und ich finde dort keinen verbleibenden Falsch-Grün-Pfad. P0-1
ist jedoch ein reproduzierbarer Falsch-Grün-/Datenverlustpfad im von AG3-164
geänderten CP10-End-to-End-Vertrag. Er ist klein genug, deterministisch zu
schließen, und keine vertretbare dokumentierte Grenze.

### (a) Durch den Umsetzungsagenten zu beheben

- P0-1: striktes, gemeinsames Laden und Shape-Validieren der Ziel-`.mcp.json`,
  fail-closed Ergebnis in allen Modi, `allow_nan=False` sowie die genannten
  Byte-Erhalt-/Negativtests.

Danach genügt eine fokussierte Nachprüfung dieses Loader-/Merge-Pfads; am
MCP-Wire-, SDK-, Prozess- oder Cleanup-Code fehlt nach dieser Runde nichts
mehr.

### (b) Durch den Orchestrator zu erledigen

- AG3-172 als externen Landeblocker abschließen;
- anschließend Status, Story-Bericht, vollständige CI-/Jenkins-/Sonar- und
  Coverage-Belege dokumentieren;
- die nichtautoritative `depends_on: []`-Prosa in `story.md` bei der
  Abschlussredaktion an das autoritative `status.yaml` (`AG3-172`) angleichen.

