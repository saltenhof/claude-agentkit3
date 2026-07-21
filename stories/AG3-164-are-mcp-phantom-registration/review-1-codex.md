# Implementierungsreview AG3-164

## Findings

### P0-1 — Ein syntaktisch passendes Pseudo-Protokoll besteht den Check als MCP

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:398-437`, `:440-463`; fehlende Negativfaelle in `tests/unit/installer/test_mcp_conformance.py`.

Die Response-Pruefung ist wesentlich schwaecher als der behauptete MCP-Erfolgsbegriff:

- `jsonrpc: "2.0"` wird in keiner Response verlangt.
- Beim `initialize` genuegt bereits die blosse Existenz **eines** Keys `protocolVersion` **oder** `serverInfo`; Typ, Inhalt, `capabilities`, `serverInfo.name/version`, Protokollkompatibilitaet und die fuer `tools/list` erforderliche `tools`-Capability werden nicht validiert.
- Bei `tools/list` werden aus beliebigen Listenelementen nur vorhandene String-Namen herausgefiltert. Ein Eintrag ohne `inputSchema`, mit leerem Namen oder neben weiteren kaputten Eintraegen gilt als wohlgeformt.

Ein adversarialer Read-only-Lauf hat damit einen Prozess, der Responses ohne `jsonrpc`, ohne `protocolVersion`, ohne `capabilities` und ein Tool ohne `inputSchema` liefert, als `McpConformanceResult(ok=True, tool_names=('x',))` akzeptiert. CP10 darf danach die Registrierung schreiben. Das ist der zentrale Falsch-Gruen-Pfad der Story.

Die bindende MCP-Version 2024-11-05 verlangt im Initialize-Ergebnis `protocolVersion`, `capabilities` und `serverInfo`; ein Tools-Server muss die Capability deklarieren, und eine Tooldefinition umfasst mindestens Identitaet und Eingabeschema ([MCP Lifecycle](https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle), [MCP Tools](https://modelcontextprotocol.io/specification/2024-11-05/server/tools)).

**Fix:** JSON-RPC-Envelope und MCP-Payload strikt typisieren und fail-closed validieren:

1. passende ID und exakt `jsonrpc == "2.0"`;
2. Initialize-Ergebnis mit nichtleerer, unterstuetzter `protocolVersion`, Objekt `capabilities` inklusive `tools`, sowie `serverInfo.name` und `serverInfo.version` als nichtleere Strings;
3. explizite Version-Negotiation: unbekannte Server-Version ist `mcp_protocol_error`, nicht still akzeptiert;
4. jedes Tool ist ein Objekt mit nichtleerem String `name` und Objekt `inputSchema`; **ein** ungueltiger Eintrag macht die gesamte Liste zum Protokollfehler;
5. `mcp_tools_list_empty` gilt nur fuer eine gueltige, tatsaechlich leere Liste.

Adversarial-Tests muessen fuer fehlendes/falsches `jsonrpc`, fehlende Initialize-Pflichtfelder, unbekannte Protokollversion, fehlende `tools`-Capability, leeren Toolnamen und fehlendes/falsches `inputSchema` jeweils rot werden. Ein Interoperabilitaetstest gegen einen Server des offiziellen MCP-Python-SDK verhindert ein gemeinsames Fehlverstaendnis von selbst geschriebenem Client und selbst geschriebenem Testserver.

### P0-2 — Der Timeout-Reader verliert gueltige Responses durch konkurrierende Reads

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:314-342`, insbesondere `_readline_with_timeout` `:466-490`.

Bei jedem 250-ms-Poll wird ein neuer Daemon-Thread gestartet, der auf derselben `TextIOWrapper`-Instanz `readline()` ausfuehrt. Laeuft der Poll ab, bleibt der alte Thread blockiert und der naechste Thread liest parallel. Trifft spaeter eine Response ein, kann ein alter Thread sie konsumieren; dessen lokaler `holder` wird vom Aufrufer nie mehr ausgewertet. Gleichzeitig aus mehreren Threads auf denselben Stream zu lesen ist nicht threadsicher und verliert Nachrichten.

