---
concept_id: META-DEC-2026-07-14-THIRD-PARTY-BACKEND-MEDIATION
title: Concept-Decision-Record — Dritt-System-Backend-Mediation
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, installer, third-party, mediation, secrets, AG3-132]
formal_scope: prose-only
---

# Concept-Decision-Record — Dritt-System-Backend-Mediation

Datum: 2026-07-14. Record gemaess META-CONCEPT-CONSISTENCY P3 und
W4, auf Grundlage des Design Freeze fuer AG3-132.

## 1. Anlass

Der Projektraum-Installer erzeugte Sonar- und Jenkins-Clients im
Dev-Prozess und fuehrte Erreichbarkeits-, Token- und Plugin-Probes
direkt aus. Damit lagen Secret-Aufloesung und Dritt-System-Zugriff
ausserhalb der in FK-10 §10.1.0 I2 geforderten Backend-Mediation.
Zugleich war der schwere, mutierende Branch-Plugin-Self-Test mit dem
synchronen CP10d-Preflight gekoppelt und konnte dadurch implizit bei
Registrierung oder Verifikation laufen.

## 2. Entscheidung

Die Control Plane besitzt mit `ThirdPartyPreflightService` genau eine
in-process Capability fuer Dritt-System-Validierung. Der Installer
nutzt ausschliesslich den offiziellen Project Edge Client und den
projekt-skopierten Endpoint
`POST /v1/projects/{project_key}/installation/third-party-validation`.
Eine unskopierte Route und ein zweiter Transport existieren nicht.
Projekt-Token, Tenant-Scope, Versions-Handshake, Correlation-ID und
client-beigestellte `op_id`-Idempotenz gelten unveraendert.

Die synchrone leichte Validierung umfasst Sonar-/Jenkins-
Erreichbarkeit, Token-Gultigkeit, Sonar-Mindestversion und
Branch-Plugin-Praesenz sowie bei `features.are: true` den
authentifizierten ARE-Health-Read. Der Backend-Service loest nur
`token_env`-Referenzen in seiner eigenen Umgebung auf. Secret-Werte
ueberschreiten den Wire nie und werden an der Service-Grenze aus
Details, Fehlern, Telemetrie und Logs redigiert. Bei Backend- oder
Dritt-System-Ausfall bricht der Installer sichtbar fail-closed ab;
es gibt keinen Dev-Fallback.

Die einzige lokale Ausnahme ist die Dateiexistenzpruefung des
Default-Sonar-Profils als Pre-Send-Konfigurationsvalidierung. Sie ist
kein Dritt-System-Probe und uebertraegt keinen `repo_root` zum Backend.
`verify-project` darf die leichten Live-Reads ausfuehren, mutiert aber
weder Dritt-Systeme noch Registrierungszustand.

Der schwere Branch-Plugin-Conformance-Self-Test ist eine explizite
on-demand Operation ueber
`POST /v1/projects/{project_key}/installation/branch-plugin-self-test`.
Er antwortet mit `202` und `op_id`, laeuft in einem bounded Backend-
Executor, persistiert genau einen idempotenten
`ControlPlaneOperationRecord` und wird ueber
`GET /v1/project-edge/operations/{op_id}` gepollt. Register und Verify
starten ihn niemals implizit.

## 3. Alternativen

- Direkte Sonar-/Jenkins-Clients im Dev-Prozess wurden verworfen, weil
  sie Backend-Mediation, Secret-Grenze und eine einzige
  Validierungsheimat verletzen.
- Ein Backend-Endpoint plus Dev-Fallback wurde verworfen, weil ein
  Control-Plane-Ausfall sonst zum Error-Bypass wuerde.
- Ein gemeinsamer synchroner Endpoint fuer leichte und schwere
  Pruefung wurde verworfen, weil Verify read-only bleiben und Register
  keine mutierende Konformanzpruefung implizit starten darf.
- Ein neues allgemeines Async-Framework wurde verworfen; der bestehende
  Operation-Record und der kanonische Operation-GET genuegen fuer diese
  eng begrenzte, nicht-story-skopierte Infrastrukturpruefung.

## 4. Impact-Sweep (P3/W4)

Der Sweep umfasst FK-01 §1.1a, FK-03, FK-10 §10.1.0 I2 sowie
§10.2.1/§10.2.2, FK-50 §50.2/§50.3, FK-72 §72.8.2, FK-91 §91.1a und
die formalen Installer-Commands, -Invarianten, -State-Machine und
-Szenarien. FK-33 §33.6 und FK-27 §27.6a wurden auf Gate-Semantik
geprueft und bleiben unveraendert; die Entscheidung verschiebt nur
Mediation, Timing und Secret-Aufloesung der Installer-Vorbedingung.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-01 §1.1a | bestaetigt | Integration-Clients bleiben duenne externe Adapter; Semantik liegt im Backend-Service. |
| FK-03 | geaendert | `token_env` ist Backend-aufgeloeste Referenz fuer Sonar, Jenkins und ARE; kein Inline-Secret. |
| FK-10 §10.1.0 I2/§10.2.1/§10.2.2 | geaendert | Projektraum konsumiert die backend-vermittelte Capability ueber Project Edge. |
| FK-50 §50.2/§50.3 | geaendert | CP10d konsumiert den leichten Backend-Entscheid; lokaler Profilcheck bleibt; Heavy ist explizit async. |
| FK-72 §72.8.2 | geprueft, nicht geaendert | Eine Control-Plane-Route bleibt die BFF-/Service-Grenze; keine neue Frontend-Semantik. |
| FK-91 §91.1a | geaendert | Sync-/Async-Endpoint, Handshake, Idempotenz, Operation-Row und begrenzte Regel-14-Ausnahme sind gepinnt. |
| `formal.installer.commands` | geaendert | Backend-Validierung und expliziter Self-Test sind formale Commands. |
| `formal.installer.invariants` | geaendert | Backend-Ownership, Secret-Grenze, lokaler Profil-Wobble, Fail-Closed und Light/Heavy-Split sind explizit. |
| `formal.installer.state-machine` | geaendert | Dritt-System-Validierung liegt zwischen Bindung und Verifikation; die Async-Operation veraendert den Registrierungsstatus nicht. |
| `formal.installer.scenarios` | geaendert | Happy Path, beide Fail-Closed-Negative und idempotenter Async-Self-Test sind nachvollziehbar. |
| W1-Referenz-Baseline | nur Zeilenanker nachgezogen | Drei bestehende, unveraenderte Target-Projekt-Pfad-Ausnahmen wurden auf ihre durch diese Textaenderung verschobenen Zeilen aktualisiert; keine neue Ausnahme. |
| FK-33 §33.6 / FK-27 §27.6a | geprueft, nicht geaendert | Green-/Accept-Gate-Semantik bleibt SSOT im Verify-System-BC. |

## 6. P4-Formalisierungspruefung

Ja. Die Entscheidung ist als Command-, Invariant-, State-Machine-
und Szenario-Aenderung formalisiert. Die schwere Operation ist kein
neues allgemeines Async-Story-Modell, sondern ein eng begrenzter,
nicht-story-skopierter `ControlPlaneOperationRecord`-Lebenszyklus.
Ein Baseline-Eintrag fuer einen unformalisierten W2-/W3-Befund ist
nicht erforderlich.
