---
concept_id: META-DEC-2026-08-04-EIN-WRITER-EIN-VERTRAG
title: Concept-Decision-Record — Ein Writer, zwei Listener, ein Claim-Vertrag
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to:
  - target: FK-10
    scope: runtime-deployment
    reason: FK-10 besitzt Boot-Ablauf, Listener und Writer-Lebenszyklus
  - target: FK-15
    scope: api-security
    reason: FK-15 besitzt Auth-Kontexte, Principal- und Routengrenzen
  - target: FK-30
    scope: human-governance-guard-paths
    reason: FK-30 besitzt die Guard-Ausnahme fuer offizielle menschliche Story-Administrationspfade
  - target: FK-41
    scope: failure-corpus-cli-and-writes
    reason: FK-41 besitzt die vier mutierenden Failure-Corpus-CLI-Verben und ihre State-Wirkungen
  - target: FK-50
    scope: installer-writer-and-asynchronous-third-party-self-test
    reason: FK-50 besitzt CP7 bis CP9 sowie den Lifecycle des asynchronen Branch-Plugin-Conformance-Self-Tests
  - target: FK-51
    scope: upgrade-writer
    reason: FK-51 besitzt den UP-04-Hook-Migrationsvertrag
  - target: FK-53
    scope: story-reset
    reason: FK-53 besitzt CLI-, Audit- und Reset-Service-Vertrag
  - target: FK-58
    scope: story-exit
    reason: FK-58 besitzt CLI-, Ownership- und Exit-Service-Vertrag
  - target: FK-91
    scope: api-and-claim-contract
    reason: FK-91 besitzt API-, CLI-, Idempotenz- und Claim-Vertrag
supersedes:
  - target: META-DEC-2026-08-03-ERSTZUGANG-BOOTSTRAP
    scope: control-plane-process-topology-and-auth-orphan-recovery
    reason: Der PO-Entscheid vom 2026-08-04 ersetzt getrennte Listener-Prozesse und eine Auth-Erfolgsrekonstruktion durch einen Writer-Prozess und sendergebundene Startup-Finalisierung
  - target: META-DEC-2026-08-02-PORT-9702-SINGLE-OWNER-UND-ENDPUNKT-HERKUNFT
    scope: separately-startable-serve-profiles
    reason: Der PO-Entscheid vom 2026-08-04 ersetzt die einzeln startbaren Profile durch einen gemeinsamen Zwei-Listener-Start; Port-Ownership und Endpunkt-Herkunft bleiben bestehen
superseded_by:
tags: [meta, decision-record, control-plane, single-writer, claims, auth, tls, AG3-214]
formal_scope: prose-only
---

# Concept-Decision-Record — Ein Writer, zwei Listener, ein Claim-Vertrag

Datum: 2026-08-04. Record gemaess META-CONCEPT-CONSISTENCY P3/W4 fuer
AG3-214 und die zwei PO-Entscheide vom 2026-08-04.

## 1. Anlass

FK-91 verlangt genau eine aktive Control-Plane-Writer-Instanz pro Datenbank.
FK-10 verlangte zugleich zwei getrennte `agentkit serve`-Prozesse, obwohl beide
dieselbe vollstaendige Anwendung starteten, dieselbe persistierte
Backend-Identitaet inkrementierten und vor Request-Annahme Claims frueherer
Inkarnationen reconciliierten. Der zweite empfohlene Prozess konnte deshalb den
noch lebenden ersten Writer wie einen abgestuerzten Vorgaenger behandeln.

Daneben liess der generische In-Flight-Guard seine Claim-Absenderfelder bewusst
`NULL`. Der `op_id`-Primaerschluessel und der Status `claimed` verhinderten zwar
eine zweite Ausfuehrung, beantworteten aber nicht, ob der Claim-Halter noch
lebt. Nach einem Absturz blieb nur der administrative Abbruch, obwohl FK-10 und
FK-91 fuer jeden Claim die eigene Startup-Reconciliation festlegen.

