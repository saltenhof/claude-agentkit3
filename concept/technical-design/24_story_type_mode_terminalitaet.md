---
concept_id: FK-24
title: Story Type, Mode und Terminalitaet
module: story-types
domain: story-lifecycle
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: story-types
  - scope: terminality-contract
defers_to:
  - target: FK-59
    scope: story-contract-classification
    reason: Konsolidierte Vertragsachsen und Kombinationsregeln werden dort normiert
  - target: FK-23
    scope: mode-routing
    reason: Modusermittlung und Exploration-Phase in FK-23 beschrieben
  - target: FK-20
    scope: phase-model
    reason: Phasenmodell und Story-Typ-Routing in FK-20 definiert
  - target: FK-54
    scope: story-split
    reason: Cancelled-Endzustand bei Scope-Explosion und Nachfolger-Bildung sind in FK-54 normiert
  - target: FK-56
    scope: operating-modes
    reason: "`operating_mode` (ai_augmented vs. story_execution) ist in FK-56 normiert und nicht mit `mode`/`execution_route` zu verwechseln"
supersedes: []
superseded_by:
tags: [story-types, terminality, delivery-contract, exploration-guard, fail-closed]
prose_anchor_policy: strict
glossary:
  exported_terms:
    - id: execution-route
      definition: >
        Abgeleitete Laufzeitachse innerhalb eines story_execution-Runs.
        Gibt an, ob eine Story unmittelbar in die Umsetzung geht
        (execution) oder zuerst Exploration durchlaeuft (exploration).
        Historisch als mode bezeichnet. Darf die Lieferpflicht des
        story_type niemals abschwaechen.
      values: [execution, exploration]
      see_also:
        - term: operating-mode
          domain: story-lifecycle
        - term: story-type
          domain: story-lifecycle
    - id: implementation-contract
      definition: >
        Zweite persistente Vertragsachse, nur zulaessig bei
        story_type=implementation. Werte standard und
        integration_stabilization. Erzeugt keinen neuen Betriebsmodus,
        sondern einen engeren Ausfuehrungsvertrag fuer bewusst breite
        Integrations- und Stabilisierungslagen.
      values: [standard, integration_stabilization]
      see_also:
        - term: story-type
          domain: story-lifecycle
    - id: story-type
      definition: >
        Primaere persistente Liefervertragsachse einer Story mit genau
        vier gueltigen Werten: implementation, bugfix, concept, research.
        Bestimmt Lieferpflicht, Guard-Verhalten, Verify- und
        Closure-Zulaessigkeit sowie administrativen Endpfad. Ungueltige
        oder leere Werte sind fail-closed und duerfen nicht auf
        implementation defaulten.
      values: [implementation, bugfix, concept, research]
      see_also:
        - term: implementation-contract
          domain: story-lifecycle
        - term: terminal-state
          domain: story-lifecycle
    - id: terminality
      definition: >
        Fachlicher Abschlussstatus einer Story: eine
        implementation- oder bugfix-Story gilt nur dann als
        abgeschlossen, wenn Implementierungsartefakte, Verify-Evidence
        und worker-manifest.json vorliegen. Reine Exploration-Artefakte
        ermoeglichen keine Terminality. Concept- und Research-Stories
        koennen nach erfolgreichem Exploration-QA terminal sein.
formal_refs:
  - formal.story-contracts.entities
  - formal.story-contracts.invariants
  - formal.story-contracts.scenarios
  - formal.story-workflow.state-machine
  - formal.story-workflow.scenarios
  - formal.integration-stabilization.entities
  - formal.integration-stabilization.invariants
  - formal.setup-preflight.invariants
---

# 24 — Story Type, Mode und Terminalitaet

<!-- PROSE-FORMAL: formal.story-contracts.entities, formal.story-contracts.invariants, formal.story-contracts.scenarios, formal.story-workflow.state-machine, formal.story-workflow.scenarios, formal.integration-stabilization.entities, formal.integration-stabilization.invariants -->

## 24.1 Ziel

Dieses Dokument definiert den normativen Runtime-Vertrag fuer:

- die **kanonische Story-Type-Wertemenge**
- die **Bedeutung von `story_type` vs. `mode`**
- die **zulaessigen terminalen Endzustaende**
- die **Mindestnachweise fuer den Abschluss einer Story**

Es schliesst eine kritische Architektur-Luecke:

