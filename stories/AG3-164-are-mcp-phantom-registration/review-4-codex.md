# Implementierungsreview 4 — AG3-164

## Auflösung der Befunde aus Review 3

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — Wire-Validator akzeptiert ungültige Envelopes/UTF-8 | **teilweise geschlossen** | Die drei geforderten Gegenproben sind jetzt materiell rot: Notification mit `params: 7`, Response mit `"method": 123` und rohes ungültiges UTF-8 liefern jeweils `mcp_protocol_error`. Request, Response und Notification werden disjunkt klassifiziert; gültiges UTF-8 wird erst nach vollständiger Byte-Frame-Bildung strikt dekodiert. Ein weiterer echter JSON-Falsch-Grün-Pfad bleibt jedoch offen (neues P0-1). |
| P0-2 — Windows-Prozessklammer nicht atomar/fail-closed | **teilweise geschlossen** | Der Rootprozess wird nun `CREATE_SUSPENDED` erzeugt, erfolgreich dem Job zugewiesen und erst danach fortgesetzt. Der sofort aussteigende Parent mit langlebigem Enkel hinterließ in meinem Wiederholungslauf 25/25-mal keinen Restprozess; der 700-ms-Handshake bestand 5/5-mal. PID und Create-Time werden am selben `psutil.Process`-Objekt geprüft. Einzelne Win32-Cleanup-Ergebnisse werden aber noch verschluckt und ein Fehler-Wait liegt außerhalb der Deadline (P1-1/P1-2). |
| P1-1 — Job-Handle-Leak bei Launchfehler | **geschlossen** | `Popen`-Fehler schließen den vorab erzeugten Job in der Fehlerstrecke; `shutdown()` schließt ihn auch ohne `proc`. Der reale Wiederholungstest zeigt kein lineares Handle-Wachstum, und auch 30 erfolgreiche Probes stabilisieren sich nach einmaligem Thread-Runtime-Aufbau. |
| P1-2 — fehlende Tests der Transport-/Plattformgrenzen | **teilweise geschlossen** | Oversize-Frame, Queue-Overflow, ungültiges UTF-8, stderr-Tail, Job-Create/Assign-Fehler, Create-Time-Mismatch und erschöpfter Join besitzen Tests. Die Win32-Fakes sind eng auf nicht zuverlässig erzwingbare API-Fehler begrenzt; der normale Baumtest nutzt echte Subprozesse. Resume-/Terminate-/Close-Fehler sowie der tatsächliche Gesamtbudgetvertrag sind noch nicht bis zum öffentlichen Resultat verprobt. |
| P2-1 — großer stderr-Chunk verliert seinen Tail | **geschlossen** | Der bytebegrenzte Tailpuffer behält das Ende eines großen Einzel-Chunks; der 4-KiB-Grenztest beweist die Diagnose. |
| P2-2 — falscher `Popen`-Typ | **geschlossen** | Prozess und Pump-Grenzen verwenden jetzt konsistent `Popen[bytes]`; die früheren Typ-Ignores sind entfallen. Auch die Modulprosa ist englisch. |

## Neue Findings

### P0-1 — Nicht-JSON-Konstanten können den vollständigen MCP-Handshake weiterhin grün passieren

**Ort:** `src/agentkit/backend/installer/mcp_conformance/protocol.py:41-47`; fehlender Angriff in `tests/unit/installer/test_mcp_conformance.py:155-183`.

`json.loads()` akzeptiert in seiner Python-Standardeinstellung `NaN`, `Infinity` und `-Infinity`, obwohl diese Token nicht zur JSON-Grammatik und damit nicht zu JSON-RPC 2.0 gehören. Meine echte Subprozess-Gegenprobe lieferte `ok=True`, obwohl sowohl die Initialize-Response (`capabilities.x: NaN`) als auch das Tool-`inputSchema` (`const: NaN`) formal kein JSON waren. Damit bleibt AC 4 in exakt seiner zentralen Fehlerklasse offen.

**Fix:** `json.loads` mit einem `parse_constant`-Callback aufrufen, der jedes dieser Token verwirft, und den daraus entstehenden Parserfehler deterministisch auf `mcp_protocol_error` abbilden. Echte Subprozess-Grenztests für `NaN`, `Infinity` und `-Infinity` ergänzen; mindestens einer muss die ungültige Konstante in einem ansonsten akzeptierten `inputSchema` tragen.

