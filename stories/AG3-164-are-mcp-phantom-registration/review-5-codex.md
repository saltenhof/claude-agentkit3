# Implementierungsreview 5 — AG3-164

## Vorrangbefund: Die Installer-Suite ist nicht hermetisch

### P0-1 — Reproduzierbare xdist-Race im bestehenden Postgres-Schema-Check blockiert die Landung

**Ort:** `tests/fixtures/postgres_backend.py:603-665`,
`src/agentkit/backend/state_backend/postgres_store/_schema.py:273-288,330-404,664-678`,
sichtbar unter anderem in
`tests/integration/installer/test_third_party_backend_mediation.py` und
`tests/integration/installer/test_upgrade_entry.py`.

Der rote Lauf des Auftraggebers enthielt keinen aufgezeichneten
`--randomly-seed`. Ich habe deshalb den Seed meines ersten Gesamtlaufs
festgehalten (`3250338151`) und ausschließlich diesen wiederholt. Derselbe
Arbeitsbaum und dieselbe Reihenfolge ergaben dreimal `506 passed` und einmal
`1 failed, 505 passed`. Der Fehler war:

```text
psycopg.errors.InternalError_: could not open relation with OID ...
```

Er entstand in `_verify_evidence_command_kind_present()` beim Aufruf von
`pg_get_constraintdef(c.oid)`. Noch schärfer reproduzierbar ist das
interagierende Paar:

```powershell
.venv\Scripts\python -m pytest -n 2 --dist loadfile `
  --randomly-seed=3250338151 `
  tests/integration/installer/test_third_party_backend_mediation.py `
  tests/integration/installer/test_upgrade_entry.py
