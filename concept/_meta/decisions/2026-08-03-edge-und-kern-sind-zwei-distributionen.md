---
concept_id: META-DEC-2026-08-03-EDGE-UND-KERN-SIND-ZWEI-DISTRIBUTIONEN
title: Concept-Decision-Record — Edge und Kern sind zwei Distributionen
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, deployment, packaging, FK-10, FK-01, FK-30]
formal_scope: prose-only
---

# Concept-Decision-Record — Edge und Kern sind zwei Distributionen

Datum: 2026-08-03. Entscheider: Product Owner.

## 1. Anlass

Bei der Bewertung eines Strukturbefunds aus AG3-180 fiel auf, dass
`harness_client` an **40 Stellen** aus `agentkit.backend.*` importiert. Die
Pruefung dieser Kante gegen das Zielbetriebsszenario ergab einen Befund, der
groesser ist als die Imports.

**Das Zielbetriebsszenario (PO, 2026-08-03):** Der Harness-Adapter laeuft auf
einem Entwicklerrechner — Windows oder macOS. Der Kern laeuft in der Cloud und
ist **ausschliesslich** ueber seine HTTP-Schnittstelle ansprechbar. Der Laptop
ist aus dem Internet **gar nicht** erreichbar.

**Der Befund:** AK3 wird als **eine einzige Distribution** ausgeliefert
(`pyproject.toml`, `[tool.hatch.build.targets.wheel] packages = ["src/agentkit"]`).
Wer den Hook auf dem Laptop installiert, installiert damit den vollstaendigen
Kern: den Postgres-Store, den Control-Plane-HTTP-Server, `psycopg`,
`weaviate-client` — auf einer Maschine, die die Datenbank nie sehen wird.

## 2. Was daran falsch ist — und was nicht

Die Importrichtung `harness_client -> backend` ist **nicht** per se der Fehler.
Der Fehler liegt eine Ebene tiefer:

- **Dev-seitiger Code liegt in der Kern-Deployment-Unit.**
  `backend/governance/runner.py` ist die Guard-Engine. Sie wird vom
  Hook-Wrapper aufgerufen und laeuft **im Hook-Prozess auf dem Laptop**. Sie
  liegt trotzdem unter `backend/`. Dasselbe gilt fuer
  `backend/story_creation/` und `backend/code_backend/provider_port`.
- Die 40 Kanten zerfallen in drei Klassen: **Wire-Vertraege/DTOs**
  (`control_plane.models`, `core_types.*`, `config.models`, `exceptions`) —
  gemeinsames Vokabular zweier Programme, legitim, falscher Ort;
  **ausfuehrende Engine** — Dev-Code am falschen Ort; **Hilfsfunktionen**
  (`utils.io`) — trivial, falscher Ort.

**Das Konzept sagt es bereits richtig.** FK-10 §10.1: *„Duenn sind die Raender,
nicht der Kern."* Dieselbe Stelle warnt sogar ausdruecklich davor, den
logischen Kern mit dem Python-Paket `agentkit.backend.*` zu verwechseln. Das
Artefakt loest diese Zusage nicht ein: der Rand ist duenn im Konzept und
traegt in der Auslieferung den ganzen Kern mit.

**AG3-129 hat die Trennung nur halb vollzogen.** Die Story (completed) hat den
Hook von der direkten PostgreSQL-Verbindung geloest — auf der **Datenebene**
korrekt und belegt. Auf der **Paketebene** ist sie nicht begonnen: der Hook
importiert die Engine unveraendert.

## 3. Entscheidung

**3.1 AK3 wird in zwei Distributionen ausgeliefert.** Ein Edge-Artefakt
(Hook-Adapter, ProjectEdge, Guard-Engine, CLI-Anteil des Bedieners) und ein
Kern-Artefakt. Begruendung des PO: der Laptop darf die Backend-Distribution
nicht mitschleppen.

