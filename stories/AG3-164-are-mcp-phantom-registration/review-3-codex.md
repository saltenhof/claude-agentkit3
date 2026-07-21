# Implementierungsreview 3 — AG3-164

## Aufloesung der Befunde aus Review 2

| Befund | Urteil | Begruendung |
|---|---|---|
| P0-1 — verbleibende Protokoll-Falsch-Gruen-Pfade | **teilweise geschlossen** | Alle drei konkret geforderten Gegenproben sind jetzt rot: Garbage vor der Response, Boolean-ID und `capabilities.tools: null` liefern jeweils `mcp_protocol_error`. `protocol.py` ist wesentlich strenger und isoliert testbar. Weitere ungueltige Wire-Varianten werden jedoch weiterhin repariert bzw. ignoriert und enden mit `ok=True` (neues P0-1). |
| P0-2 — Prozessbaum-Supervisor nicht total/sicher | **teilweise geschlossen** | Der schnelle Python-Wrapper mit langlebigem Enkel hinterliess in 25 Wiederholungen keinen Restprozess. POSIX Process-Group und Windows Job Object sind der richtige Mechanismus; Identitaeten tragen PID und Create-Time. Total ist der Vertrag trotzdem nicht: Der Windows-Prozess laeuft vor der Job-Zuweisung, alle relevanten Win32-Rueckgabewerte werden ignoriert, PID/Create-Time wird mit unsicherem TOCTOU erneut aufgeloest und nicht jeder Wait ist deadlinegebunden (neues P0-2). |
| P1-1 — offizieller SDK-Test optional | **geschlossen** | `mcp>=1.0` ist eine deklarierte Dev-Abhaengigkeit (`pyproject.toml:39-43`); der Integrationstest importiert hart statt `importorskip` und startet real `FastMCP` als Subprozess. Der gemeinsame gezielte Lauf bestand. |
| P1-2 — Leak-Orakel unter xdist flaky | **geschlossen** | Jeder Fixture-Lauf traegt nun einen UUID-Token bis in den Enkelprozess; das Orakel sucht nur diesen Token. Der zuvor rote gezielte Standardlauf unter `-n 4 --dist loadfile` ist jetzt mit 41 Tests gruen. Keine globale Dateinamen-Kollision mehr. |
| P1-3 — Stream-Pumps nicht ressourcenbegrenzt | **teilweise geschlossen** | stdout besitzt Frame- und Queue-Limits, stderr ist drain-only mit begrenztem Ring. Ein eigener Angriff mit einer >256-KiB-Zeile endete korrekt in `mcp_protocol_error`. Fuer diese neuen Grenzen fehlen jedoch Regressionstests; ausserdem repariert stdout ungueltiges UTF-8 und der stderr-Ring verliert grosse Einzel-Chunks vollstaendig (P0-1/P1-2). |
| P1-4 — Konzept-Referenzgate rot | **geschlossen** | Frontmatter-, Referenz-, Decision-Record- und Formal-Gate wurden unabhaengig erneut ausgefuehrt und sind gruen; das Referenzgate meldet 0 Errors. Die frueheren Platzhalter-/Baselinefehler sind beseitigt. |
| P1-5 — 947-Zeilen-God-File | **geschlossen** | Der Schnitt in `types`, `protocol`, `transport`, `process` und `check` folgt echten Verantwortungen, nicht bloss Dateigroessen. Die oeffentliche Importoberflaeche bleibt kompatibel; es gibt keine Zirkularitaet oder doppelte Prozess-/Protokoll-Ownership. |

## Neue Findings

### P0-1 — Der Wire-Validator akzeptiert weiterhin ungueltiges JSON-RPC und ungueltiges UTF-8

**Ort:** `src/agentkit/backend/installer/mcp_conformance/protocol.py:60-96`, `transport.py:91-102`, `check.py:299-328`; fehlende E2E-Grenztests in `tests/unit/installer/test_mcp_conformance.py`.

Die drei vorgelegten Faelle sind sauber behoben. Der weitergehende Angriff zeigt aber noch mindestens drei echte Falsch-Gruen-Pfade:

1. `{"jsonrpc":"2.0","method":"notice","params":7}` wird als Notification ignoriert, obwohl JSON-RPC `params` — sofern vorhanden — als strukturierten Wert (Objekt oder Array) verlangt. Danach folgende gueltige Responses fuehren zu `ok=True`.
2. Eine Initialize-Response mit zusaetzlichem `"method": 123` wird als Response behandelt, weil `has_method` nur bei bereits korrektem String wahr wird. Ein vorhandenes, aber falsch typisiertes Standardmember wird dadurch semantisch unsichtbar.
3. Eine Response mit einem rohen ungueltigen UTF-8-Byte im `serverInfo.name` wird in `transport.py:101` per `errors="replace"` repariert und danach als gueltiges MCP akzeptiert.