```

Vier von acht identischen Wiederholungen scheiterten mit demselben
verschwundenen Constraint-OID. Ein serieller Lauf von
`test_third_party_backend_mediation.py` mit zehn festen Seeds blieb dagegen
grün.

**Schuldzuweisung:** Das ist ein **Vorbestandsdefekt im
Postgres-Test-/Schema-Pfad**, nicht ein Fremdprozess-Kill durch AG3-164. Der
Fehler tritt weiterhin auf, wenn alle drei neuen AG3-164-Testdateien explizit
ausgeschlossen werden: In vier identischen Wiederholungen waren drei grün;
eine endete mit zwei Setup-Errors und demselben fehlenden OID. Damit sind die
neuen MCP-Subprozesse, Process Groups und Windows Job Objects als notwendige
Ursache widerlegt. Es gibt auch kein Indiz für geänderte Umgebung, gemeinsame
MCP-Ports oder terminierte Fremdprozesse.

Die kausale Race ist im Code sichtbar: Jeder xdist-Worker erzeugt und löscht
sein eigenes Schema, einschließlich `DROP SCHEMA ... CASCADE`. Die
Produktionssicherung in `_ensure_schema()` ist aber absichtlich auf den
jeweiligen Schemanamen begrenzt. Parallel dazu scannt der Verify-Pfad den
systemweiten `pg_constraint`-Katalog und wertet `pg_get_constraintdef(c.oid)`
aus. Ein anderer Worker kann das zu diesem OID gehörige Schema zwischen
Katalogsicht und Funktionsauswertung löschen. Die Schema-spezifischen
Advisory Locks serialisieren diese beiden Worker nicht.

**Fix:** Der State-Backend-Owner muss die Constraint-Prüfungen auf die zuvor
explizit aufgelöste Zielrelation binden (`to_regclass`/`conrelid`) und
`pg_get_constraintdef` nur noch auf OIDs dieser Relation auswerten; dieselbe
Korrektur ist für die vergleichbaren Katalogabfragen in den Alter-Statements
zu prüfen. Alternativ muss ein wirklich gemeinsames Koordinationsprimitiv
alle konkurrierenden Schema-Verify-/DDL-/Drop-Operationen umfassen. Ein Lock
nur um Create oder Bootstrap reicht nicht, solange ein anderer Worker während
einer Verify-Abfrage droppen darf. Das isolierte Zwei-Dateien-xdist-Szenario
ist als deterministischer Regressionstest aufzunehmen und wiederholt grün zu
fahren.

**Schwere:** P0 für den Lieferzustand. Unter FAIL-CLOSED und ZERO DEBT darf
eine identische Pflichtsuite nicht zufällig grün oder rot werden. Dass der
Defekt vorbesteht und fachlich einem anderen Owner gehört, entlastet die
AG3-164-Implementierung von der Ursache, nicht aber die Landungsentscheidung.

### P1-1 — Der neue MCP-Integrationstest wird unnötig in die Postgres-Race hineingezogen

**Ort:** `tests/integration/conftest.py:19-25,54-57,73-88`,
`tests/integration/installer/test_mcp_conformance.py`.

Die grobe Allow-List hängt `postgres_isolated_schema` an jede Datei unter
`tests/integration/installer/`. Der neue MCP-Test benötigt Postgres nicht; der
CP10-Pfad verwendet ein `InMemoryRegistrationRepo`. Damit verletzt die neue
Datei die im selben Hook dokumentierte Opt-in-Absicht und erzeugt unnötige
Schema-Lebenszyklen. Das ist nicht die Ursache von P0-1 — dessen Reproduktion
ohne die MCP-Tests beweist das —, erhöht aber Laufzeit und Race-Exposition.

**Fix:** `test_mcp_conformance.py` ausdrücklich in die Liste der
Postgres-unabhängigen Integrationstestdateien aufnehmen, besser langfristig
die Installer-Bindung positiv auf tatsächlich datenbanknutzende Tests
verengen. Ein Collection-Test soll belegen, dass diese Datei die Fixture
nicht erhält.

## Auflösung der Befunde aus Review 4

| Befund | Urteil | Begründung |
|---|---|---|
| P0-1 — Nicht-JSON-Konstanten passieren den Handshake | **geschlossen** | `parse_constant` verwirft `NaN`, `Infinity` und `-Infinity`; zusätzlich wird auch der von Python still zu `inf` dekodierte Zahlenüberlauf `1e400` rekursiv abgelehnt. Meine vier echten Subprozess-Gegenproben endeten jeweils mit `ok=False/mcp_protocol_error`. Der Bearbeiter hat damit nicht nur die genannte Instanz, sondern eine weitere geerbte Decoder-Nachsicht erfasst. Weitere semantisch mehrdeutige Decoder-Defaults bleiben dennoch offen (neues P1-2). |
| P1-1 — Win32-Cleanup nicht vollständig fail-closed | **teilweise geschlossen** | Resume-, Terminate- und reguläre Close-Fehler werden bis zum öffentlichen `mcp_process_control_error` propagiert; der Teardown-Control-Fehler gewinnt nun auch gegen einen früheren Handshake-Fehler. Zwei kombinierte Fehlerpfade verschlucken Close-Fehler weiterhin (neues P1-3). |
| P1-2 — Deadline-/Reserve-Vertrag verletzt | **teilweise geschlossen** | Die arithmetische Invariante `handshake_deadline <= full_deadline` gilt nun, und Windows-Startfehler warten nur im Restbudget. Der als „außerhalb des Budgets“ normierte synchrone `Popen` wird zeitlich jedoch nicht aus dem Budget herausgerechnet; nach langsamer Rückkehr kann die gesamte Reserve bereits verfallen sein (neues P1-4). |

## Weitere Findings

### P1-2 — Der JSON-Decoder akzeptiert weiterhin semantisch mehrdeutige Wire-Nachrichten

**Ort:** `src/agentkit/backend/installer/mcp_conformance/protocol.py:72-98`;
fehlende Grenzfälle in `tests/unit/installer/test_mcp_conformance.py:155-205`.

Die neue Suche nach geerbter Nachsicht endet noch zu früh. Python akzeptiert
doppelte Objektnamen und behält still den letzten Wert. Meine echten
Subprozess-Gegenproben mit doppeltem `id` beziehungsweise doppeltem `result`
lieferten jeweils `ok=True`. Damit entscheidet Parser-Reihenfolge, welche von
zwei widersprüchlichen JSON-RPC-Aussagen „gilt“. Ebenso bestand
`serverInfo.name: "\ud800"`: Ein isolierter UTF-16-Surrogate wird als
Python-String weitergereicht, obwohl er keinen Unicode-Skalarwert bezeichnet.
Gültige Escape-Paare werden von Python dagegen korrekt zu einem einzelnen
Skalarwert zusammengesetzt und dürfen nicht abgelehnt werden.

RFC 8259 formuliert die Eindeutigkeit von Objektnamen als `SHOULD`, nicht als
Syntax-`MUST`; der jetzige Parser ist daher kein bloßer JSON-Syntaxfehler.
Für den hier ausdrücklich fail-closed ausgeprägten Interoperabilitätscheck ist
das still gewählte „last value wins“ dennoch ein Falsch-Grün: Andere
JSON-RPC-Implementierungen dürfen dieselbe Nachricht anders auswerten.

**Fix:** `json.loads()` mit einem `object_pairs_hook` betreiben, der doppelte
Namen auf jeder Verschachtelungsebene ablehnt. Nach dem Dekodieren alle Strings
rekursiv auf isolierte Codepoints `U+D800..U+DFFF` prüfen. Beide Fehler als
`mcp_protocol_error` ausgeben und durch echte Subprozessfälle belegen. Falls
AK3 bewusst nur die RFC-MUST-Menge prüfen soll, muss diese mildere Grenze in
FK-50 ausdrücklich entschieden werden; stiller Parser-Zufall ist keine
akzeptable Entscheidung.

### P1-3 — Zwei kombinierte Win32-Cleanup-Fehler werden weiterhin verschluckt

**Ort:** `src/agentkit/backend/installer/mcp_conformance/process.py:198-216,505-521`.

Scheitert `Popen` nach bereits erzeugtem Job Object, unterdrückt der
`except OSError`-Pfad einen zusätzlichen `CloseHandle`-/
`ProcessControlError` vollständig und meldet nach außen nur
`mcp_command_not_found`. Ein möglicherweise geleaktes Kontroll-Handle bleibt
damit unsichtbar. Außerdem prüft `_create_windows_job()` beim Fehler von
`SetInformationJobObject` den unmittelbar folgenden rohen `CloseHandle`-
Rückgabewert nicht. Genau diese kombinierten Pfade sind von den neuen
Boundary-Tests nicht erfasst.

**Fix:** Beim `Popen`-Fehler bestmöglich schließen, einen Close-Fehler aber als
`ProcessControlError` (mit dem ursprünglichen `OSError` als verketteter
Ursache) bis zum öffentlichen Resultat tragen. Im SetInformation-Fehlerpfad
den gemeinsamen geprüften Handle-Close-Helper verwenden. Enge Tests für
`Popen fails + CloseHandle fails` und `SetInformation fails + CloseHandle
fails` ergänzen. Das ist wegen AC 6 keine dokumentierbare Restgrenze.

### P1-4 — „Popen liegt außerhalb des Budgets“ ist nicht implementiert

**Ort:** `src/agentkit/backend/installer/mcp_conformance/check.py:58-70,84-92,164-183`,
`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md:525-529`.

`full_deadline` und `handshake_deadline` werden vor Command-Auflösung und vor
dem synchronen `Popen` berechnet. Blockiert `Popen` und kehrt erst spät
zurück, sind Handshake- und Teardown-Budget bereits teilweise oder vollständig
verbraucht. Das ist nicht die normierte Ausnahme „Popen selbst ist außerhalb
des kontrollierten Budgets“: Eine außerhalb liegende Zeitspanne darf das
anschließende kontrollierte Budget nicht aufzehren. Im Extremfall bleibt nach
erfolgreichem Start keine normierte Teardown-Reserve.

**Fix:** Für Launch/Cleanup eine eigene absolute Frist führen und nach
erfolgreicher `Popen`-Rückkehr das kontrollierte Gesamt- und
Handshake-Deadline-Paar neu auf `monotonic()` basieren. Alternativ müsste
FK-50 ehrlich sagen, dass die nicht unterbrechbare Launchzeit das Budget
trotzdem verbraucht; das widerspräche aber dem derzeitigen Reserveversprechen.
Ein Slow-`Popen`-Boundary-Test muss beweisen, dass nach der Rückkehr weiterhin
das vollständige kontrollierte Budget einschließlich Reserve verfügbar ist.

## Test-, Konzept- und Regressionsurteil

Die NaN-/Infinity-/Overflow-Reparatur ist materiell und durch echte
Subprozesse belegt. Der gezielte MCP-Lauf bestand mit `56 passed`; SDK-Interop,
realer Positivserver und reale Prozessbaumtests wurden nicht durch Fakes
ersetzt. Die neuen Win32-Fakes bleiben auf nicht zuverlässig erzwingbare
API-Fehler beschränkt. Eine Abschwächung der bestehenden CP10-Zusicherungen
ist nicht erkennbar.

FK-50 ist gegenüber der aktuellen Deadline-Implementierung allerdings noch
stärker als der Code (P1-4). Die Konzept-Gates sind laut nachgefahrenem Stand
grün; das ersetzt keine semantische Vertragserfüllung. Coverage wurde für
diese Runde noch nicht nachgewiesen. Vor allem ist `pytest grün` als Definition
of Done wegen P0-1 derzeit nicht reproduzierbar erfüllt.

## Akzeptanzkriterien

| AC | Urteil | Begründung |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfüllt** | Der reale CP10-/Installationspfad liefert `FAILED/mcp_command_not_found`. |
| AC 2 — kein `are-mcp`-Teilwrite | **erfüllt** | Sämtliche gewünschten Server passieren das Gate vor dem einzigen atomaren Konfigurationswrite; ein Fehler lässt den Zielinhalt unverändert. |
| AC 3 — generisch für mindestens zwei Serverdefinitionen | **erfüllt** | Mindestens zwei unterschiedliche Definitionen nutzen denselben serverunabhängigen Check. |
| AC 4 — kein Falsch-Grün | **teilweise erfüllt** | Die bisher angegriffenen Envelope-, UTF-8- und Nicht-JSON-Zahlenfälle sind geschlossen. Doppelte Objektnamen und isolierte Surrogates können jedoch einen vollständigen Handshake noch grün passieren (P1-2). |
| AC 5 — realer positiver MCP-Subprozess | **erfüllt** | Minimalserver und offizieller FastMCP-SDK-Server laufen als echte Subprozesse durch `initialize` und `tools/list`. |
| AC 6 — Ressourcensauberkeit in allen Ausgängen | **teilweise erfüllt** | Normale Erfolgs-, Timeout-, Exit-, Enkel- und kontrollierte Win32-Fehlerpfade sind belegt. Kombinierte Launch-/Job-Setup- und Close-Fehler bleiben fail-open (P1-3); die Teardown-Reserve ist nach langsamem Launch nicht garantiert (P1-4). |
| AC 7 — ARE=false bleibt SKIPPED | **erfüllt** | Feature-off bleibt `SKIPPED/vectordb_disabled` ohne Probe und Write. |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfüllt, aber DoD blockiert** | Die fachlichen Bestandstests wurden nicht abgeschwächt. Die Gesamtsuite ist unabhängig davon wegen der vorbestehenden Postgres-Race nicht hermetisch (P0-1). |
| AC 9 — FK-50 und Konzeptgates | **teilweise erfüllt** | Ursachenkatalog und Gates sind vorhanden; der Code unterschreitet den normierten Budgetvertrag noch (P1-4). |

## Gesamturteil

**Rework. AG3-164 darf noch nicht auf `completed` gesetzt oder gelandet
werden.**

### (a) Durch den Umsetzungsagenten zu beheben

- P1-1: den neuen datenbankfreien MCP-Integrationstest aus der pauschalen
  Postgres-Fixture-Bindung nehmen;
- P1-2: doppelte JSON-Namen und isolierte Surrogates entweder strikt ablehnen
  oder — nur nach ausdrücklicher normativer Entscheidung — als mildere
  Interoperabilitätsgrenze festlegen;
- P1-3: kombinierte Win32-Start-/Setup-/Close-Fehler vollständig fail-closed
  propagieren und testen;
- P1-4: die normierte Popen-/Deadline-Semantik tatsächlich implementieren und
  mit einem langsamen Launch verproben.

P1-3 und P1-4 erfüllen unmittelbar AC 6 beziehungsweise FK-50 noch nicht und
sind keine unverhältnismäßigen Restgrenzen. P1-2 ist ebenfalls klein und
wirksam genug, um den wiederholt beobachteten Parser-Default jetzt zu
schließen statt eine weitere bekannte Falsch-Grün-Stelle zu hinterlassen.

### (b) Durch den Orchestrator beziehungsweise den zuständigen State-Backend-Owner

- P0-1 als landungsblockierenden Vorbestandsdefekt routen und die
  Postgres-Katalog-/Schema-Race beheben; danach das isolierte xdist-Paar und
  die vollständige Installer-Suite mehrfach mit identischem Seed grün fahren;
- anschließend Coverage, Jenkins/Sonar, Status-/Story-Bericht sowie die
  erforderlichen Konzeptbelege vollständig nachziehen.

Der Orchestrator kann P0-1 nicht als „AG3-164 nicht schuld“ wegklassifizieren:
Die Story darf erst landen, wenn der gemeinsame Arbeitsbaum wieder eine
deterministische Pflichtsuite besitzt. Eine separate Vorab-Story für den
State-Backend-Fix wäre organisatorisch sauber, hebt die harte Landekante aber
erst nach ihrer tatsächlichen Umsetzung auf.