Der Boot- und Registrierungsablauf in FK-10 sowie Auth-Katalog und
Erst-Credential-Ausnahme in FK-91 stammten ausserdem aus dem Stand vor AG3-180;
die dokumentierten Serve-Kommandos konnten ohne Zertifikatsparameter keinen
gueltigen HTTPS-Listener starten.

## 2. Entscheidung

### 2.1 Eine Datenbank hat einen Writer-Prozess mit zwei Listenern

`agentkit serve` startet UI-BFF und Project-API gemeinsam. Beide Listener
teilen exakt eine Control-Plane-Anwendung, eine Boot-Identitaet, eine
Startup-Reconciliation und einen Writer-Lebenszyklus. Getrennte Profilprozesse
und einzeln startbare Writer-Listener entfallen; FK-91s Single-Writer-Vertrag
wird nicht abgeschwaecht.

Vor jeder Aenderung der persistenten Boot-Inkarnation erwirbt der Prozess einen
datenbankweiten, PostgreSQL-sessiongebundenen Advisory-Lock ohne Wartepfad. Der
Lock bleibt fuer die gesamte Listener-Lebensdauer auf der Verbindung gehalten,
ueber die saemtliche im aktiven Writer ausgefuehrten State-Operationen
serialisiert werden. Ein
Konkurrent scheitert mit
`ControlPlaneWriterAlreadyActive`, bevor er Inkarnation oder Claims beruehrt.
Verliert der Writer seine Lock-Session, scheitern damit auch laufende
Transaktionen; der alte Prozess versucht den Lock nicht neu zu erwerben. Ein
applikationseigener Liveness-Monitor prueft die Lease aktiv und regelmaessig
ueber dieselbe reservierte Session, sodass auch ein untaetiger Writer den
serverseitigen Session-Verlust ohne folgenden HTTP-Request erkennt. Beim
geordneten Shutdown werden angenommene Handler und asynchrone Writer-Futures
vor Unlock vollstaendig gedraint. Bei Lease-Verlust sperrt der fatale
Abbruchzustand die Finalisierung noch laufender Futures; es gibt weder
Pool-Fallback noch Late-Commit.

Diese Reihenfolge ist tragend: `Lock -> Inkarnation -> Reconciliation -> beide
Sockets -> Request-Annahme`. Dadurch existiert kein produktiver Pfad, auf dem
ein abgewiesener Zweitstart Claims des lebenden Writers zu Alt-Claims macht.
Die produktive Serve-Grenze prueft diesen Vertrag selbst: Auch eine injizierte
Anwendung oder ein ersetzter Startup-Hook darf keinen Socket binden, bevor die
Anwendung eine gehaltene Writer-Lease nachweist. Lease-Pflicht ist der sichere
Anwendungsdefault; eine explizit leasefreie Anwendung bleibt eine direkte
Testnaht und wird am Servereintritt abgewiesen.

### 2.2 Die entfallene Prozessgrenze wird als In-Prozess-Grenze hergestellt

Die beiden Listener erhalten getrennte Auth-Middleware-Instanzen und getrennt
konfigurierbare Bind-Adressen. Sie teilen nur die autoritativen Credential-,
Session- und Token-Owner. Eine Surface-Policy erzwingt die Listenerrechte vor
dem BC-Router:

- Jeder Bind ist exklusiv. Eine bereits belegte Listener-Adresse laesst den
  gesamten Zwei-Listener-Start fehlschlagen; Adresswiederverwendung mit einem
  fremden Prozess ist keine zulaessige Betriebsform.
- Der UI-BFF nimmt keine Project-Token-Principals an und exponiert keine
  Project-Edge-, Installer-, Telemetrie- oder maschinenbezogenen
  Governance-Routen.
- Die Project-API exponiert keine Dashboard-/Planning- und
  Takeover-Approval-UI-Routen.
- Login und die ausdruecklich Strategen-geschuetzten administrativen
  Auth-Routen bleiben auf beiden Listenern erreichbar; deren Autorisierung
  bleibt principal-basiert.
