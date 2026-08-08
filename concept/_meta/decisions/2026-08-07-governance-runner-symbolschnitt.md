---
concept_id: META-DEC-2026-08-07-GOVERNANCE-RUNNER-SYMBOL-CUT
title: Concept-Decision-Record — governance.runner traegt Symbole beider Distributionen und wird geschnitten
module: meta
cross_cutting: true
status: active
authority_over: []
doc_kind: decision-record
defers_to:
  - target: FK-10
    scope: distribution-boundary
    reason: FK-10 owns the edge/core deployment cut this record applies to a single module
  - target: FK-30
    scope: governance-hooks
    reason: FK-30 owns hook registration and lock deactivation as operations
supersedes: []
superseded_by:
tags: [meta, decision-record, architecture-conformance, distribution, governance, AG3-239]
formal_scope: prose-only
---

# Concept-Decision-Record — `governance.runner` traegt Symbole beider Distributionen

Datum: 2026-08-07. Record fuer AG3-239, Mandatsentscheid M2.

## 1. Anlass

Die eingefrorene Klassifikation in
`concept/formal-spec/architecture-conformance/entities.md` fuehrt
`agentkit.backend.governance.runner` als Modul der **Edge**-Distribution,
entschieden ueber Regel E1 (direkter Anker-Kontakt).

Die AG3-239-Messung des Bounded Context `governance-and-guards` ergab **64
Grenzverletzungen** — mengengleich mit der Teilmenge, die
`distribution_boundary_violations.pairs` fuer diesen BC fuehrt. Zehn davon
entstanden allein daraus, dass ein einziges Modul Symbole **beider** Seiten
trug:

- **Hook-Dispatch** (`GuardRunner`, `run_hook`, `parse_hook_wrapper_args`,
  `validate_hook_selector` und die Per-Hook-Dispatchfunktionen) entscheidet
  synchron im kurzlebigen Hook-Prozess auf dem Entwicklerrechner, bevor ein
  Werkzeug laeuft (FK-30). Ein Netzaufruf pro Tool-Use ist weder schnell noch
  verfuegbar genug — diese Haelfte ist Edge.
- **`Governance`** haelt eine `HookRegistrationRepository` und eine
  `LockRecordRepository`, wird ausschliesslich von Kern-Komposition
  (`composition_closure`, `composition_project`, `story_reset_adapters`) und vom
  Installer konstruiert, und `deactivate_locks` wird von ClosureSequence
  gerufen (FK-29 §29.5). Kanonischer Zustand und seine Repositories gehoeren in
  den Kern (FK-01 §1.1a) — diese Haelfte ist Kern.

`distribution_mixing_freedom_criterion` existiert genau fuer diesen Fall.

## 2. Der Beleg, der nicht aus der Messung kommt

Die Zahl allein wuerde nur „viele Kanten" zeigen. Der Beweis, dass die
**Modulzuordnung** falsch war und nicht bloss die Kantenzahl hoch, liegt an den
Konstruktionsstellen:

> **Alle FUENF Konstruktionsstellen lieferten eine Attrappe fuer die Haelfte, die
> sie nicht brauchten -- und zwar in beide Richtungen.**

- Der Installer (`installer.writer_client.InstallerHookGovernance`) baute ein
  fail-closed `_UnavailableInstallerLockRepository`, das bei Benutzung wirft —
  nur um den Konstruktor zu befriedigen.
- Die drei Kompositionsstellen banden ein direkt an die Datenbank gebundenes
  `StateBackendHookRegistrationRepository`, das sie **nie** riefen. Drei davon
  stehen in `composition_project`, einem als **edge** klassifizierten
  Composition-Root.

Eine Klasse, deren saemtliche Aufrufer die Haelfte ihrer Abhaengigkeiten faelschen
muessen -- die einen den Hook-Teil, die anderen den Lock-Teil --, ist nicht eine
Klasse.

## 3. Entscheidung

**Der Schnitt verlaeuft entlang der Symbole, nicht entlang der Datei.**

