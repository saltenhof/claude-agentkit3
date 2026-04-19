---
concept_id: FK-57
title: Integrationsstabilisierung und systemischer E2E-Vertrag
module: integration-stabilization
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: integration-stabilization
  - scope: integration-scope-manifest
  - scope: stabilization-budget
  - scope: stability-gate
defers_to:
  - target: FK-59
    scope: story-contract-classification
    reason: implementation_contract wird dort als zweite persistente Vertragsachse konsolidiert
  - target: FK-24
    scope: story-type-contract
    reason: Story-Typ und Lieferpflicht bleiben dort kanonisch
  - target: FK-25
    scope: scope-explosion-classification
    reason: Scope-Explosion bleibt der harte Eskalationsmechanismus
  - target: FK-26
    scope: implementation-runtime
    reason: Worker-Loop und Drift-Mechanik werden dort operationalisiert
  - target: FK-27
    scope: verify-and-closure
    reason: Verify- und Closure-Pfade bleiben dort kanonisch
  - target: FK-55
    scope: principal-capabilities
    reason: Storybezogene Schreibrechte muessen capability-scharf bleiben
supersedes: []
superseded_by:
tags: [integration, e2e, stabilization, implementation-contract, manifest, stability-gate]
prose_anchor_policy: strict
formal_refs:
  - formal.integration-stabilization.entities
  - formal.integration-stabilization.state-machine
  - formal.integration-stabilization.commands
  - formal.integration-stabilization.events
  - formal.integration-stabilization.invariants
  - formal.integration-stabilization.scenarios
  - formal.story-contracts.invariants
---

# 57 — Integrationsstabilisierung und systemischer E2E-Vertrag

<!-- PROSE-FORMAL: formal.integration-stabilization.entities, formal.integration-stabilization.state-machine, formal.integration-stabilization.commands, formal.integration-stabilization.events, formal.integration-stabilization.invariants, formal.integration-stabilization.scenarios, formal.story-contracts.invariants -->

## 57.1 Zweck

Es gibt spaete User Stories, deren fachlicher Zweck **nicht** ein
einzelnes Feature oder ein lokaler Bugfix ist, sondern die kontrollierte
Zusammenfuehrung und Stabilisierung mehrerer bereits gelieferter
Anwendungsteile.

Typische Beispiele:

- echte End-to-End-Integrationslaeufe ueber mehrere Subsysteme
- systemische Stabilisierung nach grossen Merge- oder Release-Wellen
- letzte Integrationsschleife vor produktionsnaher Abnahme

Diese Stories duerfen in AK3 **nicht** als stiller Freibrief fuer
beliebige Cross-Scope-Arbeit behandelt werden. Sie brauchen einen
eigenen, explizit deklarierten Liefervertrag.

## 57.2 Grundentscheidung

AK3 fuehrt dafuer **keinen neuen Betriebsmodus** ein.

Es fuehrt auch **nicht** vorschnell einen neuen kanonischen Story-Typ
ein.

Stattdessen gilt:

1. `story_type` bleibt `implementation`
2. zusaetzlich wird ein Pflichtfeld `implementation_contract`
   ausgewertet
3. fuer normale Stories gilt `implementation_contract=standard`
4. fuer systemische Integrations- und Stabilisierungslagen gilt
   `implementation_contract=integration_stabilization`

Der Story-Typ bleibt also der Liefervertragstyp.
`implementation_contract` praezisiert den **Ausfuehrungsvertrag**
innerhalb dieses Typs.

Im konsolidierten Vertragsmodell gemaess FK-59 ist
`implementation_contract` damit genau die zweite persistente
Vertragsachse neben `story_type` und gerade **keine** freie
Metadaten-Erweiterung.

## 57.3 Abgrenzung

`integration_stabilization` ist:

- **kein** freier `ai_augmented`-Modus
- **kein** Lockern der Guards
- **kein** Ersatz fuer Scope-Explosion
- **kein** Ersatz fuer Story-Split
- **kein** Story-Reset

`integration_stabilization` ist ein **engerer, staerker deklarierter**
Story-Vertrag fuer bewusst breite, aber kontrollierte
Integrationsarbeit.

## 57.4 Wann dieser Vertrag zulaessig ist

Der Vertrag ist nur zulaessig, wenn die Story fachlich tatsaechlich
darauf zielt,

- mehrere Anwendungsteile zusammenzufuehren,
- Integrationsbrueche aufzudecken,
- systemische Regressionen zu beseitigen,
- und die Gesamtanwendung auf definierte Stabilitaetsziele zu bringen.

Nicht zulaessig ist der Vertrag fuer:

- normale Feature-Umsetzung mit schlecht geschnittenem Scope
- “wir wissen noch nicht, was wir tun”
- opportunistisches Cross-Scope-Refactoring
- nachtraegliches Legitimieren bereits ausgebrochener Arbeit

## 57.5 Integrations-Scope-Manifest

