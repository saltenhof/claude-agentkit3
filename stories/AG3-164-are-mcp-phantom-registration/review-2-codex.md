# Implementierungsreview 2 — AG3-164

## Aufloesung der Befunde aus Review 1

| Befund | Urteil | Begruendung |
|---|---|---|
| P0-1 — Pseudo-Protokoll wird akzeptiert | **teilweise geschlossen** | Das urspruengliche Gegenbeispiel ohne `jsonrpc`, Initialize-Pflichtfelder und `inputSchema` endet jetzt korrekt in `mcp_protocol_error`; die neuen Feldpruefungen in `mcp_conformance.py:598-780` sind substantiell. Die JSON-RPC-/MCP-Pruefung ist aber noch nicht strikt: ungueltige Nachrichten vor einer gueltigen Response, Boolean-IDs und `capabilities.tools: null` werden weiterhin gruen (neues P0-1). |
| P0-2 — konkurrierende Reads verlieren Responses | **geschlossen** | Pro Stream existiert genau ein langlebiger `_LinePump` (`mcp_conformance.py:285-353`). Der erneut ausgefuehrte 700-ms-Test war in drei von drei Laeufen erfolgreich (je ca. 0,92 s bei 2-s-Budget); auch die neuen 300-/700-ms- und Notification-Tests adressieren den alten Race. Keine konkurrierenden `readline()`-Aufrufe mehr. |
| P0-3 — Timeout und Prozessbaum nicht total | **teilweise geschlossen** | Die Deadline wird nun vor `Popen` gesetzt, stdout/stderr werden kontinuierlich gelesen und der Erfolgsfall schliesst zuerst stdin. Die nicht abbrechbare `Popen`-Grenze ist ehrlich dokumentiert. Der Prozessbaum-Vertrag bleibt jedoch falsch: Ein schnell aussteigender Wrapper hinterlaesst reproduzierbar seinen langlebigen Enkel; ausserdem ignorieren Teile des Teardowns die Deadline (neues P0-2). |
| P0-4 — Dry-run/Verify starten Zielprozesse | **geschlossen** | `cp10.py:198-207` verlaesst den read-only Pfad vor dem Gate; `_conformance_gate` wird nur in REGISTER aufgerufen (`:209-219`). Der urspruengliche Dry-run-Plan-Test ist in seiner alten Verhaltensform wiederhergestellt; der zusaetzliche Negativtest beweist, dass weder Dry-run noch Verify den Probeprozess starten. FK-50:539-544 ist entsprechend korrigiert. |
| P1-1 — Transportfehler fallen unklassifiziert heraus | **geschlossen** | Erwartete Pipefehler werden an der Transportgrenze typisiert; unerwartete Fehler werden im oeffentlichen Check und nochmals am CP10-Rand auf einen benannten Fehler abgebildet (`mcp_conformance.py:247-260`, `cp10.py:271-278`). Vor einem Fehler erfolgt kein Write. Die verbleibenden Teardown-Luecken sind unter P0-2 erfasst. |
| P1-2 — Testorakel/Regressionstiefe unzureichend | **teilweise geschlossen** | Adversarial-, Slow-Response-, Byte-Erhalt-, Idempotenz-, Fremdeintrag- und reale CP10-Vorgaengertests wurden nachgeliefert. Der SDK-Test startet tatsaechlich einen `FastMCP`-Server als Subprozess und bestand lokal. Er ist jedoch optional und kann in einer sauberen Dev-/CI-Installation still uebersprungen werden; die Prozessresttests sind zudem nicht xdist-isoliert und der Enkeltest deckt gerade den schnellen Escape nicht ab (P1-1/P1-2). |
| P1-3 — Decision Record/P3-/Formal-Impact unvollstaendig | **teilweise geschlossen** | Der Record besitzt nun einen brauchbaren Impact-Sweep und eine klassifizierte Betroffenheitsmatrix; der Decision-Gate-Lauf ist gruen. Der Referenz-Gate-Lauf ist dagegen mit 11 Errors rot, und FK-50 behauptet weiterhin eine Prozessbaum-Totalitaet, die der Code nicht erfuellt (P1-4). |
| P1-4 — Probeprozess erbt Installer-Secrets | **geschlossen** | `_build_minimal_env` (`mcp_conformance.py:814-830`) uebergibt nur plattformnotwendige Basisvariablen plus explizites Entry-Env. Der Sentinel-Test beweist: Parent-Secret unsichtbar, explizite MCP-Variable sichtbar. |
| P2-1 — doppelte Reason-SSOT/schwache Typisierung | **geschlossen** | `McpConformanceReason` projiziert die zentralen Konstanten aus `reasons.py`; `McpConformanceResult.reason` ist typisiert. Ein Contract-Test bindet alle Werte. |
| P2-2 — relative Kommandos ignorieren `cwd` | **geschlossen** | `_resolve_command(..., cwd=...)` loest relative Pfade gegen das effektive Arbeitsverzeichnis auf (`mcp_conformance.py:784-811`); Windows- und POSIX-Wrapper werden real gestartet. |