**3.2 Die geteilten Wire-Vertraege bekommen ein eigenes, kleines
Vertragspaket.** Beide Seiten sprechen dasselbe Vokabular; genau dieses
Vokabular — und nichts sonst — wird geteilt.

**3.3 Die Grenze wird maschinell wahr, nicht konventionell.** Was der Edge
nicht importieren darf, ist auf dem Laptop **nicht installiert**. Eine
Konvention, die erst auffaellt, wenn jemand sie verletzt, ist keine Grenze.

**3.4 Guard-Evaluation bleibt Edge-seitig.** Sie muss einen Werkzeugaufruf
lokal und in Millisekunden entscheiden. Kanonischer Zustand geht weiterhin per
REST an den Kern (AG3-129, FK-10 §10.1.0 I1/I3) — das bleibt unveraendert. Der
Edge fuehrt aus, der Kern besitzt.

## 4. Nachtrag desselben Tages — Namen, Versionierung, Edge-Umfang

Beim Schnitt von AG3-208/209 blieben drei Fragen offen; der PO hat sie am
selben Tag entschieden.

**4.1 `agentkit` gehoert keinem der beiden Artefakte.** „AgentKit" ist der
**Framework-Name**. Das Framework hat ein Backend und einen Client (Project
Edge); die Artefaktnamen sind zusammengesetzt. Keine Distribution traegt den
blossen Namen `agentkit`.

Daraus folgt zwingend, dass auch die **Importwurzel** faellt: AK2 liefert ein
regulaeres Paket namens `agentkit` aus, und ein regulaeres Paket verdeckt
Namespace-Portionen gleichen Namens vollstaendig. Behielte AK3 `agentkit.*`,
waere der Zustand vom 2026-08-02 auf genau der Maschine reproduziert, auf der
er entstanden ist. **Damit ist der AK2-Namenskonflikt aufgeloest statt nur
isoliert** — FK-10 und `PROJECT_STRUCTURE.md` ziehen das in AG3-208 nach, und
die Wirkung auf AG3-189 ist gesondert zu bewerten.

**4.2 Eine Version fuer beide Artefakte, gebunden an den Repository-Stand.**
Beide werden aus einem Repository gebaut und synchron veroeffentlicht. Keine
unabhaengigen Reihen, kein Kompatibilitaetsbereich, keine Matrix — eine Matrix
waere genau die verbotene Kompatibilitaetsschicht. Die Drahtebene deckt der
`/v1/compat`-Handshake ab (AG3-121).

**4.3 Der Story-Knowledge-MCP und `weaviate-client` gehoeren zum Edge.** Der
lokal vom Harness gestartete Prozess bleibt auf dem Entwicklerrechner;
`weaviate-client` ist eine Edge-Abhaengigkeit. Das ist eine **bewusst
getragene Last**: der Rand wird dadurch schwerer, als er ohne diese
Abhaengigkeit waere. Die Alternative haette jede Wissensabfrage auf den
Netzweg gelegt.

## 5. Konsequenzen

- Der Schnitt beruehrt `pyproject.toml`, die Entry Points, den Installer,
  `PROJECT_STRUCTURE.md` und die Deployment-Unit-Regeln.
- **FK-10 geht dem Code voraus.** Die Frage „was genau ist der Edge" ist
  normativ zu beantworten, nicht im Code zu entdecken.
- Die normative Ausarbeitung ist in **AG3-208**, der atomare
  Distributionsschnitt in **AG3-209** geschnitten. **AG3-210** besitzt getrennt
  den Update-Pfad fuer das ausgelieferte Bundle.
- **AG3-189 und AG3-206 kurieren ein Symptom dieser Ursache.** Zwei parallele
  `agentkit`-Installationen mit getrennten Abhaengigkeiten (Fremdinstallation
  `intima`, 2026-08-02/03) waren nur moeglich, weil es genau ein Artefakt gibt,
  das alles enthaelt. Beide Storys bleiben gueltig; sie erzwingen Isolation und
  Vollstaendigkeit, sie verkleinern die Angriffsflaeche nicht.