1. `Governance` zieht nach `agentkit.backend.governance.administration`
   (**Kern**) und behaelt **nur** `deactivate_locks` samt `LockRecordRepository`.
2. Der Hook-Dispatch bleibt in `agentkit.backend.governance.runner` (**Edge**).
3. `register_hooks` folgt `Governance` **nicht** in den Kern. Der Vorgang
   persistiert ueber eine `HookRegistrationRepository` (Kern, produktiv der
   REST-gestuetzte `WriterHookRegistrationRepository`) **und** materialisiert
   danach `.claude/settings.json` und `.codex/hooks.json` auf dem
   **Entwicklerrechner**. Die zweite Haelfte kann der Kern in einer geteilten
   Installation nicht ausfuehren — als Kern-Code erzeugte sie einen
   core-to-edge-Import nach `harness_client.harness_adapters.settings_writer`.
   Der zusammengesetzte Vorgang ist **Edge-Orchestrierung** und liegt in
   `installer.writer_client.InstallerHookGovernance`.
4. Die Re-Export-Fassaden entfallen ersatzlos: `Governance.run_hook` (eine
   Zeile Delegation an `run_hook`) und die Re-Exporte von `Governance`,
   `GuardRunner` und `HookDecision` aus dem Kern-Paketwurzelmodul
   `agentkit.backend.governance`. Beides sind zweite Importpfade fuer Symbole
   mit vorhandenem Owner und damit nach dem Record
   `2026-08-06-keine-reexport-fassaden` unzulaessig; der Paketwurzel-Re-Export
   machte zusaetzlich jeden Importeur von `agentkit.backend.governance` zum
   Importeur des Hook-Dispatchers.

## 4. Was an der Klassifikation korrigiert wird

Die eingefrorene Klassifikation wird **belegt geaendert, nicht umgangen**:

- Neuer Eintrag `architecture-conformance.symbol_boundary.governance_runner`.
  Er ist der einzige Eintrag der Liste, der nicht an das Vertragspaket abgibt,
  sondern die edge/core-Grenze **innerhalb** von `backend/` zieht.
- Der E1-Zeuge von `governance.runner` wird korrigiert. Dort stand
  `harness_client.harness_adapters.settings_writer` — erzeugt von **genau einem**
  Symbol des Moduls, `Governance._materialise_harness_settings`, also genau dem
  Symbol, das nicht auf die Edge-Seite gehoert. Das Ergebnis der Zuordnung
  bleibt richtig (die beiden verbleibenden Zeugen `projectedge.governance_client`
  und `projectedge.runtime` tragen die Hook-Dispatch-Haelfte allein), die
  **Begruendung** war es nicht. Ein Zeuge, der aus dem falsch einsortierten
  Symbol stammt, darf nicht stehen bleiben.

Die Modulzuordnung `governance.runner -> edge` bleibt damit bestehen; sie gilt
jetzt fuer die Symbole, fuer die sie zutrifft.

## 5. Wirkung, gemessen

Mit demselben Kommando gerechnet
(`stories/AG3-239-.../measure_boundary_violations.py --bc agentkit.backend.governance`):

| Stand | Paare | edge→core | core→edge |
|---|---|---|---|
| Ausgang | 64 | 54 | 10 |
| nach Symbolschnitt `Governance` | 61 | 52 | 9 |
| nach Schnitt `register_hooks` | **59** | 51 | 8 |

Zehn Ueberquerungen entfallen, **ohne einen einzigen Endpunkt**. Das ist die
Antwort (b) aus AG3-239 AC 1 in Reinform: nicht alles, was die Grenze quert,
braucht eine Schnittstelle — manches steht nur auf der falschen Seite.

Drei Ueberquerungen traten dabei neu hervor. Sie sind **keine Regression**,
sondern Defekte, die das gemischte Modul verdeckt hatte: der Kern schrieb
Harness-Settings auf den Laptop, und der Edge-Composition-Root sowie der
Installer bauten den Kern-Service direkt. Zwei davon sind mit Punkt 3 behoben;
die dritte (`composition_project -> governance.administration`) ist der
Composition-Root-Schnitt und gehoert AG3-209.

