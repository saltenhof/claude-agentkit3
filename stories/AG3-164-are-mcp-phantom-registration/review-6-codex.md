# Implementierungsreview 6 — AG3-164

## Auflösung der Befunde aus Review 5

| Befund | Urteil | Begründung |
|---|---|---|
| P1-1 — MCP-Integrationstest unnötig an Postgres gebunden | **geschlossen** | `tests/integration/conftest.py:54-59` führt `test_mcp_conformance.py` nun ausdrücklich als Postgres-unabhängig. `pytest --fixtures-per-test` weist für alle drei Integrationstests keine `postgres_isolated_schema`-Fixture mehr aus; der Pfad nutzt ausschließlich echte MCP-Subprozesse, `tmp_path` und das In-Memory-Repository. |
| P1-2 — doppelte JSON-Namen und isolierte Surrogates | **teilweise geschlossen** | `object_pairs_hook` verwirft doppelte Namen rekursiv, einschließlich escaped Alias-Namen; isolierte hohe/niedrige Surrogates in Keys und Werten werden verworfen, ein gültiges Paar bleibt erlaubt. Die echte Subprozessprobe liefert jeweils `mcp_protocol_error`. Die JSON-/UTF-8-/Envelope-Schicht selbst hielt meinem erweiterten Angriff stand. Auf der darüberliegenden MCP-Payload-Schicht bleibt jedoch eine neue Falsch-Grün-Klasse offen (P0-1); die Wire-Grenze ist als Gesamtvertrag daher noch nicht geschlossen. |
| P1-3 — kombinierte Start-/Setup-/Close-Fehler | **teilweise geschlossen** | `Popen`-Fehler plus Job-Close-Fehler und `SetInformationJobObject` plus Close-Fehler werden jetzt als `mcp_process_control_error` gemeldet. Weitere kombinierte Setup-/Close-Pfade verlieren aber weiterhin einen der beiden Befunde (P1-1). |
| P1-4 — Popen verbraucht kontrolliertes Budget | **teilweise geschlossen** | Nach einem erfolgreichen `ProcessSupervisor.start()` werden Handshake- und Teardown-Budget korrekt neu auf `monotonic()` basiert; der Slow-Start-Test beweist das. Bei einem nach langsamem `Popen` eintretenden Assign-/Resume-Fehler verwendet der Supervisor dagegen weiterhin die vor `Popen` berechnete und dann bereits abgelaufene Cleanup-Deadline (P1-2). |

## Adversarialer Wire-Angriff

Die in Review 5 benannten Fälle sind materiell repariert. Zusätzlich habe ich
folgende Varianten geprüft:

- Duplicate-Key über Unicode-Escape (`id` und `\u0069d`) sowie verschachtelte
  Duplicates;
- isolierter niedriger Surrogate und Surrogate im Objektnamen;
- rohes Control-Zeichen, BOM, Trailing Garbage, Zahlenüberlauf;
- overlong UTF-8, CESU-8-Surrogate und abgeschnittene Multibyte-Sequenz;
- Batch-Envelope, `result` plus `error`, falsch typisierte Methode/Parameter,
  Float-/Null-ID und Server-Request während des Handshakes.

Diese Fälle werden jetzt fail-closed abgewiesen. Gültige Surrogate-Paare und
syntaktisch gültige, endliche JSON-Zahlen bleiben zu Recht erlaubt. Auf dieser
Syntax-/Envelope-Ebene habe ich **keine fünfte geerbte Parser-Nachsicht** mehr
gefunden.

Der systematische Angriff auf die vollständige Wire-Nachricht fand jedoch die
folgende, darüberliegende Variante.

## Neue Findings

### P0-1 — Der Check akzeptiert MCP-Payloads, die das offizielle SDK als schemawidrig verwirft

**Ort:**
`src/agentkit/backend/installer/mcp_conformance/protocol.py:314-413`;
Vertragsbegriff in
`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:518-524`;
fehlende Negativfälle in
`tests/unit/installer/test_mcp_conformance.py:155-233`.

