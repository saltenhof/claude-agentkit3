# Implementierungsreview 9 — AG3-164

## Auflösung von Review 8

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — permissiver CP10-`.mcp.json`-Loader | **teilweise geschlossen** | Die vier vorgegebenen Hauptangriffe sind materiell geschlossen: `NaN`, doppelte Top-Level-`mcpServers`, Root `[]` und numerisches `mcpServers` ergeben in **REGISTER, DRY_RUN und VERIFY** jeweils `FAILED/mcp_configuration_invalid`; die vorhandene Datei bleibt byte-identisch und ein Startmarker beweist, dass kein Conformance-Subprozess gestartet wird. Der Loader weist außerdem Zahlenüberlauf und verschachtelte Duplikate ab; Schreiben nutzt `allow_nan=False`. Der abschließende Mustersweep fand aber noch eine strukturelle Falsch-Grün-Variante und unvollständige Fehlerpfade (neue Findings). |
| Trennung Config- vs. Wire-Fehler | **geschlossen** | Eine ungültige Zielkonfiguration liefert `mcp_configuration_invalid`. Bei gültiger Zielkonfiguration und strukturell ungültigem Pseudo-MCP liefert derselbe echte REGISTER-Pfad dagegen `mcp_protocol_error`. Reasons, Code und FK-50 führen die Klassen getrennt. |
| Gültiger Merge / Fremdinhalt | **für den normativen Wertvertrag geschlossen** | Eine gültige vorhandene Datei mit Top-Level-Fremdfeld und fremdem Serverobjekt wurde nach echtem MCP-Handshake korrekt gemergt; alle fremden JSON-Werte blieben per Deep-Equality unverändert. Die lexikalischen Bytes des Fremdobjekts werden wegen der vollständigen `json.dumps`-Neuserialisierung nicht erhalten; diese Abgrenzung steht unter P2-1. |

Mein fokussierter Lauf der neuen Loader-Tests bestand mit `8 passed`. Die vom
Auftraggeber dreimal stabil gemeldeten 102 MCP-/CP10-Tests, Ruff, Mypy,
Konzept-Gates und die vorgelegte Coverage sind belastbare Positivbelege. Die
folgenden Befunde stammen aus zusätzlichen realen Checkpoint-Läufen und werden
von dieser vorhandenen Testauswahl nicht erfasst.

## Neue Findings

### P0-1 — Einzelne fremde `mcpServers`-Definitionen dürfen weiterhin Nicht-Objekte sein

**Ort:**
`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:137-144,180-208`;
fehlende Negativabdeckung nach
`tests/unit/installer/checkpoint_engine/test_cp10_mcp_conformance.py:568-598`.

Der Loader prüft nur, dass `mcpServers` selbst ein Objekt ist. Seine Werte
werden nicht geprüft. Dadurch bestanden diese vorhandenen Konfigurationen den
Loader:

```json
{"mcpServers":{"foreign":7}}
{"mcpServers":{"foreign":[]}}
```

Mit einem echten, konformen MCP-Subprozess endeten beide REGISTER-Läufe als
`UPDATED` ohne Reason; CP10 schrieb den strukturell ungültigen Fremdeintrag
erneut neben den funktionierenden eigenen Eintrag. Das ist die siebte Instanz
der geerbten Nachsicht: Der Container ist typkorrekt, sein fachlich
entscheidender Inhalt aber nicht. Der Kernauftrag ist damit noch nicht total —
der Guard kann Erfolg melden, obwohl die resultierende MCP-Konfiguration nicht
durchgehend aus Serverobjekten besteht.

**Fix:** `_load_target_mcp_json()` muss für jedes Element von `mcpServers`
mindestens `isinstance(entry, dict)` erzwingen. `null`, Skalar, Liste und String
müssen in allen drei Modi als `FAILED/mcp_configuration_invalid` enden, ohne
Conformance-Start und bei byte-identischer Datei. Eine weitergehende
Validierung fremder transport- oder harnessspezifischer Felder ist hier nicht
angezeigt; die Objektgrenze schließt den Defekt, ohne fremde Dialekte zu
verbieten.

### P1-1 — Dekodier- und Parser-Ressourcenfehler verlassen den benannten Loader-Vertrag

**Ort:**
`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:116-129`.

`read_text(encoding="utf-8")` fängt nur `OSError`; ungültige UTF-8-Bytes lösen
deshalb einen nackten `UnicodeDecodeError` aus. Ebenso entweicht bei stark
verschachteltem, aber lexikalisch plausiblem JSON ein `RecursionError` aus
`json.loads()`. Meine direkten Gegenproben lieferten in beiden Fällen eine
Exception statt `FAILED/mcp_configuration_invalid`. Die Datei wird zwar nicht
geschrieben, der versprochene maschinenlesbare Fehlervertrag ist aber gebrochen.

