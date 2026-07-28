---
concept_id: META-DEC-2026-07-28-VECTORDB-ENDPOINT-CONSOLIDATION
title: Concept-Decision-Record — VektorDB-Adressquelle konsolidiert, MCP-Registrierungsvertrag praezisiert
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, config, installer, mcp, harness, FK-03, FK-13, FK-50, FK-76]
formal_scope: prose-only
---

# Concept-Decision-Record — VektorDB-Adressquelle konsolidiert, MCP-Registrierungsvertrag praezisiert

Datum: 2026-07-28. Zwei ratifizierte Entscheidungen aus der Umsetzung von
**AG3-175** (projektlokale MCP-Registrierung fuer Claude Code und Codex).

- **D-2** ist eine **PO-Entscheidung**: `vectordb.host` / `vectordb.port` werden
  **entfernt**, nicht deprecated.
- **D-3** autorisiert die **Nachziehung** des MCP-Registrierungsvertrags in vier
  Konzepten. Es wird kein neuer Scope erfunden: der Code folgt bereits dem
  Konsumenten, und die Dokumente holen auf.

Beide Entscheidungen sind vom PO getroffen; dieser Record verankert sie normativ.

---

## D-2 — `vectordb.host` / `vectordb.port` entfernt (PO-ENTSCHEIDUNG)

### Befund

`VectorDbConfig` trug nach AG3-175 **beide** Formen gleichzeitig: die zwei neuen
Felder `weaviate_http_endpoint` / `weaviate_grpc_endpoint` (gelesen von CP 10) und
die alten `host` / `port` (gelesen von `story_creation/runtime_factory.py` und
`vectordb/wait_for_weaviate.py`). Zwei Wege, dieselbe Tatsache auszudruecken —
**wo liegt Weaviate** — ohne jede Beziehung zwischen ihnen. Das ist die zweite
operative Wahrheit, die die Guardrails verbieten (FIX THE MODEL, SINGLE SOURCE OF
TRUTH). Sie in FK-03 zu dokumentieren haette sie normativ gemacht.

### Entscheidung

**Entfernen, sofort, nicht deprecaten.** Begruendung des PO (ZERO DEBT): Es gibt
genau **eine** AK3-Installation, und das betroffene Projekt hat nicht begonnen.
Damit ist dies die **billigste Migration, die je verfuegbar sein wird** — „jetzt
tun und nicht irgendwann". Ein Deprecation-Pfad mit Folgestory wurde
ausdruecklich **verworfen**: er haette die zweite Wahrheit fuer die gesamte
Deprecation-Dauer normativ gemacht.

### Konsequenzen (verbindlich)

1. `vectordb.host` und `vectordb.port` existieren nicht mehr. Da `VectorDbConfig`
   `extra="forbid"` fuehrt, ist ein dennoch gesetzter Schluessel ein **benannter
   Validierungsfehler**, kein stilles Ignorieren.
2. Jeder Konsument leitet Host/Port aus dem **Endpunkt** ab, ueber genau **eine**
   oeffentliche Naht: `agentkit.backend.vectordb.endpoints`
   (`split_http_endpoint` / `split_grpc_endpoint`). `vectordb.engine`
   re-exportiert sie unter den historischen Namen. Ein **zweiter** Parser ist
   unzulaessig — die Drift zwischen zwei Zerlegern ist genau der Fehler, den die
   Konsolidierung beseitigt.
3. **Kein `config_version`-Bump.** Belegt, nicht angenommen: `InstallConfig`
   fuehrt kein `vectordb_host`/`vectordb_port`, und die Scaffold-Ausgabe kann
   ausschliesslich die zwei Endpunkt-Schluessel oder **gar keine**
   `vectordb`-Stanza enthalten (ueber alle drei Feature-/Endpunkt-Kombinationen
   gemessen und durch einen Test gepinnt). FK-03 hat die beiden Schluessel
   ausserdem **nie** dokumentiert. Es kann also kein AK3-erzeugtes und kein
   dokumentiert-konfiguriertes `project.yaml` geben, das sie traegt; die Aenderung
   ist fuer jedes von AK3 erzeugte Artefakt unsichtbar.
