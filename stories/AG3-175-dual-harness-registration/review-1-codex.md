# Codex-Review 1 (die EINZIGE Runde) — AG3-175

- **Datum:** 2026-07-27
- **Reviewer:** Codex, read-only (`write:false`), Job `job-76549c18`
- **Branch:** `feat/ag3-175-dual-harness-registration` gegen `main`, 31 Dateien, +6635/-212
- **Verdikt:** **Merge blockiert** — 7x P1, 2x P2, 1x P3, kein P0
- **Review-Budget:** verbraucht. Die Findings werden ohne weitere Review-Runde
  eingearbeitet (PO-Vorgabe, `status.yaml` Zeile 15). Der Orchestrator ist damit
  das letzte Gate und reproduziert jeden Fix selbst.

Codex' Gesamturteil: Der Kernentwurf — ein unveraenderlicher Server-Spec,
digest-gebundenes Rendering, zwei geordnete atomare Writes, Rollback — ist in
der Absicht stimmig. Blockierend sind Datenerhaltungsloecher, ein
Stale-Snapshot-Rennen, uebersprungene Conformance bei idempotenten Laeufen, ein
unvollstaendiges `cwd`-Invariant und unvollstaendige bzw. zu stark behauptete
Verifikationsevidenz.

Codex trennt durchgehend **verified by execution** von **inferred by reading**.
Diese Kennzeichnung ist beibehalten, weil ohne zweite Runde niemand eine falsche
Inferenz auffaengt.

---

## R01 — P1 — Ownership-Klassifikation kann fremde Codex-Konfiguration loeschen

**Ort:** `harness_adapters/codex_config_toml.py:317`, `:335`; Loeschung in
`installer/lifecycle/detach.py:379`; Writer-Nebenstelle `codex_config_toml.py:272`

**Verified by execution.** Codex hat syntaktisch kanonisches TOML direkt an
`classify_ownership` gegeben (ohne Dateisystem). Mit vorhandenem AK3-Hook
klassifizierten **alle** folgenden Faelle als `ak3_only`:

- leere Tabelle `[mcp_servers.story-knowledge-base]`
- `command = "foreign-tool"` mit fremden Argumenten
- `required = false`
- falscher `cwd`

**Folge:** Detach entfernt die **komplette Datei**, samt der Tabelle des Nutzers
unter dem reservierten Namen.

**Ursache (Codex, wortgleich in der Sache):** Der kanonische Byte-Vergleich
beweist nur, dass die Datei zu einem Rendering **der gefundenen Werte** passt —
nicht, dass diese Werte je von AK3 geschrieben oder besessen wurden.

Zusaetzlich akzeptiert der Writer eine leere Tabelle unter dem reservierten Namen
als *unbelegt* und fuellt sie, statt die ambivalente Belegung abzulehnen.

**Nicht betroffen (vom Praedikat korrekt erhalten):** fremde Kommentare,
BOM/unparsebare Eingabe, Inline-Table-Schreibweise, doppelte Tabellen, unbekannte
Felder. Das dritte Loch ist **Wert-/Provenienz-Identitaet**.

**Sollzustand:** Ganzdatei-Eigentum nicht aus reserviertem Namen plus kanonischer
Schreibweise ableiten. Entweder gegen die **erwartete** AK3-Registrierung/Provenienz
klassifizieren (veraenderte, unvollstaendige, ambivalente Eintraege = MIXED), oder
Detach entfernt nur exakt erkannten AK3-Inhalt und erhaelt alles andere.
Testfaelle ergaenzen: leere reservierte Tabelle, fremdes `command`,
`required = false`, veraendertes `env`/`cwd`, Unicode-Normalisierungsvarianten,
Inline-Table-Formen.

**Orchestrator-Nachpruefung: bestaetigt.** Eigene Ausfuehrung ueber
`render_canonical_codex_config` reproduzierte `ak3_only` fuer eine Tabelle mit
`command="foreign-tool"`, `args=["--evil"]`, `cwd="C:/mine"`, `required=false`
sowie fuer die leere Tabelle.

