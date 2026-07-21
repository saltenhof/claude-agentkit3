# Implementierungsreview 10 — AG3-164

## Auflösung von Review 9

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — Nicht-Objekte als einzelne `mcpServers`-Werte | **geschlossen** | Zahl, Array, `null`, String und Boolean endeten in REGISTER, DRY_RUN und VERIFY jeweils als `FAILED/mcp_configuration_invalid`. Die vorhandene Datei blieb byte-identisch; ein Startmarker blieb in allen 15 Läufen aus. Ein gültiges fremdes Objekt mit unbekannten Vendor-/Harnessfeldern, verschachtelten Werten und Unicode wurde nach echtem MCP-Handshake unverändert per Deep-Equality erhalten. Die Prüfung ist bewusst nur auf Objekt-Shape beschränkt und verbietet keine fremden Transportdialekte. |
| P1-1 — Decode-/Parserfehler und isolierte Surrogates | **teilweise geschlossen** | Ungültiges UTF-8, der bestehende 100.000-Ebenen-Fall sowie isolierte Surrogates in Key und Value liefern in den geprüften Modi korrekt `FAILED/mcp_configuration_invalid`, ohne Prozessstart und bei byte-identischer Datei. Die gemeinsame Hilfslogik ist sauber geschnitten. Eine weitere `RecursionError`-Stelle liegt jedoch **nach** dem Decoder in den rekursiven Nachprüfungen (neues P1-1). |
| P1-2 — read-only ARE-Zweig umgeht Loader | **geschlossen** | Bei vorhandener ungültiger Datei liefert `_are_mcp_registered()` in REGISTER, DRY_RUN und VERIFY denselben Loaderfehler. Bei fehlender Datei bleibt die Semantik korrekt: REGISTER meldet nicht registriert; DRY_RUN/VERIFY leiten ausschließlich dann aus `are_enabled` ab. Der öffentliche CP10c-Test weist `mcp_configuration_invalid` in beiden read-only Modi nach. |
| P2-1 — semantischer statt lexikalisch bytegenauer Fremdeintragserhalt | **unverändert akzeptierte Restgrenze** | Fremde JSON-Werte bleiben semantisch exakt erhalten; die Datei wird deterministisch neu serialisiert. Eine tokenerhaltende JSON-Patch-Engine bleibt für AG3-164 unverhältnismäßig und gehört nur bei neuer PO-Norm in eine eigene Story. Die Klarstellung gehört in den Abschlussbericht. |

Der fokussierte Testlauf der neuen Config-/ARE-Fälle plus offizieller
SDK-Interop bestand mit `7 passed`. Die vom Auftraggeber dreimal stabil
gemeldeten 107 Tests, Ruff, Mypy und Konzept-Gates bestätigen, dass die
benannten Reparaturen keine normale Regression erzeugt haben.

## Neue Findings

### P1-1 — `RecursionError` aus der Nachprüfung entweicht trotz abgefangenem Decoder-Fehler

**Ort:**
`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:96-118`;
`src/agentkit/backend/installer/strict_json.py:44-80`;
unzureichendes Orakel in
`tests/unit/installer/checkpoint_engine/test_cp10_mcp_conformance.py:716-747`.

Der neue Test mit 100.000 Arrayebenen lässt bereits `json.loads()` mit
`RecursionError` scheitern und trifft damit den ausdrücklich abgefangenen
Decoderpfad. Es gibt aber eine niedrigere Zone, in der der C-/JSON-Decoder
noch erfolgreich ist und erst die rekursiven Python-Prädikate
`contains_non_finite_float()` beziehungsweise `contains_lone_surrogate()`
ihre Rekursionsgrenze erreichen.

Eine reale `.mcp.json` mit einem fremden Objekt und etwa 700 verschachtelten
Arrayebenen ergab auf dem aktuellen Projekt-Venv:

| Modus | Ergebnis | Datei verändert | Conformance gestartet |
|---|---|---|---|
| REGISTER | nackter `RecursionError` | nein | nein |
| DRY_RUN | nackter `RecursionError` | nein | nein |
| VERIFY | nackter `RecursionError` | nein | nein |

Damit ist der Vorgang zwar fail-closed im Sicherheits- und Mutationssinn, aber
nicht im ausdrücklich normierten Ergebnisvertrag: Statt
`FAILED/mcp_configuration_invalid` verlässt eine Exception den Checkpoint.
Das ist kein P0, weil weder falsches Grün noch Datenverlust oder ein gestarteter
Fremdprozess entsteht. Es ist aber auch keine sinnvolle dokumentierbare
Restgrenze: Der Fix liegt lokal am gerade eingeführten Loader.

**Fix:** Die beiden Nachprüfungen im Config-Loader gemeinsam gegen
`RecursionError` kapseln und denselben Detail-/Reason-Pfad
`mcp_configuration_invalid` verwenden. Alternativ dürfen die gemeinsamen
Baumprädikate iterativ implementiert werden; dann ist zusätzlich
sicherzustellen, dass die spätere Serialisierung dieselbe Tiefenklasse vor dem
Conformance-Start deterministisch ablehnt. Der Regressionstest muss eine Tiefe
verwenden, für die ein Kontroll-`json.loads(..., parse_constant=...,
object_pairs_hook=...)` nachweislich **erfolgreich** ist, während der bisherige
Nachprüfpfad scheitert; anschließend sind für alle drei Modi benannter Fehler,
Byte-Erhalt und fehlender Start zu prüfen.