Der Defekt ist reproduziert: Ein vollstaendig gueltiger Server, der lediglich 700 ms bis zur Initialize-Response benoetigt, endet in drei von drei Laeufen trotz eines 2-s-Gesamtbudgets mit `mcp_timeout`. Ein realer MCP-Server mit kaltem Import/Startup ist damit gerade im Normalfall gefaehrdet.

**Fix:** Genau **ein** langlebiger stdout-Reader pro Prozess. Er liest bis EOF und legt vollstaendige Zeilen in eine `queue.Queue`; der Handshake wartet mit dem verbleibenden Deadline-Budget auf der Queue. Keine Poll-Threads, keine parallelen Reads, keine verworfenen Holder. Analog stderr kontinuierlich und begrenzt drainieren. Teardown muss Reader nach geschlossenem/terminiertem Prozess deterministisch joinen. Tests: gueltige Responses nach 300 ms, 700 ms und knapp vor Deadline; mehrere Notifications vor der Response; Initialize und `tools/list` mit unterschiedlichen Verzögerungen.

### P0-3 — Harter Timeout und Ressourcensauberkeit sind nicht total

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:120-157`, `_drain_stderr` `:493-506`, `_terminate_process` `:509-530`; `tests/unit/installer/test_mcp_conformance.py:62-81` und `:111-137`.

Der versprochene harte Gesamt-Timeout umfasst den Prozessstart nicht: Die Deadline wird erst **nach** dem synchronen `Popen` in `_handshake` gesetzt. Ausserdem kann `_drain_stderr()` unbegrenzt auf EOF blockieren. Das tritt insbesondere auf, wenn der direkte Prozess endet, aber ein von ihm gestartetes Kind den geerbten stderr-Handle offen haelt. Damit kann gerade der `PROCESS_EXITED`-Fehlerpfad den Installer ohne Deadline blockieren.

Der Teardown terminiert nur den direkten Prozess. Auf POSIX wird kein eigener Prozess-Session-/Gruppen-Kontext erzeugt; das spaete `killpg(proc.pid, 9)` kann die nicht erzeugte Gruppe daher nicht verlaesslich treffen. Unter Windows gibt es ueberhaupt keinen Baum-Teardown. Ein Server, Wrapper oder Console-Script kann Kindprozesse hinterlassen. Die Tests suchen nur nach dem direkten Fixture-Kommando in Erfolg und Hang; sofortiger Tod, Protokollfehler, leere Toolliste, interne Exception und ein absichtlich erzeugter Enkelprozess werden nicht auf Restprozesse geprueft.

Auch die Shutdown-Reihenfolge ist unnoetig hart: Auf Erfolg wird sofort `terminate()` gesendet, statt zuerst stdin zu schliessen und dem MCP-Server den spezifizierten stdio-Shutdown zu erlauben ([MCP Lifecycle, Shutdown](https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle#shutdown)).

**Fix:**

- Eine monotone Deadline vor dem Launch festlegen und in **jedem** wartenden Schritt verwenden. Falls die Plattform keinen abbrechbaren `Popen` garantiert, diese Grenze ehrlich dokumentieren und den kontrollierbaren Handshake-/Shutdown-Anteil separat benennen; nicht „voller Probe-Timeout“ behaupten.
- stdout/stderr kontinuierlich ueber je einen Reader drainieren; niemals unbeschraenkt `read()` auf einer Pipe aufrufen.
- Auf Erfolg zuerst stdin schliessen, begrenzt auf freiwilligen Exit warten, dann terminate/kill eskalieren.
- Den gesamten Prozessbaum plattformneutral beseitigen, vorzugsweise ueber das bereits produktive `psutil` mit rekursiver Child-Erfassung und abschliessender Alive-Pruefung; alternativ POSIX-Session plus Windows-Job-Object.
- Fuer Erfolg, Timeout, sofortigen Tod, Protokollfehler, leere Toolliste und geworfene interne Exception jeweils denselben Ressourcen-Nachweis ausfuehren. Ein Fixture muss einen langlebigen Enkel erzeugen und dessen PID explizit als beendet beweisen.

### P0-4 — Dry-run/Verify fuehren nun beliebigen Zielprozess aus und brechen den bestehenden Modusvertrag

**Ort:** `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:182-184` vor der Mode-Verzweigung `:203`; `src/agentkit/backend/installer/checkpoint_engine/execution_mode.py:28-49`; `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:536-537`; abgeschwaechter Test `tests/unit/installer/checkpoint_engine/test_more_checkpoints.py:88-104`.

Der Conformance-Check laeuft vor jeder Pruefung von `mutations_allowed` und startet daher auch in `dry_run` und `verify` das konfigurierte Kommando. Ein Prozessstart ist keine side-effect-freie Vorschau: Das Programm kann beim Import, Start oder Initialize Dateien, Netzwerk oder Drittsysteme veraendern. Der vorhandene typisierte Modusvertrag garantiert fuer Dry-run und Verify Side-Effect-Freiheit; FK-50 §50.2 bezeichnet Dry-run als Vorschau und Verify als read-only. Die Implementierung hat diesen Vertrag nicht erhalten, sondern FK-50 nachtraeglich auf das neue Verhalten umformuliert. Der Decision Record entscheidet diesen Blast Radius nicht.

Der bestehende Test `test_cp10_dry_run_plan_contract_with_vectordb` wurde dabei nicht erhalten, sondern in einen erwarteten `FAILED`-Test umgeschrieben. Damit ist AC 8 („Dry-Run/Verify bleiben erhalten“) materiell nicht erfuellt.

**Fix:** Den startenden Conformance-Check ausschliesslich im mutierenden `REGISTER`-Pfad unmittelbar vor dem Write ausfuehren. Dry-run bleibt reine Planableitung. Verify prueft Konfigurationsshape und Soll/Ist-Differenz read-only; ein aktiver MCP-Healthcheck braucht einen eigenen, explizit autorisierten Betriebsvertrag und ist nicht nebenbei Bestandteil dieser Story. FK-50:536-537 entfernen/korrigieren und den alten Dry-run-Plan-Test wiederherstellen. Falls der PO einen aktiven Verify-Prozessstart will, ist das eine neue normative Entscheidung mit Formal-/Security-Impact, nicht eine Implementierungsinterpretation.

### P1-1 — Transportfehler koennen unklassifiziert aus CP10 herausfallen

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:286-295`, `:493-500`, `_safe_close_pipes` `:533-539`; `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:263`.