## Neue Findings

### P0-1 — Der Protokollvalidator besitzt weiterhin echte Falsch-Gruen-Pfade

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:598-638`, `:665-693`; fehlende Grenzfaelle in `tests/unit/installer/test_mcp_conformance.py:107-126`.

Die Feldpruefung ist deutlich besser, aber die Eingangsmessage wird nur dann validiert, wenn ihre `id` per Python-Gleichheit zur erwarteten ID passt. Drei read-only Gegenproben endeten weiterhin mit `ok=True`:

1. Der Server schreibt zuerst `{"garbage": true}` und danach gueltige Responses. Das ungueltige Nicht-JSON-RPC-Objekt wird als vermeintlich fremde Message still ignoriert.
2. Die Initialize-Response verwendet die JSON-ID `true`. In Python gilt `True == 1`; JSON-RPC erlaubt als ID String, Number oder Null, nicht Boolean.
3. Initialize deklariert `"capabilities": {"tools": null}` und liefert danach eine Toolliste. `null` ist keine wohlgeformte Tools-Capability, wird in `:684-693` aber ausdruecklich akzeptiert.

Damit kann CP10 weiterhin nach strukturell ungueltigem Wire-Verhalten schreiben; AC 4 ist nicht erfuellt.

**Fix:** Jede stdout-Message vor einer fachlichen Behandlung als JSON-RPC-Envelope klassifizieren. Nur wohlgeformte Notifications duerfen ohne passende ID ignoriert werden; Garbage-Objekte, Responses mit fremder/ungueltiger ID und ungueltige Requests muessen `mcp_protocol_error` liefern. Fuer eigene Integer-Requests die ID typstreng vergleichen (`type(id) is int`, kein Boolean). `capabilities.tools` muss ein Objekt sein, nicht `null`. Die drei obigen Gegenbeispiele sowie falsche Notification-Envelopes als Negativtests aufnehmen.

### P0-2 — Der Prozessbaum-Supervisor garantiert weder Totalitaet noch sichere Identitaet

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:833-889`; unzureichendes Orakel `tests/fixtures/mcp_bad_servers.py:189-197` und `tests/unit/installer/test_mcp_conformance.py:161-178`.

Der neue Test laesst den Parent absichtlich 400 ms leben. Dadurch kann das periodische `psutil`-Snapshotting den Enkel bequem sehen. Ein adversarialer Wrapper, der den Enkel startet und **sofort** endet, hinterliess auf Windows reproduzierbar die langlebigen Python-Enkelprozesse nach Rueckkehr von `check_mcp_conformance`; sie wurden nach dem Nachweis diagnostisch beendet. Das Verfahren kann einen bereits reparenteten Prozess nicht mehr ueber `root.children()` finden. `start_new_session=True` auf POSIX hilft nicht, weil die erzeugte Prozessgruppe nirgends terminiert wird.