> Eine `implementation`- oder `bugfix`-Story darf niemals als erfolgreich
> abgeschlossen gelten, wenn nur ein Exploration-Ergebnis vorliegt und keine
> Umsetzung stattgefunden hat.

---

## 24.2 Kanonische Story-Type-Wertemenge

### 24.2.1 Erlaubte Werte

Die einzig gueltigen Story Types in AgentKit sind:

- `implementation`
- `bugfix`
- `concept`
- `research`

### 24.2.2 Verbotene Werte

Die folgenden Werte sind ungueltig:

- leerer Story Type
- `refactoring`
- `refactor`
- jeder sonstige nicht explizit erlaubte Wert

### 24.2.3 Normative Regel

Ein ungueltiger oder leerer Story Type darf **niemals**:

- auf `implementation` defaulten
- stillschweigend normalisiert werden
- durch Label-Heuristik in einen gueltigen Fachtyp umgedeutet werden

Stattdessen muss der Lauf **fail-closed** anhalten.

---

## 24.3 Fachliche Bedeutung von `story_type`

### 24.3.1 `story_type` ist ein Liefervertrag

`story_type` beschreibt nicht nur Routing, sondern die fachliche Pflicht der Story.

Die Pflichten sind:

- `concept`: erzeugt ein Konzept-Ergebnis, aber keine Code-Lieferpflicht
- `research`: erzeugt ein Recherche-Ergebnis, aber keine Code-Lieferpflicht
- `implementation`: erzeugt zwingend Code-/Test-/Lieferartefakte
- `bugfix`: erzeugt zwingend Code-/Test-/Lieferartefakte

### 24.3.2 `mode` ist kein fachlicher Ersatz fuer `story_type`

**Entkopplung `mode` <-> `execution_route` (normativ, AG3-018-Modell):**
Das Story-Attribut `mode` ist **nicht mehr blosser Alias** der
Intra-Run-Achse `execution_route`. `mode` traegt den `fast`-Wert als
gleichrangigen Story-Modus (§24.3.4); `execution_route` bleibt die davon
abgeleitete Intra-Run-Laufweg-Achse `{execution, exploration, None}`, die
**nur fuer nicht-fast Storys** eine eigenstaendige Bedeutung hat. Die
Standard-Familie (`execution`/`exploration`) faltet projektweit auf den
`mode_lock`-Wert `standard`; `fast` ist der dritte, dazu exklusive Wert
(§24.3.3). `fast` ist mit `exploration` wechselseitig ausschliessend
(§24.3.4: Exploration entfaellt unter Fast). Das Applicability-Praedikat
des `sonarqube_gate` liest entsprechend `mode == fast` (Story) bzw.
`mode_lock == fast` (Projekt), FK-33 §33.6.5.

Der historisch als `mode` bezeichnete Wert beschreibt fuer die
nicht-fast Standard-Familie den Intra-Run-Laufweg. Im konsolidierten
Vertragsmodell aus FK-59 ist damit fachlich die Achse
**`execution_route`** gemeint.

Dieser abgeleitete Laufweg kennt:

- `execution`
- `exploration`
- `None` fuer nicht-implementierende Storys

Dieser Laufweg darf nie mit `operating_mode` aus FK-56 verwechselt
werden. `operating_mode` trennt `ai_augmented` und `story_execution`,
waehrend `execution_route` nur den Pfad **innerhalb** eines
gebundenen Story-Runs bezeichnet.

Weder `mode` (inkl. `fast`) noch `execution_route` darf die fachliche
Lieferpflicht des Story Types **je** abschwaechen.

Insbesondere gilt:

- `story_type=implementation` + `mode=exploration` bedeutet:
  Exploration ist ein Vorlauf, nicht das Endergebnis.
- `story_type=bugfix` + `mode=exploration` bedeutet:
  Exploration ist ein Vorlauf, nicht das Endergebnis.

### 24.3.3 Mutual Exclusion zwischen Fast- und Standard-Mode

Fast (`mode=fast`, eingefuehrt mit AG3-018) und Standard
(`mode=execution` oder `mode=exploration`) sind **fachlich
ausschliesslich**. Solange in einem Projekt mindestens eine Story
im Standard-Mode aktiv ist (Status `In Progress`), darf keine
Fast-Story starten — und umgekehrt.

Begruendung:

1. Fast deaktiviert die Story-scoped Repo-Schutz-Guards
   (Branch-Guard, Scope-Overlap, Lock-Records). Genau diese
   Guards sind aber von einer parallel laufenden Standard-Story
   aktiv geschaltet und schuetzen ihren Scope. Eine Fast-Story
   wuerde reproduzierbar in den Geltungsbereich dieser Guards
   laufen und damit nicht das liefern, was Fast verspricht.
2. Fast-Mode setzt voraus, dass ein Mensch die Story aktiv
   begleitet (vgl. AG3-018). Eine zweite, parallel laufende
   Standard-Pipeline verwaessert dieses Begleit-Versprechen.
3. Pre-Merge-Rebase-Konflikte zwischen Fast und Standard sind
   wahrscheinlicher als zwischen zwei Fast- oder zwei Standard-
   Stories desselben Modes.

**Innerhalb** eines Modes ist Parallelitaet erlaubt und wird
ueber die Execution-Caps (FK-70 §70.6.2) reglementiert.

**Normativer `mode_lock`-Wertebereich:** Der projektweite `mode_lock`
fuehrt **genau drei** normative Werte: `null`/idle, `standard` und
`fast`. Die Intra-Run-Achse `execution_route` (§24.3.2: `execution` /
`exploration`) **faltet auf Projekt-Lock-Ebene in `standard`** — beide
Standard-Laufwege halten denselben `standard`-Lock. `fast` ist der
dritte, dazu exklusive Wert. Aeltere Schreibweisen wie
`{EXECUTION, EXPLORATION, FAST}` sind **Drift** und auf diesen
`{null/idle | standard | fast}`-Wertebereich zu vereinheitlichen.

**Enforcement:** AK3 fuehrt einen projektweiten `mode_lock` als
Zustandsobjekt der Control Plane: Wert ist `null`, `standard`
oder `fast` plus ein `holder_count`. Beim Story-Start
(Setup-Preflight) wird der Lock atomar geprueft und gesetzt:

- `mode_lock = null` -> setze auf gewuenschten Mode, holder_count = 1.
- `mode_lock = gewuenschter Mode` -> holder_count++.
- `mode_lock = anderer Mode` -> Setup faellt durch den
  Mode-Konflikt-Check (FK-22 §22.3.1, Check 10
  `no_competing_story_mode_active`); Story bleibt in Approved.

Beim Story-Abschluss (Closure / Cancellation) wird
`holder_count--`; bei `0` faellt der Lock zurueck auf `null`.
Der Mode-Wechsel ist damit erst moeglich, wenn die letzte
Story des aktiven Modus beendet ist.

<!-- PROSE-FORMAL: formal.setup-preflight.invariants -->

Formale Invariante: `formal.setup-preflight.no_competing_story_mode_active`.

### 24.3.4 Mode-Profil Fast (kanonische Tabelle, Owner FK-24)

Fast (`mode=fast`) ist ein gleichrangiger Projekt-Modus fuer eng
menschlich begleitete codeproduzierende Stories: die Story bleibt eine
vollwertige AK3-Story (Story-ID, Branch, Closure-Workflow, Telemetrie),
aber Schutz- und Pruef-Schichten sind gezielt reduziert, weil ein Mensch
das Inhaltliche selbst reviewt. Fast ist **nur** fuer Story-Typen
`implementation` und `bugfix` zulaessig; `concept`/`research` mit
`mode=fast` ist **fail-closed**.

Die folgende Tabelle ist die **kanonische Quelle** des Fast-Profils
(Single Source of Truth, ZERO DEBT — keine Duplikation). Alle
abhaengigen Konzepte (FK-22, FK-23, FK-26, FK-27, FK-29, FK-30/31/35,
FK-33) **verweisen** hierher. Auszeichnung: **IN** unveraendert /
**OUT** entfaellt / **MOD** veraendert (Delta hinter dem Doppelpunkt).