- `POST /v1/projects` ist der eng begrenzte adminseitige Bootstrap fuer den
  kernseitigen Projektkontext, der vor der ersten Tokenausstellung bestehen
  muss. Er kann nur einen noch nicht vorhandenen, damit credential-losen
  Projektkontext anlegen; ein vorhandener Key endet ohne Mutation in `409`.
- Strategen-Sessions werden auf projektfachlichen Project-API-Routen `403`
  abgewiesen; nur die expliziten Auth- und Human-Governance-Routen bleiben dort
  fuer sie offen.
- Administrative Story-Splits, Story-Resets, Story-Exits und Admin-Aborts sind
  solche expliziten Human-Governance-Routen. Alle vier Operator-Verben
  authentisieren sich produktiv per Strategen-Login, Session-Cookie und CSRF.
  `split-story`, `reset-story` und `exit-story` senden ihre fachlichen
  Parameter an den aktiven Writer; nur dort wird der jeweilige Domain-Service
  unter der bereits gebundenen Lease-Identitaet gebaut. Die handelnde Identitaet
  stammt aus der authentisierten Session, nicht aus einer Payload-Attestierung;
  beim Exit loest der Writer die aktive Ziel-Session aus seinem Ownership-State
  auf. Diese drei kurzlebigen CLI-Pfade fuehren weder Boot-Reconciliation noch
  direkte State-Mutationen aus. Auch `watch-worker` schreibt Worker-Health nur
  ueber den vorhandenen REST-Repository-Adapter und oeffnet keinen lokalen
  State-Writer. Die Failure-Corpus-Verben `add-incident`, `review-patterns`,
  `review-checks` und `effectiveness-report` authentisieren sich ebenfalls per
  Strategen-Login und erreichen projektgeskoppte HTTPS-Routen; erst der aktive
  Writer baut dort `ProjectionAccessor` und `FailureCorpus`. `suggest-patterns`
  und `list-checks` bleiben read-only.
  Alle vier Mutationen legen ihr client-beigestelltes `op_id` vor dem Transport
  offen und verwenden den gemeinsamen Claim-, Body-Hash-, Replay- und
  In-Flight-Vertrag. Da sie keinen lokalen Story-/Session-Guard-State
  materialisieren, liefern sie wie die Installer-Validierungen kein Project-
  Edge-Bundle; der typisierte Mutationsentscheid und der Operation-Record sind
  ihr vollstaendiges Resultat.
  Ihre Mehrschrittwirkungen laufen zusammen mit der terminalen Claim-
  Finalisierung in einer Transaktion auf der reservierten Writer-Session. Das
  schliesst insbesondere APPROVED zwischen Story-Anlage und ACTIVE-Save, REVISE
  zwischen REJECTED- und neuer DRAFT-Revision sowie den Effektivitaetslauf
  zwischen zwei Check-Saves. Ein Fehler rollt alle Schritte zurueck; der Claim
  wird erst danach fuer denselben `op_id` wieder ausfuehrbar.

Eine Route, die nicht zur Surface gehoert, wird wie eine nicht exponierte Route
behandelt. Damit ersetzt die In-Prozess-Grenze die fruehere getrennte
Exponierbarkeit, ohne eine nicht mehr existierende Prozessisolation zu
behaupten.

### 2.3 Jeder In-Flight-Claim traegt denselben Absendervertrag