4. **Seam zu AG3-176 (nicht praeempted):** AG3-176 Scope 1 besitzt das
   *Ausschliessen* des localhost-/Default-Fallbacks fuer den projektgebundenen
   Installationspfad und das *Beibehalten* dokumentierter Defaults fuer den
   projektlosen Diagnose-CLI-Pfad; es nennt `wait_for_weaviate.py` ausdruecklich.
   D-2 aendert dort **nur die Feldquelle**. Die **Fallback-Politik** bleibt
   unveraendert und ist durch einen Test gepinnt, damit AG3-176 die Naht findet.

### Betroffene Konzepte

| Konzept | Aenderung |
|---|---|
| FK-03 §3.1 | Beide Endpunktfelder dokumentiert (Form, Validierung, kein Default), CP-5-Herkunft, und die **Entfernung** von `host`/`port` festgehalten. Der Vollstaendigkeitsanspruch des Kapitels macht das verbindlich. |
| FK-03 §3.4.2 | Defaults-Tabelle um beide Felder ergaenzt (*kein Default*). |

---

## D-3 — MCP-Registrierungsvertrag nachgezogen (ABLEITUNG, autorisiert)

Die zehn Positionen sind **Nachziehung**, keine Neuerfindung: der Code folgt
zwingend dem Konsumenten (ein Server, der seine eigene Runtime-Bindung verweigert,
ist kein Server), und die Konzeptprosa hinkte nachweisbar hinterher. Positionen
1-8 wurden vom Reviewer als einzeln korrekt beurteilt; 9-10 sind
Vollstaendigkeit.

### D-3.1 — Ausfuehrbares Modul (FK-13 §13.4.3, FK-50 §50.3 CP 10)

Registriert wird `-m agentkit.backend.vectordb.engine`.
`vectordb.mcp_server` ist ein **Bibliotheksmodul**: als `-m` ausgefuehrt laeuft
sein Modulrumpf und endet mit Exit 0, ohne zu serven — der generische
MCP-Conformance-Check (AG3-164) wertet das korrekt als `mcp_process_exited`. Beide
Konzepte nannten zuvor das Bibliotheksmodul, FK-13 zusaetzlich in einer
Skriptpfad-Form.

### D-3.2 — Endpunkte statt Host+Port im `env` (FK-13 §13.4.3)

Die Registrierung traegt `WEAVIATE_HTTP_ENDPOINT` und `WEAVIATE_GRPC_ENDPOINT` als
vollstaendige Werte; `WEAVIATE_HOST` / `WEAVIATE_HTTP_PORT` /
`WEAVIATE_GRPC_PORT` entfallen. Konsistent mit D2 (2026-07-23) und mit D-2 oben.

### D-3.3 — `GH_REPO` entfaellt (FK-13 §13.4.3)

Der Server liest den Wert nicht; er kommt im Produktionscode nicht vor.

### D-3.4 — `AGENTKIT_CONCEPTS_DIR` ist Pflicht ohne Default (FK-13 §13.4.3)

Der stdio-Einstiegspunkt verlangt den Schluessel und beendet sich sonst
fail-closed. Grund (N20/D2): ein Default hat den Server einmal auf AK3s **eigenen**
Entwicklungskorpus gezeigt. Der Schluessel fehlte im Konzept vollstaendig.

### D-3.5 — `AGENTKIT_STORIES_DIR` und `cwd` explizit (FK-13 §13.4.3)

`AGENTKIT_STORIES_DIR` ist technisch optional, wird aber **explizit**
registriert: sein Default loest gegen die Prozess-`cwd` auf, und `cwd` darf nach
D2 keine zweite Konfigurationsquelle sein. Ein Projekt mit abweichendem
Story-Verzeichnis wuerde sonst still aus dem falschen Korpus indizieren. `cwd` ist
die Containment-Grenze und immer der Zielprojekt-Root.

### D-3.6 — CP-10-Beispielblock ist normativ, nicht illustrativ (FK-50 §50.3 CP 10)

`env` und `cwd` gehoeren in das Beispiel: ein ohne sie registrierter Server
verweigert beim Start seine eigene Runtime-Bindung.

### D-3.7 — Reason-Katalog ergaenzt (FK-50 §50.3 CP 10)

- `configuration_invalid` — die **konsumierte Projektkonfiguration** fehlt oder ist
  ungueltig (PO-ratifizierte Vokabel aus D4).
- `registration_incomplete` — I/O-Fehler in der Write-Phase liess die
  Zwei-Dateien-Registrierung unvollstaendig (D6).
