---
concept_id: META-DEC-2026-08-06-NO-REEXPORT-FACADES
title: Concept-Decision-Record — Reexport-Fassaden sind in AK3 nicht zulaessig
module: meta
cross_cutting: true
status: active
authority_over: []
doc_kind: decision-record
defers_to:
  - target: FK-07
    scope: architecture-conformance
    reason: FK-07 owns the import boundaries and the conformance suite that must carry this prohibition
supersedes: []
superseded_by:
tags: [meta, decision-record, architecture-conformance, imports, AG3-229]
formal_scope: prose-only
---

# Concept-Decision-Record — Reexport-Fassaden sind in AK3 nicht zulaessig

Datum: 2026-08-06. Record fuer AG3-229, Blocker B2 der unabhaengigen Review.

## 1. Anlass

Der Importpfad `agentkit.backend.control_plane.http` existierte seit AG3-090
als reine Reexport-Fassade auf `agentkit.backend.control_plane_http`. Das
Modul bezeichnete sich in seinem eigenen Docstring als „Compat re-export",
damit „existing callers … continue to resolve". `CLAUDE.md`
§KEINE KOMPATIBILITAETSSCHICHTEN verbietet Reexport-Fassaden ausnahmslos und
verpflichtet zu ihrer Entfernung.

Der eigentliche Befund lag jedoch tiefer als das Modul: **Die Architekturregeln
erlaubten die verbotene Konstruktion.** Der deterministische
Architektur-Konformanz-Gate konnte deshalb gruen werden, obwohl die
Grundregel absolut verbietet, was er durchwinkte:

- `concept/formal-spec/architecture-conformance/entities.md` fuehrte
  `agentkit.backend.control_plane.http` neben dem kanonischen
  `agentkit.backend.control_plane_http` als zweiten `module_prefixes`-Eintrag der
  Boundary `architecture-conformance.boundary.control_plane_http` — die Fassade
  war damit ein regulaer klassifiziertes Boundary-Modul.
- FK-07 §7.8 Punkt 5 erlaubte ausdruecklich, dass „kompatible Legacy-Reexporte"
  aus zugelassenen Komponentenoberflaechen importiert werden duerfen.

Ein Gate, das eine verbotene Konstruktion durchwinkt, ist schlimmer als kein
Gate: Es bescheinigt Konformitaet, wo keine ist.

## 2. Entscheidung

**In AK3 hat jedes Symbol genau einen Importpfad.** Ein Modul, dessen Zweck
ausschliesslich darin besteht, Namen aus einem anderen Modul unter einem
zweiten Pfad erreichbar zu halten, ist unzulaessig — unabhaengig davon, ob es
eine zweite Definition traegt. Der SINGLE-SOURCE-OF-TRUTH-Beweis „es ist ja
dieselbe Klasse" rechtfertigt eine Fassade nicht; er beschreibt nur, dass sie
keinen *zusaetzlichen* Defekt einfuehrt.

Daraus folgt konkret:

1. `agentkit.backend.control_plane.http` ist geloescht. Der einzige
   Importpfad ist `agentkit.backend.control_plane_http` (`.app` fuer
   `ControlPlaneApplication` / `ControlPlaneApplicationRoutes` / `HttpResponse`,
   `.server` fuer `serve_control_plane`, `.tenant_scope` fuer
   `TenantScopeMiddleware`).
2. Die Architekturregeln tragen das Verbot ab jetzt, statt es zu unterlaufen:
   Der zweite `module_prefixes`-Eintrag der Boundary `control_plane_http` ist
   gestrichen, und FK-07 §7.8 Punkt 5 nennt Reexport-Fassaden ausdruecklich als
   **keine** zulaessige Importoberflaeche.
3. Alles, was nur der Fassade wegen existierte, ist mitentfernt — insbesondere
   der Identitaetstest `test_compat_reexport_is_same_class`, der die
   Klassengleichheit ueber die beiden Pfade bewies. Ohne zweiten Pfad hat er
   keinen Gegenstand mehr; ihn stehen zu lassen haette den geloeschten Pfad
   ueber die Testsuite wiederbelebt.

