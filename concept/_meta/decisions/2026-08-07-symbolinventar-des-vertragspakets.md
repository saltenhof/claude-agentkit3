---
concept_id: META-DEC-2026-08-07-SYMBOLINVENTAR-DES-VERTRAGSPAKETS
title: Concept-Decision-Record — Symbolinventar des Vertragspakets und Klassifikation der 44 Backend-Subpakete
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: [FK-10, FK-07, FK-01, FK-30]
supersedes: []
superseded_by:
tags: [meta, decision-record, deployment, packaging, FK-10, FK-01, FK-07, FK-30]
formal_scope: prose-only
---

# Concept-Decision-Record — Symbolinventar des Vertragspakets

Datum: 2026-08-07. Story: AG3-237. Vorgaenger:
`2026-08-03-edge-und-kern-sind-zwei-distributionen.md` (§9.4, §9.5).

## 1. Anlass

AG3-208 hat den Distributionsschnitt zielbildhaft gesetzt, die
Klassifikation der 44 unmittelbaren Backend-Subpakete aber ausdruecklich
**nicht** getroffen: drei aufeinanderfolgende unabhaengige Reviews hatten
je eine weitere Zuweisung widerlegt, die ohne Messung getroffen worden
war. Vier Bereiche standen als `pending_symbol_inventory`,
`distribution_classification_status` stand auf `open`, und das
Packaging-Gate meldete `NOT_RUN`.

Der Befund, an dem die drei Runden haengen, hat eine gemeinsame Wurzel,
und es ist **nicht** die einzelne falsche Zeile: **ohne festgelegte
Zaehleinheit ist „das Modul mischt keine Belange" nicht pruefbar.** Die
Vormessung mischte 13 Module, 33 importierte Symbole, 63 Klassen und fuer
ein Paket gar keine Zahl — vier Einheiten in einer Tabelle. Jede Runde
konnte deshalb eine weitere Zuweisung widerlegen, ohne dass jemand einen
Fehler gemacht haette: es gab kein Kriterium, gegen das eine Zuweisung
haette richtig sein koennen.

## 2. Entscheidung

### 2.1 Zaehleinheit

Zaehleinheit ist das **oeffentliche Modul-Symbol** — ein auf Modulebene
gebundener Name ohne fuehrenden Unterstrich: Klasse, Funktion,
Modulkonstante, Typalias. Aggregationseinheit ist das **Modul**.

Begruendung, nicht Konvention: genau auf diesen beiden Granularitaeten
arbeiten die Gate-Checks, die Distributionszugehoerigkeit durchsetzen.
`wire_surface_matches_symbol_boundaries` vergleicht die oeffentliche
Oberflaeche des gebauten Wheels — eine Menge von **Symbolen**.
`source_graph` und `wheel_reachability` loesen die Zugehoerigkeit ueber
Modulpraefixe auf — eine Menge von **Modulen**. Kleiner als ein Symbol
laesst sich nichts ausliefern, groesser als ein Modul nichts schneiden;
jede andere Einheit misst etwas, das das Gate nicht durchsetzen kann.

Re-exportierte Namen zaehlen fuer das **definierende** Modul, damit ein
Symbol genau einmal gezaehlt wird.

### 2.2 Mischungsfreiheit — ein Veto, keine Wahl

Eine Praefixzuweisung eines Pakets an eine Distribution ist zulaessig,
wenn kein Modul des Pakets **direkt** einen Anker einer anderen
Distribution importiert und keine Drittdistribution einer anderen
Distribution deklariert.

**Anker** sind ausschliesslich Zuordnungen, die FK-10 Abschnitt A
(Deployment Units ausserhalb `backend/`), Abschnitt C
(`integration_clients`-Adapter) und Abschnitt E (Drittabhaengigkeiten)
bereits treffen und die AG3-208 nicht zurueckgezogen hat. **Nichts aus
den 44 Subpaketen ist Anker** — ihre Zugehoerigkeit ist Ergebnis der
Messung, nie ihre Eingabe. Damit ist das Kriterium nicht zirkulaer.

Abschnitt E traegt dabei mehr als eine Konvention: `psycopg`,
`psycopg-pool` und `argon2-cffi` sind Kern-only und auf einer
Ebene-2-Umgebung **nicht installiert**. Ein Modul, das sie braucht, kann
im Edge-Wheel nicht laufen — es faellt beim Import um, und der bereits
spezifizierte Check `clean_edge_install` beweist das. Symmetrisch fuer
`weaviate-client`, `mcp`, `tokenizers`, `tomlkit` und `psutil` auf der
Edge-Seite.