### P1-1 — Win32-Cleanup ist noch nicht vollständig fail-closed

**Ort:** `src/agentkit/backend/installer/mcp_conformance/process.py:202-215,296-300,491-567`; Ergebnispriorisierung in `check.py:134-146`.

Die kontrollentscheidenden Aufrufe `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject` und `TerminateJobObject` werden nun geprüft. Nicht total ist jedoch die Cleanup-Grenze:

- `_close_job_handle()` unterdrückt einen von `_close_windows_job()` bereits korrekt erkannten `CloseHandle`-Fehler. Ein erfolgreicher Handshake kann deshalb trotz nicht geschlossenem Job-Handle grün zurückkehren.
- `CloseHandle` für Thread- und Snapshot-Handles wird in `_resume_suspended_process()` nicht ausgewertet; `ResumeThread == 0xFFFFFFFF` führt zwar am Ende fail-closed, verliert aber den konkreten Win32-Fehler.
- Scheitert die Prozesssteuerung während des Teardowns nach einem bereits feststehenden anderen Fehler, behält `check.py` den alten Grund. FK-50 verlangt bei nicht terminierbarer Klammer jedoch den benannten `mcp_process_control_error`.

**Fix:** Handle-Close-Fehler nach bestmöglichem Cleanup als `ProcessControlError` propagieren; keine pauschale Unterdrückung in `_close_job_handle`. Thread-/Snapshot-Handles in `finally` schließen und Rückgabefehler sammeln, ohne einen früheren Primärfehler zu verlieren. Ein Teardown-Control-Fehler muss das öffentliche Resultat auf `mcp_process_control_error` setzen. Enge Boundary-Fakes für Resume-, Terminate- und Close-Fehler bis zum öffentlichen `McpConformanceResult` ergänzen.

### P1-2 — Der deklarierte Deadline-/Teardown-Reserve-Vertrag gilt nicht für alle zulässigen Timeouts

**Ort:** `src/agentkit/backend/installer/mcp_conformance/check.py:64-72`, `process.py:202-210`; normative Aussage in `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:525-529`.

Für kleine positive `timeout_seconds` zieht die Reserveberechnung mindestens 0,5 Sekunden ab und verschiebt einen bereits abgelaufenen Handshake anschließend wieder um mindestens 0,1 Sekunden in die Zukunft. Damit kann `handshake_deadline` hinter `full_deadline` liegen. Reproduziert: `timeout_seconds=0.01` dauerte rund 0,186 Sekunden; ein Teil davon ist zwar der offen dokumentierte synchrone `Popen`, die Handshake-Frist selbst wurde aber nachweislich über das Gesamtbudget hinausgesetzt. Zusätzlich wartet die Resume-/Assign-Fehlerstrecke fest `timeout=1.0`, ohne das verbleibende Budget zu kennen.

**Fix:** Reserve ausschließlich als Anteil innerhalb des Gesamtbudgets berechnen und `handshake_deadline <= full_deadline` invariant halten; alternativ einen fachlich begründeten Mindestwert für `timeout_seconds` hart validieren. Die Windows-Startfehlerstrecke erhält ebenfalls die absolute Deadline und wartet höchstens deren Restbudget. Ein Wall-Clock-/Deadline-Test muss die kontrollierte Zeit nach Rückkehr aus `Popen` messen und die Invariante für sehr kleine, normale und Default-Timeouts beweisen.

## Norm-, Test- und Regressionsurteil

FK-50 weist die unvermeidbare Grenze des synchronen OS-`Popen` ausdrücklich aus; diese Korrektur ist auch im Decision Record und in der Paketdokumentation sichtbar und nicht stillschweigend erfolgt. Diese Grenze ist **dokumentierbar und für AG3-164 verhältnismäßig**. Ebenso ist PID+Create-Time als sekundäre, unmittelbar revalidierte Rückfallspur ausreichend, weil die atomare Job-Klammer der primäre Windows-Owner des Prozessbaums ist.

