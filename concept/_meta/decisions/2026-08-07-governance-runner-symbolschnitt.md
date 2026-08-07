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

> **Alle vier Konstruktionsstellen lieferten eine Attrappe fuer die Haelfte, die
> sie nicht brauchten.**

- Der Installer (`installer.writer_client.InstallerHookGovernance`) baute ein
  fail-closed `_UnavailableInstallerLockRepository`, das bei Benutzung wirft —
  nur um den Konstruktor zu befriedigen.
- Die drei Kompositionsstellen banden ein direkt an die Datenbank gebundenes
  `StateBackendHookRegistrationRepository`, das sie **nie** riefen. Drei davon
  stehen in `composition_project`, einem als **edge** klassifizierten
  Composition-Root.

Eine Klasse, deren saemtliche Aufrufer die Haelfte ihrer Abhaengigkeiten faelschen
muessen, ist nicht eine Klasse.

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

## 6. Betroffenheitsmatrix

| Dokument / Artefakt | Betroffen | Aenderung |
|---|---|---|
| `formal-spec/architecture-conformance/entities.md` | ja | neuer `symbol_boundary`-Eintrag, Zeugenkorrektur |
| FK-10 (Distributionsschnitt) | nein | Regel unveraendert, hier nur angewandt |
| FK-30 (Hook-Registrierung, Lock-Deaktivierung) | nein | Operationen unveraendert, nur ihr Ort |
| FK-29 §29.5 (ClosureSequence) | nein | ruft `deactivate_locks` unveraendert |
| Record `2026-08-06-keine-reexport-fassaden` | ja, angewandt | zwei weitere Fassaden entfernt |
| `distribution_boundary_violations.pairs` | ja, abgeleitet | wird von AG3-209 vollstaendig neu gerechnet, nicht hier nachgepflegt |