---

## R02 — P1 — Zwei Reads koennen ein neueres Before-Image an ein veraltetes Rendering binden

**Ort:** `.mcp.json`-Load `cp10.py:483`; Codex-Doppelread `cp10.py:493`;
zweiter `.mcp.json`-Read `cp10.py:502`; strukturgleich
`installer/codex_settings.py:146` (`render_project_codex_config` liest die Datei
erneut).

**Verified by execution.** Mit einem In-Memory-Fake-Pfad liess Codex
`_load_target_mcp_json` Version A parsen (enthaelt `foreign-A`) und danach
`read_bytes()` Version B zurueckgeben (enthaelt `foreign-B`). `_render_both`
lieferte:

- einen Before-Image-Fingerprint ueber **B**,
- ein gerendertes JSON abgeleitet aus **A**,
- kein `foreign-B` im Ergebnis.

Der Reread unmittelbar vor dem Write sieht B, findet Uebereinstimmung mit dem
gebundenen Before-Image und **erlaubt** damit, dass das aus A abgeleitete,
veraltete Rendering B ueberschreibt. Der Waechter, der Stale-Writes verhindern
soll, autorisiert einen.

**Sollzustand:** Die Bytes jeder Datei **genau einmal** in Phase 2 lesen, strikt
aus genau diesen Bytes parsen und rendern, und genau diese Bytes binden. Die von
CP10 benutzten Render-Helfer muessen die erfassten Bytes/das Dokument annehmen
statt den Pfad erneut zu lesen. Der Reread unmittelbar vor dem Write bleibt.

---

## R03 — P1 — Ein fremder `.mcp.json`-Server unter AK3s Namen wird still ueberschrieben

**Ort:** `installer/mcp_registration.py:380`

**Verified by execution.** Codex mergte einen bestehenden Eintrag
`story-knowledge-base` mit `command = "foreign-tool"` und einem fremden Feld.
`merge_mcp_json_servers` ersetzte das gesamte Objekt durch AK3s Wunscheintrag und
entfernte das fremde Feld.

Das widerspricht D6 (beide Dateien vor dem ersten Write konfliktgeprueft). Codex
erkennt die entsprechende Kollision, Claude Code nicht.

**Sollzustand:** Dieselbe Identitaets-/Kollisionsregel vor dem Rendern auch auf
`.mcp.json`: abweichendes `command`/`args` unter AK3-eigenem Namen = benanntes
`mcp_configuration_invalid`, null Writes; passende Identitaet = eigene Felder
aktualisieren, unbekannte erhalten, soweit vertraglich zulaessig; anders benannte
Server unveraendert. Plus ein Zwei-Dateien-Null-Write-Regressionstest.

---

## R04 — P1 — Eine unveraenderte Registrierung liefert PASS ohne erneute Conformance

**Ort:** `cp10.py:426` (Return), Probe erst `cp10.py:439`

**Inferred by reading.** Im REGISTER-Modus kehrt `changed == false` **vor**
`probe_registration` zurueck. Ein manuell byte-exakt vorbelegter Eintrag — oder
ein zuvor funktionierender Server, der **aufgehoert hat zu funktionieren** —
erhaelt PASS ohne jeden MCP-Handshake.

Das widerspricht FK-50 §50.3 wortwoertlich
(`50_installer_checkpoint_engine_bootstrap.md:590`): „bereits identische
Eintraege -> PASS (Conformance erneut bestanden)". Die `main`-Implementierung
hatte das Conformance-Gate **vor** dem Idempotenz-Return.

**Sollzustand:** Im REGISTER-Modus die Probe vor dem idempotenten PASS fahren.
DRY_RUN/VERIFY bleiben prozessfrei.

**Orchestrator-Nachpruefung: bestaetigt, und es ist eine von dieser Story
eingefuehrte Regression.** Diff gegen `main`: dort `_conformance_gate(...)` und
danach `if not changed and mcp_path.is_file(): PASS`; auf HEAD Phase 4
`if not changed: PASS` vor Phase 5 `probe_registration(...)`.

---

