# AG3-248 — Projektanlage und Konfigurationsaenderung ruft der Edge heute als Funktion auf und schreibt dabei direkt in die Projekttabelle des Kerns.

- **Typ:** implementation
- **Groesse:** S
- **Bounded Context:** `project-management`
- **Betroffene Subpakete:** `backend/project_management/` sowie `state_backend/store/project_management_repository`
- **BC-Konzepte:** DK-14, FK-73
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
**project-management**.

Projektanlage ist ein **mutierender** Vorgang auf Kern-Zustand, ausgeloest vom
Laptop. Heute ist er ein lokaler Funktionsaufruf: `create_project` und
`update_configuration` laufen im Edge-Prozess und schreiben ueber
`StateBackendProjectRepository` direkt in Postgres.

Das ist der Fall, in dem die fehlende Schnittstelle am teuersten ist: Ein
mutierender Vorgang ohne Endpunkt hat keine Idempotenz, keine Serialisierung und
keine Autorisierung — die drei Dinge, die die `/v1`-Strecke mitbringt.

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
| `project_management` — Verhalten + ungeklaert (Vormessung) | 3 + 0 = **3** |
| Grenzverletzungspaare Edge→Kern in `project_management` | **5** |
| davon eigene Messung: distinkte Symbole | **5** (`entities.ProjectConfiguration`, `lifecycle.create_project`, `lifecycle.update_configuration`, `read_model_routes.ReadModelRoutes`, `repository.ProjectRepository`) |
| `state_backend/store/project_management_repository` | **1** |

> **Diese Zahlen sind ein Startpunkt, kein Sollwert.** Sie stammen aus einer
> Vormessung, deren Klassifikator an 59 Symbolen gescheitert ist. Der Umfang
> dieser Story wird in AC 1 **selbst gemessen**. Weicht das Ergebnis ab, gilt
> die eigene Messung — die Abweichung wird benannt, nicht stillschweigend
> uebernommen.

`ReadModelRoutes` faellt auf: Das ist bereits eine HTTP-Routendefinition, die
der Edge **importiert** statt sie aufzurufen. Fuer diesen Posten ist die Arbeit
nicht „einen Endpunkt bauen", sondern den vorhandenen benutzen.

`entities.ProjectConfiguration` ist Daten und geht an **AG3-237**.

## Scope

### In Scope

- Fuer jede der 5 Ueberquerungen die Antwort (a)/(b)/(c) nach AC 1.
- Projektanlage und Konfigurationsaenderung laufen als **mutierende** `/v1`-Operationen mit Idempotenz und Serialisierung — nicht als lokaler Funktionsaufruf mit Direktschreibzugriff.
- `ReadModelRoutes` wird aufgerufen, nicht importiert.

### Out of Scope

- **`ProjectConfiguration` als Datentyp** — **Owner: AG3-237**.
- **AG3-211 (`projektidentitaet-statt-getippter-schluessel`)** bleibt
  unberuehrt; diese Story aendert nicht, *wie* ein Projekt identifiziert wird.
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