- Bis der Schnitt landet, gilt die Grenze weiter als Konvention — **benannt
  und sichtbar**, nicht stillschweigend.

## 6. Impact-Sweep (P3/W4)

Geprueft wurden FK-10 als Eigentuemer von Runtime-Topologie, Deployment Units
und Thin-Edge-Zielbild, FK-01 fuer die Maschinen- und Netzwerk-Trust-Boundaries,
FK-30 fuer die lokal auszufuehrende Guard-Engine, FK-07 fuer den Wire-Vertrag,
FK-51 fuer den getrennten Upgrade-Pfad sowie `PROJECT_STRUCTURE.md` und
`pyproject.toml` fuer den heutigen Paket- und Build-Iststand. Der Record
entscheidet das Zielbild und die gemeinsame Versionsbindung, setzt den
Distributionsschnitt in AG3-180 aber nicht um. AG3-180 entfernt lediglich die
unerlaubte sechste Deployment Unit `agentkit.shared` und erzeugt auf der
Edge-Seite keine neue Backend-Importkante. Die normative Detailausarbeitung
liegt in AG3-208, die atomare Paket-/Importmigration in AG3-209 und der
Bundle-Updatepfad in AG3-210. AG3-189 und AG3-206 bleiben als eigenstaendige
Isolations- und Vollstaendigkeitsnachweise gueltig; sie ersetzen den Schnitt
nicht und werden von ihm nicht stillschweigend umdefiniert.

## 7. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-10 §10.1.1–§10.1.3 | nachzufuehren in AG3-208 | Edge, Kern, Vertragspaket, Artefaktnamen und gemeinsamer Versionsstand werden dort autoritativ ausformuliert. |
| FK-01 Trust Boundaries | geprueft, in AG3-208 zu praezisieren | Der Entwicklerrechner bleibt nicht erreichbar; der Core ist ausschliesslich ueber seinen geschuetzten HTTP-Vertrag erreichbar. |
| FK-30 Guard-Engine/Adapter | geprueft, in AG3-208 zu praezisieren | Guard-Evaluation bleibt lokal auf dem Edge, kanonischer Zustand im Core. |
| FK-07 Wire-Vertrag | geprueft, Umsetzung in AG3-209 | Das kleine gemeinsame Vertragspaket enthaelt nur Wire-Vokabular und keine ausfuehrende Engine. |
| FK-51 Upgrade | geprueft, Umsetzung in AG3-210 | Der Update-Pfad muss das gebundene Edge-Bundle tatsaechlich ausrollen. |
| `PROJECT_STRUCTURE.md` | geprueft, nachzufuehren in AG3-208/209 | Die heutigen Deployment-Unit-Regeln bilden den Zwei-Distributions-Schnitt noch nicht ab; AG3-180 legalisiert keine sechste Unit. |
| `pyproject.toml`, Paketnamen und Entry Points | Umsetzung in AG3-209 | Build-Artefakte und Importwurzeln werden atomar getrennt; bis dahin bleibt der aktuelle Iststand bestehen. |
| AG3-180 | begrenzt betroffen | `agentkit.shared` entfaellt; Core- und Edge-Dateirechte bleiben getrennt, ohne den Distributionsschnitt vorwegzunehmen. |
| AG3-189 und AG3-206 | geprueft, nicht ersetzt | Installationsisolation und Abhaengigkeitsvollstaendigkeit bleiben eigene Auftraege. |
| AG3-208 | normativer Umsetzungslocator | Zieht das Zielbild in die zulaessigen autoritativen Konzeptstellen nach. |
| AG3-209 | technischer Umsetzungslocator | Realisiert Distributionen, Importwurzeln, Vertragspaket und Buildgrenzen atomar. |
| AG3-210 | getrennter Umsetzungslocator | Realisiert den Bundle-Updatepfad ohne den Distributionsschnitt zu duplizieren. |