- `mcp_configuration_invalid` — praezisiert: gilt fuer **beide** Spiegel-Dateien,
  nicht nur `.mcp.json`.

### D-3.8 — Zwei-Dateien-Fehlersemantik (FK-76 §76.5.4.2)

Kein gemeinsamer Transaktionsraum; jede Datei wird **genau einmal** gelesen und
Parsen/Rendern/Before-Image stammen aus denselben Bytes; Fehler vor dem ersten
Write bedeuten null Writes; Einzelwrites atomar, die Paarung nicht; I/O-Fehler nach
dem ersten Write → best-effort-Rollback plus `registration_incomplete`, ein
gescheitertes Rollback wird als solches gemeldet; das Crashfenster wird
**dokumentiert, nicht als Atomizitaet verkauft**.

### D-3.9 — FK-03-Dokumentation (siehe D-2, Variante c)

Beide Endpunktfelder mit Validierungs-/Default-Semantik **und** CP-5-Herkunft,
**plus** die festgehaltene Entfernung von `host`/`port`.

### D-3.10 — Gleichnamen-Kollisionsidentitaet (FK-76 §76.5.4.1)

**Die geschlossene Luecke:** §76.5.4 forderte „ein Konflikt mit einem
bestehenden, **fremd belegten** Server-Namen ist ein harter Fehler", **ohne je zu
definieren, wie „fremd belegt" erkannt wird.** Dieser undefinierte Begriff war die
Ursache **zweier** Datenerhaltungsfehler: eine fremde Tabelle unter einem
AK3-Namen wurde als AK3-eigen eingestuft und beim Detach mitgeloescht, und ein
fremder `.mcp.json`-Eintrag wurde still ueberschrieben, waehrend Codex ihn
ablehnte — zwei Antworten auf „ist dieser Eintrag unser", je nach Format.

Normativ, **einmal fuer beide** Spiegel-Dateien: Identitaet ist `command` +
`args`; Treffer aktualisiert die AK3-eigenen Felder und **erhaelt unbekannte**;
Nicht-Treffer **und** ein Eintrag ohne `command`/`args` (ambivalente Belegung,
z. B. leere Tabelle) sind ein benannter Fehler mit null Writes; anders benannte
Server bleiben unveraendert. Ganzdatei-Eigentum wird gegen die **erwartete**
AK3-Registrierung geprueft, nicht aus reserviertem Namen plus kanonischer
Schreibweise abgeleitet.

---

## Betroffenheitsmatrix

| Entscheidung | Konzept | Status | Kern |
|---|---|---|---|
| D-2 | FK-03 §3.1, §3.4.2 | geaendert | Endpunkte dokumentiert; `host`/`port` entfernt; CP-5-Herkunft; kein Versionsbump |
| D-2 | FK-13 §13.2 | nicht-betroffen | Infrastruktur-/Pinning-Aussagen unberuehrt |
| D-3.1-D-3.5 | FK-13 §13.4.3 | geaendert | Modul, Endpunkt-`env`, `GH_REPO` entfaellt, Concepts-/Stories-Dir, `cwd` |
| D-3.1, D-3.6, D-3.7 | FK-50 §50.3 CP 10 | geaendert | Beispielblock normativ; zwei neue Reasons; `mcp_configuration_invalid` praezisiert |
| D-3.8, D-3.10 | FK-76 §76.5.4 | geaendert | neue §76.5.4.1 (Kollisionsidentitaet) und §76.5.4.2 (Zwei-Dateien-Semantik) |
| D-3 | FK-13 Werkzeugvertraege (§13.9) | nicht-betroffen | Toolparameter und Authority-Ranking unberuehrt |
| D-2 | AG3-176 Scope 1 | referenziert | Fallback-Politik ausdruecklich **nicht** praeempted; nur die Feldquelle geaendert |

## Was bewusst NICHT entschieden wurde

- **Die Fallback-Politik von `wait_for_weaviate`** bleibt unveraendert; sie gehoert
  AG3-176 Scope 1.
- **`localhost:50051` / `127.0.0.1:50051`** bleiben gesperrt, obwohl FK-13 den
  lokalen gRPC-Port `:50051` nennt. Ratifizierte D2-Semantik; hier nicht
  aufgerollt.
- **Der vorbestehende Importzyklus** in `agentkit.backend.telemetry` ist bekannt,
  von dieser Aenderung unberuehrt und braucht eine eigene Story.