Zusätzlich akzeptiert der Loader noch isolierte Surrogates wie `"\ud800"` in
Schlüsseln und Werten und schreibt sie nach erfolgreicher Conformance erneut.
Der MCP-Wire-Loader weist dieselbe Unicode-Klasse bereits bewusst zurück; ein
als „strict“ normierter Config-Loader sollte an dieser Grenze nicht wieder
nachsichtiger sein.

**Fix:** `UnicodeDecodeError` beim Lesen und `RecursionError` beim Parsen in den
gemeinsamen `mcp_configuration_invalid`-Pfad überführen. Die bereits im
Wire-Parser verwendete rekursive Lone-Surrogate-Prüfung als gemeinsame reine
Hilfslogik wiederverwenden oder äquivalent im Config-Loader anwenden. Tests
müssen ungültiges UTF-8, extreme Verschachtelung sowie isolierte Surrogates in
Key und Value mit benanntem Ergebnis, Byte-Erhalt und ohne Prozessstart
nachweisen. `MemoryError` sollte nicht pauschal verschluckt werden.

### P1-2 — Die ARE-Präsenzprüfung umgeht den gemeinsamen Loader in DRY_RUN und VERIFY

**Ort:**
`src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:600-623`;
Normgegenstelle
`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:897`.

`_are_mcp_registered()` gibt in nichtmutierenden Modi bereits in Zeile 614/615
`(context.are_enabled, None)` zurück und liest eine **vorhandene** Datei nicht.
Die Gegenprobe mit `{"mcpServers":7}` ergab daher:

| Modus | `_are_mcp_registered()` |
|---|---|
| REGISTER | `(False, "... mcpServers ... must be ... object")` |
| DRY_RUN | `(True, None)` |
| VERIFY | `(True, None)` |

Der normale Gesamtfluss wird zuvor durch CP10 blockiert; deshalb ist dies kein
zweiter P0. Es widerspricht aber dem in FK-50 ausdrücklich auch für die
CP10c-ARE-Prüfung behaupteten gemeinsamen Loader- und Fehlervertrag und erzeugt
bei isolierter/read-only CP10c-Ausführung ein falsches Positivergebnis.

**Fix:** Ist die Datei vorhanden, muss `_are_mcp_registered()` sie in jedem
Modus mit `_load_target_mcp_json()` prüfen. Nur bei **nicht vorhandener** Datei
darf DRY_RUN/VERIFY weiterhin aus `are_enabled` ableiten, was CP10 angelegt
hätte. Ein Test pro read-only Modus muss den vorhandenen ungültigen Root als
`mcp_configuration_invalid` bis zum öffentlichen CP10c-Resultat nachweisen.

### P2-1 — „Byte-genauer“ Fremdeintragserhalt ist nur semantisch, nicht lexikalisch erfüllt

**Ort:** `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py:393-404`.

Der Merge erhält fremde Keys und Werte exakt, serialisiert aber die gesamte
Datei mit Einrückung und sortierten Keys neu. Eine kompakte fremde Definition
war nach dem Merge semantisch identisch, ihre ursprüngliche Bytefolge kam in
der Zieldatei jedoch nicht mehr vor. Der bisherige Story-/FK-50-Vertrag
„fremde Einträge bleiben erhalten“ ist damit nach üblicher JSON-Semantik
erfüllt; eine wörtliche lexikalische Byte-Erhaltung ist es nicht.

Eine token-/bereichserhaltende JSON-Patch-Engine wäre für den Kern dieser Story
unverhältnismäßig und riskanter als die bestehende deterministische
Neuserialisierung. Daher **kein zusätzlicher Codeblocker**, aber eine
dokumentierbare Grenze: Der Abschlussbericht sollte „wertegenau/semantisch,
nicht formatierungs- oder byteerhaltend“ festhalten. Soll „byte-genau“ künftig
wörtlich normativ gelten, ist das eine eigene PO-Entscheidung und Story, nicht
ein stilles Zusatz-AC dieses Reworks.

## Letzter Musterdurchgang

**Die Klasse ist noch nicht über Wire und Config geschlossen.** Die
MCP-Wire-Grenze bleibt vollständig geschlossen: striktes UTF-8, disjunkte
JSON-RPC-Envelopes, striktes JSON und `mcp.types` mit `strict=True`. Der
Config-Schreibpfad trennt jetzt Nicht-JSON-Konstanten, Duplikate, Zahlenüberlauf
und Root-/Container-Shape korrekt ab. Offen sind aber noch:

