# Implementierungsreview 7 — AG3-164

## Auflösung der Befunde aus Review 6

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — vollständige MCP-Schemavalidierung | **teilweise geschlossen** | Die Produktion nutzt jetzt direkt `mcp.types.InitializeResult` und `ListToolsResult`; die vier vorgegebenen echten Subprozessangriffe (`instructions`, `nextCursor`, `description`, `outputSchema` jeweils falsch typisiert) enden korrekt in `mcp_protocol_error`. Es gibt keinen optionalen Import oder weichen Fallback. Die Modelle werden jedoch im nicht-strikten Pydantic-Modus aufgerufen und koerzieren weitere schemawidrige Werte (neues P0-1). |
| P1-1 — kombinierte Setup-/Resume-/Close-Fehler | **teilweise geschlossen** | Assign plus Job-Close wird gemeinsam bis zum öffentlichen Resultat getragen; Resume- sowie Thread-/Snapshot-Close-Fehler werden vor dem Raise aggregiert. Im Teardown geht ein gleichzeitiger Job-Close-Fehler neben einem Terminate-Fehler weiterhin verloren (neues P1-1). |
| P1-2 — Cleanup-Budget nach langsamem Popen | **geschlossen** | `_start_windows()` bewahrt vor dem Launch die gewünschte Cleanup-Spanne und setzt daraus unmittelbar nach erfolgreicher `Popen`-Rückkehr eine neue absolute Deadline. Der reale Slow-Popen-/Assign-Fail-Test weist einen positiven Wait-Budgetwert und geräumten Supervisor-State nach. Der erfolgreiche Start rearmt anschließend unverändert das volle Handshake-/Teardown-Budget. |
| P1-3 — AG3-172 nur einseitig verdrahtet | **geschlossen** | `AG3-164/status.yaml` trägt nun autoritativ `depends_on: ["AG3-172"]`; `unblocks` enthält außerdem die bekannten Downstream-Stories AG3-168 und AG3-171. |
| P2-1 — Coverage-Nachweis | **geschlossen** | Die geänderte Oberfläche erreicht nach dem vorgelegten modulspezifischen Lauf 86 % (`types` 100, `transport` 88, `check` 88, `protocol` 85, `process` 84) und überschreitet damit auch lokal die 85-%-Schwelle. |

## Schema- und Dependency-Prüfung

Die vier verlangten echten Gegenproben ergaben:

| Gegenprobe | Ergebnis |
|---|---|
| `InitializeResult.instructions: 7` | `False / mcp_protocol_error` |
| `ListToolsResult.nextCursor: 7` | `False / mcp_protocol_error` |
| `Tool.description: 7` | `False / mcp_protocol_error` |
| `Tool.outputSchema: 7` | `False / mcp_protocol_error` |

Weitere echte Subprozessproben zeigen, dass falsch typisierte Icons und
`execution.taskSupport`, fehlende oder leere `serverInfo.name/version` sowie
mehrere weitere grobe Schemafehler verworfen werden. Unbekannte Extension-
Keys auf Result-, Capability-, ServerInfo-, Tool- und InputSchema-Ebene bleiben
hingegen erlaubt; AK3 ist dort nicht überstreng geworden.

Der Importpfad ist hart: `protocol.py` importiert die SDK-Modelle direkt und
enthält keinen `try/except ImportError` oder Ersatzvalidator. Eine simulierte
fehlende `mcp`-Installation führte zu `ok=False/mcp_protocol_error`, niemals
zu einem Durchwinken. `mcp` ist jetzt korrekt unter `[project.dependencies]`
statt nur im Dev-Extra geführt.

Der installierte Stand (`mcp 1.27.2`) ist mit dem übrigen Environment
auflösbar; `pip check` meldet keine gebrochenen Anforderungen. Der Wechsel
zieht erwartbar unter anderem `anyio`, `httpx`, `jsonschema`,
`pydantic-settings`, `PyJWT`, `starlette`, `uvicorn`, `python-multipart` und
auf Windows `pywin32` in die Runtime. Das ist ein merklicher Footprint, aber
bei der ausdrücklich gewählten direkten SDK-Validierung keine unbeabsichtigte
Schattenabhängigkeit. Ein optionaler Types-only-Pfad existiert im SDK nicht.
Der Lower-Bound `mcp>=1.0` entspricht der sonstigen Dependency-Policy dieses
Repos; inkompatible SDK-Änderungen werden durch den harten Import und die
Contract-Tests fail-closed sichtbar. Daraus leite ich für diese Story keinen
zusätzlichen Blocker ab.

