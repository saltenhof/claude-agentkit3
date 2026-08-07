# AG3-250 — Die Bruecke selbst hat keinen BC-Eigentuemer: Control Plane, Transport-Idempotenz und ein Edge-Composition-Root, der 18 Kern-Repositories baut.

- **Typ:** implementation
- **Groesse:** L
- **Bounded Context:** cross-cutting — kein BC, siehe Abschnitt „Warum diese Story keinen BC nennt“
- **Betroffene Subpakete:** `backend/control_plane/`, `backend/control_plane_http/`, `backend/bootstrap/composition_*`, das Transport-Residuum in `backend/state_backend/store/`, `backend/cli/serve`, `backend/auth/credentials`, `backend/code_backend/provider_port`, `integration_clients/multi_llm_hub`
- **BC-Konzepte:** FK-10, FK-91, FK-01 (alle `cross_cutting: true`)
- **Abhaengigkeiten:** `depends_on: []` — sofort startbar
- **Blockiert:** `unblocks: ["AG3-209"]`
- **Herkunft:** Orchestrator-Messung 2026-08-07 gegen die in AG3-237
  veroeffentlichte Klassifikation; PO-Entscheid vom 2026-08-07, die
  BC-Endpunktstorys **vor** AG3-209 zu ziehen

## Anlass

AK3 soll auf zwei Maschinen laufen: **Project Edge** auf dem Entwicklerrechner,
**Kern** auf einem zentralen Server. Der Code tut heute so, als waere es eine
Maschine — der Edge ruft Kern-Funktionen als normale Python-Funktionen im selben
Prozess auf. Ueber ein Netz geht das nicht.

Vorgesehen ist die `/v1`-HTTP-Schnittstelle als **einzige** Bruecke zwischen
beiden Maschinen. Sie ist unvollstaendig: fuer einen grossen Teil dessen, was der
Edge heute direkt aufruft, gibt es keine Operation.