Damit bleibt genau die zentrale Story-Fehlerklasse offen: Ein Prozess kann nicht wohlgeformtes MCP sprechen und dennoch die Registrierung freigeben.

**Fix:** JSON-RPC als disjunkte Envelope-Varianten validieren: Ein vorhandenes `method` muss String sein; Notification darf weder `id`, `result` noch `error` tragen und `params` muss bei Vorhandensein Objekt oder Array sein; Response braucht eine gueltige ID und exakt eines von `result`/`error`, aber kein `method`. UTF-8 strikt dekodieren; `UnicodeDecodeError` wird `mcp_protocol_error`, niemals U+FFFD-Reparatur. Fuer die drei Faelle sowie Notification mit `result` je einen echten Subprozess-Grenztest ergaenzen, nicht nur reine Validator-Tests.

### P0-2 — Die Windows-Prozessklammer ist noch fail-open und nicht atomar

**Ort:** `src/agentkit/backend/installer/mcp_conformance/process.py:107-142`, `:160-230`, `:263-349`; `check.py:114-122`; unvollstaendige Tests `tests/unit/installer/test_mcp_conformance.py:209-229`.

Der konkrete fruehere Enkel-Defekt ist im normalen Testtiming behoben. Die behauptete Totalitaet folgt aus dem Code dennoch nicht:

- `Popen` startet den Prozess normal; erst danach wird er dem Job zugewiesen (`process.py:131-137`). Ein schneller nativer Parent kann vor der Zuweisung Kinder erzeugen. Bereits erzeugte Kinder werden durch die spaetere Parent-Zuweisung nicht rueckwirkend Mitglieder des Jobs. Der Python-Fixture importiert erst Module und ist deshalb kein Beleg gegen dieses Race.
- `_create_windows_job`, `AssignProcessToJobObject`, `TerminateJobObject` und `CloseHandle` pruefen ihre Win32-Ergebnisse nicht vollstaendig bzw. gar nicht. Scheitert Erzeugung oder Zuweisung, degradiert der Code still auf Snapshot-Kill; genau dort kann ein reparentierter Enkel entkommen. Der Conformance-Check darf unter FAIL-CLOSED dann nicht weiterlaufen.
- Die ctypes-Signaturen (`argtypes`/`restype`) fuer Handles fehlen. Damit ist die 64-Bit-Handle-Grenze nicht belastbar ausgebildet.
- Die sekundare Identitaetspruefung nutzt eine Toleranz von 50 ms und erzeugt nach `identity_still_alive()` ein neues `psutil.Process`-Objekt, ohne dessen Create-Time unmittelbar vor `terminate()` erneut zu vergleichen (`:212-221`). Das oeffnet wieder einen PID-Reuse-TOCTOU-Pfad.
- Die Pump-Joins warten in `check.py:119-122` jeweils pauschal bis zu einer Sekunde; `_kill_tracked` erzwingt selbst bei abgelaufener Deadline mindestens 10 ms (`process.py:222-223`). Die FK-50-Aussage „Teardown-Waits an Deadline gebunden“ ist daher nicht wahr.

**Fix:** Unter Windows den Rootprozess suspendiert erzeugen, erfolgreich einem vorab konfigurierten Job zuweisen und erst danach fortsetzen; alternativ einen gleichwertig atomaren Job-at-creation-Vertrag verwenden. Jede Win32-Operation bekommt explizite ctypes-Signaturen und gepruefte Fehlerwerte. Kann die Job-Klammer nicht hergestellt oder terminiert werden, muss der Check mit einer benannten Prozesssteuerungsursache fail-closed enden. Alle Handles werden in `finally` geschlossen. Den tracked Fallback auf dasselbe, unmittelbar revalidierte `psutil.Process`-Objekt binden; keine 50-ms-Gleichsetzung fremder Identitaeten. Auch Pump-Joins und Minimal-Waits erhalten ausschliesslich das verbleibende monotone Budget; dafuer ist innerhalb des Gesamtbudgets ein Teardown-Anteil zu reservieren, statt den Handshake das komplette Budget verbrauchen zu lassen.

Tests: Job-Erzeugungs-/Zuweisungsfehler, sofortiger nativer Spawn vor normaler Parent-Arbeit, abgelaufene Deadline, Create-Time-Mismatch und nachweislich kein fremder Kill. Fuer nicht real erzwingbare Win32-Fehler ist ein eng begruendeter Boundary-Fake zulaessig; der normale Baumtest bleibt ein echter Subprozess.