Auch der generische Guard persistiert `backend_instance_id`,
`instance_incarnation` und `operation_epoch`. Seine Boot-Identitaet ist
unveraenderlich an den Lease-Owner dieser Laufzeit gebunden und wird nicht pro
Claim aus dem veraenderlichen DB-Singleton gelesen; ein Claim ohne gebundene
Lease-Identitaet ist unzulaessig. Diese Anforderung gilt nicht nur fuer den
generischen Guard: jede Control-Plane-Claim-Schreibgrenze weist einen
`claimed`-Record ohne positiven `operation_epoch`, `backend_instance_id` oder
`instance_incarnation` hart ab. Reset und Exit claimen vor ihrer ersten
Mutation und terminalisieren per Claim-Owner-CAS derselben Epoche. Die
Startup-Reconciliation scannt damit Control-Plane-Runtime- und generische
Claims ueber denselben Identitaetszaun. Fuer Tokenanlage, Tokenwiderruf und
Passwortrotation rekonstruiert sie mangels dauerhafter eindeutiger Zuordnung
keinen Erfolg. Da diese Auth-Vorgaenge keine Engine-Schreibwirkung besitzen,
finalisiert sie den eigenen frueheren Claim ohne Admin-Eingriff als `failed`.
Das behauptet keine Ruecknahme einer moeglicherweise bereits publizierten
Credential-Wirkung, beendet aber den Claim und sperrt die erneute Ausfuehrung
unter derselben `op_id`; ein Retry bleibt mit `409 operation_conflict`
blockiert.

Fuer atomare storylose Installer- und Failure-Corpus-Operationen ist ein nach
einem Bootwechsel noch `claimed` stehender Record selbst der Beweis, dass weder
Domainwirkung noch Finalisierung committet hat. Die Startup-Reconciliation gibt
diesen eigentuemer- und epochengefencten Placeholder frei, sodass derselbe
`op_id` konvergiert. Das nullable `story_id` bleibt dabei `null`; der
Pseudo-Sentinel `"None"` ist kein zulaessiger Wert.

AG3-137 und AG3-138 tragen keinen Gegengrund zu diesem Entscheid: AG3-137 nennt
einen Claim ohne Instanzidentitaet als ungueltigen Negativpfad; AG3-138 verlangt
ausdruecklich, dass jeder neue Claim gestempelt wird. Der alte Guard-Kommentar
begruendete nur den Doppelausfuehrungszaun, nicht die davon unabhaengige
Lebendigkeits- und Recovery-Frage. Es gibt keinen belegten Pfad, auf dem die
Boot-Identitaet im gestarteten Writer nicht ermittelbar waere.

### 2.4 Registrierung, Auth-Katalog und TLS folgen dem heutigen Lauf

Der Client-Bediener speichert und prueft das ausserhalb AK3 ausgehaendigte
Project-Token mit `agentkit auth store-token` vor `register-project`.
`register-project` liest kein Strategenpasswort, erzeugt keine temporaere
Session und verwendet in CP7, CP10d und allen weiteren Requests ausschliesslich
die aktive Projekt-Credential.

Der vorgelagerte Backend-Admin legt einen noch nicht vorhandenen kernseitigen
Projektkontext ueber das strategengeschuetzte `POST /v1/projects` an und stellt
danach das erste Token aus. Dieser Bootstrap ist nicht Teil von
`register-project`, nimmt keine Thin-Client-Arbeit vorweg und kann ein bereits
vorhandenes Projekt weder aktualisieren noch erneut anlegen.

Die serverseitige Strategen-Ausnahme der Third-Party-Validation ist nur
zulaessig, solange fuer den Projektkontext noch kein Project-Token existiert;
ab dem ersten Token wird sie erzwungen abgewiesen. Der heutige
Registrierungspfad benutzt diese Ausnahme nicht. FK-91 fuehrt die sechs realen
Auth-Verben und ihre tatsaechlichen Signaturen, insbesondere `store-token`,
`issue-token` ohne `--project-root` und `revoke-token` ohne Laptop-Pfad.

Der Core-Start nennt beide Bindings und die TLS-Dateien in einem Kommando. Die
Zertifikate stammen aus der Host-PKI oder werden fuer einen expliziten lokalen
Wegwerf-Core mit dem in FK-10 benannten OpenSSL-Kommando erzeugt. Plain HTTP und
ein Serve-Kommando ohne Zertifikatsquelle bleiben unzulaessig.