Am Wire-Pfad führt dieselbe Tiefe im öffentlichen echten Subprozesslauf bereits
fail-closed zu `mcp_protocol_error`, weil die Conformance-Fassade unerwartete
Validatorfehler fängt. Fachlich sauberer wäre, den `RecursionError` auch in
`parse_json_object()` explizit als „nesting exceeds validation limits“ zu
klassifizieren, statt ihn als „Internal MCP conformance fault“ bis zur Fassade
laufen zu lassen. Das kann im selben kleinen Fix erfolgen; ein weiterer
Wire-Falsch-Grün-Pfad besteht dadurch nicht.

## Finaler Musterdurchgang

**Nein, die Klasse ist noch nicht vollständig geschlossen.** Sämtliche zuvor
gefundenen Nachsichten an Transport, Envelope, JSON-Token, Unicode,
SDK-Schema, Config-Shape, Config-Write und ARE-Modusführung sind geschlossen.
Die neue gemeinsame Datei `installer/strict_json.py` ist fachlich sinnvoll und
enthält keine duplizierte Schattenlogik; der bereits abgenommene Wire-Parser
nutzt dieselben vier reinen Regeln mit unveränderter Semantik. Offengeblieben
ist ausschließlich die Rekursionstotalität der nachgelagerten Baumprüfung aus
P1-1.

Weitere `json.loads`-/Decode-Pfade für die Ziel-`.mcp.json` existieren in CP10
nicht. Nach Schließung dieses konkreten Post-Decode-Fensters sehe ich in der
von AG3-164 berührten Wire-/Config-Oberfläche weiterhin keine weitere
ungeprüfte externe Eingabegrenze.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Der reale CP10-Pfad liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite bei gescheiterter Conformance | **erfüllt** | Alle gewünschten Server passieren das Gate vor dem atomaren Write; Fehler lassen vorhandene Bytes unverändert. |
| AC 3 — generischer Check für mindestens zwei Definitionen | **erfüllt** | Unterschiedliche Serverdefinitionen verwenden denselben serverunabhängigen Check. |
| AC 4 — Falsch-Grün ausgeschlossen | **erfüllt** | Die geforderten Negativklassen und alle bisher gefundenen Wire-/Shape-Angriffe werden abgewiesen. P1-1 ist eine nackte Fehlerausgabe, kein grüner Ausgang. |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller SDK-Server bestehen; auch der Vendor-Fremdobjekt-Merge lief mit echtem Handshake. |
| AC 6 — Ressourcensauberkeit | **erfüllt** | Prozessbaum-, Deadline- und kombinierte Cleanup-Verträge bleiben geschlossen. Im offenen P1 wird kein Prozess gestartet. |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt ohne Probe und Write `SKIPPED`. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **teilweise erfüllt** | Shape, fremde Werte und Modusführung sind korrekt. Eine decoder-akzeptierte mittlere Verschachtelung liefert jedoch in allen drei Modi noch keinen benannten Checkpoint-Ausgang. |
| AC 9 — FK-50 und Konzept-Gates | **teilweise erfüllt** | Die Gates sind grün und der normierte Katalog stimmt für die geprüften Fälle. FK-50 verspricht Parser-/Recursionfehler jedoch total als `mcp_configuration_invalid`; P1-1 verletzt diese Aussage noch. |

## Gesamturteil

**Nein — AG3-164 ist in seinem eigenen Code noch nicht abnahmereif. Urteil:
Rework.** Der Kern-Guard verhindert inzwischen falsche Registrierung, erhält
gültige fremde Konfiguration semantisch und schreibt bei allen geprüften
Fehlern nichts. Der einzige verbleibende Codebefund ist ein enger P1 im
maschinenlesbaren Fehlervertrag, kein neuer Architektur- oder Prozessbaum-
Defekt. Weil seine Behebung lokal und proportional ist, wäre eine
PO-Restgrenze hier weniger ehrlich als der kleine Fix.

### (a) Durch den Umsetzungsagenten zu beheben

- P1-1: `RecursionError` aus den post-decode Baumprüfungen in Config und
  vorzugsweise Wire explizit klassifizieren; den Test so schneiden, dass der
  Decoder nachweislich erfolgreich war.

### (b) Durch den Orchestrator zu erledigen

- AG3-172 landen;
- anschließend Status `completed`, Story-Bericht einschließlich der
  semantisch-statt-lexikalisch-bytegenau-Klarstellung sowie vollständige
  CI-/Coverage-Belege.

**AG3-173 ist als ARE-Folgearbeit jetzt ausreichend konkret adressiert.** Die
Story `AG3-173-are-mcp-server-implementation` besitzt eine reale ID, einen
expliziten `depends_on: [AG3-164]`, den fehlenden Konsolenbefehl und den echten
Conformance-Durchlauf als Scope/AC. Das genügt als belastbarer
Auflösungspfad; die fachliche Qualität ihres Detailbriefings war nicht
Gegenstand dieser Codeabnahme.