### 57.5.1 Pflichtartefakt

Vor produktiver Integrationsarbeit muss ein
`integration_scope_manifest` vorliegen und offiziell freigegeben sein.

Ohne dieses Manifest gilt:

- keine produktive Integrationsmutation
- kein Worker-Spawn fuer `integration_stabilization`
- keine Aktivierung des erweiterten Cross-Scope-Profils

### 57.5.2 Mindestinhalt

Das Manifest beschreibt mindestens:

- `project_key`
- `story_id`
- `implementation_contract`
- `target_seams`
- `allowed_repos_paths`
- `integration_targets`
- `allowed_contract_changes`
- `stabilization_budget`
- `out_of_contract_examples`

### 57.5.3 Ziel des Manifests

Das Manifest macht aus “breiter Integrationsarbeit” einen **explizit
deklarierten, begrenzten Arbeitsraum**.

Die Frage lautet nicht mehr:

> Darf diese Story breit arbeiten?

sondern:

> Ist genau diese Beruehrungsflaeche, in genau diesem Umfang, fuer diese
> Story genehmigt?

### 57.5.4 Genehmigung ist attestiert, nicht nur dateibasiert

Ein lokales `integration_scope_manifest.json` ist fuer AK3 alleine
**kein** Genehmigungsnachweis.

Die Freigabe ist nur gueltig, wenn zusaetzlich ein offizieller,
attestierter `manifest_approval_record` existiert:

- erzeugt durch `human_cli` oder offiziellen `admin_service`
- gebunden an `project_key + story_id + run_id`
- mit Hash und Version des genehmigten Manifests

Fehlt dieser Approval-Record, bleibt jeder Verweis auf ein lokales
Manifest fail-closed blockiert.

### 57.5.5 Repo-Set-Grenze

Das Manifest darf keine neuen produktiven Repositories einfuehren, die
nicht bereits Teil des aktiven Story-Runs sind.

Es darf nur Pfade innerhalb der bereits gebundenen `worktree_roots` /
Participating Repos autorisieren.

Neue Repositories oder neue Worktrees sind kein Manifest-Detail,
sondern ein separater Replan-/Setup-Fall.

## 57.6 Exploration- und Setup-Regel

Fuer `implementation_contract=integration_stabilization` gilt:

1. Exploration ist **immer Pflicht**
2. Setup darf nicht direkt auf normalen `execution`-Pfad routen
3. Exploration muss mindestens erzeugen:
   - Integrations-Scope-Manifest
   - Integrationszielmatrix
   - Stabilisierungshaushalt / Budget
   - explizite Out-of-Contract-Liste

Erst nach offizieller Freigabe des Manifests darf die Story in die
produktive Integrationsschleife wechseln.

Wird der Manifest-Entwurf abgelehnt, bleibt die Story `PAUSED` und geht
in:

- Replan
- Story-Split
- oder kontrollierten Abbruch

Ein abgelehnter Entwurf wird nie still als Arbeitsgrundlage verwendet.

## 57.7 Scope-Explosion bleibt erhalten

### 57.7.1 Neue Bezugsbasis

Fuer `integration_stabilization` wird Scope-Explosion **nicht**
abgeschaltet, sondern gegen eine andere Bezugsbasis bewertet:

- `story.md`
- plus `integration_scope_manifest`

### 57.7.2 Regel

Innerhalb des genehmigten Manifests ist breite Integrationsarbeit
zulaessig.

Ausserhalb des genehmigten Manifests bleibt sie:

- `scope_explosion`
- oder `impact_exceeded`

Insbesondere gilt:

- ein neues, nicht deklariertes Zielsystem
- eine neue, nicht deklarierte Schnittstelle
- ein produktiver Pfad ausserhalb `allowed_repos_paths`
- eine neue Contract-Klasse ausserhalb `allowed_contract_changes`

ist **kein** normaler Stabilisierungsfund, sondern ein Eskalationsfall.

### 57.7.3 Keine Rueckwaerts-Legalisierung

Wird eine zuvor als `standard` laufende Story offiziell in
`integration_stabilization` reklassifiziert, duerfen bereits
entstandene Cross-Scope-Deltas **nicht** rueckwirkend legalisiert
werden.

Pflichtregel:

- vor Reklassifikation entstandene out-of-scope Deltas werden separat
  quarantainiert und menschlich bewertet
- erst ab dem genehmigten Manifest-Snapshot beginnt der regulaere
  Integrationsvertrag
- dies materialisiert sich mindestens in neuer `evidence_epoch` und
  neuem manifestgebundenen Capability-Overlay

## 57.8 Stabilisierungsschleife

Die Story darf im aktiven Vertrag zyklisch arbeiten:

1. Integrationsziel ausfuehren
2. systemischen Defekt feststellen
3. innerhalb des genehmigten Manifests beheben
4. Integrations-Verify erneut laufen lassen

Diese Schleife ist aber strikt budgetiert.

