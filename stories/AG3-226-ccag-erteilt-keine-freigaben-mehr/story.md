# AG3-226 — Der Gatekeeper bleibt, die Genehmigungsinstanz geht

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []` — `unblocks: [AG3-214]`
- **Herkunft:** PO-Entscheid vom 2026-08-05

## Anlass

Die zweite Abschlussreview zu AG3-214 fand einen produktiv erreichbaren
Schreibpfad, der die Kernzusage jener Story widerlegt:

> `governance/runner.py:2165` — `_escalate_expired_permission_requests()` liest
> abgelaufene Permission-Requests ueber Project Edge, konstruiert danach aber
> `StateBackendPhaseEnvelopeRepository` und schreibt den kanonischen
> `PhaseState` **direkt aus dem Hook-Prozess**. Ohne prozesslokale Lease faellt
> `_borrow_pool_or_writer_connection()` (`_connection.py:145`) ausdruecklich auf
> eine normale Pool-Verbindung zurueck.

Erreichbar ueber **beide** installierten Hook-Einstiege (`claude_code.py:200`,
`codex/cli.py:77`). Der zugehoerige Integrationstest
(`test_ccag_ttl_escalation_rest_pg.py:99`) macht genau diesen Mischpfad gruen —
„real REST" betrifft dort nur den Lesevorgang.

## Der Entscheid

Der PO hat nicht die Absicherung des Schreibpfads gewaehlt, sondern seinen
Wegfall:

> „Du kannst ja sonst auch den CCAG Hook bestehen lassen, aber in die Zaehne
> ziehen im Sinne von, dass er keine Freigaben mehr erteilt, sondern einfach
> nur die anderen Agentaufgaben uebernimmt."

**Ohne Genehmigungsverfahren gibt es keine ablaufenden Permission-Requests —
und damit keine TTL-Eskalation, die leasefrei schreibt.** Der Pfad verschwindet,
statt abgesichert zu werden. Das ist der staerkere Fix: Ein Weg, den es nicht
gibt, kann nicht umgangen werden.

## Warum der Hook bleibt und nicht entfernt wird

`principal_capabilities/enforcement.py:100-111` haelt fest, dass FK-91 §91.4 den
**Sub-Agent-Spawn** (`Agent`) unter dem `ccag_gatekeeper`-Matcher katalogisiert
(`Bash|Write|Edit|Read|Grep|Glob|Agent`). Die Capability-Schicht laesst den
Spawn bewusst mit ALLOW-Huelle durch — mit der ausdruecklichen Begruendung, dass
danach `prompt_integrity` **und CCAG** die eigentliche Autoritaet sind.

Eine Deregistrierung haette diesen Matcher mitgenommen und damit eine
Durchsetzungsstelle beseitigt, die eine **andere** Zusage traegt. Deshalb:
Registrierung bleibt, Autoritaet geht.

## Offene Auslegung — vom Orchestrator getroffen, korrigierbar

„Keine Freigaben mehr erteilen" laesst zwei Lesarten zu:

- **(A) CCAG ist keine Permission-Autoritaet mehr** — es genehmigt nicht und
  blockiert nicht nach Permission-Regeln; das Permission-Request-Verfahren
  entfaellt vollstaendig.
- **(B) Nur das Genehmigen entfaellt**, das Blockieren nach Regel bleibt.

**Gewaehlt ist (A)**, weil „in die Zaehne ziehen" die Autoritaet als Ganzes
meint und „nur die anderen Agentaufgaben uebernimmt" eine Rolle **neben** der
Permission-Runtime beschreibt.

**Der Unterschied ist nicht kosmetisch**, deshalb steht er hier: Unter (A)
verliert die Agent-Kante ihre CCAG-Blockade und `prompt_integrity` sowie die
Principal-Capability-Schicht sind die verbleibende Autoritaet. Unter (B) bliebe
eine Blockademoeglichkeit erhalten. Erweist sich (A) als zu weit, ist das eine
PO-Korrektur an dieser Stelle — kein neuer Entscheid.

## Scope

### Die Scope-Regel geht der Dateiliste vor (2026-08-06)

Zwei Mandatsanfragen hintereinander haben belegt, dass eine aufgezaehlte
Dateiliste fuer diese Story **nicht** funktioniert: R1 fand sechs
Code-Traeger ausserhalb der Liste, R2 nach vollstaendigem AC-5-Sweep zwoelf
weitere Konzeptdokumente und vier weitere Codestellen. Eine dritte Liste waere
mit hoher Wahrscheinlichkeit ebenfalls unvollstaendig — dieselbe Form, die
AG3-189 22 Reviewrunden gekostet hat: ein Allsatz ueber ein nie aufgezaehltes
Universum.

**Deshalb gilt ab sofort ein Kriterium statt einer Liste:**

> **In Scope ist jede Stelle in Code, Konzept oder Konfiguration, die
> ausschliesslich das Permission-Request-Verfahren traegt** — Anlage,
> Genehmigung, Lease, Ablauf, TTL-Eskalation, deren Persistenz, deren Routen,
> deren Ereignisse und deren normative Beschreibung.
>
> **Traegt eine Stelle auch eine andere Aufgabe, ist sie nicht in Scope.** Dann
> wird angehalten und gefragt — mit Locator und der Angabe, welche andere
> Aufgabe dort mit haengt.

Damit ist der Umfang entscheidbar, ohne ihn vorher zu kennen. Was unter der
Regel angefasst wurde und nicht namentlich beauftragt war, ist im Ergebnis
aufzufuehren.

**Bekannte Traeger, nicht abschliessend** (aus R1 und R2, als Startpunkt):
`control_plane_http/_permission_request_routes.py`,
`_permission_lease_routes.py`, `app.py:474,814,1174`, `default_routes.py:128`,
`routes_config.py:56`, `bootstrap/composition_governance.py:533`,
`governance/ccag/permission_service.py:42,64,75,94`,
`governance/runner.py:2165`, `state_backend/**` (Persistenz und Expiry),
`projectedge/governance_client.py`,
`pipeline_engine/phase_executor/models.py:76` (`PERMISSION_REQUEST_EXPIRED`),
`core_types/operating_mode.py:35`, `story_context_manager/operating_mode_resolver/**`.
Konzept: FK-42, FK-30, FK-55, FK-91, FK-04:316, FK-35:442, FK-10:901,934,
FK-56:519, FK-90:83, FK-93:134,348,362, FK-01:277,289, FK-07:119,
DK-09:26,99, `_meta/bc-cut-decisions.md:321,488`,
`formal-spec/principal-capabilities/**`,
`formal-spec/frontend-contracts/events.md:204`,
`formal-spec/guard-system/README.md:25`,
`formal-spec/architecture-conformance/entities.md:390,449`,
ggf. `technical-design/00_index.md:114`.

**Historische Decision Records werden nicht umgeschrieben.** Der neue Record
superseded sie ausdruecklich.

**Groessenkorrektur:** Die Story ist damit nachweislich groesser als das
urspruengliche `size: M`. Der Umfang ergibt sich aus dem Entscheid, nicht aus
einer Ausweitung — das Verfahren war breiter verankert, als bei der Anlage
sichtbar war.

### In Scope

- **Das Permission-Request-Verfahren entfaellt** — Anlage, Genehmigung, Ablauf
  und TTL-Eskalation. Damit entfaellt auch
  `_escalate_expired_permission_requests()` als produktiver Pfad.
- **Der Hook bleibt registriert** und behaelt seinen Matcher; die uebrigen
  Aufgaben laufen weiter.
- **Kein Loeschen von Code** ohne Not: Was durch den Entscheid unerreichbar
  wird, wird als unerreichbar kenntlich — nicht heimlich stehengelassen und
  nicht vorschnell entfernt. Wo Code nur noch dem entfallenen Verfahren dient
  und keine andere Aufgabe traegt, ist sein Verbleib zu begruenden.
- **Bestehende Zielprojekte**: Traegt eine `.claude/settings.json` bereits die
  Registrierung, bleibt sie gueltig — der Hook laeuft ja weiter. Aendert sich
  am materialisierten Eintrag etwas, muss der Upgrade-Pfad es mitziehen.
- **Bestehende `project.yaml`**: Der obsolete Zweig `pipeline.permissions`
  wird im produktiven Upgrade auch ohne Versionssprung entfernt. Er trug als
  einziges definiertes Blatt `request_ttl_s`. Andere, auch unbekannte
  Geschwisterschluessel werden nicht bereinigt oder gefiltert. Hintergrund ist
  der in `T:\codebase\intima` eingetretene Totalausfall: Die neue strikt
  validierende Runtime sah dort noch den alten Installationsvertrag.
- **Bestehende `project.yaml`, `pipeline.features.vectordb: false`**: Der von
  AG3-176 verursachte zweite Fall derselben Migrationsklasse kommt auf
  ausdruecklichen PO-Entscheid vom 2026-08-06 in diese Story. Das ist keine
  Scope-Ausweitung durch den Auftragnehmer. Vor AG3-176 schrieb AK3 den Wert
  selbst; heute ist VektorDB verpflichtend und `false` ungueltig. Der
  produktive Upgrade setzt deshalb exakt dieses Blatt auf den einzig
  zulaessigen Wert `true`, laesst fremde Geschwister unveraendert und meldet
  Projekt, Feld und die Verhaltensaenderung von deaktiviert zu aktiviert
  sichtbar. Das Feld bleibt als explizite Pflichtdeklaration erhalten, nicht
  als Opt-out-Wahl.
- **FK-42** (CCAG-Runtime) und die betroffenen Stellen in **FK-30**, **FK-55**
  und **FK-91** sagen, was der Gatekeeper noch tut und was nicht.

  **NACHTRAG 2026-08-06 — diese Liste war unvollstaendig.** Die Mandatsanfrage
  aus R1 hat belegt, dass das Verfahren an weiteren Stellen normativ verankert
  ist: `formal-spec/principal-capabilities/commands.md:47-132`, `entities.md:70`,
  `events.md:47`, `invariants.md:70`, `scenarios.md:71` sowie **FK-04**:316 und
  **FK-35**:442. Sie gehoeren in den Scope, sonst behauptet das Konzept nach der
  Aenderung weiter ein Verfahren, das es nicht mehr gibt (AC 5).

- **Das Verfahren lebt nicht im Hook.** R1 hat die produktiv erreichbaren
  Traeger benannt: die REST-Routen fuer Anlage, Genehmigung und Lease
  (`control_plane_http/_permission_request_routes.py`,
  `_permission_lease_routes.py`, `app.py:474,814,1174`), die Composition
  (`default_routes.py:128`, `bootstrap/composition_governance.py:533`), der
  Dienst selbst (`governance/ccag/permission_service.py:42,64,75,94`), die
  Persistenz samt Expiry unter `state_backend/**` und der Project-Edge-Client
  (`projectedge/governance_client.py`). **Ein Hook-only-Schnitt erfuellt AC 1
  und AC 5 nicht** — Requests liessen sich weiterhin per REST anlegen und
  genehmigen.

### Out of Scope

- Die Absicherung des Schreibpfads ueber den Writer-Lease. Sie wird
  gegenstandslos; **AG3-214** fuehrt den Befund als geroutet, nicht als behoben.
- Die uebrigen vier Befunde der AG3-214-Review. Sie bleiben dort.
- `prompt_integrity` und die Principal-Capability-Schicht. Sie sind betroffen,
  aber nicht Gegenstand — ausser einer Feststellung nach AC 3.

## Akzeptanzkriterien

1. **Es existiert kein produktiver Pfad mehr, auf dem der CCAG-Hook Permission-
   oder `PhaseState`-State schreibt.** Nachgewiesen durch einen Sweep mit
   Methode ueber beide Hook-Einstiege, nicht durch Sichtpruefung. Der generische
   FK-61-Aufrufzaehler in `_record_guard_invocation()` bleibt bewusst bestehen:
   Er misst jeden Guard-Aufruf als eigenen KPI und gehoert weder zum
   Permission-Verfahren noch zum `PhaseState`-Schreibpfad. Ihn fuer CCAG zu
   durchloechern, wuerde FK-61 beschaedigen und einen unbegruendbaren
   Sonderfall schaffen.
2. **Der Gatekeeper erteilt keine Freigaben.** Ein Test beweist, dass ein
   Vorgang, der frueher eine Genehmigung erhalten haette, heute keine bekommt.
   Und ein zweiter, dass daraus **kein stilles Erlauben** wird, das vorher ein
   Blockieren war — oder, falls doch, dass genau das die gewollte Wirkung von
   Auslegung (A) ist und benannt im Konzept steht.
3. **Die Agent-Kante bleibt durchgesetzt.** Ausdruckliche Feststellung, was den
   Sub-Agent-Spawn nach der Aenderung absichert — mit Locator. Faellt dabei auf,
   dass `prompt_integrity` allein nicht traegt, ist das ein Befund mit
   PO-Vorlage, nicht ein stiller Rest.
4. **Der Matcher ueberlebt.** `ccag_gatekeeper` bleibt registriert, und der
   Sub-Agent-Spawn wird weiterhin darunter katalogisiert (FK-91 §91.4). Test.
5. **Konzept und Code sagen dasselbe.** FK-42, FK-30, FK-55 und FK-91 sind
   nachgezogen; keine Stelle behauptet weiter ein Genehmigungsverfahren.
   Decision Record fuer den Entscheid.
6. **Kein toter Code und keine obsolete Zielkonfiguration ohne Aussage.** Was
   durch den Entscheid unerreichbar wird, ist entweder entfernt oder traegt
   eine Begruendung, warum es bleibt. Der produktive Upgrade-Aufruf entfernt
   die drei Regeldateien und exakt `pipeline.permissions` aus bestehender
   `project.yaml`, auch bei bereits aktueller `config_version`, mit `.bak` vor
   der Mutation. Fremde und unbekannte Schluessel ausserhalb dieses
   verfahrenseigenen Zweigs bleiben unangetastet. Vor Loeschung, Backup oder
   Rewrite beweist die zentrale Filesystem-Boundary die Projektlokalitaet;
   Symlink-/Junction-Indirektionen blockieren fail-closed.
7. `ruff` clean, `mypy --strict` fuer `win32`, `linux`, `darwin`; alle sechs
   deterministischen Konzept-Gates gruen; volle Suite gruen auf Jenkins.
8. Coverage haelt die 85-%-Schwelle.

## Definition of Done

- AC 1-8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §FAIL-CLOSED — AC 2 und AC 3 pruefen ausdruecklich, dass aus dem
  Wegfall einer Autoritaet kein stilles Erlauben wird
- `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN — kein zweiter Pfad, der das
  alte Verfahren am Leben haelt
- `CLAUDE.md` §ZERO DEBT RULE — AC 6

## R5-Feststellung zu AC 3 — Conflict-Freeze am Agent-Spawn

### Wann der Freeze gilt und wer ihn setzen soll

FK-55 §55.8 aktiviert den storybezogenen `conflict_freeze` bei
`normative_conflict`, `authoritative_snapshot_divergence` oder einem
vergleichbaren HARD STOP. FK-91 katalogisiert `conflict_freeze_entered` mit
`GuardSystem / Eskalationslogik` als Producer. Die Implementierung
`ConflictFreezeOverlay.freeze()` in
`principal_capabilities/freeze.py` persistiert zuerst den kanonischen
Backend-Record und danach den lokalen Export; `is_frozen()` behandelt einseitige
oder widerspruechliche Materialisierung fail-closed als aktiv.

Der Produktionssweep `rg "ConflictFreezeOverlay|\\.freeze\\(" src/agentkit/backend`
findet jedoch keinen Aufrufer von `ConflictFreezeOverlay.freeze()` ausserhalb
der Tests. Die Treffer in Exploration, Story-Split und Takeover verwenden
andere Freeze-Arten bzw. andere Klassen. Damit ist neben der Spawn-Auswertung
auch der vorgesehene Produktiv-Producer fuer den Conflict-Freeze als eigener
Befund zu klaeren.

### Welcher Spawn heute durchgeht

Bei einem aktiven Freeze liest
`CapabilityEnforcement._subagent_spawn_result()` in
`principal_capabilities/enforcement.py` den echten Zustand und liefert fuer
einen syntaktisch bekannten `Agent`-Aufruf dennoch `EnforcementOutcome.ALLOW`;
nur `CapabilityHull.freeze_verdict` lautet `deny`. Der danach laufende
`PromptIntegrityGuard.evaluate()` in
`guard_system/prompt_integrity_guard.py` prueft Governance-Escape,
Spawn-Schema und Template-Integritaet, aber kein Freeze-Signal. Ein gueltiger
Story-Worker-Spawn mit passendem `AGENTKIT-SUBAGENT-V1`-Header, Skill-Proof und
installiertem Prompt wird deshalb trotz zuvor materialisiertem Freeze erlaubt.
Belegt wird jede Haelfte durch
`test_agent_spawn_frozen_story_freeze_verdict_is_not_fabricated` und
`TestRunHookRealPath.test_valid_spawn_allows_via_run_hook`; kein produktiver
Consumer verbindet die beiden Werte.

### Regression oder Vorbestand

Die Luecke bestand vor AG3-226. `git blame` ordnet den besonderen
Agent-Spawn-Pfad dem Commit `cb7e36e31` vom 2026-06-11 zu. Am unveraenderten
Basisstand `8eefd4f4` nahm `ccag/runtime.py:CcagRuntime.evaluate()` den Hull zwar
entgegen, pruefte aber nur `capability_hull is None` und sprang danach direkt
nach `_evaluate_internal(hook_event)`. `git grep freeze_verdict 8eefd4f4 --
src/agentkit/backend/governance/ccag/runtime.py
src/agentkit/backend/governance/runner.py` liefert keinen Treffer. CCAG hat den
Freeze daher auch vor dieser Story nicht durchgesetzt. Eine alte Permission-
Regel konnte denselben Spawn unabhaengig blockieren, war aber weder an den
Freeze gekoppelt noch dessen Durchsetzung. AG3-226 macht die Luecke sichtbar
und entfernt diese moegliche Zufallsblockade; sie erzeugt nicht den fehlenden
Freeze-Consumer.

### Schnitt fuer eine Folgestory

Die Folgestory muss gemeinsam loesen: den fehlenden produktiven Producer fuer
die in FK-91 zugewiesenen HARD-STOP-Signale und eine explizite fail-closed
Spawn-Durchsetzung vor einem gueltigen `prompt_integrity`-ALLOW. Sie darf das
nicht als CCAG-Permission wieder einfuehren. Der derzeit ungenutzte
`CapabilityHull` darf erst danach entfallen; neben `freeze_verdict` traegt er
`principal_type`, `operation_class`, `path_classes` und
`hard_capability_verdict`. Ein Entfernen ohne Verlagerung wuerde diese
Diagnose-/Kontextwerte sowie das einzige aktuelle Freeze-Signal gemeinsam
abschneiden.