| Phase | Substep | Fast-Verhalten |
|-------|---------|----------------|
| Setup | Preflight-Gates (10 Checks) | **MOD**: 4 Mindest-Checks aktiv (story_exists, kein aktiver Run, kein staler Worktree, Mode-Konflikt aus §24.3.3); Status/Deps/Scope-Overlap weg |
| Setup | Story-Context-Berechnung | **IN** |
| Setup | ARE-Bundle laden | **OUT** |
| Setup | Story-Typ-Weiche | **MOD**: nur impl/bugfix erlaubt |
| Setup | Worktree-Erstellung | **IN** |
| Setup | green-main-Vorbedingung (§22.4c) | **OUT**: `sonarqube_gate` NOT_APPLICABLE (fast), FK-33 §33.6.5 |
| Setup | Guard-Aktivierung | **OUT** (Baseline-Guards bleiben) |
| Setup | Modus-Ermittlung | **OUT** (mode aus Story-Attribut, keine 4-Trigger-Auswertung) |
| Exploration | komplette Phase (alle Substeps) | **OUT** |
| Implementation | Worker-Start | **MOD**: Light-Prompt, keine Inkrement-/Review-Pflicht |
| Implementation | Inkrementelles Vorgehen | **MOD**: Disziplin Worker-frei, kein Inkrement-Tracking |
| Implementation | Inline-Reviews | **OUT** (User reviewed direkt) |
| Implementation | Finaler Build + Gesamttest | **MOD**: Build+Tests gruen — **harter Pflicht-Floor**, nicht abschaltbar |
| Implementation | Handover-Paket | **MOD**: nur Worker-Manifest, keine QA-Artefakte |
| QA-Subflow | Schicht 1 Strukturell | **MOD**: degeneriert auf Tests-gruen-Floor |
| QA-Subflow | Schicht 2 LLM-Bewertungen | **OUT** |
| QA-Subflow | Schicht 3 Adversarial | **OUT** |
| QA-Subflow | Schicht 4 Policy-Eval | **OUT** |
| QA-Subflow | SonarQube-Gate (§27.6a) | **OUT**: NOT_APPLICABLE (fast), FK-33 §33.6.5 |
| QA-Subflow | Feedback-Loop | **OUT** (User steuert manuell) |
| Closure | Finding-Resolution-Gate | **OUT** (keine Findings produziert) |
| Closure | Integrity-Gate (9 Dim inkl. Dim 9) | **MOD**: ersetzt durch **Sanity-Gate** (Tests gruen, Worktree clean, Pre-Merge-Rebase OK) — Pflicht; Dim 9 NOT_APPLICABLE (FK-35 §35.2.4a) |
| Closure | Story-Branch Push | **IN** |
| Closure | Branch-Merge | **MOD**: Pre-Merge-Rebase auf main statt Lock; bei Konflikt Eskalation an User |
| Closure | Main Push (mit Rollback) | **IN** |
| Closure | Teardown | **IN** |
| Closure | Story-Close | **IN** |
| Closure | Metriken schreiben | **MOD**: Records mit `mode=fast` getaggt; KPI separat aggregierbar |
| Closure | Doctreue Ebene 4 | **OUT** |
| Closure | Postflight-Gates | **MOD**: nur Hard-Failures (Branch-Reste, offene Worktrees) bleiben |
| Closure | VektorDB-Sync | **IN** |
| Closure | Guards deaktivieren | **MOD**: no-op (keine Locks aktiv) |

**Was in jedem Modus aktiv bleibt (Baseline-Guards):** destructive git
protections, secrets protection, CCAG, self-protection
(`formal.operating-modes.baseline_guards_apply_in_all_modes`). Fast
deaktiviert nur die **Story-scoped** Repo-Schutz-Guards (Branch-Guard,
Scope-Overlap, Lock-Records).

## 24.3a `implementation_contract` fuer implementierende Storys

Fuer `story_type=implementation` darf zusaetzlich ein
`implementation_contract` gesetzt werden.

Erlaubte Werte sind:

- `standard`
- `integration_stabilization`

Regeln:

- `implementation_contract` ist **kein** Ersatz fuer `story_type`
- `integration_stabilization` erzeugt keinen neuen Betriebsmodus
- `integration_stabilization` lockert keine Deliverable-Pflicht
- `integration_stabilization` ist nur ein engerer Ausfuehrungsvertrag
  fuer bewusst breite Integrations- und Stabilisierungslagen

Fehlt das Feld, gilt fail-closed fuer `implementation`:

- `implementation_contract = standard`

---

## 24.4 Setup-Vertrag

### 24.4.1 Story Type ist Pflichtfeld

Vor Worktree-Erzeugung, Worker-Spawn und Mode-Routing muss ein gueltiger Story Type feststehen.