Die gleiche Rollen- und Writer-Grenze gilt fuer bestehende administrative
Operator-Verben: `admin-abort` verwendet nicht den anonymen Maschinen-Transport,
sondern eine echte Strategen-Session. `split-story`, `reset-story` und
`exit-story` sind duenne HTTPS-Adapter auf ihre projektgeskopten Routen des
aktiven Writers; die bisherigen In-Process-Kompositionen im separaten
CLI-Prozess entfallen.

**BEHOBENER VERSTOSS — Stand 2026-08-05, AG3-214 Runde 4:**
`register-project` und `upgrade-project` bauten in
`src/agentkit/backend/cli/installer_commands.py` in den Funktionen
`_cmd_register_project` bzw. `_cmd_upgrade_project` produktive Repositories im
CLI-Prozess. Die damaligen Aufrufketten in
`src/agentkit/backend/installer/runner.py`,
`src/agentkit/backend/installer/upgrade/entry.py` in `run_checkpoint_upgrade`
und `src/agentkit/backend/installer/upgrade/engine.py` in
`up_04_migrate_hooks` schrieben
`project_registry`, `projects`, Skill-Bindings und Governance-Hook-
Registrierungen ohne Writer-Lease. Heute pruefen beide Verben vor der ersten
projektbezogenen lokalen Wirkung per Project-Token-geschuetztem HTTPS-Read den
aktiven Writer. CP 7, jeder Skill-Binding-State und CP 9/UP 04 laufen ueber
projektgeskoppelte Installer-Routen; nur der Writer baut die produktiven
Repositories. Das sichtbare Root-`op_id` erzeugt stabile Child-Claims pro
Wirkungsart und verwendet den gemeinsamen Body-Hash-, Replay-, Mismatch- und
In-Flight-Vertrag. Unerreichbarkeit endet benannt fail-closed; ein lokaler
State-Fallback existiert nicht.

Die Readiness-Grenze liegt vor jeder lokalen Projektwirkung, einschliesslich
dem Anlegen von Verzeichnis und `credentials.lock` und dem Entfernen eines
identischen Pending-Credential-Sidecars. Vor dem Readiness-Read wird Credential-
State ausschliesslich gelesen. Ein unerreichbarer Writer laesst daher jedes
lokale Artefakt unveraendert.

CP 7 committen `project_registry`, die sichtbare `projects`-Entitaet und die
terminale Claim-Finalisierung gemeinsam auf der reservierten Session. Ein
Fehler des zweiten Saves oder ein Sessionverlust vor Finalize rollt beide
Tabellen zurueck; derselbe `op_id` fuehrt CP 7 erneut aus und konvergiert, statt
einen FAILED-Teilzustand zu replayen.

CP 8 behandelt einen Antwortverlust nach einem Save als unklare Wirkung. Der
Dev-Prozess loescht die moeglicherweise persistierte Binding-Zeile dann nicht
unter einem separaten Claim, weil ein Same-`op_id`-Retry sonst nur das
gespeicherte Save-Ergebnis replayen, die geloeschte Zeile aber nicht
wiederherstellen wuerde. Er meldet den Lauf stattdessen ehrlich als partiell;
der Retry behaelt dieselben Child-Claims und konvergiert bis `VERIFIED`.

### 2.5 Entscheidung zum Erstregistrierungs-Sonderfall

Entschieden ist Alternative **(a): Ebene-3-Registrierung und Upgrade setzen
einen erreichbaren aktiven Writer voraus**. Der Installer erwirbt die Lease
nicht selbst. Das folgt aus den bereits geltenden Ankern: FK-10s Ebene 1 ist
Voraussetzung fuer Ebene 3; `POST /v1/projects` legt zuvor den kernseitigen
Projektkontext an, danach stellt der Backend-Admin das erste Project-Token aus
und `auth store-token` publiziert es auf der Dev-Seite. Erst dann beginnt
`register-project`. Der Zeitpunkt ist die erste Ebene-3-Registrierung, nicht
der Aufbau des Ebene-1-Cores.