Zusaetzlich speichert `tracked_pids` nur Zahlen. Stirbt ein kurzlebiges Kind und wird seine PID wiederverwendet, kann `_kill_tracked_pids` spaeter einen unbeteiligten Prozess terminieren. Und `psutil.wait_procs(..., timeout=2)` in `:884` und erneut in `:889` verwendet nicht das verbleibende Deadline-Budget; die Modulbehauptung, kontrollierte Teardown-Waits seien von der Deadline umfasst, ist damit falsch.

**Fix:** Eine echte plattformspezifische Lebenszyklus-Klammer verwenden: POSIX-Session/Process-Group mit begrenztem `SIGTERM`/`SIGKILL`; Windows-Job-Object mit Kill-on-close. Prozessidentitaeten mindestens an PID **und** Create-Time binden. Jeder Wait erhaelt das verbleibende monotone Budget. Tests muessen einen sofort aussteigenden Wrapper, einen weiterhin lebenden Parent, Erfolg, Timeout und Protokollfehler abdecken und die konkrete Child-Identitaet nachweisen. Der bisherige 400-ms-Test darf bleiben, ist aber kein Totalitaetsbeleg.

### P1-1 — Der offizielle SDK-Interop-Beleg ist in einer sauberen Umgebung optional

**Ort:** `tests/integration/installer/test_mcp_conformance.py:44-55`, `tests/fixtures/official_mcp_sdk_server.py:10-23`, `pyproject.toml:29-42`.

Der Test ist echt: Er startet einen unabhaengigen `mcp.server.fastmcp.FastMCP`-Server als Subprozess und bestand lokal. `pytest.importorskip("mcp")` macht ihn jedoch zu einem freiwilligen Orakel, waehrend `mcp` nicht in den Dev-Abhaengigkeiten steht. Eine frische CI-Umgebung kann den wichtigsten Common-Mode-Schutz ueberspringen und trotzdem gruen werden.

**Fix:** Eine kompatible MCP-SDK-Version als Dev-/Testabhaengigkeit deklarieren und `importorskip` entfernen. Fehlt das SDK, muss der Testlauf rot sein. Der SDK-Server bleibt als handgeschriebenes Hilfsmodul unter `tests/fixtures/` korrekt platziert.

### P1-2 — Die neuen Restprozess-Tests sind unter dem repo-eigenen xdist-Modus flaky

**Ort:** `tests/unit/installer/test_mcp_conformance.py:35-45` sowie alle Aufrufe von `_assert_no_fixture_leftovers`; `pyproject.toml:52-62`.

Das Orakel sucht global nach dem gemeinsamen Dateinamen `mcp_bad_servers.py`. Parallel laufende Tests anderer Dateien benutzen denselben Prozess und werden als Leak des gerade geprueften Falls gewertet. Der gezielte Lauf der drei neuen Testmodule unter dem konfigurierten `-n 4 --dist loadfile` endete deshalb mit zwei Fehlern: Der Slow-Response-Test sah den `die`-Prozess, der Immediate-Exit-Test den parallelen `noise`-Prozess. Seriell waren die betroffenen Tests gruen. Das ist keine Produktregression, aber ein unzuverlaessiges Pflichtgate.

**Fix:** Jedem Fixture-Start einen eindeutigen Run-Token mitgeben und ausschliesslich nach diesem Token bzw. nach einer explizit publizierten PID/Create-Time-Identitaet pruefen. Der Enkel muss denselben Token tragen. Danach die Testdateien explizit gemeinsam unter dem Standard-xdist-Modus wiederholt ausfuehren.