Der Katalog verspricht fuer jeden Conformance-Fehler ein strukturiertes `FAILED`. Tatsächlich fangen Schreib- und Drain-Pfade nur Teilmengen moeglicher Pipe-Fehler. Beispielsweise kann ein zwischen Poll und Write geschlossener Textstream `ValueError` liefern; `_conformance_gate` faengt unerwartete Transport-/Teardown-Ausnahmen gar nicht. Dann entsteht kein `CheckpointResult` mit einem der `mcp_*`-Gruende, sondern ein untypisierter Installer-Abbruch.

**Fix:** Transportoperationen an einer Boundary kapseln und alle erwartbaren Start-/Pipe-/Encoding-/Teardown-Fehler deterministisch in `mcp_process_exited` oder `mcp_protocol_error` abbilden. Unerwartete interne Fehler duerfen weiterhin hart fehlschlagen, muessen aber als benannter Conformance-Fehler mit gesicherter Prozessbereinigung am CP10-Rand ankommen. Negativtests fuer geschlossene stdin/stdout/stderr, Reader-Exception und Teardown-Exception ergaenzen.

### P1-2 — Tests bestaetigen die Eigenimplementierung, nicht ausreichend die MCP-Konformitaet und Regressionen

**Ort:** `tests/fixtures/minimal_mcp_server.py:1-80`, `tests/integration/installer/test_mcp_conformance.py:30-69`, `tests/unit/installer/test_mcp_conformance.py:97-137`, Aenderungen in `test_checkpoints.py:313-337` und `test_remediation_fixes.py:203-230`.