Die Entscheidung haelt ausserdem die Remote-Topologie intakt: Ein Dev-
Installer, der selbst eine PostgreSQL-Session-Lease erwuerbe, waere ein zweiter
Control-Plane-Writer ohne Listener-, Liveness-, Drain- und Startup-
Reconciliation-Lebenszyklus. Er koennte den projektlokalen Pfad nur in einer
topologisch lokalen Sonderform dereferenzieren und wuerde so einen zweiten
Betriebsvertrag schaffen. Stattdessen beweist `writer-ready` Authentisierung,
Versionskompatibilitaet und die bereits von der Anwendung gehaltene Lease vor
jeder Installationswirkung. Bei der Erstregistrierung verwendet der Handshake
die read-only aus dem zentralen Zielmanifest ermittelte geplante Bundle-Version,
weil der projektlokale Binding-Lock erst in CP 8 entsteht.

## 3. Verworfene Alternativen

- Ein nicht schreibender UI-BFF-Proxy wurde verworfen: er haette eine neue,
  technisch zu erzwingende Nicht-Schreib-Rolle und einen zweiten Runtime-Pfad
  geschaffen.
- Zwei koexistierende Writer wurden verworfen: dies haette FK-91s feste
  Single-Writer-Groesse abgeschwaecht.
- Ein reines Boot-Advisory-Lock wurde verworfen: es serialisiert nur den
  Inkarnationsschritt, verhindert aber keinen zweiten Writer waehrend der
  Listener-Lebensdauer.
- PID-, TTL- und Heartbeat-Heuristiken wurden verworfen: sie koennen
  Prozesslebendigkeit nicht autoritativ fuer die Datenbank entscheiden und
  widersprechen dem wanduhrfreien Claim-Vertrag.
- Ein stiller lokaler Installer-Fallback wurde verworfen: Er reproduziert den
  zu behebenden leasefreien Writer und macht Unerreichbarkeit zur
  Doppelausfuehrungsgefahr.
- Eine vom Installer fuer CP 7 bis CP 9/UP 04 selbst gehaltene Lease wurde
  verworfen: Sie schafft einen zweiten, verkuerzten Writer-Lifecycle ausserhalb
  der Control-Plane-Anwendung und widerspricht dem Ebene-1-vor-Ebene-3-Anker.

## 4. Impact-Sweep (P3/W4)

Geprueft wurden FK-10 als Owner von Boot, Deployment, TLS und Writer-Lifecycle,
FK-15 als Owner der aeusseren API-Sicherheitsgrenzen, FK-30 als Owner der
offiziellen Guard-Ausnahmen, FK-41 als Owner der Failure-Corpus-Mutationen,
FK-50 als Owner von CP7 bis CP10d, FK-51 als Owner des Upgrade-Flows,
FK-53 und FK-58 als Owner der
Reset-/Exit-Pfade sowie FK-91 als Owner von API, CLI,
Idempotenz und Claims. Die Zielstellen besitzen den jeweiligen Scope: der
Record setzt keine neue Grundentscheidung neben ihnen, sondern detailliert die
PO-Entscheide entlang ihrer bestehenden Single-Writer-, Principal-, Claim- und
Human-Governance-Anker.

Die Aussagen sind untereinander widerspruchsfrei: Der Lebensdauer-Lock wird vor
der Inkarnation erworben; deshalb kann nur der Lock-Owner reconciliieren. Beide
Listener teilen diese Identitaet; deshalb sind generische Claims immer einem
eindeutigen Boot zuordenbar. Die weggefallene Prozessgrenze wird nicht nur aus
FK-15 entfernt, sondern durch Auth-Kontexte, Bindings und Route-Policies
ersetzt. Der neue Registrierungsablauf stimmt mit der bereits von FK-15
geforderten Rollenfolge und der realen CLI ueberein. Auth-Orphans eroeffnen
keinen dritten Endweg: Die Start-Rekonsiliierung beendet den eigenen frueheren
Claim ohne Admin-Eingriff als `failed`; eine Erfolgsrekonstruktion oder erneute
Ausfuehrung unter derselben `op_id` findet nicht statt.

