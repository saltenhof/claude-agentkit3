# Implementierungsreview 11 — AG3-164

## Auflösung von Review 10

| Befund | Urteil | Begründung |
|---|---|---|
| P1-1 — `RecursionError` aus der post-decode Nachprüfung | **geschlossen** | Die gemeinsame JSON-Baumprüfung arbeitet jetzt iterativ und erzwingt `MAX_JSON_NESTING_DEPTH = 256`. Meine frühere 700-Ebenen-Gegenprobe endete in REGISTER, DRY_RUN und VERIFY jeweils als `FAILED/mcp_configuration_invalid`; die Datei blieb byte-identisch und der Startmarker aus. Es entwich kein `RecursionError`. |
| Wire-Klassifikation derselben Tiefenklasse | **geschlossen** | Ein echter MCP-Subprozess mit 700 Ebenen in der Initialize-Antwort lieferte `False / mcp_protocol_error` mit expliziter Nesting-Ursache. Die frühere Meldung `Internal MCP conformance fault` trat nicht mehr auf. |
| P2-1 — semantischer statt lexikalisch bytegenauer Fremdeintragserhalt | **unverändert akzeptierte Restgrenze** | Fremde JSON-Werte bleiben semantisch exakt erhalten; Formatierung und lexikalische Bytes werden beim deterministischen Gesamt-Write normalisiert. Diese Abgrenzung gehört in den Story-Bericht, erfordert aber keinen weiteren AG3-164-Code. |

## Prüfung der iterativen Implementierung

Die Vereinheitlichung in
`src/agentkit/backend/installer/strict_json.py:22-126` ist fachlich sauber:

- `exceeds_max_json_nesting()` legt für jedes Dict **alle Werte** und für jede
  Liste **alle Elemente** mit der korrekten Kindtiefe auf den expliziten Stack.
- `contains_non_finite_float()` besucht dieselben beiden Containerzweige und
  prüft jeden Float mit `math.isfinite()`.
- `contains_lone_surrogate()` prüft skalare Strings, jeden Dict-Key, jeden
  Dict-Wert und jedes Listenelement. Damit bleibt kein Key-/Value- oder
  Mischbaumzweig ungeprüft.
- Die vier Regeln sind Single-Source; Config-Loader und Wire-Parser importieren
  dieselben reinen Funktionen. Es existiert keine zweite, abweichende
  Surrogate-/Non-Finite-Logik.

Adversarial geprüft wurden gemischte, etwa 160 Pfadebenen tiefe Dict-/List-
Bäume mit mehreren Geschwisterzweigen. Ein tief verstecktes `inf`, ein
Surrogate-Wert und ein Surrogate-Key wurden jeweils erkannt; der gleich
strukturierte endliche/Unicode-gültige Baum blieb unbeanstandet. Echte
CP10-Läufe mit tief verstecktem `1e400` beziehungsweise Surrogate in Key und
Value lieferten `mcp_configuration_invalid`, ohne Mutation und ohne
Conformance-Start. Ein durch den Fix erzeugter Falsch-Grün-Pfad ist damit nicht
erkennbar.

Die Grenze von 256 ist angemessen. Sie liegt weit oberhalb realistischer
`.mcp.json`- und MCP-Toolschema-Tiefen, aber deutlich unter den
plattformabhängigen Rekursionsgrenzen nachgelagerter Standardbibliotheks-
Serializer. Im direkten Grenztest wurden 255 verschachtelte Listencontainer
noch akzeptiert und der nächste abgewiesen. Eine gültige vorhandene
Vendor-Konfiguration mit 100 verschachtelten Ebenen wurde nach echtem
MCP-Handshake korrekt gemergt und semantisch unverändert erhalten. Der
offizielle MCP-SDK-Server blieb ebenfalls grün.

Der fokussierte Repo-Testlauf aus offiziellem SDK-Interop, Wire-Nesting und
Config-Nesting bestand mit `3 passed`. Zusammen mit den vom Auftraggeber
dreimal stabil gemeldeten 109 Tests sowie Ruff und Mypy liegt ausreichende
Regressionsevidenz vor.

## Neue Findings