### P1-1 — Prozessstartfehler lecken Windows-Job-Handles

**Ort:** `src/agentkit/backend/installer/mcp_conformance/process.py:128-132`, `:160-163`, `:197-200`.

Der Job wird vor `Popen` erzeugt. Scheitert `Popen`, bleibt `self.proc` `None`; `shutdown()` kehrt dann in Zeile 163 zurueck, bevor der Job-Handle geschlossen wird. Der Fehler ist reproduzierbar: 50 Aufrufe gegen eine vorhandene, aber nicht startbare Datei erhoehten im Probeprozess die Handlezahl von 155 auf 210, obwohl jeder Aufruf korrekt `mcp_command_not_found` meldete.

**Fix:** `ProcessSupervisor.start()` muss den Job bei jedem Launchfehler in einem lokalen `except/finally` schliessen und seinen Zustand zuruecksetzen. `shutdown()` darf Job-/sonstige Handles auch bei `proc is None` nicht ueberspringen. Regressionstest ueber `num_handles()` oder einen injizierbaren, zaehlenden Handle-Owner; nach wiederholtem Startfehler darf die Handlezahl nicht linear wachsen.

### P1-2 — Die neuen Transport- und Plattformgrenzen besitzen keine eigenen Fehlervertrags-Tests

**Ort:** `src/agentkit/backend/installer/mcp_conformance/transport.py:27-187`, `process.py:79-349`; `tests/unit/installer/test_mcp_conformance.py`.

Die sieben neuen Tests decken die drei bekannten Wire-Faelle, Token-Isolation und den schnellen Python-Enkel ab. Nicht getestet sind aber die eigentlichen neuen Mechanismen: Oversize-Frame, Pending-Queue-Overflow, striktes Encoding, stderr-Cap, Create-Time-Mismatch, Job-API-Fehler, Handle-Cleanup und deadlinegebundene Joins. Das verletzt die Repo-Regel „Bugfix braucht reproduzierenden Test“ und erlaubt, dass gerade die Reparaturmechanik unbemerkt wieder aufweicht.

**Fix:** Reine Tests fuer `protocol.py`, begrenzte Pump-Tests mit echten Byte-Streams sowie plattformspezifische Supervisor-Tests ergaenzen. Mindestens ein E2E-Subprozess muss jeden Transportfehler bis zum oeffentlichen `McpConformanceResult` und CP10-Write-Gate verfolgen.

### P2-1 — Der stderr-Ring verliert grosse Einzel-Chunks statt deren Tail zu behalten

**Ort:** `src/agentkit/backend/installer/mcp_conformance/transport.py:143-183`.

Bei einem 4096-Byte-stderr-Write wird der gesamte Chunk angehaengt und anschliessend wegen des 500-Byte-Limits komplett aus der `deque` entfernt. Der reproduzierte Fehler enthielt deshalb keinen stderr-Tail. Das beeintraechtigt nicht das Fail-Closed-Ergebnis, aber die verlangte klare Fehlerdiagnose.

**Fix:** Einen bytebegrenzten Tailpuffer verwenden, der bei grossen Chunks deren letzte `STDERR_DETAIL_CHARS` Bytes behaelt, statt nur ganze Chunks zu entfernen. Grenztest fuer einen einzelnen 4-KiB-Write und mehrere Chunks.

### P2-2 — Kleine Schnitt-/Guardrail-Nacharbeiten

**Ort:** `src/agentkit/backend/installer/mcp_conformance/check.py:1-4,91-93`, `process.py:101,131,323`.

Der Modulschnitt selbst ist richtig. Zwei Details sollten beim Rework mitbereinigt werden: Die deutsche Modulprosa „Fassade: bindet ...“ verletzt den verbindlichen ARCH-55-Code-/Kommentarvertrag; zudem sind die Prozesse trotz binaerer Pipes als `Popen[str]` typisiert und werden an den Pump-Grenzen mit `type: ignore` korrigiert. Das Modell ist `Popen[bytes]`, nicht ein dauerhaft erklaerter Ignore.

**Fix:** Modul-Docstring englisch formulieren und die Popen-/Win32-Typen korrekt auspraegen, sodass die beiden Pump-Ignores entfallen.

## Schnitt- und Normurteil

Der Fuenf-Modul-Schnitt ist **fachlich tragfaehig**:

- `protocol.py` ist reine A-Logik,
- `transport.py` besitzt Byteframing und Pumps,
- `process.py` besitzt Plattformprozess und Environment,
- `check.py` orchestriert den Use Case,
- `types.py` traegt die stabilen Vertrage.