## 6. Nachtrag 2026-08-08 — das Vertragspaket und der `_temp`-Defekt

Zwei Folgeentscheide desselben Auftrags, hier festgehalten, weil sie dieselbe
Grenze betreffen.

### 6a. `src/agentkit_wire/` ist angelegt

Der Symbolschnitt loeste zehn Ueberquerungen ohne Endpunkt. Die naechste Gruppe
liess sich **gar nicht** loesen, solange es keinen Ort gab, den beide Seiten
importieren duerfen. Der Beweis dafuer war ein fertiger Endpunkt:
`/v1/governance/guard-counters` ist korrekt mediiert — der Hook-Prozess spricht
REST, nie die Datenbank — und zaehlte trotzdem als Grenzverletzung, allein wegen
`GuardCounterMutationRequest`. Nicht der Endpunkt war das Problem, sondern das
Vokabular.

**Vier Symbole sind gewandert**, jedes an den Ort, den
`distribution_symbol_boundaries` ihm bereits zuwies:

| Symbol | von | nach |
|---|---|---|
| `HookDefinition`, `HookEventName` | `governance.hook_registration` | `agentkit_wire.governance_registration` |
| `TelemetryConfig` | `config.models` | `agentkit_wire.project_config` |
| `GuardCounterMutationRequest` | `control_plane.models` | `agentkit_wire.control_plane_mutations` |

**Das ist ein Umzug, keine Kompatibilitaetsschicht.** Der alte Ort ist jeweils
weg; kein Symbol loest an zwei Stellen auf. `test_wire_package_purity.py`
erzwingt beides — die Reinheit des Pakets (kein Import aus `agentkit`, kein I/O,
nur pydantic) und die Einmaligkeit des Ortes.

**Zwei Korrekturen, die der erste Messlauf danach erzwungen hat:**

1. Die Distribution `wire` trug `module_prefixes: []`, weil das Paket bis dahin
   nur ein *Ziel* war. Sobald es existierte, war der leere Wert schaedlich: die
   Messung hielt fail-closed an, weil die neue Wurzel von niemandem beansprucht
   war. Ohne diesen Halt haette sie jede Kante an das Vertragspaket **still
   uebersehen**. Der Praefix steht jetzt dort.
2. Eine Kante **nach** `wire` ist keine Verletzung, sondern der Mechanismus, der
   eine ersetzt. Das Messwerkzeug zaehlte sie zunaechst mit.

Die dritte **Distribution** (eigenes Wheel) bleibt AG3-209; hier entstand nur
der Importwurzel-Baum, eingetragen in `pyproject.toml`.

### 6b. Story-Exit haette auf dem Kern-Host nie funktioniert

Der Symbolschnitt legte den Defekt frei. `deactivate_locks` schrieb einen
Tombstone nach `_temp/governance/locks/{story_id}/mode.json` — **relativ zum
Prozess-CWD** — und leitete `restored_to_ai_augmented` daraus ab, ob dieses
Verzeichnis existierte. `_temp/governance/**` ist aber das lokale
Projektionsverzeichnis des **Edge** (FK-30 §30.6.1 liest dort
`current.json` im Hook-Prozess). Auf einem Kern-Host existiert es nie.

`story_exit/service.py` gatete genau auf dieses Flag und haette **jeden** Exit
mit „guards were not deactivated" abgewiesen — ein Totalausfall, den kein Test
zeigte, weil lokal beide Seiten auf einer Maschine liefen.

**Entscheidung:** Der Beweis „Guards sind deaktiviert" ist kanonischer Zustand,
kein Dateipfad. `deactivate_locks` fasst kein Dateisystem mehr an; das Feld
heisst `guards_deactivated` und ist wahr, wenn die Lock-Deaktivierung
stattgefunden hat (auch idempotent wiederholt), und falsch nur bei unbekannter
Story — dann ist ueber ihre Guards nichts bewiesen. Die drei Felder, die
Entwicklerrechner-Dateien meldeten, sind entfernt.