Der JSON-RPC-Envelope ist inzwischen streng, die standardisierten MCP-Payloads
werden aber nur auf eine Auswahl von Pflichtfeldern geprüft. Ein realer
Subprozess bestand den vollständigen `initialize`-/`tools/list`-Handshake in
allen vier folgenden Fällen mit `ok=True`:

| Nachricht | Schemawidriges Feld | Ergebnis AK3 | Ergebnis `mcp.types` |
|---|---|---|---|
| `InitializeResult` | `instructions: 7` | akzeptiert | verworfen (`string_type`) |
| `ListToolsResult` | `nextCursor: 7` | akzeptiert | verworfen (`string_type`) |
| `Tool` | `description: 7` | akzeptiert | verworfen (`string_type`) |
| `Tool` | `outputSchema: 7` | akzeptiert | verworfen (`dict_type`) |

Das sind keine unbekannten Extension-Felder, sondern bekannte Felder des
MCP-Vertrags mit falschem Typ. Damit ist die Antwort nicht „wohlgeformt“,
obwohl CP10 sie als Conformance-Erfolg behandelt und anschließend
registrieren darf. Das ist derselbe zentrale Falsch-Grün-Typ wie die früheren
Pseudo-Protokollbefunde, nicht bloß zusätzliche Validierungs-Kür.

**Fix:** Die unterstützten `InitializeResult`- und `ListToolsResult`-/`Tool`-
Objekte vollständig gegen den offiziellen MCP-Typvertrag validieren; erst
danach die strengeren AK3-Regeln (unterstützte Version, Tools-Capability,
nichtleere Toolliste und nichtleere Namen) anwenden. Der bereits als harte
Dev-Abhängigkeit vorhandene offizielle SDK-Typvertrag soll als Contract-Orakel
für einen Negativkorpus dienen, damit nicht Feld für Feld nachgebessert wird.
Wenn die Produktionsvalidierung direkt dessen Modelle nutzt, muss `mcp` aus
`[project.optional-dependencies].dev` in eine tatsächlich installierte
Runtime-Abhängigkeit verschoben werden; ein optionaler Import mit weichem
Fallback wäre unzulässig. Alternativ braucht AK3 eigene vollständige,
versionsgebundene Modelle plus einen Paritätstest gegen `mcp.types`.

Mindestens die vier obigen Fälle sowie falsch typisierte verschachtelte
Capability-/Tool-Optionsfelder müssen als echte Subprozess-Negativfälle
`mcp_protocol_error` liefern. Unbekannte Extension-Keys dürfen entsprechend
dem SDK-Vertrag erhalten bleiben.

### P1-1 — Kombinierte Setup-/Close-Fehler sind noch nicht vollständig bis zur öffentlichen Diagnose gebunden

**Ort:**
`src/agentkit/backend/installer/mcp_conformance/process.py:223-246,588-632`;
öffentliche Projektion in
`src/agentkit/backend/installer/mcp_conformance/check.py:102-110`.

Bei Assign- oder Resume-Fehler wird ein zusätzlicher Job-Close-Fehler nur als
Exception-Cause an den primären `ProcessControlError` gehängt. Die öffentliche
Fassade projiziert ausschließlich `exc.detail`; der Close-Fehler verschwindet
damit aus der maschinenlesbaren Fehlerdiagnose. Meine kombinierte
Gegenprobe ergab:

```text
False mcp_process_control_error ... ATTACK_ASSIGN_FAILED
```

`ATTACK_CLOSE_FAILED` war im öffentlichen Resultat nicht mehr enthalten.
Dasselbe Muster besteht innerhalb `_resume_suspended_process()`: Liegen
gleichzeitig Resume- und Thread-/Snapshot-Close-Fehler vor, wird wegen der
frühen `resume_errors`-Verzweigung nur die erste Fehlerklasse gemeldet. Ein
tatsächlich fehlgeschlagener `CloseHandle` kann einen Handle-Leak bedeuten;
er darf nicht nur in einer intern nicht ausgegebenen Exception-Kette stehen.