Die in den Runden 1 bis 3 umgesetzten Pfade sind ohne Zusatzannahmen
ausformuliert: FK-10 nennt die Zertifikatsquelle und das vollstaendige
Startkommando; FK-91 nennt die vollstaendigen Auth-Signaturen; der Writer-Lock
benennt Akquisitionszeitpunkt, Lebensdauer, aktiven Liveness-Probe,
Request-Fence, Hintergrund-Drain, Listener-Abbruch bei Verlust und Fehlergrund.
FK-50 bindet die `202`-Future bis zur terminalen Finalisierung an diesen
Lifecycle. Die produktiven Operator-Pfade fuer Split, Reset, Exit,
Admin-Abort und die vier mutierenden Failure-Corpus-Verben nennen Endpoint,
Strategen-Authentisierung und die ausschliessliche Ausfuehrung im
lease-haltenden Writer; FK-41, FK-53 und FK-58 verankern ihre
Mutationsgrenzen. Runde 4 schliesst den in Abschnitt 2.4 historisch benannten
Installer-Verstoss entlang der Ebene-1-, Project-Token- und Single-Writer-
Anker. Damit ist der Writer-Vertrag systemweit umsetzbar, ohne einen zweiten
Installer-spezifischen Lease-Lifecycle einzufuehren.
Runde 7 zieht die Durchsetzung an die Serve-Grenze, legt die Readiness vor jedes
lokale Credential-Artefakt und schliesst bei Installer- und Failure-Corpus-
Mutationen Domainwirkung und Claim-Finalisierung transaktional zusammen. Damit
ist ein frueherer storyloser `claimed`-Record nach Bootwechsel ein belastbarer
Rollback-Beweis und kann fuer Same-`op_id`-Konvergenz freigegeben werden.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-10 §10.2.1 | geaendert | Registrierungsfolge verwendet vorab gespeicherte Project-Credential statt temporaerer Strategen-Session. |
| FK-10 §10.2.5 und §10.7 | geaendert | Ein vollstaendiges Zwei-Listener-Kommando nennt Zertifikatsquelle, TLS-Dateien, Bindings und Ports. |
| FK-10 §10.5.4 | geaendert | Single-Writer ist als datenbankweiter Lebensdauer-Lock vor Inkarnation und Reconciliation erzwungen; die Serve-Grenze bindet auch bei injizierter Anwendung oder Startup-Hook keinen Socket ohne nachweislich gehaltene Lease. |
| FK-15 §15.10.2–§15.10.4 | geaendert | Die nicht mehr existente Prozessgrenze wird durch getrennte Auth-Kontexte, Bind-Adressen und Surface-Rechte ersetzt; Session-Owner lebt im einen Prozess. |
| FK-30 §30.3.3 | geaendert | Reset, Split und Exit sind menschliche Guard-Ausnahmen ausschliesslich ueber ihre strategengeschuetzten Writer-Routen, nicht lokale Service-Kompositionen. |
| FK-41 §41.9 | geaendert | Vier mutierende Failure-Corpus-Verben laufen als Strategen-HTTPS-Adapter ueber den aktiven Writer und den gemeinsamen `op_id`-/Claim-Vertrag; die zwei Read-only-Verben bleiben unveraendert. |
| FK-50 CP 7–CP 10d | geaendert; frueherer CP-7–CP-9-Verstoss behoben | CP 7 konvergiert `project_registry`, `projects` und Claim-Finalisierung in einer Writer-Transaktion; ein zweiter Save- oder Sessionfehler rollt vollstaendig zurueck und derselbe `op_id` konvergiert. CP 8 schreibt Binding-State und CP 9 Hook-State ueber dieselben projektgeskoppelten Claim-Routen. Unklare CP-8-Saves behalten den moeglichen kanonischen State fuer Same-Claim-Konvergenz statt ihn mit einem separaten Delete-Claim zu entwerten. Physische Links und Settings bleiben Dev-lokal. CP 10d behaelt seinen asynchronen Writer-Lifecycle. |
| FK-51 §51.2/§51.6 | geaendert | `upgrade-project` prueft den Writer vor lokaler Wirkung; Registration-/Binding-Reads und UP-04-Hook-Persistenz verwenden authentisierte Installer-Routen und stabile Child-Claims. |
| FK-53 §53.3/§53.5 | geaendert | Reset-CLI ist duenner HTTPS-Adapter; authentisierte Identitaet, Writer-Claim-Absender und Epoch-CAS sind normiert. |
| FK-58 §58.5/§58.6 | geaendert | Exit-CLI ist duenner HTTPS-Adapter; Ziel-Session-Aufloesung, Writer-Claim und atomare Epoch-CAS-Finalisierung sind normiert. |
| FK-91 §91.1a Regeln 4/5/10/13/16 | geaendert | Die zwei lokalen Credential-Owner-Ausnahmen bleiben abschliessend; der datierte Installer-Verstoss ist durch Project-Token-geschuetzte Writer-Routen behoben. Installer- und Failure-Corpus-Mehrschrittwirkungen finalisieren den projekt-/sessiongebundenen Operation-Claim in derselben Writer-Transaktion. Ein frueherer eigener storyloser `claimed`-Placeholder beweist den Rollback und wird fuer Same-`op_id`-Konvergenz freigegeben. |
| FK-91 Endpoint-Katalog | geaendert | Erst-Credential-Ausnahme, Writer-Readiness, CP-7-Aggregat, Registration-/Binding-Reads und CP-8-/CP-9-/UP-04-Mutationen sind als projektgeskoppelte Routen ausgewiesen. |
| FK-91 Auth-CLI-Katalog | geaendert | Sechs reale Verben und ihre aktuellen Signaturen ersetzen den veralteten Fuenfer-Katalog. |
| FK-91 Story-Admin-, Failure-Corpus-, Installer- und Admin-Abort-Vertraege | geaendert | Split, Reset, Exit, vier mutierende Failure-Corpus-Verben, Register, Upgrade und Admin-Abort laufen authentisiert ueber den aktiven Writer. |
| Control-Plane-Startup und State-Backend | geaendert | Lebensdauer-Lock, aktive Lease-Liveness, Identitaetsladen, Claim-Validierung und Reconciliation-Reihenfolge setzen den Writer-Vertrag um. |
| CLI und Control-Plane-HTTP | geaendert | Ein Serve-Aufruf startet beide Listener erst nach eigenem Lease-Nachweis; Auth-Kontexte und Surface-Policies erzwingen die In-Prozess-Grenze. Installer-Verben pruefen Readiness vor `credentials.lock` und Pending-Bereinigung und erreichen den Writer per Project-Token, Human-Admin- und Failure-Corpus-Verben per Strategen-Session; kein produktiver CLI-Repository-Fallback bleibt. |
| Third-Party-Preflight und bounded Executor | geaendert | Futures gehoeren bis zur terminalen Finalisierung zum Writer-Lifecycle; Shutdown draint, Lease-Verlust abortiert Finalisierung. |
| Auth-Middleware und generischer In-Flight-Guard | geaendert | Die Erst-Credential-Pruefung ist mit Token-Transitionen serialisiert; Claim-Absender werden fail-closed persistiert. |
| Betroffene Unit-, Integration-, Contract- und Konzepttests | geaendert | Zusaetzlich zu den Runden 1–3 belegen echte HTTPS-/Postgres-Tests CP 7, CP-8-Same-Claim-Konvergenz und UP 04 im lease-haltenden Writer, Upgrade-Reads, Replay/Mismatch/In-Flight sowie je Verb den fail-closed Pfad ohne Writer und ohne lokale Projektwirkung. |
| FK-11, FK-33, FK-69 und FK-76 | geprueft, nicht geaendert | Die scoped Supersession wurde gegen diese Zielstellen erneut geprueft; die geaenderten Failure-Corpus- und Installer-Writer-Vertraege liegen bei FK-41 beziehungsweise FK-50 und sind deshalb nicht aus dieser Zeile ausgeschlossen. |