**Das Kriterium hat ZWEI Bedingungen.** Eine dritte -- "kein Entry-Point
der anderen Distribution erreicht das Paket" -- stand in der ersten
Fassung und ist **entfernt**, nicht ausgesetzt. Sie war sachlich falsch,
und zwar auf eine Weise, die sich nicht durch Aussetzen heilen laesst:
sie vermischt *wo ein Modul hingehoert* mit *ob der Code sich heute daran
haelt*. Eine Kante `edge->core` beweist nicht, dass eine Zugehoerigkeit
unbekannt waere; sie beweist, dass jemand eine bekannte Grenze verletzt.
Als Vorbedingung der Klassifikation gefuehrt haette sie die
Klassifikation durch ihre eigenen Verstoesse unschliessbar gemacht --
"ich kann nicht sagen, wo das hingehoert, solange es falsch benutzt
wird". Die Kanten stehen jetzt als `distribution_boundary_violations`:
Arbeitsliste von AG3-209, kein Bestandteil des Klassifikationsbeweises.
Damit sind beide verbliebenen Bedingungen heute erfuellbar, und
`distribution_classification_status: closed` ist gedeckt.

**Das Kriterium ist ein Veto.** Es kann eine Zuweisung verbieten; es kann
keine Seite bestimmen. Die Seite waehlen die Regeln E1 bis E3 (§2.3a).

**Der Anker-Begriff ist zirkelfrei -- und war es in der ersten Fassung
nicht.** Die Definition schloss die 44 Subpakete als Anker aus, die
*Messung* tat es nicht: die Abschnitt-E-Regel wurde auf Importer
propagiert, wodurch `backend.auth.credentials` (ueber `argon2`) und
`backend.vectordb.*` (ueber `mcp`) faktisch als Anker wirkten und damit
Mitglieder der 44 ueber andere Mitglieder der 44 entschieden. Korrigiert:
Anker sind ausschliesslich Module **ausserhalb** `src/agentkit/backend`;
die Abschnitt-E-Regel ist eine Eigenschaft des **deklarierenden** Moduls
und propagiert nicht.

### 2.3a Wie die Seite bestimmt wird -- und wo das eine Wahl ist

| Regel | Art | Entscheidet |
|---|---|---|
| **E1 Anker** | Ableitung | 85 Module |
| **E2 Entry-Point** | Ableitung | 11 Module |
| **E3 Autoritaet** | **Wahl** | 859 Module, entschieden in **46 Paketbegruendungen** |

**E3 ist eine Wahl, keine Ableitung, und sie entscheidet die grosse
Mehrheit.** Das wird hier ausdruecklich gesagt, weil die erste Fassung es
verschwiegen hat: FK-10 §10.2.11 ordnet nur Console-Scripts und
CLI-Kommandopfade zu. Fuer `artifacts`, `boundary`, `concept_catalog`,
`utils`, `workers` und 30 weitere Pakete gibt es dort **keine Seite**.
Sie sind entlang der Autoritaets-Invarianten I1/I3/I5 gesetzt worden --
kanonischer Zustand und Adjudication gehoeren dem Kern.