**Fix:** Primär- und Cleanup-Fehler deterministisch in einem neuen
`ProcessControlError.detail` aggregieren und diesen bis zum öffentlichen
`mcp_process_control_error` tragen. Resume-, Thread-Close-, Snapshot-Close-
und Job-Close-Probleme erst vollständig sammeln, dann gemeinsam ausgeben.
Ein öffentlicher Boundary-Test muss bei `assign/resume fails + close fails`
beide benannten Ursachen im Resultat nachweisen.

### P1-2 — Das Deadline-Rearming fehlt im langsamen Popen-Fehlerpfad

**Ort:**
`src/agentkit/backend/installer/mcp_conformance/check.py:74-116`,
`src/agentkit/backend/installer/mcp_conformance/process.py:138-148,180-246`;
unzureichendes Orakel in
`tests/unit/installer/test_mcp_conformance.py:757-800`.

Der neue Test verzögert `ProcessSupervisor.start()` und beweist überzeugend,
dass **nach erfolgreicher Rückkehr** das volle Handshake-/Teardown-Budget neu
beginnt. Er prüft aber nicht den zweiten Ausgang: `Popen` kehrt nach langer
Zeit erfolgreich zurück, danach scheitert Job-Assign oder Resume. Für dessen
Kill/Wait/Cleanup erhält `_start_windows()` weiterhin das vor `Popen`
berechnete `launch_deadline`. Ist dieses abgelaufen, wird `proc.wait()` ganz
übersprungen. Das widerspricht der eigenen Docstring-Aussage, die separate
Launch-Cleanup-Frist erhalte Cleanup auch nach langsamem OS-Launch, und
unterschreitet FK-50s Ressourcenvertrag „in jedem Ausgang“.

**Fix:** Das Fehler-Cleanup-Budget unmittelbar nach erfolgreicher
`subprocess.Popen`-Rückkehr innerhalb des Supervisors neu auf die monotone Uhr
basieren. Erst danach Assign/Resume ausführen. Ein Test muss einen langsamen
echten Popen mit anschließendem Assign-/Resume-Fehler kombinieren und sowohl
das frische Restbudget als auch das Ausbleiben von Prozess-/Handle-Resten
beweisen. Das erfolgreiche Re-Arming in `check.py` bleibt zusätzlich bestehen.

### P1-3 — Der externe Landeblocker ist nur einseitig, nicht autoritativ verdrahtet

**Ort:**
`stories/AG3-164-are-mcp-phantom-registration/status.yaml:20-21` und
`stories/AG3-172-postgres-schema-xdist-race/status.yaml:25-29`.

AG3-172 dokumentiert korrekt `unblocks: [AG3-164]`, während AG3-164 weiterhin
`depends_on: []` führt. Nach dem im Story-System verwendeten Vertrag ist
`depends_on` die autoritative Ausführungskante; `unblocks` ist lediglich die
Rückprojektion. Der Scheduler kann den externen Blocker daher nicht aus
AG3-164 selbst ableiten.

**Fix:** AG3-164 in `status.yaml` und Story-Metadaten autoritativ von AG3-172
abhängig machen. Das ist reine Orchestrator-/Metadatenarbeit und kein Defekt
des MCP-Produktionscodes.

### P2-1 — Der vorhandene Coverage-Datensatz belegt das globale Gate, aber nicht eine ≥85%-Abdeckung der neuen Oberfläche

**Ort:** repo-lokale `.coverage`; kein Coverage-Bericht im
AG3-164-Storyordner.

Ein Coverage-Datensatz ist vorhanden, ein nachvollziehbarer Story-Bericht mit
Befehl und Ergebnis jedoch nicht. Ausgelesen ergibt er **92 % repo-weit** und
erfüllt damit das normative globale `fail_under = 85`. Für die geänderte
Installer-/Conformance-Oberfläche ergibt derselbe Datensatz dagegen zusammen
**83 %** (`1124` Statements, `187` nicht getroffen); insbesondere
`check.py` 83 %, `process.py` 75 %, `protocol.py` 84 % und `transport.py`
88 %. Der gezielte MCP-Lauf selbst ist mit `75 passed` stabil und substanziell,
aber die globale Zahl verdeckt gerade die noch offenen Kombinations- und
Payloadpfade.