### P1-3 — Die Stream-Pumps sind nicht ressourcenbegrenzt

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:285-324`, insbesondere die unbeschraenkte `queue.Queue()` in `:296` und `readline()` ohne Frame-Limit in `:311`.

Auch der stderr-Pump legt **jede** Zeile in eine unbeschraenkte Queue, obwohl diese Queue nie konsumiert wird; nur die separate Anzeige-Liste ist begrenzt. stdout kann ebenso beliebig viele Notifications einreihen. Eine endlose Zeile kann bereits in `TextIOWrapper.readline()` unbeschraenkt wachsen. Ein fehlerhafter Server kann den Installer daher vor Ablauf des Timeouts per Speicherverbrauch ausfallen lassen — erneut ausserhalb des versprochenen benannten Fehlerpfads.

**Fix:** stderr als drain-only Kanal mit begrenztem Ringpuffer behandeln, nicht in eine unbenutzte Queue schreiben. Fuer stdout eine maximale Framegroesse und eine begrenzte Pending-Message-Kapazitaet normieren; Overflow/oversize wird deterministisch `mcp_protocol_error`, waehrend der Reader bis zum Teardown weiter drainiert.

### P1-4 — Das verpflichtende Konzept-Referenzgate ist rot

**Ort:** `concept/_meta/decisions/2026-07-20-mcp-conformance-registration-gate.md:39,90-93`, `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:515,530,572,789`, `concept/_meta/reference-integrity-baseline.yaml`.

Frontmatter und Formal-Compiler waren gruen, der Decision-Record-Gate ebenfalls. `check_concept_reference_integrity.py` endete dagegen mit **11 Errors**: unter anderem werden die backticked MCP-Methode `tools/list` und die Platzhalter `src/.../...` als nicht existente Repo-Pfade erkannt; durch die FK-50-Einfuegung sind ausserdem zwei Baseline-Anker stale bzw. verschoben. AC 9 und das Pflichtgate vor Landung sind damit objektiv nicht erfuellt.

**Fix:** Im Record reale vollstaendige Repo-Pfade verwenden. Fuer protocol literals wie `tools/list` die dokumentierte, begruendete `REF-INTEGRITY:IGNORE-LINE`-Direktive oder eine nicht als Pfad interpretierte eindeutige Schreibweise verwenden. Die unveraendert legitimen Baseline-Eintraege auf die neuen Anker rebasieren und den Gate-Lauf auf null Errors bringen; keine neuen materiellen Fehler blind baselinen.

### P1-5 — Bei 947 Zeilen ist der fachliche Modulschnitt jetzt faellig

**Ort:** `src/agentkit/backend/installer/mcp_conformance.py:1-947`.

Das Modul besitzt inzwischen vier eigenstaendige Verantwortungen: oeffentlicher Check-/Resultvertrag, JSON-RPC-/MCP-Validierung, stdio-Pump/Framing sowie plattformspezifische Prozess- und Environment-Steuerung. Die private Queue wird bereits ueber `_try_consume_enqueued` von aussen angefasst (`:540-552`), ein deutliches Schnittsignal. Mit den notwendigen Prozess- und Ressourcenfixes wuerde die Datei weiter wachsen. Nach `CLAUDE.md` ist sie damit nicht mehr nur „gross“, sondern ein faelliger God-File-Kandidat.

**Fix:** Vor weiterer Erweiterung in mindestens (a) reine Protokollmodelle/-validatoren, (b) stdio-/Prozess-Supervisor und (c) kleine oeffentliche Conformance-Fassade schneiden. Die Abhaengigkeitsrichtung bleibt Fassade -> Supervisor/Validator; reine Validatoren erhalten direkte Unit-Tests, Prozessgarantien reale Subprozesstests.

## Akzeptanzkriterien

| AC | Urteil | Begruendung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfuellt** | Realer CP10- und Full-Install-Pfad liefern `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfuellt** | Alle Server werden vor dem einzigen atomaren Write geprueft; frischer und bereits vorhandener `.mcp.json`-Zustand sind getestet, letzterer bleibt byte-identisch. |
| AC 3 — generischer Check fuer mindestens zwei Definitionen | **erfuellt** | Der Code ist servertypunabhaengig; zwei reale Definitionen passieren dasselbe Gate, ein Fehler einer Definition verhindert den Gesamtwrite. |
| AC 4 — drei Negativfaelle, kein Falsch-Gruen | **nicht erfuellt** | Die verlangten groben Negativfaelle sind vorhanden, aber strukturell ungueltige JSON-RPC-/MCP-Varianten bestehen weiterhin nachweislich (P0-1). |
| AC 5 — echter positiver MCP-Subprozess | **erfuellt** | Minimalserver und offizieller SDK-Server laufen als echte Subprozesse mit Initialize und `tools/list`; der SDK-Beleg muss lediglich verpflichtend gemacht werden. |
| AC 6 — keine Restprozesse in allen Ausgaengen | **nicht erfuellt** | Der langsam aussteigende Testenkel wird beseitigt; ein sofort reparenteter Enkel entkommt reproduzierbar (P0-2). |
| AC 7 — ARE=false bleibt SKIPPED | **erfuellt** | Beide Features aus ergibt weiterhin `SKIPPED/vectordb_disabled` ohne Prozess oder Write. |
| AC 8 — Merge-Idempotenz, Fremdinhalt, Dry-run/Verify erhalten | **erfuellt** | Zweiter REGISTER-Lauf ist `PASS` und byte-identisch; Fremdeintraege bleiben; Dry-run/Verify sind wieder read-only. Keine der drei geaenderten Bestandsdateien wurde erneut abgeschwaecht: Die ARE-Erwartung wurde fachlich korrekt auf ehrliches FAILED umgestellt, Dry-run in alter Semantik restauriert und CP10c nun ueber echten Vorgaenger-State aufgebaut. |
| AC 9 — FK-50 plus gruene Konzeptgates | **nicht erfuellt** | Record und normative Inhalte sind strukturell wesentlich verbessert, aber das Referenzgate ist mit 11 Errors rot und die behauptete Prozessbaum-Totalitaet stimmt noch nicht mit dem Code ueberein. |