Der positive Test ist ein echter Subprozess und schreibt einen gueltigen Handshake; das ist besser als ein Mock. Er ist aber von Hand exakt gegen dieselben Annahmen wie der Produktionsparser gebaut. Deshalb entdeckt er weder die permissive Schema-Pruefung noch den Reader-Race. Ein unabhaengiger offizieller MCP-Server fehlt.

Die Ressourcenpruefung deckt nur Erfolg und einen direkten Hang ab. Ebenso fehlt ein erfolgreicher zweiter CP10-Lauf, der die Merge-Idempotenz **nach** Conformance als `PASS` belegt. Die CP10c-Tests erzeugen den angeblich vom Vorgaenger gelieferten `.mcp.json`-State nun direkt per `write_text`, statt einen conforming Testserver durch den realen CP10-Vorgaenger laufen zu lassen. Das schwaecht die vorhandene Pipeline-Grenze und widerspricht der Testregel, produktiven Vorgaenger-State nicht manuell zu erfinden.

**Fix:**

- mindestens ein Integrationstest gegen das offizielle MCP-Python-SDK;
- die adversarialen Wire-, Slow-Response- und Prozessbaum-Faelle aus P0-1 bis P0-3;
- CP10 zweimal mit einem conforming Server ausfuehren und beim zweiten Lauf `PASS`, byte-/semantisch unveraenderten Fremdinhalt und keine zusaetzliche Mutation beweisen;
- bei Conformance-Fehler eine bereits vorhandene `.mcp.json` byte-identisch erhalten;
- CP10c-Fixtures ueber einen tatsaechlich bestandenen CP10-Vorgaenger erzeugen oder die Unit-Grenze ueber einen typisierten, als solchen benannten Fixture-Builder abbilden, nicht durch ad-hoc Produktionsstate.

### P1-3 — Decision Record und Formal-Impact erfuellen die P3-Pflicht nicht

**Ort:** `concept/_meta/decisions/2026-07-20-mcp-conformance-registration-gate.md:70-78`; `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:502-540`; `concept/formal-spec/installer/invariants.md:81-86`.

Der Record endet mit einer siebenzeiligen Tabelle „Impact / Betroffenheit“. Sie ist weder der vorgeschriebene lexikalisch/semantische Impact-Sweep noch eine Betroffenheitsmatrix mit Klassifikation `geaendert` / `referenziert-jetzt` / `nicht-betroffen` und Begruendung. Insbesondere fehlen `reasons.py`, die geaenderten Tests, die Ausfuehrungsmodus-Semantik, Formal-Installer-Invarianten und der Prozess-/Trust-Boundary-Impact.

FK-50 behauptet ausserdem „wohlgeformtes MCP“ und totale Prozessbereinigung, die der Code nicht erfuellt, und normiert den aktiven Dry-run/Verify-Prozessstart trotz des bestehenden read-only/side-effect-free-Vertrags. Gruene Syntax-/Referenzgates koennen diese semantische Luecke nicht heilen.

**Fix:** Nach den Codekorrekturen einen echten P3-Impact-Sweep und eine vollstaendige Betroffenheitsmatrix in den Record aufnehmen. Dry-run/Verify, Formal-Installer, Security/Prozesslebenszyklus, Tests und Ursachenkatalog explizit klassifizieren. FK-50 erst dann auf das tatsaechlich implementierte, formal konsistente Verhalten ausrichten; W1, W4 sowie W2/W3 fuer `authority_over: installer` nachweislich ausfuehren.