Wenn der Story Type fehlt oder ungueltig ist, muss `setup`:

- `FAILED` oder `PAUSED` liefern
- einen eindeutigen Fehlercode schreiben
- **keinen** Worktree anlegen
- **keinen** Worker spawnen
- **keinen** Phase-Fortschritt erlauben

### 24.4.2 Mode-Routing nur nach erfolgreicher Typvalidierung

Erst nachdem ein gueltiger Story Type festgestellt wurde, darf das System zwischen
`exploration` und `execution` fuer implementierende Storys routen.

---

## 24.5 Exploration-Vertrag fuer implementierende Storys

### 24.5.1 Exploration ist nur Zwischenzustand

Fuer `implementation` und `bugfix` ist Exploration ausdruecklich erlaubt, aber nur als vorbereitender Schritt.

Exploration darf in diesen Story-Typen:

- ein Design-/Change-Frame erzeugen
- Scope, Impact und offene Punkte klaeren
- Guardrail-/Semantic-Feedback vorbereiten

Exploration darf in diesen Story-Typen **nicht**:

- den Story-Abschluss ermoeglichen
- Closure freigeben
- Merge freigeben
- AK3-Story-Status `Done` setzen

### 24.5.2 Verpflichtender Folge-Zustand

Wenn Exploration fuer `implementation` oder `bugfix` erfolgreich endet, muss AgentKit explizit persistieren:

- `implementation_required = true`
- `closure_allowed = false`
- `story_done = false`

Optional zusaetzlich:

- `exploration_completed = true`
- `execution_pending = true`

### 24.5.3 Konzept-Hierarchie bei Implementation mit Exploration

Wenn eine Implementation-Story eine vorgelagerte Exploration
durchlaeuft, koennen zwei Konzeptebenen koexistieren:

1. **Primaerkonzepte** (aus dem `concept/`-Verzeichnis, referenziert
   in `concept_paths`): Single Source of Truth. Unverletzlich.
   Diese Dokumente sind qualitaetsgesichert und vom Menschen
   freigegeben.

2. **Explorations-Konzept** (Ergebnis der Exploration Phase):
   Abgeleitetes technisches Feinkonzept fuer den konkreten
   Implementierungsscope. Wird am Ende der Exploration
   qualitaetsgesichert, aber ist den Primaerkonzepten stets
   subordiniert.

**Kollisionsregel Explorations-Konzept vs. Primaerkonzept:** Bei
Widerspruch zwischen Explorations-Konzept und Primaerkonzept gewinnt
das Primaerkonzept — unabhaengig davon, ob das Explorations-Konzept
den QA-Prozess bestanden hat. Ein Widerspruch zu einem
Primaerkonzept ist ein Fehler im Explorations-Konzept, kein Grund
zur Anpassung des Primaerkonzepts.

**Kollisionsregel Primaerkonzept vs. Primaerkonzept:** Wenn zwei
Primaerkonzepte sich widersprechen (z.B. Fachkonzept vs.
Feinkonzept, Altkonzept vs. neues Konzept), darf AgentKit keine
eigenstaendige Vorrangentscheidung treffen. Die Story wird
`PAUSED` mit Eskalation an den Menschen. Erst nach Klaerung durch
den Menschen (Konzeptkorrektur oder explizite Vorrangentscheidung)
darf die Story fortgesetzt werden.

**Fehlerbefund in einem Primaerkonzept:** Wenn die Exploration
oder die Implementierung einen Fehler oder Widerspruch in einem
Primaerkonzept identifiziert, darf das Primaerkonzept nicht durch
den Worker oder die Exploration ueberschrieben werden. Stattdessen:
Story wird `PAUSED`, Befund wird eskaliert. Ggf. wird eine
vorgeschaltete Concept-Story zur Konzeptkorrektur erzeugt. Erst
nach Korrektur und Freigabe des Primaerkonzepts darf die
urspruengliche Story fortgesetzt werden.

---

## 24.6 Mindestnachweise fuer `implementation` und `bugfix`

Eine Story vom Typ `implementation` oder `bugfix` darf nur dann als abgeschlossen gelten, wenn mindestens folgende Nachweise vorliegen:

- Implementierungsphase wurde erfolgreich durchlaufen
- primaeres Lieferartefakt der Umsetzung existiert
- Code-/Datei-Aenderungen im primaeren Umsetzungsbereich sind nachweisbar
- `worker-manifest.json` beschreibt die Umsetzung
- `protocol.md` dokumentiert die Umsetzung
- Verify lief gegen die Umsetzungsartefakte, nicht nur gegen Exploration

Zusaetzliche Nachweise koennen je nach Story/Config gelten:

- Handover-Artefakte
- Build-/Test-/E2E-Evidence
- Guardrail-Evidence
- Semantic-/Policy-Evidence

---

## 24.7 Verify-Vertrag

### 24.7.1 Harte Precondition fuer implementierende Storys

`verify` muss bei `story_type in {implementation, bugfix}` vor dem eigentlichen QA-Lauf pruefen:

- liegt nur Exploration-Evidence vor?
- oder existiert auch Umsetzungsevidence?

Wenn keine Umsetzungsevidence vorliegt, darf `verify` nicht `COMPLETED` liefern.

Zulaessige Reaktionen sind nur:

- `FAILED`
- `PAUSED`
- `ESCALATED`

mit einem klaren Fehlergrund, z. B.:

- `IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION`

### 24.7.2 Exploration-only Verify ist nicht terminal

Eine Exploration-Verifikation bei `implementation`/`bugfix` darf nur ein Zwischenresultat erzeugen, nie ein terminales Weitergehen in Closure.

---

## 24.8 Closure-Vertrag

### 24.8.1 Fachliche Terminalitaet

Closure darf fuer `implementation` und `bugfix` nur laufen, wenn die Story fachlich lieferfaehig ist.

Das bedeutet:

- reine Exploration-Artefakte reichen nicht
- ein Design Artifact allein reicht nicht
- ein erfolgreiches Exploration-QA allein reicht nicht

### 24.8.2 Fail-Closed Regeln

Wenn `story_type in {implementation, bugfix}` und keine Umsetzungsevidence vorliegt, dann muss Closure:

- `ESCALATED` oder `FAILED` liefern
- keinen Merge ausfuehren
- keinen Branch zurueckmergen
- kein Issue schliessen
- keinen Project-Status auf `Done` setzen

### 24.8.3 Administrativer Alternativ-Endzustand

Neben dem erfolgreichen Liefer-Endzustand `Done` gibt es fuer
implementierende Stories einen separaten **administrativen**
Endzustand `Cancelled`. Dieser darf nicht durch Closure entstehen,
sondern nur durch einen offiziellen administrativen Pfad wie den
Story-Split bei `Scope-Explosion` (FK-54).

`Cancelled` bedeutet:

- keine erfolgreiche Lieferung
- kein Merge
- keine Closure-Semantik
- Story-Vertrag beendet, Scope lebt in Nachfolger-Stories weiter

---

## 24.9 Sichtbares Exploration-Ergebnis

> **[Entscheidung 2026-04-08]** Element 14 — Exploration-Summary Markdown ist Pflichtartefakt. Menschenlesbares Aggregat aus strukturierten Artefakten. Primaerdokument bei Eskalation an Operator.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 14.

### 24.9.1 Menschenlesbares Pflichtartefakt

Wenn Exploration innerhalb einer `implementation`- oder `bugfix`-Story stattfindet, muss das Ergebnis ausserhalb des reinen QA-Temp-Bereichs sichtbar sein.

Es muss mindestens ein menschenlesbares Artefakt im Story-Verzeichnis existieren, z. B.:

- `exploration-summary.md`
- oder ein definierter Exploration-Abschnitt in `protocol.md`

### 24.9.2 Mindestinhalt

Dieses Artefakt muss mindestens enthalten:

- was wurde untersucht
- was wurde entschieden
- was ist noch offen
- was ist die verpflichtende naechste Phase
- warum die Story noch **nicht** abgeschlossen ist

---

## 24.10 Orchestrator-Reaktionsvertrag

Die Orchestrator-Reaktionsmatrix muss zwischen diesen zwei Faellen unterscheiden:

1. `exploration COMPLETED` fuer `concept` oder `research`
2. `exploration COMPLETED` fuer `implementation` oder `bugfix`

Fuer Fall 2 darf die Reaktion nicht lauten:

- "Story kann jetzt in Closure gehen"

Sondern nur:

- "Implementation ist jetzt verpflichtend"

Die Reaktionsmatrix muss diesen Zustand explizit modellieren.

---

## 24.11 Konsistenzanforderung fuer Story Types