## Weitere Bewertung

- **Reader-Architektur:** Der alte konkurrierende-Read-Defekt ist weg; normale EOF-/Queue-Verarbeitung und Join-Reihenfolge zeigen keinen neuen Deadlock. Die neue Schwachstelle ist Ressourcenbegrenzung, nicht Nachrichtenverlust im normalen Lauf.
- **Launch-Deadline:** Die Deadline beginnt jetzt vor `Popen`; dass der synchrone OS-Launch selbst nicht abbrechbar ist, ist entsprechend Review 1 ehrlich als Plattformgrenze dokumentiert und fuer sich kein neuer Blocker. Die nachgelagerten `wait_procs` muessen dennoch an das Budget gebunden werden.
- **Fixture-Ort:** Alle drei Python-Fixtures sind handgeschriebene Testprogramme, keine generierten Dateien. `tests/fixtures/` bleibt korrekt.
- **Regressionen:** Der alte Dry-run-Test wurde materiell restauriert, Fremdinhalt/Idempotenz wurden verschaerft, und die CP10c-Fixtures erfinden den Vorgaengerzustand nicht mehr ad hoc. Die festgestellte xdist-Flakiness liegt in den neuen globalen Leak-Orakeln.

## Gesamturteil

**Rework. AG3-164 darf noch nicht auf `completed` gesetzt oder gelandet werden.**

Blockierend durch den Umsetzungsagenten zu beheben sind P0-1 und P0-2 sowie die ressourcenbegrenzte Transportausbildung aus P1-3. Vor Landung muessen ausserdem der SDK-Test verpflichtend, die Leak-Orakel parallelfest, der faellige Modulschnitt vollzogen und das Referenzgate gruen sein. Danach ist eine erneute adversariale Abnahme sinnvoll, weil Protokollvalidator und plattformspezifischer Prozess-Supervisor die beiden sicherheitsrelevanten Kernstellen dieser Story sind.

Ohne weitere fachliche Review kann der Orchestrator anschliessend die rein operativen Abschlussarbeiten erledigen: Status/Story-Bericht aktualisieren, Coverage >= 85 % nachweisen und die vollstaendigen Pflichtlaeufe einschliesslich W2/W3, Jenkins und Sonar ausfuehren. Diese Gates sind keine Ersatzhandlung fuer die oben genannten Codefixes.