Mitgenommen: `story_exit` las das Flag als `getattr(..., default=False)` ueber
einen `object`-Parameter. Diese Form macht aus einer Umbenennung stillschweigend
„nicht deaktiviert". Der Port ist jetzt typisiert (`_DeactivationOutcome`), der
Zugriff direkt.

## 6c. Nachtrag Review-Runde 2 — der Endpunkt war falsch und ist zurueckgebaut

Runde 1 baute `POST /v1/governance/capability-adjudications`. **Das war ein
Fehler, und er ist vollstaendig zurueckgenommen.**

**Der normative Grund.** FK-01 §1.2.3 sagt woertlich:

> „Ein Tool-Call muss lokal und in Millisekunden entschieden werden; ein
> Netz-Roundtrip pro Werkzeugaufruf ist kein zulaessiges Design. Die
> Guard-Engine ist deshalb Edge-ausgeliefert und laeuft im Hook-Prozess (FK-30,
> FK-10 §10.1.3). Ihre Regelbasis stammt aus dem zentral publizierten
> Edge-Bundle; sie erzeugt keine eigene. Sicherheitskritische Zustandsfragen
> (haelt ein Lock? ist eine Schwelle ueberschritten?) werden weiterhin am Core
> bestaetigt **oder fail-closed blockiert**."

Die Capability-Adjudikation ist Guard-Engine. Ein Endpunkt, den **jeder**
Werkzeugaufruf trifft, ist genau das verbotene Design. `story.md` sagt im Anlass
dasselbe.

**Der empirische Grund.** Der Endpunkt hat **null** Grenzverletzungen geloest:
50 Paare mit ihm, 50 ohne ihn. Die drei Ueberquerungen, die ihm zugeschrieben
waren, loest der strukturelle Eingangs-Port
(`principal_capabilities/adjudication_input.py`) — der ist von jedem Endpunkt
unabhaengig, bleibt, und ist der eigentliche Gewinn dieses Umbaus.

**Die richtige Form steht im Anker selbst:** kanonischer Zustand im Kern,
publiziert als lokale Materialisierung; Entscheidung lokal; fehlende oder
versionsfremde Materialisierung blockiert fail-closed. Das ist dasselbe Muster
wie beim Freeze.