### P1-4 — Der Probeprozess erbt unnoetig alle Installer-Secrets

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:179-184`.

`_build_env` kopiert das komplette `os.environ` und legt die MCP-Entry-Werte darueber. Der Conformance-Check startet damit ein ueber `PATH` aufgeloestes Zielkommando mit allen Credentials des Installerprozesses, in dieser Entwicklungsumgebung unter anderem CI-/Sonar-Zugaengen. Fuer die MCP-Konformitaet werden diese Secrets nicht benoetigt. Ein falsches oder kompromittiertes Binary auf einem frueheren PATH-Eintrag erhaelt sie bereits beim Preflight.

**Fix:** Einen dokumentierten Minimal-Environment-Vertrag festlegen: nur plattformnotwendige Startvariablen und die expliziten `entry.env`-Werte uebergeben; bekannte AK3-/CI-Credentials nie vererben. Auf Windows die benoetigten Systemvariablen explizit beruecksichtigen. Test mit gesetztem Sentinel-Secret: Der Server darf es nicht sehen, die explizite MCP-Umgebungsvariable dagegen schon.

### P2-1 — Ursachen-SSOT und Typisierung sind doppelt ausgebildet

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:41-64` gegen `src/agentkit/backend/installer/checkpoint_engine/reasons.py:35-42`; `McpConformanceResult.reason` `mcp_conformance.py:92-95`.

Die fuenf Reason-Strings existieren zweimal; der neue `McpConformanceReason` wird fuer das Resultat nicht verwendet, dessen `reason` weiterhin ein beliebiger `str` ist. Die Werte stimmen heute zufaellig ueberein, koennen aber ohne Test auseinanderlaufen.

**Fix:** Genau eine Quelle waehlen. Vorzugsweise importiert `mcp_conformance.py` die zentralen Checkpoint-Reasons aus `checkpoint_engine.reasons`, oder das Conformance-Modul besitzt den Enum und `reasons.py` projiziert daraus. `McpConformanceResult.reason` auf `McpConformanceReason | None` typisieren und erst am Checkpoint-Rand in den Wire-String projizieren. Ein Contract-Test bindet den FK-50-Katalog an diese SSOT.