1. Shape der einzelnen `mcpServers`-Werte (P0-1),
2. totaler Decode-/Parser-Fehlertransport und Surrogate (P1-1),
3. Loader-Nutzung im read-only ARE-Zweig (P1-2).

Weitere Parse-Stellen für die Ziel-`.mcp.json` existieren in CP10 nicht; nach
Schließung dieser drei lokal bestimmten Punkte sehe ich in der von AG3-164
berührten Wire-/Config-Oberfläche keine weitere ungeprüfte externe
Eingabegrenze.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Der reale CP10-Pfad liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite bei gescheiterter Conformance | **erfüllt** | Das Gate liegt vor dem einzigen atomaren Write; Probe-Fehler lassen vorhandene Bytes unverändert. |
| AC 3 — generischer Check für mindestens zwei Definitionen | **erfüllt** | Unterschiedliche Serverdefinitionen verwenden denselben serverunabhängigen Check. |
| AC 4 — Falsch-Grün ausgeschlossen | **nicht vollständig erfüllt** | Der MCP-Wire-Probevertrag ist geschlossen. Ein nicht-objektförmiger fremder Servereintrag bleibt jedoch trotz erfolgreichem Gesamtresultat in der geschriebenen Konfiguration (P0-1). |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller SDK-Server bestehen als echte Subprozesse. Auch der positive Merge wurde mit echtem Handshake geprüft. |
| AC 6 — Ressourcensauberkeit | **erfüllt** | Aus den Prozessbaum-, Deadline- und Cleanup-Prüfungen bleibt kein Befund offen. |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt ohne Probe und Write `SKIPPED`. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **teilweise erfüllt** | Die vier Review-8-Hauptangriffe sind in allen Modi byte-identisch fail-closed; gültige Fremdwerte bleiben semantisch erhalten. Nicht-Objekt-Serverwerte werden noch akzeptiert, Decode-/Parserfehler sind nicht total benannt und CP10c umgeht den Loader read-only. |
| AC 9 — FK-50 und Konzept-Gates | **teilweise erfüllt** | Reason und Hauptvertrag sind normiert, die Gates sind grün. FK-50 behauptet für die CP10c-ARE-Prüfung jedoch mehr Modustotalität als `_are_mcp_registered()` implementiert (P1-2). |

## Gesamturteil

**Nein — AG3-164 ist in seinem eigenen Code noch nicht abnahmereif. Urteil:
Rework.** Der ursprüngliche Review-8-Angriff ist sauber geschlossen, und der
MCP-Conformance-Guard selbst ist fachlich fertig. P0-1 ist aber ein weiterer
reproduzierbarer Falsch-Grün-Pfad im Kernvertrag „funktionierender Server plus
erhaltene, gültige Fremdkonfiguration“. Die Behebung ist eine kleine
Erweiterung desselben Loaders und keine unverhältnismäßige neunte
Architekturrunde.

### (a) Durch den Umsetzungsagenten zu beheben

- P0-1: jeden fremden `mcpServers`-Wert auf Objekt-Shape prüfen;
- P1-1: Unicode-/Recursion-Fehler und isolierte Surrogates total in
  `mcp_configuration_invalid` binden;
- P1-2: vorhandene `.mcp.json` auch im read-only ARE-Zweig strikt laden.

Die jeweils genannten Negativtests sind Teil des Fixes. P2-1 ist keine
Anweisung, eine tokenerhaltende JSON-Engine in diese Story einzubauen.

### (b) Durch den Orchestrator zu erledigen

- P2-1 als semantischen statt lexikalischen Fremdeintragserhalt im
  Abschlussbericht transparent abgrenzen;
- AG3-172 landen; danach Status, Story-Bericht und vollständige
  CI-/Coverage-Belege abschließen;
- die `depends_on`-Prosa in `story.md` an das autoritative `status.yaml`
  angleichen.

Der eigentliche `agentkit-are-mcp`-Folgeserver ist derzeit **noch nicht
ausreichend als benannte Folge-Story adressiert**: Im Storytext steht nur
„eigener Strang, im Story-Bericht zu benennen“; eine Suche unter `stories/`
findet keine konkrete Story-ID als Owner. Das blockiert den AG3-164-Code nicht,
muss aber vor `completed` im Story-Bericht durch eine reale Story-ID mit Owner
ersetzt werden. Andernfalls bliebe der bewusst ehrlich rot gemachte ARE-Pfad
ohne belastbaren Auflösungspfad.