**Mit der Fassade verschwinden ihre Regelnennungen — in beide Richtungen.**
Eine Fassade hinterlaesst zwei Sorten von Spuren in den Architekturregeln, und
beide sind schaedlich:

- **Erlaubende Nennungen** (die Fassade als klassifiziertes Boundary-Modul)
  bescheinigen Konformitaet, wo keine ist. Sie sind der Befund dieses Records.
- **Verbietende Nennungen** (die Fassade als `forbidden_module_prefixes`)
  sehen aus wie Schutz und sind keiner. Wer sie liest, haelt den Importpfad fuer
  abgesichert; tatsaechlich zeigt die Regel ins Leere, und legte jemand morgen
  ein Modul desselben Namens an, griffe sie wieder, ohne dass das jemand
  entschieden haette.

Der zweite Fall war hier der gravierendere und **aelter als diese Story**: Die
Invarianten „Story/Dashboard koppeln nicht an den Control-Plane-Transport" und
„ProjectEdge koppelt nicht an den Control-Plane-Transport" nannten seit dem
Modulumzug in AG3-090 ausschliesslich die Fassade und **nie** den kanonischen
Traeger `agentkit.backend.control_plane_http`. Beide Invarianten waren damit
seit AG3-090 wirkungslos: Ein direkter Import des kanonischen Transportmoduls
aus `story`, `dashboard` oder `projectedge` waere durch keine der beiden Regeln
aufgefallen.

Daraus folgt die Unterscheidung, nach der die Nennungen behandelt wurden:

- Wo die Regelabsicht fortbesteht und nur der Name tot war, wird der Name
  **auf den kanonischen Traeger gezogen**, nicht gestrichen. Eine Invariante zu
  loeschen, weil sie falsch verdrahtet war, wuerde die Luecke bestaetigen statt
  sie zu schliessen. Betroffen: die beiden oben genannten Invarianten
  (`architecture-conformance.rule.story_dashboard_must_not_depend_on_transport_or_hook_adapters`,
  `architecture-conformance.rule.projectedge_must_not_depend_on_control_plane_http`)
  samt ihrer Prosaspiegelung in FK-07 §7.9 Punkt 1 und 5. Beide sind damit zum
  ersten Mal wirksam; der Konformanz-Gate bleibt gruen, es gibt also keinen
  bestehenden Verstoss, den diese Reparatur aufdeckt.
- Wo die Nennung nur eine **Dopplung** des bereits vorhandenen kanonischen
  Praefixes war, wird sie ersatzlos gestrichen. Betroffen:
  `architecture-conformance.rule.control_plane_http_must_not_depend_on_state_backend_repository`,
  dessen `source_module_prefixes` beide Pfade fuehrte.

Keine `dependency_rule` wurde durch die Bereinigung leer oder gegenstandslos;
es musste daher keine Regel als Ganzes entfallen.

## 3. Alternativen

- **Fassade als „harmlos" belassen, weil sie kein Verhalten aendert.**
  Verworfen: Die Grundregel verbietet nicht den Schaden, sondern den zweiten
  Importweg, den ab sofort jeder mitlesen, mitpflegen und mitpruefen muss.
- **Fassade entfernen, Konzeptstellen unveraendert lassen.** Verworfen: Die
  Erlaubnis waere stehen geblieben und die naechste Fassade regelkonform
  entstanden. Der Befund ist die Erlaubnis, nicht das Modul.
- **Verbot nur in `CLAUDE.md` fuehren.** Verworfen: `CLAUDE.md` ist keine
  maschinell gepruefte Oberflaeche. Ein Verbot, das der Gate nicht traegt, ist
  ein Verbot mit gruenem Beleg dagegen.

## 4. Impact-Sweep

Gesucht wurde repo-weit nach `control_plane.http` sowie nach den Begriffen
`compat`, `re-export`, `reexport` und `Legacy-Reexport` in `concept/`, `src/`,
`tests/` und `scripts/`. Ergebnis:

- **Ein** produktiver Aufrufer: `src/agentkit/backend/cli/serve.py`
  (`_default_serve_fn`), auf `control_plane_http.server` umgezogen.
- Vierzehn Testmodule mit Import ueber die Fassade sowie zwei
  `monkeypatch`-Ziele in den CLI-Tests, alle auf den kanonischen Pfad gezogen.
- Zwei Modul-Docstrings (`control_plane_http/__init__.py`,
  `control_plane_http/app.py`), die die Fassade beschrieben.
- Die erlaubende Konzeptstelle (Boundary-Praefix) und die Legacy-Reexport-
  Erlaubnis in FK-07 §7.8 Punkt 5.
- Die drei verbietenden Konzeptstellen in `invariants.md` samt Prosaspiegelung
  in FK-07 §7.9 Punkt 1 und 5.

Zusaetzlich wurde `concept/formal-spec/architecture-conformance/**` maschinell
gegen den Codebestand geprueft: 178 gepunktete `agentkit.`-Referenzen, davon 33
ohne Modul oder Paket auf der Platte. Ausserhalb des hier behobenen
Reexport-Falls bleiben diese unangetastet und sind als eigener Befund
festgehalten (siehe Betroffenheitsmatrix).

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| `backend/control_plane/http.py` | entfernt | Reine Reexport-Fassade ohne eigene Definition. |
| `backend/cli/serve.py` | geaendert | Einziger produktiver Aufrufer; laedt jetzt `control_plane_http.server`. |
| `control_plane_http/__init__.py`, `app.py` | geaendert | Docstrings sagten die Fassade als bestehende Oberflaeche zu. |
| FK-07 §7.8 Punkt 5 | geaendert | Erlaubnis fuer „kompatible Legacy-Reexporte" gestrichen. |
| `formal-spec/architecture-conformance/entities.md` | geaendert | Zweiter `module_prefixes`-Eintrag der Boundary `control_plane_http` gestrichen. |
| `formal-spec/architecture-conformance/invariants.md` | geaendert | Drei tote Nennungen in `dependency_rules`: zwei auf den kanonischen Traeger gezogen (Regelabsicht besteht fort, war seit AG3-090 wirkungslos), eine als Dopplung gestrichen. |
| FK-07 §7.9 Punkt 1 und 5 | geaendert | Prosaspiegelung der beiden reparierten Invarianten; nennt jetzt denselben kanonischen Traeger wie die Formal-Spec. |
| Testsuite | geaendert | Importe umgezogen; der reine Fassaden-Identitaetstest entfaellt mit seinem Gegenstand. |
| `backend/state_backend/postgres_store/__init__.py` | Befund, Folgestory | Zweite, deutlich groessere Reexport-Fassade („Compatibility import surface", dynamische Reflexion ueber 272 Namen). Faellt unter dasselbe Verbot, aber nicht unter dieses Mandat. |
| Uebrige stale Praefixe in `architecture-conformance/**` | Befund, Folgestory | 32 weitere Praefixe ohne Modul auf der Platte. Zwei Klassen: vorausgreifende Komponentengruppen-/Boundary-Praefixe in `entities.md` (Klassifikation vor Implementierung, kein Fehlschutz) und wirkungslose Regelpraefixe in `invariants.md` — `agentkit.dashboard`, `agentkit.pipeline`, `agentkit.backend.governance.hookruntime`. Letztere sind dieselbe Krankheit wie der hier reparierte Fall und brauchen dieselbe Entscheidung je Regel. Betreffen nicht den entfernten Reexport, daher hier nicht behoben. |

## 6. P4-Formalisierungspruefung

Nein — die Entscheidung fuegt keinen neuen Vertrag hinzu, sondern streicht eine
Erlaubnis aus einem bestehenden. Der formale Architektur-Konformanz-Vertrag
bleibt strukturell unveraendert; er verliert genau einen Boundary-Praefix.