## R05 — P1 — Ein durchgaengig falscher, nicht-leerer `cwd` wird akzeptiert

**Ort:** `vectordb/runtime_binding.py:148`, `installer/mcp_registration.py:166`

**Verified by execution.** Ein `RuntimeBinding` mit `cwd="C:/wrong-project"` und
sonst gueltigen Produktionsfeldern wurde von `RuntimeBinding.from_env` **und**
`desired_server_from_spec` akzeptiert.

Der Digest erkennt einen **nach** der Probe geaenderten `cwd`, aber nicht einen
von Anfang an falschen, der konsistent bleibt. Der bestehende „wrong cwd"-Fall
(`tests/contract/installer/test_mcp_registration_binding.py:157`) ist nur eine
Post-Probe-Mutation, keine Validierung eines initial falschen Orts.

Produktiv liefert heute `context.project_root`; AC 5 verlangt aber ein
fail-closed Negativ-Invariant, damit eine spaetere Neuableitung es nicht still
aufweichen kann.

**Sollzustand:** Den aufgeloesten Spec-`cwd` an der produktiven
Projektionsgrenze gegen den erwarteten aufgeloesten Project-Root pruefen. Plus
ein Pre-Probe-Test „falsch, aber nicht leer", getrennt vom Digest-Mutationstest.

---

## R06 — P1 — Produktive CP10-Verdrahtung ist durch Testdoubles ersetzt, entgegen der behaupteten Evidenz und der Mock-Regel

**Ort:** `tests/integration/installer/test_codex_mcp_registration.py:114`, ferner
`:202`, `:221`; geteilte Unit-Substitution
`tests/unit/installer/checkpoint_engine/test_cp10_dual_registration.py:92`;
die Behauptung „exactly one stub" in `impl-plan.md:1267`