Nicht ehrlich erfüllt ist derzeit noch der stärkere Satz, dass sämtliche Handshake-/Tree-Waits im verbleibenden Budget liegen; P1-2 ist daher Code- und kein Dokumentationsproblem. Die aktuelle Hauptstrecke gegen echte Windows-Subprozesse ist dagegen belastbar. Die Boundary-Fakes sind schmal geblieben und ersetzen weder den echten Enkeltest noch den verpflichtenden offiziellen FastMCP-SDK-Subprozess. Mein gezielter Integrations-/CP10-Lauf bestand mit 15 Tests; der SDK-Test ist ein harter Import und kann sich in einer sauberen Dev-Umgebung nicht still überspringen.

Die drei geänderten Bestandstestdateien wurden nicht erneut abgeschwächt. Der frühere ARE-Erfolgstest erwartet nun sachgerecht den ehrlichen Fehler des noch fehlenden Servers; abhängige CP10c-Tests erzeugen ihren Vorgängerzustand über einen realen MCP-Subprozess statt durch handgeschriebenes Produktions-JSON. Dry-run/Verify, Merge-Idempotenz und Fremdeinträge bleiben erhalten.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Reale CP10-/Installationspfade liefern `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfüllt** | Alle gewünschten Server passieren das Gate vor dem einzigen atomaren Write; Fehlschläge lassen bestehende Bytes unverändert. |
| AC 3 — generisch für mindestens zwei Serverdefinitionen | **erfüllt** | Zwei unterschiedliche Definitionen laufen durch denselben servertyp-unabhängigen Check. |
| AC 4 — kein Falsch-Grün | **nicht erfüllt** | Die vorgelegten Wire-Angriffe sind geschlossen, aber formal ungültiges JSON mit `NaN` kann den vollständigen Handshake noch mit `ok=True` bestehen (P0-1). |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller FastMCP-SDK-Server bestehen als echte Subprozesse `initialize` und `tools/list`. |
| AC 6 — Ressourcensauberkeit in allen Ausgängen | **teilweise erfüllt** | Normale Erfolgs-, Timeout-, Exit- und schnelle-Enkelpfade sind sauber; seltene Resume-/Terminate-/Close-Fehler sind noch nicht vollständig propagiert bzw. deadlinegebunden (P1-1/P1-2). |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt `SKIPPED/vectordb_disabled` ohne Probe oder Write. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfüllt** | Die bestehenden Verträge und ihre Tests sind materiell erhalten. |
| AC 9 — FK-50 und Konzeptgates | **teilweise erfüllt** | Alle Konzeptgates sind grün und die Prozessstartgrenze ist ehrlich dokumentiert; die Implementierung unterschreitet noch den normierten Deadline-/Cleanup-Vertrag. |

## Gesamturteil

**Rework. AG3-164 darf noch nicht auf `completed` gesetzt oder gelandet werden.**

### (a) Durch den Umsetzungsagenten zu beheben

- P0-1: nicht standardkonforme JSON-Konstanten strikt ablehnen und per echtem Subprozess testen;
- P1-1: Win32-Resume-/Terminate-/Close-Fehler vollständig und benannt bis zum öffentlichen Resultat propagieren;
- P1-2: Deadlineinvariante und Startfehler-Waits korrigieren und mit Grenztests belegen.

Das sind Erfolgs- und Ressourcenverträge, keine redaktionellen Kleinigkeiten. P0-1 ist unmittelbar landungsblockierend; P1-1/P1-2 sind wegen AC 6, FK-50 und ZERO DEBT ebenfalls vor Abschluss zu schließen.

### (b) Danach ohne erneute fachliche Review durch den Orchestrator erledigbar

- `status.yaml` und Story-Bericht auf den tatsächlichen Abschlussstand bringen;
- vollständige Pflichtläufe einschließlich Coverage, Jenkins/Sonar und der für die normative Änderung erforderlichen W2-/W3-Belege dokumentieren.

Als benannte, akzeptable Restgrenze darf ausschließlich die bereits offen dokumentierte Nicht-Unterbrechbarkeit des synchronen OS-`Popen` verbleiben. Die aktuellen P1-Befunde sind dagegen klein genug und vertraglich relevant genug, dass sie nicht als bloße dokumentierbare Grenzen verschoben werden sollten.