### P2-2 — Relative Kommandos werden nicht relativ zum deklarierten `cwd` aufgeloest

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:120`, `_resolve_command` `:160-176`; CP10-Bindung `bootstrap_checkpoints/cp10.py:256-262`.

Der generische Vertrag fuehrt `cwd`, aber `_resolve_command` prueft `./server` oder `bin/server` gegen das aktuelle AK3-Arbeitsverzeichnis, bevor `Popen` spaeter mit dem Zielprojekt-`cwd` startet. Ein gueltiges projektlokales Kommando kann daher als `mcp_command_not_found` abgelehnt werden. Die aktuellen zwei Produktstanzas verwenden zwar bare Commands; fuer den als generisch deklarierten, spaeter von AG3-168 konsumierten Check bleibt der Vertrag unvollstaendig.

**Fix:** `_resolve_command(command, cwd=...)`; relative Pfade gegen das effektive `cwd` normalisieren und erst dann Startbarkeit pruefen. Windows-PATHEXT und POSIX-Executable-Bit getrennt testen.

## AC-Tabelle

| AC | Urteil | Begruendung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfuellt** | Der reale Full-Install-Test endet `success=False`; CP10 liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfuellt** | Alle gewuenschten Server werden vor `_write_mcp_json` geprueft; im frischen Fehlerfall entsteht keine Datei. Ein Regressionstest fuer byte-identischen Erhalt einer vorhandenen Datei fehlt, aendert aber den aktuellen Codebefund nicht. |
| AC 3 — generischer Check fuer mindestens zwei Definitionen | **erfuellt** | Der Check kennt nur Command/Args/Env/Cwd; ein Test laesst zwei unterschiedliche Definitionen real durch das Gate laufen. |
| AC 4 — drei Negativfaelle, kein Falsch-Gruen | **nicht erfuellt** | Kommando fehlt, sofortiger Tod, Noise und leere Liste sind getestet; ein strukturell ungueltiges Pseudo-MCP besteht jedoch nachweislich und kann die Registrierung freigeben (P0-1). |
| AC 5 — echter positiver MCP-Subprozess | **erfuellt** | Der minimale Server ist ein echter Kindprozess und liefert einen gueltigen Initialize-/Tools-Handshake. Ein unabhaengiger SDK-Interoperabilitaetsbeleg fehlt als Testhaertung, nicht als Negation dieses engen AC. |
| AC 6 — keine Restprozesse in allen Ausgaengen | **nicht erfuellt** | Nur direkter Erfolg und Hang sind geprueft; Prozessbaum, stderr-EOF, weitere Fehlerausgaenge und Reader-Threads sind nicht total bereinigt (P0-2/P0-3). |
| AC 7 — ARE=false bleibt SKIPPED | **erfuellt** | Bei beiden deaktivierten Features bleibt `SKIPPED/vectordb_disabled`; kein Write. |
| AC 8 — Merge-Idempotenz, Fremdinhalt, Dry-run/Verify erhalten | **nicht erfuellt** | Fremdinhalt wird erhalten. Der erfolgreiche Idempotenz-Re-Run fehlt, und der bestehende Dry-run-Planvertrag wurde zu einem aktiven Prozessstart mit erwartetem `FAILED` umgeschrieben (P0-4/P1-2). |
| AC 9 — FK-50 plus gruene Konzeptgates | **teilweise** | FK-50 enthaelt Gate und Katalog, behauptet aber strengere Semantik als der Code und fuehrt einen nicht gedeckten Dry-run/Verify-Vertrag ein; Record/Impact-Sweep sind unvollstaendig (P1-3). |

## Weitere Pruefergebnisse

- **CP10-Schreibreihenfolge:** Positiv. Im Registerpfad laufen alle gewuenschten Checks vor Merge/Write; ein erkannter Fehler hat keinen internen Teil-Schreibpfad. `_write_mcp_json` verwendet den vorhandenen atomaren Writer.
- **Fixtures:** `tests/fixtures/minimal_mcp_server.py` und `mcp_bad_servers.py` sind handgeschriebene, statische Testprogramme und damit am vorhandenen Ort korrekt. Das Verbot in `CLAUDE.md`/`PROJECT_STRUCTURE.md` betrifft generierte Dateien; im Verzeichnis existieren bereits vergleichbare Python-Fixtures. Kein Umzug erforderlich.
- **Architektur/ARCH-55:** Produktionscode liegt korrekt unter `src/agentkit/backend/installer/`; Bezeichner und Codekommentare sind englisch. Das neue Modul ist gross, bleibt aber fachlich auf Conformance konzentriert und ist fuer sich noch kein God-File.
- **Mocks:** Der Kern-Handshake laeuft gegen reale Subprozesse. Das Monkeypatching ersetzt die gewuenschte Serverdefinition, nicht den Conformance-Transport, und ist dafuer vertretbar.
- **Coverage:** Die gemeldeten 457 Tests, Ruff und Mypy sind wertvolle Basisbelege. Ein Coverage-Ergebnis >= 85 % sowie die Pflicht-Konzeptgates wurden fuer diesen Stand nicht als Evidenz vorgelegt; wegen der materiellen P0-Luecken waeren sie ohnehin noch kein Freigabebeleg.

## Gesamturteil

**Rework.** Die grundlegende CP10-Idee und die Write-before/after-Reihenfolge sind richtig umgesetzt; ein bloss aufloesbares Kommando reicht im normalen Codepfad nicht. Der eigentliche Erfolgsbegriff ist dennoch nicht belastbar: Strukturell ungueltiges Pseudo-MCP wird gruen, ein nur leicht verzögerter gueltiger Server wird durch konkurrierende Pipe-Reader rot, und Timeout/Prozessbaum-Bereinigung sind nicht total. Zusaetzlich wurde der bestehende Dry-run/Verify-Vertrag eigenmaechtig aufgeweicht.

Vor erneuter Abnahme muessen alle vier P0 geschlossen sein. Danach sind insbesondere ein offizieller MCP-SDK-Interoperabilitaetstest, vollstaendige Ressourcen-Negativtests, der echte Idempotenz-Re-Run sowie der korrigierte P3-/Formal-Impact erforderlich. In der aktuellen Form darf AG3-164 nicht auf `completed` gesetzt oder gelandet werden.