**AG3-209 kann diese Luecke nicht schliessen.** Sein Scope verbietet neue
REST-Endpunkte ausdruecklich und verweist auf „eigene Story beim jeweiligen BC"
(`stories/AG3-209-edge-kern-distributionsschnitt/story.md`, Abschnitt
„Out of Scope"). Diese Story ist genau das — fuer den Bounded Context
**cross-cutting — kein BC, siehe Abschnitt „Warum diese Story keinen BC nennt“**.

Diese Story sammelt, was **keinen** Bounded Context hat — und sie hat einen
Befund, der sie traegt:

> **Ein einziges Edge-Modul erzeugt 18 der 23 `state_backend`-Ueberquerungen.**

`backend/bootstrap/composition_project.py` ist der Composition-Root der
Edge-Seite. Er baut dort Story-Repository, Read-Repository, Fact-Repository,
Analytics-Source, Freeze-Repository, Lock-Record-Repository,
Hook-Registration-Repository, Projekt-Repository, Telemetrie-Projektion,
Takeover-Approval-Quelle, Writer-Lease-Identitaet, Parallelisierungs-Config und
Story-Dependency-Repository — alles Postgres, alles Kern.

Das ist **eine** strukturelle Ursache, nicht 18 Einzelfehler. Sie wird an einer
Stelle behoben, nicht an achtzehn nacheinander.

## Umfang, gemessen

Gesamtbild vom 2026-08-07, AST-gemessen gegen die in
`concept/formal-spec/architecture-conformance/entities.md` veroeffentlichte
Klassifikation: **354 distinkte Symbole** holt der Edge aus dem Kern, an **638
Importstellen**. 179 davon sind Daten (Modelle, Enums, Konstanten, Ausnahmen) und
werden von **AG3-237** ueber das Vertragspaket geloest — nicht hier. Uebrig
bleiben **116 Verhalten** und **59 ungeklaerte** Symbole; die ungeklaerten sind
die, an denen der Klassifikator der Vormessung an Re-Exporten gescheitert ist.

Die 347 Grenzverletzungen stehen einzeln als
`distribution_boundary_violations.pairs` in `entities.md` (297 Edge→Kern,
50 Kern→Edge). Die Teilmenge dieses BC ist daraus mechanisch ableitbar.

**Fuer diesen BC:**

| Groesse | Startwert |
|---|---|
| `control_plane` — Verhalten + ungeklaert (Vormessung) | 4 + 0 = **4** |
| `state_backend` — Verhalten + ungeklaert (Vormessung) | 22 + 1 = **23** |
| `bootstrap` ohne `story_reset_adapters` — Verhalten + ungeklaert | **11** |
| `cli` / `auth` / `multi_llm_hub` — Verhalten + ungeklaert | 2 / 1 / 2 = **5** |
| Grenzverletzungspaare mit `control_plane` auf einer Seite | **26** Edge→Kern |
| davon `composition_project.py` als alleiniger Importeur | **18** der 23 `state_backend`-Ueberquerungen |

> **Diese Zahlen sind ein Startpunkt, kein Sollwert.** Sie stammen aus einer
> Vormessung, deren Klassifikator an 59 Symbolen gescheitert ist. Der Umfang
> dieser Story wird in AC 1 **selbst gemessen**. Weicht das Ergebnis ab, gilt
> die eigene Messung — die Abweichung wird benannt, nicht stillschweigend
> uebernommen.

Der Rest verteilt sich auf lauter Einzelposten mit gemeinsamem Merkmal — sie
gehoeren zur **Bruecke**, nicht zu einer Fachlichkeit:

| Posten | Symbole | Was es ist |
|---|---|---|
| `control_plane.{edge_command_repository, edge_commands, push_sync, ownership, repository, writer_lease}` | 8 | Run-Ownership, Edge-Kommando-Dispatch, Push-Gate |
| `state_backend.store.inflight_idempotency_guard` | 11 | Idempotenz und Serialisierung **des Transports selbst** |
| `state_backend.store.{control_plane_writer_lease, takeover_approval_read_repository, pipeline_runtime_store}` | 3 | Writer-Lease, Takeover, Phase-State |
| `state_backend.store.{parallelization_config_repository, story_dependency_repository, story_are_link_repository}` | 3 | Planungs-/ARE-Daten ohne eigene BC-Story (siehe unten) |
| `bootstrap.composition_{root,state}` | 10 | Fabriken, die der Edge zieht |
| `cli.serve.{run_serve, run_ui}` | 2 | Kernprozess-Start, vom Edge-CLI importiert |
| `auth.credentials.StrategistCredentialStore` | 1 | Credential-Speicher |
| `code_backend.provider_port.StoryRefWriteCredential*` | 2 | Schreibrecht-Klassifikation |
| `integration_clients.multi_llm_hub.{HubClient, load_multi_llm_hub_config, HubBackendName}` | 3 | Hub-Adapter |

`control_plane.models` traegt allein 47 der 63 gemessenen `control_plane`-Symbole
und ist **Nutzlast** — es steht bereits in AG3-237s Wire-Huelle. Diese Story
besitzt die **Vorgaenge**, nicht die Modelle.

## Scope

### In Scope

- Fuer jede Ueberquerung dieses Bestands die Antwort (a)/(b)/(c) nach AC 1.
- **`composition_project.py` baut keine Kern-Repositories mehr.** Das ist der Liefergegenstand, an dem diese Story gemessen wird. Jede Bindung, fuer die eine BC-Story den Ersatz liefert, wird dort entfernt; jede Bindung ohne BC-Story bekommt hier ihre Antwort.
- Die drei Repositories ohne eigene BC-Story (`parallelization_config_repository` und `story_dependency_repository` → execution-planning, `story_are_link_repository` → requirements-and-scope-coverage) bekommen hier ihre Antwort. Die erwartete ist **(c)**: der Edge braucht keine Planungsdaten. Faellt die Messung anders aus, ist das ein Befund fuer den PO — dann fehlt eine BC-Story, und sie wird angefordert statt hier miterledigt.
- `cli.serve.{run_serve, run_ui}` verlassen den Edge-CLI-Pfad. Ein Edge, der den Kernprozess starten kann, hat die Grenze nicht verstanden.

### Out of Scope

- **`control_plane.models` und `control_plane.third_party_models`** — Daten,
  **Owner: AG3-237** (Wire-Huelle, 118 Symbole in 13 Zielmodulen).
- **`bootstrap/story_reset_adapters.py`** — wandert, **Owner: AG3-209**;
  fachlich bei **AG3-240** abgegrenzt.
- **Die AG3-237-Eingangsliste E1–E7 in AG3-209** — diese Story leitet die
  Symbolpopulation **nicht** neu ab. Das ist ausdruecklich AG3-209s Auftrag
  (E1).
- **Die 179 Datensymbole** (Modelle, Enums, Konstanten, Ausnahmen) —
  **Owner: AG3-237**, geloest ueber das Vertragspaket. Diese Story baut keinen
  Endpunkt fuer ein Datum, das im Wire-Paket liegt.
- **Die Paketmigration, die Wheel-Trennung und das Distribution-Gate** —
  **Owner: AG3-209**. Diese Story macht den Schnitt moeglich; sie vollzieht ihn
  nicht.
- **`utils` (5 Symbole), `config` (3) und `boundary` (6)** — der Edge bekommt
  eine **eigene Kopie**. Das ist Duplikation ohne fachliche Entscheidung und
  mechanisch; **Owner: AG3-209**. Ein Endpunkt waere hier schlicht falsch: ein
  Netzaufruf fuer `ensure_dir` oder `atomic_write_text` bezahlt Latenz und einen
  Ausfallpfad fuer Code, den der Edge lokal ausfuehren muss.
- **Jede normative Grundentscheidung.** Taucht eine auf, stoppt die Story und
  legt sie dem PO vor; sie wird nicht durch einen Endpunkt-Default ersetzt.

## Akzeptanzkriterien

1. **Der eigene Umfang ist gemessen, nicht uebernommen.** Jede Ueberquerung
   dieses BC ist einzeln aufgefuehrt und traegt genau **eine** von drei
   Antworten:
   - **(a) gehoert ueber die Schnittstelle** → ein `/v1`-Endpunkt wird gebaut
     oder erweitert, dazu ein duenner Client auf der Edge-Seite;
   - **(b) ist Edge-Logik, im Kern falsch einsortiert** → das Modul wandert;
     **kein** Endpunkt;
   - **(c) darf nicht stattfinden** → der Aufruf entfaellt, mit Begruendung.

   Eine Ueberquerung ohne Antwort ist ein Verstoss gegen dieses Kriterium, kein
   Restposten. Die Messung ist reproduzierbar: Kommando und Ergebnis liegen im
   Story-Record.

2. **Der BC zaehlt am Ende NULL Grenzverletzungen.** Nachgewiesen mit einer
   **Suche mit Zahl** gegen den Arbeitsbaum, nicht durch Sichtpruefung. Die
   Ausgangsmenge ist die aus `distribution_boundary_violations.pairs`
   abgeleitete Teilmenge dieses BC; sie wird zu Beginn und am Ende mit demselben
   Kommando gerechnet, und beide Zahlen stehen im Record.

3. **Kein Endpunkt ohne Bedarf.** Mehrere Aufrufe desselben fachlichen Vorgangs
   werden **EINE** Operation, nicht drei. Wer heute drei Repository-Funktionen
   nacheinander ruft, bekommt **einen** Endpunkt, der den Vorgang als Ganzes
   ausdrueckt. Je Endpunkt steht im Record, welche heutigen Aufrufstellen er
   ersetzt; ein Endpunkt ohne Aufrufstelle wird nicht gebaut.

4. **Neue Endpunkte sind katalogisiert und vertraglich verankert.** Jeder neue
   oder erweiterte Endpunkt steht in **FK-91 §91.1** und im `/v1`-Vertrag
   (Pfad, Verb, Request-/Response-Schema, Fehlerfaelle). Ein Endpunkt, der nur
   im Code existiert, gilt als nicht geliefert.

5. **Alle sechs bindenden deterministischen Konzept-Gates sind gruen**
   (`AGENTS.md`; W2/W3 sind seit der PO-Entscheidung 2026-08-02 kein
   Abnahmekriterium und werden nie als „gruen" mitgezaehlt); Referenzintegritaet
   ohne neue Baseline-Eintraege.

   **Zusaetzlich, bei jeder Aenderung an der Formal Spec:** `check.py formal`
   und `check.py frontmatter` aus
   `src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/`.
   Die Repo-Gates erzwingen einen **anderen** Vertrag als der ausgelieferte
   Parser — in AG3-237 waren dadurch **vier Fehler bei sechs gruenen Gates
   unsichtbar**. Beide Werkzeuge laufen, beide Ergebnisse stehen im Record.

6. **Neue Business-Logik hat Unit-Tests, Negativpfade an den Phasengrenzen sind
   bewiesen.** Fuer jeden neuen Endpunkt mindestens: fehlende/ungueltige
   Autorisierung, unbekannte Story-/Objekt-Identitaet und der fail-closed
   Ausgang bei nicht erreichbarem Kern. Ein Test, der nur den Gutfall zeigt,
   erfuellt dieses Kriterium nicht.

## Warum diese Story keinen BC nennt

**Sie ist die einzige der Reihe ohne `domain:`-Wert, und das ist begruendet, nicht
uebersehen.** `concept/technical-design/00_index.md` §19.13 fuehrt
`cross_cutting: true` ausdruecklich als **eigene Kategorie** ein: Foundation-,
Adapter- und Runtime-Rahmen-Konzepte „haben keine Sprachgrenze und keinen
Owner-BC, sondern sind universell lesbare Grundlage fuer alle BCs".

Genau das trifft auf diesen Bestand zu:

- `FK-10` (Runtime/Deployment), `FK-91` (API-/Event-Katalog) und `FK-01`
  (Systemkontext) tragen alle `cross_cutting: true`.
- `control_plane` **ist** die Bruecke — es bedient jeden BC und gehoert keinem.
- `state_backend` ist die Persistenz-Adapterschicht; `bc-cut-decisions.md:718`
  fuehrt sie ausdruecklich als „Querschnitt-Adapter".

Einen BC zu erfinden, waere der Fehler, den `CLAUDE.md` §ZERO DEBT als
„fehlenden Eigentuemer durch **eigene Autoritaet** ersetzen" beschreibt. Der
Posten in eine benachbarte BC-Story zu schieben, waere die zweite verbotene
Variante — stillschweigendes Weglassen. Bleibt der dritte Weg: die Luecke
sichtbar tragen, mit Verweis auf die Regel, die sie legitimiert.

**Fuer den PO:** Wenn hier doch ein BC entstehen soll (etwa `run-ownership` oder
`control-plane`), ist das eine Meta-Konzeptentscheidung und gehoert vor die
Umsetzung dieser Story, nicht in sie hinein.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg: Kommando, Locator, Testname oder
  Reviewbeleg.
- Die Messung aus AC 1 liegt reproduzierbar im Story-Record — Kommando,
  Rohergebnis und die Zuordnung (a)/(b)/(c) je Ueberquerung.
- Anfangs- und Endzahl aus AC 2 stehen im Record, mit demselben Kommando
  gerechnet.
- `ruff` und `mypy` gruen; die von der Aenderung betroffene Test-Teilmenge ist
  lokal gruen. **Der vollstaendige Testnachweis kommt ausschliesslich aus
  Jenkins** (`AGENTS.md`, PO-Anweisung 2026-08-04) — ein lokaler
  `pytest`-Lauf ohne Pfadangabe ist untersagt.
- Unabhaengiges Codex-Review bis zu einem der Abbruchkriterien aus `CLAUDE.md`.

**PO-Vorgabe vom 2026-08-07, woertlich:**

> **Hoechstens DREI QS-/Remediation-Runden.** Ist die Story nach der dritten
> Runde nicht abnahmereif, wird sie **an den PO eskaliert** statt eine vierte zu
> fahren. Das ist eine harte Kappung, keine Richtgroesse.

## Guardrail-Referenzen

- `CLAUDE.md` §ZERO DEBT RULE — jede Ueberquerung bekommt eine Antwort; eine
  offen gelassene ist eine Schuld mit Zinseszins, kein Restposten.
- `CLAUDE.md` §KEINE KOMPATIBILITAETSSCHICHTEN — kein Endpunkt neben dem
  weiterlebenden Direktaufruf. Der Schnitt wird an einer Stelle gemacht.
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — AC 3: ein Endpunkt bildet den
  fachlichen Vorgang ab, nicht die heutige Aufrufreihenfolge.
- `CLAUDE.md` §FAIL-CLOSED — AC 6: ein nicht erreichbarer Kern hat einen
  normierten Ausgang, keinen lokalen Ersatzstate.
- `guardrails/testing-guardrails.md` — Negativpfade an den Phasengrenzen.
- `guardrails/test-execution-efficiency.md` R1–R4 — innere Schleife nur auf der
  betroffenen Teilmenge. **Die volle Testsuite laeuft ausschliesslich auf
  Jenkins** (`AGENTS.md`, PO-Anweisung 2026-08-04).