## Neue Findings

### P0-1 — Pydantic-Koerzierung erzeugt trotz offiziellem SDK erneut Falsch-Grün

**Ort:**
`src/agentkit/backend/installer/mcp_conformance/protocol.py:330-345,392-407`;
unzureichende Negativauswahl in
`tests/unit/installer/test_mcp_conformance.py:216-269` und
`tests/fixtures/mcp_bad_servers.py:174-188`.

`InitializeResult.model_validate(result)` und
`ListToolsResult.model_validate(result)` laufen mit Pydantics Default
`strict=False`. Der offizielle Typvertrag ist damit zwar die SSOT, wird aber
nicht als strikter Wire-Schemavertrag angewendet. Pydantic koerziert
insbesondere übliche String-/Integerdarstellungen zu Boolean.

Zwei echte Subprozessangriffe bestanden den vollständigen Handshake mit
`ok=True`:

| Schemafeld | Wire-Wert | SDK-Modell nach Default-Validierung |
|---|---|---|
| `capabilities.prompts.listChanged` | `"yes"` | `True` |
| `tools[0].annotations.readOnlyHint` | `"yes"` | `True` |

Das zugehörige `model_json_schema()` verwirft beide Werte korrekt als
nicht-boolean. Ebenso verwirft `model_validate(..., strict=True)` beide
Gegenproben. Die bisherigen Tests verwenden für `listChanged` den Wert `7`;
dieser liegt außerhalb Pydantics koerzierbarer Boolean-Menge und entdeckt den
Default deshalb nicht. Auch `0`, `1`, `"true"`, `"false"`, `"on"` und
`"off"` sind für Boolean-Felder zu prüfen.

**Fix:** Beide SDK-Aufrufe mit `strict=True` ausführen. Danach bleiben die
bereits vorhandenen AK3-Zusatzregeln (unterstützte Version, Tools-Capability,
nichtleere Liste/Namen) unverändert. Echte Subprozess-Negativtests müssen
mindestens einen koerzierbaren String und eine koerzierbare Zahl in
verschachtelten Capability- und Tool-Annotations-Booleanfeldern abweisen.
Der positive Extension-Key-Test und der offizielle SDK-Server müssen
weiterhin grün bleiben. Das schließt die Klasse systematisch, ohne eine zweite
Schemaquelle oder eine neue Abhängigkeit einzuführen.

### P1-1 — Terminate- und Job-Close-Fehler werden im Teardown noch nicht gemeinsam gemeldet

**Ort:**
`src/agentkit/backend/installer/mcp_conformance/process.py:290-350`.

`shutdown()` speichert einen Fehler aus `TerminateJobObject` als
`control_error`. Scheitert danach zusätzlich `_close_job_handle()`, wird der
zweite Fehler in Zeile 343–346 nur berücksichtigt, wenn noch kein primärer
Fehler existiert. Die öffentliche Gegenprobe mit gleichzeitig injiziertem
`ATTACK_TERMINATE_FAILED` und `ATTACK_CLOSE_FAILED` ergab:

```text
False mcp_process_control_error ... ATTACK_TERMINATE_FAILED
```

`ATTACK_CLOSE_FAILED` verschwand. Der Ausgang ist zwar fail-closed, aber ein
potenzieller Handle-Leak wird nicht vollständig benannt. Das ist dieselbe
Kombinationsregel, die für Assign/Resume gerade korrekt eingeführt wurde.

**Fix:** In `shutdown()` alle Control-/Close-Details sammeln oder beim zweiten
Fehler mit `merge_control_details()` aggregieren. Ein Boundary-Test muss im
öffentlichen Resultat sowohl Terminate- als auch Job-Close-Ursache nachweisen.

### P2-1 — SDK-Interop-Test beschreibt `mcp` noch als Dev-Abhängigkeit

**Ort:** `tests/integration/installer/test_mcp_conformance.py:43-49`.