**Keine.** Die iterative Umstellung hat weder den positiven Wire-/Config-Pfad
verschärft noch einen übersprungenen Baumzweig, eine neue Exception oder einen
weichen Fallback eingeführt.

## Finaler Musterdurchgang

**Ja — die Klasse der geerbten Nachsicht ist über Wire und Config strukturell
geschlossen.** Der abschließende Sweep umfasst:

1. strikte stdout-UTF-8-Dekodierung; lossy Decode bleibt nur für begrenzten,
   nicht entscheidungsrelevanten stderr-Diagnosetext,
2. disjunkte JSON-RPC-Envelope-Varianten und strikte IDs,
3. Nicht-JSON-Konstanten, Zahlenüberlauf und doppelte Namen,
4. isolierte Surrogates in Keys und Values,
5. vollständige offizielle MCP-Schemavalidierung mit `strict=True`,
6. begrenzte Frames/Queues sowie totaler Timeout-/Prozessbaum-Teardown,
7. striktes Config-Root-, `mcpServers`- und Serverwert-Shape,
8. identische Config-Prüfung in REGISTER, DRY_RUN, VERIFY und im ARE-Zweig,
9. iterative, explizit begrenzte Nachprüfung vor Merge, Conformance und Write.

Die relevanten externen Parse-/Decode-/Model-Grenzen sind damit vollständig
adressiert. `allow_nan=False` bleibt als zusätzliche Schreibsicherung aktiv;
Config- und Wire-Fehler bleiben maschinenlesbar getrennt.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | CP10 liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfüllt** | Conformance und Config-Prüfung liegen vor dem einzigen atomaren Write; sämtliche Negativpfade erhalten vorhandene Bytes. |
| AC 3 — generischer Check für mindestens zwei Definitionen | **erfüllt** | Unterschiedliche Serverdefinitionen verwenden denselben serverunabhängigen Check. |
| AC 4 — Falsch-Grün ausgeschlossen | **erfüllt** | Kommando-, Prozess-, Wire-, Schema-, Config-Shape- und Nestingfehler werden benannt abgewiesen; ein bloß auflösbares oder pseudo-konformes Kommando genügt nicht. |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller SDK-Server bestehen `initialize` und `tools/list` als echte Subprozesse. |
| AC 6 — Ressourcensauberkeit | **erfüllt** | Prozessbaum-, Deadline-, Pump- und kombinierte Cleanup-Fehlerpfade sind total und regressionsgeprüft. |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Bewusst abwesendes Feature bleibt ohne Probe und Write `SKIPPED`. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfüllt** | Gültige Fremdwerte bleiben semantisch erhalten; ungültige Dateien scheitern in allen Modi byte-identisch; read-only startet keine Conformance. Die lexikalische Byte-Normalisierung ist die dokumentierte P2-Restgrenze. |
| AC 9 — FK-50 und Konzept-Gates | **erfüllt** | Implementierung, Reason-Katalog, gemeinsame iterative Tiefengrenze und FK-50 stimmen überein; die vorgelegten Gates sind grün. |

## Gesamturteil

**Ja — AG3-164 ist in seinem eigenen Code abnahmereif. Freigegeben.** Am
AG3-164-Code fehlt nichts mehr. Der Kernauftrag ist erreicht: CP10 registriert
nur tatsächlich lauffähige MCP-Server, klassifiziert Fehler fail-closed und
maschinenlesbar, mutiert bei Fehlern nichts und erhält gültige fremde
Konfiguration semantisch.

Es verbleibt ausschließlich **(b) Orchestrator-Arbeit**:

1. den externen Landeblocker AG3-172 abschließen und landen,
2. AG3-164 auf `completed` setzen,
3. den Story-Bericht einschließlich „semantisch/wertgenau, nicht lexikalisch
   bytegenau“ und AG3-173 als ARE-Folgearbeit ergänzen,
4. vollständige CI-/Jenkins-/Sonar-, Coverage- und Konzept-Gate-Belege
   dokumentieren.

AG3-173 ist als konkrete Folge-Story mit ID, Abhängigkeit, Server-/CLI-Scope
und echtem Conformance-AC ausreichend adressiert. Für den AG3-164-Code ist
keine weitere fachliche Review erforderlich.