**Inferred by reading.** Die CP10-Tests ersetzen `_desired_mcp_servers` durch
`_conforming_desired`; die Integrationssuite nutzt zusaetzlich
`InMemoryRegistrationRepo`. Das sind Testdoubles jenseits des simulierten
`OSError` beim zweiten Write, und die Integrationsnutzung liegt **ausserhalb**
der CLAUDE.md-Ausnahme („isolierter Unit-Test technisch sonst nicht moeglich").

Der minimale MCP-Server selbst ist echt und konform; das Problem ist die
Ersetzung des **produktiven Producers**. Eine Regression, bei der CP10 aufhoert
die produktive `RuntimeBinding`/das Engine-Kommando zu benutzen, laesst diese
Integrationstests **gruen**. Auch der formatuebergreifende Contract-Test
konstruiert und rendert das gemeinsame Server-Objekt selbst
(`test_mcp_registration_binding.py:65`) — er beweist nicht, dass CP10 diese
Kette benutzt.

**Sollzustand:** Fixture-Server-Mechanik als Unit-/Functional-Abdeckung trennen
und benennen; in der Integrationsabdeckung ein echtes Produktions-Repository
verwenden; einen nicht-substituierten Test durch CP10s tatsaechliche
Ableitungsgrenze ergaenzen. Keinen produktiven
Ein-Spec-zu-Probe-zu-Write-Beweis behaupten, solange der produktive Pfad nicht
wirklich durchlaufen wird.

---

## R07 — P1 — Der Konzept-Delta-Vorschlag laesst das autoritative Konfigurationskonzept aus

**Ort:** Vorschlag auf drei Konzepte begrenzt (`impl-plan.md:1406`); neue Felder
`config/models.py:578`; CP5-Projektion `installer/runner.py:413`

**Inferred by reading.** FK-03 erklaert sich selbst zur vollstaendigen Definition
der AgentKit-Konfiguration; **jeder** konfigurierbare Parameter muss dort
dokumentiert sein
(`03_konfigurationsmodell_schemas_versionierung.md:25`). Das VectorDB-Beispiel
dort enthaelt weiterhin nur Threshold-/Candidate-Einstellungen (`:157`).

Die sieben FK-13-Positionen sind **einzeln korrekt**, der Vorschlag ist aber
unvollstaendig, weil er auslaesst:

- FK-03-Dokumentation plus Validierungs-/Default-Semantik fuer **beide**
  Endpunktfelder,
- die CP5-/Scaffold-Quelle dieser operator-eigenen Werte,
- explizite Gleichnamen-Kollisionssemantik fuer **beide** Spiegel-Dateien (von
  R03 aufgedeckt).

**Sollzustand:** Das autorisierte Konzept-/Decision-Delta auf FK-03 ausweiten und
die Zwei-Dateien-Kollisionsidentitaet spezifizieren. Die normativen Aenderungen
mit dem erforderlichen Decision Record/Trailer und den W2/W3-Governance-Checks
landen.

---

## R08 — P2 — Die Meldung eines gescheiterten Rollbacks hat keinen Regressionsbeweis

**Ort:** ungetesteter Fehlerzweig `cp10.py:640`; der bestehende Rollback-Test
prueft nur das erfolgreiche Wiederherstellen
(`tests/unit/installer/checkpoint_engine/test_cp10_dual_registration.py:253`)

**Inferred by reading and test search.** Die Implementierung liefert korrekt
`ROLLBACK FAILED (...)` und meldet den neuen Zustand ehrlich — aber **kein**
AG3-175-Test laesst `_rollback_mcp_json` selbst scheitern. Diese Negativ-
Zusicherung koennte ohne roten Test regredieren.

**Sollzustand:** Einen minimal gescoptem `OSError` beim Rollback-Write/-Delete
nach dem Fehlschlag des zweiten Writes. Assertions auf
`registration_incomplete`, auf das explizite „rollback failed"-Detail und auf die
**tatsaechlichen** Restbytes.

---

## R09 — P2 — I/O-Fehler beim Lesen entkommen dem benannten Checkpoint-Ergebnispfad

**Ort:** `installer/codex_settings.py:193`, Rohread `:112`; CP10-Rereads
`cp10.py:556`

**Inferred by reading.** `write_codex_settings` dokumentiert `InstallationError`
fuer unlesbare Konfiguration, faengt aber nur `CodexConfigError`; ein
ACL-/Share-Lock-`OSError` entkommt. CP10 faengt um die Codex-Rereads ebenfalls nur
`CodexConfigError`, nicht `OSError`, und der `.mcp.json`-Bound-Before-Reread ist
ungeschuetzt.

Das bleibt fail-closed — es wird nichts ueberschrieben — bricht aber die
Checkpoint-Engine mit einer **rohen Exception** ab statt mit einem benannten
FAILED-Ergebnis.

**Sollzustand:** Read-`OSError` vor jedem Write in das etablierte
`configuration_invalid`-Ergebnis uebersetzen, beide Dateien byte-fuer-byte
erhalten. CP8 soll sie konsistent in `InstallationError` huellen.

---

## R10 — P3 — Der Dependency-Kommentar nennt einen nicht existierenden Writer-Pfad

**Ort:** `pyproject.toml:47`

**Inferred by reading.** Der Kommentar nennt
`harness_adapters/codex/config_toml.py`, implementiert ist
`harness_adapters/codex_config_toml.py`.

**Sollzustand:** Kommentar auf den tatsaechlichen Ort korrigieren.

---

## Akzeptanzkriterien (Codex-Verdikt)

| AC | Verdikt | Begruendung |
|---|---|---|
| **AC1** | **teilweise** | Frische und wiederholte Writes konvergieren, der CP8-Ueberschreiber ist behoben. R02 kann eine konkurrierende Fremdaenderung verlieren, R03 ueberschreibt einen fremden `.mcp.json`-Eintrag unter reserviertem Namen. |
| **AC2** | **erfuellt** | Beide Renderer projizieren denselben unveraenderlichen `DesiredMcpServer`; Feldgleichheit und Codex `required = true` sind festgenagelt. |
| **AC3** | **erfuellt** | Pfade projektlokal, `CODEX_HOME` unbenutzt, Geschwisterprojekt-Isolation und ein echter, windowsfaehiger Junction-Guard. Die ersten zwei Tests sind korrekt als Regressionssperren beschrieben, nicht als Revert-Rot-Beweise. |
| **AC4** | **teilweise** | Geaenderte Registrierungen werden vor dem Write geprobt, ein Probe-Fehlschlag schreibt nichts. Byte-identische bestehende Registrierungen umgehen die Conformance vollstaendig (R04). |
| **AC5** | **teilweise** | Der Digest deckt Spec-Werte, beide gerenderten Texte und absent-vs-empty-unterscheidbare Before-Image-Fingerprints; Post-Probe-Aenderungen blockieren Writes. Ein initial falscher, nicht-leerer `cwd` wird akzeptiert, und die produktive CP10-Verdrahtung ist in den zentralen Mechanik-Tests substituiert (R05/R06). |
| **AC6** | **teilweise** | Write-Reihenfolge, absent-vs-empty-Rollback, erfolgreiches Rollback, Retry-Konvergenz und die ehrliche Crash-Window-Dokumentation liegen vor. Der inkonsistente Snapshot kann ein veraltetes Ueberschreiben autorisieren, `.mcp.json` hat keine Konfliktpruefung, und die Meldung eines gescheiterten Rollbacks ist ungetestet. |
| **AC7** | **teilweise** | Die dokumentierte Parser-/Typ-/Junction-Matrix ist breit implementiert. Leere/veraenderte reservierte Tabellen koennen als AK3-eigen gelten und spaeter geloescht werden, damit ist der Erhalt nicht vollstaendig (R01). |

---

## Architektur- und Scope-Urteile (Codex)

- **Writer-Platzierung: korrekt.** Die formale Gruppe `harness_adapters_codex`
  macht `agentkit.harness_client.harness_adapters.codex` internal, und FK-76
  §76.9 verbietet den Import dieses konkreten Adapters. Ein Schwestermodul neben
  `settings_writer.py` erfuellt beide Bedingungen.
- **Scope-Ausweitung: korrekt und notwendig.** Writer-Konsolidierung,
  `write_codex_settings`, Detach-Klassifikation und Loeschung der Bundle-Kopie
  schliessen **einen** Architekturuebergang. **Kein weiterer** aktiver
  `.codex/config.toml`-Writer und kein weiterer byte-gleichheits-gekoppelter
  Aufrufer gefunden.
- **Vorbestehender Datenverlust-Defekt:** Diagnose korrekt, **beide** Ursachen
  adressiert. Der Zwei-Lauf-Test ist strukturell revert-rot gegen jede der beiden
  Ursachen; historische Reverts konnte Codex nicht ausfuehren.
- **ARE-Spiegelung:** Alle gewuenschten Server zu projizieren ist die **bessere**
  Konzeptlesung — FK-76 sagt „je Server" und definiert Codex als Spiegel. Der
  Ein-Zeilen-Filter existiert real, wuerde aber einen konzeptinkonsistenten
  Sonderfall einfuehren. Das generische Verhalten ist **kein** Defekt.
- **Executable-Modul und Env:** `-m agentkit.backend.vectordb.engine` ist
  korrekt. Die fuenf registrierten Schluessel enthalten das prozessseitig
  erforderliche Concepts-Verzeichnis, und die Superset-Sperre wuerde einen neu
  hinzugefuegten Pflicht-Env-Read vor dem Connect fangen.
- **Digest-Erreichbarkeit:** Ausser der offen eingeraeumten Receipt-Faelschung auf
  Python-Ebene verlangt der produktive Write-Pfad ein `ProbedRegistration` und
  ruft `verify_binding`. **Kein** gewoehnlicher CP10-Pfad schreibt nach
  fehlgeschlagenem oder fehlendem Receipt. Der Idempotenz-Fruehausstieg ist eine
  **separate** Conformance-Umgehung: R04.

## Restrisiken (Codex-Einordnung)

- **Live-Weaviate fuer produktives AC1:** korrekt als akzeptierte Evidenzgrenze
  unter dem ausdruecklichen E2E-Ausschluss der Story eingeordnet. CI beweist
  Mechanik und Offline-Startfaehigkeit, **nicht** einen produktiv erfolgreichen
  CP10-Lauf.
- **Unlesbare bestehende Codex-Datei:** Verweigerung des Ueberschreibens ist
  korrektes FAIL-CLOSED. Die rohe Exception statt eines benannten Ergebnisses ist
  R09.
- **Ein kosmetisches CRLF→LF-Rewrite:** akzeptabel.
- **Gesperrtes `localhost:50051`:** korrekt unter ratifiziertem D2, kein Defekt
  dieser Story.
- **Zwei-Dateien-Crash-Window:** korrekt als nicht-atomar und retry-konvergent
  beschrieben. Die Konzeptaktualisierung braucht noch Autorisierung und Landung.

## Test-Ehrlichkeit (Codex-Urteil)

- Die zwei offengelegten Nicht-Revert-Rot-Tests (isoliertes `CODEX_HOME`,
  Unsichtbarkeit aus dem zweiten Projekt) sind **korrekt** als Regressionssperren
  beschrieben.
- Der simulierte `OSError` beim zweiten Write ist minimal gescopt; **keine**
  zweite Art injizierten Fehlers gefunden.
- **Aber:** er ist nicht das einzige Testdouble — `_desired_mcp_servers` ist in
  den CP10-Mechanik-Tests durchgaengig ersetzt, die Integration nutzt ein
  In-Memory-Repository. Das ist R06.
- Der direkte Produktiv-Engine-Test ist nuetzlich, umgeht aber CP10. Der
  formatuebergreifende Contract-Test ist nuetzlich, konstruiert das gemeinsame
  Objekt aber selbst. **Keiner** von beiden schliesst die Luecke im
  Produktionsverdrahtungs-Beweis.
- Die Meldung eines gescheiterten Rollbacks ist ungetestet: R08.

## Bestaetigt ausserhalb des Scopes

- `remove_codex_settings`: kein produktiver Aufrufer, Detach ist der echte
  Lifecycle-Pfad.
- Drei `agentkit-hook-codex`-Literale plus Console-Entry: vorbestehende
  Namensdopplung ohne neue Verhaltenskopplung.
- `server_command_from_mcp_entry`: jetzt ohne produktiven Aufrufer, bleibt aber
  bestehende oeffentliche AG3-164-Oberflaeche.
- Vorbestehender Telemetrie-Importzyklus: von diesem Diff unberuehrt und nicht an
  die Dual-Registrierung gekoppelt.

## Was Codex NICHT verifizieren konnte

Ausdruecklich benannt, weil eine ungeprueft als sauber praesentierte Flaeche
schlechter ist als eine eingeraeumte Luecke:

- **Keine** historischen Revert-Rot-Varianten ausgefuehrt — der Read-only-Modus
  verbietet Checkouts, Worktrees und temporaer modifizierte Kopien.
- Suite, Coverage, mypy, ruff, Endpunktmatrix und Dependency-Pin **nicht**
  nachgefahren; Codex stuetzt sich auf die im Auftrag mitgelieferten,
  orchestratorseitig verifizierten Ergebnisse.
- **Keine** dateisystem-mutierenden Write-, Rollback- oder Junction-Tests
  ausgefuehrt. Nur die In-Memory-Adversarial-Reproduktionen sind als
  ausfuehrungsverifiziert markiert.
- Ein produktiver MCP-Conformance-Erfolg gegen eine **laufende** Weaviate bleibt
  unverifiziert (von der Implementierung selbst offengelegt).
- **`llm_hub` war nicht verfuegbar:** beide Versuche erreichten
  `127.0.0.1:9600` und liefen in `ECONNREFUSED`. Codex' eigene vorgeschriebene
  Gegen-Review ist damit **nicht gelaufen**.
- **Jenkins und Sonar liefen in Timeouts**, und `check_remote_gates.ps1` hatte in
  dieser Shell keine Credentials. Codex kann **nicht** unabhaengig aussagen, dass
  diese Pflicht-Gates gruen sind.