Es ging keine oeffentliche API verloren; CP10 und bestehende Importe nutzen weiterhin das Paket-Root. Die verbleibenden Probleme sind Boundary-Implementierungsfehler, keine Folge einer mechanischen Zerlegung.

FK-50 wurde nicht auf eine Luecke abgeschwaecht, sondern beschreibt weiterhin das richtige Ziel: Job/Group, PID+Create-Time, sauberer Prozessbaum in jedem Ausgang und deadlinegebundene Waits. Der aktuelle Code erfuellt diese Aussagen jedoch noch nicht. Insbesondere fehlt ausserdem die in Review 1 akzeptierte ehrliche Dokumentation, dass der synchrone OS-`Popen`-Aufruf selbst nicht auf allen Plattformen abbrechbar ist. Diese Grenze ist in FK-50, Decision Record und Paketdokumentation wieder explizit auszuweisen; die Job-/Wait-Luecken sind dagegen im Code zu schliessen, nicht normativ wegzuformulieren.

## Akzeptanzkriterien

| AC | Urteil | Begruendung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfuellt** | Reale CP10-/Installationspfade liefern `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfuellt** | Alle gewuenschten Server passieren das Gate vor dem einzigen atomaren Write; Fehler erhalten bestehende Bytes. |
| AC 3 — generisch fuer mindestens zwei Serverdefinitionen | **erfuellt** | Check und CP10 sind servertypunabhaengig; zwei Definitionen laufen durch dieselbe Oberflaeche. |
| AC 4 — kein Falsch-Gruen | **nicht erfuellt** | Die drei bekannten Angriffe sind geschlossen, aber ungueltige JSON-RPC-Notification/Membertypen und ungueltiges UTF-8 bestehen weiterhin mit `ok=True` (P0-1). |
| AC 5 — realer positiver MCP-Subprozess | **erfuellt** | Minimalserver und verpflichtender offizieller FastMCP-SDK-Server bestehen real den Handshake. |
| AC 6 — Ressourcensauberkeit in allen Ausgaengen | **nicht erfuellt** | Der konkrete schnelle Enkel wird beseitigt, aber Job-Zuweisung/-Fehler ist fail-open und Startfehler lecken nachweislich Handles (P0-2/P1-1). |
| AC 7 — ARE=false bleibt SKIPPED | **erfuellt** | Feature-off bleibt `SKIPPED/vectordb_disabled` ohne Prozessstart oder Write. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfuellt** | Idempotenter Re-Run, Fremdeintraege und read-only Modi bleiben materiell erhalten. Die drei geaenderten Bestandstestdateien wurden nicht erneut abgeschwaecht; Dry-run ist in alter Semantik vorhanden und CP10c konsumiert echten Vorgaenger-State. |
| AC 9 — FK-50 und Konzeptgates | **teilweise erfuellt** | Alle mechanischen Konzeptgates sind gruen und der Record ist vollstaendig. FK-50 behauptet aber derzeit staerkere Prozess-/Deadline-Garantien als die Implementierung liefert. |

## Gesamturteil

**Rework. AG3-164 darf noch nicht auf `completed` gesetzt oder gelandet werden.**

### (a) Durch den Umsetzungsagenten zu beheben

- P0-1: strikte JSON-RPC-Varianten und striktes UTF-8;
- P0-2: atomare, gepruefte Windows-Job-Klammer, sichere Identitaetspruefung und vollstaendige Deadlinebindung;
- P1-1: Job-Handle-Cleanup bei Launchfehlern;
- P1-2: deterministische Tests der neuen Transport-/Plattformgrenzen;
- P2-1 und die Typkorrektur aus P2-2 sollten im selben Modul-Rework mit erledigt werden.

Diese Punkte betreffen den Erfolgsbegriff und die Prozess-Sicherheitsgrenze; sie sind keine Orchestrator-Kleinigkeiten und brauchen nach der Reparatur eine erneute gezielte Abnahme.

### (b) Danach ohne erneute fachliche Review durch den Orchestrator erledigbar

- den einzelnen deutschen Modul-Docstring auf Englisch korrigieren, falls nicht bereits im Rework geschehen;
- `status.yaml` von `phase: setup` auf den tatsaechlichen Abschlussstand bringen und den Story-Bericht/ARE-Folgearbeit dokumentieren;
- Coverage >= 85 %, vollstaendige Test-/Lint-/Mypy-Laeufe sowie W2/W3, Jenkins und Sonar als Landungsbelege ausfuehren.

Es sind somit **nicht nur (b)-Punkte** uebrig.