Der Testtext sagt weiterhin, `mcp` sei eine deklarierte Dev-Abhängigkeit.
Nach Weg 1 ist es bewusst eine harte Runtime-Abhängigkeit. Das Verhalten des
Tests ist korrekt; nur Kommentar und Begründung sind veraltet.

**Fix:** Prosa auf „declared runtime dependency / hard contract oracle“
aktualisieren. Das ist redaktionell und kann zusammen mit dem Code-Rework ohne
eigene fachliche Review erledigt werden.

## Test- und Regressionsurteil

Mein fokussierter Lauf der neuen Schema-, Prozess- und Deadlinefälle sowie der
Integration/CP10-Verträge bestand mit `29 passed` plus `15 passed`. Die vom
Auftraggeber dreimal stabil gemeldeten `90 passed`, Ruff/Mypy und 86 %
modulspezifische Coverage sind substanzielle Belege. Die SDK-Umstellung hat
keine Importzyklen oder aufgelösten Dependency-Konflikte erzeugt. Die neue
Falsch-Grün-Stelle entsteht nicht durch einen Fallback, sondern durch die
Default-Semantik des nun korrekt gewählten SDK-Orakels.

AG3-172 bleibt unverändert ein externer, autoritativ verdrahteter
Landeblocker. Die Postgres-Race ist weder durch AG3-164 verursacht noch durch
dessen Code zu beheben.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Der reale CP10-/Installationspfad liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfüllt** | Alle gewünschten Server passieren das Gate vor dem einzigen atomaren Konfigurationswrite. |
| AC 3 — generisch für mindestens zwei Serverdefinitionen | **erfüllt** | Unterschiedliche Serverdefinitionen verwenden denselben serverunabhängigen Check. |
| AC 4 — kein Falsch-Grün | **nicht erfüllt** | Grobe und nicht koerzierbare SDK-Schemafehler werden abgewiesen; koerzierbare falsche Boolean-Werte in bekannten MCP-Feldern bestehen weiterhin (P0-1). |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller FastMCP-SDK-Server bestehen als echte Subprozesse. |
| AC 6 — Ressourcensauberkeit in allen Ausgängen | **teilweise erfüllt** | Prozessbaum- und Deadlineverträge einschließlich Slow-Popen-/Assign-Fail sind materiell geschlossen. Bei gleichzeitigem Terminate-/Close-Fehler wird der mögliche Handle-Leak aber nicht vollständig diagnostiziert (P1-1). |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt `SKIPPED/vectordb_disabled` ohne Probe und Write. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfüllt** | Die bestehenden CP10-Verträge bleiben materiell erhalten. |
| AC 9 — FK-50 und Konzeptgates | **erfüllt** | Deadline-, Register-only-, Ursachenkatalog- und Prozessklammervertrag stimmen nun mit FK-50 überein; AG3-172 ist ein separater Testinfrastrukturdefekt. |

## Gesamturteil

**Rework. AG3-164 ist in seinem eigenen Code noch nicht abnahmereif.** Nach
einer Landung von AG3-172 blieben P0-1 und P1-1 im MCP-Code bestehen.

### (a) Durch den Umsetzungsagenten zu beheben

- P0-1: beide SDK-Modelle strikt validieren und koerzierbare Boolean-Werte als
  echte Subprozess-Negativfälle ergänzen;
- P1-1: gleichzeitige Terminate-/Job-Close-Fehler im öffentlichen Detail
  aggregieren und testen;
- P2-1: veralteten Dependency-Kommentar korrigieren.

P0-1 ist ein echter Falsch-Grün-Pfad im zentralen Erfolgsbegriff. P1-1 ist ein
kleiner, aber realer Rest der bereits verlangten Ressourcen-/Fehleraggregation.
Beide Fixes sind lokal und klar bestimmt; sie sollten nicht als Grenzen
dokumentiert werden.

### (b) Durch den Orchestrator zu erledigen

- AG3-172 abschließen und damit die autoritative Landekante auflösen;
- anschließend vollständige CI-/Jenkins-/Sonar- und Konzept-Gate-Belege,
  Story-Bericht und Statusabschluss dokumentieren.

Da noch ein Falsch-Grün-Pfad im Produktionscode offen ist, sind derzeit nicht
nur Orchestrator-Schritte übrig; eine fokussierte fachliche Nachprüfung des
strikten SDK-Pfads ist erforderlich.