## 57.9 Stabilization Budget

Das Budget ist kein Reporting-Wert, sondern ein hartes Steuerungsobjekt.

Es begrenzt mindestens:

- Zahl der Stabilisierungsschleifen
- Zahl neuer betroffener Pfadgruppen / Surfaces
- Zahl deklarierter Contract-Aenderungen
- zulaessige Regressionen zwischen zwei Verify-Zyklen

Wird das Budget gerissen, endet die Schleife nicht still, sondern in:

- `PAUSED.integration_replan_required`
- `requires_decomposition`
- oder `ESCALATED.integration_budget_exhausted`

**Technikregel:** Das Budget wirkt nicht nur in Verify. Es muss bereits
im Hook-/Capability-Layer live blockieren, sobald der naechste
produktive Stabilisierungsschritt ausserhalb des Restbudgets liegen
wuerde.

## 57.10 Verify-Profil

Der Vertrag verwendet **keine weichere** Verify-Pipeline, sondern ein
spezialisiertes Profil innerhalb des bestehenden Verify-Rahmens.

Pflichtsaeulen sind:

- deterministische Contract-/Seam-Pruefung
- Integrationszielmatrix
- Regression-/E2E-Nachweis
- bestehende QA-/Policy-Mechanik

Zusaetzlich gilt ein spezielles Gate:

- `stability_gate`

Dieses Gate prueft mindestens:

- alle `integration_targets` erreicht
- keine `undeclared_surface` offen
- Stabilisierung innerhalb des freigegebenen Budgets
- keine offenen hochkritischen Findings

`declared_surfaces_only` ist dabei **kein** LLM-Urteil, sondern ein
deterministischer Schicht-1-/Guard-Check gegen Diff, Manifest,
Seam-Allowlist und aktives Repo-Set.

## 57.11 Closure-Regel

Closure darf fuer `integration_stabilization` nur laufen, wenn:

1. `stability_gate = PASS`
2. alle deklarierten Integrationsziele erreicht sind
3. keine ungeklaerte Manifest-Verletzung offen ist
4. kein Replan-/Split-Bedarf mehr besteht

Damit bleibt Closure hart. Der Vertrag erweitert die
Eingangsvoraussetzungen, waechst sie aber nicht weich.

## 57.12 Capability- und Guard-Schnitt

`integration_stabilization` lockert keine Plattformgrenzen global.

Stattdessen aktivieren die Guards ein **engeres Overlay**:

- Cross-Scope-Write ist nur innerhalb `allowed_repos_paths` zulaessig
- neue Zielsysteme oder neue Pfadklassen bleiben blockiert
- Guard-Entscheidungen muessen gegen einen lokal materialisierten
  `seam_allowlist`-Export pruefen
- freies Weiterschreiben ausserhalb der deklarierten Integrationsflaeche
  bleibt technisch blockiert

## 57.13 Replan, Split oder Weiterfuehrung

Wenn eine als `standard` gestartete Implementation-Story in der Praxis
ein legitimer Integrations-/Stabilisierungsfall ist, gilt:

1. die Story geht zunaechst regulaer auf `PAUSED`
2. der Mensch entscheidet offiziell:
   - `split-story`
   - `cancel`
   - oder Reklassifikation nach
     `implementation_contract=integration_stabilization`
3. eine Weiterfuehrung derselben Story ist nur ueber diesen offiziellen
   Reklassifikationspfad zulaessig

Es gibt also **keinen** stillen Rueckkanal von Scope-Explosion zu
ungeplannter Breit-Weiterarbeit.

Wenn sich dagegen zeigt, dass nicht mehr ein Scope-, Repo- oder
API-Mandat die Kernfrage ist, sondern die Tragfaehigkeit des gesamten
Loesungsvorschlags, ist statt weiterer Story-Dehnung auch der
offizielle Story-Exit gemaess FK-58 zulaessig.

## 57.14 Technische Materialisierung

Damit der Vertrag nicht in Prosa stecken bleibt, braucht AK3:

1. `integration_scope_manifest.schema.json`
2. `manifest_approval_record.schema.json`
3. lokale Hook-Materialisierung:
   - `.agent-guard/seam_allowlist.json`
   - `.agent-guard/stabilization_budget.json`
   - `.agent-guard/manifest_approval.json`
4. Guard-Overlay fuer `worker`-Writes
5. Verify-Registry-Eintrag fuer `stability_gate`
6. eigene Telemetrie fuer Manifest-Freigabe, Undeclared-Surface und
   Budget-Erschoepfung

## 57.15 Normative Zusammenfassung

Der Vertrag erlaubt **breite Integrationsarbeit ohne manuelles
Guard-Bypassen**, aber nur unter drei harten Bedingungen:

1. die Breite ist **vorab deklariert**
2. die Breite ist **technisch gegen Manifest und Budget erzwungen**
3. neue, nicht deklarierte Breite bleibt **harter Eskalationsfall**