Eine konsumbasierte **Ableitung** ("alle heutigen Importer liegen auf
einer Seite") ist erwogen und **verworfen** worden. Sie leitet die Seite
aus dem heutigen, defekten Aufrufgraphen ab und lieferte unter anderem
`state_backend.store.fact_repository -> edge`,
`governance.principal_capabilities -> edge` und
`implementation.worker_health -> edge`. Eine als Ableitung getarnte Wahl
ist schlechter als eine benannte Wahl.

**E3 ist trotzdem keine `default_distribution`.** Eine Auffangregel weist
einem Modul einen Eigentuemer zu, das niemand angesehen hat. E3 ist je
Paket in `distribution_membership_evidence` aufgezaehlt, und jeder
Eintrag nennt die Norm, der er folgt. Der Unterschied ist der Beleg,
nicht der Mechanismus.

### 2.3 Direkt, nicht transitiv

Gemessen wird der **direkte** Ankerkontakt. Transitive Erreichbarkeit
vermischt zwei verschiedene Defekte mit zwei verschiedenen Heilmitteln:
ein Modul, das selbst beide Seiten importiert, mischt Belange und muss
symbolgenau geschnitten werden; ein Modul, das beide Seiten nur ueber
andere Backend-Module *erreicht*, hat irgendwo auf dem Pfad eine
verbotene Kante, und das Heilmittel ist, diese Kante zu entfernen.

Gemessen 2026-08-07: **drei** Module mischen direkt, waehrend die
transitive Erreichbarkeit **222** markiert. Ein transitives Kriterium
haette 219 Schnitte spezifiziert, die niemand braucht.

### 2.4 Ergebnis der Messung

`backend/` fuehrt **955 Module in 44 unmittelbaren Subpaketen plus dem
Wurzelmodul `exceptions.py`** mit zusammen **3838 oeffentlichen
Modul-Symbolen**. Die Zahl „rund 150" aus der Vormessung war ein
Startwert.

46 Eintraege, vier disjunkte Klassen:

| Klasse | Zahl |
|---|---|
| Praefix, mischungsfrei, Kern | 36 |
| Praefix, mischungsfrei, Edge | 1 (`vectordb`) |
| Praefix + benannte Modulausnahmen | 7 |
| Praefix + Modulausnahmen + Symbolschnitt in einem Modul | 2 |
| **Summe Subpakete** | **44**, plus `exceptions.py` und `backend/__init__.py` = 46 |

`pending_symbol_inventory` ist leer,
`distribution_classification_status` ist `closed`, jede Zuordnung traegt
ihren Messbeleg in `distribution_membership_evidence`.

### 2.5 Das Vertragspaket ist neuer Code

Die Wire-Distribution traegt **kein einziges** `agentkit.backend.*`-Praefix
mehr. Die sechs Praefixe, die AG3-208 dort vorlaeufig fuehrte, sind
ersetzt durch **13 neue Module unter `agentkit_wire`, in die 118 Symbole
wandern**.

**Ein Symbol wandert nur, wenn seine transitive Huelle mitwandert oder
bereits wire-legal ist.** Diese Regel fehlte in der ersten Fassung, und
ihr Fehlen war kein Formfehler: die dortige Behauptung, die bekannten
Wire-Regel-Verstoesse laegen saemtlich in den zurueckgelassenen Symbolen,
war **falsch**. Gegen die Huelle gemessen schliessen **28** der 123
zunaechst ausgewaehlten Symbole nicht -- `HookEvent` benutzt
`pathlib.Path` und den Edge-Typ `FreshnessClass`; `ProjectRegistration`,
`RegisterProjectStateRequest` und `SkillBindingWriteRequest` haben
`Path`-Felder; `AgentHealthState` haengt an nicht mitwandernden
Worker-Health-Typen; `ReconciliationEvidence` importiert Kern **und**
Edge. Auch `ProjectConfig` faellt darunter: seine Huelle zieht
`RepositoryConfig`, `PipelineConfig`, `PolicyConfig`, `AreConfig` und
weitere nach und traegt `pathlib` bis in die Blaetter -- die sechs
Symbole aus AG3-208 waren keine geschlossene Oberflaeche.

Die Pruefung laeuft bis zum **Fixpunkt** und muss **Re-Exporte aufloesen**:
ohne das wurde `FailureCategory` (ueber `core_types/__init__`) stillschweigend
uebersprungen, und zwei Failure-Corpus-Nutzlasten galten zu Unrecht als
geschlossen -- sie haetten einen Wire->Kern-Import hinterlassen. Die 28
stehen als `wire_deferred_symbols` mit je einem benannten Blocker: sie
wandern nicht, AG3-209 zerlegt sie zuerst.

Arithmetik: von **181** qualifizierenden beidseitigen Vertragssymbolen
wandern **95** als Wurzelsymbole, **28** sind zurueckgestellt, **58**
ausgeschlossen. Die Huellenschliessung zieht **23** modul-interne
Datentypen nach; Endbestand **118**.

### 2.6 Korrekturen an bereits normativen Aussagen

| Stelle | Alt | Neu |
|---|---|---|
| `entities.md` `distributions[wire].module_prefixes` | sechs Backend-Praefixe, „VORLAEUFIG" | leer; `wire_target_modules` traegt den Inhalt |
| `entities.md` Zugehoerigkeitsfunktion | 45 Eintraege deckten 954 von 955 Modulen; `backend/__init__.py` fiel durch | 46 Eintraege, 955 von 955. Das Paketwurzelmodul steht als `module_members`, nicht als Praefix -- ein Praefix `agentkit.backend` waere unter longest-match-wins die wiederhergestellte Auffangregel |
| `entities.md` Anker | die acht Anker ausserhalb `backend/` trugen keinen Messbeleg, und die Gate-Vorbedingung war auf „under agentkit.backend" verengt | `distribution_anchors` mit Messbeleg je Anker; die Vorbedingung deckt Praefixe **und** `module_members` aller Distributionen |
| `entities.md` Ausschlussliste | enthielt `agentkit.__version__` (ausserhalb `backend/`) sowie `_AGENT_TOOL` und `_MANIFEST_SKILL_PROOF_KEY` (privat) | nach der Zaehleinheit keine Symbole; nirgends mehr gefuehrt, mit Begruendung an Ort und Stelle |
| Zahl der Grenzverletzungen | „696" (Runde 1, keine Einheit), „340" (Runde 2, stillschweigender Ausschluss), „353" (Runde 3/4, vor der letzten Zuordnungsaenderung) | **347** eindeutige geordnete Modulpaare, 297 Edge→Kern und 50 Kern→Edge, **ohne jeden Ausschluss** und **einzeln** in `distribution_boundary_violations.pairs` gespeichert. Jede Zuordnungsaenderung rechnet diese Liste vollstaendig neu; sie ist ein abgeleitetes Artefakt. Auf den Gate-Report kann sich die Liste nicht berufen: das Packaging-Gate existiert noch nicht |
| FK-10 §10.2.12 D Governance-Wire | Runde 1: zwoelf Symbole; Runde 2: sieben | **zwei**: `HookDefinition` und seine typisierte Abhaengigkeit `HookEventName`. `HookId` und die vier Hook-ID-Konstanten sind lokale Dispatch-/Validierungslogik (`governance/hook_ids.py:5`) und keine Vertragsfelder |
| `entities.md` Kommentar zu `distribution_prefix_resolution` | drei zurueckgezogene Beispiele, darunter die entfernte Auffangregel `agentkit.backend -> core` | vier gemessene Beispiele plus die ausdrueckliche Feststellung, dass `agentkit.backend` in keiner Distribution als Praefix existiert |
| `entities.md` `symbol_boundary.backend_config_models` | `split_required: false` | `split_required: true` — zugunsten von FK-10 §10.2.12 entschieden; 24 oeffentliche Symbole, 6 davon Vertragsvokabular, `pathlib` in den uebrigen |
| FK-30 §30.3.1 | „Auslieferungsbesitzer **aller** `governance.*`- und `telemetry.hooks`-Locatoren ist die Edge-Distribution (normativ)" | `governance` und `telemetry` sind **Kern**; Edge sind vier namentlich benannte Module |
| FK-01 §1.4.3 Zonentabelle | Zone 1 Guard-Engine → `agentkit-project-edge` | praezisiert auf die vier namentlich benannten Governance-Edge-Module; die Adjudication liegt im Kern |
| FK-01 §1.2.2, `PROJECT_STRUCTURE.md` Distributionstabelle | Inhaltsspalte las sich als Paketliste | ausdruecklich als Faehigkeitsliste ausgewiesen, mit Verweis auf `distribution_membership_evidence` |
| FK-10 §10.2.12 B Tabelle B | „Der uebrige `code_backend/` bleibt Kern" neben „nicht gemessen" | alle 3 Module gemessen, Kern, kein Ankerkontakt |
| FK-10 §10.2.12 B Gegenkanten | 46 Kanten „entstehen ausnahmslos in Modulen, die ohnehin zum Edge gehoeren" (berief sich auf die zurueckgezogene Matrix) | gegen die geschlossene Zuordnung nachgemessen; die Zahl steht in der Zeile „Zahl der Grenzverletzungen" oben und ist dort mit ihrer Zaehleinheit gefuehrt. Arbeitsliste fuer AG3-209, keine Rechtfertigung. Die frueher hier stehenden 696/619/77 sind dieselben ueberholten Werte, die acht Zeilen weiter oben bereits als einheitslos ausgewiesen werden |
| FK-10 §10.2.12 D | „nur die 38 beidseitig genutzten Klassen" aus `control_plane/models` | 43 namentlich benannte Symbole, verteilt auf drei Zielmodule |
| FK-10 §10.2.12 D | Symbolliste „gilt als Spezifikation des Schnitts" fuer zwei Module | 23 Module verlieren Symbole (9 loesen sich auf), 4 weitere tragen einen Edge/Kern-Schnitt; vollstaendig in `distribution_symbol_boundaries` |

### 2.7 Korrekturen der dritten Runde

| Befund | Alt | Neu |
|---|---|---|
| `decided_by` in allen 46 Eintraegen | `E4` — eine Regel, die es nicht gibt; maschinenlesbar war damit nicht festgelegt, welche Zuordnung eine Wahl ist | **Zwei Populationen, getrennt gezaehlt.** Die 46 Membership-Eintraege: `E1` (11), `E2` (4), `E3` (31). Die 21 Modulausnahmen darunter: `E1` (16), `E2` (3), `E3` (2). Zusammen 67 `decided_by`-Felder in der Datei — eine Zaehlung ueber alle Vorkommen ergibt deshalb `E1` (27), `E2` (7), `E3` (33) und meint etwas anderes |
| Huellenpruefung | uebersprang re-exportierte Symbole stillschweigend; `FailureCategory` (ueber `core_types/__init__`) fiel durch, und zwei Failure-Corpus-Nutzlasten galten zu Unrecht als geschlossen — sie haetten einen Wire→Kern-Import hinterlassen | reexport-aufloesender Fixpunkt; `hull_closure_method` ist als Feld gefuehrt, 28 statt 23 zurueckgestellt |
| Grenzverletzungen | 340, mit stillschweigendem Ausschluss der symbolgeschnittenen Module | **347**, ohne Ausschluss, alle Paare einzeln gespeichert (Runde 3 stand hier 353; die letzte Zuordnungsaenderung hat die Liste erneut neu gerechnet) |
| `governance.default_hook_definitions` | Kern, begruendet mit „kanonische Default-Menge" | **Edge**. Fuer die Kernfunktion gab es keine normative Aussage; die Begruendung war eine Umdeutung des Gegenbeweises und ist zurueckgezogen |
| `core_types.mcp_server_registration` | FK-10 sagte Edge, die Formal-Spec liess es im Kern-Praefix | **Edge**, als benannte Praefixausnahme. Anker ist FK-10 §10.1.0a (Laufzeitbesitzer vor historischem Namespace). Zwei Ableitungen dorthin sind zurueckgezogen: E2 (verlangt einen implementierten Console-Script-Pfad) und die Kern-Zuordnung ueber FK-76 §76.9 (normiert nur Importrichtungen; der zitierte Wortlaut stammte aus dem Modul-Docstring) |
| `closure.runtime_ports` | FK-10 sagte Edge-Modul, begruendet mit „haelt einen Anker" | **Kern**. `backend.vectordb` liegt innerhalb `backend/` und ist nach der korrigierten Ankerdefinition kein Anker; die Begruendung war mit der eigenen Definition unvereinbar |
| E1-Arithmetik | 84 | **85** — 49 Edge + 37 Kern − 1 beidseitig |
| Ablehnung der Konsumentenregel | drei Gegenbeispiele | ein tragfaehiges (`state_backend.store.fact_repository`); `governance.principal_capabilities` und `implementation.worker_health` werden von zahlreichen Kernmodulen importiert, die Regel liefert dort nicht Edge — beide zurueckgezogen |
| Governance-Wire | zwoelf (R1) → sieben (R2) | **zwei**: `HookDefinition`, `HookEventName` |
| E3-Granularitaet | „entscheidet 860 Module" | 859 Module in **46 Paketbegruendungen**; AC 3 verlangt Belege je Praefixzuweisung, nicht je Modul |

**Der Rollback-Vorfall.** Eine ungeankerte Textersetzung hat in Runde 2 einen
1190-Zeilen-Bereich der Formal-Spec ueberschrieben. Die Wiederherstellung aus
HEAD hat dabei stillschweigend den Kriterienblock mit zurueckgesetzt; sechs
Prosa-Stellen behielten alte Zahlen. Beides ist behoben, und die Ersetzungen
laufen seitdem gegen verankerte Indizes. Der Vorfall steht hier, weil er die
Ursache fuer die Mehrzahl der Runde-3-Befunde war.

## 3. Betroffenheitsmatrix

| Dokument | Art der Aenderung | Normativ? |
|---|---|---|
| `concept/formal-spec/architecture-conformance/entities.md` | Zaehleinheit, Kriterium, Wahlregeln, 46 Membership-Belege, 8 Anker-Belege, 13 Wire-Zielmodule, 24 Symbolgrenzen, Huellenalgorithmus, private Huellenbindungen, 347 Verstoehungspaare, `pending_symbol_inventory: []`, Status `closed` | ja |
| `concept/formal-spec/architecture-conformance/invariants.md` | `symbol_boundary_is_the_rule` an Zaehleinheit und Kriterium gebunden; zweiteilige Vorbedingung von `distribution_membership_is_total_and_disjoint`; Gate-Checkliste `preconditions` | ja |
| `concept/technical-design/10_runtime_deployment_speicher.md` | §10.2.12 B0/B/D neu; B4, B5, B6, B7 ersetzt | ja |
| `concept/technical-design/30_hook_adapter_guard_enforcement.md` | §30.3.1 Distributionszuordnung ersetzt | ja |
| `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` | §1.2.2 Komponententabelle praezisiert, §1.4.3 Zonentabelle praezisiert | ja |
| `PROJECT_STRUCTURE.md` | Distributionstabelle praezisiert, Lesehinweis ergaenzt | ja |
| `concept/_meta/reference-integrity-baseline.yaml` | drei Zeilennummern nachgezogen (FK-30 verschob sich um 11 Zeilen); **keine neuen Eintraege**, weiterhin 50 | nein |

Nicht beruehrt und bewusst nicht beruehrt: Artefaktnamen und
Importwurzeln, die Maschinen- und Zustandsgrenze, der Entry-Point- und
CLI-Vertrag, die Dependency-Regeln und der Gate-Mechanismus. Sie sind in
AG3-208 entschieden.

## 4. Was diese Entscheidung nicht entscheidet

- **Den Schnitt selbst.** AG3-237 spezifiziert; AG3-209 fuehrt aus. Kein
  Produktionscode ist geaendert worden.
- **Das Packaging-Gate.** Es wird von AG3-209 gebaut. Diese Entscheidung
  stellt nur sicher, dass die Vorbedingung `pending_symbol_inventory is
  empty` in seiner Checkliste steht und **zur Laufzeit** gelesen wird —
  ein Gate, das sie nur einmal zur Bauzeit prueft, wuerde auf einer
  spaeter wieder geoeffneten Klassifikation `PASS` melden.
- **Die VektorDB-Laufzeit im Kern.** Drei Locatoren, nicht zwei:
  `closure/runtime_ports.py`, `bootstrap/composition_project.py:114,171`
  (instanziiert `WeaviateStoryAdapter` direkt im Kern) und
  und `composition_project.py:96,105` (`resolve_split_export_project_id`
  erreicht selbst Edge-VektorDB-Code und ist deshalb zusammen mit
  `build_story_split_service` als `unresolved` gefuehrt).
  **`composition_project.py:636` ist kein Defekt** und faellt heraus: dort
  wird der Project-Edge-Client fuer das ausdruecklich Edge-klassifizierte
  `build_compat_window_reader` importiert. Das widerspricht FK-01 §1.1a und ist die
  bereits benannte Luecke aus FK-10 §10.2.12 C, Eigentuemer Product
  Owner. AG3-237 entscheidet sie nicht ein zweites Mal.
  **Korrektur an der eigenen Runde-1-Meldung:** `closure/runtime_ports.py`
  „Edge" zu nennen war falsch. Das Modul ist **Kern** und traegt **keinen**
  Anker -- `backend.vectordb` liegt innerhalb `backend/` und ist nach der
  korrigierten Ankerdefinition kein Anker. Sein einziger Importer ist der
  Kern-Composition-Root (`composition_closure.py:427`), und es enthaelt
  weitere kernseitige Closure-Ports. Der Nachsatz aus Runde 2, es falle
  „ueber einen Edge-Anker ins Edge-Praefix", widersprach der eigenen
  Korrekturtabelle und ist ebenfalls zurueckgezogen.
- **`governance/hook_event_inputs.py:46`** importiert `build_skills` aus
  dem Composition Root. **Korrektur an der eigenen Runde-1-Meldung:** die
  Richtung war falsch notiert. `hook_event_inputs` ist als **Kern**
  klassifiziert; der Edge-Einstieg ist `governance.runner`, der es
  importiert. Die Kante ist damit **Edge→Kern**, nicht Kern→Edge. Ihre
  Wirkung bleibt dieselbe: ueber sie erreicht der Hook-Prozess den
  gesamten Kern. Behebung gehoert zu AG3-209.
- **Die elf verwaisten Kommandopfade.** Eigentuemer Product Owner.