Die Wertemenge der Story Types muss in allen normativen und ausfuehrbaren Stellen identisch sein:

- Domain-Modelle
- CLI-Choices
- Story-Attribut-Setup im AK3-Story-Backend
- Installer
- Context-Ableitung
- Worker-Routing
- Verify
- Integrity
- Policy
- Skills
- normative Dokumentation

Abweichungen sind Build- oder Review-Fehler.

---

## 24.12 Testpflichten

Folgende Tests sind Pflicht:

- `test_setup_fails_when_story_type_missing`
- `test_setup_fails_when_story_type_invalid`
- `test_story_type_enum_matches_project_field_catalog`
- `test_no_refactoring_story_type_in_runtime_contract`
- `test_no_refactor_alias_in_context_derivation`
- `test_exploration_for_implementation_sets_execution_pending`
- `test_verify_rejects_exploration_only_implementation_story`
- `test_verify_rejects_exploration_only_bugfix_story`
- `test_closure_blocks_exploration_only_implementation_story`
- `test_issue_cannot_be_closed_for_implementation_without_execution`
- `test_exploration_writes_human_readable_summary`

---

## 24.13 Architekturentscheidungen

### 24.13.0 Begruendungsprinzip fuer Story Types

Story Types werden in AgentKit nicht nach alltagssprachlicher Taetigkeit
benannt, sondern nach **governance-semantischem Verhalten**.

Ein Story Type ist nur dann zulaessig, wenn er einen eigenstaendigen
Runtime-Vertrag erzwingt, insbesondere in mindestens einem der folgenden Punkte:

- anderer erlaubter Wirkungsraum
- andere Verbote
- andere Pflichtartefakte
- andere Verify-/Closure-Regeln
- andere Impact-Grenzen
- andere Guardrail-/Governance-Behandlung

Wenn sich das System fuer einen vermeintlich neuen Typ nicht substantiell
anders verhalten muss, ist dieser Typ unzulaessig und darf nicht in die
kanonische Wertemenge aufgenommen werden.

### 24.13.1 Explizite Entscheidung

AgentKit kennt fachlich nur vier Story Types:

- `implementation`
- `bugfix`
- `concept`
- `research`

### 24.13.2 Explizite Entscheidung

`refactoring` ist **kein** Story Type von AgentKit.

Wenn `refactoring` oder `refactor` in produktivem Code, Setup, Installer,
GitHub-Felddefinitionen, Runtime-Routing oder normativer Doku auftaucht,
ist das als Defekt zu behandeln, sofern nicht eine dokumentierte
Migrations- oder Kompatibilitaetsausnahme vorliegt.

Begruendung:

- Refactoring erzeugt keinen eigenstaendigen Governance-Pfad.
- Refactoring hat keinen eigenstaendigen Abschlussvertrag.
- Refactoring ist keine eigene Lieferklasse, sondern eine moegliche
  Umsetzungsform innerhalb einer `implementation`.
- Wenn eine Aenderung funktional/systemisch wirkt, gelten ohnehin die
  Regeln der `implementation`.
- Wenn eine Aenderung nur lokal Fehler beseitigt und keinen erweiterten
  Impact haben darf, faellt sie in den Bereich `bugfix`.

Damit fehlt `refactoring` die noetige handlungsleitende Differenz zu den
existierenden Story Types.

Explizit gilt:

- Eine `implementation` darf Refactoring enthalten, wenn dies fuer die
  Umsetzung erforderlich ist.
- Ein `bugfix` darf lokale Umstellungen enthalten, solange die strengeren
  Impact-Grenzen des Bugfix-Vertrags eingehalten werden.
- Refactoring allein rechtfertigt niemals einen eigenen Story Type.

### 24.13.3 Explizite Entscheidung

Eine `implementation`- oder `bugfix`-Story darf nie mit reiner Exploration
geschlossen werden.

---

## 24.14 Konsequenz fuer BB2-093-artige Faelle

Ein Lauf wie BB2-093 haette nach diesem Vertrag so enden muessen:

- Exploration erfolgreich
- Exploration-Ergebnis sichtbar dokumentiert
- Story bleibt offen
- Implementierung ist verpflichtend
- Verify/Closure fuer einen exploration-only Zustand sind nicht terminal

Das Schliessen der Story waere nach diesem Vertrag unzulaessig.