**Ein Gewinn ist bewusst behalten worden.** `FreezeRepository` ist aus dem
Hook-Prozess verschwunden und bleibt draussen. Der Freeze wird ueber den
**lokalen Export** konsultiert (`ConflictFreezeOverlay(local_export=...)`) —
ohne Datenbank und ohne Netzaufruf. Das erfuellt beide Normen zugleich: FK-01
§1.2.3 (lokale Entscheidung) und AG3-209 AC 3 („aus dem Hook-Prozess ist weder
psycopg noch ein Postgres-Repository erreichbar"). Der Zustand **vor** dieser
Story konstruierte `FreezeRepository(project_root)` im kurzlebigen Hook-Prozess;
das ist weg und durch einen Strukturtest gepinnt.

**Sechs Folgebefunde der Runde 2 loesen sich mit dem Rueckbau auf**, weil ihr
Gegenstand nicht mehr existiert: die ungeprueft uebernommene Story-Identitaet,
der Loopback als Attrappe fuer die HTTP-Grenze, die `story_id`-Luecke im
Freeze-Vergleich, das TOCTOU zwischen zwei Record-Lesungen, die vom Edge
behauptbare `local_freeze`-Angabe und der fehlende `allowed`/`outcome`-Validator.
Der vierte Informationsverlust ist ebenfalls behoben: die konkrete Fehlerklasse
(z. B. `FreezePersistenceError`) erreicht den Audit-Trail wieder, weil die
Ausnahme lokal bleibt statt durch eine Wire-Antwort in einen generischen
`RuntimeError` verpackt zu werden.

**Korrigiert:** `GuardDecision` war als „(b) edge-internal" eingestuft. Das war
falsch — es ist ein kanonischer, append-only Audit-Record (FK-18 §173), den zehn
Kern-Module lesen; ein Umzug auf den Edge haette die Verletzungszahl von 64 auf
98 getrieben. Der Edge **erzeugt** die Entscheidung, das kanonische Anhaengen
gehoert dem Kern. Einen Eigentuemer dafuer gibt es unter AG3-240..250 nicht, und
er wird hier nicht erfunden: der Posten geht **offen an den PO**, zusammen mit
dem Nebenbefund, dass produktiv gar kein Decision-Repository injiziert wird
(`guard_evaluation.py:114`).

## 6d. Nachtrag — der Interpreter-Guard pinnt wieder einen Ort

Der Guard war von (Pfad, Zeile, Literal) auf (Pfad, Literal, **Anzahl**)
umgebaut worden. Das schwaechte ihn: ein erlaubtes Vorkommen entfernen und
dasselbe Literal an **anderer Stelle derselben Datei** einfuegen laesst die
Gesamtzahl unveraendert und blieb damit unsichtbar.

Der Locator traegt jetzt zusaetzlich den **qualifizierten Namen** der
umschliessenden Funktion beziehungsweise Klasse, mit Anzahl je Scope
(`_SelectorLiteralException.scopes`). Das ueberlebt Zeilenverschiebungen — anders
als der alte Zeilenanker — und faengt die Verlagerung.

**Revert-Red-Beweis, gefuehrt:** Ein erlaubtes `'python'` wurde innerhalb
derselben Datei aus `StoryService.get_story` in `_story_run_view` verschoben, in
identischer Aufrufargument-Rolle, Gesamtzahl unveraendert 1.

- Anzahl-Pruefung: **nicht** gefeuert (wie erwartet — sie ist blind dafuer)
- Scope-Pruefung: **gefeuert**, Exit 1

Genau die Luecke, die der Reviewer benannt hat, und der Beweis zeigt, dass der
neue Teil sie schliesst und nicht bloss den alten dupliziert.

## 7. Betroffenheitsmatrix

| Dokument / Artefakt | Betroffen | Aenderung |
|---|---|---|
| `formal-spec/architecture-conformance/entities.md` | ja | neuer `symbol_boundary`-Eintrag, Zeugenkorrektur |
| FK-10 (Distributionsschnitt) | nein | Regel unveraendert, hier nur angewandt |
| FK-30 (Hook-Registrierung, Lock-Deaktivierung) | nein | Operationen unveraendert, nur ihr Ort |
| FK-29 §29.5 (ClosureSequence) | nein | ruft `deactivate_locks` unveraendert |
| Record `2026-08-06-keine-reexport-fassaden` | ja, angewandt | zwei weitere Fassaden entfernt |
| `distribution_boundary_violations.pairs` | ja, abgeleitet | wird von AG3-209 vollstaendig neu gerechnet, nicht hier nachgepflegt |
| FK-30 §30.3.1 / §30.6.0 | ja | Owner und Effekt der beiden Top-Surfaces korrigiert |
| FK-50 §50.3, FK-51 §51.6, FK-68, `bc-cut-decisions.md` | ja | Namens-Sweep auf den tatsaechlichen Owner |
| `pyproject.toml` | ja | `src/agentkit_wire` als zweiter Importwurzel-Baum |
| FK-58 (Story-Exit) | ja | Gate liest `guards_deactivated` statt eines Dateipfad-Flags |
| FK-55 §55.10.3 | nein | Schritte und Ort unveraendert: lokal im Hook-Prozess |
| FK-01 §1.2.3 | nein, angewandt | traegt den Rueckbau des Endpunkts |
| FK-76 §76.5 | ja, bestaetigt | FK-30 beanspruchte die Settings-Schemas mit; alleiniger Owner ist FK-76 |
| `scripts/ci/check_interpreter_entrypoints.py` | ja | struktureller Locator statt blosser Anzahl |