**Empfehlung:** Nach den Codefixes einen frischen Coverage-Lauf mit
dokumentiertem Befehl ausführen und sowohl das globale ≥85%-Gate als auch die
geänderten Module ausweisen. Eine neue modulbezogene 85%-Norm ist daraus nicht
rückwirkend abzuleiten; die lokale Unterdeckung ist hier aber ein sinnvoller
Risikohinweis und korreliert mit P0-1/P1-1/P1-2.

## Abgrenzung zu AG3-172

Die erneut beobachtete `could not open relation with OID`-Race bleibt nach
meinem Review-5-Nachweis ein Vorbestandsdefekt des Postgres-Schema-/Testpfads.
Die neue AG3-164-Integration zieht die Postgres-Fixture nicht mehr und ist
nicht Ursache. AG3-172 ist daher der richtige separate technische Owner und
bleibt ein externer Landeblocker. Die Ausgliederung ändert nichts an den oben
gefundenen Eigenbefunden von AG3-164.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Der reale CP10-/Installationspfad liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfüllt** | Alle gewünschten Server passieren das Gate vor dem einzigen atomaren Konfigurationswrite. |
| AC 3 — generisch für mindestens zwei Serverdefinitionen | **erfüllt** | Unterschiedliche Serverdefinitionen nutzen denselben serverunabhängigen Check. |
| AC 4 — kein Falsch-Grün | **nicht erfüllt** | JSON, UTF-8 und JSON-RPC-Envelope sind nun belastbar; offiziell schemawidrige MCP-Result-/Tool-Felder passieren den vollständigen realen Handshake dennoch mit `ok=True` (P0-1). |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller FastMCP-SDK-Server bestehen als echte Subprozesse. |
| AC 6 — Ressourcensauberkeit in allen Ausgängen | **teilweise erfüllt** | Normale und bisherige adversariale Prozessbaumfälle sind sauber. Kombinierte Setup-/Close-Diagnosen und das Cleanup-Budget nach langsamem Popen sind noch nicht total (P1-1/P1-2). |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt `SKIPPED/vectordb_disabled` ohne Probe und Write. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfüllt** | Die fachlichen Bestandstests wurden nicht abgeschwächt; AG3-172 betrifft eine unabhängige Postgres-Race. |
| AC 9 — FK-50 und Konzeptgates | **teilweise erfüllt** | Norm und Code stimmen für den erfolgreichen Slow-Popen-Pfad überein; der Fehler-Cleanup-Pfad unterschreitet den Vertrag noch (P1-2). Die Konzeptgates waren im gemeldeten Stand grün. |

## Gesamturteil

**Rework. AG3-164 ist in seinem eigenen Code noch nicht abnahmereif.** Auch
nach einer Landung von AG3-172 wären P0-1, P1-1 und P1-2 im MCP-Code offen.

### (a) Durch den Umsetzungsagenten zu beheben

- P0-1: vollständige, versionsgebundene MCP-Payload-Validierung statt einer
  bloßen Pflichtfeld-Teilmenge; Parität gegen das offizielle SDK und echte
  Subprozess-Negativfälle;
- P1-1: kombinierte Setup-/Resume-/Close-Fehler gemeinsam bis zum öffentlichen
  Resultat tragen;
- P1-2: Cleanup-Budget unmittelbar nach langsamem `Popen` rearmen und den
  anschließenden Fehlerpfad mit Restfreiheit testen.

Diese Punkte betreffen den Kern von AC 4 und AC 6. Sie sind weder
redaktionelle Kleinigkeiten noch als Restgrenzen unverhältnismäßig.

### (b) Durch den Orchestrator zu erledigen

- die autoritative `depends_on: [AG3-172]`-Kante nachziehen;
- AG3-172 vor der Landung tatsächlich abschließen;
- danach frischen Coverage-, vollständigen Test-, Jenkins-/Sonar- und
  Konzept-Gate-Nachweis dokumentieren sowie Status und Story-Bericht
  aktualisieren.

Da noch Produktionscode-Befunde bestehen, sind diese Abschlussarbeiten noch
nicht die einzigen verbleibenden Schritte; eine fachliche Nachprüfung nach dem
Rework ist erforderlich.
